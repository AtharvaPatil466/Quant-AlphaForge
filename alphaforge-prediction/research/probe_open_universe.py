"""Read-only probe: characterize the LIVE open-market universe on the free host.

Substrate #10 (Kalshi FLB), Phase 2 diagnostics. This is a *diagnostic* tool —
it places NO orders and writes NO journal; it only tabulates the currently-open
Kalshi universe so the forward-config decision (design §9 / §16 ADDENDUM) is made
against real numbers rather than a single-page sample.

It answers, across N paged open markets:
  - category mix (MVE vs non-MVE, by the event category and the MVE name marker);
  - entry-price bucket distribution (the §4 cent buckets, on the YES price);
  - time-to-close distribution (sub-minute MVE vs hours/days non-MVE);
  - the cross-tab that actually matters: how many open markets are
    (a) non-MVE event-category AND (b) at a price extreme (≤15c or ≥85c) AND
    (c) have enough time-to-close to enter-and-hold — i.e. how many the
    DEFAULT_RULE_SPEC would actually journal per full sweep, and how many a
    widened/MVE-inclusive variant would journal.

Network access is confined to ``ingest.kalshi_client`` (the open-markets pager +
the event lookups for category/series). Everything else is pure.

Usage:
    python3.13 -m research.probe_open_universe --max-pages 10 \
        --rate-limit-seconds 0.15 [--no-events] [--json OUT.json]

``--no-events`` skips the per-event category lookups (much faster; classifies MVE
purely from the ticker/collection markers). With events on, the probe resolves
each distinct event once (cached) for its real ``category`` — the same field the
rule's category filter keys on.
"""
from __future__ import annotations

import argparse
import json
import logging
import math
import sys
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable

# Path bootstrap — allow `python -m research.probe_open_universe` from the root.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from ingest import schema as S                       # noqa: E402
from ingest.kalshi_client import (                   # noqa: E402
    KalshiClient, KalshiClientConfig, KalshiAPIError, RateLimitedError,
)
from signals.strategy import (                        # noqa: E402
    DEFAULT_RULE_SPEC, extract_open_market, select_orders,
)

log = logging.getLogger("prediction.probe")

# §4 cent buckets (lo, hi] in dollars, plus a 0-bucket for exactly-0/no-price.
PRICE_BUCKETS: tuple[tuple[float, float, str], ...] = (
    (0.00, 0.05, "(0,5]"),
    (0.05, 0.15, "(5,15]"),
    (0.15, 0.35, "(15,35]"),
    (0.35, 0.65, "(35,65]"),
    (0.65, 0.85, "(65,85]"),
    (0.85, 0.95, "(85,95]"),
    (0.95, 1.00, "(95,100]"),
)
EXTREME_BUCKETS: frozenset[str] = frozenset({"(0,5]", "(5,15]", "(85,95]", "(95,100]"})

# Time-to-close strata (seconds). MVE markets resolve sub-minute; classic FLB
# event markets sit hours→days out. The "enter-and-hold" threshold is the
# operative one: a forward record needs the contract to live long enough to
# journal an entry now and reconcile a resolution later.
TTC_STRATA: tuple[tuple[float, float, str], ...] = (
    (0.0, 60.0, "<1min (MVE)"),
    (60.0, 3600.0, "1min-1h"),
    (3600.0, 86400.0, "1h-1d"),
    (86400.0, 7 * 86400.0, "1d-7d"),
    (7 * 86400.0, float("inf"), ">7d"),
)
# A contract needs at least this long to enter-and-hold for the forward record.
ENTER_AND_HOLD_MIN_SECONDS: float = 3600.0


def _price_bucket(price: float) -> str | None:
    if not math.isfinite(price):
        return None
    for lo, hi, label in PRICE_BUCKETS:
        left_closed = lo == 0.0
        if (lo <= price <= hi) if left_closed else (lo < price <= hi):
            return label
    return None


def _ttc_stratum(seconds: float) -> str:
    if not math.isfinite(seconds):
        return ">7d"
    for lo, hi, label in TTC_STRATA:
        if lo <= seconds < hi:
            return label
    return ">7d"


def _is_mve(market: dict[str, Any], category: str) -> bool:
    """Heuristic MVE classifier (design §16: sub-minute crypto/sports exotics).

    True iff any MVE marker is present: an ``mve_collection_ticker``/
    ``mve_selected_legs`` field, an ``MVE`` token in the event/series ticker, or
    the event category resolving to "exotics".
    """
    if market.get("mve_collection_ticker") or market.get("mve_selected_legs"):
        return True
    et = str(market.get("event_ticker") or "").upper()
    if "MVE" in et:
        return True
    if (category or "").strip().lower() == "exotics":
        return True
    return False


@dataclass
class ProbeAccumulator:
    n_seen: int = 0
    n_priced: int = 0                       # finite YES price formed
    cat_counts: Counter = field(default_factory=Counter)
    mve_counts: Counter = field(default_factory=Counter)     # "MVE" / "non-MVE"
    bucket_counts: Counter = field(default_factory=Counter)
    ttc_counts: Counter = field(default_factory=Counter)
    # cross-tab: mve_flag -> bucket -> ttc -> count
    cross: dict[str, dict[str, Counter]] = field(
        default_factory=lambda: defaultdict(lambda: defaultdict(Counter)))
    # how many would the DEFAULT (non-MVE) rule journal, and a widened variant
    default_eligible_tickers: set = field(default_factory=set)
    # non-MVE & price-extreme & enough-ttc (the §9 target)
    nonmve_extreme_holdable: int = 0
    # MVE & price-extreme & enough-ttc (the separate §16 MVE track)
    mve_extreme_holdable: int = 0
    # MVE & price-extreme regardless of ttc (sub-minute resolve-fast pool)
    mve_extreme_any_ttc: int = 0


def probe(client: KalshiClient, *, max_pages: int | None, limit: int,
          resolve_events: bool, now_ns: int) -> dict[str, Any]:
    """Page open markets and tabulate. Returns a JSON-serialisable summary."""
    acc = ProbeAccumulator()
    event_cache: dict[str, tuple[str, str]] = {}
    open_market_objs = []   # for re-running select_orders exactly as the harness does

    def _event(event_ticker: str) -> tuple[str, str]:
        if not event_ticker:
            return "", ""
        if event_ticker in event_cache:
            return event_cache[event_ticker]
        if not resolve_events:
            event_cache[event_ticker] = ("", "")
            return "", ""
        try:
            ev = client.get_event(event_ticker)
            res = (str(ev.get("series_ticker") or ""), str(ev.get("category") or ""))
        except KalshiAPIError as e:
            log.warning("event lookup failed %s: %s", event_ticker, e)
            res = ("", "")
        event_cache[event_ticker] = res
        return res

    try:
        for market, _cursor in client.iter_settled_markets(
                limit=limit, max_pages=max_pages, status="open"):
            acc.n_seen += 1
            event_ticker = str(market.get("event_ticker") or "")
            series, category = _event(event_ticker)
            mve = _is_mve(market, category)
            mve_label = "MVE" if mve else "non-MVE"
            acc.mve_counts[mve_label] += 1
            acc.cat_counts[(category or "(unknown)").strip().lower() or "(blank)"] += 1

            om = extract_open_market(market, series, category)
            if om is None:
                continue
            acc.n_priced += 1
            open_market_objs.append(om)

            bucket = _price_bucket(om.yes_price)
            if bucket is not None:
                acc.bucket_counts[bucket] += 1
            ttc_s = (om.close_time - now_ns) / 1e9 if om.close_time > 0 else float("nan")
            ttc = _ttc_stratum(ttc_s)
            acc.ttc_counts[ttc] += 1
            if bucket is not None:
                acc.cross[mve_label][bucket][ttc] += 1

            is_extreme = bucket in EXTREME_BUCKETS
            holdable = math.isfinite(ttc_s) and ttc_s >= ENTER_AND_HOLD_MIN_SECONDS
            has_quote = math.isfinite(om.yes_bid) and math.isfinite(om.yes_ask)
            has_vol = math.isfinite(om.volume_fp) and om.volume_fp > 0
            if is_extreme and holdable and has_quote and has_vol:
                if mve:
                    acc.mve_extreme_holdable += 1
                else:
                    acc.nonmve_extreme_holdable += 1
            if mve and is_extreme and has_quote and has_vol:
                acc.mve_extreme_any_ttc += 1
    except RateLimitedError as e:
        log.error("rate limited during probe: %s", e)

    # Re-run the EXACT harness rule on the collected open markets so the probe's
    # "would journal" count is the same code path as paper_trader.place.
    default_orders = select_orders(open_market_objs, DEFAULT_RULE_SPEC)

    return {
        "n_seen": acc.n_seen,
        "n_priced": acc.n_priced,
        "n_distinct_events": len(event_cache),
        "events_resolved": resolve_events,
        "mve_split": dict(acc.mve_counts),
        "category_counts": dict(acc.cat_counts.most_common()),
        "price_bucket_counts": {lbl: acc.bucket_counts.get(lbl, 0)
                                for _, _, lbl in PRICE_BUCKETS},
        "ttc_counts": {lbl: acc.ttc_counts.get(lbl, 0) for _, _, lbl in TTC_STRATA},
        "cross_tab": {
            mve_label: {
                bucket: dict(ttc_counter)
                for bucket, ttc_counter in buckets.items()
            }
            for mve_label, buckets in acc.cross.items()
        },
        "eligibility": {
            "default_rule_would_journal": len(default_orders),
            "nonmve_extreme_holdable": acc.nonmve_extreme_holdable,
            "mve_extreme_holdable": acc.mve_extreme_holdable,
            "mve_extreme_any_ttc": acc.mve_extreme_any_ttc,
        },
    }


def render(summary: dict[str, Any]) -> str:
    lines: list[str] = []
    lines.append(f"seen={summary['n_seen']}  priced={summary['n_priced']}  "
                 f"distinct_events={summary['n_distinct_events']}  "
                 f"events_resolved={summary['events_resolved']}")
    lines.append("")
    lines.append("MVE split: " + ", ".join(
        f"{k}={v}" for k, v in summary["mve_split"].items()))
    lines.append("")
    lines.append("Category counts (top 15):")
    for cat, n in list(summary["category_counts"].items())[:15]:
        lines.append(f"  {cat:32s} {n}")
    lines.append("")
    lines.append("Price-bucket counts (YES price):")
    for lbl, n in summary["price_bucket_counts"].items():
        mark = "  <-- extreme" if lbl in EXTREME_BUCKETS else ""
        lines.append(f"  {lbl:10s} {n}{mark}")
    lines.append("")
    lines.append("Time-to-close strata:")
    for lbl, n in summary["ttc_counts"].items():
        lines.append(f"  {lbl:14s} {n}")
    lines.append("")
    lines.append("Cross-tab  (MVE/non-MVE x price-bucket x time-to-close):")
    for mve_label, buckets in summary["cross_tab"].items():
        lines.append(f"  [{mve_label}]")
        for bucket in (lbl for _, _, lbl in PRICE_BUCKETS):
            ttcs = buckets.get(bucket)
            if not ttcs:
                continue
            extreme = "  *extreme*" if bucket in EXTREME_BUCKETS else ""
            detail = ", ".join(f"{t}={c}" for t, c in ttcs.items())
            lines.append(f"    {bucket:10s} {detail}{extreme}")
    lines.append("")
    el = summary["eligibility"]
    lines.append("ELIGIBILITY (per full sweep of the paged universe):")
    lines.append(f"  DEFAULT_RULE_SPEC would journal (non-MVE, extreme, quote, vol>0): "
                 f"{el['default_rule_would_journal']}")
    lines.append(f"  non-MVE & extreme & holdable(>=1h) & quote & vol>0:            "
                 f"{el['nonmve_extreme_holdable']}")
    lines.append(f"  MVE     & extreme & holdable(>=1h) & quote & vol>0:            "
                 f"{el['mve_extreme_holdable']}")
    lines.append(f"  MVE     & extreme & any-ttc        & quote & vol>0:            "
                 f"{el['mve_extreme_any_ttc']}")
    return "\n".join(lines)


def main(argv: Iterable[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Probe the live Kalshi open universe (read-only).")
    p.add_argument("--max-pages", type=int, default=10)
    p.add_argument("--limit-per-page", type=int, default=200)
    p.add_argument("--rate-limit-seconds", type=float, default=0.2)
    p.add_argument("--no-events", action="store_true",
                   help="Skip per-event category lookups (faster; MVE from markers only).")
    p.add_argument("--json", type=Path, default=None, help="Write the summary JSON here.")
    p.add_argument("--verbose", "-v", action="count", default=0)
    args = p.parse_args(list(argv) if argv is not None else None)
    logging.basicConfig(level=max(logging.WARNING - 10 * args.verbose, logging.DEBUG),
                        format="%(asctime)s %(levelname)s %(name)s: %(message)s")

    import time
    now_ns = int(time.time() * 1_000_000_000)
    client = KalshiClient(KalshiClientConfig(rate_limit_seconds=args.rate_limit_seconds))
    summary = probe(client, max_pages=args.max_pages, limit=args.limit_per_page,
                    resolve_events=not args.no_events, now_ns=now_ns)
    print(render(summary))
    if args.json is not None:
        args.json.parent.mkdir(parents=True, exist_ok=True)
        args.json.write_text(json.dumps(summary, indent=2))
        print(f"\nwrote {args.json}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
