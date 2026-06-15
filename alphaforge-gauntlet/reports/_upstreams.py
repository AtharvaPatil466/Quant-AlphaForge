"""Load the historical per-substrate DSR implementations for comparison.

Two load strategies:
  * modules that only import numpy/pandas at top level (VIX, crypto, India) are
    loaded whole via importlib;
  * modules with package-relative imports (PEAD's run_phase1) can't be imported
    standalone, so we AST-extract the single self-contained DSR function from
    the real source bytes and exec it in a minimal namespace.

Either way we run the *actual published code*, not a transcription.
"""
from __future__ import annotations

import ast
import importlib.util
import math
import os
import sys

import numpy as np
import pandas as pd

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def load_module(rel_path: str, name: str):
    full = os.path.join(REPO_ROOT, rel_path)
    spec = importlib.util.spec_from_file_location(name, full)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


def extract_function(rel_path: str, func_name: str):
    full = os.path.join(REPO_ROOT, rel_path)
    with open(full, "r") as fh:
        src = fh.read()
    tree = ast.parse(src)
    for node in tree.body:
        if isinstance(node, ast.FunctionDef) and node.name == func_name:
            seg = ast.get_source_segment(src, node)
            ns = {"np": np, "math": math, "pd": pd}
            exec(seg, ns)
            return ns[func_name]
    raise LookupError(f"{func_name} not found in {rel_path}")


def vix_dsr():
    return load_module("alphaforge-vix/gauntlet/stats.py",
                       "vix_stats_dsr").deflated_sharpe_ratio


def crypto_dsr():
    return load_module("alphaforge-crypto/research/carry_primitives.py",
                       "crypto_carry_dsr").deflated_sharpe_ratio


def india_dsr():
    return load_module("alphaforge-india/gauntlet/gates.py",
                       "india_gates_dsr").deflated_sharpe_ratio


def pead_dsr():
    return extract_function("alphaforge-pead/gauntlet/run_phase1.py",
                            "_deflated_sharpe")
