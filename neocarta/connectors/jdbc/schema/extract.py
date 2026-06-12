"""JDBC schema extractor — bridges to SchemaCrawler via a subprocess.

The extractor shells out to the SchemaCrawler CLI (a Java tool) to read schema
metadata from any JDBC-compatible database, captures its JSON catalog on
stdout, and flattens it into the pandas-DataFrame cache shape the
:class:`~neocarta.connectors.jdbc.schema.transform.JdbcSchemaTransformer`
consumes — the same shape the BigQuery schema connector uses.

Java 11+, a SchemaCrawler distribution JAR, and a JDBC driver JAR for the
target database must be installed on the host; see
``neocarta/connectors/jdbc/README.md`` for setup.

Extraction uses SchemaCrawler's ``template`` command with the bundled FreeMarker
template (:data:`_TEMPLATE_PATH`), which renders a compact JSON catalog carrying
full table / column / primary-key / foreign-key detail. SchemaCrawler's
``serialize`` command omits tables and foreign keys, so it cannot be used; the
template has full access to the catalog model. A FreeMarker JAR must be on the
SchemaCrawler classpath — see the README.
"""

import importlib.resources
import json
import os
import re
import shutil
import subprocess
from typing import Any

import pandas as pd

from ...._logging import log_stage
from ....errors import ConfigError, ExtractionError, OperationTimeoutError
from .models import JdbcSchemaExtractorCache

# Bundled FreeMarker template that renders the JSON catalog this extractor parses.
# Resolved via importlib.resources so it always references THIS package's file
# (module-scoped, and correct for wheel installs) — never some other file in the
# project tree.
_TEMPLATE_PATH = importlib.resources.files(__package__) / "catalog.json.ftl"

# Minimum supported Java major version (a named connector requirement).
_MIN_JAVA_MAJOR = 11

# Env var name SchemaCrawler reads the DB password from (``--password:env=``).
# Passing the secret via the environment keeps it off the process argv, where
# it would otherwise be visible to anyone who can list processes.
_PASSWORD_ENV_VAR = "NEOCARTA_JDBC_PASSWORD"  # noqa: S105 — env var name, not a secret

_SETUP_HINT = (
    "See neocarta/connectors/jdbc/README.md for setup (Java 11+, the SchemaCrawler "
    "distribution, a FreeMarker JAR on its classpath, and a JDBC driver JAR)."
)


def _parse_java_major(version_output: str) -> int | None:
    """Parse the major Java version from ``java -version`` output.

    Handles modern (``version "17.0.19"`` → 17) and legacy
    (``version "1.8.0_392"`` → 8) version strings. Returns ``None`` if no version
    can be found.
    """
    match = re.search(r'version "(\d+)(?:\.(\d+))?', version_output)
    if match is None:
        return None
    major = int(match.group(1))
    if major == 1 and match.group(2) is not None:
        # Legacy ``1.x`` scheme: the real major is the second component.
        major = int(match.group(2))
    return major


def _assert_java_available() -> None:
    """Verify a usable Java runtime (>= 11) is on ``PATH``.

    Raises:
    ------
    ConfigError
        If ``java`` is not found, ``java -version`` fails, the version cannot be
        determined, or the runtime is older than Java 11.
    """
    if shutil.which("java") is None:
        raise ConfigError(
            "Java runtime not found on PATH; the JDBC connector shells out to "
            "SchemaCrawler, which requires Java.",
            suggestion=f"Install Java {_MIN_JAVA_MAJOR}+. {_SETUP_HINT}",
        )

    version_cmd = ["java", "-version"]
    try:
        result = subprocess.run(  # noqa: S603
            version_cmd,
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise ConfigError(
            f"Failed to invoke 'java -version': {exc}",
            suggestion=f"Install a working Java {_MIN_JAVA_MAJOR}+ runtime. {_SETUP_HINT}",
        ) from exc

    if result.returncode != 0:
        raise ConfigError(
            "'java -version' exited non-zero; no usable Java runtime found.",
            suggestion=f"Install Java {_MIN_JAVA_MAJOR}+. {_SETUP_HINT}",
            details={"stderr": result.stderr.strip()},
        )

    # `java -version` prints to stderr; fall back to stdout defensively.
    version_output = result.stderr or result.stdout
    major = _parse_java_major(version_output)
    if major is None:
        raise ConfigError(
            "Could not determine the Java version from 'java -version' output.",
            suggestion=f"Ensure Java {_MIN_JAVA_MAJOR}+ is installed. {_SETUP_HINT}",
            details={"output": version_output.strip()},
        )
    if major < _MIN_JAVA_MAJOR:
        raise ConfigError(
            f"Java {major} found, but the JDBC connector requires Java {_MIN_JAVA_MAJOR}+.",
            suggestion=f"Install Java {_MIN_JAVA_MAJOR}+. {_SETUP_HINT}",
            details={"detected_major": major},
        )


def derive_source_database_name(jdbc_url: str) -> str | None:
    """Best-effort parse of the database name from a JDBC URL path component.

    Handles the common ``jdbc:<subprotocol>://host:port/<database>?params``
    form (e.g. PostgreSQL, MySQL). Returns ``None`` for shapes without a clear
    path-based database name (e.g. Oracle SID URLs, SQL Server
    ``;databaseName=`` URLs), in which case the caller should supply
    ``source_database_name`` explicitly.

    Parameters
    ----------
    jdbc_url : str
        The JDBC connection URL.

    Returns:
    -------
    str or None
        The parsed database name, or ``None`` if it could not be derived.

    Examples:
    --------
    >>> derive_source_database_name("jdbc:postgresql://localhost:5432/mydb?ssl=true")
    'mydb'
    """
    # Strip query string (``?...``) and SQL-Server-style params (``;...``).
    trimmed = jdbc_url.split("?", 1)[0].split(";", 1)[0]
    if "//" not in trimmed:
        return None
    # Everything after the ``//`` authority separator: ``host:port/db`` or ``host``.
    after_authority = trimmed.split("//", 1)[1]
    if "/" not in after_authority:
        return None
    candidate = after_authority.split("/", 1)[1].strip("/").rsplit("/", 1)[-1]
    # Reject empty / host:port-looking fragments (no real database segment present).
    if not candidate or ":" in candidate:
        return None
    return candidate


class JdbcSchemaExtractor:
    """Extractor for JDBC schema metadata via the SchemaCrawler CLI.

    Internal cached state is *not* part of the public API — callers interact
    only through :class:`JdbcSchemaConnector`. Extract results are exposed as
    read-only properties for the transformer to consume.

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
    source_database_name : str
        Logical database name used to build graph entity ids (the ``Database``
        node name). Typically derived from the JDBC URL by the connector.
    db_user : str, optional
        Database username. Passed to SchemaCrawler via ``--user=``.
    db_password : str, optional
        Database password. The connector forwards it to SchemaCrawler via an
        environment variable (``--password:env=``), never on the process command
        line. It is a constructor argument (rather than a pre-authenticated client,
        as the BigQuery/Dataplex connectors use) because JDBC has no shared client
        object — authentication happens at connection time, per driver.
    platform : str, optional
        Hosting platform for the graph ``Database`` node (e.g. ``"AWS_RDS"``).
        Not derivable from JDBC metadata, so it defaults to ``None``; supply it
        if known.
    service : str, optional
        Database service/engine for the graph ``Database`` node. Defaults to the
        database product name SchemaCrawler reports (e.g. ``"POSTGRESQL"``).
    timeout : int, default 120
        Maximum seconds to wait for the SchemaCrawler subprocess.
    """

    def __init__(
        self,
        jdbc_url: str,
        jdbc_driver: str,
        jdbc_driver_jar: str,
        schemacrawler_jar: str,
        source_database_name: str,
        db_user: str | None = None,
        db_password: str | None = None,
        platform: str | None = None,
        service: str | None = None,
        timeout: int = 120,
    ) -> None:
        """Initialize the extractor and verify Java (>= 11) is available."""
        _assert_java_available()
        self.jdbc_url = jdbc_url
        self.jdbc_driver = jdbc_driver
        self.jdbc_driver_jar = jdbc_driver_jar
        self.schemacrawler_jar = schemacrawler_jar
        self.source_database_name = source_database_name
        self.db_user = db_user
        self.db_password = db_password
        self.platform = platform
        self.service = service
        self.timeout = timeout
        self._cache: JdbcSchemaExtractorCache = JdbcSchemaExtractorCache()

    @property
    def database_info(self) -> pd.DataFrame:
        """Get the database information."""
        return self._cache.get("database_info", pd.DataFrame())

    @property
    def schema_info(self) -> pd.DataFrame:
        """Get the schema information."""
        return self._cache.get("schema_info", pd.DataFrame())

    @property
    def table_info(self) -> pd.DataFrame:
        """Get the table information."""
        return self._cache.get("table_info", pd.DataFrame())

    @property
    def column_info(self) -> pd.DataFrame:
        """Get the column information."""
        return self._cache.get("column_info", pd.DataFrame())

    @property
    def column_references_info(self) -> pd.DataFrame:
        """Get the column references (foreign key) information."""
        return self._cache.get("column_references_info", pd.DataFrame())

    def build_command(self, schemas: list[str] | None = None) -> list[str]:
        """Build the SchemaCrawler subprocess argv.

        Uses SchemaCrawler's ``template`` command with the bundled FreeMarker
        template, so the rendered JSON includes tables, primary keys, and
        foreign keys. The DB password is referenced via ``--password:env=``
        only; its value is supplied through the subprocess environment, not argv.

        Parameters
        ----------
        schemas : list of str, optional
            Schema names to include. Joined into a regex alternation for
            SchemaCrawler's ``--schemas=<regex>``. If omitted, all schemas are
            extracted.

        Returns:
        -------
        list of str
            The command argument vector.
        """
        classpath = os.pathsep.join([self.schemacrawler_jar, self.jdbc_driver_jar])
        cmd = [
            "java",
            "-cp",
            classpath,
            "schemacrawler.Main",
            f"--url={self.jdbc_url}",
            f"--driver={self.jdbc_driver}",
            "--info-level=detailed",
            "--command=template",
            "--templating-language=freemarker",
            f"--template={_TEMPLATE_PATH}",
        ]
        if self.db_user is not None:
            cmd.append(f"--user={self.db_user}")
        if self.db_password is not None:
            cmd.append(f"--password:env={_PASSWORD_ENV_VAR}")
        if schemas:
            cmd.append("--schemas=" + "|".join(schemas))
        return cmd

    def _run_schemacrawler(self, schemas: list[str] | None = None) -> dict[str, Any]:
        """Run SchemaCrawler and return the parsed JSON catalog.

        Raises:
        ------
        OperationTimeoutError
            If the subprocess exceeds ``timeout``.
        ExtractionError
            If the subprocess fails to start, exits non-zero, or emits output
            that is not valid JSON.
        """
        cmd = self.build_command(schemas)
        env = {**os.environ, "SC_LOGLEVEL": "SEVERE"}
        if self.db_password is not None:
            env[_PASSWORD_ENV_VAR] = self.db_password

        try:
            result = subprocess.run(  # noqa: S603
                cmd,
                capture_output=True,
                text=True,
                timeout=self.timeout,
                env=env,
                check=False,
            )
        except subprocess.TimeoutExpired as exc:
            raise OperationTimeoutError(
                f"SchemaCrawler timed out after {self.timeout}s.",
                suggestion="Increase `timeout`, or narrow extraction with `schemas=[...]`.",
            ) from exc
        except (OSError, subprocess.SubprocessError) as exc:
            raise ExtractionError(
                f"Failed to run SchemaCrawler: {exc}",
                suggestion=f"Check the JAR paths and that Java works. {_SETUP_HINT}",
            ) from exc

        if result.returncode != 0:
            raise ExtractionError(
                f"SchemaCrawler exited with code {result.returncode}.",
                details={"stderr": result.stderr.strip()},
            )

        try:
            return json.loads(result.stdout)
        except json.JSONDecodeError as exc:
            raise ExtractionError(
                "SchemaCrawler did not return valid JSON.",
                details={"error": str(exc), "stderr": result.stderr.strip()},
            ) from exc

    @log_stage
    def extract(self, schemas: list[str] | None = None) -> None:
        """Run SchemaCrawler once and populate every cache DataFrame.

        Parameters
        ----------
        schemas : list of str, optional
            Schema names to include. If omitted, all schemas are extracted.
        """
        catalog = self._run_schemacrawler(schemas)
        self._cache["database_info"] = self._flatten_database_info(catalog)
        self._cache["schema_info"] = self._flatten_schema_info(catalog)
        self._cache["table_info"] = self._flatten_table_info(catalog)
        self._cache["column_info"] = self._flatten_column_info(catalog)
        self._cache["column_references_info"] = self._flatten_column_references_info(catalog)

    def _flatten_database_info(self, catalog: dict[str, Any]) -> pd.DataFrame:
        """Build the single-row database DataFrame (name + platform + service).

        ``service`` defaults to SchemaCrawler's reported database product name
        (e.g. ``PostgreSQL``); ``platform`` is left unset unless supplied. The
        transformer omits whichever of these is ``None`` from the graph node.
        """
        service = self.service or (catalog.get("product") or None)
        return pd.DataFrame(
            [
                {
                    "database_name": self.source_database_name,
                    "platform": self.platform,
                    "service": service,
                }
            ]
        )

    def _flatten_schema_info(self, catalog: dict[str, Any]) -> pd.DataFrame:
        """Flatten template schemas into ``database_name, schema_name, description`` rows."""
        rows = [
            {
                "database_name": self.source_database_name,
                "schema_name": schema["name"],
                "description": schema.get("remarks") or None,
            }
            for schema in catalog.get("schemas", [])
        ]
        return pd.DataFrame(rows)

    def _flatten_table_info(self, catalog: dict[str, Any]) -> pd.DataFrame:
        """Flatten template tables into per-table rows."""
        rows = [
            {
                "database_name": self.source_database_name,
                "schema_name": table["schema"],
                "table_name": table["name"],
                "description": table.get("remarks") or None,
            }
            for table in catalog.get("tables", [])
        ]
        return pd.DataFrame(rows)

    def _flatten_column_info(self, catalog: dict[str, Any]) -> pd.DataFrame:
        """Flatten template columns, carrying type / nullable / primary-/foreign-key flags."""
        rows = [
            {
                "database_name": self.source_database_name,
                "schema_name": table["schema"],
                "table_name": table["name"],
                "column_name": column["name"],
                "type": column.get("type") or None,
                "nullable": bool(column.get("nullable", True)),
                "description": column.get("remarks") or None,
                "is_primary_key": bool(column.get("is_primary_key", False)),
                "is_foreign_key": bool(column.get("is_foreign_key", False)),
            }
            for table in catalog.get("tables", [])
            for column in table.get("columns", [])
        ]
        return pd.DataFrame(rows)

    def _flatten_column_references_info(self, catalog: dict[str, Any]) -> pd.DataFrame:
        """Flatten template foreign keys into source/target reference rows."""
        rows = [
            {
                "database_name": self.source_database_name,
                "source_schema_name": fk["source_schema"],
                "source_table_name": fk["source_table"],
                "source_column_name": fk["source_column"],
                "target_schema_name": fk["target_schema"],
                "target_table_name": fk["target_table"],
                "target_column_name": fk["target_column"],
            }
            for fk in catalog.get("foreign_keys", [])
        ]
        return pd.DataFrame(rows)
