from pathlib import Path
import zarr
import threading
import numpy as np
import const
import queue

class FSM:
    def __init__(self, tick):
        self.write_active = False
        self.tick = tick
        # Sets up the directory and Zarr files for training data
        self.training_root, self.label_set, self.feature_set = self.create_trial_data()
        self.ev_event_buffer = [EventObj(3,i, (0.0, 0.0, 0.0)) for i in range(const.MAXIMUM_EMERGENCY_VEHICLES)]
        
        # Queues for communication between audio and vehicle threads
        self.labelqueue = {queue_index: queue.Queue(maxsize=2) for queue_index in range(const.MAXIMUM_EMERGENCY_VEHICLES)}
        self.featurequeue = queue.Queue(maxsize=2)

        # Writer thread object that flushes the above buffers every chunk
        self.writer = ZarrWriter(self.feature_set, 
                                 self.label_set, 
                                 self.tick, 
                                 self.labelqueue, 
                                 self.featurequeue)
     

    def create_trial_data(self):
        base_path = Path('trials').resolve()
        base_path.mkdir(parents=True, exist_ok=True)
        
        # Iterative trial folders for each run
        highest_num = 0
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

        # Create Zarr arrays for training data with Blosc compression
        compressor = zarr.codecs.BloscCodec(cname='zstd', clevel=3, shuffle=zarr.codecs.BloscShuffle.shuffle)
        training_root = zarr.group(new_trial_path / "training_data.zarr")
        label_set = training_root.create_array(
            name="labels",
            shape=(const.TOTAL_FRAMES+1, (const.MAXIMUM_EMERGENCY_VEHICLES), 3),
            dtype="f4",
            chunks=(const.CHUNK_SIZE, const.MAXIMUM_EMERGENCY_VEHICLES, 3),
            compressors=compressor
        )

        feature_set = training_root.create_array(
            name="features",
            shape=(const.TOTAL_FRAMES+1, const.N_INPUTS, const.N_BINS),
            dtype="f4",
            chunks=(const.CHUNK_SIZE, const.N_INPUTS, const.N_BINS),
            compressors=compressor
        )

        # Driver data will be dealt with later, but this is roughly how'd you do it
        # driver_root = zarr.group(self.trial_path / "driver_data.zarr")
        # driver_set = driver_root.create_array(
        #     name="driver",
        #     shape=(const.TOTAL_FRAMES+1, 10),
        #     dtype="f4",
        #     chunks=(const.CHUNK_SIZE, 10),
        #     compressor=compressor
        # )
        return training_root, label_set, feature_set
    
    # ---------- Queue for FSM to read from ---------- 

    def queue_soundevent_data(self, class_index,track_index, position):
        if self.write_active:
            msg = EventObj(class_index, track_index, position)
            try:
                self.eventqueue[track_index].put_nowait(msg)
            except queue.Full:
                    _ = self.eventqueue[track_index].get_nowait()
                    self.eventqueue[track_index].task_done()
                    self.eventqueue[track_index].put_nowait(msg)

    def queue_feature_data(self, features):
        if self.write_active:
            try:
                self.featurequeue.put_nowait(features)
            except queue.Full:
                _ = self.featurequeue.get_nowait()
                self.featurequeue.task_done()
                self.featurequeue.put_nowait(features)

    # Collection of primitives, do processing here instead in future
    # Poll: Damage, Steering, Braking, Velocity (x,y,z), Lane Distances (left line, center, right, halfwidth; remove the max to determine directionality)
    # def queue_driver_data(self, damage, steering, braking, velocity, lane_data):
    #     if self.write_active:
    #         msg = DriverData(damage, steering, braking, velocity, lane_data)
    #         try:
    #             self.driverqueue.put_nowait(msg)
    #         except queue.Full:
    #             _ = self.driverqueue.get_nowait()
    #             self.driverqueue.task_done()
    #             self.driverqueue.put_nowait(msg)          
    
    #  ---------- Writing functions  ---------- 
    # These functions read their relative queues (similar to rust spsc) to have lock-free updates


    def write_driver_data(self):
        try:
            msg = self.driverqueue.get_nowait()
            self.driverqueue.task_done()
        except queue.Empty:
            msg = None
        if msg is not None:
            self.driver_buffer = msg
        #self.driver_set[self.tick.frame_index, :] = self.driver_buffer.row()

class ZarrWriter(threading.Thread):
    def __init__(self, feature_set, label_set, tick, labelqueue, featurequeue):
        super().__init__(daemon=True)
        self.tick = tick
        self.feature_set = feature_set
        self.label_set = label_set
        self.labelqueue = labelqueue
        self.featurequeue = featurequeue
        self.feature_buffer = np.zeros((const.CHUNK_SIZE, const.N_INPUTS, const.N_BINS), dtype="f4")
        self.label_buffer = np.zeros((const.CHUNK_SIZE, const.MAXIMUM_EMERGENCY_VEHICLES, 3), dtype="f4")
        self.next_flush_frame = const.CHUNK_SIZE

    def run(self):
        print("ZarrWriter thread started.")
        while not (self.tick.shutdown.is_set()):
            current_frame = self.tick.frame_index
            # Note: Maybe add the frame_index to events themselves so we know when they were sent to the queue
            # Gets latest event data from queues for each track and updates label buffer
            for track_index in range(0, const.MAXIMUM_EMERGENCY_VEHICLES):
                try:
                    msg = self.labelqueue[track_index].get_nowait()
                    self.labelqueue[track_index].task_done()
                    self.label_buffer[self.tick.frame_index, track_index, :] = msg.row()
                except queue.Empty:
                    pass
                         
            # Gets latest feature data from queue and updates feature buffer
            try:                
                features = self.featurequeue.get_nowait()
                self.featurequeue.task_done()
                self.feature_buffer[self.tick.frame_index, :, :] = features
            except queue.Empty:                
                pass      

            if current_frame >= self.next_flush_frame:
                start_idx = self.next_flush_frame - const.CHUNK_SIZE
                end_idx = self.next_flush_frame
                
                self._flush_chunk(start_idx, end_idx)
                
                # Update the target for the next chunk
                self.next_flush_frame += const.CHUNK_SIZE
        
        remainder = (self.tick.frame_index % const.CHUNK_SIZE)
        if remainder != 0:
                    start_idx = current_frame - remainder
                    self._flush_chunk(start_idx, current_frame + 1)
                    print("Final partial chunk flushed.")
    
    def _flush_chunk(self, start, end):
        self.label_set[start:end] = self.label_buffer[start:end]
        self.feature_set[start:end] = self.feature_buffer[start:end]
        
        print(f"Flushed chunk to Zarr: frames {start} to {end-1}")
        self.label_buffer.fill(0)
        self.feature_buffer.fill(0)

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
        return self.position