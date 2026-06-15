"""Pre-registration integrity gate tests.

Cover the two invariants: contract immutability (hash anchor) and trial-count
fidelity (deflation denominator). Tempfiles keep every case self-contained.
"""
import hashlib
import re
import tempfile
from pathlib import Path

import pytest

import afgauntlet as g

_HEX64 = re.compile(r"^[0-9a-f]{64}$")


@pytest.fixture()
def contract(tmp_path: Path) -> Path:
    p = tmp_path / "DESIGN.md"
    p.write_text("# Frozen design doc\n\n28 pre-committed trials.\n")
    return p


# ─── compute_contract_hash ───────────────────────────────────────────────────

def test_compute_contract_hash_matches_hashlib(contract: Path):
    expected = hashlib.sha256(contract.read_bytes()).hexdigest()
    assert g.compute_contract_hash(contract) == expected
    assert _HEX64.match(g.compute_contract_hash(contract))


def test_editing_tempfile_changes_hash(contract: Path):
    before = g.compute_contract_hash(contract)
    contract.write_text("# Frozen design doc\n\n29 trials (tampered).\n")
    after = g.compute_contract_hash(contract)
    assert before != after


# ─── verify_contract_hash ────────────────────────────────────────────────────

def test_verify_contract_hash_noop_on_match(contract: Path):
    h = g.compute_contract_hash(contract)
    assert g.verify_contract_hash(contract, h) is None


def test_verify_contract_hash_raises_on_edit(contract: Path):
    h = g.compute_contract_hash(contract)
    contract.write_text("# tampered\n")
    with pytest.raises(g.PreRegistrationError) as exc:
        g.verify_contract_hash(contract, h)
    msg = str(exc.value)
    assert h in msg  # both hashes named in the message
    assert g.compute_contract_hash(contract) in msg


# ─── assert_trial_count ──────────────────────────────────────────────────────

def test_assert_trial_count_passes_on_match():
    assert g.assert_trial_count(28, 28) is None


def test_assert_trial_count_raises_on_inflation():
    with pytest.raises(g.PreRegistrationError) as exc:
        g.assert_trial_count(29, 28)
    msg = str(exc.value)
    assert "29" in msg and "28" in msg
    assert "deflation" in msg.lower()


def test_assert_trial_count_raises_on_deflation():
    with pytest.raises(g.PreRegistrationError) as exc:
        g.assert_trial_count(27, 28)
    assert "27" in str(exc.value) and "28" in str(exc.value)


# ─── PreRegistration.verify ──────────────────────────────────────────────────

def test_preregistration_verify_ok(contract: Path):
    pre = g.PreRegistration(
        contract_path=contract,
        expected_hash=g.compute_contract_hash(contract),
        n_trials_committed=28,
    )
    d = pre.verify(28)
    assert d["preregistration_ok"] is True
    assert d["n_trials_committed"] == 28
    assert d["n_trials_evaluated"] == 28
    assert d["contract_path"] == str(contract)
    assert d["contract_hash"] == g.compute_contract_hash(contract)


def test_preregistration_verify_returns_source_hash(contract: Path):
    pre = g.PreRegistration(
        contract_path=contract,
        expected_hash=g.compute_contract_hash(contract),
        n_trials_committed=10,
    )
    d = pre.verify(10)
    assert _HEX64.match(d["gauntlet_source_hash"])
    assert d["gauntlet_source_hash"] == g.source_hash()


def test_preregistration_verify_raises_on_tampered_file(contract: Path):
    pre = g.PreRegistration(
        contract_path=contract,
        expected_hash=g.compute_contract_hash(contract),
        n_trials_committed=28,
    )
    contract.write_text("# tampered after freeze\n")
    with pytest.raises(g.PreRegistrationError):
        pre.verify(28)


def test_preregistration_verify_raises_on_wrong_count(contract: Path):
    pre = g.PreRegistration(
        contract_path=contract,
        expected_hash=g.compute_contract_hash(contract),
        n_trials_committed=28,
    )
    with pytest.raises(g.PreRegistrationError):
        pre.verify(27)


def test_preregistration_is_frozen(contract: Path):
    pre = g.PreRegistration(
        contract_path=contract,
        expected_hash=g.compute_contract_hash(contract),
        n_trials_committed=28,
    )
    with pytest.raises(Exception):
        pre.n_trials_committed = 29  # type: ignore[misc]
