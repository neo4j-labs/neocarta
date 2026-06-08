"""Unit tests for the NeocartaGraph metadata node model."""

from datetime import datetime, timezone

import pytest
from pydantic import ValidationError

from neocarta.data_model.metadata import NeocartaGraph


def test_neocarta_graph_round_trip():
    """All four fields are preserved through model construction and dump."""
    now = datetime(2026, 5, 20, 12, 0, 0, tzinfo=timezone.utc)
    node = NeocartaGraph(
        initial_version="0.3.0",
        latest_version="0.4.0",
        create_date=now,
        last_updated=now,
    )

    dumped = node.model_dump()
    assert dumped["initial_version"] == "0.3.0"
    assert dumped["latest_version"] == "0.4.0"
    assert dumped["create_date"] == now
    assert dumped["last_updated"] == now


def test_neocarta_graph_requires_all_fields():
    """The model has no defaults; constructing without fields fails."""
    with pytest.raises(ValidationError):
        NeocartaGraph()  # type: ignore[call-arg]
