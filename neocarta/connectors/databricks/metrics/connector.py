"""Databricks Unity Catalog metrics sub-connector."""

from __future__ import annotations

import logging
import warnings
from typing import TYPE_CHECKING

from ...._logging import log_transform_counts
from ....errors import ConfigError, StateError
from ...osi.load import OsiNeo4jLoader
from .extract import DatabricksMetricsExtractor
from .transform import DatabricksMetricsTransformer

if TYPE_CHECKING:
    from typing import Self

    from databricks.sql.client import Connection
    from neo4j import Driver

logger = logging.getLogger(__name__)

# (human label, transformer attribute) pairs logged at the end of transform().
_TRANSFORM_COUNTS = (
    ("metric views", "osi_semantic_model_nodes"),
    ("tables", "table_nodes"),
    ("dimensions", "column_nodes"),
    ("metrics", "metric_nodes"),
    ("expressions", "expression_nodes"),
    ("AI contexts", "ai_context_nodes"),
    ("business terms", "business_term_nodes"),
)


class DatabricksMetricsConnector:
    """
    Connector for ingesting Databricks Unity Catalog **metric views** into Neo4j.

    Reads metric-view (Business Semantics) definitions from a catalog's
    ``<catalog>.information_schema.*`` views over a Databricks SQL warehouse using
    the injected ``databricks.sql`` (DB-API) connection — no Spark, no JDBC — and
    maps them onto neocarta's existing **OSI** semantic-model nodes:
    ``OsiSemanticModel``/``OsiTable``/``OsiColumn``/``Metric``/``Expression``/
    ``OsiAiContext`` and their ``HAS_METRIC``/``HAS_COLUMN``/``HAS_EXPRESSION``/
    ``HAS_ASPECT``/``HAS_TABLE`` (Domain→Table) edges.

    Follows an Extract → Transform → Load pipeline; :meth:`ingest` runs all three
    stages and records the neocarta graph metadata node at the end. One schema is
    ingested per call (``ingest(schema=...)``), mirroring the Databricks schema
    connector.

    The caller constructs and owns the ``connection`` (mirroring how the schema
    connector takes a ``databricks.sql`` connection and the BigQuery connector a
    ``client``); :meth:`close` is a no-op and never closes it.

    Parameters
    ----------
    connection : databricks.sql.client.Connection
        An open ``databricks.sql`` connection to a SQL warehouse.
    catalog : str
        The Unity Catalog catalog to read.
    neo4j_driver : Driver
        Neo4j driver instance.
    database_name : str, default "neo4j"
        Target Neo4j database name.
    """

    def __init__(
        self,
        connection: Connection,
        catalog: str,
        neo4j_driver: Driver,
        database_name: str = "neo4j",
    ) -> None:
        """Initialize the Databricks metrics connector."""
        if connection is None:
            raise ConfigError(
                "connection is required for the Databricks metrics connector.",
                suggestion="Pass connection=databricks.sql.connect(...).",
            )
        if not catalog:
            raise ConfigError(
                "catalog is required for the Databricks metrics connector.",
                suggestion="Pass catalog=... (the Unity Catalog catalog name).",
            )
        if neo4j_driver is None:
            raise ConfigError(
                "neo4j_driver is required for the Databricks metrics connector.",
                suggestion="Pass neo4j_driver=GraphDatabase.driver(...).",
            )

        self.connection = connection
        self.catalog = catalog
        self.neo4j_driver = neo4j_driver
        self.database_name = database_name

        self.extractor = DatabricksMetricsExtractor(connection, catalog)
        self.transformer = DatabricksMetricsTransformer()
        self.loader = OsiNeo4jLoader(neo4j_driver, database_name)
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
        Extract and cache Databricks metric-view definitions for one schema.

        Parameters
        ----------
        schema : str
            The Unity Catalog schema to scan within the connector's catalog.

        Raises:
        ------
        ConfigError
            If ``schema`` is empty or contains a backtick (a malformed identifier).
        """
        if not schema:
            raise ConfigError(
                "schema is required for the Databricks metrics connector.",
                suggestion="Pass connector.ingest(schema=...) / connector.extract(schema=...).",
            )
        if "`" in schema:
            raise ConfigError(
                f"Invalid schema identifier {schema!r}: backticks are not allowed.",
                suggestion="Pass a schema name without backtick characters.",
            )
        logger.info("Extracting Databricks metric views...")
        self._extracted = False
        self._transformed = False
        self.extractor.extract_metric_views(schema=schema)
        self._extracted = True

    def transform(self) -> None:
        """
        Transform cached metric-view definitions into OSI graph objects.

        Raises:
        ------
        StateError
            If called before :meth:`extract`.
        """
        if not self._extracted:
            raise StateError(
                "DatabricksMetricsConnector.transform() called before extract().",
                suggestion="Call connector.extract(schema=...) before connector.transform().",
            )
        self._transformed = False
        logger.info("Transforming Databricks metric views...")
        self.transformer.transform(self.extractor.metric_views)
        log_transform_counts(logger, self.transformer, _TRANSFORM_COUNTS)
        self._transformed = True

    def load(self) -> None:
        """
        Load transformed OSI metadata into Neo4j.

        Raises:
        ------
        StateError
            If called before :meth:`transform`.
        """
        if not self._transformed:
            raise StateError(
                "DatabricksMetricsConnector.load() called before transform(); call .transform() first.",
                suggestion="Call connector.extract() and connector.transform() first.",
            )
        logger.info("Loading Databricks metric views into Neo4j...")
        transformer = self.transformer
        loader = self.loader

        # Nodes before relationships; parents before children. Each list is
        # written only when non-empty so an empty schema stays quiet. Property
        # lists omit undefined fields (e.g. OsiColumn key flags) so no fabricated
        # values are written.
        if transformer.osi_semantic_model_nodes:
            loader.load_osi_semantic_model_nodes(transformer.osi_semantic_model_nodes)
        if transformer.table_nodes:
            loader.load_osi_table_nodes(
                transformer.table_nodes,
                properties_list=["name", "description", "source"],
            )
        if transformer.column_nodes:
            loader.load_osi_column_nodes(
                transformer.column_nodes,
                properties_list=["name", "description", "label"],
            )
        if transformer.metric_nodes:
            loader.load_metric_nodes(transformer.metric_nodes)
        if transformer.expression_nodes:
            loader.load_expression_nodes(transformer.expression_nodes)
        if transformer.ai_context_nodes:
            loader.load_osi_ai_context_nodes(transformer.ai_context_nodes)
        if transformer.business_term_nodes:
            loader.load_business_term_nodes_by_name(
                transformer.business_term_nodes, properties_list=[]
            )

        if transformer.domain_has_table_rels:
            loader.load_domain_has_table_relationships(transformer.domain_has_table_rels)
        if transformer.has_column_rels:
            loader.load_has_column_relationships(transformer.has_column_rels)
        if transformer.has_metric_rels:
            loader.load_has_metric_relationships(transformer.has_metric_rels)
        if transformer.has_expression_rels:
            loader.load_has_expression_relationships(transformer.has_expression_rels)
        if transformer.has_aspect_rels:
            loader.load_has_aspect_relationships(transformer.has_aspect_rels)
        if transformer.tagged_with_rels:
            loader.load_osi_tagged_with_relationships(
                transformer.tagged_with_rels, transformer.business_term_nodes
            )

    def ingest(self, schema: str) -> None:
        """
        Run the Databricks metrics connector (extract → transform → load).

        Parameters
        ----------
        schema : str
            The Unity Catalog schema to ingest within the connector's catalog.
        """
        self.extract(schema)
        self.transform()
        self.load()
        self.loader.upsert_neocarta_graph_node()
        logger.info("Recorded neocarta graph metadata")
        logger.info("Databricks metrics connector completed successfully")

    def run(self, schema: str) -> None:
        """
        Run the Databricks metrics connector.

        .. deprecated::
            Use :meth:`ingest` instead. ``run`` will be removed in a future release.
        """
        warnings.warn(
            "DatabricksMetricsConnector.run() is deprecated; "
            "use DatabricksMetricsConnector.ingest() instead.",
            DeprecationWarning,
            stacklevel=2,
        )
        self.ingest(schema)
