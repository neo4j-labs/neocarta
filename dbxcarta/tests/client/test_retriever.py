"""Unit tests for the Retriever ABC, ContextBundle, and MockRetriever."""

from __future__ import annotations

from dbxcarta.client.graph_retriever import (
    _fetch_columns,
    _filter_seed_pairs_to_schemas,
    _select_schemas,
)
from dbxcarta.client.retriever import ColumnEntry, ContextBundle, JoinLine, Retriever


class MockRetriever(Retriever):
    """Deterministic retriever for unit tests — returns a canned ContextBundle."""

    def __init__(self, bundle: ContextBundle) -> None:
        self._bundle = bundle

    def retrieve(self, question: str, embedding: list[float]) -> ContextBundle:
        return self._bundle


def _make_bundle() -> ContextBundle:
    return ContextBundle(
        columns=[
            ColumnEntry(
                table_fqn="cat.schema.accounts",
                column_name="account_id",
                data_type="BIGINT",
                comment="Primary key",
                column_id="cat.schema.accounts.account_id",
            ),
            ColumnEntry(
                table_fqn="cat.schema.accounts",
                column_name="status",
                data_type="STRING",
                comment="",
                column_id="cat.schema.accounts.status",
            ),
            ColumnEntry(
                table_fqn="cat.schema.transactions",
                column_name="amount",
                data_type="DOUBLE",
                comment="Transaction amount in USD",
                column_id="cat.schema.transactions.amount",
            ),
        ],
        values={"cat.schema.accounts.status": ["active", "closed", "pending"]},
    )


def test_mock_retriever_implements_abc() -> None:
    bundle = _make_bundle()
    retriever: Retriever = MockRetriever(bundle)
    result = retriever.retrieve("how many accounts are active?", [0.1, 0.2, 0.3])
    assert result is bundle


def test_context_bundle_to_text_groups_by_table() -> None:
    bundle = _make_bundle()
    text = bundle.to_text()
    lines = text.splitlines()

    table_lines = [ln for ln in lines if ln.startswith("Table:")]
    assert len(table_lines) == 2
    assert "cat.schema.accounts" in table_lines[0]
    assert "cat.schema.transactions" in table_lines[1]


def test_context_bundle_to_text_includes_columns() -> None:
    bundle = _make_bundle()
    text = bundle.to_text()
    assert "account_id" in text
    assert "BIGINT" in text
    assert "Primary key" in text
    assert "status" in text


def test_context_bundle_to_text_includes_values() -> None:
    bundle = _make_bundle()
    text = bundle.to_text()
    assert "Sample values:" in text
    assert "active" in text


def test_context_bundle_values_in_dedicated_section() -> None:
    """Sample values appear in a dedicated section, not inline on column lines."""
    bundle = _make_bundle()
    lines = bundle.to_text().splitlines()
    # Column line for status has no inline sample values.
    status_col_line = next(line for line in lines if line.startswith("  status") and "(" in line)
    assert "Sample values" not in status_col_line
    # Values appear under "Sample values:" instead.
    text = "\n".join(lines)
    seed_section_start = text.index("Sample values:")
    seed_section = text[seed_section_start:]
    assert "active, closed, pending" in seed_section


def test_context_bundle_to_text_empty() -> None:
    assert ContextBundle().to_text() == ""


def test_context_bundle_no_values_omits_sample_line() -> None:
    bundle = ContextBundle(
        columns=[ColumnEntry("c.s.t", "col", "STRING", column_id="c.s.t.col")],
        values={},
    )
    text = bundle.to_text()
    assert "Sample values" not in text


def test_column_entry_defaults() -> None:
    col = ColumnEntry(table_fqn="c.s.t", column_name="col", data_type="INT")
    assert col.comment == ""
    assert col.column_id == ""


# ---------------------------------------------------------------------------
# Phase F: to_text() section structure
# ---------------------------------------------------------------------------


def test_to_text_target_schema_section() -> None:
    bundle = ContextBundle(
        columns=[ColumnEntry("cat.sp_a.t1", "col", "INT")],
        selected_schemas=["sp_a"],
    )
    text = bundle.to_text()
    assert text.startswith("Target schema: sp_a")


def test_to_text_no_target_schema_when_unset() -> None:
    bundle = _make_bundle()
    text = bundle.to_text()
    assert "Target schema" not in text


def test_to_text_target_schema_multi_schema() -> None:
    bundle = ContextBundle(
        columns=[ColumnEntry("cat.sp_a.t1", "col", "INT")],
        selected_schemas=["sp_a", "sp_b"],
    )
    assert bundle.to_text().startswith("Target schema: sp_a, sp_b")


def test_to_text_tables_section_header() -> None:
    bundle = _make_bundle()
    text = bundle.to_text()
    assert "Tables:" in text


def test_to_text_join_lines_with_source_and_confidence() -> None:
    bundle = ContextBundle(
        columns=[
            ColumnEntry("cat.s.orders", "user_id", "INT", column_id="cat.s.orders.user_id"),
            ColumnEntry("cat.s.users", "id", "INT", column_id="cat.s.users.id"),
        ],
        join_lines=[
            JoinLine(
                "cat.s.orders.user_id = cat.s.users.id",
                source="declared",
            ),
            JoinLine(
                "cat.s.orders.ref = cat.s.other.key",
                source="metadata",
                confidence=0.91,
            ),
        ],
    )
    text = bundle.to_text()
    assert "Joins:" in text
    assert "cat.s.orders.user_id = cat.s.users.id  [declared]" in text
    assert "cat.s.orders.ref = cat.s.other.key  [metadata, conf=0.91]" in text


def test_to_text_join_lines_no_source() -> None:
    bundle = ContextBundle(
        columns=[ColumnEntry("cat.s.t", "col", "INT")],
        join_lines=[JoinLine("cat.s.t.a = cat.s.t2.b")],
    )
    text = bundle.to_text()
    assert "Joins:" in text
    assert "cat.s.t.a = cat.s.t2.b\n" in text + "\n"
    # No annotation appended — annotation format is always "  [...]".
    assert "  [" not in text.split("Joins:")[-1]


def test_to_text_no_joins_section_when_empty() -> None:
    bundle = _make_bundle()
    assert "Joins:" not in bundle.to_text()


def test_to_text_values_only_for_columns_in_bundle() -> None:
    """Values for column IDs absent from columns list are silently skipped."""
    bundle = ContextBundle(
        columns=[ColumnEntry("cat.s.t", "col", "INT", column_id="cat.s.t.col")],
        values={
            "cat.s.t.col": ["a", "b"],
            "cat.s.t.orphan": ["x"],  # not in columns list
        },
    )
    text = bundle.to_text()
    assert "Sample values:" in text
    assert "col (cat.s.t): a, b" in text
    assert "orphan" not in text


# ---------------------------------------------------------------------------
# Phase F: schema selection
# ---------------------------------------------------------------------------


def test_select_schemas_single_dominant() -> None:
    col_pairs = [
        ("cat.sp_a.t1.col1", 0.9),
        ("cat.sp_a.t1.col2", 0.8),
        ("cat.sp_b.t2.col3", 0.2),
    ]
    result = _select_schemas(col_pairs, [])
    assert result == ["sp_a"]


def test_select_schemas_runner_up_above_threshold() -> None:
    # sp_a gets 0.55 / 1.0 = 0.55; sp_b gets 0.45 / 1.0 = 0.45 (>= 0.20)
    col_pairs = [
        ("cat.sp_a.t1.col", 0.55),
        ("cat.sp_b.t2.col", 0.45),
    ]
    result = _select_schemas(col_pairs, [])
    assert result == ["sp_a", "sp_b"]


def test_select_schemas_runner_up_below_threshold() -> None:
    # sp_a: 0.9, sp_b: 0.05, sp_c: 0.05 → normalized sp_b ≈ 0.05 < 0.20
    col_pairs = [
        ("cat.sp_a.t.c", 0.9),
        ("cat.sp_b.t.c", 0.05),
        ("cat.sp_c.t.c", 0.05),
    ]
    result = _select_schemas(col_pairs, [])
    assert result == ["sp_a"]


def test_select_schemas_uses_tbl_seeds_too() -> None:
    col_pairs = [("cat.sp_a.t.c", 0.5)]
    tbl_pairs = [("cat.sp_b.t2", 0.5)]
    result = _select_schemas(col_pairs, tbl_pairs)
    # sp_a and sp_b each have 0.50 normalized — both selected
    assert "sp_a" in result
    assert "sp_b" in result


def test_select_schemas_normalizes_column_and_table_indexes_before_aggregation() -> None:
    col_pairs = [("cat.sp_a.t.c", 10.0)]
    tbl_pairs = [("cat.sp_b.t", 1.0)]
    result = _select_schemas(col_pairs, tbl_pairs)
    assert result == ["sp_a", "sp_b"]


def test_filter_seed_pairs_to_configured_schemas() -> None:
    pairs = [
        ("cat.allowed.t.c", 0.8),
        ("cat.blocked.t.c", 0.9),
        ("bad_id", 1.0),
    ]
    assert _filter_seed_pairs_to_schemas(pairs, ["allowed"]) == [
        ("cat.allowed.t.c", 0.8),
    ]


def test_select_schemas_empty_seeds() -> None:
    assert _select_schemas([], []) == []


def test_fetch_columns_uses_catalog_name_from_database_node() -> None:
    class SessionStub:
        def run(self, _query, **kwargs):
            assert kwargs["tids"] == ["bronze.sales.orders", "gold.sales.orders"]
            assert kwargs["schemas"] == ["sales"]
            return [
                {
                    "catalog_name": "bronze",
                    "schema_name": "sales",
                    "table_name": "orders",
                    "col_id": "bronze.sales.orders.id",
                    "col_name": "id",
                    "data_type": "BIGINT",
                    "comment": "raw id",
                    "pos": 1,
                },
                {
                    "catalog_name": "gold",
                    "schema_name": "sales",
                    "table_name": "orders",
                    "col_id": "gold.sales.orders.id",
                    "col_name": "id",
                    "data_type": "BIGINT",
                    "comment": "curated id",
                    "pos": 1,
                },
            ]

    columns = _fetch_columns(
        SessionStub(),
        ["bronze.sales.orders", "gold.sales.orders"],
        ["sales"],
    )

    assert [column.table_fqn for column in columns] == [
        "`bronze`.`sales`.`orders`",
        "`gold`.`sales`.`orders`",
    ]


def test_fetch_columns_emits_true_hyphenated_name_not_normalized_id() -> None:
    """Regression: the FQN must use Database.name, not the normalized id.

    Ingest normalizes hyphens to underscores in node ids while .name keeps
    the true catalog/schema. Building the FQN from the id produced a
    nonexistent catalog and every graph_rag query failed
    TABLE_OR_VIEW_NOT_FOUND.
    """

    class SessionStub:
        def run(self, _query, **kwargs):
            return [
                {
                    "catalog_name": "graph-enriched-finance-silver",
                    "schema_name": "graph-enriched-schema",
                    "table_name": "accounts",
                    "col_id": (
                        "graph_enriched_finance_silver.graph_enriched_schema.accounts.account_id"
                    ),
                    "col_name": "account_id",
                    "data_type": "BIGINT",
                    "comment": "",
                    "pos": 1,
                },
            ]

    columns = _fetch_columns(
        SessionStub(),
        ["graph_enriched_finance_silver.graph_enriched_schema.accounts"],
        ["graph-enriched-schema"],
    )

    assert columns[0].table_fqn == (
        "`graph-enriched-finance-silver`.`graph-enriched-schema`.`accounts`"
    )


def test_filter_seed_pairs_matches_hyphenated_configured_schema() -> None:
    """Regression: a hyphenated configured schema must select normalized-id seeds.

    schema_from_node_id yields the normalized id part
    (graph_enriched_schema); the configured name is hyphenated
    (graph-enriched-schema). Without normalization every vector seed was
    dropped and seed-driven expansion was dead.
    """
    pairs = [
        ("graph_enriched_finance_silver.graph_enriched_schema.accounts.id", 0.9),
        ("other_cat.other_schema.t.c", 0.5),
    ]
    assert _filter_seed_pairs_to_schemas(pairs, ["graph-enriched-schema"]) == [
        ("graph_enriched_finance_silver.graph_enriched_schema.accounts.id", 0.9),
    ]


def test_select_schemas_three_schemas_only_top_two_considered() -> None:
    col_pairs = [
        ("cat.sp_a.t.c", 0.6),
        ("cat.sp_b.t.c", 0.25),
        ("cat.sp_c.t.c", 0.15),
    ]
    result = _select_schemas(col_pairs, [])
    # sp_a=0.60, sp_b=0.25 (>=0.20 → included), sp_c=0.15 (<0.20, and capped at 2)
    assert result == ["sp_a", "sp_b"]
    assert len(result) <= 2


# ---------------------------------------------------------------------------
# Phase F: prompt single-schema constraint
# ---------------------------------------------------------------------------


def test_graph_rag_prompt_single_schema_constraint() -> None:
    from dbxcarta.client.prompt import graph_rag_prompt

    prompt = graph_rag_prompt("find users", "mycat", ["sp_a"], "Target schema: sp_a\n...")
    assert "Use ONLY the exact tables and columns listed in the context" in prompt
    assert "backtick-quoted three-part names" in prompt
    assert "target schema" in prompt.lower()


def test_graph_rag_prompt_treats_context_fqns_as_authoritative() -> None:
    from dbxcarta.client.prompt import graph_rag_prompt

    context = "Table: `other_catalog`.`sp_a`.`users`\n  id (BIGINT)"
    prompt = graph_rag_prompt("find users", "default_catalog", ["sp_a"], context)

    assert "catalog 'default_catalog'" not in prompt
    assert "full three-part table names in the context as authoritative" in prompt
    assert "`other_catalog`.`sp_a`.`users`" in prompt
