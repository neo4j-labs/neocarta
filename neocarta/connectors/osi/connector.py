"""OSI (Open Semantic Interchange) connector — bidirectional Neo4j integration."""

from pathlib import Path

from neo4j import Driver

from .export.extract import OsiGraphExtractor
from .export.transform import OsiExportTransformer
from .ingest.extract import OsiSpecExtractor
from .ingest.transform import OsiIngestTransformer
from .load import OsiNeo4jLoader


class OsiConnector:
    """
    Bidirectional OSI connector.

    Supports two directions:

    - :meth:`ingest` reads an OSI YAML spec (local path or URL) and loads it into Neo4j.
    - :meth:`export` reads an OSI semantic model from Neo4j (filtered by name) and emits
      an OSI YAML spec.

    Parameters
    ----------
    neo4j_driver : neo4j.Driver
        Connected Neo4j driver.
    database_name : str, default "neo4j"
        Target Neo4j database.
    http_timeout : float, default 30.0
        Timeout in seconds when fetching an OSI spec by URL.
    """

    def __init__(
        self,
        neo4j_driver: Driver,
        database_name: str = "neo4j",
        http_timeout: float = 30.0,
    ) -> None:
        self.neo4j_driver = neo4j_driver
        self.database_name = database_name
        self.http_timeout = http_timeout
        self.loader = OsiNeo4jLoader(neo4j_driver, database_name)

    def ingest(self, spec_source: str | Path) -> None:
        """
        Read an OSI YAML spec and load it into Neo4j.

        Parameters
        ----------
        spec_source : str | Path
            A local filesystem path or an ``http(s)://`` URL pointing to the OSI YAML.
        """
        print(f"Extracting OSI spec from {spec_source}...")
        extractor = OsiSpecExtractor(spec_source, http_timeout=self.http_timeout)
        spec = extractor.extract()

        print("Transforming OSI spec...")
        transformer = OsiIngestTransformer()
        transformer.transform(spec)

        print("Loading OSI semantic model into Neo4j...")
        self._load_ingest(transformer)

        print("Recording neocarta graph metadata...")
        print(self.loader.upsert_neocarta_graph_node().model_dump())
        print("OSI ingest completed successfully!")

    def export(self, semantic_model_name: str, output_path: str | Path) -> None:
        """
        Read an OSI semantic model from Neo4j and emit an OSI YAML spec.

        Parameters
        ----------
        semantic_model_name : str
            The ``name`` of the :OsiSemanticModel to export. Required.
        output_path : str | Path
            Destination path for the OSI YAML output.
        """
        print(f"Extracting OSI semantic model '{semantic_model_name}' from Neo4j...")
        extractor = OsiGraphExtractor(self.neo4j_driver, self.database_name)
        snapshot = extractor.extract(semantic_model_name)

        print("Transforming graph snapshot to OSI spec...")
        transformer = OsiExportTransformer()
        transformer.transform(snapshot)

        print(f"Writing OSI YAML to {output_path}...")
        transformer.to_yaml(output_path)
        print("OSI export completed successfully!")

    def run(self, spec_source: str | Path) -> None:
        """
        Run the OSI connector in ingest mode.

        .. note::
           This entrypoint is retained for compatibility with other connectors;
           prefer calling :meth:`ingest` directly. A deprecation warning will be
           added in a future PR.
        """
        self.ingest(spec_source)

    # ------------------------------------------------------------------ #
    # Loader orchestration
    # ------------------------------------------------------------------ #

    def _load_ingest(self, transformer: OsiIngestTransformer) -> None:
        """Load all nodes and relationships produced by an ingest transformer.

        Order matters for referential integrity in Neo4j: parent nodes are loaded
        before their children, and relationships only after both endpoints exist.
        """
        loader = self.loader

        # Each OSI-specific node loader MERGEs on the primary label (e.g. :Table)
        # and adds the OSI subtype label (e.g. :OsiTable) in the same write, so we
        # don't also call the base loader's load_table_nodes — that would create
        # the node first and the second call's ON CREATE props (source,
        # primary_key, unique_keys) would never fire.
        if transformer.database_nodes:
            loader.load_database_nodes(transformer.database_nodes)
        if transformer.schema_nodes:
            loader.load_schema_nodes(transformer.schema_nodes)
        if transformer.table_nodes:
            loader.load_osi_table_nodes(transformer.table_nodes)
        if transformer.column_nodes:
            loader.load_osi_column_nodes(transformer.column_nodes)
        if transformer.query_nodes:
            loader.load_query_nodes(
                transformer.query_nodes,
                properties_list=["name", "content", "description"],
            )
        if transformer.osi_semantic_model_nodes:
            loader.load_osi_semantic_model_nodes(transformer.osi_semantic_model_nodes)
        if transformer.metric_nodes:
            loader.load_metric_nodes(transformer.metric_nodes)
        if transformer.join_nodes:
            loader.load_join_nodes(transformer.join_nodes)
        if transformer.expression_nodes:
            loader.load_expression_nodes(transformer.expression_nodes)
        if transformer.ai_context_nodes:
            loader.load_osi_ai_context_nodes(transformer.ai_context_nodes)
        if transformer.custom_extension_nodes:
            loader.load_osi_custom_extensions_nodes(transformer.custom_extension_nodes)
        if transformer.business_term_nodes:
            loader.load_business_term_nodes_by_name(transformer.business_term_nodes)

        # Relationships
        if transformer.has_schema_rels:
            loader.load_has_schema_relationships(transformer.has_schema_rels)
        if transformer.has_table_rels:
            loader.load_has_table_relationships(transformer.has_table_rels)
        if transformer.has_column_rels:
            loader.load_has_column_relationships(transformer.has_column_rels)
        if transformer.references_rels:
            loader.load_references_relationships(transformer.references_rels)
        if transformer.domain_has_table_rels:
            loader.load_domain_has_table_relationships(transformer.domain_has_table_rels)
        if transformer.has_query_rels:
            loader.load_has_query_relationships(transformer.has_query_rels)
        if transformer.uses_column_rels:
            loader.load_uses_column_relationships(transformer.uses_column_rels)
        if transformer.has_metric_rels:
            loader.load_has_metric_relationships(transformer.has_metric_rels)
        if transformer.has_aspect_rels:
            loader.load_has_aspect_relationships(transformer.has_aspect_rels)
        if transformer.has_expression_rels:
            loader.load_has_expression_relationships(transformer.has_expression_rels)
        if transformer.has_source_table_rels:
            loader.load_has_source_table_relationships(transformer.has_source_table_rels)
        if transformer.has_target_table_rels:
            loader.load_has_target_table_relationships(transformer.has_target_table_rels)
        if transformer.used_in_join_rels:
            loader.load_used_in_join_relationships(transformer.used_in_join_rels)
        if transformer.tagged_with_rels:
            loader.load_osi_tagged_with_relationships(
                transformer.tagged_with_rels,
                transformer.business_term_nodes,
            )
