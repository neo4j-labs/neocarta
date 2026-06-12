---
name: neocarta-add-connector-cli-command
description: Scaffold, wire, and verify a neocarta CLI command that wraps a source/format connector (the `neocarta <source> <verb>` integration that follows building the library connector). Use when asked to add/expose/wire a connector into the CLI, add a `neocarta <source>` subcommand, or check a connector command against the CLI contract. Connectors only — enrichment/embedding and MCP-tool CLI commands are separate skills.
---

Wire an existing source/format connector into the `neocarta` CLI as a
`neocarta <source> <verb>` command. This file is the **operational loop**; the
full prose standard lives in
[connector-cli-command-contract.md](.claude/skills/neocarta-add-connector-cli-command/connector-cli-command-contract.md)
(read it before designing a command — it's self-contained). Drive the whole loop
with the driver:
`.claude/skills/neocarta-add-connector-cli-command/scripts/driver.py`, run through `uv`.

All paths below are relative to the repo root.

## Scope

- **Connectors only.** This is for source/format connector commands. The CLI
  will also grow enrichment/embedding commands and MCP-tool commands — those are
  **separate skills**, not this one.
- **Follow-up PR, not the connector itself.** The library connector under
  `neocarta/connectors/` is built and verified by the
  `neocarta-add-source-connector` skill, which defers CLI wiring to here. Build
  the connector first; this skill wraps it.

## Prerequisites

The managed environment, with the CLI extras and dev groups installed:

```bash
uv sync --all-groups --all-extras
```

(`click`/`rich`/`pydantic-settings` are the `cli` *extra*, not a dependency
group, so plain `uv sync --all-groups` will not install the CLI — use
`--all-extras` too.)

## Run (agent path) — the driver

```bash
# Gap map: every connector and whether it already has a CLI command:
uv run .claude/skills/neocarta-add-connector-cli-command/scripts/driver.py list

# Scaffold a command module + unit test and wire it into main.py.
# <source> is the CLI group name (== command-module stem). By default the
# connector package is the same name and the first exported *Connector is used:
uv run .claude/skills/neocarta-add-connector-cli-command/scripts/driver.py scaffold databricks

# Point at a specific package / class, and/or give multiple verbs:
uv run .claude/skills/neocarta-add-connector-cli-command/scripts/driver.py \
  scaffold bigquery --connector-pkg bigquery --connector-class BigQuerySchemaConnector \
  --verb schema --verb logs

# Verify a command against the contract (import, registration, agent-context,
# --help, ruff, and its unit test):
uv run .claude/skills/neocarta-add-connector-cli-command/scripts/driver.py verify databricks
```

`scaffold` writes a conformant skeleton — `neocarta/_cli/commands/<source>.py`
(group + one ingest-shaped command per verb, with the dry-run / JSON / error
plumbing already correct) and `tests/unit/_cli/test_<source>.py` — and wires the
import + `cli.add_command` into `main.py` alphabetically (idempotent). The
skeleton's `--help` and `--dry-run` work and the generated test **passes as-is**
once the wrapped connector class is importable. You then fill the TODOs for the
connector's real constructor and `ingest()` signature.

`verify` imports the module, checks the group is registered on `cli`, confirms it
appears in `neocarta agent-context`, runs `--help` for each verb, runs `ruff
check` on the module, and runs the unit test. It exits non-zero on any failure.

### Typical workflow

1. `list` to confirm the connector exists and has no CLI command yet.
2. `scaffold <source>` (add `--connector-pkg` / `--connector-class` / repeated
   `--verb` as needed).
3. Fill the TODOs in `neocarta/_cli/commands/<source>.py`: the connector's real
   constructor args and `ingest()` (or `export()`) call, and the success/dry-run
   payload fields.
4. Promote the `--source` input to a `CLISettings` field + an `ENV_VARS` entry in
   [neocarta/_cli/config.py](neocarta/_cli/config.py) (see
   [contract §6](.claude/skills/neocarta-add-connector-cli-command/connector-cli-command-contract.md#6-config--configpy)),
   and resolve from `settings` instead of `os.environ`.
5. Flesh out the unit test for connector-specific behaviour beyond the skeleton.
6. `verify <source>` until green.
7. Run the full CLI suite + ruff, update `CHANGELOG.md`.

## Test

```bash
make test-cli           # CLI unit tests — NOTE: make test-unit ignores tests/unit/_cli
make fmt && make lint   # ruff format + lint (select = ["ALL"]) — must be clean before PR
make test-it            # integration: real ingest into a Neo4j testcontainer (Docker)
```

## Gotchas

- **`make test-unit` does not run the CLI tests.** They live under
  `tests/unit/_cli` which that target ignores; use `make test-cli` (the driver's
  `verify` runs the single new test file directly).
- **CLI deps are an extra, not a group.** `uv sync --all-groups` alone omits
  `click`/`rich`; the CLI then fails to import. Sync with `--all-extras`.
- **The scaffold reads its input from `os.environ`, deliberately.** That keeps
  the generated command + test self-contained and green before you touch
  `config.py`. Promote it to a `CLISettings` field (step 4) for the real PR — the
  house pattern resolves inputs from `settings`, not `os.environ`.
- **`agent-context` is generated, never hand-edited.** It introspects the live
  command tree; a registered command with its `ENV_VARS` entry shows up
  automatically. If it's missing, the command isn't registered in `main.py`.
- **Multiple connector classes / non-ingest shapes need hand-editing.** The
  scaffold emits one ingest-shaped command per `--verb`. A `schema`/`logs` split
  (like `bigquery`) or an `export` verb (like `osi`) starts from the scaffold,
  then adapt against `bigquery.py` / `osi.py`.
- **Don't unwrap the Neo4j password into a named local.** Use the `_common.py`
  helpers (`_require_neo4j_settings`, `_neo4j_driver`) as-is; they keep the
  secret off CodeQL's logging-sink radar.

## Troubleshooting

- **`verify` FAIL: `cannot import neocarta.connectors.<pkg>`** — the library
  connector isn't built/installed yet, or `--connector-pkg` is wrong. Build the
  connector first (the `neocarta-add-source-connector` skill).
- **`verify` FAIL: `<source>` is not registered in main.py** — re-run `scaffold`
  (the wiring step is idempotent) or add the import + `cli.add_command(<source>)`
  by hand, alphabetically.
- **`verify` FAIL: ruff** — run `make fmt` then `uv run ruff check
  neocarta/_cli/commands/<source>.py`; the generated skeleton is clean, so a
  failure is in a TODO you filled.
- **`scaffold` WARN: `exports no *Connector`** — the package has no connector
  class in `__all__` yet (e.g. `databricks`, `collibra` are work-in-progress).
  Pass `--connector-class` explicitly or finish the library connector first.
