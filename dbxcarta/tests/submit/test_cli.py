"""Unit tests for dbxcarta-submit CLI guardrails."""

from __future__ import annotations

import pytest
from databricks_job_runner import BootstrapConfig, ClassicCluster, Serverless
from databricks_job_runner.errors import RunnerError
from dbxcarta.submit import cli


class _RunnerStub:
    wheel_volume_dir = "/Volumes/catalog/schema/volume/wheels"
    run_name_prefix = "dbxcarta"
    cli_command = "uv run dbxcarta-submit"

    def __init__(self, compute: object) -> None:
        self._compute_obj = compute
        self.submitted: list[tuple[BootstrapConfig, dict]] = []

    def _compute(self, mode_override: str | None = None) -> object:
        return self._compute_obj

    def submit_bootstrap(self, bootstrap: BootstrapConfig, **kwargs: object) -> None:
        self.submitted.append((bootstrap, kwargs))


def test_submit_ingest_rejects_serverless_compute(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    stub = _RunnerStub(Serverless())
    monkeypatch.setattr(cli, "_ingest_runner", lambda: stub)

    with pytest.raises(RunnerError, match="Neo4j Spark Connector"):
        cli._submit_bootstrap_entrypoint("ingest", compute_mode="serverless", no_wait=True)
    assert stub.submitted == []


def test_submit_unknown_entrypoint_raises() -> None:
    with pytest.raises(RunnerError, match="unknown wheel entrypoint"):
        cli._submit_bootstrap_entrypoint("bogus", compute_mode=None, no_wait=True)


def test_submit_ingest_builds_bootstrap_with_probe_and_closure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    stub = _RunnerStub(ClassicCluster(cluster_id="c-1"))
    monkeypatch.setattr(cli, "_ingest_runner", lambda: stub)

    cli._submit_bootstrap_entrypoint("ingest", compute_mode=None, no_wait=True)

    assert len(stub.submitted) == 1
    bootstrap, kwargs = stub.submitted[0]
    assert bootstrap.wheel_package == "dbxcarta-spark"
    assert bootstrap.console_script == "dbxcarta-ingest"
    assert bootstrap.jvm_probe_class == cli._INGEST_JVM_PROBE_CLASS
    assert bootstrap.pinned_closure == list(cli._INGEST_PINNED_CLOSURE)
    assert bootstrap.wheel_volume_path.endswith("dbxcarta_spark-stable.whl")
    assert kwargs["run_name_suffix"] == "ingest"


def test_submit_client_uses_shared_runner_without_probe(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    stub = _RunnerStub(ClassicCluster(cluster_id="c-1"))
    monkeypatch.setattr(cli, "runner", stub)
    monkeypatch.setattr(
        cli, "_ingest_runner", lambda: pytest.fail("client must not use ingest runner")
    )

    cli._submit_bootstrap_entrypoint("client", compute_mode=None, no_wait=True)

    bootstrap, _ = stub.submitted[0]
    assert bootstrap.wheel_package == "dbxcarta-client"
    assert bootstrap.console_script == "dbxcarta-client"
    assert bootstrap.jvm_probe_class is None
    assert bootstrap.pinned_closure == list(cli._CLIENT_PINNED_CLOSURE)


def test_is_serverless_compute_discriminates_real_compute_types() -> None:
    assert cli._is_serverless_compute(Serverless()) is True
    assert cli._is_serverless_compute(ClassicCluster(cluster_id="c-1")) is False


def test_help_lists_all_dbxcarta_commands(capsys: pytest.CaptureFixture[str]) -> None:
    # dbxcarta's own commands are intercepted before the runner sees them, so
    # they are invisible unless help advertises them. Guard that all four appear.
    cli._print_help()

    out = capsys.readouterr().out
    assert "submit-entrypoint" in out
    assert "publish-wheels" in out
    assert "bootstrap" in out
    assert "teardown" in out


def test_publish_wheels_rejects_unknown_args() -> None:
    # publish-wheels takes no arguments; the old `upload --wheel` form swallowed
    # any extra argv silently. argparse must now reject unknown tokens before
    # touching the workspace.
    with pytest.raises(SystemExit):
        cli._handle_publish_wheels(["--wheel"])


def test_smoke_imports_name_only_shared_environment_packages() -> None:
    # The runner bootstrap runs the post-install smoke check before it prepends
    # the per-run wheel target to sys.path, so a wheel module (dbxcarta.*) is
    # not importable at that point and would fail every cluster run. Wheel
    # content is guaranteed at build time instead (_assert_wheel_bundles_core),
    # so the smoke lists must name only shared-environment (closure) packages.
    for entrypoint, modules in cli._ENTRYPOINT_SMOKE_IMPORTS.items():
        wheel_modules = [m for m in modules if m == "dbxcarta" or m.startswith("dbxcarta.")]
        assert not wheel_modules, (
            f"{entrypoint} smoke imports name wheel modules {wheel_modules}; "
            "the smoke check runs before the wheel target joins sys.path"
        )


def _no_workspace(monkeypatch: pytest.MonkeyPatch) -> None:
    """Stub env loading and fail loudly if a handler touches the workspace.

    The bootstrap/teardown no-op and error paths must short-circuit before any
    warehouse call. Patching the env loader keeps the repo `.env` from bleeding
    into the test, and the boom stubs assert nothing was created or dropped.
    """

    def _boom(*args: object, **kwargs: object) -> object:
        pytest.fail("handler must not touch the workspace on this path")

    # Keep a developer's exported overlay selection from steering the handler:
    # the tests drive env entirely through monkeypatch.setenv below.
    monkeypatch.delenv("DBXCARTA_ENV_FILE", raising=False)
    monkeypatch.setattr("dbxcarta.core.env.load_env_files", lambda files: None)
    monkeypatch.setattr("dbxcarta.core.workspace.build_workspace_client", _boom)
    monkeypatch.setattr("dbxcarta.submit.uc_admin.ensure_uc_volume", _boom)
    monkeypatch.setattr("dbxcarta.submit.uc_admin.drop_teardown_target", _boom)


def test_bootstrap_missing_volume_path_errors(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _no_workspace(monkeypatch)
    monkeypatch.delenv("DATABRICKS_VOLUME_PATH", raising=False)
    assert cli._handle_bootstrap([]) == 2


def test_bootstrap_dry_run_reports_names_without_workspace(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _no_workspace(monkeypatch)
    monkeypatch.setenv("DATABRICKS_VOLUME_PATH", "/Volumes/cat/sch/vol")
    monkeypatch.setenv("DBXCARTA_CATALOG", "dense_data")
    assert cli._handle_bootstrap(["--dry-run"]) == 0
    err = capsys.readouterr().err
    assert "data catalog=dense_data" in err
    assert "catalog=cat" in err
    assert "schema=sch" in err
    assert "volume=vol" in err


def test_bootstrap_dry_run_refuses_protected_catalog(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _no_workspace(monkeypatch)
    monkeypatch.setenv("DATABRICKS_VOLUME_PATH", "/Volumes/main/sch/vol")
    monkeypatch.setenv("DBXCARTA_CATALOG", "dense_data")
    assert cli._handle_bootstrap(["--dry-run"]) == 2


def test_teardown_missing_target_errors(monkeypatch: pytest.MonkeyPatch) -> None:
    _no_workspace(monkeypatch)
    monkeypatch.delenv("DBXCARTA_TEARDOWN_TARGET", raising=False)
    assert cli._handle_teardown([]) == 2


def test_teardown_without_confirmation_is_noop(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _no_workspace(monkeypatch)
    monkeypatch.setenv("DBXCARTA_TEARDOWN_TARGET", "schema:cat.sch")
    assert cli._handle_teardown([]) == 0


def test_teardown_dry_run_is_noop_even_with_confirmation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _no_workspace(monkeypatch)
    monkeypatch.setenv("DBXCARTA_TEARDOWN_TARGET", "catalog:schemapile_lakehouse")
    assert cli._handle_teardown(["--dry-run", "--yes-i-mean-it"]) == 0


def test_teardown_dry_run_lists_every_target(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _no_workspace(monkeypatch)
    monkeypatch.setenv(
        "DBXCARTA_TEARDOWN_TARGET",
        "catalog:schemapile_lakehouse,schema:dbxcarta-catalog.schemapile_ops",
    )
    assert cli._handle_teardown(["--dry-run"]) == 0
    err = capsys.readouterr().err
    assert "catalog schemapile_lakehouse" in err
    assert "schema dbxcarta-catalog.schemapile_ops" in err
