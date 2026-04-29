"""Risk-model helpers for Phase 3 residualization work.

The critical invariants here are:
1. residualization must be explicit and testable;
2. rolling residuals must be no-look-ahead;
3. validation against a reference factor table should be mechanical,
   not ad hoc notebook logic.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Sequence

import numpy as np
import pandas as pd


REFERENCE_FACTOR_COLUMNS = ("MKT", "SMB", "HML", "RMW", "CMA", "UMD")
_REFERENCE_ALIASES = {
    "MKT-RF": "MKT",
    "MKT_RF": "MKT",
    "MKT": "MKT",
    "MKT_EXCESS": "MKT",
    "MKT_EXCESS_RETURN": "MKT",
}


@dataclass
class OLSFactorModelResult:
    alpha: float
    betas: Dict[str, float]
    residuals: pd.Series
    fitted: pd.Series
    r_squared: float
    n_obs: int


def _coerce_reference_columns(columns: Sequence[str]) -> dict[str, str]:
    mapping: dict[str, str] = {}
    for col in columns:
        raw = str(col).strip()
        upper = raw.upper().replace("-", "_").replace(" ", "_")
        canonical = _REFERENCE_ALIASES.get(raw.upper(), _REFERENCE_ALIASES.get(upper, raw.upper()))
        mapping[raw] = canonical
    return mapping


def load_reference_factor_table(
    path: str | Path,
    *,
    required: Sequence[str] = REFERENCE_FACTOR_COLUMNS,
) -> pd.DataFrame:
    """Load a local daily factor table for Phase 3 validation.

    Contract:
      - local file only (`.csv` or `.parquet`)
      - must contain a date column or datetime index
      - columns must normalize to the required factor set
      - returns are expected in decimal daily units, not percent
    """
    file = Path(path).expanduser().resolve()
    if not file.exists():
        raise FileNotFoundError(f"reference factor table not found: {file}")
    if file.suffix.lower() == ".parquet":
        df = pd.read_parquet(file)
    else:
        df = pd.read_csv(file)

    lower_cols = {str(c).lower() for c in df.columns}
    if "date" in lower_cols:
        date_col = next(c for c in df.columns if str(c).lower() == "date")
        df[date_col] = pd.to_datetime(df[date_col]).dt.tz_localize(None).dt.normalize()
        df = df.set_index(date_col)
    elif not isinstance(df.index, pd.DatetimeIndex):
        maybe_first = df.columns[0]
        try:
            idx = pd.to_datetime(df[maybe_first]).dt.tz_localize(None).dt.normalize()
        except Exception as exc:
            raise ValueError("reference factor table needs a date column or DatetimeIndex") from exc
        df = df.set_index(idx).drop(columns=[maybe_first])
    else:
        df.index = pd.to_datetime(df.index).tz_localize(None).normalize()

    df = df.rename(columns=_coerce_reference_columns(df.columns))
    missing = [c for c in required if c not in df.columns]
    if missing:
        raise ValueError(f"reference factor table missing required columns: {missing}")
    out = df.loc[:, list(required)].sort_index()
    out = out.apply(pd.to_numeric, errors="coerce")
    return out


def fit_factor_model(
    asset_returns: pd.Series,
    factor_returns: pd.DataFrame,
) -> OLSFactorModelResult:
    """Full-sample OLS of one return series on named factor returns."""
    joined = pd.concat(
        [asset_returns.rename("asset"), factor_returns],
        axis=1,
        join="inner",
    ).dropna()
    if joined.empty or len(joined) < len(factor_returns.columns) + 2:
        empty = pd.Series(dtype=float)
        return OLSFactorModelResult(
            alpha=0.0,
            betas={col: 0.0 for col in factor_returns.columns},
            residuals=empty,
            fitted=empty,
            r_squared=0.0,
            n_obs=0,
        )

    y = joined["asset"].to_numpy(dtype=np.float64)
    X_f = joined[factor_returns.columns].to_numpy(dtype=np.float64)
    X = np.column_stack([np.ones(len(joined), dtype=np.float64), X_f])

    try:
        beta, *_ = np.linalg.lstsq(X, y, rcond=None)
    except np.linalg.LinAlgError:
        empty = pd.Series(dtype=float)
        return OLSFactorModelResult(
            alpha=0.0,
            betas={col: 0.0 for col in factor_returns.columns},
            residuals=empty,
            fitted=empty,
            r_squared=0.0,
            n_obs=0,
        )

    fitted = pd.Series(X @ beta, index=joined.index, name="fitted")
    residuals = pd.Series(y - fitted.to_numpy(), index=joined.index, name="residual")
    ss_res = float(np.sum(np.square(residuals.to_numpy())))
    ss_tot = float(np.sum(np.square(y - y.mean())))
    r_sq = 0.0 if ss_tot <= 1e-12 else max(0.0, min(1.0, 1.0 - ss_res / ss_tot))
    return OLSFactorModelResult(
        alpha=float(beta[0]),
        betas={col: float(beta[i + 1]) for i, col in enumerate(factor_returns.columns)},
        residuals=residuals,
        fitted=fitted,
        r_squared=r_sq,
        n_obs=len(joined),
    )


def rolling_factor_residuals(
    asset_returns: pd.Series,
    factor_returns: pd.DataFrame,
    *,
    window: int = 252,
    min_obs: int | None = None,
) -> pd.Series:
    """No-look-ahead rolling residuals.

    Residual at t is computed using betas fit on [t-window, t-1] and
    evaluated on the realized asset/factor return at t.
    """
    min_obs = min_obs or window
    joined = pd.concat(
        [asset_returns.rename("asset"), factor_returns],
        axis=1,
        join="inner",
    )
    out = pd.Series(np.nan, index=joined.index, name=asset_returns.name or "residual")
    if len(joined) < min_obs + 1:
        return out

    factor_cols = list(factor_returns.columns)
    for pos in range(1, len(joined)):
        train = joined.iloc[max(0, pos - window):pos].dropna()
        if len(train) < min_obs:
            continue
        current = joined.iloc[pos]
        if not np.isfinite(current.to_numpy(dtype=np.float64)).all():
            continue
        fit = fit_factor_model(train["asset"], train[factor_cols])
        x_t = current[factor_cols].to_numpy(dtype=np.float64)
        y_t = float(current["asset"])
        y_hat = fit.alpha + float(np.dot(x_t, np.array([fit.betas[c] for c in factor_cols])))
        out.iloc[pos] = y_t - y_hat
    return out


def rolling_factor_residuals_panel(
    asset_returns: pd.DataFrame,
    factor_returns: pd.DataFrame,
    *,
    window: int = 252,
    min_obs: int | None = None,
) -> pd.DataFrame:
    """Column-wise wrapper over `rolling_factor_residuals`."""
    cols = {}
    for col in asset_returns.columns:
        cols[col] = rolling_factor_residuals(
            asset_returns[col],
            factor_returns,
            window=window,
            min_obs=min_obs,
        )
    return pd.DataFrame(cols, index=asset_returns.index)


def factor_replication_correlation(
    replica: pd.DataFrame,
    reference: pd.DataFrame,
) -> pd.DataFrame:
    """Correlation summary for overlapping factor columns."""
    common = [c for c in replica.columns if c in reference.columns]
    rows = []
    for col in common:
        joined = pd.concat(
            [replica[col].rename("replica"), reference[col].rename("reference")],
            axis=1,
            join="inner",
        ).dropna()
        corr = float(joined["replica"].corr(joined["reference"])) if len(joined) >= 2 else float("nan")
        rows.append(
            {
                "factor": col,
                "correlation": corr,
                "n_obs": int(len(joined)),
                "replica_mean": float(joined["replica"].mean()) if len(joined) else float("nan"),
                "reference_mean": float(joined["reference"].mean()) if len(joined) else float("nan"),
            }
        )
    return pd.DataFrame(rows).set_index("factor") if rows else pd.DataFrame(
        columns=["correlation", "n_obs", "replica_mean", "reference_mean"]
    )
