"""AlphaForge signal scanner — cross-sectional signal scan + classification."""

from .scanner import scan_universe, SignalRow, TickerScore, compute_factor_scores
from .classifier import classify_signal
