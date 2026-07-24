"""Unit tests for the LPG loader's query building (mocked driver)."""

from unittest.mock import MagicMock

from neocarta.data_model.schema.lpg import Node, NodeHasProperty
from neocarta.ingest.lpg import Neo4jLPGLoader


def _loader() -> tuple[Neo4jLPGLoader, MagicMock]:
    """Build a loader over a driver mock that takes the community-edition branch."""
    driver = MagicMock()
    # execute_query returns an unpackable (results, summary, keys); results[0]["edition"]
    # resolves to "community" so is_enterprise_edition (called during constraint writing)
    # takes the community branch without raising.
    driver.execute_query.return_value = ({"edition": "community"}, MagicMock(), None)
    return Neo4jLPGLoader(driver, "neo4j"), driver


def _queries(driver: MagicMock) -> str:
    return " ".join(c.kwargs.get("query_", "") for c in driver.execute_query.call_args_list)


def test_load_node_nodes_merges_on_node_label():
    loader, driver = _loader()
    loader.load_node_nodes([Node(id="dbms.neo4j.person", label="Person")])
    assert "MERGE (n:Node {id: row.id})" in _queries(driver)


def test_load_node_has_property_relationship_uses_node_source():
    loader, driver = _loader()
    loader.load_node_has_property_relationships(
        [NodeHasProperty(source_id="dbms.neo4j.person", property_id="dbms.neo4j.person.name")]
    )
    q = _queries(driver)
    assert "MATCH (n1:Node {id: row.source_id})" in q
    assert "MATCH (n2:Property {id: row.property_id})" in q
    assert "MERGE (n1)-[r:HAS_PROPERTY]->(n2)" in q
