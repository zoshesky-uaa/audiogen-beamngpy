import sounddevice as sd
import numpy as np
import audioflux as af
import const 

class AudioRec:
    def __init__(self, tick, fsm, channels=4):
        #Sets up audio stream parameters and the external clock settings
        self.samplerate = const.SAMPLING_FREQUENCY
        self.channels = channels
        self.tick = tick
        self.fsm = fsm

        # Helper selection function
        def select_device(target_name):
            devices = sd.query_devices()
            for i, dev in enumerate(devices):
                if target_name in dev['name'] and dev['max_input_channels'] > 0:
                    self.device = i
                    print(f"Input audio device set to '{target_name}' (Index {i})")
                    return
            raise RuntimeError(f"Could not find device: {target_name}. Check your VoiceMeeter settings!")
        
        select_device(target_name = const.AUDIO_INPUT_DEVICE_NAME)

        self.hop_length = int(self.samplerate / const.TICK_RATE) # Number of samples per tick
        self.fft_length = const.FFT_SIZE       
        
        self.stft_obj = af.STFT(radix2_exp=(self.fft_length).bit_length() - 1,
                                window_type=af.type.WindowType.HANN,
                                slide_length=self.hop_length)
        
        # Rolling buffer to hold exactly n_fft samples per channel
        self.buffer = np.zeros((self.channels, self.fft_length), dtype=np.float32)
        
        # Start continuous audio stream, reading exactly hop_length samples at a time
        try:
            self.stream = sd.InputStream(samplerate=self.samplerate,
                                         channels=self.channels,
                                         blocksize=self.hop_length,
                                         device=self.device,
                                         callback=self._audio_callback)
            self.stream.start()
        except Exception as e:
            raise RuntimeError(
                f"Failed to start audio input stream (device={self.device}, channels={self.channels}, samplerate={self.samplerate}): {e}"
            ) from e
   


    def _audio_callback(self, indata, hop_length, time, status):
        """Called every time hop_length samples are available."""
        # Issues regarding this fallback could be causing crashes
        # This status check is not enough and I need to read how to setup this callback safely
        if status:
            print(f"Audio status string: {status}")
            
        # Shift the buffer left by 'hop_length' (remove old samples)
        self.buffer[:, :-hop_length] = self.buffer[:, hop_length:]
        # Insert new another hop_length samples to the end (transpose to match channel structure)
        self.buffer[:, -hop_length:] = indata.T
        
        # Compute STFT for the snapshot. 
        # Since we're passing exactly 1 windowed length, Audioflux evaluates the frame.
        spec = self.stft_obj.stft(self.buffer)
        frame_data = spec[..., 0] #Remove the time dimension
        
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
        if const.TRAINING:
            # Store the combined features in the pre-allocated memmap array at the correct frame index
            if self.tick.frame_index < const.TOTAL_FRAMES: 
                self.fsm.queue_feature_data(combined_features)
            elif self.tick.frame_index == const.TOTAL_FRAMES:
                print(f"Audio stream reached pre-allocated storage size ({const.TOTAL_FRAMES}). Further frames will be dropped.")
            
            # Use the precise audio hardware callback clock to drive the simulation tick
            self.tick.advance_frame()
    
    def stop(self):
        self.stream.stop()
        self.stream.close()
