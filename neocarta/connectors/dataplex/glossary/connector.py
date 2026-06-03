"""Dataplex glossary sub-connector."""

import warnings

from google.cloud import dataplex_v1
from neo4j import Driver

from ....errors import StateError
from ....ingest.rdbms import Neo4jRDBMSLoader
from .extract import DataplexGlossaryExtractor
from .transform import DataplexGlossaryTransformer


class DataplexGlossaryConnector:
    """
    Connector for Dataplex business glossary content and catalog↔glossary entry links.

    Produces:

    - Glossary / Category / BusinessTerm nodes and their HAS_CATEGORY /
      HAS_BUSINESS_TERM edges.
    - (:Column)-[:TAGGED_WITH]->(:BusinessTerm) and (:Table)-[:TAGGED_WITH]->(:BusinessTerm)
      edges from the entry-link API.

    The TAGGED_WITH edges target Column / Table nodes by id; the matching schema
    nodes must already exist in Neo4j (typically via
    :class:`DataplexSchemaConnector` run beforehand).

    Parameters
    ----------
    glossary_client : dataplex_v1.BusinessGlossaryServiceClient
        The Dataplex Business Glossary client.
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
        glossary_client: dataplex_v1.BusinessGlossaryServiceClient,
        project_id: str,
        project_number: str,
        dataplex_location: str,
        neo4j_driver: Driver,
        database_name: str = "neo4j",
    ) -> None:
        """Initialize the Dataplex glossary connector."""
        self.glossary_client = glossary_client
        self.project_id = project_id
        self.project_number = project_number
        self.dataplex_location = dataplex_location
        self.neo4j_driver = neo4j_driver
        self.database_name = database_name

        self.extractor = DataplexGlossaryExtractor(
            glossary_client, project_id, project_number, dataplex_location
        )
        self.transformer = DataplexGlossaryTransformer()
        self.loader = Neo4jRDBMSLoader(neo4j_driver, database_name)
        self._extracted = False
        self._include_entry_links = True

    def extract(self, include_entry_links: bool = True) -> None:
        """
        Extract glossary content and (optionally) entry links into the cache.

        Parameters
        ----------
        include_entry_links : bool, default True
            Whether to also extract the catalog↔glossary entry links. Set to
            False if the catalog isn't in this Neo4j instance, or to skip the
            REST-API round trips when you only want glossary content.
        """
        self.extractor.extract(include_entry_links=include_entry_links)
        self._extracted = True
        self._include_entry_links = include_entry_links

    def transform(self) -> None:
        """
        Transform cached glossary data into nodes/edges.

        Raises:
        ------
        StateError
            If called before :meth:`extract`.
        """
        if not self._extracted:
            raise StateError(
                "DataplexGlossaryConnector.transform() called before extract().",
                suggestion="Call connector.extract() before connector.transform().",
            )
        e = self.extractor
        t = self.transformer

        t.transform_to_glossary_nodes(e.glossary_info)
        t.transform_to_category_nodes(e.category_info)
        t.transform_to_business_term_nodes(e.business_term_info)

        t.transform_to_has_category_relationships(e.category_info)
        t.transform_to_has_business_term_relationships(e.business_term_info)

        if self._include_entry_links:
            t.transform_to_column_tagged_with_relationships(e.column_term_info)
            t.transform_to_table_tagged_with_relationships(e.table_term_info)

    def load(self) -> None:
        """
        Load transformed glossary data into Neo4j.

        Raises:
        ------
        StateError
            If called before :meth:`transform`.
        """
        if not self._extracted:
            raise StateError(
                "DataplexGlossaryConnector.load() called before extract()/transform().",
                suggestion="Call connector.extract() and connector.transform() first.",
            )
        t = self.transformer

        print(
            self.loader.load_glossary_nodes(
                t.glossary_nodes,
                properties_list=["name", "description", "resource_path"],
            )
        )
        print(
            self.loader.load_category_nodes(
                t.category_nodes,
                properties_list=["name", "description", "resource_path"],
            )
        )
        print(
            self.loader.load_business_term_nodes(
                t.business_term_nodes,
                properties_list=["name", "description", "resource_path"],
            )
        )

        print(self.loader.load_has_category_relationships(t.has_category_relationships))
        print(self.loader.load_has_business_term_relationships(t.has_business_term_relationships))

        if self._include_entry_links:
            print(
                self.loader.load_column_tagged_with_relationships(
                    t.column_tagged_with_relationships
                )
            )
            print(
                self.loader.load_table_tagged_with_relationships(t.table_tagged_with_relationships)
            )

    def ingest(self, include_entry_links: bool = True) -> None:
        """
        Run the Dataplex glossary connector (extract → transform → load).

        Parameters
        ----------
        include_entry_links : bool, default True
            Whether to also ingest catalog↔glossary entry links (TAGGED_WITH).
        """
        print("Extracting glossary metadata from Dataplex...")
        self.extract(include_entry_links=include_entry_links)
        print("Transforming glossary metadata from Dataplex...")
        self.transform()
        print("Loading glossary metadata into Neo4j...")
        self.load()
        print("Recording neocarta graph metadata...")
        print(self.loader.upsert_neocarta_graph_node().model_dump())
        print("Dataplex glossary connector completed successfully!")

    def run(self, include_entry_links: bool = True) -> None:
        """
        Run the Dataplex glossary connector.

        .. deprecated::
            Use :meth:`ingest` instead. ``run`` will be removed in a future release.
        """
        warnings.warn(
            "DataplexGlossaryConnector.run() is deprecated; "
            "use DataplexGlossaryConnector.ingest() instead.",
            DeprecationWarning,
            stacklevel=2,
        )
        self.ingest(include_entry_links=include_entry_links)
