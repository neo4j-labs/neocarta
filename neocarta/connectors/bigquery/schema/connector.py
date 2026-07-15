"""BigQuery schema connector."""

from __future__ import annotations

import logging
import warnings
from typing import TYPE_CHECKING

from ...._logging import log_transform_counts
from ....errors import ConfigError, StateError
from ....ingest.rdbms import Neo4jRDBMSLoader
from ....normalization.graph_transform import NormalizedGraphTransformer
from ....normalization.information_schema.bigquery import (
    build_bigquery_information_schema_normalizer,
)
from .extract import BigQuerySchemaExtractor

if TYPE_CHECKING:
    from typing import Self

    from google.cloud import bigquery
    from neo4j import Driver

logger = logging.getLogger(__name__)

# (human label, transformer attribute) pairs logged at the end of transform().
_TRANSFORM_COUNTS = (
    ("databases", "database_nodes"),
    ("schemas", "schema_nodes"),
    ("tables", "table_nodes"),
    ("columns", "column_nodes"),
    ("values", "value_nodes"),
)


class BigQuerySchemaConnector:
    """
    Connector for extracting BigQuery schema metadata into Neo4j.

    Follows an Extract → Transform → Load pipeline. :meth:`ingest` runs all
    three stages and records the neocarta graph metadata node at the end.

    Parameters
    ----------
    client : bigquery.Client
        Authenticated BigQuery client.
    project_id : str
        GCP project id. Falls back to ``client.project`` when omitted.
    neo4j_driver : Driver
        Neo4j driver instance.
    dataset_id : str, optional
        Deprecated. Pass ``dataset_id`` to :meth:`ingest` / :meth:`extract` instead.
        Retained as a fallback for callers that have not yet migrated.
    database_name : str, default "neo4j"
        Target Neo4j database name.
    """

    def __init__(
        self,
        client: bigquery.Client,
        project_id: str,
        neo4j_driver: Driver,
        dataset_id: str | None = None,
        database_name: str = "neo4j",
    ) -> None:
        """Initialize the BigQuery schema connector."""
        self.client = client
        self.project_id = client.project or project_id

        if self.project_id is None:
            raise ConfigError(
                "Project ID is required as argument in constructor or as attribute in BigQuery client."
            )

        if dataset_id is not None:
            warnings.warn(
                "Passing `dataset_id` to BigQuerySchemaConnector.__init__ is deprecated; "
                "pass it to .ingest(dataset_id=...) / .extract(dataset_id=...) instead.",
                DeprecationWarning,
                stacklevel=2,
            )

        self.dataset_id = dataset_id
        self.neo4j_driver = neo4j_driver
        self.database_name = database_name

        self.extractor = BigQuerySchemaExtractor(client, project_id, dataset_id)
        self.transformer = NormalizedGraphTransformer()
        self.loader = Neo4jRDBMSLoader(neo4j_driver, database_name)
        self._extracted = False
        self._transformed = False

    def close(self) -> None:
        """No connector-owned resources to release; the injected Neo4j driver is the caller's."""

    def __enter__(self) -> Self:
        """Return self for use as a context manager."""
        return self

    def __exit__(self, exc_type: object, exc_value: object, traceback: object) -> None:
        """Release owned resources on context-manager exit."""
        self.close()

    def extract(self, dataset_id: str | None = None) -> None:
        """
        Extract and cache BigQuery schema metadata.

        Parameters
        ----------
        dataset_id : str, optional
            Dataset id to extract. If omitted, falls back to the (deprecated)
            constructor-provided ``dataset_id``.
        """
        logger.info("Extracting BigQuery schema metadata...")
        target_dataset = dataset_id if dataset_id is not None else self.dataset_id
        self._extracted = False
        self._transformed = False
        self.extractor.extract_database_info(cache=True)
        self.extractor.extract_schema_info(dataset_id=target_dataset)
        self.extractor.extract_table_info(dataset_id=target_dataset)
        self.extractor.extract_column_info(dataset_id=target_dataset)
        self.extractor.extract_column_references_info(dataset_id=target_dataset)
        self.extractor.extract_column_unique_values_for_all_tables(dataset_id=target_dataset)
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
                "BigQuerySchemaConnector.transform() called before extract().",
                suggestion="Call connector.extract(dataset_id=...) before connector.transform().",
            )
        self._transformed = False
        logger.info("Transforming BigQuery schema metadata...")
        normalizer = build_bigquery_information_schema_normalizer(self.extractor)
        self.transformer.transform(normalizer.normalize())
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
                "BigQuerySchemaConnector.load() called before transform(); "
                "call .transform() first.",
                suggestion="Call connector.extract() and connector.transform() first.",
            )
        logger.info("Loading BigQuery schema metadata into Neo4j...")
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

    def ingest(self, dataset_id: str | None = None) -> None:
        """
        Run the BigQuery schema connector (extract → transform → load).

        Parameters
        ----------
        dataset_id : str, optional
            Dataset id to ingest. If omitted, falls back to the (deprecated)
            constructor-provided ``dataset_id``.
        """
        self.extract(dataset_id)
        self.transform()
        self.load()
        self.loader.upsert_neocarta_graph_node()
        logger.info("Recorded neocarta graph metadata")
        logger.info("BigQuery schema connector completed successfully")

    def run(self, dataset_id: str | None = None) -> None:
        """
        Run the BigQuery schema connector.

        .. deprecated::
            Use :meth:`ingest` instead. ``run`` will be removed in a future release.
        """
        warnings.warn(
            "BigQuerySchemaConnector.run() is deprecated; "
            "use BigQuerySchemaConnector.ingest() instead.",
            DeprecationWarning,
            stacklevel=2,
        )
        self.ingest(dataset_id)
