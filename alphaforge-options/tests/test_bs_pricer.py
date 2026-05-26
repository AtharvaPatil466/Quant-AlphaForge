"""Tests for alphaforge-options/ingest/bs_pricer.py.

Covers:
- BS call/put parity (put-call parity)
- BS prices >= intrinsic value
- Delta targeting: |delta(K)| ≈ target_delta_abs
- CondorStrikes ordering invariants
- open_condor: net premium > 0 under normal conditions
- cycle_pnl: expired worthless = premium - tx_cost
- expiry_payoff: boundary cases
"""
import math
import pytest

from ingest.bs_pricer import (
    CondorCycle,
    CondorStrikes,
    bs_delta,
    bs_price,
    close_condor_cost,
    cycle_pnl,
    expiry_payoff,
    find_strike_for_delta,
    open_condor,
)

# ---------------------------------------------------------------------------
# Canonical parameters
# ---------------------------------------------------------------------------
S = 400.0        # SPY ~ $400
T = 30 / 365.0   # 30-DTE
r = 0.001        # near-zero rate (post-2009 fallback)
sigma = 0.20     # VIX=20 → sigma=0.20


# ---------------------------------------------------------------------------
# BS price
# ---------------------------------------------------------------------------

class TestBsPrice:
    def test_put_call_parity(self):
        K = 400.0
        c = bs_price(S, K, T, r, sigma, "call")
        p = bs_price(S, K, T, r, sigma, "put")
        # C - P = S - K * exp(-rT)
        parity = S - K * math.exp(-r * T)
        assert abs((c - p) - parity) < 1e-8

    def test_call_above_intrinsic(self):
        K = 380.0  # deep ITM call
        c = bs_price(S, K, T, r, sigma, "call")
        assert c >= max(S - K, 0.0) - 1e-10

    def test_put_above_intrinsic(self):
        K = 420.0  # deep ITM put
        p = bs_price(S, K, T, r, sigma, "put")
        assert p >= max(K - S, 0.0) - 1e-10

    def test_call_at_T0_intrinsic_only(self):
        K = 390.0
        c = bs_price(S, K, 0.0, r, sigma, "call")
        assert abs(c - max(S - K, 0.0)) < 1e-12

    def test_put_at_T0_intrinsic_only(self):
        K = 410.0
        p = bs_price(S, K, 0.0, r, sigma, "put")
        assert abs(p - max(K - S, 0.0)) < 1e-12

    def test_call_positive_for_atm(self):
        c = bs_price(S, S, T, r, sigma, "call")
        assert c > 0

    def test_put_positive_for_atm(self):
        p = bs_price(S, S, T, r, sigma, "put")
        assert p > 0


# ---------------------------------------------------------------------------
# BS delta
# ---------------------------------------------------------------------------

class TestBsDelta:
    def test_atm_call_delta_near_half(self):
        d = bs_delta(S, S, T, r, sigma, "call")
        assert 0.45 < d < 0.55

    def test_atm_put_delta_near_minus_half(self):
        d = bs_delta(S, S, T, r, sigma, "put")
        assert -0.55 < d < -0.45

    def test_put_delta_negative(self):
        d = bs_delta(S, S * 1.1, T, r, sigma, "put")
        assert d < 0

    def test_call_delta_positive(self):
        d = bs_delta(S, S * 0.9, T, r, sigma, "call")
        assert d > 0

    def test_call_delta_at_T0_itm(self):
        d = bs_delta(S, S * 0.9, 0.0, r, sigma, "call")
        assert abs(d - 1.0) < 1e-12

    def test_put_delta_at_T0_itm(self):
        d = bs_delta(S, S * 1.1, 0.0, r, sigma, "put")
        assert abs(d - (-1.0)) < 1e-12


# ---------------------------------------------------------------------------
# Delta targeting
# ---------------------------------------------------------------------------

class TestFindStrikeForDelta:
    @pytest.mark.parametrize("target_delta", [0.05, 0.10, 0.16, 0.20, 0.30])
    def test_put_delta_accuracy(self, target_delta):
        K = find_strike_for_delta(S, T, r, sigma, target_delta, "put")
        actual_delta = abs(bs_delta(S, K, T, r, sigma, "put"))
        assert abs(actual_delta - target_delta) < 1e-3

    @pytest.mark.parametrize("target_delta", [0.05, 0.10, 0.16, 0.20, 0.30])
    def test_call_delta_accuracy(self, target_delta):
        K = find_strike_for_delta(S, T, r, sigma, target_delta, "call")
        actual_delta = bs_delta(S, K, T, r, sigma, "call")
        assert abs(actual_delta - target_delta) < 1e-3

    def test_put_16delta_strike_below_atm(self):
        K = find_strike_for_delta(S, T, r, sigma, 0.16, "put")
        assert K < S

    def test_call_16delta_strike_above_atm(self):
        K = find_strike_for_delta(S, T, r, sigma, 0.16, "call")
        assert K > S

    def test_long_wing_strike_further_from_atm_than_short(self):
        K_short = find_strike_for_delta(S, T, r, sigma, 0.16, "put")
        K_long = find_strike_for_delta(S, T, r, sigma, 0.05, "put")
        assert K_long < K_short  # 5Δ put further OTM → lower strike

    def test_rejects_delta_geq_half(self):
        with pytest.raises(AssertionError):
            find_strike_for_delta(S, T, r, sigma, 0.50, "put")

    def test_rejects_delta_zero(self):
        with pytest.raises(AssertionError):
            find_strike_for_delta(S, T, r, sigma, 0.0, "put")


# ---------------------------------------------------------------------------
# CondorStrikes
# ---------------------------------------------------------------------------

class TestCondorStrikes:
    def _make_strikes(self):
        K_pl = 350.0
        K_ps = 375.0
        K_cs = 425.0
        K_cl = 450.0
        return CondorStrikes(K_pl, K_ps, K_cs, K_cl)

    def test_put_wing_width(self):
        cs = self._make_strikes()
        assert abs(cs.put_wing_width - 25.0) < 1e-10

    def test_call_wing_width(self):
        cs = self._make_strikes()
        assert abs(cs.call_wing_width - 25.0) < 1e-10

    def test_max_loss(self):
        cs = self._make_strikes()
        assert abs(cs.max_loss_per_share - 25.0) < 1e-10

    def test_asymmetric_max_loss_takes_max_wing(self):
        cs = CondorStrikes(350.0, 375.0, 425.0, 460.0)
        assert abs(cs.max_loss_per_share - 35.0) < 1e-10


# ---------------------------------------------------------------------------
# open_condor
# ---------------------------------------------------------------------------

class TestOpenCondor:
    def test_premium_positive(self):
        cyc = open_condor(S, T, r, sigma, 0.16, 0.05)
        assert cyc.premium > 0

    def test_strike_ordering(self):
        cyc = open_condor(S, T, r, sigma, 0.16, 0.05)
        st = cyc.strikes
        assert st.K_put_long < st.K_put_short < S < st.K_call_short < st.K_call_long

    def test_premium_increases_with_vol(self):
        cyc_lo = open_condor(S, T, r, 0.10, 0.16, 0.05)
        cyc_hi = open_condor(S, T, r, 0.40, 0.16, 0.05)
        assert cyc_hi.premium > cyc_lo.premium

    def test_wider_long_wing_reduces_premium(self):
        cyc_5d = open_condor(S, T, r, sigma, 0.16, 0.05)
        cyc_10d = open_condor(S, T, r, sigma, 0.16, 0.10)
        assert cyc_5d.premium > cyc_10d.premium

    def test_stores_entry_params(self):
        cyc = open_condor(S, T, r, sigma, 0.16, 0.05)
        assert abs(cyc.S_entry - S) < 1e-10
        assert abs(cyc.T_entry - T) < 1e-10
        assert abs(cyc.sigma_entry - sigma) < 1e-10
        assert abs(cyc.r_entry - r) < 1e-10


# ---------------------------------------------------------------------------
# expiry_payoff
# ---------------------------------------------------------------------------

class TestExpiryPayoff:
    def setup_method(self):
        self.cyc = open_condor(S, T, r, sigma, 0.16, 0.05)

    def test_zero_payoff_when_atm(self):
        # If SPY stays at S (inside the body), payoff = 0
        payoff = expiry_payoff(S, self.cyc.strikes)
        assert abs(payoff) < 1e-10

    def test_max_payoff_at_put_breach(self):
        # SPY falls below K_put_long → max loss = put_wing_width
        payoff = expiry_payoff(self.cyc.strikes.K_put_long - 10, self.cyc.strikes)
        assert abs(payoff - self.cyc.strikes.put_wing_width) < 1e-10

    def test_max_payoff_at_call_breach(self):
        # SPY rises above K_call_long → max loss = call_wing_width
        payoff = expiry_payoff(self.cyc.strikes.K_call_long + 10, self.cyc.strikes)
        assert abs(payoff - self.cyc.strikes.call_wing_width) < 1e-10

    def test_payoff_nonnegative(self):
        for spy in [300, 350, 380, 400, 420, 440, 500]:
            assert expiry_payoff(float(spy), self.cyc.strikes) >= 0.0


# ---------------------------------------------------------------------------
# cycle_pnl
# ---------------------------------------------------------------------------

class TestCyclePnl:
    def setup_method(self):
        self.cyc = open_condor(S, T, r, sigma, 0.16, 0.05)

    def test_expired_worthless_equals_premium_minus_tx(self):
        # If SPY stays inside the body and expires, payoff=0, pnl=premium-tx
        tx = 0.07
        pnl = cycle_pnl(
            self.cyc,
            S_close=S,
            T_remaining=0.0,
            r_close=r,
            sigma_close=sigma,
            tx_cost_per_share=tx,
            hold_to_expiry=True,
        )
        expected = self.cyc.premium - tx
        assert abs(pnl - expected) < 1e-10

    def test_pnl_negative_when_spy_crashes(self):
        # Large adverse move → negative pnl
        pnl = cycle_pnl(
            self.cyc,
            S_close=self.cyc.strikes.K_put_long - 20,
            T_remaining=0.0,
            r_close=r,
            sigma_close=sigma,
            tx_cost_per_share=0.07,
            hold_to_expiry=True,
        )
        assert pnl < 0

    def test_mtm_close_gives_smaller_pnl_than_expiry_when_vol_spikes(self):
        # Vol spike increases close cost, so rolling before expiry hurts
        T_roll = 9 / 365.0
        sigma_spike = 0.50
        pnl_roll = cycle_pnl(
            self.cyc,
            S_close=S,
            T_remaining=T_roll,
            r_close=r,
            sigma_close=sigma_spike,
            tx_cost_per_share=0.07,
            hold_to_expiry=False,
        )
        pnl_expiry = cycle_pnl(
            self.cyc,
            S_close=S,
            T_remaining=0.0,
            r_close=r,
            sigma_close=sigma,
            tx_cost_per_share=0.07,
            hold_to_expiry=True,
        )
        assert pnl_roll < pnl_expiry
