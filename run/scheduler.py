import threading
from time import sleep
from run import ev, filesystem, recorder, driver, traffic
import const

class Tick:
    def __init__(self,delay):
        self.frame_index = 0
        self._cond = threading.Condition()
        self.shutdown = threading.Event()
        self.delay = delay
        self.on = False
        #Hijacks the external clock of the audio callback to do frame time writes.
        self.external_clock = False
    
    # Starts tick loops, then iterates based on either internal clock or external clock (audio callback)
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
            while (self.frame_index < endframe) and (not self.shutdown.is_set()) and self.on:
                self.iterate()

    # Stops the tick loop and signals shutdown to any waiting vehicle threads
    def stop(self):
        with self._cond:
            self.on = False
            self.shutdown.set()
            self._cond.notify_all()

    # Resets frame index to 0, but doesn't trigger exit conditions (shutdown) so loops can be continued
    def reset(self):
        with self._cond:
            self.on = False
            self.frame_index = 0
            self._cond.notify_all()

    # Self-iteration loop following a set tick delay
    def iterate(self):
        with self._cond:
            if not self.on:
                return
        sleep(self.delay)
        self.advance_frame()

    # Advances the tick by one frame
    def advance_frame(self):
        with self._cond:
            if not self.on:
                return
            self.frame_index += 1
            self._cond.notify_all()

    # Delay added that waits for a specific frame iteration before returning said frame, typically +1 the current frame
    def wait_next(self, last_frame):
        with self._cond:
            self._cond.wait_for(
                lambda: self.shutdown.is_set() or (self.frame_index > last_frame and self.on)
            )
            if self.shutdown.is_set():
                return None
            return self.frame_index

    # Waits for next frame before performing an action
    def waited_action(self, action=None):
        if action:
            action()
        frame = self.wait_next(self.frame_index)
        return frame

    # Waits for next frame before next action, with optional frame to stop at and limit condition function/lambda
    def waited_action_iterate(self, action=None, max_frame=None, cond_func = None):
        while not self.shutdown.is_set():
            if max_frame is not None and self.frame_index >= max_frame:
                break
            if cond_func is not None and not cond_func():
                break
            if action:
                action()
            frame = self.wait_next(self.frame_index)
            if frame is None:
                break


class Scheduler:
    def __init__(self, simulation):
        # Intializes the tick with a finite delay constant defined
        self.tick = Tick(delay=const.TICK_DURATION_SECONDS)
        self.vehicle_update_tick = Tick(delay=const.TICK_DURATION_SECONDS/2)
        # Intiales the FSM class that holds the writing functions for datasets
        self.fsm = filesystem.FSM(self.tick)  
        # Reference to main simulation  
        self.simulation = simulation
        # Thread handles
        self.threads = []
        # Keeps count of each class event by adding it's index to an array, used to determine the track index
        self.class_events = []

    # Creats an event thread based on the class index
    def append_event(self, class_index, vehicle_ref=None, ai=True):
        match class_index:
            case 99:
                thread = threading.Thread(target=driver.DriverRecorder, 
                                            args=(self.fsm, 
                                            self.simulation,
                                            self.vehicle_update_tick,
                                            self.tick,
                                            ai), 
                                          daemon=True)
                self.threads.append(thread)
            case 0:
                thread = threading.Thread(target=traffic.VehicleSoundEvent, 
                                            args=(self.simulation,
                                            class_index,
                                            self.class_events.count(1),
                                            self.fsm,
                                            vehicle_ref, 
                                            self.vehicle_update_tick,
                                            self.tick), 
                                          daemon=True)
                self.class_events.append(class_index)
                self.threads.append(thread)
            case 1:
                thread = threading.Thread(target=ev.VehicleSoundEvent, 
                                            args=(self.simulation,
                                            class_index,
                                            self.class_events.count(2),
                                            self.fsm,
                                            vehicle_ref, 
                                            self.vehicle_update_tick,
                                            self.tick), 
                                        daemon=True)
                self.class_events.append(class_index)
                self.threads.append(thread)
            case _: return   
        thread.start()  

    def transition_to_scenario(self):
        instruct = lambda : (
            self.simulation.dispatcher.send(self.simulation.beamng.queue_lua_command, "core_input_actionFilter.setGroup('all', true)"),
            self.simulation.dispatcher.send(self.simulation.beamng.queue_lua_command, "ui_fadeScreen.fadeToBlack(0.5)"),
            self.simulation.dispatcher.send_sync(self.simulation.beamng.queue_lua_command, "SFXSystem.setGlobalParameter('g_FadeTimeMS', {1.0 * 1000})"),
            self.simulation.dispatcher.send_sync(self.simulation.beamng.queue_lua_command, "SFXSystem.setGlobalParameter('g_GameLoading', 1)"),
            self.tick.waited_action(),
            self.simulation.dispatcher.send(self.simulation.beamng.queue_lua_command, "SFXSystem.setGlobalParameter('g_GameLoading', 0)"),
            self.simulation.dispatcher.send(self.simulation.beamng.queue_lua_command, "ui_fadeScreen.fadeFromBlack(0.5)"),  
            self.simulation.dispatcher.send(self.simulation.beamng.queue_lua_command, "core_input_actionFilter.setGroup('all', false)"),
        )  
        thread = threading.Thread(target=instruct, daemon=True)
        self.threads.append(thread)
        thread.start()

    # Control flow function for the simulation
    def simulate(self):
        audio_data = None
        self.simulation.dispatcher.send(self.simulation.beamng.control.resume)
        # Does a warmup for 20 seconds to ensure recordings don't start at a zero state
        print("Warming up scenario...")
        self.tick.start(20*const.TICK_RATE)
        self.vehicle_update_tick.start(2*const.TOTAL_FRAMES)
        self.tick.reset()

        # Main scenario loop, starts audio recording and FSM writing
        print("Starting scenario loop.")
        # Writer thread to write to Zarr dataset
        self.fsm.writer.start()
        self.threads.append(self.fsm.writer)

        # Start recorder
        audio_data = recorder.AudioRec(tick=self.tick, fsm=self.fsm)

        # FFT compute thread for audio feature extraction
        audio_data.fft_thread.start()
        self.threads.append(audio_data.fft_thread)

        self.tick.external_clock = True
        self.tick.start(const.TOTAL_FRAMES)

        # After reaching end frame, intiate shutdown for the internal tick and audio recording
        self.tick.stop()
        if audio_data is not None:
            audio_data.stop()
        print("Scenario ended")
        self.simulation.dispatcher.send(self.simulation.beamng.control.pause)

    # Cleanup for the threads
    def stop_all(self):
        self.tick.stop()
        self.vehicle_update_tick.stop()
        sleep(5)
        for thread in self.threads:
            thread.join(timeout=10.0)
            if thread.is_alive():
                print(f"Warning: thread {thread.name} did not stop in time.")