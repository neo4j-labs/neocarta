"""Integration tests for the Collibra connector (skipped without live env vars)."""

import os

import pytest

from neocarta.connectors.collibra import CollibraConnector


def _env_or_skip(var: str) -> str:
    val = os.environ.get(var)
    if not val:
        pytest.skip(f"{var} not set — skipping Collibra integration tests")
    return val


@pytest.mark.integration
def test_collibra_connector_run(neo4j_driver):
    """Run the full ETL pipeline against a real Collibra instance."""
    collibra_url = _env_or_skip("COLLIBRA_URL")
    token = os.environ.get("COLLIBRA_TOKEN")
    username = os.environ.get("COLLIBRA_USERNAME")
    password = os.environ.get("COLLIBRA_PASSWORD")

    if not token and not (username and password):
        pytest.skip("Neither COLLIBRA_TOKEN nor COLLIBRA_USERNAME/COLLIBRA_PASSWORD set")

    connector = CollibraConnector(
        collibra_url=collibra_url,
        neo4j_driver=neo4j_driver,
        token=token,
        username=username,
        password=password,
        include_lineage=False,  # lineage API path TBD on real instance
    )
    connector.run(overwrite_existing=True)

    # Basic sanity: at least some communities were ingested
    assert len(connector.extractor.community_info) > 0
    assert connector.transformer is not None
    assert len(connector.transformer.database_nodes) > 0
