### Check List
* Information regarding delay and other possible issues with KMixxer:
https://github.com/PortAudio/portaudio/wiki/Win32AudioBackgroundInfo
* Voicemeter Input = Voicemeter Out B1

Bugs:
1) Audio status string: input overflow, apparently the callback isn't fast enough and I need another thread just for the FFT.
2) Zarr writer doesn't do anything? (I don't see any file size change to the files), likely due to the issue above and zeros being compressed to basically nothing.
Current Objectives:
1) Procesing the poll data from `driver.py` into the respective data type information required, then write it to a zarr file. 