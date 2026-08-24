"""Shared fixtures for the Neo4j schema connector unit tests."""

import pandas as pd
import pytest

from neocarta.connectors.neo4j.schema.extract import Neo4jSchemaExtractor


@pytest.fixture
def extractor_with_cache() -> Neo4jSchemaExtractor:
    """An extractor pre-seeded with the flattened APOC-shaped cache frames."""
    ext = Neo4jSchemaExtractor(source_neo4j_driver=None, source_name="dbms")
    ext._cache["database_info"] = pd.DataFrame([{"source_name": "dbms"}])
    ext._cache["schema_info"] = pd.DataFrame([{"source_name": "dbms", "database": "neo4j"}])
    ext._cache["node_info"] = pd.DataFrame([{"label": "Person"}])
    ext._cache["relationship_info"] = pd.DataFrame([{"type": "KNOWS"}])
    ext._cache["node_property_info"] = pd.DataFrame(
        [
            {
                "label": "Person",
                "property": "name",
                "type": "STRING",
                "unique": False,
                "indexed": False,
                "existence": False,
            }
        ]
    )
    ext._cache["relationship_endpoint_info"] = pd.DataFrame(
        [{"type": "KNOWS", "source_label": "Person", "target_label": "Person"}]
    )
    return ext
