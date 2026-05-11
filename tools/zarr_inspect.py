from __future__ import annotations

import sys
from pathlib import Path
from typing import Dict, List, Tuple
from contextlib import redirect_stdout

import numpy as np
import zarr

# Adjust this to match your specific repository structure
root_dir = Path(__file__).resolve().parent.parent
sys.path.append(str(root_dir))

import const


class ZarrValidator:
    """Scans and validates a directory of Zarr files for ML readiness."""
    
    # Validation Thresholds
    MIN_ACTIVITY_RATIO = 0.30      # At least 35% of frames must contain an event
    MAX_ACTIVITY_RATIO = 0.80      # Avoid datasets that are 80% noise/events (no silence)
    MAX_CONSECUTIVE_SILENCE = 650  # No more than 650 consecutive empty frames 
    LOG_MEL_MIN = -10.0            # Expected floor is ~ -7.0
    LOG_MEL_MAX = 5.0              # Mel energy shouldn't explode
    IV_TOLERANCE = 1.0001          # Intensity Vectors must stay within [-1.0, 1.0]

    def __init__(self, trials_dir: Path | str) -> None:
        self.trials_dir = Path(trials_dir)
        self.zarr_files = sorted(self.trials_dir.glob("*.zarr"))
        
        self.expected_fields = ["doa_features", "sed_features", "doa_labels", "sed_labels"]

    @staticmethod
    def _chunk_slices(arr: zarr.Array, chunk_index: Tuple[int, ...]) -> Tuple[slice, ...]:
        slices = []
        for axis, chunk_i in enumerate(chunk_index):
            start = chunk_i * arr.chunks[axis]
            stop = min(start + arr.chunks[axis], arr.shape[axis])
            slices.append(slice(start, stop))
        return tuple(slices)

    def validate_file(self, zarr_path: Path) -> Tuple[bool, List[str], Dict]:
        """Runs integrity and sparsity checks on a single Zarr file."""
        root = zarr.open_group(zarr_path, mode="r")
        errors = []
        stats = {}
        
        # 1. Structural Checks
        missing = [f for f in self.expected_fields if f not in root]
        if missing:
            errors.append(f"Missing required fields: {missing}")
            return False, errors, stats

        # 2. Label Sparsity, Class Distribution, and Run-Length Checks
        sed_arr = root["sed_labels"]
        if sed_arr.size == 0:
            errors.append("sed_labels is completely empty.")
        else:
            # Labels are small enough to load entirely into RAM
            sed_data = sed_arr[:] 
            
            # Assuming shape is (channels, time, class_index)
            time_axis = 1 if sed_data.shape[0] in (1, 4, 5) else 0
            time_len = sed_data.shape[time_axis]
            
            # 1D boolean array: True if ANY class has an event, False if pure silence
            active_frames_mask = np.any(sed_data > 0.0, axis=tuple(i for i in range(sed_data.ndim) if i != time_axis))
            
            # Calculate overall ratio
            active_frames = active_frames_mask.sum()
            activity_ratio = active_frames / time_len
            stats["activity_ratio"] = activity_ratio
            
            if activity_ratio < self.MIN_ACTIVITY_RATIO:
                errors.append(f"Activity too low ({activity_ratio*100:.2f}%). Simulation may have failed to spawn events.")
            elif activity_ratio > self.MAX_ACTIVITY_RATIO:
                errors.append(f"Activity unusually high ({activity_ratio*100:.2f}%). Potential labeling run-away.")

            # --- LONG SILENCE CHECK (Run-Length Encoding) ---
            # Pad with True (Active) to catch silences that hit the absolute edges of the array
            is_silent = ~active_frames_mask
            padded_silence = np.pad(is_silent, (1, 1), mode='constant', constant_values=False)
            
            # np.diff finds where the boolean state flips
            diffs = np.diff(padded_silence.astype(int))
            starts = np.where(diffs == 1)[0]   # Where silence begins
            ends = np.where(diffs == -1)[0]    # Where silence ends
            
            silence_lengths = ends - starts
            max_silence = silence_lengths.max() if len(silence_lengths) > 0 else 0
            stats["max_consecutive_silence"] = max_silence

            if max_silence > self.MAX_CONSECUTIVE_SILENCE:
                errors.append(f"Massive silence gap found: {max_silence} consecutive empty frames.")

            # Per-class sparsity check
            if sed_data.ndim == 3:
                class_axis = 2
                active_classes = []
                for c_idx in range(sed_data.shape[class_axis]):
                    class_sum = np.sum(sed_data[:, :, c_idx] > 0)
                    if class_sum > 0:
                        active_classes.append(c_idx)
                stats["active_classes"] = active_classes
                if not active_classes:
                    errors.append("No active classes found across the entire timeline.")

            # --- VALIDATION SET (LAST 20%) EVENT CHECK ---
            # Isolate the final 20% of the timeline
            val_split_index = int(time_len * 0.8)
            
            if time_axis == 1:
                val_sed_data = sed_data[:, val_split_index:, :]
            else:
                val_sed_data = sed_data[val_split_index:, ...]
                
            # Check if there are ANY active frames in this final 20% slice
            val_active_mask = np.any(val_sed_data > 0.0)
            
            if not val_active_mask:
                errors.append("Validation Split Error: The last 20% of the timeline contains zero events.")

        # 3. Feature Integrity & Bounds (Chunked for memory safety)
        doa_arr = root["doa_features"]
        if doa_arr.size > 0:
            g_min, g_max = np.inf, -np.inf
            iv_exploded = False
            has_nan, has_inf = False, False

            for chunk_idx in np.ndindex(*doa_arr.cdata_shape):
                chunk = doa_arr.get_orthogonal_selection(self._chunk_slices(doa_arr, chunk_idx))
                
                if not has_nan and np.isnan(chunk).any():
                    has_nan = True
                    errors.append("NaN values detected in doa_features.")
                if not has_inf and np.isinf(chunk).any():
                    has_inf = True
                    errors.append("Infinity values detected in doa_features.")
                
                # Check Intensity Vector bounds (Assuming channels 3 & 4 are IVs)
                if chunk.shape[0] >= 5 and not iv_exploded:
                    iv_channels = chunk[3:5, ...]
                    if np.any(iv_channels > self.IV_TOLERANCE) or np.any(iv_channels < -self.IV_TOLERANCE):
                        iv_exploded = True
                        errors.append("Intensity Vectors exploded out of [-1.0, 1.0] bounds.")

                valid_data = chunk[np.isfinite(chunk)]
                if valid_data.size > 0:
                    g_min = min(g_min, np.min(valid_data))
                    g_max = max(g_max, np.max(valid_data))

            stats["doa_min"] = g_min
            stats["doa_max"] = g_max
            
            if g_min < self.LOG_MEL_MIN or g_max > self.LOG_MEL_MAX:
                if not iv_exploded: # Prevent double-reporting if IVs caused the massive range
                    errors.append(f"doa_features range [{g_min:.2f}, {g_max:.2f}] falls outside expected Mel bounds.")

        is_good = len(errors) == 0
        return is_good, errors, stats

    def run_batch_validation(self, output_file: Path | None = None) -> None:
        """Iterates through all files and builds a consolidated report."""
        if not self.zarr_files:
            print(f"No .zarr files found in {self.trials_dir}")
            return

        report_lines = []
        report_lines.append("=" * 60)
        report_lines.append(" ZARR DATASET BATCH VALIDATION REPORT")
        report_lines.append("=" * 60)
        report_lines.append(f"Directory: {self.trials_dir}")
        report_lines.append(f"Files Found: {len(self.zarr_files)}\n")

        passed_count = 0
        
        for idx, file_path in enumerate(self.zarr_files, 1):
            is_good, errors, stats = self.validate_file(file_path)
            status_tag = "[PASS]" if is_good else "[FAIL]"
            
            report_lines.append(f"[{idx}/{len(self.zarr_files)}] {file_path.name} ".ljust(50, ".") + f" {status_tag}")
            
            # Print Stats
            activity = stats.get('activity_ratio', 0)
            max_silence = stats.get('max_consecutive_silence', 0)
            report_lines.append(f"  - Activity Ratio : {activity*100:05.2f}%")
            report_lines.append(f"  - Max Silence Gap: {max_silence} frames")
            
            if 'active_classes' in stats:
                report_lines.append(f"  - Active Classes : {stats['active_classes']}")
            
            if 'doa_min' in stats and 'doa_max' in stats:
                report_lines.append(f"  - Feature Range  : [{stats['doa_min']:.2f}, {stats['doa_max']:.2f}]")

            # Print Errors
            if not is_good:
                for err in errors:
                    report_lines.append(f"  ! ERROR: {err}")
            else:
                passed_count += 1
                
            report_lines.append("") # Spacer
            
        report_lines.append("=" * 60)
        report_lines.append(f" SUMMARY: {passed_count}/{len(self.zarr_files)} files PASSED validation.")
        report_lines.append("=" * 60)

        report_text = "\n".join(report_lines)
        
        if output_file:
            with open(output_file, "w", encoding="utf-8") as f:
                f.write(report_text)
            print(f"Batch validation complete. Report saved to: {output_file}")
        else:
            print(report_text)


def main() -> None:
    repo_root = Path(__file__).resolve().parent.parent
    trials_dir = repo_root / "trials"
    output_path = repo_root / "tools" / "dataset_validation_report.txt"

    validator = ZarrValidator(trials_dir)
    validator.run_batch_validation(output_file=output_path)


if __name__ == "__main__":
    main()