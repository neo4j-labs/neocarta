"""Shared Neo4j credential helper for client modules."""

from __future__ import annotations

import logging
import os
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from dbxcarta.client.settings import ClientSettings

logger = logging.getLogger(__name__)


def neo4j_credentials(settings: ClientSettings) -> tuple[str, str, str]:
    """Return (uri, username, password) from secret scope or env vars."""
    try:
        from databricks.sdk.runtime import dbutils

        scope = settings.databricks_secret_scope
        return (
            dbutils.secrets.get(scope=scope, key="NEO4J_URI"),
            dbutils.secrets.get(scope=scope, key="NEO4J_USERNAME"),
            dbutils.secrets.get(scope=scope, key="NEO4J_PASSWORD"),
        )
    except Exception as exc:
        # Best-effort resolver: databricks-sdk always ships RemoteDbUtils, so
        # the import succeeds off-cluster but secrets.get() then fails (no
        # workspace / scope / auth). ANY failure to read the secret scope must
        # fall back to env vars — this is the local / non-Databricks path, so
        # a broad catch is deliberate here.
        logger.debug(
            "Neo4j secret-scope lookup failed (%s); falling back to environment",
            exc,
        )
        return (
            os.environ["NEO4J_URI"],
            os.environ["NEO4J_USERNAME"],
            os.environ["NEO4J_PASSWORD"],
        )
