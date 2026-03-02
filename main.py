
import threading
from run import intiation
from scenarios import siren
import sounddevice as sd



def main():

    simulation = intiation.Simulation()
    driver = simulation.random_vehicle()
    simulation.vehicle_setup(driver, location=(-603, 101, 104), rotation=(0, 0, 0.3826834, 0.9238795))
    simulation.start_scenario()
    simulation.vehicle_connect(driver)
    siren.siren_scenario(simulation, driver)  

    simulation.close()

class Tick:
    def __init__(self):
        self.frame_index = 0
        # event to notify waiting threads when the tick advances
        self._event = threading.Event()
    
    def iterate(self):
        """Advance the tick and wake anyone waiting for the next frame."""
        self.frame_index += 1
        self._event.set()
        self._event.clear()

    def wait_next(self):
        """Block until the next tick iteration occurs."""
        self._event.wait()

class AudioRec:
    def __init__(self, duration, samplerate=24000):
        self.device = sd.default.device[0]
        self.recording = sd.rec(frames=samplerate * duration, 
                                samplerate=samplerate, 
                                channels=4,
                                device=self.device)
    
    def stop(self):
        sd.wait() 
        return self.recording.copy()

if __name__ == "__main__":
    main()
