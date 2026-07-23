import pytest

from neocarta.connectors.bigquery.schema.extract import BigQuerySchemaExtractor
from neocarta.connectors.bigquery.schema.transform import BigQuerySchemaTransformer
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
from tests.support.characterization.bigquery_cache import (
    make_mock_bigquery_client,
    seed_bigquery_schema_cache,
)


@pytest.fixture
def mock_bigquery_client():
    """Create a mock BigQuery client."""
    return make_mock_bigquery_client()


@pytest.fixture
def bigquery_extractor(mock_bigquery_client):
    """Create a BigQuerySchemaExtractor with a mocked client."""
    return BigQuerySchemaExtractor(client=mock_bigquery_client, dataset_id="test_dataset")


@pytest.fixture
def bigquery_extractor_with_cache(mock_bigquery_client):
    """Create a BigQuerySchemaExtractor with the shared customers/orders cache pre-populated.

    Seeded via the characterization harness (``seed_bigquery_schema_cache``), the single
    source of truth for the offline customers/orders fixture the golden-masters feed through.
    """
    extractor = BigQuerySchemaExtractor(client=mock_bigquery_client, dataset_id="test_dataset")
    return seed_bigquery_schema_cache(extractor)


@pytest.fixture
def bigquery_transformer():
    """Create a BigQuerySchemaTransformer."""
    return BigQuerySchemaTransformer()


@pytest.fixture
def bigquery_transformer_with_cache():
    """Create a BigQuerySchemaTransformer with pre-populated cache."""
    transformer = BigQuerySchemaTransformer()

    # Database nodes
    database_nodes = [Database(id="test_project_id", name="test-project-id", description=None)]

    # Schema nodes
    schema_nodes = [
        Schema(
            id="test_project_id.test_dataset",
            name="test_dataset",
            description="Test dataset description",
        )
    ]

    # Table nodes
    table_nodes = [
        Table(
            id="test_project_id.test_dataset.customers",
            name="customers",
            description="Customer table",
        ),
        Table(id="test_project_id.test_dataset.orders", name="orders", description="Order table"),
    ]

    # Column nodes
    column_nodes = [
        Column(
            id="test_project_id.test_dataset.customers.customer_id",
            name="customer_id",
            description="Customer ID",
            type="INT64",
            nullable="NO",
            is_primary_key=True,
            is_foreign_key=False,
        ),
        Column(
            id="test_project_id.test_dataset.customers.customer_name",
            name="customer_name",
            description="Customer name",
            type="STRING",
            nullable="YES",
            is_primary_key=False,
            is_foreign_key=False,
        ),
        Column(
            id="test_project_id.test_dataset.orders.order_id",
            name="order_id",
            description="Order ID",
            type="INT64",
            nullable="NO",
            is_primary_key=True,
            is_foreign_key=False,
        ),
        Column(
            id="test_project_id.test_dataset.orders.customer_id",
            name="customer_id",
            description="Customer ID reference",
            type="INT64",
            nullable="NO",
            is_primary_key=False,
            is_foreign_key=True,
        ),
    ]

    # Value nodes
    value_nodes = [
        Value(
            id="test_project_id.test_dataset.customers.customer_id.c4ca4238a0b923820dcc509a6f75849b",
            value="1",
        ),
        Value(
            id="test_project_id.test_dataset.customers.customer_id.c81e728d9d4c2f636f067f89cc14862c",
            value="2",
        ),
    ]

    # Has schema relationships
    has_schema_relationships = [
        HasSchema(database_id="test_project_id", schema_id="test_project_id.test_dataset")
    ]

    # Has table relationships
    has_table_relationships = [
        HasTable(
            schema_id="test_project_id.test_dataset",
            table_id="test_project_id.test_dataset.customers",
        ),
        HasTable(
            schema_id="test_project_id.test_dataset", table_id="test_project_id.test_dataset.orders"
        ),
    ]

    # Has column relationships
    has_column_relationships = [
        HasColumn(
            table_id="test_project_id.test_dataset.customers",
            column_id="test_project_id.test_dataset.customers.customer_id",
        ),
        HasColumn(
            table_id="test_project_id.test_dataset.customers",
            column_id="test_project_id.test_dataset.customers.customer_name",
        ),
        HasColumn(
            table_id="test_project_id.test_dataset.orders",
            column_id="test_project_id.test_dataset.orders.order_id",
        ),
        HasColumn(
            table_id="test_project_id.test_dataset.orders",
            column_id="test_project_id.test_dataset.orders.customer_id",
        ),
    ]

    # References relationships
    references_relationships = [
        References(
            source_column_id="test_project_id.test_dataset.orders.customer_id",
            target_column_id="test_project_id.test_dataset.customers.customer_id",
        )
    ]

    # Has value relationships
    has_value_relationships = [
        HasValue(
            column_id="test_project_id.test_dataset.customers.customer_id",
            value_id="test_project_id.test_dataset.customers.customer_id.c4ca4238a0b923820dcc509a6f75849b",
        ),
        HasValue(
            column_id="test_project_id.test_dataset.customers.customer_id",
            value_id="test_project_id.test_dataset.customers.customer_id.c81e728d9d4c2f636f067f89cc14862c",
        ),
    ]

    # Set all caches
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
