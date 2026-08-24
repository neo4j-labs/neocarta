"""Integration tests: load hand-built LPG objects into a real Neo4j testcontainer."""

from neocarta.data_model.schema.lpg import (
    Database,
    HasNode,
    HasSchema,
    Node,
    NodeHasProperty,
    Property,
    Schema,
)
from neocarta.ingest.lpg import Neo4jLPGLoader


def test_lpg_loader_writes_nodes_edges_and_indexes(neo4j_driver):
    """A full LPG load writes the nodes, edges, indexes, and metadata node."""
    loader = Neo4jLPGLoader(neo4j_driver, "neo4j")
    loader.load_database_nodes([Database(id="dbms", name="dbms", service="NEO4J")])
    loader.load_schema_nodes([Schema(id="dbms.neo4j", name="neo4j")])
    loader.load_node_nodes([Node(id="dbms.neo4j.person", label="Person")])
    loader.load_property_nodes([Property(id="dbms.neo4j.person.name", name="name", type="STRING")])
    loader.load_has_schema_relationships([HasSchema(database_id="dbms", schema_id="dbms.neo4j")])
    loader.load_has_node_relationships(
        [HasNode(schema_id="dbms.neo4j", node_id="dbms.neo4j.person")]
    )
    loader.load_node_has_property_relationships(
        [NodeHasProperty(source_id="dbms.neo4j.person", property_id="dbms.neo4j.person.name")]
    )
    loader.upsert_neocarta_graph_node(version="test")

    with neo4j_driver.session(database="neo4j") as session:
        assert (
            session.run("MATCH (n:Node {id:'dbms.neo4j.person'}) RETURN n.label AS l").single()["l"]
            == "Person"
        )
        assert (
            session.run(
                "MATCH (:Node)-[:HAS_PROPERTY]->(p:Property) RETURN count(p) AS c"
            ).single()["c"]
            == 1
        )
        assert (
            session.run(
                "MATCH (:Database)-[:HAS_SCHEMA]->(:Schema)-[:HAS_NODE]->(:Node) "
                "RETURN count(*) AS c"
            ).single()["c"]
            == 1
        )
        assert session.run("MATCH (g:__neocarta_graph__) RETURN count(g) AS c").single()["c"] == 1
        index_names = {r["name"] for r in session.run("SHOW INDEXES YIELD name RETURN name")}
        assert "node_label_index" in index_names
