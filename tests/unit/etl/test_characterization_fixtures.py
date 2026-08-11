"""The shared characterization seed matches what the real extractor actually produces.

A golden is only as trustworthy as the fixture feeding it. The BigQuery value seed used to carry
three columns (``project_id`` / ``dataset_id`` / ``table_name``) that the real extractor never
writes, under a comment claiming it mirrored it — added speculatively for a future normalizer.
Nothing read them, so no golden was wrong, but the trap was live: a normalizer built against the
fixture would have worked in tests and failed on real data, and the failure would have surfaced
during the S4 cutover rather than here.

So the fixture's shape is pinned rather than maintained by eye. The columns below are the ones
``extract_column_unique_values_for_table`` declares for its empty frame, which is the
extractor's own statement of the value frame's shape.
"""

from __future__ import annotations

from neocarta.connectors.bigquery.schema.extract import BigQuerySchemaExtractor
from tests.support.characterization.bigquery_cache import (
    make_mock_bigquery_client,
    seed_bigquery_schema_cache,
)

REAL_VALUE_FRAME_COLUMNS = ["column_name", "unique_value", "column_id", "value_id"]


def test_value_seed_matches_the_extractors_frame_shape() -> None:
    """The seeded value frame has exactly the extractor's columns — no more, no fewer.

    The "no more" half is the one that matters: an extra column makes the fixture more
    convenient and less true, and a consumer that reads it passes here and fails live. The
    container path a value record needs is recovered from ``column_id`` instead, which is the
    projection ``normalized_schema/README.md`` records as the connector's to own.
    """
    extractor = seed_bigquery_schema_cache(
        BigQuerySchemaExtractor(client=make_mock_bigquery_client(), dataset_id="test_dataset")
    )
    assert list(extractor.column_unique_values.columns) == REAL_VALUE_FRAME_COLUMNS
