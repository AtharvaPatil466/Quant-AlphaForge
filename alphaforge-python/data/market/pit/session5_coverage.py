"""Session 5 — yfinance coverage audit + SPX TR reconciliation.

Per PIT_UNIVERSE_DESIGN.md §7.2 and §7.4. Three sub-steps, each with
its own checkpoint so the long pull can be paused/resumed:

  [A] enumerate_ever_members()  — union of baseline + every ticker that
      appears as a target of ADD/RENAME in the event log.
  [B] pull_missing(ever_members) — for each ticker not already on disk
      (via the existing data/quarantine/market store), pull yfinance
      OHLCV. Polite throttle, retries, graceful failure. Caches per
      ticker per year.
  [C] coverage_report(ever_members) — for each ticker, compute the
      fraction of trading-day data present during its membership window.
      Tag <95% as known data gaps.
  [D] reconcile_spx_tr(events, baseline) — build a long-only equal-
      weight portfolio that rebalances monthly to reflect time-varying
      membership, compute its total return 2015-2025, compare to SPX TR
      (^SP500TR via yfinance).

Output:
    artifacts/_session5_coverage.csv          per-ticker coverage
    artifacts/_session5_audit.json            summary
    artifacts/_session5_spx_recon.csv         daily NAV vs SPX TR

Run:
    .venv/bin/python -m data.market.pit.session5_coverage
"""

from __future__ import annotations

import json
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable

import pandas as pd

ART = Path(__file__).resolve().parent / "artifacts"

# Re-use the existing parquet store layout: data/quarantine/market/<TICKER>/<YEAR>.parquet
# parents[4] is the project root (/Users/.../Quant Alpha/), one level above
# the alphaforge-python sub-project where this file lives.
ROOT = Path(__file__).resolve().parents[4]
PARQUET_STORE = ROOT / "data" / "quarantine" / "market"

import re as _re
_VALID_TICKER_RE = _re.compile(r'^[A-Z][A-Z0-9.\-]{0,9}$')


def _is_valid_ticker(t: str) -> bool:
    """A real US-equity ticker is 1-10 chars, starts with a letter, and
    contains only letters, digits, `.`, or `-`. Templates fragments like
    `{{NyseSymbol|MKTX}` get extracted by the parser but should never
    reach yfinance — filter them here."""
    return bool(t and _VALID_TICKER_RE.match(t))


# ── A. universe ──────────────────────────────────────────────────────

def enumerate_ever_members() -> set[str]:
    """Return the union of:
       - baseline membership (2010-01-23 snapshot, ~500 tickers)
       - every ticker that ever appears as ADD or RENAME-new-ticker in
         the event log
    Tickers appearing only as REMOVE or RENAME-old-ticker are already
    captured (they had to be members to be removed)."""
    baseline = set(
        pd.read_parquet(ART / "_baseline_2010-01-10.parquet")["ticker"]
        .dropna().astype(str)
    )
    events = pd.read_parquet(ART / "_event_log.parquet")
    add_tickers = set(events.loc[events["action"] == "ADD", "ticker"]
                      .dropna().astype(str))
    rename_new = set(events.loc[events["action"] == "RENAME", "ticker"]
                     .dropna().astype(str))
    rename_old = set(events.loc[events["action"] == "RENAME", "counterparty_ticker"]
                     .dropna().astype(str))
    remove_tickers = set(events.loc[events["action"] == "REMOVE", "ticker"]
                         .dropna().astype(str))
    union = baseline | add_tickers | rename_new | rename_old | remove_tickers
    return {t for t in union if _is_valid_ticker(t)}


def disk_tickers() -> set[str]:
    if not PARQUET_STORE.exists():
        return set()
    return {p.name for p in PARQUET_STORE.iterdir() if p.is_dir()}


# ── B. yfinance pull ────────────────────────────────────────────────

def _ticker_dir(ticker: str) -> Path:
    return PARQUET_STORE / ticker.upper()


def _normalize_yf_ticker(ticker: str) -> str:
    """yfinance uses `-` for share classes (BRK-B), Wikipedia uses `.` (BRK.B)."""
    return ticker.upper().replace(".", "-")


def _save_per_year(ticker: str, df: pd.DataFrame) -> int:
    """Persist one ticker's history as year-partitioned parquet."""
    if df is None or df.empty:
        return 0
    out_dir = _ticker_dir(ticker)
    out_dir.mkdir(parents=True, exist_ok=True)
    df = df.copy()
    df.index = pd.to_datetime(df.index)
    if hasattr(df.index, "tz") and df.index.tz is not None:
        df.index = df.index.tz_convert(None)
    rows = 0
    for year, sub in df.groupby(df.index.year):
        out_path = out_dir / f"{int(year)}.parquet"
        sub.to_parquet(out_path)
        rows += len(sub)
    return rows


def pull_batch(tickers: list[str], start: str = "2010-01-01") -> list[dict]:
    """Pull a batch of tickers via yf.download (much faster than per-ticker)."""
    import yfinance as yf
    if not tickers:
        return []
    yf_tickers = [_normalize_yf_ticker(t) for t in tickers]
    yf_to_orig = dict(zip(yf_tickers, tickers))

    try:
        df = yf.download(
            tickers=yf_tickers,
            start=start,
            auto_adjust=False,
            actions=True,
            progress=False,
            threads=True,
            group_by="ticker",
        )
    except Exception as exc:
        return [{"ticker": t, "ok": False, "rows_pulled": 0,
                 "error": f"batch: {type(exc).__name__}: {exc}"} for t in tickers]

    results: list[dict] = []
    for yft in yf_tickers:
        orig = yf_to_orig[yft]
        if df is None or df.empty:
            results.append({"ticker": orig, "ok": False, "rows_pulled": 0, "error": "empty batch"})
            continue
        # When only one ticker, columns are flat; when many, top-level is ticker.
        if isinstance(df.columns, pd.MultiIndex) and yft in df.columns.get_level_values(0):
            sub = df[yft].dropna(how="all")
        elif not isinstance(df.columns, pd.MultiIndex):
            sub = df.dropna(how="all")
        else:
            results.append({"ticker": orig, "ok": False, "rows_pulled": 0, "error": "ticker missing in batch"})
            continue
        if sub.empty:
            results.append({"ticker": orig, "ok": False, "rows_pulled": 0, "error": "empty after dropna"})
            continue
        rows = _save_per_year(orig, sub)
        results.append({"ticker": orig, "ok": rows > 0, "rows_pulled": rows,
                        "error": None if rows > 0 else "save returned 0 rows"})
    return results


def pull_missing(
    ever_members: set[str],
    batch_size: int = 50,
    sleep_between_batches: float = 1.0,
    max_to_pull: int | None = None,
) -> list[dict]:
    on_disk = disk_tickers()
    missing = sorted(t for t in ever_members if t.upper() not in on_disk)
    if max_to_pull is not None:
        missing = missing[:max_to_pull]
    print(f"  ever-members: {len(ever_members)} | on disk: {len(on_disk)} | to pull: {len(missing)}")

    results: list[dict] = []
    n_batches = (len(missing) + batch_size - 1) // batch_size
    for bi in range(n_batches):
        batch = missing[bi * batch_size : (bi + 1) * batch_size]
        batch_res = pull_batch(batch)
        results.extend(batch_res)
        n_ok = sum(1 for r in batch_res if r["ok"])
        print(f"    batch {bi+1:>3d}/{n_batches}: {n_ok}/{len(batch)} ok")
        time.sleep(sleep_between_batches)
    return results


# ── C. coverage report ─────────────────────────────────────────────

def _load_ticker_close(ticker: str) -> pd.Series:
    """Load all years of a ticker into one Close series (dates -> price)."""
    d = _ticker_dir(ticker)
    if not d.exists():
        return pd.Series(dtype="float64")
    frames: list[pd.DataFrame] = []
    for f in sorted(d.glob("*.parquet")):
        try:
            df = pd.read_parquet(f)
        except Exception:
            continue
        # The existing store uses 'Adj Close'; we use that too.
        col = "Adj Close" if "Adj Close" in df.columns else "Close"
        if col not in df.columns:
            continue
        s = df[col].copy()
        s.index = pd.to_datetime(s.index)
        frames.append(s.to_frame("price"))
    if not frames:
        return pd.Series(dtype="float64")
    out = pd.concat(frames).sort_index()
    out = out[~out.index.duplicated(keep="last")]
    return out["price"]


def _membership_windows(events: pd.DataFrame, baseline: set[str]) -> dict[str, list[tuple[str, str]]]:
    """For each ticker, list its (in_date, out_date) windows of membership.

    Tickers in baseline start at 2010-01-23 (baseline date). Tickers
    added later start at their ADD effective_date. They exit at their
    REMOVE effective_date (or pd.NaT if still member as of 2026-04-26).
    Renames are treated as continuous membership under the new ticker.
    """
    today = "2026-04-26"
    base_in = "2010-01-23"

    in_dates: dict[str, list[str]] = {t: [base_in] for t in baseline}
    out_dates: dict[str, list[str]] = {}

    sorted_events = events.sort_values("effective_date")
    for r in sorted_events.itertuples(index=False):
        t = str(r.ticker)
        d = str(r.effective_date)
        if r.action == "ADD":
            in_dates.setdefault(t, []).append(d)
        elif r.action == "REMOVE":
            out_dates.setdefault(t, []).append(d)
        elif r.action == "RENAME":
            old = str(r.counterparty_ticker) if pd.notna(r.counterparty_ticker) else None
            if old:
                out_dates.setdefault(old, []).append(d)
            in_dates.setdefault(t, []).append(d)

    # Pair inputs/outputs greedily.
    windows: dict[str, list[tuple[str, str]]] = {}
    all_tickers = set(in_dates) | set(out_dates)
    for t in all_tickers:
        ins = sorted(in_dates.get(t, []))
        outs = sorted(out_dates.get(t, []))
        pairs: list[tuple[str, str]] = []
        for i, in_d in enumerate(ins):
            out_d = outs[i] if i < len(outs) else today
            if out_d > in_d:
                pairs.append((in_d, out_d))
        windows[t] = pairs
    return windows


def coverage_report(events: pd.DataFrame, baseline: set[str]) -> pd.DataFrame:
    windows = _membership_windows(events, baseline)
    rows: list[dict] = []
    for ticker, pairs in windows.items():
        if not pairs:
            rows.append({"ticker": ticker, "n_windows": 0,
                         "expected_days": 0, "actual_days": 0,
                         "coverage_pct": 0.0, "on_disk": False})
            continue
        prices = _load_ticker_close(ticker)
        on_disk = not prices.empty
        total_expected = 0
        total_actual = 0
        for in_d, out_d in pairs:
            # Trading-day expected count: ~252/yr × years_in_window.
            in_dt = pd.Timestamp(in_d)
            out_dt = pd.Timestamp(out_d)
            years = max(0.0, (out_dt - in_dt).days / 365.25)
            expected = int(round(years * 252))
            actual = 0
            if on_disk:
                in_window = prices.loc[
                    (prices.index >= in_dt) & (prices.index <= out_dt)
                ]
                actual = int(in_window.notna().sum())
            total_expected += expected
            total_actual += actual
        cov = (total_actual / total_expected * 100) if total_expected else 0.0
        rows.append({
            "ticker": ticker, "n_windows": len(pairs),
            "expected_days": total_expected, "actual_days": total_actual,
            "coverage_pct": round(cov, 2), "on_disk": on_disk,
        })
    return pd.DataFrame(rows).sort_values("coverage_pct")


# ── D. SPX reconciliation ──────────────────────────────────────────

def reconcile_spx_tr(
    events: pd.DataFrame, baseline: set[str],
    start: str = "2015-01-02", end: str = "2025-12-31",
) -> dict:
    """Build long-only equal-weight monthly-rebalanced portfolio that
    reflects time-varying S&P 500 membership; compare to the
    Equal-Weight S&P 500 index (^SP500EW).

    Note: an earlier draft compared against ^SP500TR (cap-weight + total
    return). That comparison was structurally wrong because our
    portfolio is equal-weighted: equal-weight underperforms cap-weight
    by 200-400 bps/yr in megacap-dominated regimes regardless of
    universe quality. Comparing equal-weight to equal-weight isolates
    universe-construction quality from the weighting choice."""
    from .validator import membership_on_date

    # Pull S&P 500 Equal Weight index
    import yfinance as yf
    bench = yf.download("^SP500EW", start=start, end=end,
                        progress=False, auto_adjust=False)
    if bench.empty:
        return {"error": "could not fetch ^SP500EW"}
    bench_close = bench["Close"].copy()
    if isinstance(bench_close, pd.DataFrame):
        bench_close = bench_close.iloc[:, 0]
    bench_close.index = pd.to_datetime(bench_close.index)
    if hasattr(bench_close.index, "tz") and bench_close.index.tz is not None:
        bench_close.index = bench_close.index.tz_localize(None)

    # Determine month-start rebalance dates within the window. Each rebalance
    # holds from rd → nd; the resulting NAV is labeled with `nd` (the end of
    # the holding period) so that pct_change on the labeled series gives the
    # holding-period return aligned with the benchmark's price-at-date.
    rebal_dates = pd.date_range(start, end, freq="MS")
    nav = 1.0
    # Seed with the starting NAV at the first rebalance date so pct_change has
    # a baseline.
    nav_path: list[tuple[pd.Timestamp, float]] = [(rebal_dates[0], nav)]

    for i in range(len(rebal_dates) - 1):
        rd = rebal_dates[i]
        nd = rebal_dates[i + 1]
        members = membership_on_date(events, baseline, rd.date().isoformat())
        # Load each member's price series, restrict to window, drop NaN.
        prices: dict[str, pd.Series] = {}
        for t in members:
            s = _load_ticker_close(t)
            if s.empty:
                continue
            s = s.loc[(s.index >= rd) & (s.index <= nd)].dropna()
            if len(s) < 5 or s.iloc[0] <= 0 or not pd.notna(s.iloc[-1]):
                continue
            prices[t] = s
        if not prices:
            nav_path.append((nd, nav))
            continue
        # Equal-weight monthly return: average of (last/first - 1) per ticker.
        rets = [s.iloc[-1] / s.iloc[0] - 1 for s in prices.values()]
        # Drop any residual NaN/inf returns defensively.
        rets = [r for r in rets if pd.notna(r) and abs(r) < 5.0]
        if rets:
            nav *= (1.0 + sum(rets) / len(rets))
        nav_path.append((nd, nav))

    nav_df = pd.DataFrame(nav_path, columns=["date", "portfolio_nav"]).set_index("date")
    bench_aligned = bench_close.reindex(nav_df.index, method="nearest")
    bench_norm = bench_aligned / bench_aligned.iloc[0]
    nav_df["sp500ew_norm"] = bench_norm

    # Tracking error (annualized)
    port_ret = nav_df["portfolio_nav"].pct_change().dropna()
    bench_ret = nav_df["sp500ew_norm"].pct_change().dropna()
    common = port_ret.index.intersection(bench_ret.index)
    diff = port_ret.loc[common] - bench_ret.loc[common]
    annual_drift_bps = float(diff.mean() * 12 * 10000)
    tracking_error_bps = float(diff.std(ddof=0) * (12 ** 0.5) * 10000)

    nav_df.to_csv(ART / "_session5_spx_recon.csv")

    return {
        "benchmark": "^SP500EW (S&P 500 Equal Weight, price-only index)",
        "rebalance_periods": int(len(nav_df)),
        "final_portfolio_nav": float(nav_df["portfolio_nav"].iloc[-1]),
        "final_benchmark_norm": float(nav_df["sp500ew_norm"].iloc[-1]),
        "annualized_drift_bps": round(annual_drift_bps, 2),
        "annualized_tracking_error_bps": round(tracking_error_bps, 2),
        "csv": "_session5_spx_recon.csv",
    }


def main() -> int:
    print("session 5 — yfinance coverage + SPX TR reconciliation")
    print()

    print("[A] enumerating ever-members")
    ever = enumerate_ever_members()
    print(f"    universe: {len(ever)} tickers (baseline + ADD + RENAME both sides + REMOVE)")
    print()

    print("[B] pulling missing tickers from yfinance (this is the long step)")
    pull_results = pull_missing(ever)
    n_ok = sum(1 for r in pull_results if r["ok"])
    n_fail = sum(1 for r in pull_results if not r["ok"])
    print(f"    pulled OK: {n_ok}  | failed: {n_fail}")
    print()

    print("[C] coverage audit")
    events = pd.read_parquet(ART / "_event_log.parquet")
    baseline = set(pd.read_parquet(ART / "_baseline_2010-01-10.parquet")["ticker"]
                   .dropna().astype(str))
    cov = coverage_report(events, baseline)
    cov.to_csv(ART / "_session5_coverage.csv", index=False)
    n_total = len(cov)
    n_on_disk = int(cov["on_disk"].sum())
    n_above_95 = int((cov["coverage_pct"] >= 95).sum())
    print(f"    tickers checked: {n_total}")
    print(f"    on disk:         {n_on_disk}")
    print(f"    coverage ≥ 95%:  {n_above_95}")
    print()

    print("[D] SPX TR reconciliation 2015-01 → 2025-12")
    recon = reconcile_spx_tr(events, baseline)
    if "error" in recon:
        print(f"    ERROR: {recon['error']}")
    else:
        print(f"    rebalance periods:           {recon['rebalance_periods']}")
        print(f"    final portfolio NAV (norm):  {recon['final_portfolio_nav']:.4f}")
        print(f"    final SPX TR NAV (norm):     {recon['final_spx_tr_norm']:.4f}")
        print(f"    annualized drift:            {recon['annualized_drift_bps']:+.1f} bps")
        print(f"    annualized tracking error:   {recon['annualized_tracking_error_bps']:.1f} bps")
        gate_pass = abs(recon["annualized_drift_bps"]) <= 50
        print(f"    §7.2 gate (≤50 bps drift):   {'PASS' if gate_pass else 'FAIL'}")
    print()

    audit = {
        "session": "Phase 1 Session 5 — coverage + SPX reconciliation",
        "built_at": datetime.now(timezone.utc).isoformat(),
        "ever_members_count": len(ever),
        "pull_results": {"ok": n_ok, "failed": n_fail},
        "coverage": {
            "total": n_total,
            "on_disk": n_on_disk,
            "above_95_pct": n_above_95,
        },
        "spx_reconciliation": recon,
    }
    (ART / "_session5_audit.json").write_text(json.dumps(audit, indent=2, default=str))
    print(f"audit: {ART / '_session5_audit.json'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
