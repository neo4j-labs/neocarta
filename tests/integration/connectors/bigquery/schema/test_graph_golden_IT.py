"""Layer B characterization: BigQuery schema post-ingest graph state (Docker).

BigQuery's ``ingest()`` calls the live BigQuery API, so this seeds the extractor cache
offline (the shared customers/orders fixture) and drives transform → load → metadata
directly into a Neo4j testcontainer, then golden-masters the resulting graph. The
``__neocarta_graph__`` singleton is excluded from the dump and characterized by shape
invariants. Regenerate with ``UPDATE_GOLDENS=1`` / ``--update-goldens``.
"""

from pathlib import Path

import neocarta
from neocarta.connectors.bigquery.schema.connector import BigQuerySchemaConnector
from tests.support.characterization import (
    assert_matches_golden,
    dump_graph,
    fetch_metadata_node,
    make_mock_bigquery_client,
    seed_bigquery_schema_cache,
)

_GOLDEN = Path(__file__).parent / "golden" / "bigquery_schema_graph.json"
_EXPECTED_LABELS = {"Database", "Schema", "Table", "Column", "Value"}


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

    graph = dump_graph(neo4j_driver, "neo4j")

    labels_present = {label for node in graph["nodes"] for label in node["labels"]}
    assert labels_present >= _EXPECTED_LABELS, _EXPECTED_LABELS - labels_present

    metadata = fetch_metadata_node(neo4j_driver, "neo4j")
    assert metadata is not None
    assert metadata["initial_version"] == metadata["latest_version"] == neocarta.__version__
    assert metadata["create_date"] <= metadata["last_updated"]

    assert_matches_golden(_GOLDEN, graph)
