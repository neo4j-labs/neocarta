"""Tests for embedding-node selection."""

from unittest.mock import MagicMock

from neocarta.enrichment.embeddings.utils import get_nodes_to_embed
from neocarta.enums import NodeLabel


def test_get_nodes_to_embed_uses_name_and_type_when_description_is_missing():
    """Optional descriptions must not prevent schema nodes from receiving vectors."""
    driver = MagicMock()
    driver.execute_query.return_value = []

    get_nodes_to_embed(driver, NodeLabel.COLUMN)

    query = driver.execute_query.call_args.kwargs["query_"]
    assert "n.description IS NOT NULL" not in query
    assert "[n.name, n.type, n.description]" in query
    assert "reduce(text = head(parts)" in query
