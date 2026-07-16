"""Logging behaviour for the OSI connector (instance-attr transform counts)."""

import logging
from unittest.mock import MagicMock

from neocarta.connectors.osi.connector import OsiConnector

_OSI_LOGGER = "neocarta.connectors.osi.connector"


def test_osi_transform_logs_per_type_counts(minimal_spec, caplog):
    """OsiConnector.transform() counts its instance-attr node lists, skipping empties."""
    connector = OsiConnector(neo4j_driver=MagicMock())
    # Inject the spec directly to avoid touching the filesystem / network.
    connector.extractor.spec = minimal_spec
    connector._extracted = True

    with caplog.at_level(logging.INFO, logger=_OSI_LOGGER):
        connector.transform()

    messages = [r.getMessage() for r in caplog.records if r.name == _OSI_LOGGER]
    # minimal_spec declares two datasets (orders, customers) and one semantic model.
    assert any("Transformed 2 tables" in m for m in messages)
    assert any("semantic models" in m for m in messages)
    # No SQL / spec source text leaks into the phase logging.
    assert all("SELECT" not in m for m in messages)
