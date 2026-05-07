from __future__ import annotations

from pathlib import Path
import sys
from contextlib import redirect_stdout
from typing import Iterable, Iterator, List, Tuple

import numpy as np
import zarr
root_dir = Path(__file__).resolve().parent.parent
sys.path.append(str(root_dir))

import const


class ZarrInspector:
    def __init__(self, zarr_path: Path | str, fields: Iterable[str]) -> None:
        self.zarr_path = Path(zarr_path)
        self.fields = list(fields)
        self.root = zarr.open_group(self.zarr_path, mode="r")

    def _iter_nonzero_time_rows(
        self, arr: zarr.Array, time_axis: int
    ) -> Iterator[Tuple[int, np.ndarray]]:
        # Walk time chunks to avoid loading everything at once.
        time_len = arr.shape[time_axis]
        step = arr.chunks[time_axis] if arr.chunks else 1
        other_axes = tuple(axis for axis in range(arr.ndim) if axis != time_axis)
        for start in range(0, time_len, step):
            stop = min(start + step, time_len)
            slices = [slice(None)] * arr.ndim
            slices[time_axis] = slice(start, stop)
            chunk = arr[tuple(slices)]
            nonzero_mask = np.any(chunk != 0.0, axis=other_axes)
            for offset, has_nonzero in enumerate(nonzero_mask):
                if has_nonzero:
                    yield start + offset, np.take(chunk, offset, axis=time_axis)

    @staticmethod
    def _chunk_slices(arr: zarr.Array, chunk_index: Tuple[int, ...]) -> Tuple[slice, ...]:
        slices = []
        for axis, chunk_i in enumerate(chunk_index):
            start = chunk_i * arr.chunks[axis]
            stop = min(start + arr.chunks[axis], arr.shape[axis])
            slices.append(slice(start, stop))
        return tuple(slices)

    def _guess_time_axis(self, arr: zarr.Array, label_mode: bool) -> int:
        if arr.ndim == 1:
            return 0
        if label_mode and arr.ndim == 3 and arr.shape[0] == 1:
            return 1
        if not label_mode and arr.ndim == 3 and arr.shape[0] in (1, 4, 5):
            return 1
        return 0

    def _guess_time_axis_from_const(self, field: str, arr: zarr.Array) -> int | None:
        expected = None
        if field == "doa_features":
            expected = const.doa_fet_buffer_dim
        elif field == "sed_features":
            expected = const.sed_fet_buffer_dim
        elif field == "doa_labels":
            expected = const.doa_label_buffer_dim
        elif field == "sed_labels":
            expected = const.sed_label_buffer_dim

        if expected is None or arr.ndim != 3:
            return None
        # Buffer dims are (channels, time, features) in const.py
        if arr.shape[0] == expected[0]:
            return 1
        return None

    def _guess_channel_axis(self, arr: zarr.Array) -> int:
        if arr.ndim == 1:
            return 0
        if arr.ndim == 3:
            if arr.shape[0] in (1, 4, 5):
                return 0
            if arr.shape[-1] in (1, 4, 5):
                return 2
        return 0

    def _read_time_row(self, arr: zarr.Array, time_axis: int, index: int) -> np.ndarray:
        slices = [slice(None)] * arr.ndim
        slices[time_axis] = index
        return arr[tuple(slices)]

    @staticmethod
    def _summarize_feature_row(feature_row: np.ndarray) -> np.ndarray:
        if feature_row.ndim <= 1:
            return feature_row
        axes = tuple(range(1, feature_row.ndim))
        return np.mean(feature_row, axis=axes)

    @staticmethod
    def _map_time_index(label_index: int, label_len: int, feature_len: int) -> int:
        if feature_len <= 1:
            return 0
        if feature_len == label_len:
            return label_index
        mapped = int(label_index * feature_len / label_len)
        return min(max(mapped, 0), feature_len - 1)

    def report_nonzero_label_rows(self, label_field: str, feature_field: str) -> List[int]:
        if label_field not in self.root:
            print(f"[WARN] Missing label field: {label_field}")
            return []
        if feature_field not in self.root:
            print(f"[WARN] Missing feature field: {feature_field}")
            return []

        label_arr = self.root[label_field]
        feature_arr = self.root[feature_field]
        if label_arr.size == 0:
            print(f"[INFO] Empty label array: {label_field}")
            return []
        if feature_arr.size == 0:
            print(f"[INFO] Empty feature array: {feature_field}")
            return []

        label_time_axis = self._guess_time_axis(label_arr, label_mode=True)
        feature_time_axis = self._guess_time_axis(feature_arr, label_mode=False)
        label_len = label_arr.shape[label_time_axis]
        feature_len = feature_arr.shape[feature_time_axis]

        print(
            f"\n[{label_field}] shape={label_arr.shape} time_axis={label_time_axis}"
            f" -> [{feature_field}] shape={feature_arr.shape} time_axis={feature_time_axis}"
        )
        if label_len != feature_len:
            print(
                f"[INFO] Time axis length mismatch: labels={label_len}, features={feature_len}. "
                "Feature indices will be scaled."
            )

        nonzero_indices: List[int] = []
        for time_index, label_row in self._iter_nonzero_time_rows(label_arr, label_time_axis):
            feature_index = self._map_time_index(time_index, label_len, feature_len)
            feature_row = self._read_time_row(feature_arr, feature_time_axis, feature_index)
            feature_summary = self._summarize_feature_row(feature_row)
            nonzero_indices.append(time_index)
            print(f"\nTime {time_index} (feature index {feature_index}):")
            print(f"Label row:\n{label_row}")
            print(f"Feature row summary:\n{feature_summary}")

        if not nonzero_indices:
            print(f"No nonzero rows found in {label_field}.")
        return nonzero_indices

    def check_sed_has_doa(self, sed_field: str, doa_field: str) -> None:
        if sed_field not in self.root:
            print(f"[WARN] Missing label field: {sed_field}")
            return
        if doa_field not in self.root:
            print(f"[WARN] Missing label field: {doa_field}")
            return
        sed_arr = self.root[sed_field]
        doa_arr = self.root[doa_field]
        if sed_arr.size == 0 or doa_arr.size == 0:
            print("[INFO] One or both label arrays are empty; skipping alignment check.")
            return

        sed_time_axis = self._guess_time_axis(sed_arr, label_mode=True)
        doa_time_axis = self._guess_time_axis(doa_arr, label_mode=True)
        sed_len = sed_arr.shape[sed_time_axis]
        doa_len = doa_arr.shape[doa_time_axis]

        missing_doa: List[int] = []
        for sed_time, _ in self._iter_nonzero_time_rows(sed_arr, sed_time_axis):
            doa_time = self._map_time_index(sed_time, sed_len, doa_len)
            doa_row = self._read_time_row(doa_arr, doa_time_axis, doa_time)
            if not np.any(doa_row != 0.0):
                missing_doa.append(sed_time)

        if not missing_doa:
            print("SED-to-DOA alignment check: OK (every nonzero SED row has a DOA row).")
        else:
            print("SED-to-DOA alignment check: missing DOA rows for SED times:")
            print(missing_doa)

    def report_nonzero_combined(self, label_to_feature: dict[str, str]) -> None:
        label_fields = list(label_to_feature.keys())
        feature_fields = [label_to_feature[field] for field in label_fields]
        missing = [field for field in label_fields + feature_fields if field not in self.root]
        if missing:
            print(f"[WARN] Missing fields: {missing}")
            return

        label_arrays = [self.root[field] for field in label_fields]
        feature_arrays = [self.root[field] for field in feature_fields]
        if any(arr.size == 0 for arr in label_arrays + feature_arrays):
            print("[INFO] One or more arrays are empty; skipping combined report.")
            return

        label_time_axes = [self._guess_time_axis(arr, label_mode=True) for arr in label_arrays]
        feature_time_axes = [self._guess_time_axis(arr, label_mode=False) for arr in feature_arrays]
        label_lens = [arr.shape[axis] for arr, axis in zip(label_arrays, label_time_axes)]
        feature_lens = [arr.shape[axis] for arr, axis in zip(feature_arrays, feature_time_axes)]

        if len(set(label_lens)) != 1:
            print("[WARN] Label time axis lengths differ; falling back to per-label reporting.")
            for label_field, feature_field in label_to_feature.items():
                self.report_nonzero_label_rows(label_field, feature_field)
            return

        time_len = label_lens[0]
        for time_index in range(time_len):
            label_rows = [
                self._read_time_row(arr, axis, time_index)
                for arr, axis in zip(label_arrays, label_time_axes)
            ]
            if not any(np.any(row != 0.0) for row in label_rows):
                continue

            feature_rows = []
            feature_summaries = []
            for arr, axis, feature_len in zip(feature_arrays, feature_time_axes, feature_lens):
                feature_index = self._map_time_index(time_index, time_len, feature_len)
                feature_row = self._read_time_row(arr, axis, feature_index)
                feature_rows.append(feature_row)
                feature_summaries.append(self._summarize_feature_row(feature_row))

            print(f"\nTime {time_index}:")
            for label_field, label_row in zip(label_fields, label_rows):
                print(f"{label_field} row:\n{label_row}")
            for feature_field, summary in zip(feature_fields, feature_summaries):
                print(f"{feature_field} summary:\n{summary}")

    def print_edge_samples(self, field: str, rows: int = 5) -> None:
        if field not in self.root:
            print(f"[WARN] Missing field: {field}")
            return
        arr = self.root[field]
        if arr.size == 0:
            print(f"[INFO] Empty array: {field}")
            return
        label_mode = field.endswith("labels")
        time_axis = self._guess_time_axis_from_const(field, arr)
        if time_axis is None:
            time_axis = self._guess_time_axis(arr, label_mode=label_mode)
        print(f"\n[{field}] shape={arr.shape} dtype={arr.dtype} time_axis={time_axis}")

        front = self._read_time_slice(arr, time_axis, 0, rows)
        back = self._read_time_slice(arr, time_axis, arr.shape[time_axis] - rows, arr.shape[time_axis])
        print(f"First {rows} time rows:")
        print(front)
        print(f"Last {rows} time rows:")
        print(back)

    def _read_time_slice(
        self, arr: zarr.Array, time_axis: int, start: int, stop: int
    ) -> np.ndarray:
        slices = [slice(None)] * arr.ndim
        slices[time_axis] = slice(start, stop)
        return arr[tuple(slices)]

    def summarize_feature_ranges(self, field: str) -> None:
        if field not in self.root:
            print(f"[WARN] Missing field: {field}")
            return
        arr = self.root[field]
        if arr.size == 0:
            print(f"[INFO] Empty array: {field}")
            return

        time_axis = self._guess_time_axis_from_const(field, arr)
        if time_axis is None:
            time_axis = self._guess_time_axis(arr, label_mode=False)
        channel_axis = self._guess_channel_axis(arr)

        time_len = arr.shape[time_axis]
        step = arr.chunks[time_axis] if arr.chunks else 1
        channel_count = arr.shape[channel_axis] if arr.ndim > 1 else 1
        min_vals = np.full(channel_count, np.inf, dtype=np.float64)
        max_vals = np.full(channel_count, -np.inf, dtype=np.float64)

        for start in range(0, time_len, step):
            stop = min(start + step, time_len)
            chunk = self._read_time_slice(arr, time_axis, start, stop)
            if arr.ndim == 1:
                chunk_min = np.min(chunk)
                chunk_max = np.max(chunk)
                min_vals[0] = min(min_vals[0], chunk_min)
                max_vals[0] = max(max_vals[0], chunk_max)
                continue
            chunk = np.moveaxis(chunk, time_axis, 1)
            if channel_axis != 0:
                if channel_axis == time_axis:
                    channel_axis = 1
                chunk = np.moveaxis(chunk, channel_axis, 0)
            reduce_axes = tuple(range(1, chunk.ndim))
            chunk_min = np.min(chunk, axis=reduce_axes)
            chunk_max = np.max(chunk, axis=reduce_axes)
            min_vals = np.minimum(min_vals, chunk_min)
            max_vals = np.maximum(max_vals, chunk_max)

        print(
            f"\n[{field}] per-channel ranges (min/max): {list(zip(min_vals, max_vals))}"
        )

    def run_data_integrity_report(self, sed_label_field: str = "sed_labels", doa_feat_field: str = "doa_features") -> None:
        print("\n" + "="*30)
        print(" DATA INTEGRITY & ACTIVITY REPORT")
        print("="*30)
        
        for field in self.fields:
            if field not in self.root:
                continue
            arr = self.root[field]
            if arr.size == 0:
                print(f"[{field}] Status: EMPTY")
                continue

            # 1. Global Value Scans (Min, Max, NaN, Inf)
            # Iterate by chunk to remain memory-efficient
            g_min, g_max = np.inf, -np.inf
            has_nan = False
            has_inf = False
            
            for chunk_idx in np.ndindex(*arr.cdata_shape):
                chunk = arr.get_orthogonal_selection(self._chunk_slices(arr, chunk_idx))
                if not has_nan and np.isnan(chunk).any(): has_nan = True
                if not has_inf and np.isinf(chunk).any(): has_inf = True
                
                # Filter out nans/infs for min/max calculation
                valid_data = chunk[np.isfinite(chunk)]
                if valid_data.size > 0:
                    g_min = min(g_min, np.min(valid_data))
                    g_max = max(g_max, np.max(valid_data))

            status = "OK" if not (has_nan or has_inf) else "CRITICAL (Math Errors Found)"
            print(f"\n[{field}] Status: {status}")
            print(f"  > Range: [{g_min:.4f}, {g_max:.4f}]")
            print(f"  > Math Errors: {'NaNs ' if has_nan else ''}{'Infs' if has_inf else 'None'}")

            # 2. Activity / Sparsity Check (Specifically for SED labels)
            if field == sed_label_field:
                # Load labels to RAM for activity analysis (typically small)
                data = arr[:]
                # Frame is active if any track in any class is > 0
                active_frames = np.any(data > 0.0, axis=(0, 2)).sum()
                total_frames = data.shape[1]
                ratio = (active_frames / total_frames) * 100
                print(f"  > Activity: {active_frames}/{total_frames} frames ({ratio:.2f}%)")

            # 3. Domain Bound Checks (Reporting only)
            if field == doa_feat_field:
                if g_min < -7.0001 or g_max > 5.0: # Broad Log-Mel bounds
                    print(f"  > [ALERT] Log-Mel values suggest unusual scaling.")
                # Intensity Vectors (Channels 3 & 4) should be checked specifically in summarize_feature_ranges

def main() -> None:
    repo_root = Path(__file__).resolve().parent.parent
    zarr_path = repo_root / "trials" / "trial_1.zarr"
    output_path = repo_root / "tools" / "inspect_zarr_output.txt"
    label_to_feature = {
        "doa_labels": "doa_features",
        "sed_labels": "sed_features",
    }

    inspector = ZarrInspector(
        zarr_path, list(label_to_feature.keys()) + list(label_to_feature.values())
    )

    with output_path.open("w", encoding="utf-8") as output_file:
        with redirect_stdout(output_file):
            print(f"Inspecting: {zarr_path}")
            print("\nNonzero label rows and corresponding features:")
            inspector.report_nonzero_combined(label_to_feature)

            print("\nEdge samples: labels")
            for field in label_to_feature.keys():
                inspector.print_edge_samples(field, rows=5)

            print("\nEdge samples: features")
            for field in label_to_feature.values():
                inspector.print_edge_samples(field, rows=5)

            print("\nFeature ranges (min/max per channel):")
            for field in label_to_feature.values():
                inspector.summarize_feature_ranges(field)

            print("\nDeep Integrity Check:")
            inspector.run_data_integrity_report()
            
    print(f"Wrote output to: {output_path}")


if __name__ == "__main__":
    main()
