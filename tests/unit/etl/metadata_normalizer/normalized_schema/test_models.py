"""Contract-level tests for the normalized structural-core models.

Proves the standardized vocabulary absorbs every schema connector's *raw* source
field-names without loss, that value coercions (D7) apply, and that the only graph
identity (D6) on any field is the one reserved, opt-in ``explicit_id`` override
S1.4 (#295) added — never a second one, and never on an edge record. The full
connector flip is S4; here we prove the contract only.
"""

from __future__ import annotations

import pytest
from pydantic import BaseModel, ValidationError

from neocarta.data_model._validators import coerce_nullable
from neocarta.etl.metadata_normalizer import normalized_schema
from neocarta.etl.metadata_normalizer.normalized_schema import (
    BusinessTermAssignmentRecord,
    BusinessTermRecord,
    CategoryRecord,
    ColumnRecord,
    DatabaseRecord,
    ForeignKeyRecord,
    GlossaryRecord,
    GovernanceTagKeyRecord,
    GovernanceTagValueRecord,
    LineageRecord,
    NormalizedStructuralSchema,
    SchemaRecord,
    TableRecord,
    ValueRecord,
)
from neocarta.etl.metadata_normalizer.normalized_schema._vocabulary import (
    DATA_TYPE_SYNONYMS,
    DATABASE_NAME_SYNONYMS,
    NULLABLE_SYNONYMS,
)

from . import _accepted_input_names

# Each divergence class below also pins its synonym tuple by full equality. The
# `parametrize` lists are literals, so on their own they would stay green while a new
# synonym staled the x6/x4/x3 counts `docs/refactor/field-vocabulary.md` quotes — which
# is exactly how models.py's "x4 container" went wrong once the tuple grew to six.

ALL_MODELS = [
    DatabaseRecord,
    SchemaRecord,
    TableRecord,
    ColumnRecord,
    ForeignKeyRecord,
    # S1.2 facet records — the D6 identity guards are contract-wide, so they live
    # here once rather than being duplicated in test_facets.py.
    ValueRecord,
    GlossaryRecord,
    CategoryRecord,
    BusinessTermRecord,
    BusinessTermAssignmentRecord,
    GovernanceTagKeyRecord,
    GovernanceTagValueRecord,
    LineageRecord,
    NormalizedStructuralSchema,
]

# The S1.4 (#295) partition of the contract. Only an *entity* record has an identity
# of its own, so only an entity record carries the D6 explicit-ID override; an edge is
# merged on its endpoint pair, and the bundle is a container. `test_the_partition_covers
# _every_exported_model` keeps the three lists exhaustive and disjoint, so a new record
# has to be classified before it can exist.
ENTITY_MODELS = [
    DatabaseRecord,
    SchemaRecord,
    TableRecord,
    ColumnRecord,
    ValueRecord,
    GlossaryRecord,
    CategoryRecord,
    BusinessTermRecord,
    GovernanceTagKeyRecord,
    GovernanceTagValueRecord,
]
EDGE_MODELS = [ForeignKeyRecord, BusinessTermAssignmentRecord, LineageRecord]

EXPLICIT_ID = "explicit_id"

# Ids the generated-id normalizer would rewrite (it lowercases and folds spaces/hyphens to
# underscores), so any accidental coercion of the override shows up as an inequality. The
# first is the real cross-source-alignment case: a Dataplex resource path.
VERBATIM_IDS = [
    "projects/p/locations/us/glossaries/ecommerce-glossary",
    "Custom-ID With Spaces",
    "  padded  ",
    "MixedCase.Id",
]

# A minimal valid row per entity record: every required natural-key segment and nothing
# else, so an override test exercises the field rather than the rest of the vocabulary.
MINIMAL_ENTITY_ROWS: dict[str, dict] = {
    "DatabaseRecord": {"database_name": "d"},
    "SchemaRecord": {"database_name": "d", "schema_name": "s"},
    "TableRecord": {"database_name": "d", "schema_name": "s", "table_name": "t"},
    "ColumnRecord": {
        "database_name": "d",
        "schema_name": "s",
        "table_name": "t",
        "column_name": "c",
    },
    "ValueRecord": {
        "database_name": "d",
        "schema_name": "s",
        "table_name": "t",
        "column_name": "c",
        "value": "v",
    },
    "GlossaryRecord": {"glossary_name": "g"},
    "CategoryRecord": {"glossary_name": "g", "category_name": "cat"},
    "BusinessTermRecord": {"glossary_name": "g", "category_name": "cat", "term_name": "term"},
    "GovernanceTagKeyRecord": {"tag_namespace": "ns", "tag_key": "k"},
    "GovernanceTagValueRecord": {"tag_namespace": "ns", "tag_key": "k", "tag_value": "v"},
}


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
    def test_the_reserved_override_is_the_only_id_field(self, model: type[BaseModel]) -> None:
        # Natural-key names end in "_name"/"_type"; a bare "*_id" would be a graph id.
        # D6 sanctions exactly one — the opt-in explicit-ID override (S1.4) — so the
        # guard is narrowed to that single name rather than lifted: a *second* id field,
        # or the override on a record that should not have one, still fails here.
        assert [name for name in model.model_fields if name.endswith("_id")] in ([], [EXPLICIT_ID])

    @pytest.mark.parametrize("model", ALL_MODELS)
    def test_no_graph_label_discriminator(self, model: type[BaseModel]) -> None:
        # The graph's polymorphic TAGGED_WITH carries source_label + source_id; a
        # facet row instead derives its grain from key-path depth, so naming an
        # ontology label here would re-couple the contract to the ontology (§6).
        assert "source_label" not in model.model_fields

    def test_guard_covers_every_exported_model(self) -> None:
        # A new record cannot be added to the package without these guards seeing it.
        exported = {
            getattr(normalized_schema, name)
            for name in normalized_schema.__all__
            if isinstance(getattr(normalized_schema, name), type)
        }
        assert exported == set(ALL_MODELS)

    def test_the_partition_covers_every_exported_model(self) -> None:
        # Entity / edge / bundle is what decides whether a record may carry the D6
        # override, so the partition has to be exhaustive and disjoint — otherwise a new
        # record could join the package without anyone deciding which side it is on.
        assert set(ENTITY_MODELS) | set(EDGE_MODELS) | {NormalizedStructuralSchema} == set(
            ALL_MODELS
        )
        assert len(ENTITY_MODELS) + len(EDGE_MODELS) + 1 == len(ALL_MODELS)


class TestExplicitIdOverride:
    """D6 (S1.4): the one reserved identity field — opt-in, unaliased, verbatim."""

    @pytest.mark.parametrize("model", ALL_MODELS)
    def test_only_entity_records_carry_the_override(self, model: type[BaseModel]) -> None:
        # Positive and negative in one assertion: an edge record or the bundle growing
        # the field fails here just as loudly as an entity record losing it. An edge is
        # merged on its endpoint pair and has no id of its own, so the field would be
        # permanently unconsumed there.
        assert (EXPLICIT_ID in model.model_fields) is (model in ENTITY_MODELS)

    @pytest.mark.parametrize("model", ENTITY_MODELS)
    def test_override_is_optional_and_defaults_to_none(self, model: type[BaseModel]) -> None:
        # "Identity-agnostic remains the default" — every row a connector emits today
        # validates unchanged and carries no id.
        assert model.model_validate(MINIMAL_ENTITY_ROWS[model.__name__]).explicit_id is None

    @pytest.mark.parametrize("model", ENTITY_MODELS)
    def test_override_is_never_aliased(self, model: type[BaseModel]) -> None:
        # The one field with no AliasChoices. A source "*_id" column is not reliably a
        # graph id — the vocabulary already spends table_id / dataset_id / project_id on
        # *name* concepts — and an override wins over generation, so a wrong binding
        # corrupts the id rather than being rejected. The connector must project.
        assert model.model_fields[EXPLICIT_ID].validation_alias is None

    @pytest.mark.parametrize(
        ("model", "id_column", "source_value"),
        [
            pytest.param(DatabaseRecord, "database_id", "custom-db-id", id="csv_database_id"),
            pytest.param(SchemaRecord, "schema_id", "custom-schema-id", id="csv_schema_id"),
            pytest.param(TableRecord, "table_id", "t_1234", id="dataplex_table_id"),
            pytest.param(ColumnRecord, "column_id", "custom-col-id", id="csv_column_id"),
            pytest.param(ValueRecord, "value_id", "custom-val-id", id="sampling_frame_value_id"),
            # The Dataplex values are the real shapes a live `neocarta-rajvardhan` glossary
            # emits: the glossary/category ids are slugs, and term_id is a full resource path.
            pytest.param(
                GlossaryRecord, "glossary_id", "ecommerce-glossary", id="dataplex_glossary_id"
            ),
            pytest.param(
                CategoryRecord, "category_id", "revenue-metrics", id="dataplex_category_id"
            ),
            pytest.param(
                BusinessTermRecord,
                "term_id",
                "projects/p/locations/us/glossaries/ecommerce-glossary/terms/gross-merchandise-value",
                id="dataplex_term_id",
            ),
        ],
    )
    def test_a_source_id_column_does_not_populate_the_override(
        self, model: type[BaseModel], id_column: str, source_value: str
    ) -> None:
        # Dataplex "*_id" columns are slugs (or resource paths) and CSV's are graph ids, and the
        # contract cannot tell them apart — so it absorbs neither. table_id is still accepted as
        # the Dataplex identity segment for table_name; what must not happen is it arriving as an
        # override, which would win over generation unnormalized.
        row = {**MINIMAL_ENTITY_ROWS[model.__name__], id_column: source_value}
        assert model.model_validate(row).explicit_id is None

    @pytest.mark.parametrize("model", ENTITY_MODELS)
    def test_the_shared_declaration_is_live_on_every_entity_record(
        self, model: type[BaseModel]
    ) -> None:
        # One blank and one verbatim value per record proves the _identity.py factories actually
        # bound here — they return a fresh descriptor per class, so a failure to attach would be
        # silent. The value matrices below then run once, since the declaration is shared.
        row = MINIMAL_ENTITY_ROWS[model.__name__]
        assert model.model_validate({**row, EXPLICIT_ID: "  "}).explicit_id is None
        assert (
            model.model_validate({**row, EXPLICIT_ID: VERBATIM_IDS[0]}).explicit_id
            == (VERBATIM_IDS[0])
        )

    @pytest.mark.parametrize("supplied", VERBATIM_IDS)
    def test_override_is_preserved_verbatim(self, supplied: str) -> None:
        row = {**MINIMAL_ENTITY_ROWS["ColumnRecord"], EXPLICIT_ID: supplied}
        assert ColumnRecord.model_validate(row).explicit_id == supplied

    @pytest.mark.parametrize("blank", ["", " ", "\t", None, float("nan")])
    def test_every_blank_form_folds_to_none(self, blank: object) -> None:
        # A blank cell means "generate this row", not "the id is the empty string": an
        # empty string is falsy but is not None, so leaving it intact would make the
        # resolver return "" and collapse every row of this type onto one empty-id node.
        row = {**MINIMAL_ENTITY_ROWS["ColumnRecord"], EXPLICIT_ID: blank}
        assert ColumnRecord.model_validate(row).explicit_id is None

    @pytest.mark.parametrize("model", EDGE_MODELS)
    def test_no_edge_record_accepts_the_override(self, model: type[BaseModel]) -> None:
        # Not merely absent as a field — not an accepted input name either, so a
        # connector projecting one onto an edge row gets it dropped, not honored.
        assert EXPLICIT_ID not in _accepted_input_names(model)


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

    def test_synonym_set_is_exactly_the_documented_four(self) -> None:
        assert DATA_TYPE_SYNONYMS == ("data_type", "column_data_type", "type", "column_type")


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

    def test_synonym_set_is_exactly_the_documented_three(self) -> None:
        assert NULLABLE_SYNONYMS == ("nullable", "is_nullable", "column_mode")

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
    """The x6 container names resolve onto ``database_name`` across frames.

    x4 appear in a table/column-grain frame; the remaining x2 only in a
    database-grain frame, which is why the two parametrized cases are separate.
    """

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

    def test_synonym_set_is_exactly_the_documented_six(self) -> None:
        # The x4-vs-x2 split above is about which *frames* carry which name, not the tuple.
        assert DATABASE_NAME_SYNONYMS == (
            "database_name",
            "project_id",
            "table_catalog",
            "catalog_name",
            "database",
            "catalog",
        )


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
