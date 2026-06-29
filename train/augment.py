import torch
import torch.nn as nn
import torch.distributions as dist

class Augmenter(nn.Module):
    def __init__(self, config):
        super().__init__()
        self.alpha = config.mixup_alpha
        self.noise_std = config.noise_std
        self.f_mask = 48  # AST Baseline
        self.t_mask = 56  # AST Baseline
        self.spec_prob = 0.4
        self.rot_prob = 0.5
        self.silence = -7.0

    def forward(self, x, sed_target, doa_target=None):
        batch_size = x.shape[0]
        device = x.device

        # ==========================================
        # 1. NOISE INJECTION
        # ==========================================
        if self.noise_std > 0:
            x = x + torch.randn_like(x) * self.noise_std

        # ==========================================
        # 2. MIXUP (SED)
        # ==========================================
        if self.alpha > 0:
            lam = dist.Beta(self.alpha, self.alpha).sample().item()
            index = torch.randperm(batch_size, device=device)
            
            x = lam * x + (1 - lam) * x[index]
            sed_target = lam * sed_target + (1 - lam) * sed_target[index]
            
        # ==========================================
        # 3. SPATIAL MIXUP & ROTATION (DOA ONLY)
        # ==========================================
        if doa_target is not None:
                neg_x = (torch.rand((batch_size, 1, 1, 1), device=device) < self.rot_prob)
                neg_y = (torch.rand((batch_size, 1, 1, 1), device=device) < self.rot_prob)
                swap  = (torch.rand((batch_size, 1, 1, 1), device=device) < self.rot_prob)

                # Feature channels: [0:W logmel, 1:X logmel, 2:Y logmel, 3:IV_x, 4:IV_y]

                # A. Directional loudness on the X/Y power channels. These hold 0.5*log10(power),
                #    so a loudness scale by g is an ADDITIVE offset of 0.5*log10(g). A multiply
                #    here lifts the -7 silence floor instead of attenuating. Note this perturbs
                #    only the power channels; a physically exact directional loudness would also
                #    rescale W and re-derive the intensity vectors, so treat this as a light cap.
                g_x = torch.empty((batch_size, 1, 1, 1), device=device).uniform_(0.7, 1.0)
                g_y = torch.empty((batch_size, 1, 1, 1), device=device).uniform_(0.7, 1.0)
                x[:, 1:2] += 0.5 * torch.log10(g_x)
                x[:, 2:3] += 0.5 * torch.log10(g_y)

                # B. Negate the intensity channels FIRST (power channels are magnitudes, never negated).
                x[:, 3:4] = torch.where(neg_x, -x[:, 3:4], x[:, 3:4])
                x[:, 4:5] = torch.where(neg_y, -x[:, 4:5], x[:, 4:5])

                # C. THEN swap X<->Y on the power channels and the (now negated) intensity channels.
                #    Clone after negation so the sign survives the swap.
                p_x, p_y = x[:, 1:2].clone(), x[:, 2:3].clone()
                x[:, 1:2] = torch.where(swap, p_y, x[:, 1:2])
                x[:, 2:3] = torch.where(swap, p_x, x[:, 2:3])

                i_x, i_y = x[:, 3:4].clone(), x[:, 4:5].clone()
                x[:, 3:4] = torch.where(swap, i_y, x[:, 3:4])
                x[:, 4:5] = torch.where(swap, i_x, x[:, 4:5])

                # Targets: last dim is interleaved (x, y) per class/track -> 0::2 = x, 1::2 = y.
                # Negate first ...
                doa_target[:, :, :, 0::2] = torch.where(neg_x, -doa_target[:, :, :, 0::2], doa_target[:, :, :, 0::2])
                doa_target[:, :, :, 1::2] = torch.where(neg_y, -doa_target[:, :, :, 1::2], doa_target[:, :, :, 1::2])
                # ... then swap, on the post-negation values.
                tx = doa_target[:, :, :, 0::2].clone()
                ty = doa_target[:, :, :, 1::2].clone()
                doa_target[:, :, :, 0::2] = torch.where(swap, ty, tx)
                doa_target[:, :, :, 1::2] = torch.where(swap, tx, ty)

        # ==========================================
        # 4. SPECAUGMENT (Per-Channel)
        # ==========================================
        _, num_channels, time_steps, freq_bins = x.shape
        
        # Freq Masking
        f_apply = (torch.rand((batch_size, num_channels, 1, 1), device=device) < self.spec_prob)
        f_widths = torch.randint(1, self.f_mask, (batch_size, num_channels, 1, 1), device=device)
        f_starts = (torch.rand((batch_size, num_channels, 1, 1), device=device) * (freq_bins - f_widths)).long()
        f_grid = torch.arange(freq_bins, device=device).view(1, 1, 1, freq_bins)
        
        f_mask = (f_grid >= f_starts) & (f_grid < f_starts + f_widths) & f_apply
        x = torch.where(f_mask, torch.tensor(self.silence, device=device), x)

        # Time Masking
        t_apply = (torch.rand((batch_size, num_channels, 1, 1), device=device) < self.spec_prob)
        t_widths = torch.randint(1, self.t_mask, (batch_size, num_channels, 1, 1), device=device)
        t_starts = (torch.rand((batch_size, num_channels, 1, 1), device=device) * (time_steps - t_widths)).long()
        t_grid = torch.arange(time_steps, device=device).view(1, 1, time_steps, 1)
        
        t_mask = (t_grid >= t_starts) & (t_grid < t_starts + t_widths) & t_apply
        x = torch.where(t_mask, torch.tensor(self.silence, device=device), x)

        return x, sed_target, doa_target