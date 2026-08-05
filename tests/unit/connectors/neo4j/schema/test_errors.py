"""Error-mapping tests for the Neo4j connector."""

from unittest.mock import MagicMock

import pytest
from neo4j.exceptions import AuthError as Neo4jAuthError
from neo4j.exceptions import Forbidden, ServiceUnavailable

from neocarta.connectors.neo4j import Neo4jSchemaConnector
from neocarta.connectors.neo4j._errors import wrap_neo4j_errors
from neocarta.errors import (
    AuthError,
    ConfigError,
    ExtractionError,
    Neo4jConnectionError,
    TransformError,
)
from neocarta.warnings import Neo4jSchemaWarning


def _connector(source):
    return Neo4jSchemaConnector(
        source_neo4j_driver=source, neo4j_driver=MagicMock(), source_name="dbms"
    )


def test_service_unavailable_maps_to_connection_error():
    @wrap_neo4j_errors
    def boom():
        raise ServiceUnavailable("down")

    with pytest.raises(Neo4jConnectionError):
        boom()


def test_auth_error_maps_to_auth_error():
    @wrap_neo4j_errors
    def boom():
        raise Neo4jAuthError("nope")

    with pytest.raises(AuthError):
        boom()


def test_unrelated_exception_is_not_masked():
    @wrap_neo4j_errors
    def boom():
        raise ValueError("local bug")

    with pytest.raises(ValueError, match="local bug"):
        boom()


def test_missing_source_name_raises_config_error():
    with pytest.raises(ConfigError):
        Neo4jSchemaConnector(
            source_neo4j_driver=MagicMock(), neo4j_driver=MagicMock(), source_name=""
        )


def test_apoc_missing_raises_config_error():
    source = MagicMock()

    def _fake_exec(**kwargs):
        if "SHOW PROCEDURES" in kwargs["query_"]:
            return [{"c": 0}]  # apoc.meta.schema not registered => APOC absent
        return []

    source.execute_query.side_effect = _fake_exec
    with pytest.raises(ConfigError):
        _connector(source).extract()


def test_query_failure_maps_to_extraction_error():
    """APOC present, but a Forbidden on the schema query is an ExtractionError."""
    source = MagicMock()

    def _fake_exec(**kwargs):
        q = kwargs["query_"]
        if "SHOW PROCEDURES" in q:
            return [{"c": 1}]  # APOC present
        if "apoc.meta.schema" in q:
            raise Forbidden("insufficient privilege")
        return []

    source.execute_query.side_effect = _fake_exec
    with pytest.raises(ExtractionError):
        _connector(source).extract()


def test_missing_value_raises_transform_error():
    source = MagicMock()

    def _fake_exec(**kwargs):
        q = kwargs["query_"]
        if "SHOW PROCEDURES" in q:
            return [{"c": 1}]
        if "apoc.meta.schema" in q:
            return [{}]  # unexpected shape: no "value"
        return []

    source.execute_query.side_effect = _fake_exec
    with pytest.raises(TransformError):
        _connector(source).extract()


def test_empty_schema_warns_and_writes_only_roots():
    source = MagicMock()

    def _fake_exec(**kwargs):
        q = kwargs["query_"]
        if "SHOW PROCEDURES" in q:
            return [{"c": 1}]  # APOC present
        if "apoc.meta.schema" in q:
            return [{"value": {}}]  # empty schema
        return []

    source.execute_query.side_effect = _fake_exec
    connector = _connector(source)
    with pytest.warns(Neo4jSchemaWarning):
        connector.extract()
    connector.transform()
    assert connector.transformer.database_nodes
    assert connector.transformer.node_nodes == []
