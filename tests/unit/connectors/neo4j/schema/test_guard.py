"""Unit tests for the Neo4j connector's same-database guard."""

from unittest.mock import MagicMock

import pandas as pd
import pytest

from neocarta.connectors.neo4j.schema._guard import (
    _SHOW_DATABASES,
    _resolve_database_id,
    ensure_distinct_databases,
    ensure_source_is_not_neocarta_graph,
)
from neocarta.errors import ConfigError


def _driver_returning(rows):
    driver = MagicMock()
    driver.execute_query.return_value = rows  # guard uses result_transformer_ -> list
    return driver


def _row(name="neo4j", aliases=(), db_id="AAA", status="online"):
    return {"name": name, "aliases": list(aliases), "databaseID": db_id, "currentStatus": status}


def _driver_with_id(db_id):
    return _driver_returning([_row(db_id=db_id)])


# --- _resolve_database_id ---


def test_resolve_returns_id_for_matching_online_db():
    assert _resolve_database_id(_driver_returning([_row()]), "neo4j") == "AAA"


def test_resolve_queries_system_with_show_databases():
    driver = _driver_returning([_row()])
    _resolve_database_id(driver, "neo4j")
    kwargs = driver.execute_query.call_args.kwargs
    assert kwargs["query_"] == _SHOW_DATABASES
    assert kwargs["database_"] == "system"


def test_resolve_matches_on_alias():
    assert _resolve_database_id(_driver_returning([_row(aliases=["catalog"])]), "catalog") == "AAA"


def test_resolve_tolerates_null_aliases():
    driver = _driver_returning(
        [{"name": "neo4j", "aliases": None, "databaseID": "AAA", "currentStatus": "online"}]
    )
    assert _resolve_database_id(driver, "neo4j") == "AAA"


def test_resolve_matches_when_not_first_row():
    driver = _driver_returning([_row(name="system", db_id="SYS"), _row(db_id="AAA")])
    assert _resolve_database_id(driver, "neo4j") == "AAA"


def test_resolve_fails_closed_when_missing():
    with pytest.raises(ConfigError, match="not found"):
        _resolve_database_id(_driver_returning([_row(name="other")]), "neo4j")


def test_resolve_fails_closed_when_online_but_null_id():
    with pytest.raises(ConfigError, match="verify the identity"):
        _resolve_database_id(_driver_returning([_row(db_id=None, status="online")]), "neo4j")


def test_resolve_fails_closed_when_offline_with_id():
    with pytest.raises(ConfigError, match="verify the identity"):
        _resolve_database_id(_driver_returning([_row(status="offline")]), "neo4j")


def test_resolve_fails_closed_on_query_error():
    driver = MagicMock()
    driver.execute_query.side_effect = RuntimeError("boom")
    with pytest.raises(ConfigError, match="Could not read the database identity"):
        _resolve_database_id(driver, "neo4j")


# --- ensure_distinct_databases ---


def test_distinct_passes_for_different_ids():
    ensure_distinct_databases(_driver_with_id("AAA"), "neo4j", _driver_with_id("BBB"), "neo4j")


def test_distinct_refuses_same_id():
    with pytest.raises(ConfigError, match="same Neo4j database"):
        ensure_distinct_databases(_driver_with_id("AAA"), "neo4j", _driver_with_id("AAA"), "neo4j")


def test_distinct_fails_closed_when_source_identity_unresolved():
    bad = MagicMock()
    bad.execute_query.side_effect = RuntimeError("boom")
    with pytest.raises(ConfigError):
        ensure_distinct_databases(bad, "neo4j", _driver_with_id("BBB"), "neo4j")


def test_distinct_fails_closed_when_target_identity_unresolved():
    bad = MagicMock()
    bad.execute_query.side_effect = RuntimeError("boom")
    with pytest.raises(ConfigError):
        ensure_distinct_databases(_driver_with_id("AAA"), "neo4j", bad, "neo4j")


# --- ensure_source_is_not_neocarta_graph ---


def test_fingerprint_refuses_when_neocarta_graph_present():
    node_info = pd.DataFrame([{"label": "Person"}, {"label": "__neocarta_graph__"}])
    with pytest.raises(ConfigError, match="already contains a neocarta graph"):
        ensure_source_is_not_neocarta_graph(node_info)


def test_fingerprint_passes_for_genuine_source():
    node_info = pd.DataFrame([{"label": "Person"}, {"label": "Database"}])
    ensure_source_is_not_neocarta_graph(node_info)  # legit :Database label is fine


def test_fingerprint_passes_for_empty_frame():
    ensure_source_is_not_neocarta_graph(pd.DataFrame())
