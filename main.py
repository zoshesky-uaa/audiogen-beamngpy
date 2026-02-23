from beamngpy import BeamNGpy, Scenario, Vehicle
from beamngpy.logging import BNGDisconnectedError
import threading
import sounddevice as sd
import soundfile as sf
import numpy as np
import os
import time


def main():
    #Preferences
    BEAMNG_LOCATION = r"E:\BeamNG.tech.v0.38.3.0"
    PORT = 25252

    # Create a BeamNGpy instance
    beamng = BeamNGpy('localhost', PORT, home=BEAMNG_LOCATION)
    while True: 
        try:
            beamng.open(launch=False)
            break
        except BNGDisconnectedError:  
            print("Retrying connection...")  
            time.sleep(5)
    
    beamng.settings.set_nondeterministic() 
    beamng.settings.set_steps_per_second(30)
    beamng.control.pause()  

    # Create a scenario
    scenario = Scenario('west_coast_usa', 'example')

    # Create a vehicle
    vehicle = Vehicle('ego_vehicle', model='etk800', licence='PYTHON')
    scenario.add_vehicle(vehicle, pos=(-717, 101, 118), rot_quat=(0, 0, 0.3826834, 0.9238795))
    vehicle.ai.set_mode('traffic')
    
    # Make, load, and start the scenario
    scenario.make(beamng)
    beamng.scenario.load(scenario)
    beamng.scenario.start()
    
    # Tick system
    while True:
        threads = thread_queue(2,
                            [simulation_stream, audio_stream],
                            [beamng, sd.default.device])

        threads[0][1].wait()  # Wait for simulation stream to be ready
        threads[1][1].wait()  # Wait for audio stream to be ready

        user_input = input('Press Enter for next tick, or type q to quit: ').strip().lower()
        if user_input in ("q", "quit", "exit"):
            break

    beamng.close()

def thread_queue(count, funcs, args):
    threads = []
    for i in range(count):
        tick = threading.Event()
        thread = threading.Thread(target=funcs[i], args=(args[i], tick), daemon=True)
        threads.append((thread, tick))
        thread.start()
    return threads

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