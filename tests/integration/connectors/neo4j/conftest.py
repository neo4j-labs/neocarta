"""APOC-enabled source + plain target Neo4j testcontainers for the connector IT.

The connector reads the source via ``apoc.meta.schema()`` (APOC required on the source)
and writes the neocarta graph to a SEPARATE target -- the same-database guard refuses
ingesting into the source database. Each driver is wiped of nodes, constraints, and
indexes between tests so the loader's schema objects don't leak across tests.
"""

import contextlib

import pytest
from neo4j import GraphDatabase
from testcontainers.neo4j import Neo4jContainer


def _wipe(driver):
    """Clear nodes, constraints, and non-lookup indexes from the driver's database."""
    with driver.session(database="neo4j") as session:
        session.run("MATCH (n) DETACH DELETE n")
        for row in session.run("SHOW CONSTRAINTS YIELD name").data():
            with contextlib.suppress(Exception):
                session.run(f"DROP CONSTRAINT `{row['name']}` IF EXISTS")
        for row in session.run("SHOW INDEXES YIELD name, type").data():
            if row.get("type") == "LOOKUP":
                continue  # built-in token-lookup indexes cannot be dropped
            with contextlib.suppress(Exception):
                session.run(f"DROP INDEX `{row['name']}` IF EXISTS")


@pytest.fixture(scope="session")
def _apoc_container():
    """Start one APOC-enabled Neo4j container (the source)."""
    container = Neo4jContainer("neo4j:5.26.23").with_env("NEO4J_PLUGINS", '["apoc"]')
    container.start()
    try:
        yield container
    finally:
        container.stop()


@pytest.fixture(scope="session")
def _target_container():
    """Start one plain Neo4j container (the target neocarta graph; no APOC needed)."""
    container = Neo4jContainer("neo4j:5.26.23")
    container.start()
    try:
        yield container
    finally:
        container.stop()


@pytest.fixture
def neo4j_driver(_apoc_container):
    """A source driver against the APOC container, wiped before/after."""
    driver = GraphDatabase.driver(
        _apoc_container.get_connection_url(),
        auth=(_apoc_container.username, _apoc_container.password),
    )
    _wipe(driver)
    try:
        yield driver
    finally:
        _wipe(driver)
        driver.close()


@pytest.fixture
def target_driver(_target_container):
    """A target driver against a separate container, wiped before/after."""
    driver = GraphDatabase.driver(
        _target_container.get_connection_url(),
        auth=(_target_container.username, _target_container.password),
    )
    _wipe(driver)
    try:
        yield driver
    finally:
        _wipe(driver)
        driver.close()


@pytest.fixture
def seeded_source(neo4j_driver):
    """Seed a small source graph: (Person)-[:KNOWS]->(Person) plus a legit :Database node.

    The ``:Database`` node deliberately reuses a name from neocarta's own vocabulary -- it
    must be ingested faithfully now that the reserved-vocabulary filtering is gone.
    """
    with neo4j_driver.session(database="neo4j") as session:
        session.run(
            "CREATE CONSTRAINT person_email IF NOT EXISTS FOR (p:Person) REQUIRE p.email IS UNIQUE"
        )
        session.run(
            "CREATE (a:Person {email:'a@x.com', name:'A'})"
            "-[:KNOWS {since:2020}]->(b:Person {email:'b@x.com', name:'B'})"
        )
        session.run("CREATE (:Database {name:'legacy'})")
    return neo4j_driver
