"""Layer B characterization: post-ingest Neo4j-connector graph (Docker).

Golden-masters the full post-ingest graph: the seeded source graph plus its LPG
description. Regenerate with ``UPDATE_GOLDENS=1``.
"""

from pathlib import Path

from neocarta.connectors.neo4j import Neo4jSchemaConnector
from tests.support.characterization import assert_matches_golden, dump_graph

_GOLDEN = Path(__file__).parent / "golden" / "neo4j_schema_graph.json"


def test_neo4j_ingest_graph_matches_golden(seeded_source):
    """The post-ingest graph matches the committed golden."""
    driver = seeded_source
    connector = Neo4jSchemaConnector(
        source_neo4j_driver=driver,
        neo4j_driver=driver,
        source_name="dbms",
    )
    connector.ingest(source_database="neo4j")

    assert_matches_golden(_GOLDEN, dump_graph(driver, "neo4j"))
