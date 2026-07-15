from unittest.mock import Mock

import pandas as pd
import pytest

from neocarta.connectors.bigquery.schema.extract import BigQuerySchemaExtractor


@pytest.fixture
def mock_bigquery_client():
    """Create a mock BigQuery client."""
    client = Mock()
    client.project = "test-project-id"
    return client


@pytest.fixture
def bigquery_extractor(mock_bigquery_client):
    """Create a BigQuerySchemaExtractor with a mocked client."""
    return BigQuerySchemaExtractor(client=mock_bigquery_client, dataset_id="test_dataset")


@pytest.fixture
def bigquery_extractor_with_cache(mock_bigquery_client):
    """Create a BigQuerySchemaExtractor with pre-populated cache."""
    extractor = BigQuerySchemaExtractor(client=mock_bigquery_client, dataset_id="test_dataset")

    # Database info cache
    database_info = pd.DataFrame([{"project_id": "test-project-id"}])

    # Schema info cache
    schema_info = pd.DataFrame(
        [
            {
                "project_id": "test-project-id",
                "dataset_id": "test_dataset",
                "description": "Test dataset description",
            }
        ]
    )

    # Table info cache
    table_info = pd.DataFrame(
        [
            {
                "table_catalog": "test-project-id",
                "table_schema": "test_dataset",
                "table_name": "customers",
                "table_type": "BASE TABLE",
                "creation_time": None,
                "ddl": None,
                "description": "Customer table",
            },
            {
                "table_catalog": "test-project-id",
                "table_schema": "test_dataset",
                "table_name": "orders",
                "table_type": "BASE TABLE",
                "creation_time": None,
                "ddl": None,
                "description": "Order table",
            },
        ]
    )

    # Column info cache
    column_info = pd.DataFrame(
        [
            {
                "table_catalog": "test-project-id",
                "table_schema": "test_dataset",
                "table_name": "customers",
                "column_name": "customer_id",
                "is_nullable": "NO",
                "data_type": "INT64",
                "description": "Customer ID",
                "constraint_name": "test_project_id.test_dataset.customers.pk$",
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
                "constraint_name": "test_project_id.test_dataset.orders.pk$",
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
                "description": "Customer ID reference",
                "constraint_name": "test_project_id.test_dataset.orders.fk_customer",
                "is_primary_key": False,
                "is_foreign_key": True,
            },
        ]
    )

    # Column references info cache
    column_references_info = pd.DataFrame(
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
            }
        ]
    )

    # Column unique values cache. Mirrors the real extractor, which carries the
    # table's name-parts (project_id/dataset_id/table_name) so the normalizer's
    # ``values`` mapping can build value records without re-deriving them.
    column_unique_values = pd.DataFrame(
        [
            {
                "column_name": "customer_id",
                "unique_value": "1",
                "column_id": "test_project_id.test_dataset.customers.customer_id",
                "value_id": "test_project_id.test_dataset.customers.customer_id.c4ca4238a0b923820dcc509a6f75849b",
                "project_id": "test-project-id",
                "dataset_id": "test_dataset",
                "table_name": "customers",
            },
            {
                "column_name": "customer_id",
                "unique_value": "2",
                "column_id": "test_project_id.test_dataset.customers.customer_id",
                "value_id": "test_project_id.test_dataset.customers.customer_id.c81e728d9d4c2f636f067f89cc14862c",
                "project_id": "test-project-id",
                "dataset_id": "test_dataset",
                "table_name": "customers",
            },
        ]
    )

    extractor._cache["database_info"] = database_info
    extractor._cache["schema_info"] = schema_info
    extractor._cache["table_info"] = table_info
    extractor._cache["column_info"] = column_info
    extractor._cache["column_references_info"] = column_references_info
    extractor._cache["column_unique_values"] = column_unique_values

    return extractor
