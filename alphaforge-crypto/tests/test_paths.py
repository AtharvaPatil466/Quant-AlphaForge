from pathlib import Path

from data.paths import default_paths, funding_path, kline_year_path, oi_year_path


def test_default_paths_creates_all_dirs(tmp_path: Path) -> None:
    base = tmp_path / "binance"
    paths = default_paths(base)
    assert paths.binance_root == base.resolve()
    for p in (
        paths.spot_klines_root,
        paths.perp_klines_root,
        paths.funding_root,
        paths.open_interest_root,
        paths.quarantine_root,
    ):
        assert p.is_dir(), f"{p} should be created by default_paths"
    assert paths.manifest_path == paths.binance_root / "_manifest.json"


def test_kline_year_path_segregates_markets(tmp_path: Path) -> None:
    spot = kline_year_path("BTCUSDT", 2024, "spot", base_dir=tmp_path / "binance")
    perp = kline_year_path("BTCUSDT", 2024, "perp", base_dir=tmp_path / "binance")
    assert spot.parent.parent.name == "klines_1h_spot"
    assert perp.parent.parent.name == "klines_1h_perp"
    assert spot != perp
    assert spot.name == "2024.parquet"


def test_funding_and_oi_paths(tmp_path: Path) -> None:
    base = tmp_path / "binance"
    fp = funding_path("ethusdt", base_dir=base)
    op = oi_year_path("ethusdt", 2025, base_dir=base)
    assert fp.parent == default_paths(base).funding_root
    assert fp.name == "ETHUSDT.parquet"
    assert op.parent.name == "ETHUSDT"
    assert op.name == "2025.parquet"


def test_quarantine_paths(tmp_path: Path) -> None:
    base = tmp_path / "binance"
    qp = kline_year_path("BTCUSDT", 2024, "spot", base_dir=base, quarantined=True)
    assert "_quarantine" in qp.parts
