"""Shared Extract → Transform → Load lifecycle for RDBMS schema connectors.

The Snowflake and Databricks schema connectors run an identical pipeline over the
core RDBMS data model — only their driver/connection type, the caller-facing
argument name (``database`` vs ``catalog``), the display name in log/error text,
and the per-source schema-identifier resolution differ. This base holds the shared
lifecycle (state guards, transform, load, ingest/run, context manager, close);
each subclass supplies its extractor/transformer in ``__init__`` and overrides
:meth:`_resolve_schema`.

The caller constructs and owns the ``connection`` (mirroring how the BigQuery
connector takes a ``client``); :meth:`close` is a no-op and never closes it.
"""

from __future__ import annotations

import logging
import warnings
from typing import TYPE_CHECKING, ClassVar

from ..._logging import log_transform_counts
from ...errors import ConfigError, StateError
from ...ingest.rdbms import Neo4jRDBMSLoader

if TYPE_CHECKING:
    from typing import Self

    from neo4j import Driver

# (human label, transformer attribute) pairs logged at the end of transform().
_TRANSFORM_COUNTS = (
    ("databases", "database_nodes"),
    ("schemas", "schema_nodes"),
    ("tables", "table_nodes"),
    ("columns", "column_nodes"),
    ("values", "value_nodes"),
)


class RdbmsSchemaConnector:
    """Extract → Transform → Load lifecycle shared by RDBMS schema connectors.

    Subclasses build the extractor/transformer in their own ``__init__`` (preserving
    the caller-facing argument name and validation messages), set ``_DISPLAY_NAME``,
    and override :meth:`_resolve_schema` for source-specific identifier handling.
    """

    #: Human-readable source name used in log lines (e.g. ``"Snowflake"``).
    _DISPLAY_NAME: ClassVar[str] = "RDBMS"

    @property
    def _logger(self) -> logging.Logger:
        """Logger attributed to the concrete connector's module (not this base module)."""
        return logging.getLogger(type(self).__module__)

    def _init_pipeline(
        self,
        *,
        connection: object,
        neo4j_driver: Driver,
        database_name: str,
        extractor: object,
        transformer: object,
    ) -> None:
        """Wire the shared pipeline state (loader, caches, stage flags).

        Called by each subclass ``__init__`` after it has validated its inputs and
        built the source-specific ``extractor`` / ``transformer``.
        """
        self.connection = connection
        self.neo4j_driver = neo4j_driver
        self.database_name = database_name
        self.extractor = extractor
        self.transformer = transformer
        self.loader = Neo4jRDBMSLoader(neo4j_driver, database_name)
        self._extracted = False
        self._transformed = False

    def _resolve_schema(self, schema: str) -> str:
        """Resolve / validate a schema identifier before extraction.

        Default is identity; subclasses override to fold case, reject malformed
        names, etc. Returns the resolved schema used for every extractor call.
        """
        return schema

    def close(self) -> None:
        """No connector-owned resources to release; the injected connection/driver are the caller's."""

    def __enter__(self) -> Self:
        """Return self for use as a context manager."""
        return self

    def __exit__(self, exc_type: object, exc_value: object, traceback: object) -> None:
        """Release owned resources on context-manager exit."""
        self.close()

    def extract(self, schema: str) -> None:
        """Extract and cache schema metadata for one schema.

        Parameters
        ----------
        schema : str
            The schema to extract within the connector's database/catalog. Resolved
            via :meth:`_resolve_schema` (source-specific).

        Raises:
        ------
        ConfigError
            If ``schema`` is empty or a malformed identifier.
        """
        if not schema:
            raise ConfigError(
                f"schema is required for the {self._DISPLAY_NAME} schema connector.",
                suggestion="Pass connector.ingest(schema=...) / connector.extract(schema=...).",
            )
        schema = self._resolve_schema(schema)
        self._logger.info("Extracting %s schema metadata...", self._DISPLAY_NAME)
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
        """Transform cached metadata into graph data-model objects.

        Raises:
        ------
        StateError
            If called before :meth:`extract`.
        """
        if not self._extracted:
            raise StateError(
                f"{type(self).__name__}.transform() called before extract().",
                suggestion="Call connector.extract(schema=...) before connector.transform().",
            )
        self._transformed = False
        self._logger.info("Transforming %s schema metadata...", self._DISPLAY_NAME)
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
        log_transform_counts(self._logger, self.transformer, _TRANSFORM_COUNTS)
        self._transformed = True

    def load(self) -> None:
        """Load transformed metadata into Neo4j.

        Raises:
        ------
        StateError
            If called before :meth:`transform`.
        """
        if not self._transformed:
            raise StateError(
                f"{type(self).__name__}.load() called before transform(); call .transform() first.",
                suggestion="Call connector.extract() and connector.transform() first.",
            )
        self._logger.info("Loading %s schema metadata into Neo4j...", self._DISPLAY_NAME)
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
        """Run the connector (extract → transform → load) for one schema.

        Parameters
        ----------
        schema : str
            The schema to ingest within the connector's database/catalog.
        """
        self.extract(schema)
        self.transform()
        self.load()
        self.loader.upsert_neocarta_graph_node()
        self._logger.info("Recorded neocarta graph metadata")
        self._logger.info("%s schema connector completed successfully", self._DISPLAY_NAME)

    def run(self, schema: str) -> None:
        """Run the connector.

        .. deprecated::
            Use :meth:`ingest` instead. ``run`` will be removed in a future release.
        """
        name = type(self).__name__
        warnings.warn(
            f"{name}.run() is deprecated; use {name}.ingest() instead.",
            DeprecationWarning,
            stacklevel=2,
        )
        self.ingest(schema)
