## Audiogen BeamNGpy

This branch ports the useful simulation, spawning, data-writing, and event fixes from the older local bugfix work onto the latest partner baseline without bringing back the dispatcher. There is no `dispatcher.py`, generic command queue, `send_sync`, or `dispatcher_thread`.

## Running

Install the Python requirements, make sure BeamNG.tech is installed, then run:

```powershell
python main.py
```

BeamNG is discovered automatically when possible. If discovery fails, set `BEAMNG_LOCATION` to the BeamNG home folder.

## Audio

Audio capture still requires VoiceMeeter B1:

```python
AUDIO_INPUT_DEVICE_NAME = "Voicemeeter Out B1"
AUDIO_CHANNELS = 4
```

The recorder does not use aliases, fallback microphones, no-audio mode, or a new audio pipeline. Some systems expose B1 as an 8-channel input device; that is accepted because it can satisfy the configured 4-channel stream.

## Runtime Defaults

The default vehicle ranges are intentionally conservative to reduce BeamNG lag and avoid `Audio status string: input overflow`:

```python
MINIMUM_TRAFFIC_VEHICLES = 8
MAXIMUM_TRAFFIC_VEHICLES = 12
MINIMUM_EMERGENCY_VEHICLES = 4
MAXIMUM_EMERGENCY_VEHICLES = 6
```

During a normal run, `FFTCompute` starts after the B1 device is selected and Zarr chunk flush messages are expected as trial data is written.
