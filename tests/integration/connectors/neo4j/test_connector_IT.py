"""End-to-end integration test: introspect a seeded source graph into the LPG graph."""

from collections import Counter

from neocarta.connectors.neo4j import Neo4jSchemaConnector

_RESERVED_LABELS = ["Database", "Schema", "Node", "Relationship", "Property"]
_RESERVED_TYPES = [
    "HAS_SCHEMA",
    "HAS_NODE",
    "HAS_RELATIONSHIP",
    "HAS_SOURCE_NODE",
    "HAS_TARGET_NODE",
    "HAS_PROPERTY",
]


def _graph_snapshot(driver):
    """Fingerprint the whole graph: node counts by label set and edge counts by type."""
    with driver.session(database="neo4j") as session:
        node_rows = session.run("MATCH (n) RETURN labels(n) AS labels").data()
        rel_rows = session.run("MATCH ()-[r]->() RETURN type(r) AS t").data()
    nodes = Counter(tuple(sorted(r["labels"])) for r in node_rows)
    rels = Counter(r["t"] for r in rel_rows)
    return dict(nodes), dict(rels)


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


def test_repeated_ingest_is_idempotent(seeded_source):
    """Re-ingesting into the same database does not accumulate neocarta's own metadata.

    The target IS the source database here, so the second and third ingests also see
    neocarta's own LPG output (``Database`` / ``Schema`` / ``Node`` / ``Relationship`` /
    ``Property`` and the ``HAS_*`` edges) reported back by ``apoc.meta.schema()``. The
    reserved-vocabulary exclusion must keep the graph byte-stable across re-runs.
    """
    driver = seeded_source

    Neo4jSchemaConnector(
        source_neo4j_driver=driver, neo4j_driver=driver, source_name="dbms"
    ).ingest(source_database="neo4j")
    baseline = _graph_snapshot(driver)

    for _ in range(2):
        Neo4jSchemaConnector(
            source_neo4j_driver=driver, neo4j_driver=driver, source_name="dbms"
        ).ingest(source_database="neo4j")
        assert _graph_snapshot(driver) == baseline

    with driver.session(database="neo4j") as session:
        # No :Node / :Relationship describes neocarta's own reserved vocabulary.
        self_labels = session.run(
            "MATCH (n:Node) WHERE n.label IN $r RETURN count(n) AS c", r=_RESERVED_LABELS
        ).single()["c"]
        self_types = session.run(
            "MATCH (r:Relationship) WHERE r.type IN $r RETURN count(r) AS c", r=_RESERVED_TYPES
        ).single()["c"]
    assert self_labels == 0
    assert self_types == 0
