"""Sensitivity proof for the CSV Layer A harness.

A golden test that cannot fail guards nothing. Each test writes a baseline golden to a
temp path, confirms the *unmutated* output still matches (green), then monkeypatches a
real production rule and asserts the comparison RAISES (red) — demonstrating the
harness detects an injected behavior change. ``update=`` is passed explicitly so a
repo-wide ``UPDATE_GOLDENS`` run cannot subvert the red assertion.
"""

from pathlib import Path
from unittest.mock import MagicMock

import pytest

from neocarta.connectors.csv import CSVConnector
from neocarta.connectors.utils.generate_id import generate_table_id
from tests.support.characterization import (
    DATASETS_CSV,
    assert_matches_golden,
    serialize_transform,
)


def _csv_transform_output() -> dict:
    connector = CSVConnector(csv_directory=str(DATASETS_CSV), neo4j_driver=MagicMock())
    connector.extract()
    connector.transform()
    return serialize_transform(connector.transformer)


def test_harness_detects_id_rule_change(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Changing the table-id rule (a real behavior change) makes the golden diverge."""
    golden = tmp_path / "csv_transform.json"
    assert_matches_golden(golden, _csv_transform_output(), update=True)  # capture baseline
    assert_matches_golden(
        golden, _csv_transform_output(), update=False
    )  # green: unchanged reproduces

    # Inject a real change at the id helper the CSV extractor uses to build table ids.
    monkeypatch.setattr(
        "neocarta.connectors.csv.extract.generate_table_id",
        lambda *args, **kwargs: generate_table_id(*args, **kwargs) + "_MUT",
    )
    with pytest.raises(AssertionError):
        assert_matches_golden(golden, _csv_transform_output(), update=False)


def test_harness_detects_property_allowlist_change(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Changing which columns are written (the allowlist) makes the golden diverge."""
    golden = tmp_path / "csv_transform.json"
    assert_matches_golden(golden, _csv_transform_output(), update=True)  # capture baseline

    # Inject a change to the get_properties allowlist (invisible to model_dump alone).
    monkeypatch.setattr(
        "neocarta.connectors.csv.transform._available_properties",
        lambda *_args, **_kwargs: [],
    )
    with pytest.raises(AssertionError):
        assert_matches_golden(golden, _csv_transform_output(), update=False)
