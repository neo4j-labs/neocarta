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
    # MDX/TABLEAU/MAQL are non-SQL; unknown/unspecified fall back to the default.
    assert osi_dialect_to_sqlglot("MDX") is None
    assert osi_dialect_to_sqlglot("some_future_dialect") is None
    assert osi_dialect_to_sqlglot(None) is None
    assert osi_dialect_to_sqlglot("") is None


def test_non_sql_dialect_is_not_parsed():
    # A non-SQL OSI dialect yields no references (sqlglot cannot parse it) -> None.
    assert extract_references("SUM([Measures].[Sales])", "MDX") is None
    assert extract_references("SUM(orders.amount)", "TABLEAU") is None


# ---------------------------------------------------------------------- #
# Reference extraction
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


def test_unqualified_column_has_none_qualifier():
    refs = extract_references("SUM(amount)", "ANSI_SQL")
    assert refs.tables == set()
    assert refs.columns == {(None, "amount")}


def test_star_reference_captures_table_without_a_column():
    refs = extract_references("COUNT(orders.*)", "ANSI_SQL")
    assert refs.tables == {"orders"}
    assert refs.columns == set()


def test_multi_part_qualifier_is_kept_as_written():
    # OSI sources are multi-part (db.schema.table); the full qualifier is preserved so the
    # transformer can resolve it as a source path (it is NOT silently dropped/skipped).
    refs = extract_references("SUM(warehouse.public.orders.amount)", "ANSI_SQL")
    assert refs.tables == {"warehouse.public.orders"}
    assert refs.columns == {("warehouse.public.orders", "amount")}


def test_alias_is_resolved_to_the_real_table_name():
    refs = extract_references("SELECT SUM(o.amount) FROM orders o", "ANSI_SQL")
    assert refs.tables == {"orders"}
    assert refs.columns == {("orders", "amount")}


def test_cte_local_names_are_excluded_and_aliases_resolved():
    refs = extract_references(
        "SELECT SUM(cte.x) FROM (WITH cte AS (SELECT o.x FROM orders o) SELECT * FROM cte) AS cte",
        "ANSI_SQL",
    )
    # `cte` is query-local (not a dataset); only the real table `orders` is captured.
    assert "cte" not in refs.tables
    assert "orders" in refs.tables
    assert ("orders", "x") in refs.columns


def test_duplicate_references_are_deduped():
    refs = extract_references("orders.a + orders.a + orders.b", "ANSI_SQL")
    assert refs.columns == {("orders", "a"), ("orders", "b")}


def test_empty_expression_returns_empty_refs():
    for expr in ("", "   "):
        refs = extract_references(expr, "ANSI_SQL")
        assert refs.tables == set()
        assert refs.columns == set()


def test_unparseable_expression_returns_none():
    # Unbalanced parentheses -> sqlglot cannot parse -> None (caller skips the expression).
    assert extract_references("SUM(amount", "ANSI_SQL") is None


def test_reused_alias_across_subqueries_is_not_misattributed():
    # The same alias `t` binds to two different tables — ambiguous, so the columns are not
    # attributed to an arbitrary one; both real tables are still captured.
    refs = extract_references(
        "SUM((SELECT t.value FROM revenue t) - (SELECT t.value FROM costs t))", "ANSI_SQL"
    )
    assert refs.tables == {"revenue", "costs"}
    assert refs.columns == set()  # no wrong-table column edge from the ambiguous alias


def test_subquery_alias_is_excluded_like_a_cte():
    # `sub` is a derived-table alias, not a dataset; it must not be reported as a table or a
    # column qualifier even if a dataset happens to be named `sub`.
    refs = extract_references(
        "SELECT SUM(sub.amount) FROM (SELECT amount FROM orders) sub", "ANSI_SQL"
    )
    assert "sub" not in refs.tables
    assert all(qualifier != "sub" for qualifier, _ in refs.columns)


def test_unqualified_column_in_full_select_is_query_local():
    # With a FROM clause present, a bare column resolves against the query's sources, not the
    # model's datasets, so it is not reported as an unqualified dataset column.
    refs = extract_references("SELECT SUM(amount) FROM orders", "ANSI_SQL")
    assert refs.tables == {"orders"}
    assert refs.columns == set()
