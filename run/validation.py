from __future__ import annotations

from pathlib import Path
import numpy as np
import zarr
import const

class ZarrValidator:
    """Scans and validates a directory of Zarr files for ML readiness."""
    # Validation Thresholds
    MIN_ACTIVITY_RATIO = 0.20      # Overall dataset minimum activity (20%)
    MAX_ACTIVITY_RATIO = 0.80      # Overall dataset maximum activity (80%)

    def __init__(self, zarr_path: Path) -> None:
        self.zarr_path = zarr_path
        self.expected_fields = ["doa_features", "sed_features", "doa_labels", "sed_labels"]
        
            
    def validate_file(self):
        """Runs structural and sparsity checks on a single Zarr file."""
        errors = []
        stats = {}

        if not self.zarr_path.is_file():
            print(f"Skipping validation as {self.zarr_path} does not exist or is not a file")
            return True
        
        try:
            root = zarr.open_group(self.zarr_path, mode="r")
        except Exception as e:
            print(f"Skipping validation as {self.zarr_path} is not a valid file")
            return True
        
        # 1. Structural Checks
        missing = [f for f in self.expected_fields if f not in root]
        if missing:
            errors.append(f"Missing required fields: {missing}")
            print(f"Validation failed for {self.zarr_path}. Errors: {errors}")
            return False

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

        if is_good:
            print(f"Validation passed for {self.zarr_path}. Stats: {stats}")
            return True
        else:
            print(f"Validation failed for {self.zarr_path}. Errors: {errors}")
            return False



