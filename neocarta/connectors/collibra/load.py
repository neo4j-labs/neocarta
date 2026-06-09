"""Collibra-specific Neo4j loader.

Adds load methods for the ``Collibra*`` subtype nodes (written with a secondary
graph label, e.g. ``(:Table:CollibraTable)``) and the cross-sub-connector
``TAGGED_WITH`` edge that is matched by ``collibra_id``. Layered on top of the
base :class:`Neo4jRDBMSLoader`, mirroring :class:`OsiNeo4jLoader`.

Every Collibra node carries its source ``collibra_id`` and each node loader
creates a range index on that property (on the secondary label) so the
``TAGGED_WITH`` loader can seek the tagged Table/Column — produced by the schema
sub-connector — from the glossary sub-connector without recomputing deterministic
ids across connectors.
"""

from functools import partial

from neo4j import Driver

from ...data_model.rdbms import (
    CollibraBusinessTerm,
    CollibraCategory,
    CollibraColumn,
    CollibraDatabase,
    CollibraGlossary,
    CollibraSchema,
    CollibraTable,
    CollibraTaggedWith,
)
from ...enums import NodeLabel, RelationshipType
from ...ingest.indexes import create_range_index
from ...ingest.rdbms.load import Neo4jRDBMSLoader
from ...ingest.utils import _build_node_ingest_query, _validate_properties_list

_COLLIBRA_ID = "collibra_id"


class CollibraNeo4jLoader(Neo4jRDBMSLoader):
    """Neo4j loader with Collibra subtype + ``TAGGED_WITH``-by-``collibra_id`` loaders."""

    def __init__(self, neo4j_driver: Driver, database_name: str = "neo4j") -> None:
        """Initialise the base loader and the ``collibra_id`` range-index helper."""
        super().__init__(neo4j_driver, database_name)
        self._create_collibra_id_range_index = partial(
            create_range_index,
            neo4j_driver=self.neo4j_driver,
            property_name=_COLLIBRA_ID,
            database_name=self.database_name,
        )

    # ------------------------------------------------------------------ #
    # Node loaders (primary + secondary label, with collibra_id index)
    # ------------------------------------------------------------------ #

    def _load_collibra_nodes(
        self,
        nodes: list,
        model: type,
        primary_label: NodeLabel,
        secondary_label: NodeLabel,
        properties_list: list[str],
        overwrite_existing: bool,
    ) -> dict:
        """Shared body: write subtype nodes with a secondary label + collibra_id index."""
        _validate_properties_list(model, properties_list)
        self._write_node_constraint(node_labels=[primary_label])
        self._create_collibra_id_range_index(node_label=secondary_label)
        query = _build_node_ingest_query(
            primary_label,
            overwrite_existing,
            properties_list,
            secondary_labels=[secondary_label],
        )
        return self._run_write(query, [n.model_dump() for n in nodes])

    def load_collibra_database_nodes(
        self,
        nodes: list[CollibraDatabase],
        overwrite_existing: bool = False,
        properties_list: list[str] = ["name", "description", "service", "platform", "collibra_id"],
    ) -> dict:
        """Load CollibraDatabase nodes (``:Database:CollibraDatabase``)."""
        return self._load_collibra_nodes(
            nodes,
            CollibraDatabase,
            NodeLabel.DATABASE,
            NodeLabel.COLLIBRA_DATABASE,
            properties_list,
            overwrite_existing,
        )

    def load_collibra_schema_nodes(
        self,
        nodes: list[CollibraSchema],
        overwrite_existing: bool = False,
        properties_list: list[str] = ["name", "description", "collibra_id"],
    ) -> dict:
        """Load CollibraSchema nodes (``:Schema:CollibraSchema``)."""
        return self._load_collibra_nodes(
            nodes,
            CollibraSchema,
            NodeLabel.SCHEMA,
            NodeLabel.COLLIBRA_SCHEMA,
            properties_list,
            overwrite_existing,
        )

    def load_collibra_table_nodes(
        self,
        nodes: list[CollibraTable],
        overwrite_existing: bool = False,
        properties_list: list[str] = [
            "name",
            "description",
            "status",
            "collibra_id",
            "collibra_asset_type",
        ],
    ) -> dict:
        """Load CollibraTable nodes (``:Table:CollibraTable``)."""
        return self._load_collibra_nodes(
            nodes,
            CollibraTable,
            NodeLabel.TABLE,
            NodeLabel.COLLIBRA_TABLE,
            properties_list,
            overwrite_existing,
        )

    def load_collibra_column_nodes(
        self,
        nodes: list[CollibraColumn],
        overwrite_existing: bool = False,
        properties_list: list[str] = [
            "name",
            "description",
            "type",
            "status",
            "collibra_id",
            "collibra_asset_type",
        ],
    ) -> dict:
        """Load CollibraColumn nodes (``:Column:CollibraColumn``)."""
        return self._load_collibra_nodes(
            nodes,
            CollibraColumn,
            NodeLabel.COLUMN,
            NodeLabel.COLLIBRA_COLUMN,
            properties_list,
            overwrite_existing,
        )

    def load_collibra_glossary_nodes(
        self,
        nodes: list[CollibraGlossary],
        overwrite_existing: bool = False,
        properties_list: list[str] = ["name", "description", "collibra_id"],
    ) -> dict:
        """Load CollibraGlossary nodes (``:Glossary:CollibraGlossary``)."""
        return self._load_collibra_nodes(
            nodes,
            CollibraGlossary,
            NodeLabel.GLOSSARY,
            NodeLabel.COLLIBRA_GLOSSARY,
            properties_list,
            overwrite_existing,
        )

    def load_collibra_category_nodes(
        self,
        nodes: list[CollibraCategory],
        overwrite_existing: bool = False,
        properties_list: list[str] = ["name", "description", "status", "collibra_id"],
    ) -> dict:
        """Load CollibraCategory nodes (``:Category:CollibraCategory``)."""
        return self._load_collibra_nodes(
            nodes,
            CollibraCategory,
            NodeLabel.CATEGORY,
            NodeLabel.COLLIBRA_CATEGORY,
            properties_list,
            overwrite_existing,
        )

    def load_collibra_business_term_nodes(
        self,
        nodes: list[CollibraBusinessTerm],
        overwrite_existing: bool = False,
        properties_list: list[str] = ["name", "description", "status", "collibra_id"],
    ) -> dict:
        """Load CollibraBusinessTerm nodes (``:BusinessTerm:CollibraBusinessTerm``)."""
        return self._load_collibra_nodes(
            nodes,
            CollibraBusinessTerm,
            NodeLabel.BUSINESS_TERM,
            NodeLabel.COLLIBRA_BUSINESS_TERM,
            properties_list,
            overwrite_existing,
        )

    # ------------------------------------------------------------------ #
    # Relationship loaders
    # ------------------------------------------------------------------ #

    def load_collibra_tagged_with_relationships(
        self,
        rels: list[CollibraTaggedWith],
    ) -> dict:
        """
        Load ``(:Table|:Column)-[:TAGGED_WITH]->(:BusinessTerm)`` edges.

        The tagged source is matched by ``collibra_id`` on the secondary Collibra
        label (seeks via the per-label ``collibra_id`` range index), so this edge
        resolves whether or not the schema sub-connector ran in the same process.
        """
        cypher = f"""
UNWIND $rows AS row
MATCH (s:{NodeLabel.COLLIBRA_TABLE}|{NodeLabel.COLLIBRA_COLUMN} {{collibra_id: row.source_collibra_id}})
MATCH (b:{NodeLabel.BUSINESS_TERM} {{id: row.business_term_id}})
MERGE (s)-[:{RelationshipType.TAGGED_WITH}]->(b)
""".strip()
        return self._run_write(cypher, [r.model_dump() for r in rels])
