/* ============================================================
   AlphaForge — Python Backend API Client
   Fetches data from the Python FastAPI server when backend mode
   is set to "api". Falls back to local JS computation otherwise.
   ============================================================ */

(function () {
  const PREFIX = '/api/v1';

  function getBaseUrl() {
    const el = document.getElementById('backend-url');
    return el ? el.value.replace(/\/+$/, '') : 'http://localhost:8000';
  }

  function isApiMode() {
    const el = document.getElementById('backend-toggle');
    return el && el.value === 'api';
  }

  async function apiFetch(path, options) {
    const url = getBaseUrl() + PREFIX + path;
    const resp = await fetch(url, options);
    if (!resp.ok) {
      const body = await resp.json().catch(() => ({}));
      throw new Error(body.detail || body.error || `API error ${resp.status}`);
    }
    return resp.json();
  }

  // ── Scanner ────────────────────────────────────────────────
  async function fetchScanner(sector, lookback) {
    const params = new URLSearchParams({ sector, lookback, data_source: 'real' });
    return apiFetch('/scanner?' + params);
  }

  // ── Backtest ───────────────────────────────────────────────
  async function fetchBacktest(config) {
    return apiFetch('/backtest', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        sector: config.sector,
        lookback: config.lookback,
        factor_name: config.factor,
        holding_period: config.holdingPeriod,
        position_size: config.positionSize,
        stop_loss: config.stopLoss,
        tx_cost_bps: config.txCostBps,
        data_source: 'real',
      }),
    });
  }

  // ── Correlation ────────────────────────────────────────────
  async function fetchCorrelation(sector, lookback) {
    const params = new URLSearchParams({ sector, lookback, data_source: 'real' });
    return apiFetch('/correlation?' + params);
  }

  async function fetchMarketAvailability(sector = 'All') {
    const params = new URLSearchParams({ sector });
    return apiFetch('/market/availability?' + params);
  }

  async function fetchLivePrices(sector = 'All') {
    const params = new URLSearchParams({ sector });
    return apiFetch('/market/live-prices?' + params);
  }

  window.AlphaBackend = {
    isApiMode,
    fetchScanner,
    fetchBacktest,
    fetchCorrelation,
    fetchMarketAvailability,
    fetchLivePrices,
  };
})();
