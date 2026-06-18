"""Unit tests for DatabricksGlossaryTransformer (ids + node/edge construction)."""

from neocarta.connectors.utils.generate_id import (
    generate_business_term_id,
    generate_category_id,
    generate_glossary_id,
)

from .conftest import METASTORE_ID


def test_glossary_node(extractor_with_cache, transformer):
    nodes = transformer.transform_to_glossary_nodes(extractor_with_cache.glossary_info)
    assert len(nodes) == 1
    assert nodes[0].id == generate_glossary_id(METASTORE_ID)
    assert nodes[0].name == "Unity Catalog Governed Tags"
    assert nodes[0].resource_path == METASTORE_ID
    assert nodes[0].description is None


def test_category_nodes_carry_key_description_and_policy_id(extractor_with_cache, transformer):
    nodes = transformer.transform_to_category_nodes(extractor_with_cache.category_info)
    by_name = {node.name: node for node in nodes}
    assert set(by_name) == {"department", "cost_center", "free_form"}
    department = by_name["department"]
    assert department.id == generate_category_id(METASTORE_ID, "department")
    assert department.description == "Owning department"
    assert department.resource_path == "tp-department"


def test_business_term_nodes_are_name_only(extractor_with_cache, transformer):
    nodes = transformer.transform_to_business_term_nodes(extractor_with_cache.business_term_info)
    by_name = {node.name: node for node in nodes}
    assert set(by_name) == {"finance", "hr", "sales", "alpha", "beta"}
    finance = by_name["finance"]
    assert finance.id == generate_business_term_id(METASTORE_ID, "department", "finance")
    # allowed values have no description in Databricks; none is fabricated
    assert all(node.description is None for node in nodes)
    assert all(node.resource_path is None for node in nodes)


def test_has_category_edges(extractor_with_cache, transformer):
    rels = transformer.transform_to_has_category_relationships(extractor_with_cache.category_info)
    pairs = {(rel.glossary_id, rel.category_id) for rel in rels}
    assert (
        generate_glossary_id(METASTORE_ID),
        generate_category_id(METASTORE_ID, "department"),
    ) in pairs
    assert len(rels) == 3


def test_has_business_term_edges(extractor_with_cache, transformer):
    rels = transformer.transform_to_has_business_term_relationships(
        extractor_with_cache.business_term_info
    )
    pairs = {(rel.category_id, rel.business_term_id) for rel in rels}
    assert (
        generate_category_id(METASTORE_ID, "department"),
        generate_business_term_id(METASTORE_ID, "department", "finance"),
    ) in pairs
    assert len(rels) == 5


def test_no_tagged_with_in_v1(transformer):
    """v1 reads definitions only — no assignment / TAGGED_WITH machinery."""
    assert not hasattr(transformer, "column_tagged_with_relationships")
    assert not hasattr(transformer, "table_tagged_with_relationships")
