import os
from pathlib import Path
import csv
import os

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
        self.trial_path = new_trial_path


    def write_event_csv(self, event):
        csv_file = self.trial_path / f"{event.class_index}_{event.track_index}_output.csv"
        with open(csv_file, "a", newline="") as f:
            writer = csv.writer(f)
            writer.writerow([event.tick.frame_index, event.class_index, event.track_index, event.position[0], event.position[1], event.position[2]])

