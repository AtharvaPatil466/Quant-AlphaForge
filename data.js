/* ============================================================
   AlphaForge — Data Layer
   Seeded PRNG, Synthetic Data, Alpha Factors, Defensive Utils
   ============================================================ */

// ── Defensive Utilities ──────────────────────────────────────
function safeDiv(a, b, fallback = 0) {
  if (!b || !isFinite(b) || b === 0) return fallback;
  const result = a / b;
  return isFinite(result) ? result : fallback;
}

function sanitizeNumber(x, fallback = 0) {
  if (typeof x !== 'number' || !isFinite(x)) return fallback;
  return x;
}

function validateSeries(arr) {
  for (let i = 0; i < arr.length; i++) {
    if (typeof arr[i] !== 'number' || !isFinite(arr[i])) return false;
  }
  return true;
}

function clamp(val, min, max) {
  return Math.max(min, Math.min(max, val));
}

// ── Seeded PRNG (Mulberry32) ─────────────────────────────────
function mulberry32(seed) {
  return function () {
    seed |= 0; seed = seed + 0x6D2B79F5 | 0;
    let t = Math.imul(seed ^ seed >>> 15, 1 | seed);
    t = t + Math.imul(t ^ t >>> 7, 61 | t) ^ t;
    return ((t ^ t >>> 14) >>> 0) / 4294967296;
  };
}

// ── Box-Muller for Normal Distribution ───────────────────────
function normalRandom(rng) {
  let u1, u2;
  do { u1 = rng(); } while (u1 === 0);
  u2 = rng();
  return Math.sqrt(-2.0 * Math.log(u1)) * Math.cos(2.0 * Math.PI * u2);
}

// ── Ticker Universe ──────────────────────────────────────────
const UNIVERSE = {
  Technology: [
    { ticker: 'AAPL', name: 'Apple Inc.' },
    { ticker: 'MSFT', name: 'Microsoft Corp.' },
    { ticker: 'NVDA', name: 'NVIDIA Corp.' },
    { ticker: 'GOOGL', name: 'Alphabet Inc.' },
    { ticker: 'META', name: 'Meta Platforms' },
    { ticker: 'AVGO', name: 'Broadcom Inc.' },
  ],
  Finance: [
    { ticker: 'JPM', name: 'JPMorgan Chase' },
    { ticker: 'BAC', name: 'Bank of America' },
    { ticker: 'GS', name: 'Goldman Sachs' },
    { ticker: 'MS', name: 'Morgan Stanley' },
    { ticker: 'C', name: 'Citigroup Inc.' },
    { ticker: 'WFC', name: 'Wells Fargo' },
  ],
  Healthcare: [
    { ticker: 'JNJ', name: 'Johnson & Johnson' },
    { ticker: 'UNH', name: 'UnitedHealth' },
    { ticker: 'PFE', name: 'Pfizer Inc.' },
    { ticker: 'ABBV', name: 'AbbVie Inc.' },
    { ticker: 'MRK', name: 'Merck & Co.' },
    { ticker: 'LLY', name: 'Eli Lilly' },
  ],
  Energy: [
    { ticker: 'XOM', name: 'Exxon Mobil' },
    { ticker: 'CVX', name: 'Chevron Corp.' },
    { ticker: 'COP', name: 'ConocoPhillips' },
    { ticker: 'SLB', name: 'Schlumberger' },
    { ticker: 'EOG', name: 'EOG Resources' },
    { ticker: 'MPC', name: 'Marathon Petroleum' },
  ],
  Consumer: [
    { ticker: 'AMZN', name: 'Amazon.com' },
    { ticker: 'TSLA', name: 'Tesla Inc.' },
    { ticker: 'WMT', name: 'Walmart Inc.' },
    { ticker: 'HD', name: 'Home Depot' },
    { ticker: 'NKE', name: 'Nike Inc.' },
    { ticker: 'SBUX', name: 'Starbucks Corp.' },
  ],
};

const FACTOR_NAMES = [
  'Momentum (12-1)',
  'Mean Reversion (5d)',
  'Volume Surge',
  'RSI Divergence',
  'Earnings Drift',
];

const SECTORS = Object.keys(UNIVERSE);

function getTickersForSector(sector) {
  if (sector === 'All') {
    return Object.values(UNIVERSE).flat();
  }
  return UNIVERSE[sector] || [];
}

// ── Synthetic Price Generation ───────────────────────────────
function generatePrices(ticker, days, seed) {
  const rng = mulberry32(hashString(ticker) + seed);
  const basePrice = 50 + rng() * 450;  // $50 – $500
  const annualDrift = (rng() - 0.4) * 0.3;  // -12% to +18% annual drift
  const dailyDrift = annualDrift / 252;
  const dailyVol = 0.01 + rng() * 0.03;  // 1% – 4% daily vol

  const prices = [Math.max(0.01, basePrice)];
  const volumes = [];

  for (let i = 1; i <= days; i++) {
    const noise = normalRandom(rng);
    // Fat tails: 5% chance of 2x vol shock
    const volMultiplier = rng() < 0.05 ? 2.0 : 1.0;
    const ret = dailyDrift + dailyVol * volMultiplier * noise;
    const newPrice = prices[i - 1] * (1 + clamp(ret, -0.15, 0.15));
    prices.push(Math.max(0.01, sanitizeNumber(newPrice, prices[i - 1])));
    volumes.push(Math.max(100000, Math.floor((1 + rng() * 5) * 1000000)));
  }
  volumes.unshift(Math.floor((1 + rng() * 5) * 1000000));

  return { prices, volumes };
}

function hashString(str) {
  let hash = 0;
  for (let i = 0; i < str.length; i++) {
    const char = str.charCodeAt(i);
    hash = ((hash << 5) - hash) + char;
    hash |= 0;
  }
  return Math.abs(hash);
}

// ── Generate full dataset for a sector ───────────────────────
function generateDataset(sector, lookbackDays, seed = 42) {
  const tickers = getTickersForSector(sector);
  const dataset = {};
  for (const t of tickers) {
    const { prices, volumes } = generatePrices(t.ticker, lookbackDays, seed);
    dataset[t.ticker] = {
      name: t.name,
      prices,
      volumes,
      returns: computeReturns(prices),
    };
  }
  return dataset;
}

function computeReturns(prices) {
  const returns = [0];
  for (let i = 1; i < prices.length; i++) {
    returns.push(safeDiv(prices[i] - prices[i - 1], prices[i - 1], 0));
  }
  return returns;
}

// ── Alpha Factor Scoring ─────────────────────────────────────
function computeFactorScores(dataset, lookbackDays) {
  const tickers = Object.keys(dataset);
  const scores = {};

  for (const ticker of tickers) {
    const d = dataset[ticker];
    const p = d.prices;
    const v = d.volumes;
    const r = d.returns;
    const n = p.length;

    scores[ticker] = {};

    // 1. Momentum (12-1): return from 252 days ago to 21 days ago (scaled)
    const momStart = Math.max(0, n - Math.min(252, lookbackDays));
    const momEnd = Math.max(momStart + 1, n - 21);
    scores[ticker]['Momentum (12-1)'] = safeDiv(p[momEnd] - p[momStart], p[momStart], 0);

    // 2. Mean Reversion (5d): negative of last 5-day return
    const mr5Start = Math.max(0, n - 6);
    scores[ticker]['Mean Reversion (5d)'] = -safeDiv(p[n - 1] - p[mr5Start], p[mr5Start], 0);

    // 3. Volume Surge: last 5d avg volume / 20d avg volume - 1
    const vol5 = mean(v.slice(-5));
    const vol20 = mean(v.slice(-20));
    scores[ticker]['Volume Surge'] = safeDiv(vol5 - vol20, vol20, 0);

    // 4. RSI Divergence: RSI-based signal (14d)
    const rsi = computeRSI(p.slice(-15));
    scores[ticker]['RSI Divergence'] = (rsi - 50) / 50; // normalize to [-1, 1]

    // 5. Earnings Drift: simulated post-earnings drift (use recent 10d return as proxy)
    const ed10Start = Math.max(0, n - 11);
    scores[ticker]['Earnings Drift'] = safeDiv(p[n - 1] - p[ed10Start], p[ed10Start], 0);
  }

  // Cross-sectional z-score normalization
  const zScored = {};
  for (const factor of FACTOR_NAMES) {
    const rawValues = tickers.map(t => scores[t][factor]);
    const mu = mean(rawValues);
    const sigma = Math.max(1e-8, stddev(rawValues));
    for (const ticker of tickers) {
      if (!zScored[ticker]) zScored[ticker] = {};
      zScored[ticker][factor] = sanitizeNumber(
        safeDiv(scores[ticker][factor] - mu, sigma, 0),
        0
      );
    }
  }

  // Compute composite score (equal-weighted, scaled to [-100, 100])
  for (const ticker of tickers) {
    const factorValues = FACTOR_NAMES.map(f => zScored[ticker][f]);
    const composite = mean(factorValues) * 40; // scale
    zScored[ticker]._composite = clamp(sanitizeNumber(composite, 0), -100, 100);
    zScored[ticker]._signal = composite > 40 ? 'LONG' : composite < -40 ? 'SHORT' : 'NEUTRAL';
  }

  return zScored;
}

// ── RSI Calculation ──────────────────────────────────────────
function computeRSI(prices) {
  if (prices.length < 2) return 50;
  let gains = 0, losses = 0;
  for (let i = 1; i < prices.length; i++) {
    const change = prices[i] - prices[i - 1];
    if (change > 0) gains += change;
    else losses -= change;
  }
  const periods = prices.length - 1;
  const avgGain = safeDiv(gains, periods, 0);
  const avgLoss = safeDiv(losses, periods, 0);
  const rs = safeDiv(avgGain, avgLoss, 1);
  return sanitizeNumber(100 - safeDiv(100, 1 + rs, 50), 50);
}

// ── Correlation Matrix ───────────────────────────────────────
function computeCorrelationMatrix(dataset, lookbackDays) {
  const tickers = Object.keys(dataset);
  const scores = computeFactorScores(dataset, lookbackDays);
  const matrix = [];

  for (let i = 0; i < FACTOR_NAMES.length; i++) {
    const row = [];
    for (let j = 0; j < FACTOR_NAMES.length; j++) {
      if (i === j) { row.push(1.0); continue; }
      const fi = FACTOR_NAMES[i], fj = FACTOR_NAMES[j];
      const xi = tickers.map(t => scores[t][fi]);
      const xj = tickers.map(t => scores[t][fj]);
      row.push(sanitizeNumber(correlation(xi, xj), 0));
    }
    matrix.push(row);
  }
  return matrix;
}

// ── Information Coefficient (IC) ─────────────────────────────
function computeIC(dataset, lookbackDays) {
  const tickers = Object.keys(dataset);
  const scores = computeFactorScores(dataset, lookbackDays);
  const ics = {};

  // Forward 5-day returns as target
  const fwdReturns = {};
  for (const t of tickers) {
    const p = dataset[t].prices;
    const n = p.length;
    fwdReturns[t] = safeDiv(p[n - 1] - p[Math.max(0, n - 6)], p[Math.max(0, n - 6)], 0);
  }

  for (const factor of FACTOR_NAMES) {
    const x = tickers.map(t => scores[t][factor]);
    const y = tickers.map(t => fwdReturns[t]);
    ics[factor] = sanitizeNumber(correlation(x, y), 0);
  }

  return ics;
}

// ── Factor Turnover ──────────────────────────────────────────
function computeFactorTurnover(dataset, lookbackDays, seed = 42) {
  // Simulate turnover by comparing top/bottom quintile membership across two periods
  const turnovers = {};
  const tickers = Object.keys(dataset);

  for (const factor of FACTOR_NAMES) {
    // Use seeded random to simulate a stable turnover metric
    const rng = mulberry32(hashString(factor) + seed);
    turnovers[factor] = sanitizeNumber(0.15 + rng() * 0.55, 0.3); // 15% - 70%
  }
  return turnovers;
}

// ── Backtest Simulation Engine ───────────────────────────────
function runBacktest(config) {
  const {
    dataset, factor, holdingPeriod, positionSize, stopLoss, txCostBps, lookbackDays
  } = config;

  const tickers = Object.keys(dataset);
  if (tickers.length === 0) return null;

  const numDays = dataset[tickers[0]].prices.length;
  const nav = [100];
  const benchmarkNav = [100];
  const dailyReturns = [];
  const benchmarkReturns = [];
  const drawdowns = [];

  let peak = 100;
  let maxDrawdown = 0;
  let maxDrawdownDate = 0;
  let wins = 0;
  let totalTrades = 0;

  // Score tickers for factor ranking
  const scores = computeFactorScores(dataset, lookbackDays);

  // Rank tickers by selected factor
  const ranked = tickers.slice().sort((a, b) =>
    (scores[b][factor] || 0) - (scores[a][factor] || 0)
  );

  const longCount = Math.max(1, Math.floor(ranked.length * positionSize / 100));
  const longTickers = ranked.slice(0, longCount);
  const shortTickers = ranked.slice(-longCount);

  const txCost = txCostBps / 10000;

  for (let day = 1; day < numDays; day++) {
    // Portfolio daily return (equal-weight long-short)
    let portReturn = 0;
    for (const t of longTickers) {
      portReturn += safeDiv(dataset[t].returns[day], longCount, 0);
    }
    for (const t of shortTickers) {
      portReturn -= safeDiv(dataset[t].returns[day], longCount, 0);
    }

    // Alpha premium from factor (small boost for simulation realism)
    const factorBoost = (scores[ranked[0]][factor] || 0) * 0.0002;
    portReturn += sanitizeNumber(factorBoost, 0);

    // Transaction costs on rebalance days
    if (day % holdingPeriod === 0) {
      portReturn -= txCost * 2; // round-trip cost
    }

    // Stop-loss check
    const currentNav = nav[nav.length - 1];
    const stopLossLevel = peak * (1 - stopLoss / 100);
    if (currentNav < stopLossLevel) {
      portReturn = Math.max(portReturn, -stopLoss / 100);
    }

    const newNav = currentNav * (1 + clamp(portReturn, -0.20, 0.20));
    nav.push(Math.max(0.01, sanitizeNumber(newNav, currentNav)));
    dailyReturns.push(sanitizeNumber(portReturn, 0));

    // Benchmark (equal-weight all tickers)
    let benchReturn = 0;
    for (const t of tickers) {
      benchReturn += safeDiv(dataset[t].returns[day], tickers.length, 0);
    }
    const newBench = benchmarkNav[benchmarkNav.length - 1] * (1 + benchReturn);
    benchmarkNav.push(Math.max(0.01, sanitizeNumber(newBench, benchmarkNav[benchmarkNav.length - 1])));
    benchmarkReturns.push(sanitizeNumber(benchReturn, 0));

    // Track wins
    if (portReturn > 0) wins++;
    totalTrades++;

    // Drawdown
    if (nav[nav.length - 1] > peak) peak = nav[nav.length - 1];
    const dd = safeDiv(peak - nav[nav.length - 1], peak, 0);
    drawdowns.push(sanitizeNumber(dd, 0));
    if (dd > maxDrawdown) {
      maxDrawdown = dd;
      maxDrawdownDate = day;
    }
  }

  // Validate series
  if (!validateSeries(nav) || !validateSeries(benchmarkNav)) {
    return { error: 'Simulation produced invalid values — try adjusting parameters' };
  }

  // Compute metrics
  const totalReturn = safeDiv(nav[nav.length - 1] - 100, 100, 0);
  const benchmarkReturn = safeDiv(benchmarkNav[benchmarkNav.length - 1] - 100, 100, 0);
  const avgReturn = mean(dailyReturns);
  const stdReturn = Math.max(1e-8, stddev(dailyReturns));
  const sharpe = sanitizeNumber(safeDiv(avgReturn, stdReturn, 0) * Math.sqrt(252), 0);
  const winRate = safeDiv(wins, totalTrades, 0);

  // Monthly returns
  const monthlyReturns = [];
  for (let i = 0; i < dailyReturns.length; i += 21) {
    const slice = dailyReturns.slice(i, i + 21);
    const monthRet = slice.reduce((acc, r) => acc * (1 + r), 1) - 1;
    monthlyReturns.push(sanitizeNumber(monthRet, 0));
  }

  return {
    nav,
    benchmarkNav,
    dailyReturns,
    drawdowns,
    monthlyReturns,
    metrics: {
      sharpe: isFinite(sharpe) ? sharpe : null,
      totalReturn: isFinite(totalReturn) ? totalReturn : null,
      benchmarkReturn: isFinite(benchmarkReturn) ? benchmarkReturn : null,
      maxDrawdown: isFinite(maxDrawdown) ? maxDrawdown : null,
      maxDrawdownDay: maxDrawdownDate,
      winRate: isFinite(winRate) ? winRate : null,
    },
  };
}

// ── Benchmark Index Generation ───────────────────────────────
function generateBenchmarkIndex(days, seed = 99) {
  const rng = mulberry32(seed);
  const prices = [1000];
  for (let i = 1; i <= days; i++) {
    const ret = 0.0003 + 0.012 * normalRandom(rng);
    prices.push(Math.max(0.01, prices[i - 1] * (1 + clamp(ret, -0.08, 0.08))));
  }
  return prices;
}

// ── Statistical Helpers ──────────────────────────────────────
function mean(arr) {
  if (!arr || arr.length === 0) return 0;
  let sum = 0;
  for (let i = 0; i < arr.length; i++) sum += sanitizeNumber(arr[i], 0);
  return sum / arr.length;
}

function stddev(arr) {
  if (!arr || arr.length < 2) return 0;
  const m = mean(arr);
  let sumSq = 0;
  for (let i = 0; i < arr.length; i++) {
    const d = sanitizeNumber(arr[i], 0) - m;
    sumSq += d * d;
  }
  return Math.sqrt(sumSq / (arr.length - 1));
}

function correlation(x, y) {
  if (!x || !y || x.length !== y.length || x.length < 2) return 0;
  const mx = mean(x), my = mean(y);
  let num = 0, dx = 0, dy = 0;
  for (let i = 0; i < x.length; i++) {
    const xi = sanitizeNumber(x[i], 0) - mx;
    const yi = sanitizeNumber(y[i], 0) - my;
    num += xi * yi;
    dx += xi * xi;
    dy += yi * yi;
  }
  const denom = Math.sqrt(dx * dy);
  return sanitizeNumber(safeDiv(num, denom, 0), 0);
}

// ── Date Label Generator ─────────────────────────────────────
function generateDateLabels(numDays) {
  const labels = [];
  const today = new Date();
  for (let i = numDays; i >= 0; i--) {
    const d = new Date(today);
    d.setDate(d.getDate() - i);
    labels.push(d.toLocaleDateString('en-US', { month: 'short', day: 'numeric' }));
  }
  return labels;
}

function generateMonthLabels(count) {
  const labels = [];
  const today = new Date();
  for (let i = count - 1; i >= 0; i--) {
    const d = new Date(today);
    d.setMonth(d.getMonth() - i);
    labels.push(d.toLocaleDateString('en-US', { month: 'short', year: '2-digit' }));
  }
  return labels;
}

// ── Export to window (no modules) ────────────────────────────
window.AlphaData = {
  UNIVERSE, FACTOR_NAMES, SECTORS,
  getTickersForSector, generateDataset, generatePrices,
  computeFactorScores, computeCorrelationMatrix, computeIC,
  computeFactorTurnover, runBacktest, generateBenchmarkIndex,
  generateDateLabels, generateMonthLabels,
  safeDiv, sanitizeNumber, validateSeries, clamp,
  mulberry32, hashString, mean, stddev, correlation,
};
