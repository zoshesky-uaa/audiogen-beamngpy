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
    
    def start(self, endframe):
        with self._cond:
            self.on = True
            self._cond.notify_all()

        endframe = int(endframe)
        if self.external_clock:
            with self._cond:
                self._cond.wait_for(lambda: self.frame_index > endframe or self.shutdown.is_set() or not self.on)
        else:
            while (self.frame_index < endframe) and (not self.shutdown.is_set()) and self.on:
                self.iterate()

    def stop(self):
        self.shutdown.set()
        with self._cond:
            self._cond.notify_all()

    def reset(self):
        with self._cond:
            self.on = False
            self.frame_index = 0
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
        frame = self.wait_next(self.frame_index)
        return frame

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
        self.tick = Tick(delay=const.TICK_DURATION_SECONDS)
        self.fsm = filesystem.FSM(self.tick)      
        self.simulation = simulation
        self.threads = []
        self.class_events = []

    def append_event(self, class_index, vehicle=None, ai=True):
        match class_index:
            case 0:
                thread = threading.Thread(target=driver.DriverRecorder, 
                                          args=(self.simulation.vehicle_controller.driver,
                                                self.simulation.dispatcher,
                                                self.fsm, 
                                                self.tick,
                                                self.simulation,
                                                ai), 
                                          daemon=True)
                self.threads.append(thread)
            case 1:
                thread = threading.Thread(target=traffic.VehicleSoundEvent, 
                                args=(self.simulation.vehicle_controller.driver,
                                                self.simulation.dispatcher,
                                                class_index,
                                                self.class_events.count(1),
                                                self.fsm,
                                                vehicle, 
                                                self.tick), 
                                          daemon=True)
                self.class_events.append(class_index)
                self.threads.append(thread)
            case 3:
                thread = threading.Thread(target=ev.VehicleSoundEvent, 
                                        args=(self.simulation.vehicle_controller.driver,
                                            self.simulation.dispatcher,
                                            class_index,
                                            self.class_events.count(3),
                                            self.fsm,
                                            vehicle, 
                                            self.tick), 
                                        daemon=True)
                self.class_events.append(class_index)
                self.threads.append(thread)
            case _: return   
        thread.start()  

    def simulate(self):
        self.simulation.dispatcher.send(self.simulation.beamng.control.resume)

        print("Warming up scenario...")
        self.tick.start(15*const.TICK_RATE)
        self.tick.reset()

        print("Starting scenario loop.")
        audio_data = recorder.AudioRec(tick=self.tick, fsm=self.fsm)
        self.fsm.startup()
        self.tick.start(const.END_FRAME)

        self.tick.stop()
        audio_data.stop()
        self.fsm.shutdown()
        print("Scenario ended")
        self.simulation.dispatcher.send(self.simulation.beamng.control.pause)

    def stop_all(self):
        self.tick.stop()
        for thread in self.threads:
            thread.join(timeout=10.0)
            if thread.is_alive():
                print(f"Warning: thread {thread.name} did not stop in time.")