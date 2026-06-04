from __future__ import annotations

import contextlib
import os
import shutil
import sys
from pathlib import Path
from typing import TYPE_CHECKING, TypedDict

from databricks_job_runner import (
    Compute,
    DesiredLibrary,
    Runner,
    Serverless,
    maven_libraries_preflight,
)
from dbxcarta.core.env import select_overlay_path

if TYPE_CHECKING:
    from collections.abc import Iterator

_ENTRYPOINT_WHEEL_PACKAGE: dict[str, str] = {
    "ingest": "dbxcarta-spark",
    "client": "dbxcarta-client",
    "materialize": "dbxcarta-materialize",
}

_ENTRYPOINT_CONSOLE_SCRIPT: dict[str, str] = {
    "ingest": "dbxcarta-ingest",
    "client": "dbxcarta-client",
    "materialize": "dbxcarta-materialize",
}

# Packages the Databricks Runtime provides on the cluster and that the
# curated closures below must never reinstall. ``pyspark``/``py4j`` are
# the cluster runtime itself; ``databricks-sdk`` is DBR-managed and
# reinstalling it would shadow the platform SDK and drag in a heavy auth
# subtree. ``pydantic``/``pydantic-core`` are deliberately NOT excluded:
# the ingest and client code require pydantic v2 and the DBR-bundled
# version is not guaranteed to match.
_DBR_PROVIDED_PACKAGES: frozenset[str] = frozenset({"pyspark", "py4j", "databricks-sdk"})

# Fully pinned dependency closures installed by the runner bootstrap into
# the shared driver environment with ``--no-deps``. These are curated
# transitive closures, not top-level lists: pip performs no resolution,
# so a steady-state run cannot pull a newer transitive that conflicts
# with a DBR-managed package. Each excludes the DBR-provided packages
# above. The cluster Python/platform must have matching binary wheels
# (notably ``pydantic-core``); that is validated on the warm cluster in
# Phase V3.
_INGEST_PINNED_CLOSURE: tuple[str, ...] = (
    "databricks-job-runner==0.6.2",
    "neo4j==6.1.0",
    "pytz==2026.1.post1",
    "pydantic==2.13.3",
    "pydantic-core==2.46.3",
    "pydantic-settings==2.14.0",
    "python-dotenv==1.2.2",
    "annotated-types==0.7.0",
    "typing-extensions==4.15.0",
    "typing-inspection==0.4.2",
)

_CLIENT_PINNED_CLOSURE: tuple[str, ...] = (
    "neo4j==6.1.0",
    "pytz==2026.1.post1",
    "pydantic==2.13.3",
    "pydantic-core==2.46.3",
    "pydantic-settings==2.14.0",
    "python-dotenv==1.2.2",
    "annotated-types==0.7.0",
    "typing-extensions==4.15.0",
    "typing-inspection==0.4.2",
)

# Materialize needs neither Neo4j nor the job runner: it only builds DDL strings
# (core) and runs them with spark.sql. Its closure is the client one with neo4j
# (and neo4j's pytz dependency) dropped — just pydantic v2 and its transitives,
# the config-boundary surface MaterializeSettings reads through.
_MATERIALIZE_PINNED_CLOSURE: tuple[str, ...] = (
    "pydantic==2.13.3",
    "pydantic-core==2.46.3",
    "pydantic-settings==2.14.0",
    "python-dotenv==1.2.2",
    "annotated-types==0.7.0",
    "typing-extensions==4.15.0",
    "typing-inspection==0.4.2",
)

_ENTRYPOINT_PINNED_CLOSURE: dict[str, tuple[str, ...]] = {
    "ingest": _INGEST_PINNED_CLOSURE,
    "client": _CLIENT_PINNED_CLOSURE,
    "materialize": _MATERIALIZE_PINNED_CLOSURE,
}

# Top-level import names checked by the bootstrap post-install smoke
# check. Import names cannot be derived from version pins, so they are
# supplied explicitly. These name only shared-environment packages (the
# --no-deps closure), never wheel modules: the runner bootstrap runs the
# smoke check before it prepends the per-run wheel target to sys.path, so a
# wheel module like ``dbxcarta.core`` is not importable at that point. The
# guarantee that the wheels physically carry ``dbxcarta/core`` is enforced
# at build time instead (see ``_assert_wheel_bundles_core``).
_ENTRYPOINT_SMOKE_IMPORTS: dict[str, tuple[str, ...]] = {
    "ingest": (
        "databricks_job_runner",
        "neo4j",
        "pydantic",
        "pydantic_core",
        "pydantic_settings",
        "dotenv",
    ),
    "client": (
        "neo4j",
        "pydantic",
        "pydantic_core",
        "pydantic_settings",
    ),
    "materialize": (
        "pydantic",
        "pydantic_core",
        "pydantic_settings",
    ),
}

# The Neo4j Spark Connector stays a pinned JVM cluster library (pip
# cannot install it). Only the ingest path probes and asserts it.
_NEO4J_MAVEN_COORDINATES = "org.neo4j:neo4j-connector-apache-spark_2.13:5.3.10_for_spark_3"
_INGEST_JVM_PROBE_CLASS = "org.neo4j.spark.DataSource"

_ENTRYPOINT_JVM_PROBE_CLASS: dict[str, str | None] = {
    "ingest": _INGEST_JVM_PROBE_CLASS,
    "client": None,
    "materialize": None,
}


class _RunnerKwargs(TypedDict):
    """Per-key types for the shared Runner kwargs.

    A plain ``dict(...)`` literal makes mypy unify the str and list[str]
    values to ``Sequence[str]``, which then fails to match Runner's distinct
    parameter types when splatted. The TypedDict preserves each key's type
    through ``Runner(**_RUNNER_KWARGS)`` while keeping the single source of
    truth shared by both call sites.
    """

    run_name_prefix: str
    wheel_package: str
    scripts_dir: str
    cli_command: str
    secret_keys: list[str]


_RUNNER_KWARGS: _RunnerKwargs = {
    "run_name_prefix": "dbxcarta",
    "wheel_package": "dbxcarta-spark",
    "scripts_dir": "scripts",
    "cli_command": "uv run dbxcarta-submit",
    "secret_keys": ["NEO4J_URI", "NEO4J_USERNAME", "NEO4J_PASSWORD"],
}

# Shared runner for generic pass-through commands, the client path, and
# uploads. No preflights: client and generic commands do not need the
# Neo4j connector.
runner = Runner(**_RUNNER_KWARGS)


def _ingest_runner() -> Runner:
    """Runner scoped to the ingest submission with the connector preflight.

    The maven preflight is wired here rather than on the shared runner so
    submit/validate of the client and generic pass-through paths, which
    do not use the Neo4j connector, are not gated on it. The check is
    assert-only: it never installs or uninstalls a library.
    """
    return Runner(
        **_RUNNER_KWARGS,
        preflights=[
            maven_libraries_preflight(
                [DesiredLibrary.maven(_NEO4J_MAVEN_COORDINATES)],
                name="neo4j connector",
            )
        ],
        env_file=runner.env_file,
    )


def main() -> None:
    """Entry point for the operator submission CLI.

    dbxcarta owns five first-class commands; every other command is passed
    through to ``databricks-job-runner`` (submit, validate, logs, clean,
    upload, download, catalog, schema, volume).

    - `dbxcarta-submit submit-entrypoint {ingest|client}` submits the wheel
      entrypoint.
    - `dbxcarta-submit materialize` stages the committed blueprint to the ops
      Volume and submits the materialize wheel entrypoint as a serverless job.
    - `dbxcarta-submit publish-wheels` publishes the stable per-package
      wheels and ships the bootstrap script.
    - `dbxcarta-submit bootstrap` creates the data catalog the selected overlay
      names in `DBXCARTA_CATALOG`, plus the ops catalog, schema, and volume it
      names in `DATABRICKS_VOLUME_PATH`.
    - `dbxcarta-submit teardown` drops the catalog and/or schema targets the
      selected overlay names in `DBXCARTA_TEARDOWN_TARGET` (comma-separated).
    """
    overlay = select_overlay_path()
    runner.env_file = overlay
    if overlay is not None:
        # Path only, never resolved values, so no secret reaches logs.
        print(f"dbxcarta-submit: active env overlay: {overlay}", file=sys.stderr)

    argv = sys.argv[1:]
    if argv[:1] == ["submit-entrypoint"]:
        sys.exit(_handle_submit_entrypoint(argv[1:]))
    if argv[:1] == ["materialize"]:
        sys.exit(_handle_materialize(argv[1:], overlay))
    if argv[:1] == ["publish-wheels"]:
        sys.exit(_handle_publish_wheels(argv[1:]))
    if argv[:1] == ["bootstrap"]:
        sys.exit(_handle_bootstrap(argv[1:]))
    if argv[:1] == ["teardown"]:
        sys.exit(_handle_teardown(argv[1:]))
    if not argv or argv[0] in ("-h", "--help"):
        _print_help()
        sys.exit(0 if argv else 2)

    # Any other command is a generic job-runner command.
    runner.main()


def _print_help() -> None:
    """Summarize the dbxcarta commands, then the runner's own help.

    dbxcarta owns ``submit-entrypoint``, ``publish-wheels``, ``bootstrap``, and
    ``teardown``; every other command is the runner's. Delegating to the
    runner's ``--help`` keeps that list authoritative instead of duplicating
    (and drifting from) it.
    """
    print(
        "usage: dbxcarta-submit <command> [options]\n"
        "\n"
        "dbxcarta operator commands:\n"
        "  submit-entrypoint {ingest|client}   Submit a wheel entrypoint as a Databricks job.\n"
        "  materialize                         Stage the committed blueprint to the ops Volume\n"
        "                                      and submit the materialize entrypoint (serverless).\n"
        "  publish-wheels                      Publish the ingest, client, and materialize wheels\n"
        "                                      to the stable Volume path and ship the bootstrap\n"
        "                                      script.\n"
        "  bootstrap                           Create the data catalog (DBXCARTA_CATALOG) and the\n"
        "                                      ops catalog/schema/volume (DATABRICKS_VOLUME_PATH),\n"
        "                                      idempotent.\n"
        "  teardown                            Drop the catalog/schema targets named by the overlay's\n"
        "                                      DBXCARTA_TEARDOWN_TARGET (needs --yes-i-mean-it).\n"
        "\n"
        "Commands passed through to databricks-job-runner:"
    )
    with contextlib.suppress(SystemExit):
        runner.main(["--help"])


# The entrypoint wheels the runner installs with --no-deps. Each must
# physically carry ``dbxcarta/core`` because the bootstrap installs a single
# application wheel by name and has no slot for a separate core wheel.
_CORE_BUNDLE_PACKAGES: tuple[str, ...] = (
    "dbxcarta-spark",
    "dbxcarta-client",
    "dbxcarta-materialize",
)


@contextlib.contextmanager
def _core_bundled_into(project_dir: Path) -> Iterator[None]:
    """Copy the core source into each entrypoint package for the wheel build.

    The runner bootstrap installs one application wheel by name with
    ``--no-deps`` and cannot resolve or pull a separate ``dbxcarta-core``
    wheel, so the core modules must ride inside the spark and client wheels.
    The source stays single in ``dbxcarta-core``: this copies ``dbxcarta/core``
    into each entrypoint package's ``src/dbxcarta`` only for the duration of the
    build, then removes it so the working tree is left unchanged. Both
    entrypoint build backends set ``module-name = "dbxcarta"`` with
    ``namespace = true``, so the copied ``core`` package is packaged alongside
    the entrypoint's own modules.
    """
    from databricks_job_runner.errors import RunnerError

    root = Path(project_dir)
    # Package dirs sit directly under the dbxcarta subtree root (no ``packages/``
    # layer after the move into neocarta); project_dir is that subtree root.
    core_src = root / "dbxcarta-core" / "src" / "dbxcarta" / "core"
    if not core_src.is_dir():
        raise RunnerError(
            f"core source not found at {core_src}; cannot bundle it into the entrypoint wheels"
        )
    targets = [root / pkg / "src" / "dbxcarta" / "core" for pkg in _CORE_BUNDLE_PACKAGES]
    for target in targets:
        if target.exists():
            shutil.rmtree(target)
        shutil.copytree(core_src, target)
    try:
        yield
    finally:
        for target in targets:
            shutil.rmtree(target, ignore_errors=True)


def _assert_wheel_bundles_core(wheel_path: Path) -> None:
    """Fail loudly if a built entrypoint wheel is missing ``dbxcarta/core``.

    The runner bootstrap installs the application wheel with ``--no-deps`` and
    cannot pull a separate core wheel, so each entrypoint wheel must physically
    carry the core modules (bundled by ``_core_bundled_into``). The post-install
    smoke check cannot verify this — it runs before the wheel target is on
    ``sys.path`` — so the guarantee is enforced here, at build time, where a
    missing core package surfaces immediately instead of as an ``ImportError``
    on the cluster at first ``import dbxcarta.core``.
    """
    import zipfile

    from databricks_job_runner.errors import RunnerError

    with zipfile.ZipFile(wheel_path) as zf:
        names = zf.namelist()
    if not any(n.startswith("dbxcarta/core/") for n in names):
        raise RunnerError(
            f"built wheel {wheel_path.name} does not bundle dbxcarta/core; "
            "the entrypoint wheel must physically carry the core modules "
            "(the runner installs it with --no-deps and cannot pull a "
            "separate core wheel)"
        )


def _handle_publish_wheels(argv: list[str]) -> int:
    import argparse

    from databricks_job_runner.errors import RunnerError
    from databricks_job_runner.upload import find_latest_wheel, publish_wheel_stable

    parser = argparse.ArgumentParser(
        prog="dbxcarta-submit publish-wheels",
        description=(
            "Publish a stable wheel for each submit-entrypoint package "
            "(ingest and client) to the fixed Volume path, then ship the "
            "runner bootstrap script."
        ),
    )
    parser.parse_args(argv)  # no arguments; errors on anything extra

    # Publish a stable wheel for every submit-entrypoint package so both
    # `submit-entrypoint ingest` and `submit-entrypoint client` resolve
    # their wheel from the fixed Volume path. `upload_all` then ships the
    # runner bootstrap script the SparkPythonTask runs.
    try:
        # Bundle the core source into each entrypoint package so the built
        # wheels physically carry dbxcarta/core; the runner bootstrap installs
        # them with --no-deps and cannot pull a separate core wheel.
        with _core_bundled_into(runner.project_dir):
            for wheel_package in dict.fromkeys(_ENTRYPOINT_WHEEL_PACKAGE.values()):
                publish_wheel_stable(
                    runner.ws,
                    runner.project_dir,
                    runner.wheel_volume_dir,
                    wheel_package,
                )
                built = find_latest_wheel(runner.project_dir / "dist", wheel_package)
                if built is None:
                    raise RunnerError(f"no built wheel found for {wheel_package} in dist/")
                _assert_wheel_bundles_core(built)
        runner.upload_all()
    except RunnerError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    return 0


def _handle_bootstrap(argv: list[str]) -> int:
    """Create the data catalog and the ops catalog/schema/volume.

    The data catalog comes from ``DBXCARTA_CATALOG``; the ops catalog, schema,
    and volume come from the overlay's ``DATABRICKS_VOLUME_PATH``. Runs locally
    against a SQL warehouse. Idempotent: every object is created only if
    missing, so the make targets can run it before each ingest.
    """
    import argparse

    from dbxcarta.core.env import (
        EnvFileError,
        load_env_files,
        read_required_warehouse_id,
        resolve_env_files,
    )
    from dbxcarta.core.identifiers import (
        check_not_protected,
        parse_volume_path,
        validate_identifier,
    )
    from dbxcarta.core.workspace import build_workspace_client
    from dbxcarta.submit.uc_admin import ensure_uc_catalog, ensure_uc_volume

    try:
        files, cleaned_argv = resolve_env_files(argv)
    except EnvFileError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    load_env_files(files)

    parser = argparse.ArgumentParser(
        prog="dbxcarta-submit bootstrap",
        description=(
            "Create the data catalog (DBXCARTA_CATALOG) and the ops catalog, "
            "schema, and volume (DATABRICKS_VOLUME_PATH). Idempotent; safe to "
            "run before every ingest."
        ),
    )
    parser.add_argument("--warehouse-id", default=None, help="Override DATABRICKS_WAREHOUSE_ID.")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print the catalog, schema, and volume that would be created, then exit.",
    )
    args = parser.parse_args(cleaned_argv)

    volume_path = os.environ.get("DATABRICKS_VOLUME_PATH", "").strip()
    if not volume_path:
        print(
            "error: DATABRICKS_VOLUME_PATH is not set; select an example overlay "
            "with --env-file or DBXCARTA_ENV_FILE.",
            file=sys.stderr,
        )
        return 2
    data_catalog = os.environ.get("DBXCARTA_CATALOG", "").strip()
    if not data_catalog:
        print(
            "error: DBXCARTA_CATALOG is not set; select an example overlay "
            "with --env-file or DBXCARTA_ENV_FILE.",
            file=sys.stderr,
        )
        return 2
    try:
        catalog, schema, volume = parse_volume_path(volume_path)
        # Refuse a protected catalog before the dry-run print, so --dry-run
        # surfaces a typo'd /Volumes/main/... the same way teardown does.
        check_not_protected(catalog, label="catalog")
        # Validate the data catalog up front too, so a malformed or protected
        # DBXCARTA_CATALOG fails before any DDL runs and before the dry-run print.
        validate_identifier(data_catalog, label="data catalog")
        check_not_protected(data_catalog, label="catalog")
    except ValueError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    if args.dry_run:
        print(
            f"[bootstrap] would ensure data catalog={data_catalog} and "
            f"ops catalog={catalog} schema={schema} volume={volume}",
            file=sys.stderr,
        )
        return 0

    try:
        warehouse_id = read_required_warehouse_id(args.warehouse_id, operation="bootstrap")
        ws = build_workspace_client()
        ensure_uc_catalog(ws, warehouse_id, catalog=data_catalog)
        ensure_uc_volume(ws, warehouse_id, catalog=catalog, schema=schema, volume=volume)
    except (ValueError, RuntimeError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    print(
        f"[bootstrap] ensured data catalog {data_catalog} and {catalog}.{schema}.{volume}",
        file=sys.stderr,
    )
    return 0


def _handle_teardown(argv: list[str]) -> int:
    """Drop every catalog/schema target named by the overlay's teardown value.

    Destructive and never automatic: without ``--yes-i-mean-it`` it prints the
    targets and exits without dropping anything.
    """
    import argparse

    from dbxcarta.core.env import (
        EnvFileError,
        load_env_files,
        read_required_warehouse_id,
        resolve_env_files,
    )
    from dbxcarta.core.workspace import build_workspace_client
    from dbxcarta.submit.uc_admin import (
        drop_teardown_target,
        parse_teardown_targets,
    )

    try:
        files, cleaned_argv = resolve_env_files(argv)
    except EnvFileError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    load_env_files(files)

    parser = argparse.ArgumentParser(
        prog="dbxcarta-submit teardown",
        description=(
            "Drop the catalog or schema named by the overlay's "
            "DBXCARTA_TEARDOWN_TARGET. Requires --yes-i-mean-it; destructive."
        ),
    )
    parser.add_argument("--warehouse-id", default=None, help="Override DATABRICKS_WAREHOUSE_ID.")
    parser.add_argument(
        "--yes-i-mean-it",
        action="store_true",
        help="Required to actually drop; without it the command is a no-op.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print the target that would be dropped, then exit.",
    )
    args = parser.parse_args(cleaned_argv)

    target_value = os.environ.get("DBXCARTA_TEARDOWN_TARGET", "").strip()
    if not target_value:
        print(
            "error: DBXCARTA_TEARDOWN_TARGET is not set; select an example "
            "overlay with --env-file or DBXCARTA_ENV_FILE.",
            file=sys.stderr,
        )
        return 2
    try:
        targets = parse_teardown_targets(target_value)
    except ValueError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    described = ", ".join(t.describe() for t in targets)
    if args.dry_run:
        print(f"[teardown] would drop {described}", file=sys.stderr)
        return 0
    if not args.yes_i_mean_it:
        print(
            f"[teardown] refusing to drop {described} without --yes-i-mean-it; nothing changed.",
            file=sys.stderr,
        )
        return 0

    try:
        warehouse_id = read_required_warehouse_id(args.warehouse_id, operation="teardown")
        ws = build_workspace_client()
    except ValueError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    # Drop each target in its own try so a mid-list failure reports which
    # targets already dropped. Re-running is safe: every drop is IF EXISTS.
    for target in targets:
        try:
            drop_teardown_target(ws, warehouse_id, target)
        except (ValueError, RuntimeError) as exc:
            print(f"error: dropping {target.describe()} failed: {exc}", file=sys.stderr)
            return 2
        print(f"[teardown] dropped {target.describe()}", file=sys.stderr)
    return 0


def _handle_submit_entrypoint(argv: list[str]) -> int:
    import argparse

    from databricks_job_runner.errors import RunnerError

    parser = argparse.ArgumentParser(prog="dbxcarta-submit submit-entrypoint")
    parser.add_argument("entrypoint", choices=("ingest", "client"))
    parser.add_argument("--compute", choices=("cluster", "serverless"), default=None)
    parser.add_argument("--no-wait", action="store_true")
    args = parser.parse_args(argv)

    try:
        _submit_bootstrap_entrypoint(
            args.entrypoint,
            compute_mode=args.compute,
            no_wait=args.no_wait,
        )
    except RunnerError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    return 0


def _handle_materialize(argv: list[str], overlay: Path | None) -> int:
    """Stage the committed blueprint to the ops Volume, then submit the job.

    Uploads the blueprint to the canonical ``{volume}/dbxcarta/blueprint/
    blueprint.json`` (the path the cluster job derives from
    ``DATABRICKS_VOLUME_PATH``), then submits the ``dbxcarta-materialize`` wheel
    entrypoint as a standalone serverless Spark job. The local blueprint is
    ``--blueprint`` when given, else the single ``*.json`` under the selected
    overlay's sibling ``blueprint/`` directory. The data catalog must already
    exist (run ``dbxcarta-submit bootstrap`` first).
    """
    import argparse

    from databricks_job_runner.errors import RunnerError
    from dbxcarta.core.config import derive_ops_config
    from dbxcarta.core.env import (
        EnvFileError,
        load_env_files,
        resolve_env_files,
    )
    from dbxcarta.core.volume_io import upload_file_to_volume
    from dbxcarta.core.workspace import build_workspace_client

    try:
        files, cleaned_argv = resolve_env_files(argv)
    except EnvFileError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    load_env_files(files)

    parser = argparse.ArgumentParser(
        prog="dbxcarta-submit materialize",
        description=(
            "Stage the committed blueprint to the ops Volume and submit the "
            "materialize entrypoint as a serverless Spark job."
        ),
    )
    parser.add_argument(
        "--blueprint",
        type=Path,
        default=None,
        help=(
            "Local blueprint JSON to stage. Defaults to the single *.json under "
            "the selected overlay's sibling blueprint/ directory."
        ),
    )
    parser.add_argument("--compute", choices=("cluster", "serverless"), default=None)
    parser.add_argument("--no-wait", action="store_true")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print the blueprint that would be staged and where, then exit.",
    )
    args = parser.parse_args(cleaned_argv)

    volume_path = os.environ.get("DATABRICKS_VOLUME_PATH", "").strip()
    if not volume_path:
        print(
            "error: DATABRICKS_VOLUME_PATH is not set; select an example overlay "
            "with --env-file or DBXCARTA_ENV_FILE.",
            file=sys.stderr,
        )
        return 2

    try:
        local_blueprint = _resolve_local_blueprint(args.blueprint, overlay)
        _validate_blueprint_file(local_blueprint)
        dest = derive_ops_config(volume_path).blueprint_volume
    except (ValueError, FileNotFoundError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    if args.dry_run:
        print(
            f"[materialize] would stage {local_blueprint} -> {dest}, "
            "then submit the materialize entrypoint (serverless)",
            file=sys.stderr,
        )
        return 0

    try:
        ws = build_workspace_client()
        upload_file_to_volume(ws, local_blueprint, dest)
        print(f"[materialize] staged {local_blueprint.name} -> {dest}", file=sys.stderr)
        _submit_bootstrap_entrypoint(
            "materialize",
            compute_mode=args.compute,
            no_wait=args.no_wait,
        )
    except RunnerError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    return 0


def _resolve_local_blueprint(explicit: Path | None, overlay: Path | None) -> Path:
    """Return the local blueprint JSON to stage.

    ``explicit`` (``--blueprint``) wins when given. Otherwise the blueprint is
    the single ``*.json`` under the selected overlay's sibling ``blueprint/``
    directory; zero or several candidates is a hard error, since there is no
    unambiguous default to pick.
    """
    if explicit is not None:
        if not explicit.is_file():
            raise FileNotFoundError(f"blueprint not found at {explicit}")
        return explicit
    if overlay is None:
        raise ValueError(
            "no --blueprint given and no overlay selected; pass --blueprint or "
            "select an overlay with --env-file or DBXCARTA_ENV_FILE."
        )
    blueprint_dir = overlay.resolve().parent / "blueprint"
    candidates = sorted(blueprint_dir.glob("*.json"))
    if not candidates:
        raise FileNotFoundError(
            f"no blueprint *.json found under {blueprint_dir}; pass --blueprint explicitly."
        )
    if len(candidates) > 1:
        names = ", ".join(p.name for p in candidates)
        raise ValueError(
            f"multiple blueprint *.json under {blueprint_dir} ({names}); "
            "pass --blueprint to choose one."
        )
    return candidates[0]


def _validate_blueprint_file(path: Path) -> None:
    """Light structural check before staging: a JSON object with a non-empty
    ``schemas`` array. The cluster job re-reads and fully validates it; this just
    catches an empty or malformed file before a job is submitted.
    """
    from dbxcarta.core.volume_io import load_json_file

    payload = load_json_file(path, label="blueprint")
    if not isinstance(payload, dict):
        raise ValueError(f"blueprint must be a JSON object: {path}")  # noqa: TRY004
    schemas = payload.get("schemas")
    if not isinstance(schemas, list) or not schemas:
        raise ValueError(f"blueprint must carry a non-empty 'schemas' array: {path}")


def _submit_bootstrap_entrypoint(
    name: str,
    *,
    compute_mode: str | None,
    no_wait: bool,
) -> None:
    from databricks_job_runner import BootstrapConfig
    from databricks_job_runner.errors import RunnerError
    from databricks_job_runner.upload import stable_wheel_name

    wheel_package = _ENTRYPOINT_WHEEL_PACKAGE.get(name)
    if wheel_package is None:
        raise RunnerError(f"unknown wheel entrypoint {name!r}")

    # Ingest is gated on the Neo4j connector via the dedicated runner's
    # maven preflight; the client and generic paths do not need it.
    submit_runner = _ingest_runner() if name == "ingest" else runner

    # Runner._compute is private but is the only accessor for the resolved
    # Compute strategy; there is no public equivalent. Pinned to
    # databricks-job-runner==0.6.2 in the closures above, so the surface is
    # stable for this code's lifetime.
    if name == "ingest" and _is_serverless_compute(submit_runner._compute(compute_mode)):
        raise RunnerError(
            "dbxcarta ingest uses the Neo4j Spark Connector, which is not "
            "supported on Databricks serverless jobs compute. Use classic "
            "compute with `--compute cluster`."
        )

    wheel_volume_path = f"{submit_runner.wheel_volume_dir}/{stable_wheel_name(wheel_package)}"

    bootstrap = BootstrapConfig(
        wheel_volume_path=wheel_volume_path,
        pinned_closure=list(_ENTRYPOINT_PINNED_CLOSURE[name]),
        wheel_package=wheel_package,
        console_script=_ENTRYPOINT_CONSOLE_SCRIPT[name],
        jvm_probe_class=_ENTRYPOINT_JVM_PROBE_CLASS[name],
        smoke_imports=list(_ENTRYPOINT_SMOKE_IMPORTS[name]),
    )

    submit_runner.submit_bootstrap(
        bootstrap,
        run_name_suffix=name,
        no_wait=no_wait,
        compute_mode=compute_mode,
    )


def _is_serverless_compute(compute: Compute) -> bool:
    return isinstance(compute, Serverless)
