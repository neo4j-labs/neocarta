"""Contract-level tests for the normalized structural-core models.

Proves the standardized vocabulary absorbs every schema connector's *raw* source
field-names without loss, that value coercions (D7) apply, and that no graph
identity (D6) leaks onto any field. The full connector flip is S4; here we prove
the contract only.
"""

from __future__ import annotations

import pytest
from pydantic import AliasChoices, BaseModel, ValidationError

from neocarta.data_model._validators import coerce_nullable
from neocarta.etl.metadata_normalizer.normalized_schema import (
    ColumnRecord,
    DatabaseRecord,
    ForeignKeyRecord,
    NormalizedStructuralSchema,
    SchemaRecord,
    TableRecord,
)

ALL_MODELS = [
    DatabaseRecord,
    SchemaRecord,
    TableRecord,
    ColumnRecord,
    ForeignKeyRecord,
    NormalizedStructuralSchema,
]


def _accepted_input_names(model: type[BaseModel]) -> set[str]:
    """Every input key ``model`` accepts: field names plus all validation aliases."""
    names: set[str] = set()
    for field_name, info in model.model_fields.items():
        names.add(field_name)
        alias = info.validation_alias
        if isinstance(alias, AliasChoices):
            names.update(choice for choice in alias.choices if isinstance(choice, str))
        elif isinstance(alias, str):
            names.add(alias)
    return names


# --- Raw source rows, keyed by their real per-connector column names (from the audit).
# Each connector maps onto the same canonical ColumnRecord without loss.
RAW_COLUMN_ROWS: dict[str, dict] = {
    "bigquery": {
        "table_catalog": "proj",
        "table_schema": "ds",
        "table_name": "orders",
        "column_name": "customer_id",
        "data_type": "INT64",
        "is_nullable": "YES",
        "is_primary_key": False,
        "is_foreign_key": True,
        "description": "fk to customers",
    },
    "dataplex": {
        "project_id": "proj",
        "dataset_id": "ds",
        "table_id": "orders",
        "column_name": "customer_id",
        "column_data_type": "INTEGER",
        "column_mode": "NULLABLE",
        "column_description": "fk to customers",
    },
    "rdbms_base": {  # snowflake / databricks share this frame
        "table_catalog": "proj",
        "table_schema": "ds",
        "table_name": "orders",
        "column_name": "customer_id",
        "data_type": "NUMBER",
        "is_nullable": True,
        "is_primary_key": False,
        "is_foreign_key": True,
        "description": "fk to customers",
    },
    "jdbc": {
        "database_name": "proj",
        "schema_name": "ds",
        "table_name": "orders",
        "column_name": "customer_id",
        "type": "INTEGER",
        "nullable": True,
        "is_primary_key": False,
        "is_foreign_key": True,
        "description": "fk to customers",
    },
    "unity_catalog": {
        "catalog_name": "proj",
        "schema_name": "ds",
        "table_name": "orders",
        "column_name": "customer_id",
        "column_type": "int",
        "nullable": False,
        "comment": "fk to customers",
    },
    "csv": {  # shipped CSV column_info.csv carries the full natural-key path (see README Connector notes)
        "database_name": "proj",
        "schema_name": "ds",
        "table_name": "orders",
        "column_name": "customer_id",
        "data_type": "INTEGER",
        "is_nullable": "NO",
        "is_primary_key": True,
        "is_foreign_key": False,
        "description": "fk to customers",
    },
}


class TestNoGraphIdentity:
    """D6: source-derived fields only — no graph IDs, no embeddings."""

    @pytest.mark.parametrize("model", ALL_MODELS)
    def test_no_id_or_embedding_field(self, model: type[BaseModel]) -> None:
        assert "id" not in model.model_fields
        assert "embedding" not in model.model_fields

    @pytest.mark.parametrize("model", ALL_MODELS)
    def test_no_field_looks_like_a_graph_id(self, model: type[BaseModel]) -> None:
        # Natural-key names end in "_name"/"_type"; a bare "*_id" would be a graph id.
        assert not any(name.endswith("_id") for name in model.model_fields)


class TestColumnRecordMapsEveryConnector:
    """AC: each connector's raw column field-set maps onto ColumnRecord losslessly."""

    @pytest.mark.parametrize("connector", sorted(RAW_COLUMN_ROWS))
    def test_natural_key_and_type_populated(self, connector: str) -> None:
        record = ColumnRecord.model_validate(RAW_COLUMN_ROWS[connector])
        assert record.database_name == "proj"
        assert record.schema_name == "ds"
        assert record.table_name == "orders"
        assert record.column_name == "customer_id"
        assert record.data_type  # the x4 data-type names all land here
        assert isinstance(record.nullable, bool)

    @pytest.mark.parametrize("connector", sorted(RAW_COLUMN_ROWS))
    def test_no_source_field_is_unmapped(self, connector: str) -> None:
        # Every raw source key is an accepted input of the model (nothing silently dropped).
        accepted = _accepted_input_names(ColumnRecord)
        assert set(RAW_COLUMN_ROWS[connector]) <= accepted

    def test_key_flags_none_when_source_omits_them(self) -> None:
        # Dataplex / Unity expose no key metadata → None (not fabricated False), D10.
        assert ColumnRecord.model_validate(RAW_COLUMN_ROWS["dataplex"]).is_primary_key is None
        assert ColumnRecord.model_validate(RAW_COLUMN_ROWS["unity_catalog"]).is_foreign_key is None

    def test_key_flags_preserved_when_source_provides_them(self) -> None:
        record = ColumnRecord.model_validate(RAW_COLUMN_ROWS["csv"])
        assert record.is_primary_key is True
        assert record.is_foreign_key is False


class TestDataTypeDivergence:
    """The x4 data-type source names all resolve onto ``data_type``."""

    @pytest.mark.parametrize(
        "source_name", ["data_type", "column_data_type", "type", "column_type"]
    )
    def test_all_four_names_populate_data_type(self, source_name: str) -> None:
        row = {
            "database_name": "d",
            "schema_name": "s",
            "table_name": "t",
            "column_name": "c",
            source_name: "STRING",
        }
        assert ColumnRecord.model_validate(row).data_type == "STRING"


class TestNullabilityDivergenceAndCoercion:
    """The x3 nullability names + value coercion (D7)."""

    @pytest.mark.parametrize("source_name", ["nullable", "is_nullable", "column_mode"])
    def test_all_three_names_populate_nullable(self, source_name: str) -> None:
        row = {
            "database_name": "d",
            "schema_name": "s",
            "table_name": "t",
            "column_name": "c",
            source_name: "NO" if source_name != "column_mode" else "REQUIRED",
        }
        assert ColumnRecord.model_validate(row).nullable is False

    @pytest.mark.parametrize(
        ("raw", "expected"),
        [
            ("YES", True),
            ("yes", True),
            ("NO", False),
            ("no", False),
            ("NULLABLE", True),
            ("REQUIRED", False),
            (True, True),
            (False, False),
        ],
    )
    def test_column_mode_and_yes_no_coerce(self, raw: object, expected: bool) -> None:
        row = {
            "database_name": "d",
            "schema_name": "s",
            "table_name": "t",
            "column_name": "c",
            "nullable": raw,
        }
        assert ColumnRecord.model_validate(row).nullable is expected

    def test_default_true_when_absent(self) -> None:
        row = {"database_name": "d", "schema_name": "s", "table_name": "t", "column_name": "c"}
        assert ColumnRecord.model_validate(row).nullable is True

    def test_unrecognized_token_is_rejected(self) -> None:
        # A source-specific token (e.g. Dataplex "REPEATED") must be pre-folded by the
        # connector; the contract does not silently accept it.
        row = {
            "database_name": "d",
            "schema_name": "s",
            "table_name": "t",
            "column_name": "c",
            "column_mode": "REPEATED",
        }
        with pytest.raises(ValidationError):
            ColumnRecord.model_validate(row)


class TestCoerceNullableUnit:
    """Direct coverage of the coerce_nullable branches."""

    @pytest.mark.parametrize("token", ["NULLABLE", "yes", "Y", "true", "t", "1"])
    def test_true_tokens(self, token: str) -> None:
        assert coerce_nullable(token) is True

    @pytest.mark.parametrize("token", ["REQUIRED", "no", "N", "false", "f", "0"])
    def test_false_tokens(self, token: str) -> None:
        assert coerce_nullable(token) is False

    def test_bool_passthrough(self) -> None:
        assert coerce_nullable(True) is True
        assert coerce_nullable(False) is False

    def test_none_and_nan_default_true(self) -> None:
        assert coerce_nullable(None) is True
        assert coerce_nullable(float("nan")) is True

    def test_unrecognized_passthrough(self) -> None:
        assert coerce_nullable("REPEATED") == "REPEATED"
        assert coerce_nullable(0) == 0


class TestContainerDivergence:
    """The x4 container names resolve onto ``database_name`` across frames."""

    @pytest.mark.parametrize(
        "source_name", ["database_name", "project_id", "table_catalog", "catalog_name"]
    )
    def test_container_names_map(self, source_name: str) -> None:
        record = ColumnRecord.model_validate(
            {source_name: "proj", "schema_name": "s", "table_name": "t", "column_name": "c"}
        )
        assert record.database_name == "proj"

    @pytest.mark.parametrize("source_name", ["database", "catalog"])
    def test_database_frame_names_map(self, source_name: str) -> None:
        # Snowflake ("database") / Databricks ("catalog") database-frame names.
        assert DatabaseRecord.model_validate({source_name: "db"}).database_name == "db"


class TestDatabaseSchemaTableMapping:
    """Database / Schema / Table records absorb each connector's raw rows."""

    def test_database_platform_service_uppercased(self) -> None:
        record = DatabaseRecord.model_validate(
            {"project_id": "proj", "platform": "gcp", "service": "bigquery"}
        )
        assert record.database_name == "proj"
        assert record.platform == "GCP"
        assert record.service == "BIGQUERY"

    def test_database_description_from_comment(self) -> None:
        assert (
            DatabaseRecord.model_validate({"catalog_name": "c", "comment": "x"}).description == "x"
        )

    def test_schema_dataset_id_and_description(self) -> None:
        record = SchemaRecord.model_validate(
            {"project_id": "proj", "dataset_id": "ds", "description": "d"}
        )
        assert record.schema_name == "ds"
        assert record.description == "d"

    def test_table_identity_and_display_name_split(self) -> None:
        # Dataplex: identity is table_id, human label is table_display_name.
        record = TableRecord.model_validate(
            {
                "project_id": "proj",
                "dataset_id": "ds",
                "table_id": "t_1234",
                "table_display_name": "Orders",
                "table_description": "the orders table",
            }
        )
        assert record.table_name == "t_1234"
        assert record.display_name == "Orders"
        assert record.description == "the orders table"

    def test_table_name_wins_over_table_id_when_both_present(self) -> None:
        # CSV rows can carry both a real table_name and a precomputed table_id.
        record = TableRecord.model_validate(
            {
                "database_name": "d",
                "schema_name": "s",
                "table_name": "orders",
                "table_id": "ignored",
            }
        )
        assert record.table_name == "orders"


class TestForeignKeyRecord:
    """All three FK-frame shapes converge on one canonical 8-part key."""

    @pytest.mark.parametrize(
        "raw",
        [
            pytest.param(
                {
                    "table_catalog": "p",
                    "table_schema": "s",
                    "table_name": "orders",
                    "column_name": "customer_id",
                    "referenced_catalog": "p",
                    "referenced_schema": "s",
                    "referenced_table": "customers",
                    "referenced_column": "id",
                },
                id="rdbms_base",
            ),
            pytest.param(
                {
                    "constraint_catalog": "p",
                    "constraint_schema": "s",
                    "table_name": "orders",
                    "column_name": "customer_id",
                    "referenced_table": "customers",
                    "referenced_column": "id",
                },
                id="bigquery",
            ),
            pytest.param(
                {
                    "database_name": "p",
                    "source_schema_name": "s",
                    "source_table_name": "orders",
                    "source_column_name": "customer_id",
                    "target_schema_name": "s",
                    "target_table_name": "customers",
                    "target_column_name": "id",
                },
                id="jdbc",
            ),
        ],
    )
    def test_source_and_target_resolve(self, raw: dict) -> None:
        record = ForeignKeyRecord.model_validate(raw)
        assert (record.source_table_name, record.source_column_name) == ("orders", "customer_id")
        assert (record.target_table_name, record.target_column_name) == ("customers", "id")
        assert record.source_database_name == "p"
        assert record.target_database_name == "p"

    def test_criteria_defaults_none_and_coerces_nan(self) -> None:
        base = {
            "source_database_name": "p",
            "source_schema_name": "s",
            "source_table_name": "o",
            "source_column_name": "cid",
            "target_database_name": "p",
            "target_schema_name": "s",
            "target_table_name": "c",
            "target_column_name": "id",
        }
        assert ForeignKeyRecord.model_validate(base).criteria is None
        assert ForeignKeyRecord.model_validate({**base, "criteria": float("nan")}).criteria is None


class TestFieldSemantics:
    """Required keys, defaults, and NaN scrubbing."""

    def test_required_natural_keys_raise_when_missing(self) -> None:
        with pytest.raises(ValidationError):
            ColumnRecord.model_validate({"schema_name": "s", "table_name": "t", "column_name": "c"})
        with pytest.raises(ValidationError):
            DatabaseRecord.model_validate({})

    def test_pk_fk_default_none(self) -> None:
        record = ColumnRecord.model_validate(
            {"database_name": "d", "schema_name": "s", "table_name": "t", "column_name": "c"}
        )
        assert record.is_primary_key is None
        assert record.is_foreign_key is None

    def test_nan_scrubbed_to_none(self) -> None:
        record = ColumnRecord.model_validate(
            {
                "database_name": "d",
                "schema_name": "s",
                "table_name": "t",
                "column_name": "c",
                "data_type": float("nan"),
                "description": float("nan"),
            }
        )
        assert record.data_type is None
        assert record.description is None


class TestNormalizedStructuralSchema:
    """The bundle: sparse by default, holds records."""

    def test_defaults_to_empty_tables(self) -> None:
        bundle = NormalizedStructuralSchema()
        assert bundle.databases == []
        assert bundle.schemas == []
        assert bundle.tables == []
        assert bundle.columns == []
        assert bundle.foreign_keys == []

    def test_holds_records(self) -> None:
        bundle = NormalizedStructuralSchema(
            databases=[DatabaseRecord(database_name="proj")],
            columns=[ColumnRecord.model_validate(RAW_COLUMN_ROWS["bigquery"])],
        )
        assert bundle.databases[0].database_name == "proj"
        assert bundle.columns[0].column_name == "customer_id"
