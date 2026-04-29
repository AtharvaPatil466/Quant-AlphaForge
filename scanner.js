/* ============================================================
   AlphaForge — Signal Scanner (Module 2) — Terminal Edition
   Sorting, composite bars, staggered animations, pagination, stats
   ============================================================ */

(function () {
  const D = window.AlphaData;
  let currentFilter = 'all';
  let currentSort = { col: 'composite', dir: 'desc' };
  let allRows = [];
  let filteredRows = [];
  let currentPage = 1;
  const PAGE_SIZE = 15;
  let lastScanTime = null;

  function init() {
    // Scan button
    document.getElementById('scanner-refresh').addEventListener('click', () => {
      refreshScan();
    });

    // Filter pills
    document.querySelectorAll('.filter-pill').forEach(pill => {
      pill.addEventListener('click', () => {
        document.querySelectorAll('.filter-pill').forEach(p => p.classList.remove('active'));
        pill.classList.add('active');
        currentFilter = pill.dataset.filter;
        currentPage = 1;
        applyFilterAndRender();
      });
    });

    // Column sorting
    document.querySelectorAll('.signal-table th[data-col]').forEach(th => {
      th.addEventListener('click', () => {
        const col = th.dataset.col;
        if (currentSort.col === col) {
          currentSort.dir = currentSort.dir === 'desc' ? 'asc' : 'desc';
        } else {
          currentSort.col = col;
          currentSort.dir = 'desc';
        }
        applySortAndRender();
        updateSortIndicators();
      });
    });

    // Init detail panel
    initDetailPanel();
  }

  function refreshScan() {
    const B = window.AlphaBackend;
    if (B && B.isApiMode()) {
      refreshScanAPI();
    } else {
      refreshScanLocal();
    }
  }

  async function refreshScanAPI() {
    const state = window.AlphaApp.getState();
    const sub = document.getElementById('scanner-subtitle');
    if (sub) sub.textContent = `Fetching from Python API... · ${state.lookback}-day lookback`;

    try {
      const data = await window.AlphaBackend.fetchScanner(state.sector, state.lookback);
      allRows = data.map(r => ({
        ticker: r.ticker,
        name: r.name,
        composite: D.sanitizeNumber(r.composite, 0),
        signal: r.signal,
        ret5d: r.ret5d,
        volume: r.volume,
        momentum: D.sanitizeNumber((r.factor_scores || {})['Momentum (12-1)'], 0),
        meanrev: D.sanitizeNumber((r.factor_scores || {})['Mean Reversion (5d)'], 0),
        volsurge: D.sanitizeNumber((r.factor_scores || {})['Volume Surge'], 0),
        rsidiv: D.sanitizeNumber((r.factor_scores || {})['RSI Divergence'], 0),
        earndrift: D.sanitizeNumber((r.factor_scores || {})['Earnings Drift'], 0),
      }));
      if (sub) sub.textContent = `Python API · ${state.lookback}-day lookback`;
    } catch (err) {
      window.AlphaApp.showToast('API error: ' + err.message, 'error');
      if (sub) sub.textContent = `API error — falling back to local`;
      refreshScanLocal();
      return;
    }

    lastScanTime = new Date();
    currentPage = 1;
    applySortAndRender();
    updateStats();
    updateSortIndicators();
  }

  function refreshScanLocal() {
    const state = window.AlphaApp.getState();
    const dataset = D.generateDataset(state.sector, state.lookback);
    const scores = D.computeFactorScores(dataset, state.lookback);

    // Update subtitle
    const sub = document.getElementById('scanner-subtitle');
    if (sub) sub.textContent = `Real-time factor-based signal screening across the equity universe · ${state.lookback}-day lookback`;

    // Build row data
    const tickers = Object.keys(dataset);
    allRows = tickers.map(ticker => {
      const s = scores[ticker];
      const d = dataset[ticker];
      const p = d.prices;
      const n = p.length;
      const ret5d = D.safeDiv(p[n - 1] - p[Math.max(0, n - 6)], p[Math.max(0, n - 6)], 0);
      const volume = d.volumes[n - 1];
      return {
        ticker,
        name: d.name,
        composite: D.sanitizeNumber(s._composite, 0),
        signal: s._signal,
        ret5d,
        volume,
        momentum: D.sanitizeNumber(s['Momentum (12-1)'], 0),
        meanrev: D.sanitizeNumber(s['Mean Reversion (5d)'], 0),
        volsurge: D.sanitizeNumber(s['Volume Surge'], 0),
        rsidiv: D.sanitizeNumber(s['RSI Divergence'], 0),
        earndrift: D.sanitizeNumber(s['Earnings Drift'], 0),
      };
    });

    lastScanTime = new Date();
    currentPage = 1;
    applySortAndRender();
    updateStats();
    updateSortIndicators();
  }

  function updateStats() {
    const longs = allRows.filter(r => r.signal === 'LONG');
    const shorts = allRows.filter(r => r.signal === 'SHORT');
    const neutrals = allRows.filter(r => r.signal === 'NEUTRAL');

    document.getElementById('stat-long-count').textContent = longs.length;
    document.getElementById('stat-long-tickers').textContent = longs.length ? longs.slice(0, 5).map(r => r.ticker).join(', ') : '—';

    document.getElementById('stat-short-count').textContent = shorts.length;
    document.getElementById('stat-short-tickers').textContent = shorts.length ? shorts.slice(0, 5).map(r => r.ticker).join(', ') : '—';

    document.getElementById('stat-neutral-count').textContent = neutrals.length;
    document.getElementById('stat-neutral-tickers').textContent = neutrals.length ? neutrals.slice(0, 5).map(r => r.ticker).join(', ') : '—';

    const absScores = allRows.map(r => Math.abs(r.composite));
    const avg = D.mean(absScores);
    const sd = D.stddev(absScores);
    document.getElementById('stat-avg-score').textContent = avg.toFixed(1);
    document.getElementById('stat-avg-detail').textContent = `σ = ${sd.toFixed(1)}`;
  }

  function applySortAndRender() {
    // Sort
    const col = currentSort.col;
    const dir = currentSort.dir === 'asc' ? 1 : -1;

    allRows.sort((a, b) => {
      let va = a[col], vb = b[col];
      if (typeof va === 'string') return dir * va.localeCompare(vb);
      return dir * (va - vb);
    });

    applyFilterAndRender();
  }

  function applyFilterAndRender() {
    if (currentFilter === 'all') {
      filteredRows = allRows.slice();
    } else {
      filteredRows = allRows.filter(r => r.signal === currentFilter);
    }
    renderTable();
  }

  function renderTable() {
    const tbody = document.getElementById('scanner-tbody');
    const totalPages = Math.max(1, Math.ceil(filteredRows.length / PAGE_SIZE));
    if (currentPage > totalPages) currentPage = totalPages;

    const start = (currentPage - 1) * PAGE_SIZE;
    const pageRows = filteredRows.slice(start, start + PAGE_SIZE);
    const maxAbsScore = Math.max(1, ...allRows.map(r => Math.abs(r.composite)));

    tbody.innerHTML = pageRows.map((r, idx) => {
      const barWidth = Math.min(50, (Math.abs(r.composite) / maxAbsScore) * 50);
      const barClass = r.composite >= 0 ? 'positive' : 'negative';
      const barStyle = r.composite >= 0
        ? `left:50%;width:${barWidth}%`
        : `right:50%;width:${barWidth}%`;

      const scoreClass = r.composite >= 0 ? 'pos' : 'neg';
      const sigClass = r.signal.toLowerCase();
      const retClass = r.ret5d > 0 ? 'ret-pos' : r.ret5d < 0 ? 'ret-neg' : '';

      return `<tr style="animation-delay: ${idx * 30}ms">
        <td class="ticker-cell">${r.ticker}</td>
        <td class="name-cell">${r.name}</td>
        <td class="composite-cell">
          <div class="composite-bar-wrapper">
            <div class="composite-bar-track">
              <div class="composite-bar-center"></div>
              <div class="composite-bar-fill ${barClass}" style="${barStyle}"></div>
            </div>
            <span class="composite-value ${scoreClass}">${r.composite > 0 ? '+' : ''}${r.composite.toFixed(1)}</span>
          </div>
        </td>
        <td><span class="signal-badge ${sigClass}"><span class="signal-badge-dot"></span> ${r.signal}</span></td>
        <td class="${retClass}">${r.ret5d > 0 ? '+' : ''}${(r.ret5d * 100).toFixed(2)}%</td>
        <td>${(r.volume / 1e6).toFixed(1)}</td>
        <td class="${zClass(r.momentum)}">${fmtZ(r.momentum)}</td>
        <td class="${zClass(r.meanrev)}">${fmtZ(r.meanrev)}</td>
        <td class="${zClass(r.volsurge)}">${fmtZ(r.volsurge)}</td>
        <td class="${zClass(r.rsidiv)}">${fmtZ(r.rsidiv)}</td>
        <td class="${zClass(r.earndrift)}">${fmtZ(r.earndrift)}</td>
      </tr>`;
    }).join('');

    // Footer
    const scanTimeStr = lastScanTime ? lastScanTime.toLocaleTimeString('en-US', { hour12: false }) : '--:--:--';
    document.getElementById('table-footer-info').textContent =
      `Showing ${pageRows.length} of ${filteredRows.length} signals · Last scan ${scanTimeStr}`;

    renderPagination(totalPages);
    attachRowClickHandlers();
  }

  function renderPagination(totalPages) {
    const container = document.getElementById('table-pagination');
    if (totalPages <= 1) { container.innerHTML = ''; return; }

    let html = '';
    for (let i = 1; i <= Math.min(totalPages, 5); i++) {
      html += `<button class="page-btn ${i === currentPage ? 'active' : ''}" data-page="${i}">${i}</button>`;
    }
    if (totalPages > 5) {
      html += `<button class="page-btn" data-page="${Math.min(currentPage + 1, totalPages)}">›</button>`;
    }
    container.innerHTML = html;

    container.querySelectorAll('.page-btn').forEach(btn => {
      btn.addEventListener('click', () => {
        currentPage = parseInt(btn.dataset.page);
        renderTable();
      });
    });
  }

  function updateSortIndicators() {
    document.querySelectorAll('.signal-table th[data-col]').forEach(th => {
      th.classList.remove('sorted');
      const arrow = th.querySelector('.sort-arrow');
      if (arrow) arrow.textContent = '↕';
    });
    const activeTh = document.querySelector(`.signal-table th[data-col="${currentSort.col}"]`);
    if (activeTh) {
      activeTh.classList.add('sorted');
      const arrow = activeTh.querySelector('.sort-arrow');
      if (arrow) arrow.textContent = currentSort.dir === 'asc' ? '↑' : '↓';
    }
  }

  function zClass(val) {
    if (val > 0.3) return 'zscore-pos';
    if (val < -0.3) return 'zscore-neg';
    return 'zscore-zero';
  }

  function fmtZ(val) {
    return (val > 0 ? '+' : '') + val.toFixed(2);
  }

  // ── Ticker Detail Panel ─────────────────────────────────────

  let detailPriceChart = null;
  let detailVolumeChart = null;

  function initDetailPanel() {
    document.getElementById('detail-close').addEventListener('click', closeDetail);
    document.getElementById('detail-backdrop').addEventListener('click', closeDetail);
    document.addEventListener('keydown', (e) => {
      if (e.key === 'Escape') closeDetail();
    });
  }

  function openDetail(ticker) {
    const row = allRows.find(r => r.ticker === ticker);
    if (!row) return;

    const panel = document.getElementById('ticker-detail-panel');
    document.getElementById('detail-ticker').textContent = row.ticker;
    document.getElementById('detail-name').textContent = row.name;

    // Signal badge
    const badge = document.getElementById('detail-signal');
    badge.textContent = row.signal;
    badge.className = 'signal-badge ' + row.signal.toLowerCase();

    // Composite
    const comp = document.getElementById('detail-composite');
    comp.textContent = (row.composite > 0 ? '+' : '') + row.composite.toFixed(1);
    comp.style.color = row.composite > 0 ? 'var(--green)' : row.composite < 0 ? 'var(--red)' : 'var(--text-dim)';

    // Factor breakdown
    const factors = [
      { name: 'Momentum (12-1)', value: row.momentum },
      { name: 'Mean Reversion', value: row.meanrev },
      { name: 'Volume Surge', value: row.volsurge },
      { name: 'RSI Divergence', value: row.rsidiv },
      { name: 'Earnings Drift', value: row.earndrift },
    ];
    const factorGrid = document.getElementById('detail-factors');
    factorGrid.innerHTML = factors.map(f => {
      const cls = f.value > 0.3 ? 'pos' : f.value < -0.3 ? 'neg' : 'zero';
      const barWidth = Math.min(50, Math.abs(f.value) * 15) + '%';
      const barCls = f.value >= 0 ? 'pos' : 'neg';
      return `<div class="detail-factor-item">
        <div class="detail-factor-name">${f.name}</div>
        <div class="detail-factor-bar-wrap">
          <div class="detail-factor-bar ${barCls}" style="width:${barWidth}"></div>
        </div>
        <div class="detail-factor-value ${cls}">${fmtZ(f.value)}</div>
      </div>`;
    }).join('');

    // Generate price/volume charts from synthetic data if available
    renderDetailCharts(row.ticker);

    panel.classList.add('open');
  }

  function closeDetail() {
    document.getElementById('ticker-detail-panel').classList.remove('open');
    if (detailPriceChart) { detailPriceChart.destroy(); detailPriceChart = null; }
    if (detailVolumeChart) { detailVolumeChart.destroy(); detailVolumeChart = null; }
  }

  function renderDetailCharts(ticker) {
    if (typeof Chart === 'undefined') return;

    const D = window.AlphaData;
    const state = window.AlphaApp.getState();
    let prices = [], volumes = [];

    // Try to get data from the dataset
    try {
      const dataset = D.generateDataset(state.sector, state.lookback);
      if (dataset[ticker]) {
        prices = dataset[ticker].prices.slice(-60);
        volumes = dataset[ticker].volumes.slice(-60);
      }
    } catch (e) {
      // Use simple synthetic data as fallback
      const seed = ticker.split('').reduce((a, c) => a + c.charCodeAt(0), 0);
      let p = 100;
      for (let i = 0; i < 60; i++) {
        p *= 1 + (Math.sin(seed + i * 0.3) * 0.02);
        prices.push(p);
        volumes.push(1e6 + Math.abs(Math.sin(seed + i * 0.7)) * 3e6);
      }
    }

    if (prices.length === 0) return;
    const labels = prices.map((_, i) => 'D-' + (prices.length - i));

    // Destroy existing charts
    if (detailPriceChart) { detailPriceChart.destroy(); }
    if (detailVolumeChart) { detailVolumeChart.destroy(); }

    const chartDefaults = {
      plugins: { legend: { display: false } },
      scales: {
        x: { display: false },
        y: { grid: { color: 'rgba(255,255,255,0.04)' }, ticks: { font: { size: 9 } } }
      },
      elements: { point: { radius: 0 } },
      animation: { duration: 600 }
    };

    // Price chart
    const priceUp = prices[prices.length - 1] >= prices[0];
    detailPriceChart = new Chart(document.getElementById('detail-price-chart'), {
      type: 'line',
      data: {
        labels,
        datasets: [{
          data: prices,
          borderColor: priceUp ? '#00e676' : '#ff3d57',
          backgroundColor: priceUp ? 'rgba(0,230,118,0.08)' : 'rgba(255,61,87,0.08)',
          fill: true, tension: 0.3, borderWidth: 2,
        }]
      },
      options: chartDefaults,
    });

    // Volume chart
    detailVolumeChart = new Chart(document.getElementById('detail-volume-chart'), {
      type: 'bar',
      data: {
        labels,
        datasets: [{
          data: volumes.map(v => v / 1e6),
          backgroundColor: 'rgba(68,138,255,0.4)',
          borderColor: 'rgba(68,138,255,0.6)',
          borderWidth: 1, borderRadius: 2,
        }]
      },
      options: { ...chartDefaults, scales: { ...chartDefaults.scales, y: { ...chartDefaults.scales.y, title: { display: true, text: 'Vol (M)', font: { size: 9 } } } } },
    });
  }

  // Attach row click handlers after rendering
  function attachRowClickHandlers() {
    document.querySelectorAll('#scanner-tbody tr').forEach(tr => {
      tr.addEventListener('click', () => {
        const tickerCell = tr.querySelector('.ticker-cell');
        if (tickerCell) openDetail(tickerCell.textContent);
      });
    });
  }

  window.ScannerModule = { init, refreshScan };
})();
