"""Phase 4 stage precondition: Ingest confirms Materialize produced tables.

These exercise ``_assert_materialized_tables_exist`` directly with a fake Spark
session so the catalog-scan SQL and the fail-loud behavior are covered without a
live warehouse. The check's contract: at least one user table anywhere in the
resolved catalogs (scoped to the configured schemas, or all non-system schemas
when blank) passes; zero tables raises a clear "run Materialize first" error.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest
from dbxcarta.spark.ingest.preflight import _assert_materialized_tables_exist


class _FakeDF:
    def __init__(self, rows: list[tuple]) -> None:
        self._rows = rows

    def take(self, n: int) -> list[tuple]:
        return self._rows[:n]


class _FakeSpark:
    """Returns ``rows`` for any query whose catalog is in ``has_tables``."""

    def __init__(self, has_tables: set[str]) -> None:
        self._has_tables = has_tables
        self.queries: list[str] = []

    def sql(self, query: str) -> _FakeDF:
        self.queries.append(query)
        present = any(f"`{c}`" in query for c in self._has_tables)
        return _FakeDF([(1,)] if present else [])


def _settings(schemas: str = "") -> SimpleNamespace:
    return SimpleNamespace(dbxcarta_schemas=schemas)


def test_passes_when_a_table_is_present() -> None:
    spark = _FakeSpark(has_tables={"cat"})

    _assert_materialized_tables_exist(spark, _settings(), ["cat"])

    assert "information_schema.tables" in spark.queries[0]
    assert "table_schema <> 'information_schema'" in spark.queries[0]


def test_raises_clear_error_when_no_tables() -> None:
    spark = _FakeSpark(has_tables=set())

    with pytest.raises(RuntimeError, match="Materialize stage must run before Ingest"):
        _assert_materialized_tables_exist(spark, _settings(), ["cat"])


def test_error_names_the_scanned_catalogs() -> None:
    spark = _FakeSpark(has_tables=set())

    with pytest.raises(RuntimeError, match="cat_a, cat_b"):
        _assert_materialized_tables_exist(spark, _settings(), ["cat_a", "cat_b"])


def test_scopes_to_configured_schemas_when_set() -> None:
    spark = _FakeSpark(has_tables={"cat"})

    _assert_materialized_tables_exist(spark, _settings("s1,s2"), ["cat"])

    assert "table_schema IN ('s1', 's2')" in spark.queries[0]


def test_no_schema_filter_when_schemas_blank() -> None:
    spark = _FakeSpark(has_tables={"cat"})

    _assert_materialized_tables_exist(spark, _settings(""), ["cat"])

    assert " IN (" not in spark.queries[0]


def test_returns_on_first_catalog_with_tables() -> None:
    # First catalog empty, second has tables: the run is valid and must not
    # fail just because one resolved catalog materialized nothing.
    spark = _FakeSpark(has_tables={"cat_b"})

    _assert_materialized_tables_exist(spark, _settings(), ["cat_a", "cat_b"])

    assert len(spark.queries) == 2
