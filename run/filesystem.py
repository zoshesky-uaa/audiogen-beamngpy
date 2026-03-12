from pathlib import Path
import csv
import soundfile as sf
import matplotlib.pyplot as plt

class FSM:
    def __init__(self):
        """
        Sequential data collection
        """
        base_path = Path('trials').resolve()
        base_path.mkdir(parents=True, exist_ok=True)

        highest_num = 0
        # Search for existing trial directories to find the highest number
        for child in base_path.iterdir():
            if child.is_dir() and child.name.startswith("trial_"):
                try:
                    num = int(child.name.split("_")[1])
                    highest_num = max(highest_num, num)
                except ValueError:
                    # Ignore folders like "trial_abc"
                    pass

        next_trial_name = f"trial_{highest_num + 1}"
        new_trial_path = base_path / next_trial_name

        # Create the new directory
        new_trial_path.mkdir()

        tracking_path = new_trial_path / "tracking"
        tracking_path.mkdir(parents=True, exist_ok=True)

        self.tracking_path = tracking_path
        self.trial_path = new_trial_path

    def write_soundevent_csv(self, class_index, track_index, position, frame_index):
        csv_file = self.trial_path / f"{class_index}_{track_index}_soundevent.csv"
        with open(csv_file, "a", newline="") as f:
            writer = csv.writer(f)
            writer.writerow([frame_index, class_index, track_index, position[0], position[1], position[2]])

    # Collection of primitives about the driver for later use:
    # Poll: Damage, Steering, Braking, Velocity (x,y,z), Lane Distances (left line, center, right, halfwidth; remove the max to determine directionality)
    def write_driver_data_csv(self, frame_index, velocity, steering, braking, lane_data, damage):
        csv_file = self.tracking_path / f"drive_data.csv"
        with open(csv_file, "a", newline="") as f:
            writer = csv.writer(f)
            writer.writerow([frame_index, damage, steering, braking, velocity[0], velocity[1], velocity[2], lane_data[0], lane_data[1], lane_data[2], lane_data[3], damage])

    def write_wav(self, audio_data):
        wav_file = self.trial_path / f"driver_audio.wav"
        with sf.SoundFile(wav_file, mode='w', samplerate=24000, channels=4, format='WAV', subtype='PCM_16') as f:
            f.write(audio_data)

    def testplot(self, audio_data):
        plt.plot(audio_data[:1000,0], label="FL")
        plt.plot(audio_data[:1000,1], label="FR")
        plt.plot(audio_data[:1000,2], label="BL")
        plt.plot(audio_data[:1000,3], label="BR")
        plt.title("Audio Data")
        plt.xlabel("Sample Index")
        plt.ylabel("Amplitude")
        plt.legend()
        plt.show()