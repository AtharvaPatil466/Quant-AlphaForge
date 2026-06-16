"""Read-only Kalshi REST client — the ONLY module that touches the network.

Per `research/PREDICTION_MARKETS_DESIGN.md` §2 and the confirmed endpoint
shapes in `research/SPIKE_NOTES.md`.

Base: ``https://api.elections.kalshi.com/trade-api/v2`` (no auth for market data).

Surfaces:
  - ``iter_settled_markets`` — cursor-paginated settled/finalized markets.
  - ``get_event``           — event lookup → (series_ticker, category, ...).
  - ``get_candlesticks``    — price/quote history for entry-price reconstruction.

Operational policy (mirrors `alphaforge-india/ingest/downloader.py`):
  - Single ``requests.Session``; injectable for tests (no live calls in tests).
  - Rate-limited: a minimum gap between requests (token-bucket on wall clock).
  - Retry with exponential backoff on 5xx / timeouts / connection errors.
  - 429 honours ``Retry-After`` when present, else backs off and retries; after
    exhausting retries it raises ``RateLimitedError`` (caller may halt/resume).
  - 4xx other than 429 raise ``KalshiAPIError`` immediately (no retry).
  - All ``*_dollars`` / ``*_fp`` fields are JSON strings — callers coerce via
    ``ingest.schema``; the client returns raw JSON dicts unmodified.
"""
from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from typing import Any, Iterator

import requests

log = logging.getLogger("prediction.kalshi_client")

BASE_URL = "https://api.elections.kalshi.com/trade-api/v2"

DEFAULT_HEADERS: dict[str, str] = {
    "Accept": "application/json",
    "User-Agent": "alphaforge-prediction/0.1 (+research; read-only)",
}

# Retry schedule (seconds). Length determines max attempt count.
RETRY_BACKOFF: tuple[float, ...] = (1.0, 4.0, 16.0)

# Candlesticks hard limits confirmed live (SPIKE_NOTES.md (a)).
VALID_PERIOD_INTERVALS: frozenset[int] = frozenset({1, 60, 1440})
MAX_CANDLES_PER_REQUEST: int = 5000


class KalshiAPIError(Exception):
    """Non-retryable HTTP error (4xx other than 429), or a malformed body."""

    def __init__(self, message: str, status: int | None = None):
        super().__init__(message)
        self.status = status


class RateLimitedError(KalshiAPIError):
    """429 persisted across all retries. Caller may halt and resume later."""


@dataclass
class KalshiClientConfig:
    base_url: str = BASE_URL
    rate_limit_seconds: float = 0.25     # >= 4 req/s ceiling; conservative
    timeout_seconds: float = 30.0
    headers: dict[str, str] = field(default_factory=lambda: dict(DEFAULT_HEADERS))
    max_attempts: int = len(RETRY_BACKOFF)


class KalshiClient:
    def __init__(
        self,
        config: KalshiClientConfig | None = None,
        session: requests.Session | None = None,
    ):
        self.cfg = config or KalshiClientConfig()
        self.session = session or requests.Session()
        self._last_request_at: float = 0.0

    # -- low-level -----------------------------------------------------------

    def _throttle(self) -> None:
        elapsed = time.time() - self._last_request_at
        wait = self.cfg.rate_limit_seconds - elapsed
        if wait > 0:
            time.sleep(wait)
        self._last_request_at = time.time()

    def _get(self, path: str, params: dict[str, Any] | None = None) -> dict:
        """GET {base}{path}; retry transient failures; return parsed JSON dict."""
        url = self.cfg.base_url + path
        last_error: str | None = None
        for attempt in range(1, self.cfg.max_attempts + 1):
            self._throttle()
            try:
                resp = self.session.get(
                    url,
                    params=params,
                    headers=self.cfg.headers,
                    timeout=self.cfg.timeout_seconds,
                )
            except requests.RequestException as e:
                last_error = repr(e)
                log.warning("GET %s attempt %d transient error: %s", path, attempt, last_error)
                self._sleep_for_attempt(attempt)
                continue

            status = resp.status_code
            if status == 200:
                try:
                    body = resp.json()
                except ValueError as e:
                    raise KalshiAPIError(f"GET {path} returned non-JSON 200: {e!r}", status)
                if not isinstance(body, dict):
                    raise KalshiAPIError(f"GET {path} returned non-object JSON", status)
                return body

            if status == 429:
                retry_after = self._retry_after_seconds(resp)
                last_error = f"429 rate limited (retry_after={retry_after})"
                log.warning("GET %s attempt %d: %s", path, attempt, last_error)
                if attempt < self.cfg.max_attempts:
                    time.sleep(retry_after if retry_after is not None
                               else RETRY_BACKOFF[min(attempt - 1, len(RETRY_BACKOFF) - 1)])
                    continue
                raise RateLimitedError(f"GET {path} rate limited after {attempt} attempts", status)

            if 500 <= status < 600:
                last_error = f"http {status}"
                log.warning("GET %s attempt %d server error %d", path, attempt, status)
                self._sleep_for_attempt(attempt)
                continue

            # 4xx (other than 429): non-retryable.
            detail = self._error_detail(resp)
            raise KalshiAPIError(f"GET {path} -> {status}: {detail}", status)

        raise KalshiAPIError(f"GET {path} failed after {self.cfg.max_attempts} attempts: {last_error}")

    def _sleep_for_attempt(self, attempt: int) -> None:
        if attempt < self.cfg.max_attempts:
            time.sleep(RETRY_BACKOFF[min(attempt - 1, len(RETRY_BACKOFF) - 1)])

    @staticmethod
    def _retry_after_seconds(resp: requests.Response) -> float | None:
        val = resp.headers.get("Retry-After")
        if val is None:
            return None
        try:
            return max(0.0, float(val))
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _error_detail(resp: requests.Response) -> str:
        try:
            body = resp.json()
        except ValueError:
            return resp.text[:200]
        if isinstance(body, dict):
            err = body.get("error")
            if isinstance(err, dict):
                return str(err.get("message") or err.get("details") or err)
            return str(body.get("msg") or body.get("error") or body)[:200]
        return str(body)[:200]

    # -- markets -------------------------------------------------------------

    def get_markets_page(
        self,
        status: str | None = "settled",
        limit: int = 200,
        cursor: str | None = None,
        extra_params: dict[str, Any] | None = None,
    ) -> tuple[list[dict], str | None]:
        """One page of markets. Returns (markets, next_cursor).

        ``next_cursor`` is None when there are no further pages (empty/absent).

        ``status=None`` omits the ``status`` filter — required when paging by
        ``min_close_ts``/``max_close_ts`` to reach historical markets (the
        ``status=settled`` filter returns empty for old date windows on the
        elections host; resolved rows are filtered client-side instead). See
        SPIKE_NOTES.md.
        """
        params: dict[str, Any] = {"limit": limit}
        if status is not None:
            params["status"] = status
        if cursor:
            params["cursor"] = cursor
        if extra_params:
            params.update(extra_params)
        body = self._get("/markets", params)
        markets = body.get("markets") or []
        if not isinstance(markets, list):
            raise KalshiAPIError("/markets returned non-list 'markets'")
        next_cursor = body.get("cursor") or None
        return markets, next_cursor

    def iter_settled_markets(
        self,
        limit: int = 200,
        max_pages: int | None = None,
        status: str | None = "settled",
        start_cursor: str | None = None,
        min_close_ts: int | None = None,
        max_close_ts: int | None = None,
    ) -> Iterator[tuple[dict, str | None]]:
        """Yield (market, cursor_that_produced_this_page) across all pages.

        The yielded cursor is the *next* cursor for the page the market came
        from, enabling the downloader to checkpoint resumption precisely.
        Stops after ``max_pages`` pages if set.

        Pass ``min_close_ts``/``max_close_ts`` (epoch seconds) to page a
        historical date window; in that mode pass ``status=None`` so the
        ``status`` filter does not suppress old rows (see SPIKE_NOTES.md), and
        the downloader filters resolved + volume-bearing rows client-side.
        """
        extra: dict[str, Any] = {}
        if min_close_ts is not None:
            extra["min_close_ts"] = int(min_close_ts)
        if max_close_ts is not None:
            extra["max_close_ts"] = int(max_close_ts)
        cursor = start_cursor
        pages = 0
        while True:
            markets, next_cursor = self.get_markets_page(
                status=status, limit=limit, cursor=cursor,
                extra_params=extra or None,
            )
            pages += 1
            for m in markets:
                yield m, next_cursor
            if not next_cursor or not markets:
                return
            if max_pages is not None and pages >= max_pages:
                return
            cursor = next_cursor

    # -- events --------------------------------------------------------------

    def get_events_page(
        self,
        status: str | None = "open",
        limit: int = 200,
        cursor: str | None = None,
        with_nested_markets: bool = True,
        extra_params: dict[str, Any] | None = None,
    ) -> tuple[list[dict], str | None]:
        """One page of events. Returns (events, next_cursor).

        Each event carries ``category`` and ``series_ticker`` (both absent on the
        bare market) and — with ``with_nested_markets`` — its open markets inline
        (each nested market carries ``ticker``/``volume_fp``/``yes_bid/ask_dollars``/
        ``last_price_dollars``/``close_time``). This is the ONLY way to reach the
        non-MVE classic-event universe on the free host: the unfiltered
        ``/markets?status=open`` feed is saturated by MVE parlay legs and never
        surfaces classic events (probe `research/probe_open_universe.py`).
        """
        params: dict[str, Any] = {"limit": limit}
        if status is not None:
            params["status"] = status
        if with_nested_markets:
            params["with_nested_markets"] = "true"
        if cursor:
            params["cursor"] = cursor
        if extra_params:
            params.update(extra_params)
        body = self._get("/events", params)
        events = body.get("events") or []
        if not isinstance(events, list):
            raise KalshiAPIError("/events returned non-list 'events'")
        next_cursor = body.get("cursor") or None
        return events, next_cursor

    def iter_open_events(
        self,
        limit: int = 200,
        max_pages: int | None = None,
        status: str | None = "open",
        with_nested_markets: bool = True,
        start_cursor: str | None = None,
    ) -> Iterator[tuple[dict, str | None]]:
        """Yield (event, next_cursor) across event pages (cursor-paginated).

        Mirrors ``iter_settled_markets`` semantics. Stops after ``max_pages``.
        """
        cursor = start_cursor
        pages = 0
        while True:
            events, next_cursor = self.get_events_page(
                status=status, limit=limit, cursor=cursor,
                with_nested_markets=with_nested_markets,
            )
            pages += 1
            for e in events:
                yield e, next_cursor
            if not next_cursor or not events:
                return
            if max_pages is not None and pages >= max_pages:
                return
            cursor = next_cursor

    def get_event(self, event_ticker: str) -> dict:
        """Event lookup. Returns the inner event dict.

        Carries ``series_ticker`` and ``category`` (both absent on the market;
        see SPIKE_NOTES.md (a)).
        """
        body = self._get(f"/events/{event_ticker}")
        event = body.get("event")
        if isinstance(event, dict):
            return event
        # Some responses inline the event fields at top level.
        return body

    def get_series(self, series_ticker: str) -> dict:
        """Series lookup (richer metadata). Returns the inner series dict."""
        body = self._get(f"/series/{series_ticker}")
        series = body.get("series")
        if isinstance(series, dict):
            return series
        return body

    # -- candlesticks --------------------------------------------------------

    def get_candlesticks(
        self,
        series_ticker: str,
        ticker: str,
        start_ts: int,
        end_ts: int,
        period_interval: int = 1,
    ) -> list[dict]:
        """Candlesticks for one market over [start_ts, end_ts] (epoch seconds).

        ``period_interval`` minutes must be in {1, 60, 1440}. Raises
        ``ValueError`` for an invalid interval or a window that would exceed the
        5000-candle cap (caller must window long-lived markets).
        """
        if period_interval not in VALID_PERIOD_INTERVALS:
            raise ValueError(
                f"period_interval must be one of {sorted(VALID_PERIOD_INTERVALS)}, "
                f"got {period_interval}"
            )
        if end_ts < start_ts:
            raise ValueError(f"end_ts ({end_ts}) < start_ts ({start_ts})")
        n_candles = (end_ts - start_ts) / (period_interval * 60)
        if n_candles > MAX_CANDLES_PER_REQUEST:
            raise ValueError(
                f"window implies {n_candles:.0f} candles > {MAX_CANDLES_PER_REQUEST} cap; "
                f"window the request"
            )
        body = self._get(
            f"/series/{series_ticker}/markets/{ticker}/candlesticks",
            {"start_ts": int(start_ts), "end_ts": int(end_ts),
             "period_interval": int(period_interval)},
        )
        candles = body.get("candlesticks") or []
        if not isinstance(candles, list):
            raise KalshiAPIError("candlesticks returned non-list 'candlesticks'")
        return candles
