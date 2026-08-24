"""Unit tests for OSI metric expression reference extraction (no database)."""

from neocarta.connectors.osi.ingest.expression_refs import (
    extract_references,
    osi_dialect_to_sqlglot,
)

# ---------------------------------------------------------------------- #
# Dialect mapping (OSI enum: ANSI_SQL, SNOWFLAKE, MDX, TABLEAU, DATABRICKS, MAQL)
# ---------------------------------------------------------------------- #


def test_sql_dialects_map_to_sqlglot():
    assert osi_dialect_to_sqlglot("ANSI_SQL") is None  # sqlglot default
    assert osi_dialect_to_sqlglot("snowflake") == "snowflake"
    assert osi_dialect_to_sqlglot("DATABRICKS") == "databricks"


def test_non_sql_and_unknown_dialects_map_to_none():
    assert osi_dialect_to_sqlglot("MDX") is None
    assert osi_dialect_to_sqlglot("some_future_dialect") is None
    assert osi_dialect_to_sqlglot(None) is None
    assert osi_dialect_to_sqlglot("") is None


def test_non_sql_dialect_is_not_parsed():
    assert extract_references("SUM([Measures].[Sales])", "MDX") is None
    assert extract_references("SUM(orders.amount)", "TABLEAU") is None


# ---------------------------------------------------------------------- #
# Reference extraction — bare scalar expressions (the common OSI case)
# ---------------------------------------------------------------------- #


def test_qualified_single_column():
    refs = extract_references("SUM(orders.amount)", "ANSI_SQL")
    assert refs.tables == {"orders"}
    assert refs.columns == {("orders", "amount")}


def test_qualified_multi_table_expression():
    refs = extract_references(
        "SUM(store_sales.ss_ext_sales_price) / COUNT(DISTINCT customer.c_customer_sk)",
        "ANSI_SQL",
    )
    assert refs.tables == {"store_sales", "customer"}
    assert refs.columns == {
        ("store_sales", "ss_ext_sales_price"),
        ("customer", "c_customer_sk"),
    }


def test_unqualified_column_bare_fragment_has_none_qualifier():
    # No FROM -> the bare column is left for dataset name-matching downstream.
    refs = extract_references("SUM(amount)", "ANSI_SQL")
    assert refs.tables == set()
    assert refs.columns == {(None, "amount")}


def test_star_reference_captures_table_without_a_column():
    refs = extract_references("COUNT(orders.*)", "ANSI_SQL")
    assert refs.tables == {"orders"}
    assert refs.columns == set()


def test_multi_part_qualifier_is_kept_as_written():
    refs = extract_references("SUM(warehouse.public.orders.amount)", "ANSI_SQL")
    assert refs.tables == {"warehouse.public.orders"}
    assert refs.columns == {("warehouse.public.orders", "amount")}


def test_duplicate_references_are_deduped():
    refs = extract_references("orders.a + orders.a + orders.b", "ANSI_SQL")
    assert refs.columns == {("orders", "a"), ("orders", "b")}


def test_empty_expression_returns_empty_refs():
    for expr in ("", "   "):
        refs = extract_references(expr, "ANSI_SQL")
        assert refs.tables == set()
        assert refs.columns == set()


def test_unparseable_expression_returns_none():
    assert extract_references("SUM(amount", "ANSI_SQL") is None


# ---------------------------------------------------------------------- #
# Outer-scope resolution: FROM aliases, single-FROM unqualified attribution
# ---------------------------------------------------------------------- #


def test_alias_is_resolved_to_the_real_table_name():
    refs = extract_references("SELECT SUM(o.amount) FROM orders o", "ANSI_SQL")
    assert refs.tables == {"orders"}
    assert refs.columns == {("orders", "amount")}


def test_unqualified_column_attributed_to_single_from_table():
    # A FROM-bearing expression with exactly one source: the unqualified column belongs to it.
    refs = extract_references("SELECT SUM(arr_usd) FROM subscriptions", "ANSI_SQL")
    assert refs.tables == {"subscriptions"}
    assert refs.columns == {("subscriptions", "arr_usd")}


def test_top_level_unqualified_kept_even_when_a_subquery_has_from():
    # The outer scope has no FROM; the subquery's FROM must not suppress the top-level column.
    refs = extract_references("SELECT amount - (SELECT AVG(o.amount) FROM orders o)", "ANSI_SQL")
    assert refs.columns == {(None, "amount")}  # top-level `amount` is a dataset ref
    assert "orders" not in refs.tables  # subquery-internal table is not a metric dependency


# ---------------------------------------------------------------------- #
# Subquery / CTE references are query-local, not metric dataset dependencies
# ---------------------------------------------------------------------- #


def test_subquery_internal_tables_are_not_reported():
    refs = extract_references("SUM(sales.amt) - (SELECT AVG(x) FROM audit_log a)", "ANSI_SQL")
    assert refs.tables == {"sales"}  # audit_log lives only inside the subquery -> excluded
    assert refs.columns == {("sales", "amt")}


def test_subquery_alias_is_not_a_dataset():
    refs = extract_references(
        "SELECT SUM(sub.amount) FROM (SELECT amount FROM orders) sub", "ANSI_SQL"
    )
    assert refs.tables == set()  # `sub` is a derived table; `orders` is subquery-internal
    assert refs.columns == set()


def test_cte_and_reused_subquery_aliases_are_query_local():
    refs = extract_references(
        "SELECT SUM(cte.x) FROM (WITH cte AS (SELECT o.x FROM orders o) SELECT * FROM cte) AS cte",
        "ANSI_SQL",
    )
    assert refs.tables == set()
    assert refs.columns == set()


def test_reused_alias_across_subqueries_reports_no_metric_refs():
    # Both branches are subqueries; nothing is in the metric's own scope -> no refs, and in
    # particular no column mis-attributed to an arbitrary table.
    refs = extract_references(
        "SUM((SELECT t.value FROM revenue t) - (SELECT t.value FROM costs t))", "ANSI_SQL"
    )
    assert refs.tables == set()
    assert refs.columns == set()


# ---------------------------------------------------------------------- #
# Derived-table aliases (LATERAL / VALUES) are query-local, not datasets
# ---------------------------------------------------------------------- #


def test_lateral_alias_is_not_reported_as_a_dataset():
    # Snowflake LATERAL FLATTEN: `line` is a derived-table alias, so `line.value` is
    # query-local; the real dependency is the flattened `sales.items` column.
    refs = extract_references(
        "SELECT SUM(line.value) FROM sales, LATERAL FLATTEN(input => sales.items) line",
        "SNOWFLAKE",
    )
    assert refs.tables == {"sales"}  # `line` must NOT leak in as a table
    assert ("line", "value") not in refs.columns
    assert not any(qualifier == "line" for qualifier, _ in refs.columns)
    assert ("sales", "items") in refs.columns


def test_lateral_view_alias_is_not_reported_as_a_dataset():
    # Databricks LATERAL VIEW EXPLODE: `exploded` is a derived-table alias, not a dataset.
    refs = extract_references(
        "SELECT SUM(exploded.item) FROM sales LATERAL VIEW EXPLODE(sales.items) exploded AS item",
        "DATABRICKS",
    )
    assert refs.tables == {"sales"}
    assert not any(qualifier == "exploded" for qualifier, _ in refs.columns)
    assert ("sales", "items") in refs.columns


def test_values_alias_is_not_reported_as_a_dataset():
    # `v` names an inline VALUES derived table, not a dataset.
    refs = extract_references("SELECT SUM(v.col) FROM (VALUES (1), (2)) AS v(col)", "ANSI_SQL")
    assert refs.tables == set()
    assert refs.columns == set()


# ---------------------------------------------------------------------- #
# Set operations (UNION/INTERSECT/EXCEPT): every branch is the outer scope
# ---------------------------------------------------------------------- #


def test_union_captures_every_branch():
    refs = extract_references("SELECT SUM(a.x) FROM a UNION ALL SELECT SUM(b.y) FROM b", "ANSI_SQL")
    assert refs.tables == {"a", "b"}
    assert refs.columns == {("a", "x"), ("b", "y")}


def test_three_way_union_captures_all_branches():
    refs = extract_references(
        "SELECT a.x FROM a UNION SELECT b.y FROM b UNION SELECT c.z FROM c", "ANSI_SQL"
    )
    assert refs.tables == {"a", "b", "c"}
    assert refs.columns == {("a", "x"), ("b", "y"), ("c", "z")}


def test_intersect_and_except_capture_both_branches():
    for op in ("INTERSECT", "EXCEPT"):
        refs = extract_references(f"SELECT a.x FROM a {op} SELECT b.y FROM b", "ANSI_SQL")
        assert refs.tables == {"a", "b"}, op
        assert refs.columns == {("a", "x"), ("b", "y")}, op


def test_set_operation_still_excludes_nested_subquery_refs():
    # A subquery inside one branch stays query-local even across a set operation.
    refs = extract_references(
        "SELECT SUM(a.x) FROM a WHERE a.id IN (SELECT s.id FROM sub s) "
        "UNION ALL SELECT SUM(b.y) FROM b",
        "ANSI_SQL",
    )
    assert refs.tables == {"a", "b"}  # `sub` is nested -> excluded
    # `a.id` lives in branch A's own WHERE (outer scope), so it is captured; `s.id` is nested.
    assert refs.columns == {("a", "x"), ("a", "id"), ("b", "y")}
    assert not any(qualifier == "s" for qualifier, _ in refs.columns)


# ---------------------------------------------------------------------- #
# A parenthesized full statement is the statement it wraps, not a subquery
# ---------------------------------------------------------------------- #


def test_parenthesized_full_statement_links_like_the_unparenthesized_form():
    parenthesized = extract_references("(SELECT SUM(orders.amount) FROM orders)", "ANSI_SQL")
    plain = extract_references("SELECT SUM(orders.amount) FROM orders", "ANSI_SQL")
    assert parenthesized.tables == plain.tables == {"orders"}
    assert parenthesized.columns == plain.columns == {("orders", "amount")}


def test_scalar_subquery_nested_in_expression_stays_query_local():
    # Contrast with the parenthesized-whole-statement case: here the subquery is one operand
    # of a larger expression, so its refs remain query-local (customers excluded).
    refs = extract_references("SUM(orders.amount) / (SELECT COUNT(*) FROM customers)", "ANSI_SQL")
    assert refs.tables == {"orders"}
    assert refs.columns == {("orders", "amount")}
