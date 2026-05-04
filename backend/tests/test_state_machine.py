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
    # Out of terminal states
    ("completed", "discovering"),
    ("completed", "failed"),
    ("rejected", "discovering"),
    ("failed", "discovering"),
    ("partial", "publishing"),
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
    # Every target state must either be a source or be terminal
    terminal = {"completed", "partial", "rejected", "failed"}
    for t in all_targets:
        assert t in all_sources or t in terminal, f"State {t!r} has no outgoing transitions defined"


def test_terminal_states_have_no_outgoing() -> None:
    terminal = {"completed", "partial", "rejected", "failed"}
    for state in terminal:
        assert VALID_TRANSITIONS[state] == frozenset(), (
            f"Terminal state {state!r} should have no outgoing transitions"
        )
