from unittest.mock import MagicMock

from neo4j import RoutingControl

from neocarta.enums import NodeLabel
from neocarta.ingest.indexes import create_name_range_index
from neocarta.ingest.rdbms import Neo4jRDBMSLoader


def _mock_driver() -> MagicMock:
    """A Neo4j driver mock whose ``execute_query`` returns an unpackable summary tuple.

    ``results[0]["edition"]`` resolves to ``"community"`` so ``is_enterprise_edition`` (called
    during constraint writing) takes the community branch without raising.
    """
    driver = MagicMock()
    driver.execute_query.return_value = ({"edition": "community"}, MagicMock(), None)
    return driver


def _executed_queries(driver: MagicMock) -> list[str]:
    """Collect every ``query_`` string passed to ``execute_query``, in call order."""
    return [call.kwargs["query_"] for call in driver.execute_query.call_args_list]


def test_create_name_range_index_generates_range_index_cypher():
    driver = _mock_driver()

    create_name_range_index(driver, "Schema")

    query = driver.execute_query.call_args.kwargs["query_"]
    assert "CREATE INDEX schema_name_index IF NOT EXISTS" in query
    assert "FOR (n:Schema)" in query
    assert "ON (n.name)" in query
    # Must be a RANGE index, not full-text or vector.
    assert "FULLTEXT" not in query
    assert "VECTOR" not in query


def test_create_name_range_index_lowercases_node_label_enum():
    """A ``NodeLabel`` member yields a lowercased index name and the cased label in the pattern."""
    driver = _mock_driver()

    create_name_range_index(driver, NodeLabel.SCHEMA)

    query = driver.execute_query.call_args.kwargs["query_"]
    assert "CREATE INDEX schema_name_index IF NOT EXISTS" in query
    assert "FOR (n:Schema)" in query


def test_create_name_range_index_routes_write_to_named_db():
    driver = _mock_driver()

    create_name_range_index(driver, "Table", database_name="catalog")

    kwargs = driver.execute_query.call_args.kwargs
    assert kwargs["routing_"] == RoutingControl.WRITE
    assert kwargs["database_"] == "catalog"


def test_loader_creates_name_index_after_constraint():
    """The Schema loader emits the name range index, ordered after the id constraint."""
    driver = _mock_driver()
    loader = Neo4jRDBMSLoader(driver)

    loader.load_schema_nodes([])

    queries = _executed_queries(driver)
    constraint_idx = next(i for i, q in enumerate(queries) if "schema_id_constraint" in q)
    name_index_idx = next(i for i, q in enumerate(queries) if "schema_name_index" in q)
    assert name_index_idx > constraint_idx


def test_loader_skips_name_index_when_disabled():
    driver = _mock_driver()
    loader = Neo4jRDBMSLoader(driver)

    loader.load_schema_nodes([], create_name_index=False)

    assert all("schema_name_index" not in q for q in _executed_queries(driver))


def test_loader_does_not_create_name_index_for_value_nodes():
    """Value nodes have no ``name`` property, so no name index is created."""
    driver = _mock_driver()
    loader = Neo4jRDBMSLoader(driver)

    loader.load_value_nodes([])

    assert all("_name_index" not in q for q in _executed_queries(driver))


def test_name_range_index_defaults_to_name_property():
    driver = _mock_driver()
    create_name_range_index(driver, "Table")
    query = driver.execute_query.call_args.kwargs["query_"]
    assert "CREATE INDEX table_name_index IF NOT EXISTS" in query
    assert "ON (n.name)" in query


def test_name_range_index_accepts_property_override():
    driver = _mock_driver()
    create_name_range_index(driver, "Node", property_name="label")
    query = driver.execute_query.call_args.kwargs["query_"]
    assert "CREATE INDEX node_label_index IF NOT EXISTS" in query
    assert "ON (n.label)" in query
