"""BigQuery query log connector."""

import warnings

from google.cloud import bigquery
from neo4j import Driver

from ....errors import ConfigError, StateError
from ....ingest.rdbms import Neo4jRDBMSLoader
from ...query_log.transform import QueryLogTransformer
from .extract import BigQueryLogsExtractor


class BigQueryLogsConnector:
    """
    Connector for extracting BigQuery query logs into Neo4j.

    Follows an Extract → Transform → Load pipeline. :meth:`ingest` runs all
    three stages and records the neocarta graph metadata node at the end.

    Parameters
    ----------
    client : bigquery.Client
        The BigQuery client.
    project_id : str
        The GCP project ID.
    neo4j_driver : Driver
        The Neo4j driver.
    database_name : str, default "neo4j"
        The Neo4j database name.
    """

    def __init__(
        self,
        client: bigquery.Client,
        project_id: str,
        neo4j_driver: Driver,
        database_name: str = "neo4j",
    ) -> None:
        """Initialize the BigQuery logs connector."""
        self.client = client
        self.project_id = client.project or project_id
        self.neo4j_driver = neo4j_driver
        self.database_name = database_name

        if self.project_id is None:
            raise ConfigError(
                "Project ID is required as argument in constructor or as attribute in BigQuery client."
            )

        self.extractor = BigQueryLogsExtractor(client, project_id)
        self.transformer = QueryLogTransformer()
        self.loader = Neo4jRDBMSLoader(neo4j_driver, database_name)
        self._extracted = False

    def extract(
        self,
        dataset_id: str,
        region: str = "region-us",
        start_timestamp: str | None = None,
        end_timestamp: str | None = None,
        limit: int = 100,
        drop_failed_queries: bool = True,
    ) -> None:
        """
        Extract and cache query logs from BigQuery.

        Parameters
        ----------
        dataset_id : str
            The dataset ID to filter queries by.
        region : str, default "region-us"
            The BigQuery region.
        start_timestamp : str, optional
            Start timestamp for query window.
        end_timestamp : str, optional
            End timestamp for query window.
        limit : int, default 100
            Maximum number of queries to extract.
        drop_failed_queries : bool, default True
            Whether to exclude failed queries.
        """
        self.extractor.extract_query_logs(
            dataset_id=dataset_id,
            region=region,
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
                "BigQueryLogsConnector.transform() called before extract().",
                suggestion="Call connector.extract(dataset_id=...) before connector.transform().",
            )

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

    def load(self) -> None:
        """
        Load transformed query log metadata into Neo4j.

        Raises:
        ------
        StateError
            If called before :meth:`transform`.
        """
        if not self._extracted:
            raise StateError(
                "BigQueryLogsConnector.load() called before extract()/transform().",
                suggestion="Call connector.extract() and connector.transform() first.",
            )

        # Load nodes
        print(
            self.loader.load_database_nodes(
                self.transformer.database_nodes, properties_list=["name", "service", "platform"]
            )
        )
        print(
            self.loader.load_schema_nodes(self.transformer.schema_nodes, properties_list=["name"])
        )
        print(self.loader.load_table_nodes(self.transformer.table_nodes, properties_list=["name"]))
        print(
            self.loader.load_column_nodes(self.transformer.column_nodes, properties_list=["name"])
        )
        print(self.loader.load_query_nodes(self.transformer.query_nodes))
        print(self.loader.load_cte_nodes(self.transformer.cte_nodes))

        # Load relationships
        print(self.loader.load_has_schema_relationships(self.transformer.has_schema_relationships))
        print(self.loader.load_has_table_relationships(self.transformer.has_table_relationships))
        print(self.loader.load_has_column_relationships(self.transformer.has_column_relationships))
        print(self.loader.load_references_relationships(self.transformer.references_relationships))
        print(self.loader.load_uses_table_relationships(self.transformer.uses_table_relationships))
        print(
            self.loader.load_uses_column_relationships(self.transformer.uses_column_relationships)
        )
        print(self.loader.load_defines_relationships(self.transformer.defines_relationships))

    def ingest(
        self,
        dataset_id: str,
        region: str = "region-us",
        start_timestamp: str | None = None,
        end_timestamp: str | None = None,
        limit: int = 100,
        drop_failed_queries: bool = True,
    ) -> None:
        """
        Run the BigQuery logs connector (extract → transform → load).

        Parameters
        ----------
        dataset_id : str
            The dataset ID to filter queries by.
        region : str, default "region-us"
            The BigQuery region.
        start_timestamp : str, optional
            Start timestamp for query window.
        end_timestamp : str, optional
            End timestamp for query window.
        limit : int, default 100
            Maximum number of queries to extract.
        drop_failed_queries : bool, default True
            Whether to exclude failed queries.
        """
        print("Extracting query logs from BigQuery...")
        self.extract(
            dataset_id=dataset_id,
            region=region,
            start_timestamp=start_timestamp,
            end_timestamp=end_timestamp,
            limit=limit,
            drop_failed_queries=drop_failed_queries,
        )
        print("Transforming query log metadata...")
        self.transform()
        print("Loading metadata into Neo4j...")
        self.load()
        print("Recording neocarta graph metadata...")
        print(self.loader.upsert_neocarta_graph_node().model_dump())
        print("BigQuery logs connector completed successfully!")

    def run(
        self,
        dataset_id: str,
        region: str = "region-us",
        start_timestamp: str | None = None,
        end_timestamp: str | None = None,
        limit: int = 100,
        drop_failed_queries: bool = True,
    ) -> None:
        """
        Run the BigQuery logs connector.

        .. deprecated::
            Use :meth:`ingest` instead. ``run`` will be removed in a future release.
        """
        warnings.warn(
            "BigQueryLogsConnector.run() is deprecated; "
            "use BigQueryLogsConnector.ingest() instead.",
            DeprecationWarning,
            stacklevel=2,
        )
        self.ingest(
            dataset_id=dataset_id,
            region=region,
            start_timestamp=start_timestamp,
            end_timestamp=end_timestamp,
            limit=limit,
            drop_failed_queries=drop_failed_queries,
        )
