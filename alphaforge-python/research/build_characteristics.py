"""
Build monthly characteristics table for Phase 3.
Output: date, ticker, market_cap, book_to_market, profitability, investment

Sources:
  - Prices:      data/quarantine/market/<TICKER>/<YEAR>.parquet
  - Fundamentals: SEC EDGAR Financial Statement Data Sets
  - CIK map:     data/market/pit/artifacts/edgar_company_tickers.json
"""
from __future__ import annotations
import json
import requests
import pandas as pd
import numpy as np
from pathlib import Path
import time

PYTHON_DIR   = Path(__file__).resolve().parent.parent
REPO_DIR     = PYTHON_DIR.parent
QUARANTINE   = REPO_DIR / "data/quarantine/market"
CIK_FILE     = PYTHON_DIR / "data/market/pit/artifacts/edgar_company_tickers.json"
OUT_PATH     = PYTHON_DIR / "research/phase3_raw_characteristics.csv"

EDGAR_BASE   = "https://data.sec.gov/api/xbrl/companyfacts"
FSDS_BASE    = "https://www.sec.gov/Archives/edgar/full-index"
HEADERS      = {"User-Agent": "atharva research atharva@example.com"}

# XBRL tags to try in order (first hit wins).
# Each entry is (namespace, tag, preferred_units).
TAGS = {
    "shares": [
        ("dei", "EntityCommonStockSharesOutstanding", ("shares",)),
        ("dei", "CommonStockSharesOutstanding", ("shares",)),
        ("us-gaap", "CommonStockSharesOutstanding", ("shares",)),
        ("us-gaap", "EntityCommonStockSharesOutstanding", ("shares",)),
    ],
    "equity": [
        ("us-gaap", "StockholdersEquity", ("USD",)),
        ("us-gaap", "StockholdersEquityIncludingPortionAttributableToNoncontrollingInterest", ("USD",)),
        ("us-gaap", "StockholdersEquityIncludingPortionAttributableToRedeemableNoncontrollingInterest", ("USD",)),
        ("us-gaap", "CommonStockholdersEquity", ("USD",)),
    ],
    "deferred_taxes": [
        ("us-gaap", "DeferredTaxAssetsLiabilitiesNet", ("USD",)),
        ("us-gaap", "DeferredTaxAssetsNet", ("USD",)),
        ("us-gaap", "DeferredTaxLiabilitiesNet", ("USD",)),
        ("us-gaap", "DeferredTaxAndInvestmentTaxCredit", ("USD",)),
    ],
    "preferred_stock": [
        ("us-gaap", "PreferredStockValue", ("USD",)),
        ("us-gaap", "PreferredStockLiquidatingValue", ("USD",)),
        ("us-gaap", "PreferredStockRedemptionValue", ("USD",)),
        ("us-gaap", "RedeemablePreferredStockCarryingAmount", ("USD",)),
    ],
    "revenue": [
        ("us-gaap", "RevenueFromContractWithCustomerExcludingAssessedTax", ("USD",)),
        ("us-gaap", "RevenueFromContractWithCustomerIncludingAssessedTax", ("USD",)),
        ("us-gaap", "SalesRevenueNet", ("USD",)),
        ("us-gaap", "Revenues", ("USD",)),
    ],
    "cogs": [
        ("us-gaap", "CostOfGoodsSold", ("USD",)),
        ("us-gaap", "CostOfRevenue", ("USD",)),
        ("us-gaap", "CostOfSales", ("USD",)),
    ],
    "sga": [
        ("us-gaap", "SellingGeneralAndAdministrativeExpense", ("USD",)),
    ],
    "interest_expense": [
        ("us-gaap", "InterestExpenseAndDebtExpense", ("USD",)),
        ("us-gaap", "InterestExpense", ("USD",)),
        ("us-gaap", "InterestAndDebtExpense", ("USD",)),
    ],
    "assets": [
        ("us-gaap", "Assets", ("USD",)),
    ],
}

ANNUAL_FORMS = ("10-K", "10-K/A")
SHARE_FORMS = ("10-K", "10-K/A", "10-Q", "10-Q/A")

def load_cik_map() -> dict[str, str]:
    """Return {TICKER: CIK_padded_10} from edgar_company_tickers.json"""
    raw = json.loads(CIK_FILE.read_text())
    out = {}
    for entry in raw.values():
        ticker = str(entry.get("ticker", "")).upper()
        cik    = str(entry.get("cik_str", entry.get("cik", ""))).zfill(10)
        if ticker and cik:
            out[ticker] = cik
    return out

def get_available_tickers() -> list[str]:
    return sorted([p.name for p in QUARANTINE.iterdir() if p.is_dir()])

def load_month_end_prices(ticker: str) -> pd.Series:
    """Return month-end close prices as Series indexed by date."""
    folder = QUARANTINE / ticker
    frames = []
    for f in sorted(folder.glob("*.parquet")):
        try:
            df = pd.read_parquet(f)
            frames.append(df)
        except Exception:
            continue
    if not frames:
        return pd.Series(dtype=float)
    prices = pd.concat(frames).sort_index()
    # normalize index to datetime
    if not isinstance(prices.index, pd.DatetimeIndex):
        prices.index = pd.to_datetime(prices.index)
    # get close column
    col = next((c for c in ["Close", "close", "Adj Close", "adj_close"] 
                if c in prices.columns), None)
    if col is None:
        return pd.Series(dtype=float)
    close = prices[col].dropna()
    close.index = pd.to_datetime(close.index)
    return close.resample("ME").last()

def fetch_company_facts(cik: str) -> dict:
    url = f"{EDGAR_BASE}/CIK{cik}.json"
    try:
        r = requests.get(url, headers=HEADERS, timeout=15)
        if r.status_code == 200:
            return r.json()
    except Exception:
        pass
    return {}

def extract_reported_frame(
    facts: dict,
    tags: list[tuple[str, str, tuple[str, ...]]],
    forms: tuple[str, ...],
) -> pd.DataFrame:
    """Extract reported values for the first matching tag.

    Returns a frame with columns `end`, `filed`, `val`, sorted by filing
    date. Multiple rows can exist for one fiscal period end when a later
    amendment updates the value.
    """
    fact_roots = facts.get("facts", {})
    for namespace, tag, unit_priority in tags:
        namespace_facts = fact_roots.get(namespace, {})
        if tag not in namespace_facts:
            continue
        units = namespace_facts[tag].get("units", {})
        ordered_units = [u for u in unit_priority if u in units]
        ordered_units.extend(u for u in units if u not in ordered_units)
        for unit_key in ordered_units:
            if unit_key not in units:
                continue
            rows = [r for r in units[unit_key]
                    if r.get("form") in forms
                    and r.get("end") and r.get("filed") and r.get("val") is not None]
            if not rows:
                continue
            df = pd.DataFrame(rows)
            df["end"] = pd.to_datetime(df["end"])
            df["filed"] = pd.to_datetime(df["filed"]).dt.tz_localize(None).dt.normalize()
            df["val"] = pd.to_numeric(df["val"], errors="coerce")
            df = df.dropna(subset=["filed", "val"])
            if df.empty:
                continue
            # Keep every filing-date update, including later 10-K/A amendments.
            # If multiple rows share the same filing date, prefer the latest one.
            df = df.sort_values(["filed", "end"]).drop_duplicates("filed", keep="last")
            out = df.loc[:, ["end", "filed", "val"]].reset_index(drop=True)
            out.attrs["source_tag"] = tag
            out.attrs["source_namespace"] = namespace
            return out
    return pd.DataFrame(columns=["end", "filed", "val"])


def extract_annual_frame(
    facts: dict,
    tags: list[tuple[str, str, tuple[str, ...]]],
) -> pd.DataFrame:
    """Extract annual 10-K values for the first matching tag."""
    return extract_reported_frame(facts, tags, ANNUAL_FORMS)


def extract_annual_series(
    facts: dict,
    tags: list[tuple[str, str, tuple[str, ...]]],
) -> pd.Series:
    """Filed-date indexed wrapper over `extract_annual_frame()`."""
    frame = extract_annual_frame(facts, tags)
    if frame.empty:
        return pd.Series(dtype=float)
    return frame.set_index("filed")["val"].sort_index()


def extract_share_frame(facts: dict) -> pd.DataFrame:
    """Extract share-count facts from annual and quarterly filings."""
    return extract_reported_frame(facts, TAGS["shares"], SHARE_FORMS)


def compute_annual_growth(frame: pd.DataFrame) -> pd.Series:
    """Filed-date indexed annual growth that respects 10-K/A amendments.

    When an amended filing updates the same fiscal year end, growth is
    recomputed versus the latest available prior fiscal year rather than
    versus the superseded original filing from the same fiscal year.
    """
    if frame.empty:
        return pd.Series(dtype=float)

    latest_by_end: dict[pd.Timestamp, float] = {}
    growth_rows: list[tuple[pd.Timestamp, float]] = []
    ordered = frame.sort_values(["filed", "end"]).reset_index(drop=True)
    for row in ordered.itertuples(index=False):
        current_end = pd.Timestamp(row.end)
        prev_ends = [end for end in latest_by_end if end < current_end]
        if prev_ends:
            prev_end = max(prev_ends)
            prev_val = latest_by_end[prev_end]
            growth = np.nan if not np.isfinite(prev_val) or abs(prev_val) <= 1e-12 else float(row.val / prev_val - 1.0)
        else:
            growth = np.nan
        latest_by_end[current_end] = float(row.val)
        growth_rows.append((pd.Timestamp(row.filed), growth))
    return pd.Series(dict(growth_rows)).sort_index()


def latest_fiscal_year_value(
    frame: pd.DataFrame,
    fiscal_year: int,
    as_of: pd.Timestamp,
) -> float:
    """Latest filed annual value for a fiscal-year end, as known on `as_of`."""
    if frame.empty:
        return float("nan")
    eligible = frame[
        (frame["end"].dt.year == fiscal_year)
        & (frame["filed"] <= pd.Timestamp(as_of))
    ]
    if eligible.empty:
        return float("nan")
    row = eligible.sort_values(["filed", "end"]).iloc[-1]
    return float(row["val"])


def ff_formation_year(as_of: pd.Timestamp) -> int:
    """French annual sorts formed each June and held through next June."""
    dt = pd.Timestamp(as_of)
    return dt.year if dt.month >= 6 else dt.year - 1

def build_ticker_characteristics(
    ticker: str,
    cik: str,
) -> pd.DataFrame:
    """Return monthly rows for one ticker."""
    prices = load_month_end_prices(ticker)
    if prices.empty:
        return pd.DataFrame()

    facts = fetch_company_facts(cik)
    if not facts:
        return pd.DataFrame()

    shares_frame = extract_share_frame(facts)
    equity_frame = extract_annual_frame(facts, TAGS["equity"])
    equity       = equity_frame.set_index("filed")["val"].sort_index() if not equity_frame.empty else pd.Series(dtype=float)
    deferred_tax_frame = extract_annual_frame(facts, TAGS["deferred_taxes"])
    preferred_stock_frame = extract_annual_frame(facts, TAGS["preferred_stock"])
    assets_frame = extract_annual_frame(facts, TAGS["assets"])
    assets       = assets_frame.set_index("filed")["val"].sort_index() if not assets_frame.empty else pd.Series(dtype=float)
    revenue_frame = extract_annual_frame(facts, TAGS["revenue"])
    cogs_frame = extract_annual_frame(facts, TAGS["cogs"])
    sga_frame = extract_annual_frame(facts, TAGS["sga"])
    interest_expense_frame = extract_annual_frame(facts, TAGS["interest_expense"])

    if shares_frame.empty or equity.empty or assets.empty:
        return pd.DataFrame()

    # Reindex annual series to month-end and forward-fill from filing dates,
    # not fiscal-period end dates, so characteristics only become usable
    # after the annual report was actually filed with the SEC.
    idx = prices.index
    def to_monthly(s: pd.Series) -> pd.Series:
        if s.empty:
            return pd.Series(np.nan, index=idx)
        combined = s.reindex(s.index.union(idx)).sort_index().ffill()
        return combined.reindex(idx)

    shares_filed = shares_frame.set_index("filed")["val"].sort_index()
    sh = to_monthly(shares_filed)
    mktcap = sh * prices

    shares_period_end = (
        shares_frame.sort_values(["end", "filed"])
        .drop_duplicates("end", keep="last")
        .set_index("end")["val"]
        .sort_index()
    )
    sh_period_end = to_monthly(shares_period_end)
    dec_market_cap_series = sh_period_end * prices

    dec_market_cap: dict[int, float] = {}
    dec_rows = dec_market_cap_series[dec_market_cap_series.index.month == 12].dropna()
    for dt, val in dec_rows.items():
        dec_market_cap[pd.Timestamp(dt).year] = float(val)

    rows: list[dict[str, object]] = []
    for dt in idx:
        formation_year = ff_formation_year(dt)
        fiscal_year = formation_year - 1
        prior_fiscal_year = fiscal_year - 1
        dec_year = formation_year - 1

        market_cap = float(mktcap.loc[dt]) if dt in mktcap.index and np.isfinite(mktcap.loc[dt]) else float("nan")
        base_equity = latest_fiscal_year_value(equity_frame, fiscal_year, dt)
        deferred_taxes = latest_fiscal_year_value(deferred_tax_frame, fiscal_year, dt)
        preferred_stock = latest_fiscal_year_value(preferred_stock_frame, fiscal_year, dt)
        assets_t1 = latest_fiscal_year_value(assets_frame, fiscal_year, dt)
        assets_t2 = latest_fiscal_year_value(assets_frame, prior_fiscal_year, dt)
        revenue = latest_fiscal_year_value(revenue_frame, fiscal_year, dt)
        cogs = latest_fiscal_year_value(cogs_frame, fiscal_year, dt)
        sga = latest_fiscal_year_value(sga_frame, fiscal_year, dt)
        interest_expense = latest_fiscal_year_value(interest_expense_frame, fiscal_year, dt)
        dec_cap = dec_market_cap.get(dec_year, float("nan"))

        book_equity = base_equity
        if np.isfinite(book_equity):
            if np.isfinite(deferred_taxes):
                book_equity += deferred_taxes
            if equity_frame.attrs.get("source_tag") != "CommonStockholdersEquity" and np.isfinite(preferred_stock):
                book_equity -= preferred_stock

        has_op_inputs = np.isfinite(revenue) and any(
            np.isfinite(x) for x in (cogs, sga, interest_expense)
        )
        operating_profitability = float("nan")
        if has_op_inputs and np.isfinite(book_equity) and abs(book_equity) > 1e-12:
            operating_profitability = float(
                revenue
                - (cogs if np.isfinite(cogs) else 0.0)
                - (sga if np.isfinite(sga) else 0.0)
                - (interest_expense if np.isfinite(interest_expense) else 0.0)
            ) / float(book_equity)

        book_to_market = (
            float(book_equity / dec_cap)
            if np.isfinite(book_equity) and np.isfinite(dec_cap) and abs(dec_cap) > 1e-12
            else float("nan")
        )
        investment = (
            float(assets_t1 / assets_t2 - 1.0)
            if np.isfinite(assets_t1) and np.isfinite(assets_t2) and abs(assets_t2) > 1e-12
            else float("nan")
        )

        rows.append(
            {
                "date": dt,
                "ticker": ticker,
                "market_cap": market_cap,
                "book_to_market": book_to_market,
                "profitability": operating_profitability,
                "investment": investment,
            }
        )

    out = pd.DataFrame(rows).dropna(subset=["market_cap", "book_to_market"])

    return out

def main():
    cik_map  = load_cik_map()
    tickers  = get_available_tickers()
    print(f"Tickers in quarantine store: {len(tickers)}")
    print(f"CIK map entries:             {len(cik_map)}")

    matched = [(t, cik_map[t]) for t in tickers if t in cik_map]
    print(f"Matched ticker→CIK:          {len(matched)}")

    all_frames = []
    for i, (ticker, cik) in enumerate(matched):
        print(f"[{i+1}/{len(matched)}] {ticker} (CIK {cik})", end=" ... ")
        try:
            df = build_ticker_characteristics(ticker, cik)
            if not df.empty:
                all_frames.append(df)
                print(f"{len(df)} rows")
            else:
                print("no data")
        except Exception as e:
            print(f"ERROR: {e}")
        time.sleep(0.12)   # SEC rate limit: ~8 req/s

    if not all_frames:
        print("No data collected.")
        return

    result = pd.concat(all_frames, ignore_index=True)
    result = result.sort_values(["date", "ticker"]).reset_index(drop=True)

    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    result.to_csv(OUT_PATH, index=False)
    print(f"\nSaved {len(result)} rows to {OUT_PATH}")
    print(result.head(5).to_string())

if __name__ == "__main__":
    main()
