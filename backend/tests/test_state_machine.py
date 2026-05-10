"""Unit tests for the orchestrator state machine.

These tests cover validate_transition() only — no DB, no network, no async.
"""

import pytest

from agents.orchestrator import VALID_TRANSITIONS, validate_transition


# ── Happy-path transitions ────────────────────────────────────────────────────


LEGAL = [
    ("discovering", "generating"),
    ("discovering", "failed"),
    ("generating", "validating"),
    ("generating", "failed"),
    ("validating", "regenerating"),
    ("validating", "awaiting_review"),
    ("validating", "failed"),
    ("regenerating", "validating"),
    ("regenerating", "awaiting_review"),
    ("regenerating", "rejected"),
    ("regenerating", "failed"),
    ("awaiting_review", "publishing"),
    ("awaiting_review", "rejected"),
    ("awaiting_review", "failed"),
    ("publishing", "completed"),
    ("publishing", "partial"),
    ("publishing", "failed"),
    # retry-publish paths
    ("partial", "completed"),
    ("failed", "partial"),
    ("failed", "completed"),
]


@pytest.mark.parametrize("current,target", LEGAL)
def test_legal_transition(current: str, target: str) -> None:
    validate_transition(current, target)  # must not raise


# ── Illegal transitions ───────────────────────────────────────────────────────


ILLEGAL = [
    # Skipping states
    ("discovering", "validating"),
    ("discovering", "awaiting_review"),
    ("discovering", "completed"),
    ("generating", "awaiting_review"),
    ("generating", "completed"),
    # Backwards
    ("validating", "discovering"),
    ("validating", "generating"),
    ("awaiting_review", "discovering"),
    ("awaiting_review", "generating"),
    ("awaiting_review", "validating"),
    # Out of completed / rejected (fully terminal)
    ("completed", "discovering"),
    ("completed", "failed"),
    ("rejected", "discovering"),
    ("rejected", "failed"),
    # partial / failed cannot go backwards or sideways
    ("partial", "publishing"),
    ("partial", "failed"),
    ("failed", "discovering"),
    ("failed", "failed"),
]


@pytest.mark.parametrize("current,target", ILLEGAL)
def test_illegal_transition_raises(current: str, target: str) -> None:
    with pytest.raises(ValueError, match="Invalid state transition"):
        validate_transition(current, target)


# ── Coverage completeness ─────────────────────────────────────────────────────


def test_every_state_in_valid_transitions() -> None:
    """Ensure VALID_TRANSITIONS covers all states that appear as values."""
    all_targets = {t for targets in VALID_TRANSITIONS.values() for t in targets}
    all_sources = set(VALID_TRANSITIONS.keys())
    # Every target state must be a key in VALID_TRANSITIONS (even if empty set)
    for t in all_targets:
        assert t in all_sources, f"State {t!r} has no entry in VALID_TRANSITIONS"


def test_fully_terminal_states_have_no_outgoing() -> None:
    # completed and rejected can never transition to anything.
    # partial and failed allow retry-publish paths (→ completed / → partial).
    fully_terminal = {"completed", "rejected"}
    for state in fully_terminal:
        assert VALID_TRANSITIONS[state] == frozenset(), (
            f"State {state!r} should have no outgoing transitions"
        )
