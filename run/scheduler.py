import threading
import traceback
from time import sleep, monotonic
import atexit
import const
from run import driver, filesystem, soundevent


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

        endframe = int(endframe)
        if not self.external_clock:
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
        self.advance_frame()
        sleep(self.delay)
        
    def advance_frame(self):
        with self._cond:
            if not self.on:
                return
            self._cond.notify_all()
            self.frame_index += 1
            
    def wait_next(self, last_frame):
        with self._cond:
            self._cond.wait_for(
                lambda: self.shutdown.is_set() or (self.frame_index != last_frame and self.on)
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
        self.tick = Tick(delay=const.target_res)
        self.vehicle_update_tick = Tick(delay=const.target_res/3)
        self.fsm = filesystem.FSM(self.tick, simulation)
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
            case _:
                track_index = self.class_events.count(class_index)
                target = lambda: soundevent.VehicleSoundEvent(
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
        warmup_frames = int(5 * const.t_prime) # Warmup for 15s
        if not self.simulation.trial_valid:
            print(f"Scenario aborted: {self.simulation.abort_reason}")
            return

        self.simulation.beamng.control.resume()
        print("Warming up scenario...")
        self._start_guarded_thread(
            "Vehicle state tick thread",
            lambda: self.vehicle_update_tick.start(2 * (const.label_max + warmup_frames)),
            "Vehicle state tick thread",
        )
        self.tick.start(warmup_frames)
        if not self.simulation.trial_valid:
            print(f"Scenario aborted: {self.simulation.abort_reason}")
            self.simulation.beamng.control.pause()
            return
        
        
        self.tick.reset()
        print("Starting scenario loop.")
        # External lock flip over
        self.tick.external_clock = True
        from pathlib import Path
        import subprocess
        import json 
  
        # Call path for application
        repo_root = Path(__file__).resolve().parent.parent
        application_path = (repo_root / const.GEN_BINARY_PATH).resolve()
        if not application_path.exists():
            raise FileNotFoundError(f"EXE not found: {application_path}")
        
        self.simulation.process = subprocess.Popen(
            [str(application_path)],
            cwd=str(repo_root),
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,   # Capture terminal output (creates process.stdout stream)
            stderr=subprocess.STDOUT,  # Merge stderr into stdout for unified reading
            text=True,
            bufsize=1
        )

        def send_exit():
            if self.simulation.process.poll() is None and self.simulation.process.stdin:
                try:
                    self.simulation.process.stdin.write("exit\n")
                    self.simulation.process.stdin.flush()
                except (BrokenPipeError, OSError):
                    pass

        atexit.register(send_exit)
        
        try:
            self.simulation.process.stdin.write(json.dumps(self.fsm.gen_cmd) + "\n")
            self.simulation.process.stdin.flush()
        except (BrokenPipeError, OSError) as e:
            print(f"Failed to communicate with binary: {e}")
            self.simulation.invalidate_trial(f"Binary pipe error: {e}", stop_run=True)
            self.tick.stop()
            return
        
        if self.simulation.process.stdout is None:
            self.simulation.invalidate_trial("Binary stdout not captured", stop_run=True)
            self.tick.stop()
            return

        compression_ratio = int(const.target_res / const.input_frame_time)
        started = False
        try:
            for line in self.simulation.process.stdout:
                line = line.strip()
                if not line:
                    continue
                parts = line.split(":", 1)
                prefix = parts[0]
                match prefix:
                    case "START":
                        print("\n[ACCDOA] Intercepted START.")
                        self.tick.start(const.label_max)
                        self.fsm.writer.start()
                        started = True

                    case "END":
                        print("\n[ACCDOA] Intercepted END. Sequence complete.")
                        self.tick.stop()
                        break 

                    case "TICK" if started and len(parts) == 2:
                        try:
                            frame_idx = int(parts[1])
                            if (frame_idx + 1) % compression_ratio == 0:
                                self.tick.advance_frame()
                            if frame_idx % 1000 == 0:
                                print(f"[ACCDOA] Progress: {frame_idx}/{const.frame_max} frames processed...", end='\r', flush=True)
                        except ValueError:
                            pass # Safely ignore if it wasn't a clean integer

                    case _ if "error" in line.lower():
                        print(f"\n[ACCDOA] Reported error: {line}")
                        self.simulation.invalidate_trial(f"Error: {line}", stop_run=True)
                        break
                        
                    case _:
                        print(f"\n[ACCDOA]: {line}")
                        continue

        except Exception as e:
            print(f"Error reading from binary: {e}")
            self.simulation.invalidate_trial(f"Binary read error: {e}", stop_run=True)
        
        sleep(5)
        self.simulation.process.poll()
        if self.simulation.process.returncode is not None and self.simulation.process.returncode != 0:
            self.simulation.invalidate_trial(f"Binary exited with code {self.simulation.process.returncode}", stop_run=True)
        join_thread(self.fsm.writer)
        print("Scenario ended")
        if not self.simulation.trial_valid:
            print(f"Scenario aborted: {self.simulation.abort_reason}")
        self.simulation.beamng.control.pause()

    def stop_all(self):
        self.tick.stop()
        self.vehicle_update_tick.stop()
        for thread in self.threads:
            join_thread(thread)

# Seperate function for use elsewhere
def join_thread(thread):
    if thread is threading.current_thread():
        return
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
