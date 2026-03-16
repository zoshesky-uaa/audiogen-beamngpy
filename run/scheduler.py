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
    
    def iterate(self):
        """Advance the tick and wake anyone waiting for the next frame."""
        with self._cond:
            self.frame_index += 1
            self._cond.notify_all()
        sleep(self.delay)

    def wait_next(self, last_frame):
        """Block until the next tick iteration occurs."""
        with self._cond:
            self._cond.wait_for(
                lambda: self.shutdown.is_set() or self.frame_index > last_frame
            )
            if self.shutdown.is_set():
                return None
            return self.frame_index

    def waited_action(self, action=None, last_frame=0):
        if action:
            action()
        frame = self.wait_next(last_frame)
        last_frame = frame

    def waited_action_iterate(self, action=None, last_frame=0, max_frame=None, secondary_cond = None):
        """Helper to perform an action every tick, with an iterate in between."""
        while not self.shutdown.is_set():
            if (max_frame is not None and last_frame >= max_frame) or not secondary_cond:
                break
            if action:
                action()
            frame = self.wait_next(last_frame)
            if frame is None:
                break
            last_frame = frame

    def stop(self):
        self.shutdown.set()
        with self._cond:
            self._cond.notify_all()


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
                                          args=(self.simulation,
                                                self.fsm, 
                                                self.tick,
                                                ai), 
                                          daemon=True)
                self.threads.append(thread)
            case 1:
                thread = threading.Thread(target=traffic.VehicleSoundEvent, 
                                          args=(class_index,
                                                self.class_events.count(1),
                                                self.simulation,
                                                self.fsm,
                                                vehicle, 
                                                self.tick), 
                                          daemon=True)
                self.class_events.append(class_index)
                self.threads.append(thread)
            case 3:
                thread = threading.Thread(target=ev.VehicleSoundEvent, 
                                        args=(class_index,
                                            self.class_events.count(3),
                                            self.simulation,
                                            self.fsm,
                                            vehicle, 
                                            self.tick), 
                                        daemon=True)
                self.class_events.append(class_index)
                self.threads.append(thread)
            case _: return   
        thread.start()  

    def simulate(self):
        self.simulation.beamng.control.resume()  
        print("Warming up scenario...")
        while self.tick.frame_index < 15*const.TICK_RATE and not self.tick.shutdown.is_set():
            self.tick.iterate()

        self.tick.frame_index = 0

        print("Starting scenario loop.")
        audio_data = recorder.AudioRec(tick=self.tick, fsm=self.fsm)

        self.fsm.startup()
        while self.tick.frame_index < const.END_FRAME and not self.tick.shutdown.is_set():
            self.tick.iterate()
        audio_data.stop()
        self.fsm.shutdown()

        self.simulation.beamng.control.pause()

    def stop_all(self):
        self.tick.stop()
        for thread in self.threads:
            thread.join(timeout=10.0)
            if thread.is_alive():
                print(f"Warning: thread {thread.name} did not stop in time.")

'''
def thread_queue(count, funcs, args):
    threads = []
    for i in range(count):
        tick = threading.Event()
        thread = threading.Thread(target=funcs[i], args=(args[i], tick), daemon=True)
        threads.append((thread, tick))
        thread.start()
    return threads
'''