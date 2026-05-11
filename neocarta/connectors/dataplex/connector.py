"""Dataplex connector for extracting, transforming, and loading metadata into Neo4j."""

from google.cloud import dataplex_v1
from neo4j import Driver

from ...ingest.rdbms import Neo4jRDBMSLoader
from .extract import DataplexExtractor
from .transform import DataplexTransformer


class DataplexConnector:
    """Connector class for Dataplex."""

    def __init__(
        self,
        catalog_client: dataplex_v1.CatalogServiceClient,
        glossary_client: dataplex_v1.BusinessGlossaryServiceClient,
        project_id: str,
        project_number: str,
        dataplex_location: str,
        neo4j_driver: Driver,
        dataset_id: str | None = None,
        database_name: str = "neo4j",
        include_schema: bool = True,
        include_glossary: bool = True,
    ) -> None:
        """Initialize the Dataplex connector."""
        self.catalog_client = catalog_client
        self.glossary_client = glossary_client
        self.project_id = project_id
        self.project_number = project_number
        self.dataplex_location = dataplex_location
        self.dataset_id = dataset_id
        self.neo4j_driver = neo4j_driver
        self.database_name = database_name

        self.include_schema = include_schema
        self.include_glossary = include_glossary
        self.include_entry_links = include_schema and include_glossary

        self.extractor = DataplexExtractor(
            catalog_client,
            glossary_client,
            project_id,
            project_number,
            dataplex_location,
            dataset_id,
        )
        self.transformer = DataplexTransformer()
        self.loader = Neo4jRDBMSLoader(neo4j_driver, database_name)

    def extract_metadata(self, dataset_id: str | None = None) -> None:
        """
        Extract and cache metadata from Dataplex.

        Parameters
        ----------
        dataset_id: Optional[str] = None
            The dataset ID. If not provided, will use default instance `dataset_id`.

        Returns:
        -------
        None
            The metadata is extracted and cached.
        """
        self.extractor.extract_bigquery_info_for_all_tables(dataset_id=dataset_id)
        self.extractor.extract_glossary_info(cache=True)
        if self.include_entry_links:
            self.extractor.extract_entry_links(cache=True)

    def transform_metadata(self) -> None:
        """Transform and cache metadata from Dataplex. `extract_metadata` must be called before this method."""
        if self.include_schema:
            self.transformer.transform_to_database_nodes(self.extractor.database_info)
            self.transformer.transform_to_schema_nodes(self.extractor.schema_info)
            self.transformer.transform_to_table_nodes(self.extractor.table_info)
            self.transformer.transform_to_column_nodes(self.extractor.column_info)

            self.transformer.transform_to_has_schema_relationships(self.extractor.schema_info)
            self.transformer.transform_to_has_table_relationships(self.extractor.table_info)
            self.transformer.transform_to_has_column_relationships(self.extractor.column_info)

        if self.include_glossary:
            self.transformer.transform_to_glossary_nodes(self.extractor.glossary_info)
            self.transformer.transform_to_category_nodes(self.extractor.category_info)
            self.transformer.transform_to_business_term_nodes(self.extractor.business_term_info)

            self.transformer.transform_to_has_category_relationships(self.extractor.category_info)
            self.transformer.transform_to_has_business_term_relationships(
                self.extractor.business_term_info
            )

        if self.include_entry_links:
            self.transformer.transform_to_column_tagged_with_relationships(
                self.extractor.column_term_info
            )
            self.transformer.transform_to_table_tagged_with_relationships(
                self.extractor.table_term_info
            )

    def load_metadata(self) -> None:
        """Load Dataplex metadata into Neo4j. `transform_metadata` must be called before this method."""
        if self.include_schema:
            print(self.loader.load_database_nodes(self.transformer.database_nodes))
            print(self.loader.load_schema_nodes(self.transformer.schema_nodes))
            print(self.loader.load_table_nodes(self.transformer.table_nodes))
            print(
                self.loader.load_column_nodes(
                    self.transformer.column_nodes, properties_list=["name", "description", "type"]
                )
            )

            print(
                self.loader.load_has_schema_relationships(self.transformer.has_schema_relationships)
            )
            print(
                self.loader.load_has_table_relationships(self.transformer.has_table_relationships)
            )
            print(
                self.loader.load_has_column_relationships(self.transformer.has_column_relationships)
            )

        if self.include_glossary:
            print(
                self.loader.load_glossary_nodes(
                    self.transformer.glossary_nodes,
                    properties_list=["name", "description", "resource_path"],
                )
            )
            print(
                self.loader.load_category_nodes(
                    self.transformer.category_nodes,
                    properties_list=["name", "description", "resource_path"],
                )
            )
            print(
                self.loader.load_business_term_nodes(
                    self.transformer.business_term_nodes,
                    properties_list=["name", "description", "resource_path"],
                )
            )

            print(
                self.loader.load_has_category_relationships(
                    self.transformer.has_category_relationships
                )
            )
            print(
                self.loader.load_has_business_term_relationships(
                    self.transformer.has_business_term_relationships
                )
            )

        if self.include_entry_links:
            print(
                self.loader.load_column_tagged_with_relationships(
                    self.transformer.column_tagged_with_relationships
                )
            )
            print(
                self.loader.load_table_tagged_with_relationships(
                    self.transformer.table_tagged_with_relationships
                )
            )

    def run(self, dataset_id: str | None = None) -> None:
        """
        Run the Dataplex connector.

        Parameters
        ----------
        dataset_id: Optional[str] = None
            The dataset ID. If not provided, will use default instance `dataset_id`.

        Returns:
        -------
        None
            The metadata is extracted, transformed, and loaded into Neo4j.
        """
        print("Extracting metadata from Dataplex...")
        self.extract_metadata(dataset_id)
        print("Transforming metadata from Dataplex...")
        self.transform_metadata()
        print("Loading metadata into Neo4j...")
        self.load_metadata()
        print("Dataplex connector completed successfully!")
