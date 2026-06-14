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
