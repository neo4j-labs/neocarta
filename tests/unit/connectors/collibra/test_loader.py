"""Unit tests for CollibraNeo4jLoader: dual labels, collibra_id index, tagged-by-uuid."""

from unittest.mock import MagicMock

import pytest

from neocarta.connectors.collibra.load import CollibraNeo4jLoader
from neocarta.data_model.rdbms import CollibraTable, CollibraTaggedWith


@pytest.fixture
def loader() -> tuple[CollibraNeo4jLoader, MagicMock]:
    """A loader wired to a MagicMock driver whose execute_query returns a 3-tuple."""
    driver = MagicMock()
    driver.execute_query.return_value = (None, MagicMock(), None)
    return CollibraNeo4jLoader(driver, "neo4j"), driver


def _queries(driver: MagicMock) -> list[str]:
    return [call.kwargs["query_"] for call in driver.execute_query.call_args_list]


def test_table_nodes_written_with_secondary_label_and_collibra_id_index(loader):
    """Table nodes get the :CollibraTable secondary label and a collibra_id range index."""
    ldr, driver = loader
    ldr.load_collibra_table_nodes(
        [CollibraTable(id="db.s.t", name="t", collibra_id="uuid-1", collibra_asset_type="Table")]
    )
    queries = _queries(driver)
    assert any("n:CollibraTable" in q for q in queries), "secondary label not applied"
    assert any(
        "collibratable_collibra_id_index" in q and "ON (n.collibra_id)" in q for q in queries
    ), "collibra_id range index not created on the secondary label"


def test_tagged_with_matches_source_by_collibra_id(loader):
    """TAGGED_WITH matches the tagged asset by collibra_id and the term by id."""
    ldr, driver = loader
    ldr.load_collibra_tagged_with_relationships(
        [CollibraTaggedWith(source_collibra_id="uuid-col", business_term_id="g.c.term")]
    )
    (query,) = _queries(driver)
    assert "collibra_id: row.source_collibra_id" in query
    assert "CollibraTable" in query
    assert "CollibraColumn" in query
    assert ":BusinessTerm" in query
    assert "TAGGED_WITH" in query


def test_tagged_with_passes_rows_as_dicts(loader):
    """Relationship rows are serialised to dicts for the driver."""
    ldr, driver = loader
    ldr.load_collibra_tagged_with_relationships(
        [CollibraTaggedWith(source_collibra_id="uuid-col", business_term_id="g.c.term")]
    )
    params = driver.execute_query.call_args.kwargs["parameters_"]
    assert params["rows"] == [{"source_collibra_id": "uuid-col", "business_term_id": "g.c.term"}]
