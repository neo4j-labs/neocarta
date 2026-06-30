from unittest.mock import MagicMock

import pandas as pd
import pytest

from neocarta.connectors.databricks.schema.extract import DatabricksSchemaExtractor
from neocarta.connectors.databricks.schema.transform import DatabricksSchemaTransformer
from neocarta.connectors.utils.generate_id import generate_column_id, generate_value_id
from neocarta.data_model.instance import HasValue, Value
from neocarta.data_model.schema.rdbms import (
    Column,
    Database,
    HasColumn,
    HasSchema,
    HasTable,
    References,
    Schema,
    Table,
)

CATALOG = "test_catalog"
SCHEMA = "test_schema"

_CUSTOMER_ID_COLUMN_ID = generate_column_id(CATALOG, SCHEMA, "customers", "customer_id")
_VALUE_ID_1 = generate_value_id(CATALOG, SCHEMA, "customers", "customer_id", "1")
_VALUE_ID_2 = generate_value_id(CATALOG, SCHEMA, "customers", "customer_id", "2")


@pytest.fixture
def mock_databricks_connection():
    """Create a mock databricks.sql connection (cursor returns empty frames by default)."""
    connection = MagicMock()
    connection.cursor.return_value.fetchall_arrow.return_value.to_pandas.return_value = (
        pd.DataFrame()
    )
    return connection


@pytest.fixture
def databricks_extractor(mock_databricks_connection):
    """Create a DatabricksSchemaExtractor with a mocked connection."""
    return DatabricksSchemaExtractor(connection=mock_databricks_connection, catalog=CATALOG)


@pytest.fixture
def databricks_extractor_with_cache(mock_databricks_connection):
    """Create a DatabricksSchemaExtractor with pre-populated cache."""
    extractor = DatabricksSchemaExtractor(connection=mock_databricks_connection, catalog=CATALOG)

    database_info = pd.DataFrame([{"catalog": CATALOG}])

    schema_info = pd.DataFrame(
        [
            {
                "catalog_name": CATALOG,
                "schema_name": SCHEMA,
                "description": "Test schema description",
            }
        ]
    )

    table_info = pd.DataFrame(
        [
            {
                "table_catalog": CATALOG,
                "table_schema": SCHEMA,
                "table_name": "customers",
                "table_type": "MANAGED",
                "description": "Customer table",
            },
            {
                "table_catalog": CATALOG,
                "table_schema": SCHEMA,
                "table_name": "orders",
                "table_type": "MANAGED",
                "description": "Order table",
            },
        ]
    )

    column_info = pd.DataFrame(
        [
            {
                "table_catalog": CATALOG,
                "table_schema": SCHEMA,
                "table_name": "customers",
                "column_name": "customer_id",
                "is_nullable": False,
                "data_type": "INT",
                "description": "Customer ID",
                "is_primary_key": True,
                "is_foreign_key": False,
            },
            {
                "table_catalog": CATALOG,
                "table_schema": SCHEMA,
                "table_name": "customers",
                "column_name": "customer_name",
                "is_nullable": True,
                "data_type": "STRING",
                "description": "Customer name",
                "is_primary_key": False,
                "is_foreign_key": False,
            },
            {
                "table_catalog": CATALOG,
                "table_schema": SCHEMA,
                "table_name": "orders",
                "column_name": "order_id",
                "is_nullable": False,
                "data_type": "INT",
                "description": "Order ID",
                "is_primary_key": True,
                "is_foreign_key": False,
            },
            {
                "table_catalog": CATALOG,
                "table_schema": SCHEMA,
                "table_name": "orders",
                "column_name": "customer_id",
                "is_nullable": False,
                "data_type": "INT",
                "description": "Customer ID reference",
                "is_primary_key": False,
                "is_foreign_key": True,
            },
        ]
    )

    column_references_info = pd.DataFrame(
        [
            {
                "constraint_type": "FOREIGN KEY",
                "table_catalog": CATALOG,
                "table_schema": SCHEMA,
                "table_name": "orders",
                "column_name": "customer_id",
                "ordinal_position": 1,
                "referenced_catalog": CATALOG,
                "referenced_schema": SCHEMA,
                "referenced_table": "customers",
                "referenced_column": "customer_id",
            }
        ]
    )

    column_unique_values = pd.DataFrame(
        [
            {
                "column_name": "customer_id",
                "unique_value": "1",
                "column_id": _CUSTOMER_ID_COLUMN_ID,
                "value_id": _VALUE_ID_1,
            },
            {
                "column_name": "customer_id",
                "unique_value": "2",
                "column_id": _CUSTOMER_ID_COLUMN_ID,
                "value_id": _VALUE_ID_2,
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


@pytest.fixture
def databricks_transformer():
    """Create a DatabricksSchemaTransformer."""
    return DatabricksSchemaTransformer()


@pytest.fixture
def databricks_transformer_with_cache():
    """Create a DatabricksSchemaTransformer with pre-populated cache."""
    transformer = DatabricksSchemaTransformer()

    database_nodes = [
        Database(
            id=CATALOG,
            name=CATALOG,
            description=None,
            platform="DATABRICKS",
            service="UNITY_CATALOG",
        )
    ]

    schema_nodes = [
        Schema(
            id=f"{CATALOG}.{SCHEMA}",
            name=SCHEMA,
            description="Test schema description",
        )
    ]

    table_nodes = [
        Table(
            id=f"{CATALOG}.{SCHEMA}.customers",
            name="customers",
            description="Customer table",
        ),
        Table(id=f"{CATALOG}.{SCHEMA}.orders", name="orders", description="Order table"),
    ]

    column_nodes = [
        Column(
            id=f"{CATALOG}.{SCHEMA}.customers.customer_id",
            name="customer_id",
            description="Customer ID",
            type="INT",
            nullable="NO",
            is_primary_key=True,
            is_foreign_key=False,
        ),
        Column(
            id=f"{CATALOG}.{SCHEMA}.customers.customer_name",
            name="customer_name",
            description="Customer name",
            type="STRING",
            nullable="YES",
            is_primary_key=False,
            is_foreign_key=False,
        ),
        Column(
            id=f"{CATALOG}.{SCHEMA}.orders.order_id",
            name="order_id",
            description="Order ID",
            type="INT",
            nullable="NO",
            is_primary_key=True,
            is_foreign_key=False,
        ),
        Column(
            id=f"{CATALOG}.{SCHEMA}.orders.customer_id",
            name="customer_id",
            description="Customer ID reference",
            type="INT",
            nullable="NO",
            is_primary_key=False,
            is_foreign_key=True,
        ),
    ]

    value_nodes = [
        Value(id=_VALUE_ID_1, value="1"),
        Value(id=_VALUE_ID_2, value="2"),
    ]

    has_schema_relationships = [HasSchema(database_id=CATALOG, schema_id=f"{CATALOG}.{SCHEMA}")]

    has_table_relationships = [
        HasTable(schema_id=f"{CATALOG}.{SCHEMA}", table_id=f"{CATALOG}.{SCHEMA}.customers"),
        HasTable(schema_id=f"{CATALOG}.{SCHEMA}", table_id=f"{CATALOG}.{SCHEMA}.orders"),
    ]

    has_column_relationships = [
        HasColumn(
            table_id=f"{CATALOG}.{SCHEMA}.customers",
            column_id=f"{CATALOG}.{SCHEMA}.customers.customer_id",
        ),
        HasColumn(
            table_id=f"{CATALOG}.{SCHEMA}.customers",
            column_id=f"{CATALOG}.{SCHEMA}.customers.customer_name",
        ),
        HasColumn(
            table_id=f"{CATALOG}.{SCHEMA}.orders",
            column_id=f"{CATALOG}.{SCHEMA}.orders.order_id",
        ),
        HasColumn(
            table_id=f"{CATALOG}.{SCHEMA}.orders",
            column_id=f"{CATALOG}.{SCHEMA}.orders.customer_id",
        ),
    ]

    references_relationships = [
        References(
            source_column_id=f"{CATALOG}.{SCHEMA}.orders.customer_id",
            target_column_id=f"{CATALOG}.{SCHEMA}.customers.customer_id",
        )
    ]

    has_value_relationships = [
        HasValue(column_id=_CUSTOMER_ID_COLUMN_ID, value_id=_VALUE_ID_1),
        HasValue(column_id=_CUSTOMER_ID_COLUMN_ID, value_id=_VALUE_ID_2),
    ]

    transformer._node_cache["database_nodes"] = database_nodes
    transformer._node_cache["schema_nodes"] = schema_nodes
    transformer._node_cache["table_nodes"] = table_nodes
    transformer._node_cache["column_nodes"] = column_nodes
    transformer._node_cache["value_nodes"] = value_nodes
    transformer._relationships_cache["has_schema_relationships"] = has_schema_relationships
    transformer._relationships_cache["has_table_relationships"] = has_table_relationships
    transformer._relationships_cache["has_column_relationships"] = has_column_relationships
    transformer._relationships_cache["references_relationships"] = references_relationships
    transformer._relationships_cache["has_value_relationships"] = has_value_relationships

    return transformer
