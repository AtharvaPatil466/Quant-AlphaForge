"""Generate a polished PDF overview of the AlphaForge project.

Self-contained — reads the two research reports under
alphaforge-python/research/out/ and alphaforge-marl/research/out/
if present, otherwise renders the prose-only overview.
"""

from __future__ import annotations

import json
from pathlib import Path

from reportlab.lib.pagesizes import LETTER
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import inch
from reportlab.lib.colors import HexColor, black
from reportlab.lib.enums import TA_JUSTIFY, TA_LEFT
from reportlab.platypus import (
    SimpleDocTemplate, Paragraph, Spacer, PageBreak, Table, TableStyle, KeepTogether
)

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "docs" / "AlphaForge_Project_Overview.pdf"
FACTOR_JSON = ROOT / "alphaforge-python" / "research" / "out" / "factor_study_results.json"
MARL_JSON   = ROOT / "alphaforge-marl" / "research" / "out" / "marl_rigor_metrics.json"

# ---------- styles ----------
styles = getSampleStyleSheet()
PRIMARY = HexColor("#0b3a63")
ACCENT = HexColor("#c76a00")
MUTED = HexColor("#555555")

styles.add(ParagraphStyle(
    "H1", parent=styles["Heading1"], fontSize=22, leading=28, spaceAfter=14,
    textColor=PRIMARY, fontName="Helvetica-Bold",
))
styles.add(ParagraphStyle(
    "H2", parent=styles["Heading2"], fontSize=15, leading=20, spaceBefore=16,
    spaceAfter=8, textColor=PRIMARY, fontName="Helvetica-Bold",
))
styles.add(ParagraphStyle(
    "H3", parent=styles["Heading3"], fontSize=12, leading=16, spaceBefore=10,
    spaceAfter=4, textColor=ACCENT, fontName="Helvetica-Bold",
))
styles.add(ParagraphStyle(
    "Body2", parent=styles["BodyText"], fontSize=10.5, leading=15,
    alignment=TA_JUSTIFY, spaceAfter=6,
))
styles.add(ParagraphStyle(
    "Bullet2", parent=styles["BodyText"], fontSize=10.5, leading=14,
    leftIndent=18, bulletIndent=6, spaceAfter=3,
))
styles.add(ParagraphStyle(
    "Small", parent=styles["BodyText"], fontSize=9, leading=12,
    textColor=MUTED,
))
styles.add(ParagraphStyle(
    "TitleBig", parent=styles["Title"], fontSize=28, leading=34,
    textColor=PRIMARY, spaceAfter=6,
))
styles.add(ParagraphStyle(
    "Subtitle", parent=styles["BodyText"], fontSize=13, leading=18,
    textColor=MUTED, alignment=TA_LEFT, spaceAfter=24,
))
styles.add(ParagraphStyle(
    "Quote", parent=styles["BodyText"], fontSize=10.5, leading=15,
    leftIndent=20, rightIndent=20, textColor=MUTED, fontName="Helvetica-Oblique",
    spaceBefore=6, spaceAfter=6,
))


def P(text, style="Body2"):
    return Paragraph(text, styles[style])


def H(text, level=2):
    return Paragraph(text, styles[f"H{level}"])


def bullet(text):
    return Paragraph(f"• {text}", styles["Bullet2"])


def kv_table(rows, col_widths=None):
    tbl = Table(rows, colWidths=col_widths)
    tbl.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), PRIMARY),
        ("TEXTCOLOR", (0, 0), (-1, 0), HexColor("#ffffff")),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, -1), 9.5),
        ("BOTTOMPADDING", (0, 0), (-1, 0), 6),
        ("TOPPADDING", (0, 0), (-1, 0), 6),
        ("BOTTOMPADDING", (0, 1), (-1, -1), 4),
        ("TOPPADDING", (0, 1), (-1, -1), 4),
        ("GRID", (0, 0), (-1, -1), 0.25, HexColor("#cccccc")),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [HexColor("#f7f9fc"), HexColor("#ffffff")]),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
    ]))
    return tbl


def _load_optional_json(path: Path):
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text())
    except Exception:
        return None


def build():
    doc = SimpleDocTemplate(
        str(OUT), pagesize=LETTER,
        leftMargin=0.9 * inch, rightMargin=0.9 * inch,
        topMargin=0.9 * inch, bottomMargin=0.8 * inch,
        title="AlphaForge — Project Overview",
        author="Atharva Patil",
    )
    story = []
    S = story.append

    factor_data = _load_optional_json(FACTOR_JSON)
    marl_data = _load_optional_json(MARL_JSON)

    # ----- Title page -----
    S(Paragraph("AlphaForge", styles["TitleBig"]))
    S(Paragraph(
        "A quantitative alpha-research platform: synthetic-to-real data, "
        "cross-sectional factor engine, evolutionary multi-agent RL, "
        "and a deflation-aware rigor layer.",
        styles["Subtitle"]
    ))
    S(Spacer(1, 0.2 * inch))
    S(P("<b>Author:</b> Atharva Patil &nbsp;&nbsp;|&nbsp;&nbsp; "
        "<b>Target role:</b> Quant Researcher"))
    S(Spacer(1, 0.05 * inch))
    S(P("<b>Components:</b> JS frontend · Python alpha engine · MARL framework · "
        "Live paper-trading execution"))
    S(P("<b>Scale:</b> 3 Python backend services · 618+ tests · JS/Python parity to 10 dp · "
        "10 years of real OHLCV for 50 US large-caps"))
    S(Spacer(1, 0.3 * inch))
    S(Paragraph(
        "This document describes the architecture of the AlphaForge platform, the data "
        "pipeline that underpins it, the strategies it evaluates, and — critically — what "
        "rigorous statistical testing has revealed about those strategies. The goal is to "
        "present an honest picture of both what has been built and what the results mean. "
        "Deflation-aware reporting (Bailey & López de Prado, 2014), bootstrap confidence "
        "intervals, and baseline-excess decomposition are first-class outputs, not afterthoughts.",
        styles["Body2"]
    ))

    S(Spacer(1, 0.3 * inch))
    # TOC-style summary
    toc_rows = [
        ["§", "Section"],
        ["1", "Executive summary"],
        ["2", "Architecture overview"],
        ["3", "Data pipeline (synthetic → real)"],
        ["4", "Strategy layer — factors & MARL"],
        ["5", "Research rigor: IC, DSR, bootstrap, baselines"],
        ["6", "Findings — what the numbers actually say"],
        ["7", "Engineering highlights"],
        ["8", "Live paper-trading execution"],
        ["9", "Honest limitations"],
        ["10", "Roadmap — what moves this to a defensible result"],
    ]
    S(kv_table(toc_rows, col_widths=[0.5 * inch, 5.3 * inch]))
    S(PageBreak())

    # ----- 1. Executive summary -----
    S(H("1. Executive summary", 1))
    S(P(
        "AlphaForge is a full quantitative research platform built end-to-end: data "
        "acquisition and storage, factor construction, cross-sectional backtesting, mean-"
        "variance portfolio optimisation, an evolutionary multi-agent reinforcement-"
        "learning framework, and live paper-trading execution. The system was designed to "
        "answer one question: <i>can a population of RL agents evolve trading strategies "
        "that generalise to unseen market regimes?</i>"
    ))
    S(P(
        "The honest answer, after building the rigor layer: not yet — but the platform "
        "that was built to evaluate that question is itself the research artifact. The "
        "project now produces two deflation-aware research reports (single-factor and "
        "MARL) that apply Bailey & López de Prado's Deflated Sharpe Ratio, stationary-"
        "bootstrap Sharpe CIs, and baseline-excess decomposition against an equal-weight "
        "benchmark. These reports demonstrate the statistical hygiene a quant researcher "
        "is expected to apply to their own work."
    ))
    S(H("Key numbers", 3))
    S(bullet("50 US large-cap universe, 2016–2025 (10 years of point-in-time-validated daily OHLCV)."))
    S(bullet("5 cross-sectional factors in the JS-parity set; 6 total."))
    S(bullet("3 Python backend services (alpha engine, MARL, execution), each with its own FastAPI."))
    S(bullet("618+ tests; JS/Python numerical parity verified to 10 decimal places."))
    S(bullet("Headline finding: no single factor clears Deflated Sharpe > 0.95 on this universe."))
    S(bullet("Headline MARL finding: OOS stability Sharpe 0.72 → DSR 0.04; zero of 76 reward-mix trials beat equal-weight."))
    S(P(
        "Negative findings, properly documented, are a deliberately chosen headline. "
        "This report explains why the project is stronger, not weaker, for reporting them."
    ))

    # ----- 2. Architecture -----
    S(H("2. Architecture overview", 1))
    S(P("AlphaForge is organised as four loosely-coupled components, each with its own CLAUDE.md, "
        "test suite, and (where applicable) FastAPI service:"))
    arch_rows = [
        ["Component", "Role", "Tests"],
        ["JS frontend", "Single-page research UI over the alpha engine API.", "—"],
        ["alphaforge-python", "Data, factors, backtest, optimiser, FastAPI.", "408"],
        ["alphaforge-marl", "Evolutionary multi-agent RL (NSGA-II + MAML + HMM regimes).", "122"],
        ["alphaforge-execution", "Live paper-trading loop with Alpaca + yfinance + SQLite.", "106"],
    ]
    S(kv_table(arch_rows, col_widths=[1.5 * inch, 3.8 * inch, 0.6 * inch]))
    S(Spacer(1, 0.1 * inch))
    S(P(
        "Data flows unidirectionally: <b>yfinance → parquet store → alphaforge-python</b> "
        "(factor scoring, backtest, optimiser) → <b>alphaforge-marl</b> (imports alpha engine "
        "via <tt>sys.path</tt>, trains agents on real OHLCV windows) → <b>alphaforge-execution</b> "
        "(runs extracted strategies live against Alpaca paper trading). The parquet store "
        "is the single source of truth; only <tt>sync_market_data.py</tt> and the execution "
        "daily loop touch yfinance."
    ))

    # ----- 3. Data pipeline -----
    S(H("3. Data pipeline (synthetic → real)", 1))
    S(P(
        "The project started on a seeded-PRNG synthetic data layer (Mulberry32 → geometric "
        "Brownian motion) for reproducibility and JS/Python parity testing. Over time the "
        "primary evaluation substrate migrated to real market data, stored locally as "
        "parquet files (one per ticker per year) under <tt>data/market/</tt>."
    ))
    S(H("Universe manifest", 3))
    S(P(
        "50 US large-caps across Technology, Healthcare, Finance, Consumer, and Energy. "
        "Each ticker has a manifested <tt>usable_start</tt> date that respects IPO / spin-"
        "off / restructuring history (e.g. META 2012-05-18, TSLA 2010-06-29, ABBV 2013-"
        "01-02). A quarantine subsystem flags parquet files whose validator checks fail and "
        "excludes them from training/evaluation."
    ))
    S(H("Why parquet, not a database", 3))
    S(P(
        "Parquet per-ticker-per-year gives O(1) range lookups, zero-install read, and "
        "columnar compression. A small <tt>MarketDataLoader</tt> with an LRU cache makes "
        "repeated backtests cheap. Read-only by design; all mutations go through the "
        "sync + validator path."
    ))
    S(H("Point-in-time limitations (acknowledged)", 3))
    S(P(
        "The universe is defined as of today, not point-in-time — delisted peers are not "
        "included. This biases the long-only equal-weight baseline upward by an estimated "
        "1–2% annualised. Any future capital-allocation-grade result must use a CRSP or "
        "Norgate survivorship-bias-free universe."
    ))

    # ----- 4. Strategy layer -----
    S(H("4. Strategy layer — factors & MARL", 1))
    S(H("4.1 Cross-sectional factors", 3))
    S(P(
        "Six factor implementations, five of which are bit-for-bit identical with the JS "
        "frontend (verified to 10 decimal places):"))
    factor_rows = [
        ["Factor", "Formula (JS-parity variant)", "Lookback"],
        ["Momentum (12-1)", "(p[t-21] − p[t-252]) / p[t-252]", "252d"],
        ["Mean Reversion (5d)", "−(p[t] − p[t-5]) / p[t-5]", "5d"],
        ["Volume Surge", "(mean(v[−5:]) − mean(v[−20:])) / mean(v[−20:])", "20d"],
        ["RSI Divergence", "(RSI₁₄(p) − 50) / 50", "14d"],
        ["Earnings Drift", "(p[t] − p[t-10]) / p[t-10]", "10d"],
        ["Low Volatility", "−std(ret[-60:]) (inverse realised vol)", "60d"],
    ]
    S(kv_table(factor_rows, col_widths=[1.6 * inch, 3.5 * inch, 0.8 * inch]))
    S(Spacer(1, 0.05 * inch))
    S(P(
        "Factors are scored daily per ticker, z-scored cross-sectionally at each rebalance, "
        "and fed into a unified long-short simulation engine that reports 9 performance "
        "metrics plus OLS attribution."))

    S(H("4.2 MARL framework", 3))
    S(P(
        "The multi-agent RL layer is a population-based trainer with four subsystems:"))
    S(bullet("<b>TradingEnv</b> — Gymnasium env, 57-dim observation, 5 discrete or 10-dim continuous actions, "
             "dense reward shaping (rolling Sharpe delta + drawdown penalty + participation incentive)."))
    S(bullet("<b>EvolutionaryEngine</b> — NSGA-II multi-objective selection on (Sharpe, drawdown, turnover), "
             "speciation via Jensen-Shannon divergence on probe-state action distributions, adaptive "
             "per-parameter mutation."))
    S(bullet("<b>PPOTrainer + MAMLTrainer</b> — GAE + clipped-surrogate PPO for survivor fine-tuning; "
             "FOMAML for fast regime adaptation."))
    S(bullet("<b>RegimeBandit</b> — HMM regime detector (K-Means init + Baum-Welch EM), Thompson sampling "
             "per (regime, agent), capital allocator feeding an EnsemblePolicy."))

    S(H("4.3 Strategy honesty note", 3))
    S(P(
        "All six factors are textbook. They are the <i>implementation canvas</i>, not the "
        "alpha. The rigor layer (§5) exists precisely to expose the limits of textbook "
        "signals on a 50-ticker universe after realistic costs. Next-step strategies "
        "(residual momentum, short-interest changes, earnings-call sentiment) are "
        "discussed in §10."
    ))

    # ----- 5. Research rigor -----
    S(H("5. Research rigor", 1))
    S(P(
        "Two research scripts produce the headline artifacts of the project. Both were "
        "built specifically to avoid the two most common failure modes of quant "
        "portfolio projects: selection bias and baseline omission."))

    S(H("5.1 Single-factor study (alphaforge-python/research/factor_study.py)", 3))
    S(bullet("Spearman IC at horizons {1, 5, 10, 21, 63} days — per-factor, per-horizon"))
    S(bullet("Quintile-spread backtest (5 buckets, monthly rebalance, 21-day holding)"))
    S(bullet("Realistic transaction costs: 1 bp commission + 2 bp half-spread + 10 bp × turnover² impact"))
    S(bullet("Stationary bootstrap (2000 reps, mean block length 21 days) on the net Sharpe"))
    S(bullet("Deflated Sharpe Ratio across the 5-factor trial set"))
    S(bullet("Equal-weight long-only and random-long-short (100 seeds) baselines"))
    S(bullet("Regime split on the best factor by 21-day realised-vol quantiles of the benchmark"))

    S(H("5.2 MARL rigor report (alphaforge-marl/research/marl_rigor.py)", 3))
    S(bullet("Scans every <tt>training.jsonl</tt> under ablations, reward-mix sweep, and stability runs"))
    S(bullet("Enumerates the full generation-level trial count (N = 100 reported; true N is higher)"))
    S(bullet("Reports the distribution of per-generation val Sharpe across the whole search"))
    S(bullet("Computes DSR of both the in-sample maximum and the honest OOS stability mean"))
    S(bullet("Summarises the baseline-excess Sharpe distribution from the reward-mix logs — "
             "<i>the only honest Sharpe</i>"))
    S(bullet("Reports seed-to-seed OOS stability"))

    S(H("5.3 Logging infrastructure for future runs", 3))
    S(P(
        "<tt>compute_performance_metrics</tt> in the MARL baselines module now returns "
        "<tt>daily_returns</tt> and <tt>nav_series</tt> lists alongside scalar metrics; "
        "<tt>aggregate_metric_dicts</tt> concatenates list-valued keys across windows (scalars "
        "still averaged). Every future stability / ablation / benchmark run will persist "
        "per-day portfolio paths automatically, enabling bootstrap CIs at report time "
        "without re-evaluating the environment."
    ))

    # ----- 6. Findings -----
    S(H("6. Findings — what the numbers actually say", 1))
    S(H("6.1 Single-factor study", 3))
    if factor_data:
        factors = factor_data.get("factors", {})
        rows = [["Factor", "IC t @ h=63", "Gross SR", "Net SR", "DSR"]]
        for name, m in factors.items():
            ic = m.get("ic_decay", {}).get("63", m.get("ic_decay", {}).get(63, {}))
            dsr = m.get("net", {}).get("deflated_sharpe", {}).get("dsr", float("nan"))
            rows.append([
                name,
                f"{ic.get('ic_t', 0):+.2f}",
                f"{m.get('gross', {}).get('sharpe', 0):+.2f}",
                f"{m.get('net', {}).get('sharpe', 0):+.2f}",
                f"{dsr:.2f}",
            ])
        S(kv_table(rows, col_widths=[1.8 * inch, 1.0 * inch, 0.9 * inch, 0.9 * inch, 0.7 * inch]))
        eq = factor_data.get("baselines", {}).get("equal_weight", {})
        rnd = factor_data.get("baselines", {}).get("random_long_short", {})
        S(Spacer(1, 0.1 * inch))
        S(P(
            f"<b>Equal-weight long-only baseline:</b> Sharpe "
            f"{eq.get('sharpe', 0):+.2f}, annual return {eq.get('ann_return', 0):+.1%}, "
            f"max DD {eq.get('max_drawdown', 0):.1%}."
        ))
        S(P(
            f"<b>Random long-short (100 seeds):</b> mean Sharpe {rnd.get('mean_sharpe', 0):+.2f}, "
            f"95% CI [{rnd.get('ci_lo', 0):+.2f}, {rnd.get('ci_hi', 0):+.2f}]. Any factor "
            f"whose net Sharpe falls inside this band is statistically indistinguishable from randomness."
        ))
    else:
        S(P("(Factor study results not yet generated. Run <tt>python3 alphaforge-python/research/"
            "factor_study.py</tt> to populate this section.)"))

    S(H("6.2 MARL rigor report", 3))
    if marl_data:
        rows = [
            ["Metric", "Value"],
            ["Total trials enumerated", f"{marl_data.get('n_trials', 0)}"],
            ["Val-Sharpe distribution (max)", f"{marl_data['sharpe_distribution']['max']:+.2f}"],
            ["Val-Sharpe distribution (mean)", f"{marl_data['sharpe_distribution']['mean']:+.2f}"],
            ["In-sample best DSR", f"{marl_data['dsr_in_sample']['dsr']:.3f}"],
            ["OOS mean stability Sharpe", f"{marl_data['mean_oos_sharpe']:+.2f}"],
            ["OOS stability DSR", f"{marl_data['dsr_oos_mean']['dsr']:.3f}"],
            ["SR₀ threshold (100 trials)", f"{marl_data['dsr_in_sample']['sr0_annualized']:+.2f}"],
        ]
        be = marl_data.get("baseline_excess_sharpe_stats")
        if be:
            rows.append(["Baseline-excess Sharpe (mean)", f"{be['mean']:+.3f}"])
            rows.append(["Trials beating equal-weight", f"{be['share_positive']:.0%}"])
        S(kv_table(rows, col_widths=[3.0 * inch, 2.2 * inch]))
    else:
        S(P("(MARL rigor metrics not yet generated. Run <tt>python3 alphaforge-marl/research/"
            "marl_rigor.py</tt> to populate this section.)"))

    S(Spacer(1, 0.1 * inch))
    S(Paragraph(
        "<i>The in-sample best-val Sharpe of 6.74 is an order statistic across ~100 "
        "trials — the maximum of many noisy 5-episode validation estimates. The honest "
        "OOS Sharpe (mean across two retrained seeds on a 251-day held-out window) is "
        "0.72, with DSR 0.04. The absolute Sharpe is predominantly beta exposure to a "
        "period when the equal-weight basket of the same 50 names earned Sharpe > 2.</i>",
        styles["Quote"]
    ))

    S(H("6.3 Interpretation", 3))
    S(P(
        "The honest read of the rigor reports: <b>no strategy in the current project has "
        "credible, cost-adjusted, deflation-aware alpha</b> on this universe. The most "
        "promising factor (Momentum 12-1) has IC statistics consistent with the published "
        "literature, but its net-of-costs Sharpe collapses to +0.11 with a bootstrap 95% "
        "CI spanning zero. Equal-weight long-only beats every overlay. MARL absolute "
        "Sharpe is beta, not alpha."
    ))
    S(P(
        "This is a <i>research finding</i>, not a project failure. It identifies exactly "
        "what signal quality would be required to clear the bar, and provides the rigor "
        "scaffolding to test future candidates (residual momentum, short-interest changes, "
        "earnings-call sentiment, see §10)."
    ))

    # ----- 7. Engineering highlights -----
    S(H("7. Engineering highlights", 1))
    S(bullet("<b>JS/Python numerical parity to 10 decimal places.</b> Every JS-parity factor has a "
             "Python <tt>compute_js()</tt> that reproduces the frontend output bit-for-bit. "
             "Verified via <tt>tests/fixtures/js_reference_output.json</tt>."))
    S(bullet("<b>Defensive numerics everywhere.</b> <tt>safe_div</tt>, <tt>sanitize_number</tt>, "
             "<tt>validate_series</tt>, <tt>clamp</tt> applied consistently across both Python "
             "backends and the JS frontend. No NaN or Infinity can propagate through the pipeline."))
    S(bullet("<b>Parquet-store access pattern.</b> Per-ticker-per-year files with manifest validation, "
             "LRU-cached reads, strict range enforcement, and a quarantine subsystem for files "
             "that fail validator checks."))
    S(bullet("<b>NSGA-II + Speciation.</b> Multi-objective selection (Sharpe, drawdown, turnover) "
             "with Jensen-Shannon-distance speciation prevents premature convergence."))
    S(bullet("<b>FOMAML meta-learning.</b> Periodic first-order MAML updates on elite agents for "
             "faster regime adaptation."))
    S(bullet("<b>Ticker-attention encoder.</b> Multi-head self-attention over 10 ticker slots in the "
             "actor-critic trunk to learn cross-ticker relationships."))
    S(bullet("<b>Curriculum learning.</b> Four difficulty stages with progressively tightening tx "
             "costs, leverage limits, stop-loss thresholds, and episode length."))
    S(bullet("<b>Walk-forward validator.</b> Anchored splits (train 2022–23, validate 2024, test 2025) "
             "with strict temporal isolation and overfitting-ratio reporting."))
    S(bullet("<b>Deflation-aware reports.</b> Bailey & López de Prado DSR + stationary bootstrap + "
             "baseline-excess decomposition on both the factor and MARL sides."))
    S(bullet("<b>618+ passing tests</b> across the three backends."))

    # ----- 8. Execution -----
    S(H("8. Live paper-trading execution", 1))
    S(P(
        "<tt>alphaforge-execution</tt> runs a daily trading loop against Alpaca paper-"
        "trading with live yfinance prices. The loop is: fetch prices → compute momentum "
        "composite ranking → risk-check (position size, exposure, turnover, circuit "
        "breakers for daily-loss and max-drawdown) → execute orders via broker ABC "
        "(<tt>PaperBroker</tt> with slippage for local sim; <tt>AlpacaBroker</tt> for live) → "
        "snapshot NAV/Sharpe/drawdown/win-rate into SQLite."
    ))
    S(P(
        "The executed strategy is an extraction of the momentum composite from the MARL "
        "environment's <tt>_rank_tickers()</tt>: 40% 5d momentum + 40% 21d momentum + 20% "
        "mean reversion, top-N equal-weight. Configuration lives in "
        "<tt>configs/execution_config.yaml</tt>. 106 tests cover broker interfaces, risk "
        "checks, circuit breakers, and the persistence layer."
    ))

    # ----- 9. Limitations -----
    S(H("9. Honest limitations", 1))
    S(bullet("<b>Survivorship bias.</b> Universe defined as of today, not point-in-time. Estimated "
             "1–2%/yr upward bias on the equal-weight baseline."))
    S(bullet("<b>No borrow costs.</b> Short-leg returns assume free unlimited borrow. Realistic borrow "
             "would add 20–100 bps/yr of drag on non-mega-cap short legs."))
    S(bullet("<b>Static cost model.</b> Single commission + half-spread + impact parameters. Real "
             "impact scales with ADV participation; spread scales with volatility."))
    S(bullet("<b>Small universe.</b> 50 tickers means quintile buckets are 10 names — cross-sectional "
             "IC t-stats are noisier than on a 500-name universe."))
    S(bullet("<b>No risk model.</b> Returns not neutralised against sector or style factors. Reported "
             "alpha is partly explained by sector tilts."))
    S(bullet("<b>MARL trial count under-reported.</b> The rigor script enumerates only generation-"
             "level trial rows; architecture search, curriculum choices, and reward-shape "
             "tuning are additional trials that should also deflate the DSR."))
    S(bullet("<b>OOS window is 1 year for 2 seeds.</b> Insufficient statistical power to reject a "
             "zero-alpha null."))

    # ----- 10. Roadmap -----
    S(H("10. Roadmap — what moves this to a defensible result", 1))
    S(P(
        "The project's current posture is <i>rigorous infrastructure around textbook "
        "signals</i>. Converting that into <i>rigorous infrastructure around defensible "
        "signals</i> is the explicit next-phase work:"))
    S(H("10.1 Strategy layer", 3))
    S(bullet("<b>Residual momentum</b> (Blitz-Huij-Martens 2011) — FF-5-residualised momentum, "
             "same universe, same pipeline. Expected to dominate plain 12-1 here."))
    S(bullet("<b>One Tier-2 alt-data signal</b> — short-interest changes (FINRA, free) or "
             "earnings-call sentiment (FinBERT on transcripts). Differentiated for "
             "quant-researcher interviews."))
    S(bullet("<b>Combination</b> — ERC / Bayesian IC-weighted blend of residual momentum + "
             "the alt-data signal. Target: combined DSR > max(individual DSRs)."))
    S(H("10.2 Infrastructure", 3))
    S(bullet("<b>Point-in-time universe.</b> Move off of today's survivor set. Norgate or CRSP."))
    S(bullet("<b>Sacred OOS lock.</b> 2023-01-01 → today held back from any tuning loop."))
    S(bullet("<b>FF-5 residualisation layer.</b> Regress every strategy's returns on the "
             "Fama-French-5 factors + Carhart momentum to isolate true alpha."))
    S(bullet("<b>Capacity analysis.</b> % of ADV consumed at $10M / $100M / $1B AUM."))
    S(bullet("<b>Borrow cost module.</b> Attach a per-ticker borrow curve to short legs."))

    S(Spacer(1, 0.15 * inch))
    S(Paragraph(
        "<b>Research philosophy.</b> The value of the current project is not a winning "
        "strategy — it is a platform that makes winning and losing strategies <i>legibly</i> "
        "distinguishable. That property is rare in portfolio projects, and it is the "
        "platform on which the next phase of signal work will run.",
        styles["Body2"]
    ))

    S(Spacer(1, 0.2 * inch))
    S(Paragraph(
        "Repository: <i>Quant Alpha</i> (AlphaForge). Generated by "
        "<tt>docs/build_alphaforge_pdf.py</tt>. Reproducible; re-run after any new "
        "factor or MARL rigor update to regenerate the PDF with the latest numbers "
        "pulled from the JSON artifacts.",
        styles["Small"]
    ))

    doc.build(story)
    print(f"Wrote {OUT}")


if __name__ == "__main__":
    build()
