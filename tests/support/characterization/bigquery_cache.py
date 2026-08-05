"""Offline BigQuery schema extractor cache seed, shared by unit + integration tests.

The customers/orders fixture (one foreign key, two sampled values) that both the
Layer A transform golden and the Layer B graph golden feed through the BigQuery schema
pipeline without a live BigQuery client. Kept here as the single source of truth so the
unit conftest fixtures and the integration golden test seed identical data.
"""

from __future__ import annotations

from typing import TYPE_CHECKING
from unittest.mock import Mock

import pandas as pd

if TYPE_CHECKING:
    from neocarta.connectors.bigquery.schema.extract import BigQuerySchemaExtractor


def make_mock_bigquery_client() -> Mock:
    """Return a mock BigQuery client whose ``project`` is ``"test-project-id"``."""
    client = Mock()
    client.project = "test-project-id"
    return client


def seed_bigquery_schema_cache(extractor: BigQuerySchemaExtractor) -> BigQuerySchemaExtractor:
    """Populate ``extractor._cache`` with the customers/orders frames and return it.

    Args:
        extractor: The extractor whose private cache is seeded in place.

    Returns:
        The same extractor, for convenient chaining.
    """
    extractor._cache["database_info"] = pd.DataFrame([{"project_id": "test-project-id"}])

    extractor._cache["schema_info"] = pd.DataFrame(
        [
            {
                "project_id": "test-project-id",
                "dataset_id": "test_dataset",
                "description": "Test dataset description",
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
            }
        ]
    )

    # Exactly the four columns the real extractor produces — see the empty-frame column list in
    # ``extract_column_unique_values_for_table``, which declares
    # ``["column_name", "unique_value", "column_id", "value_id"]`` and adds nothing else.
    #
    # This seed previously also carried ``project_id`` / ``dataset_id`` / ``table_name`` under a
    # comment claiming it "mirrors the real extractor". It does not: the extractor has those
    # values in scope when it mints ``column_id`` but never writes them to the frame. Nothing
    # read them, so removing them changes no golden — but leaving them would have been a parity
    # trap, because a normalizer built against this fixture would work here and fail on live
    # data. The container path a value record needs is recovered from ``column_id`` instead,
    # which is the projection ``normalized_schema/README.md`` records as the connector's to own.
    extractor._cache["column_unique_values"] = pd.DataFrame(
        [
            {
                "column_name": "customer_id",
                "unique_value": "1",
                "column_id": "test_project_id.test_dataset.customers.customer_id",
                "value_id": "test_project_id.test_dataset.customers.customer_id.c4ca4238a0b923820dcc509a6f75849b",
            },
            {
                "column_name": "customer_id",
                "unique_value": "2",
                "column_id": "test_project_id.test_dataset.customers.customer_id",
                "value_id": "test_project_id.test_dataset.customers.customer_id.c81e728d9d4c2f636f067f89cc14862c",
            },
        ]
    )

    return extractor
