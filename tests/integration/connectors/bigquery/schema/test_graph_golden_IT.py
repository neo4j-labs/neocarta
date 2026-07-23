"""Layer B characterization: BigQuery schema post-ingest graph state (Docker).

BigQuery's ``ingest()`` calls the live BigQuery API, so the extractor cache is seeded
offline (the shared customers/orders fixture) and transform -> load -> metadata is driven
directly into a Neo4j testcontainer. Regenerate with ``UPDATE_GOLDENS=1``.
"""

from pathlib import Path

from neocarta.connectors.bigquery.schema.connector import BigQuerySchemaConnector
from tests.support.characterization import (
    assert_matches_golden,
    dump_graph,
    make_mock_bigquery_client,
    seed_bigquery_schema_cache,
)

_GOLDEN = Path(__file__).parent / "golden" / "bigquery_schema_graph.json"


def test_bigquery_schema_post_ingest_graph_matches_golden(neo4j_driver) -> None:
    """The full BigQuery-schema-ingested graph matches the committed golden."""
    connector = BigQuerySchemaConnector(
        client=make_mock_bigquery_client(),
        project_id="test-project-id",
        neo4j_driver=neo4j_driver,
    )
    seed_bigquery_schema_cache(connector.extractor)
    connector._extracted = True  # cache seeded offline; skip the live extract() network calls
    connector.transform()
    connector.load()
    connector.loader.upsert_neocarta_graph_node()
    assert_matches_golden(_GOLDEN, dump_graph(neo4j_driver, "neo4j"))
