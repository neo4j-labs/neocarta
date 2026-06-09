"""Unit tests for CollibraSchemaTransformer: subtype nodes, ids, hierarchy, filtering."""

import pytest

from neocarta.connectors.collibra.schema.connector import CollibraSchemaConnector
from neocarta.connectors.collibra.schema.extract import CollibraSchemaExtractor
from neocarta.connectors.collibra.schema.transform import CollibraSchemaTransformer
from neocarta.data_model.rdbms import (
    CollibraColumn,
    CollibraDatabase,
    CollibraSchema,
    CollibraTable,
)
from neocarta.enums import NodeLabel, RelationshipType
from neocarta.warnings import UnresolvedCollibraParentWarning


def _transform(fake_client, **kwargs) -> CollibraSchemaTransformer:
    include_nodes = kwargs.get("include_nodes")
    include_relationships = kwargs.get("include_relationships")
    extractor = CollibraSchemaExtractor(fake_client)
    # The schema extractor only filters node caches; relationship filtering is applied
    # at transform time (relations are still fetched to resolve column parents).
    extractor.extract(include_nodes=include_nodes)
    transformer = CollibraSchemaTransformer()
    transformer.transform_all(extractor, include_nodes, include_relationships)
    return transformer


def test_builds_subtype_nodes(fake_client):
    """Communities/domains/assets become Collibra* subtype instances."""
    t = _transform(fake_client)
    assert isinstance(t.database_nodes[0], CollibraDatabase)
    assert isinstance(t.schema_nodes[0], CollibraSchema)
    assert isinstance(t.table_nodes[0], CollibraTable)
    assert all(isinstance(c, CollibraColumn) for c in t.column_nodes)


def test_node_ids_and_collibra_metadata(fake_client):
    """Deterministic ids are generated and collibra_id/status are carried through."""
    t = _transform(fake_client)
    db = t.database_nodes[0]
    table = t.table_nodes[0]
    column = next(c for c in t.column_nodes if c.name == "order_id")
    assert db.id == "sales"
    assert db.collibra_id == "comm-sales"
    assert table.id == "sales.warehouse.orders"
    assert table.collibra_id == "a-orders"
    assert table.status == "Accepted"
    assert table.collibra_asset_type == "Table"
    assert column.id == "sales.warehouse.orders.order_id"
    assert column.collibra_id == "a-orderid"


def test_hierarchy_relationships(fake_client):
    """HAS_SCHEMA / HAS_TABLE / HAS_COLUMN wire the hierarchy by deterministic id."""
    t = _transform(fake_client)
    assert (t.has_schema_relationships[0].database_id, t.has_schema_relationships[0].schema_id) == (
        "sales",
        "sales.warehouse",
    )
    assert t.has_table_relationships[0].table_id == "sales.warehouse.orders"
    assert {r.column_id for r in t.has_column_relationships} == {
        "sales.warehouse.orders.order_id",
        "sales.warehouse.orders.customer_id",
    }
    assert all(r.table_id == "sales.warehouse.orders" for r in t.has_column_relationships)


def test_include_nodes_filters_output(fake_client):
    """include_nodes=[TABLE] emits only table nodes (no db/schema/column nodes)."""
    t = _transform(fake_client, include_nodes=[NodeLabel.TABLE])
    assert t.table_nodes
    assert not t.database_nodes
    assert not t.schema_nodes
    assert not t.column_nodes


def test_include_relationships_filters_output(fake_client):
    """include_relationships=[HAS_COLUMN] emits only HAS_COLUMN edges."""
    t = _transform(fake_client, include_relationships=[RelationshipType.HAS_COLUMN])
    assert t.has_column_relationships
    assert not t.has_schema_relationships
    assert not t.has_table_relationships


def test_columns_only_still_resolve_parent_table(fake_client):
    """include_nodes=[COLUMN] yields columns with correctly resolved parent-table ids."""
    t = _transform(fake_client, include_nodes=[NodeLabel.COLUMN])
    assert not t.table_nodes
    assert {c.id for c in t.column_nodes} == {
        "sales.warehouse.orders.order_id",
        "sales.warehouse.orders.customer_id",
    }


def test_columns_without_parent_table_warn_and_skip(fake_client):
    """Columns whose parent table is out of scope are skipped with a warning."""
    # Scope to Column assets only, so the parent tables are never extracted.
    extractor = CollibraSchemaExtractor(fake_client)
    extractor.extract(asset_type_names=["Column"])
    transformer = CollibraSchemaTransformer()
    with pytest.warns(UnresolvedCollibraParentWarning, match="order_id"):
        transformer.transform_all(extractor)
    assert transformer.column_nodes == []
    assert transformer.has_column_relationships == []


def test_connector_end_to_end_load_calls_loader(fake_client):
    """The connector drives extract→transform→load using the Collibra loader methods."""
    from unittest.mock import MagicMock

    driver = MagicMock()
    driver.execute_query.return_value = (None, MagicMock(), None)
    connector = CollibraSchemaConnector(client=fake_client, neo4j_driver=driver)
    connector.loader = MagicMock()
    connector.extract()
    connector.transform()
    connector.load()
    connector.loader.load_collibra_table_nodes.assert_called_once()
    connector.loader.load_collibra_column_nodes.assert_called_once()
    connector.loader.load_has_column_relationships.assert_called_once()
