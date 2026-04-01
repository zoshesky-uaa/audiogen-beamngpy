## Check List
* Information regarding delay and other possible issues with KMixxer:
https://github.com/PortAudio/portaudio/wiki/Win32AudioBackgroundInfo
* Voicemeter Input = Voicemeter Out B1

## Bugs:
1) It appears a crash still occurs, seperate from polling operations. It always occurs whilst its unpaused and running the simulation. I'll leaving polling commented out so its not being done. Not sure if its related to non-deterministic stepping or some other effect, will check that next.


## Current Objectives:
1) Procesing the poll data from `driver.py` into the respective data type information required, then write it to a zarr file. 