"""Build each declared connector's **real** extractor with a deterministic, offline cache.

Every driver runs the production extractor class — no network, no Docker, no JVM, no optional
extra — so a Layer R golden captured through one is a statement about the real connector, not
about a stand-in. Every input is an oracle **already committed to the repo** before this ticket:
the shared BigQuery cache seed, the SchemaCrawler catalog, the ``datasets/csv`` sample, the
BigQuery audit-log JSON. The one exception is Databricks tags, whose SDK objects cannot be
committed as data; it replays a dozen lines of SDK-shaped stand-ins through the real extract path.
"""

import pathlib
from collections.abc import Callable
from types import SimpleNamespace
from typing import Any
from unittest.mock import MagicMock, patch

from neocarta.connectors.bigquery.schema.extract import BigQuerySchemaExtractor
from neocarta.connectors.csv import CSVConnector
from neocarta.connectors.databricks.tags.extract import DatabricksTagsExtractor
from neocarta.connectors.jdbc.schema.extract import JdbcSchemaExtractor
from neocarta.connectors.query_log.extract import QueryLogExtractor
from tests.support.characterization import DATASETS_CSV
from tests.support.characterization.bigquery_cache import (
    make_mock_bigquery_client,
    seed_bigquery_schema_cache,
)

_TESTS = pathlib.Path(__file__).parents[2]
_JDBC_CATALOG = _TESTS / "unit" / "connectors" / "jdbc" / "schema" / "fixtures"
_QUERY_LOG_JSON = _TESTS / "unit" / "connectors" / "query_log" / "test_bigquery_query_log.json"

_JAVA_CHECK = "neocarta.connectors.jdbc.schema.extract._assert_java_available"
_SUBPROCESS_RUN = "neocarta.connectors.jdbc.schema.extract.subprocess.run"


def bigquery_schema() -> BigQuerySchemaExtractor:
    """BigQuery schema, from the shared committed cache seed."""
    return seed_bigquery_schema_cache(
        BigQuerySchemaExtractor(client=make_mock_bigquery_client(), dataset_id="test_dataset")
    )


def jdbc_schema() -> JdbcSchemaExtractor:
    """JDBC schema, replaying a committed SchemaCrawler catalog through a mocked subprocess."""
    catalog = (_JDBC_CATALOG / "schemacrawler_postgres.json").read_text(encoding="utf-8")
    with patch(_JAVA_CHECK):
        extractor = JdbcSchemaExtractor(
            jdbc_url="jdbc:postgresql://localhost:5432/neocarta_test",
            jdbc_driver="org.postgresql.Driver",
            jdbc_driver_jar="schemacrawler-jars/postgresql.jar",
            schemacrawler_jar="schemacrawler-jars/schemacrawler.jar",
            source_database_name="neocarta_test",
        )
        completed = MagicMock(returncode=0, stdout=catalog, stderr="")
        with patch(_SUBPROCESS_RUN, return_value=completed):
            extractor.extract()
    return extractor


def csv_connector() -> CSVConnector:
    """The CSV connector, extracted from the committed sample dataset.

    Returns the whole connector rather than its extractor: the Layer A parity suite needs the
    hand-written transformer too, and both hang off the same object.
    """
    connector = CSVConnector(csv_directory=str(DATASETS_CSV), neo4j_driver=MagicMock())
    connector.extract()
    return connector


def csv() -> Any:
    """CSV, as the extractor the declaration binds against."""
    return csv_connector().extractor


def query_log() -> QueryLogExtractor:
    """Query log, parsed from the committed BigQuery audit-log JSON by the real sqlglot path."""
    extractor = QueryLogExtractor()
    extractor.extract_info_from_query_log_json(str(_QUERY_LOG_JSON))
    return extractor


def databricks_tags() -> DatabricksTagsExtractor:
    """Databricks governance tags, from SDK-shaped stand-ins with no real workspace.

    Covers the shapes the governance facet has to survive: two enumerated tags, a value-less tag
    (whose rows the extractor drops from the value table), and a ``system.``-prefixed tag
    (excluded by default).
    """

    def policy(tag_key: str, description: str, values: list[str]) -> SimpleNamespace:
        return SimpleNamespace(
            tag_key=tag_key,
            description=description,
            id=f"tp-{tag_key}",
            values=[SimpleNamespace(name=value) for value in values],
        )

    client = MagicMock()
    client.tag_policies.list_tag_policies.return_value = [
        policy("department", "Owning department", ["finance", "hr", "sales"]),
        policy("cost_center", "Finance cost center", ["alpha", "beta"]),
        policy("free_form", "Free-form governed tag", []),
        policy("system.certification_status", "Platform tag", ["certified"]),
    ]
    client.metastores.summary.return_value = SimpleNamespace(
        global_metastore_id="aws:us-west-2:abc-123", metastore_id="abc-123", name="prod"
    )
    extractor = DatabricksTagsExtractor(client)
    extractor.extract()
    return extractor


#: Connector name → its offline driver, matching the declaration registry and golden filenames.
OFFLINE_EXTRACTORS: dict[str, Callable[[], Any]] = {
    "bigquery/schema": bigquery_schema,
    "jdbc/schema": jdbc_schema,
    "csv": csv,
    "databricks/tags": databricks_tags,
    "query_log": query_log,
}


def build_extractor(connector: str) -> Any:
    """Build one connector's offline extractor by name.

    Args:
        connector: A key of :data:`OFFLINE_EXTRACTORS`, e.g. ``"bigquery/schema"``.

    Returns:
        The real extractor, with its cache populated offline.
    """
    return OFFLINE_EXTRACTORS[connector]()
