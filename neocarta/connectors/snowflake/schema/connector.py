"""Snowflake schema sub-connector."""

from __future__ import annotations

import logging
import warnings
from typing import TYPE_CHECKING

from ...._logging import log_transform_counts
from ....errors import ConfigError, StateError
from ....ingest.rdbms import Neo4jRDBMSLoader
from .extract import SnowflakeSchemaExtractor
from .transform import SnowflakeSchemaTransformer

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
    ("values", "value_nodes"),
)


class SnowflakeSchemaConnector:
    """
    Connector for ingesting Snowflake schema metadata into Neo4j.

    Reads a database's ``<database>.INFORMATION_SCHEMA.*`` views (and ``SHOW
    PRIMARY KEYS`` / ``SHOW IMPORTED KEYS`` for keys, which Snowflake's
    INFORMATION_SCHEMA does not expose per-column) over the injected
    ``snowflake.connector`` (DB-API 2.0) connection, and maps them onto the core
    RDBMS data model: ``Database``/``Schema``/``Table``/``Column``/``Value`` nodes
    and the ``HAS_SCHEMA``/``HAS_TABLE``/``HAS_COLUMN``/``HAS_VALUE``/``REFERENCES``
    edges.

    Follows an Extract → Transform → Load pipeline; :meth:`ingest` runs all three
    stages and records the neocarta graph metadata node at the end. One schema is
    ingested per call (``ingest(schema=...)``), analogous to the BigQuery schema
    connector's per-dataset model.

    The caller constructs and owns the ``connection`` (mirroring how the BigQuery
    connector takes a ``client``); :meth:`close` is a no-op and never closes it.

    Parameters
    ----------
    connection : snowflake.connector.SnowflakeConnection
        An open ``snowflake.connector`` connection. The connection's warehouse and
        role must be able to read the target database's ``INFORMATION_SCHEMA`` (and
        run ``SHOW ... KEYS``).
    database : str
        The Snowflake database to read (the ``:Database``; analog of the BigQuery
        ``project_id`` / Databricks ``catalog``). Each database has its own
        ``INFORMATION_SCHEMA``.
    neo4j_driver : Driver
        Neo4j driver instance.
    database_name : str, default "neo4j"
        Target Neo4j database name.
    value_sample_limit : int, default 10
        Distinct sample values to read per groupable column. ``0`` disables value
        sampling (no table-data reads, so no ``:Value`` nodes / ``HAS_VALUE`` edges).
    """

    def __init__(
        self,
        connection: SnowflakeConnection,
        database: str,
        neo4j_driver: Driver,
        database_name: str = "neo4j",
        *,
        value_sample_limit: int = 10,
    ) -> None:
        """Initialize the Snowflake schema connector."""
        if connection is None:
            raise ConfigError(
                "connection is required for the Snowflake schema connector.",
                suggestion="Pass connection=snowflake.connector.connect(...).",
            )
        if not database:
            raise ConfigError(
                "database is required for the Snowflake schema connector.",
                suggestion="Pass database=... (the Snowflake database name).",
            )
        if neo4j_driver is None:
            raise ConfigError(
                "neo4j_driver is required for the Snowflake schema connector.",
                suggestion="Pass neo4j_driver=GraphDatabase.driver(...).",
            )

        self.connection = connection
        self.database = database
        self.neo4j_driver = neo4j_driver
        self.database_name = database_name

        self.extractor = SnowflakeSchemaExtractor(
            connection, database, value_sample_limit=value_sample_limit
        )
        self.transformer = SnowflakeSchemaTransformer()
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

    def extract(self, schema: str) -> None:
        """
        Extract and cache Snowflake schema metadata for one schema.

        Parameters
        ----------
        schema : str
            The schema to extract within the connector's database.

        Raises:
        ------
        ConfigError
            If ``schema`` is empty or contains a double-quote (a malformed identifier).
        """
        if not schema:
            raise ConfigError(
                "schema is required for the Snowflake schema connector.",
                suggestion="Pass connector.ingest(schema=...) / connector.extract(schema=...).",
            )
        # Validate the schema identifier up front so a malformed name fails fast and
        # uniformly, regardless of value_sample_limit (off the sampling path the schema is
        # only ever a bound parameter, so it would otherwise never be checked).
        if '"' in schema:
            raise ConfigError(
                f"Invalid schema identifier {schema!r}: double-quotes are not allowed.",
                suggestion="Pass a schema name without double-quote characters.",
            )
        logger.info("Extracting Snowflake schema metadata...")
        self._extracted = False
        self._transformed = False
        self.extractor.extract_database_info(cache=True)
        self.extractor.extract_schema_info(schema=schema)
        self.extractor.extract_table_info(schema=schema)
        self.extractor.extract_column_info(schema=schema)
        self.extractor.extract_column_references_info(schema=schema)
        self.extractor.extract_column_unique_values_for_all_tables(schema=schema)
        self._extracted = True

    def transform(self) -> None:
        """
        Transform cached metadata into graph data model objects.

        Raises:
        ------
        StateError
            If called before :meth:`extract`.
        """
        if not self._extracted:
            raise StateError(
                "SnowflakeSchemaConnector.transform() called before extract().",
                suggestion="Call connector.extract(schema=...) before connector.transform().",
            )
        self._transformed = False
        logger.info("Transforming Snowflake schema metadata...")
        self.transformer.transform_to_database_nodes(self.extractor.database_info)
        self.transformer.transform_to_schema_nodes(self.extractor.schema_info)
        self.transformer.transform_to_table_nodes(self.extractor.table_info)
        self.transformer.transform_to_column_nodes(self.extractor.column_info)
        self.transformer.transform_to_value_nodes(self.extractor.column_unique_values)

        self.transformer.transform_to_has_schema_relationships(self.extractor.schema_info)
        self.transformer.transform_to_has_table_relationships(self.extractor.table_info)
        self.transformer.transform_to_has_column_relationships(self.extractor.column_info)
        self.transformer.transform_to_references_relationships(
            self.extractor.column_references_info
        )
        self.transformer.transform_to_has_value_relationships(self.extractor.column_unique_values)
        log_transform_counts(logger, self.transformer, _TRANSFORM_COUNTS)
        self._transformed = True

    def load(self) -> None:
        """
        Load transformed metadata into Neo4j.

        Raises:
        ------
        StateError
            If called before :meth:`transform`.
        """
        if not self._transformed:
            raise StateError(
                "SnowflakeSchemaConnector.load() called before transform(); call .transform() first.",
                suggestion="Call connector.extract() and connector.transform() first.",
            )
        logger.info("Loading Snowflake schema metadata into Neo4j...")
        self.loader.load_database_nodes(self.transformer.database_nodes)
        self.loader.load_schema_nodes(self.transformer.schema_nodes)
        self.loader.load_table_nodes(self.transformer.table_nodes)
        self.loader.load_column_nodes(self.transformer.column_nodes)
        self.loader.load_value_nodes(self.transformer.value_nodes)

        self.loader.load_has_schema_relationships(self.transformer.has_schema_relationships)
        self.loader.load_has_table_relationships(self.transformer.has_table_relationships)
        self.loader.load_has_column_relationships(self.transformer.has_column_relationships)
        self.loader.load_references_relationships(self.transformer.references_relationships)
        self.loader.load_has_value_relationships(self.transformer.has_value_relationships)

    def ingest(self, schema: str) -> None:
        """
        Run the Snowflake schema connector (extract → transform → load).

        Parameters
        ----------
        schema : str
            The schema to ingest within the connector's database.
        """
        self.extract(schema)
        self.transform()
        self.load()
        self.loader.upsert_neocarta_graph_node()
        logger.info("Recorded neocarta graph metadata")
        logger.info("Snowflake schema connector completed successfully")

    def run(self, schema: str) -> None:
        """
        Run the Snowflake schema connector.

        .. deprecated::
            Use :meth:`ingest` instead. ``run`` will be removed in a future release.
        """
        warnings.warn(
            "SnowflakeSchemaConnector.run() is deprecated; "
            "use SnowflakeSchemaConnector.ingest() instead.",
            DeprecationWarning,
            stacklevel=2,
        )
        self.ingest(schema)
