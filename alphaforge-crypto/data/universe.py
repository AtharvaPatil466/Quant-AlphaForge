"""USDT-margined perpetual universe selection.

v0 universe rule: top-N by 24h quote volume on the USDT-M perp venue, restricted
to symbols whose underlying spot pair also trades on Binance (so we can build
spot-perp basis features cleanly).

Known limitation (documented in CLAUDE.md): this is a current-snapshot universe
with survivorship bias. A point-in-time crypto universe is a future project.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from .binance_client import BinanceClient
from .paths import default_paths


DEFAULT_TOP_N = 30


@dataclass(frozen=True)
class PerpetualSpec:
    symbol: str            # e.g. "BTCUSDT"
    base_asset: str        # e.g. "BTC"
    quote_asset: str       # always "USDT" for v0
    contract_type: str     # "PERPETUAL"
    onboard_date_ms: int   # exchange-reported onboard time (perp listing date)
    has_spot_pair: bool    # whether the corresponding spot pair trades on Binance

    def to_dict(self) -> dict:
        return {
            "symbol": self.symbol,
            "base_asset": self.base_asset,
            "quote_asset": self.quote_asset,
            "contract_type": self.contract_type,
            "onboard_date_ms": self.onboard_date_ms,
            "has_spot_pair": self.has_spot_pair,
        }


def discover_usdt_perpetuals(client: BinanceClient) -> list[PerpetualSpec]:
    """Return all currently-trading USDT-margined perpetuals on Binance Futures.

    The result also flags whether the corresponding spot pair is currently
    listed, which we'll require for basis features.
    """
    fapi_info = client.fapi_exchange_info()
    spot_info = client.spot_exchange_info()

    spot_symbols = {
        s["symbol"]
        for s in spot_info.get("symbols", [])
        if s.get("status") == "TRADING"
    }

    perps: list[PerpetualSpec] = []
    for entry in fapi_info.get("symbols", []):
        if entry.get("status") != "TRADING":
            continue
        if entry.get("contractType") != "PERPETUAL":
            continue
        if entry.get("quoteAsset") != "USDT":
            continue
        symbol = entry["symbol"]
        perps.append(
            PerpetualSpec(
                symbol=symbol,
                base_asset=entry["baseAsset"],
                quote_asset=entry["quoteAsset"],
                contract_type=entry["contractType"],
                onboard_date_ms=int(entry.get("onboardDate", 0)),
                has_spot_pair=symbol in spot_symbols,
            )
        )
    return perps


def select_top_n_by_volume(
    client: BinanceClient,
    perps: list[PerpetualSpec],
    top_n: int = DEFAULT_TOP_N,
    *,
    require_spot_pair: bool = True,
) -> list[PerpetualSpec]:
    """Sort `perps` by 24h quote volume on the perp venue and return the top N.

    When `require_spot_pair=True`, perpetuals without a corresponding TRADING
    spot pair are excluded — basis research needs both legs.
    """
    candidates = [p for p in perps if (not require_spot_pair or p.has_spot_pair)]
    ticker_rows = client.fapi_24h_tickers()
    quote_vol = {row["symbol"]: float(row.get("quoteVolume", 0.0)) for row in ticker_rows}

    ranked = sorted(
        candidates,
        key=lambda p: quote_vol.get(p.symbol, 0.0),
        reverse=True,
    )
    return ranked[: int(top_n)]


def write_universe_manifest(
    perps: list[PerpetualSpec],
    *,
    top_n: int,
    base_dir: str | Path | None = None,
    quote_volume_by_symbol: dict[str, float] | None = None,
) -> Path:
    """Persist the pinned universe to `<binance_root>/_manifest.json`.

    The manifest is the single source of truth for which symbols the downloader
    will fetch. Downstream studies should read this file rather than re-querying
    the exchange.
    """
    paths = default_paths(base_dir)
    payload = {
        "schema_version": 1,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "selection_rule": "top_n_by_24h_quote_volume_usdt_perp",
        "top_n": int(top_n),
        "require_spot_pair": True,
        "known_limitations": [
            "current-snapshot universe; survivorship bias for delisted symbols",
            "no PIT membership; symbols may have onboarded mid-history",
        ],
        "symbols": [
            {
                **spec.to_dict(),
                "quote_volume_24h_usd": (
                    quote_volume_by_symbol.get(spec.symbol)
                    if quote_volume_by_symbol is not None
                    else None
                ),
            }
            for spec in perps
        ],
    }
    paths.manifest_path.write_text(json.dumps(payload, indent=2))
    return paths.manifest_path


def load_universe_manifest(base_dir: str | Path | None = None) -> dict:
    paths = default_paths(base_dir)
    if not paths.manifest_path.exists():
        raise FileNotFoundError(
            f"universe manifest not found at {paths.manifest_path} — run sync_binance_data.py first"
        )
    return json.loads(paths.manifest_path.read_text())
