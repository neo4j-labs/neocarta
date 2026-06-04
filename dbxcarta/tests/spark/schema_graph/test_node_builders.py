"""Node builders under the fail-closed contract.

Pure DataFrame builders, exercised in local Spark. Asserts the contract:
each builder emits exactly its declared per-label property set
(`contract.NODE_PROPERTIES`, minus the optional `embedding`) plus one
transient `embedding_text` column — no information_schema helper column
(`table_catalog` / `table_schema` / `table_name` / `catalog_name`) leaves
the builder. Also pins the multi-catalog Database fan-out, the
catalog-derived `layer`, HAS_SCHEMA linking each schema to its own
Database, and the catalog-qualified embedding text so two catalogs with an
identical schema.table no longer collide.
"""

from __future__ import annotations

from dbxcarta.spark.contract import (
    EMBEDDING_TEXT_EXPR,
    NODE_PROPERTIES,
    NodeLabel,
    generate_id,
)
from dbxcarta.spark.ingest.schema_graph import (
    build_column_nodes,
    build_database_nodes,
    build_has_schema_rel,
    build_schema_nodes,
    build_table_nodes,
)


def _declared_plus_embedding_text(label: NodeLabel) -> set[str]:
    """Declared properties minus the optional `embedding` (not present until
    the embed stage runs), plus the transient `embedding_text` the builder
    attaches and the write boundary strips."""
    return {c for c in NODE_PROPERTIES[label] if c != "embedding"} | {"embedding_text"}


def test_build_database_nodes_one_per_catalog(local_spark) -> None:
    rows = build_database_nodes(local_spark, ["bronze", "silver", "gold"]).collect()
    assert {r["name"] for r in rows} == {"bronze", "silver", "gold"}
    assert {r["id"] for r in rows} == {
        generate_id("bronze"),
        generate_id("silver"),
        generate_id("gold"),
    }
    # embedding_text equals name (the Database embedding-text expression).
    assert all(r["embedding_text"] == r["name"] for r in rows)


def test_build_database_nodes_single_catalog_one_node(local_spark) -> None:
    """A single-catalog run passes a one-element list — historical behavior."""
    rows = build_database_nodes(local_spark, ["main"]).collect()
    assert len(rows) == 1
    assert rows[0]["name"] == "main"


def test_build_database_nodes_service_constant_platform_default_null(local_spark) -> None:
    """service is always "DATABRICKS"; platform defaults to null and
    description is null (no catalog comment in the extract)."""
    rows = build_database_nodes(local_spark, ["bronze", "silver"]).collect()
    assert {r["service"] for r in rows} == {"DATABRICKS"}
    assert all(r["platform"] is None for r in rows)
    assert all(r["description"] is None for r in rows)


def test_build_database_nodes_platform_passed_through(local_spark) -> None:
    """A supplied platform tag lands on every Database node verbatim."""
    rows = build_database_nodes(local_spark, ["bronze", "silver"], "AWS").collect()
    assert {r["platform"] for r in rows} == {"AWS"}


def test_build_database_nodes_emits_only_declared_plus_embedding_text(
    local_spark,
) -> None:
    df = build_database_nodes(local_spark, ["main"])
    assert set(df.columns) == _declared_plus_embedding_text(NodeLabel.DATABASE)


_TABLES_SCHEMA = (
    "table_catalog string, table_schema string, table_name string,"
    " table_type string, comment string, created string, last_altered string"
)
_COLUMNS_SCHEMA = (
    "table_catalog string, table_schema string, table_name string,"
    " column_name string, data_type string, is_nullable string,"
    " ordinal_position int, comment string"
)


def _tables_df(local_spark):
    return local_spark.createDataFrame(
        [
            ("bronze", "sales", "orders", "TABLE", "raw orders", None, None),
            ("gold", "sales", "orders", "TABLE", "curated orders", None, None),
        ],
        _TABLES_SCHEMA,
    )


def _columns_df(local_spark):
    return local_spark.createDataFrame(
        [
            ("bronze", "sales", "orders", "id", "bigint", "NO", 1, "pk"),
            ("gold", "sales", "orders", "id", "bigint", "NO", 1, "pk"),
        ],
        _COLUMNS_SCHEMA,
    )


def _schemata_df(local_spark):
    return local_spark.createDataFrame(
        [("bronze", "sales", "sales schema"), ("gold", "sales", "sales schema")],
        "catalog_name string, schema_name string, comment string",
    )


_BRONZE_ORDERS = generate_id("bronze", "sales", "orders")
_GOLD_ORDERS = generate_id("gold", "sales", "orders")


def test_build_table_nodes_layer_from_catalog(local_spark) -> None:
    rows = build_table_nodes(
        _tables_df(local_spark),
        {"bronze": "bronze", "gold": "gold"},
    ).collect()
    by_id = {r["id"]: r for r in rows}
    assert by_id[_BRONZE_ORDERS]["layer"] == "bronze"
    assert by_id[_GOLD_ORDERS]["layer"] == "gold"
    # ids stay catalog-distinct even though schema.table is identical.
    assert _BRONZE_ORDERS != _GOLD_ORDERS


def test_build_table_nodes_unmapped_catalog_null_layer(local_spark) -> None:
    rows = build_table_nodes(_tables_df(local_spark), {"bronze": "bronze"}).collect()
    by_id = {r["id"]: r for r in rows}
    assert by_id[_BRONZE_ORDERS]["layer"] == "bronze"
    assert by_id[_GOLD_ORDERS]["layer"] is None


def test_build_table_nodes_emits_only_declared_plus_embedding_text(
    local_spark,
) -> None:
    df = build_table_nodes(_tables_df(local_spark), None)
    assert set(df.columns) == _declared_plus_embedding_text(NodeLabel.TABLE)
    assert "table_catalog" not in df.columns
    assert "table_schema" not in df.columns


def test_build_column_nodes_emits_only_declared_plus_embedding_text(
    local_spark,
) -> None:
    df = build_column_nodes(_columns_df(local_spark))
    assert set(df.columns) == _declared_plus_embedding_text(NodeLabel.COLUMN)
    for helper in ("table_catalog", "table_schema", "table_name"):
        assert helper not in df.columns
    ids = {r["id"] for r in df.collect()}
    assert len(ids) == 2  # catalog-qualified, so no collision


def test_build_schema_nodes_emits_only_declared_plus_embedding_text(
    local_spark,
) -> None:
    df = build_schema_nodes(_schemata_df(local_spark))
    assert set(df.columns) == _declared_plus_embedding_text(NodeLabel.SCHEMA)
    assert "catalog_name" not in df.columns


def test_build_has_schema_rel_links_each_schema_to_its_own_database(
    local_spark,
) -> None:
    rows = build_has_schema_rel(_schemata_df(local_spark)).collect()
    pairs = {(r["source_id"], r["target_id"]) for r in rows}
    assert (generate_id("bronze"), generate_id("bronze", "sales")) in pairs
    assert (generate_id("gold"), generate_id("gold", "sales")) in pairs


def test_table_embedding_text_distinguishes_catalogs(local_spark) -> None:
    """The builder-attached `embedding_text` leads with catalog, so two
    catalogs with an identical schema.table no longer embed identically.
    The values also equal the contract TABLE expression applied to the same
    rows (text content unchanged across the refactor)."""
    df = build_table_nodes(_tables_df(local_spark), None)
    texts = {r["id"]: r["embedding_text"] for r in df.collect()}
    assert texts[_BRONZE_ORDERS] == "bronze.sales.orders | raw orders"
    assert texts[_GOLD_ORDERS] == "gold.sales.orders | curated orders"
    assert texts[_BRONZE_ORDERS] != texts[_GOLD_ORDERS]
    # Pin to the single source of truth so a drift in the expression fails
    # here, not silently in production.
    assert "table_catalog" in EMBEDDING_TEXT_EXPR[NodeLabel.TABLE]


def test_column_embedding_text_distinguishes_catalogs(local_spark) -> None:
    df = build_column_nodes(_columns_df(local_spark))
    texts = {r["id"]: r["embedding_text"] for r in df.collect()}
    bronze_id = generate_id("bronze", "sales", "orders", "id")
    gold_id = generate_id("gold", "sales", "orders", "id")
    assert texts[bronze_id] == "bronze.sales.orders.id | bigint | pk"
    assert texts[gold_id] == "gold.sales.orders.id | bigint | pk"
    assert texts[bronze_id] != texts[gold_id]
