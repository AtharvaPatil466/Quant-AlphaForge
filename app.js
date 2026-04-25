/* ============================================================
   AlphaForge — App State Manager (Terminal Edition)
   Tab switching, workspace controls, live clock, module dispatch
   ============================================================ */

(function () {
  // ── State ──────────────────────────────────────────────────
  const state = {
    sector: 'All',
    lookback: 252,
    activeTab: 'scanner',
    backend: 'api',
  };

  // ── Init ───────────────────────────────────────────────────
  function init() {
    // Chart.js global config
    if (window.CHARTJS_LOADED && typeof Chart !== 'undefined') {
      configureChartDefaults();
    } else {
      window.addEventListener('chartjs-ready', configureChartDefaults);
    }

    bindTabNav();
    bindWorkspaceControls();
    startClock();

    // Initialize modules
    if (window.ScannerModule) window.ScannerModule.init();
    if (window.CorrelationModule) window.CorrelationModule.init();
    if (window.AIEngineModule) window.AIEngineModule.init();
    if (window.MARLModule) window.MARLModule.init();
    if (window.ExecutionModule) window.ExecutionModule.init();

    // Auto-scan on load
    setTimeout(() => {
      if (window.ScannerModule) window.ScannerModule.refreshScan();
    }, 100);
  }

  // ── Chart.js Global Config ─────────────────────────────────
  function configureChartDefaults() {
    if (typeof Chart === 'undefined') return;
    Chart.defaults.font.family = "'JetBrains Mono', monospace";
    Chart.defaults.color = '#6b7280';
    Chart.defaults.responsive = true;
    Chart.defaults.maintainAspectRatio = false;
  }

  // ── Live Clock ─────────────────────────────────────────────
  function startClock() {
    function tick() {
      const now = new Date();
      const estStr = now.toLocaleTimeString('en-US', {
        hour12: false, hour: '2-digit', minute: '2-digit', second: '2-digit',
        timeZone: 'America/New_York'
      });
      const el = document.getElementById('header-clock');
      if (el) el.innerHTML = estStr + ' <span class="tz">EST</span>';
    }
    tick();
    setInterval(tick, 1000);
  }

  // ── Tab Navigation ─────────────────────────────────────────
  function bindTabNav() {
    const tabs = document.querySelectorAll('.tab-btn');
    tabs.forEach(tab => {
      tab.addEventListener('click', () => {
        const target = tab.dataset.tab;
        if (target === state.activeTab) return;

        tabs.forEach(t => {
          t.classList.remove('active');
          t.setAttribute('aria-selected', 'false');
        });
        tab.classList.add('active');
        tab.setAttribute('aria-selected', 'true');

        document.querySelectorAll('.module-panel').forEach(p => p.classList.remove('active'));
        const panel = document.getElementById('panel-' + target);
        if (panel) panel.classList.add('active');

        state.activeTab = target;
        onTabActivated(target);
      });

      tab.addEventListener('keydown', (e) => {
        if (e.key === 'Enter' || e.key === ' ') {
          e.preventDefault();
          tab.click();
        }
      });
    });
  }

  function onTabActivated(tab) {
    switch (tab) {
      case 'scanner':
        if (window.ScannerModule) window.ScannerModule.refreshScan();
        break;
      case 'correlation':
        if (window.CorrelationModule) window.CorrelationModule.render();
        break;
    }
  }

  // ── Workspace Controls ─────────────────────────────────────
  function bindWorkspaceControls() {
    const sectorFilter = document.getElementById('sector-filter');
    const lookbackSlider = document.getElementById('lookback-slider');
    const lookbackValue = document.getElementById('lookback-value');
    const backendToggle = document.getElementById('backend-toggle');
    const backendUrlGroup = document.getElementById('backend-url-group');

    sectorFilter.addEventListener('change', () => {
      state.sector = sectorFilter.value;
      refreshActiveModule();
    });

    lookbackSlider.addEventListener('input', () => {
      let v = parseInt(lookbackSlider.value);
      v = Math.max(21, Math.min(504, v));
      state.lookback = v;
      lookbackValue.textContent = v + 'd';
    });

    lookbackSlider.addEventListener('change', () => {
      refreshActiveModule();
    });

    if (backendToggle) {
      backendToggle.addEventListener('change', () => {
        state.backend = backendToggle.value;
        backendUrlGroup.style.display = backendToggle.value === 'api' ? '' : 'none';
        refreshActiveModule();
      });
    }
  }

  function refreshActiveModule() {
    switch (state.activeTab) {
      case 'scanner':
        if (window.ScannerModule) window.ScannerModule.refreshScan();
        break;
      case 'correlation':
        if (window.CorrelationModule) window.CorrelationModule.render();
        break;
    }
  }

  // ── Toast Notification ─────────────────────────────────────
  function showToast(message, type = 'info') {
    const container = document.getElementById('toast-container');
    const toast = document.createElement('div');
    toast.className = 'toast ' + type;
    toast.textContent = message;
    container.appendChild(toast);
    setTimeout(() => {
      toast.style.opacity = '0';
      toast.style.transform = 'translateX(100%)';
      toast.style.transition = 'all 300ms ease';
      setTimeout(() => toast.remove(), 300);
    }, 4000);
  }

  // ── Public API ─────────────────────────────────────────────
  window.AlphaApp = {
    getState: () => ({ ...state }),
    showToast,
    init,
  };

  // ── Boot ───────────────────────────────────────────────────
  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }
})();
