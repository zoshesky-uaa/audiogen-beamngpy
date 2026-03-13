from pathlib import Path
import csv
import queue
import threading
import numpy as np
import const

class FSM:
    def __init__(self):
        self.write_active = False
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
        self.features_storage = np.memmap(
                self.trial_path / 'training_features.npy', 
                dtype='float32', 
                mode='w+', 
                shape=(const.TOTAL_FRAMES, const.N_INPUTS, const.N_BINS)
            )
        
        # Single writer thread with queue. Only this thread touches open CSV handles.
        self._csv_queue = queue.Queue()
        self.open_files = {}
        self.csv_writers = {}
        self._sentinel = object() # Shutdown signaling
        self._csv_writer_thread = threading.Thread(target=self._csv_writer_loop, name="fsm-csv-writer", daemon=True)
        self._csv_writer_thread.start()


    def write_soundevent_csv(self, class_index, track_index, position, frame_index):
        if self.write_active:
            csv_file = self.trial_path / f"{class_index}_{track_index}_soundevent.csv"
            row = [frame_index, class_index, track_index, position[0], position[1], position[2]]
            self._csv_queue.put((csv_file, row))

    # Collection of primitives about the driver for later use:
    # Poll: Damage, Steering, Braking, Velocity (x,y,z), Lane Distances (left line, center, right, halfwidth; remove the max to determine directionality)
    def write_driver_data_csv(self, frame_index, velocity, steering, braking, lane_data, damage):
        if self.write_active:
            csv_file = self.tracking_path / f"drive_data.csv"
            row = [frame_index, damage, steering, braking, velocity[0], velocity[1], velocity[2], lane_data[0], lane_data[1], lane_data[2], lane_data[3], damage]
            self._csv_queue.put((csv_file, row))

    def _csv_writer_loop(self):
        while True:
            item = self._csv_queue.get()
            if item is self._sentinel:
                self._csv_queue.task_done()
                break

            csv_file, row = item
            csv_path = str(csv_file)
            try:
                if csv_path not in self.open_files:
                    csv_file.parent.mkdir(parents=True, exist_ok=True)
                    f = open(csv_file, "a", newline="")
                    self.open_files[csv_path] = f
                    self.csv_writers[csv_path] = csv.writer(f)

                self.csv_writers[csv_path].writerow(row)
            finally:
                self._csv_queue.task_done()

    def _close_open_csv_handles(self):
        for path_key, f in self.open_files.items():
            try:
                f.flush()
                f.close()
            except Exception as e:
                print(f"Failed to close CSV file {path_key}: {e}")
        self.open_files.clear()
        self.csv_writers.clear()

    def shutdown(self):
        self.write_active = False
        try:
            # Signal completion and wait until all queued CSV work is done.
            self._csv_queue.put(self._sentinel)
            self._csv_queue.join()
            self._csv_writer_thread.join(timeout=10.0)
        except Exception as e:
            print(f"Error occurred while shutting down CSV writer: {e}")
        finally:
            self._close_open_csv_handles()

    def startup(self):
        self.write_active = True

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        try:
            self.shutdown()
        except Exception:
            pass

    def __del__(self):
        try:
            self.shutdown()
        except Exception:
            pass
