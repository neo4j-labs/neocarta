"""Unit tests for UnityCatalogSchemaTransformer (ids + node/edge construction)."""


def test_database_nodes(extractor_with_cache, transformer):
    nodes = transformer.transform_to_database_nodes(extractor_with_cache.catalog_info)
    assert len(nodes) == 1
    assert nodes[0].id == "main"
    assert nodes[0].name == "main"
    assert nodes[0].service == "UNITY_CATALOG"
    assert nodes[0].platform == "DATABRICKS"


def test_schema_nodes(extractor_with_cache, transformer):
    nodes = transformer.transform_to_schema_nodes(extractor_with_cache.schema_info)
    assert {node.id for node in nodes} == {"main.sales", "main.ops"}


def test_table_nodes(extractor_with_cache, transformer):
    nodes = transformer.transform_to_table_nodes(extractor_with_cache.table_info)
    assert {node.id for node in nodes} == {"main.sales.orders", "main.sales.customers_view"}


def test_column_nodes_ids_types_and_key_flags(extractor_with_cache, transformer):
    nodes = transformer.transform_to_column_nodes(extractor_with_cache.column_info)
    by_id = {node.id: node for node in nodes}

    assert "main.sales.orders.order_id" in by_id
    amount = by_id["main.sales.orders.amount"]
    assert amount.type == "decimal(10,2)"
    assert amount.nullable is True
    # The open Unity Catalog API exposes no constraints; key flags are left null (unknown).
    assert all(node.is_primary_key is None for node in nodes)
    assert all(node.is_foreign_key is None for node in nodes)


def test_has_schema_relationships(extractor_with_cache, transformer):
    rels = transformer.transform_to_has_schema_relationships(extractor_with_cache.schema_info)
    pairs = {(rel.database_id, rel.schema_id) for rel in rels}
    assert ("main", "main.sales") in pairs
    assert ("main", "main.ops") in pairs


def test_has_table_relationships(extractor_with_cache, transformer):
    rels = transformer.transform_to_has_table_relationships(extractor_with_cache.table_info)
    pairs = {(rel.schema_id, rel.table_id) for rel in rels}
    assert ("main.sales", "main.sales.orders") in pairs


def test_has_column_relationships(extractor_with_cache, transformer):
    rels = transformer.transform_to_has_column_relationships(extractor_with_cache.column_info)
    pairs = {(rel.table_id, rel.column_id) for rel in rels}
    assert ("main.sales.orders", "main.sales.orders.order_id") in pairs
    assert len(rels) == 3
