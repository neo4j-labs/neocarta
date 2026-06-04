from __future__ import annotations

import threading
from typing import Any

import pytest
from dbxcarta.materialize import run as run_mod
from dbxcarta.materialize.run import materialize_blueprint, run_materialize
from pyspark.errors import AnalysisException


class _Recorder:
    """Thread-safe fake ``run_sql`` that records statements and can fail matches.

    A matched statement raises ``AnalysisException`` — the kind of SQL-execution
    failure spark.sql raises on the cluster, which the shell tolerates (skips).
    """

    def __init__(self, fail_on: str | None = None) -> None:
        self.statements: list[str] = []
        self._fail_on = fail_on
        self._lock = threading.Lock()

    def __call__(self, statement: str, label: str) -> None:
        with self._lock:
            self.statements.append(statement)
        if self._fail_on is not None and self._fail_on in statement:
            raise AnalysisException(f"forced failure: {label}")


def _two_table_schema() -> list[dict[str, Any]]:
    return [
        {
            "uc_schema": "shop",
            "source_id": "shop_db",
            "tables": [
                {
                    "name": "customers",
                    "columns": [{"name": "id", "type": "int"}, {"name": "name", "type": "text"}],
                    "primary_keys": ["id"],
                    "foreign_keys": [],
                    "rows": [[1, "Ada"], [2, "Grace"]],
                },
                {
                    "name": "orders",
                    "columns": [
                        {"name": "id", "type": "int"},
                        {"name": "customer_id", "type": "int"},
                    ],
                    "primary_keys": ["id"],
                    "foreign_keys": [
                        {
                            "columns": ["customer_id"],
                            "foreign_table": "customers",
                            "referred_columns": ["id"],
                        }
                    ],
                    "rows": [[10, 1]],
                },
            ],
        }
    ]


@pytest.mark.parametrize("workers", [1, 4])
def test_materializes_schema_with_constraints(workers: int) -> None:
    rec = _Recorder()
    stats = materialize_blueprint(_two_table_schema(), catalog="cat", run_sql=rec, workers=workers)
    assert stats.schemas_created == 1
    assert stats.tables_created == 2
    assert stats.rows_inserted == 3
    assert stats.pk_constraints_added == 2
    assert stats.fk_constraints_added == 1

    joined = "\n".join(rec.statements)
    assert "CREATE SCHEMA IF NOT EXISTS `cat`.`shop`" in joined
    assert "COMMENT 'dbxcarta source: shop_db'" in joined
    assert "INSERT OVERWRITE TABLE `cat`.`shop`.`orders`" in joined
    assert "`id` INT NOT NULL" in joined
    assert "CONSTRAINT `pk_orders` PRIMARY KEY (`id`)" in joined
    assert "FOREIGN KEY (`customer_id`) REFERENCES `cat`.`shop`.`customers`" in joined
    # The shared product step uses a single constant property prefix.
    assert "'dbxcarta.source_id' = 'shop_db'" in joined


@pytest.mark.parametrize("workers", [1, 4])
def test_foreign_key_pass_runs_after_all_creates(workers: int) -> None:
    """The FK ALTER runs only after every table's CREATE in the schema."""
    rec = _Recorder()
    materialize_blueprint(_two_table_schema(), catalog="cat", run_sql=rec, workers=workers)
    create_idxs = [i for i, s in enumerate(rec.statements) if s.startswith("CREATE TABLE")]
    fk_idxs = [
        i for i, s in enumerate(rec.statements) if "ADD CONSTRAINT" in s and "FOREIGN KEY" in s
    ]
    assert create_idxs
    assert fk_idxs
    assert min(fk_idxs) > max(create_idxs)


@pytest.mark.parametrize("workers", [1, 4])
def test_skip_tolerates_failed_table_create(workers: int) -> None:
    rec = _Recorder(fail_on="CREATE TABLE")
    stats = materialize_blueprint(_two_table_schema(), catalog="cat", run_sql=rec, workers=workers)
    # One bad table never aborts the run; no table is created, so no FK is added.
    assert stats.tables_created == 0
    assert stats.fk_constraints_added == 0
    assert stats.schemas_created == 1


@pytest.mark.parametrize("workers", [1, 4])
def test_skip_tolerates_failed_insert(workers: int) -> None:
    rec = _Recorder(fail_on="INSERT OVERWRITE")
    stats = materialize_blueprint(_two_table_schema(), catalog="cat", run_sql=rec, workers=workers)
    assert stats.rows_inserted == 0
    assert stats.tables_created == 2  # tables still created despite insert failures


@pytest.mark.parametrize("workers", [1, 4])
def test_build_time_skip_counts_without_creating(workers: int) -> None:
    schemas = [
        {
            "uc_schema": "s",
            "source_id": "src",
            "tables": [
                {"name": "empty", "columns": [], "primary_keys": [], "rows": []},
                {
                    "name": "ok",
                    "columns": [{"name": "c", "type": "int"}],
                    "primary_keys": [],
                    "rows": [],
                },
            ],
        }
    ]
    stats = materialize_blueprint(schemas, catalog="cat", run_sql=_Recorder(), workers=workers)
    assert stats.tables_skipped == 1
    assert stats.tables_created == 1


def test_parallel_tally_sums_across_many_tables() -> None:
    schemas = [
        {
            "uc_schema": "s",
            "source_id": "src",
            "tables": [
                {
                    "name": f"t{i}",
                    "columns": [{"name": "c", "type": "int"}],
                    "primary_keys": [],
                    "foreign_keys": [],
                    "rows": [],
                }
                for i in range(40)
            ],
        }
    ]
    stats = materialize_blueprint(schemas, catalog="cat", run_sql=_Recorder(), workers=4)
    assert stats.tables_created == 40
    assert stats.schemas_created == 1


def test_rejects_schema_entry_missing_keys() -> None:
    entry = {"source_id": "src", "tables": []}  # missing uc_schema
    with pytest.raises(ValueError, match="missing required key.*uc_schema"):
        materialize_blueprint([entry], catalog="cat", run_sql=_Recorder())


@pytest.mark.parametrize("workers", [1, 4])
def test_non_sql_error_propagates_and_is_not_skipped(workers: int) -> None:
    """A non-SQL error (a programming bug) must abort, not be tolerated as a skip.

    The shell tolerates only SQL-execution failures (PySparkException/Py4JJavaError);
    anything else — here a RuntimeError standing in for a bug — propagates so a
    real defect is never masked as a silently skipped table.
    """

    def run_sql(statement: str, _label: str) -> None:
        if statement.startswith("CREATE TABLE"):
            raise RuntimeError("not a SQL error")

    with pytest.raises(RuntimeError, match="not a SQL error"):
        materialize_blueprint(_two_table_schema(), catalog="cat", run_sql=run_sql, workers=workers)


class _FakeSpark:
    """Minimal spark stand-in: only .sql is used (emit is stubbed in the test)."""

    def __init__(self, fail_schema: str) -> None:
        self.statements: list[str] = []
        self._fail_schema = fail_schema

    def sql(self, statement: str):
        self.statements.append(statement)
        if statement.startswith("CREATE SCHEMA") and f"`{self._fail_schema}`" in statement:
            raise AnalysisException(f"forced failure creating {self._fail_schema}")


def test_partial_failure_summary_records_what_landed(monkeypatch: pytest.MonkeyPatch) -> None:
    """A failure on schema 2 still records schema 1's schema name and tally.

    Regression guard for the summary-on-failure path: stats/schemas are applied
    per completed schema, so the emitted failure summary reflects what actually
    materialized rather than zeros / the planned set.
    """
    monkeypatch.setenv("DBXCARTA_CATALOG", "data_cat")
    monkeypatch.setenv("DATABRICKS_VOLUME_PATH", "/Volumes/ops/sch/vol")
    monkeypatch.delenv("DBXCARTA_SUMMARY_VOLUME", raising=False)
    monkeypatch.delenv("DBXCARTA_SUMMARY_TABLE", raising=False)
    monkeypatch.delenv("DBXCARTA_BLUEPRINT_VOLUME", raising=False)

    def _one_table_schema(name: str) -> dict[str, Any]:
        return {
            "uc_schema": name,
            "source_id": f"{name}_src",
            "tables": [
                {
                    "name": "t1",
                    "columns": [{"name": "id", "type": "int"}],
                    "primary_keys": [],
                    "foreign_keys": [],
                    "rows": [],
                }
            ],
        }

    monkeypatch.setattr(
        run_mod,
        "_load_blueprint_schemas",
        lambda _path: [_one_table_schema("schema1"), _one_table_schema("schema2")],
    )
    captured: dict[str, Any] = {}
    monkeypatch.setattr(
        run_mod,
        "_emit_summary",
        lambda summary, *a, **k: captured.setdefault("summary", summary),
    )

    spark = _FakeSpark(fail_schema="schema2")
    with pytest.raises(AnalysisException):
        run_materialize(spark=spark)

    summary = captured["summary"]
    assert summary.status == "failure"
    assert summary.schemas == ["schema1"]  # schema2 never landed
    assert summary.stats.schemas_created == 1
    assert summary.stats.tables_created == 1
