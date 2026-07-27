"""Fixtures for Salesforce connector integration tests.

All sobject data is entirely synthetic — no real org names, credentials, or
proprietary field/object definitions are included.

When NEO4J_URI is set in the environment (or a .env file is present), the
``neo4j_driver`` fixture uses that real instance instead of testcontainers,
so Docker is not required.  Cleanup always runs against the ``neo4j`` default
database — the production database is never touched.
"""

import os
from pathlib import Path

import pytest
from dotenv import load_dotenv
from neo4j import GraphDatabase

# Load credentials from .env if present (checked up to 4 levels up).
for _candidate in [Path(__file__).parents[i] / ".env" for i in range(5)]:
    if _candidate.exists():
        load_dotenv(_candidate)
        break

ORG_NAME = "integration-test-org"
_TEST_DB = "neo4j"  # always use the default DB for tests — never the production one


@pytest.fixture(scope="module")
def neo4j_driver():
    """
    Provide a Neo4j driver for integration tests.

    Uses the real instance from NEO4J_URI / NEO4J_USERNAME / NEO4J_PASSWORD
    environment variables when available; otherwise falls back to testcontainers.
    Cleanup runs against the ``neo4j`` default database.
    """
    uri = os.environ.get("NEO4J_URI")
    user = os.environ.get("NEO4J_USERNAME", "neo4j")
    password = os.environ.get("NEO4J_PASSWORD", "neo4j")

    if uri:
        driver = GraphDatabase.driver(uri, auth=(user, password))
        driver.verify_connectivity()
        # Clean up before the module runs.
        with driver.session(database=_TEST_DB) as s:
            s.run("MATCH (n) DETACH DELETE n")
        try:
            yield driver
        finally:
            with driver.session(database=_TEST_DB) as s:
                s.run("MATCH (n) DETACH DELETE n")
            driver.close()
    else:
        # Fall back to testcontainers when no real instance is configured.
        from testcontainers.neo4j import Neo4jContainer

        container = Neo4jContainer("neo4j:5.26.23")
        container.start()
        driver = GraphDatabase.driver(
            container.get_connection_url(),
            auth=(container.username, container.password),
        )
        with driver.session(database=_TEST_DB) as s:
            s.run("MATCH (n) DETACH DELETE n")
        try:
            yield driver
        finally:
            with driver.session(database=_TEST_DB) as s:
                s.run("MATCH (n) DETACH DELETE n")
            driver.close()
            container.stop()


@pytest.fixture
def sample_objects():
    """Four synthetic Salesforce objects covering standard, managed, and custom."""
    return [
        {
            "name": "Account",
            "label": "Account",
            "labelPlural": "Accounts",
            "keyPrefix": "001",
            "custom": False,
            "queryable": True,
            "createable": True,
            "updateable": True,
            "deletable": False,
            "fields": [
                {
                    "name": "Id",
                    "label": "Account ID",
                    "type": "id",
                    "length": 18,
                    "precision": 0,
                    "scale": 0,
                    "nillable": False,
                    "unique": False,
                    "idLookup": True,
                    "referenceTo": [],
                    "picklistValues": [],
                },
                {
                    "name": "Name",
                    "label": "Account Name",
                    "type": "string",
                    "length": 255,
                    "precision": 0,
                    "scale": 0,
                    "nillable": False,
                    "unique": False,
                    "idLookup": False,
                    "referenceTo": [],
                    "picklistValues": [],
                },
                {
                    "name": "Type",
                    "label": "Account Type",
                    "type": "picklist",
                    "length": 40,
                    "precision": 0,
                    "scale": 0,
                    "nillable": True,
                    "unique": False,
                    "idLookup": False,
                    "referenceTo": [],
                    "picklistValues": [
                        {"value": "Customer", "active": True},
                        {"value": "Partner", "active": True},
                    ],
                },
            ],
        },
        {
            "name": "Contact",
            "label": "Contact",
            "labelPlural": "Contacts",
            "keyPrefix": "003",
            "custom": False,
            "queryable": True,
            "createable": True,
            "updateable": True,
            "deletable": True,
            "fields": [
                {
                    "name": "Id",
                    "label": "Contact ID",
                    "type": "id",
                    "length": 18,
                    "precision": 0,
                    "scale": 0,
                    "nillable": False,
                    "unique": False,
                    "idLookup": True,
                    "referenceTo": [],
                    "picklistValues": [],
                },
                {
                    "name": "AccountId",
                    "label": "Account ID",
                    "type": "reference",
                    "length": 18,
                    "precision": 0,
                    "scale": 0,
                    "nillable": True,
                    "unique": False,
                    "idLookup": False,
                    "referenceTo": ["Account"],
                    "picklistValues": [],
                },
                {
                    "name": "OwnerId",
                    "label": "Owner ID",
                    "type": "reference",
                    "length": 18,
                    "precision": 0,
                    "scale": 0,
                    "nillable": False,
                    "unique": False,
                    "idLookup": False,
                    "referenceTo": ["User"],  # system object — not in described set
                    "picklistValues": [],
                },
            ],
        },
        {
            "name": "Acme__Widget__c",
            "label": "Widget",
            "labelPlural": "Widgets",
            "keyPrefix": "a0B",
            "custom": True,
            "queryable": True,
            "createable": True,
            "updateable": True,
            "deletable": True,
            "fields": [
                {
                    "name": "Id",
                    "label": "Record ID",
                    "type": "id",
                    "length": 18,
                    "precision": 0,
                    "scale": 0,
                    "nillable": False,
                    "unique": False,
                    "idLookup": True,
                    "referenceTo": [],
                    "picklistValues": [],
                },
            ],
        },
    ]
