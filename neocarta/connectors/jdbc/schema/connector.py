"""JDBC schema connector."""

import warnings

from neo4j import Driver

from ....errors import ConfigError, StateError
from ....ingest.rdbms import Neo4jRDBMSLoader
from .extract import JdbcSchemaExtractor, derive_source_database_name
from .transform import JdbcSchemaTransformer


class JdbcSchemaConnector:
    """
    Connector for extracting JDBC schema metadata into Neo4j via SchemaCrawler.

    Follows an Extract → Transform → Load pipeline. :meth:`ingest` runs all
    three stages and records the neocarta graph metadata node at the end.

    Extraction shells out to the SchemaCrawler CLI (Java); Java 11+ and the
    SchemaCrawler / JDBC-driver JARs must be installed on the host. See
    ``neocarta/connectors/jdbc/README.md``.

    Parameters
    ----------
    jdbc_url : str
        JDBC connection URL, e.g. ``jdbc:postgresql://host:5432/mydb``.
    jdbc_driver : str
        Fully-qualified JDBC driver class, e.g. ``org.postgresql.Driver``.
    jdbc_driver_jar : str
        Filesystem path to the JDBC driver JAR for the target database.
    schemacrawler_jar : str
        Filesystem path to the SchemaCrawler distribution (fat) JAR.
    neo4j_driver : Driver
        Neo4j driver instance.
    database_name : str, default "neo4j"
        Target Neo4j database name.
    source_database_name : str, optional
        Name for the graph ``Database`` node (and the root of all entity ids).
        Defaults to the database parsed from ``jdbc_url``; required when the URL
        shape (e.g. Oracle SID, SQL Server ``;databaseName=``) cannot be parsed.
    db_user : str, optional
        Database username.
    db_password : str, optional
        Database password. Forwarded to SchemaCrawler via an environment variable
        (``--password:env=``), never on the command line. A constructor arg
        (rather than a pre-authed client, as BigQuery/Dataplex use) because JDBC
        has no shared client object — auth happens at connection time, per driver.
    platform : str, optional
        Hosting platform for the graph ``Database`` node (e.g. ``"AWS_RDS"``).
        Not derivable from JDBC metadata; defaults to ``None`` (omitted from the
        node) unless supplied.
    service : str, optional
        Database service/engine for the graph ``Database`` node. Defaults to the
        database product name SchemaCrawler reports (e.g. ``"POSTGRESQL"``).
    timeout : int, default 120
        Maximum seconds to wait for the SchemaCrawler subprocess.

    Raises:
    ------
    ConfigError
        If ``source_database_name`` is omitted and cannot be derived from the
        JDBC URL, or if no usable Java runtime is found.
    """

    def __init__(
        self,
        jdbc_url: str,
        jdbc_driver: str,
        jdbc_driver_jar: str,
        schemacrawler_jar: str,
        neo4j_driver: Driver,
        database_name: str = "neo4j",
        source_database_name: str | None = None,
        db_user: str | None = None,
        db_password: str | None = None,
        platform: str | None = None,
        service: str | None = None,
        timeout: int = 120,
    ) -> None:
        """Initialize the JDBC schema connector."""
        resolved_source_db = source_database_name or derive_source_database_name(jdbc_url)
        if not resolved_source_db:
            raise ConfigError(
                "Could not derive the source database name from the JDBC URL.",
                suggestion="Pass source_database_name=... explicitly.",
                details={"jdbc_url": jdbc_url},
            )

        self.jdbc_url = jdbc_url
        self.source_database_name = resolved_source_db
        self.neo4j_driver = neo4j_driver
        self.database_name = database_name

        self.extractor = JdbcSchemaExtractor(
            jdbc_url=jdbc_url,
            jdbc_driver=jdbc_driver,
            jdbc_driver_jar=jdbc_driver_jar,
            schemacrawler_jar=schemacrawler_jar,
            source_database_name=resolved_source_db,
            db_user=db_user,
            db_password=db_password,
            platform=platform,
            service=service,
            timeout=timeout,
        )
        self.transformer = JdbcSchemaTransformer()
        self.loader = Neo4jRDBMSLoader(neo4j_driver, database_name)
        self._extracted = False
        self._transformed = False

    def extract(self, schemas: list[str] | None = None) -> None:
        """
        Extract and cache JDBC schema metadata via SchemaCrawler.

        Parameters
        ----------
        schemas : list of str, optional
            Schema names to include. If omitted, all schemas are extracted.
        """
        self._extracted = False
        self._transformed = False
        self.extractor.extract(schemas)
        self._extracted = True

    def transform(self) -> None:
        """
        Transform cached metadata into graph data model objects.

        Raises:
        ------
        StateError
            If called before :meth:`extract`.
        """
        if not self._extracted:
            raise StateError(
                "JdbcSchemaConnector.transform() called before extract(); call .extract() first.",
                suggestion="Call connector.extract(...) before connector.transform().",
            )
        self._transformed = False
        self.transformer.transform_to_database_nodes(self.extractor.database_info)
        self.transformer.transform_to_schema_nodes(self.extractor.schema_info)
        self.transformer.transform_to_table_nodes(self.extractor.table_info)
        self.transformer.transform_to_column_nodes(self.extractor.column_info)

        self.transformer.transform_to_has_schema_relationships(self.extractor.schema_info)
        self.transformer.transform_to_has_table_relationships(self.extractor.table_info)
        self.transformer.transform_to_has_column_relationships(self.extractor.column_info)
        self.transformer.transform_to_references_relationships(
            self.extractor.column_references_info
        )
        self._transformed = True

    def load(self) -> None:
        """
        Load transformed metadata into Neo4j.

        Raises:
        ------
        StateError
            If called before :meth:`transform`.
        """
        if not self._transformed:
            raise StateError(
                "JdbcSchemaConnector.load() called before transform(); call .transform() first.",
                suggestion="Call connector.extract() and connector.transform() first.",
            )
        print(
            self.loader.load_database_nodes(
                self.transformer.database_nodes,
                properties_list=self.transformer.get_database_properties(),
            )
        )
        print(self.loader.load_schema_nodes(self.transformer.schema_nodes))
        print(self.loader.load_table_nodes(self.transformer.table_nodes))
        print(
            self.loader.load_column_nodes(
                self.transformer.column_nodes,
                properties_list=self.transformer.get_column_properties(),
            )
        )

        print(self.loader.load_has_schema_relationships(self.transformer.has_schema_relationships))
        print(self.loader.load_has_table_relationships(self.transformer.has_table_relationships))
        print(self.loader.load_has_column_relationships(self.transformer.has_column_relationships))
        print(self.loader.load_references_relationships(self.transformer.references_relationships))

    def ingest(self, schemas: list[str] | None = None) -> None:
        """
        Run the JDBC schema connector (extract → transform → load).

        Parameters
        ----------
        schemas : list of str, optional
            Schema names to include. If omitted, all schemas are extracted.
        """
        print("Extracting metadata from JDBC source via SchemaCrawler...")
        self.extract(schemas)
        print("Transforming metadata...")
        self.transform()
        print("Loading metadata into Neo4j...")
        self.load()
        print("Recording neocarta graph metadata...")
        print(self.loader.upsert_neocarta_graph_node().model_dump())
        print("JdbcSchemaConnector completed successfully!")

    def run(self, schemas: list[str] | None = None) -> None:
        """
        Run the JDBC schema connector.

        .. deprecated::
            Use :meth:`ingest` instead. ``run`` will be removed in a future release.
        """
        warnings.warn(
            "JdbcSchemaConnector.run() is deprecated; use JdbcSchemaConnector.ingest() instead.",
            DeprecationWarning,
            stacklevel=2,
        )
        self.ingest(schemas)
