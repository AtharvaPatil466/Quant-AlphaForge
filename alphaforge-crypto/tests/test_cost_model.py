from research.cost_model import (
    CryptoCostConfig,
    borrow_cost_bps_for_period,
    funding_pnl_bps,
    make_leg_cost,
)


def test_round_trip_bps_sum_to_expected_total() -> None:
    cfg = CryptoCostConfig()
    # perp: 2 * (4 + 2) = 12
    # spot: 2 * (10 + 2) = 24
    assert cfg.round_trip_perp_bps() == 12.0
    assert cfg.round_trip_spot_bps() == 24.0
    assert cfg.round_trip_combined_bps() == 36.0


def test_funding_pnl_sign_convention() -> None:
    # Longs pay funding when rate > 0
    assert funding_pnl_bps(0.0001, perp_side="short") == 1.0
    assert funding_pnl_bps(0.0001, perp_side="long") == -1.0
    assert funding_pnl_bps(-0.0001, perp_side="short") == -1.0


def test_borrow_cost_for_8h_period() -> None:
    # 30 bps/year over 8h
    cost_8h = borrow_cost_bps_for_period(30.0, 8 * 3600)
    # Sanity: ~ 30 / (365.25 * 3) = ~0.0274 bps for 8h
    assert 0.025 < cost_8h < 0.030


def test_make_leg_cost_dispatches_by_market() -> None:
    cfg = CryptoCostConfig()
    perp = make_leg_cost("perp", cfg)
    spot = make_leg_cost("spot", cfg)
    assert perp.total_bps == 6.0
    assert spot.total_bps == 12.0
