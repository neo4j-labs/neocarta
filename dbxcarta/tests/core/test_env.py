"""Unit tests for `dbxcarta.core.env.inject_params`."""

from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest
from dbxcarta.core import env as _bootstrap


def test_inject_params_overlays_key_value_args(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(sys, "argv", ["prog", "FOO=bar", "BAZ=qux", "leftover"])
    monkeypatch.delenv("FOO", raising=False)
    monkeypatch.delenv("BAZ", raising=False)

    _bootstrap.inject_params()

    import os

    assert os.environ["FOO"] == "bar"
    assert os.environ["BAZ"] == "qux"
    assert sys.argv[1:] == ["leftover"]


def test_inject_params_existing_env_wins(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(sys, "argv", ["prog", "FOO=from_argv"])
    monkeypatch.setenv("FOO", "from_env")

    _bootstrap.inject_params()

    import os

    assert os.environ["FOO"] == "from_env"


_LAYER_KEY = "DBXCARTA_TEST_LAYER_KEY"


def _write_env(path: Path, key: str, value: str) -> None:
    path.write_text(f"{key}={value}\n", encoding="utf-8")


def test_resolve_no_overlay_is_base_only(monkeypatch: pytest.MonkeyPatch) -> None:
    """No --env-file and no DBXCARTA_ENV_FILE reproduces today exactly."""
    monkeypatch.delenv(_bootstrap._ENV_FILE_KEY, raising=False)

    files, argv = _bootstrap.resolve_env_files(["--run-id", "r1"])

    assert files == [_bootstrap._BASE_ENV_FILE]
    assert argv == ["--run-id", "r1"]


def test_resolve_cli_option_wins_over_env_var(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    cli_overlay = tmp_path / "cli.env"
    _write_env(cli_overlay, "X", "1")
    env_overlay = tmp_path / "env.env"
    _write_env(env_overlay, "X", "2")
    monkeypatch.setenv(_bootstrap._ENV_FILE_KEY, str(env_overlay))

    files, argv = _bootstrap.resolve_env_files(["--env-file", str(cli_overlay), "spec"])

    assert files == [cli_overlay, _bootstrap._BASE_ENV_FILE]
    assert argv == ["spec"]


def test_resolve_env_var_used_when_no_cli_option(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    env_overlay = tmp_path / "env.env"
    _write_env(env_overlay, "X", "2")
    monkeypatch.setenv(_bootstrap._ENV_FILE_KEY, str(env_overlay))

    files, argv = _bootstrap.resolve_env_files(["spec"])

    assert files == [env_overlay, _bootstrap._BASE_ENV_FILE]
    assert argv == ["spec"]


def test_resolve_unresolvable_overlay_is_hard_error(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A selected overlay that does not resolve must raise, not fall back."""
    monkeypatch.delenv(_bootstrap._ENV_FILE_KEY, raising=False)
    missing = tmp_path / "does-not-exist.env"

    with pytest.raises(_bootstrap.EnvFileError):
        _bootstrap.resolve_env_files(["--env-file", str(missing)])


def test_resolve_bare_env_file_option_is_error() -> None:
    with pytest.raises(_bootstrap.EnvFileError):
        _bootstrap.resolve_env_files(["--env-file"])


def test_resolve_empty_env_file_value_is_error() -> None:
    with pytest.raises(_bootstrap.EnvFileError):
        _bootstrap.resolve_env_files(["--env-file="])


def test_load_precedence_process_over_overlay_over_base(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Real process env > overlay > base, for the same key."""
    base = tmp_path / "base.env"
    overlay = tmp_path / "overlay.env"
    _write_env(base, _LAYER_KEY, "from_base")
    _write_env(overlay, _LAYER_KEY, "from_overlay")

    # load_dotenv mutates os.environ directly, outside monkeypatch's
    # tracking, so the key is popped explicitly to keep tests isolated.
    try:
        # Process env wins over both.
        monkeypatch.setenv(_LAYER_KEY, "from_process")
        _bootstrap.load_env_files([overlay, base])
        assert os.environ[_LAYER_KEY] == "from_process"

        # Without a process value, overlay wins over base.
        monkeypatch.delenv(_LAYER_KEY, raising=False)
        _bootstrap.load_env_files([overlay, base])
        assert os.environ[_LAYER_KEY] == "from_overlay"

        # Base-only reproduces today's single-file behaviour.
        monkeypatch.delenv(_LAYER_KEY, raising=False)
        os.environ.pop(_LAYER_KEY, None)
        _bootstrap.load_env_files([base])
        assert os.environ[_LAYER_KEY] == "from_base"
    finally:
        os.environ.pop(_LAYER_KEY, None)


def test_select_overlay_none_when_unselected(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv(_bootstrap._ENV_FILE_KEY, raising=False)
    assert _bootstrap.select_overlay_path(["verify", "--run-id", "r"]) is None


def test_select_overlay_cli_wins_over_env_var(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(_bootstrap._ENV_FILE_KEY, "/from/env.env")
    selected = _bootstrap.select_overlay_path(["--env-file", "/from/cli.env"])
    assert selected == Path("/from/cli.env")


def test_select_overlay_env_var_fallback(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(_bootstrap._ENV_FILE_KEY, "/from/env.env")
    assert _bootstrap.select_overlay_path(["submit-entrypoint", "ingest"]) == Path("/from/env.env")


def test_select_overlay_malformed_flag_is_no_selection(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Malformed --env-file does not raise at selection; the consuming
    path's own parser surfaces the clean error instead."""
    monkeypatch.delenv(_bootstrap._ENV_FILE_KEY, raising=False)
    assert _bootstrap.select_overlay_path(["--env-file"]) is None


def test_load_missing_file_is_silent_noop(tmp_path) -> None:
    """A missing file is a no-op, matching today's base-.env behaviour."""
    import os

    missing = tmp_path / "nope.env"
    os.environ.pop(_LAYER_KEY, None)

    _bootstrap.load_env_files([missing])

    assert _LAYER_KEY not in os.environ


def test_read_required_warehouse_id_prefers_and_strips_override(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("DATABRICKS_WAREHOUSE_ID", "ignored")
    assert _bootstrap.read_required_warehouse_id(" wh-1 ", operation="bootstrap") == "wh-1"


def test_read_required_warehouse_id_falls_back_to_env(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("DATABRICKS_WAREHOUSE_ID", "wh-env")
    assert _bootstrap.read_required_warehouse_id(None, operation="bootstrap") == "wh-env"


def test_read_required_warehouse_id_missing_raises(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("DATABRICKS_WAREHOUSE_ID", "   ")
    with pytest.raises(ValueError, match="DATABRICKS_WAREHOUSE_ID"):
        _bootstrap.read_required_warehouse_id(None, operation="bootstrap")


def test_read_required_warehouse_id_appends_extra_hint(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("DATABRICKS_WAREHOUSE_ID", raising=False)
    with pytest.raises(ValueError, match="or use --skip-validate"):
        _bootstrap.read_required_warehouse_id(
            None, operation="SQL validation", extra_hint="or use --skip-validate"
        )


def test_read_materialize_workers_defaults_to_five() -> None:
    assert _bootstrap.read_materialize_workers({}) == 5


def test_read_materialize_workers_blank_uses_default() -> None:
    assert _bootstrap.read_materialize_workers({"DBXCARTA_MATERIALIZE_WORKERS": "  "}) == 5


def test_read_materialize_workers_reads_override() -> None:
    assert _bootstrap.read_materialize_workers({"DBXCARTA_MATERIALIZE_WORKERS": "8"}) == 8


def test_read_materialize_workers_reads_process_env(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("DBXCARTA_MATERIALIZE_WORKERS", "3")
    assert _bootstrap.read_materialize_workers() == 3


def test_read_materialize_workers_rejects_below_one() -> None:
    with pytest.raises(ValueError, match=">= 1"):
        _bootstrap.read_materialize_workers({"DBXCARTA_MATERIALIZE_WORKERS": "0"})


def test_read_materialize_workers_rejects_non_integer() -> None:
    with pytest.raises(ValueError, match="must be an integer"):
        _bootstrap.read_materialize_workers({"DBXCARTA_MATERIALIZE_WORKERS": "many"})
