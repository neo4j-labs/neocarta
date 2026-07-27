"""Contract-level tests for the optional-facet models.

Proves each facet is independently omittable, that every facet a current connector
produces is expressible from its *raw* audited column names, that the attach grain
follows from key-path depth rather than a graph label, and that the coercion
choices (D7/D10) hold. The connector flip is S4; here we prove the contract only.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest
from pydantic import AliasChoices, BaseModel, ValidationError

import neocarta
from neocarta.data_model._validators import (
    coerce_key_segment_or_none,
    coerce_str_or_none,
    coerce_str_required,
)
from neocarta.etl.metadata_normalizer import normalized_schema
from neocarta.etl.metadata_normalizer.normalized_schema import (
    BusinessTermAssignmentRecord,
    BusinessTermRecord,
    CategoryRecord,
    ColumnRecord,
    GlossaryRecord,
    GovernanceTagKeyRecord,
    GovernanceTagValueRecord,
    LineageRecord,
    NormalizedStructuralSchema,
    ValueRecord,
)

FACET_MODELS = [
    ValueRecord,
    GlossaryRecord,
    CategoryRecord,
    BusinessTermRecord,
    BusinessTermAssignmentRecord,
    GovernanceTagKeyRecord,
    GovernanceTagValueRecord,
    LineageRecord,
]

# The source-derived-only rule is a property of the whole vocabulary, not just the
# facet half, so its guard walks everything the package exports — which also keeps
# it correct as records are added.
CONTRACT_MODELS = [
    obj
    for obj in (getattr(normalized_schema, name) for name in normalized_schema.__all__)
    if isinstance(obj, type) and issubclass(obj, BaseModel)
]

# Every facet table on the bundle, so "independently omittable" is checked per facet
# rather than asserted once. `foreign_keys` is the references facet, landed by S1.1.
FACET_TABLES = [
    "values",
    "glossaries",
    "categories",
    "business_terms",
    "business_term_assignments",
    "governance_tag_keys",
    "governance_tag_values",
    "lineage",
    "foreign_keys",
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

# The sampled-values frames (`_VALUE_COLUMNS`) are per-table and carry no container
# path: it lives on the extractor call, which already passes it to the id builder.
# The connector projects it, as the "rdbms_sampling_frame" row shows.
RAW_VALUE_ROWS: dict[str, dict] = {
    "csv": {  # datasets/csv/value_info.csv header, verbatim
        "database_name": "Demo E-commerce",
        "schema_name": "demo_ecommerce",
        "table_name": "products",
        "column_name": "category",
        "value": "Electronics",
    },
    "rdbms_sampling_frame": {  # bigquery / databricks / snowflake share this frame
        "table_catalog": "Demo E-commerce",
        "table_schema": "demo_ecommerce",
        "table_name": "products",
        "column_name": "category",
        "unique_value": "Electronics",
    },
}

# The two pre-computed graph ids the sampling frame also carries. They are private
# extractor-cache artifacts (D5), so the contract must not accept them.
SAMPLING_FRAME_GRAPH_IDS = ("column_id", "value_id")

RAW_GLOSSARY_ROWS: dict[str, dict] = {
    "csv": {  # datasets/csv/glossary_info.csv header, verbatim
        "glossary_name": "ecommerce_glossary",
        "name": "E-commerce Business Glossary",
        "description": "Standard business terms and metrics for e-commerce analytics",
    },
    "dataplex": {  # projected: identity = the slug, label = the raw glossary_name column
        "glossary_name": "ecommerce-glossary",
        "display_name": "E-commerce Business Glossary",
        "glossary_resource_path": "projects/p/locations/us/glossaries/ecommerce-glossary",
    },
}

RAW_CATEGORY_ROWS: dict[str, dict] = {
    "csv": {  # datasets/csv/category_info.csv header, verbatim
        "glossary_name": "ecommerce_glossary",
        "category_name": "revenue_metrics",
        "name": "Revenue Metrics",
        "description": "Key revenue and financial metrics",
    },
    "dataplex": {  # projected: category_name = parse_category_slug(category_id)
        "glossary_name": "ecommerce-glossary",
        "category_name": "entity-identifiers",
        "resource_path": (
            "projects/p/locations/us/glossaries/ecommerce-glossary/categories/entity-identifiers"
        ),
    },
}

RAW_BUSINESS_TERM_ROWS: dict[str, dict] = {
    "csv": {  # datasets/csv/business_term_info.csv header, verbatim
        "glossary_name": "ecommerce_glossary",
        "category_name": "revenue_metrics",
        "term_name": "Gross Merchandise Value",
        "description": "Total sales value of merchandise sold through the platform",
    },
    "dataplex": {  # projected: term_name = parse_business_term_slug(term_id);
        # the raw term_name column is the *label*, so it becomes display_name.
        "glossary_name": "ecommerce-glossary",
        "category_name": "entity-identifiers",
        "term_name": "order-item-id",
        "display_name": "Order Item ID",
        "term_description": "Identifies one line of an order",
        "resource_path": (
            "projects/p/locations/us/glossaries/ecommerce-glossary/terms/order-item-id"
        ),
    },
    "osi": {  # synthetic terms from ai_context.synonyms; no label, no container node
        "glossary_name": "osi",
        "category_name": "synonyms",
        "term_name": "revenue",
    },
}

RAW_TERM_ASSIGNMENT_ROWS: dict[str, dict] = {
    "csv_column": {  # datasets/csv/column_term_info.csv header, verbatim
        "database_name": "Demo E-commerce",
        "schema_name": "demo_ecommerce",
        "table_name": "orders",
        "column_name": "total_amount",
        "glossary_name": "ecommerce_glossary",
        "category_name": "revenue_metrics",
        "term_name": "Gross Merchandise Value",
    },
    "csv_table": {  # datasets/csv/table_term_info.csv — the same, minus column_name
        "database_name": "Demo E-commerce",
        "schema_name": "demo_ecommerce",
        "table_name": "orders",
        "glossary_name": "ecommerce_glossary",
        "category_name": "revenue_metrics",
        "term_name": "Average Order Value",
    },
    "dataplex_column": {  # projected from the segments the entry-link parser already holds
        "project_id": "proj",
        "dataset_id": "demo_ecommerce",
        "table_id": "orders",
        "column_name": "total_amount",
        "glossary_name": "ecommerce-glossary",
        "category_name": "entity-identifiers",
        "term_name": "order-item-id",
    },
}

# The pre-resolved graph ids the Dataplex entry-link frame carries instead of segments.
ENTRY_LINK_GRAPH_IDS = ("entity_id", "term_id", "business_term_id")

RAW_GOVERNANCE_KEY_ROWS: dict[str, dict] = {
    "databricks": {  # databricks/tags/extract.py _KEY_COLS, verbatim
        "source": "aws:us-west-2:abc-123",
        "tag_key": "sensitivity",
        "tag_description": "Data sensitivity classification",
    },
}

RAW_GOVERNANCE_VALUE_ROWS: dict[str, dict] = {
    "databricks": {  # databricks/tags/extract.py _VALUE_COLS, verbatim
        "source": "aws:us-west-2:abc-123",
        "tag_key": "sensitivity",
        "value_name": "pii",
    },
}

RAW_LINEAGE_ROW = {  # no producer today; the shape a CTAS would yield
    "source_database_name": "proj",
    "source_schema_name": "raw",
    "source_table_name": "orders",
    "target_database_name": "proj",
    "target_schema_name": "mart",
    "target_table_name": "daily_revenue",
}

RAW_FOREIGN_KEY_ROW = {  # datasets/csv/column_references_info.csv header, verbatim
    "source_database_name": "Demo E-commerce",
    "source_schema_name": "demo_ecommerce",
    "source_table_name": "orders",
    "source_column_name": "customer_id",
    "target_database_name": "Demo E-commerce",
    "target_schema_name": "demo_ecommerce",
    "target_table_name": "customers",
    "target_column_name": "customer_id",
    "criteria": "orders.customer_id = customers.customer_id",
}

# One real row per facet table, so per-facet omittability is proven with validated
# data rather than a sentinel.
ONE_ROW_PER_FACET: dict[str, dict] = {
    "values": RAW_VALUE_ROWS["csv"],
    "glossaries": RAW_GLOSSARY_ROWS["csv"],
    "categories": RAW_CATEGORY_ROWS["csv"],
    "business_terms": RAW_BUSINESS_TERM_ROWS["csv"],
    "business_term_assignments": RAW_TERM_ASSIGNMENT_ROWS["csv_column"],
    "governance_tag_keys": RAW_GOVERNANCE_KEY_ROWS["databricks"],
    "governance_tag_values": RAW_GOVERNANCE_VALUE_ROWS["databricks"],
    "lineage": RAW_LINEAGE_ROW,
    "foreign_keys": RAW_FOREIGN_KEY_ROW,
}


class TestFacetsAreIndependentlyOmittable:
    """AC: each facet is omittable, and a core-only connector validates."""

    def test_structural_core_only_validates(self) -> None:
        schema = NormalizedStructuralSchema(
            columns=[
                ColumnRecord.model_validate(
                    {
                        "database_name": "proj",
                        "schema_name": "ds",
                        "table_name": "orders",
                        "column_name": "customer_id",
                    }
                )
            ]
        )
        assert schema.columns
        assert all(getattr(schema, table) == [] for table in FACET_TABLES)

    def test_empty_bundle_defaults_every_facet_table(self) -> None:
        schema = NormalizedStructuralSchema()
        assert all(getattr(schema, table) == [] for table in FACET_TABLES)

    @pytest.mark.parametrize("table", FACET_TABLES)
    def test_each_facet_table_can_be_the_only_one_populated(self, table: str) -> None:
        # Each facet is emitted on its own, with a real validated row, and nothing
        # else is required alongside it.
        schema = NormalizedStructuralSchema.model_validate({table: [ONE_ROW_PER_FACET[table]]})
        others = [other for other in FACET_TABLES if other != table]
        assert len(getattr(schema, table)) == 1
        assert all(getattr(schema, other) == [] for other in others)

    def test_facets_are_omitted_independently_of_each_other(self) -> None:
        schema = NormalizedStructuralSchema(
            values=[ValueRecord.model_validate(RAW_VALUE_ROWS["csv"])],
            governance_tag_keys=[
                GovernanceTagKeyRecord.model_validate(RAW_GOVERNANCE_KEY_ROWS["databricks"])
            ],
        )
        assert schema.values
        assert schema.governance_tag_keys
        assert schema.glossaries == []
        assert schema.lineage == []


class TestEverySynonymHasARealProducer:
    """Source-derived only: a synonym must be a name some connector actually emits.

    Covers every exported record, core and facet — the vocabulary is shared.
    """

    def test_no_invented_aliases(self) -> None:
        # The canonical token is the public field name and needs no producer; every
        # *other* alias asserts "some source spells it this way", so it must be
        # findable in the connector/dataset tree. Guards against aliases added from
        # plausibility (`glossary_description`, `category_resource_path`, …) rather
        # than from the audit.
        repo_root = Path(neocarta.__file__).parents[1]
        corpus_roots = [repo_root / "neocarta" / "connectors", repo_root / "datasets"]
        if not all(root.is_dir() for root in corpus_roots):
            pytest.skip("connector/dataset sources not available (installed distribution)")
        blob = "\n".join(
            path.read_text(errors="ignore")
            for root in corpus_roots
            for path in root.rglob("*")
            if path.is_file() and path.suffix in {".py", ".csv"}
        )
        orphans = [
            f"{model.__name__}.{field_name} <- {synonym!r}"
            for model in CONTRACT_MODELS
            for field_name, info in model.model_fields.items()
            if isinstance(info.validation_alias, AliasChoices)
            for synonym in [c for c in info.validation_alias.choices if isinstance(c, str)][1:]
            if not re.search(rf"\b{re.escape(synonym)}\b", blob)
        ]
        assert orphans == []


class TestEveryTableIsFlat:
    """D14: every table — core and facet — is a flat Graph Spec tabular ``source``."""

    @pytest.mark.parametrize(
        "model", [m for m in CONTRACT_MODELS if m is not NormalizedStructuralSchema]
    )
    def test_every_field_is_a_scalar(self, model: type[BaseModel]) -> None:
        # A Graph Spec `source` is a table of columns, so a nested model or a
        # list-valued field would have no column to land in. Booleans and ints are
        # columns; only containers and sub-models are not.
        scalars = {str, bool, int, float}
        allowed = scalars | {t | None for t in scalars}
        offenders = [
            f"{name}: {info.annotation}"
            for name, info in model.model_fields.items()
            if info.annotation not in allowed
        ]
        assert offenders == []


class TestDerivedFacetEdgesAreNotModelled:
    """Negative controls: an edge derivable from a key path is not a table."""

    @pytest.mark.parametrize(
        ("child", "parent", "parent_key"),
        [
            pytest.param(
                ValueRecord,
                ColumnRecord,
                ("database_name", "schema_name", "table_name", "column_name"),
                id="HAS_VALUE",
            ),
            pytest.param(CategoryRecord, GlossaryRecord, ("glossary_name",), id="HAS_CATEGORY"),
            pytest.param(
                BusinessTermRecord,
                CategoryRecord,
                ("glossary_name", "category_name"),
                id="HAS_BUSINESS_TERM",
            ),
            pytest.param(
                GovernanceTagValueRecord,
                GovernanceTagKeyRecord,
                ("tag_namespace", "tag_key"),
                id="HAS_VALUE_OPTION",
            ),
        ],
    )
    def test_child_key_path_extends_its_parents(
        self,
        child: type[BaseModel],
        parent: type[BaseModel],
        parent_key: tuple[str, ...],
    ) -> None:
        # The edge is derivable precisely because the child carries every key
        # segment of the parent, so it needs no table of its own.
        assert set(parent_key) <= set(parent.model_fields)
        assert set(parent_key) <= set(child.model_fields)
        assert all(child.model_fields[segment].is_required() for segment in parent_key)


class TestFacetRecordsRejectPreResolvedGraphIds:
    """D6: the ids connectors pre-compute today are not accepted inputs."""

    @pytest.mark.parametrize("graph_id", SAMPLING_FRAME_GRAPH_IDS)
    def test_sampling_frame_ids_are_not_accepted(self, graph_id: str) -> None:
        assert graph_id not in _accepted_input_names(ValueRecord)

    @pytest.mark.parametrize("graph_id", ENTRY_LINK_GRAPH_IDS)
    def test_entry_link_ids_are_not_accepted(self, graph_id: str) -> None:
        assert graph_id not in _accepted_input_names(BusinessTermAssignmentRecord)

    @pytest.mark.parametrize("identity_column", ["glossary_id", "category_id", "term_id"])
    def test_dataplex_identity_columns_are_not_aliased(self, identity_column: str) -> None:
        # AliasChoices resolves to the first alias *present*, and a raw Dataplex row
        # carries both the identity slug and the display label — so aliasing these
        # would silently bind the label as identity. The connector pre-folds instead.
        for model in (GlossaryRecord, CategoryRecord, BusinessTermRecord):
            assert identity_column not in _accepted_input_names(model)


class TestValueRecordMapsEveryProducer:
    """AC: the values facet is expressible from every producer's raw frame."""

    @pytest.mark.parametrize("producer", sorted(RAW_VALUE_ROWS))
    def test_natural_key_and_value_populated(self, producer: str) -> None:
        record = ValueRecord.model_validate(RAW_VALUE_ROWS[producer])
        assert record.database_name == "Demo E-commerce"
        assert record.schema_name == "demo_ecommerce"
        assert record.table_name == "products"
        assert record.column_name == "category"
        assert record.value == "Electronics"

    @pytest.mark.parametrize("producer", sorted(RAW_VALUE_ROWS))
    def test_no_source_field_is_unmapped(self, producer: str) -> None:
        assert set(RAW_VALUE_ROWS[producer]) <= _accepted_input_names(ValueRecord)

    def test_sampling_frame_alone_cannot_populate_the_key_path(self) -> None:
        # The frame carries only column_name/unique_value; the container path is
        # extractor state the connector must project.
        with pytest.raises(ValidationError):
            ValueRecord.model_validate({"column_name": "category", "unique_value": "Electronics"})


class TestValueIsNeverFabricated:
    """D10: a value is a key segment, so a missing cell is rejected, not coerced."""

    @pytest.mark.parametrize("missing", [None, float("nan")])
    def test_missing_value_is_rejected(self, missing: object) -> None:
        with pytest.raises(ValidationError):
            ValueRecord.model_validate({**RAW_VALUE_ROWS["csv"], "value": missing})

    def test_numeric_value_is_cast_to_str(self) -> None:
        # A dtype-inferred frame can hand a numeric column here; today's producers
        # stringify upstream, and this keeps that behaviour rather than rejecting.
        record = ValueRecord.model_validate({**RAW_VALUE_ROWS["csv"], "value": 5})
        assert record.value == "5"

    def test_value_is_preserved_verbatim(self) -> None:
        record = ValueRecord.model_validate({**RAW_VALUE_ROWS["csv"], "value": "  High Risk  "})
        assert record.value == "  High Risk  "


class TestGlossaryIdentityDisplaySplit:
    """One record serves CSV names, Dataplex slugs, and OSI synonyms."""

    @pytest.mark.parametrize("producer", sorted(RAW_GLOSSARY_ROWS))
    def test_glossary_row_maps(self, producer: str) -> None:
        record = GlossaryRecord.model_validate(RAW_GLOSSARY_ROWS[producer])
        assert record.glossary_name
        assert record.display_name == "E-commerce Business Glossary"

    @pytest.mark.parametrize("producer", sorted(RAW_CATEGORY_ROWS))
    def test_category_row_maps(self, producer: str) -> None:
        record = CategoryRecord.model_validate(RAW_CATEGORY_ROWS[producer])
        assert record.glossary_name
        assert record.category_name

    @pytest.mark.parametrize("producer", sorted(RAW_BUSINESS_TERM_ROWS))
    def test_business_term_row_maps(self, producer: str) -> None:
        record = BusinessTermRecord.model_validate(RAW_BUSINESS_TERM_ROWS[producer])
        assert record.glossary_name
        assert record.category_name
        assert record.term_name

    @pytest.mark.parametrize(
        ("model", "rows"),
        [
            pytest.param(GlossaryRecord, RAW_GLOSSARY_ROWS, id="glossary"),
            pytest.param(CategoryRecord, RAW_CATEGORY_ROWS, id="category"),
            pytest.param(BusinessTermRecord, RAW_BUSINESS_TERM_ROWS, id="business_term"),
        ],
    )
    def test_no_source_field_is_unmapped(
        self, model: type[BaseModel], rows: dict[str, dict]
    ) -> None:
        accepted = _accepted_input_names(model)
        assert all(set(row) <= accepted for row in rows.values())

    def test_csv_name_column_becomes_the_display_label(self) -> None:
        record = CategoryRecord.model_validate(RAW_CATEGORY_ROWS["csv"])
        assert record.category_name == "revenue_metrics"
        assert record.display_name == "Revenue Metrics"

    def test_resource_path_is_carried_when_the_source_has_one(self) -> None:
        assert (
            GlossaryRecord.model_validate(RAW_GLOSSARY_ROWS["dataplex"]).resource_path
            == "projects/p/locations/us/glossaries/ecommerce-glossary"
        )
        assert GlossaryRecord.model_validate(RAW_GLOSSARY_ROWS["csv"]).resource_path is None

    def test_term_description_alias_resolves(self) -> None:
        record = BusinessTermRecord.model_validate(RAW_BUSINESS_TERM_ROWS["dataplex"])
        assert record.description == "Identifies one line of an order"

    def test_downstream_label_falls_back_to_the_identity_segment(self) -> None:
        # Business terms dedupe by name across connectors, so `display_name or
        # term_name` must reproduce that merge key for every producer.
        for row in RAW_BUSINESS_TERM_ROWS.values():
            record = BusinessTermRecord.model_validate(row)
            assert record.display_name or record.term_name

    def test_nan_scrubbed_to_none(self) -> None:
        record = GlossaryRecord.model_validate(
            {"glossary_name": "g", "description": float("nan"), "name": float("nan")}
        )
        assert record.description is None
        assert record.display_name is None

    @pytest.mark.parametrize(
        ("model", "row"),
        [
            pytest.param(GlossaryRecord, {}, id="glossary_without_name"),
            pytest.param(CategoryRecord, {"glossary_name": "g"}, id="category_without_name"),
            pytest.param(
                BusinessTermRecord,
                {"glossary_name": "g", "category_name": "c"},
                id="term_without_name",
            ),
        ],
    )
    def test_identity_segments_are_required(self, model: type[BaseModel], row: dict) -> None:
        with pytest.raises(ValidationError):
            model.model_validate(row)


class TestBusinessTermAssignmentGrain:
    """The attach grain is key-path depth, not a graph label."""

    @pytest.mark.parametrize("producer", sorted(RAW_TERM_ASSIGNMENT_ROWS))
    def test_every_producer_row_resolves(self, producer: str) -> None:
        record = BusinessTermAssignmentRecord.model_validate(RAW_TERM_ASSIGNMENT_ROWS[producer])
        assert record.table_name == "orders"
        assert record.term_name

    @pytest.mark.parametrize("producer", sorted(RAW_TERM_ASSIGNMENT_ROWS))
    def test_no_source_field_is_unmapped(self, producer: str) -> None:
        accepted = _accepted_input_names(BusinessTermAssignmentRecord)
        assert set(RAW_TERM_ASSIGNMENT_ROWS[producer]) <= accepted

    def test_column_grain_when_column_name_present(self) -> None:
        record = BusinessTermAssignmentRecord.model_validate(RAW_TERM_ASSIGNMENT_ROWS["csv_column"])
        assert record.column_name == "total_amount"

    def test_table_grain_when_column_name_absent(self) -> None:
        record = BusinessTermAssignmentRecord.model_validate(RAW_TERM_ASSIGNMENT_ROWS["csv_table"])
        assert record.column_name is None

    @pytest.mark.parametrize("blank", [float("nan"), None, "", "   ", "\t"])
    def test_blank_column_name_is_unambiguously_table_grain(self, blank: object) -> None:
        # Today a blank cell yields a dangling "...nan" column id. Folding every
        # blank form to None makes the row an honest table-grain tag *and* keeps
        # truthiness and identity from disagreeing about the grain: an empty string
        # is falsy but is not None, so a consumer checking either one would
        # otherwise classify the same row differently.
        record = BusinessTermAssignmentRecord.model_validate(
            {**RAW_TERM_ASSIGNMENT_ROWS["csv_column"], "column_name": blank}
        )
        assert record.column_name is None
        assert not record.column_name

    def test_a_padded_column_name_is_preserved_verbatim(self) -> None:
        # Only *blank* folds to None; a real name keeps its exact spelling.
        record = BusinessTermAssignmentRecord.model_validate(
            {**RAW_TERM_ASSIGNMENT_ROWS["csv_column"], "column_name": " total_amount "}
        )
        assert record.column_name == " total_amount "

    def test_column_grain_still_requires_the_table_path(self) -> None:
        # Prefix-closure is structural: column_name is the only optional segment,
        # so a gapped key path is unrepresentable rather than merely rejected.
        row = dict(RAW_TERM_ASSIGNMENT_ROWS["csv_column"])
        del row["table_name"]
        with pytest.raises(ValidationError):
            BusinessTermAssignmentRecord.model_validate(row)

    def test_only_the_trailing_segment_is_optional(self) -> None:
        required = {
            name
            for name, info in BusinessTermAssignmentRecord.model_fields.items()
            if info.is_required()
        }
        assert required == {
            "database_name",
            "schema_name",
            "table_name",
            "glossary_name",
            "category_name",
            "term_name",
        }


class TestGovernanceDefinitionLayerOnly:
    """The definition layer is the only governance layer a connector reads."""

    @pytest.mark.parametrize("producer", sorted(RAW_GOVERNANCE_KEY_ROWS))
    def test_key_row_maps(self, producer: str) -> None:
        record = GovernanceTagKeyRecord.model_validate(RAW_GOVERNANCE_KEY_ROWS[producer])
        assert record.tag_namespace == "aws:us-west-2:abc-123"
        assert record.tag_key == "sensitivity"
        assert record.description == "Data sensitivity classification"

    @pytest.mark.parametrize("producer", sorted(RAW_GOVERNANCE_VALUE_ROWS))
    def test_value_row_maps(self, producer: str) -> None:
        record = GovernanceTagValueRecord.model_validate(RAW_GOVERNANCE_VALUE_ROWS[producer])
        assert record.tag_namespace == "aws:us-west-2:abc-123"
        assert record.tag_key == "sensitivity"
        assert record.tag_value == "pii"

    @pytest.mark.parametrize(
        ("model", "rows"),
        [
            pytest.param(GovernanceTagKeyRecord, RAW_GOVERNANCE_KEY_ROWS, id="key"),
            pytest.param(GovernanceTagValueRecord, RAW_GOVERNANCE_VALUE_ROWS, id="value"),
        ],
    )
    def test_no_source_field_is_unmapped(
        self, model: type[BaseModel], rows: dict[str, dict]
    ) -> None:
        accepted = _accepted_input_names(model)
        assert all(set(row) <= accepted for row in rows.values())

    def test_namespace_is_required_on_both_definition_records(self) -> None:
        for model in (GovernanceTagKeyRecord, GovernanceTagValueRecord):
            assert model.model_fields["tag_namespace"].is_required()

    def test_source_column_is_absorbed_not_named(self) -> None:
        # `source_*` already means "the referencing side of an edge" on
        # ForeignKeyRecord, so the canonical token is tag_namespace.
        assert "source" not in GovernanceTagKeyRecord.model_fields
        assert "source" in _accepted_input_names(GovernanceTagKeyRecord)

    @pytest.mark.parametrize("raw", ["High Risk", "high-risk", "high_risk", "  pii  "])
    def test_tag_value_is_carried_verbatim(self, raw: str) -> None:
        # Downstream identity content-hashes the raw value so these stay distinct.
        record = GovernanceTagValueRecord.model_validate(
            {**RAW_GOVERNANCE_VALUE_ROWS["databricks"], "value_name": raw}
        )
        assert record.tag_value == raw

    @pytest.mark.parametrize("missing", [None, float("nan")])
    def test_value_less_key_yields_no_value_row(self, missing: object) -> None:
        # A governed key with zero allowed values: the connector drops the row.
        with pytest.raises(ValidationError):
            GovernanceTagValueRecord.model_validate(
                {**RAW_GOVERNANCE_VALUE_ROWS["databricks"], "value_name": missing}
            )


class TestLineageRecord:
    """A two-sided, un-reified derivation row; no producer populates it yet."""

    def test_column_grain_on_both_sides(self) -> None:
        record = LineageRecord.model_validate(
            {
                "source_database_name": "proj",
                "source_schema_name": "raw",
                "source_table_name": "orders",
                "source_column_name": "total_amount",
                "target_database_name": "proj",
                "target_schema_name": "mart",
                "target_table_name": "daily_revenue",
                "target_column_name": "revenue",
            }
        )
        assert record.source_column_name == "total_amount"
        assert record.target_column_name == "revenue"

    def test_table_grain_on_both_sides(self) -> None:
        # What a CREATE TABLE AS SELECT yields before column-level resolution.
        record = LineageRecord.model_validate(
            {
                "source_database_name": "proj",
                "source_schema_name": "raw",
                "source_table_name": "orders",
                "target_database_name": "proj",
                "target_schema_name": "mart",
                "target_table_name": "daily_revenue",
            }
        )
        assert record.source_column_name is None
        assert record.target_column_name is None

    def test_mixed_grain_is_allowed(self) -> None:
        record = LineageRecord.model_validate(
            {
                "source_database_name": "proj",
                "source_schema_name": "raw",
                "source_table_name": "orders",
                "source_column_name": "total_amount",
                "target_database_name": "proj",
                "target_schema_name": "mart",
                "target_table_name": "daily_revenue",
            }
        )
        assert record.source_column_name == "total_amount"
        assert record.target_column_name is None

    @pytest.mark.parametrize("side", ["source", "target"])
    def test_table_path_is_required_on_both_sides(self, side: str) -> None:
        required = {name for name, info in LineageRecord.model_fields.items() if info.is_required()}
        assert f"{side}_database_name" in required
        assert f"{side}_schema_name" in required
        assert f"{side}_table_name" in required
        assert f"{side}_column_name" not in required

    @pytest.mark.parametrize("side", ["source", "target"])
    @pytest.mark.parametrize("blank", [float("nan"), None, "", "   "])
    def test_blank_column_segment_is_unambiguously_table_grain(
        self, side: str, blank: object
    ) -> None:
        record = LineageRecord.model_validate({**RAW_LINEAGE_ROW, f"{side}_column_name": blank})
        assert getattr(record, f"{side}_column_name") is None

    def test_no_reification_fields(self) -> None:
        # Minting a Transform node and choosing its key is an identity decision,
        # which the ontology makes downstream of this contract (D6).
        assert not {"transform_name", "transform_type", "transform_expression"} & set(
            LineageRecord.model_fields
        )


class TestCoerceKeySegmentOrNoneUnit:
    """Direct coverage of the coerce_key_segment_or_none branches."""

    @pytest.mark.parametrize("blank", ["", "   ", "\t\n", None, float("nan")])
    def test_blank_becomes_none(self, blank: object) -> None:
        assert coerce_key_segment_or_none(blank) is None

    @pytest.mark.parametrize("value", ["total_amount", " total_amount ", "0"])
    def test_real_value_is_returned_unchanged(self, value: str) -> None:
        assert coerce_key_segment_or_none(value) == value

    def test_non_str_non_nan_passes_through(self) -> None:
        # Left for Pydantic to coerce or reject, as coerce_str_or_none does.
        assert coerce_key_segment_or_none(5) == 5

    def test_differs_from_coerce_str_or_none_on_empty_string(self) -> None:
        # The whole reason this validator exists: an empty *description* stays "",
        # but an empty *key segment* must become None.
        assert coerce_str_or_none("") == ""
        assert coerce_key_segment_or_none("") is None


class TestCoerceStrRequiredUnit:
    """Direct coverage of the coerce_str_required branches."""

    def test_str_passes_through(self) -> None:
        assert coerce_str_required("Electronics") == "Electronics"

    def test_empty_str_passes_through(self) -> None:
        assert coerce_str_required("") == ""

    @pytest.mark.parametrize(("raw", "expected"), [(5, "5"), (0, "0"), (1.5, "1.5")])
    def test_numeric_is_cast(self, raw: object, expected: str) -> None:
        assert coerce_str_required(raw) == expected

    def test_bool_is_cast(self) -> None:
        assert coerce_str_required(False) == "False"

    def test_none_is_returned_unchanged(self) -> None:
        assert coerce_str_required(None) is None

    def test_nan_is_returned_unchanged(self) -> None:
        result = coerce_str_required(float("nan"))
        assert isinstance(result, float)
