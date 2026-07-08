"""Snowflake query log connector."""

from __future__ import annotations

import logging
import warnings
from typing import TYPE_CHECKING

from ...._logging import log_transform_counts
from ....errors import ConfigError, StateError
from ....ingest.rdbms import Neo4jRDBMSLoader
from ...query_log.transform import QueryLogTransformer
from .extract import SnowflakeLogsExtractor

if TYPE_CHECKING:
    from typing import Self

    from neo4j import Driver
    from snowflake.connector import SnowflakeConnection

logger = logging.getLogger(__name__)

# (human label, transformer attribute) pairs logged at the end of transform().
_TRANSFORM_COUNTS = (
    ("databases", "database_nodes"),
    ("schemas", "schema_nodes"),
    ("tables", "table_nodes"),
    ("columns", "column_nodes"),
    ("queries", "query_nodes"),
    ("CTEs", "cte_nodes"),
)


class SnowflakeLogsConnector:
    """
    Connector for extracting Snowflake query logs into Neo4j.

    Reads ``SNOWFLAKE.ACCOUNT_USAGE.QUERY_HISTORY`` over the injected
    ``snowflake.connector`` (DB-API 2.0) connection, parses each statement into
    table/column usage, and loads ``Query``/``CTE`` nodes and the
    ``USES_TABLE``/``USES_COLUMN``/``DEFINES`` edges (plus the RDBMS scaffolding
    they touch). Follows an Extract → Transform → Load pipeline; :meth:`ingest`
    runs all three stages and records the neocarta graph metadata node at the end.

    The caller constructs and owns the ``connection`` (mirroring how the BigQuery
    connector takes a ``client``); :meth:`close` is a no-op and never closes it.

    Parameters
    ----------
    connection : snowflake.connector.SnowflakeConnection
        An open ``snowflake.connector`` connection with access to
        ``SNOWFLAKE.ACCOUNT_USAGE``.
    database : str
        The Snowflake database whose queries to read (the ``:Database``; used to
        filter ``QUERY_HISTORY`` and as the default project when resolving names).
    neo4j_driver : Driver
        The Neo4j driver.
    database_name : str, default "neo4j"
        The Neo4j database name.
    """

    def __init__(
        self,
        connection: SnowflakeConnection,
        database: str,
        neo4j_driver: Driver,
        database_name: str = "neo4j",
    ) -> None:
        """Initialize the Snowflake logs connector."""
        if connection is None:
            raise ConfigError(
                "connection is required for the Snowflake logs connector.",
                suggestion="Pass connection=snowflake.connector.connect(...).",
            )
        if not database:
            raise ConfigError(
                "database is required for the Snowflake logs connector.",
                suggestion="Pass database=... (the Snowflake database name).",
            )
        if neo4j_driver is None:
            raise ConfigError(
                "neo4j_driver is required for the Snowflake logs connector.",
                suggestion="Pass neo4j_driver=GraphDatabase.driver(...).",
            )

        self.connection = connection
        self.database = database
        self.neo4j_driver = neo4j_driver
        self.database_name = database_name

        self.extractor = SnowflakeLogsExtractor(connection, database)
        self.transformer = QueryLogTransformer()
        self.loader = Neo4jRDBMSLoader(neo4j_driver, database_name)
        self._extracted = False
        self._transformed = False

    def close(self) -> None:
        """No connector-owned resources to release; the injected connection/driver are the caller's."""

    def __enter__(self) -> Self:
        """Return self for use as a context manager."""
        return self

    def __exit__(self, exc_type: object, exc_value: object, traceback: object) -> None:
        """Release owned resources on context-manager exit."""
        self.close()

    def extract(
        self,
        schema: str | None = None,
        start_timestamp: str | None = None,
        end_timestamp: str | None = None,
        limit: int = 100,
        drop_failed_queries: bool = True,
    ) -> None:
        """
        Extract and cache query logs from Snowflake.

        Parameters
        ----------
        schema : str, optional
            The schema to filter queries by (and default schema for name resolution).
        start_timestamp : str, optional
            Start timestamp for query window.
        end_timestamp : str, optional
            End timestamp for query window.
        limit : int, default 100
            Maximum number of queries to extract.
        drop_failed_queries : bool, default True
            Whether to exclude failed queries.
        """
        logger.info("Extracting Snowflake query logs...")
        self._extracted = False
        self._transformed = False
        self.extractor.extract_query_logs(
            schema=schema,
            start_timestamp=start_timestamp,
            end_timestamp=end_timestamp,
            limit=limit,
            drop_failed_queries=drop_failed_queries,
            cache=True,
        )
        self._extracted = True

    def transform(self) -> None:
        """
        Transform cached query log metadata into graph data model objects.

        Raises:
        ------
        StateError
            If called before :meth:`extract`.
        """
        if not self._extracted:
            raise StateError(
                "SnowflakeLogsConnector.transform() called before extract().",
                suggestion="Call connector.extract() before connector.transform().",
            )
        self._transformed = False
        logger.info("Transforming Snowflake query log metadata...")

        # Transform nodes
        self.transformer.transform_to_database_nodes(self.extractor.database_info)
        self.transformer.transform_to_schema_nodes(self.extractor.schema_info)
        self.transformer.transform_to_table_nodes(self.extractor.table_info)
        self.transformer.transform_to_column_nodes(self.extractor.column_info)
        self.transformer.transform_to_query_nodes(self.extractor.query_info)
        self.transformer.transform_to_cte_nodes(self.extractor.cte_info)

        # Transform relationships
        self.transformer.transform_to_has_schema_relationships(self.extractor.schema_info)
        self.transformer.transform_to_has_table_relationships(self.extractor.table_info)
        self.transformer.transform_to_has_column_relationships(self.extractor.column_info)
        self.transformer.transform_to_references_relationships(
            self.extractor.column_references_info
        )
        self.transformer.transform_to_uses_table_relationships(self.extractor.query_table_info)
        self.transformer.transform_to_uses_column_relationships(self.extractor.query_column_info)
        self.transformer.transform_to_defines_relationships(self.extractor.cte_info)
        log_transform_counts(logger, self.transformer, _TRANSFORM_COUNTS)
        self._transformed = True

    def load(self) -> None:
        """
        Load transformed query log metadata into Neo4j.

        Raises:
        ------
        StateError
            If called before :meth:`transform`.
        """
        if not self._transformed:
            raise StateError(
                "SnowflakeLogsConnector.load() called before transform(); call .transform() first.",
                suggestion="Call connector.extract() and connector.transform() first.",
            )

        logger.info("Loading Snowflake query log metadata into Neo4j...")
        # Load nodes
        self.loader.load_database_nodes(
            self.transformer.database_nodes, properties_list=["name", "service", "platform"]
        )
        self.loader.load_schema_nodes(self.transformer.schema_nodes, properties_list=["name"])
        self.loader.load_table_nodes(self.transformer.table_nodes, properties_list=["name"])
        self.loader.load_column_nodes(self.transformer.column_nodes, properties_list=["name"])
        self.loader.load_query_nodes(self.transformer.query_nodes)
        self.loader.load_cte_nodes(self.transformer.cte_nodes)

        # Load relationships
        self.loader.load_has_schema_relationships(self.transformer.has_schema_relationships)
        self.loader.load_has_table_relationships(self.transformer.has_table_relationships)
        self.loader.load_has_column_relationships(self.transformer.has_column_relationships)
        self.loader.load_references_relationships(self.transformer.references_relationships)
        self.loader.load_uses_table_relationships(self.transformer.uses_table_relationships)
        self.loader.load_uses_column_relationships(self.transformer.uses_column_relationships)
        self.loader.load_defines_relationships(self.transformer.defines_relationships)

    def ingest(
        self,
        schema: str | None = None,
        start_timestamp: str | None = None,
        end_timestamp: str | None = None,
        limit: int = 100,
        drop_failed_queries: bool = True,
    ) -> None:
        """
        Run the Snowflake logs connector (extract → transform → load).

        Parameters
        ----------
        schema : str, optional
            The schema to filter queries by (and default schema for name resolution).
        start_timestamp : str, optional
            Start timestamp for query window.
        end_timestamp : str, optional
            End timestamp for query window.
        limit : int, default 100
            Maximum number of queries to extract.
        drop_failed_queries : bool, default True
            Whether to exclude failed queries.
        """
        self.extract(
            schema=schema,
            start_timestamp=start_timestamp,
            end_timestamp=end_timestamp,
            limit=limit,
            drop_failed_queries=drop_failed_queries,
        )
        self.transform()
        self.load()
        self.loader.upsert_neocarta_graph_node()
        logger.info("Recorded neocarta graph metadata")
        logger.info("Snowflake logs connector completed successfully")

    def run(
        self,
        schema: str | None = None,
        start_timestamp: str | None = None,
        end_timestamp: str | None = None,
        limit: int = 100,
        drop_failed_queries: bool = True,
    ) -> None:
        """
        Run the Snowflake logs connector.

        .. deprecated::
            Use :meth:`ingest` instead. ``run`` will be removed in a future release.
        """
        warnings.warn(
            "SnowflakeLogsConnector.run() is deprecated; "
            "use SnowflakeLogsConnector.ingest() instead.",
            DeprecationWarning,
            stacklevel=2,
        )
        self.ingest(
            schema=schema,
            start_timestamp=start_timestamp,
            end_timestamp=end_timestamp,
            limit=limit,
            drop_failed_queries=drop_failed_queries,
        )
