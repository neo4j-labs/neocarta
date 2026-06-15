import pandas as pd
import pytest

from neocarta.connectors.query_log.extract import QueryLogExtractor
from neocarta.connectors.query_log.transform import QueryLogTransformer
from neocarta.data_model.query import Query, UsesColumn, UsesTable
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


@pytest.fixture
def query_log_extractor() -> QueryLogExtractor:
    return QueryLogExtractor()


@pytest.fixture
def query_log_extractor_with_cache() -> QueryLogExtractor:
    e = QueryLogExtractor()

    query_info_records = [
        {
            "project_id": "example-project-id",
            "query": "SELECT o.order_id, oi.order_item_id, p.product_name, oi.quantity, oi.price\nFROM `example-project-id.demo_ecommerce.orders` AS o\nJOIN `example-project-id.demo_ecommerce.order_items` AS oi ON o.order_id = oi.order_id\nJOIN `example-project-id.demo_ecommerce.products` AS p ON oi.product_id = p.product_id;",
            "query_id": "e45079ee36de11097b070f3e0b6dbc5d365827af3c19a3737cf3331daca26e76",
        },
    ]

    table_info_records = [
        {
            "platform": "GCP",
            "service": "BIGQUERY",
            "table_id": "example_project_id.demo_ecommerce.orders",
            "table_name": "orders",
            "dataset_id": "example_project_id.demo_ecommerce",
            "dataset_name": "demo_ecommerce",
            "project_name": "example-project-id",
            "project_id": "example-project-id",
            "table_alias": "o",
            "query_id": "e45079ee36de11097b070f3e0b6dbc5d365827af3c19a3737cf3331daca26e76",
        },
        {
            "platform": "GCP",
            "service": "BIGQUERY",
            "table_id": "example_project_id.demo_ecommerce.order_items",
            "table_name": "order_items",
            "dataset_id": "example_project_id.demo_ecommerce",
            "dataset_name": "demo_ecommerce",
            "project_name": "example-project-id",
            "project_id": "example-project-id",
            "table_alias": "oi",
            "query_id": "e45079ee36de11097b070f3e0b6dbc5d365827af3c19a3737cf3331daca26e76",
        },
        {
            "platform": "GCP",
            "service": "BIGQUERY",
            "table_id": "example_project_id.demo_ecommerce.products",
            "table_name": "products",
            "dataset_id": "example_project_id.demo_ecommerce",
            "dataset_name": "demo_ecommerce",
            "project_name": "example-project-id",
            "project_id": "example-project-id",
            "table_alias": "p",
            "query_id": "e45079ee36de11097b070f3e0b6dbc5d365827af3c19a3737cf3331daca26e76",
        },
    ]

    column_info_records = [
        {
            "query_id": "e45079ee36de11097b070f3e0b6dbc5d365827af3c19a3737cf3331daca26e76",
            "table_id": "example_project_id.demo_ecommerce.orders",
            "table_name": "orders",
            "table_alias": "o",
            "column_id": "example_project_id.demo_ecommerce.orders.order_id",
            "column_name": "order_id",
        },
        {
            "query_id": "e45079ee36de11097b070f3e0b6dbc5d365827af3c19a3737cf3331daca26e76",
            "table_id": "example_project_id.demo_ecommerce.orders",
            "table_name": "orders",
            "table_alias": "o",
            "column_id": "example_project_id.demo_ecommerce.orders.order_date",
            "column_name": "order_date",
        },
        {
            "query_id": "e45079ee36de11097b070f3e0b6dbc5d365827af3c19a3737cf3331daca26e76",
            "table_id": "example_project_id.demo_ecommerce.orders",
            "table_name": "orders",
            "table_alias": "o",
            "column_id": "example_project_id.demo_ecommerce.orders.customer_id",
            "column_name": "customer_id",
        },
        {
            "query_id": "e45079ee36de11097b070f3e0b6dbc5d365827af3c19a3737cf3331daca26e76",
            "table_id": "example_project_id.demo_ecommerce.orders",
            "table_name": "orders",
            "table_alias": "o",
            "column_id": "example_project_id.demo_ecommerce.orders.total_amount",
            "column_name": "total_amount",
        },
        {
            "query_id": "e45079ee36de11097b070f3e0b6dbc5d365827af3c19a3737cf3331daca26e76",
            "table_id": "example_project_id.demo_ecommerce.order_items",
            "table_name": "order_items",
            "table_alias": "oi",
            "column_id": "example_project_id.demo_ecommerce.order_items.order_item_id",
            "column_name": "order_item_id",
        },
        {
            "query_id": "e45079ee36de11097b070f3e0b6dbc5d365827af3c19a3737cf3331daca26e76",
            "table_id": "example_project_id.demo_ecommerce.order_items",
            "table_name": "order_items",
            "table_alias": "oi",
            "column_id": "example_project_id.demo_ecommerce.order_items.order_id",
            "column_name": "order_id",
        },
        {
            "query_id": "e45079ee36de11097b070f3e0b6dbc5d365827af3c19a3737cf3331daca26e76",
            "table_id": "example_project_id.demo_ecommerce.order_items",
            "table_name": "order_items",
            "table_alias": "oi",
            "column_id": "example_project_id.demo_ecommerce.order_items.product_id",
            "column_name": "product_id",
        },
        {
            "query_id": "e45079ee36de11097b070f3e0b6dbc5d365827af3c19a3737cf3331daca26e76",
            "table_id": "example_project_id.demo_ecommerce.order_items",
            "table_name": "order_items",
            "table_alias": "oi",
            "column_id": "example_project_id.demo_ecommerce.order_items.quantity",
            "column_name": "quantity",
        },
    ]

    column_references_info_records = [
        {
            "left_table_name": "orders",
            "left_table_id": "example_project_id.demo_ecommerce.orders",
            "left_table_alias": "o",
            "left_column_name": "order_id",
            "left_column_id": "example_project_id.demo_ecommerce.orders.order_id",
            "right_table_name": "order_items",
            "right_table_id": "example_project_id.demo_ecommerce.order_items",
            "right_table_alias": "oi",
            "right_column_name": "order_id",
            "right_column_id": "example_project_id.demo_ecommerce.order_items.order_id",
            "criteria": "o.order_id = oi.order_id",
        },
        {
            "left_table_name": "order_items",
            "left_table_id": "example_project_id.demo_ecommerce.order_items",
            "left_table_alias": "oi",
            "left_column_name": "product_id",
            "left_column_id": "example_project_id.demo_ecommerce.order_items.product_id",
            "right_table_name": "products",
            "right_table_id": "example_project_id.demo_ecommerce.products",
            "right_table_alias": "p",
            "right_column_name": "product_id",
            "right_column_id": "example_project_id.demo_ecommerce.products.product_id",
            "criteria": "oi.product_id = p.product_id",
        },
    ]

    e._cache["query_info"] = pd.DataFrame(query_info_records)
    e._cache["table_info"] = pd.DataFrame(table_info_records)
    e._cache["column_info"] = pd.DataFrame(column_info_records)
    e._cache["column_references_info"] = pd.DataFrame(column_references_info_records)

    return e


@pytest.fixture
def query_log_transformer() -> QueryLogTransformer:
    return QueryLogTransformer()


@pytest.fixture
def query_log_transformer_with_cache() -> QueryLogTransformer:
    t = QueryLogTransformer()

    database_nodes = [
        Database(
            id="example_project_id", name="example-project-id", platform="GCP", service="BIGQUERY"
        )
    ]
    schema_nodes = [Schema(id="example_project_id.demo_ecommerce", name="demo_ecommerce")]
    table_nodes = [
        Table(id="example_project_id.demo_ecommerce.orders", name="orders"),
        Table(id="example_project_id.demo_ecommerce.order_items", name="order_items"),
        Table(id="example_project_id.demo_ecommerce.products", name="products"),
    ]
    column_nodes = [
        Column(id="example_project_id.demo_ecommerce.orders.order_id", name="order_id"),
        Column(id="example_project_id.demo_ecommerce.orders.order_date", name="order_date"),
        Column(id="example_project_id.demo_ecommerce.orders.customer_id", name="customer_id"),
        Column(id="example_project_id.demo_ecommerce.orders.total_amount", name="total_amount"),
        Column(
            id="example_project_id.demo_ecommerce.order_items.order_item_id", name="order_item_id"
        ),
        Column(id="example_project_id.demo_ecommerce.order_items.order_id", name="order_id"),
        Column(id="example_project_id.demo_ecommerce.order_items.product_id", name="product_id"),
        Column(id="example_project_id.demo_ecommerce.order_items.quantity", name="quantity"),
    ]
    has_schema_relationships = [
        HasSchema(database_id="example_project_id", schema_id="example_project_id.demo_ecommerce")
    ]
    has_table_relationships = [
        HasTable(
            schema_id="example_project_id.demo_ecommerce",
            table_id="example_project_id.demo_ecommerce.orders",
        ),
        HasTable(
            schema_id="example_project_id.demo_ecommerce",
            table_id="example_project_id.demo_ecommerce.order_items",
        ),
        HasTable(
            schema_id="example_project_id.demo_ecommerce",
            table_id="example_project_id.demo_ecommerce.products",
        ),
    ]
    has_column_relationships = [
        HasColumn(
            table_id="example_project_id.demo_ecommerce.orders",
            column_id="example_project_id.demo_ecommerce.orders.order_id",
        ),
        HasColumn(
            table_id="example_project_id.demo_ecommerce.orders",
            column_id="example_project_id.demo_ecommerce.orders.order_date",
        ),
        HasColumn(
            table_id="example_project_id.demo_ecommerce.orders",
            column_id="example_project_id.demo_ecommerce.orders.customer_id",
        ),
        HasColumn(
            table_id="example_project_id.demo_ecommerce.orders",
            column_id="example_project_id.demo_ecommerce.orders.total_amount",
        ),
        HasColumn(
            table_id="example_project_id.demo_ecommerce.order_items",
            column_id="example_project_id.demo_ecommerce.order_items.order_item_id",
        ),
        HasColumn(
            table_id="example_project_id.demo_ecommerce.order_items",
            column_id="example_project_id.demo_ecommerce.order_items.order_id",
        ),
        HasColumn(
            table_id="example_project_id.demo_ecommerce.order_items",
            column_id="example_project_id.demo_ecommerce.order_items.product_id",
        ),
        HasColumn(
            table_id="example_project_id.demo_ecommerce.order_items",
            column_id="example_project_id.demo_ecommerce.order_items.quantity",
        ),
    ]
    references_relationships = [
        References(
            source_column_id="example_project_id.demo_ecommerce.orders.order_id",
            target_column_id="example_project_id.demo_ecommerce.order_items.order_id",
            criteria="o.order_id = oi.order_id",
        ),
        References(
            source_column_id="example_project_id.demo_ecommerce.order_items.product_id",
            target_column_id="example_project_id.demo_ecommerce.products.product_id",
            criteria="oi.product_id = p.product_id",
        ),
    ]
    query_nodes = [
        Query(
            id="e45079ee36de11097b070f3e0b6dbc5d365827af3c19a3737cf3331daca26e76",
            content="SELECT o.order_id, oi.order_item_id, p.product_name, oi.quantity, oi.price\nFROM `example-project-id.demo_ecommerce.orders` AS o\nJOIN `example-project-id.demo_ecommerce.order_items` AS oi ON o.order_id = oi.order_id\nJOIN `example-project-id.demo_ecommerce.products` AS p ON oi.product_id = p.product_id;",
        )
    ]
    uses_table_relationships = [
        UsesTable(
            query_id="e45079ee36de11097b070f3e0b6dbc5d365827af3c19a3737cf3331daca26e76",
            table_id="example_project_id.demo_ecommerce.orders",
        ),
        UsesTable(
            query_id="e45079ee36de11097b070f3e0b6dbc5d365827af3c19a3737cf3331daca26e76",
            table_id="example_project_id.demo_ecommerce.order_items",
        ),
        UsesTable(
            query_id="e45079ee36de11097b070f3e0b6dbc5d365827af3c19a3737cf3331daca26e76",
            table_id="example_project_id.demo_ecommerce.products",
        ),
    ]
    uses_column_relationships = [
        UsesColumn(
            query_id="e45079ee36de11097b070f3e0b6dbc5d365827af3c19a3737cf3331daca26e76",
            column_id="example_project_id.demo_ecommerce.orders.order_id",
        ),
        UsesColumn(
            query_id="e45079ee36de11097b070f3e0b6dbc5d365827af3c19a3737cf3331daca26e76",
            column_id="example_project_id.demo_ecommerce.orders.order_date",
        ),
        UsesColumn(
            query_id="e45079ee36de11097b070f3e0b6dbc5d365827af3c19a3737cf3331daca26e76",
            column_id="example_project_id.demo_ecommerce.orders.customer_id",
        ),
        UsesColumn(
            query_id="e45079ee36de11097b070f3e0b6dbc5d365827af3c19a3737cf3331daca26e76",
            column_id="example_project_id.demo_ecommerce.orders.total_amount",
        ),
        UsesColumn(
            query_id="e45079ee36de11097b070f3e0b6dbc5d365827af3c19a3737cf3331daca26e76",
            column_id="example_project_id.demo_ecommerce.order_items.order_item_id",
        ),
        UsesColumn(
            query_id="e45079ee36de11097b070f3e0b6dbc5d365827af3c19a3737cf3331daca26e76",
            column_id="example_project_id.demo_ecommerce.order_items.order_id",
        ),
        UsesColumn(
            query_id="e45079ee36de11097b070f3e0b6dbc5d365827af3c19a3737cf3331daca26e76",
            column_id="example_project_id.demo_ecommerce.order_items.product_id",
        ),
        UsesColumn(
            query_id="e45079ee36de11097b070f3e0b6dbc5d365827af3c19a3737cf3331daca26e76",
            column_id="example_project_id.demo_ecommerce.order_items.quantity",
        ),
    ]
    t._node_cache["database_nodes"] = database_nodes
    t._node_cache["schema_nodes"] = schema_nodes
    t._node_cache["table_nodes"] = table_nodes
    t._node_cache["column_nodes"] = column_nodes
    t._node_cache["query_nodes"] = query_nodes
    t._relationships_cache["has_schema_relationships"] = has_schema_relationships
    t._relationships_cache["has_table_relationships"] = has_table_relationships
    t._relationships_cache["has_column_relationships"] = has_column_relationships
    t._relationships_cache["references_relationships"] = references_relationships
    t._relationships_cache["uses_table_relationships"] = uses_table_relationships
    t._relationships_cache["uses_column_relationships"] = uses_column_relationships

    return t
