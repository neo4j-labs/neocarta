"""OSI (Open Semantic Interchange) connector — bidirectional Neo4j integration."""

from pathlib import Path

from neo4j import Driver

from ...ingest.rdbms import Neo4jRDBMSLoader
from .export.extract import OsiGraphExtractor
from .export.transform import OsiExportTransformer
from .ingest.extract import OsiSpecExtractor
from .ingest.transform import OsiIngestTransformer


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
        self.loader = Neo4jRDBMSLoader(neo4j_driver, database_name)

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

    def _load_ingest(self, transformer: OsiIngestTransformer) -> None:
        """Load all nodes and relationships produced by an ingest transformer."""
        # TODO(osi-connector): wire up loader calls once Neo4jRDBMSLoader is extended
        # with OSI-specific load methods (step 10 in the implementation plan).
        raise NotImplementedError(
            "OsiConnector loader wiring pending Neo4jRDBMSLoader OSI extensions"
        )
