"""Error-mapping tests for the Neo4j connector."""

from unittest.mock import MagicMock

import pytest
from neo4j.exceptions import AuthError as Neo4jAuthError
from neo4j.exceptions import ClientError, ServiceUnavailable

from neocarta.connectors.neo4j import Neo4jSchemaConnector
from neocarta.connectors.neo4j._errors import wrap_neo4j_errors
from neocarta.errors import AuthError, ConfigError, Neo4jConnectionError
from neocarta.warnings import Neo4jSchemaWarning


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
    source.execute_query.side_effect = ClientError("procedure not found")
    connector = Neo4jSchemaConnector(
        source_neo4j_driver=source, neo4j_driver=MagicMock(), source_name="dbms"
    )
    with pytest.raises(ConfigError):
        connector.extract()


def test_empty_schema_warns_and_writes_only_roots():
    source = MagicMock()

    def _fake_exec(**kwargs):
        if "apoc.meta.schema" in kwargs["query_"]:
            return [{"value": {}}]
        return []  # apoc.version() pre-flight

    source.execute_query.side_effect = _fake_exec
    connector = Neo4jSchemaConnector(
        source_neo4j_driver=source, neo4j_driver=MagicMock(), source_name="dbms"
    )
    with pytest.warns(Neo4jSchemaWarning):
        connector.extract()
    connector.transform()
    assert connector.transformer.database_nodes
    assert connector.transformer.node_nodes == []
