"""Spark-native metadata FK inference (`fk.inference`).

The metadata strategy is a DataFrame pipeline now: no driver collect, no
Python all-pairs loop. These tests drive it the way the orchestrator does —
information_schema-shaped `columns_df` / `constraints_df` in, a REFERENCES
DataFrame out — and assert edges, confidences, and prior-pair suppression
on known fixtures. Score constants are pulled from `_SCORE_TABLE` so the
assertions move with the rule table.
"""

from __future__ import annotations

from dbxcarta.spark.contract import REFERENCES_PROPERTIES, EdgeSource
from dbxcarta.spark.ingest.fk.common import PKEvidence
from dbxcarta.spark.ingest.fk.inference import (
    build_columns_frame,
    build_pk_gate,
    infer_metadata_edges,
)
from dbxcarta.spark.ingest.fk.metadata import _SCORE_TABLE, NameMatchKind

_CAT = "main"
_SA = "dbxcarta_fk_test"
_SB = "dbxcarta_fk_test_b"

_S_SUFFIX_DPK_NO_COMMENT = _SCORE_TABLE[
    (NameMatchKind.SUFFIX, PKEvidence.DECLARED_PK, False)
]  # 0.83
_S_SUFFIX_UOH_COMMENT = _SCORE_TABLE[
    (NameMatchKind.SUFFIX, PKEvidence.UNIQUE_OR_HEUR, True)
]  # 0.82

_COL_FIELDS = (
    "table_catalog",
    "table_schema",
    "table_name",
    "column_name",
    "data_type",
    "comment",
)
_CON_FIELDS = (
    "table_catalog",
    "table_schema",
    "table_name",
    "column_name",
    "constraint_type",
    "ordinal_position",
    "constraint_name",
)
_EXPECTED_COLUMNS = ("source_id", "target_id", "confidence", "source", "criteria")


def _columns_schema():
    from pyspark.sql.types import StringType, StructField, StructType

    return StructType([StructField(n, StringType(), True) for n in _COL_FIELDS])


def _constraints_schema():
    from pyspark.sql.types import (
        IntegerType,
        StringType,
        StructField,
        StructType,
    )

    return StructType(
        [
            StructField("table_catalog", StringType(), True),
            StructField("table_schema", StringType(), True),
            StructField("table_name", StringType(), True),
            StructField("column_name", StringType(), True),
            StructField("constraint_type", StringType(), True),
            StructField("ordinal_position", IntegerType(), True),
            StructField("constraint_name", StringType(), True),
        ]
    )


def _columns_df(spark, rows: list[tuple]):
    return spark.createDataFrame(list(rows), schema=_columns_schema())


def _constraints_df(spark, rows: list[tuple]):
    return spark.createDataFrame(list(rows), schema=_constraints_schema())


def _pk(schema: str, table: str, column: str = "id") -> tuple:
    return (
        _CAT,
        schema,
        table,
        column,
        "PRIMARY KEY",
        1,
        f"{schema}_{table}_pk",
    )


def _run(spark, col_rows, con_rows, declared_df=None):
    columns_df = _columns_df(spark, col_rows)
    constraints_df = _constraints_df(spark, con_rows)
    cf = build_columns_frame(columns_df)
    pk_gate, composite_pk_count = build_pk_gate(cf, constraints_df)
    edges_df, counts, composite = infer_metadata_edges(
        spark,
        cf,
        pk_gate,
        declared_df,
        composite_pk_count=composite_pk_count,
    )
    rows = edges_df.collect()
    edges = {(r["source_id"], r["target_id"]): r["confidence"] for r in rows}
    return edges, counts, composite, edges_df


def _v5fk_columns() -> list[tuple]:
    b = "BIGINT"
    return [
        (_CAT, _SA, "customers", "id", b, None),
        (_CAT, _SA, "customers", "name", "STRING", None),
        (_CAT, _SA, "orders", "id", b, None),
        (_CAT, _SA, "orders", "customer_id", b, None),
        (_CAT, _SA, "order_items", "id", b, None),
        (_CAT, _SA, "order_items", "order_id", b, None),
        (_CAT, _SA, "shipments", "id", b, None),
        (_CAT, _SA, "shipments", "order_id", b, None),
    ]


def _v5fk_constraints() -> list[tuple]:
    return [_pk(_SA, t) for t in ("customers", "orders", "order_items", "shipments")]


# --- Declared-FK rediscovery -------------------------------------------------


def test_v5fk_rediscovers_three_declared_fks(local_spark) -> None:
    edges, counts, _composite, df = _run(
        local_spark,
        _v5fk_columns(),
        _v5fk_constraints(),
    )
    expected = {
        (f"{_CAT}.{_SA}.orders.customer_id", f"{_CAT}.{_SA}.customers.id"),
        (f"{_CAT}.{_SA}.order_items.order_id", f"{_CAT}.{_SA}.orders.id"),
        (f"{_CAT}.{_SA}.shipments.order_id", f"{_CAT}.{_SA}.orders.id"),
    }
    assert expected == set(edges), f"got {set(edges)}"
    for pair in expected:
        assert edges[pair] == _S_SUFFIX_DPK_NO_COMMENT
    for r in df.collect():
        assert r["source"] == EdgeSource.INFERRED_METADATA.value
        assert r["criteria"] is None
    assert counts.accepted == len(expected)


def test_declared_prior_pair_suppression(local_spark) -> None:
    """A declared-only prior frame removes exactly that edge from output."""
    prior = local_spark.createDataFrame(
        [(f"{_CAT}.{_SA}.orders.customer_id", f"{_CAT}.{_SA}.customers.id")],
        schema=["source_id", "target_id"],
    )
    edges, counts, _composite, _df = _run(
        local_spark,
        _v5fk_columns(),
        _v5fk_constraints(),
        declared_df=prior,
    )
    assert (
        f"{_CAT}.{_SA}.orders.customer_id",
        f"{_CAT}.{_SA}.customers.id",
    ) not in edges
    assert (
        f"{_CAT}.{_SA}.order_items.order_id",
        f"{_CAT}.{_SA}.orders.id",
    ) in edges
    assert counts.accepted == 2


# --- No-declared-PK heuristic recovery ---------------------------------------


def test_heuristic_recovers_with_comment_overlap(local_spark) -> None:
    """Zero declared PKs: the `id` name heuristic gates the target and
    comment overlap lifts the suffix score to 0.82 (above the 0.8 floor)."""
    cols = [
        (_CAT, _SA, "customers", "id", "BIGINT", "customer identifier"),
        (_CAT, _SA, "customers", "name", "BIGINT", None),
        (_CAT, _SA, "orders", "id", "BIGINT", "order identifier"),
        (_CAT, _SA, "orders", "customer_id", "BIGINT", "customer identifier"),
    ]
    edges, _counts, _composite, _df = _run(local_spark, cols, [])
    suffix_edge = (
        f"{_CAT}.{_SA}.orders.customer_id",
        f"{_CAT}.{_SA}.customers.id",
    )
    assert suffix_edge in edges
    assert edges[suffix_edge] == _S_SUFFIX_UOH_COMMENT


def test_heuristic_without_comment_drops_below_threshold(local_spark) -> None:
    """Suffix + heuristic + no comment scores 0.78 < 0.8 → no edges."""
    edges, counts, _composite, _df = _run(local_spark, _v5fk_columns(), [])
    assert edges == {}
    assert counts.accepted == 0


# --- Tie-break attenuation ---------------------------------------------------


def test_tie_break_drops_fanout(local_spark) -> None:
    """`user_id` fans out to three stem-matching `user*` tables in one schema.

    Three same-schema suffix candidates → denom = sqrt(2) attenuates 0.83 to
    0.587 < 0.8; nothing emitted.
    """
    schema = "tenant"
    cols = [
        (_CAT, schema, "accounts", "user_id", "BIGINT", None),
        (_CAT, schema, "accounts", "id", "BIGINT", None),
    ]
    cons = [_pk(schema, "accounts")]
    for t in ("user", "users", "useres"):
        cols.append((_CAT, schema, t, "id", "BIGINT", None))
        cons.append(_pk(schema, t))
    edges, counts, _composite, _df = _run(local_spark, cols, cons)
    assert edges == {}
    assert counts.accepted == 0


def test_tie_break_preserves_two_way_pair(local_spark) -> None:
    """Two stem-matching tables → n=2, denom=1, full 0.83 preserved."""
    cols = [
        (_CAT, "shop", "accounts", "user_id", "BIGINT", None),
        (_CAT, "shop", "user", "id", "BIGINT", None),
        (_CAT, "shop", "users", "id", "BIGINT", None),
    ]
    cons = [_pk("shop", "user"), _pk("shop", "users")]
    edges, counts, _composite, _df = _run(local_spark, cols, cons)
    suffix_targets = {
        (f"{_CAT}.shop.accounts.user_id", f"{_CAT}.shop.user.id"),
        (f"{_CAT}.shop.accounts.user_id", f"{_CAT}.shop.users.id"),
    }
    assert suffix_targets.issubset(edges.keys())
    for pair in suffix_targets:
        assert edges[pair] == _S_SUFFIX_DPK_NO_COMMENT
    assert counts.accepted >= 2


# --- Schema / catalog isolation ---------------------------------------------


def test_cross_schema_candidates_rejected(local_spark) -> None:
    cols = [
        (_CAT, _SA, "customers", "id", "BIGINT", None),
        (_CAT, _SB, "orders", "customer_id", "BIGINT", None),
    ]
    cons = [_pk(_SA, "customers")]
    edges, _counts, _composite, _df = _run(local_spark, cols, cons)
    assert edges == {}


def test_cross_catalog_candidates_rejected(local_spark) -> None:
    cols = [
        ("bronze", _SA, "customers", "id", "BIGINT", None),
        ("gold", _SA, "orders", "customer_id", "BIGINT", None),
    ]
    cons = [("bronze", _SA, "customers", "id", "PRIMARY KEY", 1, "customers_pk")]
    edges, _counts, _composite, _df = _run(local_spark, cols, cons)
    assert edges == {}


def test_same_catalog_schema_pair_inferred(local_spark) -> None:
    """Control for the isolation tests: same catalog+schema does emit."""
    cols = [
        ("bronze", _SA, "customers", "id", "BIGINT", None),
        ("bronze", _SA, "orders", "customer_id", "BIGINT", None),
    ]
    cons = [("bronze", _SA, "customers", "id", "PRIMARY KEY", 1, "customers_pk")]
    edges, _counts, _composite, _df = _run(local_spark, cols, cons)
    assert (
        f"bronze.{_SA}.orders.customer_id",
        f"bronze.{_SA}.customers.id",
    ) in edges


def test_generic_id_exact_matches_are_not_inferred(local_spark) -> None:
    """Standalone `id` columns are not useful FK evidence by themselves."""
    cols = [
        (_CAT, "s", "customers", "id", "BIGINT", None),
        (_CAT, "s", "orders", "id", "BIGINT", None),
    ]
    cons = [_pk("s", "customers"), _pk("s", "orders")]
    edges, counts, _composite, _df = _run(local_spark, cols, cons)
    assert edges == {}
    assert counts.accepted == 0


# --- Type compatibility ------------------------------------------------------


def test_type_equiv_accepts_int_and_bigint(local_spark) -> None:
    cols = [
        (_CAT, "s", "orders", "customer_id", "INT", None),
        (_CAT, "s", "customer", "id", "BIGINT", None),
    ]
    cons = [_pk("s", "customer")]
    edges, _counts, _composite, _df = _run(local_spark, cols, cons)
    assert (f"{_CAT}.s.orders.customer_id", f"{_CAT}.s.customer.id") in edges


def test_type_mismatch_blocks_match(local_spark) -> None:
    cols = [
        (_CAT, "s", "orders", "customer_id", "STRING", None),
        (_CAT, "s", "customer", "id", "BIGINT", None),
    ]
    cons = [_pk("s", "customer")]
    edges, _counts, _composite, _df = _run(local_spark, cols, cons)
    assert edges == {}


# --- Composite PK accounting -------------------------------------------------


def test_composite_pk_counted_not_indexed(local_spark) -> None:
    """A two-column declared PK is counted and never gates a target.

    `junction` has only a composite PK and no `id`/`{table}_id` column, so
    `things.junction_id` finds no PK-like target and emits nothing — while
    the composite PK is still counted.
    """
    cols = [
        (_CAT, "s", "junction", "alpha_key", "BIGINT", None),
        (_CAT, "s", "junction", "beta_key", "BIGINT", None),
        (_CAT, "s", "things", "junction_id", "BIGINT", None),
    ]
    cons = [
        (_CAT, "s", "junction", "alpha_key", "PRIMARY KEY", 1, "junction_pk"),
        (_CAT, "s", "junction", "beta_key", "PRIMARY KEY", 2, "junction_pk"),
    ]
    edges, counts, composite, _df = _run(local_spark, cols, cons)
    assert composite == 1
    assert counts.composite_pk_skipped == 1
    assert edges == {}


# --- Column-parity guard ----------------------------------------------------


def test_edges_df_columns_match_references_properties(local_spark) -> None:
    _edges, _counts, _composite, df = _run(
        local_spark,
        _v5fk_columns(),
        _v5fk_constraints(),
    )
    assert tuple(df.columns) == _EXPECTED_COLUMNS
    assert set(REFERENCES_PROPERTIES).issubset(set(df.columns))


def test_empty_input_yields_empty_schema_frame(local_spark) -> None:
    cols = [(_CAT, "s", "t", "name", "STRING", None)]
    _edges, counts, _composite, df = _run(local_spark, cols, [])
    assert tuple(df.columns) == _EXPECTED_COLUMNS
    assert df.count() == 0
    assert counts.accepted == 0
