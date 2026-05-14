"""Binance public REST client.

Covers the endpoints needed by the v0 crypto data layer:
- spot klines, spot exchangeInfo, spot 24h ticker
- futures klines, futures exchangeInfo, futures 24h ticker
- futures funding rate history
- futures open interest history

No API key required — all endpoints used here are public. The client is
weight-aware: it parses the `X-MBX-USED-WEIGHT-1M` response header, tracks
recent consumption locally, and sleeps proactively if a request would push
usage past a configurable safety threshold. On 429 it honors the
`Retry-After` header; on 418 (IP ban) it raises immediately rather than
sleeping for many minutes inside a process.

For testability, the underlying `httpx.Client` is injectable. Tests pass an
`httpx.MockTransport` so no real network calls occur.
"""

from __future__ import annotations

import time
from collections import deque
from dataclasses import dataclass, field
from typing import Any, Iterable

import httpx


SPOT_BASE_URL = "https://api.binance.com"
FAPI_BASE_URL = "https://fapi.binance.com"

DEFAULT_TIMEOUT = 30.0
DEFAULT_USER_AGENT = "alphaforge-crypto/0.1 (research; public-data-only)"

SPOT_WEIGHT_PER_MINUTE = 6000
FAPI_WEIGHT_PER_MINUTE = 2400
WEIGHT_SAFETY_FRACTION = 0.85


class BinanceAPIError(RuntimeError):
    """Raised for non-2xx responses other than 429 (rate limit) and 418 (ban)."""

    def __init__(self, status_code: int, message: str, payload: Any = None):
        super().__init__(f"HTTP {status_code}: {message}")
        self.status_code = status_code
        self.payload = payload


class RateLimitedError(BinanceAPIError):
    """Raised on 429/418 after retry budget is exhausted, or immediately on 418."""


@dataclass
class _UsageTracker:
    """Rolling 60-second weight tracker shared across requests to the same venue."""

    cap: int
    used_recent: deque = field(default_factory=deque)

    def record(self, weight: int) -> None:
        now = time.monotonic()
        self.used_recent.append((now, weight))
        self._evict(now)

    def current(self) -> int:
        self._evict(time.monotonic())
        return sum(weight for _, weight in self.used_recent)

    def _evict(self, now: float) -> None:
        cutoff = now - 60.0
        while self.used_recent and self.used_recent[0][0] < cutoff:
            self.used_recent.popleft()

    def maybe_sleep(self, intended_weight: int) -> float:
        threshold = int(self.cap * WEIGHT_SAFETY_FRACTION)
        if self.current() + intended_weight <= threshold:
            return 0.0
        if not self.used_recent:
            return 0.0
        oldest_ts = self.used_recent[0][0]
        wait = max(0.0, 60.0 - (time.monotonic() - oldest_ts) + 0.25)
        if wait > 0:
            time.sleep(wait)
        return wait


def _kline_weight(limit: int) -> int:
    if limit <= 100:
        return 2
    if limit <= 500:
        return 5
    if limit <= 1000:
        return 10
    return 20


class BinanceClient:
    """Weight-aware HTTP client for Binance public endpoints.

    The two venues (spot vs futures) are tracked separately because their
    rate-limit pools are independent.
    """

    def __init__(
        self,
        *,
        spot_base_url: str = SPOT_BASE_URL,
        fapi_base_url: str = FAPI_BASE_URL,
        timeout: float = DEFAULT_TIMEOUT,
        transport: httpx.BaseTransport | None = None,
        max_retries: int = 4,
    ):
        self.spot_base_url = spot_base_url.rstrip("/")
        self.fapi_base_url = fapi_base_url.rstrip("/")
        self.max_retries = max_retries
        self._client = httpx.Client(
            timeout=timeout,
            transport=transport,
            headers={"User-Agent": DEFAULT_USER_AGENT, "Accept": "application/json"},
        )
        self._spot_usage = _UsageTracker(cap=SPOT_WEIGHT_PER_MINUTE)
        self._fapi_usage = _UsageTracker(cap=FAPI_WEIGHT_PER_MINUTE)

    def close(self) -> None:
        self._client.close()

    def __enter__(self) -> "BinanceClient":
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self.close()

    # ---- low-level request loop -------------------------------------------------

    def _request(
        self,
        venue: str,
        path: str,
        params: dict[str, Any] | None,
        intended_weight: int,
    ) -> Any:
        if venue == "spot":
            base = self.spot_base_url
            usage = self._spot_usage
        elif venue == "fapi":
            base = self.fapi_base_url
            usage = self._fapi_usage
        else:
            raise ValueError(f"unknown venue {venue!r}")

        usage.maybe_sleep(intended_weight)
        url = f"{base}{path}"
        clean_params = {k: v for k, v in (params or {}).items() if v is not None}

        attempt = 0
        backoff = 1.0
        while True:
            response = self._client.get(url, params=clean_params)
            used_header = (
                response.headers.get("X-MBX-USED-WEIGHT-1M")
                or response.headers.get("X-MBX-USED-WEIGHT")
            )
            if used_header is not None:
                try:
                    observed = int(used_header)
                    usage.used_recent.clear()
                    usage.used_recent.append((time.monotonic(), observed))
                except ValueError:
                    usage.record(intended_weight)
            else:
                usage.record(intended_weight)

            if response.status_code == 200:
                return response.json()

            if response.status_code == 418:
                raise RateLimitedError(418, "IP banned by Binance (418)", response.text)

            if response.status_code == 429 and attempt < self.max_retries:
                retry_after = float(response.headers.get("Retry-After", backoff))
                time.sleep(retry_after)
                attempt += 1
                backoff *= 2
                continue

            if 500 <= response.status_code < 600 and attempt < self.max_retries:
                time.sleep(backoff)
                attempt += 1
                backoff *= 2
                continue

            try:
                payload = response.json()
                message = payload.get("msg", response.text) if isinstance(payload, dict) else response.text
            except Exception:
                payload = response.text
                message = response.text

            if response.status_code == 429:
                raise RateLimitedError(429, "rate-limited after retries", payload)
            raise BinanceAPIError(response.status_code, message, payload)

    # ---- exchange info ---------------------------------------------------------

    def spot_exchange_info(self) -> dict[str, Any]:
        return self._request("spot", "/api/v3/exchangeInfo", None, intended_weight=10)

    def fapi_exchange_info(self) -> dict[str, Any]:
        return self._request("fapi", "/fapi/v1/exchangeInfo", None, intended_weight=1)

    # ---- 24h tickers ----------------------------------------------------------

    def spot_24h_tickers(self, symbols: Iterable[str] | None = None) -> list[dict[str, Any]]:
        params: dict[str, Any] = {}
        if symbols is not None:
            params["symbols"] = _binance_symbols_array(symbols)
        weight = 1 if symbols and len(list(symbols)) <= 20 else 40
        result = self._request("spot", "/api/v3/ticker/24hr", params, intended_weight=weight)
        return result if isinstance(result, list) else [result]

    def fapi_24h_tickers(self, symbol: str | None = None) -> list[dict[str, Any]]:
        params = {"symbol": symbol} if symbol else None
        weight = 1 if symbol else 40
        result = self._request("fapi", "/fapi/v1/ticker/24hr", params, intended_weight=weight)
        return result if isinstance(result, list) else [result]

    # ---- klines ----------------------------------------------------------------

    def spot_klines(
        self,
        symbol: str,
        interval: str,
        *,
        start_time_ms: int | None = None,
        end_time_ms: int | None = None,
        limit: int = 1000,
    ) -> list[list[Any]]:
        params = {
            "symbol": symbol.upper(),
            "interval": interval,
            "startTime": start_time_ms,
            "endTime": end_time_ms,
            "limit": limit,
        }
        return self._request("spot", "/api/v3/klines", params, intended_weight=_kline_weight(limit))

    def fapi_klines(
        self,
        symbol: str,
        interval: str,
        *,
        start_time_ms: int | None = None,
        end_time_ms: int | None = None,
        limit: int = 1000,
    ) -> list[list[Any]]:
        params = {
            "symbol": symbol.upper(),
            "interval": interval,
            "startTime": start_time_ms,
            "endTime": end_time_ms,
            "limit": limit,
        }
        return self._request("fapi", "/fapi/v1/klines", params, intended_weight=_kline_weight(limit))

    # ---- funding & OI ----------------------------------------------------------

    def funding_rate_history(
        self,
        symbol: str,
        *,
        start_time_ms: int | None = None,
        end_time_ms: int | None = None,
        limit: int = 1000,
    ) -> list[dict[str, Any]]:
        params = {
            "symbol": symbol.upper(),
            "startTime": start_time_ms,
            "endTime": end_time_ms,
            "limit": limit,
        }
        return self._request("fapi", "/fapi/v1/fundingRate", params, intended_weight=1)

    def open_interest_history(
        self,
        symbol: str,
        period: str = "1h",
        *,
        start_time_ms: int | None = None,
        end_time_ms: int | None = None,
        limit: int = 500,
    ) -> list[dict[str, Any]]:
        params = {
            "symbol": symbol.upper(),
            "period": period,
            "startTime": start_time_ms,
            "endTime": end_time_ms,
            "limit": limit,
        }
        return self._request("fapi", "/futures/data/openInterestHist", params, intended_weight=1)


def _binance_symbols_array(symbols: Iterable[str]) -> str:
    quoted = ",".join(f'"{s.upper()}"' for s in symbols)
    return f"[{quoted}]"
