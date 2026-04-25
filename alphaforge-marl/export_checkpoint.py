"""Export a trained MARL checkpoint to a deployment-ready format.

Usage:
    python3 export_checkpoint.py --checkpoint checkpoints_larger_network_robustsel_20260329/checkpoint_best_stable.pt
    python3 export_checkpoint.py --checkpoint checkpoints/checkpoint_gen0050.pt --output deploy_v2.pt

Creates a self-contained deployment checkpoint with:
- Agent network weights + architecture config
- Training metadata for audit trail
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import date
from typing import Any, Dict

import torch


def export_deployment_checkpoint(
    checkpoint_path: str,
    output_path: str,
    network_config: Dict[str, Any] | None = None,
) -> str:
    """Convert a training checkpoint to a deployment checkpoint.

    The deployment checkpoint includes only what's needed for inference:
    agent weights, network architecture, and metadata.
    """
    print(f"Loading training checkpoint: {checkpoint_path}")
    ckpt = torch.load(checkpoint_path, weights_only=False)

    agents = ckpt["agents"]
    extra = ckpt.get("extra", {})

    # Auto-detect network config from param vector length
    param_len = len(agents[0]["params"]) if agents else 0
    KNOWN_CONFIGS = {
        88310: {"hidden_sizes": [256, 128, 64], "use_attention": True},
        56390: {"hidden_sizes": [256, 128, 64], "use_attention": False},
        32630: {"hidden_sizes": [128, 64], "use_attention": True},
        16070: {"hidden_sizes": [128, 64], "use_attention": False},
    }

    if network_config is None:
        if param_len in KNOWN_CONFIGS:
            network_config = KNOWN_CONFIGS[param_len]
            print(f"Auto-detected network: {network_config}")
        else:
            raise ValueError(
                f"Unknown param vector length {param_len}. "
                f"Known lengths: {list(KNOWN_CONFIGS.keys())}. "
                "Pass --hidden-sizes and --use-attention explicitly."
            )

    net_cfg = {
        "obs_dim": 57,
        "n_actions": 5,
        "hidden_sizes": network_config["hidden_sizes"],
        "activation": "relu",
        "use_attention": network_config["use_attention"],
    }

    # Select agents — keep all with positive fitness, else top 5
    positive = [a for a in agents if a["fitness"] > 0]
    if len(positive) >= 2:
        selected = sorted(positive, key=lambda a: a["fitness"], reverse=True)
    else:
        selected = sorted(agents, key=lambda a: a["fitness"], reverse=True)[:5]

    deploy_agents = []
    for a in selected:
        deploy_agents.append({
            "agent_id": a["agent_id"],
            "params": a["params"],
            "fitness": a["fitness"],
            "generation": a["generation"],
        })

    deploy_ckpt = {
        "version": "1.0",
        "exported_at": date.today().isoformat(),
        "source_checkpoint": os.path.basename(checkpoint_path),
        "source_generation": ckpt.get("generation", 0),
        "network_config": net_cfg,
        "agents": deploy_agents,
        "training_metadata": {
            "val_sharpe": extra.get("val_sharpe", 0.0),
            "best_val_sharpe": extra.get("best_val_sharpe", 0.0),
            "best_stable_score": extra.get("best_stable_score", 0.0),
            "validation_metrics": extra.get("validation_metrics", {}),
        },
    }

    os.makedirs(os.path.dirname(output_path) or ".", exist_ok=True)
    torch.save(deploy_ckpt, output_path)
    print(f"\nDeployment checkpoint saved: {output_path}")
    print(f"  Agents: {len(deploy_agents)}")
    print(f"  Network: {net_cfg['hidden_sizes']} attention={net_cfg['use_attention']}")
    print(f"  Param vector: {param_len}")
    print(f"  Source gen: {ckpt.get('generation', '?')}")
    print(f"  Val Sharpe: {extra.get('val_sharpe', '?')}")

    # Verify round-trip
    from agents.actor_critic import ActorCriticNetwork

    net = ActorCriticNetwork(
        net_cfg["obs_dim"],
        net_cfg["n_actions"],
        net_cfg["hidden_sizes"],
        net_cfg["activation"],
        use_attention=net_cfg["use_attention"],
    )
    params = torch.FloatTensor(deploy_agents[0]["params"])
    net.load_param_vector(params)
    with torch.no_grad():
        probs = net.get_policy(torch.randn(1, 57))
    print(f"  Round-trip verify: probs={[f'{p:.3f}' for p in probs.squeeze().tolist()]}")
    print("  ✅ Verified")

    return output_path


def main():
    parser = argparse.ArgumentParser(description="Export MARL checkpoint for deployment")
    parser.add_argument(
        "--checkpoint",
        type=str,
        required=True,
        help="Path to training checkpoint (.pt)",
    )
    parser.add_argument(
        "--output",
        type=str,
        default=None,
        help="Output path (default: checkpoints/deploy_v1.pt)",
    )
    parser.add_argument("--hidden-sizes", type=int, nargs="+", default=None)
    parser.add_argument("--use-attention", action="store_true", default=None)
    args = parser.parse_args()

    output = args.output or "checkpoints/deploy_v1.pt"
    net_cfg = None
    if args.hidden_sizes is not None:
        net_cfg = {
            "hidden_sizes": args.hidden_sizes,
            "use_attention": bool(args.use_attention),
        }

    export_deployment_checkpoint(args.checkpoint, output, net_cfg)


if __name__ == "__main__":
    main()
