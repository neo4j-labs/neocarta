"""Layer B characterization: CSV connector post-ingest graph state (Docker).

Ingests the committed ``datasets/csv`` sample into a Neo4j testcontainer and
golden-masters the resulting nodes + relationships. Deterministic by construction:
ingest is embedding-free and idempotent (MERGE on ``id``); the ``__neocarta_graph__``
singleton (wall-clock timestamps + release version) is excluded from the dump and
characterized by shape invariants instead. Regenerate with ``UPDATE_GOLDENS=1`` /
``--update-goldens``.
"""

from pathlib import Path

import pytest

import neocarta
from neocarta.connectors.csv import CSVConnector
from neocarta.connectors.utils.generate_id import generate_table_id
from tests.support.characterization import (
    DATASETS_CSV,
    assert_matches_golden,
    dump_graph,
    fetch_metadata_node,
)

_GOLDEN = Path(__file__).parent / "golden" / "csv_graph.json"
_EXPECTED_LABELS = {
    "Database",
    "Schema",
    "Table",
    "Column",
    "Value",
    "Query",
    "Glossary",
    "Category",
    "BusinessTerm",
}


def test_csv_post_ingest_graph_matches_golden(neo4j_driver) -> None:
    """The full CSV-ingested graph matches the committed golden byte-for-byte."""
    CSVConnector(csv_directory=str(DATASETS_CSV), neo4j_driver=neo4j_driver).ingest()

    graph = dump_graph(neo4j_driver, "neo4j")

    # Readable guard: every expected family is present (a vanished family fails here
    # loudly rather than only inside a large JSON diff).
    labels_present = {label for node in graph["nodes"] for label in node["labels"]}
    assert labels_present >= _EXPECTED_LABELS, _EXPECTED_LABELS - labels_present

    # Characterize the excluded metadata node by shape, never frozen values.
    metadata = fetch_metadata_node(neo4j_driver, "neo4j")
    assert metadata is not None
    assert metadata["initial_version"] == metadata["latest_version"] == neocarta.__version__
    assert metadata["create_date"] <= metadata["last_updated"]

    assert_matches_golden(_GOLDEN, graph)


def test_harness_detects_post_ingest_change(neo4j_driver, monkeypatch: pytest.MonkeyPatch) -> None:
    """Sensitivity proof: an injected id change makes the graph golden diverge (red).

    Complements the Layer A mutation meta-tests — confirms the post-ingest layer also
    catches a real behavior change, not just a no-op pass. ``update=False`` is explicit
    so a repo-wide regeneration run cannot subvert the assertion.
    """
    monkeypatch.setattr(
        "neocarta.connectors.csv.extract.generate_table_id",
        lambda *args, **kwargs: generate_table_id(*args, **kwargs) + "_MUT",
    )
    CSVConnector(csv_directory=str(DATASETS_CSV), neo4j_driver=neo4j_driver).ingest()

    with pytest.raises(AssertionError):
        assert_matches_golden(_GOLDEN, dump_graph(neo4j_driver, "neo4j"), update=False)
