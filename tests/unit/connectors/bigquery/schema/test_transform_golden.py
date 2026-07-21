"""Layer A characterization: BigQuery schema transform-level output (no Docker).

Golden-master of the node/relationship model lists ``NormalizedGraphTransformer``
produces from the shared offline customers/orders extractor cache. Complements the
existing ``test_normalized_parity.py`` (which pins the same output against in-code
literals): this frozen JSON is the reusable-harness form S1/S3 reuse. Regenerate with
``UPDATE_GOLDENS=1`` / ``--update-goldens``.
"""

from pathlib import Path

from neocarta.normalization.graph_transform import NormalizedGraphTransformer
from neocarta.normalization.information_schema.bigquery import (
    build_bigquery_information_schema_normalizer,
)
from tests.support.characterization import (
    assert_matches_golden,
    assert_transform_embeddings_absent,
    serialize_transform,
)

_GOLDEN = Path(__file__).parent / "golden" / "bigquery_schema_transform.json"


def test_bigquery_schema_transform_output_matches_golden(bigquery_extractor_with_cache) -> None:
    """The BigQuery schema transform output matches the committed golden byte-for-byte."""
    transformer = NormalizedGraphTransformer()
    normalizer = build_bigquery_information_schema_normalizer(bigquery_extractor_with_cache)
    transformer.transform(normalizer.normalize())

    assert_transform_embeddings_absent(transformer)
    assert_matches_golden(_GOLDEN, serialize_transform(transformer))
