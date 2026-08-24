"""Guards that keep the Neo4j connector from ingesting the database it writes to.

The connector describes a source graph using neocarta's own graph, so writing its
output into the same database it reads would let a re-ingest re-describe neocarta's
metadata. These read-only, fail-closed guards refuse that up front: the connector
never writes into the database it reads.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from neo4j import RoutingControl

from ....enums import NodeLabel
from ....errors import ConfigError

if TYPE_CHECKING:
    import pandas as pd
    from neo4j import Driver

logger = logging.getLogger(__name__)

_SHOW_DATABASES = "SHOW DATABASES YIELD name, aliases, databaseID, currentStatus"


def _resolve_database_id(driver: Driver, database_name: str) -> str:
    """Return the online database's unique ``databaseID``, or raise ``ConfigError``.

    Reads ``SHOW DATABASES`` against the ``system`` database and matches
    ``database_name`` against each row's ``name`` or ``aliases``. Fails closed
    (``ConfigError``) when the identity cannot be established -- a missing row, a NULL
    id, a non-online database, or a query failure -- because the connector must never
    proceed on an unverifiable identity.

    Args:
        driver: The Neo4j driver whose current database to identify.
        database_name: The configured database name (or a local alias of it).

    Returns:
        The database's unique id string.
    """
    try:
        rows = driver.execute_query(
            query_=_SHOW_DATABASES,
            database_="system",
            routing_=RoutingControl.READ,
            result_transformer_=lambda r: [record.data() for record in r],
        )
    except Exception as exc:  # any failure must fail closed
        raise ConfigError(
            f"Could not read the database identity for {database_name!r} to verify the "
            "source and target are different databases.",
            suggestion="Ensure the database is online and the user can run SHOW DATABASES.",
        ) from exc

    for row in rows:
        aliases = row.get("aliases") or []
        if row.get("name") == database_name or database_name in aliases:
            if row.get("currentStatus") != "online" or not row.get("databaseID"):
                raise ConfigError(
                    f"Could not verify the identity of database {database_name!r}: it "
                    "must be online with a databaseID.",
                    suggestion="Ensure the database is online and retry.",
                )
            return row["databaseID"]

    raise ConfigError(
        f"Database {database_name!r} was not found via SHOW DATABASES.",
        suggestion="Check the database name and that the user has ACCESS to it.",
    )


def ensure_distinct_databases(
    source_driver: Driver,
    source_database: str,
    target_driver: Driver,
    target_database: str,
) -> None:
    """Refuse when source and target resolve to the same database (fail-closed).

    Compares the two databases' ``databaseID``s. Raises ``ConfigError`` when they
    match, or when either identity cannot be established (so an unverifiable identity
    never permits writing into the source). The matching id is logged at debug only.

    Args:
        source_driver: Driver for the source Neo4j.
        source_database: The source database being introspected.
        target_driver: Driver for the target neocarta graph.
        target_database: The target database being written to.
    """
    source_id = _resolve_database_id(source_driver, source_database)
    target_id = _resolve_database_id(target_driver, target_database)
    if source_id == target_id:
        logger.debug("Same-database guard tripped on databaseID %s", source_id)
        raise ConfigError(
            "Source and target are the same Neo4j database. Point the target at a "
            "separate database or instance -- the connector never writes into the "
            "database it reads.",
            suggestion="Configure a separate target database or instance.",
        )


def ensure_source_is_not_neocarta_graph(node_info: pd.DataFrame) -> None:
    """Refuse when the source already contains a neocarta graph (defense-in-depth).

    Keyed on neocarta's private ``__neocarta_graph__`` singleton. This backstops the
    identity guard and intentionally refuses cataloging a neocarta graph that lives in
    a genuinely different database -- you cannot catalog your own catalog.

    Args:
        node_info: The extracted node-label frame (``Neo4jSchemaExtractor.node_info``).
    """
    if node_info.empty or "label" not in node_info:
        return
    if NodeLabel.NEOCARTA_GRAPH.value in set(node_info["label"]):
        raise ConfigError(
            "The source database already contains a neocarta graph; it cannot be ingested.",
            suggestion="Point the connector at a source that is not itself a neocarta graph.",
        )
