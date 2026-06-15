"""Version + source-hash pinning for the canonical gauntlet.

A verdict records ``afgauntlet.source_hash()`` so any reviewer can confirm
*exactly* which evaluation code produced it. Changing any core module changes
the hash, which by convention invalidates a frozen pre-commit anchor — the
same discipline the VIX substrate already applies to its design doc.
"""
from __future__ import annotations

import hashlib
import pathlib

__version__ = "1.0.0"

# Core modules whose contents define the statistical behaviour of the gauntlet.
# version.py and __init__.py are deliberately excluded so re-exports / version
# bumps do not churn the statistical hash.
_HASHED_MODULES = (
    "sharpe.py",
    "deflated.py",
    "bootstrap.py",
    "multiple_testing.py",
    "cross_val.py",
    "gates.py",
)


def source_hash() -> str:
    """SHA-256 over the concatenated source of the core modules, in fixed
    order. Deterministic and import-environment independent."""
    here = pathlib.Path(__file__).resolve().parent
    h = hashlib.sha256()
    for name in _HASHED_MODULES:
        h.update(name.encode("utf-8"))
        h.update(b"\0")
        h.update((here / name).read_bytes())
        h.update(b"\0")
    return h.hexdigest()
