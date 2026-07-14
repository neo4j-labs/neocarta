"""Shared fixtures usable by both the unit and integration test suites.

Fixtures here are loaded for every ``tests/`` run (rootdir is the repo root), so
keep this file to genuinely cross-cutting fixtures — colocated per-package
fixtures remain the norm elsewhere.
"""

import pytest

from neocarta.data_model.normalized import (
    ColumnRecord,
    DatabaseRecord,
    InformationSchemaTable,
    ReferenceRecord,
    SchemaRecord,
    TableRecord,
    ValueRecord,
)

# A hyphenated project id (normalizes to ``test_project_id``); lowercase
# platform/service to exercise the record validators' upper-casing.
_DATABASE = "test-project-id"
_SCHEMA = "test_dataset"


@pytest.fixture
def information_schema_table() -> InformationSchemaTable:
    """A small customers/orders ``InformationSchemaTable`` shared by the graph-transform tests.

    Exercises every relational family plus the parity-critical edge cases: a
    ``is_nullable`` given raw as ``"YES"``/``"NO"``, a real foreign key, a
    self-referential foreign-key artifact (which the transformer must drop), and
    sampled column values.
    """
    return InformationSchemaTable(
        databases=[
            DatabaseRecord(
                database_name=_DATABASE, platform="gcp", service="bigquery", description=None
            ),
        ],
        schemas=[
            SchemaRecord(
                database_name=_DATABASE, schema_name=_SCHEMA, description="Test dataset description"
            ),
        ],
        tables=[
            TableRecord(
                database_name=_DATABASE,
                schema_name=_SCHEMA,
                table_name="customers",
                description="Customer table",
            ),
            TableRecord(
                database_name=_DATABASE,
                schema_name=_SCHEMA,
                table_name="orders",
                description="Order table",
            ),
        ],
        columns=[
            ColumnRecord(
                database_name=_DATABASE,
                schema_name=_SCHEMA,
                table_name="customers",
                column_name="customer_id",
                data_type="INT64",
                is_nullable="NO",
                is_primary_key=True,
                is_foreign_key=False,
                description="Customer ID",
            ),
            ColumnRecord(
                database_name=_DATABASE,
                schema_name=_SCHEMA,
                table_name="customers",
                column_name="customer_name",
                data_type="STRING",
                is_nullable="YES",
                is_primary_key=False,
                is_foreign_key=False,
                description="Customer name",
            ),
            ColumnRecord(
                database_name=_DATABASE,
                schema_name=_SCHEMA,
                table_name="orders",
                column_name="order_id",
                data_type="INT64",
                is_nullable="NO",
                is_primary_key=True,
                is_foreign_key=False,
                description="Order ID",
            ),
            ColumnRecord(
                database_name=_DATABASE,
                schema_name=_SCHEMA,
                table_name="orders",
                column_name="customer_id",
                data_type="INT64",
                is_nullable="NO",
                is_primary_key=False,
                is_foreign_key=True,
                description="Customer ID reference",
            ),
        ],
        references=[
            # Real FK: orders.customer_id -> customers.customer_id.
            ReferenceRecord(
                source_database_name=_DATABASE,
                source_schema_name=_SCHEMA,
                source_table_name="orders",
                source_column_name="customer_id",
                target_database_name=_DATABASE,
                target_schema_name=_SCHEMA,
                target_table_name="customers",
                target_column_name="customer_id",
                criteria=None,
            ),
            # Self-referential FK artifact: the transformer must drop this.
            ReferenceRecord(
                source_database_name=_DATABASE,
                source_schema_name=_SCHEMA,
                source_table_name="orders",
                source_column_name="customer_id",
                target_database_name=_DATABASE,
                target_schema_name=_SCHEMA,
                target_table_name="orders",
                target_column_name="customer_id",
                criteria=None,
            ),
        ],
        values=[
            ValueRecord(
                database_name=_DATABASE,
                schema_name=_SCHEMA,
                table_name="customers",
                column_name="customer_id",
                value="1",
            ),
            ValueRecord(
                database_name=_DATABASE,
                schema_name=_SCHEMA,
                table_name="customers",
                column_name="customer_id",
                value="2",
            ),
        ],
    )
