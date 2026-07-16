"""Integration test for the JDBC schema connector (skip-guarded).

Runs the real SchemaCrawler subprocess against a Dockerized PostgreSQL instance,
then asserts the resulting graph. It requires Java 11+, a SchemaCrawler
distribution JAR (``SCHEMACRAWLER_JAR``), and a PostgreSQL JDBC driver JAR
(``JDBC_DRIVER_JAR``) on the host — see ``neocarta/connectors/jdbc/README.md``.
When that tooling is absent (e.g. in CI) the whole module is skipped; the
mocked-subprocess unit tests provide CI coverage instead.
"""

import os
import shutil
import subprocess

import pytest

from neocarta.connectors.jdbc import JdbcSchemaConnector


def _java_runtime_available() -> bool:
    """Return True only if a Java runtime is present and ``java -version`` works."""
    if shutil.which("java") is None:
        return False
    version_cmd = ["java", "-version"]
    try:
        result = subprocess.run(  # noqa: S603
            version_cmd,
            capture_output=True,
            timeout=30,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return False
    return result.returncode == 0


pytestmark = pytest.mark.skipif(
    not _java_runtime_available()
    or not os.getenv("SCHEMACRAWLER_JAR")
    or not os.getenv("JDBC_DRIVER_JAR"),
    reason="requires Java 11+ and SCHEMACRAWLER_JAR + JDBC_DRIVER_JAR env vars",
)


def test_jdbc_schema_ingest_postgres(neo4j_driver, postgres_jdbc):
    """Ingest a seeded Postgres schema and assert nodes + REFERENCES edge."""
    connector = JdbcSchemaConnector(
        jdbc_url=postgres_jdbc["url"],
        jdbc_driver="org.postgresql.Driver",
        jdbc_driver_jar=os.environ["JDBC_DRIVER_JAR"],
        schemacrawler_jar=os.environ["SCHEMACRAWLER_JAR"],
        neo4j_driver=neo4j_driver,
        source_database_name=postgres_jdbc["database"],
        db_user=postgres_jdbc["user"],
        db_password=postgres_jdbc["password"],
    )

    connector.ingest(schemas=["public"])

    with neo4j_driver.session(database="neo4j") as session:
        tables = sorted(r["name"] for r in session.run("MATCH (t:Table) RETURN t.name AS name"))
        assert tables == ["customers", "orders"]

        pk = session.run(
            "MATCH (t:Table {name: 'customers'})-[:HAS_COLUMN]->(c:Column {name: 'id'}) "
            "RETURN c.is_primary_key AS pk"
        ).single()["pk"]
        assert pk

        ref = session.run(
            "MATCH (src:Column)-[:REFERENCES]->(tgt:Column) RETURN src.name AS src, tgt.name AS tgt"
        ).single()
        assert ref["src"] == "customer_id"
        assert ref["tgt"] == "id"
