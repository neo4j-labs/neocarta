"""Tests for the neocarta warning hierarchy."""

from neocarta.warnings import Neo4jSchemaWarning, NeocartaWarning


def test_neo4j_schema_warning_is_neocarta_warning():
    assert issubclass(Neo4jSchemaWarning, NeocartaWarning)
