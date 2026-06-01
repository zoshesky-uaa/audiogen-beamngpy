from __future__ import annotations

import sys
from pathlib import Path
from typing import Dict, List, Tuple

import numpy as np
import z5py
from concurrent.futures import ProcessPoolExecutor, as_completed

# Adjust this to match your specific repository structure
root_dir = Path(__file__).resolve().parent.parent
sys.path.append(str(root_dir))

import const


class ZarrFeatureValidator:
    """Scans and validates Zarr feature datasets for audio data presence."""

    VAR_EPS = 1e-6
    LOG_MEL_MIN = -7.0
    LOG_MEL_EPS = 1e-3
    IV_MIN = -1.0
    IV_MAX = 1.0
    IV_EPS = 1e-3

    def __init__(self, trials_dir: Path | str) -> None:
        self.trials_dir = Path(trials_dir)
        self.zarr_files = sorted(self.trials_dir.glob("*.zarr"))

        self.feature_fields = ["sed_features", "doa_features"]

    def _time_axis(self, data: np.ndarray) -> int:
        # Features are expected to be (channels, time, freq), but be defensive.
        return 1 if data.shape[0] in (1, 4, 5) else 0

    def _frame_variance(self, data: np.ndarray, time_axis: int) -> np.ndarray:
        return np.var(
            data,
            axis=tuple(i for i in range(data.ndim) if i != time_axis),
            dtype=np.float32,
        )

    def _batch_variance(self, data: np.ndarray, time_axis: int) -> List[float]:
        frames_per_batch = const.frame_time_seq * const.batch_size
        num_batches = const.batch_amount
        batch_variances: List[float] = []

        for b in range(num_batches):
            start_idx = b * frames_per_batch
            end_idx = start_idx + frames_per_batch
            if time_axis == 1:
                batch_data = data[:, start_idx:end_idx, :]
            else:
                batch_data = data[start_idx:end_idx, ...]

            actual_frames = batch_data.shape[time_axis]
            if actual_frames == 0:
                batch_variances.append(0.0)
                continue

            frame_var = self._frame_variance(batch_data, time_axis)
            batch_variances.append(float(np.mean(frame_var)))

        return batch_variances

    def validate_file(self, zarr_path: Path) -> Tuple[bool, List[str], Dict]:
        root = z5py.File(zarr_path, use_zarr_format=True)
        errors: List[str] = []
        stats: Dict[str, Dict] = {}

        for field in self.feature_fields:
            if field not in root:
                errors.append(f"Missing required field: {field}")
                continue

            arr = root[field]
            if arr.size == 0:
                errors.append(f"{field} is completely empty.")
                continue

            data = arr[:]
            time_axis = self._time_axis(data)
            frame_var = self._frame_variance(data, time_axis)
            overall_variance = float(np.mean(frame_var))
            batch_variances = self._batch_variance(data, time_axis)

            if not np.isfinite(data).all():
                errors.append(f"{field} contains NaN or Inf values.")

            stats[field] = {
                "overall_variance": overall_variance,
                "batch_variances": batch_variances,
            }

            if overall_variance <= self.VAR_EPS:
                errors.append(f"{field} variance is too low across the trial.")
            for b, var in enumerate(batch_variances, 1):
                if var <= self.VAR_EPS:
                    errors.append(f"{field} batch {b} variance is too low.")

            if data.ndim == 3 and data.shape[0] >= 1:
                channel_mins = data.min(axis=(1, 2))
                channel_maxs = data.max(axis=(1, 2))
                stats[field]["channel_mins"] = [float(v) for v in channel_mins]
                stats[field]["channel_maxs"] = [float(v) for v in channel_maxs]

                if field == "sed_features":
                    if channel_mins[0] < self.LOG_MEL_MIN - self.LOG_MEL_EPS:
                        errors.append(
                            f"{field} log-mel min below theoretical floor: {channel_mins[0]:.3f}."
                        )
                elif field == "doa_features" and data.shape[0] >= 5:
                    for ch_idx in range(3):
                        if channel_mins[ch_idx] < self.LOG_MEL_MIN - self.LOG_MEL_EPS:
                            errors.append(
                                f"{field} log-mel ch{ch_idx} min below theoretical floor: {channel_mins[ch_idx]:.3f}."
                            )
                    for ch_idx in (3, 4):
                        if channel_mins[ch_idx] < self.IV_MIN - self.IV_EPS:
                            errors.append(
                                f"{field} intensity ch{ch_idx} below -1: {channel_mins[ch_idx]:.3f}."
                            )
                        if channel_maxs[ch_idx] > self.IV_MAX + self.IV_EPS:
                            errors.append(
                                f"{field} intensity ch{ch_idx} above 1: {channel_maxs[ch_idx]:.3f}."
                            )

        is_good = len(errors) == 0
        return is_good, errors, stats

    def run_batch_validation(self, output_file: Path | None = None) -> None:
        if not self.zarr_files:
            print(f"No .zarr files found in {self.trials_dir}")
            return

        report_lines: List[str] = []
        report_lines.append("=" * 60)
        report_lines.append(" ZARR FEATURE DATA VALIDATION REPORT")
        report_lines.append("=" * 60)
        report_lines.append(f"Directory: {self.trials_dir}")
        report_lines.append(f"Files Found: {len(self.zarr_files)}\n")

        passed_count = 0

        with ProcessPoolExecutor() as executor:
            futures = {
                executor.submit(self.validate_file, file_path): file_path
                for file_path in self.zarr_files
            }
            for idx, future in enumerate(as_completed(futures), 1):
                file_path = futures[future]
                is_good, errors, stats = future.result()
                status_tag = "[PASS]" if is_good else "[FAIL]"

                report_lines.append(
                    f"[{idx}/{len(self.zarr_files)}] {file_path.name} ".ljust(50, ".")
                    + f" {status_tag}"
                )

                for field in self.feature_fields:
                    if field not in stats:
                        continue
                    overall_var = stats[field].get("overall_variance", 0.0)
                    report_lines.append(
                        f"  - {field} Overall Variance: {overall_var:.6e}"
                    )
                    batch_variances = stats[field].get("batch_variances", [])
                    if batch_variances:
                        batch_strs = [
                            f"B{i + 1}:{var:.2e}"
                            for i, var in enumerate(batch_variances)
                        ]
                        report_lines.append(
                            f"  - {field} Batch Variance : {' | '.join(batch_strs)}"
                        )
                    channel_mins = stats[field].get("channel_mins", [])
                    channel_maxs = stats[field].get("channel_maxs", [])
                    if channel_mins and channel_maxs:
                        min_strs = [f"C{i}:{v:.3f}" for i, v in enumerate(channel_mins)]
                        max_strs = [f"C{i}:{v:.3f}" for i, v in enumerate(channel_maxs)]
                        report_lines.append(
                            f"  - {field} Channel Mins  : {' | '.join(min_strs)}"
                        )
                        report_lines.append(
                            f"  - {field} Channel Maxs  : {' | '.join(max_strs)}"
                        )

                if not is_good:
                    for err in errors:
                        report_lines.append(f"  ! ERROR: {err}")
                else:
                    passed_count += 1

                report_lines.append("")

        report_lines.append("=" * 60)
        report_lines.append(
            f" SUMMARY: {passed_count}/{len(self.zarr_files)} files PASSED validation."
        )
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
    output_path = repo_root / "tools" / "feature_validation_report.txt"

    validator = ZarrFeatureValidator(trials_dir)
    validator.run_batch_validation(output_file=output_path)


if __name__ == "__main__":
    main()
