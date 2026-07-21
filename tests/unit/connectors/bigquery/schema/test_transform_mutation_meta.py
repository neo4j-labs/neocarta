"""Sensitivity proof for the BigQuery Layer A harness.

Demonstrates the harness catches two classes of real behavior change: an id-rule
change, and a regression in the self-referential-FK drop rule the transform is
required to apply. Each asserts the golden comparison RAISES under the mutation.
"""

from pathlib import Path

import pytest

from neocarta.connectors.utils.generate_id import generate_column_id
from neocarta.normalization import graph_transform as gt
from neocarta.normalization.graph_transform import NormalizedGraphTransformer
from neocarta.normalization.information_schema.bigquery import (
    build_bigquery_information_schema_normalizer,
)
from tests.support.characterization import assert_matches_golden, serialize_transform


def _output_from_cache(extractor) -> dict:
    transformer = NormalizedGraphTransformer()
    transformer.transform(build_bigquery_information_schema_normalizer(extractor).normalize())
    return serialize_transform(transformer)


def _output_from_metadata(metadata) -> dict:
    transformer = NormalizedGraphTransformer()
    transformer.transform(metadata)
    return serialize_transform(transformer)


def test_harness_detects_id_rule_change(
    bigquery_extractor_with_cache, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Collapsing value ids (a real behavior change) makes the golden diverge."""
    golden = tmp_path / "bigquery_schema_transform.json"
    assert_matches_golden(golden, _output_from_cache(bigquery_extractor_with_cache), update=True)
    assert_matches_golden(golden, _output_from_cache(bigquery_extractor_with_cache), update=False)

    monkeypatch.setattr(
        "neocarta.normalization.graph_transform.generate_value_id",
        lambda *_args, **_kwargs: "collapsed",
    )
    with pytest.raises(AssertionError):
        assert_matches_golden(
            golden, _output_from_cache(bigquery_extractor_with_cache), update=False
        )


def test_harness_detects_selfref_drop_regression(
    information_schema_table, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Dropping the self-referential-FK skip makes the references golden gain a row."""
    golden = tmp_path / "bigquery_schema_transform.json"
    assert_matches_golden(golden, _output_from_metadata(information_schema_table), update=True)
    assert_matches_golden(golden, _output_from_metadata(information_schema_table), update=False)

    def _build_without_selfref_skip(records):
        return [
            gt.References(
                source_column_id=generate_column_id(
                    record.source_database_name,
                    record.source_schema_name,
                    record.source_table_name,
                    record.source_column_name,
                ),
                target_column_id=generate_column_id(
                    record.target_database_name,
                    record.target_schema_name,
                    record.target_table_name,
                    record.target_column_name,
                ),
                criteria=record.criteria,
            )
            for record in records
        ]

    monkeypatch.setattr(
        NormalizedGraphTransformer,
        "_build_references_relationships",
        staticmethod(_build_without_selfref_skip),
    )
    with pytest.raises(AssertionError):
        assert_matches_golden(golden, _output_from_metadata(information_schema_table), update=False)
