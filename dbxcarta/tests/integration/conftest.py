"""Fixtures for tests/integration/.

This conftest holds the live `ws`, `neo4j_driver`, and `run_summary` fixtures
used by `test_semantic_search.py`. These tests assume a completed DBxCarta
run and live Databricks/Neo4j credentials, so local unit-test runs should not
collect them unless integration tests are explicitly requested.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import TYPE_CHECKING

import pytest
from dotenv import load_dotenv

if TYPE_CHECKING:
    from collections.abc import Iterator


@pytest.fixture(scope="session", autouse=True)
def _load_integration_env() -> None:
    """Load the repo ``.env`` for live integration tests only.

    A module-scoped ``load_dotenv`` would run at collection time and leak
    the developer's ``.env`` into the whole session's ``os.environ``, which
    pydantic ``BaseSettings`` constructors elsewhere then read as unset
    fields. Confining it to an autouse session fixture means it loads only
    when a test in this directory actually executes — never in the default
    ``-m "not live"`` unit run, where these tests are deselected.
    """
    load_dotenv(Path(__file__).parent.parent.parent / ".env")


@pytest.fixture(scope="session")
def ws(_load_integration_env: None):
    from dbxcarta.core.workspace import build_workspace_client

    return build_workspace_client()


@pytest.fixture(scope="session")
def neo4j_driver(ws) -> Iterator:
    from dbxcarta.core.workspace import read_workspace_secret
    from neo4j import GraphDatabase

    scope = os.environ["DATABRICKS_SECRET_SCOPE"]
    driver = GraphDatabase.driver(
        read_workspace_secret(ws, scope, "NEO4J_URI"),
        auth=(
            read_workspace_secret(ws, scope, "NEO4J_USERNAME"),
            read_workspace_secret(ws, scope, "NEO4J_PASSWORD"),
        ),
    )
    yield driver
    driver.close()


@pytest.fixture(scope="session")
def run_summary(ws) -> dict:
    """Load the most recent successful run-summary JSON from the UC Volume."""
    from dbxcarta.spark.ingest.summary_io import LoadSummaryError, load_summary_from_volume

    volume_path = os.environ["DBXCARTA_SUMMARY_VOLUME"]
    try:
        summary = load_summary_from_volume(ws, volume_path)
    except LoadSummaryError as e:
        pytest.skip(f"Could not load run summary: {e}")
    if summary is None:
        pytest.skip("No dbxcarta run summary found — run the job first")
    return summary
