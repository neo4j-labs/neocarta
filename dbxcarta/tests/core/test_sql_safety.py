from __future__ import annotations

from dbxcarta.core.sql_safety import sql_targets_only_catalog


def test_accepts_safe_single_catalog_select() -> None:
    sql = (
        "SELECT * FROM `schemapile_lakehouse`.`sp_shop`.`orders` o "
        "JOIN `schemapile_lakehouse`.`sp_shop`.`customers` c "
        "ON o.customer_id = c.id"
    )
    assert sql_targets_only_catalog(sql, "schemapile_lakehouse") is True


def test_rejects_unqualified_table() -> None:
    assert sql_targets_only_catalog("SELECT * FROM orders", "cat") is False


def test_rejects_other_catalog() -> None:
    sql = "SELECT * FROM `other_catalog`.`sp_shop`.`orders`"
    assert sql_targets_only_catalog(sql, "schemapile_lakehouse") is False


def test_rejects_multi_statement() -> None:
    sql = "SELECT * FROM `cat`.`sp_shop`.`orders`; DROP TABLE `cat`.`sp_shop`.`orders`"
    assert sql_targets_only_catalog(sql, "cat") is False


def test_rejects_non_select() -> None:
    assert sql_targets_only_catalog("DELETE FROM `cat`.`s`.`t`", "cat") is False


def test_rejects_forbidden_keyword() -> None:
    sql = "SELECT * FROM `cat`.`s`.`t` UNION SELECT 1; DROP TABLE x"
    assert sql_targets_only_catalog(sql, "cat") is False


def test_rejects_information_schema() -> None:
    sql = "SELECT * FROM `cat`.information_schema.tables"
    assert sql_targets_only_catalog(sql, "cat") is False


def test_rejects_system_catalog() -> None:
    sql = "SELECT * FROM system.information_schema.tables"
    assert sql_targets_only_catalog(sql, "system") is False
