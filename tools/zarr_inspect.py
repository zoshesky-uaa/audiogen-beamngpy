from __future__ import annotations

import sys
from pathlib import Path
from typing import Dict, List, Tuple

import numpy as np
import z5py
import shutil
# Adjust this to match your specific repository structure
root_dir = Path(__file__).resolve().parent.parent
sys.path.append(str(root_dir))

import const

class ZarrValidator:
    """Scans and validates a directory of Zarr files for ML readiness."""
    
    # Validation Thresholds
    MIN_ACTIVITY_RATIO = 0.20      # Overall dataset minimum activity (20%)
    MAX_ACTIVITY_RATIO = 0.80      # Overall dataset maximum activity (80%)

    def __init__(self, trials_dir: Path | str) -> None:
        self.trials_dir = Path(trials_dir)
        self.zarr_files = sorted(self.trials_dir.glob("*.zarr"))
        
        self.expected_fields = ["doa_features", "sed_features", "doa_labels", "sed_labels"]

    def validate_file(self, zarr_path: Path) -> Tuple[bool, List[str], Dict]:
        """Runs structural and sparsity checks on a single Zarr file."""
        root = z5py.File(zarr_path, use_zarr_format=True)
        errors = []
        stats = {}
        
        # 1. Structural Checks
        missing = [f for f in self.expected_fields if f not in root]
        if missing:
            errors.append(f"Missing required fields: {missing}")
            return False, errors, stats

        # 2. Label Sparsity, Class Distribution, and Per-Batch Checks
        sed_arr = root["sed_labels"]
        if sed_arr.size == 0:
            errors.append("sed_labels is completely empty.")
        else:
            # Labels are small enough to load entirely into RAM safely
            sed_data = sed_arr[:] 
            
            # Assuming shape is (channels, time, class_index)
            time_axis = 1 if sed_data.shape[0] in (1, 4, 5) else 0
            time_len = sed_data.shape[time_axis]
            
            # Global activity calculation
            global_active_mask = np.any(sed_data > 0.0, axis=tuple(i for i in range(sed_data.ndim) if i != time_axis))
            activity_ratio = global_active_mask.sum() / time_len
            stats["activity_ratio"] = activity_ratio
            
            # --- RESTORED GLOBAL ACTIVITY CHECK ---
            if activity_ratio < self.MIN_ACTIVITY_RATIO:
                errors.append(f"Overall activity too low ({activity_ratio*100:.2f}% < {self.MIN_ACTIVITY_RATIO*100:.0f}%).")
            elif activity_ratio > self.MAX_ACTIVITY_RATIO:
                errors.append(f"Overall activity unusually high ({activity_ratio*100:.2f}% > {self.MAX_ACTIVITY_RATIO*100:.0f}%).")

            # --- PER-BATCH EXTREMES CHECK (0% or 100%) ---
            frames_per_batch = const.t_prime * const.batch_size
            num_batches = const.batch_amount
            
            batch_activities = []
            for b in range(num_batches):
                start_idx = b * frames_per_batch
                end_idx = start_idx + frames_per_batch
                
                # Slice the specific batch along the time axis
                if time_axis == 1:
                    batch_data = sed_data[:, start_idx:end_idx, :]
                else:
                    batch_data = sed_data[start_idx:end_idx, ...]
                    
                # Calculate activity for this specific batch
                batch_mask = np.any(batch_data > 0.0, axis=tuple(i for i in range(batch_data.ndim) if i != time_axis))
                actual_frames = batch_data.shape[time_axis]
                
                if actual_frames == 0:
                    batch_activity = 0.0
                else:
                    batch_activity = batch_mask.sum() / actual_frames
                    
                batch_activities.append(batch_activity)
                
                # Evaluate against extremes (0% or 100%)
                if batch_activity <= 0.0:
                    errors.append(f"Batch {b+1} is completely empty (0% activity).")
                elif batch_activity >= 1.0:
                    errors.append(f"Batch {b+1} is completely saturated (100% activity).")

            stats["batch_activities"] = batch_activities

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
            report_lines.append(f"  - Overall Activity: {activity*100:05.2f}%")
            
            if 'batch_activities' in stats:
                batch_strs = [f"B{i+1}:{act*100:02.0f}%" for i, act in enumerate(stats['batch_activities'])]
                report_lines.append(f"  - Batch Activity  : {' | '.join(batch_strs)}")
            
            if 'active_classes' in stats:
                report_lines.append(f"  - Active Classes  : {stats['active_classes']}")

            # Print Errors
            if not is_good:
                for err in errors:
                    report_lines.append(f"  ! ERROR: {err}, file will be deleted.")
                shutil.rmtree(file_path)
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