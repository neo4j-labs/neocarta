#!/usr/bin/env python
"""Scaffold, wire, and verify ``neocarta`` CLI commands that wrap a *connector*.

This is the agent-facing handle for the *CLI integration* PR that follows
building a library connector (see the ``neocarta-add-source-connector`` skill).
It is scoped to source/format **connector** commands; enrichment-only and MCP
tool commands are separate (future) skills. It mirrors the existing command
modules under ``neocarta/_cli/commands/`` (``bigquery``, ``csv``, ``dataplex``,
``osi``, ``query_log``) and the contract in this skill's
``connector-cli-command-contract.md``.

    list      — every connector + whether it already has a CLI command (gap map)
    scaffold  — generate a command module + unit test, and wire it into main.py
    verify    — check a command against the contract (import, registration,
                agent-context, --help, ruff, and its unit test)

Run it through the managed environment, e.g.::

    uv run .claude/skills/neocarta-add-connector-cli-command/scripts/driver.py list
    uv run .claude/skills/neocarta-add-connector-cli-command/scripts/driver.py scaffold databricks
    uv run .claude/skills/neocarta-add-connector-cli-command/scripts/driver.py verify databricks

``<source>`` is the CLI group name and the command-module stem under
``neocarta/_cli/commands/`` (``databricks`` -> ``neocarta databricks ...``).
"""

from __future__ import annotations

import argparse
import importlib
import pathlib
import re
import subprocess
import sys

REPO_ROOT = pathlib.Path(__file__).resolve().parents[4]
CLI_DIR = REPO_ROOT / "neocarta" / "_cli"
COMMANDS_DIR = CLI_DIR / "commands"
CONNECTORS_DIR = REPO_ROOT / "neocarta" / "connectors"
CLI_TESTS_DIR = REPO_ROOT / "tests" / "unit" / "_cli"
MAIN_PY = CLI_DIR / "main.py"

# Command modules that aren't connector groups.
SKIP_COMMAND_STEMS = {"__init__", "_common", "agent_context"}
SKIP_CONNECTOR_DIRS = {"utils", "__pycache__"}


# --------------------------------------------------------------------------- #
# helpers
# --------------------------------------------------------------------------- #
def _group_func(source: str) -> str:
    """CLI group function name (a valid identifier) for a source."""
    return source.strip().replace("-", "_")


def _connector_classes(pkg: str) -> list[str]:
    """Exported ``*Connector`` class names for ``neocarta.connectors.<pkg>``."""
    try:
        module = importlib.import_module(f"neocarta.connectors.{pkg}")
    except Exception:  # best-effort introspection for the gap map
        return []
    return [n for n in getattr(module, "__all__", []) if n.endswith("Connector")]


def _existing_command_stems() -> set[str]:
    """Module stems under ``_cli/commands/`` that are connector groups."""
    return {p.stem for p in COMMANDS_DIR.glob("*.py") if p.stem not in SKIP_COMMAND_STEMS}


# --------------------------------------------------------------------------- #
# scaffold templates
# --------------------------------------------------------------------------- #
def _command_py(source: str, connector_pkg: str, connector_cls: str, verbs: list[str]) -> str:
    """Render a command module: a Click group plus one ingest-shaped verb each."""
    func = _group_func(source)
    env = f"{source.upper().replace('-', '_')}_SOURCE"
    flag = "--source"
    commands = "\n\n".join(
        _verb_block(source, func, verb, connector_pkg, connector_cls, flag, env) for verb in verbs
    )
    verb_list = ", ".join(f"``{v}``" for v in verbs)
    return f'''"""``neocarta {source} ...`` commands.

Wraps :class:`neocarta.connectors.{connector_pkg}.{connector_cls}`. Verbs: {verb_list}.
"""

from __future__ import annotations

import os

import click

from ...errors import NeocartaError
from ..config import load_settings, require, resolve
from ..errors import cli_error_from
from ..output import cli_status, emit_json
from ._common import (
    DEFAULT_SCHEMA_NODE_LABELS,
    _build_embedder,
    _neo4j_driver,
    _require_neo4j_settings,
    _run_embeddings,
)


@click.group()
def {func}() -> None:
    """Run {source} connectors."""


{commands}
'''


def _verb_block(
    source: str,
    func: str,
    verb: str,
    connector_pkg: str,
    connector_cls: str,
    flag: str,
    env: str,
) -> str:
    """Render one ingest-shaped command function for ``verb``."""
    handler = f"{func}_{verb}"
    key = f"{func}_{verb}"
    return f'''@{func}.command("{verb}")
@click.option(
    "{flag}",
    default=None,
    help="Source input for the {source} connector. Overrides {env}.",
)
@click.option(
    "--embeddings/--no-embeddings",
    "embeddings",
    default=False,
    help="Generate embeddings for ingested nodes after {verb} (default: disabled).",
)
@click.option(
    "--embedding-model",
    default=None,
    help="Embedding model id in LiteLLM format (default: text-embedding-3-small).",
)
@click.option(
    "--embedding-dimensions",
    type=int,
    default=None,
    help="Embedding vector dimensions (default: auto-detected from the model).",
)
@click.option(
    "--dry-run",
    is_flag=True,
    default=False,
    help="Print the planned ingestion without touching Neo4j.",
)
@click.option(
    "--json",
    "json_flag",
    is_flag=True,
    default=False,
    help="Emit JSON on stdout. Also accepted as a top-level flag.",
)
@click.pass_context
def {handler}(
    ctx: click.Context,
    *,
    source: str | None,
    embeddings: bool,
    embedding_model: str | None,
    embedding_dimensions: int | None,
    dry_run: bool,
    json_flag: bool,
) -> None:
    """{verb.capitalize()} {source} metadata into the Neo4j semantic graph.

    TODO: describe what nodes/relationships land in Neo4j. The source input can
    come from the {flag} flag or the {env} env var. Pass --dry-run to print the
    planned ingestion without touching Neo4j.
    """
    settings = load_settings()
    # TODO: promote this input to a CLISettings field + ENV_VARS entry in
    # config.py (see cli-command-contract.md), then resolve from settings.
    source = require(
        "{flag}",
        resolve(source, os.environ.get("{env}")),
        env_var="{env}",
    )
    if embedding_model is not None:
        settings.embedding_model = embedding_model
    if embedding_dimensions is not None:
        settings.embedding_dimensions = embedding_dimensions

    stdout = ctx.obj["stdout"]
    stderr = ctx.obj["stderr"]
    as_json = ctx.obj["as_json"] or json_flag
    node_labels = list(DEFAULT_SCHEMA_NODE_LABELS)

    if dry_run:
        payload = {{
            "{key}": {{
                "dry_run": True,
                "source": source,
                "database": settings.neo4j_database,
                "embeddings": embeddings,
                "embedding_model": settings.embedding_model if embeddings else None,
            }}
        }}
        if as_json:
            emit_json(payload)
        else:
            stdout.print(payload)
        return

    _require_neo4j_settings(settings)

    # Lazy import: keep the connector dependency off the --help / --dry-run path.
    from ...connectors.{connector_pkg} import {connector_cls}  # noqa: PLC0415

    with _neo4j_driver(settings) as driver:
        try:
            # TODO: pass the real constructor args this connector needs.
            connector = {connector_cls}(
                neo4j_driver=driver,
                database_name=settings.neo4j_database,
            )
            with cli_status(stderr, "Ingesting {source} metadata..."):
                connector.ingest(source)  # TODO: match the connector's ingest() signature.

            if embeddings:
                embedder = _build_embedder(settings, driver)
                with cli_status(stderr, "Generating embeddings..."):
                    _run_embeddings(embedder, node_labels)
        except NeocartaError as exc:
            raise cli_error_from(exc) from exc

    payload = {{
        "{key}": {{
            "source": source,
            "database": settings.neo4j_database,
            "embeddings": embeddings,
            "status": "succeeded",
        }}
    }}
    if as_json:
        emit_json(payload)
    else:
        stdout.print(
            f"Ingested {source} metadata into [bold]{{settings.neo4j_database}}[/bold] "
            f"({{'with' if embeddings else 'without'}} embeddings)."
        )'''


def _test_py(source: str, connector_pkg: str, connector_cls: str, verbs: list[str]) -> str:
    """Render a unit test mirroring tests/unit/_cli/test_csv.py."""
    func = _group_func(source)
    env = f"{source.upper().replace('-', '_')}_SOURCE"
    verb = verbs[0]
    key = f"{func}_{verb}"
    return f'''"""Unit tests for ``neocarta {source} {verb}``.

The connector requires a live Neo4j, so these tests cover CLI plumbing only:
--help shape, --dry-run side-effect-freeness, missing-config errors, the success
envelope, and library-error -> exit-code routing. End-to-end connector behaviour
is exercised by the integration suite.
"""

import json
from unittest.mock import MagicMock, patch

import pytest
from click.testing import CliRunner

from neocarta._cli import cli
from neocarta._cli.errors import EXIT_CODES
from neocarta.errors import (
    AuthError,
    ConfigError,
    Neo4jConnectionError,
    NeocartaError,
    RateLimitError,
)


def test_{verb}_help_documents_key_flags():
    runner = CliRunner()
    result = runner.invoke(cli, ["{source}", "{verb}", "--help"])
    assert result.exit_code == 0
    for token in ("--source", "--embeddings", "--no-embeddings", "--dry-run"):
        assert token in result.output, f"--help should document {{token}}"


def test_{verb}_dry_run_emits_json_and_skips_clients(monkeypatch):
    monkeypatch.setenv("{env}", "demo-source")
    runner = CliRunner()
    result = runner.invoke(cli, ["--json", "{source}", "{verb}", "--dry-run"])
    assert result.exit_code == 0, result.output
    body = json.loads(result.output)["{key}"]
    assert body["dry_run"] is True
    assert body["embeddings"] is False


def test_{verb}_missing_source_fails_with_usage_error(monkeypatch):
    # python-dotenv walks up from CWD for a .env; stub it and clear the env var.
    monkeypatch.setattr("neocarta._cli.config.load_dotenv", lambda *_a, **_kw: None)
    monkeypatch.delenv("{env}", raising=False)
    runner = CliRunner()
    result = runner.invoke(cli, ["--json", "{source}", "{verb}", "--dry-run"])
    assert result.exit_code == 2, result.stdout + result.stderr
    assert json.loads(result.stdout)["error"]["code"] == "usage_error"


@pytest.fixture
def _cli_env(monkeypatch):
    """Populate the env vars required for the command to start."""
    monkeypatch.setenv("NEO4J_URI", "bolt://localhost:7687")
    monkeypatch.setenv("NEO4J_USERNAME", "neo4j")
    monkeypatch.setenv("NEO4J_PASSWORD", "password")
    monkeypatch.setenv("{env}", "demo-source")


@pytest.mark.usefixtures("_cli_env")
def test_{verb}_success_emits_json():
    runner = CliRunner()
    with (
        patch("neocarta._cli.commands.{func}._neo4j_driver") as mock_driver_ctx,
        patch("neocarta.connectors.{connector_pkg}.{connector_cls}", return_value=MagicMock()),
    ):
        mock_driver_ctx.return_value.__enter__.return_value = MagicMock()
        mock_driver_ctx.return_value.__exit__.return_value = False
        result = runner.invoke(cli, ["--json", "{source}", "{verb}"])

    assert result.exit_code == 0, result.output
    out = result.output
    payload = json.loads(out[out.index("{{") :])
    assert payload["{key}"]["status"] == "succeeded"


@pytest.mark.parametrize(
    ("error", "expected_exit_code"),
    [
        (ConfigError("bad config"), EXIT_CODES["validation_error"]["code"]),
        (AuthError("bad credentials"), EXIT_CODES["auth_error"]["code"]),
        (RateLimitError("quota exceeded"), EXIT_CODES["rate_limited"]["code"]),
        (Neo4jConnectionError("Cannot reach Neo4j."), EXIT_CODES["upstream_error"]["code"]),
    ],
)
@pytest.mark.usefixtures("_cli_env")
def test_{verb}_routes_library_errors_to_exit_codes(error: NeocartaError, expected_exit_code: int):
    """Every NeocartaError raised from the connector becomes its CLI code."""
    runner = CliRunner()
    with (
        patch("neocarta._cli.commands.{func}._neo4j_driver") as mock_driver_ctx,
        patch("neocarta.connectors.{connector_pkg}.{connector_cls}", side_effect=error),
    ):
        mock_driver_ctx.return_value.__enter__.return_value = MagicMock()
        mock_driver_ctx.return_value.__exit__.return_value = False
        result = runner.invoke(cli, ["{source}", "{verb}"])

    assert result.exit_code == expected_exit_code, (
        f"{{type(error).__name__}} should exit {{expected_exit_code}}, got {{result.exit_code}}."
    )
'''


# --------------------------------------------------------------------------- #
# main.py wiring
# --------------------------------------------------------------------------- #
def _wire_main(source: str) -> str:
    """Insert the import + add_command for ``source`` into main.py, alphabetically.

    Idempotent: returns a status string and leaves main.py untouched if the
    wiring is already present.
    """
    func = _group_func(source)
    text = MAIN_PY.read_text()
    import_line = f"from .commands.{func} import {func}"
    add_line = f"cli.add_command({func})"

    if import_line in text and add_line in text:
        return "already wired"

    lines = text.splitlines()

    # 1. import: place among the existing `from .commands.X import X` block.
    import_re = re.compile(r"^from \.commands\.(\w+) import (\w+)$")
    import_idxs = [i for i, ln in enumerate(lines) if import_re.match(ln)]
    if import_line not in text and import_idxs:
        insert_at = import_idxs[-1] + 1
        for i in import_idxs:
            if import_re.match(lines[i]).group(1) > func:
                insert_at = i
                break
        lines.insert(insert_at, import_line)

    # 2. add_command: place among the existing `cli.add_command(X)` block.
    add_re = re.compile(r"^cli\.add_command\((\w+)\)$")
    add_idxs = [i for i, ln in enumerate(lines) if add_re.match(ln)]
    if add_line not in "\n".join(lines) and add_idxs:
        insert_at = add_idxs[-1] + 1
        for i in add_idxs:
            if add_re.match(lines[i]).group(1) > func:
                insert_at = i
                break
        lines.insert(insert_at, add_line)

    MAIN_PY.write_text("\n".join(lines) + "\n")
    return "wired"


def cmd_scaffold(args: argparse.Namespace) -> int:
    """Generate a command module + unit test and wire it into main.py."""
    source = args.source.strip("/").strip()
    func = _group_func(source)
    connector_pkg = args.connector_pkg or func
    verbs = args.verb or ["ingest"]

    classes = _connector_classes(connector_pkg)
    connector_cls = args.connector_class or (
        classes[0] if classes else f"{func.capitalize()}Connector"
    )
    if not classes:
        print(
            f"  WARN: neocarta.connectors.{connector_pkg} exports no *Connector "
            f"(using {connector_cls!r}); build the library connector first."
        )

    cmd_path = COMMANDS_DIR / f"{func}.py"
    if cmd_path.exists() and not args.force:
        print(f"ERROR: {cmd_path.relative_to(REPO_ROOT)} exists. Use --force to overwrite.")
        return 1

    cmd_path.write_text(_command_py(source, connector_pkg, connector_cls, verbs))
    print(f"  wrote {cmd_path.relative_to(REPO_ROOT)}")

    test_path = CLI_TESTS_DIR / f"test_{func}.py"
    if not test_path.exists() or args.force:
        test_path.write_text(_test_py(source, connector_pkg, connector_cls, verbs))
        print(f"  wrote {test_path.relative_to(REPO_ROOT)}")

    status = _wire_main(source)
    print(f"  main.py: {status}")

    env = f"{source.upper().replace('-', '_')}_SOURCE"
    print(f"\nScaffolded `neocarta {source} {' / '.join(verbs)}` wrapping {connector_cls}.")
    print("Next:")
    print(f"  1. Fill the TODOs in {cmd_path.relative_to(REPO_ROOT)} (constructor + ingest args).")
    print(
        f"  2. Promote the --source input to a CLISettings field + an ENV_VARS entry "
        f"({env}) in neocarta/_cli/config.py."
    )
    print("  3. Update CHANGELOG.md.")
    print(f"  4. uv run {pathlib.Path(__file__).relative_to(REPO_ROOT)} verify {source}")
    return 0


# --------------------------------------------------------------------------- #
# verify
# --------------------------------------------------------------------------- #
def cmd_verify(args: argparse.Namespace) -> int:
    """Check a command against the CLI contract; return a process exit code."""
    source = args.source.strip("/").strip()
    func = _group_func(source)
    cli_name = source.replace("_", "-")
    failures: list[str] = []

    print(f"== verifying `neocarta {cli_name}` ==")

    # 1. module imports + group object present
    try:
        module = importlib.import_module(f"neocarta._cli.commands.{func}")
    except Exception as exc:
        print(f"FAIL: cannot import neocarta._cli.commands.{func}: {type(exc).__name__}: {exc}")
        return 1
    group = getattr(module, func, None)
    if group is None:
        failures.append(f"module does not expose a `{func}` Click group")

    # 2. registered on the top-level cli group
    from neocarta._cli import cli as root_cli  # noqa: PLC0415

    registered = root_cli.commands.get(cli_name) or root_cli.commands.get(func)
    if registered is None:
        failures.append(f"`{cli_name}` is not registered in main.py (cli.add_command)")

    # 3. surfaced in agent-context + each verb's --help exits 0
    from click.testing import CliRunner  # noqa: PLC0415

    runner = CliRunner()
    ctx_result = runner.invoke(root_cli, ["agent-context"])
    if cli_name not in (ctx_result.output or ""):
        failures.append(f"`{cli_name}` missing from `neocarta agent-context` output")

    if registered is not None:
        for verb in registered.commands:
            r = runner.invoke(root_cli, [cli_name, verb, "--help"])
            if r.exit_code != 0:
                failures.append(f"`{cli_name} {verb} --help` exited {r.exit_code}")
            else:
                print(f"  {cli_name} {verb}: --help OK")

    for f in failures:
        print(f"  FAIL: {f}")

    # 4. ruff (format + lint) on the command module
    cmd_path = COMMANDS_DIR / f"{func}.py"
    ruff_rc = subprocess.run(  # noqa: S603
        ["uv", "run", "ruff", "check", str(cmd_path)],  # noqa: S607
        cwd=REPO_ROOT,
        check=False,
    ).returncode

    # 5. unit test, if present
    test_path = CLI_TESTS_DIR / f"test_{func}.py"
    pytest_rc = 0
    if test_path.exists():
        print(f"\n== running {test_path.relative_to(REPO_ROOT)} ==")
        pytest_rc = subprocess.run(  # noqa: S603
            ["uv", "run", "pytest", str(test_path), "-q"],  # noqa: S607
            cwd=REPO_ROOT,
            check=False,
        ).returncode
    else:
        print(f"  WARN: no unit test at {test_path.relative_to(REPO_ROOT)}")

    ok = not failures and ruff_rc == 0 and pytest_rc == 0
    print(f"\n{'PASS' if ok else 'FAIL'}: `neocarta {cli_name}`")
    return 0 if ok else 1


# --------------------------------------------------------------------------- #
# list
# --------------------------------------------------------------------------- #
def cmd_list(args: argparse.Namespace) -> int:
    """List every connector and whether it has a CLI command (gap map)."""
    have = _existing_command_stems()
    print(f"{'connector':14} {'CLI command?':14} exported connector class(es)")
    for entry in sorted(CONNECTORS_DIR.iterdir()):
        if not entry.is_dir() or entry.name in SKIP_CONNECTOR_DIRS:
            continue
        classes = _connector_classes(entry.name)
        has_cli = "yes" if entry.name in have else ("n/a (no class)" if not classes else "MISSING")
        print(f"{entry.name:14} {has_cli:14} {', '.join(classes) or '-'}")
    return 0


def main() -> int:
    """Parse argv and dispatch to the chosen subcommand."""
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_scaffold = sub.add_parser("scaffold", help="generate a command module + test, wire main.py")
    p_scaffold.add_argument("source", help="CLI group / module name, e.g. databricks")
    p_scaffold.add_argument("--verb", action="append", help="verb(s); repeatable (default: ingest)")
    p_scaffold.add_argument("--connector-pkg", help="connectors/ package (default: <source>)")
    p_scaffold.add_argument("--connector-class", help="connector class (default: first exported)")
    p_scaffold.add_argument("--force", action="store_true", help="overwrite existing files")
    p_scaffold.set_defaults(func=cmd_scaffold)

    p_verify = sub.add_parser("verify", help="check a command against the CLI contract")
    p_verify.add_argument("source", help="CLI group / module name, e.g. databricks")
    p_verify.set_defaults(func=cmd_verify)

    p_list = sub.add_parser("list", help="connector -> CLI-command gap map")
    p_list.set_defaults(func=cmd_list)

    args = parser.parse_args()
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
