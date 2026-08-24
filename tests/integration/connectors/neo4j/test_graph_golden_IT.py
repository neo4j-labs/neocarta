"""Layer B characterization: post-ingest Neo4j-connector graph (Docker).

Golden-masters the full post-ingest graph: the seeded source graph plus its LPG
description. Regenerate with ``UPDATE_GOLDENS=1``.
"""

from pathlib import Path

from neocarta.connectors.neo4j import Neo4jSchemaConnector
from tests.support.characterization import assert_matches_golden, dump_graph

_GOLDEN = Path(__file__).parent / "golden" / "neo4j_schema_graph.json"


def test_neo4j_ingest_graph_matches_golden(seeded_source, target_driver):
    """The post-ingest target graph matches the committed golden."""
    connector = Neo4jSchemaConnector(
        source_neo4j_driver=seeded_source,
        neo4j_driver=target_driver,
        source_name="dbms",
    )
    connector.ingest(source_database="neo4j")

    assert_matches_golden(_GOLDEN, dump_graph(target_driver, "neo4j"))
