## Check List
* Information regarding delay and other possible issues with KMixxer:
https://github.com/PortAudio/portaudio/wiki/Win32AudioBackgroundInfo
* Voicemeter Input = Voicemeter Out B1
* Some systems expose B1 as more than 4 input channels; that is fine as long as it can satisfy the configured 4-channel stream.

## BeamNG startup stability
* BeamNG runtime user data uses `beamng_user` instead of `beamngpy`, and `SkipGenerateLicencePlate` is forced true before launch.
* Startup does not call `control.pause()` immediately after `scenario.start()`, and `random_tod_setup()` is disabled because `env.set_tod(...)` was observed to hang.
* Driver AI is armed once from the main thread after traffic setup; the background DriverRecorder/event-99 path no longer calls `beamng.vehicles.switch(...)`.
* Setup-time traffic `set_mode("traffic")` remains skipped because it was observed to block.

## Bugs:
1) Consult `bug_rants.md` for remaining simulation/data issues.
2) Dispatcher has been removed. Current vehicle defaults are kept lower to avoid BeamNG lag and audio input overflow during recording.

## Current Objectives:
1) Processing the poll data from `driver.py` into the respective data type information required, then write it to a zarr file. 
