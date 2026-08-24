"""End-to-end integration tests: introspect a seeded source graph into a separate target."""

from collections import Counter

import pytest

from neocarta.connectors.neo4j import Neo4jSchemaConnector
from neocarta.errors import ConfigError


def _graph_snapshot(driver):
    """Fingerprint the graph: node counts by label set, edge counts by type, and schema."""
    with driver.session(database="neo4j") as session:
        node_rows = session.run("MATCH (n) RETURN labels(n) AS labels").data()
        rel_rows = session.run("MATCH ()-[r]->() RETURN type(r) AS t").data()
        constraints = sorted(r["name"] for r in session.run("SHOW CONSTRAINTS YIELD name").data())
        indexes = sorted(r["name"] for r in session.run("SHOW INDEXES YIELD name").data())
    nodes = Counter(tuple(sorted(r["labels"])) for r in node_rows)
    rels = Counter(r["t"] for r in rel_rows)
    return dict(nodes), dict(rels), constraints, indexes


def test_ingest_builds_lpg_graph(seeded_source, target_driver):
    """A full ingest describes the seeded source graph as LPG nodes/edges in the target."""
    connector = Neo4jSchemaConnector(
        source_neo4j_driver=seeded_source,
        neo4j_driver=target_driver,
        source_name="dbms",
    )
    connector.ingest(source_database="neo4j")

    with target_driver.session(database="neo4j") as session:
        assert (
            session.run("MATCH (n:Node {label:'Person'}) RETURN count(n) AS c").single()["c"] == 1
        )
        # Reservation is gone: a source label named :Database is ingested faithfully.
        assert (
            session.run("MATCH (n:Node {label:'Database'}) RETURN count(n) AS c").single()["c"] == 1
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


def test_repeated_ingest_is_idempotent(seeded_source, target_driver):
    """Re-ingesting source -> a separate target yields a byte-stable target graph."""

    def _ingest():
        Neo4jSchemaConnector(
            source_neo4j_driver=seeded_source, neo4j_driver=target_driver, source_name="dbms"
        ).ingest(source_database="neo4j")

    _ingest()
    baseline = _graph_snapshot(target_driver)
    for _ in range(2):
        _ingest()
        assert _graph_snapshot(target_driver) == baseline


def test_same_database_ingest_is_refused(seeded_source):
    """Pointing the target at the source database is refused before any write."""
    driver = seeded_source  # source == target
    before = _graph_snapshot(driver)
    connector = Neo4jSchemaConnector(
        source_neo4j_driver=driver, neo4j_driver=driver, source_name="dbms"
    )
    with pytest.raises(ConfigError):
        connector.ingest(source_database="neo4j")
    # No neocarta nodes, edges, indexes, or constraints were written on refusal.
    assert _graph_snapshot(driver) == before
