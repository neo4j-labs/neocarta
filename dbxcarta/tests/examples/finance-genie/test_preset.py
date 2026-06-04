from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from dbxcarta.core.presets import (
    Preset,
    QuestionsUploadable,
    ReadinessCheckable,
    StandardPreset,
)
from dbxcarta.spark.loader import load_preset
from dbxcarta.spark.settings import SparkIngestSettings
from dbxcarta_finance_genie_example import preset
from dotenv import dotenv_values

if TYPE_CHECKING:
    import pytest

# The committed overlay is the single source of per-example dbxcarta config.
_OVERLAY = (
    Path(__file__).resolve().parents[3] / "examples" / "finance-genie" / "dbxcarta-overlay.env"
)


def test_preset_is_the_shared_standard_preset() -> None:
    assert isinstance(preset, StandardPreset)


def test_preset_satisfies_protocols() -> None:
    assert isinstance(preset, Preset)
    assert isinstance(preset, ReadinessCheckable)
    assert isinstance(preset, QuestionsUploadable)


def test_preset_resolvable_via_import_path() -> None:
    assert load_preset("dbxcarta_finance_genie_example:preset") is preset


def test_preset_bundles_questions_at_example_root() -> None:
    assert preset.questions_file.name == "questions.json"
    assert preset.questions_file.parent.name == "finance-genie"


def test_overlay_builds_valid_settings(monkeypatch: pytest.MonkeyPatch) -> None:
    for key, value in dotenv_values(_OVERLAY).items():
        if value is not None:
            monkeypatch.setenv(key, value)
    settings = SparkIngestSettings()
    assert settings.databricks_secret_scope == "dbxcarta-neo4j-finance-genie"
    assert settings.dbxcarta_catalog == "graph-enriched-finance-silver"
    assert settings.dbxcarta_schemas == "graph-enriched-schema"
    # The layer rides on the DBXCARTA_CATALOGS entries; resolved_catalogs()
    # strips the suffix and layer_map() reads it from the same list.
    assert settings.resolved_catalogs() == [
        "graph-enriched-finance-silver",
        "graph-enriched-finance-gold",
    ]
    assert settings.layer_map() == {
        "graph-enriched-finance-silver": "silver",
        "graph-enriched-finance-gold": "gold",
    }


def test_overlay_pins_known_keys() -> None:
    env = dotenv_values(_OVERLAY)
    assert env["DBXCARTA_INJECT_CRITERIA"] == "false"
    assert env["DBXCARTA_CLIENT_ARMS"] == "no_context,schema_dump,graph_rag"
    assert env["DBXCARTA_CLIENT_QUESTIONS"].endswith("/dbxcarta/questions.json")
    # The layer is folded into DBXCARTA_CATALOGS; the separate map is gone.
    assert "DBXCARTA_LAYER_MAP" not in env
    assert env["DBXCARTA_CATALOGS"] == (
        "graph-enriched-finance-silver:silver,graph-enriched-finance-gold:gold"
    )
