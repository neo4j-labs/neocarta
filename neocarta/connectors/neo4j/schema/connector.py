"""Neo4jSchemaConnector connector."""

import logging
import warnings
from typing import Self

from neo4j import Driver

from ...._logging import log_transform_counts
from ....errors import StateError
from ....ingest.rdbms import Neo4jRDBMSLoader
from .extract import Neo4jSchemaExtractor
from .transform import Neo4jSchemaTransformer

logger = logging.getLogger(__name__)

# (human label, transformer attribute) pairs logged at the end of transform().
# log_transform_counts skips zero-count types, so an unfilled tuple stays quiet.
# TODO: add a pair per produced node / relationship list — e.g. a "tables" label
# for the "table_nodes" attribute; see csv/connector.py for a full example.
_TRANSFORM_COUNTS: tuple[tuple[str, str], ...] = ()


class Neo4jSchemaConnector:
    """
    Connector for loading neo4j schema metadata into Neo4j.

    Follows an Extract → Transform → Load pipeline. :meth:`ingest` runs all
    three stages and records the neocarta graph metadata node at the end.

    Parameters
    ----------
    neo4j_driver : Driver
        Neo4j driver instance.
    database_name : str, default "neo4j"
        Target Neo4j database name.
    """

    def __init__(self, neo4j_driver: Driver, database_name: str = "neo4j") -> None:
        """Initialize the neo4j schema connector."""
        self.neo4j_driver = neo4j_driver
        self.database_name = database_name

        self.extractor = Neo4jSchemaExtractor()
        self.transformer = Neo4jSchemaTransformer()
        self.loader = Neo4jRDBMSLoader(neo4j_driver, database_name)
        self._extracted = False
        self._transformed = False

    def close(self) -> None:
        """Release any resources the connector owns; the injected driver is the caller's."""

    def __enter__(self) -> Self:
        """Return self for use as a context manager."""
        return self

    def __exit__(self, exc_type: object, exc_value: object, traceback: object) -> None:
        """Release owned resources on context-manager exit."""
        self.close()

    def extract(self, source: str | None = None) -> None:
        """
        Read from the external system and populate the extractor cache.

        Each call replaces any previously cached extract state.

        Parameters
        ----------
        source : str, optional
            Source-specific input (e.g. a dataset id, file path, API handle).
        """
        self._extracted = False
        self._transformed = False
        self.extractor.extract(source)
        self._extracted = True

    def transform(self) -> None:
        """
        Convert cached extract state into graph data model objects.

        Raises:
        ------
        StateError
            If called before :meth:`extract`.
        """
        if not self._extracted:
            raise StateError(
                "Neo4jSchemaConnector.transform() called before extract(); call .extract() first.",
                suggestion="Call connector.extract(...) before connector.transform().",
            )
        self._transformed = False
        logger.info("Transforming neo4j schema metadata...")
        # TODO: drive self.transformer here, reading self.extractor.* caches.
        log_transform_counts(logger, self.transformer, _TRANSFORM_COUNTS)
        self._transformed = True

    def load(self) -> None:
        """
        Write transformed objects into Neo4j.

        Raises:
        ------
        StateError
            If called before :meth:`transform`.
        """
        if not self._transformed:
            raise StateError(
                "Neo4jSchemaConnector.load() called before transform(); call .transform() first.",
                suggestion="Call connector.extract() and connector.transform() first.",
            )
        logger.info("Loading neo4j schema metadata into Neo4j...")
        # TODO: self.loader.load_*_nodes(self.transformer.*_nodes, ...)
        # The loader logs each write by its graph pattern + merge counts itself,
        # so don't re-log per-type counts here.

    def ingest(self, source: str | None = None) -> None:
        """
        Run the neo4j schema connector (extract → transform → load).

        Parameters
        ----------
        source : str, optional
            Source-specific input forwarded to :meth:`extract`.
        """
        # Extract-phase progress is logged by @log_stage on the extractor's
        # methods; transform() and load() emit their own phase lines.
        self.extract(source)
        self.transform()
        self.load()
        self.loader.upsert_neocarta_graph_node()
        logger.info("Recorded neocarta graph metadata")
        logger.info("Neo4jSchemaConnector completed successfully")

    def run(self, source: str | None = None) -> None:
        """
        Run the neo4j schema connector.

        .. deprecated::
            Use :meth:`ingest` instead. ``run`` will be removed in a future release.
        """
        warnings.warn(
            "Neo4jSchemaConnector.run() is deprecated; use Neo4jSchemaConnector.ingest() instead.",
            DeprecationWarning,
            stacklevel=2,
        )
        self.ingest(source)
