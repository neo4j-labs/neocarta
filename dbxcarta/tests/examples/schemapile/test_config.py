from __future__ import annotations

import pytest
from dbxcarta_schemapile_example.config import load_config


def _base_env(tmp_path, **overrides):
    env = {
        "SCHEMAPILE_REPO": str(tmp_path),
        "DBXCARTA_CATALOG": "schemapile_lakehouse",
        "DATABRICKS_VOLUME_PATH": "/Volumes/dbxcarta-catalog/schemapile_ops/dbxcarta-ops",
    }
    env.update(overrides)
    return env


def test_load_config_defaults(tmp_path):
    cfg = load_config(_base_env(tmp_path))
    assert cfg.target_tables == 1000
    assert cfg.strategy == "random"
    assert cfg.seed == 42
    assert cfg.catalog == "schemapile_lakehouse"


def test_load_config_rejects_project_catalog(tmp_path):
    with pytest.raises(ValueError) as exc:
        load_config(_base_env(tmp_path, DBXCARTA_CATALOG="graph-enriched-lakehouse"))
    assert "collides" in str(exc.value)


def test_load_config_rejects_shared_ops_catalog(tmp_path):
    # The data catalog must never be the shared ops catalog, or materialize
    # would write data schemas into the ops plane and collapse the separation.
    with pytest.raises(ValueError) as exc:
        load_config(_base_env(tmp_path, DBXCARTA_CATALOG="dbxcarta-catalog"))
    assert "collides" in str(exc.value)


def test_load_config_rejects_project_catalog_case_insensitive(tmp_path):
    with pytest.raises(ValueError) as exc:
        load_config(_base_env(tmp_path, DBXCARTA_CATALOG="Graph-Enriched-Lakehouse"))
    assert "collides" in str(exc.value)


def test_load_config_requires_repo(tmp_path):
    env = _base_env(tmp_path)
    env["SCHEMAPILE_REPO"] = ""
    with pytest.raises(ValueError) as exc:
        load_config(env)
    assert "SCHEMAPILE_REPO" in str(exc.value)


def test_load_config_truthy_parsing(tmp_path):
    cfg = load_config(_base_env(tmp_path, SCHEMAPILE_REQUIRE_SELF_CONTAINED="false"))
    assert cfg.require_self_contained is False
    cfg2 = load_config(_base_env(tmp_path, SCHEMAPILE_REQUIRE_SELF_CONTAINED="YES"))
    assert cfg2.require_self_contained is True


def test_volume_path_uses_env_ops_path(tmp_path):
    cfg = load_config(
        _base_env(
            tmp_path,
            DATABRICKS_VOLUME_PATH="/Volumes/dbxcarta-catalog/schemapile_ops/dbxcarta-ops",
        )
    )
    assert cfg.volume_path == "/Volumes/dbxcarta-catalog/schemapile_ops/dbxcarta-ops"
    # questions_path defaults under the ops volume, not the data catalog.
    assert cfg.questions_path == (
        "/Volumes/dbxcarta-catalog/schemapile_ops/dbxcarta-ops/dbxcarta/questions.json"
    )


def test_volume_path_requires_env_ops_path(tmp_path):
    # No in-catalog fallback: a missing DATABRICKS_VOLUME_PATH fails loudly
    # rather than routing the ops plane into the data-only catalog.
    env = _base_env(tmp_path)
    del env["DATABRICKS_VOLUME_PATH"]
    with pytest.raises(ValueError, match="DATABRICKS_VOLUME_PATH"):
        load_config(env)
