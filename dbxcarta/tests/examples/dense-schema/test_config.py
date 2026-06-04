from __future__ import annotations

import pytest
from dbxcarta_dense_schema_example.config import load_config


def _base_env(**overrides: str) -> dict[str, str]:
    env = {
        "DBXCARTA_CATALOG": "dense-schema-example",
        "DATABRICKS_VOLUME_PATH": "/Volumes/dbxcarta-catalog/dense-ops/dbxcarta-ops",
    }
    env.update(overrides)
    return env


def test_load_config_defaults() -> None:
    cfg = load_config(_base_env())
    assert cfg.catalog == "dense-schema-example"


def test_load_config_rejects_project_catalog() -> None:
    with pytest.raises(ValueError, match="collides"):
        load_config(_base_env(DBXCARTA_CATALOG="graph-enriched-lakehouse"))


def test_load_config_rejects_shared_ops_catalog() -> None:
    # The data catalog must never be the shared ops catalog, or materialize
    # would write data schemas into the ops plane and collapse the separation.
    with pytest.raises(ValueError, match="collides"):
        load_config(_base_env(DBXCARTA_CATALOG="dbxcarta-catalog"))


def test_volume_path_uses_env_ops_path() -> None:
    cfg = load_config(
        _base_env(
            DATABRICKS_VOLUME_PATH="/Volumes/dbxcarta-catalog/dense-ops/dbxcarta-ops",
        )
    )
    assert cfg.volume_path == "/Volumes/dbxcarta-catalog/dense-ops/dbxcarta-ops"
    # questions_path defaults under the ops volume, not the data catalog.
    assert cfg.questions_path == (
        "/Volumes/dbxcarta-catalog/dense-ops/dbxcarta-ops/dbxcarta/dense_questions.json"
    )


def test_volume_path_requires_env_ops_path() -> None:
    # No in-catalog fallback: a missing DATABRICKS_VOLUME_PATH fails loudly
    # rather than routing the ops plane into the data-only catalog.
    env = _base_env()
    del env["DATABRICKS_VOLUME_PATH"]
    with pytest.raises(ValueError, match="DATABRICKS_VOLUME_PATH"):
        load_config(env)
