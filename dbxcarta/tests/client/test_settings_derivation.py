"""Phase 5c: ClientSettings derives the ops sinks from the volume root.

These lock the guarantee Phase 6 relies on: with the summary and questions vars
absent, ClientSettings reproduces exactly what the core resolver derives, and an
explicitly supplied value still wins over derivation (behavior-neutral while the
overlays still set them).
"""

from __future__ import annotations

from dbxcarta.client.settings import ClientSettings
from dbxcarta.core.config import derive_ops_config

_VOLUME = "/Volumes/dbxcarta-catalog/finance_genie_ops/dbxcarta-ops"
_REQUIRED: dict[str, str] = {
    "dbxcarta_catalog": "finance",
    "databricks_warehouse_id": "wh-123",
    "databricks_secret_scope": "dbxcarta-neo4j-finance",
    "databricks_volume_path": _VOLUME,
}


def _make(**overrides: str) -> ClientSettings:
    return ClientSettings(_env_file=None, **{**_REQUIRED, **overrides})


def test_summary_and_questions_derived_when_unset() -> None:
    settings = _make(
        dbxcarta_summary_volume="",
        dbxcarta_summary_table="",
        dbxcarta_client_questions="",
    )
    expected = derive_ops_config(_VOLUME)

    assert settings.dbxcarta_summary_volume == expected.summary_volume
    assert settings.dbxcarta_summary_table == expected.summary_table
    assert settings.dbxcarta_client_questions == expected.client_questions


def test_explicit_values_win_over_derivation() -> None:
    settings = _make(
        dbxcarta_summary_volume="/Volumes/a/b/c/custom",
        dbxcarta_summary_table="a.b.custom",
        dbxcarta_client_questions="/Volumes/a/b/c/custom.json",
    )

    assert settings.dbxcarta_summary_volume == "/Volumes/a/b/c/custom"
    assert settings.dbxcarta_summary_table == "a.b.custom"
    assert settings.dbxcarta_client_questions == "/Volumes/a/b/c/custom.json"
