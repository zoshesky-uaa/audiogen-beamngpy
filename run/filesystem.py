from pathlib import Path
from collections import deque
import re
import threading
import traceback

import numpy as np
import zarr

import const


TRIAL_DIR_PATTERN = re.compile(r"^trial_(\d+)(?:\..+)?$")


class FSM:
    def __init__(self, tick, simulation=None, write_features=True):
        self.write_active = False
        self.tick = tick
        self.simulation = simulation
        self.trial_name = None
        self.trial_path = None
        self.final_trial_path = None
        self.status_path = None
        self.completed = False

        self.training_root, self.label_set, self.feature_set = self.create_trial_data(write_features)
        self.labelqueue = {
            class_index: {
                track_index: deque()
                for track_index in range(const.MAXIMUM_CONTROLLABLE_VEHICLES)
            }
            for class_index in range(const.NUMBER_OF_SOUND_CLASSES)
        }
        self.featurequeue = deque()

        self.writer = ZarrWriter(
            self.feature_set,
            self.label_set,
            self.tick,
            self.labelqueue,
            self.featurequeue,
            self.simulation,
        )

    def create_trial_data(self, write_features=True):
        base_path = Path("trials").resolve()
        base_path.mkdir(parents=True, exist_ok=True)

        highest_num = 0
        for child in base_path.iterdir():
            if not child.is_dir():
                continue
            match = TRIAL_DIR_PATTERN.match(child.name)
            if match is not None:
                highest_num = max(highest_num, int(match.group(1)))

        self.trial_name = f"trial_{highest_num + 1}"
        self.final_trial_path = base_path / self.trial_name
        self.trial_path = base_path / f"{self.trial_name}.incomplete"
        self.status_path = self.trial_path / "trial_status.txt"
        print(f"Writing to folder: {self.trial_path.name}")
        self.trial_path.mkdir()
        self._write_status("incomplete")

        compressor = zarr.codecs.BloscCodec(
            cname="zstd",
            clevel=3,
            shuffle=zarr.codecs.BloscShuffle.shuffle,
        )
        training_root = zarr.group(self.trial_path / "training_data.zarr")
        label_set = training_root.create_array(
            name="labels",
            shape=(const.TOTAL_FRAMES + 1, const.NUMBER_OF_SOUND_CLASSES, const.MAXIMUM_CONTROLLABLE_VEHICLES, 3),
            dtype="f4",
            chunks=(const.CHUNK_SIZE, const.NUMBER_OF_SOUND_CLASSES, const.MAXIMUM_CONTROLLABLE_VEHICLES, 3),
            compressors=compressor,
        )

        feature_set = None
        if write_features:
            feature_set = training_root.create_array(
                name="features",
                shape=(const.TOTAL_FRAMES + 1, const.N_INPUTS, const.N_BINS),
                dtype="f4",
                chunks=(const.CHUNK_SIZE, const.N_INPUTS, const.N_BINS),
                compressors=compressor,
            )

        return training_root, label_set, feature_set

    def _write_status(self, status, reason=None):
        lines = [f"status={status}"]
        if reason:
            lines.append(f"reason={reason}")
        self.status_path.write_text("\n".join(lines) + "\n", encoding="utf-8")

    def finalize_trial(self):
        if self.completed:
            return
        if self.trial_path != self.final_trial_path:
            self.trial_path.rename(self.final_trial_path)
            self.trial_path = self.final_trial_path
            self.status_path = self.trial_path / "trial_status.txt"
        self._write_status("complete")
        self.completed = True
        print(f"Finalized trial data: {self.trial_path.name}")

    def invalidate_trial(self, reason):
        if self.completed:
            return
        invalid_path = self.final_trial_path.with_name(f"{self.trial_name}.invalid")
        if self.trial_path != invalid_path:
            self.trial_path.rename(invalid_path)
            self.trial_path = invalid_path
            self.status_path = self.trial_path / "trial_status.txt"
        self._write_status("invalid", reason)
        self.completed = True
        print(f"Marked trial data invalid: {self.trial_path.name}")


class ZarrWriter(threading.Thread):
    def __init__(self, feature_set, label_set, tick, labelqueue, featurequeue, simulation=None):
        super().__init__(name="Zarr writer", daemon=True)
        self.tick = tick
        self.simulation = simulation
        self.feature_set = feature_set
        self.label_set = label_set
        self.labelqueue = labelqueue
        self.featurequeue = featurequeue
        print("ZarrWriter initialized.")
        self.feature_buffer = np.full((const.CHUNK_SIZE, const.N_INPUTS, const.N_BINS), np.nan, dtype="f4")
        self.label_buffer = np.zeros((const.CHUNK_SIZE, const.NUMBER_OF_SOUND_CLASSES, const.MAXIMUM_CONTROLLABLE_VEHICLES, 3), dtype="f4")
        self.last_feature = np.full((const.N_INPUTS, const.N_BINS), np.nan, dtype="f4")
        self.last_label = np.zeros((const.NUMBER_OF_SOUND_CLASSES, const.MAXIMUM_CONTROLLABLE_VEHICLES, 3), dtype="f4")
        self.next_flush_frame = const.CHUNK_SIZE

    def run(self):
        print("ZarrWriter thread started.")
        try:
            while True:
                source_frame = self.tick.frame_index
                current_frame = source_frame - self.tick.recording_start_frame
                chunk_start = self.next_flush_frame - const.CHUNK_SIZE
                local_idx = current_frame % const.CHUNK_SIZE

                for class_index in range(const.NUMBER_OF_SOUND_CLASSES):
                    for track_index in range(const.MAXIMUM_CONTROLLABLE_VEHICLES):
                        while True:
                            try:
                                msg = self.labelqueue[class_index][track_index].popleft()
                            except IndexError:
                                break
                            record_frame = msg[0] - self.tick.recording_start_frame
                            self.last_label[class_index, track_index, :] = msg[1:]
                            if record_frame >= chunk_start:
                                self.label_buffer[record_frame % const.CHUNK_SIZE, class_index, track_index, :] = msg[1:]
                        if current_frame >= 0:
                            self.label_buffer[local_idx, class_index, track_index, :] = self.last_label[class_index, track_index, :]

                if self.feature_set is not None:
                    while True:
                        try:
                            msg = self.featurequeue.popleft()
                        except IndexError:
                            break
                        record_frame = msg[0] - self.tick.recording_start_frame
                        self.last_feature[:, :] = msg[1]
                        if record_frame >= chunk_start:
                            self.feature_buffer[record_frame % const.CHUNK_SIZE, :, :] = msg[1]
                    if current_frame >= 0:
                        self.feature_buffer[local_idx, :, :] = self.last_feature

                if current_frame + 1 >= self.next_flush_frame:
                    self._flush_chunk(self.next_flush_frame - const.CHUNK_SIZE, self.next_flush_frame)
                    self.next_flush_frame += const.CHUNK_SIZE

                pending_labels = any(
                    self.labelqueue[class_index][track_index]
                    for class_index in range(const.NUMBER_OF_SOUND_CLASSES)
                    for track_index in range(const.MAXIMUM_CONTROLLABLE_VEHICLES)
                )
                if self.tick.shutdown.is_set() and not pending_labels and not self.featurequeue:
                    break
                self.tick.wait_next(source_frame)

            final_end = (self.tick.frame_index - self.tick.recording_start_frame) + 1
            while final_end >= self.next_flush_frame:
                self._flush_chunk(self.next_flush_frame - const.CHUNK_SIZE, self.next_flush_frame)
                self.next_flush_frame += const.CHUNK_SIZE
            remainder = final_end % const.CHUNK_SIZE
            if remainder:
                self._flush_chunk(final_end - remainder, final_end)
                print("Final partial chunk flushed.")
        except Exception as e:
            if self.simulation is not None and getattr(self.simulation, "on", True) and not self.tick.shutdown.is_set():
                print(f"ZarrWriter failed: {e}")
                traceback.print_exc()
                self.simulation.invalidate_trial(f"Trial writer failed: {e}", stop_run=True)

    def _flush_chunk(self, start, end):
        if end <= start:
            return
        start = max(0, int(start))
        end = min(int(end), const.TOTAL_FRAMES + 1)
        if end <= start:
            return
        length = end - start
        self.label_set[start:end] = self.label_buffer[0:length]
        if self.feature_set is not None:
            self.feature_set[start:end] = self.feature_buffer[0:length]

        print(f"Flushed chunk to Zarr: frames {start} to {end - 1}")
        self.label_buffer.fill(0)
        self.feature_buffer.fill(np.nan)
