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
            B, Chunks, Tracks, Coords = doa_target.shape
            neg_x = (torch.rand((batch_size, 1, 1, 1), device=device) < self.rot_prob)
            neg_y = (torch.rand((batch_size, 1, 1, 1), device=device) < self.rot_prob)
            swap  = (torch.rand((batch_size, 1, 1, 1), device=device) < self.rot_prob)

            # A. Directional Loudness (Scaling X, Y Power Only: Channels 1, 2)
            # Scaling intensity (3, 4) is not physically required for soft caps
            x[:, 1:2] *= torch.empty((batch_size, 1, 1, 1), device=device).uniform_(0.7, 1.0)
            x[:, 2:3] *= torch.empty((batch_size, 1, 1, 1), device=device).uniform_(0.7, 1.0)

            # B. Rotation (Negate & Swap ONLY Intensity Channels 3 and 4)
            # Power Channels (1, 2) Swap only, never negate!
            x[:, 1:3] = torch.where(swap, x[:, 2:4], x[:, 1:3]) 
            
            # Corrected Swap Logic for Power (Ch 1, 2) and Intensity (Ch 3, 4)
            p_x, p_y = x[:, 1:2].clone(), x[:, 2:3].clone()
            x[:, 1:2] = torch.where(swap, p_y, x[:, 1:2])
            x[:, 2:3] = torch.where(swap, p_x, x[:, 2:3])

            i_x, i_y = x[:, 3:4].clone(), x[:, 4:5].clone()
            x[:, 3:4] = torch.where(neg_x, -x[:, 3:4], x[:, 3:4]) # Negate X-IV
            x[:, 4:5] = torch.where(neg_y, -x[:, 4:5], x[:, 4:5]) # Negate Y-IV
            
            x[:, 3:4] = torch.where(swap, i_y, x[:, 3:4])
            x[:, 4:5] = torch.where(swap, i_x, x[:, 4:5])

            # 3. Rotate Ground Truth Targets [Batch, 1, Tracks*2]
            m_neg_x = neg_x.view(B, 1, 1, 1)
            m_neg_y = neg_y.view(B, 1, 1, 1)
            m_swap  = swap.view(B, 1, 1, 1)

            # 3. Expand to match [B, Chunks, Tracks, Coords]
            m_neg_x = m_neg_x.expand(B, Chunks, Tracks, Coords)
            m_neg_y = m_neg_y.expand(B, Chunks, Tracks, Coords)
            m_swap  = m_swap.expand(B, Chunks, Tracks, Coords)

            # Apply Negation (using the [Batch, 1, 1, 1] masks directly)
            doa_target[:, :, :, 0::2] = torch.where(neg_x, -doa_target[:, :, :, 0::2], doa_target[:, :, :, 0::2])
            doa_target[:, :, :, 1::2] = torch.where(neg_y, -doa_target[:, :, :, 1::2], doa_target[:, :, :, 1::2])

            # Apply Swap
            # Extract the halves (size [24, Chunks, Tracks, 9])
            tx = doa_target[:, :, :, 0::2].clone()
            ty = doa_target[:, :, :, 1::2].clone()
            
            # Here, 'swap' is [24, 1, 1, 1], which broadcasts perfectly to [24, Chunks, Tracks, 9]
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