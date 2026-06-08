"""CollibraSchemaConnector: Collibra physical-layer metadata into Neo4j."""

import warnings

from neo4j import Driver

from ....enums import NodeLabel, RelationshipType
from ....errors import StateError
from ..client import CollibraClient
from ..load import CollibraNeo4jLoader
from .extract import CollibraSchemaExtractor
from .transform import CollibraSchemaTransformer


class CollibraSchemaConnector:
    """
    Connector for loading Collibra physical-layer metadata into Neo4j.

    Maps Collibra Communities → Database, physical-data Domains → Schema, and
    Table/Column assets → Table/Column, all as ``Collibra*`` subtype nodes
    (``:Table:CollibraTable`` etc.). Follows an Extract → Transform → Load
    pipeline; :meth:`ingest` runs all three stages and records the neocarta graph
    metadata node at the end.

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
        """Initialize the Collibra schema connector."""
        self.client = client
        self.neo4j_driver = neo4j_driver
        self.database_name = database_name

        self.extractor = CollibraSchemaExtractor(client)
        self.transformer = CollibraSchemaTransformer()
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
        Extract and cache Collibra physical-layer metadata.

        Parameters
        ----------
        community_ids, domain_ids : list[str], optional
            Restrict extraction to these Collibra community/domain UUIDs.
        asset_type_names : list[str], optional
            Restrict assets to these Collibra asset-type display names.
        include_nodes : list[NodeLabel], optional
            Subset of {DATABASE, SCHEMA, TABLE, COLUMN} to produce. ``None`` = all.
        include_relationships : list[RelationshipType], optional
            Subset of {HAS_SCHEMA, HAS_TABLE, HAS_COLUMN} to produce. ``None`` = all.
        """
        self._extracted = False
        self._transformed = False
        self._include_nodes = include_nodes
        self._include_relationships = include_relationships
        self.extractor.extract(
            community_ids, domain_ids, asset_type_names, include_nodes=include_nodes
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
                "CollibraSchemaConnector.transform() called before extract(); call .extract() first.",
                suggestion="Call connector.extract(...) before connector.transform().",
            )
        self._transformed = False
        self.transformer = CollibraSchemaTransformer()
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
                "CollibraSchemaConnector.load() called before transform(); call .transform() first.",
                suggestion="Call connector.extract() and connector.transform() first.",
            )
        t = self.transformer
        if t.database_nodes:
            print(
                self.loader.load_collibra_database_nodes(
                    t.database_nodes, overwrite_existing=overwrite_existing
                )
            )
        if t.schema_nodes:
            print(
                self.loader.load_collibra_schema_nodes(
                    t.schema_nodes, overwrite_existing=overwrite_existing
                )
            )
        if t.table_nodes:
            print(
                self.loader.load_collibra_table_nodes(
                    t.table_nodes, overwrite_existing=overwrite_existing
                )
            )
        if t.column_nodes:
            print(
                self.loader.load_collibra_column_nodes(
                    t.column_nodes, overwrite_existing=overwrite_existing
                )
            )
        if t.has_schema_relationships:
            print(
                self.loader.load_has_schema_relationships(
                    t.has_schema_relationships, overwrite_existing=overwrite_existing
                )
            )
        if t.has_table_relationships:
            print(
                self.loader.load_has_table_relationships(
                    t.has_table_relationships, overwrite_existing=overwrite_existing
                )
            )
        if t.has_column_relationships:
            print(
                self.loader.load_has_column_relationships(
                    t.has_column_relationships, overwrite_existing=overwrite_existing
                )
            )

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
        """Run the Collibra schema connector (extract → transform → load)."""
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
        print("CollibraSchemaConnector completed successfully!")

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
        Run the Collibra schema connector.

        .. deprecated::
            Use :meth:`ingest` instead. ``run`` will be removed in a future release.
        """
        warnings.warn(
            "CollibraSchemaConnector.run() is deprecated; use CollibraSchemaConnector.ingest() instead.",
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
