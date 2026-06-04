"""Client-settings catalog-list parsing.

These guard the fix that unblocked the ``finance-genie`` client run: the client
must accept the same ``catalog`` / ``catalog:layer`` list the pipeline does and
strip the ``:layer`` suffix identically, while single-catalog setups keep
resolving exactly as before.
"""

from __future__ import annotations

import pytest
from dbxcarta.client.settings import ClientSettings
from pydantic import ValidationError

# Required, no-default fields, so a ClientSettings can be built without reading
# a real .env. ``_env_file=None`` keeps the construction hermetic.
_BASE_SETTINGS: dict[str, str] = {
    "dbxcarta_catalog": "finance",
    "databricks_warehouse_id": "wh-123",
    "databricks_secret_scope": "dbxcarta-neo4j-finance",
    "dbxcarta_summary_volume": "/Volumes/finance/default/vol/summaries",
    "dbxcarta_summary_table": "finance.default.summary",
    "databricks_volume_path": "/Volumes/finance/default/vol",
}


def _make(**overrides: str) -> ClientSettings:
    return ClientSettings(_env_file=None, **{**_BASE_SETTINGS, **overrides})


def test_catalog_layer_list_is_accepted_and_stripped() -> None:
    # The production failure: a catalog:layer list was rejected at config load.
    settings = _make(dbxcarta_catalogs="bronze:bronze,silver:silver,gold:gold")

    assert settings.resolved_catalogs == ["bronze", "silver", "gold"]


def test_single_catalog_falls_back_when_list_blank() -> None:
    assert _make().resolved_catalogs == ["finance"]


def test_plain_multi_catalog_list_dedupes_order_preserving() -> None:
    settings = _make(dbxcarta_catalogs="bronze,gold,bronze,silver")

    assert settings.resolved_catalogs == ["bronze", "gold", "silver"]


def test_malformed_catalog_identifier_is_rejected() -> None:
    with pytest.raises(ValidationError):
        _make(dbxcarta_catalogs="1bad")


def test_max_questions_defaults_to_no_cap() -> None:
    assert _make().dbxcarta_client_max_questions == 0


def test_max_questions_parses_from_env_value() -> None:
    # Forwarded as a job-param string; pydantic coerces it to int.
    assert _make(dbxcarta_client_max_questions="5").dbxcarta_client_max_questions == 5
