"""Layer A characterization: BigQuery schema transform-level output (no Docker).

Golden-masters the node/relationship model lists ``NormalizedGraphTransformer`` produces
from the shared offline customers/orders extractor cache. Complements
``test_normalized_parity.py`` (which pins the same output against in-code literals): this
frozen JSON is the reusable-harness form. Regenerate with ``UPDATE_GOLDENS=1``.
"""

from pathlib import Path

import pytest

from neocarta.normalization.graph_transform import NormalizedGraphTransformer
from neocarta.normalization.information_schema.bigquery import (
    build_bigquery_information_schema_normalizer,
)
from tests.support.characterization import assert_matches_golden, serialize_transform

_GOLDEN = Path(__file__).parent / "golden" / "bigquery_schema_transform.json"


def _transform_output(extractor) -> dict:
    transformer = NormalizedGraphTransformer()
    transformer.transform(build_bigquery_information_schema_normalizer(extractor).normalize())
    return serialize_transform(transformer)


def test_bigquery_schema_transform_output_matches_golden(bigquery_extractor_with_cache) -> None:
    """Current BigQuery schema transform output matches the committed golden."""
    assert_matches_golden(_GOLDEN, _transform_output(bigquery_extractor_with_cache))


def test_golden_detects_injected_change(bigquery_extractor_with_cache, monkeypatch) -> None:
    """An injected value-id change makes the comparison fail — the golden catches regressions."""
    monkeypatch.setattr(
        "neocarta.normalization.graph_transform.generate_value_id",
        lambda *_args, **_kwargs: "collapsed",
    )
    with pytest.raises(AssertionError):
        assert_matches_golden(
            _GOLDEN, _transform_output(bigquery_extractor_with_cache), update=False
        )
