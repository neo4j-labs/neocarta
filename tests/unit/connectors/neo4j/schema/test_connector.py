"""Unit tests for the Neo4j connector's same-database guard wiring."""

from unittest.mock import MagicMock, patch

import pytest

from neocarta.connectors.neo4j import Neo4jSchemaConnector
from neocarta.errors import ConfigError

_MOD = "neocarta.connectors.neo4j.schema.connector"


def _connector():
    return Neo4jSchemaConnector(MagicMock(), MagicMock(), source_name="dbms")


def test_guard_runs_before_reading_the_schema():
    """The distinct-database guard fires before any extractor read; fingerprint after."""
    c = _connector()
    events = []
    c.extractor.extract_database_info = MagicMock(
        side_effect=lambda *_a, **_k: events.append("db_info")
    )
    c.extractor.extract_schema = MagicMock(side_effect=lambda *_a, **_k: events.append("schema"))
    with (
        patch(
            f"{_MOD}.ensure_distinct_databases",
            side_effect=lambda *_a, **_k: events.append("guard"),
        ),
        patch(
            f"{_MOD}.ensure_source_is_not_neocarta_graph",
            side_effect=lambda *_a, **_k: events.append("fingerprint"),
        ),
    ):
        c.extract(source_database="neo4j")
    assert events == ["guard", "db_info", "schema", "fingerprint"]


def test_ingest_stops_at_guard_refusal_without_transform_or_load():
    c = _connector()
    c.transformer.build_all = MagicMock()
    c.loader.load_database_nodes = MagicMock()
    with patch(f"{_MOD}.ensure_distinct_databases", side_effect=ConfigError("same db")):
        with pytest.raises(ConfigError):
            c.ingest(source_database="neo4j")
    c.transformer.build_all.assert_not_called()
    c.loader.load_database_nodes.assert_not_called()


def test_ingest_stops_at_fingerprint_refusal_before_transform():
    c = _connector()
    c.extractor.extract_database_info = MagicMock()
    c.extractor.extract_schema = MagicMock()
    c.transformer.build_all = MagicMock()
    with (
        patch(f"{_MOD}.ensure_distinct_databases"),
        patch(
            f"{_MOD}.ensure_source_is_not_neocarta_graph",
            side_effect=ConfigError("neocarta graph"),
        ),
    ):
        with pytest.raises(ConfigError):
            c.ingest(source_database="neo4j")
    c.transformer.build_all.assert_not_called()
