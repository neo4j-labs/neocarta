"""BigQuery schema connector."""

from google.cloud import bigquery
from neo4j import Driver

from ....errors import ConfigError
from ....ingest.rdbms import Neo4jRDBMSLoader
from .extract import BigQuerySchemaExtractor
from .transform import BigQuerySchemaTransformer


class BigQuerySchemaConnector:
    """A connector for extracting, transforming, and loading BigQuery data into Neo4j."""

    def __init__(
        self,
        client: bigquery.Client,
        project_id: str,
        dataset_id: str,
        neo4j_driver: Driver,
        database_name: str = "neo4j",
    ) -> None:
        """Initialize the BigQuery connector."""
        self.client = client
        self.project_id = client.project or project_id

        if self.project_id is None:
            raise ConfigError(
                "Project ID is required as argument in constructor or as attribute in BigQueryclient."
            )

        self.dataset_id = dataset_id
        self.neo4j_driver = neo4j_driver
        self.database_name = database_name

        self.extractor = BigQuerySchemaExtractor(client, project_id, dataset_id)
        self.transformer = BigQuerySchemaTransformer()
        self.loader = Neo4jRDBMSLoader(neo4j_driver, database_name)

    def extract_metadata(self, dataset_id: str | None = None) -> None:
        """
        Extract and cache metadata from BigQuery.

        Parameters
        ----------
        dataset_id: Optional[str] = None
            The dataset ID. If not provided, will use default instance `dataset_id`.
        """
        self.extractor.extract_database_info(cache=True)
        self.extractor.extract_schema_info(dataset_id=dataset_id)
        self.extractor.extract_table_info(dataset_id=dataset_id)
        self.extractor.extract_column_info(dataset_id=dataset_id)
        self.extractor.extract_column_references_info(dataset_id=dataset_id)
        self.extractor.extract_column_unique_values_for_all_tables(dataset_id=dataset_id)

    def transform_metadata(self) -> None:
        """Transform and cache metadata from BigQuery. `extract_metadata` must be called before this method."""
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

    def load_metadata(self) -> None:
        """Load BigQuery metadata into Neo4j. `transform_metadata` must be called before this method."""
        print(self.loader.load_database_nodes(self.transformer.database_nodes))
        print(self.loader.load_schema_nodes(self.transformer.schema_nodes))
        print(self.loader.load_table_nodes(self.transformer.table_nodes))
        print(self.loader.load_column_nodes(self.transformer.column_nodes))
        print(self.loader.load_value_nodes(self.transformer.value_nodes))

        print(self.loader.load_has_schema_relationships(self.transformer.has_schema_relationships))
        print(self.loader.load_has_table_relationships(self.transformer.has_table_relationships))
        print(self.loader.load_has_column_relationships(self.transformer.has_column_relationships))
        print(self.loader.load_references_relationships(self.transformer.references_relationships))
        print(self.loader.load_has_value_relationships(self.transformer.has_value_relationships))

    def run(self, dataset_id: str | None = None) -> None:
        """
        Run the BigQuery connector.

        Parameters
        ----------
        dataset_id: Optional[str] = None
            The dataset ID. If not provided, will use default instance `dataset_id`.
        """
        print("Extracting metadata from BigQuery...")
        self.extract_metadata(dataset_id)
        print("Transforming metadata from BigQuery...")
        self.transform_metadata()
        print("Loading metadata into Neo4j...")
        self.load_metadata()
        print("Recording neocarta graph metadata...")
        print(self.loader.upsert_neocarta_graph_node().model_dump())
        print("BigQuery connector completed successfully!")
