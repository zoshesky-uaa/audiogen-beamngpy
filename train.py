from __future__ import annotations

import argparse
import math
import time
from pathlib import Path

import torch
import const
from train.augment import Augmenter

try:
    from train.data import ZarrReader
    from train.model import M2MAST, ModelType
except ModuleNotFoundError as exc:
        raise ModuleNotFoundError(
            "accdoa_torch not found on PYTHONPATH. Install it or add the repo to PYTHONPATH."
    ) from exc


def _count_trials(trial_dir: Path) -> int:
    return sum(1 for path in trial_dir.glob("trial_*.zarr") if path.exists())


import atexit
def _cleanup_cuda(device_type: str) -> None:
    """Registered via atexit to ensure VRAM is flushed on script termination."""
    if device_type == "cuda":
        try:
            torch.cuda.synchronize()
            torch.cuda.empty_cache()
            print("\n[Cleanup] CUDA memory successfully cleared.")
        except Exception:
            pass


def save_torchscript(model, config, model_type, save_path: Path) -> None:
    """Serialize the model as a TorchScript module that the C++ inference binary
    (``torch::jit::load`` in ACCDOA-libtorch) can load directly.

    A fresh CPU copy of the network is built and the current weights are copied
    into it, so the live (possibly CUDA / channels_last) model is never moved or
    mutated, and the artifact is device-portable (inference moves it to CUDA on
    its own). Tracing is sufficient because ``M2MAST.forward`` has no
    data-dependent control flow; its only branch depends on ``model_type``, which
    is fixed for the exported instance.
    """
    export_model = M2MAST(config, model_type)
    export_model.load_state_dict(model.state_dict())
    export_model.eval()

    in_chans = int(model_type)  # SED -> 1, DOA -> 5 (enum value doubles as channel count)
    example = torch.zeros(
        1, in_chans, int(config.frame_time_seq), int(config.mel_bins),
        dtype=torch.float32,
    )
    with torch.no_grad():
        scripted = torch.jit.trace(export_model, example, strict=False)
    torch.jit.save(scripted, str(save_path))


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


def compute_f1(
    sed_pred: torch.Tensor, 
    sed_target: torch.Tensor, 
    threshold: float,
    doa_pred: torch.Tensor = None,
    doa_target: torch.Tensor = None
) -> float:
    """
    Computes standard SED F1 or Location-Dependent F20 Score based on available targets.
    Returns: float (the calculated F1 or F20 metric)
    """
    # 1. Binarize SED predictions based on the validation threshold
    sed_binary = (sed_pred > threshold).to(torch.float32)
    
    # 2. If no DOA tensors are provided, compute standard semantic SED F1
    if doa_pred is None or doa_target is None:
        tp = (sed_binary * sed_target).sum().item()
        fp = (sed_binary * (1.0 - sed_target)).sum().item()
        fn = ((1.0 - sed_binary) * sed_target).sum().item()
        
        precision = tp / (tp + fp + 1e-8)
        recall = tp / (tp + fn + 1e-8)
        return 2.0 * (precision * recall) / (precision + recall + 1e-8)

    # 3. If DOA tensors are provided, compute Location-Dependent F20 Score
    batch_size, time_steps, _ = doa_pred.shape
    
    # Reshape flattened Cartesian coordinates: [B, T, Classes*2] -> [B, T, Classes, 2]
    p_cart = doa_pred.view(batch_size, time_steps, -1, 2)
    g_cart = doa_target.view(batch_size, time_steps, -1, 2)
    
    # Normalize vectors to unit length for accurate angular math (predictions aren't spatially perfect)
    p_norm = torch.nn.functional.normalize(p_cart, p=2, dim=-1)
    g_norm = torch.nn.functional.normalize(g_cart, p=2, dim=-1)
    
    # Dot product along the spatial coordinate dimensions (X, Y)
    dot_product = (p_norm * g_norm).sum(dim=-1)
    
    # Clamp to safely handle floating-point drift out of arccos bounds
    dot_product = torch.clamp(dot_product, -1.0 + 1e-7, 1.0 - 1e-7)
    
    # Calculate angular error in degrees
    angular_dist = torch.acos(dot_product) * (180.0 / math.pi)
    
    # Spatial tolerance gate: 1.0 if within 20 degrees, else 0.0  (F20 threshold)
    spatial_mask = (angular_dist <= 20.0).to(torch.float32)
    
    # Location-Dependent True Positives: Event detected AND active in ground truth AND spatial error <= 20°
    f20_tp = (sed_binary * sed_target * spatial_mask).sum().item()
    
    # Location-Dependent False Positives: Predicted event, but it didn't exist OR was outside the 20° boundary
    f20_fp = (sed_binary * (1.0 - (sed_target * spatial_mask))).sum().item()
    
    # Location-Dependent False Negatives: True event existed, but was missed OR predicted outside the 20° boundary
    f20_fn = (sed_target * (1.0 - (sed_binary * spatial_mask))).sum().item()
    
    f20_precision = f20_tp / (f20_tp + f20_fp + 1e-8)
    f20_recall = f20_tp / (f20_tp + f20_fn + 1e-8)
    
    return 2.0 * (f20_precision * f20_recall) / (f20_precision + f20_recall + 1e-8)


def train_on_zarr(
    model,
    config,
    reader,
    optimizer: torch.optim.Optimizer,
    model_type,
    augmenter: Augmenter = None
) -> tuple[float, float, float]:
    train_batches = int((config.batch_amount * 4) / 5)
    val_batches = int(config.batch_amount - train_batches)

    total_train_loss = 0.0
    total_val_loss = 0.0
    total_f1 = 0.0

    def fetch_batch(is_val: bool = False):
        valid_mask = [False] * config.batch_size
        apply_aug = not is_val
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
        x_in, sed_target, doa_target = augmenter(x_in, sed_target, doa_target)
        
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
            x_in, sed_target, doa_target = fetch_batch(is_val=True)
            prediction = model(x_in)
            val_loss = model.compute_loss(prediction, sed_target, doa_target)
            total_val_loss += float(val_loss.detach().cpu().item())
            if model_type.name == "SED":
                s_target = sed_target.squeeze(1)
                total_f1 += compute_f1(prediction, s_target, config.validation_threshold)
            else: 
                s_target = sed_target.squeeze(1)
                ground_sed_pred = s_target.clone()
                d_target = doa_target.squeeze(1)
                total_f1 += compute_f1(ground_sed_pred, s_target, config.validation_threshold, prediction, d_target)

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

import torch.distributions as dist
def apply_mixup_and_noise(
    x: torch.Tensor, 
    sed_target: torch.Tensor, 
    doa_target: torch.Tensor = None, 
    alpha: float = 0.2, 
    noise_std: float = 0.05
):
    batch_size = x.size(0)
    
    # 1. Noise Injection (Keep this: great for blurring synthetic sharpness)
    if noise_std > 0:
        x = x + torch.randn_like(x) * noise_std
    
    # 2. MixUp Block
    if alpha > 0:
        beta = dist.Beta(alpha, alpha)
        lam = beta.sample().item()
        index = torch.randperm(batch_size, device=x.device)
        
        # Always mix features and SED targets
        x_mixed = lam * x + (1 - lam) * x[index]
        sed_mixed = lam * sed_target + (1 - lam) * sed_target[index]
        
        # IF DOA training, do NOT linearly blend the coordinates.
        # Keep the dominant target's coordinates based on lambda.
        if doa_target is not None:
            doa_mixed = doa_target if lam >= 0.5 else doa_target[index]
        else:
            doa_mixed = None
            
        return x_mixed, sed_mixed, doa_mixed
        
    return x, sed_target, doa_target

def run_stage(
    config,
    zarr_dir: Path,
    zarr_amount: int,
    save_path: Path,
    device: torch.device,
    deit_init: bool,
    deit_model: str,
    model_type: str,
    M2MAST,
    ZarrReader,
) -> None:
    atexit.register(_cleanup_cuda, device.type)
    stage_name = "SED" if model_type == "SED" else "DOA"
    model_type = ModelType.SED if model_type == "SED" else ModelType.DOA
    print(f"Starting {stage_name} training for {zarr_amount} zarr files.")

    model = M2MAST(config, model_type).to(device)
    if device.type == "cuda":
        model = model.to(memory_format=torch.channels_last)

    warmup = True
    if save_path.exists():
        # Checkpoints are TorchScript modules; read the weights back out for resuming.
        scripted = torch.jit.load(str(save_path), map_location=device)
        model.load_state_dict(scripted.state_dict())
        warmup = False
        print(f"Resumed existing model (TorchScript): {save_path}")
    elif deit_init:
        model.load_deit_weights(model_name=deit_model)
        print(f"Initialized with pre-trained weights from {deit_model}")
    else:
        model.init_weights()
        print("Initialized new model weights.")

    optimizer = torch.optim.AdamW(
        model.parameters(),
        lr=config.learning_rate,
        weight_decay=config.weight_decay,
    )

    augmenter = Augmenter(config).to(device)

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
                augmenter
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
            save_torchscript(model, config, model_type, save_path)
            print(f"--> New best {stage_name} model saved (TorchScript): {save_path}")

def main() -> None:
    parser = argparse.ArgumentParser(description="Train ACCDOA M2M-AST model in PyTorch")
    parser.add_argument("--model-type", type=str, default="SED", choices=["SED", "DOA"])
    parser.add_argument("--zarr-dir", type=Path, default=const.trial_path)
    parser.add_argument("--zarr-amount", type=int)
    parser.add_argument("--save-sed", type=Path, default=Path("m2m_ast_sed.script.pt"))
    parser.add_argument("--save-doa", type=Path, default=Path("m2m_ast_doa.script.pt"))
    parser.add_argument("--device", type=str, default="cuda" if torch.cuda.is_available() else "cpu")
    parser.add_argument("--deit-init", action="store_true")
    parser.add_argument("--deit-model", type=str, default="deit_base_distilled_patch16_224")

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
        args.save_sed if args.model_type == "SED" else args.save_doa,
        device,
        args.deit_init,
        args.deit_model,
        args.model_type,
        M2MAST,
        ZarrReader,
    )

if __name__ == "__main__":
    main()