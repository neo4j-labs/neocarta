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

import warnings
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pyspark.sql import SparkSession

    from neocarta.connectors.databricks.ingest.summary import RunSummary
    from neocarta.connectors.databricks.settings import SparkIngestSettings

_EXTRA_HINT = (
    "The Databricks connector requires Spark. "
    "Install the optional dependencies with: pip install neocarta[databricks-spark]"
)

_STAGE_HINT = (
    "The Databricks connector runs as a single Spark job and does not expose "
    "separate extract/transform/load stages; call ingest() to run the pipeline."
)


class DatabricksSparkSchemaConnector:
    """Ingest Unity Catalog schema facts into Neo4j via a Spark job.

    Parameters
    ----------
    settings : SparkIngestSettings, optional
        Ingest configuration. When omitted, settings are loaded from the
        environment (the ``NEOCARTA_DATABRICKS_*`` variables) at :meth:`ingest` time.
    neo4j_uri, neo4j_username, neo4j_password : str, optional
        Neo4j connection details. When all three are supplied they take
        precedence; otherwise ``ingest`` falls back to ``NEO4J_*`` process env, and
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
        """Store ingest settings and optional explicit Neo4j credentials.

        Both are resolved lazily at run time, so construction never imports
        Spark or touches the environment. See the class docstring for how the
        ``settings`` and ``neo4j_*`` arguments are resolved.
        """
        self._settings = settings
        self._neo4j_creds = (neo4j_uri, neo4j_username, neo4j_password)

    def extract(self, *args: object, **kwargs: object) -> None:
        """Not a separate stage for this connector — see :meth:`ingest`.

        The in-process connectors (BigQuery, CSV, Dataplex) read into an
        extractor cache, transform it, then load. This connector instead runs a
        single Spark job that streams catalog metadata straight to Neo4j, so the
        extract/transform/load stages are not individually addressable. Call
        :meth:`ingest` to run the whole pipeline.
        """
        raise NotImplementedError(_STAGE_HINT)

    def transform(self, *args: object, **kwargs: object) -> None:
        """Not a separate stage for this connector — see :meth:`ingest`.

        See :meth:`extract` for why the stages are not individually addressable.
        """
        raise NotImplementedError(_STAGE_HINT)

    def load(self, *args: object, **kwargs: object) -> None:
        """Not a separate stage for this connector — see :meth:`ingest`.

        See :meth:`extract` for why the stages are not individually addressable.
        """
        raise NotImplementedError(_STAGE_HINT)

    def ingest(self, spark: SparkSession | None = None) -> RunSummary:
        """Run the schema ingest and return the finished ``RunSummary``.

        This is the connector's entrypoint. It runs the Spark job that reads
        Unity Catalog metadata and writes the schema graph to Neo4j in one pass.

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

    def run(self, spark: SparkSession | None = None) -> RunSummary:
        """Run the schema ingest and return the finished ``RunSummary``.

        .. deprecated::
            Use :meth:`ingest` instead. ``run`` will be removed in a future
            release.
        """
        warnings.warn(
            "DatabricksSparkSchemaConnector.run() is deprecated; "
            "use DatabricksSparkSchemaConnector.ingest() instead.",
            DeprecationWarning,
            stacklevel=2,
        )
        return self.ingest(spark)

    @staticmethod
    def _lazy_imports() -> tuple[object, object, object]:
        """Import the Spark-dependent entry points, mapping a missing optional
        dependency to a clear, actionable ``ImportError``.
        """
        try:
            import pyspark.sql  # noqa: F401 — presence probe for the optional extra

            from neocarta.connectors.databricks.ingest.load.neo4j_io import Neo4jConfig
            from neocarta.connectors.databricks.run import run_ingest
            from neocarta.connectors.databricks.settings import SparkIngestSettings
        except ModuleNotFoundError as exc:  # pragma: no cover - import guard
            raise ImportError(_EXTRA_HINT) from exc
        return run_ingest, Neo4jConfig, SparkIngestSettings
