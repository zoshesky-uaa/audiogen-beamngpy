import sounddevice as sd

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