"""Cache TypedDicts for the Neo4j schema extractor and transformer."""

from __future__ import annotations

from typing import TYPE_CHECKING, TypedDict

if TYPE_CHECKING:
    import pandas as pd

    from ....data_model.schema.lpg import (
        Database,
        HasNode,
        HasRelationship,
        HasSchema,
        HasSourceNode,
        HasTargetNode,
        Node,
        NodeHasProperty,
        Property,
        Relationship,
        RelationshipHasProperty,
        Schema,
    )


class SchemaExtractorCache(TypedDict, total=False):
    """Cached source-read DataFrames for one extract() pass (flattened from APOC)."""

    database_info: pd.DataFrame
    schema_info: pd.DataFrame
    node_info: pd.DataFrame  # label
    relationship_info: pd.DataFrame  # type
    node_property_info: pd.DataFrame  # label, property, type, unique, indexed, existence
    relationship_property_info: pd.DataFrame  # type, property, type, unique, indexed, existence
    relationship_endpoint_info: pd.DataFrame  # type, source_label, target_label


class NodesCache(TypedDict, total=False):
    """Transformed LPG node lists."""

    database_nodes: list[Database]
    schema_nodes: list[Schema]
    node_nodes: list[Node]
    relationship_nodes: list[Relationship]
    property_nodes: list[Property]


class RelationshipsCache(TypedDict, total=False):
    """Transformed LPG relationship lists."""

    has_schema_relationships: list[HasSchema]
    has_node_relationships: list[HasNode]
    has_relationship_relationships: list[HasRelationship]
    has_source_node_relationships: list[HasSourceNode]
    has_target_node_relationships: list[HasTargetNode]
    node_has_property_relationships: list[NodeHasProperty]
    relationship_has_property_relationships: list[RelationshipHasProperty]
