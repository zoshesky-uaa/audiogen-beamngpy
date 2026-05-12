import threading
import traceback
from time import sleep, monotonic, time
import atexit
import const
from run import driver, filesystem, soundevent, exceptions


class Tick:
    def __init__(self, delay, simulation):
        self.frame_index = 0
        self.recording_start_frame = 0
        self._cond = threading.Condition()
        self.shutdown = threading.Event()
        self.delay = delay
        self.on = False
        self.external_clock = False
        self.restart = simulation.trial_invalid  # Use the simulation's restart event

    def start(self, endframe):
        with self._cond:
            self.shutdown.clear()
            self.on = True

        endframe = int(endframe)
        if not self.external_clock:
            while self.frame_index < endframe and self.on:
                self.iterate()

    def check_interrupt(self):
        if self.restart.is_set():
            raise exceptions.RestartInterrupt("Restart signal received")
        if self.shutdown.is_set():
            raise exceptions.ShutdownInterrupt("Shutdown signal received")

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
        self.advance_frame()
        sleep(self.delay)
        
    def advance_frame(self):
        with self._cond:
            self._cond.notify_all()
            self.frame_index += 1
        self.check_interrupt()
            
    def wait_next(self, last_frame=None):
        if last_frame is None:
            last_frame = self.frame_index
        with self._cond:
            self._cond.wait_for(
                lambda: self.shutdown.is_set() or (self.frame_index != last_frame and self.on)
            )
        self.check_interrupt()
        return self.frame_index

    def waited_action(self, action=None):
        if action:
            action()
        return self.wait_next(self.frame_index)

    def waited_action_iterate(self, action=None, max_frame=None, cond_func=None):
        while True:
            if max_frame is not None and self.frame_index >= max_frame:
                break
            if cond_func is not None and not cond_func():
                break
            if action:
                action()
            self.wait_next(self.frame_index)
            
class Scheduler:
    def __init__(self, simulation):
        self.tick = Tick(delay=const.target_res, simulation=simulation)
        self.vehicle_update_tick = Tick(delay=const.target_res/2, simulation=simulation)
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

    @exceptions.interruptable
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
        thread = start_guarded_thread(self.simulation, target, failure_label)
        self.threads.append(thread)

    @exceptions.interruptable
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

        thread = start_guarded_thread(self.simulation, instruct, "Scenario transition thread")
        self.threads.append(thread)

    @exceptions.interruptable
    def simulate(self):
        audio_data = None
        warmup_frames = int(5 * const.t_prime) # Warmup for 15s

        print(f"Running scenario: {self.simulation.project_name}")
        self.simulation.beamng.control.resume()
        print("Warming up scenario...")
        start_guarded_thread(
            self.simulation,
            lambda: self.vehicle_update_tick.start(2 * (const.label_max + warmup_frames)),
            "Vehicle state tick thread",
        )
        self.tick.start(warmup_frames)
        
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
                if self.simulation.trial_invalid.is_set():
                    print("\n[ACCDOA] Aborting read loop: Trial was invalidated by a background thread.")
                    break
                line = line.strip()
                if not line:
                    continue
                parts = line.split(":", 1)
                prefix = parts[0]
                match prefix:
                    case "START":
                        print("\n[ACCDOA] Intercepted START.")
                        self.tick.start(const.label_max)
                        self.fsm.writer_thread = start_guarded_thread(
                            simulation=self.simulation,
                            target=self.fsm.writer.run,
                            thread_name="ZarrWriter"
                        )
                        started = True

                    case "END":
                        print("\n[ACCDOA] Intercepted END. Sequence complete.")
                        self.simulation.completed.set()  # Signal completion to prevent false invalidation
                        timeout = time() + 5.0
                        while (self.fsm.sed_queue) and time() < timeout:
                            sleep(0.1)
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
        
        if not self.simulation.trial_invalid.is_set():
            if self.fsm.writer_thread is not None:
                join_thread(self.fsm.writer_thread)
            print("Scenario ended")

    def stop_all(self):
        self.tick.stop()
        self.vehicle_update_tick.stop()

    def join_all(self):
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

def start_guarded_thread(simulation, target, thread_name):
    """Global thread spawner that invalidates the simulation on crash."""
    def guarded():
        try:
            target()
        except Exception as e:
            err_name = type(e).__name__
            # Catch the stack-unwinding interrupt cleanly
            if err_name in ("RestartInterrupt", "ShutdownInterrupt"):
                return 

            if simulation.completed.is_set() or simulation.trial_invalid.is_set():
                if err_name in ("ConnectionResetError", "ConnectionAbortedError", "OSError", "BNGDisconnectedError"):
                    return
                    
            print(f"{thread_name} failed: {e}")
            traceback.print_exc()
            
            # Push the invalidation directly to the simulation
            simulation.invalidate_trial(f"{thread_name} failed: {e}", stop_run=True)

    thread = threading.Thread(target=guarded, name=thread_name, daemon=True)
    thread.start()
    return thread