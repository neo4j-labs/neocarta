"""Layer A characterization: BigQuery schema transform-level output (no Docker).

Golden-masters the node/relationship model lists ``BigQuerySchemaTransformer`` produces
from the shared offline customers/orders extractor cache — capturing the current (pre-
normalizer) BigQuery behavior on ``main`` as the safety-net baseline (GUIDE §4
characterization-first). Regenerate with ``UPDATE_GOLDENS=1``.
"""

from pathlib import Path

import pytest

from neocarta.connectors.bigquery.schema.transform import BigQuerySchemaTransformer
from tests.support.characterization import assert_matches_golden, serialize_transform

_GOLDEN = Path(__file__).parent / "golden" / "bigquery_schema_transform.json"


def _transform_output(extractor) -> dict:
    """Drive the transformer exactly as the connector does, then serialize its output."""
    transformer = BigQuerySchemaTransformer()
    transformer.transform_to_database_nodes(extractor.database_info)
    transformer.transform_to_schema_nodes(extractor.schema_info)
    transformer.transform_to_table_nodes(extractor.table_info)
    transformer.transform_to_column_nodes(extractor.column_info)
    transformer.transform_to_value_nodes(extractor.column_unique_values)
    transformer.transform_to_has_schema_relationships(extractor.schema_info)
    transformer.transform_to_has_table_relationships(extractor.table_info)
    transformer.transform_to_has_column_relationships(extractor.column_info)
    transformer.transform_to_references_relationships(extractor.column_references_info)
    transformer.transform_to_has_value_relationships(extractor.column_unique_values)
    return serialize_transform(transformer)


def test_bigquery_schema_transform_output_matches_golden(bigquery_extractor_with_cache) -> None:
    """Current BigQuery schema transform output matches the committed golden."""
    assert_matches_golden(_GOLDEN, _transform_output(bigquery_extractor_with_cache))


def test_golden_detects_injected_change(bigquery_extractor_with_cache, monkeypatch) -> None:
    """An injected table-id change makes the comparison fail — the golden catches regressions."""
    monkeypatch.setattr(
        "neocarta.connectors.bigquery.schema.transform.generate_table_id",
        lambda *_args, **_kwargs: "collapsed",
    )
    with pytest.raises(AssertionError):
        assert_matches_golden(
            _GOLDEN, _transform_output(bigquery_extractor_with_cache), update=False
        )
