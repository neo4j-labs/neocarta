"""Error-mapping tests for the Neo4j connector."""

import pytest
from neo4j.exceptions import AuthError as Neo4jAuthError
from neo4j.exceptions import ServiceUnavailable

from neocarta.connectors.neo4j._errors import wrap_neo4j_errors
from neocarta.errors import AuthError, Neo4jConnectionError


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
