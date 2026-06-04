"""Direct tests for the shared FK primitives in `dbxcarta.spark.ingest.fk.common`.

These helpers are called by all three discovery strategies. Direct coverage
keeps future refactors honest.
"""

from __future__ import annotations

from dbxcarta.spark.ingest.fk.common import (
    ColumnMeta,
    ConstraintRow,
    PKEvidence,
    PKIndex,
    build_id_cols_index,
    canonicalize,
    pk_kind,
    types_compatible,
)

# --- types_compatible / canonicalize ----------------------------------------


def test_canonicalize_int_family_collapses_to_integer() -> None:
    assert canonicalize("BIGINT") == ("INTEGER", None)
    assert canonicalize("INT") == ("INTEGER", None)
    assert canonicalize("LONG") == ("INTEGER", None)
    assert canonicalize("SMALLINT") == ("INTEGER", None)


def test_canonicalize_string_length_stripped() -> None:
    """STRING, STRING(n), VARCHAR, VARCHAR(n), CHAR all canonicalise to STRING."""
    assert canonicalize("STRING") == ("STRING", None)
    assert canonicalize("STRING(255)") == ("STRING", None)
    assert canonicalize("VARCHAR(10)") == ("STRING", None)
    assert canonicalize("CHAR") == ("STRING", None)


def test_canonicalize_decimal_keeps_scale_drops_precision() -> None:
    """DECIMAL(10,2) ↔ DECIMAL(18,2); DECIMAL(10,2) ≠ DECIMAL(10,0)."""
    assert canonicalize("DECIMAL(10,2)") == ("DECIMAL", "2")
    assert canonicalize("DECIMAL(18,2)") == ("DECIMAL", "2")
    assert canonicalize("NUMERIC(10,0)") == ("DECIMAL", "0")


def test_types_compatible_decimal_same_scale_different_precision() -> None:
    assert types_compatible("DECIMAL(10,2)", "DECIMAL(18,2)") is True
    assert types_compatible("DECIMAL(10,2)", "DECIMAL(10,0)") is False


def test_types_compatible_int_and_bigint() -> None:
    assert types_compatible("INT", "BIGINT") is True


def test_types_compatible_int_and_string() -> None:
    assert types_compatible("INT", "STRING") is False


# --- pk_kind: declared beats heuristic --------------------------------------


def _col(table: str, column: str) -> ColumnMeta:
    return ColumnMeta(
        catalog="c",
        schema="s",
        table=table,
        column=column,
        data_type="BIGINT",
        comment=None,
    )


def test_pk_kind_declared_pk_wins() -> None:
    rows = [
        ConstraintRow(
            table_catalog="c",
            table_schema="s",
            table_name="users",
            column_name="id",
            constraint_type="PRIMARY KEY",
            ordinal_position=1,
            constraint_name="users_pk",
        )
    ]
    idx = PKIndex.from_constraints(rows)
    tgt = _col("users", "id")
    assert pk_kind(tgt, idx, build_id_cols_index([tgt])) is PKEvidence.DECLARED_PK


def test_pk_kind_unique_leftmost_classifies_as_unique_or_heur() -> None:
    rows = [
        ConstraintRow(
            table_catalog="c",
            table_schema="s",
            table_name="t",
            column_name="key",
            constraint_type="UNIQUE",
            ordinal_position=1,
            constraint_name="t_uniq",
        )
    ]
    idx = PKIndex.from_constraints(rows)
    tgt = _col("t", "key")
    assert pk_kind(tgt, idx, {}) is PKEvidence.UNIQUE_OR_HEUR


def test_pk_kind_id_heuristic_fires_when_no_declared_pk() -> None:
    """`id` column on a table with no declared constraints — still qualifies."""
    idx = PKIndex.from_constraints([])
    tgt = _col("users", "id")
    assert pk_kind(tgt, idx, build_id_cols_index([tgt])) is PKEvidence.UNIQUE_OR_HEUR


def test_pk_kind_table_id_heuristic_requires_sole_id_col() -> None:
    """`{table}_id` qualifies only when it's the SOLE _id-suffixed col."""
    idx = PKIndex.from_constraints([])
    users_id = _col("users", "users_id")
    other_id = _col("users", "other_id")
    cols = [users_id, other_id]
    assert pk_kind(users_id, idx, build_id_cols_index(cols)) is None


def test_pk_kind_returns_none_for_non_pk_like_column() -> None:
    idx = PKIndex.from_constraints([])
    tgt = _col("users", "email")
    assert pk_kind(tgt, idx, build_id_cols_index([tgt])) is None


# --- PKIndex.from_constraints -----------------------------------------------


def test_pk_index_composite_pk_counted_not_indexed() -> None:
    """A two-column declared PK does not populate pk_cols."""
    rows = [
        ConstraintRow(
            table_catalog="c",
            table_schema="s",
            table_name="junction",
            column_name="left_id",
            constraint_type="PRIMARY KEY",
            ordinal_position=1,
            constraint_name="junction_pk",
        ),
        ConstraintRow(
            table_catalog="c",
            table_schema="s",
            table_name="junction",
            column_name="right_id",
            constraint_type="PRIMARY KEY",
            ordinal_position=2,
            constraint_name="junction_pk",
        ),
    ]
    idx = PKIndex.from_constraints(rows)
    assert idx.pk_cols == {}
    assert idx.composite_pk_count == 1


def test_build_id_cols_index_groups_by_table_and_filters_non_id_suffix() -> None:
    cols = [
        _col("users", "id"),
        _col("users", "user_id"),
        _col("users", "email"),  # no _id suffix → excluded
        _col("orders", "order_id"),
    ]
    index = build_id_cols_index(cols)
    assert set(index["c.s.users"]) == {"user_id"}
    assert set(index["c.s.orders"]) == {"order_id"}
    assert "id" not in index["c.s.users"]  # 'id' doesn't end in '_id'
