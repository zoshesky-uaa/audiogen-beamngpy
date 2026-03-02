
import threading

from run import filesystem, intiation, se
from scenarios import siren
import sounddevice as sd
import soundfile as sf
import numpy as np
from time import sleep


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
 

def simulation_stream(beamng, tick):
    tick.clear()
    for _ in range(10):  
        beamng.control.step(30, wait=True)   
    tick.set()

def audio_stream(device, tick):
    tick.clear()
    recording = sd.rec(48000, 
                    samplerate=48000, 
                    channels=8,
                    device=device)
    sd.wait()

    # Extract only the 4 channels you want
    # Indices: 0=FL, 1=FR, 2=FC, 3=LFE, 4=BR, 5=BL, 6=SR, 7=SL
    fl = recording[:, 0]  # Front-Left
    fr = recording[:, 1]  # Front-Right
    bl = recording[:, 5]  # Back-Left
    br = recording[:, 4]  # Back-Right

    # PCM quadraphonic audio data in the order: FL, FR, BL, BR
    audio_4ch = np.column_stack([fl, fr, bl, br])
    index = ["fl", "fr", "bl", "br"]
    for i in range(4):
        audio_4ch[:, i] = np.clip(audio_4ch[:, i], -1.0, 1.0)
        out_file = "audio_4ch_" + index[i] + ".wav"
        if not os.path.exists(out_file):
            # Create new file if it doesn't exist
            with sf.SoundFile(out_file, mode='w', samplerate=48000, channels=1, format='WAV', subtype='PCM_16') as f:
                f.write(audio_4ch[:, i])
        else:
            # Append to existing file
            with sf.SoundFile(out_file, mode='r+') as f:
                f.seek(f.frames)
                f.write(audio_4ch[:, i])
    tick.set()
    return audio_4ch


if __name__ == "__main__":
    main()