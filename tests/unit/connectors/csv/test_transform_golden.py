"""Layer A characterization: CSV connector transform-level output (no Docker).

Golden-masters the node/relationship model lists and ``get_properties`` allowlist
``CSVTransformer`` produces from the committed ``datasets/csv`` sample, running offline
against a mock Neo4j driver. Regenerate intentionally with ``UPDATE_GOLDENS=1``.
"""

from pathlib import Path
from unittest.mock import MagicMock

import pytest

from neocarta.connectors.csv import CSVConnector
from neocarta.connectors.utils.generate_id import generate_table_id
from tests.support.characterization import DATASETS_CSV, assert_matches_golden, serialize_transform

_GOLDEN = Path(__file__).parent / "golden" / "csv_transform.json"


def _transform_output() -> dict:
    connector = CSVConnector(csv_directory=str(DATASETS_CSV), neo4j_driver=MagicMock())
    connector.extract()
    connector.transform()
    return serialize_transform(connector.transformer)


def test_csv_transform_output_matches_golden() -> None:
    """Current CSV transform output matches the committed golden (parity on a no-op)."""
    assert_matches_golden(_GOLDEN, _transform_output())


def test_golden_detects_injected_change(monkeypatch: pytest.MonkeyPatch) -> None:
    """An injected id-rule change makes the comparison fail — the golden catches regressions."""
    monkeypatch.setattr(
        "neocarta.connectors.csv.extract.generate_table_id",
        lambda *args, **kwargs: generate_table_id(*args, **kwargs) + "_x",
    )
    with pytest.raises(AssertionError):
        assert_matches_golden(_GOLDEN, _transform_output(), update=False)
