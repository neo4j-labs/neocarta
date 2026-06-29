"""Unit tests for OSI metric/column expression reference extraction (no database)."""

from neocarta.connectors.osi.ingest.expression_refs import (
    extract_column_references,
    osi_dialect_to_sqlglot,
)

# ---------------------------------------------------------------------- #
# Dialect mapping
# ---------------------------------------------------------------------- #


def test_ansi_and_unknown_dialects_map_to_none():
    assert osi_dialect_to_sqlglot("ANSI_SQL") is None
    assert osi_dialect_to_sqlglot("ansi") is None
    assert osi_dialect_to_sqlglot(None) is None
    assert osi_dialect_to_sqlglot("") is None
    # Unknown dialect degrades to None (sqlglot's permissive default) rather than raising.
    assert osi_dialect_to_sqlglot("some_future_dialect") is None


def test_known_dialects_map_case_insensitively():
    assert osi_dialect_to_sqlglot("BigQuery") == "bigquery"
    assert osi_dialect_to_sqlglot("snowflake") == "snowflake"
    assert osi_dialect_to_sqlglot("PostgreSQL") == "postgres"


# ---------------------------------------------------------------------- #
# Reference extraction
# ---------------------------------------------------------------------- #


def test_qualified_single_column():
    assert extract_column_references("SUM(orders.amount)", "ANSI_SQL") == [("orders", "amount")]


def test_qualified_multi_table_expression():
    refs = extract_column_references(
        "SUM(store_sales.ss_ext_sales_price) / COUNT(DISTINCT customer.c_customer_sk)",
        "ANSI_SQL",
    )
    assert set(refs) == {
        ("store_sales", "ss_ext_sales_price"),
        ("customer", "c_customer_sk"),
    }


def test_unqualified_column_has_none_qualifier():
    assert extract_column_references("SUM(amount)", "ANSI_SQL") == [(None, "amount")]


def test_star_projection_is_skipped():
    # COUNT(*) carries no concrete column reference.
    assert extract_column_references("COUNT(*)", "ANSI_SQL") == []


def test_duplicate_references_are_deduped():
    # The same column referenced twice collapses to a single pair (order is unspecified —
    # it follows sqlglot's AST traversal, not source order — so compare as a set).
    refs = extract_column_references("orders.a + orders.a + orders.b", "ANSI_SQL")
    assert len(refs) == 2
    assert set(refs) == {("orders", "a"), ("orders", "b")}


def test_empty_expression_returns_empty_list():
    assert extract_column_references("", "ANSI_SQL") == []
    assert extract_column_references("   ", "ANSI_SQL") == []


def test_unparseable_expression_returns_none():
    # Unbalanced parentheses -> sqlglot cannot parse -> None (caller skips the expression).
    assert extract_column_references("SUM(amount", "ANSI_SQL") is None


def test_multi_part_qualifier_is_skipped():
    # OSI qualifiers are single-token dataset names; a multi-part reference (schema.table.col)
    # would drop the leading segment, so it is skipped rather than mis-resolved.
    assert extract_column_references("SUM(schema.table.col)", "ANSI_SQL") == []
    # A normal single-token qualifier in the same expression is still captured.
    assert extract_column_references("SUM(schema.table.col) + orders.amount", "ANSI_SQL") == [
        ("orders", "amount")
    ]
