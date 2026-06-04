"""Phase 4: FK column-count guardrail backstop.

Exercises `_fk_guardrail_tripped` / `_skipped_result` independently of the
heavy `run_fk_discovery` path. Pins: disabled by default, below/above
limit behavior, the skip recorded on the summary, the all-None result
honoring the load-step None-edge contract, and the flat `fk_skipped*` keys
reaching `row_counts`.
"""

from __future__ import annotations

from dbxcarta.spark.ingest.fk.discovery import (
    _fk_guardrail_tripped,
    _skipped_result,
)
from dbxcarta.spark.ingest.summary import RunSummary
from dbxcarta.spark.settings import SparkIngestSettings
from dbxcarta.spark.verify.references import _check_accounting

_BASE = {
    "databricks_secret_scope": "dbxcarta-neo4j-test",
    "dbxcarta_catalog": "main",
    "dbxcarta_summary_volume": "/Volumes/cat/schema/vol/dbxcarta",
    "dbxcarta_summary_table": "cat.schema.table",
}


def _summary(columns: int) -> RunSummary:
    s = RunSummary(
        run_id="r1",
        job_name="job",
        contract_version="v1",
        catalog="main",
        schemas=["s"],
    )
    s.extract.columns = columns
    return s


def _settings(**overrides) -> SparkIngestSettings:
    return SparkIngestSettings(**{**_BASE, **overrides})


def test_disabled_by_default_never_trips() -> None:
    s = _summary(columns=10_000_000)
    assert _fk_guardrail_tripped(_settings(), s) is False
    assert s.fk_skip is None


def test_below_limit_runs_fk_and_records_nothing() -> None:
    s = _summary(columns=500)
    assert _fk_guardrail_tripped(_settings(dbxcarta_fk_max_columns=1000), s) is False
    assert s.fk_skip is None


def test_at_limit_runs_fk() -> None:
    """The comparison is strict `>`, so columns == limit still runs."""
    s = _summary(columns=1000)
    assert _fk_guardrail_tripped(_settings(dbxcarta_fk_max_columns=1000), s) is False
    assert s.fk_skip is None


def test_above_limit_skips_and_records_on_summary() -> None:
    s = _summary(columns=1001)
    assert _fk_guardrail_tripped(_settings(dbxcarta_fk_max_columns=1000), s) is True
    assert s.fk_skip is not None
    assert s.fk_skip.column_count == 1001
    assert s.fk_skip.column_limit == 1000


def test_skip_surfaces_in_row_counts() -> None:
    s = _summary(columns=1001)
    _fk_guardrail_tripped(_settings(dbxcarta_fk_max_columns=1000), s)
    rc = s.to_dict()["row_counts"]
    assert rc["fk_discovery_skipped"] == 1
    assert rc["fk_discovery_skipped_column_count"] == 1001
    assert rc["fk_discovery_skipped_column_limit"] == 1000
    # Must NOT collide with declared-FK accounting's `fk_skipped`.
    assert "fk_skipped" not in rc


def test_no_skip_keeps_row_counts_clean() -> None:
    s = _summary(columns=10)
    _fk_guardrail_tripped(_settings(dbxcarta_fk_max_columns=1000), s)
    assert "fk_discovery_skipped" not in s.to_dict()["row_counts"]


def test_guardrail_skip_does_not_break_declared_fk_accounting() -> None:
    """Regression for the `row_counts` key collision: a guardrail trip
    leaves declared FK absent, so reusing the bare `fk_skipped` key made
    `verify.references._check_accounting` see `fk_skipped(1) != 0 - 0` and
    raise a false `references.accounting_mismatch`. The namespaced
    `fk_discovery_skipped*` keys must not trip that invariant."""
    s = _summary(columns=1001)
    _fk_guardrail_tripped(_settings(dbxcarta_fk_max_columns=1000), s)
    codes = [v.code for v in _check_accounting(s.to_dict())]
    assert "references.accounting_mismatch" not in codes


def test_skipped_result_is_all_none_for_the_load_contract() -> None:
    r = _skipped_result()
    assert r.declared_edges_df is None
    assert r.declared_edge_count == 0
    assert r.metadata_edges_df is None
    assert r.metadata_edge_count == 0
    # Honors the FKDiscoveryResult None-edge contract: unpersist is a no-op.
    r.unpersist_cached()
