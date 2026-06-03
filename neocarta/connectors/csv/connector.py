"""CSV Connector for loading metadata from CSV files into Neo4j."""

import warnings

from neo4j import Driver

from ...enums import NodeLabel, RelationshipType
from ...errors import StateError
from ...ingest.rdbms import Neo4jRDBMSLoader
from .extract import CSVExtractor
from .transform import CSVTransformer


class CSVConnector:
    """
    Connector for loading metadata from CSV files into Neo4j.

    Follows an Extract → Transform → Load pipeline:

    - :meth:`extract` reads and validates CSV files into DataFrames.
    - :meth:`transform` converts DataFrames into typed data model objects.
    - :meth:`load` writes the objects to Neo4j.

    :meth:`ingest` runs all three stages in order and records the neocarta graph
    metadata node at the end.

    Parameters
    ----------
    csv_directory : str
        Path to directory containing CSV files.
    neo4j_driver : Driver
        Neo4j driver instance.
    database_name : str, optional
        Neo4j database name, by default "neo4j".
    csv_file_map : dict[str, str], optional
        Custom mapping of entity keys to CSV filenames.
        Merges with CSVExtractor.DEFAULT_FILE_MAP, allowing partial overrides.
    """

    def __init__(
        self,
        csv_directory: str,
        neo4j_driver: Driver,
        database_name: str = "neo4j",
        csv_file_map: dict[str, str] | None = None,
    ) -> None:
        """Initialize the CSV connector."""
        self.extractor = CSVExtractor(csv_directory, csv_file_map)
        self.transformer = CSVTransformer()
        self.loader = Neo4jRDBMSLoader(neo4j_driver, database_name)
        self._extracted = False

    def extract(
        self,
        *,
        include_nodes: list[NodeLabel] | None = None,
        include_relationships: list[RelationshipType] | None = None,
    ) -> None:
        """
        Read and validate CSV files from the configured directory.

        Parameters
        ----------
        include_nodes : list[NodeLabel], optional
            Node types to extract. If None, all node CSVs are read.
        include_relationships : list[RelationshipType], optional
            Relationship types to extract. If None, all relationship CSVs are read.
        """
        self.extractor.extract_all(include_nodes, include_relationships)
        self._extracted = True

    def transform(self) -> None:
        """
        Convert extracted DataFrames into data model objects.

        Raises:
        ------
        StateError
            If called before :meth:`extract`.
        """
        if not self._extracted:
            raise StateError(
                "CSVConnector.transform() called before extract(); call .extract() first.",
                suggestion="Call connector.extract() before connector.transform().",
            )

        e = self.extractor
        t = self.transformer

        t.transform_to_database_nodes(e.database_info)
        t.transform_to_schema_nodes(e.schema_info)
        t.transform_to_table_nodes(e.table_info)
        t.transform_to_column_nodes(e.column_info)
        t.transform_to_value_nodes(e.value_info)
        t.transform_to_query_nodes(e.query_info)
        t.transform_to_glossary_nodes(e.glossary_info)
        t.transform_to_category_nodes(e.category_info)
        t.transform_to_business_term_nodes(e.business_term_info)

        t.transform_to_has_schema_relationships(e.schema_info)
        t.transform_to_has_table_relationships(e.table_info)
        t.transform_to_has_column_relationships(e.column_info)
        t.transform_to_has_value_relationships(e.value_info)
        t.transform_to_has_category_relationships(e.category_info)
        t.transform_to_has_business_term_relationships(e.business_term_info)
        t.transform_to_references_relationships(e.column_references_info)
        t.transform_to_uses_table_relationships(e.query_table_info)
        t.transform_to_uses_column_relationships(e.query_column_info)
        t.transform_to_column_tagged_with_relationships(e.column_tagged_with_info)
        t.transform_to_table_tagged_with_relationships(e.table_tagged_with_info)

    def load(self) -> None:
        """
        Write transformed data model objects into Neo4j.

        Nodes are always loaded before relationships.

        Raises:
        ------
        StateError
            If called before :meth:`transform`.
        """
        t = self.transformer
        if not self._extracted:
            raise StateError(
                "CSVConnector.load() called before extract()/transform().",
                suggestion="Call connector.extract() and connector.transform() first.",
            )

        print("\n=== Loading Nodes ===")
        if t.database_nodes:
            print(f"Loading {len(t.database_nodes)} database nodes...")
            print(
                self.loader.load_database_nodes(
                    t.database_nodes, properties_list=t.get_properties("database_nodes")
                )
            )
        if t.schema_nodes:
            print(f"Loading {len(t.schema_nodes)} schema nodes...")
            print(
                self.loader.load_schema_nodes(
                    t.schema_nodes, properties_list=t.get_properties("schema_nodes")
                )
            )
        if t.table_nodes:
            print(f"Loading {len(t.table_nodes)} table nodes...")
            print(
                self.loader.load_table_nodes(
                    t.table_nodes, properties_list=t.get_properties("table_nodes")
                )
            )
        if t.column_nodes:
            print(f"Loading {len(t.column_nodes)} column nodes...")
            print(
                self.loader.load_column_nodes(
                    t.column_nodes, properties_list=t.get_properties("column_nodes")
                )
            )
        if t.value_nodes:
            print(f"Loading {len(t.value_nodes)} value nodes...")
            print(
                self.loader.load_value_nodes(
                    t.value_nodes, properties_list=t.get_properties("value_nodes")
                )
            )
        if t.query_nodes:
            print(f"Loading {len(t.query_nodes)} query nodes...")
            print(
                self.loader.load_query_nodes(
                    t.query_nodes, properties_list=t.get_properties("query_nodes")
                )
            )
        if t.glossary_nodes:
            print(f"Loading {len(t.glossary_nodes)} glossary nodes...")
            print(
                self.loader.load_glossary_nodes(
                    t.glossary_nodes, properties_list=t.get_properties("glossary_nodes")
                )
            )
        if t.category_nodes:
            print(f"Loading {len(t.category_nodes)} category nodes...")
            print(
                self.loader.load_category_nodes(
                    t.category_nodes, properties_list=t.get_properties("category_nodes")
                )
            )
        if t.business_term_nodes:
            print(f"Loading {len(t.business_term_nodes)} business term nodes...")
            print(
                self.loader.load_business_term_nodes(
                    t.business_term_nodes, properties_list=t.get_properties("business_term_nodes")
                )
            )

        print("\n=== Loading Relationships ===")
        if t.has_schema_relationships:
            print(f"Loading {len(t.has_schema_relationships)} HAS_SCHEMA relationships...")
            print(self.loader.load_has_schema_relationships(t.has_schema_relationships))
        if t.has_table_relationships:
            print(f"Loading {len(t.has_table_relationships)} HAS_TABLE relationships...")
            print(self.loader.load_has_table_relationships(t.has_table_relationships))
        if t.has_column_relationships:
            print(f"Loading {len(t.has_column_relationships)} HAS_COLUMN relationships...")
            print(self.loader.load_has_column_relationships(t.has_column_relationships))
        if t.has_value_relationships:
            print(f"Loading {len(t.has_value_relationships)} HAS_VALUE relationships...")
            print(self.loader.load_has_value_relationships(t.has_value_relationships))
        if t.has_category_relationships:
            print(f"Loading {len(t.has_category_relationships)} HAS_CATEGORY relationships...")
            print(self.loader.load_has_category_relationships(t.has_category_relationships))
        if t.has_business_term_relationships:
            print(
                f"Loading {len(t.has_business_term_relationships)} HAS_BUSINESS_TERM relationships..."
            )
            print(
                self.loader.load_has_business_term_relationships(t.has_business_term_relationships)
            )
        if t.references_relationships:
            print(f"Loading {len(t.references_relationships)} REFERENCES relationships...")
            print(self.loader.load_references_relationships(t.references_relationships))
        if t.uses_table_relationships:
            print(f"Loading {len(t.uses_table_relationships)} USES_TABLE relationships...")
            print(self.loader.load_uses_table_relationships(t.uses_table_relationships))
        if t.uses_column_relationships:
            print(f"Loading {len(t.uses_column_relationships)} USES_COLUMN relationships...")
            print(self.loader.load_uses_column_relationships(t.uses_column_relationships))
        if t.column_tagged_with_relationships:
            print(
                f"Loading {len(t.column_tagged_with_relationships)} column TAGGED_WITH relationships..."
            )
            print(
                self.loader.load_column_tagged_with_relationships(
                    t.column_tagged_with_relationships
                )
            )
        if t.table_tagged_with_relationships:
            print(
                f"Loading {len(t.table_tagged_with_relationships)} table TAGGED_WITH relationships..."
            )
            print(
                self.loader.load_table_tagged_with_relationships(t.table_tagged_with_relationships)
            )

    def ingest(
        self,
        *,
        include_nodes: list[NodeLabel] | None = None,
        include_relationships: list[RelationshipType] | None = None,
    ) -> None:
        """
        Run the complete CSV connector (extract → transform → load).

        Files that don't exist are skipped with a warning message.

        Parameters
        ----------
        include_nodes : list[NodeLabel], optional
            Node types to load. If None, all available node CSVs are loaded.
        include_relationships : list[RelationshipType], optional
            Relationship types to load. If None, all available relationship CSVs
            are loaded.

        Examples:
        --------
        Load only core schema entities:

        >>> connector.ingest(
        ...     include_nodes=[
        ...         NodeLabel.DATABASE,
        ...         NodeLabel.SCHEMA,
        ...         NodeLabel.TABLE,
        ...         NodeLabel.COLUMN,
        ...     ],
        ...     include_relationships=[
        ...         RelationshipType.HAS_SCHEMA,
        ...         RelationshipType.HAS_TABLE,
        ...         RelationshipType.HAS_COLUMN,
        ...     ],
        ... )

        Load everything:

        >>> connector.ingest()
        """
        print("Extracting metadata from CSV files...")
        self.extract(include_nodes=include_nodes, include_relationships=include_relationships)
        print("Transforming metadata...")
        self.transform()
        print("Loading metadata into Neo4j...")
        self.load()
        print("Recording neocarta graph metadata...")
        print(self.loader.upsert_neocarta_graph_node().model_dump())
        print("\nCSV connector completed successfully!")

    def run(
        self,
        include_nodes: list[NodeLabel] | None = None,
        include_relationships: list[RelationshipType] | None = None,
    ) -> None:
        """
        Run the CSV connector.

        .. deprecated::
            Use :meth:`ingest` instead. ``run`` will be removed in a future release.
        """
        warnings.warn(
            "CSVConnector.run() is deprecated; use CSVConnector.ingest() instead.",
            DeprecationWarning,
            stacklevel=2,
        )
        self.ingest(include_nodes=include_nodes, include_relationships=include_relationships)
