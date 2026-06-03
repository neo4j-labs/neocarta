"""Query log connector."""

import warnings

from neo4j import Driver

from ...errors import StateError
from ...ingest.rdbms import Neo4jRDBMSLoader
from .extract import QueryLogExtractor
from .transform import QueryLogTransformer


class QueryLogConnector:
    """
    Connector for loading query log file metadata into Neo4j.

    Reads a query log JSON file (currently BigQuery-flavored) and follows an
    Extract → Transform → Load pipeline. :meth:`ingest` runs all three stages
    and records the neocarta graph metadata node at the end.
    """

    def __init__(self, neo4j_driver: Driver, database_name: str = "neo4j") -> None:
        """Initialize the query log connector."""
        self.neo4j_driver = neo4j_driver
        self.database_name = database_name

        self.extractor = QueryLogExtractor()
        self.transformer = QueryLogTransformer()
        self.loader = Neo4jRDBMSLoader(neo4j_driver, database_name)
        self._extracted = False

    def extract(self, query_log_file: str, source: str = "bigquery") -> None:
        """
        Extract metadata from a query log file into the connector's extract cache.

        Parameters
        ----------
        query_log_file : str
            The path to the query log file.
        source : str, default "bigquery"
            The source of the query log file.
        """
        self.extractor.extract_info_from_query_log_json(query_log_file, source)
        self._extracted = True

    def transform(self) -> None:
        """
        Convert extracted metadata into graph data model objects.

        Raises
        ------
        StateError
            If called before :meth:`extract`.
        """
        if not self._extracted:
            raise StateError(
                "QueryLogConnector.transform() called before extract(); "
                "call .extract(query_log_file) first.",
                suggestion="Call connector.extract(query_log_file) before connector.transform().",
            )

        # transform nodes
        self.transformer.transform_to_database_nodes(self.extractor.database_info)
        self.transformer.transform_to_schema_nodes(self.extractor.schema_info)
        self.transformer.transform_to_table_nodes(self.extractor.table_info)
        self.transformer.transform_to_column_nodes(self.extractor.column_info)
        self.transformer.transform_to_query_nodes(self.extractor.query_info)
        self.transformer.transform_to_cte_nodes(self.extractor.cte_info)

        # transform relationships
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
        Load the transformed metadata into Neo4j.

        Raises
        ------
        StateError
            If called before :meth:`transform`.
        """
        if not self._extracted:
            raise StateError(
                "QueryLogConnector.load() called before extract()/transform().",
                suggestion="Call connector.extract() and connector.transform() first.",
            )

        # load nodes
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

        # load relationships
        print(self.loader.load_has_schema_relationships(self.transformer.has_schema_relationships))
        print(self.loader.load_has_table_relationships(self.transformer.has_table_relationships))
        print(self.loader.load_has_column_relationships(self.transformer.has_column_relationships))
        print(self.loader.load_references_relationships(self.transformer.references_relationships))
        print(self.loader.load_uses_table_relationships(self.transformer.uses_table_relationships))
        print(
            self.loader.load_uses_column_relationships(self.transformer.uses_column_relationships)
        )
        print(self.loader.load_defines_relationships(self.transformer.defines_relationships))

    def ingest(self, query_log_file: str, source: str = "bigquery") -> None:
        """
        Run the query log connector (extract → transform → load).

        Parameters
        ----------
        query_log_file : str
            The path to the query log file.
        source : str, default "bigquery"
            The source of the query log file.
        """
        print("Extracting metadata from query log...")
        self.extract(query_log_file, source)
        print("Transforming metadata from query log...")
        self.transform()
        print("Loading metadata into Neo4j...")
        self.load()
        print("Recording neocarta graph metadata...")
        print(self.loader.upsert_neocarta_graph_node().model_dump())
        print("Query log connector completed successfully!")

    def run(self, query_log_file: str, source: str = "bigquery") -> None:
        """
        Run the query log connector.

        .. deprecated::
            Use :meth:`ingest` instead. ``run`` will be removed in a future release.
        """
        warnings.warn(
            "QueryLogConnector.run() is deprecated; use QueryLogConnector.ingest() instead.",
            DeprecationWarning,
            stacklevel=2,
        )
        self.ingest(query_log_file, source)
