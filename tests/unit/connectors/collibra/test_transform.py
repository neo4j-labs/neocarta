"""Unit tests for CollibraTransformer: type mapping, asset conversion, relations."""

from typing import ClassVar

import pandas as pd
import pytest

from neocarta.connectors.collibra.transform import CollibraTransformer
from neocarta.data_model.rdbms import (
    BusinessTerm,
    CatalogAsset,
    Category,
    Column,
    Database,
    FlowsInto,
    Glossary,
    HasColumn,
    Schema,
    Table,
    TaggedWith,
)


class _FakeExtractor:
    """Minimal extractor stub that returns pre-built DataFrames."""

    asset_types: ClassVar[dict[str, str]] = {
        "at-table": "Table",
        "at-column": "Column",
        "at-business-term": "Business Term",
        "at-data-domain": "Data Domain",
        "at-unknown": "Custom Report Layout",
    }
    domain_types: ClassVar[dict[str, str]] = {
        "dt-physical": "Physical Data Dictionary",
        "dt-glossary": "Business Glossary",
    }
    relation_types: ClassVar[dict[str, str]] = {
        "rt-contains-col": "Table contains Column",
        "rt-tagged-with": "Data Attribute / Data Element / Business Term association",
    }

    community_info = pd.DataFrame(
        [
            {
                "community_id": "comm-finance",
                "community_name": "Finance",
                "description": "Finance div",
            },
        ]
    )

    domain_info = pd.DataFrame(
        [
            {
                "domain_id": "dom-schema-1",
                "domain_name": "Finance Schema",
                "description": None,
                "community_id": "comm-finance",
                "domain_type_id": "dt-physical",
                "domain_type_name": "Physical Data Dictionary",
            },
            {
                "domain_id": "dom-glossary-1",
                "domain_name": "Finance Glossary",
                "description": None,
                "community_id": "comm-finance",
                "domain_type_id": "dt-glossary",
                "domain_type_name": "Business Glossary",
            },
        ]
    )

    asset_info = pd.DataFrame(
        [
            {
                "asset_id": "asset-table-1",
                "asset_name": "Orders",
                "domain_id": "dom-schema-1",
                "asset_type_id": "at-table",
                "asset_type_name": "Table",
                "status": "Accepted",
            },
            {
                "asset_id": "asset-col-1",
                "asset_name": "order_id",
                "domain_id": "dom-schema-1",
                "asset_type_id": "at-column",
                "asset_type_name": "Column",
                "status": "Accepted",
            },
            {
                "asset_id": "asset-bt-1",
                "asset_name": "Revenue",
                "domain_id": "dom-glossary-1",
                "asset_type_id": "at-business-term",
                "asset_type_name": "Business Term",
                "status": "Draft",
            },
            {
                "asset_id": "asset-dd-1",
                "asset_name": "Financial Data",
                "domain_id": "dom-glossary-1",
                "asset_type_id": "at-data-domain",
                "asset_type_name": "Data Domain",
                "status": None,
            },
            {
                "asset_id": "asset-unknown-1",
                "asset_name": "Custom Layout A",
                "domain_id": "dom-schema-1",
                "asset_type_id": "at-unknown",
                "asset_type_name": "Custom Report Layout",
                "status": None,
            },
        ]
    )

    attribute_info = pd.DataFrame(
        [
            {
                "attribute_id": "attr-1",
                "asset_id": "asset-table-1",
                "attribute_type": "Description",
                "value": "All customer orders",
            },
            {
                "attribute_id": "attr-2",
                "asset_id": "asset-bt-1",
                "attribute_type": "Definition",
                "value": "Total income from sales",
            },
        ]
    )

    relation_info = pd.DataFrame(
        [
            {
                "relation_id": "rel-1",
                "source_id": "asset-table-1",
                "source_name": "Orders",
                "target_id": "asset-col-1",
                "target_name": "order_id",
                "relation_type_id": "rt-contains-col",
                "relation_type_name": "Table contains Column",
            },
            {
                "relation_id": "rel-2",
                "source_id": "asset-col-1",
                "source_name": "order_id",
                "target_id": "asset-bt-1",
                "target_name": "Revenue",
                "relation_type_id": "rt-tagged-with",
                "relation_type_name": "Data Attribute / Data Element / Business Term association",
            },
        ]
    )

    lineage_info = pd.DataFrame(
        [
            {"source_id": "asset-table-1", "target_id": "asset-table-1", "lineage_type": "TABLE"},
        ]
    )


@pytest.fixture
def transformer():
    """Return a CollibraTransformer backed by _FakeExtractor."""
    t = CollibraTransformer(_FakeExtractor())  # type: ignore[arg-type]
    t.transform_all()
    return t


def test_community_maps_to_database(transformer):
    """Community rows should produce Database nodes."""
    assert len(transformer.database_nodes) == 1
    db = transformer.database_nodes[0]
    assert isinstance(db, Database)
    assert db.name == "Finance"
    assert db.platform == "COLLIBRA"


def test_physical_domain_maps_to_schema(transformer):
    """Physical Data Dictionary domain should produce Schema node."""
    schemas = [n for n in transformer.schema_nodes if n.name == "Finance Schema"]
    assert len(schemas) == 1
    assert isinstance(schemas[0], Schema)


def test_glossary_domain_maps_to_glossary(transformer):
    """Business Glossary domain should produce Glossary node."""
    glossaries = [n for n in transformer.glossary_nodes if n.name == "Finance Glossary"]
    assert len(glossaries) == 1
    assert isinstance(glossaries[0], Glossary)


def test_table_asset_maps_to_table_node(transformer):
    """Asset type 'Table' should produce a Table node with status and collibra_id."""
    tables = [n for n in transformer.table_nodes if n.name == "Orders"]
    assert len(tables) == 1
    t = tables[0]
    assert isinstance(t, Table)
    assert t.status == "Accepted"
    assert t.collibra_id == "asset-table-1"


def test_column_asset_maps_to_column_node(transformer):
    """Asset type 'Column' should produce a Column node."""
    cols = [n for n in transformer.column_nodes if n.name == "order_id"]
    assert len(cols) == 1
    assert isinstance(cols[0], Column)
    assert cols[0].collibra_id == "asset-col-1"


def test_business_term_asset_maps_correctly(transformer):
    """Asset type 'Business Term' should produce a BusinessTerm node."""
    terms = [n for n in transformer.business_term_nodes if n.name == "Revenue"]
    assert len(terms) == 1
    bt = terms[0]
    assert isinstance(bt, BusinessTerm)
    assert bt.status == "Draft"
    assert bt.collibra_id == "asset-bt-1"


def test_data_domain_asset_maps_to_category(transformer):
    """Asset type 'Data Domain' should produce a Category node."""
    cats = [n for n in transformer.category_nodes if n.name == "Financial Data"]
    assert len(cats) == 1
    assert isinstance(cats[0], Category)


def test_unknown_type_maps_to_catalog_asset(transformer):
    """Unknown asset type should produce a CatalogAsset node."""
    cas = [n for n in transformer.catalog_asset_nodes if n.name == "Custom Layout A"]
    assert len(cas) == 1
    ca = cas[0]
    assert isinstance(ca, CatalogAsset)
    assert ca.asset_type == "Custom Report Layout"
    assert ca.collibra_id == "asset-unknown-1"


def test_catalog_asset_has_has_asset_relationship(transformer):
    """CatalogAsset nodes should have a HAS_ASSET relationship to parent domain."""
    has_asset_rels = transformer.has_asset_relationships
    asset_ids = {r.asset_id for r in has_asset_rels}
    catalog_ids = {n.id for n in transformer.catalog_asset_nodes}
    assert asset_ids == catalog_ids


def test_attribute_description_on_table_node(transformer):
    """Table node description should come from the 'Description' attribute."""
    tables = [n for n in transformer.table_nodes if n.name == "Orders"]
    assert tables[0].description == "All customer orders"


def test_has_column_relationship_from_relation(transformer):
    """Table-contains-Column relation should produce a HAS_COLUMN relationship."""
    has_col = transformer.has_column_relationships
    assert len(has_col) >= 1
    assert all(isinstance(r, HasColumn) for r in has_col)


def test_tagged_with_relationship_from_relation(transformer):
    """Business-term-association relation should produce a TAGGED_WITH relationship."""
    tagged = transformer.tagged_with_relationships
    assert len(tagged) >= 1
    assert all(isinstance(r, TaggedWith) for r in tagged)


def test_flows_into_from_lineage(transformer):
    """Lineage rows should produce FlowsInto relationships."""
    flows = transformer.flows_into_relationships
    assert len(flows) >= 1
    assert isinstance(flows[0], FlowsInto)
    assert flows[0].lineage_type == "TABLE"
