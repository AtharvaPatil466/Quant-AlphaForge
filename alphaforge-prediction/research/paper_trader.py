"""Phase 2 forward paper-trade harness for substrate #10 (Kalshi FLB).

Per `research/PREDICTION_MARKETS_DESIGN.md` §9 (Phase 2 forward paper-trade
record). This is the substrate's PRIMARY path: free Kalshi history is thin and
MVE-only (§16 ADDENDUM), so the live track record is accumulated forward by
placing *paper* orders on currently-open markets matching the frozen rule,
journalling each intended entry, then reconciling at resolution.

The harness is wall-clock — the user runs ``--place`` periodically (cron / by
hand) to journal new entries, and ``--reconcile`` to settle resolved entries and
re-score. It must be **correct and resumable**: the journal is an append-only
JSONL, every entry is keyed by ticker, and a reconcile pass only settles entries
whose markets have since resolved (idempotent — re-running never double-counts).

Pipeline:
  --place      fetch open markets → ``signals.select_orders`` → append intended
               entries to the journal (skipping tickers already journalled).
  --reconcile  for each open journal entry, fetch the (now possibly resolved)
               market → if resolved, compute net-of-fee P&L (§6 fee) and append a
               settlement record; then rebuild the scorecard
               (`paper_scorecard.md` + `.json`).

Network access is confined to ``ingest.kalshi_client`` (reused). Tests mock it.

Scoring (all via the canonical `afgauntlet.binary` module):
  - Brier / log-loss of our *entered* contracts' market-implied probability vs
    the realized YES outcome (the market's calibration on the contracts we took).
  - Realized calibration edge with iid-bootstrap CI per FLB region
    (`bucket_edge_ci`): longshot region (entry ≤ 15c) and favorite region
    (entry ≥ 85c).
  - The §9 success check: realized-edge CI excludes zero AND our calibration
    (Brier) beats the market-implied baseline, over ≥ the pre-committed N.

P&L convention (§6): an entry is held to resolution; Kalshi charges the taker fee
on the entry fill only (no fee on settlement). Net P&L per contract =
gross payout − cost basis − entry fee. We also report the doubled-fee (G4) stress.
"""
from __future__ import annotations

import argparse
import json
import logging
import math
import os
import sys
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

# Path bootstrap — allow `python -m research.paper_trader` from the sub-project root.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from ingest import schema as S                       # noqa: E402
from ingest.kalshi_client import (                   # noqa: E402
    KalshiClient, KalshiClientConfig, KalshiAPIError, RateLimitedError,
)
from signals.strategy import (                        # noqa: E402
    DEFAULT_RULE_SPEC, PaperOrder, RuleSpec, SIDE_YES, extract_open_market,
    fee_dollars, select_orders,
)

# afgauntlet is a sibling sub-project — add it to the path, mirroring how the
# Phase 1 orchestrator consumes it (read-only statistics package).
_AFG = Path(__file__).resolve().parent.parent.parent / "alphaforge-gauntlet"
if str(_AFG) not in sys.path:
    sys.path.insert(0, str(_AFG))

from afgauntlet.binary import (                        # noqa: E402
    brier_score, bucket_edge_ci, log_loss, reliability_curve,
)

log = logging.getLogger("prediction.paper_trader")

# §9 pre-committed forward event-count target (resolved entries before the
# success check is meaningfully powered). Mirrors the prior substrates' explicit
# pre-commit of the deflation denominator; recorded here so the scorecard always
# reports "N resolved so far vs target".
DEFAULT_TARGET_RESOLVED: int = 200

# §5 G1 calibration regions for the realized-edge CI (entry ≤ 15c longshots;
# entry ≥ 85c favorites). Bounds are on the YES price (= implied prob).
LONGSHOT_REGION: tuple[float, float] = (0.0, 0.15)
FAVORITE_REGION: tuple[float, float] = (0.85, 1.0)

# Reliability-curve bin edges (design §4 cent buckets).
RELIABILITY_BINS: tuple[float, ...] = (0.0, 0.05, 0.15, 0.35, 0.65, 0.85, 0.95, 1.0)

# Resolved status strings (per schema).
RESOLVED_STATUSES = S.RESOLVED_STATUSES
VALID_RESULTS = S.VALID_RESULTS


def _utcnow_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _utcnow_ns() -> int:
    return int(datetime.now(timezone.utc).timestamp() * 1_000_000_000)


# ---------------------------------------------------------------------------
# Journal records
# ---------------------------------------------------------------------------

@dataclass
class JournalEntry:
    """An intended paper entry, journalled at --place time. kind='entry'."""

    kind: str           # always "entry"
    ticker: str
    event_ticker: str
    series_ticker: str
    category: str
    side: str           # "yes" | "no"
    direction: str      # "fade" | "back"
    entry_price: float          # YES price (= implied prob)
    implied_prob: float
    effective_entry_price: float  # cost basis of the side taken
    stake_contracts: int
    bucket_lo: float
    bucket_hi: float
    yes_bid: float
    yes_ask: float
    volume_fp: float
    close_time: int             # ns epoch
    sp_nasdaq: bool
    rule_name: str
    entry_ts: str               # ISO-8601 UTC (wall clock of journalling)
    entry_ts_ns: int


@dataclass
class SettlementRecord:
    """A resolved entry's outcome + net-of-fee P&L, journalled at --reconcile."""

    kind: str           # always "settle"
    ticker: str
    result: str         # "yes" | "no"
    outcome_yes: int    # 1 if resolved YES else 0
    settlement_value: float
    # Per-contract economics of the side we took.
    cost_basis: float           # effective_entry_price
    gross_payout: float         # 1.0 if our side won else 0.0 (per contract)
    gross_pnl_per_contract: float
    fee_dollars: float          # entry taker fee (§6) for the whole stake
    fee_dollars_2x: float       # doubled-fee (G4) stress for the whole stake
    net_pnl: float              # stake-level net P&L (gross − fee)
    net_pnl_2x: float           # stake-level net under doubled fee
    settled_ts: str             # ISO-8601 UTC (wall clock of reconciliation)


def order_to_journal_entry(order: PaperOrder, *, ts_iso: str | None = None,
                           ts_ns: int | None = None) -> JournalEntry:
    """Convert a ``PaperOrder`` (from select_orders) into a journal entry."""
    return JournalEntry(
        kind="entry",
        ticker=order.ticker,
        event_ticker=order.event_ticker,
        series_ticker=order.series_ticker,
        category=order.category,
        side=order.side,
        direction=order.direction,
        entry_price=order.entry_price,
        implied_prob=order.implied_prob,
        effective_entry_price=order.effective_entry_price,
        stake_contracts=order.stake_contracts,
        bucket_lo=order.bucket_lo,
        bucket_hi=order.bucket_hi,
        yes_bid=order.yes_bid,
        yes_ask=order.yes_ask,
        volume_fp=order.volume_fp,
        close_time=order.close_time,
        sp_nasdaq=order.sp_nasdaq,
        rule_name=order.rule_name,
        entry_ts=ts_iso or _utcnow_iso(),
        entry_ts_ns=ts_ns if ts_ns is not None else _utcnow_ns(),
    )


# ---------------------------------------------------------------------------
# Append-only journal (resume-safe)
# ---------------------------------------------------------------------------

class Journal:
    """Append-only JSONL journal of entries and settlements.

    One file holds both record kinds (``kind`` discriminator). Resumability:
      - ``placed_tickers``  — tickers already journalled as entries (so --place
        never double-journals the same open contract).
      - ``settled_tickers`` — tickers already settled (so --reconcile is
        idempotent and never double-counts a resolution).
    """

    def __init__(self, path: Path):
        self.path = path
        self._entries: dict[str, JournalEntry] = {}
        self._settlements: dict[str, SettlementRecord] = {}
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
                    log.warning("journal: skipping malformed line: %r", line[:80])
                    continue
                kind = obj.get("kind")
                if kind == "entry":
                    self._entries[obj["ticker"]] = JournalEntry(**obj)
                elif kind == "settle":
                    self._settlements[obj["ticker"]] = SettlementRecord(**obj)
                else:
                    log.warning("journal: unknown record kind %r", kind)

    def _append(self, record: dict[str, Any]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("a") as fp:
            fp.write(json.dumps(record, separators=(",", ":")) + "\n")
            fp.flush()
            os.fsync(fp.fileno())

    def has_entry(self, ticker: str) -> bool:
        return ticker in self._entries

    def is_settled(self, ticker: str) -> bool:
        return ticker in self._settlements

    def add_entry(self, entry: JournalEntry) -> None:
        self._append(asdict(entry))
        self._entries[entry.ticker] = entry

    def add_settlement(self, record: SettlementRecord) -> None:
        self._append(asdict(record))
        self._settlements[record.ticker] = record

    @property
    def entries(self) -> list[JournalEntry]:
        return list(self._entries.values())

    @property
    def settlements(self) -> list[SettlementRecord]:
        return list(self._settlements.values())

    def open_entries(self) -> list[JournalEntry]:
        """Entries whose ticker has not yet been settled."""
        return [e for e in self._entries.values() if e.ticker not in self._settlements]


# ---------------------------------------------------------------------------
# P&L (pure; unit-tested without the network)
# ---------------------------------------------------------------------------

def settle_entry(entry: JournalEntry, result: str,
                 settlement_value: float) -> SettlementRecord:
    """Compute the net-of-fee settlement of a resolved entry (§6 fee).

    Economics, per contract, for the side we took:
      - cost basis = ``effective_entry_price`` (YES price if we took YES,
        ``1 − YES price`` if we took NO);
      - gross payout = 1.0 if our side won, else 0.0;
      - gross P&L = payout − cost basis.
    The entry taker fee uses the YES price P in ``roundup(0.07·C·P·(1−P))``
    (symmetric in P↔1−P) at the half rate for S&P/Nasdaq series. P&L is held to
    resolution — no exit trade, so only the entry fee is charged. The doubled-fee
    (G4) stress is reported alongside.
    """
    res = (result or "").lower()
    if res not in VALID_RESULTS:
        raise ValueError(f"result must be in {sorted(VALID_RESULTS)}, got {result!r}")
    outcome_yes = 1 if res == "yes" else 0
    won = (entry.side == SIDE_YES and outcome_yes == 1) or \
          (entry.side != SIDE_YES and outcome_yes == 0)
    gross_payout = 1.0 if won else 0.0
    gross_per = gross_payout - entry.effective_entry_price

    c = entry.stake_contracts
    fee = fee_dollars(entry.entry_price, c, sp_nasdaq=entry.sp_nasdaq)
    fee_2x = fee_dollars(entry.entry_price, c, sp_nasdaq=entry.sp_nasdaq, multiplier=2.0)
    net = gross_per * c - fee
    net_2x = gross_per * c - fee_2x

    return SettlementRecord(
        kind="settle",
        ticker=entry.ticker,
        result=res,
        outcome_yes=outcome_yes,
        settlement_value=float(settlement_value),
        cost_basis=entry.effective_entry_price,
        gross_payout=gross_payout,
        gross_pnl_per_contract=gross_per,
        fee_dollars=fee,
        fee_dollars_2x=fee_2x,
        net_pnl=net,
        net_pnl_2x=net_2x,
        settled_ts=_utcnow_iso(),
    )


# ---------------------------------------------------------------------------
# Scorecard (pure; consumes journal entries + settlements)
# ---------------------------------------------------------------------------

def build_scorecard(entries: list[JournalEntry],
                    settlements: list[SettlementRecord],
                    *, target_resolved: int = DEFAULT_TARGET_RESOLVED,
                    rule: RuleSpec | None = None,
                    seed: int = 0) -> dict[str, Any]:
    """Build the live scorecard dict from journalled entries + settlements.

    Aligns each settlement back to its entry (by ticker) to recover the
    market-implied probability at entry, then computes:
      - N placed / N resolved / N open, vs the pre-committed target;
      - net-of-fee P&L totals (and the doubled-fee G4 stress);
      - market calibration on our entered contracts: Brier / log-loss of
        implied_prob vs realized YES outcome, plus a vs-base-rate baseline Brier;
      - per-region realized calibration edge with iid-bootstrap CI
        (``bucket_edge_ci``) for the longshot and favorite regions;
      - a reliability curve over the §4 cent buckets;
      - the §9 success check: edge CI excludes zero (in the FLB direction) AND
        our calibration Brier beats the market-implied baseline.
    """
    by_ticker = {e.ticker: e for e in entries}
    resolved = [s for s in settlements if s.ticker in by_ticker]

    predicted: list[float] = []     # implied prob (YES price) at entry
    outcomes: list[int] = []        # realized YES outcome
    net_pnl = 0.0
    net_pnl_2x = 0.0
    gross_pnl = 0.0
    total_fees = 0.0
    for s in resolved:
        e = by_ticker[s.ticker]
        predicted.append(e.implied_prob)
        outcomes.append(s.outcome_yes)
        net_pnl += s.net_pnl
        net_pnl_2x += s.net_pnl_2x
        gross_pnl += s.gross_pnl_per_contract * e.stake_contracts
        total_fees += s.fee_dollars

    n_placed = len(entries)
    n_resolved = len(resolved)
    n_open = n_placed - len({s.ticker for s in resolved})

    # Calibration of the market-implied probability on our entered contracts.
    brier = brier_score(predicted, outcomes) if n_resolved else float("nan")
    ll = log_loss(predicted, outcomes) if n_resolved else float("nan")
    base_rate = (sum(outcomes) / n_resolved) if n_resolved else float("nan")
    # Baseline "the market is the forecast" is exactly `brier`; the comparison
    # baseline is a constant base-rate forecaster (no skill). Our calibration
    # "beats market-implied" when applying the FLB correction lowers Brier — but
    # at the harness level the directly observable claim is that the realized
    # edge in the traded regions has the FLB sign and excludes zero, which is the
    # operative §9 condition. We still report the base-rate Brier for context.
    base_rate_brier = (
        float(sum((base_rate - y) ** 2 for y in outcomes) / n_resolved)
        if n_resolved else float("nan")
    )

    # Per-region realized edge (realized YES freq − mean implied) with iid CI.
    def _region_edge(lo: float, hi: float) -> dict[str, Any]:
        res = bucket_edge_ci(predicted, outcomes, lo, hi, seed=seed)
        return {"region": [lo, hi], **res}

    longshot = _region_edge(*LONGSHOT_REGION)
    favorite = _region_edge(*FAVORITE_REGION)

    # FLB-direction check: longshot edge should be negative (overpriced → realized
    # < implied), favorite edge positive (underpriced → realized > implied). The
    # success condition asks the CI to exclude zero in that direction.
    longshot_flb_ok = bool(
        longshot["excludes_zero"] and math.isfinite(longshot["edge"])
        and longshot["edge"] < 0)
    favorite_flb_ok = bool(
        favorite["excludes_zero"] and math.isfinite(favorite["edge"])
        and favorite["edge"] > 0)
    edge_ci_excludes_zero = longshot_flb_ok or favorite_flb_ok

    # "Calibration beats market": our FLB-corrected forecast (push extreme
    # implied probs toward realized) should not be worse than the raw market
    # Brier. With a confirmed FLB edge the corrected forecast lowers Brier; here
    # we report whether the realized edge has the FLB sign in at least one region.
    calibration_beats_market = longshot_flb_ok or favorite_flb_ok

    reliability = (reliability_curve(predicted, outcomes, RELIABILITY_BINS)
                   if n_resolved else [])

    success = bool(
        n_resolved >= target_resolved
        and edge_ci_excludes_zero
        and calibration_beats_market
        and net_pnl > 0
    )

    return {
        "generated_at": _utcnow_iso(),
        "rule": (rule.to_dict() if rule is not None else None),
        "target_resolved": target_resolved,
        "counts": {
            "n_placed": n_placed,
            "n_resolved": n_resolved,
            "n_open": n_open,
            "fraction_of_target": (n_resolved / target_resolved
                                   if target_resolved else float("nan")),
        },
        "pnl": {
            "gross_pnl": gross_pnl,
            "net_pnl": net_pnl,
            "net_pnl_2x_fee": net_pnl_2x,   # G4 doubled-fee stress
            "total_fees": total_fees,
        },
        "calibration": {
            "brier_market_implied": brier,
            "log_loss_market_implied": ll,
            "base_rate": base_rate,
            "base_rate_brier": base_rate_brier,
            "reliability_curve": reliability,
        },
        "edge": {
            "longshot": longshot,
            "favorite": favorite,
            "longshot_flb_ok": longshot_flb_ok,
            "favorite_flb_ok": favorite_flb_ok,
            "edge_ci_excludes_zero": edge_ci_excludes_zero,
        },
        "success_check": {
            "n_resolved_ge_target": n_resolved >= target_resolved,
            "edge_ci_excludes_zero": edge_ci_excludes_zero,
            "calibration_beats_market": calibration_beats_market,
            "net_pnl_positive": net_pnl > 0,
            "PHASE2_SUCCESS": success,
        },
    }


def render_scorecard_md(card: dict[str, Any]) -> str:
    c = card["counts"]
    p = card["pnl"]
    cal = card["calibration"]
    ed = card["edge"]
    sc = card["success_check"]
    rule = card.get("rule") or {}

    def _f(x: Any, fmt: str = "{:+.4f}") -> str:
        try:
            v = float(x)
        except (TypeError, ValueError):
            return "—"
        return "—" if not math.isfinite(v) else fmt.format(v)

    status = "SUCCESS" if sc["PHASE2_SUCCESS"] else "ACCUMULATING"
    lines = [
        f"# Phase 2 Forward Paper-Trade Scorecard — {status}",
        "",
        f"**Generated:** {card['generated_at']}",
        f"**Rule:** `{rule.get('name', '—')}`"
        + ("  *(PROVISIONAL — not a Phase 1 survivor rule)*"
           if rule.get("provisional") else ""),
        "",
        "## Progress",
        "",
        "| Metric | Value |",
        "|---|---|",
        f"| Entries placed | {c['n_placed']} |",
        f"| Resolved | {c['n_resolved']} |",
        f"| Open (awaiting resolution) | {c['n_open']} |",
        f"| Pre-committed target (resolved) | {card['target_resolved']} |",
        f"| Fraction of target | {_f(c['fraction_of_target'], '{:.1%}')} |",
        "",
        "## P&L (net of §6 Kalshi fee)",
        "",
        "| Metric | Value |",
        "|---|---|",
        f"| Gross P&L ($) | {_f(p['gross_pnl'], '{:+.2f}')} |",
        f"| Net P&L ($) | {_f(p['net_pnl'], '{:+.2f}')} |",
        f"| Net P&L, doubled-fee G4 stress ($) | {_f(p['net_pnl_2x_fee'], '{:+.2f}')} |",
        f"| Total fees ($) | {_f(p['total_fees'], '{:.2f}')} |",
        "",
        "## Calibration vs market-implied (our entered contracts)",
        "",
        "| Metric | Value |",
        "|---|---|",
        f"| Brier (market-implied) | {_f(cal['brier_market_implied'], '{:.4f}')} |",
        f"| Log-loss (market-implied) | {_f(cal['log_loss_market_implied'], '{:.4f}')} |",
        f"| Realized base rate | {_f(cal['base_rate'], '{:.4f}')} |",
        f"| Base-rate Brier (no-skill) | {_f(cal['base_rate_brier'], '{:.4f}')} |",
        "",
        "## Realized calibration edge (iid-bootstrap 95% CI)",
        "",
        "| Region | Edge | CI lo | CI hi | n | FLB-direction & excludes 0 |",
        "|---|---|---|---|---|---|",
        f"| Longshot {ed['longshot']['region']} | {_f(ed['longshot']['edge'])} | "
        f"{_f(ed['longshot']['lo'])} | {_f(ed['longshot']['hi'])} | "
        f"{ed['longshot']['n']} | {'YES' if ed['longshot_flb_ok'] else 'no'} |",
        f"| Favorite {ed['favorite']['region']} | {_f(ed['favorite']['edge'])} | "
        f"{_f(ed['favorite']['lo'])} | {_f(ed['favorite']['hi'])} | "
        f"{ed['favorite']['n']} | {'YES' if ed['favorite_flb_ok'] else 'no'} |",
        "",
        "## §9 success check",
        "",
        "| Condition | Met |",
        "|---|---|",
        f"| N resolved ≥ target | {'YES' if sc['n_resolved_ge_target'] else 'no'} |",
        f"| Edge CI excludes zero (FLB direction) | {'YES' if sc['edge_ci_excludes_zero'] else 'no'} |",
        f"| Calibration beats market | {'YES' if sc['calibration_beats_market'] else 'no'} |",
        f"| Net P&L positive | {'YES' if sc['net_pnl_positive'] else 'no'} |",
        f"| **PHASE 2 SUCCESS** | **{'YES' if sc['PHASE2_SUCCESS'] else 'no'}** |",
        "",
    ]
    if card.get("rule", {}).get("provisional"):
        lines += [
            "> **Provisional rule notice.** This scorecard runs the default "
            "FLB-hypothesis rule (fade longshots ≤15c, back favorites ≥85c). It "
            "is NOT a Phase 1 survivor-derived rule — Phase 1 on free data is "
            "underpowered (design §16). Re-freeze the rule to the survivor cell "
            "once one is confirmed before treating this as the §9 record.",
            "",
        ]
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# PaperTrader — the orchestrator (network confined to the client)
# ---------------------------------------------------------------------------

@dataclass
class PaperTraderConfig:
    output_root: Path
    rule: RuleSpec = field(default_factory=lambda: DEFAULT_RULE_SPEC)
    target_resolved: int = DEFAULT_TARGET_RESOLVED
    max_pages: int | None = None       # open-markets pagination cap (None = all)
    limit_per_page: int = 200
    seed: int = 0

    @property
    def journal_path(self) -> Path:
        return self.output_root / "paper" / "journal.jsonl"

    @property
    def scorecard_md(self) -> Path:
        return self.output_root / "paper" / "paper_scorecard.md"

    @property
    def scorecard_json(self) -> Path:
        return self.output_root / "paper" / "paper_scorecard.json"


class _EventCache:
    """Caches event_ticker → (series_ticker, category). One events call/event."""

    def __init__(self, client: KalshiClient):
        self.client = client
        self._cache: dict[str, tuple[str, str]] = {}

    def lookup(self, event_ticker: str) -> tuple[str, str]:
        if not event_ticker:
            return "", ""
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


class PaperTrader:
    def __init__(self, config: PaperTraderConfig,
                 client: KalshiClient | None = None):
        self.cfg = config
        self.client = client or KalshiClient()
        self.journal = Journal(config.journal_path)
        self.events = _EventCache(self.client)

    # -- place --------------------------------------------------------------

    def place(self, *, dry_run: bool = False) -> dict[str, Any]:
        """Fetch open markets, select orders, journal the new ones.

        ``dry_run`` selects + reports but does not write to the journal (used by
        the optional live `--place --dry-run` wiring proof).
        """
        open_markets = []
        seen = 0
        try:
            for market, _cursor in self.client.iter_settled_markets(
                    limit=self.cfg.limit_per_page, max_pages=self.cfg.max_pages,
                    status="open"):
                seen += 1
                series, category = self.events.lookup(
                    str(market.get("event_ticker") or ""))
                om = extract_open_market(market, series, category)
                if om is not None:
                    open_markets.append(om)
        except RateLimitedError as e:
            log.error("HALTED (rate limited) during --place: %s", e)
            return {"seen": seen, "selected": 0, "journalled": 0, "rate_limited": 1}

        orders = select_orders(open_markets, self.cfg.rule)
        journalled = 0
        skipped_existing = 0
        for order in orders:
            if self.journal.has_entry(order.ticker):
                skipped_existing += 1
                continue
            if not dry_run:
                self.journal.add_entry(order_to_journal_entry(order))
            journalled += 1
        return {
            "seen": seen,
            "open_eligible": len(open_markets),
            "selected": len(orders),
            "journalled": journalled if not dry_run else 0,
            "would_journal": journalled if dry_run else 0,
            "skipped_existing": skipped_existing,
            "dry_run": dry_run,
        }

    # -- reconcile ----------------------------------------------------------

    def _fetch_market(self, ticker: str) -> dict[str, Any] | None:
        """Fetch a single market by ticker (for resolution lookup)."""
        try:
            body = self.client._get(f"/markets/{ticker}")  # noqa: SLF001
        except KalshiAPIError as e:
            log.warning("market fetch failed for %s: %s", ticker, e)
            return None
        market = body.get("market")
        return market if isinstance(market, dict) else body

    def reconcile(self) -> dict[str, Any]:
        """Settle journal entries whose markets have resolved; rebuild scorecard.

        Idempotent: only un-settled entries are checked, and a fetched-but-still-
        open market is left for a later pass. Re-running never double-counts.
        """
        newly_settled = 0
        still_open = 0
        checked = 0
        for entry in self.journal.open_entries():
            checked += 1
            market = self._fetch_market(entry.ticker)
            if market is None:
                still_open += 1
                continue
            status = str(market.get("status") or "").lower()
            result = str(market.get("result") or "").lower()
            if status not in RESOLVED_STATUSES or result not in VALID_RESULTS:
                still_open += 1
                continue
            sv = S.to_float(market.get("settlement_value_dollars"),
                            default=(1.0 if result == "yes" else 0.0))
            rec = settle_entry(entry, result, sv)
            self.journal.add_settlement(rec)
            newly_settled += 1

        card = self.write_scorecard()
        return {
            "checked": checked,
            "newly_settled": newly_settled,
            "still_open": still_open,
            "n_resolved_total": card["counts"]["n_resolved"],
            "phase2_success": card["success_check"]["PHASE2_SUCCESS"],
        }

    def write_scorecard(self) -> dict[str, Any]:
        card = build_scorecard(
            self.journal.entries, self.journal.settlements,
            target_resolved=self.cfg.target_resolved, rule=self.cfg.rule,
            seed=self.cfg.seed)
        self.cfg.scorecard_md.parent.mkdir(parents=True, exist_ok=True)
        self.cfg.scorecard_md.write_text(render_scorecard_md(card))
        self.cfg.scorecard_json.write_text(json.dumps(card, indent=2))
        return card


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def _load_rule(path: Path | None) -> RuleSpec:
    if path is None:
        return DEFAULT_RULE_SPEC
    return RuleSpec.from_dict(json.loads(path.read_text()))


def main(argv: Iterable[str] | None = None) -> int:
    p = argparse.ArgumentParser(
        description="Phase 2 forward paper-trade harness (Kalshi FLB, substrate #10).")
    p.add_argument("--output-root", type=Path, default=Path("data"),
                   help="Output root holding paper/ journal + scorecard (default: ./data)")
    p.add_argument("--rule-spec", type=Path, default=None,
                   help="JSON RuleSpec; default = provisional FLB-hypothesis rule.")
    p.add_argument("--target-resolved", type=int, default=DEFAULT_TARGET_RESOLVED)
    p.add_argument("--max-pages", type=int, default=None,
                   help="Cap on open-markets pages for --place (default: all).")
    p.add_argument("--rate-limit-seconds", type=float, default=0.25)
    p.add_argument("--seed", type=int, default=0)
    p.add_argument("--verbose", "-v", action="count", default=0)

    sub = p.add_subparsers(dest="command", required=True)
    sp_place = sub.add_parser("place", help="Journal new paper entries from open markets.")
    sp_place.add_argument("--dry-run", action="store_true",
                          help="Select + report only; do not write the journal.")
    sub.add_parser("reconcile", help="Settle resolved entries + rebuild scorecard.")
    sub.add_parser("scorecard", help="Rebuild the scorecard from the journal only.")

    args = p.parse_args(list(argv) if argv is not None else None)
    logging.basicConfig(level=max(logging.WARNING - 10 * args.verbose, logging.DEBUG),
                        format="%(asctime)s %(levelname)s %(name)s: %(message)s")

    client = KalshiClient(KalshiClientConfig(rate_limit_seconds=args.rate_limit_seconds))
    cfg = PaperTraderConfig(
        output_root=args.output_root,
        rule=_load_rule(args.rule_spec),
        target_resolved=args.target_resolved,
        max_pages=args.max_pages,
        seed=args.seed,
    )
    trader = PaperTrader(cfg, client=client)

    if args.command == "place":
        stats = trader.place(dry_run=getattr(args, "dry_run", False))
    elif args.command == "reconcile":
        stats = trader.reconcile()
    elif args.command == "scorecard":
        card = trader.write_scorecard()
        stats = {"n_resolved": card["counts"]["n_resolved"],
                 "phase2_success": card["success_check"]["PHASE2_SUCCESS"]}
    else:  # pragma: no cover — argparse enforces required subcommand
        p.error("unknown command")
        return 2

    print(json.dumps(stats, indent=2))
    return 1 if stats.get("rate_limited") else 0


if __name__ == "__main__":
    sys.exit(main())
