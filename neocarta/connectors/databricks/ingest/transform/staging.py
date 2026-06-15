"""UC Volume path resolution and transient per-batch Delta materialization.

Everything here is pure path arithmetic or Delta/dbutils I/O — no Neo4j driver
state and no Unity Catalog metadata query. There is no whole-catalog staging
table: each (batch, label) embedding result is written to a short-lived
transient Delta path purely to invoke ai_query once (the failure-count check
and the Neo4j write both read it back), then deleted as soon as that batch is
written. The ledger root is the durable cross-run cache and is never truncated.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from neocarta.connectors.databricks._platform.identifiers import uc_volume_parent

if TYPE_CHECKING:
    from pyspark.sql import DataFrame

    from neocarta.connectors.databricks.contract import NodeLabel
    from neocarta.connectors.databricks.settings import SparkIngestSettings

logger = logging.getLogger(__name__)


def resolve_transient_root(settings: SparkIngestSettings) -> str:
    """Return the root for short-lived per-batch embedding materializations.

    This is `embedding_staging_volume` directly (validated as a /Volumes
    subpath at settings load when inline is on). Nothing durable lives here:
    each `materialize_transient` call writes one subpath and the caller deletes
    it via `delete_transient` as soon as that batch is written to Neo4j.
    """
    return settings.embedding_staging_volume.rstrip("/")


def resolve_ledger_path(settings: SparkIngestSettings) -> str:
    """Return the Delta ledger root.

    Uses `ledger_path` when set; otherwise a sibling "ledger" directory under
    the same UC volume as `embedding_staging_volume`. The ledger is never
    truncated between runs — it persists as a durable cache.
    """
    configured = settings.ledger_path.strip()
    if configured:
        return configured.rstrip("/")
    staging_root = settings.embedding_staging_volume.rstrip("/")
    return f"{uc_volume_parent(staging_root)}/ledger"


def delete_transient(path: str) -> None:
    """Delete a single transient materialization once its batch is written.

    Probe-first: check existence via `dbutils.fs.ls` and narrow-catch only on
    the probe (a missing path is fine — the batch may have had nothing to
    embed). Any failure from the destructive `rm` itself propagates as signal.
    """
    from databricks.sdk.runtime import dbutils

    # A missing path (Py4JJavaError or otherwise) is fine — the batch may have
    # had nothing to embed; any other probe failure propagates as signal.
    try:
        dbutils.fs.ls(path)
        exists = True
    except Exception as exc:
        if not _is_missing_path_error(exc):
            raise
        exists = False

    if exists:
        dbutils.fs.rm(path, recurse=True)
        logger.info("[databricks] deleted transient materialization %s", path)


def _is_missing_path_error(exc: BaseException) -> bool:
    """Return True when dbutils.fs.ls failed because the path is absent."""
    text = str(exc)
    return (
        "FileNotFoundException" in text
        or "No such file or directory" in text
        or "java.io.FileNotFoundException" in text
    )


def transient_path(transient_root: str, label: NodeLabel, batch_tag: str) -> str:
    """Compute the unique transient subpath for one (batch, label)."""
    return f"{transient_root.rstrip('/')}/{label.value.lower()}_{batch_tag}"


def materialize_transient(df: DataFrame, path: str) -> DataFrame:
    """Write df to a transient Delta `path` and read it back.

    This freezes one ai_query pass for a single batch: the failure-count check
    and the Neo4j node write both consume the returned read-back, so the
    embedding endpoint is called exactly once per item. The caller deletes
    `path` via `delete_transient` immediately after the batch is written, so
    nothing accumulates. overwriteSchema is enabled so a re-used path from an
    interrupted prior run cannot wedge on a schema diff.
    """
    (df.write.format("delta").mode("overwrite").option("overwriteSchema", "true").save(path))
    logger.info("[databricks] materialized transient batch at %s", path)
    return df.sparkSession.read.format("delta").load(path)
