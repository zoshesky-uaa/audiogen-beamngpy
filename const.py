# Configuration constants for the simulation

# Path to BeamNG.tech installation directory. Update this path to match your local setup.
BEAMNG_LOCATION = r"D:\BeamNG.tech.v0.38.3.0"

# Defines whether the simulation is in training mode (AI-controlled) or not (human-controlled)
TRAINING = True

# Audio configuration, FFT parameters
BIT_DEPTH = 16
SIMULATION_DURATION_SECONDS = 600
SAMPLING_FREQUENCY = 16000
FFT_SIZE = 1024
N_INPUTS = 7
N_BINS = (FFT_SIZE // 2) + 1
AUDIO_INPUT_DEVICE_NAME = "Voicemeeter Out B1"
AUDIO_CHANNELS = 4

# Schedular configuration
TICK_RATE = SAMPLING_FREQUENCY/(FFT_SIZE/2)
TICK_DURATION_SECONDS = 1.0 / TICK_RATE
END_FRAME = SIMULATION_DURATION_SECONDS * (TICK_RATE)

# Data storage configuration
CHUNK_SIZE = 512
TOTAL_FRAMES = int(SIMULATION_DURATION_SECONDS * TICK_RATE)

# Maximum audio source vehicles shall not exceed this value per class
MAXIMUM_CONTROLLABLE_VEHICLES = 5

# Simulation configuration
MINIMUM_TRAFFIC_VEHICLES = 5
MAXIMUM_TRAFFIC_VEHICLES = 25
MINIMUM_EMERGENCY_VEHICLES = 5
MAXIMUM_EMERGENCY_VEHICLES = 10
MAXIMUM_SPAWN_WAIT_TIME_SECONDS = 120
NUMBER_OF_SOUND_CLASSES = 2

MAXIMUM_VEHICLES = MAXIMUM_CONTROLLABLE_VEHICLES * NUMBER_OF_SOUND_CLASSES


