"""Integration tests for MCP server version validation against the graph metadata node."""

import asyncio
import logging
import os

from neo4j import AsyncGraphDatabase

from neocarta import __version__
from neocarta._mcp.server import _validate_graph_version

DATABASE_NAME = "neo4j"
# testcontainers Neo4j default credentials — not a real secret.
NEO4J_PASSWORD = "password"  # noqa: S105


def _run_validation() -> None:
    async def _go() -> None:
        driver = AsyncGraphDatabase.driver(os.environ["NEO4J_URI"], auth=("neo4j", NEO4J_PASSWORD))
        try:
            await _validate_graph_version(driver, DATABASE_NAME)
        finally:
            await driver.close()

    asyncio.run(_go())


def _enable_fastmcp_propagation():
    """Temporarily allow pytest's caplog to see FastMCP-namespaced loggers.

    ``fastmcp.utilities.logging`` configures its root logger with ``propagate=False``
    and its own handlers; without re-enabling propagation, log records never reach
    pytest's caplog handler.
    """
    fastmcp_logger = logging.getLogger("fastmcp")
    previous = fastmcp_logger.propagate
    fastmcp_logger.propagate = True
    return fastmcp_logger, previous


def test_validate_graph_version_warns_on_version_mismatch(neo4j_driver, caplog):
    """A graph stamped with a different version triggers a warning."""
    with neo4j_driver.session(database=DATABASE_NAME) as session:
        session.run(
            "MERGE (n:`__neocarta_graph__`) "
            "SET n.initial_version = '0.0.1', "
            "    n.latest_version = '0.0.1', "
            "    n.create_date = datetime(), "
            "    n.last_updated = datetime()"
        )

    fastmcp_logger, previous = _enable_fastmcp_propagation()
    try:
        with caplog.at_level(logging.WARNING):
            _run_validation()
    finally:
        fastmcp_logger.propagate = previous

    mismatch_msgs = [r.getMessage() for r in caplog.records if "version mismatch" in r.getMessage()]
    assert mismatch_msgs, "Expected a version mismatch warning"
    assert any("0.0.1" in m for m in mismatch_msgs)
    assert any(__version__ in m for m in mismatch_msgs)


def test_validate_graph_version_warns_when_metadata_node_missing(neo4j_driver, caplog):
    """A graph with no metadata node triggers a warning."""
    # neo4j_driver fixture already cleared the database; nothing more to do.
    fastmcp_logger, previous = _enable_fastmcp_propagation()
    try:
        with caplog.at_level(logging.WARNING):
            _run_validation()
    finally:
        fastmcp_logger.propagate = previous

    missing_msgs = [
        r.getMessage()
        for r in caplog.records
        if "__neocarta_graph__" in r.getMessage() and "No " in r.getMessage()
    ]
    assert missing_msgs, "Expected a 'no metadata node' warning"


def test_validate_graph_version_silent_on_match(neo4j_driver, caplog):
    """A graph stamped with the running version emits no metadata-related warning."""
    with neo4j_driver.session(database=DATABASE_NAME) as session:
        session.run(
            "MERGE (n:`__neocarta_graph__`) "
            "SET n.initial_version = $v, "
            "    n.latest_version = $v, "
            "    n.create_date = datetime(), "
            "    n.last_updated = datetime()",
            v=__version__,
        )

    fastmcp_logger, previous = _enable_fastmcp_propagation()
    try:
        with caplog.at_level(logging.WARNING):
            _run_validation()
    finally:
        fastmcp_logger.propagate = previous

    metadata_warnings = [
        r
        for r in caplog.records
        if r.levelno >= logging.WARNING
        and ("version mismatch" in r.getMessage() or "__neocarta_graph__" in r.getMessage())
    ]
    assert metadata_warnings == []
