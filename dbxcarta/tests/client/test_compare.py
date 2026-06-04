"""Unit tests for result-set normalization and comparison in compare.py."""

from __future__ import annotations

from dbxcarta.client.compare import (
    compare_result_sets,
    normalize_row,
    project_to_ref_columns,
    stringify_cell,
)

# ---------------------------------------------------------------------------
# stringify_cell
# ---------------------------------------------------------------------------


def test_stringify_cell_none():
    assert stringify_cell(None) == "NULL"


def test_stringify_cell_int():
    assert stringify_cell(42) == "42"


def test_stringify_cell_casefold():
    assert stringify_cell("Alice") == "alice"


# ---------------------------------------------------------------------------
# normalize_row — value-sort, column names and order irrelevant
# ---------------------------------------------------------------------------


def test_normalize_row_sorts_values():
    assert normalize_row(["Beta", "Alpha"]) == ("alpha", "beta")


def test_normalize_row_ignores_col_names():
    """Two rows with identical values but different column name arguments normalize the same."""
    assert normalize_row(["Alpha", 500], ["name", "amount"]) == normalize_row(
        ["Alpha", 500], ["project_name", "total_revenue"]
    )


def test_normalize_row_column_reorder():
    """Column reordering with different aliases still normalizes to the same tuple."""
    # ref: col_names=["amount", "name"], values=[500, "Alpha"]
    ref = normalize_row([500, "Alpha"], ["amount", "name"])
    # gen: col_names=["total_revenue", "project_name"], values=[500, "Alpha"]
    gen = normalize_row([500, "Alpha"], ["total_revenue", "project_name"])
    assert ref == gen


def test_normalize_row_different_values_not_equal():
    assert normalize_row(["Alice", 10]) != normalize_row(["Bob", 20])


# ---------------------------------------------------------------------------
# project_to_ref_columns
# ---------------------------------------------------------------------------


def test_project_strips_extra_column_by_name():
    gen_cols = ["name", "id", "amount"]
    gen_rows = [["Alpha", 1, 500], ["Beta", 2, 300]]
    ref_cols = ["name", "amount"]
    out_cols, out_rows = project_to_ref_columns(gen_cols, gen_rows, ref_cols)
    assert out_cols == ["name", "amount"]
    assert out_rows == [["Alpha", 500], ["Beta", 300]]


def test_project_no_op_when_same_count():
    gen_cols = ["a", "b"]
    gen_rows = [[1, 2]]
    out_cols, out_rows = project_to_ref_columns(gen_cols, gen_rows, ["x", "y"])
    assert out_cols == gen_cols
    assert out_rows == gen_rows


def test_project_no_op_when_name_not_subset():
    """When gen aliases a required column, name projection returns unchanged."""
    gen_cols = ["project_name", "id"]
    gen_rows = [["Alpha", 1]]
    out_cols, out_rows = project_to_ref_columns(gen_cols, gen_rows, ["name"])
    assert out_cols == gen_cols  # unchanged — name not found
    assert out_rows == gen_rows


# ---------------------------------------------------------------------------
# compare_result_sets — core grader correctness
# ---------------------------------------------------------------------------


def test_exact_match():
    ok, msg = compare_result_sets(["name"], [["Alpha"]], ["name"], [["Alpha"]])
    assert ok is True
    assert msg is None


def test_case_insensitive_match():
    ok, _ = compare_result_sets(["name"], [["ALPHA"]], ["name"], [["alpha"]])
    assert ok is True


def test_column_alias_same_count_passes():
    """Same data, different column alias — should pass after normalize_row fix."""
    ok, msg = compare_result_sets(
        ["project_name", "total_revenue"],
        [["Alpha", 500], ["Beta", 300]],
        ["name", "amount"],
        [["Alpha", 500], ["Beta", 300]],
    )
    assert ok is True, f"expected True, got msg={msg}"


def test_extra_id_column_aliased_aggregate_passes():
    """Core sub-pattern A case: gen has extra id col + aliased aggregate.
    ref expects [name, sum(amount)]; gen returns [name, id, total_amount]."""
    ok, msg = compare_result_sets(
        ["name", "id", "total_amount"],
        [["Alpha", 1, 500], ["Beta", 2, 300]],
        ["name", "sum(amount)"],
        [["Alpha", 500], ["Beta", 300]],
    )
    assert ok is True, f"expected True, got msg={msg}"


def test_genuinely_wrong_values_fail():
    """Wrong data is not recovered by either alias fix or subset search."""
    ok, _msg = compare_result_sets(
        ["name", "total"],
        [["Alpha", 999], ["Beta", 300]],
        ["name", "sum(amount)"],
        [["Alpha", 500], ["Beta", 300]],
    )
    assert ok is False


def test_row_count_mismatch_fails():
    """Row count difference is rejected for small result sets."""
    ok, _msg = compare_result_sets(
        ["name"],
        [["Alpha"], ["Beta"], ["Gamma"]],
        ["name"],
        [["Alpha"], ["Beta"]],
    )
    assert ok is False


def test_different_row_values_fail():
    """Gen returning different values is correctly rejected."""
    ok, _msg = compare_result_sets(
        ["name"],
        [["Alice"], ["Bob"]],
        ["name"],
        [["Alpha"], ["Beta"]],
    )
    assert ok is False


def test_extra_columns_no_subset_match_fails():
    """Extra columns that do not contain correct data are correctly rejected."""
    ok, _ = compare_result_sets(
        ["name", "id", "total"],
        [["Alpha", 1, 999]],
        ["name", "amount"],
        [["Alpha", 500]],
    )
    assert ok is False


def test_subset_search_max_extra_cols_guard():
    """More than 4 extra columns skips subset search — avoids combinatorial explosion.
    Columns must be aliased so name projection also fails, forcing subset path."""
    # col names are all aliases — name projection fails (ref has 'name'/'amount',
    # gen has none of those). 7 - 2 = 5 extra columns > 4 guard; subset skipped.
    ok, _ = compare_result_sets(
        ["col_a", "col_b", "col_c", "col_d", "col_e", "project_name", "total"],
        [["x", "y", "z", "w", "v", "Alpha", 500]],
        ["name", "amount"],
        [["Alpha", 500]],
    )
    assert ok is False


def test_row_ordering_irrelevant():
    ok, _ = compare_result_sets(
        ["name"],
        [["Beta"], ["Alpha"]],
        ["name"],
        [["Alpha"], ["Beta"]],
    )
    assert ok is True


def test_column_order_irrelevant():
    """Columns returned in different order normalize the same way."""
    ok, _ = compare_result_sets(
        ["amount", "name"],
        [[500, "Alpha"]],
        ["name", "amount"],
        [["Alpha", 500]],
    )
    assert ok is True
