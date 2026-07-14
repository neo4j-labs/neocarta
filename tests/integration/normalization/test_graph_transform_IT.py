"""Integration parity test for :class:`NormalizedGraphTransformer`.

Loads the transformer's output through the real ``Neo4jRDBMSLoader`` into a
testcontainer Neo4j and asserts the graph lands with the expected node/relationship
counts, ids and property values, that a second load is idempotent (MERGE on id),
and that no ``embedding`` property is ever written. Object-level parity with the
BigQuery transformer is covered by the unit test; this test proves the new path
persists correctly end-to-end. Uses the shared ``information_schema_table`` fixture.
"""

import pytest
from neo4j import Driver

from neocarta.connectors.utils.generate_id import generate_column_id, generate_value_id
from neocarta.data_model.normalized import InformationSchemaTable
from neocarta.ingest.rdbms import Neo4jRDBMSLoader
from neocarta.normalization.graph_transform import NormalizedGraphTransformer

DATABASE = "test-project-id"
SCHEMA = "test_dataset"
DATABASE_ID = "test_project_id"
CUSTOMER_ID = generate_column_id(DATABASE, SCHEMA, "customers", "customer_id")
ORDERS_CUSTOMER_ID = generate_column_id(DATABASE, SCHEMA, "orders", "customer_id")
VALUE_ID_1 = generate_value_id(DATABASE, SCHEMA, "customers", "customer_id", "1")
VALUE_ID_2 = generate_value_id(DATABASE, SCHEMA, "customers", "customer_id", "2")


@pytest.fixture
def transformer(
    information_schema_table: InformationSchemaTable,
) -> NormalizedGraphTransformer:
    """A transformer run over the shared fixture, ready to load."""
    transformer = NormalizedGraphTransformer()
    transformer.transform(information_schema_table)
    return transformer


def _load_all(loader: Neo4jRDBMSLoader, transformer: NormalizedGraphTransformer) -> None:
    """Load every node then relationship family through the loader."""
    loader.load_database_nodes(transformer.database_nodes)
    loader.load_schema_nodes(transformer.schema_nodes)
    loader.load_table_nodes(transformer.table_nodes)
    loader.load_column_nodes(transformer.column_nodes)
    loader.load_value_nodes(transformer.value_nodes)
    loader.load_has_schema_relationships(transformer.has_schema_relationships)
    loader.load_has_table_relationships(transformer.has_table_relationships)
    loader.load_has_column_relationships(transformer.has_column_relationships)
    loader.load_references_relationships(transformer.references_relationships)
    loader.load_has_value_relationships(transformer.has_value_relationships)


def _count(driver: Driver, query: str, **params: object) -> int:
    """Run a single-column counting query and return its integer result."""
    with driver.session(database="neo4j") as session:
        return session.run(query, **params).single()["c"]


def test_new_path_counts_ids_and_properties(
    neo4j_driver: Driver, transformer: NormalizedGraphTransformer
) -> None:
    """Loading the new path yields the expected nodes/relationships and property values."""
    _load_all(Neo4jRDBMSLoader(neo4j_driver), transformer)

    assert _count(neo4j_driver, "MATCH (n:Database) RETURN count(n) AS c") == 1
    assert _count(neo4j_driver, "MATCH (n:Schema) RETURN count(n) AS c") == 1
    assert _count(neo4j_driver, "MATCH (n:Table) RETURN count(n) AS c") == 2
    assert _count(neo4j_driver, "MATCH (n:Column) RETURN count(n) AS c") == 4
    assert _count(neo4j_driver, "MATCH (n:Value) RETURN count(n) AS c") == 2

    assert (
        _count(neo4j_driver, "MATCH (:Database)-[:HAS_SCHEMA]->(:Schema) RETURN count(*) AS c") == 1
    )
    assert _count(neo4j_driver, "MATCH (:Schema)-[:HAS_TABLE]->(:Table) RETURN count(*) AS c") == 2
    assert _count(neo4j_driver, "MATCH (:Table)-[:HAS_COLUMN]->(:Column) RETURN count(*) AS c") == 4
    assert _count(neo4j_driver, "MATCH (:Column)-[:HAS_VALUE]->(:Value) RETURN count(*) AS c") == 2

    # Exactly one REFERENCES edge; the self-referential row was dropped (two in, one out).
    assert (
        _count(neo4j_driver, "MATCH (:Column)-[:REFERENCES]->(:Column) RETURN count(*) AS c") == 1
    )

    with neo4j_driver.session(database="neo4j") as session:
        database = session.run("MATCH (n:Database {id: $id}) RETURN n", id=DATABASE_ID).single()[
            "n"
        ]
        assert database["platform"] == "GCP"
        assert database["service"] == "BIGQUERY"
        assert database["description"] is None

        column = session.run("MATCH (n:Column {id: $id}) RETURN n", id=CUSTOMER_ID).single()["n"]
        assert column["type"] == "INT64"
        assert column["nullable"] is False
        assert column["is_primary_key"] is True
        assert column["is_foreign_key"] is False

        reference = session.run(
            "MATCH (src:Column)-[r:REFERENCES]->(tgt:Column) "
            "RETURN src.id AS src, tgt.id AS tgt, r.criteria AS criteria"
        ).single()
        assert reference["src"] == ORDERS_CUSTOMER_ID
        assert reference["tgt"] == CUSTOMER_ID
        assert reference["criteria"] is None

        value_ids = {record["id"] for record in session.run("MATCH (n:Value) RETURN n.id AS id")}
        assert value_ids == {VALUE_ID_1, VALUE_ID_2}


def test_new_path_is_idempotent(
    neo4j_driver: Driver, transformer: NormalizedGraphTransformer
) -> None:
    """A second load MERGEs onto the same ids and changes nothing."""
    loader = Neo4jRDBMSLoader(neo4j_driver)
    _load_all(loader, transformer)
    assert _count(neo4j_driver, "MATCH (n) RETURN count(n) AS c") == 10
    assert _count(neo4j_driver, "MATCH ()-[r]->() RETURN count(r) AS c") == 10

    _load_all(loader, transformer)
    assert _count(neo4j_driver, "MATCH (n) RETURN count(n) AS c") == 10
    assert _count(neo4j_driver, "MATCH ()-[r]->() RETURN count(r) AS c") == 10


def test_new_path_writes_no_embedding_property(
    neo4j_driver: Driver, transformer: NormalizedGraphTransformer
) -> None:
    """No node carries an ``embedding`` property (enrichment is a separate pass)."""
    _load_all(Neo4jRDBMSLoader(neo4j_driver), transformer)
    assert _count(neo4j_driver, "MATCH (n) WHERE n.embedding IS NOT NULL RETURN count(n) AS c") == 0
