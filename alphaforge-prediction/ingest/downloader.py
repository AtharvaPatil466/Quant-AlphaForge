"""Kalshi settled-markets downloader → resolved-contract parquet.

Per `research/PREDICTION_MARKETS_DESIGN.md` §2 + §4 and the confirmed shapes in
`research/SPIKE_NOTES.md`. Pipeline per resolved market:

  1. paginate ``/markets?status=settled`` (cursor);
  2. keep only volume-bearing rows (``volume_fp > 0``, §7);
  3. resolve the event → (series_ticker, category) [cached per event];
  4. reconstruct the §4 **entry price** from 1-minute candlesticks at the frozen
     lead of one hour before ``close_time`` (fallback: last pre-close trade);
  5. assemble one schema row; write parquet under ``data/``.

Checkpointed / resumable (mirrors `alphaforge-india/ingest/downloader.py`):
  - Per-ticker JSONL checkpoint at ``data/processed/_ingest_checkpoint.jsonl``.
    A ticker is "done" once written (or recorded as skipped/failed-terminal).
  - Parquet is flushed in shards of ``flush_every`` rows; atomic os.replace.
  - On restart, completed tickers are skipped; the cursor frontier is replayed.

The ONLY network access is via ``ingest.kalshi_client.KalshiClient``.
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import sys
from dataclasses import dataclass, asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

# Path bootstrap — allow `python -m ingest.downloader` from sub-project root.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from ingest import schema as S          # noqa: E402
from ingest.kalshi_client import (      # noqa: E402
    KalshiClient, KalshiClientConfig, KalshiAPIError, RateLimitedError,
)

log = logging.getLogger("prediction.downloader")

# §4 frozen entry lead: one hour before close, in seconds.
ENTRY_LEAD_SECONDS: int = 3600

# Candlestick reconstruction window: how far before close we fetch (seconds).
# 1-minute candles; window kept well under the 5000-candle cap.
CANDLE_WINDOW_SECONDS: int = 6 * 3600


# ---------------------------------------------------------------------------
# Candle helpers (pure; unit-tested without the network)
# ---------------------------------------------------------------------------

def _candle_close_price(candle: dict[str, Any]) -> float:
    """Last-trade price within a candle bucket, or NaN if no trade occurred.

    ``price.close_dollars`` is present iff a trade happened in the bucket; when
    absent, ``price.previous_dollars`` carries the prior trade (we treat the
    candle as 'no trade here' and rely on an earlier bucket's close).
    """
    price = candle.get("price") or {}
    return S.to_float(price.get("close_dollars"), default=float("nan"))


def _candle_quote(candle: dict[str, Any]) -> tuple[float, float]:
    """(yes_bid, yes_ask) close-of-bucket quotes; NaN where missing."""
    yb = (candle.get("yes_bid") or {}).get("close_dollars")
    ya = (candle.get("yes_ask") or {}).get("close_dollars")
    return S.to_float(yb, float("nan")), S.to_float(ya, float("nan"))


@dataclass
class EntrySnapshot:
    entry_price: float
    yes_bid: float
    yes_ask: float
    snapshot_ts_s: int   # end_period_ts (epoch seconds) of the chosen candle
    used_fallback: bool


def reconstruct_entry(
    candles: list[dict[str, Any]],
    close_time_s: int,
    lead_seconds: int = ENTRY_LEAD_SECONDS,
) -> EntrySnapshot | None:
    """§4 entry-price reconstruction.

    Primary: the last candle with a real trade whose ``end_period_ts`` is at or
    before ``close_time_s - lead_seconds``. Fallback: the last candle with a
    real trade strictly before ``close_time_s``. Returns None if the market
    never traded before close.

    Look-ahead safety: the returned ``snapshot_ts_s`` is always strictly less
    than ``close_time_s`` (asserted by construction here and by the validator).
    """
    if not candles:
        return None
    target = close_time_s - lead_seconds
    # Candles sorted by end_period_ts ascending (API returns them ordered, but
    # we sort defensively).
    ordered = sorted(candles, key=lambda c: int(c.get("end_period_ts", 0)))

    def pick(upper_bound_exclusive: int | None, at_or_before: int | None):
        best: dict[str, Any] | None = None
        for c in ordered:
            ts = int(c.get("end_period_ts", 0))
            if at_or_before is not None and ts > at_or_before:
                continue
            if upper_bound_exclusive is not None and ts >= upper_bound_exclusive:
                continue
            price = _candle_close_price(c)
            if price == price:  # not NaN
                best = c
        return best

    # Primary: last real trade at/before the lead target.
    chosen = pick(upper_bound_exclusive=close_time_s, at_or_before=target)
    used_fallback = False
    if chosen is None:
        # Fallback: last real trade strictly before close.
        chosen = pick(upper_bound_exclusive=close_time_s, at_or_before=None)
        used_fallback = True
    if chosen is None:
        return None

    price = _candle_close_price(chosen)
    yes_bid, yes_ask = _candle_quote(chosen)
    snap_ts = int(chosen.get("end_period_ts", 0))
    if snap_ts >= close_time_s:
        # Defensive: never allow a snapshot at/after close.
        return None
    return EntrySnapshot(
        entry_price=price,
        yes_bid=yes_bid,
        yes_ask=yes_ask,
        snapshot_ts_s=snap_ts,
        used_fallback=used_fallback,
    )


def settlement_value_from(market: dict[str, Any]) -> float:
    """Settlement value in dollars: prefer the API field, else infer from result.

    Resolved binaries pay 1.0 (YES) or 0.0 (NO). ``settlement_value_dollars``
    is authoritative when present and finite; otherwise infer from ``result``.
    """
    sv = S.to_float(market.get("settlement_value_dollars"), default=float("nan"))
    if sv == sv:  # finite
        return sv
    result = str(market.get("result") or "").lower()
    if result == "yes":
        return 1.0
    if result == "no":
        return 0.0
    return float("nan")


# ---------------------------------------------------------------------------
# Checkpoint (per-ticker, append-only JSONL — mirrors india)
# ---------------------------------------------------------------------------

@dataclass
class IngestRow:
    ticker: str
    result: str          # "written" | "skipped_no_volume" | "skipped_unresolved"
                         # | "skipped_no_entry" | "failed"
    reason: str | None
    completed_at: str    # ISO-8601 UTC


class Checkpoint:
    def __init__(self, path: Path):
        self.path = path
        self._done: dict[str, IngestRow] = {}
        if path.exists():
            self._load()

    def _load(self) -> None:
        with self.path.open() as fp:
            for line in fp:
                line = line.strip()
                if not line:
                    continue
                try:
                    obj = json.loads(line)
                except json.JSONDecodeError:
                    log.warning("checkpoint: skipping malformed line: %r", line[:80])
                    continue
                self._done[obj["ticker"]] = IngestRow(**obj)

    def is_done(self, ticker: str) -> bool:
        row = self._done.get(ticker)
        # FAILED rows are retried on resume; everything else is terminal.
        return row is not None and row.result != "failed"

    def append(self, row: IngestRow) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("a") as fp:
            fp.write(json.dumps(asdict(row), separators=(",", ":")) + "\n")
            fp.flush()
            os.fsync(fp.fileno())
        self._done[row.ticker] = row

    def count(self, result: str | None = None) -> int:
        if result is None:
            return len(self._done)
        return sum(1 for r in self._done.values() if r.result == result)


# ---------------------------------------------------------------------------
# Parquet shard writer (atomic)
# ---------------------------------------------------------------------------

def _utcnow_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def write_rows_parquet(rows: list[dict[str, Any]], out_path: Path) -> int:
    """Write schema rows to a parquet shard atomically. Returns row count."""
    import pandas as pd

    if not rows:
        return 0
    df = pd.DataFrame(rows)
    # Enforce canonical column order + dtypes.
    for col in S.COLUMNS:
        if col not in df.columns:
            df[col] = pd.NA
    df = df[list(S.COLUMNS)].astype(S.DTYPES)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    tmp = out_path.with_suffix(out_path.suffix + ".tmp")
    df.to_parquet(tmp, index=False)
    os.replace(tmp, out_path)
    return len(df)


# ---------------------------------------------------------------------------
# Downloader
# ---------------------------------------------------------------------------

@dataclass
class DownloadConfig:
    output_root: Path
    limit_per_page: int = 200
    max_pages: int | None = None         # None = exhaust all settled markets
    flush_every: int = 500               # rows per parquet shard
    period_interval: int = 1             # candle width (minutes)
    # Historical date-window paging (epoch seconds). When either is set, the
    # status filter is dropped and resolved rows are filtered client-side
    # (see SPIKE_NOTES.md — status=settled returns empty for old windows).
    min_close_ts: int | None = None
    max_close_ts: int | None = None


class EventCache:
    """Caches event_ticker -> (series_ticker, category). One events call/event."""

    def __init__(self, client: KalshiClient):
        self.client = client
        self._cache: dict[str, tuple[str, str]] = {}

    def lookup(self, event_ticker: str) -> tuple[str, str]:
        if event_ticker in self._cache:
            return self._cache[event_ticker]
        try:
            event = self.client.get_event(event_ticker)
        except KalshiAPIError as e:
            log.warning("event lookup failed for %s: %s", event_ticker, e)
            self._cache[event_ticker] = ("", "")
            return self._cache[event_ticker]
        series = str(event.get("series_ticker") or "")
        category = str(event.get("category") or "")
        self._cache[event_ticker] = (series, category)
        return series, category


class Downloader:
    def __init__(self, config: DownloadConfig, client: KalshiClient | None = None):
        self.cfg = config
        self.client = client or KalshiClient()
        self.checkpoint = Checkpoint(
            config.output_root / "processed" / "_ingest_checkpoint.jsonl"
        )
        self.events = EventCache(self.client)
        self._buffer: list[dict[str, Any]] = []
        self._shard_index = self._next_shard_index()

    def _shard_dir(self) -> Path:
        return self.cfg.output_root / "processed" / "resolved"

    def _next_shard_index(self) -> int:
        d = self._shard_dir()
        if not d.exists():
            return 0
        idxs = []
        for p in d.glob("part-*.parquet"):
            try:
                idxs.append(int(p.stem.split("-")[1]))
            except (IndexError, ValueError):
                continue
        return (max(idxs) + 1) if idxs else 0

    def _flush(self) -> None:
        if not self._buffer:
            return
        out = self._shard_dir() / f"part-{self._shard_index:05d}.parquet"
        n = write_rows_parquet(self._buffer, out)
        log.info("flushed %d rows -> %s", n, out.name)
        self._buffer.clear()
        self._shard_index += 1

    def build_row(self, market: dict[str, Any]) -> dict[str, Any] | None:
        """Assemble one schema row for a resolved, volume-bearing market.

        Returns None (with a logged reason) if the market should be skipped:
        unresolved status/result, or no reconstructable pre-close trade.
        """
        ticker = str(market.get("ticker") or "")
        status = str(market.get("status") or "").lower()
        result = str(market.get("result") or "").lower()
        if status not in S.RESOLVED_STATUSES or result not in S.VALID_RESULTS:
            return None

        event_ticker = str(market.get("event_ticker") or "")
        series, category = self.events.lookup(event_ticker)

        close_ns = S.iso_to_ns(market.get("close_time"))
        open_ns = S.iso_to_ns(market.get("open_time"))
        if close_ns == S.NS_MISSING:
            return None
        close_s = close_ns // 1_000_000_000

        entry = self._reconstruct_entry_for(market, series, ticker, open_ns, close_s)
        if entry is None:
            return None

        return {
            "ticker": ticker,
            "event_ticker": event_ticker,
            "series_ticker": series,
            "category": category,
            "market_type": str(market.get("market_type") or ""),
            "open_time": open_ns if open_ns != S.NS_MISSING else 0,
            "close_time": close_ns,
            "settlement_ts": S.iso_to_ns(market.get("settlement_ts")),
            "result": result,
            "settlement_value": settlement_value_from(market),
            "entry_price": entry.entry_price,
            "implied_prob": entry.entry_price,
            "entry_snapshot_ts": entry.snapshot_ts_s * 1_000_000_000,
            "yes_bid": entry.yes_bid,
            "yes_ask": entry.yes_ask,
            "volume_fp": S.to_float(market.get("volume_fp"), default=0.0),
        }

    def _reconstruct_entry_for(
        self, market: dict[str, Any], series: str, ticker: str,
        open_ns: int, close_s: int,
    ) -> EntrySnapshot | None:
        """Fetch the candlestick window and run §4 reconstruction.

        Window: [max(open, close-6h), close], 1-minute candles (well under cap).
        Falls back to recorded last_price_dollars only if candlesticks are
        unavailable AND a pre-close last price exists — but per §4 the entry must
        be a *trade*, so an empty candle history → skip (returns None).
        """
        if not series:
            return None
        window_start_s = close_s - CANDLE_WINDOW_SECONDS
        if open_ns != S.NS_MISSING:
            window_start_s = max(window_start_s, open_ns // 1_000_000_000)
        if window_start_s >= close_s:
            window_start_s = close_s - CANDLE_WINDOW_SECONDS
        try:
            candles = self.client.get_candlesticks(
                series, ticker, window_start_s, close_s,
                period_interval=self.cfg.period_interval,
            )
        except (KalshiAPIError, ValueError) as e:
            log.warning("candlesticks failed for %s: %s", ticker, e)
            return None
        return reconstruct_entry(candles, close_s)

    def run(self) -> dict[str, int]:
        stats = {"seen": 0, "written": 0, "skipped_no_volume": 0,
                 "skipped_unresolved": 0, "skipped_no_entry": 0,
                 "skipped_already_done": 0, "failed": 0}
        windowed = self.cfg.min_close_ts is not None or self.cfg.max_close_ts is not None
        try:
            for market, _cursor in self.client.iter_settled_markets(
                limit=self.cfg.limit_per_page, max_pages=self.cfg.max_pages,
                status=None if windowed else "settled",
                min_close_ts=self.cfg.min_close_ts,
                max_close_ts=self.cfg.max_close_ts,
            ):
                stats["seen"] += 1
                ticker = str(market.get("ticker") or "")
                if not ticker:
                    continue
                if self.checkpoint.is_done(ticker):
                    stats["skipped_already_done"] += 1
                    continue

                # §7 volume filter.
                if S.to_float(market.get("volume_fp"), default=0.0) <= 0:
                    self.checkpoint.append(IngestRow(
                        ticker, "skipped_no_volume", "volume_fp<=0", _utcnow_iso()))
                    stats["skipped_no_volume"] += 1
                    continue

                status = str(market.get("status") or "").lower()
                result = str(market.get("result") or "").lower()
                if status not in S.RESOLVED_STATUSES or result not in S.VALID_RESULTS:
                    self.checkpoint.append(IngestRow(
                        ticker, "skipped_unresolved",
                        f"status={status},result={result}", _utcnow_iso()))
                    stats["skipped_unresolved"] += 1
                    continue

                try:
                    row = self.build_row(market)
                except (KalshiAPIError, ValueError) as e:
                    self.checkpoint.append(IngestRow(
                        ticker, "failed", repr(e), _utcnow_iso()))
                    stats["failed"] += 1
                    continue

                if row is None:
                    self.checkpoint.append(IngestRow(
                        ticker, "skipped_no_entry",
                        "no pre-close trade reconstructable", _utcnow_iso()))
                    stats["skipped_no_entry"] += 1
                    continue

                self._buffer.append(row)
                self.checkpoint.append(IngestRow(ticker, "written", None, _utcnow_iso()))
                stats["written"] += 1
                if len(self._buffer) >= self.cfg.flush_every:
                    self._flush()
        except RateLimitedError as e:
            log.error("HALTED (rate limited): %s — resume by re-running", e)
            stats["rate_limited"] = 1
        finally:
            self._flush()
        return stats


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main(argv: Iterable[str] | None = None) -> int:
    p = argparse.ArgumentParser(
        description="Kalshi settled-markets downloader (checkpointed, resumable)."
    )
    p.add_argument("--output-root", type=Path, default=Path("data"),
                   help="Output root (default: ./data)")
    p.add_argument("--limit-per-page", type=int, default=200)
    p.add_argument("--max-pages", type=int, default=None,
                   help="Stop after N pages of /markets (default: exhaust all)")
    p.add_argument("--flush-every", type=int, default=500)
    p.add_argument("--period-interval", type=int, default=1, choices=[1, 60, 1440])
    p.add_argument("--rate-limit-seconds", type=float, default=0.25)
    p.add_argument("--min-close", type=str, default=None,
                   help="ISO date/datetime; only markets closing at/after this "
                        "(drops status filter, pages historical window).")
    p.add_argument("--max-close", type=str, default=None,
                   help="ISO date/datetime; only markets closing before this.")
    p.add_argument("--verbose", "-v", action="count", default=0)
    args = p.parse_args(list(argv) if argv is not None else None)

    def _iso_to_epoch_s(s: str | None) -> int | None:
        if not s:
            return None
        ns = S.iso_to_ns(s if "T" in s else s + "T00:00:00Z")
        return None if ns == S.NS_MISSING else ns // 1_000_000_000

    level = logging.WARNING - 10 * args.verbose
    logging.basicConfig(level=max(level, logging.DEBUG),
                        format="%(asctime)s %(levelname)s %(name)s: %(message)s")

    client = KalshiClient(KalshiClientConfig(rate_limit_seconds=args.rate_limit_seconds))
    cfg = DownloadConfig(
        output_root=args.output_root,
        limit_per_page=args.limit_per_page,
        max_pages=args.max_pages,
        flush_every=args.flush_every,
        period_interval=args.period_interval,
        min_close_ts=_iso_to_epoch_s(args.min_close),
        max_close_ts=_iso_to_epoch_s(args.max_close),
    )
    dl = Downloader(cfg, client=client)
    stats = dl.run()
    log.info("done: %s", stats)
    print(json.dumps(stats, indent=2))
    return 1 if stats.get("rate_limited") else 0


if __name__ == "__main__":
    sys.exit(main())
