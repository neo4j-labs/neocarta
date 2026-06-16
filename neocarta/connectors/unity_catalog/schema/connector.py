"""Unity Catalog schema sub-connector."""

import logging
import warnings

from neo4j import Driver

from ...._logging import log_transform_counts
from ....errors import ConfigError, StateError
from ....ingest.rdbms import Neo4jRDBMSLoader
from ...utils import NodeLabel, RelationshipType
from .extract import UnityCatalogSchemaExtractor
from .transform import UnityCatalogSchemaTransformer

logger = logging.getLogger(__name__)

# (human label, transformer attribute) pairs logged at the end of transform().
_TRANSFORM_COUNTS = (
    ("databases", "database_nodes"),
    ("schemas", "schema_nodes"),
    ("tables", "table_nodes"),
    ("columns", "column_nodes"),
)


class UnityCatalogSchemaConnector:
    """
    Connector for schema metadata from the open Unity Catalog REST API.

    Speaks the vendor-neutral ``/api/2.1/unity-catalog`` REST API (no Databricks
    SDK), so it works against any conformant Unity Catalog server. Produces
    Database/Schema/Table/Column nodes and their HAS_* edges. Follows an
    Extract → Transform → Load pipeline; :meth:`ingest` runs all three stages and
    records the neocarta graph metadata node at the end.

    The open API exposes no primary/foreign-key constraints, so no ``REFERENCES``
    edges are produced and column key flags stay ``False``. Glossary/tags are not
    available via the REST API and are handled by a separate connector.

    Parameters
    ----------
    base_url : str
        Base URL of the Unity Catalog REST API, including the version prefix
        (e.g. ``http://localhost:8080/api/2.1/unity-catalog``).
    neo4j_driver : Driver
        Neo4j driver instance.
    token : str | None, default None
        Bearer token for the ``Authorization`` header. ``None`` for a local OSS
        server that requires no auth.
    database_name : str, default "neo4j"
        Target Neo4j database name.
    timeout : float, default 30.0
        Per-request HTTP timeout in seconds.
    """

    def __init__(
        self,
        base_url: str,
        neo4j_driver: Driver,
        token: str | None = None,
        database_name: str = "neo4j",
        timeout: float = 30.0,
    ) -> None:
        """Initialize the Unity Catalog schema connector."""
        if not base_url:
            raise ConfigError(
                "base_url is required for the Unity Catalog connector.",
                suggestion="Pass base_url=... (e.g. http://localhost:8080/api/2.1/unity-catalog).",
            )
        self.base_url = base_url
        self.neo4j_driver = neo4j_driver
        self.database_name = database_name

        self.extractor = UnityCatalogSchemaExtractor(base_url, token=token, timeout=timeout)
        self.transformer = UnityCatalogSchemaTransformer()
        self.loader = Neo4jRDBMSLoader(neo4j_driver, database_name)
        self._extracted = False
        self._transformed = False

    def extract(
        self,
        catalog: str,
        schemas: list[str] | None = None,
        *,
        include_nodes: list[NodeLabel] | None = None,
        include_relationships: list[RelationshipType] | None = None,
    ) -> None:
        """
        Extract Unity Catalog schema metadata for one catalog into the cache.

        Parameters
        ----------
        catalog : str
            The Unity Catalog catalog name to extract.
        schemas : list[str] | None, default None
            Optional client-side filter restricting extraction to these schemas.
        include_nodes : list[NodeLabel] | None, default None
            Node labels to produce. ``None`` includes all available.
        include_relationships : list[RelationshipType] | None, default None
            Relationship types to produce. ``None`` includes all available.
        """
        logger.info("Extracting Unity Catalog schema metadata...")
        self._extracted = False
        self._transformed = False
        self.extractor.extract(
            catalog,
            schemas,
            include_nodes=include_nodes,
            include_relationships=include_relationships,
        )
        self._extracted = True

    def transform(self) -> None:
        """
        Transform cached metadata into Database/Schema/Table/Column nodes + HAS_* edges.

        Raises:
        ------
        StateError
            If called before :meth:`extract`.
        """
        if not self._extracted:
            raise StateError(
                "UnityCatalogSchemaConnector.transform() called before extract().",
                suggestion="Call connector.extract(catalog=...) before connector.transform().",
            )
        self._transformed = False
        logger.info("Transforming Unity Catalog schema metadata...")
        e = self.extractor
        t = self.transformer

        t.transform_to_database_nodes(e.catalog_info)
        t.transform_to_schema_nodes(e.schema_info)
        t.transform_to_table_nodes(e.table_info)
        t.transform_to_column_nodes(e.column_info)

        t.transform_to_has_schema_relationships(e.schema_info)
        t.transform_to_has_table_relationships(e.table_info)
        t.transform_to_has_column_relationships(e.column_info)
        log_transform_counts(logger, t, _TRANSFORM_COUNTS)
        self._transformed = True

    def load(self) -> None:
        """
        Load transformed nodes and relationships into Neo4j.

        Raises:
        ------
        StateError
            If called before :meth:`transform`.
        """
        if not self._transformed:
            raise StateError(
                "UnityCatalogSchemaConnector.load() called before transform(); "
                "call .transform() first.",
                suggestion="Call connector.extract() and connector.transform() first.",
            )
        t = self.transformer

        logger.info("Loading Unity Catalog schema metadata into Neo4j...")
        self.loader.load_database_nodes(t.database_nodes)
        self.loader.load_schema_nodes(t.schema_nodes)
        self.loader.load_table_nodes(t.table_nodes)
        self.loader.load_column_nodes(
            t.column_nodes, properties_list=["name", "description", "type"]
        )

        self.loader.load_has_schema_relationships(t.has_schema_relationships)
        self.loader.load_has_table_relationships(t.has_table_relationships)
        self.loader.load_has_column_relationships(t.has_column_relationships)

    def ingest(
        self,
        catalog: str,
        schemas: list[str] | None = None,
        *,
        include_nodes: list[NodeLabel] | None = None,
        include_relationships: list[RelationshipType] | None = None,
    ) -> None:
        """
        Run the Unity Catalog schema connector (extract → transform → load).

        Parameters
        ----------
        catalog : str
            The Unity Catalog catalog name to ingest.
        schemas : list[str] | None, default None
            Optional client-side filter restricting ingestion to these schemas.
        include_nodes : list[NodeLabel] | None, default None
            Node labels to produce. ``None`` includes all available.
        include_relationships : list[RelationshipType] | None, default None
            Relationship types to produce. ``None`` includes all available.
        """
        self.extract(
            catalog,
            schemas,
            include_nodes=include_nodes,
            include_relationships=include_relationships,
        )
        self.transform()
        self.load()
        self.loader.upsert_neocarta_graph_node()
        logger.info("Recorded neocarta graph metadata")
        logger.info("Unity Catalog schema connector completed successfully")

    def run(
        self,
        catalog: str,
        schemas: list[str] | None = None,
        *,
        include_nodes: list[NodeLabel] | None = None,
        include_relationships: list[RelationshipType] | None = None,
    ) -> None:
        """
        Run the Unity Catalog schema connector.

        .. deprecated::
            Use :meth:`ingest` instead. ``run`` will be removed in a future release.
        """
        warnings.warn(
            "UnityCatalogSchemaConnector.run() is deprecated; "
            "use UnityCatalogSchemaConnector.ingest() instead.",
            DeprecationWarning,
            stacklevel=2,
        )
        self.ingest(
            catalog,
            schemas,
            include_nodes=include_nodes,
            include_relationships=include_relationships,
        )
