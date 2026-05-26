"""Black-Scholes iron condor pricer for Substrate #9.

Per SUBSTRATE9_DESIGN.md §4. Flat implied-vol surface (VIX as sigma),
calendar-day time convention (T = DTE_calendar / 365). Known bias
declared in §4.4: flat surface understates OTM premium → strategy P&L
is understated → conservative (makes gauntlet harder, not easier).

Units:
    S, K      : dollars per share (SPY price)
    T         : years (calendar days / 365)
    r         : annualized, decimal (e.g. 0.045 for 4.5%)
    sigma     : annualized, decimal (e.g. 0.20 for VIX=20)
    prices    : dollars per share
"""
from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np
from scipy.optimize import brentq
from scipy.stats import norm


# ---------------------------------------------------------------------------
# Core Black-Scholes functions
# ---------------------------------------------------------------------------

def _d1(S: float, K: float, T: float, r: float, sigma: float) -> float:
    return (math.log(S / K) + (r + 0.5 * sigma ** 2) * T) / (sigma * math.sqrt(T))


def bs_price(
    S: float,
    K: float,
    T: float,
    r: float,
    sigma: float,
    option_type: str = "call",
) -> float:
    """Black-Scholes option price per share. Returns intrinsic value at T=0."""
    if T <= 0.0:
        if option_type == "call":
            return max(S - K, 0.0)
        return max(K - S, 0.0)

    d1 = _d1(S, K, T, r, sigma)
    d2 = d1 - sigma * math.sqrt(T)
    disc = math.exp(-r * T)

    if option_type == "call":
        return S * norm.cdf(d1) - K * disc * norm.cdf(d2)
    return K * disc * norm.cdf(-d2) - S * norm.cdf(-d1)


def bs_delta(
    S: float,
    K: float,
    T: float,
    r: float,
    sigma: float,
    option_type: str = "call",
) -> float:
    """BS delta. Put delta is negative; |put_delta| = N(-d1)."""
    if T <= 0.0:
        if option_type == "call":
            return 1.0 if S > K else 0.0
        return -1.0 if S < K else 0.0

    d1 = _d1(S, K, T, r, sigma)
    if option_type == "call":
        return float(norm.cdf(d1))
    return float(-norm.cdf(-d1))


# ---------------------------------------------------------------------------
# Delta-targeted strike finder
# ---------------------------------------------------------------------------

def find_strike_for_delta(
    S: float,
    T: float,
    r: float,
    sigma: float,
    target_delta_abs: float,
    option_type: str,
) -> float:
    """Find strike K such that |delta(K)| = target_delta_abs.

    For puts: |delta| = N(-d1), so d1 = N_inv(1 - target).
    For calls: delta = N(d1), so d1 = N_inv(target).
    Closed-form approximation is exact when r=0; brentq polishes it.
    """
    assert 0.0 < target_delta_abs < 0.5, "OTM only: target_delta_abs in (0, 0.5)"

    # Closed-form starting guess
    if option_type == "put":
        d1_target = float(norm.ppf(1.0 - target_delta_abs))  # positive for OTM put
    else:
        d1_target = float(norm.ppf(target_delta_abs))          # negative for OTM call

    # K from d1 inversion (exact at r=0, approximate otherwise)
    K_guess = S * math.exp(-d1_target * sigma * math.sqrt(T) + (r + 0.5 * sigma ** 2) * T)

    def objective(K: float) -> float:
        delta = bs_delta(S, K, T, r, sigma, option_type)
        return abs(delta) - target_delta_abs

    # Bracket around the guess — widen ±30%
    lo = K_guess * 0.7
    hi = K_guess * 1.3

    # Make sure the bracket straddles zero
    f_lo, f_hi = objective(lo), objective(hi)
    if f_lo * f_hi > 0:
        # Expand bracket
        lo = S * 0.40 if option_type == "put" else S * 1.001
        hi = S * 0.999 if option_type == "put" else S * 3.0

    try:
        return float(brentq(objective, lo, hi, xtol=1e-4, maxiter=200))
    except ValueError:
        # Fall back to closed-form approximation
        return K_guess


# ---------------------------------------------------------------------------
# Iron condor struct and premium / close-cost computation
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class CondorStrikes:
    K_put_long: float
    K_put_short: float
    K_call_short: float
    K_call_long: float

    @property
    def put_wing_width(self) -> float:
        return self.K_put_short - self.K_put_long

    @property
    def call_wing_width(self) -> float:
        return self.K_call_long - self.K_call_short

    @property
    def max_loss_per_share(self) -> float:
        """Max possible loss per share = max wing width (assumes symmetry fails)."""
        return max(self.put_wing_width, self.call_wing_width)


@dataclass(frozen=True)
class CondorCycle:
    strikes: CondorStrikes
    premium: float          # net credit received per share at open
    T_entry: float          # years to expiry at entry
    S_entry: float
    sigma_entry: float
    r_entry: float


def open_condor(
    S: float,
    T: float,
    r: float,
    sigma: float,
    short_delta: float,
    long_delta: float,
) -> CondorCycle:
    """Compute an iron condor's strikes and net premium.

    Sell short_delta put + short_delta call.
    Buy long_delta put + long_delta call.
    All legs same expiry. Net premium is per SPY share.
    """
    K_ps = find_strike_for_delta(S, T, r, sigma, short_delta, "put")
    K_pl = find_strike_for_delta(S, T, r, sigma, long_delta, "put")
    K_cs = find_strike_for_delta(S, T, r, sigma, short_delta, "call")
    K_cl = find_strike_for_delta(S, T, r, sigma, long_delta, "call")

    premium = (
        bs_price(S, K_ps, T, r, sigma, "put")
        + bs_price(S, K_cs, T, r, sigma, "call")
        - bs_price(S, K_pl, T, r, sigma, "put")
        - bs_price(S, K_cl, T, r, sigma, "call")
    )

    strikes = CondorStrikes(K_pl, K_ps, K_cs, K_cl)
    return CondorCycle(strikes, premium, T, S, sigma, r)


def close_condor_cost(
    S: float,
    T_remaining: float,
    r: float,
    sigma: float,
    strikes: CondorStrikes,
) -> float:
    """Cost to buy back (close) the condor at current market conditions.

    Returns the net debit paid per share to exit all 4 legs.
    """
    return (
        bs_price(S, strikes.K_put_short, T_remaining, r, sigma, "put")
        + bs_price(S, strikes.K_call_short, T_remaining, r, sigma, "call")
        - bs_price(S, strikes.K_put_long, T_remaining, r, sigma, "put")
        - bs_price(S, strikes.K_call_long, T_remaining, r, sigma, "call")
    )


def expiry_payoff(S_expiry: float, strikes: CondorStrikes) -> float:
    """Net payoff at expiry (loss to the seller, per share).

    Positive value = net payment from seller to buyer = loss for us.
    """
    put_spread = max(0.0, strikes.K_put_short - S_expiry) - max(
        0.0, strikes.K_put_long - S_expiry
    )
    call_spread = max(0.0, S_expiry - strikes.K_call_short) - max(
        0.0, S_expiry - strikes.K_call_long
    )
    return put_spread + call_spread


def cycle_pnl(
    cycle: CondorCycle,
    S_close: float,
    T_remaining: float,
    r_close: float,
    sigma_close: float,
    tx_cost_per_share: float,
    hold_to_expiry: bool = False,
) -> float:
    """Net P&L per share for one iron condor cycle.

    Positive = profit.
    tx_cost_per_share: round-trip cost for all 4 legs (open already paid at entry),
                       this is the CLOSE-side cost only.
    """
    if hold_to_expiry:
        loss = expiry_payoff(S_close, cycle.strikes)
    else:
        loss = close_condor_cost(S_close, T_remaining, r_close, sigma_close, cycle.strikes)

    return cycle.premium - loss - tx_cost_per_share
