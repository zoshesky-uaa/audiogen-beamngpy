import sounddevice as sd
import numpy as np
import audioflux as af
import const 
import threading
from collections import deque

class AudioRec:
    def __init__(self, tick, fsm):
        self.tick = tick
        self.fsm = fsm

        # Helper selection function
        def select_device(target_name):
            devices = sd.query_devices()
            hostapis = sd.query_hostapis()
            for i, dev in enumerate(devices):
                if target_name in dev['name'] and dev['max_input_channels'] == const.AUDIO_CHANNELS:
                    dev.get('default_low_input_latency')
                    hostapi_info = hostapis[dev['hostapi']]
                    hostapi_name = hostapi_info.get('name', f"index {dev['hostapi']}")
                    print(f"Selected input device '{dev['name']}' (Index {i})")
                    print(f"  Host API: {hostapi_name} (index {dev['hostapi']})")
                    self.device = i
                    return
            raise RuntimeError(f"Could not find device: {target_name}. Check your VoiceMeeter settings!")
        
        select_device(target_name = const.AUDIO_INPUT_DEVICE_NAME)
        self.buffer = np.zeros((const.AUDIO_CHANNELS, const.FFT_SIZE), dtype=np.float32)
        self.audioqueue = deque(maxlen=10)
        self.fft_thread = FFTCompute(tick=self.tick, audioqueue=self.audioqueue, featurequeue=self.fsm.featurequeue)
        
        # Start continuous audio stream, reading exactly hop_length samples at a time
        try:
            self.stream = sd.InputStream(samplerate=const.SAMPLING_FREQUENCY,
                                         channels=const.AUDIO_CHANNELS,
                                         blocksize=int(const.SAMPLING_FREQUENCY / const.TICK_RATE),
                                         device=self.device,
                                         latency='low',
                                         dtype='float32',
                                         callback=self._audio_callback)
            self.stream.start()
        except Exception as e:
            raise RuntimeError(
                f"Failed to start audio input stream (device={self.device}, channels={self.channels}, samplerate={self.samplerate}): {e}"
            ) from e
   


    def _audio_callback(self, indata, blocksize, time, status):
        """Called every time hop_length samples are available."""
        if status:
            print(f"Audio status string: {status}")
        
        try:
            self.audioqueue.put_nowait(indata.copy())
        except queue.Full:
            _ = self.audioqueue.get_nowait()
            self.audioqueue.task_done()
            self.audioqueue.put_nowait(indata.copy())
        
        # Use the audio hardware callback clock to drive the simulation tick
        self.tick.advance_frame()

    def stop(self):
        self.stream.stop()
        self.stream.close()

class FFTCompute(threading.Thread):
    def __init__(self, tick, audioqueue,featurequeue):
        super().__init__(daemon=True)
        self.tick = tick
        self.featurequeue = featurequeue
        self.audioqueue = audioqueue
        # 2 blocksize buffer to hold enough context for the STFT compute
        self.blocksize =int(const.FFT_SIZE/ 2)
        self.stft_obj = af.STFT(radix2_exp=(const.FFT_SIZE).bit_length() - 1,
                            window_type=af.type.WindowType.HANN,
                            slide_length=self.blocksize)
        self.buffer = np.zeros((const.AUDIO_CHANNELS, const.FFT_SIZE), dtype=np.float32)
        
    
    def run(self):
        print("FFTCompute thread started.")
        while not (self.tick.shutdown.is_set()):
            try:
                audio_data = self.audioqueue.get_nowait()
                self.audioqueue.task_done()
                # Shift the front bits of a blocksize left to remove them
                self.buffer[:, :-self.blocksize] = self.buffer[:, self.blocksize:]
                # Insert new another hop_length samples to the end (transpose to match channel structure)
                self.buffer[:, -self.blocksize:] = audio_data.T

                # Compute the STFT for the current buffer
                spec = self.stft_obj.stft(self.buffer)
                # The resulting spec has shape (channels, bins, 1) since we compute exactly one windowed frame
                frame_data = spec[..., 0]

                # Amplitude shape: (channels = 4, bins)
                freq_amplitude = np.abs(frame_data) 
                max_val = (const.FFT_SIZE / 2) * (2**(const.BIT_DEPTH - 1))
                # Logarithmic normalization to compress dynamic range, then scale to [0, 1]
                amp_norm = np.log1p(freq_amplitude) / np.log1p(max_val)

                # Phase shape: (channels = 4, bins)
                phase_angles = np.angle(frame_data)
                # Taking channel 0 as reference for phase, we can compute relative phase differences
                phase_diff = phase_angles[1:] - phase_angles[0]
                # Wrap phase differences to the range [-pi, pi]
                phase_diff = (phase_diff + np.pi) % (2 * np.pi) - np.pi
                # Normalize to [-1, 1]
                phase_norm = phase_diff/np.pi 

                #shape: (7 = const.N_INPUTS, bins) -> 4 amplitude channels + 3 relative phase differences
                combined_features = np.concatenate([amp_norm, phase_norm], axis=0)
                msg = (self.tick.frame_index, combined_features)
                self.featurequeue.append(msg)
            except queue.Empty:
                pass