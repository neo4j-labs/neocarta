"""Neo4j schema connector: introspect a source Neo4j into the LPG graph."""

from __future__ import annotations

import logging
import warnings
from typing import TYPE_CHECKING

from ...._logging import log_transform_counts
from ....errors import ConfigError, StateError
from ....ingest.lpg import Neo4jLPGLoader
from ._guard import ensure_distinct_databases, ensure_source_is_not_neocarta_graph
from .extract import Neo4jSchemaExtractor
from .transform import Neo4jSchemaTransformer

if TYPE_CHECKING:
    from typing import Self

    from neo4j import Driver

    from ....enums import NodeLabel, RelationshipType

logger = logging.getLogger(__name__)

# (human label, transformer attribute) pairs logged at the end of transform().
_TRANSFORM_COUNTS: tuple[tuple[str, str], ...] = (
    ("databases", "database_nodes"),
    ("schemas", "schema_nodes"),
    ("nodes", "node_nodes"),
    ("relationships", "relationship_nodes"),
    ("properties", "property_nodes"),
)


class Neo4jSchemaConnector:
    """Introspect a source Neo4j instance's schema into the neocarta LPG graph.

    Reads node labels, relationship types, properties, and constraint/index flags from
    a source Neo4j via APOC (``apoc.meta.schema()``) and maps them onto the LPG data
    model (``Database``/``Schema``/``Node``/``Relationship``/``Property``). Follows an
    Extract -> Transform -> Load pipeline; :meth:`ingest` runs all three and records the
    neocarta graph metadata node.

    Both drivers are caller-owned; :meth:`close` is a no-op and never closes either.
    They may point at the same DBMS/instance, but must be **different databases** -- a
    read-only preflight guard refuses ingest when the source and target resolve to the
    same database (the connector never writes into the database it reads). Note this
    validation runs in :meth:`extract`, so even a standalone ``extract()`` requires the
    target to be online and identifiable.

    Args:
        source_neo4j_driver: Driver for the SOURCE Neo4j to introspect (read).
        neo4j_driver: Driver for the TARGET neocarta graph (write).
        source_name: Names the source DBMS; used as the ``Database`` node identity.
        database_name: Target neocarta database name.
    """

    def __init__(
        self,
        source_neo4j_driver: Driver,
        neo4j_driver: Driver,
        source_name: str,
        database_name: str = "neo4j",
    ) -> None:
        """Initialize the Neo4j schema connector."""
        if source_neo4j_driver is None:
            raise ConfigError("source_neo4j_driver is required.")
        if neo4j_driver is None:
            raise ConfigError("neo4j_driver is required.")
        if not source_name:
            raise ConfigError(
                "source_name is required (it identifies the source DBMS / Database node).",
                suggestion="Pass source_name='<a stable name for the source instance>'.",
            )

        self.source_neo4j_driver = source_neo4j_driver
        self.neo4j_driver = neo4j_driver
        self.source_name = source_name
        self.database_name = database_name

        self.extractor = Neo4jSchemaExtractor(source_neo4j_driver, source_name)
        self.transformer = Neo4jSchemaTransformer()
        self.loader = Neo4jLPGLoader(neo4j_driver, database_name)
        self._extracted = False
        self._transformed = False
        self._source_database = database_name
        self._include_nodes: list[NodeLabel] | None = None
        self._include_relationships: list[RelationshipType] | None = None

    def close(self) -> None:
        """No-op: both drivers are caller-owned and are left open."""

    def __enter__(self) -> Self:
        """Return self for use as a context manager."""
        return self

    def __exit__(self, exc_type: object, exc_value: object, traceback: object) -> None:
        """Release owned resources (none) on exit."""
        self.close()

    def extract(
        self,
        source_database: str = "neo4j",
        *,
        include_nodes: list[NodeLabel] | None = None,
        include_relationships: list[RelationshipType] | None = None,
    ) -> None:
        """Read the source schema into the extractor cache."""
        logger.info("Extracting Neo4j schema metadata...")
        self._extracted = False
        self._transformed = False
        self._source_database = source_database
        self._include_nodes = include_nodes
        self._include_relationships = include_relationships
        ensure_distinct_databases(
            self.source_neo4j_driver, source_database, self.neo4j_driver, self.database_name
        )
        self.extractor.extract_database_info(source_database)
        self.extractor.extract_schema(source_database)
        ensure_source_is_not_neocarta_graph(self.extractor.node_info)
        self._extracted = True

    def transform(self) -> None:
        """Build LPG objects from the cache. Raises StateError before extract()."""
        if not self._extracted:
            raise StateError(
                "Neo4jSchemaConnector.transform() called before extract().",
                suggestion="Call connector.extract(...) before connector.transform().",
            )
        self._transformed = False
        logger.info("Transforming Neo4j schema metadata...")
        self.transformer.build_all(
            self.extractor,
            source_name=self.source_name,
            source_database=self._source_database,
            include_nodes=self._include_nodes,
            include_relationships=self._include_relationships,
        )
        log_transform_counts(logger, self.transformer, _TRANSFORM_COUNTS)
        self._transformed = True

    def load(self) -> None:
        """Load LPG objects into Neo4j. Raises StateError before transform()."""
        if not self._transformed:
            raise StateError(
                "Neo4jSchemaConnector.load() called before transform().",
                suggestion="Call connector.extract() and connector.transform() first.",
            )
        logger.info("Loading Neo4j schema metadata into Neo4j...")
        self.loader.load_database_nodes(self.transformer.database_nodes)
        self.loader.load_schema_nodes(self.transformer.schema_nodes)
        self.loader.load_node_nodes(self.transformer.node_nodes)
        self.loader.load_relationship_nodes(self.transformer.relationship_nodes)
        self.loader.load_property_nodes(self.transformer.property_nodes)
        self.loader.load_has_schema_relationships(self.transformer.has_schema_relationships)
        self.loader.load_has_node_relationships(self.transformer.has_node_relationships)
        self.loader.load_has_relationship_relationships(
            self.transformer.has_relationship_relationships
        )
        self.loader.load_has_source_node_relationships(
            self.transformer.has_source_node_relationships
        )
        self.loader.load_has_target_node_relationships(
            self.transformer.has_target_node_relationships
        )
        self.loader.load_node_has_property_relationships(
            self.transformer.node_has_property_relationships
        )
        self.loader.load_relationship_has_property_relationships(
            self.transformer.relationship_has_property_relationships
        )

    def ingest(
        self,
        source_database: str = "neo4j",
        *,
        include_nodes: list[NodeLabel] | None = None,
        include_relationships: list[RelationshipType] | None = None,
    ) -> None:
        """Run extract -> transform -> load and record neocarta graph metadata."""
        self.extract(
            source_database,
            include_nodes=include_nodes,
            include_relationships=include_relationships,
        )
        self.transform()
        self.load()
        self.loader.upsert_neocarta_graph_node()
        logger.info("Neo4j schema connector completed successfully")

    def run(self, *args: object, **kwargs: object) -> None:
        """Run the connector.

        .. deprecated::
            Use :meth:`ingest` instead. ``run`` will be removed in a future release.
        """
        warnings.warn(
            "Neo4jSchemaConnector.run() is deprecated; use Neo4jSchemaConnector.ingest() instead.",
            DeprecationWarning,
            stacklevel=2,
        )
        self.ingest(*args, **kwargs)
