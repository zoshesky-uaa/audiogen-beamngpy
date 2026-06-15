from __future__ import annotations

from enum import Enum
from pathlib import Path
import random
from typing import Iterable, Optional

import numpy as np
import torch

from .config import Config


class DatasetType(str, Enum):
    SED_FEATURES = "sed_features"
    DOA_FEATURES = "doa_features"
    SED_LABELS = "sed_labels"
    DOA_LABELS = "doa_labels"


def _open_group(path: Path):
    import z5py
    return z5py.File(str(path), mode="r")

def _chunk_exists(ds, chunk_idx: int) -> bool:
    if hasattr(ds, "chunkExists"):
        return bool(ds.chunkExists([0, chunk_idx, 0]))

    if not hasattr(ds, "_chunk_key"):
        return True

    try:
        key = ds._chunk_key((0, chunk_idx, 0))
    except Exception:
        return True

    for store_attr in ("chunk_store", "store"):
        store = getattr(ds, store_attr, None)
        if store is None:
            continue
        try:
            return key in store
        except Exception:
            continue
    return True


class ZarrBatcher:
    def __init__(
        self,
        ds,
        chunk_shape: Iterable[int],
        batch_size: int,
        device: torch.device,
        dataset_type: DatasetType,
    ) -> None:
        self.ds = ds
        self.chunk_shape = tuple(int(x) for x in chunk_shape)
        self.batch_size = int(batch_size)
        self.device = device
        self.dataset_type = dataset_type
        self.read_chunk = 0

        self.read_buffer = np.empty(self.chunk_shape, dtype=np.float32)
        self.x_in = torch.empty(
            (self.batch_size, *self.chunk_shape),
            device=self.device,
            dtype=torch.float32,
        )
        if self.device.type == "cuda":
            self.x_in = self.x_in.to(memory_format=torch.channels_last)

    def read_reset(self) -> None:
        self.read_chunk = 0

    def _apply_silence(self) -> None:
        if self.dataset_type == DatasetType.SED_FEATURES:
            self.read_buffer.fill(-7.0)
        elif self.dataset_type == DatasetType.DOA_FEATURES:
            self.read_buffer.fill(0.0)
            self.read_buffer[0:3, :, :] = -7.0
        else:
            self.read_buffer.fill(0.0)

    def _read_chunk(self) -> bool:
        chunk_len = self.chunk_shape[1]
        start = self.read_chunk * chunk_len
        stop = start + chunk_len
        self.read_chunk += 1

        if start >= int(self.ds.shape[1]):
            return False

        if not _chunk_exists(self.ds, self.read_chunk - 1):
            return False

        data = np.asarray(self.ds[:, start:stop, :], dtype=np.float32)
        if data.shape != self.read_buffer.shape:
            return False

        np.copyto(self.read_buffer, data)
        return True
    
    def apply_spec_augment(self, tensor: torch.Tensor, max_f_mask: int = 25, max_t_mask: int = 40):
        # tensor shape: [Channels, Time, Freq]
        _, time_steps, freq_bins = tensor.shape
        
        # Frequency masking
        if random.random() < 0.5:
            f_width = random.randint(1, max_f_mask)
            f_start = random.randint(0, freq_bins - f_width)
            tensor[:, :, f_start:f_start + f_width] = -7.0 # Your silence baseline
            
        # Time masking
        if random.random() < 0.5:
            t_width = random.randint(1, max_t_mask)
            t_start = random.randint(0, time_steps - t_width)
            tensor[:, t_start:t_start + t_width, :] = -7.0
            
        return tensor
    
    def batch(
        self,
        valid_mask_out: Optional[list[bool]] = None,
        force_silence_mask: Optional[list[bool]] = None,
        apply_augment: bool = False,
    ) -> torch.Tensor:
        if valid_mask_out is not None:
            valid_mask_out[:] = [False] * self.batch_size

        use_cuda = self.device.type == "cuda"
        for batch_idx in range(self.batch_size):
            chunk_valid = False
            if force_silence_mask is not None and not force_silence_mask[batch_idx]:
                self._apply_silence()
            else:
                try:
                    chunk_valid = self._read_chunk()
                except Exception:
                    chunk_valid = False
                if not chunk_valid:
                    self._apply_silence()
                
            if valid_mask_out is not None:
                valid_mask_out[batch_idx] = chunk_valid

            chunk_tensor = torch.from_numpy(self.read_buffer)
            if apply_augment and self.dataset_type in (DatasetType.SED_FEATURES, DatasetType.DOA_FEATURES):
                            chunk_tensor = self.apply_spec_augment(chunk_tensor)
            self.x_in[batch_idx].copy_(chunk_tensor, non_blocking=use_cuda)

        return self.x_in


class ZarrReader:
    def __init__(self, path: Path, config: Config, device: torch.device) -> None:
        root = _open_group(path)
        self.sed_featureset = ZarrBatcher(
            root[DatasetType.SED_FEATURES.value],
            config.sed_fet_buffer_dim,
            config.batch_size,
            device,
            DatasetType.SED_FEATURES,
        )
        self.doa_featureset = ZarrBatcher(
            root[DatasetType.DOA_FEATURES.value],
            config.doa_fet_buffer_dim,
            config.batch_size,
            device,
            DatasetType.DOA_FEATURES,
        )
        self.sed_labelset = ZarrBatcher(
            root[DatasetType.SED_LABELS.value],
            config.sed_label_buffer_dim,
            config.batch_size,
            device,
            DatasetType.SED_LABELS,
        )
        self.doa_labelset = ZarrBatcher(
            root[DatasetType.DOA_LABELS.value],
            config.doa_label_buffer_dim,
            config.batch_size,
            device,
            DatasetType.DOA_LABELS,
        )

    def reset(self) -> None:
        self.sed_featureset.read_reset()
        self.doa_featureset.read_reset()
        self.sed_labelset.read_reset()
        self.doa_labelset.read_reset()
