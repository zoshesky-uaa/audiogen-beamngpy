from pathlib import Path
import csv
from time import sleep
import threading
import numpy as np
import const
import queue

class FSM:
    def __init__(self, tick):
        self.write_active = False
        self.tick = tick
        self.trial_path, self.tracking_path = self.path_mkdir()

        self.features_storage = np.memmap(
                self.trial_path / 'training_features.npy', 
                dtype='float32', 
                mode='w+', 
                shape=(const.TOTAL_FRAMES, const.N_INPUTS, const.N_BINS)
            )
        
        self.ev_event_buffer = []

        # Buffer all poossible emergency vehicle events
        for i in range (0, const.MAXIMUM_EMERGENCY_VEHICLES):
            self.ev_event_buffer.append(EventObj(3,i, (0.0, 0.0, 0.0)))

        self.driver_buffer = DriverData()
        
        self.driverqueue = queue.Queue(maxsize=2)
        self.eventqueue = {}
        for i in range(0, const.MAXIMUM_EMERGENCY_VEHICLES):
            self.eventqueue[i] = queue.Queue(maxsize=2)

    # ---------- Queue for producer (vehicles) to the writer thread ---------- 

    def write_soundevent_csv(self, class_index,track_index, position):
        if self.write_active:
            msg = EventObj(class_index, track_index, position)
            try:
                self.eventqueue[track_index].put_nowait(msg)
            except queue.Full:
                    _ = self.eventqueue[track_index].get_nowait()
                    self.eventqueue[track_index].task_done()
                    self.eventqueue[track_index].put_nowait(msg)

    # Collection of primitives about the driver for later use:
    # Poll: Damage, Steering, Braking, Velocity (x,y,z), Lane Distances (left line, center, right, halfwidth; remove the max to determine directionality)
    def write_driver_csv(self, velocity, steering, braking, lane_data, damage):
        if self.write_active:
            msg = DriverData(damage, steering, braking, velocity, lane_data)
            try:
                self.driverqueue.put_nowait(msg)
            except queue.Full:
                _ = self.driverqueue.get_nowait()
                self.driverqueue.task_done()
                self.driverqueue.put_nowait(msg)          
    
    #  ---------- Writer thread functions  ---------- 

    def startup(self):
        self.write_active = True
        self._csv_writer_thread = threading.Thread(target=self._csv_writer, name="fsm-csv-writer", daemon=True)
        self._csv_writer_thread.start()

    def shutdown(self):
        self.write_active = False
        try:
            self._csv_writer_thread.join(timeout=10.0)
        except Exception as e:
            print(f"Error occurred while shutting down CSV writer: {e}")
        finally:
            self._close_open_csv_handles()

    def _csv_writer(self):
        self.tick.waited_action_iterate(self._csv_write, 0, None, (lambda: self.write_active))
        
    def _csv_write(self):
        for (csvtype, csv) in self.trial_csvs.items():
                try:
                    match csvtype:
                        case "driver":
                            try:
                                driver_data = self.driverqueue.get_nowait()
                            except queue.Empty:
                                driver_data = None
                            if driver_data is not None:
                                self.driver_buffer.set_data(driver_data.damage,
                                                            driver_data.steering,
                                                            driver_data.braking,
                                                            driver_data.velocity,
                                                            driver_data.lane_data)
                                self.driverqueue.task_done()
                            if csv not in self.open_files:
                                self._open_csv_file(csv)
                            self.csv_writers[csv].writerow([self.tick.frame_index, 
                                                            *self.driver_buffer.row()])
                        case _ if csvtype.startswith("soundevent_3_"):
                            track_index = int(csvtype.split("_")[-1])
                            try:
                                event_data = self.eventqueue[track_index].get_nowait()
                                self.eventqueue[track_index].task_done()
                            except queue.Empty:
                                event_data = None

                            if event_data is not None:
                                self.ev_event_buffer[track_index].set_position(event_data.position)

                            if csv not in self.open_files:
                                self._open_csv_file(csv)
                            self.csv_writers[csv].writerow([self.tick.frame_index,
                                                            *self.ev_event_buffer[track_index].row()])
                        case _: 
                            print(f"Unknown CSV type: {csvtype}") 
                            return
                except Exception as e:
                    print(f"Failed to write to CSV file: {e}") 
            
    def _open_csv_file(self, csv_path):
        try:
            csv_path.parent.mkdir(parents=True, exist_ok=True)
            f = open(csv_path, "a", newline="")
            self.open_files[csv_path] = f
            self.csv_writers[csv_path] = csv.writer(f)
        except Exception as e:
            print(f"Failed to open CSV file {csv_path}: {e}")
 
    def _close_open_csv_handles(self):
        for path_key, f in self.open_files.items():
            try:
                f.flush()
                f.close()
            except Exception as e:
                print(f"Failed to close CSV file {path_key}: {e}")
        self.open_files.clear()
        self.csv_writers.clear()

    def path_mkdir(self):
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
                    pass
        next_trial_name = f"trial_{highest_num + 1}"
        new_trial_path = base_path / next_trial_name
        new_trial_path.mkdir()

        tracking_path = new_trial_path / "tracking"
        tracking_path.mkdir(parents=True, exist_ok=True)
        
        self.trial_csvs = {
            "driver": tracking_path / f"driver.csv"
        }

        for track in range(0,const.MAXIMUM_EMERGENCY_VEHICLES):
            self.trial_csvs[f"soundevent_3_{track}"] = new_trial_path / f"soundevent_3_{track}.csv"

        self.open_files = {}
        self.csv_writers = {}
        return new_trial_path, tracking_path    

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

class EventObj:
    def __init__(self, class_index, track_index, position):
        self.class_index = class_index
        self.track_index = track_index
        self.position = position
    
    def reset(self):
        self.position = (0.0, 0.0, 0.0)

    def set_position(self, position):
        self.position = position
    
    def row(self):
        return [self.class_index, self.track_index, *self.position]

class DriverData:
    def __init__(self, 
                 damage=0.0, 
                 steering=0.0, 
                 braking=0.0, 
                 velocity=(0.0, 0.0, 0.0), 
                 lane_data=(0.0, 0.0, 0.0, 0.0)):
        self.damage = damage
        self.steering = steering
        self.braking = braking
        self.velocity = velocity
        self.lane_data = lane_data

    def reset(self):
        self.damage = 0.0
        self.steering = 0.0
        self.braking = 0.0
        self.velocity = (0.0, 0.0, 0.0)
        self.lane_data = (0.0, 0.0, 0.0, 0.0)

    def set_data(self, damage, steering, braking, velocity, lane_data):
        self.damage = damage
        self.steering = steering
        self.braking = braking
        self.velocity = velocity
        self.lane_data = lane_data
    
    def row(self):
        return [self.damage, self.steering, self.braking, *self.velocity, *self.lane_data]