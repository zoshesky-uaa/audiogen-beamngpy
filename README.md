## Check List
* Information regarding delay and other possible issues with KMixxer:
https://github.com/PortAudio/portaudio/wiki/Win32AudioBackgroundInfo
* Voicemeter Input = Voicemeter Out B1

## Bugs:
1) Consult `bug_rants.md`, recorder is currently disabled for the moment to fix the position logic.
2) There is a thread lock for Beamng instance and Vehicles, so the dispatcher losses most of its functionality immediately. I will phase it out slowly this week just to remove a point of failure.

## Current Objectives:
1) Procesing the poll data from `driver.py` into the respective data type information required, then write it to a zarr file. 