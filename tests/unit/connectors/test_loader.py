from unittest.mock import MagicMock

import pytest

from neocarta import __version__
from neocarta.data_model.schema.rdbms import Database
from neocarta.errors import ConfigError
from neocarta.ingest.metadata import (
    FETCH_NEOCARTA_GRAPH_CYPHER,
    UPSERT_NEOCARTA_GRAPH_CYPHER,
    upsert_neocarta_graph_node,
)
from neocarta.ingest.utils import (
    _build_node_ingest_query,
    _build_relationship_ingest_query,
    _validate_properties_list,
)


def test_validate_properties_list_valid():
    _validate_properties_list(Database, ["name", "description", "service", "platform"])
    assert True


def test_validate_properties_list_invalid():
    with pytest.raises(ConfigError, match="invalid"):
        _validate_properties_list(Database, ["name", "description", "platform", "invalid"])


def test_build_node_ingest_query_no_overwrite():
    query = _build_node_ingest_query(
        "Database", False, ["name", "description", "service", "platform"]
    )
    assert (
        query
        == """
UNWIND $rows as row
MERGE (n:Database {id: row.id})
ON CREATE
    SET n.name = row.name,
        n.description = row.description,
        n.service = row.service,
        n.platform = row.platform"""
    )


def test_build_node_ingest_query_overwrite():
    query = _build_node_ingest_query(
        "Database", True, ["name", "description", "service", "platform"]
    )
    assert (
        query
        == """
UNWIND $rows as row
MERGE (n:Database {id: row.id})
SET n.name = row.name,
    n.description = row.description,
    n.service = row.service,
    n.platform = row.platform"""
    )


def test_build_node_ingest_query_no_properties():
    query = _build_node_ingest_query("Database", False, [])
    assert (
        query
        == """
UNWIND $rows as row
MERGE (n:Database {id: row.id})"""
    )


def test_build_node_ingest_query_overwrite_one_property():
    query = _build_node_ingest_query("Database", True, ["name"])
    assert (
        query
        == """
UNWIND $rows as row
MERGE (n:Database {id: row.id})
SET n.name = row.name"""
    )


def test_build_relationship_ingest_query_no_overwrite():
    query = _build_relationship_ingest_query(
        "HAS_SCHEMA",
        "Database",
        "Schema",
        "database_id",
        "schema_id",
        False,
        ["name", "description"],
    )
    assert (
        query
        == """
UNWIND $rows as row
MATCH (n1:Database {id: row.database_id})
MATCH (n2:Schema {id: row.schema_id})
MERGE (n1)-[r:HAS_SCHEMA]->(n2)
ON CREATE
    SET r.name = row.name,
        r.description = row.description"""
    )


def test_build_relationship_ingest_query_overwrite():
    query = _build_relationship_ingest_query(
        "HAS_SCHEMA",
        "Database",
        "Schema",
        "database_id",
        "schema_id",
        True,
        ["name", "description"],
    )
    assert (
        query
        == """
UNWIND $rows as row
MATCH (n1:Database {id: row.database_id})
MATCH (n2:Schema {id: row.schema_id})
MERGE (n1)-[r:HAS_SCHEMA]->(n2)
SET r.name = row.name,
    r.description = row.description"""
    )


def test_build_relationship_ingest_query_no_properties():
    query = _build_relationship_ingest_query(
        "HAS_SCHEMA", "Database", "Schema", "database_id", "schema_id", False, []
    )
    assert (
        query
        == """
UNWIND $rows as row
MATCH (n1:Database {id: row.database_id})
MATCH (n2:Schema {id: row.schema_id})
MERGE (n1)-[r:HAS_SCHEMA]->(n2)"""
    )


def test_neocarta_graph_cypher_uses_singleton_label():
    """Both upsert and fetch queries target the literal `__neocarta_graph__` label."""
    assert "`__neocarta_graph__`" in UPSERT_NEOCARTA_GRAPH_CYPHER
    assert "`__neocarta_graph__`" in FETCH_NEOCARTA_GRAPH_CYPHER
    # The upsert is a singleton MERGE — no id property in the pattern.
    assert "MERGE (n:`__neocarta_graph__`)" in UPSERT_NEOCARTA_GRAPH_CYPHER
    assert "ON CREATE" in UPSERT_NEOCARTA_GRAPH_CYPHER
    assert "ON MATCH" in UPSERT_NEOCARTA_GRAPH_CYPHER


def test_upsert_neocarta_graph_node_defaults_to_installed_version():
    """When ``version`` is omitted, the installed neocarta version is sent to Neo4j."""
    driver = MagicMock()
    create_date = MagicMock()
    create_date.to_native.return_value = "2026-05-20T00:00:00+00:00"
    last_updated = MagicMock()
    last_updated.to_native.return_value = "2026-05-20T00:00:00+00:00"
    driver.execute_query.return_value = (
        [
            {
                "initial_version": __version__,
                "latest_version": __version__,
                "create_date": create_date,
                "last_updated": last_updated,
            }
        ],
        None,
        None,
    )

    upsert_neocarta_graph_node(neo4j_driver=driver, database_name="neo4j")

    call_kwargs = driver.execute_query.call_args.kwargs
    assert call_kwargs["parameters_"] == {"version": __version__}
    assert call_kwargs["database_"] == "neo4j"


def test_upsert_neocarta_graph_node_accepts_version_override():
    """An explicit ``version`` is forwarded to the Cypher parameters."""
    driver = MagicMock()
    create_date = MagicMock()
    create_date.to_native.return_value = "2026-05-20T00:00:00+00:00"
    last_updated = MagicMock()
    last_updated.to_native.return_value = "2026-05-20T00:00:00+00:00"
    driver.execute_query.return_value = (
        [
            {
                "initial_version": "9.9.9",
                "latest_version": "9.9.9",
                "create_date": create_date,
                "last_updated": last_updated,
            }
        ],
        None,
        None,
    )

    upsert_neocarta_graph_node(neo4j_driver=driver, version="9.9.9")

    call_kwargs = driver.execute_query.call_args.kwargs
    assert call_kwargs["parameters_"] == {"version": "9.9.9"}
