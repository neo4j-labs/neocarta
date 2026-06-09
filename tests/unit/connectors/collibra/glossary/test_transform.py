"""Unit tests for CollibraGlossaryTransformer: subtype nodes, ids, categories, tags."""

from unittest.mock import MagicMock

from neocarta.connectors.collibra.glossary.connector import CollibraGlossaryConnector
from neocarta.connectors.collibra.glossary.extract import CollibraGlossaryExtractor
from neocarta.connectors.collibra.glossary.transform import CollibraGlossaryTransformer
from neocarta.data_model.rdbms import (
    CollibraBusinessTerm,
    CollibraCategory,
    CollibraGlossary,
    CollibraTaggedWith,
)
from neocarta.enums import NodeLabel, RelationshipType


def _transform(fake_client, **kwargs) -> CollibraGlossaryTransformer:
    extractor = CollibraGlossaryExtractor(fake_client)
    extractor.extract(**kwargs)
    transformer = CollibraGlossaryTransformer()
    transformer.transform_all(
        extractor, kwargs.get("include_nodes"), kwargs.get("include_relationships")
    )
    return transformer


def test_builds_subtype_nodes_with_ids_and_metadata(fake_client):
    """Glossary/Category/BusinessTerm subtypes carry deterministic ids + collibra_id."""
    t = _transform(fake_client)
    glossary = t.glossary_nodes[0]
    category = t.category_nodes[0]
    assert isinstance(glossary, CollibraGlossary)
    assert glossary.id == "sales_glossary"
    assert glossary.collibra_id == "dom-gloss"
    assert isinstance(category, CollibraCategory)
    assert category.id == "sales_glossary.orders"
    assert all(isinstance(b, CollibraBusinessTerm) for b in t.business_term_nodes)


def test_categorised_vs_uncategorised_term_ids(fake_client):
    """A categorised term nests under its category; an uncategorised one under the glossary name."""
    t = _transform(fake_client)
    by_name = {b.name: b for b in t.business_term_nodes}
    assert by_name["Order"].id == "sales_glossary.orders.order"  # under the Orders category
    assert by_name["Customer"].id == "sales_glossary.sales_glossary.customer"  # uncategorised


def test_has_category_and_has_business_term_edges(fake_client):
    """HAS_CATEGORY links glossary→category; HAS_BUSINESS_TERM only for categorised terms."""
    t = _transform(fake_client)
    assert (
        t.has_category_relationships[0].glossary_id,
        t.has_category_relationships[0].category_id,
    ) == ("sales_glossary", "sales_glossary.orders")
    assert len(t.has_business_term_relationships) == 1
    assert t.has_business_term_relationships[0].business_term_id == "sales_glossary.orders.order"


def test_tagged_with_targets_term_by_node_id_and_source_by_uuid(fake_client):
    """TAGGED_WITH carries the tagged asset's UUID and the term's neocarta node id."""
    t = _transform(fake_client)
    assert t.tagged_with_relationships == [
        CollibraTaggedWith(
            source_collibra_id="a-orderid", business_term_id="sales_glossary.orders.order"
        )
    ]


def test_tagged_with_dropped_when_term_not_produced(fake_client):
    """Tags whose term node isn't produced (e.g. BUSINESS_TERM excluded) are skipped."""
    t = _transform(fake_client, include_nodes=[NodeLabel.GLOSSARY, NodeLabel.CATEGORY])
    assert t.tagged_with_relationships == []


def test_include_relationships_excludes_tagged_with(fake_client):
    """Excluding TAGGED_WITH yields no tag edges even though terms exist."""
    t = _transform(fake_client, include_relationships=[RelationshipType.HAS_BUSINESS_TERM])
    assert t.business_term_nodes
    assert t.tagged_with_relationships == []


def test_connector_load_calls_tagged_with_loader(fake_client):
    """The glossary connector drives the Collibra tagged-with loader on load()."""
    driver = MagicMock()
    driver.execute_query.return_value = (None, MagicMock(), None)
    connector = CollibraGlossaryConnector(client=fake_client, neo4j_driver=driver)
    connector.loader = MagicMock()
    connector.extract()
    connector.transform()
    connector.load()
    connector.loader.load_collibra_glossary_nodes.assert_called_once()
    connector.loader.load_collibra_tagged_with_relationships.assert_called_once()
