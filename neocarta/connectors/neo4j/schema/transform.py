"""Transform Neo4j schema DataFrames into LPG graph nodes and relationships."""

from __future__ import annotations

from typing import TYPE_CHECKING

from ....connectors.utils.generate_id import (
    generate_database_id,
    generate_node_id,
    generate_property_id,
    generate_relationship_id,
    generate_schema_id,
)
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
from ....enums import NodeLabel, RelationshipType
from .models import NodesCache, RelationshipsCache

if TYPE_CHECKING:
    import pandas as pd

# Relationship cache key -> the RelationshipType it produces (for include_relationships).
_REL_TYPE_BY_CACHE = {
    "has_schema_relationships": RelationshipType.HAS_SCHEMA,
    "has_node_relationships": RelationshipType.HAS_NODE,
    "has_relationship_relationships": RelationshipType.HAS_RELATIONSHIP,
    "has_source_node_relationships": RelationshipType.HAS_SOURCE_NODE,
    "has_target_node_relationships": RelationshipType.HAS_TARGET_NODE,
    "node_has_property_relationships": RelationshipType.HAS_PROPERTY,
    "relationship_has_property_relationships": RelationshipType.HAS_PROPERTY,
}


class Neo4jSchemaTransformer:
    """Build LPG data-model objects from the extractor's flattened APOC frames."""

    def __init__(self) -> None:
        """Initialize empty node/relationship caches."""
        self._node_cache: NodesCache = NodesCache()
        self._relationships_cache: RelationshipsCache = RelationshipsCache()

    # --- node accessors ---
    @property
    def database_nodes(self) -> list[Database]:
        """(:Database) nodes."""
        return self._node_cache.get("database_nodes", [])

    @property
    def schema_nodes(self) -> list[Schema]:
        """(:Schema) nodes."""
        return self._node_cache.get("schema_nodes", [])

    @property
    def node_nodes(self) -> list[Node]:
        """(:Node) nodes."""
        return self._node_cache.get("node_nodes", [])

    @property
    def relationship_nodes(self) -> list[Relationship]:
        """(:Relationship) nodes."""
        return self._node_cache.get("relationship_nodes", [])

    @property
    def property_nodes(self) -> list[Property]:
        """(:Property) nodes."""
        return self._node_cache.get("property_nodes", [])

    # --- relationship accessors ---
    @property
    def has_schema_relationships(self) -> list[HasSchema]:
        """(:Database)-[:HAS_SCHEMA]->(:Schema)."""
        return self._relationships_cache.get("has_schema_relationships", [])

    @property
    def has_node_relationships(self) -> list[HasNode]:
        """(:Schema)-[:HAS_NODE]->(:Node)."""
        return self._relationships_cache.get("has_node_relationships", [])

    @property
    def has_relationship_relationships(self) -> list[HasRelationship]:
        """(:Schema)-[:HAS_RELATIONSHIP]->(:Relationship)."""
        return self._relationships_cache.get("has_relationship_relationships", [])

    @property
    def has_source_node_relationships(self) -> list[HasSourceNode]:
        """(:Relationship)-[:HAS_SOURCE_NODE]->(:Node)."""
        return self._relationships_cache.get("has_source_node_relationships", [])

    @property
    def has_target_node_relationships(self) -> list[HasTargetNode]:
        """(:Relationship)-[:HAS_TARGET_NODE]->(:Node)."""
        return self._relationships_cache.get("has_target_node_relationships", [])

    @property
    def node_has_property_relationships(self) -> list[NodeHasProperty]:
        """(:Node)-[:HAS_PROPERTY]->(:Property)."""
        return self._relationships_cache.get("node_has_property_relationships", [])

    @property
    def relationship_has_property_relationships(self) -> list[RelationshipHasProperty]:
        """(:Relationship)-[:HAS_PROPERTY]->(:Property)."""
        return self._relationships_cache.get("relationship_has_property_relationships", [])

    # --- node transforms ---
    def transform_to_database_nodes(
        self, database_info: pd.DataFrame, *, source_name: str, cache: bool = True
    ) -> list[Database]:
        """Build the single Database node from ``source_name``."""
        nodes = (
            [Database(id=generate_database_id(source_name), name=source_name, service="NEO4J")]
            if not database_info.empty
            else []
        )
        if cache:
            self._node_cache["database_nodes"] = nodes
        return nodes

    def transform_to_schema_nodes(
        self,
        schema_info: pd.DataFrame,
        *,
        source_name: str,
        source_database: str,
        cache: bool = True,
    ) -> list[Schema]:
        """Build the single Schema node from ``source_database``."""
        nodes = (
            [Schema(id=generate_schema_id(source_name, source_database), name=source_database)]
            if not schema_info.empty
            else []
        )
        if cache:
            self._node_cache["schema_nodes"] = nodes
        return nodes

    def transform_to_node_nodes(
        self,
        node_info: pd.DataFrame,
        *,
        source_name: str,
        source_database: str,
        cache: bool = True,
    ) -> list[Node]:
        """Build one Node per label; ``additional_labels`` is unused (per-label APOC view)."""
        nodes = [
            Node(
                id=generate_node_id(source_name, source_database, row["label"]),
                label=row["label"],
            )
            for _, row in node_info.iterrows()
        ]
        if cache:
            self._node_cache["node_nodes"] = nodes
        return nodes

    def transform_to_relationship_nodes(
        self,
        relationship_info: pd.DataFrame,
        *,
        source_name: str,
        source_database: str,
        cache: bool = True,
    ) -> list[Relationship]:
        """Build one Relationship per relationship type."""
        nodes = [
            Relationship(
                id=generate_relationship_id(source_name, source_database, row["type"]),
                type=row["type"],
            )
            for _, row in relationship_info.iterrows()
        ]
        if cache:
            self._node_cache["relationship_nodes"] = nodes
        return nodes

    def transform_to_property_nodes(
        self,
        node_property_info: pd.DataFrame | None,
        relationship_property_info: pd.DataFrame | None,
        *,
        source_name: str,
        source_database: str,
        cache: bool = True,
    ) -> list[Property]:
        """Build Property nodes for node- and relationship-owned properties.

        A ``None`` frame skips that owner type (used by ``build_all`` filtering so a
        property is only produced when its owning Node/Relationship is included).
        """
        nodes: list[Property] = []
        if node_property_info is not None:
            for _, row in node_property_info.iterrows():
                owner_id = generate_node_id(source_name, source_database, row["label"])
                nodes.append(_build_property(owner_id, row))
        if relationship_property_info is not None:
            for _, row in relationship_property_info.iterrows():
                owner_id = generate_relationship_id(source_name, source_database, row["rel_type"])
                nodes.append(_build_property(owner_id, row))
        if cache:
            self._node_cache["property_nodes"] = nodes
        return nodes

    # --- relationship transforms ---
    def transform_to_has_schema_relationships(
        self, *, source_name: str, source_database: str, cache: bool = True
    ) -> list[HasSchema]:
        """Build (:Database)-[:HAS_SCHEMA]->(:Schema)."""
        rels = [
            HasSchema(
                database_id=generate_database_id(source_name),
                schema_id=generate_schema_id(source_name, source_database),
            )
        ]
        if cache:
            self._relationships_cache["has_schema_relationships"] = rels
        return rels

    def transform_to_has_node_relationships(
        self,
        node_info: pd.DataFrame,
        *,
        source_name: str,
        source_database: str,
        cache: bool = True,
    ) -> list[HasNode]:
        """Build (:Schema)-[:HAS_NODE]->(:Node)."""
        schema_id = generate_schema_id(source_name, source_database)
        rels = [
            HasNode(
                schema_id=schema_id,
                node_id=generate_node_id(source_name, source_database, row["label"]),
            )
            for _, row in node_info.iterrows()
        ]
        if cache:
            self._relationships_cache["has_node_relationships"] = rels
        return rels

    def transform_to_has_relationship_relationships(
        self,
        relationship_info: pd.DataFrame,
        *,
        source_name: str,
        source_database: str,
        cache: bool = True,
    ) -> list[HasRelationship]:
        """Build (:Schema)-[:HAS_RELATIONSHIP]->(:Relationship)."""
        schema_id = generate_schema_id(source_name, source_database)
        rels = [
            HasRelationship(
                schema_id=schema_id,
                relationship_id=generate_relationship_id(source_name, source_database, row["type"]),
            )
            for _, row in relationship_info.iterrows()
        ]
        if cache:
            self._relationships_cache["has_relationship_relationships"] = rels
        return rels

    def transform_to_endpoint_relationships(
        self,
        endpoint_info: pd.DataFrame,
        *,
        source_name: str,
        source_database: str,
        cache: bool = True,
    ) -> None:
        """Build HAS_SOURCE_NODE / HAS_TARGET_NODE from the endpoint frame."""
        sources: list[HasSourceNode] = []
        targets: list[HasTargetNode] = []
        for _, row in endpoint_info.iterrows():
            rel_id = generate_relationship_id(source_name, source_database, row["type"])
            sources.append(
                HasSourceNode(
                    relationship_id=rel_id,
                    node_id=generate_node_id(source_name, source_database, row["source_label"]),
                )
            )
            targets.append(
                HasTargetNode(
                    relationship_id=rel_id,
                    node_id=generate_node_id(source_name, source_database, row["target_label"]),
                )
            )
        if cache:
            self._relationships_cache["has_source_node_relationships"] = sources
            self._relationships_cache["has_target_node_relationships"] = targets

    def transform_to_node_has_property_relationships(
        self,
        node_property_info: pd.DataFrame,
        *,
        source_name: str,
        source_database: str,
        cache: bool = True,
    ) -> list[NodeHasProperty]:
        """Build (:Node)-[:HAS_PROPERTY]->(:Property)."""
        rels = []
        for _, row in node_property_info.iterrows():
            owner_id = generate_node_id(source_name, source_database, row["label"])
            rels.append(
                NodeHasProperty(
                    source_id=owner_id, property_id=generate_property_id(owner_id, row["property"])
                )
            )
        if cache:
            self._relationships_cache["node_has_property_relationships"] = rels
        return rels

    def transform_to_relationship_has_property_relationships(
        self,
        relationship_property_info: pd.DataFrame,
        *,
        source_name: str,
        source_database: str,
        cache: bool = True,
    ) -> list[RelationshipHasProperty]:
        """Build (:Relationship)-[:HAS_PROPERTY]->(:Property)."""
        rels = []
        for _, row in relationship_property_info.iterrows():
            owner_id = generate_relationship_id(source_name, source_database, row["rel_type"])
            rels.append(
                RelationshipHasProperty(
                    source_id=owner_id, property_id=generate_property_id(owner_id, row["property"])
                )
            )
        if cache:
            self._relationships_cache["relationship_has_property_relationships"] = rels
        return rels

    # --- orchestration ---
    def build_all(
        self,
        extractor: object,
        *,
        source_name: str,
        source_database: str,
        include_nodes: list[NodeLabel] | None = None,
        include_relationships: list[RelationshipType] | None = None,
    ) -> None:
        """Build every LPG node/relationship list from the extractor caches, honoring filters."""
        # Independent runs (contract §9): clear prior state so a filtered run can't
        # leak stale lists from an earlier run on the same transformer.
        self._node_cache = NodesCache()
        self._relationships_cache = RelationshipsCache()

        def included(label: NodeLabel) -> bool:
            return include_nodes is None or label in include_nodes

        # Roots are always produced.
        self.transform_to_database_nodes(extractor.database_info, source_name=source_name)
        self.transform_to_schema_nodes(
            extractor.schema_info, source_name=source_name, source_database=source_database
        )
        self.transform_to_has_schema_relationships(
            source_name=source_name, source_database=source_database
        )

        node_inc = included(NodeLabel.NODE)
        rel_inc = included(NodeLabel.RELATIONSHIP)
        prop_inc = included(NodeLabel.PROPERTY)

        if node_inc:
            self.transform_to_node_nodes(
                extractor.node_info, source_name=source_name, source_database=source_database
            )
            self.transform_to_has_node_relationships(
                extractor.node_info, source_name=source_name, source_database=source_database
            )
        if rel_inc:
            self.transform_to_relationship_nodes(
                extractor.relationship_info,
                source_name=source_name,
                source_database=source_database,
            )
            self.transform_to_has_relationship_relationships(
                extractor.relationship_info,
                source_name=source_name,
                source_database=source_database,
            )
        if node_inc and rel_inc:
            self.transform_to_endpoint_relationships(
                extractor.relationship_endpoint_info,
                source_name=source_name,
                source_database=source_database,
            )
        if prop_inc:
            # A property is only produced when its owning Node/Relationship is included.
            self.transform_to_property_nodes(
                extractor.node_property_info if node_inc else None,
                extractor.relationship_property_info if rel_inc else None,
                source_name=source_name,
                source_database=source_database,
            )
            if node_inc:
                self.transform_to_node_has_property_relationships(
                    extractor.node_property_info,
                    source_name=source_name,
                    source_database=source_database,
                )
            if rel_inc:
                self.transform_to_relationship_has_property_relationships(
                    extractor.relationship_property_info,
                    source_name=source_name,
                    source_database=source_database,
                )

        if include_relationships is not None:
            for key, rel_type in _REL_TYPE_BY_CACHE.items():
                if rel_type not in include_relationships:
                    self._relationships_cache[key] = []


def _build_property(owner_id: str, row: pd.Series) -> Property:
    """Build a Property node from an owner id and a flattened property row."""
    existence = bool(row["existence"])
    return Property(
        id=generate_property_id(owner_id, row["property"]),
        name=row["property"],
        type=row["type"],
        unique=bool(row["unique"]),
        indexed=bool(row["indexed"]),
        existence=existence,
        nullable=not existence,
    )
