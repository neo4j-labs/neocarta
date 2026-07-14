"""Unit tests for the normalized-metadata data model components."""

import numpy as np
import pytest
from pydantic import ValidationError

from neocarta.data_model._validators import coerce_yes_no_to_bool
from neocarta.data_model.normalized import (
    ColumnRecord,
    DatabaseRecord,
    InformationSchemaTable,
    NormalizedMetadata,
    Osi,
    OsiColumnRecord,
    OsiExpressionRecord,
    OsiSemanticModelRecord,
    ReferenceRecord,
    SchemaRecord,
    TableRecord,
    ValueRecord,
)

RECORD_TYPES = [
    DatabaseRecord,
    SchemaRecord,
    TableRecord,
    ColumnRecord,
    ReferenceRecord,
    ValueRecord,
]


# --- coerce_yes_no_to_bool ---------------------------------------------------


def test_coerce_yes_no_true_strings():
    """YES/TRUE/1 (case-insensitive, trimmed) coerce to True."""
    assert coerce_yes_no_to_bool("YES") is True
    assert coerce_yes_no_to_bool(" Yes ") is True
    assert coerce_yes_no_to_bool("true") is True
    assert coerce_yes_no_to_bool("1") is True


def test_coerce_yes_no_false_strings():
    """NO/FALSE/0 coerce to False."""
    assert coerce_yes_no_to_bool("NO") is False
    assert coerce_yes_no_to_bool("false") is False
    assert coerce_yes_no_to_bool("0") is False


def test_coerce_yes_no_integral_floats():
    """Integral floats (e.g. a pandas float64 flag column) coerce like their int form."""
    assert coerce_yes_no_to_bool(0.0) is False
    assert coerce_yes_no_to_bool(1.0) is True
    assert coerce_yes_no_to_bool(np.float64(0.0)) is False
    assert coerce_yes_no_to_bool(np.float64(1.0)) is True


def test_coerce_yes_no_real_bools_passthrough():
    """Real booleans pass through unchanged."""
    assert coerce_yes_no_to_bool(True) is True
    assert coerce_yes_no_to_bool(False) is False


def test_coerce_yes_no_none_uses_default():
    """None yields the default (both default values)."""
    assert coerce_yes_no_to_bool(None) is True
    assert coerce_yes_no_to_bool(None, default=False) is False


def test_coerce_yes_no_nan_uses_default():
    """NaN yields the default (both default values)."""
    assert coerce_yes_no_to_bool(np.nan) is True
    assert coerce_yes_no_to_bool(float("nan"), default=False) is False


def test_coerce_yes_no_unrecognized_uses_default():
    """Unrecognised strings yield the default.

    Source-specific categorical nullability (e.g. column mode NULLABLE/REQUIRED)
    is not a token here — it is decoded upstream in the retriever — so it falls
    through to the default instead of being specially recognised.
    """
    assert coerce_yes_no_to_bool("maybe") is True
    assert coerce_yes_no_to_bool("maybe", default=False) is False
    assert coerce_yes_no_to_bool("NULLABLE", default=False) is False
    assert coerce_yes_no_to_bool("REQUIRED", default=False) is False


# --- records: construction + coercion ----------------------------------------


def test_database_record_uppercases_platform_service():
    """Platform and service are uppercased; name-parts pass through."""
    rec = DatabaseRecord(database_name="db", platform="gcp", service="bigquery")
    assert rec.database_name == "db"
    assert rec.platform == "GCP"
    assert rec.service == "BIGQUERY"


def test_database_record_nan_optionals_become_none():
    """NaN optional fields normalise to None."""
    rec = DatabaseRecord(database_name="db", platform=np.nan, service=np.nan, description=np.nan)
    assert rec.platform is None
    assert rec.service is None
    assert rec.description is None


def test_schema_record_from_name_parts():
    """A schema record is built from its name-parts."""
    rec = SchemaRecord(database_name="db", schema_name="s")
    assert rec.database_name == "db"
    assert rec.schema_name == "s"
    assert rec.description is None


def test_table_record_optionals_nan_to_none():
    """NaN table_type/description normalise to None."""
    rec = TableRecord(
        database_name="db",
        schema_name="s",
        table_name="t",
        table_type=np.nan,
        description=np.nan,
    )
    assert rec.table_type is None
    assert rec.description is None


def test_column_record_defaults():
    """Column defaults: nullable True, PK/FK None (unknown), others None."""
    rec = ColumnRecord(database_name="db", schema_name="s", table_name="t", column_name="c")
    assert rec.ordinal_position is None
    assert rec.data_type is None
    assert rec.is_nullable is True
    assert rec.is_primary_key is None
    assert rec.is_foreign_key is None
    assert rec.description is None


def test_column_record_is_nullable_coercion():
    """is_nullable coerces YES->True and NO->False."""
    yes = ColumnRecord(
        database_name="db", schema_name="s", table_name="t", column_name="c", is_nullable="YES"
    )
    no = ColumnRecord(
        database_name="db", schema_name="s", table_name="t", column_name="c", is_nullable="NO"
    )
    assert yes.is_nullable is True
    assert no.is_nullable is False


def test_column_record_pk_fk_preserved():
    """Real PK/FK booleans are preserved as given."""
    rec = ColumnRecord(
        database_name="db",
        schema_name="s",
        table_name="t",
        column_name="c",
        is_primary_key=True,
        is_foreign_key=False,
    )
    assert rec.is_primary_key is True
    assert rec.is_foreign_key is False


def test_reference_record_from_name_parts():
    """A reference row carries source/target name-parts, not column ids."""
    rec = ReferenceRecord(
        source_database_name="db",
        source_schema_name="s",
        source_table_name="orders",
        source_column_name="customer_id",
        target_database_name="db",
        target_schema_name="s",
        target_table_name="customers",
        target_column_name="customer_id",
        criteria="orders.customer_id = customers.customer_id",
    )
    assert rec.source_table_name == "orders"
    assert rec.target_table_name == "customers"
    assert rec.criteria == "orders.customer_id = customers.customer_id"
    assert "source_column_id" not in ReferenceRecord.model_fields
    assert "target_column_id" not in ReferenceRecord.model_fields


def test_reference_record_criteria_nan_to_none():
    """NaN criteria normalises to None."""
    rec = ReferenceRecord(
        source_database_name="db",
        source_schema_name="s",
        source_table_name="t",
        source_column_name="c",
        target_database_name="db",
        target_schema_name="s",
        target_table_name="t2",
        target_column_name="c2",
        criteria=np.nan,
    )
    assert rec.criteria is None


def test_value_record_casts_value_to_str():
    """A non-string value is cast to str."""
    rec = ValueRecord(
        database_name="db", schema_name="s", table_name="t", column_name="c", value=123
    )
    assert rec.value == "123"


def test_value_record_string_value():
    """A string value passes through unchanged."""
    rec = ValueRecord(
        database_name="db", schema_name="s", table_name="t", column_name="c", value="Electronics"
    )
    assert rec.value == "Electronics"


# --- guard: records carry no id / embedding ----------------------------------


def test_records_have_no_id_field():
    """No record model declares an ``id`` field."""
    for model in RECORD_TYPES:
        assert "id" not in model.model_fields


def test_records_have_no_embedding_field():
    """No record model declares an ``embedding`` field."""
    for model in RECORD_TYPES:
        assert "embedding" not in model.model_fields


def test_record_instance_has_no_id_or_embedding_attrs():
    """A constructed record exposes neither ``id`` nor ``embedding``."""
    col = ColumnRecord(database_name="db", schema_name="s", table_name="t", column_name="c")
    assert not hasattr(col, "id")
    assert not hasattr(col, "embedding")


# --- containers --------------------------------------------------------------


def test_information_schema_table_empty_defaults():
    """Empty InformationSchemaTable yields six empty lists and the right kind."""
    table = InformationSchemaTable()
    assert isinstance(table, NormalizedMetadata)
    assert table.normalized_kind == "information_schema"
    assert table.databases == []
    assert table.schemas == []
    assert table.tables == []
    assert table.columns == []
    assert table.references == []
    assert table.values == []


def test_information_schema_table_holds_typed_records():
    """Populated lists hold typed record instances."""
    table = InformationSchemaTable(
        databases=[DatabaseRecord(database_name="db")],
        columns=[
            ColumnRecord(database_name="db", schema_name="s", table_name="t", column_name="c")
        ],
    )
    assert isinstance(table.databases[0], DatabaseRecord)
    assert isinstance(table.columns[0], ColumnRecord)
    assert table.databases[0].database_name == "db"


def test_osi_empty_defaults():
    """Empty Osi yields eight empty lists and the right kind."""
    osi = Osi()
    assert isinstance(osi, NormalizedMetadata)
    assert osi.normalized_kind == "osi"
    for field in (
        "semantic_models",
        "tables",
        "columns",
        "metrics",
        "joins",
        "expressions",
        "relationships",
        "aspects",
    ):
        assert getattr(osi, field) == []


def test_osi_holds_typed_records():
    """Populated Osi lists hold typed record instances."""
    osi = Osi(
        semantic_models=[OsiSemanticModelRecord(name="model", osi_version="1.0")],
        columns=[OsiColumnRecord(table_name="t", name="c")],
        expressions=[OsiExpressionRecord(dialect="bigquery", expression="SUM(x)")],
    )
    assert osi.semantic_models[0].name == "model"
    assert osi.columns[0].name == "c"
    assert osi.expressions[0].dialect == "bigquery"


def test_container_forbids_extra_fields():
    """The marker base forbids unexpected fields on its containers."""
    with pytest.raises(ValidationError):
        InformationSchemaTable(unexpected="x")
