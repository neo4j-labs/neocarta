"""Phase 5a: golden characterization net for the ops-config derivation.

Reads each committed ``dbxcarta-overlay.env`` and asserts the core resolver
reproduces the values that overlay spells out today, character for character.
This is the safety net the Phase 6 flip is checked against: when the derivable
vars are deleted from the overlays, ``derive_ops_config`` must still yield the
exact strings that were removed.

The drift this guards is silent: a wrong trailing slash, a missing ``/dbxcarta/``
segment, or the wrong filename would read or write the wrong location rather
than fail, so the assertions are exact-equality, not shape checks.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from dbxcarta.core.config import derive_ops_config
from dotenv import dotenv_values

_EXAMPLES_DIR = Path(__file__).resolve().parents[2] / "examples"
_OVERLAYS = ["dense-schema", "schemapile", "finance-genie"]


def _overlay(example: str) -> dict[str, str]:
    path = _EXAMPLES_DIR / example / "dbxcarta-overlay.env"
    values = {k: v for k, v in dotenv_values(path).items() if v is not None}
    assert values, f"overlay for {example} is empty or missing at {path}"
    return values


@pytest.mark.parametrize("example", _OVERLAYS)
def test_resolver_reproduces_committed_overlay(example: str) -> None:
    env = _overlay(example)
    volume_path = env["DATABRICKS_VOLUME_PATH"]
    questions_filename = env["DBXCARTA_CLIENT_QUESTIONS"].rsplit("/", 1)[-1]

    cfg = derive_ops_config(volume_path, questions_filename=questions_filename)

    assert cfg.summary_volume == env["DBXCARTA_SUMMARY_VOLUME"]
    assert cfg.summary_table == env["DBXCARTA_SUMMARY_TABLE"]
    assert cfg.client_questions == env["DBXCARTA_CLIENT_QUESTIONS"]


@pytest.mark.parametrize("example", _OVERLAYS)
def test_resolver_reproduces_teardown_schema_half(example: str) -> None:
    env = _overlay(example)
    cfg = derive_ops_config(env["DATABRICKS_VOLUME_PATH"])

    # Every overlay's teardown target carries the derivable schema half; the
    # catalog half (data catalog) is an example choice and is not derived.
    schema_part = f"schema:{cfg.teardown_schema_target}"
    assert schema_part in env["DBXCARTA_TEARDOWN_TARGET"]
