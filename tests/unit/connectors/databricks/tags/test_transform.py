"""Unit tests for DatabricksTagsTransformer (ids + node/edge construction)."""

from neocarta.connectors.utils.generate_id import (
    generate_governance_tag_key_id,
    generate_governance_tag_value_id,
)

from .conftest import METASTORE_ID


def test_governance_tag_key_nodes_carry_description(extractor_with_cache, transformer):
    nodes = transformer.transform_to_governance_tag_key_nodes(extractor_with_cache.tag_key_info)
    by_name = {node.name: node for node in nodes}
    assert set(by_name) == {"department", "cost_center", "free_form"}
    department = by_name["department"]
    assert department.id == generate_governance_tag_key_id(METASTORE_ID, "department")
    assert department.description == "Owning department"
    # embeddings are generated post-load, not by the transform
    assert department.embedding is None


def test_governance_tag_value_nodes_are_name_only(extractor_with_cache, transformer):
    nodes = transformer.transform_to_governance_tag_value_nodes(extractor_with_cache.tag_value_info)
    by_name = {node.name: node for node in nodes}
    assert set(by_name) == {"finance", "hr", "sales", "alpha", "beta"}
    finance = by_name["finance"]
    assert finance.id == generate_governance_tag_value_id(METASTORE_ID, "department", "finance")
    # Databricks allowed values have no description; none is fabricated
    assert all(node.description is None for node in nodes)


def test_has_value_option_edges(extractor_with_cache, transformer):
    rels = transformer.transform_to_has_value_option_relationships(
        extractor_with_cache.tag_value_info
    )
    pairs = {(rel.governance_tag_key_id, rel.governance_tag_value_id) for rel in rels}
    assert (
        generate_governance_tag_key_id(METASTORE_ID, "department"),
        generate_governance_tag_value_id(METASTORE_ID, "department", "finance"),
    ) in pairs
    assert len(rels) == 5


def test_value_less_tag_has_key_but_no_value_options(extractor_with_cache, transformer):
    """A value-less governed tag becomes a key node with no value options."""
    keys = transformer.transform_to_governance_tag_key_nodes(extractor_with_cache.tag_key_info)
    rels = transformer.transform_to_has_value_option_relationships(
        extractor_with_cache.tag_value_info
    )
    assert any(node.name == "free_form" for node in keys)
    free_form_key_id = generate_governance_tag_key_id(METASTORE_ID, "free_form")
    assert all(rel.governance_tag_key_id != free_form_key_id for rel in rels)


def test_no_instance_layer_in_definition_only_transform(transformer):
    """The definition-only transform emits no assignment / TAGGED_WITH machinery."""
    assert not hasattr(transformer, "governance_tag_nodes")
    assert not hasattr(transformer, "tagged_with_governance_tag_relationships")
