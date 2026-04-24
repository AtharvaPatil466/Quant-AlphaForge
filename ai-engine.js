/* ============================================================
   AlphaForge — AI Alpha Engine (Module 4)
   ============================================================ */

(function () {
  const D = window.AlphaData;
  let previewChart = null;
  let hypothesisLibrary = [];

  function init() {
    // Load saved API key and library
    const savedKey = sessionStorage.getItem('alphaforge_api_key');
    if (savedKey) document.getElementById('ai-api-key').value = savedKey;

    const savedLib = sessionStorage.getItem('alphaforge_hypotheses');
    if (savedLib) {
      try { hypothesisLibrary = JSON.parse(savedLib); } catch (e) { hypothesisLibrary = []; }
    }
    renderLibrary();

    document.getElementById('ai-api-key').addEventListener('change', () => {
      sessionStorage.setItem('alphaforge_api_key', document.getElementById('ai-api-key').value);
    });

    document.getElementById('ai-generate').addEventListener('click', generateSignal);
  }

  async function generateSignal() {
    const hypothesis = document.getElementById('ai-hypothesis').value.trim();
    if (!hypothesis) {
      window.AlphaApp.showToast('Please enter an investment hypothesis', 'warning');
      return;
    }

    const apiKey = document.getElementById('ai-api-key').value.trim();
    const spinner = document.getElementById('ai-spinner');
    const btn = document.getElementById('ai-generate');

    btn.disabled = true;
    spinner.classList.remove('hidden');

    try {
      let spec;
      if (apiKey) {
        spec = await callClaudeAPI(apiKey, hypothesis);
      } else {
        // Demo mode
        spec = generateDemoSpec(hypothesis);
        await delay(1500); // Simulate API delay
      }

      renderSpec(spec);
      renderPreviewChart(spec);
      saveToLibrary(hypothesis, spec);

      document.getElementById('ai-output-section').classList.remove('hidden');
    } catch (err) {
      window.AlphaApp.showToast('AI generation failed: ' + (err.message || 'Unknown error'), 'error');
      console.error('AI Engine error:', err);
    } finally {
      btn.disabled = false;
      spinner.classList.add('hidden');
    }
  }

  async function callClaudeAPI(apiKey, hypothesis) {
    const systemPrompt = `You are a quantitative finance research assistant. Given an investment hypothesis, produce a structured signal specification as JSON with these exact keys:
{
  "signalName": "Short descriptive signal name",
  "universe": "Target equity universe",
  "construction": "Step-by-step signal construction methodology",
  "expectedEdge": "Why this signal should generate alpha",
  "risks": "Key risk factors and failure modes",
  "expectedIC": 0.05,
  "holdingPeriod": "5-10 days",
  "holdingDays": 7,
  "rebalanceFrequency": "Weekly"
}
Respond ONLY with valid JSON. expectedIC should be a number between 0 and 0.15.`;

    const response = await fetch('https://api.anthropic.com/v1/messages', {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        'x-api-key': apiKey,
        'anthropic-version': '2023-06-01',
        'anthropic-dangerous-direct-browser-access': 'true',
      },
      body: JSON.stringify({
        model: 'claude-sonnet-4-20250514',
        max_tokens: 1024,
        system: systemPrompt,
        messages: [{ role: 'user', content: hypothesis }],
      }),
    });

    if (!response.ok) {
      const errBody = await response.text();
      throw new Error(`API ${response.status}: ${errBody.slice(0, 200)}`);
    }

    const data = await response.json();
    const text = data.content[0].text;

    // Extract JSON from response
    const jsonMatch = text.match(/\{[\s\S]*\}/);
    if (!jsonMatch) throw new Error('Could not parse AI response as JSON');

    return JSON.parse(jsonMatch[0]);
  }

  function generateDemoSpec(hypothesis) {
    const rng = D.mulberry32(D.hashString(hypothesis));
    const ic = 0.02 + rng() * 0.08;
    const holdDays = Math.floor(3 + rng() * 17);

    const templates = [
      { name: 'Momentum Squeeze Alpha', universe: 'US Large-Cap Equities (S&P 500)' },
      { name: 'Earnings Surprise Drift', universe: 'US Mid/Large-Cap Equities' },
      { name: 'Volume Dislocation Signal', universe: 'US Equity Universe (Russell 1000)' },
      { name: 'Cross-Sectional Mean Reversion', universe: 'US Sector ETFs + Components' },
      { name: 'Sentiment-Driven Short Squeeze', universe: 'US Small/Mid-Cap High Short Interest' },
    ];
    const tpl = templates[Math.floor(rng() * templates.length)];

    return {
      signalName: tpl.name,
      universe: tpl.universe,
      construction: `1. Screen universe for stocks matching hypothesis criteria.\n2. Compute cross-sectional z-scores for the primary factor.\n3. Apply momentum/mean-reversion overlay based on recent price action.\n4. Rank by composite signal score; go long top decile, short bottom decile.\n5. Rebalance at ${holdDays}-day frequency with 2% position caps.`,
      expectedEdge: `The hypothesis targets a well-documented behavioral bias in equity markets. Historical backtests suggest the signal captures mis-pricing during regime transitions, particularly around information events. The edge decays over ${holdDays + 5}+ days, supporting the recommended holding period.`,
      risks: `1. Factor crowding — widespread adoption reduces expected alpha.\n2. Regime sensitivity — signal may reverse during risk-off environments.\n3. Liquidity risk — small-cap names may have insufficient volume for institutional sizing.\n4. Transaction costs — high turnover erodes net returns at scale.`,
      expectedIC: D.sanitizeNumber(ic, 0.04),
      holdingPeriod: `${holdDays} days`,
      holdingDays: holdDays,
      rebalanceFrequency: holdDays <= 5 ? 'Daily' : holdDays <= 15 ? 'Weekly' : 'Bi-weekly',
    };
  }

  function renderSpec(spec) {
    const fields = [
      ['Signal Name', spec.signalName || '—'],
      ['Universe', spec.universe || '—'],
      ['Construction', spec.construction || '—'],
      ['Expected Edge', spec.expectedEdge || '—'],
      ['Risks', spec.risks || '—'],
      ['Rebalance', spec.rebalanceFrequency || '—'],
    ];

    const content = document.getElementById('ai-spec-content');
    content.innerHTML = fields.map(([label, value]) =>
      `<div class="ai-spec-label">${label}</div><div class="ai-spec-value">${escapeHtml(value).replace(/\n/g, '<br>')}</div>`
    ).join('');

    // Metric cards
    const icEl = document.getElementById('ai-ic');
    const ic = D.sanitizeNumber(spec.expectedIC, 0);
    icEl.textContent = (ic * 100).toFixed(1) + '%';
    icEl.className = 'metric-value ' + (ic > 0.03 ? 'positive' : 'neutral');

    document.getElementById('ai-hold').textContent = spec.holdingPeriod || '—';
    document.getElementById('ai-hold').className = 'metric-value neutral';

    const nameEl = document.getElementById('ai-name');
    nameEl.textContent = spec.signalName || '—';
    nameEl.className = 'metric-value neutral';
    nameEl.style.fontSize = '1rem';
  }

  function renderPreviewChart(spec) {
    if (!window.CHARTJS_LOADED) {
      document.getElementById('ai-preview-fallback').classList.remove('hidden');
      document.getElementById('ai-preview-chart').classList.add('hidden');
      return;
    }

    const days = 252;
    const seed = D.hashString(spec.signalName || 'demo');
    const rng = D.mulberry32(seed);
    const ic = D.sanitizeNumber(spec.expectedIC, 0.03);
    const dailyAlpha = ic * 0.01;

    // Generate simulated NAV for this signal
    const nav = [100];
    const bench = [100];
    for (let i = 1; i <= days; i++) {
      const noise = (rng() - 0.5) * 0.03;
      const alpha = dailyAlpha + noise;
      nav.push(Math.max(0.01, nav[i - 1] * (1 + D.clamp(alpha, -0.08, 0.08))));
      const bNoise = (rng() - 0.5) * 0.015;
      bench.push(Math.max(0.01, bench[i - 1] * (1 + bNoise)));
    }

    const labels = D.generateDateLabels(days);

    if (previewChart) previewChart.destroy();
    const ctx = document.getElementById('ai-preview-chart').getContext('2d');
    document.getElementById('ai-preview-chart').classList.remove('hidden');
    document.getElementById('ai-preview-fallback').classList.add('hidden');

    const textColor = getComputedStyle(document.documentElement).getPropertyValue('--text-secondary').trim() || '#94a3b8';
    const gridColor = getComputedStyle(document.documentElement).getPropertyValue('--border-primary').trim() || 'rgba(148,163,184,0.12)';

    previewChart = new Chart(ctx, {
      type: 'line',
      data: {
        labels,
        datasets: [
          { label: 'AI Signal NAV', data: nav, borderColor: '#8b5cf6', backgroundColor: 'rgba(139,92,246,0.08)', borderWidth: 2, fill: true, pointRadius: 0, tension: 0.3 },
          { label: 'Benchmark', data: bench, borderColor: '#64748b', borderWidth: 1.5, borderDash: [5, 5], pointRadius: 0, fill: false, tension: 0.3 },
        ]
      },
      options: {
        responsive: true, maintainAspectRatio: false,
        interaction: { intersect: false, mode: 'index' },
        plugins: {
          legend: { labels: { color: textColor, font: { family: 'Inter', size: 11 }, boxWidth: 12 } },
          tooltip: { backgroundColor: 'rgba(17,24,39,0.95)', titleColor: '#f0f4f8', bodyColor: '#94a3b8', cornerRadius: 8 },
        },
        scales: {
          x: { ticks: { color: textColor, font: { size: 10 }, maxTicksLimit: 12, maxRotation: 0 }, grid: { color: gridColor } },
          y: { title: { display: true, text: 'NAV ($)', color: textColor }, ticks: { color: textColor }, grid: { color: gridColor } },
        },
      }
    });
  }

  function saveToLibrary(hypothesis, spec) {
    hypothesisLibrary.unshift({
      hypothesis: hypothesis.slice(0, 120),
      signalName: spec.signalName,
      timestamp: new Date().toLocaleString(),
      spec,
    });
    if (hypothesisLibrary.length > 20) hypothesisLibrary.pop();
    sessionStorage.setItem('alphaforge_hypotheses', JSON.stringify(hypothesisLibrary));
    renderLibrary();
  }

  function renderLibrary() {
    const container = document.getElementById('ai-library');
    if (hypothesisLibrary.length === 0) {
      container.innerHTML = '<p class="text-muted" style="font-size: 0.82rem;">No saved hypotheses yet. Generate a signal spec to save it here.</p>';
      return;
    }
    container.innerHTML = hypothesisLibrary.map((item, idx) =>
      `<div class="hypothesis-item" data-idx="${idx}">
        <div>
          <strong style="color: var(--accent-primary); font-size: 0.82rem;">${escapeHtml(item.signalName)}</strong>
          <div class="text-muted" style="font-size: 0.72rem;">${escapeHtml(item.hypothesis)}...</div>
        </div>
        <span class="text-muted" style="font-size: 0.7rem; white-space: nowrap;">${item.timestamp}</span>
      </div>`
    ).join('');

    container.querySelectorAll('.hypothesis-item').forEach(el => {
      el.addEventListener('click', () => {
        const idx = parseInt(el.dataset.idx);
        const item = hypothesisLibrary[idx];
        if (item) {
          document.getElementById('ai-hypothesis').value = item.hypothesis;
          renderSpec(item.spec);
          renderPreviewChart(item.spec);
          document.getElementById('ai-output-section').classList.remove('hidden');
        }
      });
    });
  }

  function escapeHtml(str) {
    const div = document.createElement('div');
    div.textContent = str;
    return div.innerHTML;
  }

  function delay(ms) {
    return new Promise(resolve => setTimeout(resolve, ms));
  }

  window.AIEngineModule = { init };
})();
