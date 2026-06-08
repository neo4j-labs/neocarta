from neocarta.connectors.query_log.extract import QueryLogExtractor
from neocarta.connectors.query_log.transform import QueryLogTransformer


def test_transform_to_database_nodes(
    query_log_transformer: QueryLogTransformer, query_log_extractor_with_cache: QueryLogExtractor
):
    query_log_transformer.transform_to_database_nodes(
        query_log_extractor_with_cache.database_info, cache=True
    )
    assert len(query_log_transformer.database_nodes) == 1
    assert query_log_transformer.database_nodes[0].id == "example_project_id"
    assert query_log_transformer.database_nodes[0].name == "example-project-id"
    assert query_log_transformer.database_nodes[0].platform == "GCP"
    assert query_log_transformer.database_nodes[0].service == "BIGQUERY"


def test_transform_to_schema_nodes(
    query_log_transformer: QueryLogTransformer, query_log_extractor_with_cache: QueryLogExtractor
):
    query_log_transformer.transform_to_schema_nodes(
        query_log_extractor_with_cache.schema_info, cache=True
    )
    assert len(query_log_transformer.schema_nodes) == 1
    assert query_log_transformer.schema_nodes[0].id == "example_project_id.demo_ecommerce"
    assert query_log_transformer.schema_nodes[0].name == "demo_ecommerce"


def test_transform_to_table_nodes(
    query_log_transformer: QueryLogTransformer, query_log_extractor_with_cache: QueryLogExtractor
):
    query_log_transformer.transform_to_table_nodes(
        query_log_extractor_with_cache.table_info, cache=True
    )
    assert len(query_log_transformer.table_nodes) == 3
    assert query_log_transformer.table_nodes[0].id == "example_project_id.demo_ecommerce.orders"
    assert query_log_transformer.table_nodes[0].name == "orders"
    assert (
        query_log_transformer.table_nodes[1].id == "example_project_id.demo_ecommerce.order_items"
    )
    assert query_log_transformer.table_nodes[1].name == "order_items"
    assert query_log_transformer.table_nodes[2].id == "example_project_id.demo_ecommerce.products"
    assert query_log_transformer.table_nodes[2].name == "products"


def test_transform_to_column_nodes(
    query_log_transformer: QueryLogTransformer, query_log_extractor_with_cache: QueryLogExtractor
):
    query_log_transformer.transform_to_column_nodes(
        query_log_extractor_with_cache.column_info, cache=True
    )
    assert len(query_log_transformer.column_nodes) == 8
    assert (
        query_log_transformer.column_nodes[0].id
        == "example_project_id.demo_ecommerce.orders.order_id"
    )
    assert query_log_transformer.column_nodes[0].name == "order_id"
    assert (
        query_log_transformer.column_nodes[1].id
        == "example_project_id.demo_ecommerce.orders.order_date"
    )
    assert query_log_transformer.column_nodes[1].name == "order_date"
    assert (
        query_log_transformer.column_nodes[2].id
        == "example_project_id.demo_ecommerce.orders.customer_id"
    )
    assert query_log_transformer.column_nodes[2].name == "customer_id"
    assert (
        query_log_transformer.column_nodes[3].id
        == "example_project_id.demo_ecommerce.orders.total_amount"
    )
    assert query_log_transformer.column_nodes[3].name == "total_amount"
    assert (
        query_log_transformer.column_nodes[4].id
        == "example_project_id.demo_ecommerce.order_items.order_item_id"
    )
    assert query_log_transformer.column_nodes[4].name == "order_item_id"
    assert (
        query_log_transformer.column_nodes[5].id
        == "example_project_id.demo_ecommerce.order_items.order_id"
    )
    assert query_log_transformer.column_nodes[5].name == "order_id"
    assert (
        query_log_transformer.column_nodes[6].id
        == "example_project_id.demo_ecommerce.order_items.product_id"
    )
    assert query_log_transformer.column_nodes[6].name == "product_id"
    assert (
        query_log_transformer.column_nodes[7].id
        == "example_project_id.demo_ecommerce.order_items.quantity"
    )
    assert query_log_transformer.column_nodes[7].name == "quantity"


def test_transform_to_has_schema_relationships(
    query_log_transformer: QueryLogTransformer, query_log_extractor_with_cache: QueryLogExtractor
):
    query_log_transformer.transform_to_has_schema_relationships(
        query_log_extractor_with_cache.schema_info, cache=True
    )
    assert len(query_log_transformer.has_schema_relationships) == 1
    assert query_log_transformer.has_schema_relationships[0].database_id == "example_project_id"
    assert (
        query_log_transformer.has_schema_relationships[0].schema_id
        == "example_project_id.demo_ecommerce"
    )


def test_transform_to_has_table_relationships(
    query_log_transformer: QueryLogTransformer, query_log_extractor_with_cache: QueryLogExtractor
):
    query_log_transformer.transform_to_has_table_relationships(
        query_log_extractor_with_cache.table_info, cache=True
    )
    assert len(query_log_transformer.has_table_relationships) == 3
    assert (
        query_log_transformer.has_table_relationships[0].schema_id
        == "example_project_id.demo_ecommerce"
    )
    assert (
        query_log_transformer.has_table_relationships[0].table_id
        == "example_project_id.demo_ecommerce.orders"
    )
    assert (
        query_log_transformer.has_table_relationships[1].schema_id
        == "example_project_id.demo_ecommerce"
    )
    assert (
        query_log_transformer.has_table_relationships[1].table_id
        == "example_project_id.demo_ecommerce.order_items"
    )
    assert (
        query_log_transformer.has_table_relationships[2].schema_id
        == "example_project_id.demo_ecommerce"
    )
    assert (
        query_log_transformer.has_table_relationships[2].table_id
        == "example_project_id.demo_ecommerce.products"
    )


def test_transform_to_has_column_relationships(
    query_log_transformer: QueryLogTransformer, query_log_extractor_with_cache: QueryLogExtractor
):
    query_log_transformer.transform_to_has_column_relationships(
        query_log_extractor_with_cache.column_info, cache=True
    )
    assert len(query_log_transformer.has_column_relationships) == 8
    assert (
        query_log_transformer.has_column_relationships[0].table_id
        == "example_project_id.demo_ecommerce.orders"
    )
    assert (
        query_log_transformer.has_column_relationships[0].column_id
        == "example_project_id.demo_ecommerce.orders.order_id"
    )
    assert (
        query_log_transformer.has_column_relationships[1].table_id
        == "example_project_id.demo_ecommerce.orders"
    )
    assert (
        query_log_transformer.has_column_relationships[1].column_id
        == "example_project_id.demo_ecommerce.orders.order_date"
    )
    assert (
        query_log_transformer.has_column_relationships[2].table_id
        == "example_project_id.demo_ecommerce.orders"
    )
    assert (
        query_log_transformer.has_column_relationships[2].column_id
        == "example_project_id.demo_ecommerce.orders.customer_id"
    )
    assert (
        query_log_transformer.has_column_relationships[3].table_id
        == "example_project_id.demo_ecommerce.orders"
    )
    assert (
        query_log_transformer.has_column_relationships[3].column_id
        == "example_project_id.demo_ecommerce.orders.total_amount"
    )
    assert (
        query_log_transformer.has_column_relationships[4].table_id
        == "example_project_id.demo_ecommerce.order_items"
    )
    assert (
        query_log_transformer.has_column_relationships[4].column_id
        == "example_project_id.demo_ecommerce.order_items.order_item_id"
    )
    assert (
        query_log_transformer.has_column_relationships[5].table_id
        == "example_project_id.demo_ecommerce.order_items"
    )
    assert (
        query_log_transformer.has_column_relationships[5].column_id
        == "example_project_id.demo_ecommerce.order_items.order_id"
    )
    assert (
        query_log_transformer.has_column_relationships[6].table_id
        == "example_project_id.demo_ecommerce.order_items"
    )
    assert (
        query_log_transformer.has_column_relationships[6].column_id
        == "example_project_id.demo_ecommerce.order_items.product_id"
    )
    assert (
        query_log_transformer.has_column_relationships[7].table_id
        == "example_project_id.demo_ecommerce.order_items"
    )
    assert (
        query_log_transformer.has_column_relationships[7].column_id
        == "example_project_id.demo_ecommerce.order_items.quantity"
    )


def test_transform_to_reference_relationships(
    query_log_transformer: QueryLogTransformer, query_log_extractor_with_cache: QueryLogExtractor
):
    query_log_transformer.transform_to_references_relationships(
        query_log_extractor_with_cache.column_references_info, cache=True
    )
    assert len(query_log_transformer.references_relationships) == 2
    assert (
        query_log_transformer.references_relationships[0].source_column_id
        == "example_project_id.demo_ecommerce.orders.order_id"
    )
    assert (
        query_log_transformer.references_relationships[0].target_column_id
        == "example_project_id.demo_ecommerce.order_items.order_id"
    )
    assert (
        query_log_transformer.references_relationships[1].source_column_id
        == "example_project_id.demo_ecommerce.order_items.product_id"
    )
    assert (
        query_log_transformer.references_relationships[1].target_column_id
        == "example_project_id.demo_ecommerce.products.product_id"
    )


def test_transform_to_query_nodes(
    query_log_transformer: QueryLogTransformer, query_log_extractor_with_cache: QueryLogExtractor
):
    query_log_transformer.transform_to_query_nodes(
        query_log_extractor_with_cache.query_info, cache=True
    )
    assert len(query_log_transformer.query_nodes) == 1
    assert (
        query_log_transformer.query_nodes[0].id
        == "e45079ee36de11097b070f3e0b6dbc5d365827af3c19a3737cf3331daca26e76"
    )
    assert "SELECT o.order_id" in query_log_transformer.query_nodes[0].content


def test_transform_to_uses_table_relationships(
    query_log_transformer: QueryLogTransformer, query_log_extractor_with_cache: QueryLogExtractor
):
    query_log_transformer.transform_to_uses_table_relationships(
        query_log_extractor_with_cache.query_table_info, cache=True
    )
    assert len(query_log_transformer.uses_table_relationships) == 3
    assert (
        query_log_transformer.uses_table_relationships[0].query_id
        == "e45079ee36de11097b070f3e0b6dbc5d365827af3c19a3737cf3331daca26e76"
    )
    assert (
        query_log_transformer.uses_table_relationships[0].table_id
        == "example_project_id.demo_ecommerce.orders"
    )
    assert (
        query_log_transformer.uses_table_relationships[1].query_id
        == "e45079ee36de11097b070f3e0b6dbc5d365827af3c19a3737cf3331daca26e76"
    )
    assert (
        query_log_transformer.uses_table_relationships[1].table_id
        == "example_project_id.demo_ecommerce.order_items"
    )
    assert (
        query_log_transformer.uses_table_relationships[2].query_id
        == "e45079ee36de11097b070f3e0b6dbc5d365827af3c19a3737cf3331daca26e76"
    )
    assert (
        query_log_transformer.uses_table_relationships[2].table_id
        == "example_project_id.demo_ecommerce.products"
    )


def test_transform_to_uses_column_relationships(
    query_log_transformer: QueryLogTransformer, query_log_extractor_with_cache: QueryLogExtractor
):
    query_log_transformer.transform_to_uses_column_relationships(
        query_log_extractor_with_cache.query_column_info, cache=True
    )
    assert len(query_log_transformer.uses_column_relationships) == 8
    assert (
        query_log_transformer.uses_column_relationships[0].query_id
        == "e45079ee36de11097b070f3e0b6dbc5d365827af3c19a3737cf3331daca26e76"
    )
    assert (
        query_log_transformer.uses_column_relationships[0].column_id
        == "example_project_id.demo_ecommerce.orders.order_id"
    )
    assert (
        query_log_transformer.uses_column_relationships[1].query_id
        == "e45079ee36de11097b070f3e0b6dbc5d365827af3c19a3737cf3331daca26e76"
    )
    assert (
        query_log_transformer.uses_column_relationships[1].column_id
        == "example_project_id.demo_ecommerce.orders.order_date"
    )


def test_get_database_nodes(query_log_transformer_with_cache: QueryLogTransformer):
    assert len(query_log_transformer_with_cache.database_nodes) == 1
    assert query_log_transformer_with_cache.database_nodes[0].id == "example_project_id"
    assert query_log_transformer_with_cache.database_nodes[0].name == "example-project-id"
    assert query_log_transformer_with_cache.database_nodes[0].platform == "GCP"
    assert query_log_transformer_with_cache.database_nodes[0].service == "BIGQUERY"


def test_get_schema_nodes(query_log_transformer_with_cache: QueryLogTransformer):
    assert len(query_log_transformer_with_cache.schema_nodes) == 1
    assert (
        query_log_transformer_with_cache.schema_nodes[0].id == "example_project_id.demo_ecommerce"
    )
    assert query_log_transformer_with_cache.schema_nodes[0].name == "demo_ecommerce"


def test_get_table_nodes(query_log_transformer_with_cache: QueryLogTransformer):
    assert len(query_log_transformer_with_cache.table_nodes) == 3
    assert (
        query_log_transformer_with_cache.table_nodes[0].id
        == "example_project_id.demo_ecommerce.orders"
    )
    assert query_log_transformer_with_cache.table_nodes[0].name == "orders"
    assert (
        query_log_transformer_with_cache.table_nodes[1].id
        == "example_project_id.demo_ecommerce.order_items"
    )
    assert query_log_transformer_with_cache.table_nodes[1].name == "order_items"
    assert (
        query_log_transformer_with_cache.table_nodes[2].id
        == "example_project_id.demo_ecommerce.products"
    )
    assert query_log_transformer_with_cache.table_nodes[2].name == "products"


def test_get_column_nodes(query_log_transformer_with_cache: QueryLogTransformer):
    assert len(query_log_transformer_with_cache.column_nodes) == 8
    assert (
        query_log_transformer_with_cache.column_nodes[0].id
        == "example_project_id.demo_ecommerce.orders.order_id"
    )
    assert query_log_transformer_with_cache.column_nodes[0].name == "order_id"
    assert (
        query_log_transformer_with_cache.column_nodes[1].id
        == "example_project_id.demo_ecommerce.orders.order_date"
    )
    assert query_log_transformer_with_cache.column_nodes[1].name == "order_date"
    assert (
        query_log_transformer_with_cache.column_nodes[2].id
        == "example_project_id.demo_ecommerce.orders.customer_id"
    )
    assert query_log_transformer_with_cache.column_nodes[2].name == "customer_id"
    assert (
        query_log_transformer_with_cache.column_nodes[3].id
        == "example_project_id.demo_ecommerce.orders.total_amount"
    )


def test_get_has_schema_relationships(query_log_transformer_with_cache: QueryLogTransformer):
    assert len(query_log_transformer_with_cache.has_schema_relationships) == 1
    assert (
        query_log_transformer_with_cache.has_schema_relationships[0].database_id
        == "example_project_id"
    )
    assert (
        query_log_transformer_with_cache.has_schema_relationships[0].schema_id
        == "example_project_id.demo_ecommerce"
    )


def test_get_has_table_relationships(query_log_transformer_with_cache: QueryLogTransformer):
    assert len(query_log_transformer_with_cache.has_table_relationships) == 3
    assert (
        query_log_transformer_with_cache.has_table_relationships[0].schema_id
        == "example_project_id.demo_ecommerce"
    )
    assert (
        query_log_transformer_with_cache.has_table_relationships[0].table_id
        == "example_project_id.demo_ecommerce.orders"
    )
    assert (
        query_log_transformer_with_cache.has_table_relationships[1].schema_id
        == "example_project_id.demo_ecommerce"
    )
    assert (
        query_log_transformer_with_cache.has_table_relationships[1].table_id
        == "example_project_id.demo_ecommerce.order_items"
    )
    assert (
        query_log_transformer_with_cache.has_table_relationships[2].schema_id
        == "example_project_id.demo_ecommerce"
    )
    assert (
        query_log_transformer_with_cache.has_table_relationships[2].table_id
        == "example_project_id.demo_ecommerce.products"
    )


def test_get_has_column_relationships(query_log_transformer_with_cache: QueryLogTransformer):
    assert len(query_log_transformer_with_cache.has_column_relationships) == 8
    assert (
        query_log_transformer_with_cache.has_column_relationships[0].table_id
        == "example_project_id.demo_ecommerce.orders"
    )
    assert (
        query_log_transformer_with_cache.has_column_relationships[0].column_id
        == "example_project_id.demo_ecommerce.orders.order_id"
    )
    assert (
        query_log_transformer_with_cache.has_column_relationships[1].table_id
        == "example_project_id.demo_ecommerce.orders"
    )
    assert (
        query_log_transformer_with_cache.has_column_relationships[1].column_id
        == "example_project_id.demo_ecommerce.orders.order_date"
    )
    assert (
        query_log_transformer_with_cache.has_column_relationships[2].table_id
        == "example_project_id.demo_ecommerce.orders"
    )
    assert (
        query_log_transformer_with_cache.has_column_relationships[2].column_id
        == "example_project_id.demo_ecommerce.orders.customer_id"
    )


def test_get_reference_relationships(query_log_transformer_with_cache: QueryLogTransformer):
    assert len(query_log_transformer_with_cache.references_relationships) == 2
    assert (
        query_log_transformer_with_cache.references_relationships[0].source_column_id
        == "example_project_id.demo_ecommerce.orders.order_id"
    )
    assert (
        query_log_transformer_with_cache.references_relationships[0].target_column_id
        == "example_project_id.demo_ecommerce.order_items.order_id"
    )
    assert (
        query_log_transformer_with_cache.references_relationships[1].source_column_id
        == "example_project_id.demo_ecommerce.order_items.product_id"
    )
    assert (
        query_log_transformer_with_cache.references_relationships[1].target_column_id
        == "example_project_id.demo_ecommerce.products.product_id"
    )


def test_get_query_nodes(query_log_transformer_with_cache: QueryLogTransformer):
    assert len(query_log_transformer_with_cache.query_nodes) == 1
    assert (
        query_log_transformer_with_cache.query_nodes[0].id
        == "e45079ee36de11097b070f3e0b6dbc5d365827af3c19a3737cf3331daca26e76"
    )
    assert "SELECT o.order_id" in query_log_transformer_with_cache.query_nodes[0].content


def test_get_uses_table_relationships(query_log_transformer_with_cache: QueryLogTransformer):
    assert len(query_log_transformer_with_cache.uses_table_relationships) == 3
    assert (
        query_log_transformer_with_cache.uses_table_relationships[0].query_id
        == "e45079ee36de11097b070f3e0b6dbc5d365827af3c19a3737cf3331daca26e76"
    )
    assert (
        query_log_transformer_with_cache.uses_table_relationships[0].table_id
        == "example_project_id.demo_ecommerce.orders"
    )
    assert (
        query_log_transformer_with_cache.uses_table_relationships[1].query_id
        == "e45079ee36de11097b070f3e0b6dbc5d365827af3c19a3737cf3331daca26e76"
    )
    assert (
        query_log_transformer_with_cache.uses_table_relationships[1].table_id
        == "example_project_id.demo_ecommerce.order_items"
    )
    assert (
        query_log_transformer_with_cache.uses_table_relationships[2].query_id
        == "e45079ee36de11097b070f3e0b6dbc5d365827af3c19a3737cf3331daca26e76"
    )
    assert (
        query_log_transformer_with_cache.uses_table_relationships[2].table_id
        == "example_project_id.demo_ecommerce.products"
    )


def test_get_uses_column_relationships(query_log_transformer_with_cache: QueryLogTransformer):
    assert len(query_log_transformer_with_cache.uses_column_relationships) == 8
    assert (
        query_log_transformer_with_cache.uses_column_relationships[0].query_id
        == "e45079ee36de11097b070f3e0b6dbc5d365827af3c19a3737cf3331daca26e76"
    )
    assert (
        query_log_transformer_with_cache.uses_column_relationships[0].column_id
        == "example_project_id.demo_ecommerce.orders.order_id"
    )
    assert (
        query_log_transformer_with_cache.uses_column_relationships[1].query_id
        == "e45079ee36de11097b070f3e0b6dbc5d365827af3c19a3737cf3331daca26e76"
    )
    assert (
        query_log_transformer_with_cache.uses_column_relationships[1].column_id
        == "example_project_id.demo_ecommerce.orders.order_date"
    )


def test_transform_to_cte_nodes(query_log_transformer: QueryLogTransformer):
    import pandas as pd

    cte_info = pd.DataFrame(
        [
            {
                "cte_id": "qid-1.paid",
                "cte_name": "paid",
                "definition": "SELECT invoice_id FROM proj.ds.invoices WHERE status = 'PAID'",
                "query_id": "qid-1",
            },
            {
                "cte_id": "qid-1.won",
                "cte_name": "won",
                "definition": "SELECT opp_id FROM proj.ds.opportunities WHERE stage = 'WON'",
                "query_id": "qid-1",
            },
        ]
    )
    nodes = query_log_transformer.transform_to_cte_nodes(cte_info, cache=True)

    assert len(nodes) == 2
    assert nodes[0].id == "qid-1.paid"
    assert nodes[0].name == "paid"
    assert "invoices" in nodes[0].definition
    assert nodes[0].query_id == "qid-1"


def test_transform_to_cte_nodes_empty(query_log_transformer: QueryLogTransformer):
    import pandas as pd

    nodes = query_log_transformer.transform_to_cte_nodes(pd.DataFrame(), cache=True)
    assert nodes == []


def test_transform_to_defines_relationships(query_log_transformer: QueryLogTransformer):
    import pandas as pd

    cte_info = pd.DataFrame(
        [
            {
                "cte_id": "qid-1.paid",
                "cte_name": "paid",
                "definition": "SELECT 1",
                "query_id": "qid-1",
            }
        ]
    )
    rels = query_log_transformer.transform_to_defines_relationships(cte_info, cache=True)
    assert len(rels) == 1
    assert rels[0].query_id == "qid-1"
    assert rels[0].cte_id == "qid-1.paid"
