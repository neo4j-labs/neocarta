"""Regression tests for get_nodes_to_embed's min_length threshold (see #256)."""

from unittest.mock import MagicMock

import pandas as pd

from neocarta.enrichment.embeddings.utils import get_nodes_to_embed
from neocarta.enums import NodeLabel


def test_get_nodes_to_embed_applies_min_length_in_query():
    driver = MagicMock()
    driver.execute_query.return_value = pd.DataFrame(
        columns=["id", "node_label", "description"]
    )

    get_nodes_to_embed(driver, NodeLabel.COLUMN, min_length=20)

    _, kwargs = driver.execute_query.call_args
    query = kwargs["query_"]
    params = kwargs["parameters_"]

    # The bound parameter must actually be referenced in the WHERE clause,
    # not just passed through unused (the original bug).
    assert "$min_length" in query
    assert "size(n.description) > 0" not in query
    assert params["min_length"] == 20


def test_get_nodes_to_embed_uses_inclusive_threshold():
    driver = MagicMock()
    driver.execute_query.return_value = pd.DataFrame(
        columns=["id", "node_label", "description"]
    )

    get_nodes_to_embed(driver, NodeLabel.COLUMN, min_length=20)

    _, kwargs = driver.execute_query.call_args
    query = kwargs["query_"]

    # Docstring says "minimum length", i.e. inclusive: descriptions exactly
    # min_length chars long should still be embedded.
    assert "size(n.description) >= $min_length" in query


def test_get_nodes_to_embed_rejects_non_positive_min_length():
    driver = MagicMock()

    for bad_value in (0, -1):
        try:
            get_nodes_to_embed(driver, NodeLabel.COLUMN, min_length=bad_value)
            raise AssertionError("expected ConfigError")
        except Exception as exc:
            assert "greater than 0" in str(exc)
