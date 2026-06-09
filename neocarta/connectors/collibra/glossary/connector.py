"""CollibraGlossaryConnector: Collibra business-glossary metadata into Neo4j."""

import warnings

from neo4j import Driver

from ....enums import NodeLabel, RelationshipType
from ....errors import StateError
from ..client import CollibraClient
from ..load import CollibraNeo4jLoader
from .extract import CollibraGlossaryExtractor
from .transform import CollibraGlossaryTransformer


class CollibraGlossaryConnector:
    """
    Connector for loading Collibra business-glossary metadata into Neo4j.

    Maps Collibra business-glossary Domains → Glossary, Data Category assets →
    Category, and Business Term assets → BusinessTerm (as ``Collibra*`` subtype
    nodes), and emits ``TAGGED_WITH`` edges from tagged Table/Column assets to
    Business Terms (matched by ``collibra_id``, so they resolve against nodes the
    schema sub-connector produced). Follows an Extract → Transform → Load pipeline.

    Parameters
    ----------
    client : CollibraClient
        Authenticated Collibra HTTP client (holds URL + credentials).
    neo4j_driver : Driver
        Neo4j driver instance.
    database_name : str, default "neo4j"
        Target Neo4j database name.
    """

    def __init__(
        self,
        client: CollibraClient,
        neo4j_driver: Driver,
        database_name: str = "neo4j",
    ) -> None:
        """Initialize the Collibra glossary connector."""
        self.client = client
        self.neo4j_driver = neo4j_driver
        self.database_name = database_name

        self.extractor = CollibraGlossaryExtractor(client)
        self.transformer = CollibraGlossaryTransformer()
        self.loader = CollibraNeo4jLoader(neo4j_driver, database_name)
        self._extracted = False
        self._transformed = False
        self._include_nodes: list[NodeLabel] | None = None
        self._include_relationships: list[RelationshipType] | None = None

    def extract(
        self,
        community_ids: list[str] | None = None,
        domain_ids: list[str] | None = None,
        asset_type_names: list[str] | None = None,
        *,
        include_nodes: list[NodeLabel] | None = None,
        include_relationships: list[RelationshipType] | None = None,
    ) -> None:
        """
        Extract and cache Collibra business-glossary metadata.

        Parameters
        ----------
        community_ids, domain_ids : list[str], optional
            Restrict extraction to these Collibra community/domain UUIDs.
        asset_type_names : list[str], optional
            Restrict assets to these Collibra asset-type display names.
        include_nodes : list[NodeLabel], optional
            Subset of {GLOSSARY, CATEGORY, BUSINESS_TERM} to produce. ``None`` = all.
        include_relationships : list[RelationshipType], optional
            Subset of {HAS_CATEGORY, HAS_BUSINESS_TERM, TAGGED_WITH}. ``None`` = all.
        """
        self._extracted = False
        self._transformed = False
        self._include_nodes = include_nodes
        self._include_relationships = include_relationships
        self.extractor.extract(
            community_ids,
            domain_ids,
            asset_type_names,
            include_nodes=include_nodes,
            include_relationships=include_relationships,
        )
        self._extracted = True

    def transform(self) -> None:
        """
        Convert cached metadata into ``Collibra*`` subtype graph objects.

        Raises:
        ------
        StateError
            If called before :meth:`extract`.
        """
        if not self._extracted:
            raise StateError(
                "CollibraGlossaryConnector.transform() called before extract(); call .extract() first.",
                suggestion="Call connector.extract(...) before connector.transform().",
            )
        self._transformed = False
        self.transformer = CollibraGlossaryTransformer()
        self.transformer.transform_all(
            self.extractor, self._include_nodes, self._include_relationships
        )
        self._transformed = True

    def load(self, overwrite_existing: bool = False) -> None:
        """
        Write transformed objects into Neo4j.

        Parameters
        ----------
        overwrite_existing : bool
            When True, overwrite existing node properties; otherwise set on create only.

        Raises:
        ------
        StateError
            If called before :meth:`transform`.
        """
        if not self._transformed:
            raise StateError(
                "CollibraGlossaryConnector.load() called before transform(); call .transform() first.",
                suggestion="Call connector.extract() and connector.transform() first.",
            )
        t = self.transformer
        if t.glossary_nodes:
            print(
                self.loader.load_collibra_glossary_nodes(
                    t.glossary_nodes, overwrite_existing=overwrite_existing
                )
            )
        if t.category_nodes:
            print(
                self.loader.load_collibra_category_nodes(
                    t.category_nodes, overwrite_existing=overwrite_existing
                )
            )
        if t.business_term_nodes:
            print(
                self.loader.load_collibra_business_term_nodes(
                    t.business_term_nodes, overwrite_existing=overwrite_existing
                )
            )
        if t.has_category_relationships:
            print(
                self.loader.load_has_category_relationships(
                    t.has_category_relationships, overwrite_existing=overwrite_existing
                )
            )
        if t.has_business_term_relationships:
            print(
                self.loader.load_has_business_term_relationships(
                    t.has_business_term_relationships, overwrite_existing=overwrite_existing
                )
            )
        if t.tagged_with_relationships:
            print(self.loader.load_collibra_tagged_with_relationships(t.tagged_with_relationships))

    def ingest(
        self,
        community_ids: list[str] | None = None,
        domain_ids: list[str] | None = None,
        asset_type_names: list[str] | None = None,
        *,
        include_nodes: list[NodeLabel] | None = None,
        include_relationships: list[RelationshipType] | None = None,
        overwrite_existing: bool = False,
    ) -> None:
        """Run the Collibra glossary connector (extract → transform → load)."""
        print("Extracting metadata from Collibra...")
        self.extract(
            community_ids,
            domain_ids,
            asset_type_names,
            include_nodes=include_nodes,
            include_relationships=include_relationships,
        )
        print("Transforming Collibra metadata...")
        self.transform()
        print("Loading metadata into Neo4j...")
        self.load(overwrite_existing=overwrite_existing)
        print("Recording neocarta graph metadata...")
        print(self.loader.upsert_neocarta_graph_node().model_dump())
        print("CollibraGlossaryConnector completed successfully!")

    def run(
        self,
        community_ids: list[str] | None = None,
        domain_ids: list[str] | None = None,
        asset_type_names: list[str] | None = None,
        *,
        include_nodes: list[NodeLabel] | None = None,
        include_relationships: list[RelationshipType] | None = None,
        overwrite_existing: bool = False,
    ) -> None:
        """
        Run the Collibra glossary connector.

        .. deprecated::
            Use :meth:`ingest` instead. ``run`` will be removed in a future release.
        """
        warnings.warn(
            "CollibraGlossaryConnector.run() is deprecated; use CollibraGlossaryConnector.ingest() instead.",
            DeprecationWarning,
            stacklevel=2,
        )
        self.ingest(
            community_ids,
            domain_ids,
            asset_type_names,
            include_nodes=include_nodes,
            include_relationships=include_relationships,
            overwrite_existing=overwrite_existing,
        )
