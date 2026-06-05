"""Databricks Unity Catalog schema connector (Spark-based).

Unlike the in-process connectors (BigQuery, CSV, Dataplex), this connector
executes a **Spark job** and writes to Neo4j via the Neo4j Spark Connector — it
does not use ``Neo4jRDBMSLoader``. It can run against a local or Spark Connect
session, or on a Databricks cluster (where Neo4j credentials are read from the
Databricks secret scope). Embeddings and inferred foreign keys are produced
afterward by neocarta's enrichment layer; this connector ingests catalog facts
(schema, declared foreign keys, sampled values).

Requires the optional Spark dependencies::

    pip install neocarta[databricks-spark]
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pyspark.sql import SparkSession

    from neocarta.connectors.databricks.ingest.summary import RunSummary
    from neocarta.connectors.databricks.settings import SparkIngestSettings

_EXTRA_HINT = (
    "The Databricks connector requires Spark. "
    "Install the optional dependencies with: pip install neocarta[databricks-spark]"
)


class DatabricksSparkSchemaConnector:
    """Ingest Unity Catalog schema facts into Neo4j via a Spark job.

    Parameters
    ----------
    settings : SparkIngestSettings, optional
        Ingest configuration. When omitted, settings are loaded from the
        environment (the ``NEOCARTA_DATABRICKS_*`` variables) at :meth:`run` time.
    neo4j_uri, neo4j_username, neo4j_password : str, optional
        Neo4j connection details. When all three are supplied they take
        precedence; otherwise ``run`` falls back to ``NEO4J_*`` process env, and
        finally to the Databricks secret scope (on-cluster jobs).

    Notes:
    -----
    This connector executes a Spark job and writes via the Neo4j Spark
    Connector. Its execution model differs from the in-process connectors: it
    needs a Spark session (local, Spark Connect, or a Databricks cluster) and
    the ``databricks-spark`` optional dependencies.
    """

    def __init__(
        self,
        settings: SparkIngestSettings | None = None,
        *,
        neo4j_uri: str | None = None,
        neo4j_username: str | None = None,
        neo4j_password: str | None = None,
    ) -> None:
        self._settings = settings
        self._neo4j_creds = (neo4j_uri, neo4j_username, neo4j_password)

    def run(self, spark: SparkSession | None = None) -> RunSummary:
        """Run the schema ingest and return the finished ``RunSummary``.

        Parameters
        ----------
        spark : SparkSession, optional
            The Spark session to run against. When omitted, the active session
            is resolved lazily (the Databricks cluster entrypoint).

        Raises:
        ------
        ImportError
            If the ``databricks-spark`` optional dependencies are not installed.
        """
        run_ingest, neo4j_config_cls, settings_cls = self._lazy_imports()
        settings = self._settings if self._settings is not None else settings_cls()
        neo4j = None
        uri, username, password = self._neo4j_creds
        if uri and username and password:
            neo4j = neo4j_config_cls(
                uri=uri,
                username=username,
                password=password,
                batch_size=settings.neo4j_batch_size,
            )
        return run_ingest(settings=settings, spark=spark, neo4j=neo4j)

    @staticmethod
    def _lazy_imports() -> tuple[object, object, object]:
        """Import the Spark-dependent entry points, mapping a missing optional
        dependency to a clear, actionable ``ImportError``.
        """
        try:
            import pyspark.sql  # noqa: F401 — presence probe for the optional extra

            from neocarta.connectors.databricks.ingest.load.writer import Neo4jConfig
            from neocarta.connectors.databricks.run import run_ingest
            from neocarta.connectors.databricks.settings import SparkIngestSettings
        except ModuleNotFoundError as exc:  # pragma: no cover - import guard
            raise ImportError(_EXTRA_HINT) from exc
        return run_ingest, Neo4jConfig, SparkIngestSettings
