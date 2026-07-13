"""Snowflake schema sub-connector."""

from __future__ import annotations

from typing import TYPE_CHECKING

from ....errors import ConfigError
from ...utils.rdbms_schema_connector import RdbmsSchemaConnector
from .._identifiers import normalize_identifier
from .extract import SnowflakeSchemaExtractor
from .transform import SnowflakeSchemaTransformer

if TYPE_CHECKING:
    from neo4j import Driver
    from snowflake.connector import SnowflakeConnection


class SnowflakeSchemaConnector(RdbmsSchemaConnector):
    """Connector for ingesting Snowflake schema metadata into Neo4j.

    Reads a database's ``<database>.INFORMATION_SCHEMA.*`` views (and ``SHOW PRIMARY
    KEYS`` / ``SHOW IMPORTED KEYS`` for keys, which Snowflake's INFORMATION_SCHEMA
    does not expose per-column) over the injected ``snowflake.connector`` (DB-API
    2.0) connection, and maps them onto the core RDBMS data model:
    ``Database``/``Schema``/``Table``/``Column``/``Value`` nodes and the
    ``HAS_SCHEMA``/``HAS_TABLE``/``HAS_COLUMN``/``HAS_VALUE``/``REFERENCES`` edges.

    Follows an Extract → Transform → Load pipeline (shared with the Databricks schema
    connector via :class:`RdbmsSchemaConnector`); :meth:`ingest` runs all three stages
    and records the neocarta graph metadata node at the end. One schema is ingested
    per call (``ingest(schema=...)``), analogous to the BigQuery schema connector's
    per-dataset model.

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

    _DISPLAY_NAME = "Snowflake"

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

        self.database = database
        self._init_pipeline(
            connection=connection,
            neo4j_driver=neo4j_driver,
            database_name=database_name,
            extractor=SnowflakeSchemaExtractor(
                connection, database, value_sample_limit=value_sample_limit
            ),
            transformer=SnowflakeSchemaTransformer(),
        )

    def _resolve_schema(self, schema: str) -> str:
        """Resolve the schema to Snowflake's stored case (also validates the identifier).

        A lower-case name is folded to upper-case (finding the stored object); a
        double-quoted name is a case-sensitive literal. The resolved value is what
        every downstream extractor query (quoted interpolation and bound parameter)
        uses, so they agree.
        """
        return normalize_identifier(schema)
