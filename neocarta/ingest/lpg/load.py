"""Loader for LPG (Labeled Property Graph) schema metadata into Neo4j."""

import logging
from functools import partial

from neo4j import Driver, RoutingControl

from ...data_model.metadata import NeocartaGraph
from ...data_model.schema.lpg import (
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
from ...enums import NodeLabel, RelationshipType
from ..indexes import create_full_text_index, create_name_range_index
from ..metadata import upsert_neocarta_graph_node
from ..utils import (
    _build_node_ingest_query,
    _build_relationship_ingest_query,
    _node_pattern,
    _relationship_pattern,
    _validate_properties_list,
    write_neo4j_constraints,
)
from .constraints import KEY_CONSTRAINTS_LOOKUP, UNIQUE_CONSTRAINTS_LOOKUP

logger = logging.getLogger(__name__)


class Neo4jLPGLoader:
    """Load LPG schema metadata into Neo4j.

    A peer to :class:`neocarta.ingest.rdbms.Neo4jRDBMSLoader` for the Labeled
    Property Graph data model: ``Database`` / ``Schema`` / ``Node`` /
    ``Relationship`` / ``Property`` nodes and the ``HAS_SCHEMA`` / ``HAS_NODE`` /
    ``HAS_RELATIONSHIP`` / ``HAS_SOURCE_NODE`` / ``HAS_TARGET_NODE`` /
    ``HAS_PROPERTY`` edges.
    """

    def __init__(self, neo4j_driver: Driver, database_name: str = "neo4j") -> None:
        """Initialize the loader.

        Args:
            neo4j_driver: The caller-owned Neo4j driver to write with.
            database_name: The target database name.
        """
        self.neo4j_driver = neo4j_driver
        self.database_name = database_name

        self._write_node_constraint = partial(
            write_neo4j_constraints,
            neo4j_driver=self.neo4j_driver,
            key_constraints=KEY_CONSTRAINTS_LOOKUP,
            unique_constraints=UNIQUE_CONSTRAINTS_LOOKUP,
            database_name=self.database_name,
        )
        self._create_full_text_index = partial(
            create_full_text_index,
            neo4j_driver=self.neo4j_driver,
            database_name=self.database_name,
        )
        self._create_name_range_index = partial(
            create_name_range_index,
            neo4j_driver=self.neo4j_driver,
            database_name=self.database_name,
        )

    def _run_write(self, cypher: str, rows: list[dict], *, pattern: str | None = None) -> dict:
        """Execute a write Cypher against the configured database and return counters.

        When ``pattern`` is supplied, the graph pattern written and the Neo4j merge
        counters are logged (INFO: pattern + created/properties_set; DEBUG: the full
        counters dict). The pattern string is the only place a label/relationship-type
        is surfaced — no row data or Cypher text is logged.

        Args:
            cypher: The write Cypher to execute.
            rows: The ``$rows`` parameter for the UNWIND-based ingest query.
            pattern: Human-readable graph pattern for the log line.

        Returns:
            The Neo4j summary counters.
        """
        _, summary, _ = self.neo4j_driver.execute_query(
            query_=cypher,
            parameters_={"rows": rows},
            routing_=RoutingControl.WRITE,
            database_=self.database_name,
        )
        counters = summary.counters
        if pattern is not None:
            if logger.isEnabledFor(logging.INFO):
                created = counters.nodes_created or counters.relationships_created
                logger.info(
                    "Ingested %s — created %s, properties_set %s",
                    pattern,
                    created,
                    counters.properties_set,
                )
            if logger.isEnabledFor(logging.DEBUG):
                logger.debug("Merge counters for %s: %s", pattern, counters.__dict__)
        return counters.__dict__

    # ----- node loaders -----

    def load_database_nodes(
        self,
        database_nodes: list[Database],
        overwrite_existing: bool = False,
        properties_list: list[str] = ["name", "description", "service", "platform"],
        create_name_index: bool = True,
    ) -> dict:
        """Load Database nodes into Neo4j."""
        _validate_properties_list(Database, properties_list)
        self._write_node_constraint(node_labels=[NodeLabel.DATABASE])
        if create_name_index:
            self._create_name_range_index(node_label=NodeLabel.DATABASE)
        query = _build_node_ingest_query(NodeLabel.DATABASE, overwrite_existing, properties_list)
        return self._run_write(
            query,
            [n.model_dump() for n in database_nodes],
            pattern=_node_pattern(NodeLabel.DATABASE),
        )

    def load_schema_nodes(
        self,
        schema_nodes: list[Schema],
        overwrite_existing: bool = False,
        properties_list: list[str] = ["name", "description"],
        create_name_index: bool = True,
    ) -> dict:
        """Load Schema nodes into Neo4j."""
        _validate_properties_list(Schema, properties_list)
        self._write_node_constraint(node_labels=[NodeLabel.SCHEMA])
        if create_name_index:
            self._create_name_range_index(node_label=NodeLabel.SCHEMA)
        query = _build_node_ingest_query(NodeLabel.SCHEMA, overwrite_existing, properties_list)
        return self._run_write(
            query,
            [n.model_dump() for n in schema_nodes],
            pattern=_node_pattern(NodeLabel.SCHEMA),
        )

    def load_node_nodes(
        self,
        node_nodes: list[Node],
        overwrite_existing: bool = False,
        properties_list: list[str] = ["label", "additional_labels", "description"],
        create_full_text_index: bool = True,
        create_name_index: bool = True,
    ) -> dict:
        """Load Node nodes (LPG node labels) into Neo4j.

        ``Node`` is a search entry point: its searchable name is ``label`` (not
        ``name``), so the range index targets ``label`` and the full-text index
        covers ``["label", "description"]``.
        """
        _validate_properties_list(Node, properties_list)
        self._write_node_constraint(node_labels=[NodeLabel.NODE])
        if create_name_index:
            self._create_name_range_index(node_label=NodeLabel.NODE, property_name="label")
        if create_full_text_index:
            self._create_full_text_index(
                node_labels=[NodeLabel.NODE], property_names=["label", "description"]
            )
        query = _build_node_ingest_query(NodeLabel.NODE, overwrite_existing, properties_list)
        return self._run_write(
            query,
            [n.model_dump() for n in node_nodes],
            pattern=_node_pattern(NodeLabel.NODE),
        )

    def load_relationship_nodes(
        self,
        relationship_nodes: list[Relationship],
        overwrite_existing: bool = False,
        properties_list: list[str] = ["type", "description"],
        create_full_text_index: bool = True,
        create_name_index: bool = True,
    ) -> dict:
        """Load Relationship nodes (LPG relationship types) into Neo4j.

        Search entry point: searchable name is ``type``.
        """
        _validate_properties_list(Relationship, properties_list)
        self._write_node_constraint(node_labels=[NodeLabel.RELATIONSHIP])
        if create_name_index:
            self._create_name_range_index(node_label=NodeLabel.RELATIONSHIP, property_name="type")
        if create_full_text_index:
            self._create_full_text_index(
                node_labels=[NodeLabel.RELATIONSHIP], property_names=["type", "description"]
            )
        query = _build_node_ingest_query(
            NodeLabel.RELATIONSHIP, overwrite_existing, properties_list
        )
        return self._run_write(
            query,
            [n.model_dump() for n in relationship_nodes],
            pattern=_node_pattern(NodeLabel.RELATIONSHIP),
        )

    def load_property_nodes(
        self,
        property_nodes: list[Property],
        overwrite_existing: bool = False,
        properties_list: list[str] = [
            "name",
            "type",
            "description",
            "unique",
            "nullable",
            "indexed",
            "existence",
        ],
        create_name_index: bool = True,
    ) -> dict:
        """Load Property nodes into Neo4j (name range index only; no full-text)."""
        _validate_properties_list(Property, properties_list)
        self._write_node_constraint(node_labels=[NodeLabel.PROPERTY])
        if create_name_index:
            self._create_name_range_index(node_label=NodeLabel.PROPERTY)
        query = _build_node_ingest_query(NodeLabel.PROPERTY, overwrite_existing, properties_list)
        return self._run_write(
            query,
            [n.model_dump() for n in property_nodes],
            pattern=_node_pattern(NodeLabel.PROPERTY),
        )

    # ----- relationship loaders -----

    def load_has_schema_relationships(
        self,
        rels: list[HasSchema],
        overwrite_existing: bool = False,
        properties_list: list[str] = [],
    ) -> dict:
        """Load (:Database)-[:HAS_SCHEMA]->(:Schema)."""
        query = _build_relationship_ingest_query(
            RelationshipType.HAS_SCHEMA,
            NodeLabel.DATABASE,
            NodeLabel.SCHEMA,
            "database_id",
            "schema_id",
            overwrite_existing,
            properties_list,
        )
        return self._run_write(
            query,
            [r.model_dump() for r in rels],
            pattern=_relationship_pattern(
                RelationshipType.HAS_SCHEMA, NodeLabel.DATABASE, NodeLabel.SCHEMA
            ),
        )

    def load_has_node_relationships(
        self,
        rels: list[HasNode],
        overwrite_existing: bool = False,
        properties_list: list[str] = [],
    ) -> dict:
        """Load (:Schema)-[:HAS_NODE]->(:Node)."""
        query = _build_relationship_ingest_query(
            RelationshipType.HAS_NODE,
            NodeLabel.SCHEMA,
            NodeLabel.NODE,
            "schema_id",
            "node_id",
            overwrite_existing,
            properties_list,
        )
        return self._run_write(
            query,
            [r.model_dump() for r in rels],
            pattern=_relationship_pattern(
                RelationshipType.HAS_NODE, NodeLabel.SCHEMA, NodeLabel.NODE
            ),
        )

    def load_has_relationship_relationships(
        self,
        rels: list[HasRelationship],
        overwrite_existing: bool = False,
        properties_list: list[str] = [],
    ) -> dict:
        """Load (:Schema)-[:HAS_RELATIONSHIP]->(:Relationship)."""
        query = _build_relationship_ingest_query(
            RelationshipType.HAS_RELATIONSHIP,
            NodeLabel.SCHEMA,
            NodeLabel.RELATIONSHIP,
            "schema_id",
            "relationship_id",
            overwrite_existing,
            properties_list,
        )
        return self._run_write(
            query,
            [r.model_dump() for r in rels],
            pattern=_relationship_pattern(
                RelationshipType.HAS_RELATIONSHIP, NodeLabel.SCHEMA, NodeLabel.RELATIONSHIP
            ),
        )

    def load_has_source_node_relationships(
        self,
        rels: list[HasSourceNode],
        overwrite_existing: bool = False,
        properties_list: list[str] = [],
    ) -> dict:
        """Load (:Relationship)-[:HAS_SOURCE_NODE]->(:Node)."""
        query = _build_relationship_ingest_query(
            RelationshipType.HAS_SOURCE_NODE,
            NodeLabel.RELATIONSHIP,
            NodeLabel.NODE,
            "relationship_id",
            "node_id",
            overwrite_existing,
            properties_list,
        )
        return self._run_write(
            query,
            [r.model_dump() for r in rels],
            pattern=_relationship_pattern(
                RelationshipType.HAS_SOURCE_NODE, NodeLabel.RELATIONSHIP, NodeLabel.NODE
            ),
        )

    def load_has_target_node_relationships(
        self,
        rels: list[HasTargetNode],
        overwrite_existing: bool = False,
        properties_list: list[str] = [],
    ) -> dict:
        """Load (:Relationship)-[:HAS_TARGET_NODE]->(:Node)."""
        query = _build_relationship_ingest_query(
            RelationshipType.HAS_TARGET_NODE,
            NodeLabel.RELATIONSHIP,
            NodeLabel.NODE,
            "relationship_id",
            "node_id",
            overwrite_existing,
            properties_list,
        )
        return self._run_write(
            query,
            [r.model_dump() for r in rels],
            pattern=_relationship_pattern(
                RelationshipType.HAS_TARGET_NODE, NodeLabel.RELATIONSHIP, NodeLabel.NODE
            ),
        )

    def load_node_has_property_relationships(
        self,
        rels: list[NodeHasProperty],
        overwrite_existing: bool = False,
        properties_list: list[str] = [],
    ) -> dict:
        """Load (:Node)-[:HAS_PROPERTY]->(:Property)."""
        query = _build_relationship_ingest_query(
            RelationshipType.HAS_PROPERTY,
            NodeLabel.NODE,
            NodeLabel.PROPERTY,
            "source_id",
            "property_id",
            overwrite_existing,
            properties_list,
        )
        return self._run_write(
            query,
            [r.model_dump() for r in rels],
            pattern=_relationship_pattern(
                RelationshipType.HAS_PROPERTY, NodeLabel.NODE, NodeLabel.PROPERTY
            ),
        )

    def load_relationship_has_property_relationships(
        self,
        rels: list[RelationshipHasProperty],
        overwrite_existing: bool = False,
        properties_list: list[str] = [],
    ) -> dict:
        """Load (:Relationship)-[:HAS_PROPERTY]->(:Property)."""
        query = _build_relationship_ingest_query(
            RelationshipType.HAS_PROPERTY,
            NodeLabel.RELATIONSHIP,
            NodeLabel.PROPERTY,
            "source_id",
            "property_id",
            overwrite_existing,
            properties_list,
        )
        return self._run_write(
            query,
            [r.model_dump() for r in rels],
            pattern=_relationship_pattern(
                RelationshipType.HAS_PROPERTY, NodeLabel.RELATIONSHIP, NodeLabel.PROPERTY
            ),
        )

    def upsert_neocarta_graph_node(self, version: str | None = None) -> NeocartaGraph:
        """Create or update the singleton ``__neocarta_graph__`` metadata node.

        Connectors should invoke this once per run so the graph carries an up-to-date
        record of which neocarta version last wrote to it.

        Args:
            version: Override the recorded neocarta version. Defaults to the installed
                ``neocarta`` package version; explicit overrides are for tests.

        Returns:
            The current state of the metadata node after the upsert.
        """
        return upsert_neocarta_graph_node(
            neo4j_driver=self.neo4j_driver,
            database_name=self.database_name,
            version=version,
        )
