import threading
from time import sleep
from run import ev, filesystem, recorder, driver, traffic
import const

class Tick:
    def __init__(self):
        self.frame_index = 0
        self._event = threading.Event()
        self.shutdown = threading.Event()
    
    def iterate(self):
        """Advance the tick and wake anyone waiting for the next frame."""
        self.frame_index += 1
        old, self._event = self._event, threading.Event()
        old.set()

    def wait_next(self):
        """Block until the next tick iteration occurs."""
        self._event.wait()

class Scheduler:
    def __init__(self, simulation):
        self.fsm = filesystem.FSM()
        self.tick = Tick()
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
            sleep(const.TICK_DURATION_SECONDS)

        self.tick.frame_index = 0

        print("Starting scenario loop.")
        audio_data = recorder.AudioRec(tick=self.tick, fsm=self.fsm)

        self.fsm.startup()
        while self.tick.frame_index < const.END_FRAME and not self.tick.shutdown.is_set():
            self.tick.iterate()
            sleep(const.TICK_DURATION_SECONDS)
        audio_data.stop()
        self.fsm.shutdown()
        
        self.simulation.beamng.control.pause()

    def stop_all(self):
        self.tick.shutdown.set()
        self.tick._event.set()
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