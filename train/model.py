from __future__ import annotations

import math
from enum import IntEnum
from typing import Optional

import torch
import torch.nn as nn
import torch.nn.functional as F

from .config import Config


class ModelType(IntEnum):
    SED = 1
    DOA = 5


class PatchEmbedding(nn.Module):
    def __init__(self, config: Config, in_chans: int) -> None:
        super().__init__()
        self.norm = nn.BatchNorm2d(in_chans)
        self.proj = nn.Conv2d(
            in_chans,
            config.embed_dim,
            kernel_size=config.patch_size,
            stride=config.conv_stride,
        )

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        x = self.norm(x)
        x = self.proj(x)
        return x.flatten(2).transpose(1, 2)


class M2MAST(nn.Module):
    def __init__(self, config: Config, model_type: ModelType) -> None:
        super().__init__()
        self.config = config
        self.model_type = model_type
        self.in_chans = int(model_type)

        self.patch_embed = PatchEmbedding(config, self.in_chans)
        self.cls_tokens = nn.Parameter(torch.randn(1, config.t_prime, config.embed_dim))
        self.pos_embed = nn.Parameter(torch.randn(1, config.total_seq, config.embed_dim))

        encoder_layer = nn.TransformerEncoderLayer(
            d_model=config.embed_dim,
            nhead=config.att_headers,
            dim_feedforward=config.embed_dim * 4,
            dropout=config.dropout,
            activation="gelu",
            batch_first=True,
            norm_first=True,
        )
        self.encoder = nn.TransformerEncoder(
            encoder_layer,
            num_layers=config.enc_layers,
            norm=nn.LayerNorm(config.embed_dim),
        )

        if model_type == ModelType.SED:
            out_dim = config.se_count * config.track_count
        else:
            out_dim = config.se_count * config.track_count * 2
        self.head = nn.Linear(config.embed_dim, out_dim)

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        batch_size = x.size(0)
        patches = self.patch_embed(x)
        cls_tokens = self.cls_tokens.expand(batch_size, -1, -1)
        x = torch.cat((cls_tokens, patches), dim=1)
        x = x + self.pos_embed
        x = self.encoder(x)
        tokens = x[:, : self.config.t_prime, :]
        logits = self.head(tokens)
        if self.model_type == ModelType.SED:
            return torch.sigmoid(logits)
        return torch.tanh(logits)

    def compute_loss(
        self,
        prediction: torch.Tensor,
        sed_target: torch.Tensor,
        doa_target: Optional[torch.Tensor],
    ) -> torch.Tensor:
        s_target = sed_target.squeeze(1).clamp(0.05, 0.95)
        if self.model_type == ModelType.SED:
            return F.binary_cross_entropy(prediction, s_target)

        if doa_target is None:
            raise ValueError("DOA target required for DOA loss.")

        d_target = doa_target.squeeze(1)
        active_mask = (s_target > 0.5).to(torch.float32)
        active_mask = active_mask.repeat_interleave(2, dim=-1)
        raw_mse = F.mse_loss(prediction, d_target, reduction="none")
        return (raw_mse * active_mask).sum() / (active_mask.sum() + 1e-8)

    @torch.no_grad()
    def init_weights(self) -> None:
        nn.init.normal_(self.cls_tokens, mean=0.0, std=0.02)
        self.cls_tokens.clamp_(-0.04, 0.04)
        nn.init.normal_(self.pos_embed, mean=0.0, std=0.02)
        self.pos_embed.clamp_(-0.04, 0.04)

        nn.init.normal_(self.head.weight, mean=0.0, std=0.02)
        self.head.weight.clamp_(-0.04, 0.04)
        nn.init.constant_(self.head.bias, 0.0)

        for module in self.encoder.modules():
            if isinstance(module, nn.Linear):
                nn.init.normal_(module.weight, mean=0.0, std=0.02)
                module.weight.clamp_(-0.04, 0.04)
                if module.bias is not None:
                    nn.init.constant_(module.bias, 0.0)
            elif isinstance(module, nn.LayerNorm):
                if module.weight is not None:
                    nn.init.constant_(module.weight, 1.0)
                if module.bias is not None:
                    nn.init.constant_(module.bias, 0.0)
            elif isinstance(module, nn.MultiheadAttention):
                if module.in_proj_weight is not None:
                    nn.init.normal_(module.in_proj_weight, mean=0.0, std=0.02)
                    module.in_proj_weight.clamp_(-0.04, 0.04)
                if module.in_proj_bias is not None:
                    nn.init.constant_(module.in_proj_bias, 0.0)

    @torch.no_grad()
    def load_deit_weights(
        self,
        model_name: str = "deit_base_patch16_224",
        pretrained: bool = True,
    ) -> None:
        try:
            import timm
        except ModuleNotFoundError as exc:
            raise ModuleNotFoundError(
                "Install timm to load DeiT weights: pip install timm"
            ) from exc

        deit = timm.create_model(model_name, pretrained=pretrained)
        deit.eval()

        patch_weight = deit.patch_embed.proj.weight
        patch_weight = self._adapt_input_weight(patch_weight, self.in_chans)
        self.patch_embed.proj.weight.copy_(patch_weight.to(self.patch_embed.proj.weight))
        if deit.patch_embed.proj.bias is not None:
            self.patch_embed.proj.bias.copy_(deit.patch_embed.proj.bias.to(self.patch_embed.proj.bias))

        for layer_idx, layer in enumerate(self.encoder.layers):
            block = deit.blocks[layer_idx]
            layer.self_attn.in_proj_weight.copy_(block.attn.qkv.weight.to(layer.self_attn.in_proj_weight))
            if block.attn.qkv.bias is not None:
                layer.self_attn.in_proj_bias.copy_(block.attn.qkv.bias.to(layer.self_attn.in_proj_bias))
            layer.self_attn.out_proj.weight.copy_(block.attn.proj.weight.to(layer.self_attn.out_proj.weight))
            if block.attn.proj.bias is not None:
                layer.self_attn.out_proj.bias.copy_(block.attn.proj.bias.to(layer.self_attn.out_proj.bias))

            layer.linear1.weight.copy_(block.mlp.fc1.weight.to(layer.linear1.weight))
            layer.linear1.bias.copy_(block.mlp.fc1.bias.to(layer.linear1.bias))
            layer.linear2.weight.copy_(block.mlp.fc2.weight.to(layer.linear2.weight))
            layer.linear2.bias.copy_(block.mlp.fc2.bias.to(layer.linear2.bias))

            layer.norm1.weight.copy_(block.norm1.weight.to(layer.norm1.weight))
            layer.norm1.bias.copy_(block.norm1.bias.to(layer.norm1.bias))
            layer.norm2.weight.copy_(block.norm2.weight.to(layer.norm2.weight))
            layer.norm2.bias.copy_(block.norm2.bias.to(layer.norm2.bias))

        if self.encoder.norm is not None:
            self.encoder.norm.weight.copy_(deit.norm.weight.to(self.encoder.norm.weight))
            self.encoder.norm.bias.copy_(deit.norm.bias.to(self.encoder.norm.bias))

        cls_token = deit.cls_token.to(self.cls_tokens)
        self.cls_tokens.copy_(cls_token.expand(1, self.config.t_prime, -1))

        cls_pos, patch_pos = self._resize_pos_embed(deit.pos_embed)
        pos_embed = torch.zeros_like(self.pos_embed)
        pos_embed[:, : self.config.t_prime, :] = cls_pos.expand(
            1, self.config.t_prime, cls_pos.size(-1)
        )
        pos_embed[:, self.config.t_prime :, :] = patch_pos
        self.pos_embed.copy_(pos_embed)


    @staticmethod
    def _adapt_input_weight(weight: torch.Tensor, in_chans: int) -> torch.Tensor:
        if weight.size(1) == in_chans:
            return weight
        if in_chans == 1:
            return weight.mean(dim=1, keepdim=True)
        base = weight.mean(dim=1, keepdim=True)
        return base.repeat(1, in_chans, 1, 1)

    def _resize_pos_embed(self, posemb: torch.Tensor) -> tuple[torch.Tensor, torch.Tensor]:
        pos_embed = posemb.to(self.pos_embed)
        cls_pos = pos_embed[:, 0:1]
        pos_tokens = pos_embed[:, 1:]
        grid_old = int(math.sqrt(pos_tokens.size(1)))
        if grid_old * grid_old != pos_tokens.size(1):
            raise ValueError("Unexpected DeiT pos_embed shape.")

        pos_tokens = pos_tokens.reshape(1, grid_old, grid_old, -1).permute(0, 3, 1, 2)
        pos_tokens = F.interpolate(
            pos_tokens,
            size=self.config.patch_grid(),
            mode="bicubic",
            align_corners=False,
        )
        pos_tokens = pos_tokens.permute(0, 2, 3, 1).reshape(1, -1, pos_tokens.size(1))
        return cls_pos, pos_tokens
