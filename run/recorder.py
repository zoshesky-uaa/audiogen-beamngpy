import queue
import threading

import audioflux as af
import numpy as np
import sounddevice as sd

import const


class AudioRec:
    def __init__(self, tick, fsm):
        self.tick = tick
        self.fsm = fsm

        def select_device(target_name):
            devices = sd.query_devices()
            hostapis = sd.query_hostapis()
            for i, dev in enumerate(devices):
                if target_name in dev["name"] and dev["max_input_channels"] >= const.AUDIO_CHANNELS:
                    hostapi_info = hostapis[dev["hostapi"]]
                    hostapi_name = hostapi_info.get("name", f"index {dev['hostapi']}")
                    print(f"Selected input device '{dev['name']}' (Index {i})")
                    print(f"  Host API: {hostapi_name} (index {dev['hostapi']})")
                    self.device = i
                    return
            raise RuntimeError(f"Could not find device: {target_name}. Check your VoiceMeeter settings!")

        select_device(target_name=const.AUDIO_INPUT_DEVICE_NAME)
        self.audioqueue = queue.Queue(maxsize=10)
        self.fft_thread = FFTCompute(
            tick=self.tick,
            audioqueue=self.audioqueue,
            featurequeue=self.fsm.featurequeue,
        )
        self.channels = const.AUDIO_CHANNELS
        self.samplerate = const.SAMPLING_FREQUENCY
        self.blocksize = int(const.SAMPLING_FREQUENCY / const.TICK_RATE)

        try:
            self.stream = sd.InputStream(
                samplerate=self.samplerate,
                channels=self.channels,
                blocksize=self.blocksize,
                device=self.device,
                latency="low",
                dtype="float32",
                callback=self._audio_callback,
            )
            self.fft_thread.start()
            self.stream.start()
        except Exception as e:
            self.tick.stop()
            raise RuntimeError(
                f"Failed to start audio input stream "
                f"(device={self.device}, channels={self.channels}, samplerate={self.samplerate}): {e}"
            ) from e

    def _audio_callback(self, indata, blocksize, time, status):
        if status:
            print(f"Audio status string: {status}")
        frame_index = self.tick.frame_index + 1
        try:
            self.audioqueue.put_nowait((frame_index, indata.copy()))
        except queue.Full:
            try:
                self.audioqueue.get_nowait()
                self.audioqueue.task_done()
            except queue.Empty:
                pass
            self.audioqueue.put_nowait((frame_index, indata.copy()))

        self.tick.advance_frame()

    def stop(self):
        if hasattr(self, "stream"):
            self.stream.stop()
            self.stream.close()
        self.fft_thread.join(timeout=1.0)


class FFTCompute(threading.Thread):
    def __init__(self, tick, audioqueue, featurequeue):
        super().__init__(name="FFT compute", daemon=True)
        self.tick = tick
        self.featurequeue = featurequeue
        self.audioqueue = audioqueue
        self.blocksize = int(const.FFT_SIZE / 2)
        self.stft_obj = af.STFT(
            radix2_exp=(const.FFT_SIZE).bit_length() - 1,
            window_type=af.type.WindowType.HANN,
            slide_length=self.blocksize,
        )
        self.buffer = np.zeros((const.AUDIO_CHANNELS, const.FFT_SIZE), dtype=np.float32)

    def run(self):
        print("FFTCompute thread started.")
        while not self.tick.shutdown.is_set() or not self.audioqueue.empty():
            try:
                frame_index, audio_data = self.audioqueue.get(timeout=0.1)
            except queue.Empty:
                continue
            try:
                self.buffer[:, :-self.blocksize] = self.buffer[:, self.blocksize:]
                self.buffer[:, -self.blocksize:] = audio_data.T

                spec = self.stft_obj.stft(self.buffer)
                frame_data = spec[..., 0]

                freq_amplitude = np.abs(frame_data)
                max_val = (const.FFT_SIZE / 2) * (2 ** (const.BIT_DEPTH - 1))
                amp_norm = np.log1p(freq_amplitude) / np.log1p(max_val)

                phase_angles = np.angle(frame_data)
                phase_diff = phase_angles[1:] - phase_angles[0]
                phase_diff = (phase_diff + np.pi) % (2 * np.pi) - np.pi
                phase_norm = phase_diff / np.pi

                combined_features = np.concatenate([amp_norm, phase_norm], axis=0)
                self.featurequeue.append((frame_index, combined_features))
            finally:
                self.audioqueue.task_done()
