"""Layer A characterization: CSV connector transform-level output (no Docker).

Golden-master of the node/relationship model lists and the ``get_properties``
allowlist ``CSVTransformer`` produces from the committed ``datasets/csv`` sample.
Runs fully offline against a mock Neo4j driver (``extract``/``transform`` never touch
it). Regenerate intentionally with ``UPDATE_GOLDENS=1`` / ``--update-goldens``. See
``docs/testing/characterization-harness.md``.
"""

from pathlib import Path
from unittest.mock import MagicMock

from neocarta.connectors.csv import CSVConnector
from tests.support.characterization import (
    DATASETS_CSV,
    assert_matches_golden,
    assert_transform_embeddings_absent,
    serialize_transform,
)

_GOLDEN = Path(__file__).parent / "golden" / "csv_transform.json"


def test_csv_transform_output_matches_golden() -> None:
    """The CSV transform output matches the committed golden byte-for-byte."""
    connector = CSVConnector(csv_directory=str(DATASETS_CSV), neo4j_driver=MagicMock())
    connector.extract()
    connector.transform()

    assert_transform_embeddings_absent(connector.transformer)
    assert_matches_golden(_GOLDEN, serialize_transform(connector.transformer))
