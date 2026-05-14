"""Collibra Connector: ETL from Collibra Data Intelligence Cloud into Neo4j."""

from neo4j import Driver

from ...ingest.rdbms import Neo4jRDBMSLoader
from .client import CollibraClient
from .extract import CollibraExtractor
from .transform import CollibraTransformer


class CollibraConnector:
    """
    Connector for loading Collibra metadata into Neo4j.

    Follows an Extract → Transform → Load pattern:

    * **Extract** (``CollibraExtractor``) — fetches Communities, Domains, Assets,
      Attributes, Relations, and Lineage from the Collibra Core REST API v2.
    * **Transform** (``CollibraTransformer``) — maps Collibra entities to neocarta
      model objects using UUID-based type resolution.
    * **Load** (``Neo4jRDBMSLoader``) — writes nodes and relationships to Neo4j.

    Parameters
    ----------
    collibra_url : str
        Root URL of the Collibra instance, e.g. ``https://myorg.collibra.com``.
    neo4j_driver : Driver
        Connected Neo4j driver instance.
    username : str | None
        Collibra username for basic auth.
    password : str | None
        Collibra password for basic auth.
    token : str | None
        JWT Bearer token (alternative to username/password).
    database_name : str
        Neo4j database to write into (default ``"neo4j"``).
    community_ids : list[str] | None
        Restrict extraction to these Collibra community UUIDs.
    domain_ids : list[str] | None
        Restrict extraction to these Collibra domain UUIDs.
    asset_type_names : list[str] | None
        Restrict extraction to assets of these type display names.
    include_lineage : bool
        Whether to extract technical lineage (default ``True``).
    """

    def __init__(
        self,
        collibra_url: str,
        neo4j_driver: Driver,
        username: str | None = None,
        password: str | None = None,
        token: str | None = None,
        database_name: str = "neo4j",
        community_ids: list[str] | None = None,
        domain_ids: list[str] | None = None,
        asset_type_names: list[str] | None = None,
        include_lineage: bool = True,
    ) -> None:
        """Initialise client, extractor, transformer, and loader."""
        if not token and not (username and password):
            raise ValueError("Provide either (username, password) or token.")

        self._client = CollibraClient(
            base_url=collibra_url,
            username=username,
            password=password,
            token=token,
        )
        self.extractor = CollibraExtractor(
            client=self._client,
            community_ids=community_ids,
            domain_ids=domain_ids,
            asset_type_names=asset_type_names,
            include_lineage=include_lineage,
        )
        self.transformer: CollibraTransformer | None = None
        self.loader = Neo4jRDBMSLoader(neo4j_driver, database_name)

    # ------------------------------------------------------------------
    # ETL steps
    # ------------------------------------------------------------------

    def extract_metadata(self) -> None:
        """Run all extraction steps (populates the extractor cache)."""
        self.extractor.extract_all()

    def transform_metadata(self) -> None:
        """Convert extracted DataFrames into typed neocarta model objects."""
        self.transformer = CollibraTransformer(self.extractor)
        self.transformer.transform_all()

    def load_metadata(self, overwrite_existing: bool = False) -> None:
        """
        Write transformed objects to Neo4j.

        Parameters
        ----------
        overwrite_existing : bool
            When True, SET all node properties (overwrite existing values).
            When False, only set properties on CREATE (preserve existing data).
        """
        t = self.transformer
        if t is None:
            raise RuntimeError("Call transform_metadata() before load_metadata().")

        if t.database_nodes:
            self.loader.load_database_nodes(t.database_nodes, overwrite_existing=overwrite_existing)
        if t.schema_nodes:
            self.loader.load_schema_nodes(t.schema_nodes, overwrite_existing=overwrite_existing)
        if t.glossary_nodes:
            self.loader.load_glossary_nodes(t.glossary_nodes, overwrite_existing=overwrite_existing)
        if t.table_nodes:
            self.loader.load_table_nodes(t.table_nodes, overwrite_existing=overwrite_existing)
        if t.column_nodes:
            self.loader.load_column_nodes(t.column_nodes, overwrite_existing=overwrite_existing)
        if t.business_term_nodes:
            self.loader.load_business_term_nodes(
                t.business_term_nodes, overwrite_existing=overwrite_existing
            )
        if t.category_nodes:
            self.loader.load_category_nodes(t.category_nodes, overwrite_existing=overwrite_existing)
        if t.catalog_asset_nodes:
            self.loader.load_catalog_asset_nodes(
                t.catalog_asset_nodes, overwrite_existing=overwrite_existing
            )

        if t.has_schema_relationships:
            self.loader.load_has_schema_relationships(
                t.has_schema_relationships, overwrite_existing=overwrite_existing
            )
        if t.has_table_relationships:
            self.loader.load_has_table_relationships(
                t.has_table_relationships, overwrite_existing=overwrite_existing
            )
        if t.has_column_relationships:
            self.loader.load_has_column_relationships(
                t.has_column_relationships, overwrite_existing=overwrite_existing
            )
        if t.has_category_relationships:
            self.loader.load_has_category_relationships(
                t.has_category_relationships, overwrite_existing=overwrite_existing
            )
        if t.has_business_term_relationships:
            self.loader.load_has_business_term_relationships(
                t.has_business_term_relationships, overwrite_existing=overwrite_existing
            )
        if t.has_asset_relationships:
            self.loader.load_has_asset_relationships(
                t.has_asset_relationships, overwrite_existing=overwrite_existing
            )
        if t.tagged_with_relationships:
            self.loader.load_table_tagged_with_relationships(
                list(t.tagged_with_relationships),
                overwrite_existing=overwrite_existing,
            )
        if t.flows_into_relationships:
            self.loader.load_flows_into_relationships(
                t.flows_into_relationships, overwrite_existing=overwrite_existing
            )

    # ------------------------------------------------------------------
    # Public entry point
    # ------------------------------------------------------------------

    def run(self, overwrite_existing: bool = False) -> None:
        """
        Run the full Extract → Transform → Load pipeline.

        Parameters
        ----------
        overwrite_existing : bool
            Passed through to ``load_metadata()``.
        """
        self.extract_metadata()
        self.transform_metadata()
        self.load_metadata(overwrite_existing=overwrite_existing)
