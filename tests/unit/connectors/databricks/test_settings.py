"""Pure-Python tests for ``SparkIngestSettings`` validators and helpers.

These exercise the env-var trust boundary (identifier validation, numeric
guards, catalog-list parsing) with no Spark and no Neo4j, so they run in the
default ``test-unit`` group exactly like the other connectors' transform tests.
"""

from __future__ import annotations

import pytest

from neocarta.connectors.databricks.settings import SparkIngestSettings


def test_catalog_required_and_validated():
    """A valid catalog is accepted; an unsafe identifier is rejected."""
    settings = SparkIngestSettings(catalog="sales")
    assert settings.catalog == "sales"

    with pytest.raises(ValueError, match="Invalid Databricks identifier"):
        SparkIngestSettings(catalog="bad name.with.dots")


def test_platform_is_stripped_and_upper_cased():
    """The optional platform tag is normalized; blank stays blank."""
    assert SparkIngestSettings(catalog="c", platform="  aws ").platform == "AWS"
    assert SparkIngestSettings(catalog="c", platform="").platform == ""


def test_rel_write_partitions_must_be_at_least_one():
    """0 or negative partition counts are rejected at config load."""
    assert SparkIngestSettings(catalog="c", rel_write_partitions=4).rel_write_partitions == 4

    with pytest.raises(ValueError, match="REL_WRITE_PARTITIONS must be >= 1"):
        SparkIngestSettings(catalog="c", rel_write_partitions=0)


def test_fk_max_columns_must_be_non_negative():
    """0 disables the guardrail; a negative cap is rejected."""
    assert SparkIngestSettings(catalog="c", fk_max_columns=0).fk_max_columns == 0
    assert SparkIngestSettings(catalog="c", fk_max_columns=500).fk_max_columns == 500

    with pytest.raises(ValueError, match="FK_MAX_COLUMNS must be >= 0"):
        SparkIngestSettings(catalog="c", fk_max_columns=-1)


def test_catalogs_entries_are_validated():
    """A malformed catalog-list entry fails at startup."""
    # A bare catalog and a catalog:layer pair are both accepted.
    SparkIngestSettings(catalog="c", catalogs="cat_silver:silver, cat_gold:gold")

    with pytest.raises(ValueError, match="expected 'catalog' or a single 'catalog:layer' pair"):
        SparkIngestSettings(catalog="c", catalogs="cat:silver:extra")

    with pytest.raises(ValueError, match="expected a non-empty alphanumeric/underscore token"):
        SparkIngestSettings(catalog="c", catalogs="cat:bad-layer")


def test_resolved_catalogs_falls_back_to_single_catalog():
    """A blank catalogs list resolves to just the primary catalog."""
    assert SparkIngestSettings(catalog="sales").resolved_catalogs() == ["sales"]


def test_resolved_catalogs_dedupes_and_preserves_order():
    """The multi-catalog list is order-preserving and de-duplicated."""
    settings = SparkIngestSettings(
        catalog="sales", catalogs="cat_silver:silver, cat_gold:gold, cat_silver"
    )
    assert settings.resolved_catalogs() == ["cat_silver", "cat_gold"]


def test_layer_map_only_includes_entries_with_a_layer_suffix():
    """Entries without a ``:layer`` suffix contribute no mapping."""
    settings = SparkIngestSettings(catalog="c", catalogs="cat_silver:silver, cat_plain")
    assert settings.layer_map() == {"cat_silver": "silver"}


def test_embeddings_off_by_default_is_external_mode():
    """All inline embedding flags default off, so the default is external mode."""
    settings = SparkIngestSettings(catalog="c")
    assert settings.any_embeddings_enabled() is False
    assert settings.embedding_endpoint == "databricks-gte-large-en"
    assert settings.embedding_dimension == 1024


def test_any_embeddings_enabled_flips_when_one_label_is_on():
    """Turning on a single per-label flag switches to inline mode."""
    settings = SparkIngestSettings(
        catalog="c",
        include_embeddings_columns=True,
        embedding_staging_volume="/Volumes/c/s/v/staging",
    )
    assert settings.any_embeddings_enabled() is True


def test_embedding_batch_tables_must_be_at_least_one():
    """A batch must hold at least one table; 0 or negative is rejected."""
    assert SparkIngestSettings(catalog="c", embedding_batch_tables=50).embedding_batch_tables == 50

    with pytest.raises(ValueError, match="EMBEDDING_BATCH_TABLES must be >= 1"):
        SparkIngestSettings(catalog="c", embedding_batch_tables=0)


def test_embedding_failure_max_must_be_non_negative():
    """0 disables the per-batch failure gate; a negative cap is rejected."""
    assert SparkIngestSettings(catalog="c", embedding_failure_max=0).embedding_failure_max == 0

    with pytest.raises(ValueError, match="EMBEDDING_FAILURE_MAX must be >= 0"):
        SparkIngestSettings(catalog="c", embedding_failure_max=-1)


def test_embedding_endpoint_is_validated():
    """An endpoint name that cannot be safely interpolated into SQL is rejected."""
    # A hyphenated name (like the default databricks-gte-large-en) is accepted.
    settings = SparkIngestSettings(catalog="c", embedding_endpoint="my-endpoint")
    assert settings.embedding_endpoint == "my-endpoint"

    with pytest.raises(ValueError, match="Invalid Databricks serving endpoint"):
        SparkIngestSettings(catalog="c", embedding_endpoint="bad'; DROP")


def test_inline_embeddings_require_a_staging_volume():
    """Turning on any embedding flag without a staging volume fails at load."""
    with pytest.raises(ValueError, match="require NEOCARTA_DATABRICKS_EMBEDDING_STAGING_VOLUME"):
        SparkIngestSettings(catalog="c", include_embeddings_tables=True)


def test_staging_volume_must_be_a_volumes_subpath():
    """A staging volume that is not a /Volumes/<cat>/<schema>/<vol>/<subdir> fails."""
    with pytest.raises(ValueError, match="EMBEDDING_STAGING_VOLUME"):
        SparkIngestSettings(
            catalog="c",
            include_embeddings_tables=True,
            embedding_staging_volume="/Volumes/c/s/v",  # bare volume root, no subdir
        )


def test_staging_volume_is_ignored_in_external_mode():
    """External mode never reads the staging volume, so a blank one is fine."""
    settings = SparkIngestSettings(catalog="c")
    assert settings.any_embeddings_enabled() is False
    assert settings.embedding_staging_volume == ""
    assert settings.ledger_enabled is False


def test_ledger_is_off_by_default_with_a_blank_path():
    """The cross-run ledger defaults off, deriving its path at runtime."""
    settings = SparkIngestSettings(catalog="c")
    assert settings.ledger_enabled is False
    assert settings.ledger_path == ""


def test_explicit_ledger_path_is_accepted_and_trailing_slash_trimmed():
    """An explicit /Volumes ledger path is accepted with its trailing slash trimmed."""
    settings = SparkIngestSettings(catalog="c", ledger_path="/Volumes/cat/schema/vol/ledger/")
    assert settings.ledger_path == "/Volumes/cat/schema/vol/ledger"


def test_ledger_path_rejects_a_non_volumes_subpath():
    """A ledger path that is not a /Volumes subpath fails at config load."""
    with pytest.raises(ValueError, match="NEOCARTA_DATABRICKS_LEDGER_PATH"):
        SparkIngestSettings(catalog="c", ledger_path="/tmp/ledger")


def test_ledger_path_rejects_path_traversal_segments():
    """A `..` segment in the ledger path is rejected as an invalid segment."""
    with pytest.raises(ValueError, match="invalid path segment"):
        SparkIngestSettings(catalog="c", ledger_path="/Volumes/cat/schema/vol/../ledger")
