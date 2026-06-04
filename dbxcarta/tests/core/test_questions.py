from __future__ import annotations

import dataclasses

import pytest
from dbxcarta.core.questions import GeneratedPair, ValidationOutcome


def test_generated_pair_is_frozen() -> None:
    pair = GeneratedPair(
        uc_schema="s",
        source_id="src",
        shape="aggregation",
        question="how many?",
        sql="SELECT 1",
    )
    with pytest.raises(dataclasses.FrozenInstanceError):
        pair.question = "changed"  # type: ignore[misc]


def test_validation_outcome_counts_default_to_zero() -> None:
    outcome = ValidationOutcome(accepted=[])
    assert (outcome.errored, outcome.empty, outcome.trivial) == (0, 0, 0)


def test_validation_outcome_requires_accepted() -> None:
    with pytest.raises(TypeError):
        ValidationOutcome()  # type: ignore[call-arg]
