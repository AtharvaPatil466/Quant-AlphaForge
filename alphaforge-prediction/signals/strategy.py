"""Phase 2 rule layer — turn open Kalshi markets into intended paper entries.

Per `research/PREDICTION_MARKETS_DESIGN.md` §9 (Phase 2 forward paper-trade
record). The favorite-longshot bias (FLB) hypothesis says low-price ("longshot")
YES contracts resolve YES *less* often than priced and high-price ("favorite")
contracts resolve YES *more* often than priced. A tradeable rule therefore:

  - **fades** longshots — i.e. takes the **NO** side of a low-priced YES contract;
  - **backs** favorites — i.e. takes the **YES** side of a high-priced YES contract.

This module is the deterministic, unit-testable rule layer. It contains NO
network access and NO calibration statistic — it only decides *which* currently
open contracts to enter and *on which side*, given a frozen-able ``RuleSpec``.

IMPORTANT — provisional default rule
------------------------------------
Phase 1 on free Kalshi data is EXPECTED to be UNDERPOWERED and category-narrow
(design §16 ADDENDUM), so there is **no frozen list of survivor buckets yet**.
``DEFAULT_RULE_SPEC`` is therefore a *provisional* rule derived directly from the
FLB hypothesis (fade longshots at entry ≤ 15c, back favorites at entry ≥ 85c),
not a survivor-derived rule. It is clearly labelled provisional and is meant to
be replaced by the deterministically-derived survivor rule once Phase 1 / forward
data confirms one. The harness is parameterized so swapping the spec is a config
change, not a code change.

Entry-price / implied-probability convention (matches `ingest/schema.py`):
prices are dollars in [0, 1]; the YES-contract price *is* the market-implied
probability of YES.
"""
from __future__ import annotations

import math
import time
from dataclasses import dataclass, field, replace
from typing import Any, Sequence

from ingest import schema as S

# Side conventions for a paper order on a Kalshi binary contract.
SIDE_YES: str = "yes"   # buy YES — bet the event resolves YES (back a favorite)
SIDE_NO: str = "no"     # buy NO  — bet the event resolves NO  (fade a longshot)
VALID_SIDES: frozenset[str] = frozenset({SIDE_YES, SIDE_NO})

# FLB directions for a price bucket.
DIR_FADE: str = "fade"   # bucket is an overpriced longshot → take NO
DIR_BACK: str = "back"   # bucket is an underpriced favorite → take YES
VALID_DIRECTIONS: frozenset[str] = frozenset({DIR_FADE, DIR_BACK})


# ---------------------------------------------------------------------------
# Fee model (frozen §6 — confirmed in the Phase 0 spike, SPIKE_NOTES.md (b)).
# ---------------------------------------------------------------------------

def fee_dollars(price: float, contracts: int, *, sp_nasdaq: bool = False,
                multiplier: float = 1.0) -> float:
    """Kalshi taker fee in dollars for a fill of ``contracts`` at ``price``.

    Frozen §6 schedule: ``fees = roundup(rate × C × P × (1 − P))`` with a
    whole-trade ceiling to the cent. ``rate`` is 0.07 general, 0.035 for the
    S&P 500 / Nasdaq-100 series. ``multiplier`` applies the G4 doubled-fee
    stress (pass 2.0). The cent-ceiling is applied AFTER the multiplier, matching
    the per-fill rounding on the live venue.

    Prices are clamped to [0, 1]; a non-positive contract count yields 0.
    """
    if contracts <= 0:
        return 0.0
    p = min(max(float(price), 0.0), 1.0)
    rate = (0.035 if sp_nasdaq else 0.07) * float(multiplier)
    raw = rate * contracts * p * (1.0 - p)
    # Whole-trade ceiling to the cent: ceil(raw * 100) / 100.
    return math.ceil(raw * 100.0 - 1e-9) / 100.0


# ---------------------------------------------------------------------------
# Rule spec
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class BucketRule:
    """One price-bucket rule: an entry-price band and the FLB direction to take.

    A contract whose entry price (YES price, dollars) falls in ``(lo, hi]`` is a
    candidate. ``direction`` is ``"fade"`` (take NO — overpriced longshot) or
    ``"back"`` (take YES — underpriced favorite). The first bucket of a spec is
    closed on the left (``lo`` inclusive) so a 0c contract is includable.
    """

    lo: float
    hi: float
    direction: str

    def __post_init__(self) -> None:
        if not (self.hi > self.lo):
            raise ValueError(f"bucket requires hi > lo, got ({self.lo}, {self.hi}]")
        if self.direction not in VALID_DIRECTIONS:
            raise ValueError(
                f"direction must be one of {sorted(VALID_DIRECTIONS)}, "
                f"got {self.direction!r}")

    @property
    def side(self) -> str:
        """The contract side this bucket trades: fade→NO, back→YES."""
        return SIDE_NO if self.direction == DIR_FADE else SIDE_YES

    def contains(self, price: float, *, left_closed: bool) -> bool:
        """Whether ``price`` falls in this bucket's band.

        ``left_closed`` makes the band ``[lo, hi]`` (used for the lowest bucket
        of a spec) rather than ``(lo, hi]``.
        """
        if not math.isfinite(price):
            return False
        if left_closed:
            return self.lo <= price <= self.hi
        return self.lo < price <= self.hi


@dataclass(frozen=True)
class RuleSpec:
    """A frozen-able Phase 2 trading rule.

    Attributes:
        name:          human label (e.g. "provisional-FLB-v0").
        provisional:   True until a survivor-derived rule replaces it. The
                       default rule is provisional (no Phase 1 survivor exists yet).
        buckets:       price-bucket rules; evaluated in order, first match wins.
        categories:    eligible event categories (case-insensitive). Empty set =
                       all categories eligible. MVE categories may be excluded so
                       the rule does not pool MVE with classic event markets
                       (design §16).
        max_stake_contracts: max contracts per paper entry (capacity cap; §0).
        min_volume_fp: only enter contracts whose lifetime volume exceeds this
                       (§7 liquidity filter).
        require_quote: only enter when a finite yes_bid AND yes_ask are present
                       (so the recorded entry crosses a real spread).
        sp_nasdaq_series_prefixes: series-ticker prefixes that get the half fee
                       rate (S&P 500 / Nasdaq-100); see §6.
        max_days_to_close: if set, only enter markets that resolve within this
                       many days. None = no cap (default). Targets near-term
                       markets where FLB is a genuine bias rather than far-future
                       time-value, and keeps the forward record on a useful
                       timescale. Provisional-forward tuning; does not touch the
                       frozen §4/§5 bands.
    """

    name: str
    provisional: bool
    buckets: tuple[BucketRule, ...]
    categories: frozenset[str] = field(default_factory=frozenset)
    max_stake_contracts: int = 10
    min_volume_fp: float = 0.0
    require_quote: bool = True
    sp_nasdaq_series_prefixes: tuple[str, ...] = ()
    max_days_to_close: float | None = None

    def __post_init__(self) -> None:
        if not self.buckets:
            raise ValueError("RuleSpec requires at least one bucket")
        if self.max_stake_contracts <= 0:
            raise ValueError("max_stake_contracts must be positive")
        # Normalise categories to lowercase for case-insensitive matching.
        object.__setattr__(
            self, "categories",
            frozenset(c.strip().lower() for c in self.categories if c.strip()))

    def category_eligible(self, category: str) -> bool:
        if not self.categories:
            return True
        return (category or "").strip().lower() in self.categories

    def is_sp_nasdaq(self, series_ticker: str) -> bool:
        st = (series_ticker or "").upper()
        return any(st.startswith(p.upper()) for p in self.sp_nasdaq_series_prefixes)

    def matching_bucket(self, price: float) -> BucketRule | None:
        """First bucket whose band contains ``price`` (lowest bucket left-closed)."""
        if not self.buckets:
            return None
        # The lowest-lo bucket is treated as left-closed so a 0c price is includable.
        min_lo = min(b.lo for b in self.buckets)
        for b in self.buckets:
            if b.contains(price, left_closed=(b.lo == min_lo)):
                return b
        return None

    def to_dict(self) -> dict[str, Any]:
        """JSON-serialisable spec (for journalling the rule that produced an entry)."""
        return {
            "name": self.name,
            "provisional": self.provisional,
            "buckets": [
                {"lo": b.lo, "hi": b.hi, "direction": b.direction}
                for b in self.buckets
            ],
            "categories": sorted(self.categories),
            "max_stake_contracts": self.max_stake_contracts,
            "min_volume_fp": self.min_volume_fp,
            "require_quote": self.require_quote,
            "sp_nasdaq_series_prefixes": list(self.sp_nasdaq_series_prefixes),
            "max_days_to_close": self.max_days_to_close,
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "RuleSpec":
        return cls(
            name=str(d["name"]),
            provisional=bool(d.get("provisional", True)),
            buckets=tuple(
                BucketRule(float(b["lo"]), float(b["hi"]), str(b["direction"]))
                for b in d["buckets"]
            ),
            categories=frozenset(d.get("categories", []) or []),
            max_stake_contracts=int(d.get("max_stake_contracts", 10)),
            min_volume_fp=float(d.get("min_volume_fp", 0.0)),
            require_quote=bool(d.get("require_quote", True)),
            sp_nasdaq_series_prefixes=tuple(d.get("sp_nasdaq_series_prefixes", []) or []),
            max_days_to_close=(float(d["max_days_to_close"])
                               if d.get("max_days_to_close") is not None else None),
        )

    def freeze(self, name: str | None = None) -> "RuleSpec":
        """Return a non-provisional copy (call once a survivor rule is derived)."""
        return replace(self, provisional=False,
                       name=name if name is not None else self.name)


# ---------------------------------------------------------------------------
# DEFAULT provisional rule — derived from the FLB hypothesis, NOT survivors.
# ---------------------------------------------------------------------------
#
# Longshot region (entry ≤ 15c): fade → take NO.
# Favorite region (entry ≥ 85c): back → take YES.
# Mirrors the design §5 G1 extreme regions and the §4 extreme buckets. The
# middle (15c, 85c] is intentionally untraded — FLB is an extremes effect.
#
# PROVISIONAL: there is no Phase 1 survivor cell yet (§16 — free data is thin /
# MVE-only). This rule exists so the forward harness can start accumulating a
# live record; it must be re-frozen to the survivor-derived rule once Phase 1 or
# the forward record confirms one.
DEFAULT_RULE_SPEC: RuleSpec = RuleSpec(
    name="provisional-FLB-v0",
    provisional=True,
    buckets=(
        BucketRule(0.0, 0.15, DIR_FADE),    # longshots ≤ 15c → fade (NO)
        BucketRule(0.85, 1.0, DIR_BACK),    # favorites ≥ 85c → back (YES)
    ),
    # §16: free Kalshi data is MVE-heavy ("Exotics"). Classic-FLB markets are
    # the eligible target; MVE is excluded so the forward record never pools the
    # two. Empty = all-eligible; we keep the non-MVE event categories explicitly.
    categories=frozenset({
        "economics", "financials", "politics", "weather", "climate",
        "science and technology", "world", "sports", "companies", "crypto",
    }),
    max_stake_contracts=10,
    min_volume_fp=0.0,          # §7: volume_fp > 0 (strictly) — enforced in select_orders
    require_quote=True,
    sp_nasdaq_series_prefixes=("KXINX", "KXNASDAQ100", "KXSPX", "KXNDX"),
)


# ---------------------------------------------------------------------------
# Paper order
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class PaperOrder:
    """An intended paper entry produced by ``select_orders``.

    ``entry_price`` / ``implied_prob`` are the YES price in dollars at selection
    time. ``side`` is the contract side actually taken (NO to fade a longshot,
    YES to back a favorite). ``effective_entry_price`` is the price *of the side
    taken* (``entry_price`` for YES, ``1 - entry_price`` for NO) — the cost basis
    of the contract and the per-contract fee base.
    """

    ticker: str
    event_ticker: str
    series_ticker: str
    category: str
    side: str
    direction: str
    entry_price: float        # YES price (= market-implied prob of YES)
    implied_prob: float       # == entry_price (dollars 0..1)
    effective_entry_price: float  # price of the side actually taken
    stake_contracts: int
    bucket_lo: float
    bucket_hi: float
    yes_bid: float
    yes_ask: float
    volume_fp: float
    close_time: int           # ns epoch
    sp_nasdaq: bool
    rule_name: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "ticker": self.ticker,
            "event_ticker": self.event_ticker,
            "series_ticker": self.series_ticker,
            "category": self.category,
            "side": self.side,
            "direction": self.direction,
            "entry_price": self.entry_price,
            "implied_prob": self.implied_prob,
            "effective_entry_price": self.effective_entry_price,
            "stake_contracts": self.stake_contracts,
            "bucket_lo": self.bucket_lo,
            "bucket_hi": self.bucket_hi,
            "yes_bid": self.yes_bid,
            "yes_ask": self.yes_ask,
            "volume_fp": self.volume_fp,
            "close_time": self.close_time,
            "sp_nasdaq": self.sp_nasdaq,
            "rule_name": self.rule_name,
        }


# ---------------------------------------------------------------------------
# Open-market extraction (pure; no network)
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class OpenMarket:
    """Normalised view of one currently-open Kalshi market.

    Built from the raw market dict (from the client) plus the (series, category)
    resolved from its event. All numerics are coerced from Kalshi's string-typed
    fields via ``ingest.schema``.
    """

    ticker: str
    event_ticker: str
    series_ticker: str
    category: str
    yes_price: float          # the YES price used as entry_price / implied_prob
    yes_bid: float
    yes_ask: float
    volume_fp: float
    close_time: int           # ns epoch


def extract_open_market(market: dict[str, Any], series_ticker: str,
                        category: str) -> OpenMarket | None:
    """Coerce a raw open-market dict into an ``OpenMarket``, or None if unusable.

    The YES entry price is the live ``last_price_dollars`` when present and
    finite, else the bid/ask midpoint, else the ``yes_bid``/``yes_ask`` that is
    available. Returns None if no finite YES price can be formed.
    """
    ticker = str(market.get("ticker") or "")
    if not ticker:
        return None
    yes_bid = S.to_float(market.get("yes_bid_dollars"), default=float("nan"))
    yes_ask = S.to_float(market.get("yes_ask_dollars"), default=float("nan"))
    last = S.to_float(market.get("last_price_dollars"), default=float("nan"))

    yes_price = last
    if not math.isfinite(yes_price):
        if math.isfinite(yes_bid) and math.isfinite(yes_ask):
            yes_price = 0.5 * (yes_bid + yes_ask)
        elif math.isfinite(yes_ask):
            yes_price = yes_ask
        elif math.isfinite(yes_bid):
            yes_price = yes_bid
    if not math.isfinite(yes_price):
        return None

    return OpenMarket(
        ticker=ticker,
        event_ticker=str(market.get("event_ticker") or ""),
        series_ticker=str(series_ticker or ""),
        category=str(category or ""),
        yes_price=float(yes_price),
        yes_bid=yes_bid,
        yes_ask=yes_ask,
        volume_fp=S.to_float(market.get("volume_fp"), default=0.0),
        close_time=S.iso_to_ns(market.get("close_time")),
    )


# ---------------------------------------------------------------------------
# select_orders — the pure rule application
# ---------------------------------------------------------------------------

def select_orders(open_markets: Sequence[OpenMarket],
                  rule: RuleSpec = DEFAULT_RULE_SPEC,
                  *, now_ns: int | None = None) -> list[PaperOrder]:
    """Apply ``rule`` to a snapshot of open markets → intended paper entries.

    A market becomes an order iff, in order:
      1. its category is eligible (``rule.category_eligible``);
      2. its lifetime volume exceeds ``rule.min_volume_fp`` (§7 — strictly > 0
         is the floor even when ``min_volume_fp == 0``);
      3. (if ``rule.require_quote``) a finite yes_bid AND yes_ask are present;
      4. its YES price falls in some bucket band (``rule.matching_bucket``).

    The order's ``side`` is the bucket's FLB side (fade→NO, back→YES); the
    ``effective_entry_price`` is the cost basis of the side taken. ``stake`` is
    the rule's ``max_stake_contracts`` (flat sizing; capacity-capped per §0).

    Pure function: no network, no I/O, deterministic. Returns orders sorted by
    ticker for stable journalling.
    """
    cap_ns = (None if rule.max_days_to_close is None
              else int(rule.max_days_to_close * 86_400 * 1_000_000_000))
    if cap_ns is not None and now_ns is None:
        now_ns = time.time_ns()
    orders: list[PaperOrder] = []
    for om in open_markets:
        if not rule.category_eligible(om.category):
            continue
        # Time-to-close cap (provisional forward tuning): skip markets that are
        # already closed / have an unknown close, or that resolve beyond the cap.
        # Targets near-term markets where FLB is a genuine bias (not far-future
        # time-value) and keeps the forward record on a useful timescale. The
        # frozen §4/§5 price bands are untouched.
        if cap_ns is not None and (om.close_time <= now_ns
                                   or (om.close_time - now_ns) > cap_ns):
            continue
        # §7 volume filter: strictly positive floor, plus the rule's threshold.
        if not (math.isfinite(om.volume_fp) and om.volume_fp > 0
                and om.volume_fp > rule.min_volume_fp):
            continue
        if rule.require_quote and not (
                math.isfinite(om.yes_bid) and math.isfinite(om.yes_ask)):
            continue
        bucket = rule.matching_bucket(om.yes_price)
        if bucket is None:
            continue

        side = bucket.side
        eff = om.yes_price if side == SIDE_YES else (1.0 - om.yes_price)
        orders.append(PaperOrder(
            ticker=om.ticker,
            event_ticker=om.event_ticker,
            series_ticker=om.series_ticker,
            category=om.category,
            side=side,
            direction=bucket.direction,
            entry_price=om.yes_price,
            implied_prob=om.yes_price,
            effective_entry_price=eff,
            stake_contracts=rule.max_stake_contracts,
            bucket_lo=bucket.lo,
            bucket_hi=bucket.hi,
            yes_bid=om.yes_bid,
            yes_ask=om.yes_ask,
            volume_fp=om.volume_fp,
            close_time=om.close_time,
            sp_nasdaq=rule.is_sp_nasdaq(om.series_ticker),
            rule_name=rule.name,
        ))
    orders.sort(key=lambda o: o.ticker)
    return orders
