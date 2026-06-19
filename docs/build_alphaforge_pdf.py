"""Generate a polished, comprehensive PDF overview of the AlphaForge project.

Self-contained — uses reportlab and reads the local research artifacts under
each sub-project's research/ directory when present, falling back to prose
when JSON is unavailable.

This document reflects the project state as of 2026-05-22 (post-VIX +
substrate-#8 closures). Substrate count: 8 initiated, 7 CLOSED FAILED, 1 in
flight (microstructure Phase 0). See per-substrate verdict files for
machine-anchored evidence.
"""

from __future__ import annotations

import json
from pathlib import Path

from reportlab.lib.pagesizes import LETTER
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import inch
from reportlab.lib.colors import HexColor, black, white
from reportlab.lib.enums import TA_JUSTIFY, TA_LEFT, TA_CENTER
from reportlab.platypus import (
    SimpleDocTemplate, Paragraph, Spacer, PageBreak, Table, TableStyle,
    KeepTogether, ListFlowable, ListItem, HRFlowable,
)

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "docs" / "AlphaForge_Project_Overview.pdf"

# ---------- colour palette ----------
PRIMARY   = HexColor("#0b3a63")   # deep navy
ACCENT    = HexColor("#c76a00")   # burnt orange
ACCENT2   = HexColor("#1f6f8b")   # teal
MUTED     = HexColor("#555555")
SUBTLE    = HexColor("#888888")
WARN      = HexColor("#9a3324")   # closed-failed banner
OK        = HexColor("#1f7a3a")   # not used much
LIGHT     = HexColor("#f7f9fc")
LIGHTER   = HexColor("#eef3f9")
BORDER    = HexColor("#cccccc")

# ---------- styles ----------
styles = getSampleStyleSheet()
styles.add(ParagraphStyle(
    "TitleBig", parent=styles["Title"], fontSize=34, leading=40,
    textColor=PRIMARY, spaceAfter=6, fontName="Helvetica-Bold",
))
styles.add(ParagraphStyle(
    "TitleSub", parent=styles["BodyText"], fontSize=14, leading=20,
    textColor=ACCENT2, alignment=TA_LEFT, spaceAfter=12,
    fontName="Helvetica-Oblique",
))
styles.add(ParagraphStyle(
    "Subtitle", parent=styles["BodyText"], fontSize=12, leading=17,
    textColor=MUTED, alignment=TA_LEFT, spaceAfter=18,
))
styles.add(ParagraphStyle(
    "H1", parent=styles["Heading1"], fontSize=20, leading=26, spaceBefore=4,
    spaceAfter=12, textColor=PRIMARY, fontName="Helvetica-Bold",
))
styles.add(ParagraphStyle(
    "H2", parent=styles["Heading2"], fontSize=14, leading=18, spaceBefore=14,
    spaceAfter=6, textColor=PRIMARY, fontName="Helvetica-Bold",
))
styles.add(ParagraphStyle(
    "H3", parent=styles["Heading3"], fontSize=11.5, leading=15, spaceBefore=10,
    spaceAfter=3, textColor=ACCENT, fontName="Helvetica-Bold",
))
styles.add(ParagraphStyle(
    "H4", parent=styles["Heading4"], fontSize=10.5, leading=14, spaceBefore=6,
    spaceAfter=2, textColor=ACCENT2, fontName="Helvetica-Bold",
))
styles.add(ParagraphStyle(
    "Body", parent=styles["BodyText"], fontSize=10.2, leading=14.5,
    alignment=TA_JUSTIFY, spaceAfter=6,
))
styles.add(ParagraphStyle(
    "BodyLeft", parent=styles["BodyText"], fontSize=10.2, leading=14.5,
    alignment=TA_LEFT, spaceAfter=6,
))
styles.add(ParagraphStyle(
    "AFBullet", parent=styles["BodyText"], fontSize=10.2, leading=14,
    leftIndent=18, bulletIndent=6, spaceAfter=3,
))
styles.add(ParagraphStyle(
    "AFBulletTight", parent=styles["BodyText"], fontSize=10.0, leading=13,
    leftIndent=18, bulletIndent=6, spaceAfter=1,
))
styles.add(ParagraphStyle(
    "Small", parent=styles["BodyText"], fontSize=8.8, leading=11.6,
    textColor=MUTED,
))
styles.add(ParagraphStyle(
    "Quote", parent=styles["BodyText"], fontSize=10.2, leading=14.5,
    leftIndent=18, rightIndent=18, textColor=MUTED,
    fontName="Helvetica-Oblique", spaceBefore=4, spaceAfter=6,
))
styles.add(ParagraphStyle(
    "StatusBanner", parent=styles["BodyText"], fontSize=10.5, leading=15,
    textColor=WARN, fontName="Helvetica-Bold", spaceAfter=10,
))
styles.add(ParagraphStyle(
    "Caption", parent=styles["BodyText"], fontSize=9, leading=12,
    textColor=SUBTLE, alignment=TA_LEFT, spaceAfter=10,
))
styles.add(ParagraphStyle(
    "PullQuote", parent=styles["BodyText"], fontSize=11.5, leading=16,
    leftIndent=22, rightIndent=22, textColor=PRIMARY,
    fontName="Helvetica-Oblique", spaceBefore=8, spaceAfter=10,
))


# ---------- helpers ----------
def P(text, style="Body"):
    return Paragraph(text, styles[style])


def H(text, level=2):
    return Paragraph(text, styles[f"H{level}"])


def bullet(text, tight=False):
    style = "AFBulletTight" if tight else "AFBullet"
    return Paragraph(f"&bull; {text}", styles[style])


def hr(color=BORDER, thick=0.5):
    return HRFlowable(width="100%", thickness=thick, color=color,
                      spaceBefore=4, spaceAfter=6)


def kv_table(rows, col_widths=None, header=True, align_first_left=True,
             zebra=True, font_size=9.5):
    tbl = Table(rows, colWidths=col_widths, repeatRows=1 if header else 0)
    style = [
        ("FONTSIZE", (0, 0), (-1, -1), font_size),
        ("BOTTOMPADDING", (0, 0), (-1, 0), 6),
        ("TOPPADDING", (0, 0), (-1, 0), 6),
        ("BOTTOMPADDING", (0, 1), (-1, -1), 4),
        ("TOPPADDING", (0, 1), (-1, -1), 4),
        ("GRID", (0, 0), (-1, -1), 0.25, BORDER),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
    ]
    if header:
        style += [
            ("BACKGROUND", (0, 0), (-1, 0), PRIMARY),
            ("TEXTCOLOR", (0, 0), (-1, 0), white),
            ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ]
    if zebra:
        style.append(("ROWBACKGROUNDS", (0, 1), (-1, -1), [LIGHT, white]))
    if align_first_left:
        style.append(("ALIGN", (0, 0), (0, -1), "LEFT"))
        style.append(("ALIGN", (1, 0), (-1, -1), "LEFT"))
    tbl.setStyle(TableStyle(style))
    return tbl


def metric_block(metrics):
    """metrics: list of (label, value, sublabel) tuples — render as a row of cards."""
    cells = []
    for label, value, sub in metrics:
        cell = Table(
            [
                [Paragraph(f"<font size=8 color='#666'>{label}</font>", styles["Body"])],
                [Paragraph(f"<font size=16 color='#0b3a63'><b>{value}</b></font>", styles["Body"])],
                [Paragraph(f"<font size=7.5 color='#888'>{sub}</font>", styles["Body"])],
            ],
            colWidths=[1.65 * inch],
        )
        cell.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, -1), LIGHT),
            ("BOX", (0, 0), (-1, -1), 0.3, BORDER),
            ("LEFTPADDING", (0, 0), (-1, -1), 8),
            ("RIGHTPADDING", (0, 0), (-1, -1), 8),
            ("TOPPADDING", (0, 0), (-1, -1), 6),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ]))
        cells.append(cell)
    grid = Table([cells], colWidths=[1.7 * inch] * len(cells))
    grid.setStyle(TableStyle([
        ("LEFTPADDING", (0, 0), (-1, -1), 0),
        ("RIGHTPADDING", (0, 0), (-1, -1), 0),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
    ]))
    return grid


def _load_optional_json(path: Path):
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text())
    except Exception:
        return None


# ---------- page decorations ----------
def _draw_footer(canvas, doc):
    canvas.saveState()
    canvas.setFont("Helvetica", 8)
    canvas.setFillColor(SUBTLE)
    page_num = canvas.getPageNumber()
    width, _ = LETTER
    canvas.drawCentredString(width / 2, 0.4 * inch,
                             f"AlphaForge — Project Overview  |  {page_num}")
    canvas.drawRightString(width - 0.6 * inch, 0.4 * inch,
                           "Atharva Patil  |  2026-05-22")
    canvas.setStrokeColor(BORDER)
    canvas.setLineWidth(0.3)
    canvas.line(0.6 * inch, 0.6 * inch, width - 0.6 * inch, 0.6 * inch)
    canvas.restoreState()


def _draw_title_page(canvas, doc):
    canvas.saveState()
    width, height = LETTER
    canvas.setFillColor(PRIMARY)
    canvas.rect(0, height - 1.4 * inch, width, 1.4 * inch, fill=1, stroke=0)
    canvas.setFillColor(ACCENT)
    canvas.rect(0, height - 1.45 * inch, width, 0.05 * inch, fill=1, stroke=0)
    canvas.restoreState()
    _draw_footer(canvas, doc)


# ---------- build ----------
def build():
    doc = SimpleDocTemplate(
        str(OUT), pagesize=LETTER,
        leftMargin=0.85 * inch, rightMargin=0.85 * inch,
        topMargin=0.9 * inch, bottomMargin=0.85 * inch,
        title="AlphaForge — Project Overview",
        author="Atharva Patil",
        subject="Quantitative research stack — architecture, methodology, and substrate verdicts",
    )
    story = []
    S = story.append

    # ============================================================
    # TITLE PAGE
    # ============================================================
    S(Spacer(1, 0.1 * inch))
    S(Paragraph("AlphaForge", styles["TitleBig"]))
    S(Paragraph(
        "An End-to-End Quantitative Research and Execution Stack",
        styles["TitleSub"]
    ))
    S(Paragraph(
        "Point-in-time event-driven backtesting, deflation-aware statistical "
        "evaluation, evolutionary multi-agent reinforcement learning, and live "
        "paper-trading execution — applied across ten pre-committed substrates "
        "spanning US equities, crypto perpetual futures, BTC microstructure, "
        "EDGAR-driven post-earnings drift, NSE event-driven flow, CBOE "
        "variance-risk-premium harvest, SPY iron-condor options, and Kalshi "
        "prediction markets.",
        styles["Subtitle"]
    ))

    S(Paragraph(
        "<b>Status (2026-06-19):</b> Eight substrate evaluations have CLOSED FAILED "
        "under the project's pre-committed gauntlet. Substrate #10 (Kalshi "
        "favorite-longshot bias) is Phase-1 INCONCLUSIVE (underpowered on free "
        "data) and is now accumulating a live forward paper-trade record; "
        "substrate #4 (BTC-USDT microstructure) is re-collecting Phase 0 book "
        "data after a stale-collector break. The June 2026 work added a canonical, "
        "version-pinned evaluation gauntlet (<tt>afgauntlet</tt>) and a power "
        "calibration that measures the gauntlet's own minimum detectable effect "
        "(MDE@80% &asymp; 2.4 annualized Sharpe at 28 trials over 5-year windows) "
        "&mdash; separating &lsquo;no alpha&rsquo; from &lsquo;instrument too "
        "blunt&rsquo;. The methodology has rejected every signal that does not "
        "survive honest deflation, including one with statistically significant raw "
        "alpha (MV-21 OOS Sharpe +3.06 / +2.43) and one with a clear underlying "
        "variance-risk-premium IC of +0.180.",
        styles["StatusBanner"]
    ))

    S(Spacer(1, 0.10 * inch))
    S(metric_block([
        ("SUBSTRATES INITIATED", "10", "across 6 asset classes"),
        ("CLOSED FAILED", "8", "under DSR-deflated gates"),
        ("OPEN", "2", "#4 recollecting · #10 forward"),
        ("TESTS GREEN", "1,000+", "across 11 sub-projects"),
    ]))
    S(Spacer(1, 0.12 * inch))
    S(metric_block([
        ("CROSS-SECTIONAL FACTORS", "9", "5 JS-parity + 4 Python-only"),
        ("PIT EVENT LOG", "837", "S&P 500 membership changes"),
        ("PARQUET COVERAGE", "16y", "equity OHLCV, daily"),
        ("INDIA SUBSTRATE", "7.76M", "NSE rows, 2004–2026"),
    ]))

    S(Spacer(1, 0.20 * inch))
    S(hr(PRIMARY, 0.8))
    S(P("<b>Author:</b> Atharva Patil &nbsp;&nbsp;&middot;&nbsp;&nbsp; "
        "<b>Repository:</b> <i>Quant Alpha</i> &nbsp;&nbsp;&middot;&nbsp;&nbsp; "
        "<b>Generated:</b> 2026-06-19 &nbsp;&nbsp;&middot;&nbsp;&nbsp; "
        "<b>Build:</b> <tt>docs/build_alphaforge_pdf.py</tt>", style="Caption"))
    S(hr(PRIMARY, 0.8))

    S(Spacer(1, 0.20 * inch))
    S(H("Abstract", 3))
    S(P(
        "AlphaForge applies the full systematic-trading lifecycle &mdash; data "
        "ingestion, factor construction, point-in-time event-driven backtesting, "
        "transaction-cost modelling, deflation-aware statistical evaluation, "
        "multi-agent reinforcement learning, and live paper-trading execution "
        "&mdash; to a series of pre-committed substrates of increasing methodological "
        "distinctness. Across <b>ten initiated substrates</b> (US equities Tier 1 "
        "+ Tier 2, Binance USDT-M crypto carry, BTC-USDT microstructure, EDGAR "
        "XBRL post-earnings drift, NSE event-driven flow, CBOE variance-risk "
        "premium, a follow-up VIX-baseline-anchored sizing study, SPY iron-condor "
        "options, and Kalshi prediction-market favorite-longshot bias), <b>eight "
        "have CLOSED FAILED</b> under the same five-to-six gate gauntlet: "
        "Deflated Sharpe &gt; 0.95, stationary-bootstrap 95% CI excludes zero, "
        "out-of-sample sign agreement, cost-doubling survival, regime-stress "
        "stability, and (for premium-harvest substrates) Cornish-Fisher Sharpe &gt; 0.5 "
        "with max-drawdown limit per stress period. Substrate #10 is Phase-1 "
        "INCONCLUSIVE (underpowered on free data) and is accumulating a live forward "
        "paper-trade record; substrate #4 is re-collecting Phase 0 data. The June "
        "2026 work consolidated the per-substrate statistics into one canonical, "
        "version-pinned gauntlet (<tt>afgauntlet</tt>, with binary/calibration "
        "extensions for prediction markets), added a power calibration that measures "
        "the gauntlet's own minimum detectable effect, and reconciled assumed vs "
        "realized transaction costs from live fills. "
        "The project's contribution is the methodology and infrastructure that "
        "produced these honest negative results: a research-grade stack that "
        "refuses to deploy capital against signals which do not survive multiple-"
        "testing deflation, no-look-ahead enforced by the type system "
        "(<tt>BarHistory</tt> raises if queried past <tt>as_of</tt>), per-fill "
        "cash-accounted commission and slippage, and a kill-switch-driven live "
        "execution loop currently halted by configuration.",
        style="Body"
    ))
    S(PageBreak())

    # ============================================================
    # TABLE OF CONTENTS
    # ============================================================
    S(H("Contents", 1))
    toc_rows = [
        ["§", "Section"],
        ["1",  "Executive Summary"],
        ["2",  "Project Architecture — Eleven Components"],
        ["3",  "Data Infrastructure — PIT Universes and Parquet Stores"],
        ["4",  "Alpha Engine — Factors, Scoring, and Event-Driven Backtest"],
        ["5",  "Statistical Methodology — The Gauntlet"],
        ["6",  "Transaction-Cost Modelling — Honest Frictions"],
        ["7",  "MARL Framework — Neuroevolution + PPO + MAML"],
        ["8",  "Live Execution — Daily Loop, Risk, and Kill Switch"],
        ["9",  "JavaScript Frontend — Parity-Tested Terminal UI"],
        ["10", "Substrate #1–2 — US Equity Tier 1 and Tier 2 (CLOSED FAILED)"],
        ["11", "Substrate #3 — Crypto USDT-M Carry (CLOSED FAILED)"],
        ["12", "Substrate #4 — BTC-USDT Microstructure (IN FLIGHT)"],
        ["13", "Substrate #5 — PEAD via EDGAR XBRL (CLOSED FAILED)"],
        ["14", "Substrate #6 — NSE Event-Driven + Flow (CLOSED FAILED)"],
        ["15", "Substrate #7 — CBOE Variance-Risk Premium (CLOSED FAILED)"],
        ["16", "Substrate #8 — VIX-Baseline-Anchored Sizing (CLOSED FAILED)"],
        ["17", "Failure-Mode Taxonomy — What the Verdicts Mean Together"],
        ["18", "Engineering Highlights — Tests, Parity, CI, Reproducibility"],
        ["19", "Honest Limitations and Process Disclosures"],
        ["20", "June 2026 Update — Substrates #9–#10, Gauntlet + MDE"],
        ["21", "Forward Path — The Strategy-Class Decision Window"],
    ]
    S(kv_table(toc_rows, col_widths=[0.5 * inch, 5.7 * inch], font_size=10))
    S(PageBreak())

    # ============================================================
    # 1. EXECUTIVE SUMMARY
    # ============================================================
    S(H("1. Executive Summary", 1))
    S(P(
        "<b>Headline.</b> AlphaForge is a working end-to-end systematic-trading "
        "research stack — not a single strategy. It has been used to evaluate "
        "ten pre-committed substrates against the same rigorous gauntlet; "
        "eight have CLOSED FAILED, substrate #10 (Kalshi favorite-longshot bias) "
        "is Phase-1 inconclusive and accumulating a live forward record, and "
        "substrate #4 (microstructure) is re-collecting Phase 0 book data. The "
        "infrastructure has detected and rejected signals that would pass "
        "naive statistical bars: the closest near-miss (a Markowitz overlay "
        "on nine factor return streams) produced alpha-residual OOS Sharpe "
        "<b>+3.06 / +2.43</b> with HC0 t-statistics 4.33 / 3.43 and FF5+UMD R&sup2; "
        "16% / 8% — statistically significant under any conventional bar, "
        "but failing the Deflated Sharpe hurdle (0.92 / 0.70 vs 0.95) once "
        "honestly penalised against the 24-trial search space."
    ))
    S(P(
        "<b>What the project does.</b> Eight things, all working: "
        "(1) constructs a true point-in-time S&amp;P 500 membership graph from "
        "Wikipedia revisions + EDGAR CIK enrichment, 837 events across "
        "2010–2026; (2) loads aligned OHLCV from a local Parquet store, "
        "16 years of daily history for 655 of 881 ever-member tickers; "
        "(3) computes nine cross-sectional alpha factors, four pre-committed "
        "linear combinations, and a Markowitz mean-variance overlay; "
        "(4) runs all signals through an event-driven backtest engine that "
        "architecturally enforces no-look-ahead (<tt>BarHistory</tt> raises "
        "past <tt>as_of</tt>), next-bar fills (<tt>ExecutionHandler</tt> "
        "rejects same-bar fills), and per-fill cash-accounted costs; "
        "(5) applies the statistical gauntlet (DSR, SPA, Reality Check, "
        "purged-embargoed K-fold, stationary bootstrap, FF5+UMD post-portfolio "
        "alpha residualisation) to every variant; (6) trains a multi-agent "
        "RL ensemble (NSGA-II + PPO + FOMAML + HMM regime bandit) on the "
        "same substrate and audits it against the same gauntlet; "
        "(7) operates a daily live-trading loop against Alpaca paper with "
        "a six-trigger kill-switch and three-stage unwind ladder; and "
        "(8) extends every layer to four further substrates (crypto, "
        "microstructure, PEAD, India, VIX) each with their own "
        "SHA-256-anchored pre-commit contract."
    ))
    S(P(
        "<b>What the project demonstrates.</b> That a methodologically honest "
        "research process can produce credible <i>negative</i> verdicts at "
        "scale, and that the absence of surviving signals is itself a "
        "scientifically informative outcome. Across ten substrates, six "
        "asset classes, and two strategy classes (predictive cross-sectional "
        "alpha and structural premium harvest), no construction within the "
        "tested parameter space &mdash; using free public data, parametric "
        "retail-grade cost models, and DSR deflation against pre-committed "
        "trial counts &mdash; produces a deployable signal. The methodology "
        "did its job; the data and constraint set did theirs."
    ))

    S(H("At-a-Glance Substrate Ledger", 3))
    ledger = [
        ["#", "Substrate", "Asset class", "Strategy class", "Outcome", "Date"],
        ["1", "Equity Tier 1",                 "US large-cap",   "X-section factor",   "CLOSED FAILED", "2026-05-02"],
        ["2", "Equity Tier 2",                 "US large-cap",   "Lower-turnover X",   "CLOSED FAILED", "2026-05-02"],
        ["3", "Crypto USDT-M Carry",            "Crypto perp",    "X-section funding",  "CLOSED FAILED", "2026-05-15"],
        ["4", "BTC-USDT Microstructure",        "Crypto spot L2", "Order-flow",         "PHASE 0 (recollect)", "in flight"],
        ["5", "PEAD via EDGAR XBRL",            "US large-cap",   "Event-driven",       "CLOSED FAILED", "2026-05-17"],
        ["6", "NSE Event-Driven + Flow",        "Indian equity",  "Flow / delivery %",  "CLOSED FAILED", "2026-05-20"],
        ["7", "CBOE VIX/VRP harvest",           "US vol",         "Premium harvest",    "CLOSED FAILED", "2026-05-21"],
        ["8", "VIX-baseline-anchored sizing",   "US vol",         "Premium harvest",    "CLOSED FAILED", "2026-05-21"],
        ["9", "SPY Iron-Condor Options",        "US options",     "Premium harvest",    "CLOSED FAILED", "2026-05-26"],
        ["10", "Kalshi Favorite-Longshot",      "Prediction mkt", "Calibration / FLB",  "PH1 INCONCL.",  "2026-06-17"],
    ]
    S(kv_table(
        ledger,
        col_widths=[0.32 * inch, 1.62 * inch, 1.0 * inch, 1.22 * inch, 1.36 * inch, 0.82 * inch],
        font_size=9,
    ))

    S(H("Platform Metrics", 3))
    S(bullet("<b>11 sub-projects.</b> JS frontend, <tt>alphaforge-python</tt>, "
             "<tt>-marl</tt>, <tt>-execution</tt>, <tt>-crypto</tt>, "
             "<tt>-microstructure</tt>, <tt>-pead</tt>, <tt>-india</tt>, "
             "<tt>-vix</tt>, <tt>-options</tt>, <tt>-prediction</tt>, plus the shared "
             "<tt>alphaforge-gauntlet</tt> evaluation package. Each has its own "
             "CLAUDE.md, test suite, and SHA-256-anchored design contract."))
    S(bullet("<b>1,000+ tests green.</b> incl. 531 <tt>alphaforge-python</tt>, "
             "237 <tt>-vix</tt>, 371 <tt>-india</tt>, 157 <tt>-prediction</tt>, "
             "86 <tt>alphaforge-gauntlet</tt>, plus -marl / -execution / -crypto / "
             "-pead / -microstructure / -options suites."))
    S(bullet("<b>837 PIT membership events.</b> 407 REMOVE + 352 ADD + 78 RENAME, "
             "built from 2,811 Wikipedia revisions + EDGAR CIK enrichment, "
             "validated to 0.9895 monthly correlation against <tt>^SP500EW</tt>."))
    S(bullet("<b>16 years of equity OHLCV</b> in <tt>data/quarantine/market/</tt>, "
             "655 of 881 PIT ever-members on disk; 5 years of Binance USDT-M "
             "funding + OHLCV; 7.76M NSE bhavcopy rows (2004–2026, 5,527 dates) "
             "with 100% delivery-percentage coverage on Nifty-500 ever-members."))
    S(bullet("<b>Architectural no-look-ahead enforcement.</b> <tt>BarHistory</tt> "
             "raises if asked for any row past its <tt>as_of</tt>; "
             "<tt>ExecutionHandler</tt> rejects fills whose timestamp is not "
             "strictly later than the originating order. PIT enforced by the "
             "type system, not by reviewer vigilance."))
    S(bullet("<b>End-to-end reproducibility.</b> <tt>make all</tt> rebuilds every "
             "headline research artefact (factor study, capacity study, MARL "
             "rigor, ablation ladder) from the Parquet store in ~5 minutes. "
             "GitHub Actions diffs rebuilt JSON against committed artefacts to "
             "catch silent numerical drift."))

    S(PageBreak())

    # ============================================================
    # 2. ARCHITECTURE
    # ============================================================
    S(H("2. Project Architecture — Eleven Components", 1))
    S(P(
        "AlphaForge is organised as eleven loosely-coupled sub-projects plus the "
        "shared <tt>alphaforge-gauntlet</tt> evaluation package. The equity "
        "factor / RL / execution surfaces are frozen; eight substrate sub-projects "
        "are CLOSED FAILED audit trails; <tt>-prediction</tt> (#10) is accumulating "
        "a live forward paper-trade record and <tt>-microstructure</tt> (#4) is "
        "re-collecting Phase 0 book data. The JS frontend remains parity-tested "
        "and connected to the Python data layer."
    ))
    arch_rows = [
        ["Component", "Status", "Role"],
        ["JavaScript Frontend",            "MAINTAINED",  "Vanilla-JS single-page terminal UI; PRNG / factor / backtest numerical parity to Python."],
        ["alphaforge-python",              "FROZEN (research) / READ-ONLY (data)", "Equity factor engine, event-driven backtester, optimizer, statistical hygiene library, FastAPI."],
        ["alphaforge-marl",                "FROZEN",      "Neuroevolution + PPO + FOMAML population, HMM regime bandit, walk-forward validator."],
        ["alphaforge-execution",           "HALTED",      "Daily Alpaca paper-trading loop; <tt>.halt</tt> engaged; six-trigger kill-switch enforces unwind."],
        ["alphaforge-crypto",              "CLOSED",      "Binance USDT-M carry research (CLOSED FAILED 2026-05-15); basis-study stub not auto-activated."],
        ["alphaforge-microstructure",      "ACTIVE",      "Phase 0: BTC-USDT L2 + tape book-data accumulation; Phase 1–3 contracts pre-committed."],
        ["alphaforge-pead",                "CLOSED",      "EDGAR XBRL post-earnings drift on PIT equity substrate; 0/10 trials cleared (2026-05-17)."],
        ["alphaforge-india",               "CLOSED",      "NSE bhavcopy + delivery-% + F&O expiry; 0/18 trials cleared, universal OOS sign inversion (2026-05-20)."],
        ["alphaforge-vix",                 "CLOSED",      "CBOE VIX/term-structure + SPY realized vol + ETPs; 0/28 in both substrates #7 and #8 (2026-05-21)."],
    ]
    S(kv_table(arch_rows, col_widths=[1.55 * inch, 1.45 * inch, 3.3 * inch], font_size=9))

    S(H("Inter-component contracts", 3))
    S(bullet("<b>Equity stack.</b> <tt>alphaforge-marl/env/trading_env.py</tt> "
             "dynamically adds <tt>alphaforge-python/</tt> to <tt>sys.path</tt> "
             "and consumes the same parquet store and PIT validator. The two "
             "sub-projects share zero in-process state but are version-locked."))
    S(bullet("<b>Execution stack.</b> <tt>alphaforge-execution</tt> consumes "
             "the parquet store read-only and writes orders, snapshots, and "
             "signals to SQLite. The kill-switch reads its config from "
             "<tt>execution_config.yaml</tt> and writes pager events to a "
             "human-acknowledgeable file."))
    S(bullet("<b>Substrate isolation.</b> India, microstructure, PEAD, VIX, "
             "and crypto each maintain their own data flow and never touch "
             "<tt>data/quarantine/market/</tt>. This is a hard architectural "
             "constraint: a failed substrate cannot contaminate the next one."))
    S(bullet("<b>SHA-256 anchored design contracts.</b> Every substrate writes "
             "its design contract before any data is looked at; the runner "
             "refuses to execute if the file's SHA mismatches. Substrate #7 "
             "anchored on SHA <tt>54e53be9...</tt>, #8 on <tt>2194b7b2...</tt>, "
             "India on <tt>3b397262...</tt>."))

    # ============================================================
    # 3. DATA INFRASTRUCTURE
    # ============================================================
    S(H("3. Data Infrastructure — PIT Universes and Parquet Stores", 1))
    S(P(
        "Every substrate is anchored on a local, version-controlled, "
        "network-isolated dataset. Only a small number of explicitly named "
        "scripts touch the network (one yfinance puller, one Wikipedia revision "
        "walker, one Binance public REST/WebSocket client, one NSE archive "
        "fetcher, one EDGAR Company Facts client, one CBOE/Stooq downloader). "
        "Everything downstream reads from the resulting Parquet files; training, "
        "research, and execution all run offline."
    ))

    S(H("Point-in-Time S&P 500 universe", 3))
    S(P(
        "The <tt>data/market/pit/</tt> module rebuilds membership history end-to-"
        "end from public sources. It enumerates 2,811 Wikipedia revisions of the "
        "S&amp;P 500 constituents article, applies a hybrid byte-delta plus "
        "comment-keyword filter to select 837 substantive change-events, and "
        "resolves each event through SEC EDGAR's CIK directory with a custom "
        "<tt>.&harr;-</tt> share-class normaliser. The differ enforces action-"
        "precedence (REMOVE before ADD on the same date) and runs a suspect-"
        "pair guard against same-CIK ADD/REMOVE collisions."
    ))
    pit_rows = [
        ["Component",                          "Description"],
        ["enumerate_revisions.py",             "Wikipedia revision-walker; byte-delta + comment-keyword filter; 2,811 → 837 substantive events."],
        ["fetch_content.py",                   "Batched-50 wikitext fetcher with retries and content-hash caching."],
        ["parser.py",                          "Multi-format constituents-table parser; caption / ref-tag / header-shift defences."],
        ["cik.py",                             "EDGAR ticker→CIK resolver; share-class punctuation normalisation."],
        ["differ.py",                          "CIK-based ADD/REMOVE/RENAME differ; action-precedence + suspect-pair guard."],
        ["changes_parser.py",                  "Parses Wikipedia's curated 'Selected changes' table for cross-check (84% agreement)."],
        ["validator.py",                       "Canonical <tt>membership_on_date(events, baseline, date)→set[ticker]</tt> accessor."],
        ["history.py",                         "Membership-aware panels over <tt>data/quarantine/market/</tt>."],
        ["sector_map.py",                      "Static ever-member ticker→sector map for sector-neutral factor studies."],
    ]
    S(kv_table(pit_rows, col_widths=[1.6 * inch, 4.55 * inch], font_size=9))
    S(Spacer(1, 0.04 * inch))
    S(P(
        "<b>Outputs.</b> <tt>_event_log.parquet</tt> (837 rows), "
        "<tt>_baseline_2010-01-10.parquet</tt> (500 tickers, revision "
        "<tt>339455897</tt>), per-session audit JSONs. A 12-fixture regression "
        "test (<tt>test_pit_universe_fixture.py</tt>) gates the construction "
        "against hand-verified spot checks. Membership is reconciled to "
        "0.9895 monthly return correlation against the published "
        "<tt>^SP500EW</tt> equal-weight index."
    ))
    S(P(
        "<b>Coverage gap (disclosed in every metric).</b> 226 of 881 PIT "
        "ever-member tickers have no yfinance OHLCV — mostly delisted, "
        "restructured, or pre-IPO at the request date. Every downstream "
        "metric reports this as a known limitation; CRSP-grade data would "
        "close the gap but is outside the founder-path budget."
    ))

    S(H("Per-substrate data flow", 3))
    flow_rows = [
        ["Substrate", "Source", "Egress",                                                                 "Materialisation"],
        ["Equity (#1–2 + PEAD)", "yfinance",   "<tt>data/quarantine/market/&lt;TICKER&gt;/&lt;YEAR&gt;.parquet</tt>",     "Per-ticker per-year Parquet, 655 tickers."],
        ["Wikipedia",                "Wikipedia revisions API", "<tt>data/market/pit/_event_log.parquet</tt>",                 "Append-only event log + sessioned audits."],
        ["Crypto carry",             "Binance public REST",     "<tt>alphaforge-crypto/data/binance/</tt>",                    "Funding + 1m + 1d OHLCV for top-25 perps."],
        ["Microstructure",           "Binance WS + REST",       "<tt>alphaforge-microstructure/data/</tt>",                    "100 ms book snapshots + per-trade tape (accumulating)."],
        ["PEAD",                     "SEC EDGAR Company Facts", "<tt>alphaforge-pead/data/edgar/</tt>",                        "XBRL fact tables joined to PIT equity panel."],
        ["India",                    "NSE archives",            "<tt>alphaforge-india/data/</tt>",                              "7.76M bhavcopy rows + MTO delivery + F&O expiry."],
        ["VIX/VRP",                  "CBOE + Stooq + yfinance", "<tt>alphaforge-vix/data/</tt>",                                "VIX, VIX9D, VIX3M, VIX6M, SPY OHLCV, SVXY/VXX."],
    ]
    S(kv_table(flow_rows, col_widths=[1.45 * inch, 1.6 * inch, 2.1 * inch, 1.55 * inch], font_size=8.6))

    S(PageBreak())

    # ============================================================
    # 4. ALPHA ENGINE
    # ============================================================
    S(H("4. Alpha Engine — Factors, Scoring, and Event-Driven Backtest", 1))

    S(H("Factor library (nine cross-sectional signals)", 3))
    factor_rows = [
        ["Factor",                       "Construction"],
        ["Momentum (12-1)",              "Trailing 12-month total return, skipping the most recent month (Jegadeesh-Titman 1993)."],
        ["Mean Reversion (5d)",          "Negated 5-day return."],
        ["Volume Surge",                 "Short-term volume MA divided by long-term volume MA."],
        ["RSI Divergence",               "Standard 14-day Relative Strength Index minus 50."],
        ["Earnings Drift",               "Post-earnings drift proxy (10-day return) — frontend parity factor."],
        ["Amihud Illiquidity",           "Absolute return divided by dollar volume (Amihud 2002)."],
        ["Idiosyncratic Volatility",     "Negated 60-day rolling residual vol vs equal-weight market (Ang-Hodrick-Xing-Zhang 2006)."],
        ["Residual Reversal (5d)",       "Negated 5-day sum of residuals against the equal-weight market."],
        ["Low Volatility",               "Negated annualised 60-day log-return standard deviation."],
    ]
    S(kv_table(factor_rows, col_widths=[1.9 * inch, 4.25 * inch], font_size=9))
    S(P(
        "Each factor implements <tt>BaseFactor.compute()</tt> (enhanced) and "
        "<tt>compute_js()</tt> (bit-for-bit parity with the JS frontend), "
        "registered through <tt>FACTOR_REGISTRY</tt>. Residual Reversal and "
        "Idiosyncratic Volatility additionally override <tt>compute_universe</tt> "
        "to compute the equal-weight market return once per call and reuse it "
        "across tickers, eliminating O(N) duplicated regressions."
    ))

    S(H("Cross-sectional scoring pipeline", 3))
    S(P(
        "<tt>factors/scoring.py</tt> implements the canonical cross-sectional "
        "z-score pipeline (<tt>compute_factor_scores_js</tt>) shared by the "
        "optimizer, the correlation/IC harness, the JS scanner, the MARL "
        "environment, and the execution-loop strategy. The function lives "
        "outside <tt>backtest/</tt> so callers can score factors without "
        "pulling in the engine module. Defensive numerics (<tt>safe_div</tt>, "
        "<tt>sanitize_number</tt>, <tt>clamp</tt>, <tt>validate_series</tt>) "
        "guarantee NaN / Inf cannot propagate."
    ))

    S(H("Linear combinations and Markowitz overlay", 3))
    S(bullet("<b>EWE.</b> Equal-weight ensemble of nine standardised factor "
             "scores."))
    S(bullet("<b>ICW.</b> IC-weighted ensemble, weights estimated on an "
             "expanding IS window with strict no-look-ahead."))
    S(bullet("<b>ICW-flip.</b> Sign-flipped ICW variant to demonstrate the "
             "directional dependence of the gauntlet result."))
    S(bullet("<b>MV.</b> Markowitz mean-variance overlay implemented in "
             "<tt>optimizer/</tt> using SciPy SLSQP, Ledoit-Wolf covariance "
             "shrinkage, and factor-score-blended expected returns. Modes: "
             "long-only, long-short, market-neutral. <i>MV-21 was the closest "
             "near-miss in Tier 1 — alpha-residual OOS Sharpe +3.06 / +2.43, "
             "killed by DSR deflation (0.92 / 0.70 vs 0.95).</i>"))

    S(H("Event-driven backtest engine", 3))
    S(P(
        "<tt>alphaforge-python/backtest/event_driven/</tt> implements an event-"
        "driven simulation engine that replaces the legacy vectorised panel "
        "engine retired in Phase 2 (the legacy <tt>real_engine.py</tt> was "
        "architecturally wrong: same-bar fills, daily clamp, flat post-hoc "
        "cost deduction). The current engine architecturally enforces:"
    ))
    S(bullet("<b>No-look-ahead.</b> <tt>BarHistory</tt> raises "
             "<tt>LookaheadError</tt> if asked for any row past its current "
             "<tt>as_of</tt> timestamp."))
    S(bullet("<b>No same-bar fills.</b> <tt>ExecutionHandler</tt> rejects any "
             "<tt>FillEvent</tt> whose fill timestamp is not strictly later "
             "than the originating <tt>OrderEvent</tt>."))
    S(bullet("<b>Per-fill cash-accounted costs.</b> Slippage (basis points or "
             "square-root impact) and commission are deducted on each "
             "<tt>FillEvent</tt>, not as a flat post-hoc bps reduction."))
    S(bullet("<b>Mark-to-market that fails loudly.</b> <tt>Portfolio</tt> "
             "raises if asked to mark a position whose price is missing."))
    S(P(
        "Components: <tt>events.py</tt> (Event hierarchy), "
        "<tt>data_handler.py</tt> (<tt>DataHandler</tt> + PIT <tt>BarHistory</tt>), "
        "<tt>strategy.py</tt> (<tt>Strategy</tt> ABC plus reference "
        "<tt>MomentumLongShort</tt> and <tt>PanelStrategy</tt> implementations), "
        "<tt>execution.py</tt> (<tt>ExecutionHandler</tt>, <tt>FlatSlippageModel</tt>, "
        "<tt>SameBarCloseExecutionHandler</tt>), <tt>portfolio.py</tt> (cash + "
        "positions + NAV), and <tt>core.py</tt> (<tt>EventDrivenEngine</tt>)."
    ))
    S(P(
        "<tt>backtest/synthetic_demo.py</tt> remains as the JS-parity demo "
        "surface and must stay bit-for-bit aligned with the frontend; "
        "<tt>backtest/event_driven_adapter.py</tt> bridges the legacy backtest "
        "API schema to the canonical event-driven engine for real-data API "
        "requests."
    ))
    S(PageBreak())

    # ============================================================
    # 5. STATISTICAL METHODOLOGY
    # ============================================================
    S(H("5. Statistical Methodology — The Gauntlet", 1))
    S(P(
        "The same statistical hygiene kernel is applied to every substrate "
        "before any verdict is filed. The components are pre-committed in "
        "each substrate's design contract; thresholds are frozen before "
        "the first data is looked at; SHA-256 hashes anchor the contract "
        "so the runner refuses to execute against a modified design."
    ))

    S(H("Core gates (pre-committed, SHA-anchored)", 3))
    gate_rows = [
        ["Gate", "Construction", "Threshold"],
        ["G1 — DSR",                  "Deflated Sharpe Ratio (Bailey &amp; López de Prado 2014), deflated against pre-committed trial count.", "&gt; 0.95"],
        ["G2 — Bootstrap CI",         "Stationary-bootstrap Sharpe CI (Politis-Romano 1994), 2,000–4,000 reps, 21-day mean block.",            "95% excludes 0"],
        ["G3 — Sign agreement",       "Out-of-sample window A and window B agree on sign.",                                                          "Same sign in both"],
        ["G4 — Cost-double survival", "Double the parametric cost model (commission + half-spread + impact) and re-run.",                            "Same Sharpe sign"],
        ["G5 — Regime stress",        "Run on 2008 crisis, 2013 taper tantrum, 2020 COVID, 2022 rate cycle.",                                        "4-of-4 positive months"],
        ["G6 — CF-Sharpe",            "Cornish-Fisher-adjusted Sharpe; sensitivity to higher moments (VRP only).",                                   "&gt; 0.5"],
    ]
    S(kv_table(gate_rows, col_widths=[1.4 * inch, 3.8 * inch, 1.0 * inch], font_size=9))

    S(H("Supporting statistical machinery", 3))
    S(bullet("<b>Hansen Superior Predictive Ability (SPA, 2005).</b> Tests "
             "the null that the best-in-sample trial has no edge over a "
             "benchmark, after multiple-testing correction. Reported on the "
             "full K&times;T net-return matrix per OOS window."))
    S(bullet("<b>White's Reality Check (2000).</b> Naive bootstrap variant, "
             "strictly more conservative than SPA — reported alongside as a "
             "sanity check on Hansen's p-values."))
    S(bullet("<b>Purged + Embargoed K-fold CV (López de Prado 2018).</b> "
             "K-fold cross-validation with overlap-purging and an embargo "
             "interval around each held-out fold to prevent label leakage."))
    S(bullet("<b>Stationary-bootstrap Sharpe CI (Politis-Romano 1994).</b> "
             "Block-bootstrap with random block length drawn from a geometric "
             "distribution to preserve serial dependence."))
    S(bullet("<b>Post-portfolio FF5+UMD alpha residualisation.</b> "
             "<tt>compute_portfolio_alpha</tt> runs each strategy's daily "
             "returns through a time-series regression on Mkt-RF, SMB, HML, "
             "RMW, CMA, UMD, with HC0 SEs on the intercept and bootstrap CI "
             "on the residual Sharpe."))
    S(bullet("<b>21-day embargo around every OOS boundary.</b> No training "
             "data within 21 trading days of an OOS window is permitted "
             "to influence the model for that window."))

    S(H("Pre-commit discipline", 3))
    S(P(
        "Every substrate writes a design contract before any data is "
        "examined and before any signal code is run. The contract specifies: "
        "the substrate window, the IS/OOS split, the embargo, the trial set "
        "(enumerated with parameter values), the gate thresholds, the cost "
        "model, the decision matrix for each outcome, and the hard rules "
        "for what is and is not permitted post-execution. The runner "
        "computes the contract's SHA-256 and refuses to execute if the "
        "anchor does not match."
    ))
    S(P(
        "<b>Override audit.</b> The pre-committed &sect;7 reset cooldown has "
        "been explicitly overridden four times — for crypto, PEAD, India, "
        "and VIX-as-constraint-shift. <b>All four overrides have closed "
        "FAILED.</b> The override discipline itself is now an audit-able fact "
        "of the project."
    ))
    S(PageBreak())

    # ============================================================
    # 6. COSTS
    # ============================================================
    S(H("6. Transaction-Cost Modelling — Honest Frictions", 1))
    S(P(
        "<tt>cost_model.py</tt> in each sub-project implements the explicit "
        "cost surface used by that substrate. The kernels and parameters "
        "are documented and frozen in each design contract; no post-hoc "
        "tuning is permitted once a verdict is being computed."
    ))

    S(H("Equity cost components", 3))
    S(bullet("<b>Commission:</b> 1 bp per side (parametric)."))
    S(bullet("<b>Half-spread:</b> 2 bps parametric, <i>or</i> Corwin-Schultz "
             "(High/Low based) estimator, documented as 7–8 bps median across "
             "windows. Tier 1 / Tier 2 used the parametric model with the "
             "Corwin-Schultz divergence disclosed."))
    S(bullet("<b>Linear impact:</b> 10 bps per unit turnover (quintile spread "
             "backtests)."))
    S(bullet("<b>Square-root impact (<tt>SquareRootImpactModel</tt>):</b> "
             "k&middot;&radic;participation; used in the capacity study and "
             "available to the event-driven engine."))
    S(bullet("<b>Borrow costs:</b> <tt>BorrowCostTable</tt> with annualised "
             "bps defaults and a Hard-to-Borrow override map. Currently "
             "populated with general-collateral defaults; non-mega-cap short "
             "leg materially under-estimated. Disclosed in &sect;19."))

    S(H("Crypto carry costs", 3))
    S(bullet("<b>Taker fee:</b> 4 bps per side (Binance default)."))
    S(bullet("<b>Half-spread:</b> 1 bp per side."))
    S(bullet("<b>Funding payments:</b> 8-hour funding-rate accrual per "
             "open position, honestly added/subtracted."))
    S(bullet("<b>Linear impact:</b> 5 bps per unit turnover."))
    S(P(
        "Carry study OOS realised turnover was <b>1701% annualised</b> vs "
        "an IS-implied gate at &lt;800%; the gate fired correctly and "
        "contributed to the CLOSED FAILED verdict."
    ))

    S(H("India cost surface", 3))
    S(bullet("STT (Securities Transaction Tax): 10 bps on sell side (delivery)."))
    S(bullet("Exchange + SEBI + stamp duty: ~2 bps per side."))
    S(bullet("Brokerage: 3 bps per side (parametric)."))
    S(bullet("Half-spread + impact: 5–10 bps per side (size-dependent)."))
    S(P("Total round-trip cost: ~35.9 bps + 10 bps impact at base; 2&times; "
        "stress (G4): 71.8 bps + 20 bps impact."))

    S(H("VIX/VRP execution costs", 3))
    S(bullet("ETP (SVXY/VXX) bid-ask: 5 bps per side."))
    S(bullet("ETP commission: 1 bp per side."))
    S(bullet("Carry on free cash: <b>zero</b> per &sect;17.8 ADDENDUM — the "
             "original &sect;6 carry assumed it applied to posted margin on "
             "VIX futures; &sect;17.2 removed futures from the implementation, "
             "and &sect;17.8 zeroed cash carry as a result. <i>The first Phase 3 "
             "run apparently passed 18/28 on cash carry; the zeroing produced "
             "0/28. The discipline caught its own false-pass.</i>"))

    S(PageBreak())

    # ============================================================
    # 7. MARL
    # ============================================================
    S(H("7. MARL Framework — Neuroevolution + PPO + MAML", 1))
    S(P(
        "<tt>alphaforge-marl</tt> trains a population of multi-agent "
        "reinforcement-learning policies and audits them under the same "
        "deflation-aware statistical gauntlet as the single-factor study. "
        "The framework is now FROZEN: the rigor report concluded that "
        "existing checkpoints have negative baseline-excess Sharpe (mean "
        "&minus;1.13) and learned beta to the equal-weight basket, not alpha. "
        "It is retained as infrastructure that could be redirected to support "
        "roles (execution, sizing, regime-routing) in a future Tier 3."
    ))

    S(H("Pipeline", 3))
    S(P(
        "<tt>TradingEnv &rarr; AgentPool &rarr; EvolutionaryEngine (NSGA-II + "
        "speciation + MAML) &rarr; RegimeBandit (HMM) &rarr; Ensemble</tt>"
    ))
    S(bullet("<b>TradingEnv.</b> Gymnasium env, 57-dim observation, "
             "5 discrete actions <i>or</i> 10-dim continuous weights. Dense "
             "reward shaping: rolling Sharpe delta + drawdown penalty + "
             "participation, plus Sharpe-based terminal reward. Curriculum "
             "scheduler ramps transaction costs, leverage, stops, and episode "
             "length. <tt>env/real_data.py</tt> sources aligned OHLCV from "
             "the shared parquet store — training never touches the network."))
    S(bullet("<b>Agents.</b> <tt>BaseAgent</tt> wraps an "
             "<tt>ActorCriticNetwork</tt> with multi-head attention over per-"
             "ticker features. Variants: <tt>ContinuousActorCritic</tt>, "
             "<tt>DQNHead</tt>, <tt>PPOTrainer</tt> (GAE + clipped surrogate), "
             "<tt>MAMLTrainer</tt> (FOMAML), <tt>EnsemblePolicy</tt>, "
             "<tt>ParetoFront</tt>, <tt>AgentPool</tt>."))
    S(bullet("<b>Evolution.</b> Per-generation: evaluate under common random "
             "numbers &rarr; PPO fine-tune &rarr; periodic MAML &rarr; NSGA-II "
             "select on (Sharpe, drawdown, turnover) &rarr; speciated "
             "reproduction (Jensen-Shannon distance) &rarr; per-parameter "
             "adaptive mutation."))
    S(bullet("<b>Regime bandit.</b> HMM regime detector (K-means init + "
             "Baum-Welch). Thompson sampling per (regime, agent) feeds a "
             "capital allocator."))
    S(bullet("<b>Walk-forward validator.</b> Anchored splits, strict temporal "
             "isolation, reports overfitting ratio and val/test correlation."))

    S(H("Rigor report", 3))
    S(P(
        "<tt>research/marl_rigor.py</tt> scans every <tt>training.jsonl</tt> "
        "and summary JSON in the MARL tree, enumerates the full trial count, "
        "and applies the same statistical hygiene as the single-factor study. "
        "Headline numbers:"
    ))
    rigor_rows = [
        ["Metric",                                            "Value"],
        ["Total generation-level trials enumerated",          "100"],
        ["OOS mean stability Sharpe (2 seeds, 251 days)",     "+0.72"],
        ["OOS stability DSR (deflated for 100 trials)",       "0.038"],
        ["Reward-mix trials beating equal-weight",            "0 / 60"],
        ["Mean baseline-excess Sharpe",                       "−1.13"],
        ["Best individual trial baseline-excess Sharpe",      "−0.669"],
    ]
    S(kv_table(rigor_rows, col_widths=[3.5 * inch, 1.5 * inch], font_size=9))
    S(P(
        "<b>Reading:</b> the agents learned beta to equal-weight, not alpha. "
        "Adding more training would not address the underlying problem. "
        "Detailed report: <tt>alphaforge-marl/research/out/marl_rigor_report.md</tt>; "
        "ablation ladder at <tt>research/ablation_ladder.py</tt>."
    ))

    S(PageBreak())

    # ============================================================
    # 8. LIVE EXECUTION
    # ============================================================
    S(H("8. Live Execution — Daily Loop, Risk, and Kill Switch", 1))
    S(P(
        "<tt>alphaforge-execution</tt> implements the daily Alpaca paper-"
        "trading loop. The loop is <b>currently halted</b>: <tt>.halt</tt> "
        "is engaged and <tt>run_daily.sh</tt> exits with <tt>HALTED</tt> on "
        "every cron fire. The 10 paper positions held across the momentum "
        "and MARL accounts were flattened on 2026-04-26. Re-launch requires "
        "the four conditions in <tt>docs/TIER1_PAUSE.md</tt>; with Tier 1 + "
        "Tier 2 closed failed, those conditions cannot be met from the "
        "current state."
    ))

    S(H("Daily loop", 3))
    S(P("Fetch prices &rarr; momentum ranking &rarr; pre-trade risk checks "
        "&rarr; order execution &rarr; snapshot recording &rarr; circuit "
        "breakers &rarr; kill-switch end-of-day evaluation."))
    S(bullet("<b>Brokers.</b> <tt>PaperBroker</tt> (local simulation with "
             "slippage), <tt>AlpacaBroker</tt> (paper-trading API)."))
    S(bullet("<b>Strategy.</b> <tt>strategy/momentum.py</tt> implements a "
             "composite of 5-day momentum (40%), 21-day momentum (40%), and "
             "mean reversion (20%); top-N equal-weight."))
    S(bullet("<b>Risk limits.</b> <tt>risk/limits.py</tt> enforces position "
             "size, total exposure, and turnover caps pre-trade."))
    S(bullet("<b>Storage.</b> SQLite (<tt>storage/</tt>) with auto-created "
             "<tt>orders</tt>, <tt>snapshots</tt>, and <tt>signals</tt> tables."))

    S(H("Kill switch (six triggers, three-stage unwind)", 3))
    S(P(
        "<tt>risk/kill_switch.py</tt> enforces the <tt>kill_switch:</tt> "
        "block in <tt>execution_config.yaml</tt>. <tt>KillSwitch.end_of_day()</tt> "
        "runs after every snapshot."
    ))
    triggers = [
        ["Trigger",                                  "Threshold (illustrative)"],
        ["Max drawdown",                             "&gt; 8% from peak NAV"],
        ["Single-day loss",                          "&gt; 2% NAV in one trading day"],
        ["Consecutive losing days",                  "&ge; 4 in a row"],
        ["Realised slippage median",                 "&gt; 15 bps over rolling 20 fills"],
        ["Realised cumulative fill-error drag",      "&gt; 50 bps cumulative NAV"],
        ["Minimum liquid ticker count",              "&lt; 8 tradeable names"],
    ]
    S(kv_table(triggers, col_widths=[2.4 * inch, 2.4 * inch], font_size=9))
    S(P(
        "<b>Unwind ladder:</b> 25% of current weights at halt, 50% at +4 "
        "hours, 100% by next close. Re-arm requires a human-acknowledged "
        "line starting with <tt>ACK:</tt> in the pager file. Full playbook: "
        "<tt>docs/kill_switch_playbook.md</tt>."
    ))

    S(H("Slippage reconciliation", 3))
    S(P(
        "<tt>research/slippage_reconciliation.py</tt> compares realised "
        "slippage in the live SQLite database against the backtest's "
        "assumed bps. Emits a distribution summary, a self-contained "
        "two-sample KS test (no scipy dependency), and cumulative NAV drag "
        "from fill error. Output: <tt>research/out/slippage_reconciliation."
        "md</tt> + JSON. Currently anchored on 7 lifetime fills (pre-halt); "
        "not enough for a load-bearing tracking-error number, but the "
        "infrastructure exists."
    ))

    S(PageBreak())

    # ============================================================
    # 9. JS FRONTEND
    # ============================================================
    S(H("9. JavaScript Frontend — Parity-Tested Terminal UI", 1))
    S(P(
        "The frontend is a vanilla-JS single-page application loaded via "
        "<tt>&lt;script&gt;</tt> tags — no build step, no transpiler, no "
        "package manager. Chart.js is vendored locally as <tt>chart.min.js</tt>. "
        "The Python backend mirrors every numerical primitive bit-for-bit; "
        "parity tests at the PRNG, factor-scoring, and backtest layers "
        "compare against <tt>tests/fixtures/js_reference_output.json</tt> "
        "to 10 decimal places."
    ))
    js_rows = [
        ["Module",        "Responsibility"],
        ["data.js",       "Mulberry32 seeded PRNG, synthetic price/volume generation, factor scoring, backtest engine (fallback)."],
        ["app.js",        "Tab switching, workspace controls, dispatches to modules; loads last and calls each module's <tt>init()</tt>."],
        ["scanner.js",    "Factor screening UI; cross-sectional ranking visualisation."],
        ["correlation.js","Factor correlation, IC, and turnover analysis with sortable tables."],
        ["ai-engine.js",  "Recommendations UI fed by the Python optimizer endpoint."],
        ["marl.js",       "MARL agent ensemble dashboard."],
        ["execution.js",  "Live-execution snapshot view."],
    ]
    S(kv_table(js_rows, col_widths=[1.2 * inch, 4.95 * inch], font_size=9))
    S(P(
        "<b>Communication.</b> Global state via <tt>AlphaApp.getState()</tt> "
        "&rarr; <tt>{ sector, lookback, activeTab }</tt>. The primary workflow "
        "hits the <tt>alphaforge-python</tt> FastAPI at <tt>:8000</tt> for "
        "real-market history from the local Parquet store; the seeded-PRNG "
        "synthetic path remains as an offline fallback. Five frontend "
        "factors (Momentum 12-1, Mean Reversion 5d, Volume Surge, RSI "
        "Divergence, Earnings Drift) are bit-for-bit identical to their "
        "Python counterparts."
    ))
    S(P(
        "<b>Defensive numerics.</b> The same primitive set used in Python "
        "(<tt>safeDiv</tt>, <tt>sanitizeNumber</tt>, <tt>clamp</tt>, "
        "<tt>validateSeries</tt>) is mirrored in the JS layer; NaN / Inf "
        "cannot propagate through the factor pipeline in either runtime."
    ))

    S(PageBreak())

    # ============================================================
    # 10. SUBSTRATES #1-#2
    # ============================================================
    S(H("10. Substrate #1–2 — US Equity Tier 1 and Tier 2 (CLOSED FAILED)", 1))

    S(H("Tier 1 — nine factors, four combinations, full PIT", 3))
    S(P(
        "Substrate window: 2,514 trading days (2016-01-04 through 2025-12-31) "
        "on the PIT S&amp;P 500 ever-member universe (476 of 877 ever-members "
        "with sufficient OHLCV coverage). IS: 2016-2021. OOS-A: 2022-2023. "
        "OOS-B: 2024-2025. 21-day embargo at each boundary."
    ))
    S(P(
        "<b>Trial set.</b> Nine single factors + four combinations (EWE, ICW, "
        "MV, ICW-flip) = 24 strategy-trials, deflated against this count under "
        "DSR."
    ))
    S(P(
        "<b>Verdict.</b> 0 of 9 single factors and 0 of 4 combinations cleared. "
        "The closest result was MV with alpha-residual OOS Sharpe "
        "<b>+3.06 / +2.43</b>, alpha t-stats 4.33 / 3.43 (HC0), FF5+UMD "
        "R&sup2; 16% / 8%, bootstrap p<sub>positive</sub> = 1.0 in both "
        "windows. Failed only on DSR (0.92 / 0.70 vs the pre-committed 0.95)."
    ))
    S(Paragraph(
        "\"Real signal eaten by costs and multiple-testing\" — row 2 of "
        "the failure-path matrix, committed as the diagnostic in "
        "<tt>PHASE6_WRITEUP.md</tt> &sect;4.",
        styles["PullQuote"]
    ))

    S(H("Tier 2 — lower-turnover diagnostic", 3))
    S(P(
        "Tier 2 was a pre-committed test of the row-2 hypothesis: if costs "
        "and multiple-testing were what killed MV-21, then a lower-turnover "
        "variant (rebalance every 63 or 126 days, with optional vol-cap and "
        "covariance-shrinkage variants) should preserve the alpha while "
        "saving costs."
    ))
    S(P(
        "<b>Trial set.</b> 8 strategies: MV-63, MV-126, MV-63-volcap, "
        "MV-126-volcap, MV-63-shrunk, MV-126-shrunk, MV-63-ext, MV-126-ext."
    ))
    S(P(
        "<b>Verdict.</b> 0 strategies cleared, 0 near-misses. <b>Lower "
        "turnover destroyed the alpha rather than preserving it.</b> MV-21's "
        "OOS-A alpha-residual Sharpe of +3.06 collapsed to +0.79 at 63-day "
        "rebalance and +0.95 at 126-day rebalance — the opposite of what "
        "the row-2 hypothesis predicted. The revised reading is that MV-21 "
        "is a 21-day-specific residualised mean-reversion artefact "
        "(Da-Liu-Schaumburg 2014), not a robust cross-sectional anomaly. "
        "Full writeup: <tt>TIER2_VERDICT.md</tt>."
    ))

    S(H("Methodology footnote — the residualisation bug", 3))
    S(P(
        "During Tier 2 a load-bearing wiring bug was discovered: "
        "<tt>prepare_analysis_returns()</tt> was returning raw returns "
        "regardless of the residualise flag, and "
        "<tt>compute_portfolio_alpha</tt> was not wired into the main "
        "gauntlet. The JSON metadata claimed "
        "<tt>analysis_returns_mode: residualized</tt> while the actual "
        "computation was on raw returns. Fixed in &lt;50 lines; gauntlet "
        "re-run; <i>verdict held but the documented diagnostic shifted</i>. "
        "Pre-fix outputs are preserved as <tt>*_residualized.json</tt> "
        "backups for full audit-ability."
    ))

    # ============================================================
    # 11. SUBSTRATE #3
    # ============================================================
    S(H("11. Substrate #3 — Crypto USDT-M Carry (CLOSED FAILED)", 1))
    S(P(
        "After the &sect;7 reset cooldown was overridden on 2026-05-15, "
        "the carry study was spun up on the top-25 Binance USDT-M perpetual "
        "futures by Average Dollar Volume (2021-2026). The signal: rank "
        "perpetuals by trailing K-period funding-rate accrual; long the "
        "lowest quintile, short the highest; rebalance at frequency K."
    ))
    S(P(
        "<b>Pre-commit anchors:</b> <tt>dbd77ad</tt> (design doc) and "
        "<tt>4277eba</tt> (trial log). 32 trials enumerated (including 14 "
        "considered-but-not-run alternatives, captured in the log). "
        "K<sub>primary</sub> = 63. OOS window: 2025-01-08 through 2026-05-14, "
        "1.35 years, 2,952 funding events."
    ))
    carry_gates = [
        ["Gate", "Threshold", "Realised", "Pass?"],
        ["G1 — Net annualised Sharpe",       "&gt; 0.5",      "+1.48",                          "&check;"],
        ["G2 — Bootstrap CI excludes 0",     "excludes 0",    "[-1.39, +4.33]",                 "&times;"],
        ["G3 — DSR",                         "&gt; 0.95",     "0.624 (N=32)",                   "&times;"],
        ["G4 — Annualised turnover",         "&lt; 800%",     "1701%",                          "&times;"],
        ["G5 — Sign agreement IS vs OOS",    "same sign",     "IS +3.55 / OOS +1.48",           "&check;"],
    ]
    S(kv_table(carry_gates, col_widths=[2.0 * inch, 1.25 * inch, 1.8 * inch, 0.6 * inch], font_size=9))
    S(P(
        "<b>Verdict.</b> 3 of 5 gates failed. The signal had genuine ex-ante "
        "predictive power (IC 0.46–0.59 stable across five purged CV folds at "
        "K=21 — an <i>order of magnitude</i> larger than equity factor ICs of "
        "0.02–0.05) but the OOS Sharpe of +1.48 sits below the DSR-implied "
        "minimum of ~1.6–1.8 estimated in design-doc &sect;11 ahead of time. "
        "<b>The signal is real; the deflation hurdle is what killed it.</b> "
        "Identical row-2 mechanism to equity Tier 1's MV-21 result."
    ))
    S(Paragraph(
        "\"The math worked. The cost economics were correctly diagnosed in "
        "advance. The strategy had real edge but not enough margin over the "
        "deflation penalty.\" — <tt>CARRY_STUDY_VERDICT.md</tt>",
        styles["PullQuote"]
    ))

    S(PageBreak())

    # ============================================================
    # 12. SUBSTRATE #4
    # ============================================================
    S(H("12. Substrate #4 — BTC-USDT Microstructure (IN FLIGHT)", 1))
    S(P(
        "Substrate #4 is the active research surface. Phase 0 began on "
        "2026-05-17: a live Binance public-WebSocket collector accumulates "
        "100 ms book snapshots and the per-trade tape for BTC-USDT to local "
        "disk. The earliest Phase 1 execution date is 2026-06-17 (&ge;30 days "
        "of book data required; 90 days preferred)."
    ))
    S(H("Phase 0 exit gates (must all be green)", 3))
    S(bullet("&ge;30 days of book data on disk."))
    S(bullet("<tt>validation/book_snapshot_check.py</tt> reports 0 diffs "
             "across 24 sample REST snapshots."))
    S(bullet("<tt>validation/temporal_alignment.py</tt> reports "
             "trade-vs-book violation rate &lt;0.01%."))
    S(bullet("<tt>validation/gap_detector.py</tt> reports gap fraction "
             "&lt;0.1%."))

    S(H("Phase 1 trial set (pre-committed, frozen)", 3))
    S(P(
        "<b>Phase 1a (standalone signals, 56 trials).</b> Two signal families "
        "evaluated at seven horizons:"
    ))
    micro_rows = [
        ["Family",                          "Parameter", "Values",                                  "Horizons"],
        ["Order Book Imbalance (OBI)",      "depth",     "1, 5, 10, 20",                            "1s, 5s, 30s, 60s, 5m, 15m, 1h"],
        ["Trade Flow Imbalance (TFI)",      "window",    "10s, 30s, 60s, 300s",                     "1s, 5s, 30s, 60s, 5m, 15m, 1h"],
    ]
    S(kv_table(micro_rows, col_widths=[2.2 * inch, 0.9 * inch, 1.6 * inch, 1.45 * inch], font_size=8.8))
    S(P(
        "<b>Phase 1b (spread-filtered, 112 conditional trials).</b> Only "
        "runs if Phase 1a produces &ge;1 SURVIVOR. Pre-commits the full "
        "enumeration so the deflation hurdle is anchor-able from day one."
    ))

    S(H("Phase 1 gates (pre-committed)", 3))
    S(bullet("<b>G1 — IC magnitude.</b> |IC| &ge; 0.03 at peak horizon, "
             "in BOTH halves of the data."))
    S(bullet("<b>G2 — Sign consistency.</b> Sign of peak-horizon IC "
             "agrees between first half and second half."))
    S(bullet("<b>G3 — Stability.</b> Peak horizon in the second half is "
             "within &plusmn;1 step on the horizon grid of the first-half peak."))
    S(P(
        "A signal that passes G1+G2+G3 is reported as a Phase 1 SURVIVOR and "
        "proceeds to Phase 2 (strategy design, inventory risk, execution "
        "costs, adverse selection). Phase 2 + Phase 3 contracts are also "
        "pre-committed: <tt>PHASE2_DESIGN.md</tt>, <tt>PHASE3_DESIGN.md</tt>."
    ))

    # ============================================================
    # 13. SUBSTRATE #5
    # ============================================================
    S(H("13. Substrate #5 — PEAD via EDGAR XBRL (CLOSED FAILED)", 1))
    S(P(
        "Post-Earnings Announcement Drift implemented via SEC EDGAR Company "
        "Facts XBRL on the existing PIT equity substrate. Phase 0 produced "
        "614 eligible firms and ~26,908 firm-quarter announcements over "
        "2012-2026, certified in <tt>PEAD_PHASE0_CERTIFIED.md</tt> "
        "(SHA-256 <tt>a91e2a07ee...b9f9ae8</tt>)."
    ))
    S(P(
        "<b>Trial set.</b> 10 pre-committed trials: 5 holding horizons "
        "K &isin; {5, 21, 42, 63, 84} &times; 2 bucket cuts (quintile, decile). "
        "IS: 2012-2020. OOS-A: 2021-2023. OOS-B: 2024-2026-05-17. "
        "21-day embargo. Bootstrap: 4,000 reps."
    ))
    pead_rows = [
        ["K",  "Bucket",   "OOS-A IC", "OOS-B IC", "OOS-A Sharpe", "OOS-B Sharpe", "DSR-A", "DSR-B"],
        ["5",  "quintile", "0.051",    "0.050",    "+1.36",        "+3.68",        "0.29",  "0.88"],
        ["21", "quintile", "0.055",    "0.043",    "+1.67",        "+2.70",        "0.38",  "0.68"],
        ["42", "quintile", "0.034",    "0.047",    "+1.35",        "+3.41",        "0.29",  "0.83"],
        ["63", "quintile", "0.036",    "0.059",    "+2.29",        "+2.49",        "0.58",  "0.62"],
        ["84", "quintile", "0.038",    "0.058",    "+2.87",        "+2.39",        "0.75",  "0.60"],
    ]
    S(kv_table(pead_rows, col_widths=[0.4 * inch, 0.8 * inch, 0.9 * inch, 0.9 * inch, 1.0 * inch, 1.0 * inch, 0.6 * inch, 0.6 * inch], font_size=8.8))
    S(P(
        "<b>Verdict.</b> 0 of 10 trials cleared. \"Real but weak\": <b>OOS "
        "IC is uniformly positive across all 10 trials in both OOS windows "
        "(0.034 to 0.059)</b>, peak horizon at K=63–84 aligned with the "
        "literature (Livnat-Mendenhall 2006), sign agreement 8 of 10 — "
        "but no trial cleared DSR &gt; 0.95 (closest: K=84 quintile, 0.75 / "
        "0.60). The OOS-B window (2.4 years) is too short to tighten the "
        "bootstrap CI to a deflation-survivable level."
    ))

    # ============================================================
    # 14. SUBSTRATE #6
    # ============================================================
    S(H("14. Substrate #6 — NSE Event-Driven + Flow (CLOSED FAILED)", 1))
    S(P(
        "The first substrate deliberately chosen to break the cross-sectional-"
        "rank failure mode common to substrates 1–5: NSE bhavcopy + monthly "
        "trading-to-delivery (MTO) delivery percentages + F&amp;O expiry events "
        "on Indian large-caps. Phase 0 CERTIFIED 2026-05-20 with <b>7.76M EQ "
        "rows over 5,527 dates (2004-04 → 2026-05-19), 100% delivery-"
        "percentage coverage on Nifty-500 ever-members</b>."
    ))
    S(P(
        "<b>Trial set.</b> 22 trials after the &sect;17 ADDENDUM cancelled "
        "the FII/DII branch (data integrity issues): 18 delivery-percentage "
        "trials (3 lookbacks &times; 2 bucket cuts &times; 3 holding horizons) + "
        "4 F&amp;O expiry trials. IS: 2004-2014. OOS-A: 2015-2019. "
        "OOS-B: 2020-2026."
    ))
    S(P(
        "<b>Verdict.</b> 0 of 18 evaluated trials cleared even gates 1–4. "
        "F&amp;O Phase 3 was skipped — per-event high-open-interest universe "
        "data could not be reconstructed from public archives. <b>Universal "
        "OOS sign inversion:</b> every trial produced negative Sharpe in both "
        "OOS windows (range &minus;0.62 to &minus;4.94). Cost-doubling "
        "barely moves Sharpe (e.g. &minus;4.80 &rarr; &minus;4.88), confirming "
        "the signal <i>direction</i> reversed OOS rather than being eaten by "
        "costs."
    ))
    S(Paragraph(
        "\"The delivery-pct anomaly that produced positive IC in 2004-2014 "
        "produces actively negative Sharpe in 2015-2026. Same row-2 "
        "mechanism as the prior 5 substrates with a sharper edge.\" — "
        "<tt>alphaforge-india/research/GAUNTLET_VERDICT.md</tt>",
        styles["PullQuote"]
    ))
    S(P("Phase 1 IS evidence remained legitimate (IC 0.034–0.062, all "
        "22 trials survived G1 signed-positive). The collapse occurred "
        "exclusively in OOS, exactly the pattern the gauntlet is designed "
        "to catch."))

    S(PageBreak())

    # ============================================================
    # 15. SUBSTRATE #7
    # ============================================================
    S(H("15. Substrate #7 — CBOE Variance-Risk Premium (CLOSED FAILED)", 1))
    S(P(
        "<b>The first deliberate constraint shift of the project.</b> "
        "Substrates 1–6 all shared one structural assumption: alpha comes "
        "from prediction. VIX breaks that assumption. The variance-risk "
        "premium does not predict; it harvests a structural premium that "
        "exists because portfolio managers systematically overpay for "
        "insurance (Bondarenko 2004, Carr-Wu 2009). The edge is not better "
        "forecasting — it is <i>being the insurance writer</i>."
    ))
    S(P(
        "Substrate window: 2004-03-26 → present (CBOE VIX, VIX9D, VIX3M, "
        "VIX6M, SPY OHLCV, SVXY/VXX ETPs from 2011 onward). Pre-commit "
        "anchor: <tt>VIX_DESIGN.md</tt> SHA-256 <tt>54e53be9...</tt> "
        "post-&sect;17 + &sect;17.7 + &sect;17.8 ADDENDA. Phase 2 strategy "
        "spec frozen at SHA <tt>18173b6d...</tt>."
    ))

    S(H("Phase 1 (Information Coefficient gauntlet)", 3))
    S(P(
        "<b>10 of 18 VRP trials cleared signed-positive IC.</b> Strongest "
        "result: <b>peak IC +0.180 at h=21</b>, monotonic threshold response "
        "(thr=0 &rarr; 0/6, thr=2 &rarr; 4/6, thr=4 &rarr; 6/6 clean). 0 of 6 "
        "slope trials cleared. 4 mean-reversion trials deferred to Phase 3 "
        "per design contract. This was the first substrate of seven to live "
        "past Phase 1."
    ))

    S(H("Phase 3 (six-gate gauntlet)", 3))
    S(P(
        "Trial set: 28 (trial &times; hedge-variant) combos = 18 VRP "
        "trials + 4 mean-reversion + 6 closed-slope trials remaining in the "
        "DSR denominator per &sect;15 hard rules &times; 2 hedge variants "
        "(A: SPY put-protected; B: SPY-neutral)."
    ))
    vrp_top = [
        ["Trial &times; variant",                "OOS-A SR", "OOS-B SR", "DSR-A", "DSR-B", "G3", "G4", "G5", "G6"],
        ["<tt>vrp_L63_thr4_hold5_A</tt>",        "+0.23",    "+0.17",    "0.060", "0.037", "&check;", "&check;", "&check;", "&times;"],
        ["<tt>vrp_L63_thr4_hold21_A</tt>",       "+0.10",    "+0.20",    "0.033", "0.041", "&check;", "&check;", "&check;", "&times;"],
        ["<tt>mr_k2.0_to_MA+1sigma_A</tt>",      "+0.47",    "+0.12",    "0.255", "0.043", "&check;", "&check;", "&check;", "&times;"],
        ["<tt>mr_k2.0_to_MA+1sigma_B</tt>",      "+0.41",    "+0.13",    "0.193", "0.044", "&check;", "&check;", "&check;", "&times;"],
        ["<tt>vrp_L63_thr2_hold5_A</tt>",        "+0.04",    "+0.38",    "0.026", "0.070", "&check;", "&check;", "&check;", "&times;"],
        ["<tt>vrp_L10_thr2_hold5_A</tt>",        "+0.02",    "+0.52",    "0.022", "0.143", "&check;", "&middot;", "&check;", "&middot;"],
    ]
    S(P("<b>Top six positive-direction combos (sorted by combined OOS Sharpe).</b> "
        "0 cleared G1 (DSR &gt; 0.95) in either window; 0 cleared the deploy gate."))
    S(kv_table(vrp_top, col_widths=[2.05 * inch, 0.6 * inch, 0.6 * inch, 0.55 * inch, 0.55 * inch, 0.4 * inch, 0.4 * inch, 0.4 * inch, 0.4 * inch], font_size=8.5))
    S(P(
        "<b>Verdict.</b> 0 of 28 deploy-ready. The first Phase 3 run "
        "<i>appeared</i> to produce 18/28 passes; inspection revealed the "
        "passes were driven by cash carry on the unused 99.5% of NAV (the "
        "&sect;9.1 sizing formula <tt>0.10 &times; pv / VIX</tt> yields "
        "~0.5% NAV exposure at VIX=20). &sect;17.8 ADDENDUM zeroed cash "
        "carry (filed pre-rerun, direction-of-effect strictly makes Phase 3 "
        "harder); re-run produced 0/28. <b>The discipline caught its own "
        "false-pass.</b>"
    ))
    S(Paragraph(
        "Phase 1 evidence that the VRP premium has positive IC remains "
        "valid. Phase 3 evidence that the pre-committed &sect;9.1-sized "
        "retail implementation can&apos;t extract enough of it to clear "
        "DSR/bootstrap/CF gates after deflation against 28 trials is also "
        "valid. <b>Not contradictory.</b>",
        styles["PullQuote"]
    ))

    # ============================================================
    # 16. SUBSTRATE #8
    # ============================================================
    S(H("16. Substrate #8 — VIX-Baseline-Anchored Sizing (CLOSED FAILED)", 1))
    S(P(
        "Substrate #8 was spun up the same day substrate #7 closed, under a "
        "fresh SHA-anchored design contract (<tt>SUBSTRATE8_DESIGN.md</tt> "
        "SHA <tt>2194b7b2...</tt>). It tested one hypothesis: <i>if &sect;9.1 "
        "sizing is changed so the strategy has measurable dollar exposure, "
        "does it clear the same gauntlet against the same 28-trial DSR "
        "denominator?</i> Everything else inherited from substrate #7."
    ))
    S(P(
        "<b>Sizing rule change.</b> Substrate #7 &sect;9.1: "
        "<tt>max_notional = 0.10 &times; pv / VIX</tt>. Substrate #8 &sect;9.1: "
        "<tt>max_notional = 0.10 &times; pv &times; (20 / VIX)</tt>. Exactly "
        "20&times; substrate #7 at every VIX level; auto-deleverage shape "
        "preserved; baseline anchored on the long-run VIX mean, not on "
        "substrate-#7 results (no peeking)."
    ))
    S(P(
        "<b>Verdict.</b> 0 of 28 deploy-ready. <b>This refuted the substrate-"
        "#7 &sect;17.8 secondary diagnosis</b> (which had claimed \"sizing "
        "was too small to be measurable\"). Sharpe is dimensionless: making "
        "positions 20&times; larger does not move it. The correct diagnosis "
        "is Mode A revisited: the VRP / mean-reversion signal has real but "
        "modest OOS Sharpe (range &minus;0.77 to +0.55 across 28 combos), "
        "and DSR &gt; 0.95 against a 28-trial pre-commit + 5-year OOS sample "
        "requires Sharpe in the 1.5–2.5 range. <b>The signal can&apos;t "
        "clear the deflation hurdle regardless of position sizing because "
        "sizing is irrelevant to Sharpe.</b>"
    ))
    S(Paragraph(
        "\"Two substrates closed in one calendar day from one design — "
        "that&apos;s a methodology stress test. Phase 1 PASS + Phase 3 FAIL "
        "on #7 &rarr; &sect;17.8 diagnosis &rarr; substrate #8 PRE-COMMIT "
        "&rarr; substrate #8 also FAILS, and reveals the diagnosis was "
        "partly wrong. The methodology surfaced its own error in the "
        "substrate-#7 &sect;17.8 reasoning.\" — "
        "<tt>SUBSTRATE8_VERDICT.md</tt>",
        styles["PullQuote"]
    ))

    S(PageBreak())

    # ============================================================
    # 17. FAILURE TAXONOMY
    # ============================================================
    S(H("17. Failure-Mode Taxonomy — What the Verdicts Mean Together", 1))
    S(P(
        "Across eight substrates the gauntlet has classified four distinct "
        "failure modes. The taxonomy below is the analytic deliverable of "
        "the multi-substrate programme."
    ))
    modes = [
        ["Mode", "Description",                                                                                              "Substrates"],
        ["A",    "Real signal eaten by deflation against honest multiple-testing.",                                            "#1 (MV-21), #3 (carry), #5 (PEAD), #7+#8 (VRP)"],
        ["B",    "Horizon-bound: signal exists at one horizon but does not transport to others.",                              "#2 (MV-21 → MV-63/126)"],
        ["C",    "Sign inversion: IS-positive signal flips sign OOS, indistinguishable-from-noise direction reversal.",        "#6 (India delivery-%)"],
        ["D",    "Signal-too-small-to-detect-at-pre-committed-sizing (initial diagnosis on #7; refuted by #8).",               "#7 (initial), refuted by #8"],
    ]
    S(kv_table(modes, col_widths=[0.5 * inch, 3.85 * inch, 1.95 * inch], font_size=9))
    S(P(
        "<b>Mode A is the dominant pattern</b> (five of seven failed "
        "substrates). It is what the project's methodology is specifically "
        "designed to detect: a signal that <i>looks</i> publishable under "
        "naive testing but does not survive once it is honestly penalised "
        "for the size of the search space that produced it."
    ))
    S(P(
        "<b>The asymmetry between &quot;publishable&quot; and "
        "&quot;deployable&quot;.</b> Bondarenko 2004 and Carr-Wu 2009 "
        "documented the variance risk premium with strategies producing "
        "reported Sharpes of 1.0–1.5 <i>before</i> multiple-testing "
        "deflation. After DSR-28 deflation, those reported Sharpes would "
        "also fail the gate. The gauntlet correctly identifies that "
        "<i>publishable</i> alpha and <i>deployable</i> alpha are not the "
        "same thing."
    ))
    S(P(
        "<b>What is pre-arbitraged at this constraint set:</b> any signal "
        "whose OOS Sharpe is below ~1.5–2.0 against 28-trial deflation. "
        "That is the empirical bound discovered by the programme. Any future "
        "substrate that produces sub-1.5 Sharpe under the same constraints "
        "will fail in the same way."
    ))

    # ============================================================
    # 18. ENGINEERING
    # ============================================================
    S(H("18. Engineering Highlights — Tests, Parity, CI, Reproducibility", 1))
    S(bullet("<b>JS / Python numerical parity to 10 decimal places</b> on PRNG, "
             "factor scoring, and backtest paths. Same research expressible in "
             "either runtime without numerical drift; enforced by parity-"
             "fixture tests against <tt>js_reference_output.json</tt>."))
    S(bullet("<b>Defensive numerics by construction.</b> A small primitive set "
             "(<tt>safe_div</tt>, <tt>sanitize_number</tt>, <tt>clamp</tt>, "
             "<tt>validate_series</tt>) is used uniformly across both runtimes; "
             "NaN / Inf cannot propagate."))
    S(bullet("<b>Architectural enforcement of no-look-ahead.</b> "
             "<tt>BarHistory</tt> raises if asked for any row past its "
             "<tt>as_of</tt>; <tt>ExecutionHandler</tt> rejects fills that "
             "aren&apos;t strictly later than their originating order."))
    S(bullet("<b>SHA-256-anchored design contracts.</b> Every substrate "
             "freezes its design before any data is examined; the runner "
             "refuses to execute if the SHA does not match. India "
             "<tt>3b397262...</tt>, VIX <tt>54e53be9...</tt>, Phase 2 spec "
             "<tt>18173b6d...</tt>, substrate-#8 <tt>2194b7b2...</tt>, PEAD "
             "Phase 0 <tt>a91e2a07...</tt>."))
    S(bullet("<b>Pre- and post-fix output preservation.</b> Pre-bug-fix "
             "Tier 1 outputs are retained as <tt>*_residualized.json</tt> "
             "backups alongside post-fix outputs, enabling full audit of the "
             "diagnostic shift between runs."))
    S(bullet("<b>One-command reproducibility.</b> <tt>make all</tt> rebuilds "
             "every research artefact in this document from the parquet store "
             "in ~5 minutes."))
    S(bullet("<b>CI drift detection on headline metrics.</b> GitHub Actions "
             "matrix re-runs each headline study and diffs rebuilt JSON "
             "against the committed artefact. Silent numerical regression "
             "fails the build."))
    S(bullet("<b>Per-component CLAUDE.md.</b> Each sub-project carries its "
             "own architecture documentation. The root CLAUDE.md is the "
             "cross-cutting summary; each sub-project doc is the authoritative "
             "reference for that component."))
    S(bullet("<b>Knowledge-graph backed code review.</b> The repository is "
             "indexed by a Tree-sitter-based code-review knowledge graph "
             "(3,087 nodes, 26,157 edges, 328 files); semantic search, impact "
             "radius, and review-context queries replace manual grep/read on "
             "non-trivial reviews."))

    S(PageBreak())

    # ============================================================
    # 19. LIMITATIONS
    # ============================================================
    S(H("19. Honest Limitations and Process Disclosures", 1))
    S(P(
        "The framework&apos;s methodology is sound; the items below describe "
        "specific gaps, choices, and process failures that an auditor or "
        "peer reviewer should know about."
    ))
    S(bullet("<b>Residualisation-wiring bug (process failure, fixed 2026-05-"
             "02).</b> <tt>prepare_analysis_returns()</tt> returned raw "
             "returns regardless of the residualise flag for an unknown "
             "period; the post-hoc <tt>compute_portfolio_alpha</tt> layer "
             "existed but was not wired into the main gauntlet. JSON metadata "
             "claimed <tt>analysis_returns_mode: residualized</tt> while the "
             "computation was on raw returns. Caught during Tier 2; fixed in "
             "&lt;50 lines; gauntlet re-run; verdict held but documented "
             "diagnostic shifted. An audited institutional pipeline would have "
             "caught this via code review or independent reimplementation."))
    S(bullet("<b>Phase 3 FF5 replica gate was soft-passed.</b> 3 of 6 "
             "reference factors (SMB, RMW, CMA) failed the &gt;0.85 correlation "
             "threshold against Kenneth French&apos;s published series on the "
             "476-ticker substrate (structural — French builds on full "
             "CRSP). Decision: use French&apos;s published series for "
             "residualisation rather than the local replica, sidestepping the "
             "failed sub-gate. Documented, but a partial compromise."))
    S(bullet("<b>Tier 2 design contained two no-op variants.</b> Vol-cap "
             "variants are mathematical no-ops because Sharpe and DSR are "
             "scale-invariant. Extended-history variants did not actually use "
             "extended training data given panel start = 2016. Trial set "
             "effectively reduced from 8 to 4 unique strategies. Verdict held "
             "under both interpretations."))
    S(bullet("<b>Cost model under-estimates real spreads.</b> Parametric 2 bp "
             "half-spread vs Corwin-Schultz median 7–8 bp across all "
             "windows. Direction of effect: makes the row-2 hypothesis look "
             "MORE viable than reality, strengthening the verdict, not "
             "weakening it."))
    S(bullet("<b>25% data gap on the PIT universe.</b> 226 of 881 ever-member "
             "tickers have no yfinance OHLCV (delisted / restructured). "
             "Documented in every metric. CRSP-grade data would close the gap "
             "but was out of budget."))
    S(bullet("<b>No live-vs-backtest tracking number.</b> 7 lifetime fills "
             "before the .halt; not enough for KS-test or cumulative-drag "
             "analysis. The infrastructure exists; the data does not."))
    S(bullet("<b>No per-name borrow-cost differentiation.</b> Borrow-cost "
             "table supports HTB overrides; currently populated with general-"
             "collateral defaults. Material understatement for any non-mega-"
             "cap short leg."))
    S(bullet("<b>Trial count is conservative for MARL.</b> The MARL DSR "
             "deflates against 100 generation-level trials; the true search "
             "space (architecture, curriculum, reward shaping, selection rule) "
             "is larger. Published OOS DSR is an optimistic <i>upper</i> bound "
             "on credibility."))
    S(bullet("<b>VIX &sect;7 residualisation incomplete.</b> Only SPY + "
             "&Delta;VIX are wired into the OLS (2 of 4 factors). "
             "ST-Reversal and Carry factors are not staged. Per-trial "
             "<tt>provisional=True</tt> flag in the machine output."))
    S(bullet("<b>India F&amp;O Phase 3 SKIPPED.</b> Per-event high-OI universe "
             "data could not be reconstructed from public archives; 4 of 22 "
             "trials report no Phase 3 result. Counted in the DSR denominator "
             "per &sect;17 ADDENDUM."))
    S(bullet("<b>&sect;7 reset cooldown has been overridden four times.</b> "
             "Crypto, PEAD, India, and VIX-as-constraint-shift. All four "
             "overrides closed FAILED. The override discipline is itself an "
             "audit-able fact of the project."))

    # ============================================================
    # 20. JUNE 2026 UPDATE
    # ============================================================
    S(H("20. June 2026 Update — Substrates #9–#10 and the Canonical Gauntlet", 1))
    S(P(
        "<b>This section post-dates the original document body</b> and records the "
        "work since 2026-05-22: two further substrates and a consolidation of the "
        "evaluation methodology into one audited, version-pinned package with a "
        "measured detection floor. Where it conflicts with earlier sections, this "
        "section governs."
    ))

    S(H("Substrate #9 — SPY Iron-Condor Options (CLOSED FAILED 2026-05-26)", 3))
    S(P(
        "Black-Scholes reconstruction on free VIX + OHLCV. The premium is "
        "<i>real</i>: 11 of 11 in-sample years positive, mean +$0.19/share per "
        "cycle. But the entry-time variance-risk premium has <b>no predictive "
        "power for cycle-level P&amp;L</b>: corr(VRP_entry, cycle P&amp;L) = "
        "&minus;0.0146 (required &gt; 0). <b>Mode E</b> — the binary filter "
        "(VRP &gt; 0 &rarr; positive expectation) works, but the continuous-predictor "
        "relationship is absent. Closed at Phase 1, Test 1."
    ))

    S(H("Substrate #10 — Kalshi Favorite-Longshot Bias (PHASE 1 INCONCLUSIVE)", 3))
    S(P(
        "The first substrate where <b>small capacity is the edge, not the "
        "handicap</b>: a $40k Kalshi market is too small for an institution and "
        "right-sized for a solo trader. Goal: a credible live track record, not "
        "fund-scale alpha. Phase 0 CERTIFIED (292 volume-bearing resolved "
        "contracts, no-look-ahead 100%; Kalshi fee schedule confirmed). Phase 1 "
        "INCONCLUSIVE — the free read-only host exposes only a recent, MVE-heavy "
        "universe, so available N sits <b>25–140&times; below the binary-MDE "
        "detection floor</b>; per the decision matrix this routes to forward "
        "accumulation. The Phase-1 core was adversarially audited 7/7 "
        "integrity-clean."
    ))
    S(bullet("<b>Phase 2 forward record is live.</b> A read-only paper-trade "
             "harness places against the Kalshi <tt>/events</tt> feed (the "
             "<tt>/markets</tt> feed is 100% sub-minute MVE), with a 45-day "
             "time-to-close cap so the record accrues on a useful timescale. "
             "launchd runs <tt>place</tt> 3&times;/day, <tt>reconcile</tt> + a "
             "weekly digest. Target: 200 resolved events (~weeks–2 months)."))

    S(H("The Canonical Gauntlet (afgauntlet) + DSR Audit", 3))
    S(P(
        "The per-substrate statistics (Sharpe, DSR, bootstrap CI, SPA / Reality "
        "Check, purged-embargoed CV) were consolidated into one version-pinned, "
        "golden-tested package, with a binary/calibration module (Brier, log-loss, "
        "reliability curve, calibration-edge bootstrap, binary MDE) for prediction "
        "markets. A reconciliation audit found the project had been running "
        "<b>four different DSR implementations</b>; measured divergence is at most "
        "0.026 in DSR units and produces <b>0 verdict flips across 96 grid "
        "points</b> — so no historical verdict was an artifact of its estimator."
    ))

    S(H("MDE Power Calibration — Real Null vs Blunt Instrument", 3))
    S(P(
        "A power study injects synthetic alpha of known strength onto real return "
        "noise and measures how often the gauntlet detects it. Overall power "
        "tracks the DSR-gate pass rate exactly &mdash; <b>DSR deflation is the "
        "sole binding constraint.</b> Minimum detectable true annualized Sharpe "
        "(80% power): <b>~0.93</b> generous (1 trial, 10-year window), "
        "<b>~2.40</b> VIX-like (28 trials, 5-year), <b>&gt; 3.5</b> PEAD-like "
        "(short OOS). Reading: the strongest observed signal (VIX OOS +0.55) sits "
        "below even the generous floor &mdash; a <i>real null</i> &mdash; but a "
        "2.4-Sharpe bar is economically strict versus the ~0.5–1.0 a leveraged "
        "desk trades, so the hurdle, not only the data, is part of the story."
    ))

    S(H("Cost-Model Reconciliation + Microstructure Recollection", 3))
    S(bullet("<b>Costs.</b> Realized paper-trade slippage was ~2.6–3&times; the "
             "assumed rate (on 12 live fills), but higher costs flip <b>zero</b> "
             "verdicts; only crypto carry was plausibly cost-bound. The binding "
             "constraint was deflation, not execution."))
    S(bullet("<b>Microstructure (#4) Phase 0 break.</b> The live collector ran "
             "pre-fix code for 29 days (82% gap fraction, ~33% hour coverage). "
             "Code on disk was already correct; the process was stale. Fixed the "
             "readiness tooling, added a recent-gap-rate alarm, filed a recovery "
             "runbook. Earliest honest Phase 1 ~2026-07-16."))
    S(P(
        "The full cross-substrate synthesis lives in "
        "<tt>RESEARCH_META_SYNTHESIS.md</tt>."
    ))

    S(PageBreak())

    # ============================================================
    # 21. FORWARD PATH
    # ============================================================
    S(H("21. Forward Path — The Strategy-Class Decision Window", 1))
    S(P(
        "<b>The honest question is no longer &quot;what substrate?&quot; — "
        "it is &quot;what strategy class?&quot;</b> Cross-sectional rank-based "
        "signals with linear combinations and parametric retail costs do not "
        "survive in either equity (substrates 1–2, 5), crypto perpetuals "
        "(substrate 3), Indian large-caps (substrate 6), vol-surface "
        "premium harvest (substrates 7–9), or — at free-data scale — "
        "prediction-market calibration (substrate 10). Six of the eight "
        "failures share the row-2 / Mode A pattern with variants; India shows "
        "sharper Mode C sign inversion; the VIX cluster discovered Mode D and "
        "then refuted it; and the iron condor exhibited Mode E (binary filter "
        "works, continuous predictor absent). The MDE calibration (§20) reframes "
        "this: the binding constraint is the DSR deflation floor, and the "
        "open question is whether to lower that bar deliberately or change a "
        "structural input."
    ))

    S(H("What could change the verdict (substrate #9+)", 3))
    S(bullet("<b>Larger pre-commit window.</b> 10-year OOS instead of 5-year "
             "lowers DSR variance correction. Requires waiting OR using paid "
             "pre-2004 data."))
    S(bullet("<b>Fewer pre-committed trials.</b> 10-trial DSR denominator "
             "instead of 28. Requires dropping search-space from the start; "
             "cannot subset post-hoc."))
    S(bullet("<b>Different strategy class.</b> Spin-off arbitrage (Greenblatt "
             "1997, retail-scale documented), microcap value + quality, vol-"
             "surface dispersion, crypto on-chain analytics, market-making at "
             "fast latencies. None of these were tested by substrates 1–8."))
    S(bullet("<b>Paid data.</b> CRSP, VIX futures, Kenneth French published "
             "factors, FRED — closes both the 25% PIT data gap and the "
             "&sect;7 residualisation gap."))
    S(bullet("<b>Abandon systematic alpha at retail constraints.</b> Move to "
             "market-making, non-systematic discretionary, or accept the "
             "research stack as a methodology contribution rather than a "
             "capital-deployment vehicle."))

    S(H("Live execution status", 3))
    S(P(
        "<tt>alphaforge-execution/.halt</tt> is engaged. <tt>run_daily.sh</tt> "
        "exits with <tt>HALTED</tt> on every cron fire. The 10 Alpaca paper "
        "positions across momentum and MARL accounts were flattened on "
        "2026-04-26 via <tt>scripts/tier1_close_positions.py</tt>. Re-launch "
        "requires the four conditions in <tt>docs/TIER1_PAUSE.md</tt> (Tier "
        "1 gate passed, signal is the survivor, universe expanded, &ge;6 "
        "months paper trade). With Tier 1 + Tier 2 closed, those conditions "
        "cannot be met from the current state; the .halt stays on "
        "indefinitely. The kill-switch infrastructure remains tested and "
        "wired so a future re-arm can proceed under the existing risk "
        "framework."
    ))

    S(H("What the project demonstrates today", 3))
    S(P(
        "An end-to-end research-grade systematic-trading stack built and run "
        "on free public data by a solo undergraduate, applied honestly to a "
        "known-hard problem across six asset classes and two strategy "
        "classes, with methodology bugs found and fixed in the same session "
        "they surfaced and every diagnostic shift documented openly. <b>The "
        "negative results published here are the artefact; surviving signals "
        "are not.</b> The current frontier is two-fold: substrate #10's live "
        "forward paper-trade record (the first deliberate pursuit of a "
        "small-capacity edge) and substrate #4's microstructure Phase 1 once "
        "its book-data recollection completes (~2026-07-16). The methodology "
        "now reports not just a verdict but, via the MDE calibration, whether a "
        "verdict was even detectable in the first place."
    ))

    S(Spacer(1, 0.25 * inch))
    S(hr(PRIMARY, 0.6))
    S(P(
        "<b>Repository:</b> <i>Quant Alpha</i> (AlphaForge). "
        "<b>Generator:</b> <tt>docs/build_alphaforge_pdf.py</tt>. "
        "<b>Companion artefacts:</b> <tt>PHASE6_WRITEUP.md</tt>, "
        "<tt>TIER2_VERDICT.md</tt>, "
        "<tt>alphaforge-crypto/research/CARRY_STUDY_VERDICT.md</tt>, "
        "<tt>alphaforge-pead/research/PHASE1_VERDICT.md</tt>, "
        "<tt>alphaforge-india/research/GAUNTLET_VERDICT.md</tt>, "
        "<tt>alphaforge-vix/research/GAUNTLET_VERDICT.md</tt>, "
        "<tt>alphaforge-vix/research/SUBSTRATE8_VERDICT.md</tt>, "
        "<tt>alphaforge-microstructure/research/PHASE1_DESIGN.md</tt>. "
        "Reproducible: <tt>make all</tt> rebuilds every JSON cited.",
        style="Small"
    ))

    doc.build(story, onFirstPage=_draw_title_page, onLaterPages=_draw_footer)
    print(f"Wrote {OUT}")


if __name__ == "__main__":
    build()
