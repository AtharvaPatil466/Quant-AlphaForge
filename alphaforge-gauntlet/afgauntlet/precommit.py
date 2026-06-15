"""Universal pre-registration integrity gate.

The discipline's integrity rests on two invariants that the substrates have
historically checked ad-hoc (VIX recomputes its `VIX_DESIGN.md` SHA in
`gauntlet/run_gauntlet.py` and refuses to run on mismatch; others not at all):

  1. **Contract immutability** — the frozen design doc has not been edited
     after its hash was anchored.
  2. **Trial-count fidelity** — the number of trials actually evaluated equals
     the number pre-committed, so the multiple-testing deflation denominator
     (e.g. VIX = 28, India = 22, PEAD = 10) is not silently corrupted.

This module generalizes the VIX runtime-anchor idea into one importable gate.
A verdict must not be emitted on a broken pre-registration: `PreRegistration.verify`
raises before it can return a verdict-embeddable dict.
"""
from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path

from .version import source_hash


class PreRegistrationError(RuntimeError):
    """Raised when a frozen pre-registration invariant is violated.

    Either the contract file's current hash no longer matches the anchored
    hash, or the evaluated trial count differs from the pre-committed count.
    """


def compute_contract_hash(path: str | Path) -> str:
    """Return the SHA-256 hex digest of a contract file's raw bytes."""
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def verify_contract_hash(path: str | Path, expected_hash: str) -> None:
    """Verify a contract file still matches its anchored hash.

    No-op (returns None) on a match. Raises `PreRegistrationError` naming both
    the expected and current hashes if the file has been edited after freeze.
    """
    current = compute_contract_hash(path)
    if current != expected_hash:
        raise PreRegistrationError(
            f"Contract hash mismatch — `{path}` edited after freeze.\n"
            f"  Anchored (expected): {expected_hash}\n"
            f"  Current  (on disk):  {current}"
        )


def assert_trial_count(evaluated: int, committed: int) -> None:
    """Verify the evaluated trial count equals the pre-committed count.

    No-op on a match. Raises `PreRegistrationError` if they differ — a mismatch
    corrupts the multiple-testing deflation denominator (the Deflated Sharpe is
    computed against the *pre-committed* trial count; inflating or shrinking the
    realized count invalidates that deflation).
    """
    if evaluated != committed:
        raise PreRegistrationError(
            f"Trial-count mismatch — evaluated={evaluated}, "
            f"committed={committed}. The number of trials evaluated must equal "
            f"the pre-committed count; any mismatch invalidates the "
            f"multiple-testing deflation denominator and the resulting verdict."
        )


@dataclass(frozen=True)
class PreRegistration:
    """A frozen pre-registration anchor for one substrate study.

    Holds the contract file path, its anchored SHA-256 hash, and the number of
    trials pre-committed. `verify` runs both integrity checks at runtime and
    returns a dict for embedding in a verdict — but only if both checks pass.
    """

    contract_path: str | Path
    expected_hash: str
    n_trials_committed: int

    def verify(self, n_trials_evaluated: int) -> dict:
        """Run both integrity checks and return a verdict-embeddable dict.

        Raises `PreRegistrationError` (before returning) if the contract hash
        no longer matches OR the evaluated count differs from the committed
        count. A verdict cannot be emitted on a broken pre-registration.
        """
        verify_contract_hash(self.contract_path, self.expected_hash)
        assert_trial_count(n_trials_evaluated, self.n_trials_committed)
        return {
            "contract_path": str(self.contract_path),
            "contract_hash": self.expected_hash,
            "n_trials_committed": self.n_trials_committed,
            "n_trials_evaluated": n_trials_evaluated,
            "gauntlet_source_hash": source_hash(),
            "preregistration_ok": True,
        }
