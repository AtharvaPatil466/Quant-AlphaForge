"""Download progress reporter — read-only over the live checkpoint file.

Safe to run while `ingest.downloader` is downloading. The downloader writes
to `data/processed/_download_checkpoint.jsonl` with `O_APPEND` + fsync per
row, so any concurrent reader sees a consistent prefix at any instant.

CLI:
    python -m ingest.progress --data-root data
    python -m ingest.progress --data-root data --since 2024-01-01

Output summarizes:
  - Total (date, source) attempts logged
  - Per-result breakdown (ok / not_found / failed / halted)
  - Per-year coverage (sliced from "ok" rows)
  - Recent failures + halt rows (last 10)
  - Throughput estimate (last hour) + naive ETA to substrate end
"""
from __future__ import annotations

import argparse
import json
import logging
import sys
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

log = logging.getLogger("india.progress")

# Substrate window from INDIA_DESIGN.md §3 — used for ETA estimate.
SUBSTRATE_START = date(2004, 1, 1)
SUBSTRATE_END = date(2026, 5, 18)

# Era boundary from `ingest.downloader` — pre-boundary fetches 2 sources
# (legacy + MTO), post-boundary fetches 1 source (unified). The overlap
# window is small enough to ignore for ETA purposes.
_ERA_BOUNDARY = date(2020, 2, 1)


@dataclass
class ProgressSnapshot:
    total_attempts: int
    ok: int
    not_found: int
    failed: int
    halted: int
    first_attempt_at: datetime | None
    last_attempt_at: datetime | None
    per_year_ok: dict[int, int]
    per_year_not_found: dict[int, int]
    recent_failures: list[dict]
    recent_halts: list[dict]


def read_checkpoint(path: Path) -> list[dict]:
    """Stream-parse the JSONL checkpoint. Malformed lines are skipped
    silently — the downloader fsyncs each row, so a malformed line only
    appears mid-write and is harmless."""
    if not path.exists():
        return []
    rows: list[dict] = []
    with path.open() as fp:
        for raw in fp:
            raw = raw.strip()
            if not raw:
                continue
            try:
                rows.append(json.loads(raw))
            except json.JSONDecodeError:
                continue
    return rows


def summarize(rows: list[dict], since: date | None = None) -> ProgressSnapshot:
    if since is not None:
        rows = [r for r in rows if r.get("date", "") >= since.isoformat()]
    result_counts = Counter(r.get("result", "?") for r in rows)
    per_year_ok: dict[int, int] = defaultdict(int)
    per_year_not_found: dict[int, int] = defaultdict(int)
    for r in rows:
        date_str = r.get("date", "")
        if len(date_str) < 4:
            continue
        try:
            y = int(date_str[:4])
        except ValueError:
            continue
        if r.get("result") == "ok":
            per_year_ok[y] += 1
        elif r.get("result") == "not_found":
            per_year_not_found[y] += 1

    completed_at_values = [r.get("completed_at") for r in rows
                            if r.get("completed_at")]
    parsed_times: list[datetime] = []
    for s in completed_at_values:
        try:
            t = datetime.fromisoformat(s.replace("Z", "+00:00"))
            parsed_times.append(t)
        except (ValueError, AttributeError):
            continue
    first_at = min(parsed_times) if parsed_times else None
    last_at = max(parsed_times) if parsed_times else None

    recent_failures = [r for r in rows
                       if r.get("result") in {"failed"}][-10:]
    recent_halts = [r for r in rows if r.get("result") == "halted"][-10:]

    return ProgressSnapshot(
        total_attempts=len(rows),
        ok=result_counts.get("ok", 0),
        not_found=result_counts.get("not_found", 0),
        failed=result_counts.get("failed", 0),
        halted=result_counts.get("halted", 0),
        first_attempt_at=first_at,
        last_attempt_at=last_at,
        per_year_ok=dict(per_year_ok),
        per_year_not_found=dict(per_year_not_found),
        recent_failures=recent_failures,
        recent_halts=recent_halts,
    )


def _trading_days_between(start: date, end: date) -> int:
    """Weekday count, no holiday adjustment. Coarse but fine for ETA."""
    days = (end - start).days + 1
    full_weeks = days // 7
    remainder = days - full_weeks * 7
    # Approximate: assume average 5/7 weekdays in the remainder.
    extra_weekdays = int(round(remainder * 5 / 7))
    return full_weeks * 5 + extra_weekdays


def expected_total_attempts(
    start: date = SUBSTRATE_START, end: date = SUBSTRATE_END,
    era_boundary: date = _ERA_BOUNDARY,
) -> int:
    """Total expected (date, source) attempts across the substrate window,
    honoring the pre-2020 (2 sources) vs post-2020 (1 source) era split."""
    pre_weekdays = _trading_days_between(start, min(era_boundary, end))
    if era_boundary >= end:
        return pre_weekdays * 2
    post_weekdays = _trading_days_between(era_boundary, end)
    return pre_weekdays * 2 + post_weekdays


def estimate_eta(snapshot: ProgressSnapshot,
                  target_end: date = SUBSTRATE_END) -> str:
    """Naive ETA: extrapolate observed throughput to the remaining
    (date, source) pairs in the substrate window."""
    if snapshot.last_attempt_at is None or snapshot.first_attempt_at is None:
        return "no data yet"
    if snapshot.total_attempts == 0:
        return "no attempts yet"

    elapsed = (snapshot.last_attempt_at - snapshot.first_attempt_at).total_seconds()
    if elapsed < 60:
        return "warming up"

    rate = snapshot.total_attempts / elapsed  # attempts per second
    if rate <= 0:
        return "no measurable rate"

    expected_total = expected_total_attempts(end=target_end)
    remaining = max(0, expected_total - snapshot.total_attempts)
    rate_per_min = rate * 60

    if remaining == 0:
        return (f"all expected attempts logged "
                f"({snapshot.total_attempts}/{expected_total}; "
                f"observed {rate_per_min:.1f}/min)")

    eta_seconds = remaining / rate
    h = int(eta_seconds // 3600)
    m = int((eta_seconds % 3600) // 60)
    return (f"~{h}h {m}m remaining "
            f"({snapshot.total_attempts}/{expected_total} done; "
            f"{rate_per_min:.1f}/min)")


def render(snapshot: ProgressSnapshot) -> str:
    lines: list[str] = []
    lines.append("=" * 60)
    lines.append("NSE Bhavcopy Download Progress")
    lines.append("=" * 60)
    lines.append(f"Total attempts logged: {snapshot.total_attempts:,}")
    lines.append(f"  ok        : {snapshot.ok:,}")
    lines.append(f"  not_found : {snapshot.not_found:,} (NSE holidays)")
    lines.append(f"  failed    : {snapshot.failed:,}")
    lines.append(f"  halted    : {snapshot.halted:,}")
    if snapshot.first_attempt_at:
        elapsed = snapshot.last_attempt_at - snapshot.first_attempt_at
        lines.append(f"  elapsed   : {elapsed}")
        lines.append(f"  started   : {snapshot.first_attempt_at.isoformat()}")
        lines.append(f"  latest    : {snapshot.last_attempt_at.isoformat()}")
    lines.append("")
    lines.append("Per-year coverage (ok rows):")
    all_years = sorted(set(snapshot.per_year_ok) | set(snapshot.per_year_not_found))
    if not all_years:
        lines.append("  (no data)")
    else:
        for y in all_years:
            ok = snapshot.per_year_ok.get(y, 0)
            nf = snapshot.per_year_not_found.get(y, 0)
            lines.append(f"  {y}: ok={ok:>4}  not_found={nf:>3}")
    lines.append("")
    eta = estimate_eta(snapshot)
    lines.append(f"ETA estimate: {eta}")
    lines.append("")
    if snapshot.recent_halts:
        lines.append("⚠ Recent HALT rows (manual intervention required):")
        for r in snapshot.recent_halts:
            lines.append(f"  {r.get('date')} / {r.get('source')} → status "
                         f"{r.get('status')} attempts={r.get('attempts')}")
        lines.append("")
    if snapshot.recent_failures:
        lines.append("Recent failures (last 10):")
        for r in snapshot.recent_failures:
            err = (r.get("error") or "")[:60]
            lines.append(f"  {r.get('date')} / {r.get('source')} → "
                         f"attempts={r.get('attempts')} {err}")
    return "\n".join(lines)


def _parse_date(s: str) -> date:
    return datetime.strptime(s, "%Y-%m-%d").date()


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="NSE download progress reporter.")
    p.add_argument("--data-root", type=Path, default=Path("data"))
    p.add_argument("--since", type=_parse_date, default=None,
                   help="Only summarize attempts dated on/after this date.")
    p.add_argument("--checkpoint", type=Path, default=None,
                   help="Override checkpoint path "
                        "(default: <data-root>/processed/_download_checkpoint.jsonl)")
    args = p.parse_args(argv)

    cp_path = args.checkpoint or (
        args.data_root / "processed" / "_download_checkpoint.jsonl"
    )
    rows = read_checkpoint(cp_path)
    if not rows:
        print(f"No checkpoint rows at {cp_path}. Has the downloader run?")
        return 1
    snapshot = summarize(rows, since=args.since)
    print(render(snapshot))
    return 0


if __name__ == "__main__":
    sys.exit(main())
