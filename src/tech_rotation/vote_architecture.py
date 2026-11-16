"""MOM20 vote-only risk-architecture primitives.

These functions mirror the frozen experiment in
``research/runs/mom20_10_mom_vote_architecture_20261114``. They implement
only the exposure gate; signal construction, asset selection and execution
remain in the parent strategy.
"""
from __future__ import annotations

import math
from typing import Literal

VoteOnlyVariant = Literal["half", "binary"]


def _require_finite(name: str, value: float) -> float:
    number = float(value)
    if not math.isfinite(number):
        raise ValueError(f"{name} must be finite, got {value!r}")
    return number


def mom_vote(mom_scale: float, variant: VoteOnlyVariant) -> float:
    """Convert the MOM20 1.0/0.5 state into one fifth vote.

    ``half`` keeps the original half-vote semantics: normal=1.0 and
    stressed=0.5. ``binary`` turns the state into a pass/fail vote:
    normal=1.0 and stressed=0.0.
    """
    scale = _require_finite("mom_scale", mom_scale)
    if scale not in (0.5, 1.0):
        raise ValueError("mom_scale must be 0.5 or 1.0")
    if variant == "half":
        return scale
    if variant == "binary":
        return 1.0 if scale == 1.0 else 0.0
    raise ValueError("variant must be 'half' or 'binary'")


def threshold_gate(score: float, available: float, threshold: int = 3) -> float:
    """Return 1 when enough available votes pass, otherwise 0.

    This follows the frozen parent rule: the threshold is capped by the
    number of available votes, and a row with no votes remains enabled.
    """
    score_value = _require_finite("score", score)
    available_value = _require_finite("available", available)
    if available_value < 0 or not available_value.is_integer():
        raise ValueError("available must be a non-negative integer")
    if threshold < 1:
        raise ValueError("threshold must be positive")
    if available_value == 0:
        return 1.0
    required = min(threshold, int(available_value))
    return 1.0 if score_value >= required else 0.0


def vote_only_gate(
    core_votes: float,
    core_available: float,
    mom_scale: float,
    variant: VoteOnlyVariant = "half",
    threshold: int = 3,
) -> float:
    """Compute the vote gate without applying a MOM exposure multiplier."""
    core_score = _require_finite("core_votes", core_votes)
    core_count = _require_finite("core_available", core_available)
    if core_count < 0 or not core_count.is_integer():
        raise ValueError("core_available must be a non-negative integer")
    if core_score < 0 or core_score > core_count:
        raise ValueError("core_votes must be between 0 and core_available")
    return threshold_gate(
        core_score + mom_vote(mom_scale, variant),
        core_count + 1.0,
        threshold,
    )


def vote_only_exposure(
    mother_exposure: float,
    core_votes: float,
    core_available: float,
    mom_scale: float,
    variant: VoteOnlyVariant = "half",
    threshold: int = 3,
) -> float:
    """Apply the vote-only gate to the parent strategy exposure."""
    mother = _require_finite("mother_exposure", mother_exposure)
    if mother < 0 or mother > 1:
        raise ValueError("mother_exposure must be in [0, 1]")
    return mother * vote_only_gate(
        core_votes,
        core_available,
        mom_scale,
        variant,
        threshold,
    )
