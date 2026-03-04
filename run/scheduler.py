SIMULATION_DURATION_SECONDS = 120
TICK_RATE_SECONDS = 0.1
END_FRAME = SIMULATION_DURATION_SECONDS * (1/TICK_RATE_SECONDS)

import threading
from time import sleep
from run import filesystem, recorder, sound_event

class Tick:
    def __init__(self):
        self.frame_index = 0
        self._event = threading.Event()
    
    def iterate(self):
        """Advance the tick and wake anyone waiting for the next frame."""
        self.frame_index += 1
        self._event.set()
        self._event.clear()

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

    def append_event(self, class_index):
        match class_index:
            case 1:
                 arg = (class_index,
                    self.class_events.count(1),
                    self.simulation,
                    self.fsm, 
                    self.tick)
            case 3:
                arg = (class_index,
                    self.class_events.count(3),
                    self.simulation,
                    self.fsm, 
                    self.tick)
            case _: return   
        thread = threading.Thread(target=sound_event.VehicleSoundEvent, args=arg, daemon=True)
        self.threads.append(thread)
        thread.start()

    def simulate(self):
        audio_data = recorder.AudioRec(duration=SIMULATION_DURATION_SECONDS)
        while self.tick.frame_index < END_FRAME:
            self.tick.iterate()
            sleep(TICK_RATE_SECONDS)
        recording = audio_data.stop()
        self.fsm.write_wav(recording)

    def stop_all(self):
        for thread in self.threads:
            thread.join()

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
