"""Logging behaviour for the Neo4j ingest loader (graph-pattern + merge counts)."""

import logging
from unittest.mock import MagicMock

from neocarta.data_model.schema.rdbms import Table
from neocarta.ingest.rdbms import Neo4jRDBMSLoader

_LOADER_LOGGER = "neocarta.ingest.rdbms.load"


def _mock_driver(
    *, nodes_created: int = 0, relationships_created: int = 0, properties_set: int = 0
):
    """A Neo4j driver mock returning an unpackable ``(records, summary, keys)`` tuple.

    ``records[0]["edition"]`` resolves to ``"community"`` so ``is_enterprise_edition``
    (called during constraint writing) takes the community branch without raising.
    """
    summary = MagicMock()
    summary.counters.nodes_created = nodes_created
    summary.counters.relationships_created = relationships_created
    summary.counters.properties_set = properties_set
    driver = MagicMock()
    driver.execute_query.return_value = ({"edition": "community"}, summary, None)
    return driver


def test_run_write_logs_pattern_and_counts(caplog):
    driver = _mock_driver(relationships_created=12, properties_set=3)
    loader = Neo4jRDBMSLoader(driver)
    pattern = "(:Column)-[:TAGGED_WITH]->(:BusinessTerm)"

    with caplog.at_level(logging.INFO, logger=_LOADER_LOGGER):
        loader._run_write("UNWIND $rows AS row RETURN 1", [{"id": "x"}], pattern=pattern)

    messages = [r.getMessage() for r in caplog.records if r.name == _LOADER_LOGGER]
    assert any(pattern in m and "created 12" in m for m in messages)


def test_run_write_without_pattern_is_silent(caplog):
    driver = _mock_driver()
    loader = Neo4jRDBMSLoader(driver)

    with caplog.at_level(logging.INFO, logger=_LOADER_LOGGER):
        loader._run_write("UNWIND $rows AS row RETURN 1", [{"id": "x"}])

    assert not [r for r in caplog.records if "Ingested" in r.getMessage()]


def test_load_table_nodes_logs_node_pattern(caplog):
    driver = _mock_driver(nodes_created=1, properties_set=2)
    loader = Neo4jRDBMSLoader(driver)

    with caplog.at_level(logging.INFO, logger=_LOADER_LOGGER):
        loader.load_table_nodes([Table(id="db.s.t", name="t", description="d")])

    messages = [r.getMessage() for r in caplog.records if r.name == _LOADER_LOGGER]
    assert any("(:Table)" in m and "created 1" in m for m in messages)
    # The Cypher text itself is never logged.
    assert all("MERGE" not in m for m in messages)
