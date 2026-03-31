## Check List
* Information regarding delay and other possible issues with KMixxer:
https://github.com/PortAudio/portaudio/wiki/Win32AudioBackgroundInfo
* Voicemeter Input = Voicemeter Out B1

## Bugs:
1) Default state senors don't have a fast enough poll rate to supply the writer with fresh positions and velocities. Possibly the electric and damage sensor are equally unreliable and we might need to seperate that logic entirely. Need to re-work these sensors entirely.

## Current Objectives:
1) Procesing the poll data from `driver.py` into the respective data type information required, then write it to a zarr file. 