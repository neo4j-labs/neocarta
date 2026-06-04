"""build_references_rel sets provenance from each FKEdge.source tag.

Source-agnostic builder: declared (1.0, "declared", null) and metadata
(score, "inferred_metadata", null) both flow through the same 5-column
schema via the FKEdge dataclass.
"""

from __future__ import annotations

from dbxcarta.spark.contract import REFERENCES_PROPERTIES, EdgeSource
from dbxcarta.spark.ingest.fk.common import FKEdge
from dbxcarta.spark.ingest.schema_graph import build_references_rel

_EXPECTED_COLUMNS = ("source_id", "target_id", "confidence", "source", "criteria")


def _declared_edges() -> list[FKEdge]:
    """Three declared FK edges: intra-schema + cross-schema."""
    return [
        FKEdge(
            source_id="main.dbxcarta_test_sales.orders.customer_id",
            target_id="main.dbxcarta_test_sales.customers.id",
            confidence=1.0,
            source=EdgeSource.DECLARED,
            criteria=None,
        ),
        FKEdge(
            source_id="main.dbxcarta_test_sales.order_items.order_id",
            target_id="main.dbxcarta_test_sales.orders.id",
            confidence=1.0,
            source=EdgeSource.DECLARED,
            criteria=None,
        ),
        FKEdge(
            source_id="main.dbxcarta_test_sales.order_items.product_id",
            target_id="main.dbxcarta_test_inventory.products.id",
            confidence=1.0,
            source=EdgeSource.DECLARED,
            criteria=None,
        ),
    ]


def test_build_references_emits_provenance_columns(local_spark) -> None:
    df = build_references_rel(local_spark, _declared_edges())
    assert tuple(df.columns) == _EXPECTED_COLUMNS


def test_build_references_declared_values(local_spark) -> None:
    rows = build_references_rel(local_spark, _declared_edges()).collect()
    assert len(rows) == 3
    for row in rows:
        assert row["confidence"] == 1.0
        assert row["source"] == "declared"
        assert row["criteria"] is None


def test_build_references_preserves_ids(local_spark) -> None:
    rows = build_references_rel(local_spark, _declared_edges()).collect()
    source_ids = {r["source_id"] for r in rows}
    target_ids = {r["target_id"] for r in rows}
    assert "main.dbxcarta_test_sales.orders.customer_id" in source_ids
    assert "main.dbxcarta_test_sales.customers.id" in target_ids


def test_build_references_source_tag_is_serialized_from_enum(local_spark) -> None:
    """Non-declared EdgeSource values round-trip as their string .value."""
    edges = [
        FKEdge(
            source_id="cat.s.t.a",
            target_id="cat.s.t.b",
            confidence=0.85,
            source=EdgeSource.INFERRED_METADATA,
            criteria=None,
        ),
    ]
    rows = {r["source"] for r in build_references_rel(local_spark, edges).collect()}
    assert rows == {"inferred_metadata"}


def test_references_properties_tuple_matches_dataframe(local_spark) -> None:
    """Contract's REFERENCES_PROPERTIES must be a subset of the DataFrame columns.

    The writer passes REFERENCES_PROPERTIES to the Neo4j Spark Connector's
    `relationship.properties` option. If the DataFrame columns drift from
    that tuple, property writes silently stop.
    """
    df_columns = set(build_references_rel(local_spark, _declared_edges()).columns)
    assert set(REFERENCES_PROPERTIES).issubset(df_columns)
