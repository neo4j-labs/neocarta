"""Phase 5b: unit tests for the core ops-config resolver.

These pin the derivation rule itself with explicit inputs and outputs. The
committed-overlay characterization net lives in ``test_ops_config_golden.py``.
"""

from __future__ import annotations

import pytest
from dbxcarta.core.config import (
    DEFAULT_BLUEPRINT_FILENAME,
    DEFAULT_QUESTIONS_FILENAME,
    derive_ops_config,
)


def test_derives_all_values_from_one_base() -> None:
    cfg = derive_ops_config("/Volumes/dbxcarta-catalog/dense-ops/dbxcarta-ops")

    assert cfg.summary_volume == ("/Volumes/dbxcarta-catalog/dense-ops/dbxcarta-ops/dbxcarta/runs")
    assert cfg.summary_table == "dbxcarta-catalog.dense-ops.dbxcarta_run_summary"
    assert cfg.client_questions == (
        "/Volumes/dbxcarta-catalog/dense-ops/dbxcarta-ops/dbxcarta/questions.json"
    )
    assert cfg.blueprint_volume == (
        "/Volumes/dbxcarta-catalog/dense-ops/dbxcarta-ops/dbxcarta/blueprint/blueprint.json"
    )
    assert cfg.teardown_schema_target == "dbxcarta-catalog.dense-ops"


def test_blueprint_filename_is_an_example_choice() -> None:
    cfg = derive_ops_config(
        "/Volumes/dbxcarta-catalog/dense-ops/dbxcarta-ops",
        blueprint_filename="candidates_500.json",
    )

    assert cfg.blueprint_volume == (
        "/Volumes/dbxcarta-catalog/dense-ops/dbxcarta-ops/dbxcarta/blueprint/candidates_500.json"
    )
    # The blueprint filename rides only on the blueprint path.
    assert cfg.client_questions.endswith("/dbxcarta/questions.json")


def test_default_blueprint_filename() -> None:
    assert DEFAULT_BLUEPRINT_FILENAME == "blueprint.json"


def test_questions_filename_is_an_example_choice() -> None:
    cfg = derive_ops_config(
        "/Volumes/dbxcarta-catalog/dense-ops/dbxcarta-ops",
        questions_filename="dense_questions.json",
    )

    assert cfg.client_questions == (
        "/Volumes/dbxcarta-catalog/dense-ops/dbxcarta-ops/dbxcarta/dense_questions.json"
    )
    # Only the questions path carries the example-specific filename.
    assert cfg.summary_volume.endswith("/dbxcarta/runs")


def test_default_questions_filename() -> None:
    assert DEFAULT_QUESTIONS_FILENAME == "questions.json"
    cfg = derive_ops_config("/Volumes/c/s/v")
    assert cfg.client_questions == "/Volumes/c/s/v/dbxcarta/questions.json"


def test_trailing_slash_on_base_does_not_double_up() -> None:
    cfg = derive_ops_config("/Volumes/c/s/v/")

    assert cfg.summary_volume == "/Volumes/c/s/v/dbxcarta/runs"
    assert cfg.client_questions == "/Volumes/c/s/v/dbxcarta/questions.json"


def test_malformed_base_fails_loudly() -> None:
    with pytest.raises(ValueError, match="/Volumes/<catalog>/<schema>/<volume>"):
        derive_ops_config("/Volumes/only/two")
