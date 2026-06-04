from __future__ import annotations

from typing import Any

import pytest
from dbxcarta.core.materialize import (
    MaterializedTable,
    MaterializeStats,
    build_create_schema_statement,
    build_foreign_key_statements,
    build_insert_statement,
    build_table,
    coerce_type,
    constraint_name,
    escape_sql_string,
    read_schema_entry,
    render_sql_value,
    sanitize_identifier,
)

# --- coerce_type ---------------------------------------------------------


def test_coerce_type_maps_known_types() -> None:
    assert coerce_type("integer") == ("INT", False)
    assert coerce_type("BIGINT") == ("BIGINT", False)
    assert coerce_type("text") == ("STRING", False)


def test_coerce_type_decimal_is_clamped() -> None:
    assert coerce_type("DECIMAL(40,50)") == ("DECIMAL(38,38)", False)
    assert coerce_type("numeric(5,2)") == ("DECIMAL(5,2)", False)


def test_coerce_type_sized_varchar_becomes_string() -> None:
    assert coerce_type("VARCHAR(255)") == ("STRING", False)


def test_coerce_type_strips_args_then_matches_base() -> None:
    assert coerce_type("int(11)") == ("INT", False)


def test_coerce_type_falls_back_to_string() -> None:
    assert coerce_type("") == ("STRING", True)
    assert coerce_type("WIDGET") == ("STRING", True)


def test_coerce_type_honours_custom_map() -> None:
    assert coerce_type("GEOMETRY", {"GEOMETRY": "BINARY"}) == ("BINARY", False)


def test_coerce_type_maps_unsigned_ints_to_wider_signed() -> None:
    assert coerce_type("UnsignedTinyInt") == ("SMALLINT", False)
    assert coerce_type("UnsignedSmallInt") == ("INT", False)
    assert coerce_type("UnsignedInt") == ("BIGINT", False)
    assert coerce_type("UnsignedInteger") == ("BIGINT", False)
    assert coerce_type("UnsignedBigInt") == ("DECIMAL(20,0)", False)


def test_coerce_type_maps_vendor_aliases() -> None:
    assert coerce_type("VARCHAR2") == ("STRING", False)
    assert coerce_type("CLOB") == ("STRING", False)
    assert coerce_type("serial") == ("BIGINT", False)
    assert coerce_type("money") == ("DECIMAL(18,4)", False)
    assert coerce_type("LONGBLOB") == ("BINARY", False)


def test_coerce_type_matches_camelcase_multiword_types() -> None:
    assert coerce_type("DoublePrecision") == ("DOUBLE", False)
    assert coerce_type("CharacterVarying") == ("STRING", False)


# --- sanitize_identifier -------------------------------------------------


def test_sanitize_identifier_cleans_and_lowercases() -> None:
    assert sanitize_identifier("Order Items!") == "order_items"


def test_sanitize_identifier_prefixes_leading_digit() -> None:
    assert sanitize_identifier("9lives", prefix="t") == "t_9lives"
    assert sanitize_identifier("1col", prefix="c") == "c_1col"


def test_sanitize_identifier_empty_when_nothing_usable() -> None:
    assert sanitize_identifier("!!!") == ""


# --- escape / render -----------------------------------------------------


def test_escape_sql_string() -> None:
    assert escape_sql_string("a'b\\c") == "a''b\\\\c"


def test_render_sql_value() -> None:
    assert render_sql_value(None) == "NULL"
    assert render_sql_value(5) == "'5'"
    assert render_sql_value("o'brien") == "'o''brien'"


# --- build_insert_statement ----------------------------------------------


def test_build_insert_uses_insert_overwrite() -> None:
    sql = build_insert_statement("`c`.`s`.`t`", ["a", "b"], [(1, None), ("x", 2)])
    assert sql.startswith("INSERT OVERWRITE TABLE `c`.`s`.`t` (`a`, `b`) VALUES")
    assert "('1', NULL)" in sql
    assert "('x', '2')" in sql


# --- constraint_name -----------------------------------------------------


def test_constraint_name_short_is_verbatim() -> None:
    assert constraint_name("pk", ["orders"]) == "pk_orders"
    assert constraint_name("fk", ["child", "col_a", "col_b"]) == "fk_child__col_a__col_b"


def test_constraint_name_skips_empty_parts() -> None:
    assert constraint_name("pk", ["", "orders", ""]) == "pk_orders"


def test_constraint_name_long_keeps_prefix_and_hash_suffix() -> None:
    name = constraint_name("fk", ["x" * 400])
    assert len(name) == 255
    assert name.startswith("fk_")
    # 12-char hex suffix preserved at the tail.
    suffix = name.rsplit("_", 1)[-1]
    assert len(suffix) == 12
    assert all(ch in "0123456789abcdef" for ch in suffix)


def test_constraint_name_long_is_deterministic() -> None:
    assert constraint_name("fk", ["y" * 400]) == constraint_name("fk", ["y" * 400])


# --- MaterializeStats ----------------------------------------------------


def test_materialize_stats_add_merges_fields() -> None:
    total = MaterializeStats(tables_created=2, rows_inserted=10) + MaterializeStats(
        tables_created=3, fk_constraints_added=1
    )
    assert total.tables_created == 5
    assert total.rows_inserted == 10
    assert total.fk_constraints_added == 1


def test_materialize_stats_add_rejects_other_types() -> None:
    with pytest.raises(TypeError):
        MaterializeStats() + 1  # type: ignore[operator]


# --- read_schema_entry ---------------------------------------------------


def test_read_schema_entry_returns_schema_and_source() -> None:
    assert read_schema_entry({"uc_schema": "shop", "source_id": "shop_db"}) == ("shop", "shop_db")


@pytest.mark.parametrize("missing", ["uc_schema", "source_id"])
def test_read_schema_entry_rejects_missing_keys(missing: str) -> None:
    entry = {"uc_schema": "s", "source_id": "src"}
    del entry[missing]
    with pytest.raises(ValueError, match=f"missing required key.*{missing}"):
        read_schema_entry(entry)


# --- build_create_schema_statement ---------------------------------------


def test_build_create_schema_statement() -> None:
    sql, label = build_create_schema_statement("`cat`", "shop", "shop_db", property_prefix="ex")
    assert sql == ("CREATE SCHEMA IF NOT EXISTS `cat`.`shop` COMMENT 'ex source: shop_db'")
    assert label == "CREATE SCHEMA shop"


# --- build_table ---------------------------------------------------------


def _customers_table() -> dict[str, Any]:
    return {
        "name": "customers",
        "columns": [{"name": "id", "type": "int"}, {"name": "name", "type": "text"}],
        "primary_keys": ["id"],
        "foreign_keys": [],
        "rows": [[1, "Ada"], [2, "Grace"]],
    }


def _build(table: dict[str, Any], *, prefix: str = "ex"):
    return build_table(
        table,
        catalog_q="`cat`",
        schema_q="`shop`",
        source_id="shop_db",
        property_prefix=prefix,
    )


def test_build_table_folds_primary_key_and_inserts_rows() -> None:
    build = _build(_customers_table())
    plan = build.plan
    assert plan is not None
    # The primary key is folded into the CREATE: its column carries inline NOT
    # NULL and the table ends with an inline CONSTRAINT ... PRIMARY KEY clause,
    # so the former SET-NOT-NULL and ADD-PRIMARY-KEY ALTERs are gone.
    assert "`id` INT NOT NULL" in plan.create_sql
    assert "CONSTRAINT `pk_customers` PRIMARY KEY (`id`)" in plan.create_sql
    assert "SET NOT NULL" not in plan.create_sql
    assert "ADD CONSTRAINT" not in plan.create_sql
    assert "CREATE TABLE IF NOT EXISTS `cat`.`shop`.`customers`" in plan.create_sql
    assert "'ex.source_id' = 'shop_db'" in plan.create_sql
    assert plan.create_label == "CREATE TABLE `cat`.`shop`.`customers`"
    assert plan.has_primary_key is True

    assert plan.insert_sql is not None
    assert plan.insert_sql.startswith("INSERT OVERWRITE TABLE `cat`.`shop`.`customers`")
    assert plan.insert_label == "INSERT OVERWRITE `cat`.`shop`.`customers`"
    assert plan.row_count == 2

    assert plan.record.safe_name == "customers"
    assert plan.record.columns == frozenset({"id", "name"})
    assert build.stats.type_fallbacks == 0
    assert build.stats.tables_skipped == 0


def test_build_table_skips_unusable_name() -> None:
    build = _build({"name": "!!!", "columns": [{"name": "c", "type": "int"}]})
    assert build.plan is None
    assert build.stats.tables_skipped == 1


def test_build_table_skips_when_no_columns() -> None:
    build = _build({"name": "empty", "columns": []})
    assert build.plan is None
    assert build.stats.tables_skipped == 1


def test_build_table_skips_when_no_coercible_columns() -> None:
    build = _build({"name": "t", "columns": [{"name": "!!!", "type": "int"}]})
    assert build.plan is None
    assert build.stats.tables_skipped == 1


def test_build_table_counts_type_fallbacks() -> None:
    build = _build({"name": "t", "columns": [{"name": "c", "type": "mystery"}], "rows": []})
    assert build.plan is not None
    assert build.stats.type_fallbacks == 1


def test_build_table_without_rows_emits_no_insert() -> None:
    build = _build({"name": "t", "columns": [{"name": "c", "type": "int"}], "rows": []})
    assert build.plan is not None
    assert build.plan.insert_sql is None
    assert build.plan.insert_label is None
    assert build.plan.row_count == 0


def test_build_table_drops_pk_when_sample_row_has_null_in_pk_column() -> None:
    """A NULL in a PK column drops the inline PK so the rows still load.

    Inline ``NOT NULL`` would reject the null-PK row and fail the whole
    ``INSERT OVERWRITE`` (one atomic statement), losing every row for the table.
    Dropping the key keeps the data; the table just lands without its
    informational primary key.
    """
    table = {
        "name": "t",
        "columns": [{"name": "id", "type": "int"}, {"name": "v", "type": "text"}],
        "primary_keys": ["id"],
        "rows": [[1, "a"], [None, "b"]],  # second row has a null PK
    }
    build = _build(table)
    plan = build.plan
    assert plan is not None
    assert "PRIMARY KEY" not in plan.create_sql
    assert "NOT NULL" not in plan.create_sql
    assert plan.has_primary_key is False
    assert plan.row_count == 2  # both rows kept, including the null-PK row


def test_build_table_keeps_pk_when_pk_column_has_no_nulls() -> None:
    """The null gate is row-data-specific: clean PK data still folds the key."""
    table = {
        "name": "t",
        "columns": [{"name": "id", "type": "int"}, {"name": "v", "type": "text"}],
        "primary_keys": ["id"],
        "rows": [[1, "a"], [2, None]],  # null in a non-PK column is fine
    }
    build = _build(table)
    plan = build.plan
    assert plan is not None
    assert "`id` INT NOT NULL" in plan.create_sql
    assert "CONSTRAINT `pk_t` PRIMARY KEY (`id`)" in plan.create_sql
    assert plan.has_primary_key is True
    assert plan.row_count == 2


def test_build_table_drops_pk_when_column_sanitized_away() -> None:
    table = {
        "name": "t",
        "columns": [{"name": "keep", "type": "int"}],
        "primary_keys": ["keep", "!!!"],  # one PK column sanitizes away
        "rows": [],
    }
    build = _build(table)
    plan = build.plan
    assert plan is not None
    assert plan.has_primary_key is False
    assert "PRIMARY KEY" not in plan.create_sql


# --- build_foreign_key_statements ----------------------------------------


def _materialized_shop() -> dict[str, MaterializedTable]:
    return {
        "customers": MaterializedTable(
            safe_name="customers",
            columns=frozenset({"id", "name"}),
            foreign_keys=[],
        ),
        "orders": MaterializedTable(
            safe_name="orders",
            columns=frozenset({"id", "customer_id"}),
            foreign_keys=[
                {
                    "columns": ["customer_id"],
                    "foreign_table": "customers",
                    "referred_columns": ["id"],
                }
            ],
        ),
    }


def test_build_foreign_key_statements_emits_alter_for_valid_edge() -> None:
    stmts = build_foreign_key_statements(_materialized_shop(), catalog_q="`cat`", schema_q="`shop`")
    assert len(stmts) == 1
    sql, label = stmts[0]
    assert sql.startswith("ALTER TABLE `cat`.`shop`.`orders` ADD CONSTRAINT")
    assert "FOREIGN KEY (`customer_id`) REFERENCES `cat`.`shop`.`customers` (`id`)" in sql
    assert label == "ADD FOREIGN KEY `cat`.`shop`.`orders` -> `cat`.`shop`.`customers`"


def test_build_foreign_key_statements_skips_when_parent_absent() -> None:
    materialized = {
        "orders": MaterializedTable(
            safe_name="orders",
            columns=frozenset({"id", "customer_id"}),
            foreign_keys=[
                {
                    "columns": ["customer_id"],
                    "foreign_table": "customers",  # not materialized
                    "referred_columns": ["id"],
                }
            ],
        ),
    }
    assert build_foreign_key_statements(materialized, catalog_q="`cat`", schema_q="`shop`") == []


def test_build_foreign_key_statements_skips_on_arity_mismatch() -> None:
    materialized = {
        "customers": MaterializedTable("customers", frozenset({"id"}), []),
        "orders": MaterializedTable(
            "orders",
            frozenset({"customer_id"}),
            [
                {
                    "columns": ["customer_id"],
                    "foreign_table": "customers",
                    "referred_columns": ["id", "extra"],  # arity 2 vs 1
                }
            ],
        ),
    }
    assert build_foreign_key_statements(materialized, catalog_q="`cat`", schema_q="`shop`") == []
