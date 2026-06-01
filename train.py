from __future__ import annotations

import argparse
import time
from pathlib import Path

import torch

import const

try:
    from train.data import ZarrReader
    from train.model import M2MAST, ModelType
except ModuleNotFoundError as exc:
        raise ModuleNotFoundError(
            "accdoa_torch not found on PYTHONPATH. Install it or add the repo to PYTHONPATH."
    ) from exc


def _count_trials(trial_dir: Path) -> int:
    return sum(1 for path in trial_dir.glob("trial_*.zarr") if path.exists())


def adjust_learning_rate(
    optimizer: torch.optim.Optimizer,
    epoch: int,
    total_epochs: int,
    warmup_epochs: int,
    warmup: bool,
    target_lr: float,
) -> None:
    if warmup and epoch < warmup_epochs:
        new_lr = target_lr * ((epoch + 1) / warmup_epochs)
    else:
        denom = max(total_epochs - warmup_epochs, 1)
        progress = float(epoch - warmup_epochs) / float(denom)
        new_lr = 0.5 * target_lr * (1.0 + torch.cos(torch.tensor(progress * 3.1415926535)))
        new_lr = float(new_lr)

    for group in optimizer.param_groups:
        group["lr"] = new_lr


def compute_f1(pred: torch.Tensor, target: torch.Tensor, threshold: float) -> float:
    binary = (pred > threshold).to(torch.float32)
    tp = (binary * target).sum().item()
    fp = (binary * (1.0 - target)).sum().item()
    fn = ((1.0 - binary) * target).sum().item()

    precision = tp / (tp + fp + 1e-8)
    recall = tp / (tp + fn + 1e-8)
    return 2.0 * (precision * recall) / (precision + recall + 1e-8)


def train_on_zarr(
    model,
    config,
    reader,
    optimizer: torch.optim.Optimizer,
    model_type,
) -> tuple[float, float, float]:
    train_batches = int((config.batch_amount * 4) / 5)
    val_batches = int(config.batch_amount - train_batches)

    total_train_loss = 0.0
    total_val_loss = 0.0
    total_f1 = 0.0

    def fetch_batch():
        valid_mask = [False] * config.batch_size
        if model_type.name == "SED":
            x_in = reader.sed_featureset.batch(valid_mask_out=valid_mask)
            sed_target = reader.sed_labelset.batch(force_silence_mask=valid_mask)
            doa_target = None
        else:
            x_in = reader.doa_featureset.batch(valid_mask_out=valid_mask)
            doa_target = reader.doa_labelset.batch(force_silence_mask=valid_mask)
            sed_target = reader.sed_labelset.batch(force_silence_mask=valid_mask)
        return x_in, sed_target, doa_target

    model.train()
    for _ in range(train_batches):
        x_in, sed_target, doa_target = fetch_batch()
        optimizer.zero_grad(set_to_none=True)
        prediction = model(x_in)
        loss = model.compute_loss(prediction, sed_target, doa_target)
        loss.backward()
        torch.nn.utils.clip_grad_norm_(model.parameters(), 1.0)
        optimizer.step()
        total_train_loss += float(loss.detach().cpu().item())

    model.eval()
    with torch.no_grad():
        for _ in range(val_batches):
            x_in, sed_target, doa_target = fetch_batch()
            prediction = model(x_in)
            val_loss = model.compute_loss(prediction, sed_target, doa_target)
            total_val_loss += float(val_loss.detach().cpu().item())
            if model_type.name == "SED":
                s_target = sed_target.squeeze(1)
                total_f1 += compute_f1(prediction, s_target, config.validation_threshold)

    reader.reset()

    avg_train = total_train_loss / max(train_batches, 1)
    avg_val = total_val_loss / max(val_batches, 1)
    avg_f1 = total_f1 / max(val_batches, 1)
    return avg_train, avg_val, avg_f1


def format_hms(seconds: float) -> str:
    seconds = int(seconds)
    hours = seconds // 3600
    minutes = (seconds % 3600) // 60
    secs = seconds % 60
    return f"{hours:02d}:{minutes:02d}:{secs:02d}"


def run_stage(
    config,
    zarr_dir: Path,
    zarr_amount: int,
    model_type,
    save_path: Path,
    device: torch.device,
    deit_init: bool,
    deit_model: str,
    deit_pretrained: bool,
    M2MAST,
    ZarrReader,
) -> None:
    stage_name = "SED" if model_type.name == "SED" else "DOA"
    print(f"Starting {stage_name} training for {zarr_amount} zarr files.")

    model = M2MAST(config, model_type).to(device)
    if device.type == "cuda":
        model = model.to(memory_format=torch.channels_last)

    warmup = True
    if save_path.exists():
        state = torch.load(save_path, map_location=device)
        model.load_state_dict(state)
        warmup = False
        print(f"Loaded existing model: {save_path}")
    else:
        model.init_weights()
        if deit_init:
            model.load_deit_weights(model_name=deit_model, pretrained=deit_pretrained)

    optimizer = torch.optim.AdamW(
        model.parameters(),
        lr=config.learning_rate,
        weight_decay=config.weight_decay,
    )

    best_val_loss = float("inf")
    total_epoch_seconds = 0.0
    completed_epochs = 0

    for epoch in range(config.epochs):
        epoch_start = time.time()
        adjust_learning_rate(
            optimizer,
            epoch,
            config.epochs,
            config.warmup_epochs,
            warmup,
            config.learning_rate,
        )

        epoch_train_loss = 0.0
        epoch_val_loss = 0.0
        epoch_f1 = 0.0

        for zarr_idx in range(1, zarr_amount + 1):
            zarr_path = zarr_dir / f"trial_{zarr_idx}.zarr"
            if not zarr_path.exists():
                raise FileNotFoundError(f"Missing zarr path: {zarr_path}")

            reader = ZarrReader(zarr_path, config, device)
            t_loss, v_loss, f1_val = train_on_zarr(
                model,
                config,
                reader,
                optimizer,
                model_type,
            )
            epoch_train_loss += t_loss
            epoch_val_loss += v_loss
            epoch_f1 += f1_val

        epoch_train_loss /= max(zarr_amount, 1)
        epoch_val_loss /= max(zarr_amount, 1)

        epoch_seconds = time.time() - epoch_start
        total_epoch_seconds += epoch_seconds
        completed_epochs += 1
        avg_epoch_seconds = total_epoch_seconds / max(completed_epochs, 1)
        remaining_epochs = config.epochs - (epoch + 1)
        eta_seconds = avg_epoch_seconds * max(remaining_epochs, 0)

        f1_pct = (epoch_f1 / max(zarr_amount, 1)) * 100.0
        print(
            f"Epoch {epoch + 1}/{config.epochs}"
            f" | Train: {epoch_train_loss:.6f}"
            f" | Val: {epoch_val_loss:.6f}"
            f" | F1: {f1_pct:.2f}%"
            f" | ETA {format_hms(eta_seconds)}"
        )

        if epoch_val_loss < best_val_loss and epoch_val_loss < config.validation_lowest:
            best_val_loss = epoch_val_loss
            torch.save(model.state_dict(), save_path)
            print(f"--> New best {stage_name} model saved: {save_path}")

    if device.type == "cuda":
        torch.cuda.synchronize()
        torch.cuda.empty_cache()


def main() -> None:
    parser = argparse.ArgumentParser(description="Train ACCDOA M2M-AST model in PyTorch")
    parser.add_argument("--zarr-dir", type=Path, default=const.trial_path)
    parser.add_argument("--zarr-amount", type=int)
    parser.add_argument("--save-sed", type=Path, default=Path("m2m_ast_sed.pt"))
    parser.add_argument("--save-doa", type=Path, default=Path("m2m_ast_doa.pt"))
    parser.add_argument("--device", type=str, default="cuda" if torch.cuda.is_available() else "cpu")
    parser.add_argument("--deit-init", action="store_true")
    parser.add_argument("--deit-model", type=str, default="deit_base_patch16_224")
    parser.add_argument("--deit-no-pretrained", action="store_true")

    args = parser.parse_args()

    config = const

    zarr_dir = args.zarr_dir
    if not zarr_dir.exists():
        raise FileNotFoundError(f"Missing zarr directory: {zarr_dir}")

    zarr_amount = args.zarr_amount if args.zarr_amount else _count_trials(zarr_dir)
    if zarr_amount <= 0:
        raise ValueError("No zarr trials found. Provide --zarr-amount or add trial_*.zarr.")

    device = torch.device(args.device)
    if device.type == "cuda":
        torch.backends.cudnn.benchmark = True

    run_stage(
        config,
        zarr_dir,
        zarr_amount,
        ModelType.SED,
        args.save_sed,
        device,
        args.deit_init,
        args.deit_model,
        not args.deit_no_pretrained,
        M2MAST,
        ZarrReader,
    )
    run_stage(
        config,
        zarr_dir,
        zarr_amount,
        ModelType.DOA,
        args.save_doa,
        device,
        args.deit_init,
        args.deit_model,
        not args.deit_no_pretrained,
        M2MAST,
        ZarrReader,
    )


if __name__ == "__main__":
    main()