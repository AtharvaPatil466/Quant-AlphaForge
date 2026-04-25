"""
Signal classification — LONG / SHORT / NEUTRAL.
"""

from __future__ import annotations


def classify_signal(composite_z: float, threshold: float = 0.8) -> str:
    """Classify a composite z-score into a trading signal.

    Args:
        composite_z: cross-sectional z-score (not the scaled ±100 composite)
        threshold: z-score cutoff for LONG/SHORT (default 0.8)

    Returns:
        'LONG', 'SHORT', or 'NEUTRAL'
    """
    if composite_z > threshold:
        return "LONG"
    elif composite_z < -threshold:
        return "SHORT"
    return "NEUTRAL"


def classify_signal_js(composite_scaled: float) -> str:
    """JS-compatible classification using the ±100 scaled composite.

    JS logic: composite > 40 → LONG, < -40 → SHORT, else NEUTRAL.
    """
    if composite_scaled > 40:
        return "LONG"
    elif composite_scaled < -40:
        return "SHORT"
    return "NEUTRAL"
