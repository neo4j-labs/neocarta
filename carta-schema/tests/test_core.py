"""Unit tests that the core models construct and validate as expected."""

import pytest
from carta_schema.rdbms.core import (
    Column,
    Database,
    HasColumn,
    HasSchema,
    HasTable,
    References,
    Schema,
    Table,
)
from pydantic import ValidationError


def test_database_uppercases_platform_and_service():
    db = Database(id="db1", name="db1", platform="gcp", service="bigquery")
    assert db.platform == "GCP"
    assert db.service == "BIGQUERY"
    assert db.description is None
    assert db.embedding is None


def test_optional_string_fields_default_to_none():
    assert Schema(id="s1", name="s1").description is None
    assert Table(id="t1", name="t1").description is None
    col = Column(id="c1", name="c1")
    assert col.type is None
    assert col.description is None


def test_column_boolean_defaults():
    col = Column(id="c1", name="c1")
    assert col.nullable is True
    assert col.is_primary_key is False
    assert col.is_foreign_key is False


def test_required_id_and_name_are_enforced():
    with pytest.raises(ValidationError):
        Database(name="db1")
    with pytest.raises(ValidationError):
        Column(id="c1")


def test_relationship_endpoints_are_required():
    assert HasSchema(database_id="db1", schema_id="s1").schema_id == "s1"
    assert HasTable(schema_id="s1", table_id="t1").table_id == "t1"
    assert HasColumn(table_id="t1", column_id="c1").column_id == "c1"
    ref = References(source_column_id="c1", target_column_id="c2")
    assert ref.criteria is None
    with pytest.raises(ValidationError):
        References(source_column_id="c1")
