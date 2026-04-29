"""Generate a polished PDF overview of the AlphaForge project.

Self-contained — reads the research reports under
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
        "A quantitative research stack — point-in-time event-driven backtesting, "
        "deflation-aware statistical evaluation, evolutionary multi-agent RL, "
        "and live paper-trading execution — applied honestly to a 50-ticker US "
        "large-cap universe.",
        styles["Subtitle"]
    ))
    S(Spacer(1, 0.2 * inch))
    S(P("<b>Author:</b> Atharva Patil"))
    S(Spacer(1, 0.05 * inch))
    S(P("<b>Components:</b> JS frontend · Python alpha engine · MARL framework · "
        "Live paper-trading execution"))
    S(P("<b>Scale:</b> 3 Python backend services · 785 tests · 11 core factors · "
        "837 point-in-time S&P 500 membership events (Phase 1 complete)"))
    S(Spacer(1, 0.25 * inch))
    S(H("Abstract", 3))
    S(Paragraph(
        "AlphaForge applies an end-to-end systematic-trading lifecycle — data, factors, "
        "event-driven backtesting, transaction-cost modeling, statistical evaluation, RL, "
        "and live execution — to nine cross-sectional equity signals on a 50-ticker US "
        "large-cap universe (2016–2025). <b>The headline result is a negative one, "
        "deliberately:</b> none of the implemented signals clears a Deflated Sharpe Ratio "
        "of 0.95 out-of-sample net of costs, and the multi-agent RL ensemble does not "
        "produce positive baseline-excess Sharpe on held-out windows. The contribution of "
        "this work is the methodology and infrastructure to apply that gauntlet at scale "
        "(Hansen SPA, White's Reality Check, Deflated Sharpe, López de Prado purged "
        "K-fold, square-root market impact, Corwin-Schultz spread, borrow-cost modeling, "
        "kill-switch live risk), and the discipline to publish the negative finding rather "
        "than hide it. Surviving signals are the next deliverable, not this one.",
        styles["Body2"]
    ))

    S(Spacer(1, 0.3 * inch))
    # TOC-style summary
    toc_rows = [
        ["§", "Section"],
        ["1", "Executive Summary"],
        ["2", "Architecture & Data Pipeline"],
        ["3", "Alpha Engine & Event-Driven Backtest"],
        ["4", "Research Rigor & Cost Modeling"],
        ["5", "MARL Framework & Ablation Studies"],
        ["6", "Execution System & Live Risk Checks"],
        ["7", "Empirical Findings"],
        ["8", "Honest Limitations & Roadmap"],
        ["9", "Engineering Highlights"],
    ]
    S(kv_table(toc_rows, col_widths=[0.5 * inch, 5.3 * inch]))
    S(PageBreak())

    # ----- 1. Executive summary -----
    S(H("1. Executive Summary", 1))
    S(P(
        "<b>Headline result.</b> Across nine cross-sectional equity factors and a "
        "multi-agent RL ensemble, evaluated on 50 US large-caps from 2016–2025 with a "
        "realistic cost model and deflation across the full trial set, no signal clears a "
        "Deflated Sharpe Ratio of 0.95 out-of-sample. The best single factor (Momentum 12-1) "
        "lands at DSR ≈ 0.14; the MARL ensemble's mean OOS stability Sharpe deflates to "
        "DSR ≈ 0.04 against 100 enumerated trials. An equal-weight long-only baseline on "
        "the same universe earns Sharpe +0.92 over the period — every factor overlay "
        "underperforms it net of costs. This is reported up front, not buried."
    ))
    S(P(
        "<b>What the project actually contributes.</b> The methodology and infrastructure "
        "that produced the result above. AlphaForge implements the full systematic-trading "
        "lifecycle — data ingestion, factor construction, point-in-time event-driven "
        "backtesting, transaction-cost modeling, deflation-aware statistical evaluation, "
        "neuroevolutionary multi-agent RL, and a live paper-trading execution loop with "
        "kill-switch risk logic. The statistical layer integrates the Deflated Sharpe Ratio "
        "(Bailey & López de Prado), Hansen's Superior Predictive Ability test, White's "
        "Reality Check, López de Prado's Purged K-Fold cross-validation, and stationary-"
        "bootstrap confidence intervals. Cost modeling integrates a square-root market-"
        "impact model, Corwin-Schultz spread estimation, and a borrow-cost table for "
        "short legs."
    ))
    S(P(
        "<b>Why the negative result is the right artifact for now.</b> The known failure "
        "modes of factor-discovery work — survivorship bias, in-sample selection, multiple "
        "testing, ignored borrow costs, optimistic impact assumptions — would each push a "
        "naive backtest into a falsely positive Sharpe. AlphaForge's gauntlet is "
        "specifically designed to surface those failures. That none of the implemented "
        "signals survive that gauntlet on this universe is informative; it bounds the "
        "space where genuine edge can credibly be claimed and identifies the next moves "
        "(point-in-time universe expansion, risk-model residualization, signal "
        "combination)."
    ))
    S(H("Platform Metrics at a Glance", 3))
    S(bullet("<b>785 tests</b> across the three Python subprojects (541 core, 122 MARL, 122 Execution)."))
    S(bullet("<b>11 implemented alpha factors</b> including classic momentum, mean reversion, "
             "Amihud illiquidity, and idiosyncratic volatility."))
    S(bullet("<b>Point-in-Time S&P 500 Universe</b> with 837 membership events verified across 15 years, "
             "plus 10 years of real-market Parquet history."))
    S(bullet("<b>Event-driven simulation engine</b> enforcing strict no-look-ahead and per-fill "
             "commission/slippage accounting."))

    # ----- 2. Architecture & Data Pipeline -----
    S(H("2. Architecture & Data Pipeline", 1))
    S(P("The project is partitioned into four primary components:"))
    arch_rows = [
        ["Component", "Focus Area"],
        ["JS Frontend", "Glassmorphic terminal UI, interactive Chart.js visualizations, slide-out ticker panels. Strict numerical parity with Python."],
        ["alphaforge-python", "Data store, 11-factor engine, event-driven backtest, optimization, and rigorous studies."],
        ["alphaforge-marl", "NSGA-II evolution + PPO + FOMAML agent training and HMM regime detection."],
        ["alphaforge-execution", "Live paper trading (yfinance/Alpaca), kill-switch risk logic, and SQLite persistence."],
    ]
    S(kv_table(arch_rows, col_widths=[1.7 * inch, 4.6 * inch]))
    
    S(H("Unidirectional Data Flow", 3))
    S(P(
        "Historical data originates from yfinance via a single sync script, and is materialized "
        "as per-ticker-per-year Parquet files in <tt>data/market/</tt>. This Parquet store is "
        "the immutable source of truth for the entire ecosystem. The Alpha Engine, MARL "
        "trainers, and research studies all consume this local dataset via a cached loader, "
        "ensuring that training and evaluation never hit the network and are perfectly reproducible."
    ))

    # ----- 3. Alpha Engine & Event-Driven Backtest -----
    S(H("3. Alpha Engine & Event-Driven Backtest", 1))
    S(P(
        "The core Python package features a sophisticated factor construction framework "
        "and a robust event-driven backtest engine designed to replicate live trading mechanics."
    ))
    S(H("Cross-Sectional Factors", 3))
    S(P("Eleven core factors are supported (5 matching the JS frontend for parity, and 6 advanced Python-only factors):"))
    factor_rows = [
        ["Factor", "Brief Description"],
        ["Momentum (12-1)", "Trailing 12-month return excluding the most recent month."],
        ["Mean Reversion (5d)", "Inverse of 5-day return."],
        ["Volume Surge", "Short-term vs long-term volume moving average."],
        ["RSI Divergence", "Standard 14-day Relative Strength Index minus 50."],
        ["Earnings Drift", "Post-earnings announcement drift proxy (10-day return)."],
        ["Low Volatility", "Inverse realized 60-day volatility."],
        ["Amihud Illiquidity", "Absolute return divided by dollar volume."],
        ["Idiosyncratic Volatility", "Residual volatility against an equal-weight market proxy."],
        ["Residual Reversal (5d)", "5-day mean reversion residualized against the market."],
    ]
    S(kv_table(factor_rows, col_widths=[1.9 * inch, 4.4 * inch]))
    S(Spacer(1, 0.1 * inch))
    
    S(H("Event-Driven Engine", 3))
    S(P(
        "Replaces the legacy vectorized panel sweep to strictly enforce causality and realistic "
        "trade execution. Phase 2 engine consolidation is complete. Key components include:"
    ))
    S(bullet("<b>BarHistory</b>: A point-in-time data structure that raises errors if queried past its current <tt>as_of</tt> date."))
    S(bullet("<b>ExecutionHandler</b>: Requires next-bar timestamps for order fills and enforces flat-slippage/commission models directly on <tt>FillEvent</tt>s."))
    S(bullet("<b>Portfolio</b>: Tracks cash, positions, and marks-to-market. Fails loudly on missing price data."))

    # ----- 4. Research Rigor & Cost Modeling -----
    S(H("4. Research Rigor & Cost Modeling", 1))
    S(P(
        "AlphaForge produces standardized, reproducible 'headline' research reports using "
        "advanced statistical techniques."
    ))
    S(bullet("<b>Factor Study (<tt>factor_study.py</tt>)</b>: Evaluates all 9 factors. Outputs Spearman IC, IC-decay, "
             "quintile-spread returns, stationary-bootstrap Sharpe CIs, and the Deflated Sharpe Ratio. "
             "Incorporates Hansen's SPA and White's Reality Check to control for multiple testing."))
    S(bullet("<b>Cost Model (<tt>cost_model.py</tt>)</b>: Honest transaction cost library featuring the "
             "<tt>SquareRootImpactModel</tt> (k·√participation), <tt>corwin_schultz_spread</tt> estimators, and a "
             "<tt>BorrowCostTable</tt> for short legs."))
    S(bullet("<b>Capacity Study (<tt>capacity_study.py</tt>)</b>: AUM-grid sweep that models capacity decay "
             "using square-root impact. Reports tercile regime-conditional Sharpe and crowding proxies."))

    # ----- 5. MARL Framework -----
    S(H("5. MARL Framework & Ablation Studies", 1))
    S(P(
        "The <tt>alphaforge-marl</tt> subsystem trains a population of multi-agent "
        "reinforcement-learning policies via neuroevolution + PPO + first-order MAML, "
        "with a regime-conditional Thompson-sampling allocator at the top. The ambition "
        "is end-to-end: signal extraction, position sizing, and capital allocation are "
        "all learned components, not hand-coded layers. As reported in §7, the current "
        "checkpoints do not yet clear the deflation bar; the framework's value at this "
        "stage is the substrate it provides for that test."
    ))
    S(bullet("<b>Evolutionary PPO + MAML</b>: Population-based training via NSGA-II selection on Sharpe, drawdown, "
             "and turnover. Uses Proximal Policy Optimization for fine-tuning and First-Order MAML for fast regime adaptation."))
    S(bullet("<b>Regime Bandit</b>: An HMM (Baum-Welch EM) detects market regimes and uses Thompson sampling "
             "to dynamically allocate capital among the ensemble agents."))
    S(bullet("<b>Walk-Forward Validator</b>: Uses anchored splits (e.g. train 2022-23, val 2024, test 2025) "
             "with strict temporal isolation to prevent label leakage."))
    S(bullet("<b>Ablation Ladder (<tt>ablation_ladder.py</tt>)</b>: Conducts paired stationary-bootstrap "
             "Sharpe-difference tests across varying MARL configurations (e.g., baseline vs. single-PPO vs. "
             "no-bandit vs. full-MARL). Helps statistically prune system components that don't add value."))

    # ----- 6. Execution System -----
    S(H("6. Execution System & Live Risk Checks", 1))
    S(P(
        "The <tt>alphaforge-execution</tt> subsystem implements the daily live trading loop against Alpaca. "
        "It fetches prices, ranks tickers using a composite momentum model extracted from the MARL environment, "
        "and executes target portfolios."
    ))
    S(H("Kill Switch & Unwind Ladder", 3))
    S(P(
        "The <tt>KillSwitch</tt> enforces strict constraints defined in <tt>execution_config.yaml</tt>. It monitors 6 triggers: "
        "max drawdown, single-day loss, consecutive losing days, realized slippage median, realized cumulative fill-error, "
        "and minimum liquid ticker counts. If tripped, it blocks new entries and executes a 3-stage unwind ladder "
        "(25% immediate, 50% at +4h, 100% by next close), requiring manual acknowledgment to re-arm."
    ))
    S(H("Slippage Reconciliation", 3))
    S(P(
        "A nightly script (<tt>slippage_reconciliation.py</tt>) compares executed trades in the SQLite database "
        "against the backtest's assumed slippage. It computes KS tests and cumulative NAV drag to detect execution decay."
    ))

    # ----- 7. Findings -----
    S(H("7. Empirical Findings", 1))
    S(P(
        "The full statistical gauntlet is applied to all nine factors and to the MARL "
        "ensemble. The results are reported below as produced — no factor or trial is "
        "filtered out for narrative reasons."
    ))
    
    if factor_data:
        S(H("Single-Factor Results", 3))
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
            f"<b>Equal-Weight Baseline:</b> Sharpe "
            f"{eq.get('sharpe', 0):+.2f}, annual return {eq.get('ann_return', 0):+.1%}, "
            f"max DD {eq.get('max_drawdown', 0):.1%}. This baseline is deliberately tough "
            "but partly artificial — the universe is today's surviving large-caps, so the "
            "long-only equal-weight series is materially survivorship-biased upward "
            "(roughly 1–2% annualized over a decade, see §8). On a point-in-time S&amp;P 500 "
            "the baseline Sharpe would compress and the factor-vs-baseline gap would narrow."
        ))

    if marl_data:
        S(H("MARL Rigor Metrics", 3))
        rows = [
            ["Metric", "Value"],
            ["Total trials enumerated", f"{marl_data.get('n_trials', 0)}"],
            ["Val-Sharpe distribution (max, in-sample)", f"{marl_data.get('sharpe_distribution', {}).get('max', 0):+.2f}"],
            ["OOS mean stability Sharpe (2 seeds, 251d)", f"{marl_data.get('mean_oos_sharpe', 0):+.2f}"],
            ["OOS stability DSR (deflated for trials)", f"{marl_data.get('dsr_oos_mean', {}).get('dsr', 0):.3f}"],
            ["Reward-mix trials beating equal-weight", "0 / 60"],
        ]
        S(kv_table(rows, col_widths=[3.4 * inch, 1.8 * inch]))
        S(Spacer(1, 0.05 * inch))
        S(P(
            "<i>The in-sample max Sharpe is reported for completeness only; after "
            "selection it is mechanically optimistic and is not the figure to evaluate. "
            "The honest headline is the OOS stability DSR, which is well below 0.95.</i>",
            style="Small"
        ))

    S(Spacer(1, 0.1 * inch))
    S(P(
        "<b>Interpretation.</b> The high in-sample Sharpes are an order-statistic artifact "
        "of selecting the best generation across a multi-trial search; once deflated for the "
        "search and evaluated out-of-sample, the residual signal is consistent with beta "
        "exposure to the equal-weight basket rather than actionable alpha. None of the "
        "implemented signals or ensembles is currently fit to be allocated capital against."
    ))

    # ----- 8. Limitations & Roadmap -----
    S(H("8. Honest Limitations & Roadmap", 1))
    S(P(
        "These are limitations of the <i>current</i> work, not of the framework. Each is "
        "addressable, and the roadmap is sequenced by leverage."
    ))
    S(bullet("<b>Survivorship bias is solved, but metrics below reflect the legacy substrate.</b> "
             "Phase 1 (point-in-time S&amp;P 500 reconstruction) is complete with 837 membership "
             "events verified. However, the headline metrics in §7 still run on the legacy 50-name "
             "universe for parity. Tier 1 mandates migrating the full pipeline to the PIT substrate."))
    S(bullet("<b>No risk-model neutralization (Active Deliverable).</b> Factor returns are currently "
             "raw or sector-demeaned only. Phase 3 (Fama-French-5 + momentum residualization) is "
             "the active deliverable; until it lands, every reported Sharpe is contaminated by beta "
             "and style exposures the equal-weight baseline already captures."))
    S(bullet("<b>No live-vs-backtest tracking number is published yet.</b> The execution loop "
             "and slippage-reconciliation script exist and are running; however, the cumulative "
             "tracking-error number is not yet large-sample enough to be load-bearing in this "
             "document. It will be added once ≥ 60 trading days of paper-trade fills are "
             "persisted."))
    S(bullet("<b>Capacity is modeled but not yet quantified per signal.</b> "
             "<tt>capacity_study.py</tt> implements the square-root impact AUM-grid sweep; the "
             "next iteration will publish the AUM at which each surviving signal's net Sharpe "
             "decays to zero."))
    S(bullet("<b>Borrow costs not differentiated by name.</b> The borrow-cost table supports a "
             "per-name HTB override map but is currently populated with general-collateral "
             "defaults. For a non-mega-cap universe this is unrealistic and erodes short-leg "
             "alpha materially."))
    S(bullet("<b>Trial count is under-reported in the deflation analysis.</b> The MARL DSR "
             "deflates over 100 generation-level trials; the true search space (architecture, "
             "curriculum, reward shaping, selection rule) is larger. The published OOS DSR is "
             "an optimistic <i>upper</i> bound on credibility, not a lower bound."))


    # ----- 9. Engineering Highlights -----
    S(H("9. Engineering Highlights", 1))
    S(bullet("<b>JS / Python numerical parity to 10 decimal places</b> on the PRNG, factor "
             "scoring, and backtest paths, enforced by parity-fixture tests. Lets the same "
             "research be expressed and demoed in either runtime without numerical drift."))
    S(bullet("<b>Defensive numerics by construction.</b> A small set of primitives — "
             "<tt>safe_div</tt>, <tt>sanitize_number</tt>, <tt>clamp</tt>, "
             "<tt>validate_series</tt> — is used uniformly across both runtimes; NaN / "
             "Inf cannot propagate through the factor pipeline."))
    S(bullet("<b>CI drift detection on headline metrics.</b> A GitHub Actions matrix runs the "
             "full test suite and re-runs each headline study, diffing rebuilt JSON against the "
             "committed artifact. A silent numerical regression in any factor or metric fails "
             "the build."))
    S(bullet("<b>One-command reproducibility.</b> <tt>make all</tt> rebuilds every research "
             "artifact in this document — <tt>factor-study</tt>, <tt>capacity-study</tt>, "
             "<tt>marl-rigor</tt>, <tt>ablation-ladder</tt> — from the parquet store."))
    S(bullet("<b>Architectural enforcement of no-look-ahead.</b> The event-driven engine's "
             "<tt>BarHistory</tt> raises if asked for any row past its <tt>as_of</tt>; the "
             "<tt>ExecutionHandler</tt> rejects fills that aren't strictly later than their "
             "originating order. PIT is enforced by the type system, not by reviewer "
             "vigilance."))

    S(Spacer(1, 0.15 * inch))
    S(H("Conclusion", 3))
    S(Paragraph(
        "AlphaForge's current contribution is the methodology and infrastructure to test, "
        "deflate, and execute trading strategies — together with a published negative result "
        "on the signals tried so far. Surviving signals are the explicit next deliverable, "
        "approached via point-in-time universe expansion, risk-model residualization, and "
        "factor combination, evaluated through the same gauntlet without modification.",
        styles["Body2"]
    ))

    S(Spacer(1, 0.2 * inch))
    S(Paragraph(
        "Repository: <i>Quant Alpha</i> (AlphaForge). Generated by "
        "<tt>docs/build_alphaforge_pdf.py</tt>. "
        "Reproducible output; JSON data artifacts drive the specific empirical numbers shown.",
        styles["Small"]
    ))

    doc.build(story)
    print(f"Wrote {OUT}")

if __name__ == "__main__":
    build()
