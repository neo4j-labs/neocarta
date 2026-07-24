"""Unit tests for the LPG loader's query building (mocked driver)."""

from unittest.mock import MagicMock

from neocarta.data_model.schema.lpg import (
    Database,
    HasNode,
    HasRelationship,
    HasSchema,
    HasSourceNode,
    HasTargetNode,
    Node,
    NodeHasProperty,
    Property,
    Relationship,
    RelationshipHasProperty,
    Schema,
)
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


def test_load_database_nodes_merges_on_database():
    loader, driver = _loader()

    loader.load_database_nodes([Database(id="dbms", name="dbms", service="NEO4J")])
    assert "MERGE (n:Database {id: row.id})" in _queries(driver)


def test_load_schema_nodes_merges_on_schema():
    loader, driver = _loader()

    loader.load_schema_nodes([Schema(id="dbms.neo4j", name="neo4j")])
    assert "MERGE (n:Schema {id: row.id})" in _queries(driver)


def test_load_relationship_nodes_merges_on_relationship():
    loader, driver = _loader()

    loader.load_relationship_nodes([Relationship(id="dbms.neo4j.knows", type="KNOWS")])
    q = _queries(driver)
    assert "MERGE (n:Relationship {id: row.id})" in q
    # search-entry-point index targets `type`, not `name`
    assert "relationship_type_index" in q


def test_load_property_nodes_merges_on_property():
    loader, driver = _loader()

    loader.load_property_nodes([Property(id="dbms.neo4j.person.name", name="name", type="STRING")])
    assert "MERGE (n:Property {id: row.id})" in _queries(driver)


def test_load_node_nodes_creates_label_index_not_name():
    loader, driver = _loader()
    loader.load_node_nodes([Node(id="dbms.neo4j.person", label="Person")])
    q = _queries(driver)
    assert "node_label_index" in q
    assert "node_name_index" not in q


def test_load_has_schema_relationships():
    loader, driver = _loader()

    loader.load_has_schema_relationships([HasSchema(database_id="dbms", schema_id="dbms.neo4j")])
    q = _queries(driver)
    assert "MATCH (n1:Database {id: row.database_id})" in q
    assert "MERGE (n1)-[r:HAS_SCHEMA]->(n2)" in q


def test_load_has_node_relationships():
    loader, driver = _loader()
    loader.load_has_node_relationships(
        [HasNode(schema_id="dbms.neo4j", node_id="dbms.neo4j.person")]
    )
    q = _queries(driver)
    assert "MATCH (n1:Schema {id: row.schema_id})" in q
    assert "MERGE (n1)-[r:HAS_NODE]->(n2)" in q


def test_load_has_relationship_relationships():
    loader, driver = _loader()

    loader.load_has_relationship_relationships(
        [HasRelationship(schema_id="dbms.neo4j", relationship_id="dbms.neo4j.knows")]
    )
    assert "MERGE (n1)-[r:HAS_RELATIONSHIP]->(n2)" in _queries(driver)


def test_load_has_source_node_relationships():
    loader, driver = _loader()

    loader.load_has_source_node_relationships(
        [HasSourceNode(relationship_id="dbms.neo4j.knows", node_id="dbms.neo4j.person")]
    )
    q = _queries(driver)
    assert "MATCH (n1:Relationship {id: row.relationship_id})" in q
    assert "MERGE (n1)-[r:HAS_SOURCE_NODE]->(n2)" in q


def test_load_has_target_node_relationships():
    loader, driver = _loader()

    loader.load_has_target_node_relationships(
        [HasTargetNode(relationship_id="dbms.neo4j.knows", node_id="dbms.neo4j.person")]
    )
    assert "MERGE (n1)-[r:HAS_TARGET_NODE]->(n2)" in _queries(driver)


def test_load_relationship_has_property_relationships():
    loader, driver = _loader()

    loader.load_relationship_has_property_relationships(
        [
            RelationshipHasProperty(
                source_id="dbms.neo4j.knows", property_id="dbms.neo4j.knows.since"
            )
        ]
    )
    q = _queries(driver)
    assert "MATCH (n1:Relationship {id: row.source_id})" in q
    assert "MERGE (n1)-[r:HAS_PROPERTY]->(n2)" in q


def test_upsert_neocarta_graph_node_delegates(monkeypatch):
    loader, _driver = _loader()
    called = {}

    def _fake(**kwargs):
        called.update(kwargs)
        return "graph"

    monkeypatch.setattr("neocarta.ingest.lpg.load.upsert_neocarta_graph_node", _fake)
    assert loader.upsert_neocarta_graph_node(version="test") == "graph"
    assert called["database_name"] == "neo4j"
    assert called["version"] == "test"
