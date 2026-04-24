/* ============================================================
   AlphaForge — MARL Training Module
   WebSocket-driven live training visualization
   ============================================================ */

(function () {
  let ws = null;
  let fitnessChart = null;
  let sigmaChart = null;
  let history = [];
  let running = false;

  function init() {
    document.getElementById('marl-start').addEventListener('click', startTraining);
    document.getElementById('marl-stop').addEventListener('click', stopTraining);
  }

  // ── API helpers ────────────────────────────────────────────

  function getBaseUrl() {
    return (document.getElementById('marl-url').value || 'http://localhost:8001').replace(/\/+$/, '');
  }

  function getWsUrl() {
    return getBaseUrl().replace(/^http/, 'ws') + '/ws';
  }

  // ── Training control ──────────────────────────────────────

  async function startTraining() {
    const url = getBaseUrl();
    const nGen = parseInt(document.getElementById('marl-generations').value) || 50;

    try {
      const res = await fetch(url + '/train/start', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ n_generations: nGen }),
      });
      const data = await res.json();

      if (data.error) {
        showToast(data.error, 'error');
        return;
      }

      running = true;
      history = [];
      updateUI();
      connectWebSocket();

      document.getElementById('marl-start').disabled = true;
      document.getElementById('marl-stop').disabled = false;
      document.getElementById('marl-status-text').textContent = 'Running...';
      document.getElementById('marl-status-text').style.color = 'var(--green)';
      document.getElementById('marl-gen-detail').textContent = 'of ' + nGen;

      clearLog();
      appendLog('Training started — ' + nGen + ' generations');
      showToast('MARL training started', 'success');
    } catch (e) {
      showToast('Cannot reach MARL API at ' + url, 'error');
    }
  }

  async function stopTraining() {
    const url = getBaseUrl();
    try {
      await fetch(url + '/train/stop', { method: 'POST' });
      running = false;
      updateUI();
      appendLog('Training stop requested');
      showToast('Training stopping...', 'info');
    } catch (e) {
      showToast('Failed to stop training', 'error');
    }
  }

  // ── WebSocket ─────────────────────────────────────────────

  function connectWebSocket() {
    if (ws) {
      try { ws.close(); } catch (_) {}
    }

    const wsUrl = getWsUrl();
    ws = new WebSocket(wsUrl);

    ws.onopen = function () {
      appendLog('WebSocket connected');
    };

    ws.onmessage = function (event) {
      try {
        const msg = JSON.parse(event.data);
        if (msg.type === 'generation') {
          onGenerationUpdate(msg.data);
        }
      } catch (_) {}
    };

    ws.onclose = function () {
      if (running) {
        appendLog('WebSocket disconnected — reconnecting in 2s');
        setTimeout(connectWebSocket, 2000);
      }
    };

    ws.onerror = function () {
      // Fallback: poll status endpoint
      if (running) startPolling();
    };
  }

  // ── Polling fallback ──────────────────────────────────────

  let pollTimer = null;

  function startPolling() {
    if (pollTimer) return;
    appendLog('Falling back to polling mode');
    pollTimer = setInterval(pollStatus, 3000);
  }

  function stopPolling() {
    if (pollTimer) {
      clearInterval(pollTimer);
      pollTimer = null;
    }
  }

  async function pollStatus() {
    const url = getBaseUrl();
    try {
      const res = await fetch(url + '/train/status');
      const data = await res.json();

      if (data.generation > 0 && (history.length === 0 || data.generation > history[history.length - 1].generation)) {
        // Fetch full history to catch up
        const hRes = await fetch(url + '/train/history');
        const hData = await hRes.json();
        if (hData.history && hData.history.length > history.length) {
          var newEntries = hData.history.slice(history.length);
          for (var i = 0; i < newEntries.length; i++) {
            onGenerationUpdate(newEntries[i]);
          }
        }
      }

      if (!data.running && running) {
        running = false;
        updateUI();
        stopPolling();
        appendLog('Training completed');
        showToast('MARL training complete', 'success');
      }
    } catch (_) {}
  }

  // ── Generation update handler ─────────────────────────────

  function onGenerationUpdate(data) {
    history.push(data);

    // Update stat cards
    document.getElementById('marl-gen').textContent = data.generation;
    document.getElementById('marl-best-fitness').textContent = fmt(data.best_fitness);
    document.getElementById('marl-best-agent').textContent = data.best_agent_id || '—';
    document.getElementById('marl-mean-fitness').textContent = fmt(data.mean_fitness);
    document.getElementById('marl-fitness-std').textContent = 'σ = ' + fmt(data.fitness_std);
    document.getElementById('marl-sigma').textContent = fmt(data.sigma, 4);

    // Color best fitness
    var bestEl = document.getElementById('marl-best-fitness');
    bestEl.className = 'stat-value ' + (data.best_fitness > 0 ? 'positive' : data.best_fitness < 0 ? 'negative' : 'neutral');

    // Log
    appendLog(
      'Gen ' + pad(data.generation, 3) +
      ' | best=' + fmt(data.best_fitness) +
      ' | mean=' + fmt(data.mean_fitness) +
      ' | σ_fit=' + fmt(data.fitness_std) +
      ' | σ_mut=' + fmt(data.sigma, 4) +
      ' | ' + (data.best_agent_id || '')
    );

    // Charts
    updateCharts();

    // Check if done
    var nGen = parseInt(document.getElementById('marl-generations').value) || 50;
    if (data.generation >= nGen) {
      running = false;
      updateUI();
      stopPolling();
      appendLog('Training completed — ' + data.generation + ' generations');
      showToast('MARL training complete! Best fitness: ' + fmt(data.best_fitness), 'success');
    }
  }

  // ── Charts ────────────────────────────────────────────────

  function updateCharts() {
    if (typeof Chart === 'undefined') return;

    var gens = history.map(function (h) { return h.generation; });
    var bestFit = history.map(function (h) { return h.best_fitness; });
    var meanFit = history.map(function (h) { return h.mean_fitness; });
    var sigmas = history.map(function (h) { return h.sigma; });
    var fitStds = history.map(function (h) { return h.fitness_std; });

    // Fitness chart
    var ctx1 = document.getElementById('marl-fitness-chart');
    if (fitnessChart) {
      fitnessChart.data.labels = gens;
      fitnessChart.data.datasets[0].data = bestFit;
      fitnessChart.data.datasets[1].data = meanFit;
      fitnessChart.update('none');
    } else {
      fitnessChart = new Chart(ctx1, {
        type: 'line',
        data: {
          labels: gens,
          datasets: [
            {
              label: 'Best Fitness',
              data: bestFit,
              borderColor: '#00e676',
              backgroundColor: 'rgba(0,230,118,0.1)',
              fill: true,
              tension: 0.3,
              pointRadius: 2,
              borderWidth: 2,
            },
            {
              label: 'Mean Fitness',
              data: meanFit,
              borderColor: '#ffab00',
              backgroundColor: 'rgba(255,171,0,0.05)',
              fill: true,
              tension: 0.3,
              pointRadius: 1,
              borderWidth: 1.5,
            },
          ],
        },
        options: {
          plugins: {
            legend: { labels: { font: { size: 10 }, boxWidth: 12, padding: 8 } },
          },
          scales: {
            x: { title: { display: true, text: 'Generation', font: { size: 10 } }, grid: { color: 'rgba(255,255,255,0.04)' } },
            y: { title: { display: true, text: 'Fitness (Sharpe-based)', font: { size: 10 } }, grid: { color: 'rgba(255,255,255,0.04)' } },
          },
        },
      });
    }

    // Sigma chart
    var ctx2 = document.getElementById('marl-sigma-chart');
    if (sigmaChart) {
      sigmaChart.data.labels = gens;
      sigmaChart.data.datasets[0].data = sigmas;
      sigmaChart.data.datasets[1].data = fitStds;
      sigmaChart.update('none');
    } else {
      sigmaChart = new Chart(ctx2, {
        type: 'line',
        data: {
          labels: gens,
          datasets: [
            {
              label: 'Mutation σ',
              data: sigmas,
              borderColor: '#ff3d57',
              backgroundColor: 'rgba(255,61,87,0.1)',
              fill: true,
              tension: 0.3,
              pointRadius: 2,
              borderWidth: 2,
              yAxisID: 'y',
            },
            {
              label: 'Fitness Std',
              data: fitStds,
              borderColor: '#448aff',
              backgroundColor: 'rgba(68,138,255,0.05)',
              fill: true,
              tension: 0.3,
              pointRadius: 1,
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
            x: { title: { display: true, text: 'Generation', font: { size: 10 } }, grid: { color: 'rgba(255,255,255,0.04)' } },
            y: { type: 'linear', position: 'left', title: { display: true, text: 'Mutation σ', font: { size: 10 } }, grid: { color: 'rgba(255,255,255,0.04)' } },
            y1: { type: 'linear', position: 'right', title: { display: true, text: 'Fitness Std', font: { size: 10 } }, grid: { drawOnChartArea: false } },
          },
        },
      });
    }
  }

  // ── UI helpers ─────────────────────────────────────────────

  function updateUI() {
    document.getElementById('marl-start').disabled = running;
    document.getElementById('marl-stop').disabled = !running;
    document.getElementById('marl-status-text').textContent = running ? 'Running...' : 'Idle';
    document.getElementById('marl-status-text').style.color = running ? 'var(--green)' : 'var(--text-secondary)';
  }

  function appendLog(msg) {
    var log = document.getElementById('marl-log');
    var now = new Date();
    var ts = now.toLocaleTimeString('en-US', { hour12: false, hour: '2-digit', minute: '2-digit', second: '2-digit' });
    var line = document.createElement('div');
    line.textContent = '[' + ts + '] ' + msg;
    line.style.borderBottom = '1px solid rgba(255,255,255,0.03)';
    line.style.padding = '2px 0';
    log.appendChild(line);
    log.scrollTop = log.scrollHeight;
  }

  function clearLog() {
    document.getElementById('marl-log').innerHTML = '';
  }

  function fmt(v, decimals) {
    if (v == null || isNaN(v)) return '—';
    return Number(v).toFixed(decimals != null ? decimals : 2);
  }

  function pad(n, width) {
    var s = String(n);
    while (s.length < width) s = ' ' + s;
    return s;
  }

  function showToast(msg, type) {
    if (window.AlphaApp && window.AlphaApp.showToast) {
      window.AlphaApp.showToast(msg, type);
    }
  }

  // ── Public API ─────────────────────────────────────────────

  window.MARLModule = {
    init: init,
  };
})();
