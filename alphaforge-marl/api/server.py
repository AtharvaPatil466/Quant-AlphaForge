"""MARL FastAPI server with training control, monitoring dashboard, and WebSocket broadcast."""

from __future__ import annotations

import asyncio
import json
import logging
import threading
from typing import Any, Dict, List, Optional

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse
from pydantic import BaseModel

from training.trainer import Trainer
from training.config import load_config
from training.walk_forward import WalkForwardValidator, generate_folds, WalkForwardResult
from evolution.evolutionary_engine import GenerationStats

logger = logging.getLogger(__name__)

app = FastAPI(title="AlphaForge MARL", version="2.0.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── Global state ────────────────────────────────────────────────

_trainer: Optional[Trainer] = None
_training_thread: Optional[threading.Thread] = None
_ws_clients: List[WebSocket] = []
_loop: Optional[asyncio.AbstractEventLoop] = None
_wf_result: Optional[WalkForwardResult] = None
_wf_thread: Optional[threading.Thread] = None
_wf_running: bool = False


# ── Pydantic models ────────────────────────────────────────────

class TrainRequest(BaseModel):
    n_generations: int = 50
    config_path: str | None = None


class WalkForwardRequest(BaseModel):
    n_generations: int = 30
    sector: str = "All"
    train_start: str = "2022-01-01"
    train_months: int = 24
    val_months: int = 12
    test_months: int = 12


class TrainStatus(BaseModel):
    generation: int
    running: bool
    best_fitness: float
    mean_fitness: float
    sigma: float
    n_agents: int
    best_agent_id: str | None


class GenerationUpdate(BaseModel):
    generation: int
    best_fitness: float
    mean_fitness: float
    fitness_std: float
    sigma: float
    best_agent_id: str


# ── WebSocket broadcast ────────────────────────────────────────

async def _broadcast(message: dict) -> None:
    """Send message to all connected WebSocket clients."""
    dead = []
    for ws in _ws_clients:
        try:
            await ws.send_json(message)
        except Exception:
            dead.append(ws)
    for ws in dead:
        _ws_clients.remove(ws)


def _on_generation(stats: GenerationStats) -> None:
    """Callback from trainer — schedule broadcast on the event loop."""
    msg = {
        "type": "generation",
        "data": {
            "generation": stats.generation,
            "best_fitness": stats.best_fitness,
            "mean_fitness": stats.mean_fitness,
            "fitness_std": stats.fitness_std,
            "sigma": stats.sigma,
            "best_agent_id": stats.best_agent_id,
        },
    }
    if _loop and _loop.is_running():
        asyncio.run_coroutine_threadsafe(_broadcast(msg), _loop)


# ── Endpoints ───────────────────────────────────────────────────

@app.get("/health")
def health():
    return {"status": "ok", "service": "alphaforge-marl"}


@app.post("/train/start")
def start_training(req: TrainRequest):
    global _trainer, _training_thread

    if _trainer and _trainer._running:
        return {"error": "Training already running"}

    config = load_config(req.config_path)
    _trainer = Trainer(
        config=config,
        checkpoint_dir="checkpoints",
        log_path="logs/training.jsonl",
        on_generation=_on_generation,
    )

    def _run():
        _trainer.train(n_generations=req.n_generations)

    _training_thread = threading.Thread(target=_run, daemon=True)
    _training_thread.start()

    return {"status": "started", "n_generations": req.n_generations}


@app.post("/train/stop")
def stop_training():
    global _trainer
    if _trainer:
        _trainer.stop()
        return {"status": "stopping"}
    return {"error": "No training in progress"}


@app.get("/train/status", response_model=TrainStatus)
def training_status():
    if not _trainer:
        return TrainStatus(
            generation=0,
            running=False,
            best_fitness=0.0,
            mean_fitness=0.0,
            sigma=0.0,
            n_agents=0,
            best_agent_id=None,
        )
    s = _trainer.get_status()
    return TrainStatus(**s)


@app.get("/train/history")
def training_history():
    if not _trainer:
        return {"history": []}
    return {"history": _trainer.logger.get_history()}


@app.post("/walk-forward/start")
def start_walk_forward(req: WalkForwardRequest):
    global _wf_result, _wf_thread, _wf_running
    from datetime import date as dt_date
    from training.walk_forward import _add_months

    if _wf_running:
        return {"error": "Walk-forward already running"}

    train_start = dt_date.fromisoformat(req.train_start)
    end_date = _add_months(train_start, req.train_months + req.val_months + req.test_months)

    folds = generate_folds(
        start_date=train_start,
        end_date=end_date,
        train_months=req.train_months,
        val_months=req.val_months,
        test_months=req.test_months,
    )

    validator = WalkForwardValidator(
        n_generations=req.n_generations,
        sector=req.sector,
    )

    def _run():
        global _wf_result, _wf_running
        _wf_running = True
        try:
            _wf_result = validator.run(folds)
        except Exception as e:
            logger.error(f"Walk-forward failed: {e}")
        finally:
            _wf_running = False

    _wf_thread = threading.Thread(target=_run, daemon=True)
    _wf_thread.start()
    return {"status": "started", "n_folds": len(folds)}


@app.get("/walk-forward/status")
def walk_forward_status():
    return {
        "running": _wf_running,
        "has_result": _wf_result is not None,
        "summary": _wf_result.summary() if _wf_result else None,
    }


@app.get("/dashboard/regime")
def dashboard_regime():
    """Current regime detection state."""
    if not _trainer:
        return {"regime": 0, "confidence": 0.0, "n_regimes": 4, "is_fitted": False}
    rd = _trainer.regime_detector
    regime = _trainer._detect_current_regime()
    confidence = float(rd.regime_confidence) if rd.is_fitted else 0.0
    transition = None
    if rd.is_fitted and rd.transition_matrix is not None:
        transition = rd.transition_matrix.tolist()
    return {
        "regime": regime,
        "confidence": confidence,
        "n_regimes": rd.n_regimes,
        "is_fitted": rd.is_fitted,
        "transition_matrix": transition,
    }


@app.get("/dashboard/ensemble")
def dashboard_ensemble():
    """Pareto front agents and ensemble weights."""
    if not _trainer:
        return {"agents": [], "n_pareto": 0}
    agents_info = []
    for a in _trainer.pareto_front.agents:
        agents_info.append({
            "agent_id": a.agent_id,
            "fitness": round(a.fitness, 4),
            "generation": getattr(a, "generation", 0),
        })
    # Get regime-based allocation weights if available
    weights = {}
    if _trainer.regime_detector.is_fitted:
        regime = _trainer._detect_current_regime()
        for a in _trainer.pareto_front.agents:
            w = _trainer.sampler.expected_value(regime, a.agent_id)
            weights[a.agent_id] = round(w, 4)
    return {
        "agents": agents_info,
        "n_pareto": len(agents_info),
        "regime_weights": weights,
    }


@app.get("/dashboard/portfolio")
def dashboard_portfolio():
    """Current environment portfolio state."""
    if not _trainer:
        return {"nav": 1.0, "positions": {}, "gross_exposure": 0.0, "day": 0}
    env = _trainer.env
    positions = {}
    if hasattr(env, 'positions'):
        positions = {k: round(v, 4) for k, v in env.positions.items() if abs(v) > 1e-6}
    gross = sum(abs(v) for v in positions.values())
    nav = getattr(env, 'nav', 1.0)
    peak = getattr(env, 'peak_nav', nav)
    dd = (peak - nav) / peak if peak > 0 else 0.0
    return {
        "nav": round(nav, 4),
        "peak_nav": round(peak, 4),
        "drawdown": round(dd, 4),
        "positions": positions,
        "gross_exposure": round(gross, 4),
        "day": getattr(env, 'current_step', 0),
    }


@app.get("/dashboard/training")
def dashboard_training():
    """Extended training info: curriculum, fitness trajectory, config."""
    if not _trainer:
        return {"generation": 0, "curriculum_stage": "none", "history": []}
    stage = "none"
    if hasattr(_trainer, 'curriculum') and _trainer.curriculum.current_stage:
        stage = _trainer.curriculum.current_stage.name
    history = []
    for s in _trainer.evo_engine.history[-50:]:
        history.append({
            "generation": s.generation,
            "best_fitness": round(s.best_fitness, 4),
            "mean_fitness": round(s.mean_fitness, 4),
            "fitness_std": round(s.fitness_std, 4),
            "sigma": round(s.sigma, 5),
            "val_sharpe": round(s.val_sharpe, 4),
        })
    return {
        "generation": _trainer.generation,
        "running": _trainer._running,
        "curriculum_stage": stage,
        "best_val_sharpe": round(_trainer.best_val_sharpe, 4) if _trainer.best_val_sharpe > -1e9 else 0.0,
        "sigma": round(_trainer.evo_engine.sigma, 5),
        "n_agents": _trainer.pool.n_agents,
        "history": history,
    }


@app.get("/dashboard", response_class=HTMLResponse)
def dashboard_page():
    """Self-contained live monitoring dashboard."""
    return _DASHBOARD_HTML


@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    global _loop
    _loop = asyncio.get_event_loop()
    await websocket.accept()
    _ws_clients.append(websocket)
    try:
        while True:
            # Keep connection alive, listen for client messages
            data = await websocket.receive_text()
            # Client can send ping/commands
            if data == "ping":
                await websocket.send_json({"type": "pong"})
    except WebSocketDisconnect:
        if websocket in _ws_clients:
            _ws_clients.remove(websocket)


# ── Dashboard HTML ─────────────────────────────────────────────

_DASHBOARD_HTML = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>AlphaForge MARL Dashboard</title>
<script src="https://cdn.jsdelivr.net/npm/chart.js@4"></script>
<style>
  :root { --bg: #0f1117; --card: #1a1d29; --border: #2a2d3a; --text: #e0e0e0;
          --accent: #4fc3f7; --green: #66bb6a; --red: #ef5350; --yellow: #fdd835; --purple: #ab47bc; }
  * { margin: 0; padding: 0; box-sizing: border-box; }
  body { font-family: 'SF Mono', 'Fira Code', monospace; background: var(--bg); color: var(--text); padding: 16px; }
  h1 { font-size: 1.3rem; color: var(--accent); margin-bottom: 12px; }
  .grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(380px, 1fr)); gap: 14px; }
  .card { background: var(--card); border: 1px solid var(--border); border-radius: 8px; padding: 16px; }
  .card h2 { font-size: 0.9rem; color: var(--accent); margin-bottom: 10px; text-transform: uppercase; letter-spacing: 1px; }
  .stat-row { display: flex; justify-content: space-between; padding: 4px 0; font-size: 0.85rem; }
  .stat-label { color: #888; }
  .stat-value { font-weight: 600; }
  .regime-badge { display: inline-block; padding: 2px 10px; border-radius: 12px; font-size: 0.8rem; font-weight: 700; }
  .regime-0 { background: var(--green); color: #000; }
  .regime-1 { background: var(--yellow); color: #000; }
  .regime-2 { background: var(--red); color: #fff; }
  .regime-3 { background: var(--purple); color: #fff; }
  .positions-table { width: 100%; font-size: 0.8rem; border-collapse: collapse; margin-top: 8px; }
  .positions-table th, .positions-table td { padding: 3px 6px; text-align: right; }
  .positions-table th { color: #888; border-bottom: 1px solid var(--border); }
  .pos-long { color: var(--green); }
  .pos-short { color: var(--red); }
  .agents-list { max-height: 180px; overflow-y: auto; font-size: 0.8rem; }
  .agent-row { display: flex; justify-content: space-between; padding: 3px 0; border-bottom: 1px solid var(--border); }
  .status-dot { display: inline-block; width: 8px; height: 8px; border-radius: 50%; margin-right: 6px; }
  .status-running { background: var(--green); animation: pulse 1.5s infinite; }
  .status-stopped { background: #555; }
  @keyframes pulse { 0%,100% { opacity: 1; } 50% { opacity: 0.4; } }
  .chart-container { position: relative; height: 220px; margin-top: 8px; }
  #wsStatus { font-size: 0.75rem; color: #666; margin-left: 12px; }
</style>
</head>
<body>
<h1>AlphaForge MARL <span id="wsStatus">connecting...</span></h1>
<div class="grid">

  <!-- Training Status -->
  <div class="card">
    <h2>Training Status</h2>
    <div class="stat-row"><span class="stat-label">Status</span><span class="stat-value" id="trainStatus">—</span></div>
    <div class="stat-row"><span class="stat-label">Generation</span><span class="stat-value" id="trainGen">0</span></div>
    <div class="stat-row"><span class="stat-label">Best Fitness</span><span class="stat-value" id="trainBest">0.0000</span></div>
    <div class="stat-row"><span class="stat-label">Mean Fitness</span><span class="stat-value" id="trainMean">0.0000</span></div>
    <div class="stat-row"><span class="stat-label">Sigma</span><span class="stat-value" id="trainSigma">0.0000</span></div>
    <div class="stat-row"><span class="stat-label">Val Sharpe (best)</span><span class="stat-value" id="trainValSharpe">0.0000</span></div>
    <div class="stat-row"><span class="stat-label">Curriculum Stage</span><span class="stat-value" id="trainCurriculum">—</span></div>
    <div class="stat-row"><span class="stat-label">Agents</span><span class="stat-value" id="trainAgents">0</span></div>
  </div>

  <!-- Fitness Chart -->
  <div class="card">
    <h2>Fitness Trajectory</h2>
    <div class="chart-container"><canvas id="fitnessChart"></canvas></div>
  </div>

  <!-- Regime Detection -->
  <div class="card">
    <h2>Regime Detection</h2>
    <div class="stat-row"><span class="stat-label">Current Regime</span><span class="stat-value" id="regimeCurrent">—</span></div>
    <div class="stat-row"><span class="stat-label">Confidence</span><span class="stat-value" id="regimeConf">0%</span></div>
    <div class="stat-row"><span class="stat-label">Fitted</span><span class="stat-value" id="regimeFitted">No</span></div>
    <div id="transitionMatrix" style="margin-top:10px; font-size:0.75rem; color:#888;"></div>
  </div>

  <!-- Ensemble / Pareto Front -->
  <div class="card">
    <h2>Ensemble — Pareto Front</h2>
    <div class="stat-row"><span class="stat-label">Pareto Size</span><span class="stat-value" id="paretoSize">0</span></div>
    <div class="agents-list" id="agentsList"></div>
  </div>

  <!-- Portfolio State -->
  <div class="card">
    <h2>Portfolio</h2>
    <div class="stat-row"><span class="stat-label">NAV</span><span class="stat-value" id="portNav">1.0000</span></div>
    <div class="stat-row"><span class="stat-label">Peak NAV</span><span class="stat-value" id="portPeak">1.0000</span></div>
    <div class="stat-row"><span class="stat-label">Drawdown</span><span class="stat-value" id="portDD">0.00%</span></div>
    <div class="stat-row"><span class="stat-label">Gross Exposure</span><span class="stat-value" id="portGross">0.0000</span></div>
    <div class="stat-row"><span class="stat-label">Day</span><span class="stat-value" id="portDay">0</span></div>
    <table class="positions-table" id="posTable">
      <thead><tr><th>Ticker</th><th>Weight</th></tr></thead>
      <tbody></tbody>
    </table>
  </div>

  <!-- Sigma / Diversity Chart -->
  <div class="card">
    <h2>Mutation Sigma</h2>
    <div class="chart-container"><canvas id="sigmaChart"></canvas></div>
  </div>

</div>

<script>
const REGIME_LABELS = ['Bull', 'Transition', 'Bear', 'Crisis'];
const REGIME_COLORS = ['#66bb6a', '#fdd835', '#ef5350', '#ab47bc'];

// Charts
const fitnessCtx = document.getElementById('fitnessChart').getContext('2d');
const fitnessChart = new Chart(fitnessCtx, {
  type: 'line',
  data: {
    labels: [],
    datasets: [
      { label: 'Best', data: [], borderColor: '#4fc3f7', borderWidth: 2, pointRadius: 0, tension: 0.3 },
      { label: 'Mean', data: [], borderColor: '#66bb6a', borderWidth: 1.5, pointRadius: 0, tension: 0.3 },
      { label: 'Val Sharpe', data: [], borderColor: '#fdd835', borderWidth: 1.5, borderDash: [4,2], pointRadius: 0, tension: 0.3 },
    ]
  },
  options: { responsive: true, maintainAspectRatio: false, scales: { x: { display: true, ticks: { color: '#666', maxTicksLimit: 10 } }, y: { ticks: { color: '#666' } } }, plugins: { legend: { labels: { color: '#888', boxWidth: 12, font: { size: 10 } } } } }
});

const sigmaCtx = document.getElementById('sigmaChart').getContext('2d');
const sigmaChart = new Chart(sigmaCtx, {
  type: 'line',
  data: {
    labels: [],
    datasets: [
      { label: 'Sigma', data: [], borderColor: '#ab47bc', borderWidth: 2, pointRadius: 0, fill: true, backgroundColor: 'rgba(171,71,188,0.1)', tension: 0.3 },
    ]
  },
  options: { responsive: true, maintainAspectRatio: false, scales: { x: { display: true, ticks: { color: '#666', maxTicksLimit: 10 } }, y: { ticks: { color: '#666' } } }, plugins: { legend: { labels: { color: '#888', boxWidth: 12, font: { size: 10 } } } } }
});

// Polling
async function fetchAll() {
  try {
    const [training, regime, ensemble, portfolio] = await Promise.all([
      fetch('/dashboard/training').then(r => r.json()),
      fetch('/dashboard/regime').then(r => r.json()),
      fetch('/dashboard/ensemble').then(r => r.json()),
      fetch('/dashboard/portfolio').then(r => r.json()),
    ]);
    updateTraining(training);
    updateRegime(regime);
    updateEnsemble(ensemble);
    updatePortfolio(portfolio);
  } catch (e) { console.error('fetch error', e); }
}

function updateTraining(d) {
  const statusEl = document.getElementById('trainStatus');
  statusEl.innerHTML = d.running
    ? '<span class="status-dot status-running"></span>Running'
    : '<span class="status-dot status-stopped"></span>Stopped';
  document.getElementById('trainGen').textContent = d.generation;
  document.getElementById('trainSigma').textContent = d.sigma.toFixed(5);
  document.getElementById('trainValSharpe').textContent = d.best_val_sharpe.toFixed(4);
  document.getElementById('trainCurriculum').textContent = d.curriculum_stage;
  document.getElementById('trainAgents').textContent = d.n_agents;

  if (d.history.length > 0) {
    const last = d.history[d.history.length - 1];
    document.getElementById('trainBest').textContent = last.best_fitness.toFixed(4);
    document.getElementById('trainMean').textContent = last.mean_fitness.toFixed(4);

    fitnessChart.data.labels = d.history.map(h => h.generation);
    fitnessChart.data.datasets[0].data = d.history.map(h => h.best_fitness);
    fitnessChart.data.datasets[1].data = d.history.map(h => h.mean_fitness);
    fitnessChart.data.datasets[2].data = d.history.map(h => h.val_sharpe);
    fitnessChart.update('none');

    sigmaChart.data.labels = d.history.map(h => h.generation);
    sigmaChart.data.datasets[0].data = d.history.map(h => h.sigma);
    sigmaChart.update('none');
  }
}

function updateRegime(d) {
  const r = d.regime;
  document.getElementById('regimeCurrent').innerHTML =
    '<span class="regime-badge regime-' + r + '">' + (REGIME_LABELS[r] || 'R' + r) + '</span>';
  document.getElementById('regimeConf').textContent = (d.confidence * 100).toFixed(1) + '%';
  document.getElementById('regimeFitted').textContent = d.is_fitted ? 'Yes' : 'No';

  const tmEl = document.getElementById('transitionMatrix');
  if (d.transition_matrix) {
    let html = '<strong>Transition Matrix:</strong><br><pre style="color:#aaa">';
    for (const row of d.transition_matrix) {
      html += row.map(v => v.toFixed(2)).join('  ') + '\\n';
    }
    html += '</pre>';
    tmEl.innerHTML = html;
  } else {
    tmEl.innerHTML = '';
  }
}

function updateEnsemble(d) {
  document.getElementById('paretoSize').textContent = d.n_pareto;
  const list = document.getElementById('agentsList');
  if (d.agents.length === 0) { list.innerHTML = '<div style="color:#666">No agents yet</div>'; return; }
  let html = '';
  for (const a of d.agents) {
    const w = d.regime_weights[a.agent_id];
    const wStr = w !== undefined ? (w * 100).toFixed(1) + '%' : '—';
    html += '<div class="agent-row"><span>' + a.agent_id + ' (gen ' + a.generation + ')</span><span>fit: ' + a.fitness.toFixed(4) + ' | w: ' + wStr + '</span></div>';
  }
  list.innerHTML = html;
}

function updatePortfolio(d) {
  document.getElementById('portNav').textContent = d.nav.toFixed(4);
  document.getElementById('portPeak').textContent = d.peak_nav.toFixed(4);
  document.getElementById('portDD').textContent = (d.drawdown * 100).toFixed(2) + '%';
  document.getElementById('portGross').textContent = d.gross_exposure.toFixed(4);
  document.getElementById('portDay').textContent = d.day;

  const tbody = document.querySelector('#posTable tbody');
  const entries = Object.entries(d.positions).sort((a, b) => Math.abs(b[1]) - Math.abs(a[1]));
  if (entries.length === 0) { tbody.innerHTML = '<tr><td colspan="2" style="color:#666;text-align:center">Flat</td></tr>'; return; }
  tbody.innerHTML = entries.map(([t, w]) =>
    '<tr><td style="text-align:left">' + t + '</td><td class="' + (w > 0 ? 'pos-long' : 'pos-short') + '">' + (w * 100).toFixed(2) + '%</td></tr>'
  ).join('');
}

// WebSocket for real-time generation updates
let ws;
function connectWs() {
  const proto = location.protocol === 'https:' ? 'wss' : 'ws';
  ws = new WebSocket(proto + '://' + location.host + '/ws');
  ws.onopen = () => { document.getElementById('wsStatus').textContent = 'live'; document.getElementById('wsStatus').style.color = '#66bb6a'; };
  ws.onclose = () => { document.getElementById('wsStatus').textContent = 'disconnected'; document.getElementById('wsStatus').style.color = '#ef5350'; setTimeout(connectWs, 3000); };
  ws.onmessage = (e) => {
    const msg = JSON.parse(e.data);
    if (msg.type === 'generation') { fetchAll(); }
  };
}

// Init
fetchAll();
setInterval(fetchAll, 3000);
connectWs();
</script>
</body>
</html>
"""
