"""Dataplex schema sub-connector."""

import warnings

from google.cloud import dataplex_v1
from neo4j import Driver

from ....errors import StateError
from ....ingest.rdbms import Neo4jRDBMSLoader
from .extract import DataplexSchemaExtractor
from .transform import DataplexSchemaTransformer


class DataplexSchemaConnector:
    """
    Connector for BigQuery schema metadata extracted via Dataplex Universal Catalog.

    Produces Database/Schema/Table/Column nodes and their HAS_* edges.
    Pairs with :class:`DataplexGlossaryConnector` (loaded after) to attach
    business-term tags to schema entities.

    Parameters
    ----------
    catalog_client : dataplex_v1.CatalogServiceClient
        The Dataplex Catalog client.
    project_id : str
        The GCP project ID.
    project_number : str
        The GCP project number.
    dataplex_location : str
        The Dataplex location (e.g. ``us-central1`` or ``us``).
    neo4j_driver : Driver
        Neo4j driver instance.
    database_name : str, default "neo4j"
        Target Neo4j database name.
    """

    def __init__(
        self,
        catalog_client: dataplex_v1.CatalogServiceClient,
        project_id: str,
        project_number: str,
        dataplex_location: str,
        neo4j_driver: Driver,
        database_name: str = "neo4j",
    ) -> None:
        """Initialize the Dataplex schema connector."""
        self.catalog_client = catalog_client
        self.project_id = project_id
        self.project_number = project_number
        self.dataplex_location = dataplex_location
        self.neo4j_driver = neo4j_driver
        self.database_name = database_name

        self.extractor = DataplexSchemaExtractor(
            catalog_client, project_id, project_number, dataplex_location
        )
        self.transformer = DataplexSchemaTransformer()
        self.loader = Neo4jRDBMSLoader(neo4j_driver, database_name)
        self._extracted = False

    def extract(self, dataset_id: str) -> None:
        """
        Extract BigQuery catalog metadata for a single dataset into the cache.

        Parameters
        ----------
        dataset_id : str
            The BigQuery dataset ID to extract.
        """
        self.extractor.extract(dataset_id=dataset_id)
        self._extracted = True

    def transform(self) -> None:
        """
        Transform cached metadata into Database/Schema/Table/Column nodes + HAS_* edges.

        Raises:
        ------
        StateError
            If called before :meth:`extract`.
        """
        if not self._extracted:
            raise StateError(
                "DataplexSchemaConnector.transform() called before extract().",
                suggestion="Call connector.extract(dataset_id=...) before connector.transform().",
            )
        e = self.extractor
        t = self.transformer

        t.transform_to_database_nodes(e.database_info)
        t.transform_to_schema_nodes(e.schema_info)
        t.transform_to_table_nodes(e.table_info)
        t.transform_to_column_nodes(e.column_info)

        t.transform_to_has_schema_relationships(e.schema_info)
        t.transform_to_has_table_relationships(e.table_info)
        t.transform_to_has_column_relationships(e.column_info)

    def load(self) -> None:
        """
        Load transformed nodes and relationships into Neo4j.

        Raises:
        ------
        StateError
            If called before :meth:`transform`.
        """
        if not self._extracted:
            raise StateError(
                "DataplexSchemaConnector.load() called before extract()/transform().",
                suggestion="Call connector.extract() and connector.transform() first.",
            )
        t = self.transformer

        print(self.loader.load_database_nodes(t.database_nodes))
        print(self.loader.load_schema_nodes(t.schema_nodes))
        print(self.loader.load_table_nodes(t.table_nodes))
        print(
            self.loader.load_column_nodes(
                t.column_nodes, properties_list=["name", "description", "type"]
            )
        )

        print(self.loader.load_has_schema_relationships(t.has_schema_relationships))
        print(self.loader.load_has_table_relationships(t.has_table_relationships))
        print(self.loader.load_has_column_relationships(t.has_column_relationships))

    def ingest(self, dataset_id: str) -> None:
        """
        Run the Dataplex schema connector (extract → transform → load).

        Parameters
        ----------
        dataset_id : str
            The BigQuery dataset ID to ingest.
        """
        print("Extracting schema metadata from Dataplex...")
        self.extract(dataset_id)
        print("Transforming schema metadata from Dataplex...")
        self.transform()
        print("Loading schema metadata into Neo4j...")
        self.load()
        print("Recording neocarta graph metadata...")
        print(self.loader.upsert_neocarta_graph_node().model_dump())
        print("Dataplex schema connector completed successfully!")

    def run(self, dataset_id: str) -> None:
        """
        Run the Dataplex schema connector.

        .. deprecated::
            Use :meth:`ingest` instead. ``run`` will be removed in a future release.
        """
        warnings.warn(
            "DataplexSchemaConnector.run() is deprecated; "
            "use DataplexSchemaConnector.ingest() instead.",
            DeprecationWarning,
            stacklevel=2,
        )
        self.ingest(dataset_id)
