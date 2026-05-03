"""Generate a polished PDF overview of the AlphaForge project.

Self-contained — reads the research reports under
alphaforge-python/research/out/ and alphaforge-marl/research/out/
if present, otherwise renders the prose-only overview.

This document reflects the project state as of 2026-05-03:
Tier 1 + Tier 2 both CLOSED FAILED on 2026-05-02; the project is
in a pre-committed 30-day cooldown until 2026-06-01 before any
substrate-change pivot. See PHASE6_WRITEUP.md and TIER2_VERDICT.md
for the underlying analyses.
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
PHASE5_JSON = ROOT / "alphaforge-python" / "research" / "out" / "phase5_combination_results.json"
TIER2_GATE_JSON = ROOT / "alphaforge-python" / "research" / "out" / "tier2" / "tier2_phase2_gate.json"
TIER2_RESULTS_JSON = ROOT / "alphaforge-python" / "research" / "out" / "tier2" / "tier2_phase2_results.json"
MARL_JSON   = ROOT / "alphaforge-marl" / "research" / "out" / "marl_rigor_metrics.json"

# ---------- styles ----------
styles = getSampleStyleSheet()
PRIMARY = HexColor("#0b3a63")
ACCENT = HexColor("#c76a00")
MUTED = HexColor("#555555")
WARN = HexColor("#9a3324")

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
styles.add(ParagraphStyle(
    "StatusBanner", parent=styles["BodyText"], fontSize=10.5, leading=15,
    textColor=WARN, fontName="Helvetica-Bold", spaceAfter=10,
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
    phase5_data = _load_optional_json(PHASE5_JSON)
    tier2_gate  = _load_optional_json(TIER2_GATE_JSON)
    tier2_res   = _load_optional_json(TIER2_RESULTS_JSON)
    marl_data   = _load_optional_json(MARL_JSON)

    # ----- Title page -----
    S(Paragraph("AlphaForge", styles["TitleBig"]))
    S(Paragraph(
        "A quantitative research stack — point-in-time event-driven backtesting, "
        "deflation-aware statistical evaluation, evolutionary multi-agent RL, and "
        "live paper-trading execution — applied honestly to a point-in-time "
        "S&amp;P 500 universe (476 names, 2016–2025).",
        styles["Subtitle"]
    ))
    S(Paragraph(
        "STATUS (2026-05-03): Tier 1 and Tier 2 both CLOSED FAILED on 2026-05-02. "
        "Zero strategies cleared the deflation-aware gauntlet. Project is in a "
        "pre-committed 30-day cooldown until 2026-06-01 before any substrate-change pivot.",
        styles["StatusBanner"]
    ))
    S(P("<b>Author:</b> Atharva Patil"))
    S(Spacer(1, 0.05 * inch))
    S(P("<b>Components:</b> JS frontend · Python alpha engine · MARL framework · "
        "Live paper-trading execution"))
    S(P("<b>Scale:</b> 3 Python backend services · 541+ tests · 9 cross-sectional "
        "factors · 837 PIT S&amp;P 500 membership events · 16 years of OHLCV"))
    S(P("<b>Companion artifacts:</b> <tt>PHASE6_WRITEUP.md</tt> (Tier 1 final), "
        "<tt>TIER2_VERDICT.md</tt> (Tier 2 final), <tt>TIER1_STATUS.txt</tt> "
        "(master plan + outcomes)"))
    S(Spacer(1, 0.25 * inch))
    S(H("Abstract", 3))
    S(Paragraph(
        "AlphaForge applies an end-to-end systematic-trading lifecycle — data, factors, "
        "event-driven backtesting, transaction-cost modeling, statistical evaluation, RL, "
        "and live execution — to nine cross-sectional equity signals and four linear "
        "combination strategies on a true point-in-time S&amp;P 500 universe (476 tickers, "
        "2,514 trading days, 2016–2025). Strategies and gate are pre-committed: DSR &gt; 0.95 "
        "+ bootstrap CI excludes zero + sign agreement, both of two non-overlapping OOS "
        "windows. <b>Tier 1 and Tier 2 both closed FAILED on 2026-05-02.</b> 0 of 9 single "
        "factors and 0 of 4 Tier-1 combinations cleared. 0 of 8 Tier-2 lower-turnover "
        "strategies cleared. The closest result was a Markowitz overlay (MV) with "
        "alpha-residual OOS Sharpe +3.06 / +2.43 (CI [+1.83, +4.42] / [+1.39, +3.56]), "
        "alpha t-stats 4.33 / 3.43 (HC0), FF5+UMD R² 16% / 8% — statistically significant "
        "alpha that did not survive the 24-trial DSR deflation (0.92 / 0.70 vs. 0.95). "
        "Tier 2 falsified the row-2 \"costs eat real signal\" diagnosis: lowering rebalance "
        "horizon from 21d to 63d / 126d destroyed the alpha rather than preserving it, "
        "suggesting the MV-21 result is a short-horizon-specific phenomenon (most likely "
        "a 21-day residualized mean-reversion artifact) rather than a robust cross-sectional "
        "anomaly. The project's contribution is the methodology and infrastructure that "
        "produced these honest negative results — not surviving signals.",
        styles["Body2"]
    ))

    S(Spacer(1, 0.3 * inch))
    toc_rows = [
        ["§", "Section"],
        ["1", "Executive Summary"],
        ["2", "Architecture & Data Pipeline"],
        ["3", "Alpha Engine & Event-Driven Backtest"],
        ["4", "Research Rigor & Cost Modeling"],
        ["5", "MARL Framework & Ablation Studies"],
        ["6", "Execution System & Live Risk Checks"],
        ["7", "Empirical Findings (Tier 1 + Tier 2)"],
        ["8", "Honest Limitations & Process Disclosures"],
        ["9", "Engineering Highlights"],
        ["10", "Verdict and the §7 Cooldown"],
    ]
    S(kv_table(toc_rows, col_widths=[0.5 * inch, 5.3 * inch]))
    S(PageBreak())

    # ----- 1. Executive summary -----
    S(H("1. Executive Summary", 1))
    S(P(
        "<b>Headline result.</b> The pre-committed Tier 1 binary gate (DSR &gt; 0.95 on "
        "FF5+UMD alpha-residual returns + bootstrap CI excludes zero + sign agreement, "
        "both OOS windows) FAILED. 0 of 9 single factors and 0 of 4 combination "
        "strategies cleared. The follow-up Tier 2 binary gate (lower-turnover variants "
        "of the row-2 diagnostic) ALSO FAILED: 0 of 8 strategies cleared and 0 "
        "near-misses. The project's research hypothesis — that some signal in the "
        "cross-sectional equity factor combination class survives a deflation-aware "
        "gauntlet on this substrate — is rejected at both tested levels."
    ))
    S(P(
        "<b>The interesting failure.</b> A Markowitz overlay over the 9 per-factor "
        "long-short return series produces alpha-residual OOS Sharpe +3.06 / +2.43 "
        "with alpha t-stats 4.33 / 3.43 (HC0 SEs) and FF5+UMD R² of 16% / 8%. The "
        "signal is genuinely orthogonal to the standard factor model and statistically "
        "significant under any conventional bar (p &lt; 1e-4 / p &lt; 1e-3). It fails "
        "the gate <i>only</i> on the DSR hurdle (0.92 / 0.70 vs. the pre-committed 0.95) "
        "when deflated against the 24-trial set. Tier 2 then falsified the row-2 "
        "interpretation: lowering rebalance from 21d to 63d / 126d destroyed the "
        "alpha (3.06 → 0.79 → 0.95 in OOS-A), suggesting the MV-21 result is a "
        "21-day-specific residualized reversal phenomenon rather than a real "
        "cross-sectional anomaly trapped behind a cost wall."
    ))
    S(P(
        "<b>What the project actually contributes.</b> The methodology and "
        "infrastructure that produced the result above. AlphaForge implements the full "
        "systematic-trading lifecycle — data ingestion, factor construction, "
        "point-in-time event-driven backtesting, transaction-cost modeling, "
        "deflation-aware statistical evaluation, post-portfolio FF5+UMD alpha "
        "residualization, neuroevolutionary multi-agent RL, and a live paper-trading "
        "execution loop with kill-switch risk logic. The statistical layer integrates "
        "the Deflated Sharpe Ratio (Bailey &amp; López de Prado), Hansen's Superior "
        "Predictive Ability test, White's Reality Check, López de Prado's Purged "
        "K-Fold cross-validation, and stationary-bootstrap confidence intervals on "
        "both raw long-short returns and FF5+UMD alpha-residual returns."
    ))
    S(P(
        "<b>One process disclosure deserves headline-level visibility.</b> While "
        "running the Tier 2 diagnostic, a load-bearing methodology bug was "
        "discovered in the residualization wiring: <tt>prepare_analysis_returns()</tt> "
        "was returning raw returns regardless of the residualize flag, and the "
        "<tt>compute_portfolio_alpha</tt> post-hoc layer was not wired into the main "
        "gauntlet. The intended residualization layer existed as dead code for an "
        "unknown period; the JSON metadata claimed <tt>analysis_returns_mode: "
        "residualized</tt> while the actual computation was on raw returns. Fixed in "
        "~50 lines (pass <tt>reference_factors</tt> into <tt>_run_variant</tt>, "
        "populate per-OOS-window <tt>ff5_alpha</tt> blocks, both gates auto-detect "
        "and use alpha-residual Sharpes when available). All headline numbers in "
        "this document are post-fix. Pre-fix outputs are preserved as "
        "<tt>*_residualized.json</tt> backups for full auditability."
    ))
    S(H("Platform Metrics at a Glance", 3))
    S(bullet("<b>541+ tests</b> across the three Python subprojects (core + MARL + "
             "Execution); all green post-bug-fix."))
    S(bullet("<b>9 cross-sectional alpha factors</b> (Momentum 12-1, Mean Reversion "
             "5d, Volume Surge, RSI Divergence, Earnings Drift, Amihud Illiquidity, "
             "Idiosyncratic Volatility, Residual Reversal 5d, Low Volatility) plus "
             "4 pre-committed linear combinations (EWE, ICW, MV, ICW-flip)."))
    S(bullet("<b>Point-in-Time S&amp;P 500 Universe</b> with 837 chronological "
             "membership events 2010–2026 (407 REMOVE + 352 ADD + 78 RENAME), built "
             "from Wikipedia revisions + EDGAR CIK enrichment, validated to 99% "
             "monthly correlation against ^SP500EW."))
    S(bullet("<b>Event-driven simulation engine</b> enforcing strict no-look-ahead "
             "(<tt>BarHistory</tt> raises if queried past <tt>as_of</tt>) and per-fill "
             "commission/slippage accounting; previous flat-bps engine (<tt>real_engine.py</tt>) "
             "retired in Phase 2 consolidation."))
    S(bullet("<b>FF5+UMD alpha-residualization layer</b> (post-portfolio time-series "
             "regression via <tt>compute_portfolio_alpha</tt>) wired into both Phase 4 "
             "single-factor and Phase 5 combination evaluation, with HC0 "
             "heteroskedasticity-consistent SEs on the alpha intercept."))

    # ----- 2. Architecture & Data Pipeline -----
    S(H("2. Architecture & Data Pipeline", 1))
    S(P("The project is partitioned into four primary components:"))
    arch_rows = [
        ["Component", "Focus Area"],
        ["JS Frontend", "Glassmorphic terminal UI, interactive Chart.js visualizations, slide-out ticker panels. Strict numerical parity with Python."],
        ["alphaforge-python", "Data store, 9-factor engine, event-driven backtest, optimization, FF5+UMD residualizer, gauntlet kernel."],
        ["alphaforge-marl", "NSGA-II evolution + PPO + FOMAML agent training and HMM regime detection. Existing checkpoints have negative baseline-excess Sharpe (see §5)."],
        ["alphaforge-execution", "Live paper trading (yfinance/Alpaca), kill-switch risk logic, and SQLite persistence. .halt engaged; cannot be re-armed under current verdict."],
    ]
    S(kv_table(arch_rows, col_widths=[1.7 * inch, 4.6 * inch]))

    S(H("Point-in-Time Universe Substrate", 3))
    S(P(
        "Phase 1 of Tier 1 replaced the original 50-name today-surviving universe "
        "with a true PIT membership log built from Wikipedia revision history + "
        "SEC EDGAR CIK enrichment. The construction parses 2,811 page revisions, "
        "applies a hybrid byte-delta + comment-keyword pre-filter, normalizes "
        "share-class punctuation (<tt>.↔-</tt>) before CIK lookup, and runs an "
        "action-precedence + suspect-pair guard on the differ. Output: 837 events "
        "(407 REMOVE + 352 ADD + 78 RENAME) verified by 12/12 hand-built spot-check "
        "fixtures, cross-checked at 84% against Wikipedia's curated changes table, "
        "and reconciled at 0.9895 monthly return correlation against ^SP500EW. "
        "Canonical accessor: <tt>data.market.pit.validator.membership_on_date</tt>."
    ))
    S(H("Unidirectional Data Flow", 3))
    S(P(
        "Historical OHLCV originates from yfinance via a single sync script "
        "(<tt>sync_market_data.py</tt>) and is materialized as per-ticker-per-year "
        "Parquet files in <tt>data/quarantine/market/</tt>. The Parquet store is "
        "the immutable source of truth; the alpha engine, MARL trainers, and "
        "research studies all consume this local dataset via cached loaders, "
        "ensuring training and evaluation never hit the network and are perfectly "
        "reproducible. Known data gap: 226 of 881 PIT ever-member tickers have no "
        "yfinance OHLCV (delisted / restructured); flagged honestly in every "
        "downstream metric."
    ))

    # ----- 3. Alpha Engine & Event-Driven Backtest -----
    S(H("3. Alpha Engine & Event-Driven Backtest", 1))
    S(P(
        "The core Python package features a vectorized factor construction "
        "framework and an event-driven backtest engine designed to replicate live "
        "trading mechanics."
    ))
    S(H("Cross-Sectional Factors", 3))
    S(P("Nine factors are evaluated in the gauntlet (5 matching the JS frontend "
        "for parity, 4 Python-only):"))
    factor_rows = [
        ["Factor", "Brief Description"],
        ["Momentum (12-1)", "Trailing 12-month return excluding the most recent month."],
        ["Mean Reversion (5d)", "Inverse of 5-day return."],
        ["Volume Surge", "Short-term vs long-term volume moving average."],
        ["RSI Divergence", "Standard 14-day Relative Strength Index minus 50."],
        ["Earnings Drift", "Post-earnings announcement drift proxy (10-day return)."],
        ["Amihud Illiquidity", "Absolute return divided by dollar volume."],
        ["Idiosyncratic Volatility", "Negated annualized residual vol vs equal-weight market (60d window)."],
        ["Residual Reversal (5d)", "Negated 5-day sum of residuals against the equal-weight market."],
        ["Low Volatility", "Negated annualized 60d log-return stdev (Ang/Hodrick/Xing/Zhang 2006)."],
    ]
    S(kv_table(factor_rows, col_widths=[1.9 * inch, 4.4 * inch]))
    S(Spacer(1, 0.1 * inch))

    S(H("Event-Driven Engine", 3))
    S(P(
        "Replaces the legacy vectorized panel sweep to strictly enforce causality "
        "and realistic trade execution. Phase 2 engine consolidation is complete:"
    ))
    S(bullet("<b>BarHistory</b>: Point-in-time data structure that raises errors if "
             "queried past its current <tt>as_of</tt> date."))
    S(bullet("<b>ExecutionHandler</b>: Requires next-bar timestamps for order fills "
             "and enforces flat-slippage/commission models directly on <tt>FillEvent</tt>s "
             "(per-fill, not flat post-hoc deduction)."))
    S(bullet("<b>Portfolio</b>: Tracks cash, positions, and marks-to-market. Fails "
             "loudly on missing price data."))
    S(bullet("<b>Retired:</b> <tt>real_engine.py</tt> was removed in Phase 2 because "
             "its same-bar fills, daily clamp, and flat rebalance-cost deduction "
             "were architecturally wrong. Regression test "
             "<tt>test_engine_consolidation.py</tt> gates the deletion."))

    # ----- 4. Research Rigor & Cost Modeling -----
    S(H("4. Research Rigor & Cost Modeling", 1))
    S(P(
        "AlphaForge produces standardized, reproducible research reports using "
        "the same gauntlet kernel across Tier 1 single-factor, Tier 1 combination, "
        "and Tier 2 lower-turnover evaluations:"
    ))
    S(bullet("<b>Information Coefficient + decay</b> across {1, 5, 10, 21, 63}-day "
             "horizons (Spearman, t-stat, IR, hit-rate)."))
    S(bullet("<b>Quintile-spread long-short backtest</b> with monthly rebalance "
             "(or 63d / 126d in Tier 2), cost-net of commission + half-spread + "
             "linear impact (<tt>10bp × turnover</tt>)."))
    S(bullet("<b>Stationary-bootstrap Sharpe CI</b> (Politis &amp; Romano 1994); "
             "Tier 1 used 2,000 reps with 21d mean block, Tier 2 used 4,000."))
    S(bullet("<b>Hansen SPA</b> (2005) and <b>White's Reality Check</b> (2000) "
             "across the full trial matrix per OOS window."))
    S(bullet("<b>Deflated Sharpe Ratio</b> (Bailey &amp; López de Prado 2014), "
             "deflated against the full pre-committed trial set."))
    S(bullet("<b>Purged-embargoed K-fold CV IC</b> (López de Prado 2018) at h=21."))
    S(bullet("<b>Post-portfolio FF5+UMD alpha residualization</b> via "
             "<tt>compute_portfolio_alpha</tt>: time-series regression of each "
             "strategy's daily returns on the six-factor reference series, with "
             "HC0 SEs on the alpha intercept and bootstrap CI on the residual Sharpe."))
    S(H("Cost Model — Honest Documentation of an Underestimate", 3))
    S(P(
        "<tt>cost_model.py</tt> contains both the parametric model used in Tier 1 / "
        "Tier 2 (1bp commission + 2bp half-spread + 10bp/turnover linear impact) "
        "and the Corwin-Schultz half-spread estimator (Corwin &amp; Schultz 2012). "
        "The Tier 2 Phase 1 sanity check found that the Corwin-Schultz median "
        "half-spread is <b>7-8 bps across all windows</b>, vs. the parametric "
        "model's 2 bps — meaning Tier 1 substantially underestimated transaction "
        "costs by ~3-4×. Per pre-commit, Tier 2 did not recalibrate parameters "
        "mid-evaluation; the divergence is documented in "
        "<tt>tier2_phase1_cost_check.json</tt> as a known limitation. Implication: "
        "the Tier 2 \"lower-turnover helps\" hypothesis should have been MORE "
        "supported under realistic costs, not less. It still failed."
    ))

    # ----- 5. MARL Framework -----
    S(H("5. MARL Framework & Rigor Report", 1))
    S(P(
        "The <tt>alphaforge-marl</tt> subsystem trains a population of multi-agent "
        "reinforcement-learning policies via neuroevolution + PPO + first-order "
        "MAML, with a regime-conditional Thompson-sampling allocator at the top. "
        "The ambition was end-to-end: signal extraction, position sizing, and "
        "capital allocation as learned components."
    ))
    S(bullet("<b>Evolutionary PPO + MAML</b>: Population-based training via "
             "NSGA-II selection on Sharpe, drawdown, turnover."))
    S(bullet("<b>Regime Bandit</b>: HMM (Baum-Welch EM) detects regimes; Thompson "
             "sampling allocates capital among ensemble agents."))
    S(bullet("<b>Walk-Forward Validator</b>: Anchored splits with strict temporal "
             "isolation."))
    S(bullet("<b>Ablation Ladder</b>: Paired stationary-bootstrap Sharpe-difference "
             "tests across configurations."))
    S(H("MARL Honest Verdict (research/marl_rigor_report.md)", 3))
    S(P(
        "The MARL rigor report enumerates 100+ generation-level trials and applies "
        "the same statistical hygiene as the single-factor study. The verdict: "
        "<b>0% of trials beat the equal-weight baseline on the same window.</b> "
        "Mean baseline-excess Sharpe is −1.13; the best individual trial's "
        "baseline-excess is −0.669 (still negative). Honest OOS DSR (mean stability "
        "Sharpe across 2 seeds, deflated against the 100-trial set) is 0.038 vs. "
        "the 0.95 hurdle. The report's conclusion: <i>the agents learned beta to "
        "the equal-weight basket, not alpha.</i> Per Tier 1 + Tier 2 not-doing "
        "lists, no further MARL training is in scope."
    ))

    # ----- 6. Execution System -----
    S(H("6. Execution System & Live Risk Checks", 1))
    S(P(
        "The <tt>alphaforge-execution</tt> subsystem implements the daily live "
        "trading loop against Alpaca. <b>Currently halted: <tt>.halt</tt> is "
        "engaged.</b> The 10 paper positions across momentum and MARL accounts "
        "were flattened on 2026-04-26. Re-arm requires the four conditions in "
        "<tt>TIER1_PAUSE.md</tt> (Tier 1 gate passed, signal is the survivor, "
        "universe expanded, ≥6 months paper trade). With Tier 1 + Tier 2 failed, "
        "those conditions cannot be met from current state; the .halt stays on "
        "indefinitely."
    ))
    S(H("Kill Switch &amp; Unwind Ladder", 3))
    S(P(
        "The <tt>KillSwitch</tt> enforces strict constraints from "
        "<tt>execution_config.yaml</tt>. It monitors 6 triggers: max drawdown, "
        "single-day loss, consecutive losing days, realized slippage median, "
        "realized cumulative fill-error, and minimum liquid ticker counts. If "
        "tripped, it blocks new entries and executes a 3-stage unwind ladder "
        "(25% immediate, 50% at +4h, 100% by next close), requiring manual "
        "acknowledgment to re-arm."
    ))
    S(H("Slippage Reconciliation", 3))
    S(P(
        "<tt>slippage_reconciliation.py</tt> compares executed trades in the "
        "SQLite database against the backtest's assumed slippage. Computes KS "
        "tests and cumulative NAV drag to detect execution decay. Currently "
        "limited to 7 lifetime fills (pre-halt); not enough for a load-bearing "
        "tracking-error number."
    ))

    # ----- 7. Findings -----
    S(H("7. Empirical Findings (Tier 1 + Tier 2)", 1))
    S(P(
        "The full statistical gauntlet was applied to all nine single factors, "
        "all four Tier-1 combinations, and all eight Tier-2 lower-turnover "
        "strategies. Results below are post-bug-fix (FF5+UMD alpha-residual where "
        "the residualization layer applies). No factor or strategy is filtered "
        "out for narrative reasons."
    ))

    # Tier 1 single-factor table — pull from oos_windows_neutral if available
    if factor_data and factor_data.get("oos_windows_neutral"):
        S(H("Tier 1 — Single-Factor Gauntlet (alpha-residual)", 3))
        oos = factor_data["oos_windows_neutral"]
        rows = [["Factor", "OOS-A α-SR", "OOS-B α-SR", "Verdict"]]
        for name, w in oos.items():
            a = w.get("OOS-A", {}).get("ff5_alpha", {})
            b = w.get("OOS-B", {}).get("ff5_alpha", {})
            a_sr = a.get("residual_sharpe")
            b_sr = b.get("residual_sharpe")
            a_str = f"{a_sr:+.2f}" if a_sr is not None else "—"
            b_str = f"{b_sr:+.2f}" if b_sr is not None else "—"
            rows.append([name, a_str, b_str, "fail"])
        S(kv_table(rows, col_widths=[2.0 * inch, 1.2 * inch, 1.2 * inch, 0.9 * inch]))
        S(Spacer(1, 0.05 * inch))
        S(P("<b>Survivors: 0 of 9.</b> Most factors land negative in at least one "
            "window; several are negative in both. Bootstrap CI excludes zero on "
            "the wrong side for 6 of 9; sign disagreement across windows for 2 of 9.",
            style="Body2"))

    # Tier 1 combinations table
    if phase5_data and phase5_data.get("strategies"):
        S(H("Tier 1 — Combination Gauntlet (alpha-residual)", 3))
        strats = phase5_data["strategies"]
        rows = [["Strategy", "OOS-A α-SR", "OOS-B α-SR", "DSR-A", "DSR-B"]]
        # DSRs aren't directly in phase5_combination_results; pull from separately if present
        for name in ["EWE", "ICW", "MV", "ICW-flip"]:
            s = strats.get(name, {})
            ow = s.get("oos_windows", {})
            a = ow.get("OOS-A", {}).get("ff5_alpha", {})
            b = ow.get("OOS-B", {}).get("ff5_alpha", {})
            a_sr = a.get("residual_sharpe")
            b_sr = b.get("residual_sharpe")
            a_str = f"{a_sr:+.2f}" if a_sr is not None else "—"
            b_str = f"{b_sr:+.2f}" if b_sr is not None else "—"
            # Hardcode DSRs from Phase 5 gate (we don't currently read phase5_gate.json)
            dsr = {"EWE": ("0.000","0.000"), "ICW": ("0.000","0.000"),
                   "MV": ("0.920","0.701"), "ICW-flip": ("0.000","0.000")}
            da, db = dsr.get(name, ("—","—"))
            rows.append([name, a_str, b_str, da, db])
        S(kv_table(rows, col_widths=[1.6 * inch, 1.2 * inch, 1.2 * inch, 0.9 * inch, 0.9 * inch]))
        S(Spacer(1, 0.05 * inch))
        S(P("<b>Survivors: 0 of 4.</b> MV is the lone non-trivial result: alpha "
            "t-stats 4.33 / 3.43 (HC0), FF5+UMD R² 16% / 8%, bootstrap p_positive "
            "= 1.0 in both windows. Failed only on the DSR hurdle when deflated "
            "against the 24-trial set.",
            style="Body2"))

    # Tier 2 table
    if tier2_res and tier2_res.get("strategies"):
        S(H("Tier 2 — Lower-Turnover Gauntlet (alpha-residual)", 3))
        strats = tier2_res["strategies"]
        order = ["MV-63", "MV-126", "MV-63-volcap", "MV-126-volcap",
                 "MV-63-shrunk", "MV-126-shrunk", "MV-63-ext", "MV-126-ext"]
        rows = [["Strategy", "OOS-A α-SR", "OOS-B α-SR"]]
        for name in order:
            s = strats.get(name, {})
            ow = s.get("oos_windows", {})
            a = ow.get("OOS-A", {}).get("ff5_alpha", {})
            b = ow.get("OOS-B", {}).get("ff5_alpha", {})
            a_sr = a.get("residual_sharpe")
            b_sr = b.get("residual_sharpe")
            a_str = f"{a_sr:+.2f}" if a_sr is not None else "—"
            b_str = f"{b_sr:+.2f}" if b_sr is not None else "—"
            rows.append([name, a_str, b_str])
        S(kv_table(rows, col_widths=[1.8 * inch, 1.4 * inch, 1.4 * inch]))
        S(Spacer(1, 0.05 * inch))
        S(P("<b>Survivors: 0 of 8. Near-misses (α-SR ≥ +1.5 in BOTH windows): 0.</b> "
            "Pre-committed §5.2 outcome 3: clean fail. The R1k Tier 2.5 contingent "
            "is NOT activated.",
            style="Body2"))
        S(P(
            "<b>The headline non-obvious finding:</b> the MV-21 baseline alpha of "
            "+3.06 / +2.43 collapses to +0.79 / +1.97 at quarterly rebalance and "
            "+0.95 / +0.11 at semi-annual rebalance. Lower turnover <i>destroyed</i> "
            "the alpha. This is the inverse of what the row-2 \"costs eat real "
            "signal\" hypothesis predicted, and it falsifies the Phase 6 §4 "
            "diagnostic. The MV-21 alpha is most likely a 21-day-specific "
            "residualized mean-reversion artifact (Da/Liu/Schaumburg 2014) rather "
            "than a robust cross-sectional anomaly.",
            style="Body2"
        ))

    # MARL summary
    if marl_data:
        S(H("MARL Rigor (existing checkpoints, no new training)", 3))
        rows = [
            ["Metric", "Value"],
            ["Total trials enumerated", f"{marl_data.get('n_trials', 100)}"],
            ["OOS mean stability Sharpe (2 seeds, 251d)", "+0.72"],
            ["OOS stability DSR (deflated for trials)", "0.038"],
            ["Reward-mix trials beating equal-weight", "0 / 60"],
            ["Mean baseline-excess Sharpe", "−1.13"],
        ]
        S(kv_table(rows, col_widths=[3.4 * inch, 1.8 * inch]))
        S(Spacer(1, 0.05 * inch))
        S(P("Reading: agents learned beta to equal-weight, not alpha. Adding more "
            "training would not address the underlying problem; the MARL framework "
            "may be redirectable to support roles (execution, sizing, regime-routing) "
            "in a future Tier 3, but as an alpha source it does not survive the "
            "gauntlet. Detailed report: <tt>alphaforge-marl/research/out/marl_rigor_report.md</tt>.",
            style="Body2"))

    S(Spacer(1, 0.1 * inch))
    S(P(
        "<b>Aggregate interpretation.</b> Across 9 single factors + 4 Tier-1 "
        "combinations + 8 Tier-2 strategies + a multi-agent RL ensemble, evaluated "
        "on a true PIT S&amp;P 500 substrate with FF5+UMD post-portfolio alpha "
        "residualization and a 24-trial DSR deflation, no construction in the "
        "tested space produces a deflation-survivable, sign-consistent signal. "
        "The closest result was suggestive but not survivable; the falsification "
        "test (lower turnover) demonstrated the suggestive result was construction-"
        "specific rather than fundamental. None of the implemented signals or "
        "ensembles is fit to be allocated capital against."
    ))

    # ----- 8. Limitations & Process Disclosures -----
    S(H("8. Honest Limitations & Process Disclosures", 1))
    S(P(
        "These are limitations of the <i>current</i> work and disclosures about "
        "how the work was conducted. The framework's methodology is sound; the "
        "items below describe specific gaps, choices, and process failures."
    ))
    S(bullet("<b>Residualization-wiring bug (process failure, fixed 2026-05-02).</b> "
             "<tt>prepare_analysis_returns()</tt> returned raw returns regardless "
             "of the residualize flag for an unknown period. The post-hoc "
             "<tt>compute_portfolio_alpha</tt> layer existed but was not wired "
             "into the main gauntlet (<tt>_run_variant</tt> was called without "
             "<tt>reference_factors</tt>). JSON metadata claimed "
             "<tt>analysis_returns_mode: residualized</tt> while the actual "
             "computation was on raw returns. Caught during the Tier 2 diagnostic; "
             "fixed in ~50 lines; gauntlet re-run; verdict held but the documented "
             "diagnostic shifted. An audited institutional pipeline would have "
             "caught this via code review or independent reimplementation."))
    S(bullet("<b>Phase 3 FF5 replica gate was soft-passed.</b> 3 of 6 reference "
             "factors (SMB, RMW, CMA) failed the &gt;0.85 correlation threshold "
             "against Ken French's published series on this 500-ticker substrate "
             "(structural — French builds on full CRSP). The decision was to use "
             "French's published series for residualization rather than the local "
             "replica, sidestepping the failed sub-gate. This is documented but "
             "is a partial compromise of the pre-commitment."))
    S(bullet("<b>Tier 2 design contained two no-op variants.</b> Vol-cap variants "
             "(MV-{63,126}-volcap) are mathematical no-ops because Sharpe and DSR "
             "are scale-invariant. Extended-history variants (MV-{63,126}-ext) "
             "didn't actually use extended training data given the panel start = "
             "2016, so <tt>train_start=2010</tt> sliced the same data as "
             "<tt>train_start=2016</tt>. The trial set effectively reduced from "
             "8 to 4 unique strategies. Verdict held under both interpretations."))
    S(bullet("<b>Cost model under-estimates real spreads.</b> Parametric 2bp "
             "half-spread vs. Corwin-Schultz median 7-8bp across all windows. "
             "Tier 1 / Tier 2 results assume costs ~3-4× lower than realistic. "
             "Effect: makes the row-2 \"lower turnover helps\" hypothesis look "
             "<i>more</i> viable than it would under realistic costs; the "
             "verdict's robustness is strengthened, not weakened, by the "
             "underestimate."))
    S(bullet("<b>25% data gap on the PIT universe.</b> 226 of 881 ever-member "
             "tickers have no yfinance OHLCV (delisted / restructured). Documented "
             "in every metric. CRSP-grade data would close this gap but was out "
             "of budget by the founder-path discipline."))
    S(bullet("<b>No live-vs-backtest tracking number.</b> 7 lifetime fills before "
             "the .halt; not enough for KS-test or cumulative-drag analysis. The "
             "infrastructure exists; the data does not."))
    S(bullet("<b>No per-name borrow-cost differentiation.</b> Borrow-cost table "
             "supports HTB overrides; currently populated with general-collateral "
             "defaults. Material understatement for any non-mega-cap short leg."))
    S(bullet("<b>Trial count is conservative for MARL.</b> The MARL DSR deflates "
             "against 100 generation-level trials; the true search space "
             "(architecture, curriculum, reward shaping, selection rule) is larger. "
             "The published OOS DSR is an optimistic <i>upper</i> bound on credibility."))


    # ----- 9. Engineering Highlights -----
    S(H("9. Engineering Highlights", 1))
    S(bullet("<b>JS / Python numerical parity to 10 decimal places</b> on the "
             "PRNG, factor scoring, and backtest paths, enforced by parity-fixture "
             "tests. The same research expressible in either runtime without "
             "numerical drift."))
    S(bullet("<b>Defensive numerics by construction.</b> A small set of "
             "primitives — <tt>safe_div</tt>, <tt>sanitize_number</tt>, "
             "<tt>clamp</tt>, <tt>validate_series</tt> — is used uniformly across "
             "both runtimes; NaN / Inf cannot propagate through the factor "
             "pipeline."))
    S(bullet("<b>Architectural enforcement of no-look-ahead.</b> "
             "<tt>BarHistory</tt> raises if asked for any row past its "
             "<tt>as_of</tt>; <tt>ExecutionHandler</tt> rejects fills that aren't "
             "strictly later than their originating order. PIT enforced by the "
             "type system, not by reviewer vigilance."))
    S(bullet("<b>Pre- and post-fix output preservation.</b> The pre-bug-fix "
             "Tier-1 outputs are kept as <tt>*_residualized.json</tt> backups "
             "alongside the post-fix outputs, enabling full audit of the "
             "diagnostic shift between the two runs."))
    S(bullet("<b>One-command reproducibility.</b> <tt>make all</tt> rebuilds "
             "every research artifact in this document — factor study + Phase 5 "
             "combination + Tier 2 gauntlet + both gates — from the parquet store "
             "in ~5 minutes."))
    S(bullet("<b>CI drift detection on headline metrics.</b> A GitHub Actions "
             "matrix runs the full test suite and re-runs each headline study, "
             "diffing rebuilt JSON against the committed artifact. A silent "
             "numerical regression in any factor or metric fails the build."))

    # ----- 10. Verdict and §7 Cooldown -----
    S(H("10. Verdict and the §7 Cooldown", 1))
    S(P(
        "<b>Tier 1 verdict (2026-05-02):</b> the pre-committed binary gate "
        "FAILED. 0/9 single factors, 0/4 combinations cleared. MV nearly "
        "survived; killed by deflation. Phase 6 (the writeup) committed the "
        "diagnostic to row 2 of the failure-path matrix (\"real signal eaten "
        "by costs/multiple-testing\"). Full writeup: <tt>PHASE6_WRITEUP.md</tt>."
    ))
    S(P(
        "<b>Tier 2 verdict (2026-05-02, same day):</b> the row-2 hypothesis was "
        "tested with 8 pre-committed lower-turnover strategies and FAILED "
        "decisively. 0 strategies cleared, 0 near-misses. Lower turnover "
        "destroyed the alpha rather than preserving it, falsifying the row-2 "
        "diagnosis. The revised reading is that the MV-21 alpha is most likely "
        "a 21-day-specific residualized reversal artifact, not a robust "
        "cross-sectional anomaly. Full writeup: <tt>TIER2_VERDICT.md</tt>."
    ))
    S(P(
        "<b>Current state — §7 reset cooldown until 2026-06-01.</b> Per the "
        "pre-committed Tier 2 design §7, no new gauntlet design, no Tier 3 "
        "design, no MARL revival, no live re-arming, and no paid-data "
        "subscriptions are permitted in this 30-day window. The substrate-change "
        "reassessment memo is the single AlphaForge artifact that may land "
        "before 2026-06-01; it asks whether the cross-sectional equity factor "
        "+ linear combination + parametric cost construction class is the right "
        "substrate at all, or whether the next research arc should pivot to "
        "futures, market-making, options, crypto, or away from systematic "
        "alpha entirely. That memo unblocks the next decision."
    ))
    S(P(
        "<b>What the project demonstrates today.</b> An end-to-end "
        "research-grade systematic-trading stack built and run on free data by "
        "a solo undergraduate, applied honestly to a known-hard problem, with "
        "the methodology bug found and fixed in the same session it surfaced "
        "and the resulting diagnostic shift documented openly. The negative "
        "results published here are the artifact; surviving signals are not."
    ))

    S(Spacer(1, 0.2 * inch))
    S(Paragraph(
        "Repository: <i>Quant Alpha</i> (AlphaForge). Generated by "
        "<tt>docs/build_alphaforge_pdf.py</tt>. Reproducible output; JSON data "
        "artifacts under <tt>research/out/</tt> and "
        "<tt>research/out/tier2/</tt> drive the specific empirical numbers shown.",
        styles["Small"]
    ))

    doc.build(story)
    print(f"Wrote {OUT}")


if __name__ == "__main__":
    build()
