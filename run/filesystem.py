
from collections import deque
import z5py
import const
import numpy as np
import shutil  
from run import scheduler, validation

class FSM:
    def __init__(self, tick, simulation=None):
        self.write_active = False
        self.tick = tick
        self.simulation = simulation
        self.writer_thread = None

        self.root_group = z5py.File(self.simulation.zarr_path, use_zarr_format=True)
        print(f"Created Zarr file at: {self.simulation.zarr_path.as_posix()}")
        # Create labelsets
        sed_labelset = self.root_group.create_dataset("sed_labels", 
                                    dtype="float32", 
                                    shape=(const.sed_label_buffer_dim[0], const.label_max, const.sed_label_buffer_dim[2]), 
                                    chunks=const.sed_label_buffer_dim,
                                    compression='blosc',  
                                    codec='zstd',
                                    fillvalue=0.0,   
                                    clevel=3,  
                                    shuffle=1,  
                                    blocksize=0)
        
        doa_labelset = self.root_group.create_dataset("doa_labels", 
                                    dtype="float32", 
                                    shape=(const.doa_label_buffer_dim[0], const.label_max, const.doa_label_buffer_dim[2]), 
                                    chunks=const.doa_label_buffer_dim,
                                    compression='blosc',  
                                    codec='zstd',   
                                    fillvalue=0.0,
                                    clevel=3,  
                                    shuffle=1,  
                                    blocksize=0)

        self.sed_queue = deque() 
        self.doa_queue = deque() 

        self.writer = ZarrWriter(
            self.tick,
            self.simulation,
            sed_labelset,
            doa_labelset,
            self.sed_queue,
            self.doa_queue, 
        )
        
        self.gen_cmd = {
            "device_name": const.AUDIO_INPUT_DEVICE_NAME,
            "zarr_path": str(self.simulation.zarr_path.as_posix()),
            **const.const_json["config"]
        }

        self.validator = validation.ZarrValidator(self.simulation.zarr_path)
    
    def zarr_cleanup(self):
        if self.writer_thread is not None:
            scheduler.join_thread(self.writer_thread)
        
        self.sed_labelset = None
        self.doa_labelset = None
        self.root_group = None

        if self.simulation.zarr_path.exists():
            try:
                print(f"Cleaning up Zarr directory: {self.simulation.zarr_path.as_posix()}")
                shutil.rmtree(self.simulation.zarr_path)
            except FileNotFoundError:
                pass
            except PermissionError as e:
                raise RuntimeError(f"Permission error during Zarr cleanup: {e}")


import heapq
class ZarrWriter:
    def __init__(self, 
                 tick, 
                 simulation,
                 sed_labelset,
                 doa_labelset, 
                 sed_queue, 
                 doa_queue):
        self.tick = tick
        self.simulation = simulation
        self.sed_labelset = sed_labelset
        self.doa_labelset = doa_labelset

        self.sed_queue = sed_queue
        self.doa_queue = doa_queue

        self.chunk_size = const.sed_label_buffer_dim[1]
        self.sed_chunk_buffer = np.zeros(const.sed_label_buffer_dim, dtype=np.float32)
        self.doa_chunk_buffer = np.zeros(const.doa_label_buffer_dim, dtype=np.float32)
        self.write_offset = 0

        self.messenger_registry = {}
        self.available_slots = {
            se_idx: list(range(const.track_count)) 
            for se_idx in range(const.se_count)
        }
        for se_idx in self.available_slots:
            heapq.heapify(self.available_slots[se_idx])

        print("ZarrWriter initialized.")

    def _get_or_assign_track(self, se_idx, abstract_id):
        key = (se_idx, abstract_id)
        if key in self.messenger_registry:
            return self.messenger_registry[key]
        
        # Assign lowest available track index for this specific class
        if self.available_slots[se_idx]:
            assigned_slot = heapq.heappop(self.available_slots[se_idx])
            self.messenger_registry[key] = assigned_slot
            return assigned_slot
        return None 

    def _release_track(self, se_idx, abstract_id):
        key = (se_idx, abstract_id)
        if key in self.messenger_registry:
            slot = self.messenger_registry.pop(key)
            heapq.heappush(self.available_slots[se_idx], slot)

    def run(self):
            print("ZarrWriter thread started.")
            current_frame = 0
            self.tick.wait_next(current_frame)

            try:
                while not self.tick.shutdown.is_set():
                    current_frame = self.tick.frame_index
                    pending_releases = []
                    # --- Drain Global SED Queue ---
                    while self.sed_queue:
                        # Peek at the oldest item's frame index
                        if self.sed_queue[0][0] >= self.write_offset + self.chunk_size:
                            break  # Reached data for the *next* chunk. Stop popping.
                        
                        msg_frame, se_idx, abstract_id, val = self.sed_queue.popleft()
                        
                        if msg_frame < self.write_offset:
                            continue  # Discard stale data
                        
                        local_t = msg_frame - self.write_offset
                        track_idx = self._get_or_assign_track(se_idx, abstract_id)
                        
                        if track_idx is not None:
                            # Track major index
                            flat_idx = (track_idx * const.se_count) + se_idx
                            self.sed_chunk_buffer[0, local_t, flat_idx] = val
                            
                            # Release the assigned track if this is a write_reset signal
                            if val == 0.0:
                                pending_releases.append((se_idx, abstract_id))

                    # --- Drain Global DOA Queue ---
                    while self.doa_queue:
                        if self.doa_queue[0][0] >= self.write_offset + self.chunk_size:
                            break  # Reached data for the *next* chunk. Stop popping.
                        
                        # Unpack the 6-item tuple
                        msg_frame, se_idx, abstract_id, x, y, z = self.doa_queue.popleft()
                        
                        if msg_frame < self.write_offset:
                            continue  # Discard stale data
                        
                        local_t = msg_frame - self.write_offset
                        track_idx = self._get_or_assign_track(se_idx, abstract_id)
                        
                        if track_idx is not None:
                            flat_idx = ((track_idx * const.se_count) + se_idx) * 2
                            self.doa_chunk_buffer[0, local_t, flat_idx]     = x
                            self.doa_chunk_buffer[0, local_t, flat_idx + 1] = y
                            
                            # Note: We do NOT call _release_track here. 
                            # Because write_reset fires both SED and DOA messages for the same frame
                    
                    # Safe release after processing 
                    for se_idx, a_id in pending_releases:
                        self._release_track(se_idx, a_id)
                        
                    # --- Commit Chunk ---
                    if current_frame >= self.write_offset + self.chunk_size:
                        self.commit_and_reset()
                        #print(f"Write Operation Committed: Frames {self.write_offset} to {self.write_offset + self.chunk_size - 1}")
                    self.tick.wait_next(current_frame)
            finally:
                print("[ZarrWriter] Thread shutting down. Flushing final buffer to disk...")
                self.commit_and_reset()

    def commit_and_reset(self):
            # Write to disk
            self.sed_labelset[:, self.write_offset : self.write_offset + self.chunk_size, :] = self.sed_chunk_buffer
            self.doa_labelset[:, self.write_offset : self.write_offset + self.chunk_size, :] = self.doa_chunk_buffer
            
            # Advance the window
            self.write_offset += self.chunk_size
            
            # Zero the buffers for the next chunk
            self.sed_chunk_buffer.fill(0.0)
            self.doa_chunk_buffer.fill(0.0)