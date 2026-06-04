from __future__ import annotations

from dbxcarta.core.presets import (
    Preset,
    QuestionsUploadable,
    ReadinessCheckable,
    StandardPreset,
)
from dbxcarta.spark.loader import load_preset
from dbxcarta_dense_schema_example import preset


def test_preset_is_the_shared_standard_preset() -> None:
    assert isinstance(preset, StandardPreset)


def test_preset_satisfies_protocols() -> None:
    assert isinstance(preset, Preset)
    assert isinstance(preset, ReadinessCheckable)
    assert isinstance(preset, QuestionsUploadable)


def test_preset_resolvable_via_import_path() -> None:
    assert load_preset("dbxcarta_dense_schema_example:preset") is preset


def test_preset_bundles_questions_at_example_root() -> None:
    assert preset.questions_file.name == "questions.json"
    assert preset.questions_file.parent.name == "dense-schema"
