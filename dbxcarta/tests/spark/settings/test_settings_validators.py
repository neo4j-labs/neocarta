"""Settings boundary validation: field-level identifier constraints and cross-field coherence.

`_IDENTIFIER_RE` enforces strict Databricks identifier shape.
`model_validator(mode="after")` enforces cross-field coherence:
value embeddings require sample values.

All tests construct Settings with explicit kwargs — no cloud infra, no
Spark. Validates the boundary itself, not downstream behaviour.
"""

from __future__ import annotations

import pytest
from dbxcarta.spark.settings import SparkIngestSettings
from pydantic import ValidationError

_BASE_SETTINGS = {
    "databricks_secret_scope": "dbxcarta-neo4j-test",
    "dbxcarta_summary_volume": "/Volumes/cat/schema/vol/dbxcarta",
    "dbxcarta_summary_table": "cat.schema.table",
}


# --- _IDENTIFIER_RE validation -----------------------------------------------


@pytest.mark.parametrize(
    "bad_catalog",
    [
        "evil`catalog",  # backtick — injection vector
        "cat.subcat",  # dot (catalog must be single identifier)
        "cat name",  # space
        "1cat",  # leading digit
        "",  # empty
    ],
)
def test_settings_rejects_non_strict_catalog(bad_catalog: str) -> None:
    with pytest.raises(ValidationError, match="Invalid Databricks identifier"):
        SparkIngestSettings(dbxcarta_catalog=bad_catalog, **_BASE_SETTINGS)


@pytest.mark.parametrize(
    "good_catalog",
    [
        "main",
        "my_catalog",
        "_internal",
        "dbxcarta-catalog",  # hyphens are valid; require backtick-quoting in SQL
    ],
)
def test_settings_accepts_strict_catalog(good_catalog: str) -> None:
    s = SparkIngestSettings(dbxcarta_catalog=good_catalog, **_BASE_SETTINGS)
    assert s.dbxcarta_catalog == good_catalog


def test_settings_accepts_three_part_summary_table() -> None:
    s = SparkIngestSettings(
        databricks_secret_scope=_BASE_SETTINGS["databricks_secret_scope"],
        dbxcarta_catalog="main",
        dbxcarta_summary_volume=_BASE_SETTINGS["dbxcarta_summary_volume"],
        dbxcarta_summary_table="cat.schema.table",
    )
    assert s.dbxcarta_summary_table == "cat.schema.table"


@pytest.mark.parametrize(
    "bad_table",
    [
        "table_name",  # unqualified
        "schema.table",  # missing catalog
        "schema.`table`",  # backtick in a part — injection vector
        "schema..table",  # empty middle part
        "schema.1table",  # leading digit in a part
    ],
)
def test_settings_rejects_malformed_summary_table(bad_table: str) -> None:
    with pytest.raises(ValidationError, match="Invalid Databricks"):
        SparkIngestSettings(
            dbxcarta_catalog="main",
            dbxcarta_summary_volume=_BASE_SETTINGS["dbxcarta_summary_volume"],
            dbxcarta_summary_table=bad_table,
        )


@pytest.mark.parametrize(
    "bad_path",
    [
        "/Volumes/cat/schema/vol",  # volume root, no subdir
        "/dbfs/Volumes/cat/schema/vol/runs",
        "/Volumes/cat/schema",
    ],
)
def test_settings_rejects_non_volume_summary_paths(bad_path: str) -> None:
    with pytest.raises(ValidationError, match="DBXCARTA_SUMMARY_VOLUME"):
        SparkIngestSettings(
            dbxcarta_catalog="main",
            dbxcarta_summary_volume=bad_path,
            dbxcarta_summary_table=_BASE_SETTINGS["dbxcarta_summary_table"],
        )


def test_settings_accepts_explicit_ledger_volume_path() -> None:
    s = SparkIngestSettings(
        dbxcarta_catalog="main",
        dbxcarta_ledger_path="/Volumes/cat/schema/vol/ledger/",
        **_BASE_SETTINGS,
    )
    assert s.dbxcarta_ledger_path == "/Volumes/cat/schema/vol/ledger"


def test_settings_rejects_path_traversal_in_volume_subdir() -> None:
    with pytest.raises(ValidationError, match="invalid path segment"):
        SparkIngestSettings(
            dbxcarta_catalog="main",
            dbxcarta_summary_volume="/Volumes/cat/schema/vol/../runs",
            dbxcarta_summary_table=_BASE_SETTINGS["dbxcarta_summary_table"],
        )


def test_settings_rejects_unsafe_embedding_endpoint() -> None:
    with pytest.raises(ValidationError, match="serving endpoint"):
        SparkIngestSettings(
            dbxcarta_catalog="main",
            dbxcarta_embedding_endpoint="bad'endpoint",
            **_BASE_SETTINGS,
        )


# --- Cross-field validation --------------------------------------------------


def test_settings_rejects_value_embeddings_without_sampling() -> None:
    """DBXCARTA_INCLUDE_EMBEDDINGS_VALUES=true requires DBXCARTA_INCLUDE_VALUES=true.

    The Settings cross-field validator catches this at construction time so
    the job fails at startup instead of reaching an embedding step with no
    Value nodes to process.
    """
    with pytest.raises(ValidationError, match="DBXCARTA_INCLUDE_EMBEDDINGS_VALUES"):
        SparkIngestSettings(
            dbxcarta_catalog="main",
            dbxcarta_include_values=False,
            dbxcarta_include_embeddings_values=True,
            **_BASE_SETTINGS,
        )


# --- Multi-catalog list ------------------------------------------------------


@pytest.mark.parametrize(
    "bad_list",
    [
        "good,evil`cat",  # backtick in one entry — injection vector
        "good,cat.sub",  # dotted entry
        "good,1cat",  # leading digit
    ],
)
def test_settings_rejects_bad_catalog_in_multi_list(bad_list: str) -> None:
    with pytest.raises(ValidationError, match="Invalid Databricks catalog"):
        SparkIngestSettings(
            dbxcarta_catalog="main",
            dbxcarta_catalogs=bad_list,
            **_BASE_SETTINGS,
        )


def test_settings_accepts_valid_multi_catalog_list() -> None:
    s = SparkIngestSettings(
        dbxcarta_catalog="main",
        dbxcarta_catalogs="bronze, silver ,gold",
        **_BASE_SETTINGS,
    )
    assert s.resolved_catalogs() == ["bronze", "silver", "gold"]


def test_resolved_catalogs_falls_back_to_single_when_blank() -> None:
    """Blank dbxcarta_catalogs preserves the historical single-catalog path."""
    s = SparkIngestSettings(dbxcarta_catalog="main", **_BASE_SETTINGS)
    assert s.resolved_catalogs() == ["main"]


def test_resolved_catalogs_dedupes_order_preserving() -> None:
    """A repeated catalog collapses without reordering — no double-count."""
    s = SparkIngestSettings(
        dbxcarta_catalog="main",
        dbxcarta_catalogs="bronze,gold,bronze,silver,gold",
        **_BASE_SETTINGS,
    )
    assert s.resolved_catalogs() == ["bronze", "gold", "silver"]


def test_resolved_catalogs_strips_whitespace_and_empties() -> None:
    s = SparkIngestSettings(
        dbxcarta_catalog="main",
        dbxcarta_catalogs=" bronze ,, gold ,",
        **_BASE_SETTINGS,
    )
    assert s.resolved_catalogs() == ["bronze", "gold"]


# --- Layer map (folded into dbxcarta_catalogs) -------------------------------


def test_layer_map_parses_suffixes_from_catalogs() -> None:
    s = SparkIngestSettings(
        dbxcarta_catalog="main",
        dbxcarta_catalogs="bronze:bronze, silver:silver ,gold:gold",
        **_BASE_SETTINGS,
    )
    assert s.layer_map() == {"bronze": "bronze", "silver": "silver", "gold": "gold"}
    # The same list resolves to bare catalog names with the suffix stripped,
    # so readiness and the pipeline can never disagree on the catalog set.
    assert s.resolved_catalogs() == ["bronze", "silver", "gold"]


def test_layer_map_empty_when_no_suffixes() -> None:
    s = SparkIngestSettings(
        dbxcarta_catalog="main",
        dbxcarta_catalogs="bronze,silver,gold",
        **_BASE_SETTINGS,
    )
    assert s.layer_map() == {}


def test_layer_map_empty_by_default() -> None:
    s = SparkIngestSettings(dbxcarta_catalog="main", **_BASE_SETTINGS)
    assert s.layer_map() == {}


def test_layer_map_subset_of_catalogs() -> None:
    """Only some entries carry a suffix; the rest yield a null layer."""
    s = SparkIngestSettings(
        dbxcarta_catalog="main",
        dbxcarta_catalogs="bronze:bronze,silver,gold:gold",
        **_BASE_SETTINGS,
    )
    assert s.layer_map() == {"bronze": "bronze", "gold": "gold"}
    assert s.resolved_catalogs() == ["bronze", "silver", "gold"]


@pytest.mark.parametrize(
    "bad_entry",
    [
        "bronze:b:extra",  # two colons
        "bronze:",  # empty layer
        "1bad:bronze",  # bad catalog identifier
        "bronze:has space",  # non-alnum layer token
    ],
)
def test_settings_rejects_malformed_catalog_layer_entry(bad_entry: str) -> None:
    with pytest.raises(ValidationError):
        SparkIngestSettings(
            dbxcarta_catalog="main",
            dbxcarta_catalogs=bad_entry,
            **_BASE_SETTINGS,
        )
