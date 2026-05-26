"""Cost model for the VIX gauntlet — operationalization of VIX_DESIGN.md §6.

ETP path only (futures path REMOVED per §17.2 — CBOE moved settlements to
paid DataShop). All costs are charged on a per-fill basis in basis points
of fill notional. Three scaling regimes:

  • baseline_bps        — default cost stack: 10 bp round-trip (§6.1)
  • gate4_bps           — doubled-cost stress: 20 bp round-trip (§5.4, §6.2)
  • stress_multiplier   — 3× widening during pre-committed stress periods
                          (§6.3): 2008/2011/2018/2020.

Margin financing (§9 + §14.7) is exposed via `margin_carry_bps_annual` so
the backtest can debit the SVXY/VXX position daily. No FRED dependency
at import time; `set_carry_table` lets callers swap in a real DGS3MO
series, otherwise the §14.7 fallback constants apply.

Hard rule: each `apply` call returns a positive number. Whether to debit
or credit is the caller's responsibility (commission is always a debit;
carry can be a debit or credit depending on direction × rate).
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date

import pandas as pd


# ---------------------------------------------------------------------------
# Frozen pre-commits from VIX_DESIGN.md §6 + §14.7
# ---------------------------------------------------------------------------

ETP_BASELINE_ROUND_TRIP_BPS: float = 10.0    # §6.1
ETP_GATE4_ROUND_TRIP_BPS: float = 20.0       # §5.4 — Gate-4 stress
STRESS_PERIOD_COST_MULTIPLIER: float = 3.0   # §6.3

# Per-fill (one-way) charge: half the round-trip.
def _half(bps: float) -> float:
    return bps / 2.0


# §5.5 stress periods (inclusive on both ends).
STRESS_PERIODS: tuple[tuple[str, pd.Timestamp, pd.Timestamp], ...] = (
    ("2008_financial_crisis", pd.Timestamp("2008-09-01"), pd.Timestamp("2009-03-31")),
    ("2011_debt_ceiling",     pd.Timestamp("2011-07-01"), pd.Timestamp("2011-10-31")),
    ("2018_volmageddon",      pd.Timestamp("2018-02-01"), pd.Timestamp("2018-03-31")),
    ("2020_covid_crash",      pd.Timestamp("2020-02-01"), pd.Timestamp("2020-04-30")),
)


# §14.7 fallback risk-free rates (annualized) when FRED is unavailable.
# Tiered by year window — calibrated to FRED DGS3MO long-run regimes.
_FALLBACK_CARRY_BPS_ANNUAL: tuple[tuple[int, int, float], ...] = (
    (1990, 2007, 400.0),   # pre-GFC normal regime
    (2008, 2015, 30.0),    # ZIRP era
    (2016, 2019, 150.0),   # gradual hike cycle
    (2020, 2021, 30.0),    # COVID emergency
    (2022, 2026, 450.0),   # hike-cycle peak / current regime
)


def _fallback_carry_bps(d: pd.Timestamp) -> float:
    y = d.year
    for lo, hi, bps in _FALLBACK_CARRY_BPS_ANNUAL:
        if lo <= y <= hi:
            return bps
    return 200.0  # neutral default


# ---------------------------------------------------------------------------
# Stress-period helper
# ---------------------------------------------------------------------------

def in_stress_period(trade_date: pd.Timestamp) -> str | None:
    """Return the name of the stress period containing `trade_date`, or None."""
    for name, lo, hi in STRESS_PERIODS:
        if lo <= trade_date <= hi:
            return name
    return None


# ---------------------------------------------------------------------------
# Cost model
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class FillCost:
    """Per-fill cost decomposition. All values in dollars, always positive."""
    half_spread_bps: float
    commission_bps: float
    total_bps: float
    total_dollars: float
    in_stress: bool
    stress_name: str | None


class CostModel:
    """ETP cost model per VIX_DESIGN.md §6.1-6.3.

    Two configurations:
        regime="baseline" — 10 bp round-trip (default)
        regime="gate4"    — 20 bp round-trip (Gate 4 doubled-cost stress)

    Stress-period 3× widening (§6.3) is applied automatically when
    `trade_date` falls in one of the §5.5 stress windows.
    """

    def __init__(self, regime: str = "baseline"):
        if regime not in ("baseline", "gate4"):
            raise ValueError(f"unknown regime {regime!r}; "
                             "expected 'baseline' or 'gate4'")
        self.regime = regime
        rt = (ETP_BASELINE_ROUND_TRIP_BPS if regime == "baseline"
              else ETP_GATE4_ROUND_TRIP_BPS)
        # Each side of a round-trip is half the bps; spread + commission
        # are not split in the design — they are bundled into a single
        # round-trip charge. We expose them separately for reporting
        # transparency (50/50 split is conventional and not searched).
        self.half_spread_bps_per_fill = _half(rt) * 0.5
        self.commission_bps_per_fill = _half(rt) * 0.5
        self.total_bps_per_fill = _half(rt)

    def apply(
        self,
        fill_notional: float,
        trade_date: pd.Timestamp,
    ) -> FillCost:
        """Charge a single fill. `fill_notional` is the absolute dollar size
        being transacted; sign doesn't matter for cost (long or short pays).
        """
        if fill_notional < 0:
            fill_notional = abs(fill_notional)
        stress = in_stress_period(trade_date)
        mult = STRESS_PERIOD_COST_MULTIPLIER if stress else 1.0
        eff_total_bps = self.total_bps_per_fill * mult
        eff_half_bps = self.half_spread_bps_per_fill * mult
        eff_comm_bps = self.commission_bps_per_fill * mult
        total_dollars = fill_notional * eff_total_bps / 1e4
        return FillCost(
            half_spread_bps=eff_half_bps,
            commission_bps=eff_comm_bps,
            total_bps=eff_total_bps,
            total_dollars=total_dollars,
            in_stress=stress is not None,
            stress_name=stress,
        )


# ---------------------------------------------------------------------------
# Margin financing carry
# ---------------------------------------------------------------------------

class CarryTable:
    """Daily risk-free rate lookup. Backed by FRED DGS3MO when provided,
    else uses the §14.7 fallback constants.

    Rates are stored and returned in **annualized basis points**.
    """

    def __init__(self, fred_series: pd.Series | None = None):
        if fred_series is not None:
            s = fred_series.dropna().astype(float)
            # FRED DGS3MO is in percent (e.g. 4.5 = 4.5% annualized). Convert to bp.
            self._series = (s * 100.0).rename("carry_bps_annual")
        else:
            self._series = None

    def lookup(self, d: pd.Timestamp) -> float:
        """Annualized bp on `d`. Forward-fills the FRED series; falls back
        to the §14.7 tiered constants when the date is out of range."""
        if self._series is None or self._series.empty:
            return _fallback_carry_bps(d)
        # Last observation on or before d.
        s = self._series.loc[:d]
        if s.empty:
            return _fallback_carry_bps(d)
        return float(s.iloc[-1])

    def daily_carry_dollars(
        self,
        capital_carried: float,
        d: pd.Timestamp,
        days: int = 1,
    ) -> float:
        """Dollar carry over `days` calendar days on `capital_carried`.

        Positive when the broker pays you (long cash); negative when you pay
        the broker (margin debit). The caller passes a signed
        `capital_carried` — positive for long cash, negative for borrow.
        """
        annual_bps = self.lookup(d)
        return capital_carried * (annual_bps / 1e4) * (days / 365.0)


# ---------------------------------------------------------------------------
# Convenience builders
# ---------------------------------------------------------------------------

def baseline_costs() -> CostModel:
    return CostModel(regime="baseline")


def gate4_stress_costs() -> CostModel:
    return CostModel(regime="gate4")
