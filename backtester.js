/* ============================================================
   AlphaForge — Strategy Backtester (Module 1)
   ============================================================ */

(function () {
  const D = window.AlphaData;
  let navChart = null, monthlyChart = null, ddChart = null;

  function init() {
    bindControls();
  }

  function bindControls() {
    const holdSlider = document.getElementById('bt-holding');
    const posSlider = document.getElementById('bt-position');
    const slSlider = document.getElementById('bt-stoploss');
    const txInput = document.getElementById('bt-txcost');

    holdSlider.addEventListener('input', () => {
      const v = clampInput(holdSlider, 1, 60);
      document.getElementById('bt-holding-value').textContent = v + 'd';
      validateHolding();
    });
    posSlider.addEventListener('input', () => {
      const v = clampInput(posSlider, 1, 20);
      document.getElementById('bt-position-value').textContent = v + '%';
    });
    slSlider.addEventListener('input', () => {
      const v = clampInput(slSlider, 1, 15);
      document.getElementById('bt-stoploss-value').textContent = v + '%';
    });
    txInput.addEventListener('change', () => {
      txInput.value = D.clamp(parseInt(txInput.value) || 0, 0, 100);
    });

    document.getElementById('bt-run').addEventListener('click', runBacktest);
  }

  function clampInput(el, min, max) {
    let v = parseFloat(el.value);
    v = D.clamp(v, min, max);
    el.value = v;
    return v;
  }

  function validateHolding() {
    const lookback = parseInt(document.getElementById('lookback-slider').value);
    const holding = parseInt(document.getElementById('bt-holding').value);
    const errEl = document.getElementById('bt-holding-error');
    if (holding > lookback) {
      errEl.textContent = 'Must be ≤ lookback (' + lookback + 'd)';
      errEl.classList.add('visible');
      return false;
    }
    errEl.classList.remove('visible');
    return true;
  }

  function runBacktest() {
    // Validate
    if (!validateHolding()) {
      showError('Holding period exceeds lookback window.');
      return;
    }
    hideError();

    const B = window.AlphaBackend;
    if (B && B.isApiMode()) {
      runBacktestAPI();
    } else {
      runBacktestLocal();
    }
  }

  async function runBacktestAPI() {
    const state = window.AlphaApp.getState();
    const config = {
      sector: state.sector,
      lookback: state.lookback,
      factor: document.getElementById('bt-factor').value,
      holdingPeriod: parseInt(document.getElementById('bt-holding').value),
      positionSize: parseInt(document.getElementById('bt-position').value),
      stopLoss: parseFloat(document.getElementById('bt-stoploss').value),
      txCostBps: parseInt(document.getElementById('bt-txcost').value) || 0,
    };

    try {
      const data = await window.AlphaBackend.fetchBacktest(config);
      if (data.error) {
        showError(data.error);
        return;
      }
      const result = {
        nav: data.nav,
        benchmarkNav: data.benchmark_nav,
        drawdowns: data.drawdowns,
        monthlyReturns: data.monthly_returns,
        dailyReturns: data.daily_returns,
        metrics: {
          sharpe: data.metrics.sharpe,
          totalReturn: data.metrics.total_return,
          benchReturn: data.metrics.bench_return,
          maxDrawdown: data.metrics.max_dd,
          maxDrawdownDay: data.metrics.max_dd_day,
          winRate: data.metrics.win_rate,
          annVol: data.metrics.ann_vol,
          calmar: data.metrics.calmar,
        },
      };
      renderMetrics(result.metrics);
      renderCharts(result, state.lookback);
    } catch (err) {
      showError('API error: ' + err.message);
    }
  }

  function runBacktestLocal() {
    const state = window.AlphaApp.getState();
    const factor = document.getElementById('bt-factor').value;
    const holdingPeriod = parseInt(document.getElementById('bt-holding').value);
    const positionSize = parseInt(document.getElementById('bt-position').value);
    const stopLoss = parseFloat(document.getElementById('bt-stoploss').value);
    const txCostBps = parseInt(document.getElementById('bt-txcost').value) || 0;

    const dataset = D.generateDataset(state.sector, state.lookback);

    if (Object.keys(dataset).length === 0) {
      showError('No tickers in selected universe.');
      return;
    }

    const result = D.runBacktest({
      dataset, factor, holdingPeriod, positionSize, stopLoss, txCostBps, lookbackDays: state.lookback
    });

    if (!result || result.error) {
      showError(result ? result.error : 'Backtest failed — unknown error.');
      return;
    }

    renderMetrics(result.metrics);
    renderCharts(result, state.lookback);
  }

  function renderMetrics(m) {
    setMetric('bt-sharpe', m.sharpe, v => v.toFixed(2), v => v >= 1 ? 'positive' : v >= 0 ? 'neutral' : 'negative');
    setMetric('bt-return', m.totalReturn, v => (v * 100).toFixed(1) + '%', v => v > 0 ? 'positive' : v < 0 ? 'negative' : 'neutral');
    setMetric('bt-drawdown', m.maxDrawdown, v => '-' + (v * 100).toFixed(1) + '%', () => 'negative');
    setMetric('bt-winrate', m.winRate, v => (v * 100).toFixed(1) + '%', v => v >= 0.5 ? 'positive' : 'neutral');

    const ddDate = document.getElementById('bt-dd-date');
    if (m.maxDrawdownDay != null) {
      ddDate.textContent = 'Day ' + m.maxDrawdownDay;
    }
  }

  function setMetric(id, value, formatter, classifier) {
    const el = document.getElementById(id);
    if (value == null || !isFinite(value)) {
      el.textContent = 'N/A';
      el.className = 'metric-value na';
      el.title = 'Metric could not be computed — check parameters';
    } else {
      el.textContent = formatter(value);
      el.className = 'metric-value ' + classifier(value);
      el.title = '';
    }
  }

  function renderCharts(result, lookback) {
    if (!window.CHARTJS_LOADED) {
      document.getElementById('bt-nav-fallback').classList.remove('hidden');
      document.getElementById('bt-monthly-fallback').classList.remove('hidden');
      document.getElementById('bt-dd-fallback').classList.remove('hidden');
      document.querySelectorAll('#panel-backtester canvas').forEach(c => c.classList.add('hidden'));
      return;
    }

    const dateLabels = D.generateDateLabels(result.nav.length - 1);
    const monthLabels = D.generateMonthLabels(result.monthlyReturns.length);

    // ── NAV Chart ──
    if (navChart) navChart.destroy();
    const navCtx = document.getElementById('bt-nav-chart').getContext('2d');
    document.getElementById('bt-nav-chart').classList.remove('hidden');
    document.getElementById('bt-nav-fallback').classList.add('hidden');

    navChart = new Chart(navCtx, {
      type: 'line',
      data: {
        labels: dateLabels,
        datasets: [
          { label: 'Strategy NAV', data: result.nav, borderColor: '#6366f1', backgroundColor: 'rgba(99,102,241,0.08)', borderWidth: 2, fill: true, pointRadius: 0, tension: 0.3 },
          { label: 'Benchmark', data: result.benchmarkNav, borderColor: '#64748b', borderWidth: 1.5, borderDash: [5, 5], pointRadius: 0, fill: false, tension: 0.3 },
        ]
      },
      options: chartOptions('NAV ($)')
    });

    // ── Monthly Returns ──
    if (monthlyChart) monthlyChart.destroy();
    const mCtx = document.getElementById('bt-monthly-chart').getContext('2d');
    document.getElementById('bt-monthly-chart').classList.remove('hidden');
    document.getElementById('bt-monthly-fallback').classList.add('hidden');

    monthlyChart = new Chart(mCtx, {
      type: 'bar',
      data: {
        labels: monthLabels,
        datasets: [{
          label: 'Monthly Return',
          data: result.monthlyReturns.map(r => r * 100),
          backgroundColor: result.monthlyReturns.map(r => r >= 0 ? 'rgba(34,197,94,0.7)' : 'rgba(239,68,68,0.7)'),
          borderColor: result.monthlyReturns.map(r => r >= 0 ? '#22c55e' : '#ef4444'),
          borderWidth: 1,
          borderRadius: 4,
        }]
      },
      options: chartOptions('Return (%)')
    });

    // ── Drawdown Chart ──
    if (ddChart) ddChart.destroy();
    const ddCtx = document.getElementById('bt-dd-chart').getContext('2d');
    document.getElementById('bt-dd-chart').classList.remove('hidden');
    document.getElementById('bt-dd-fallback').classList.add('hidden');

    ddChart = new Chart(ddCtx, {
      type: 'line',
      data: {
        labels: dateLabels.slice(1),
        datasets: [{
          label: 'Drawdown',
          data: result.drawdowns.map(d => -d * 100),
          borderColor: '#ef4444',
          backgroundColor: 'rgba(239,68,68,0.1)',
          borderWidth: 1.5,
          fill: true,
          pointRadius: 0,
          tension: 0.3,
        }]
      },
      options: chartOptions('Drawdown (%)')
    });
  }

  function chartOptions(yLabel) {
    const textColor = getComputedStyle(document.documentElement).getPropertyValue('--text-secondary').trim() || '#94a3b8';
    const gridColor = getComputedStyle(document.documentElement).getPropertyValue('--border-primary').trim() || 'rgba(148,163,184,0.12)';
    return {
      responsive: true,
      maintainAspectRatio: false,
      interaction: { intersect: false, mode: 'index' },
      plugins: {
        legend: { display: true, labels: { color: textColor, font: { family: 'Inter', size: 11 }, boxWidth: 12 } },
        tooltip: {
          backgroundColor: 'rgba(17,24,39,0.95)', titleColor: '#f0f4f8', bodyColor: '#94a3b8',
          borderColor: 'rgba(148,163,184,0.2)', borderWidth: 1, cornerRadius: 8,
          titleFont: { family: 'Inter', weight: '600' }, bodyFont: { family: 'JetBrains Mono', size: 12 },
        },
      },
      scales: {
        x: { ticks: { color: textColor, font: { size: 10 }, maxTicksLimit: 12, maxRotation: 0 }, grid: { color: gridColor } },
        y: { title: { display: true, text: yLabel, color: textColor, font: { size: 11 } }, ticks: { color: textColor, font: { size: 10 } }, grid: { color: gridColor } },
      },
    };
  }

  function showError(msg) {
    const banner = document.getElementById('bt-error-banner');
    document.getElementById('bt-error-msg').textContent = msg;
    banner.classList.add('visible');
  }

  function hideError() {
    document.getElementById('bt-error-banner').classList.remove('visible');
  }

  window.BacktesterModule = { init, runBacktest };
})();
