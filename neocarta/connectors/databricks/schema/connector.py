"""Databricks Unity Catalog schema sub-connector."""

from __future__ import annotations

from typing import TYPE_CHECKING

from ....errors import ConfigError
from ...utils.rdbms_schema_connector import RdbmsSchemaConnector
from .extract import DatabricksSchemaExtractor
from .transform import DatabricksSchemaTransformer

if TYPE_CHECKING:
    from databricks.sql.client import Connection
    from neo4j import Driver


class DatabricksSchemaConnector(RdbmsSchemaConnector):
    """Connector for ingesting Databricks Unity Catalog schema metadata into Neo4j.

    Reads a catalog's ``<catalog>.information_schema.*`` views over a Databricks SQL
    warehouse using the injected ``databricks.sql`` (DB-API) connection — no Spark,
    no JDBC — and maps them onto the core RDBMS data model:
    ``Database``/``Schema``/``Table``/``Column``/``Value`` nodes and the
    ``HAS_SCHEMA``/``HAS_TABLE``/``HAS_COLUMN``/``HAS_VALUE``/``REFERENCES`` edges.

    Follows an Extract → Transform → Load pipeline (shared with the Snowflake schema
    connector via :class:`RdbmsSchemaConnector`); :meth:`ingest` runs all three stages
    and records the neocarta graph metadata node at the end. One schema is ingested
    per call (``ingest(schema=...)``), analogous to the BigQuery schema connector's
    per-dataset model.

    The caller constructs and owns the ``connection`` (mirroring how the BigQuery
    connector takes a ``client``); :meth:`close` is a no-op and never closes it.

    Parameters
    ----------
    connection : databricks.sql.client.Connection
        An open ``databricks.sql`` connection to a SQL warehouse.
    catalog : str
        The Unity Catalog catalog to read (the ``:Database``; analog of the BigQuery
        ``project_id``).
    neo4j_driver : Driver
        Neo4j driver instance.
    database_name : str, default "neo4j"
        Target Neo4j database name.
    value_sample_limit : int, default 10
        Distinct sample values to read per groupable column. ``0`` disables value
        sampling (no table-data reads, so no ``:Value`` nodes / ``HAS_VALUE`` edges).
    """

    _DISPLAY_NAME = "Databricks"

    def __init__(
        self,
        connection: Connection,
        catalog: str,
        neo4j_driver: Driver,
        database_name: str = "neo4j",
        *,
        value_sample_limit: int = 10,
    ) -> None:
        """Initialize the Databricks schema connector."""
        if connection is None:
            raise ConfigError(
                "connection is required for the Databricks schema connector.",
                suggestion="Pass connection=databricks.sql.connect(...).",
            )
        if not catalog:
            raise ConfigError(
                "catalog is required for the Databricks schema connector.",
                suggestion="Pass catalog=... (the Unity Catalog catalog name).",
            )
        if neo4j_driver is None:
            raise ConfigError(
                "neo4j_driver is required for the Databricks schema connector.",
                suggestion="Pass neo4j_driver=GraphDatabase.driver(...).",
            )

        self.catalog = catalog
        self._init_pipeline(
            connection=connection,
            neo4j_driver=neo4j_driver,
            database_name=database_name,
            extractor=DatabricksSchemaExtractor(
                connection, catalog, value_sample_limit=value_sample_limit
            ),
            transformer=DatabricksSchemaTransformer(),
        )

    def _resolve_schema(self, schema: str) -> str:
        """Validate the schema identifier (reject a backtick that could break quoting).

        Validated up front so a malformed name fails fast and uniformly, regardless of
        ``value_sample_limit`` (off the sampling path the schema is only ever a bound
        parameter, so it would otherwise never be checked).
        """
        if "`" in schema:
            raise ConfigError(
                f"Invalid schema identifier {schema!r}: backticks are not allowed.",
                suggestion="Pass a schema name without backtick characters.",
            )
        return schema
