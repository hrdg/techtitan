"""Formula tests for VOTE_ONLY_HALF and VOTE_ONLY_BINARY."""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from tech_rotation import (  # noqa: E402
    mom_vote,
    threshold_gate,
    vote_only_exposure,
    vote_only_gate,
)


def test_variants_diverge_at_two_and_a_half_core_votes():
    """Only the half-vote variant reaches 3/5 in this state."""
    assert vote_only_gate(2.5, 4, 0.5, "half") == 1.0
    assert vote_only_gate(2.5, 4, 0.5, "binary") == 0.0


def test_binary_variant_requires_three_full_core_votes_when_mom_stressed():
    assert vote_only_gate(2.0, 4, 0.5, "binary") == 0.0
    assert vote_only_gate(3.0, 4, 0.5, "binary") == 1.0
    assert vote_only_gate(3.0, 4, 1.0, "binary") == 1.0


def test_half_variant_uses_the_half_vote():
    assert vote_only_gate(2.0, 4, 0.5, "half") == 0.0
    assert vote_only_gate(2.5, 4, 0.5, "half") == 1.0
    assert mom_vote(0.5, "half") == 0.5


def test_available_vote_rule_matches_parent_gate():
    assert threshold_gate(0.0, 0, 3) == 1.0
    assert threshold_gate(0.0, 1, 3) == 0.0
    assert threshold_gate(1.0, 1, 3) == 1.0
    assert threshold_gate(2.0, 2, 3) == 1.0
    assert threshold_gate(1.0, 4, 3) == 0.0
    assert threshold_gate(3.0, 4, 3) == 1.0


def test_exposure_is_mother_times_binary_vote_gate():
    assert vote_only_exposure(0.4, 3.0, 4, 1.0, "half") == pytest.approx(0.4)
    assert vote_only_exposure(0.4, 2.0, 4, 0.5, "binary") == 0.0
    assert vote_only_exposure(0.0, 4.0, 4, 1.0, "binary") == 0.0


@pytest.mark.parametrize(
    ("args", "message"),
    [
        ((0.5, "other"), "variant"),
        ((0.75, "half"), "0.5 or 1.0"),
        ((2.5, 4, 0.5, "half", 0), "threshold"),
    ],
)
def test_invalid_primitive_inputs_are_rejected(args, message):
    with pytest.raises(ValueError, match=message):
        if len(args) == 2:
            mom_vote(*args)
        else:
            vote_only_gate(*args)


def test_invalid_exposure_inputs_are_rejected():
    with pytest.raises(ValueError, match="mother_exposure"):
        vote_only_exposure(1.1, 3.0, 4, 1.0, "half")
    with pytest.raises(ValueError, match="core_available"):
        vote_only_gate(3.0, 3.5, 1.0, "half")
    with pytest.raises(ValueError, match="core_votes"):
        vote_only_gate(5.0, 4, 1.0, "half")
