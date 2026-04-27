import threading
import traceback
from time import sleep, monotonic

import const
from run import driver, ev, filesystem, recorder, traffic


class Tick:
    def __init__(self, delay):
        self.frame_index = 0
        self.recording_start_frame = 0
        self._cond = threading.Condition()
        self.shutdown = threading.Event()
        self.delay = delay
        self.on = False
        self.external_clock = False

    def start(self, endframe):
        with self._cond:
            self.shutdown.clear()
            self.on = True
            self._cond.notify_all()

        endframe = int(endframe)
        if self.external_clock:
            with self._cond:
                self._cond.wait_for(lambda: self.frame_index > endframe or self.shutdown.is_set() or not self.on)
        else:
            while self.frame_index < endframe and not self.shutdown.is_set() and self.on:
                self.iterate()

    def stop(self):
        with self._cond:
            self.on = False
            self.shutdown.set()
            self._cond.notify_all()

    def reset(self):
        with self._cond:
            self.on = False
            self.frame_index = 0
            self.recording_start_frame = 0
            self._cond.notify_all()

    def iterate(self):
        with self._cond:
            if not self.on:
                return
        sleep(self.delay)
        self.advance_frame()

    def advance_frame(self):
        with self._cond:
            if not self.on:
                return
            self.frame_index += 1
            self._cond.notify_all()

    def wait_next(self, last_frame):
        with self._cond:
            self._cond.wait_for(
                lambda: self.shutdown.is_set() or (self.frame_index > last_frame and self.on)
            )
            if self.shutdown.is_set():
                return None
            return self.frame_index

    def waited_action(self, action=None):
        if action:
            action()
        return self.wait_next(self.frame_index)

    def waited_action_iterate(self, action=None, max_frame=None, cond_func=None):
        while not self.shutdown.is_set():
            if max_frame is not None and self.frame_index >= max_frame:
                break
            if cond_func is not None and not cond_func():
                break
            if action:
                action()
            if self.wait_next(self.frame_index) is None:
                break


class Scheduler:
    def __init__(self, simulation):
        self.tick = Tick(delay=const.TICK_DURATION_SECONDS)
        self.vehicle_update_tick = Tick(delay=const.TICK_DURATION_SECONDS / 2)
        self.fsm = filesystem.FSM(self.tick, simulation, write_features=True)
        self.simulation = simulation
        self.threads = []
        self.class_events = []

    def _should_ignore_thread_failure(self):
        return (
            self.tick.shutdown.is_set()
            or self.vehicle_update_tick.shutdown.is_set()
            or not getattr(self.simulation, "on", True)
            or getattr(self.simulation, "shutting_down", False)
        )

    def _start_guarded_thread(self, name, target, failure_label):
        def guarded():
            try:
                target()
            except Exception as e:
                if self._should_ignore_thread_failure():
                    return
                print(f"{failure_label} failed: {e}")
                traceback.print_exc()
                self.simulation.invalidate_trial(f"{failure_label} failed: {e}", stop_run=True)

        thread = threading.Thread(target=guarded, name=name, daemon=True)
        self.threads.append(thread)
        thread.start()
        return thread

    def finalize_trial(self, valid, reason=None):
        if valid:
            self.fsm.finalize_trial()
        else:
            self.fsm.invalidate_trial(reason or "trial invalidated")

    def append_event(self, class_index, vehicle_ref=None, ai=True):
        match class_index:
            case 99:
                target = lambda: driver.DriverRecorder(
                    self.fsm,
                    self.simulation,
                    self.vehicle_update_tick,
                    self.tick,
                    ai,
                )
                failure_label = "Driver recorder thread"
            case 0:
                track_index = self.class_events.count(class_index)
                target = lambda: traffic.VehicleSoundEvent(
                    self.simulation,
                    class_index,
                    track_index,
                    self.fsm,
                    vehicle_ref,
                    self.vehicle_update_tick,
                    self.tick,
                )
                failure_label = f"Traffic event thread {track_index}"
                self.class_events.append(class_index)
            case 1:
                track_index = self.class_events.count(class_index)
                target = lambda: ev.VehicleSoundEvent(
                    self.simulation,
                    class_index,
                    track_index,
                    self.fsm,
                    vehicle_ref,
                    self.vehicle_update_tick,
                    self.tick,
                )
                failure_label = f"Emergency event thread {track_index}"
                self.class_events.append(class_index)
            case _:
                return
        self._start_guarded_thread(failure_label, target, failure_label)

    def transition_to_scenario(self):
        def instruct():
            self.simulation.beamng.queue_lua_command("core_input_actionFilter.setGroup('all', true)")
            self.simulation.beamng.queue_lua_command("ui_fadeScreen.fadeToBlack(0.5)")
            self.simulation.beamng.queue_lua_command("SFXSystem.setGlobalParameter('g_FadeTimeMS', 1.0 * 1000)")
            self.simulation.beamng.queue_lua_command("SFXSystem.setGlobalParameter('g_GameLoading', 1)")
            if self.tick.waited_action() is None:
                return
            self.simulation.beamng.queue_lua_command("SFXSystem.setGlobalParameter('g_GameLoading', 0)")
            self.simulation.beamng.queue_lua_command("ui_fadeScreen.fadeFromBlack(0.5)")
            self.simulation.beamng.queue_lua_command("core_input_actionFilter.setGroup('all', false)")

        self._start_guarded_thread("Scenario transition thread", instruct, "Scenario transition thread")

    def simulate(self):
        audio_data = None
        warmup_frames = int(20 * const.TICK_RATE)
        if not self.simulation.trial_valid:
            print(f"Scenario aborted: {self.simulation.abort_reason}")
            return

        self.simulation.beamng.control.resume()
        print("Warming up scenario...")
        self._start_guarded_thread(
            "Vehicle state tick thread",
            lambda: self.vehicle_update_tick.start(2 * (const.TOTAL_FRAMES + warmup_frames)),
            "Vehicle state tick thread",
        )
        self.tick.start(warmup_frames)
        if not self.simulation.trial_valid:
            print(f"Scenario aborted: {self.simulation.abort_reason}")
            self.simulation.beamng.control.pause()
            return
        self.tick.recording_start_frame = self.tick.frame_index

        print("Starting scenario loop.")
        self.fsm.writer.start()
        self.threads.append(self.fsm.writer)

        audio_data = recorder.AudioRec(tick=self.tick, fsm=self.fsm)
        self.threads.append(audio_data.fft_thread)

        self.tick.start(self.tick.recording_start_frame + const.TOTAL_FRAMES)

        self.tick.stop()
        if audio_data is not None:
            audio_data.stop()
        print("Scenario ended")
        if not self.simulation.trial_valid:
            print(f"Scenario aborted: {self.simulation.abort_reason}")
        self.simulation.beamng.control.pause()

    def stop_all(self):
        self.tick.stop()
        self.vehicle_update_tick.stop()
        for thread in self.threads:
            deadline = monotonic() + 10.0
            while thread.is_alive():
                remaining = deadline - monotonic()
                if remaining <= 0:
                    break
                try:
                    thread.join(timeout=min(0.25, remaining))
                except KeyboardInterrupt:
                    print(f"Shutdown interrupted while waiting for {thread.name}; continuing cleanup.")
            if thread.is_alive():
                print(f"Warning: thread {thread.name} did not stop in time.")
