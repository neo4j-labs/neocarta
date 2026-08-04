"""End-to-end integration test: introspect a seeded source graph into the LPG graph."""

from neocarta.connectors.neo4j import Neo4jSchemaConnector


def test_ingest_builds_lpg_graph(seeded_source):
    """A full ingest describes the seeded source graph as LPG nodes/edges."""
    driver = seeded_source
    connector = Neo4jSchemaConnector(
        source_neo4j_driver=driver,
        neo4j_driver=driver,
        source_name="dbms",
    )
    connector.ingest(source_database="neo4j")

    with driver.session(database="neo4j") as session:
        # The LPG description (:Node/:Relationship/:Property) coexists with the
        # seeded source data (:Person/:KNOWS) -- disjoint labels, no collision.
        assert (
            session.run("MATCH (n:Node {label:'Person'}) RETURN count(n) AS c").single()["c"] == 1
        )
        assert (
            session.run("MATCH (r:Relationship {type:'KNOWS'}) RETURN count(r) AS c").single()["c"]
            == 1
        )
        assert (
            session.run(
                "MATCH (:Relationship {type:'KNOWS'})-[:HAS_SOURCE_NODE]->(:Node {label:'Person'}) "
                "RETURN count(*) AS c"
            ).single()["c"]
            == 1
        )
        assert (
            session.run(
                "MATCH (:Node {label:'Person'})-[:HAS_PROPERTY]->(p:Property {name:'email'}) "
                "RETURN p.unique AS u"
            ).single()["u"]
            is True
        )
        assert session.run("MATCH (g:__neocarta_graph__) RETURN count(g) AS c").single()["c"] == 1
