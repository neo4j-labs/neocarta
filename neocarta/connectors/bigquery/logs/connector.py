"""BigQuery query log connector."""

from google.cloud import bigquery
from neo4j import Driver

from ....ingest.rdbms import Neo4jRDBMSLoader
from ...query_log.transform import QueryLogTransformer
from .extract import BigQueryLogsExtractor


class BigQueryLogsConnector:
    """A connector for extracting, transforming, and loading BigQuery query logs into Neo4j."""

    def __init__(
        self,
        client: bigquery.Client,
        project_id: str,
        neo4j_driver: Driver,
        database_name: str = "neo4j",
    ) -> None:
        """
        Initialize the BigQuery logs connector.

        Parameters
        ----------
        client: bigquery.Client
            The BigQuery client.
        project_id: str
            The GCP project ID.
        neo4j_driver: Driver
            The Neo4j driver.
        database_name: str = "neo4j"
            The Neo4j database name.
        """
        self.client = client
        self.project_id = client.project or project_id
        self.neo4j_driver = neo4j_driver
        self.database_name = database_name

        if self.project_id is None:
            raise ValueError(
                "Project ID is required as argument in constructor or as attribute in BigQuery client."
            )

        self.extractor = BigQueryLogsExtractor(client, project_id)
        self.transformer = QueryLogTransformer()
        self.loader = Neo4jRDBMSLoader(neo4j_driver, database_name)

    def extract_metadata(
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
        dataset_id: str
            The dataset ID to filter queries by.
        region: str = "region-us"
            The BigQuery region.
        start_timestamp: Optional[str] = None
            Start timestamp for query window.
        end_timestamp: Optional[str] = None
            End timestamp for query window.
        limit: int = 100
            Maximum number of queries to extract.
        drop_failed_queries: bool = True
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

    def transform_metadata(self) -> None:
        """
        Transform and cache metadata from query logs.
        `extract_metadata` must be called before this method.
        """
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

    def load_metadata(self) -> None:
        """
        Load query log metadata into Neo4j.
        `transform_metadata` must be called before this method.
        """
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

        Parameters
        ----------
        dataset_id: str
            The dataset ID to filter queries by.
        region: str = "region-us"
            The BigQuery region.
        start_timestamp: Optional[str] = None
            Start timestamp for query window.
        end_timestamp: Optional[str] = None
            End timestamp for query window.
        limit: int = 100
            Maximum number of queries to extract.
        drop_failed_queries: bool = True
            Whether to exclude failed queries.
        """
        print("Extracting query logs from BigQuery...")
        self.extract_metadata(
            dataset_id, region, start_timestamp, end_timestamp, limit, drop_failed_queries
        )
        print("Transforming query log metadata...")
        self.transform_metadata()
        print("Loading metadata into Neo4j...")
        self.load_metadata()
        print("BigQuery logs connector completed successfully!")
