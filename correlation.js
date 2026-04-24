/* ============================================================
   AlphaForge — Correlation Laboratory (Module 3)
   ============================================================ */

(function () {
  const D = window.AlphaData;
  let icChart = null, turnoverChart = null;

  function init() {
    // Auto-renders when tab is activated
  }

  function render() {
    const B = window.AlphaBackend;
    if (B && B.isApiMode()) {
      renderAPI();
    } else {
      renderLocal();
    }
  }

  async function renderAPI() {
    const state = window.AlphaApp.getState();
    try {
      const data = await window.AlphaBackend.fetchCorrelation(state.sector, state.lookback);
      renderHeatmapFromData(data.matrix, data.factors);
      renderICChartFromData(data.ic, data.factors);
      renderTurnoverChartFromData(data.turnover, data.factors);
    } catch (err) {
      window.AlphaApp.showToast('API error: ' + err.message, 'error');
      renderLocal();
    }
  }

  function renderLocal() {
    const state = window.AlphaApp.getState();
    const dataset = D.generateDataset(state.sector, state.lookback);

    if (Object.keys(dataset).length === 0) return;

    renderHeatmap(dataset, state.lookback);
    renderICChart(dataset, state.lookback);
    renderTurnoverChart(dataset, state.lookback);
  }

  function renderHeatmap(dataset, lookback) {
    const matrix = D.computeCorrelationMatrix(dataset, lookback);
    const container = document.getElementById('corr-heatmap');
    const n = D.FACTOR_NAMES.length;
    const shortNames = ['MOM', 'MR5d', 'VOL', 'RSI', 'EARN'];

    container.style.gridTemplateColumns = `80px repeat(${n}, 1fr)`;

    let html = '<div class="heatmap-cell heatmap-header"></div>';
    for (let j = 0; j < n; j++) {
      html += `<div class="heatmap-cell heatmap-header">${shortNames[j]}</div>`;
    }

    for (let i = 0; i < n; i++) {
      html += `<div class="heatmap-cell heatmap-header">${shortNames[i]}</div>`;
      for (let j = 0; j < n; j++) {
        const val = D.sanitizeNumber(matrix[i][j], 0);
        const color = corrColor(val);
        const textColor = Math.abs(val) > 0.5 ? '#fff' : 'var(--text-primary)';
        html += `<div class="heatmap-cell" style="background:${color};color:${textColor};" title="${D.FACTOR_NAMES[i]} vs ${D.FACTOR_NAMES[j]}: ${val.toFixed(3)}">${val.toFixed(2)}</div>`;
      }
    }

    container.innerHTML = html;
  }

  function corrColor(val) {
    const v = D.clamp(val, -1, 1);
    if (v > 0) {
      const intensity = Math.floor(v * 200);
      return `rgba(59, 130, 246, ${0.15 + v * 0.7})`;
    } else if (v < 0) {
      return `rgba(239, 68, 68, ${0.15 + Math.abs(v) * 0.7})`;
    }
    return 'rgba(75, 85, 99, 0.3)';
  }

  function renderICChart(dataset, lookback) {
    if (!window.CHARTJS_LOADED) {
      document.getElementById('corr-ic-fallback').classList.remove('hidden');
      document.getElementById('corr-ic-chart').classList.add('hidden');
      return;
    }

    const ics = D.computeIC(dataset, lookback);
    const values = D.FACTOR_NAMES.map(f => D.sanitizeNumber(ics[f] * 100, 0));

    if (icChart) icChart.destroy();
    const ctx = document.getElementById('corr-ic-chart').getContext('2d');
    document.getElementById('corr-ic-chart').classList.remove('hidden');
    document.getElementById('corr-ic-fallback').classList.add('hidden');

    icChart = new Chart(ctx, {
      type: 'bar',
      data: {
        labels: D.FACTOR_NAMES,
        datasets: [{
          label: 'IC (%)',
          data: values,
          backgroundColor: values.map(v => v >= 0 ? 'rgba(99,102,241,0.7)' : 'rgba(239,68,68,0.7)'),
          borderColor: values.map(v => v >= 0 ? '#6366f1' : '#ef4444'),
          borderWidth: 1,
          borderRadius: 4,
        }]
      },
      options: barOptions('Information Coefficient (%)')
    });
  }

  function renderTurnoverChart(dataset, lookback) {
    if (!window.CHARTJS_LOADED) {
      document.getElementById('corr-turnover-fallback').classList.remove('hidden');
      document.getElementById('corr-turnover-chart').classList.add('hidden');
      return;
    }

    const turnovers = D.computeFactorTurnover(dataset, lookback);
    const values = D.FACTOR_NAMES.map(f => D.sanitizeNumber(turnovers[f] * 100, 30));

    if (turnoverChart) turnoverChart.destroy();
    const ctx = document.getElementById('corr-turnover-chart').getContext('2d');
    document.getElementById('corr-turnover-chart').classList.remove('hidden');
    document.getElementById('corr-turnover-fallback').classList.add('hidden');

    turnoverChart = new Chart(ctx, {
      type: 'bar',
      data: {
        labels: D.FACTOR_NAMES,
        datasets: [{
          label: 'Turnover (%)',
          data: values,
          backgroundColor: 'rgba(139,92,246,0.6)',
          borderColor: '#8b5cf6',
          borderWidth: 1,
          borderRadius: 4,
        }]
      },
      options: barOptions('Portfolio Turnover (%)')
    });
  }

  function barOptions(yLabel) {
    const textColor = getComputedStyle(document.documentElement).getPropertyValue('--text-secondary').trim() || '#94a3b8';
    const gridColor = getComputedStyle(document.documentElement).getPropertyValue('--border-primary').trim() || 'rgba(148,163,184,0.12)';
    return {
      responsive: true,
      maintainAspectRatio: false,
      indexAxis: 'y',
      plugins: {
        legend: { display: false },
        tooltip: {
          backgroundColor: 'rgba(17,24,39,0.95)', titleColor: '#f0f4f8', bodyColor: '#94a3b8',
          borderColor: 'rgba(148,163,184,0.2)', borderWidth: 1, cornerRadius: 8,
          bodyFont: { family: 'JetBrains Mono', size: 12 },
        },
      },
      scales: {
        x: { title: { display: true, text: yLabel, color: textColor, font: { size: 11 } }, ticks: { color: textColor }, grid: { color: gridColor } },
        y: { ticks: { color: textColor, font: { size: 11, family: 'Inter' } }, grid: { display: false } },
      },
    };
  }

  // ── API-mode renderers (pre-computed data) ─────────────────

  function renderHeatmapFromData(matrix, factors) {
    const container = document.getElementById('corr-heatmap');
    const n = factors.length;
    const shortNames = ['MOM', 'MR5d', 'VOL', 'RSI', 'EARN'];

    container.style.gridTemplateColumns = `80px repeat(${n}, 1fr)`;

    let html = '<div class="heatmap-cell heatmap-header"></div>';
    for (let j = 0; j < n; j++) {
      html += `<div class="heatmap-cell heatmap-header">${shortNames[j] || factors[j]}</div>`;
    }

    for (let i = 0; i < n; i++) {
      html += `<div class="heatmap-cell heatmap-header">${shortNames[i] || factors[i]}</div>`;
      for (let j = 0; j < n; j++) {
        const val = D.sanitizeNumber(matrix[i][j], 0);
        const color = corrColor(val);
        const textColor = Math.abs(val) > 0.5 ? '#fff' : 'var(--text-primary)';
        html += `<div class="heatmap-cell" style="background:${color};color:${textColor};" title="${factors[i]} vs ${factors[j]}: ${val.toFixed(3)}">${val.toFixed(2)}</div>`;
      }
    }

    container.innerHTML = html;
  }

  function renderICChartFromData(icValues, factors) {
    if (!window.CHARTJS_LOADED) {
      document.getElementById('corr-ic-fallback').classList.remove('hidden');
      document.getElementById('corr-ic-chart').classList.add('hidden');
      return;
    }

    const values = icValues.map(v => D.sanitizeNumber(v * 100, 0));

    if (icChart) icChart.destroy();
    const ctx = document.getElementById('corr-ic-chart').getContext('2d');
    document.getElementById('corr-ic-chart').classList.remove('hidden');
    document.getElementById('corr-ic-fallback').classList.add('hidden');

    icChart = new Chart(ctx, {
      type: 'bar',
      data: {
        labels: factors,
        datasets: [{
          label: 'IC (%)',
          data: values,
          backgroundColor: values.map(v => v >= 0 ? 'rgba(99,102,241,0.7)' : 'rgba(239,68,68,0.7)'),
          borderColor: values.map(v => v >= 0 ? '#6366f1' : '#ef4444'),
          borderWidth: 1,
          borderRadius: 4,
        }]
      },
      options: barOptions('Information Coefficient (%)')
    });
  }

  function renderTurnoverChartFromData(turnoverValues, factors) {
    if (!window.CHARTJS_LOADED) {
      document.getElementById('corr-turnover-fallback').classList.remove('hidden');
      document.getElementById('corr-turnover-chart').classList.add('hidden');
      return;
    }

    const values = turnoverValues.map(v => D.sanitizeNumber(v * 100, 30));

    if (turnoverChart) turnoverChart.destroy();
    const ctx = document.getElementById('corr-turnover-chart').getContext('2d');
    document.getElementById('corr-turnover-chart').classList.remove('hidden');
    document.getElementById('corr-turnover-fallback').classList.add('hidden');

    turnoverChart = new Chart(ctx, {
      type: 'bar',
      data: {
        labels: factors,
        datasets: [{
          label: 'Turnover (%)',
          data: values,
          backgroundColor: 'rgba(139,92,246,0.6)',
          borderColor: '#8b5cf6',
          borderWidth: 1,
          borderRadius: 4,
        }]
      },
      options: barOptions('Portfolio Turnover (%)')
    });
  }

  window.CorrelationModule = { init, render };
})();
