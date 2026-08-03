"""Layer B characterization: CSV connector post-ingest graph state (Docker).

Ingests the committed ``datasets/csv`` sample into a Neo4j testcontainer and
golden-masters the resulting nodes + relationships. Deterministic by construction:
ingest is embedding-free and idempotent (MERGE on ``id``), and ``dump_graph`` excludes
the ``__neocarta_graph__`` singleton and normalizes ordering. Regenerate with
``UPDATE_GOLDENS=1``.
"""

from pathlib import Path

from neocarta.connectors.csv import CSVConnector
from tests.support.characterization import DATASETS_CSV, assert_matches_golden, dump_graph

_GOLDEN = Path(__file__).parent / "golden" / "csv_graph.json"


def test_csv_post_ingest_graph_matches_golden(neo4j_driver) -> None:
    """The full CSV-ingested graph matches the committed golden."""
    CSVConnector(csv_directory=str(DATASETS_CSV), neo4j_driver=neo4j_driver).ingest()
    assert_matches_golden(_GOLDEN, dump_graph(neo4j_driver, "neo4j"))
