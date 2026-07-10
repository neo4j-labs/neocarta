"""Unit tests for the BigQuery INFORMATION_SCHEMA normalization adapter."""

from unittest.mock import Mock

import pandas as pd
import pytest

from neocarta.connectors.bigquery.schema.extract import BigQuerySchemaExtractor
from neocarta.data_model.normalized import (
    ColumnRecord,
    DatabaseRecord,
    InformationSchemaTable,
    ReferenceRecord,
    ValueRecord,
)
from neocarta.normalization import Retriever
from neocarta.normalization.information_schema import (
    BigQueryInformationSchemaRetriever,
    build_bigquery_information_schema_normalizer,
)


@pytest.fixture
def populated_extractor():
    """A BigQuerySchemaExtractor with canned INFORMATION_SCHEMA frames in its cache.

    Mini-dataset ``test_dataset``: ``customers`` (PK ``customer_id``) and
    ``orders`` (PK ``order_id``, FK ``customer_id`` -> ``customers.customer_id``).
    ``orders`` has a NaN description (to exercise NaN -> None), and the references
    frame carries a genuine cross-table FK, a PRIMARY KEY row, and a self-ref FK.
    """
    client = Mock()
    client.project = "test-project-id"
    extractor = BigQuerySchemaExtractor(client=client, dataset_id="test_dataset")

    extractor._cache["database_info"] = pd.DataFrame([{"project_id": "test-project-id"}])
    extractor._cache["schema_info"] = pd.DataFrame(
        [
            {
                "project_id": "test-project-id",
                "dataset_id": "test_dataset",
                "description": "Test dataset",
            }
        ]
    )
    extractor._cache["table_info"] = pd.DataFrame(
        [
            {
                "table_catalog": "test-project-id",
                "table_schema": "test_dataset",
                "table_name": "customers",
                "table_type": "BASE TABLE",
                "creation_time": pd.Timestamp("2024-01-01"),
                "ddl": None,
                "description": "Customer table",
            },
            {
                "table_catalog": "test-project-id",
                "table_schema": "test_dataset",
                "table_name": "orders",
                "table_type": "BASE TABLE",
                "creation_time": pd.NaT,
                "ddl": None,
                "description": float("nan"),
            },
        ]
    )
    extractor._cache["column_info"] = pd.DataFrame(
        [
            {
                "table_catalog": "test-project-id",
                "table_schema": "test_dataset",
                "table_name": "customers",
                "column_name": "customer_id",
                "is_nullable": "NO",
                "data_type": "INT64",
                "description": "Customer ID",
                "constraint_name": "test-project-id.test_dataset.customers.pk$",
                "is_primary_key": True,
                "is_foreign_key": False,
            },
            {
                "table_catalog": "test-project-id",
                "table_schema": "test_dataset",
                "table_name": "customers",
                "column_name": "customer_name",
                "is_nullable": "YES",
                "data_type": "STRING",
                "description": "Customer name",
                "constraint_name": None,
                "is_primary_key": False,
                "is_foreign_key": False,
            },
            {
                "table_catalog": "test-project-id",
                "table_schema": "test_dataset",
                "table_name": "orders",
                "column_name": "order_id",
                "is_nullable": "NO",
                "data_type": "INT64",
                "description": "Order ID",
                "constraint_name": "test-project-id.test_dataset.orders.pk$",
                "is_primary_key": True,
                "is_foreign_key": False,
            },
            {
                "table_catalog": "test-project-id",
                "table_schema": "test_dataset",
                "table_name": "orders",
                "column_name": "customer_id",
                "is_nullable": "NO",
                "data_type": "INT64",
                "description": "Customer reference",
                "constraint_name": "test-project-id.test_dataset.orders.fk_customer",
                "is_primary_key": False,
                "is_foreign_key": True,
            },
        ]
    )
    extractor._cache["column_references_info"] = pd.DataFrame(
        [
            {
                "constraint_catalog": "test-project-id",
                "constraint_schema": "test_dataset",
                "constraint_name": "fk_customer",
                "constraint_type": "FOREIGN KEY",
                "table_name": "orders",
                "column_name": "customer_id",
                "ordinal_position": 1,
                "referenced_table": "customers",
                "referenced_column": "customer_id",
            },
            # A non-FK row that is deliberately NOT a self-reference
            # (referenced_column differs), so only the FOREIGN KEY filter — not the
            # self-ref filter — can exclude it. This independently locks that filter.
            {
                "constraint_catalog": "test-project-id",
                "constraint_schema": "test_dataset",
                "constraint_name": "pk_customers",
                "constraint_type": "PRIMARY KEY",
                "table_name": "customers",
                "column_name": "customer_id",
                "ordinal_position": 1,
                "referenced_table": "customers",
                "referenced_column": "id",
            },
            {
                "constraint_catalog": "test-project-id",
                "constraint_schema": "test_dataset",
                "constraint_name": "fk_self",
                "constraint_type": "FOREIGN KEY",
                "table_name": "orders",
                "column_name": "customer_id",
                "ordinal_position": 1,
                "referenced_table": "orders",
                "referenced_column": "customer_id",
            },
        ]
    )
    extractor._cache["column_unique_values"] = pd.DataFrame(
        [
            {
                "column_name": "customer_id",
                "unique_value": "1",
                "column_id": "test-project-id.test_dataset.customers.customer_id",
                "value_id": "test-project-id.test_dataset.customers.customer_id.hash1",
                "project_id": "test-project-id",
                "dataset_id": "test_dataset",
                "table_name": "customers",
            },
            {
                "column_name": "customer_id",
                "unique_value": "2",
                "column_id": "test-project-id.test_dataset.customers.customer_id",
                "value_id": "test-project-id.test_dataset.customers.customer_id.hash2",
                "project_id": "test-project-id",
                "dataset_id": "test_dataset",
                "table_name": "customers",
            },
        ]
    )
    return extractor


# --- Retriever (Layer 1) --------------------------------------------------


def test_databases_injects_platform_service(populated_extractor):
    """The databases stream injects the GCP/BIGQUERY platform and service constants."""
    retriever = BigQueryInformationSchemaRetriever(populated_extractor)
    assert list(retriever.stream("databases")) == [
        {"project_id": "test-project-id", "platform": "GCP", "service": "BIGQUERY"}
    ]


def test_schemas_and_tables_shapes(populated_extractor):
    """The schemas and tables streams surface their source rows verbatim."""
    retriever = BigQueryInformationSchemaRetriever(populated_extractor)
    assert [s["dataset_id"] for s in retriever.stream("schemas")] == ["test_dataset"]
    assert [t["table_name"] for t in retriever.stream("tables")] == ["customers", "orders"]


def test_columns_surface_pk_fk(populated_extractor):
    """The columns stream surfaces the extractor's derived primary/foreign-key flags."""
    retriever = BigQueryInformationSchemaRetriever(populated_extractor)
    by_name = {(c["table_name"], c["column_name"]): c for c in retriever.stream("columns")}
    assert by_name[("customers", "customer_id")]["is_primary_key"] is True
    assert by_name[("customers", "customer_id")]["is_foreign_key"] is False
    assert by_name[("orders", "customer_id")]["is_foreign_key"] is True


def test_columns_pass_is_nullable_raw(populated_extractor):
    """Layer 1 passes is_nullable through raw ("YES"/"NO"); Layer 3 owns the decode."""
    retriever = BigQueryInformationSchemaRetriever(populated_extractor)
    nullable = {
        (c["table_name"], c["column_name"]): c["is_nullable"] for c in retriever.stream("columns")
    }
    assert nullable[("customers", "customer_id")] == "NO"
    assert nullable[("customers", "customer_name")] == "YES"


def test_references_filters_to_foreign_key_and_drops_self_refs(populated_extractor):
    """References keeps only FOREIGN KEY rows and drops self-references."""
    retriever = BigQueryInformationSchemaRetriever(populated_extractor)
    refs = list(retriever.stream("references"))
    assert len(refs) == 1
    assert refs[0]["constraint_type"] == "FOREIGN KEY"
    assert refs[0]["table_name"] == "orders"
    assert refs[0]["referenced_table"] == "customers"


def test_values_include_name_parts(populated_extractor):
    """The values stream carries the additive project/dataset/table name-parts."""
    retriever = BigQueryInformationSchemaRetriever(populated_extractor)
    values = list(retriever.stream("values"))
    assert len(values) == 2
    assert values[0]["project_id"] == "test-project-id"
    assert values[0]["dataset_id"] == "test_dataset"
    assert values[0]["table_name"] == "customers"


def test_nan_and_nat_become_none(populated_extractor):
    """NaN (description) and NaT (creation_time) are both normalized to None."""
    retriever = BigQueryInformationSchemaRetriever(populated_extractor)
    tables = {t["table_name"]: t for t in retriever.stream("tables")}
    assert tables["orders"]["description"] is None
    assert tables["orders"]["creation_time"] is None
    assert tables["customers"]["description"] == "Customer table"
    assert tables["customers"]["creation_time"] == pd.Timestamp("2024-01-01")


def test_unknown_record_type_raises(populated_extractor):
    """An unknown record type raises ValueError."""
    retriever = BigQueryInformationSchemaRetriever(populated_extractor)
    with pytest.raises(ValueError, match="Unknown record type"):
        retriever.stream("bogus")


def test_empty_caches_yield_empty_streams():
    """A fresh extractor (empty caches) yields empty streams for every record type."""
    client = Mock()
    client.project = "test-project-id"
    extractor = BigQuerySchemaExtractor(client=client, dataset_id="test_dataset")
    retriever = BigQueryInformationSchemaRetriever(extractor)
    for record_type in ("databases", "schemas", "tables", "columns", "references", "values"):
        assert list(retriever.stream(record_type)) == []


def test_retriever_satisfies_protocol(populated_extractor):
    """The retriever structurally satisfies the runtime-checkable Retriever protocol."""
    assert isinstance(BigQueryInformationSchemaRetriever(populated_extractor), Retriever)


# --- End-to-end (Layer 1 + 2 + 3) -----------------------------------------


def test_normalize_populates_information_schema_table(populated_extractor):
    """normalize() populates every record list with the expected counts."""
    result = build_bigquery_information_schema_normalizer(populated_extractor).normalize()
    assert isinstance(result, InformationSchemaTable)
    assert len(result.databases) == 1
    assert len(result.schemas) == 1
    assert len(result.tables) == 2
    assert len(result.columns) == 4
    assert len(result.references) == 1
    assert len(result.values) == 2


def test_normalize_database_has_platform_service(populated_extractor):
    """A normalized database record carries the injected platform/service."""
    result = build_bigquery_information_schema_normalizer(populated_extractor).normalize()
    database = result.databases[0]
    assert isinstance(database, DatabaseRecord)
    assert database.database_name == "test-project-id"
    assert database.platform == "GCP"
    assert database.service == "BIGQUERY"


def test_normalize_reference_correct_and_no_self_refs(populated_extractor):
    """The single normalized reference has correct source/target name-parts."""
    result = build_bigquery_information_schema_normalizer(populated_extractor).normalize()
    assert len(result.references) == 1
    ref = result.references[0]
    assert isinstance(ref, ReferenceRecord)
    assert ref.source_database_name == "test-project-id"
    assert ref.source_schema_name == "test_dataset"
    assert ref.source_table_name == "orders"
    assert ref.source_column_name == "customer_id"
    assert ref.target_database_name == "test-project-id"
    assert ref.target_schema_name == "test_dataset"
    assert ref.target_table_name == "customers"
    assert ref.target_column_name == "customer_id"


def test_normalize_value_carries_name_parts_and_renamed_value(populated_extractor):
    """A normalized value record carries name-parts and the renamed `value` field."""
    result = build_bigquery_information_schema_normalizer(populated_extractor).normalize()
    value = result.values[0]
    assert isinstance(value, ValueRecord)
    assert value.database_name == "test-project-id"
    assert value.schema_name == "test_dataset"
    assert value.table_name == "customers"
    assert value.column_name == "customer_id"
    assert value.value == "1"


def test_normalize_columns_coerced_by_layer3(populated_extractor):
    """Layer 3 coerces is_nullable ("YES"/"NO" -> bool) and preserves the PK/FK bools."""
    result = build_bigquery_information_schema_normalizer(populated_extractor).normalize()
    by_name = {(c.table_name, c.column_name): c for c in result.columns}
    assert isinstance(by_name[("customers", "customer_id")], ColumnRecord)
    assert by_name[("customers", "customer_id")].is_nullable is False
    assert by_name[("customers", "customer_name")].is_nullable is True
    assert by_name[("customers", "customer_id")].is_primary_key is True
    assert by_name[("orders", "customer_id")].is_foreign_key is True
