/* ============================================================
   AlphaForge — Live Paper Trading Module
   Polls execution API for portfolio state, orders, and status
   ============================================================ */

(function () {
  var navChart = null;
  var pollTimer = null;
  var connected = false;

  function init() {
    document.getElementById('exec-connect').addEventListener('click', connect);
    document.getElementById('exec-halt').addEventListener('click', haltTrading);
    document.getElementById('exec-resume').addEventListener('click', resumeTrading);
    // Show demo data so the tab isn't empty
    setTimeout(renderDemoNavChart, 600);
  }

  function renderDemoNavChart() {
    if (typeof Chart === 'undefined' || navChart) return;

    // Generate synthetic NAV curve (252 trading days)
    var dates = [], navs = [], dds = [];
    var nav = 100000, peak = nav;
    for (var i = 0; i < 252; i++) {
      var d = new Date(2025, 0, 2 + i);
      dates.push(d.toISOString().slice(0, 10));
      var ret = (Math.sin(i * 0.05) * 0.008) + 0.0002 + (Math.cos(i * 0.12) * 0.004);
      nav *= (1 + ret);
      if (nav > peak) peak = nav;
      var dd = (peak - nav) / peak;
      navs.push(parseFloat(nav.toFixed(0)));
      dds.push(parseFloat((-dd * 100).toFixed(2)));
    }

    // Update stat cards
    document.getElementById('exec-nav').textContent = '$' + navs[251].toLocaleString();
    document.getElementById('exec-nav-detail').textContent = dates[251] + ' (demo)';
    var totalRet = (navs[251] / 100000 - 1);
    document.getElementById('exec-sharpe').textContent = '1.24';
    document.getElementById('exec-sharpe').className = 'stat-value positive';
    document.getElementById('exec-sharpe-detail').textContent = (totalRet > 0 ? '+' : '') + (totalRet * 100).toFixed(2) + '% return';
    document.getElementById('exec-drawdown').textContent = '4.12%';
    document.getElementById('exec-drawdown').className = 'stat-value positive';
    document.getElementById('exec-winrate').textContent = '53.2%';
    document.getElementById('exec-winrate-detail').textContent = '134/252 days';

    // Render NAV chart
    var ctx = document.getElementById('exec-nav-chart');
    navChart = new Chart(ctx, {
      type: 'line',
      data: {
        labels: dates,
        datasets: [
          { label: 'NAV ($)', data: navs, borderColor: '#00e676', backgroundColor: 'rgba(0,230,118,0.08)', fill: true, tension: 0.3, pointRadius: 0, borderWidth: 2, yAxisID: 'y' },
          { label: 'Drawdown (%)', data: dds, borderColor: '#ff3d57', backgroundColor: 'rgba(255,61,87,0.08)', fill: true, tension: 0.3, pointRadius: 0, borderWidth: 1.5, yAxisID: 'y1' },
        ],
      },
      options: {
        plugins: { legend: { labels: { font: { size: 10 }, boxWidth: 12, padding: 8 } } },
        scales: {
          x: { title: { display: true, text: 'Date', font: { size: 10 } }, grid: { color: 'rgba(255,255,255,0.04)' }, ticks: { maxTicksLimit: 12, font: { size: 9 } } },
          y: { type: 'linear', position: 'left', title: { display: true, text: 'NAV ($)', font: { size: 10 } }, grid: { color: 'rgba(255,255,255,0.04)' } },
          y1: { type: 'linear', position: 'right', title: { display: true, text: 'Drawdown (%)', font: { size: 10 } }, grid: { drawOnChartArea: false } },
        },
      },
    });

    // Circuit breakers demo
    document.getElementById('exec-cb-daily').textContent = '+0.34% daily';
    document.getElementById('exec-cb-daily').style.color = 'var(--green)';
    document.getElementById('exec-cb-dd').textContent = '4.12% drawdown';
    document.getElementById('exec-cb-dd').style.color = 'var(--green)';
    document.getElementById('exec-cb-status').textContent = 'ALL CLEAR';
    document.getElementById('exec-cb-status').style.color = 'var(--green)';
  }

  function getBaseUrl() {
    return (document.getElementById('exec-url').value || 'http://localhost:8002').replace(/\/+$/, '');
  }

  // ── Connection ──────────────────────────────────────────────

  async function connect() {
    var url = getBaseUrl();
    try {
      var res = await fetch(url + '/status');
      if (!res.ok) throw new Error('HTTP ' + res.status);
      var data = await res.json();
      connected = true;
      updateConnectionUI(true);
      appendLog('Connected — status: ' + data.status);
      showToast('Connected to execution API', 'success');
      await refresh();
      startPolling();
    } catch (e) {
      connected = false;
      updateConnectionUI(false);
      showToast('Cannot reach API at ' + url, 'error');
      appendLog('Connection failed: ' + e.message);
    }
  }

  function startPolling() {
    stopPolling();
    pollTimer = setInterval(refresh, 15000);
  }

  function stopPolling() {
    if (pollTimer) {
      clearInterval(pollTimer);
      pollTimer = null;
    }
  }

  // ── Data refresh ────────────────────────────────────────────

  async function refresh() {
    if (!connected) return;
    var url = getBaseUrl();
    try {
      var responses = await Promise.all([
        fetch(url + '/status'),
        fetch(url + '/portfolio/history?days=252'),
        fetch(url + '/trades'),
      ]);

      var status = await responses[0].json();
      var history = await responses[1].json();
      var trades = await responses[2].json();

      renderStatus(status);
      renderMetrics(history);
      renderNavChart(history);
      renderPositions(history);
      renderOrders(trades);
    } catch (e) {
      appendLog('Refresh failed: ' + e.message);
    }
  }

  // ── Status ──────────────────────────────────────────────────

  function renderStatus(status) {
    var el = document.getElementById('exec-system-status');
    var dot = document.getElementById('exec-status-dot');

    if (status.halted) {
      el.textContent = 'HALTED';
      el.style.color = 'var(--red)';
      dot.style.background = 'var(--red)';
      document.getElementById('exec-halt-reason').textContent = status.halt_reason || '';
    } else if (status.status === 'running' || status.last_date) {
      el.textContent = 'RUNNING';
      el.style.color = 'var(--green)';
      dot.style.background = 'var(--green)';
      document.getElementById('exec-halt-reason').textContent = '';
    } else {
      el.textContent = 'NO DATA';
      el.style.color = 'var(--text-dim)';
      dot.style.background = 'var(--text-dim)';
      document.getElementById('exec-halt-reason').textContent = '';
    }
  }

  // ── Metrics ─────────────────────────────────────────────────

  function renderMetrics(history) {
    if (!history || history.length === 0) return;

    var latest = history[history.length - 1];

    // NAV
    document.getElementById('exec-nav').textContent = '$' + Number(latest.nav).toLocaleString(undefined, { minimumFractionDigits: 0, maximumFractionDigits: 0 });
    document.getElementById('exec-nav-detail').textContent = latest.date || '';

    // Sharpe
    var sharpe = latest.sharpe_to_date || 0;
    var sharpeEl = document.getElementById('exec-sharpe');
    sharpeEl.textContent = sharpe.toFixed(2);
    sharpeEl.className = 'stat-value ' + (sharpe > 0.5 ? 'positive' : sharpe > 0 ? 'neutral' : 'negative');

    // Max drawdown
    var maxDD = 0;
    for (var i = 0; i < history.length; i++) {
      if ((history[i].drawdown || 0) > maxDD) maxDD = history[i].drawdown;
    }
    var ddEl = document.getElementById('exec-drawdown');
    ddEl.textContent = (maxDD * 100).toFixed(2) + '%';
    ddEl.className = 'stat-value ' + (maxDD < 0.05 ? 'positive' : maxDD < 0.10 ? 'neutral' : 'negative');

    // Win rate
    var wins = 0, total = 0;
    for (var j = 0; j < history.length; j++) {
      if (history[j].daily_return != null) {
        total++;
        if (history[j].daily_return > 0) wins++;
      }
    }
    var wr = total > 0 ? wins / total : 0;
    document.getElementById('exec-winrate').textContent = (wr * 100).toFixed(1) + '%';
    document.getElementById('exec-winrate-detail').textContent = wins + '/' + total + ' days';

    // Total return (in Sharpe detail)
    var totalRet = latest.cumulative_return || 0;
    document.getElementById('exec-sharpe-detail').textContent = (totalRet >= 0 ? '+' : '') + (totalRet * 100).toFixed(2) + '% return';

    // Circuit breaker indicators
    var dailyRet = latest.daily_return || 0;
    var dd = latest.drawdown || 0;

    var cbDailyEl = document.getElementById('exec-cb-daily');
    cbDailyEl.textContent = (dailyRet * 100).toFixed(2) + '% daily';
    cbDailyEl.style.color = dailyRet < -0.02 ? 'var(--red)' : 'var(--green)';

    var cbDDEl = document.getElementById('exec-cb-dd');
    cbDDEl.textContent = (dd * 100).toFixed(2) + '% drawdown';
    cbDDEl.style.color = dd > 0.10 ? 'var(--red)' : 'var(--green)';

    var cbStatusEl = document.getElementById('exec-cb-status');
    if (dailyRet < -0.02 || dd > 0.10) {
      cbStatusEl.textContent = 'TRIGGERED';
      cbStatusEl.style.color = 'var(--red)';
    } else {
      cbStatusEl.textContent = 'ALL CLEAR';
      cbStatusEl.style.color = 'var(--green)';
    }
  }

  // ── NAV Chart ───────────────────────────────────────────────

  function renderNavChart(history) {
    if (typeof Chart === 'undefined' || !history || history.length === 0) {
      var fb = document.getElementById('exec-nav-fallback');
      if (fb) fb.classList.remove('hidden');
      return;
    }

    var dates = history.map(function (h) { return h.date; });
    var navs = history.map(function (h) { return h.nav; });
    var dds = history.map(function (h) { return -(h.drawdown || 0) * 100; });

    var ctx = document.getElementById('exec-nav-chart');
    if (navChart) {
      navChart.data.labels = dates;
      navChart.data.datasets[0].data = navs;
      navChart.data.datasets[1].data = dds;
      navChart.update('none');
    } else {
      navChart = new Chart(ctx, {
        type: 'line',
        data: {
          labels: dates,
          datasets: [
            {
              label: 'NAV ($)',
              data: navs,
              borderColor: '#00e676',
              backgroundColor: 'rgba(0,230,118,0.08)',
              fill: true,
              tension: 0.3,
              pointRadius: 0,
              borderWidth: 2,
              yAxisID: 'y',
            },
            {
              label: 'Drawdown (%)',
              data: dds,
              borderColor: '#ff3d57',
              backgroundColor: 'rgba(255,61,87,0.08)',
              fill: true,
              tension: 0.3,
              pointRadius: 0,
              borderWidth: 1.5,
              yAxisID: 'y1',
            },
          ],
        },
        options: {
          plugins: {
            legend: { labels: { font: { size: 10 }, boxWidth: 12, padding: 8 } },
          },
          scales: {
            x: {
              title: { display: true, text: 'Date', font: { size: 10 } },
              grid: { color: 'rgba(255,255,255,0.04)' },
              ticks: { maxTicksLimit: 12, font: { size: 9 } },
            },
            y: {
              type: 'linear',
              position: 'left',
              title: { display: true, text: 'NAV ($)', font: { size: 10 } },
              grid: { color: 'rgba(255,255,255,0.04)' },
            },
            y1: {
              type: 'linear',
              position: 'right',
              title: { display: true, text: 'Drawdown (%)', font: { size: 10 } },
              grid: { drawOnChartArea: false },
            },
          },
        },
      });
    }
  }

  // ── Positions table ─────────────────────────────────────────

  function renderPositions(history) {
    var tbody = document.getElementById('exec-positions-tbody');
    if (!history || history.length === 0) {
      tbody.innerHTML = '<tr><td colspan="4" style="text-align:center;color:var(--text-dim);">No data</td></tr>';
      return;
    }

    var latest = history[history.length - 1];
    var weights = latest.weights;
    if (typeof weights === 'string') {
      try { weights = JSON.parse(weights); } catch (_) { weights = {}; }
    }
    weights = weights || {};

    var tickers = Object.keys(weights).sort(function (a, b) {
      return Math.abs(weights[b]) - Math.abs(weights[a]);
    });

    if (tickers.length === 0) {
      tbody.innerHTML = '<tr><td colspan="4" style="text-align:center;color:var(--text-dim);">No positions</td></tr>';
      return;
    }

    var html = '';
    for (var i = 0; i < tickers.length; i++) {
      var ticker = tickers[i];
      var w = weights[ticker];
      var side = w > 0 ? 'LONG' : 'SHORT';
      var sideClass = w > 0 ? 'positive' : 'negative';
      var mktVal = Math.abs(w * (latest.nav || 0));
      html += '<tr>' +
        '<td style="font-weight:600;">' + esc(ticker) + '</td>' +
        '<td class="' + sideClass + '">' + side + '</td>' +
        '<td>' + (Math.abs(w) * 100).toFixed(2) + '%</td>' +
        '<td>$' + mktVal.toLocaleString(undefined, { minimumFractionDigits: 0, maximumFractionDigits: 0 }) + '</td>' +
        '</tr>';
    }
    tbody.innerHTML = html;
  }

  // ── Orders table ────────────────────────────────────────────

  function renderOrders(trades) {
    var tbody = document.getElementById('exec-orders-tbody');
    if (!trades || trades.length === 0) {
      tbody.innerHTML = '<tr><td colspan="6" style="text-align:center;color:var(--text-dim);">No orders</td></tr>';
      document.getElementById('exec-orders-count').textContent = '0 orders';
      return;
    }

    var recent = trades.slice(-20).reverse();
    var html = '';
    for (var i = 0; i < recent.length; i++) {
      var t = recent[i];
      var sideClass = t.side === 'BUY' ? 'positive' : 'negative';
      var slippage = t.slippage_bps != null ? Number(t.slippage_bps).toFixed(1) : '—';
      var fillQty = t.fill_quantity != null ? Number(t.fill_quantity).toFixed(2) : '—';
      var fillPx = t.fill_price != null ? '$' + Number(t.fill_price).toFixed(2) : '—';
      html += '<tr>' +
        '<td>' + esc(t.date || '—') + '</td>' +
        '<td style="font-weight:600;">' + esc(t.ticker || '—') + '</td>' +
        '<td class="' + sideClass + '">' + esc(t.side || '—') + '</td>' +
        '<td>' + fillQty + '</td>' +
        '<td>' + fillPx + '</td>' +
        '<td>' + slippage + '</td>' +
        '</tr>';
    }
    tbody.innerHTML = html;
    document.getElementById('exec-orders-count').textContent = trades.length + ' total orders';
  }

  // ── Halt / Resume ───────────────────────────────────────────

  async function haltTrading() {
    var url = getBaseUrl();
    try {
      var res = await fetch(url + '/halt', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ reason: 'Manual halt from UI' }),
      });
      if (res.ok) {
        appendLog('Halt command sent');
        showToast('Trading halted', 'info');
        await refresh();
      }
    } catch (e) {
      showToast('Failed to halt: ' + e.message, 'error');
    }
  }

  async function resumeTrading() {
    var url = getBaseUrl();
    try {
      var res = await fetch(url + '/resume', { method: 'POST' });
      if (res.ok) {
        appendLog('Resume command sent');
        showToast('Trading resumed', 'success');
        await refresh();
      }
    } catch (e) {
      showToast('Failed to resume: ' + e.message, 'error');
    }
  }

  // ── UI helpers ──────────────────────────────────────────────

  function updateConnectionUI(isConnected) {
    var btn = document.getElementById('exec-connect');
    var statusText = document.getElementById('exec-conn-status');
    if (isConnected) {
      btn.textContent = '● Connected';
      btn.style.borderColor = 'var(--green)';
      statusText.textContent = 'Connected';
      statusText.style.color = 'var(--green)';
    } else {
      btn.textContent = '▶ Connect';
      btn.style.borderColor = '';
      statusText.textContent = 'Disconnected';
      statusText.style.color = 'var(--red)';
    }
  }

  function appendLog(msg) {
    var log = document.getElementById('exec-log');
    var now = new Date();
    var ts = now.toLocaleTimeString('en-US', { hour12: false, hour: '2-digit', minute: '2-digit', second: '2-digit' });
    var line = document.createElement('div');
    line.textContent = '[' + ts + '] ' + msg;
    line.style.borderBottom = '1px solid rgba(255,255,255,0.03)';
    line.style.padding = '2px 0';
    log.appendChild(line);
    log.scrollTop = log.scrollHeight;
  }

  function esc(s) {
    var d = document.createElement('div');
    d.textContent = s;
    return d.innerHTML;
  }

  function showToast(msg, type) {
    if (window.AlphaApp && window.AlphaApp.showToast) {
      window.AlphaApp.showToast(msg, type);
    }
  }

  // ── Public API ──────────────────────────────────────────────

  window.ExecutionModule = {
    init: init,
  };
})();
