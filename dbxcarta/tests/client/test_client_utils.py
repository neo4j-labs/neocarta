"""Unit tests for client utilities: parse_sql, _resolve_staging_table,
_format_schema, and ClientRunSummary aggregates."""

from __future__ import annotations

from types import SimpleNamespace

import pytest
from dbxcarta.client import compare_result_sets, parse_sql
from dbxcarta.client.eval.run import (
    _is_table_ref,
    _resolve_staging_table,
)
from dbxcarta.client.schema_dump import _format_schema
from dbxcarta.client.settings import ClientSettings
from dbxcarta.client.summary import ClientRunSummary

# ---------------------------------------------------------------------------
# _parse_sql
# ---------------------------------------------------------------------------


def test_parse_sql_plain_select():
    sql, ok = parse_sql("SELECT * FROM t")
    assert ok
    assert sql == "SELECT * FROM t"


def test_parse_sql_with_keyword():
    sql, ok = parse_sql("WITH cte AS (SELECT 1) SELECT * FROM cte")
    assert ok
    assert "WITH" in sql


def test_parse_sql_strips_sql_fence():
    sql, ok = parse_sql("```sql\nSELECT 1\n```")
    assert ok
    assert sql == "SELECT 1"


def test_parse_sql_strips_plain_fence():
    sql, ok = parse_sql("```\nSELECT 1\n```")
    assert ok
    assert sql == "SELECT 1"


def test_parse_sql_rejects_prose():
    _, ok = parse_sql("I cannot write that query.")
    assert not ok


def test_parse_sql_none_returns_false():
    sql, ok = parse_sql(None)
    assert not ok
    assert sql is None


def test_parse_sql_empty_string_returns_false():
    _, ok = parse_sql("")
    assert not ok


def test_parse_sql_case_insensitive_fence():
    sql, ok = parse_sql("```SQL\nSELECT 1\n```")
    assert ok
    assert sql == "SELECT 1"


# ---------------------------------------------------------------------------
# _resolve_staging_table
# ---------------------------------------------------------------------------


def _fake_settings(summary_table: str):
    return SimpleNamespace(dbxcarta_summary_table=summary_table)


def test_resolve_staging_table_standard():
    table = _resolve_staging_table(_fake_settings("cat.schema.run_summary"))
    assert table == "cat.schema.client_staging"


def test_resolve_staging_table_accepts_hyphenated_identifiers():
    table = _resolve_staging_table(
        _fake_settings("graph-enriched-lakehouse.graph-enriched-schema.run_summary")
    )
    assert table == "graph-enriched-lakehouse.graph-enriched-schema.client_staging"


def test_resolve_staging_table_rejects_short_name():
    with pytest.raises(ValueError):
        _resolve_staging_table(_fake_settings("schema.run_summary"))


def test_resolve_staging_table_rejects_invalid_identifier():
    with pytest.raises(ValueError):
        _resolve_staging_table(_fake_settings("cat.bad schema.run_summary"))


# ---------------------------------------------------------------------------
# _format_schema
# ---------------------------------------------------------------------------


def _rows(*specs, catalog="cat"):
    return [
        {
            "catalog_name": catalog,
            "schema_name": s,
            "table_name": t,
            "column_name": c,
            "data_type": d,
            "comment": comment,
        }
        for s, t, c, d, comment in specs
    ]


def test_format_schema_groups_by_table():
    rows = _rows(
        ("s", "t1", "id", "BIGINT", "pk"),
        ("s", "t1", "name", "STRING", ""),
        ("s", "t2", "val", "INT", None),
    )
    text = _format_schema(rows)
    assert "cat.s.t1" in text
    assert "cat.s.t2" in text
    assert "\n\n" in text  # blank line between tables


def test_format_schema_qualifies_each_row_by_its_own_catalog():
    rows = _rows(("s", "t", "id", "INT", ""), catalog="silver") + _rows(
        ("s", "g", "id", "INT", ""), catalog="gold"
    )
    text = _format_schema(rows)
    assert "silver.s.t" in text
    assert "gold.s.g" in text


def test_format_schema_appends_comment():
    rows = _rows(("s", "t", "id", "INT", "primary key"))
    text = _format_schema(rows)
    assert "— primary key" in text


def test_format_schema_omits_blank_comment():
    rows = _rows(("s", "t", "id", "INT", ""))
    text = _format_schema(rows)
    assert "—" not in text


def test_format_schema_omits_none_comment():
    rows = _rows(("s", "t", "id", "INT", None))
    text = _format_schema(rows)
    assert "—" not in text


# ---------------------------------------------------------------------------
# ClientRunSummary._compute_aggregates (via finish)
# ---------------------------------------------------------------------------


def _make_summary():
    return ClientRunSummary(
        run_id="test-1",
        job_name="test",
        catalog="cat",
        schemas=[],
        arms=["no_context", "schema_dump"],
    )


def test_compute_aggregates_counts():
    summary = _make_summary()
    summary.add_result("q1", "q?", "no_context", parsed=True, executed=True, non_empty=True)
    summary.add_result("q2", "q?", "no_context", parsed=True, executed=False)
    summary.add_result("q3", "q?", "no_context", parsed=False, executed=False)
    summary.finish(status="success")

    assert summary.arm_attempted["no_context"] == 3
    assert summary.arm_parsed["no_context"] == 2
    assert summary.arm_executed["no_context"] == 1
    assert summary.arm_non_empty["no_context"] == 1


def test_compute_aggregates_rates():
    summary = _make_summary()
    summary.add_result("q1", "q?", "schema_dump", parsed=True, executed=True, non_empty=True)
    summary.add_result("q2", "q?", "schema_dump", parsed=True, executed=True, non_empty=True)
    summary.add_result("q3", "q?", "schema_dump", parsed=True, executed=True, non_empty=False)
    summary.finish(status="success")

    assert summary.arm_execution_rate["schema_dump"] == 1.0
    assert summary.arm_non_empty_rate["schema_dump"] == round(2 / 3, 3)


def test_compute_aggregates_no_division_by_zero():
    summary = _make_summary()
    summary.finish(status="success")
    assert summary.arm_attempted == {}
    assert summary.arm_execution_rate == {}


def test_finish_records_status_and_time():
    summary = _make_summary()
    summary.finish(status="error", error="something broke")
    assert summary.status == "error"
    assert summary.error == "something broke"
    assert summary.ended_at is not None


def test_compute_aggregates_correct_rate():
    summary = _make_summary()
    summary.add_result(
        "q1",
        "q?",
        "no_context",
        parsed=True,
        executed=True,
        non_empty=True,
        correct=True,
        gradable=True,
    )
    summary.add_result(
        "q2",
        "q?",
        "no_context",
        parsed=True,
        executed=True,
        non_empty=True,
        correct=False,
        gradable=True,
    )
    summary.add_result(
        "q3",
        "q?",
        "no_context",
        parsed=True,
        executed=True,
        non_empty=True,
        correct=False,
        gradable=False,
    )
    summary.finish(status="success")

    assert summary.arm_correct["no_context"] == 1
    assert summary.arm_gradable["no_context"] == 2
    assert summary.arm_correct_rate["no_context"] == 0.5


def test_compute_aggregates_no_gradable_excludes_correct_rate():
    summary = _make_summary()
    summary.add_result("q1", "q?", "no_context", parsed=True, executed=True, non_empty=True)
    summary.finish(status="success")

    assert summary.arm_correct.get("no_context", 0) == 0
    assert summary.arm_gradable.get("no_context", 0) == 0
    assert "no_context" not in summary.arm_correct_rate


def test_emit_stdout_skips_incomplete_retrieval_metrics(capsys):
    summary = ClientRunSummary(
        run_id="test-1",
        job_name="test",
        catalog="cat",
        schemas=[],
        arms=["graph_rag"],
    )
    summary.add_result(
        "q1",
        "q?",
        "graph_rag",
        top1_schema_match=True,
        schema_in_context=False,
        context_purity=None,
    )
    summary.finish(status="success")

    summary.emit_stdout()
    assert "retrieval:" not in capsys.readouterr().out


# ---------------------------------------------------------------------------
# _is_table_ref
# ---------------------------------------------------------------------------


def test_is_table_ref_three_part_name():
    assert _is_table_ref("cat.schema.table")


def test_is_table_ref_absolute_path():
    assert not _is_table_ref("/Volumes/cat/schema/vol/questions.json")


def test_is_table_ref_relative_path():
    assert not _is_table_ref("./questions.json")


def test_is_table_ref_two_parts():
    assert not _is_table_ref("schema.table")


def test_client_settings_requires_three_part_summary_table() -> None:
    with pytest.raises(ValueError, match="summary table"):
        ClientSettings(
            databricks_secret_scope="dbxcarta-neo4j-test",
            dbxcarta_catalog="main",
            dbxcarta_summary_volume="/Volumes/cat/schema/vol/runs",
            dbxcarta_summary_table="schema.table",
            databricks_warehouse_id="abc",
            databricks_volume_path="/Volumes/cat/schema/vol",
        )


def test_client_settings_rejects_volume_root_as_summary_volume() -> None:
    with pytest.raises(ValueError, match="DBXCARTA_SUMMARY_VOLUME"):
        ClientSettings(
            databricks_secret_scope="dbxcarta-neo4j-test",
            dbxcarta_catalog="main",
            dbxcarta_summary_volume="/Volumes/cat/schema/vol",
            dbxcarta_summary_table="cat.schema.table",
            databricks_warehouse_id="abc",
            databricks_volume_path="/Volumes/cat/schema/vol",
        )


def test_client_settings_rejects_unsafe_chat_endpoint() -> None:
    with pytest.raises(ValueError, match="serving endpoint"):
        ClientSettings(
            databricks_secret_scope="dbxcarta-neo4j-test",
            dbxcarta_catalog="main",
            dbxcarta_summary_volume="/Volumes/cat/schema/vol/runs",
            dbxcarta_summary_table="cat.schema.table",
            databricks_warehouse_id="abc",
            databricks_volume_path="/Volumes/cat/schema/vol",
            dbxcarta_chat_endpoint="bad'endpoint",
        )


# ---------------------------------------------------------------------------
# _compare_result_sets
# ---------------------------------------------------------------------------


def test_compare_exact_match():
    cols = ["id", "name"]
    rows = [[1, "Alice"], [2, "Bob"]]
    correct, err = compare_result_sets(cols, rows, cols, [row[:] for row in rows])
    assert correct
    assert err is None


def test_compare_column_reorder_matches():
    gen_cols = ["name", "id"]
    gen_rows = [["Alice", 1], ["Bob", 2]]
    ref_cols = ["id", "name"]
    ref_rows = [[1, "Alice"], [2, "Bob"]]
    correct, err = compare_result_sets(gen_cols, gen_rows, ref_cols, ref_rows)
    assert correct, err


def test_compare_gen_missing_rows_is_mismatch():
    """Generated with fewer rows than reference is a real mismatch."""
    correct, err = compare_result_sets(["id"], [[1]], ["id"], [[1], [2]])
    assert not correct
    assert err is not None


def test_compare_gen_superset_of_ref_is_mismatch():
    """Generated with extra rows is a mismatch for small result sets."""
    correct, err = compare_result_sets(["id"], [[1], [2], [3]], ["id"], [[1], [3]])
    assert not correct
    assert err is not None


def test_compare_value_mismatch():
    correct, _err = compare_result_sets(["id"], [[1], [2]], ["id"], [[1], [3]])
    assert not correct


def test_compare_case_insensitive_strings():
    """'High' and 'high' should compare equal — the SQL filter case sensitivity
    is the model's problem, but the comparator should not double-penalize when
    the reference itself returns a case-different string."""
    correct, err = compare_result_sets(["tier"], [["High"]], ["tier"], [["high"]])
    assert correct, err


def test_compare_projects_gen_to_ref_columns():
    """Generated SELECT *, reference picks a subset — project gen down first."""
    gen_cols = ["id", "name", "extra"]
    gen_rows = [[1, "Alice", "x"], [2, "Bob", "y"]]
    ref_cols = ["id", "name"]
    ref_rows = [[1, "Alice"], [2, "Bob"]]
    correct, err = compare_result_sets(gen_cols, gen_rows, ref_cols, ref_rows)
    assert correct, err


def test_compare_projection_rejects_when_ref_has_extra_columns():
    """Reference asks for a column the generated SQL did not return → mismatch."""
    gen_cols = ["id"]
    gen_rows = [[1], [2]]
    ref_cols = ["id", "name"]
    ref_rows = [[1, "Alice"], [2, "Bob"]]
    correct, _err = compare_result_sets(gen_cols, gen_rows, ref_cols, ref_rows)
    assert not correct


def test_compare_large_short_circuit_on_gen_missing_rows():
    """Generated significantly fewer rows than reference → mismatch."""
    gen_rows = [[i] for i in range(600)]
    ref_rows = [[i] for i in range(1200)]
    correct, err = compare_result_sets(["id"], gen_rows, ["id"], ref_rows)
    assert not correct
    assert "10%" in err or "divergence" in err.lower()


def test_compare_large_gen_superset_is_correct():
    """Generated has more rows that include every reference row → correct
    even at the large-set threshold."""
    ref_rows = [[i] for i in range(600)]
    gen_rows = [[i] for i in range(1200)]
    correct, err = compare_result_sets(["id"], gen_rows, ["id"], ref_rows)
    assert correct, err


def test_compare_large_identical_rows():
    rows = [[i, f"name_{i}"] for i in range(600)]
    correct, err = compare_result_sets(["id", "name"], rows, ["id", "name"], [r[:] for r in rows])
    assert correct, err


def test_compare_large_sample_mismatch():
    gen_rows = [[i, "gen"] for i in range(600)]
    ref_rows = [[i, "ref"] for i in range(600)]
    correct, _err = compare_result_sets(["id", "label"], gen_rows, ["id", "label"], ref_rows)
    assert not correct
