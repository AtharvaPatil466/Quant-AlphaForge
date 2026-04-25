"""Market regime detection using HMM (primary) or K-Means (fallback).

The HMM captures temporal regime persistence via transition probabilities,
unlike K-Means which treats each observation independently.
"""

from __future__ import annotations

from typing import List, Optional

import numpy as np
from sklearn.cluster import KMeans


class HMMRegimeDetector:
    """Hidden Markov Model for regime detection with temporal persistence.

    Learns transition probabilities between regimes so the detector won't
    flip-flop frame-to-frame. Uses Baum-Welch (EM) for parameter estimation.
    """

    def __init__(self, n_regimes: int = 4, random_state: int = 42):
        self.n_regimes = n_regimes
        self.random_state = random_state
        self._fitted = False

        # HMM parameters (initialized on fit)
        self.transition_matrix: np.ndarray = np.ones((n_regimes, n_regimes)) / n_regimes
        self.initial_probs: np.ndarray = np.ones(n_regimes) / n_regimes
        self.means: np.ndarray = np.zeros((n_regimes, 4))
        self.covars: np.ndarray = np.array([np.eye(4)] * n_regimes)

        # Track last predicted regime for temporal smoothing
        self._last_regime: int = 0
        self._regime_confidence: np.ndarray = np.ones(n_regimes) / n_regimes

    def fit(self, features: np.ndarray, n_iter: int = 20) -> None:
        """Fit HMM via K-Means initialization + simplified Baum-Welch.

        Args:
            features: (n_samples, n_features) array of sequential market features.
            n_iter: Number of EM iterations.
        """
        if len(features) < self.n_regimes * 2:
            return

        rng = np.random.RandomState(self.random_state)
        n_samples, n_features = features.shape

        # Initialize with K-Means
        kmeans = KMeans(
            n_clusters=self.n_regimes, random_state=self.random_state, n_init=10
        )
        labels = kmeans.fit_predict(features)

        # Estimate means and covariances per cluster
        self.means = np.zeros((self.n_regimes, n_features))
        self.covars = np.array([np.eye(n_features)] * self.n_regimes)
        for k in range(self.n_regimes):
            mask = labels == k
            if mask.sum() > 1:
                self.means[k] = features[mask].mean(axis=0)
                cov = np.cov(features[mask].T)
                if cov.ndim == 0:
                    cov = np.eye(n_features) * max(float(cov), 1e-6)
                self.covars[k] = cov + np.eye(n_features) * 1e-4

        # Estimate transition matrix from K-Means labels
        trans = np.ones((self.n_regimes, self.n_regimes)) * 0.01  # Laplace smoothing
        for t in range(len(labels) - 1):
            trans[labels[t], labels[t + 1]] += 1.0
        self.transition_matrix = trans / trans.sum(axis=1, keepdims=True)

        # Initial distribution from first observations
        self.initial_probs = np.ones(self.n_regimes) * 0.01
        for k in range(min(20, len(labels))):
            self.initial_probs[labels[k]] += 1.0
        self.initial_probs /= self.initial_probs.sum()

        # Simplified EM refinement
        for _ in range(n_iter):
            # E-step: compute responsibilities
            log_likelihoods = self._compute_log_likelihoods(features)
            responsibilities = self._forward_backward(log_likelihoods)

            # M-step: update parameters
            self._m_step(features, responsibilities)

        self._fitted = True

    def _compute_log_likelihoods(self, features: np.ndarray) -> np.ndarray:
        """Compute log p(x_t | state=k) for all t, k."""
        n_samples = len(features)
        log_liks = np.zeros((n_samples, self.n_regimes))
        for k in range(self.n_regimes):
            diff = features - self.means[k]
            cov = self.covars[k]
            try:
                cov_inv = np.linalg.inv(cov)
                sign, logdet = np.linalg.slogdet(cov)
                if sign <= 0:
                    logdet = 0.0
            except np.linalg.LinAlgError:
                cov_inv = np.eye(features.shape[1])
                logdet = 0.0
            mahal = np.sum(diff @ cov_inv * diff, axis=1)
            log_liks[:, k] = -0.5 * (mahal + logdet + features.shape[1] * np.log(2 * np.pi))
        return log_liks

    def _forward_backward(self, log_liks: np.ndarray) -> np.ndarray:
        """Simplified forward pass to get state responsibilities."""
        n_samples = len(log_liks)
        # Forward
        alpha = np.zeros((n_samples, self.n_regimes))
        alpha[0] = np.log(self.initial_probs + 1e-300) + log_liks[0]
        for t in range(1, n_samples):
            for k in range(self.n_regimes):
                alpha[t, k] = (
                    _logsumexp(alpha[t - 1] + np.log(self.transition_matrix[:, k] + 1e-300))
                    + log_liks[t, k]
                )

        # Normalize to responsibilities
        resp = np.exp(alpha - alpha.max(axis=1, keepdims=True))
        resp_sum = resp.sum(axis=1, keepdims=True)
        resp_sum = np.where(resp_sum < 1e-300, 1.0, resp_sum)
        return resp / resp_sum

    def _m_step(self, features: np.ndarray, resp: np.ndarray) -> None:
        """M-step: update means, covariances, transition matrix."""
        n_features = features.shape[1]
        for k in range(self.n_regimes):
            rk = resp[:, k]
            nk = rk.sum()
            if nk < 1e-6:
                continue
            self.means[k] = (rk[:, None] * features).sum(axis=0) / nk
            diff = features - self.means[k]
            self.covars[k] = (
                (rk[:, None] * diff).T @ diff / nk
                + np.eye(n_features) * 1e-4
            )

        # Update transition matrix
        trans = np.ones((self.n_regimes, self.n_regimes)) * 0.01
        for t in range(len(resp) - 1):
            trans += np.outer(resp[t], resp[t + 1])
        self.transition_matrix = trans / trans.sum(axis=1, keepdims=True)

    def predict(self, features: np.ndarray) -> np.ndarray:
        """Predict regimes using emission probabilities + transition prior."""
        if not self._fitted:
            if features.ndim == 1:
                return np.array([0])
            return np.zeros(len(features), dtype=int)

        if features.ndim == 1:
            features = features.reshape(1, -1)

        log_liks = self._compute_log_likelihoods(features)
        # Viterbi-like: use transition from last regime
        prior = np.log(self.transition_matrix[self._last_regime] + 1e-300)
        scores = log_liks + prior[None, :]
        labels = scores.argmax(axis=1)

        if len(labels) > 0:
            self._last_regime = int(labels[-1])
            # Update confidence for smoothing
            self._regime_confidence = np.exp(scores[-1] - scores[-1].max())
            self._regime_confidence /= self._regime_confidence.sum()

        return labels

    def predict_single(self, features: np.ndarray) -> int:
        """Predict regime for a single observation."""
        return int(self.predict(features.reshape(1, -1))[0])

    @property
    def is_fitted(self) -> bool:
        return self._fitted

    @property
    def regime_confidence(self) -> np.ndarray:
        """Current posterior over regimes (useful for soft allocation)."""
        return self._regime_confidence.copy()


def _logsumexp(x: np.ndarray) -> float:
    """Numerically stable log-sum-exp."""
    m = x.max()
    return m + np.log(np.sum(np.exp(x - m)))


# Keep as alias for backward compatibility
class RegimeDetector(HMMRegimeDetector):
    """Market regime detector (HMM-based with temporal persistence)."""
    pass


def extract_regime_features(
    index_returns: np.ndarray,
    index_volumes: np.ndarray,
    index_prices: np.ndarray,
    window: int = 21,
) -> np.ndarray:
    """Extract regime features from market data at each time step.

    Returns (n_windows, 4) array: [autocorr, vol, hurst_approx, volume_ratio]
    """
    n = len(index_returns)
    features = []

    for t in range(window, n):
        chunk = index_returns[t - window : t]

        # Autocorrelation (lag 1)
        if len(chunk) > 1:
            ac = float(np.corrcoef(chunk[:-1], chunk[1:])[0, 1])
            ac = ac if np.isfinite(ac) else 0.0
        else:
            ac = 0.0

        # Realized volatility
        vol = float(np.std(chunk, ddof=1)) * np.sqrt(252) if len(chunk) > 1 else 0.0
        vol = vol if np.isfinite(vol) else 0.0

        # Hurst approximation (R/S on the window)
        hurst = _quick_hurst(chunk)

        # Volume ratio
        if t < len(index_volumes):
            avg_vol = float(np.mean(index_volumes[max(0, t - window) : t]))
            vr = float(index_volumes[t]) / avg_vol if avg_vol > 1e-8 else 1.0
            vr = vr if np.isfinite(vr) else 1.0
        else:
            vr = 1.0

        features.append([ac, vol, hurst, vr])

    return np.array(features, dtype=np.float32) if features else np.zeros((0, 4), dtype=np.float32)


def _quick_hurst(rets: np.ndarray) -> float:
    """Quick R/S Hurst estimate on a single window."""
    n = len(rets)
    if n < 10:
        return 0.5
    m = np.mean(rets)
    s = np.std(rets, ddof=1)
    if s < 1e-12:
        return 0.5
    cumdev = np.cumsum(rets - m)
    r = np.max(cumdev) - np.min(cumdev)
    rs = r / s
    if rs <= 0:
        return 0.5
    h = np.log(rs) / np.log(n)
    return float(np.clip(h, 0.0, 1.0))
