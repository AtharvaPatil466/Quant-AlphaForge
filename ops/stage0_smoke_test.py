#!/usr/bin/env python3
"""Stage 0 runtime smoke test for AlphaForge.

This script validates the minimal runnable path for the three Python stacks:
1. parquet-backed market data loads through alphaforge-execution
2. a real-data factor computation runs through alphaforge-python
3. a FastAPI endpoint responds through alphaforge-python
4. a MARL environment episode resets and steps on real local data

Run this after rebuilding the project virtual environments:
    python3 ops/stage0_smoke_test.py
"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
import json
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path


ROOT_DIR = Path(__file__).resolve().parents[1]


@dataclass(frozen=True)
class StepSpec:
    name: str
    interpreter: Path
    cwd: Path
    code: str
    timeout_seconds: int = 30


PARQUET_READ_CODE = """
import json
from datetime import date
from data.market_data import fetch_history

history = fetch_history(["AAPL"], days=30, end=date(2024, 12, 31))
if "AAPL" not in history or history["AAPL"].empty:
    raise RuntimeError("Execution market-data load returned no rows for AAPL")

df = history["AAPL"]
print(json.dumps({
    "ticker": "AAPL",
    "rows": int(len(df)),
    "start": str(df.index[0].date()),
    "end": str(df.index[-1].date()),
}))
""".strip()


FACTOR_COMPUTE_CODE = """
import json
from data.real_dataset import load_real_dataset
from factors.registry import load_factor

dataset = load_real_dataset(
    sector="Technology",
    lookback=252,
    end_date="2024-12-31",
)
if not dataset:
    raise RuntimeError("Real dataset load returned no tickers")

factor = load_factor("Momentum (12-1)")
scores = factor.compute_universe(dataset, 252)
if not scores:
    raise RuntimeError("Factor computation returned no scores")

sample_ticker = sorted(scores)[0]
print(json.dumps({
    "tickers": len(dataset),
    "sample_ticker": sample_ticker,
    "sample_score": float(scores[sample_ticker]),
}))
""".strip()


API_CALL_CODE = """
import json
from fastapi.testclient import TestClient
from api.server import app

client = TestClient(app)
response = client.get("/api/v1/health")
if response.status_code != 200:
    raise RuntimeError(f"Health endpoint failed with status {response.status_code}")

payload = response.json()
if payload.get("status") != "ok":
    raise RuntimeError(f"Unexpected health payload: {payload}")

print(json.dumps({
    "status": payload["status"],
    "version": payload["version"],
}))
""".strip()


MARL_EPISODE_CODE = """
import json
from env.trading_env import TradingEnv

env = TradingEnv(
    sector="Technology",
    lookback=63,
    episode_length=5,
    data_mode="real_strict",
    strict_real_data=True,
    real_data_start_date="2019-01-01",
    real_data_end_date="2024-12-31",
)
obs, info = env.reset(seed=42)
next_obs, reward, terminated, truncated, next_info = env.step(0)

if len(obs) != env.observation_space.shape[0]:
    raise RuntimeError(
        f"Observation shape mismatch: got {len(obs)}, expected {env.observation_space.shape[0]}"
    )
if next_info.get("resolved_data_source") != "real":
    raise RuntimeError(
        f"Expected real data source, got {next_info.get('resolved_data_source')}"
    )

print(json.dumps({
    "obs_shape": len(obs),
    "next_obs_shape": len(next_obs),
    "reward": float(reward),
    "terminated": bool(terminated),
    "truncated": bool(truncated),
    "resolved_data_source": next_info["resolved_data_source"],
}))
""".strip()


def _project_python(project: str) -> Path:
    return ROOT_DIR / project / ".venv" / "bin" / "python"


def build_steps() -> list[StepSpec]:
    return [
        StepSpec(
            name="parquet-read",
            interpreter=_project_python("alphaforge-execution"),
            cwd=ROOT_DIR / "alphaforge-execution",
            code=PARQUET_READ_CODE,
        ),
        StepSpec(
            name="factor-compute",
            interpreter=_project_python("alphaforge-python"),
            cwd=ROOT_DIR / "alphaforge-python",
            code=FACTOR_COMPUTE_CODE,
        ),
        StepSpec(
            name="api-call",
            interpreter=_project_python("alphaforge-python"),
            cwd=ROOT_DIR / "alphaforge-python",
            code=API_CALL_CODE,
        ),
        StepSpec(
            name="marl-episode",
            interpreter=_project_python("alphaforge-marl"),
            cwd=ROOT_DIR / "alphaforge-marl",
            code=MARL_EPISODE_CODE,
        ),
    ]


def run_step(step: StepSpec) -> dict[str, object]:
    if not step.interpreter.exists():
        raise FileNotFoundError(
            f"Missing interpreter for {step.name}: {step.interpreter}"
        )

    started = time.perf_counter()
    completed = subprocess.run(
        [str(step.interpreter), "-c", step.code],
        cwd=step.cwd,
        capture_output=True,
        text=True,
        timeout=step.timeout_seconds,
        check=False,
    )
    elapsed = time.perf_counter() - started

    if completed.returncode != 0:
        stdout = completed.stdout.strip()
        stderr = completed.stderr.strip()
        details = "\n".join(part for part in (stdout, stderr) if part)
        raise RuntimeError(
            f"{step.name} failed in {elapsed:.2f}s\n{details}".rstrip()
        )

    stdout = completed.stdout.strip().splitlines()
    if not stdout:
        raise RuntimeError(f"{step.name} produced no output")

    payload = json.loads(stdout[-1])
    return {
        "name": step.name,
        "elapsed_seconds": round(elapsed, 3),
        "details": payload,
    }


def main() -> int:
    started = time.perf_counter()
    steps = build_steps()
    results_by_name: dict[str, dict[str, object]] = {}

    with ThreadPoolExecutor(max_workers=len(steps)) as executor:
        futures = {
            executor.submit(run_step, step): step.name
            for step in steps
        }
        for future in as_completed(futures):
            result = future.result()
            results_by_name[result["name"]] = result
            print(f"PASS {result['name']} ({result['elapsed_seconds']}s)")

    total_seconds = time.perf_counter() - started
    results = [results_by_name[step.name] for step in steps]
    print(
        json.dumps(
            {
                "status": "ok",
                "total_seconds": round(total_seconds, 3),
                "results": results,
            },
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
