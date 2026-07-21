"""Layer B (enrichment) characterization: CSV graph with stubbed embeddings.

Embeddings are the pipeline's one nondeterministic axis. This test demonstrates the
harness's stub: after ingest it runs :class:`DeterministicEmbeddingsConnector` (vectors
are a pure function of the description text) over Table + Column nodes, then dumps the
graph *including* the embedding vectors — proving the enrichment write path is
characterizable deterministically for the later S5 work. Regenerate with
``UPDATE_GOLDENS=1`` / ``--update-goldens``.
"""

from pathlib import Path

from neocarta.connectors.csv import CSVConnector
from neocarta.enums import NodeLabel
from tests.support.characterization import (
    DATASETS_CSV,
    DeterministicEmbeddingsConnector,
    assert_matches_golden,
    dump_graph,
)

_GOLDEN = Path(__file__).parent / "golden" / "csv_enriched_graph.json"


def test_csv_enriched_graph_matches_golden(neo4j_driver) -> None:
    """The CSV graph enriched with deterministic embeddings matches the golden."""
    CSVConnector(csv_directory=str(DATASETS_CSV), neo4j_driver=neo4j_driver).ingest()

    DeterministicEmbeddingsConnector(neo4j_driver, "neo4j", dimensions=8).run(
        [NodeLabel.TABLE, NodeLabel.COLUMN]
    )

    assert_matches_golden(_GOLDEN, dump_graph(neo4j_driver, "neo4j", include_embeddings=True))
