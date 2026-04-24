# AlphaForge — reproducibility Makefile.
#
# Every headline research artifact is derivable from this file with a
# single command. All scripts consume the local parquet store (no
# network), and each target writes its output to a known path. Targets
# that share inputs are listed as explicit dependencies so `make` will
# short-circuit anything already up to date.
#
# Usage:
#   make all              # rebuild every headline report
#   make factor-study     # single-factor study
#   make capacity-study   # capacity + regime + crowding
#   make marl-rigor       # MARL rigor report
#   make ablation-ladder  # MARL ablation paired-bootstrap report
#   make tests            # run all three test suites
#   make clean            # delete every generated report

PY        := python3
PYTHON_DIR := alphaforge-python
MARL_DIR   := alphaforge-marl
EXEC_DIR   := alphaforge-execution

PY_OUT     := $(PYTHON_DIR)/research/out
MARL_OUT   := $(MARL_DIR)/research/out
EXEC_OUT   := $(EXEC_DIR)/research/out

# Deterministic seeds for every stochastic study. Override at the CLI if needed.
export ALPHAFORGE_GLOBAL_SEED ?= 42

.PHONY: all factor-study capacity-study marl-rigor ablation-ladder \
        slippage-reconciliation tests tests-python tests-marl tests-execution \
        clean print-seeds

all: factor-study capacity-study tsmom-study pairs-study marl-rigor ablation-ladder

# ─── single-factor study ────────────────────────────────────────────────
$(PY_OUT)/factor_study_report.md: \
    $(PYTHON_DIR)/research/factor_study.py \
    $(PYTHON_DIR)/research/cost_model.py \
    $(PYTHON_DIR)/research/stats_hygiene.py
	cd $(PYTHON_DIR) && $(PY) research/factor_study.py

factor-study: $(PY_OUT)/factor_study_report.md

# ─── capacity, regime, crowding ─────────────────────────────────────────
$(PY_OUT)/capacity_report.md: \
    $(PYTHON_DIR)/research/capacity_study.py \
    $(PYTHON_DIR)/research/cost_model.py
	cd $(PYTHON_DIR) && $(PY) research/capacity_study.py

capacity-study: $(PY_OUT)/capacity_report.md

# ─── TSMOM (time-series momentum) ───────────────────────────────────────
$(PY_OUT)/tsmom_report.md: \
    $(PYTHON_DIR)/research/tsmom_study.py \
    $(PYTHON_DIR)/strategies/tsmom.py
	cd $(PYTHON_DIR) && $(PY) research/tsmom_study.py

tsmom-study: $(PY_OUT)/tsmom_report.md

# ─── pairs trading ──────────────────────────────────────────────────────
$(PY_OUT)/pairs_report.md: \
    $(PYTHON_DIR)/research/pairs_study.py \
    $(PYTHON_DIR)/strategies/pairs_trading.py
	cd $(PYTHON_DIR) && $(PY) research/pairs_study.py

pairs-study: $(PY_OUT)/pairs_report.md

# ─── MARL rigor ─────────────────────────────────────────────────────────
$(MARL_OUT)/marl_rigor_report.md: $(MARL_DIR)/research/marl_rigor.py
	cd $(MARL_DIR) && $(PY) research/marl_rigor.py

marl-rigor: $(MARL_OUT)/marl_rigor_report.md

# ─── MARL ablation ladder ───────────────────────────────────────────────
$(MARL_OUT)/ablation_ladder_report.md: $(MARL_DIR)/research/ablation_ladder.py
	cd $(MARL_DIR) && $(PY) research/ablation_ladder.py

ablation-ladder: $(MARL_OUT)/ablation_ladder_report.md

# ─── slippage reconciliation (needs a populated SQLite DB) ──────────────
$(EXEC_OUT)/slippage_reconciliation.md: \
    $(EXEC_DIR)/research/slippage_reconciliation.py
	cd $(EXEC_DIR) && $(PY) research/slippage_reconciliation.py \
	   --db alphaforge_execution.db --simulated-bps 5.0 || \
	   echo "[skipped — no SQLite DB yet]"

slippage-reconciliation: $(EXEC_OUT)/slippage_reconciliation.md

# ─── tests ──────────────────────────────────────────────────────────────
tests: tests-python tests-marl tests-execution

tests-python:
	cd $(PYTHON_DIR) && $(PY) -m pytest tests/ -q

tests-marl:
	cd $(MARL_DIR) && $(PY) -m pytest tests/ -q

tests-execution:
	cd $(EXEC_DIR) && $(PY) -m pytest tests/ -q

# ─── utilities ──────────────────────────────────────────────────────────
print-seeds:
	@echo "ALPHAFORGE_GLOBAL_SEED = $(ALPHAFORGE_GLOBAL_SEED)"

clean:
	rm -f $(PY_OUT)/factor_study_report.md $(PY_OUT)/factor_study_results.json \
	      $(PY_OUT)/net_navs.csv \
	      $(PY_OUT)/capacity_report.md $(PY_OUT)/capacity_results.json $(PY_OUT)/capacity_curve.csv \
	      $(PY_OUT)/tsmom_report.md $(PY_OUT)/tsmom_results.json \
	      $(PY_OUT)/pairs_report.md $(PY_OUT)/pairs_results.json \
	      $(MARL_OUT)/marl_rigor_report.md $(MARL_OUT)/marl_rigor_metrics.json \
	      $(MARL_OUT)/ablation_ladder_report.md $(MARL_OUT)/ablation_ladder_results.json \
	      $(EXEC_OUT)/slippage_reconciliation.md $(EXEC_OUT)/slippage_reconciliation.json
