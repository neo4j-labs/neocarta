"""APOC-enabled Neo4j testcontainer for the Neo4j connector integration tests.

The connector reads the source via ``apoc.meta.schema()``, so it needs APOC on the
source. This overrides the shared ``neo4j_driver`` fixture for this package only,
starting Neo4j with the APOC plugin; the shared fixture is left unchanged.
"""

import pytest
from neo4j import GraphDatabase
from testcontainers.neo4j import Neo4jContainer


@pytest.fixture(scope="session")
def _apoc_container():
    """Start one APOC-enabled Neo4j container for the neo4j integration tests."""
    container = Neo4jContainer("neo4j:5.26.23").with_env("NEO4J_PLUGINS", '["apoc"]')
    container.start()
    try:
        yield container
    finally:
        container.stop()


@pytest.fixture
def neo4j_driver(_apoc_container):
    """A driver against the APOC container, with the graph cleaned before/after."""
    driver = GraphDatabase.driver(
        _apoc_container.get_connection_url(),
        auth=(_apoc_container.username, _apoc_container.password),
    )
    with driver.session(database="neo4j") as session:
        session.run("MATCH (n) DETACH DELETE n")
    try:
        yield driver
    finally:
        with driver.session(database="neo4j") as session:
            session.run("MATCH (n) DETACH DELETE n")
        driver.close()


@pytest.fixture
def seeded_source(neo4j_driver):
    """Seed a small source graph (Person)-[:KNOWS]->(Person) with a unique constraint."""
    with neo4j_driver.session(database="neo4j") as session:
        session.run(
            "CREATE CONSTRAINT person_email IF NOT EXISTS FOR (p:Person) REQUIRE p.email IS UNIQUE"
        )
        session.run(
            "CREATE (a:Person {email:'a@x.com', name:'A'})"
            "-[:KNOWS {since:2020}]->(b:Person {email:'b@x.com', name:'B'})"
        )
    return neo4j_driver
