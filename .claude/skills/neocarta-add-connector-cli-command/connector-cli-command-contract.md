# Neocarta connector CLI command contract

The standard every `neocarta <source> <verb>` command that wraps a **connector**
follows. This file is **self-contained**: the general agent-CLI principles below
were distilled from the design doc the CLI was built against, so you don't need
that doc to author a conformant command. The canonical *reference
implementations* are the existing connector command modules under
[neocarta/_cli/commands/](neocarta/_cli/commands/) — `csv.py` (simplest: one
connector, one verb), `bigquery.py` (two verbs, two connector classes), and
`osi.py` (a `format` connector with an `export` verb).

All paths are relative to the repo root.

## 0. Scope — connectors only, one connector's CLI per PR

This skill covers **source and format connector** commands and nothing else.
The neocarta CLI will also grow enrichment/embedding commands and MCP-tool
commands; those are **separate skills** with their own contracts — do not fold
them in here.

It is also the **follow-up** to the library-connector PR. The
`neocarta-add-source-connector` skill builds the package under
`neocarta/connectors/` and explicitly defers CLI wiring to here. Build (and
verify) the library connector first; this skill only wraps an already-working
connector in a CLI command.

## 1. The four foundations (non-negotiable)

Every command lives or dies by these. Fail one and an agent silently routes
around the command or burns tokens on it.

1. **Stable, machine-readable output.** JSON on stdout, diagnostics on stderr,
   never mixed. TTY auto-detected.
2. **A trustworthy contract.** Documented exit codes, idempotent where possible,
   non-interactive by default, predictable behaviour.
3. **In-band discoverability.** Three layers — `--help` (humans), `agent-context`
   (agents), `SKILL.md` (workflows).
4. **Compact output at the source.** No banners, no spinners-on-stdout, no
   "Using X" noise. Decorative output is forbidden on stdout.

## 2. Grammar: noun-verb

Every operation is `neocarta <source> <verb> [flags]`, exactly two levels deep.

- **Source (noun)** — lowercase, hyphenated when multi-word (`query-log`). The
  Click group *function* uses underscores (`query_log`); Click renders the
  command name with dashes automatically.
- **Verb** — the vocabulary is closed and consistent across connectors.
  Neocarta's established connector verbs:
  - `ingest` — read a source and load nodes/relationships into Neo4j (the common
    case: `csv ingest`, `osi ingest`, `query-log ingest`).
  - `schema` / `logs` / `glossary` — source-specific extraction shapes where a
    bare `ingest` would be ambiguous (`bigquery schema`, `bigquery logs`,
    `dataplex schema`, `dataplex glossary`).
  - `export` — serialise graph state back out to a file (format connectors only:
    `osi export`).

  Reuse an existing verb before coining a new one; a new verb is a deliberate,
  reviewed addition, not a per-connector synonym.

## 3. Anatomy of a connector command module

`neocarta/_cli/commands/<source>.py` contains:

1. A module docstring naming the verbs and the connector class(es) wrapped.
2. `from __future__ import annotations`.
3. A `@click.group()` function named `<source>` with a one-line docstring.
4. One `@<source>.command("<verb>")` function per verb.

Register it in [neocarta/_cli/main.py](neocarta/_cli/main.py): add the
`from .commands.<source> import <source>` import and a `cli.add_command(<source>)`
call (both kept alphabetical). **The driver does this wiring for you.**

## 4. The verb handler, in order

Every verb body runs the same spine (see `csv.py:csv_ingest`):

1. `settings = load_settings()` — env + `.env`, lowest priority after flags.
2. `require(...)` / `resolve(...)` for each required input. `resolve(flag,
   fallback)` prefers the flag; `require(name, value, env_var=...)` raises a
   `usage_error` `CLIError` (exit 2) with a fix-it suggestion when empty.
3. Apply `--embedding-model` / `--embedding-dimensions` onto `settings` if given.
4. `stdout = ctx.obj["stdout"]`, `stderr = ctx.obj["stderr"]`,
   `as_json = ctx.obj["as_json"] or json_flag`.
5. **`--dry-run` block**: build `{"<source>_<verb>": {"dry_run": True, ...}}`,
   emit via `emit_json` (JSON) or `stdout.print` (pretty), then `return` —
   before any client/credential work. Dry-run does zero side effects, exits 0.
6. `_require_neo4j_settings(settings)` — validates Neo4j creds.
7. **Lazy import** the connector inside the function (`# noqa: PLC0415`) so
   `--help`, `--dry-run`, and `agent-context` never import heavy deps.
8. `with _neo4j_driver(settings) as driver:` and a `try/except NeocartaError as
   exc: raise cli_error_from(exc) from exc` around the connector call. Wrap the
   work in `with cli_status(stderr, "Ingesting ..."):` for the spinner.
9. Optional embeddings: `_build_embedder(settings, driver)` then
   `_run_embeddings(embedder, node_labels)` (the latter normalises provider
   failures into a structured `upstream_error`).

   **Search entry point requirement:** `node_labels` must include **all**
   search-entry-point node labels the connector produces — not just the shared
   `DEFAULT_SCHEMA_NODE_LABELS`. If your connector adds nodes beyond
   Database/Schema/Table/Column that act as search entry points (e.g. `Metric`,
   `BusinessTerm`), the embedding label set must be connector-specific and
   include them. Without the embedding run there is no vector index, so the
   vector/hybrid tiers for that label never register in the MCP server.
10. Success: build `{"<source>_<verb>": {..., "status": "succeeded"}}` and emit
    the same way as step 5.

Shared helpers live in
[neocarta/_cli/commands/_common.py](neocarta/_cli/commands/_common.py):
`_require_neo4j_settings`, `_neo4j_driver`, `_build_embedder`, `_run_embeddings`,
`DEFAULT_SCHEMA_NODE_LABELS`. Reuse them — never reimplement the driver lifecycle
or unwrap the Neo4j password into a named local variable.

### 4a. The `export` verb (format connectors)

A `format` connector exposes **both** verbs: an `ingest` (read the format into
Neo4j, exactly as §4 above) **and** an `export` (read graph state back out to a
file in that format). `osi` is the reference — it has `osi ingest` *and* `osi
export` (`osi.py`). So a format connector's CLI module is the ingest command
plus an extra `export` command, not a different shape.

The `export` verb follows the same spine with three differences from ingest:

- It takes a required `--output-path` (a destination, so no env-var fallback)
  alongside the source selector (e.g. `--semantic-model-name`, env-backed). No
  `--embeddings` flags — export writes a file, not graph nodes.
- The connector call is `connector.export(...)`, not `ingest`.
- Map "the requested thing isn't in the graph" to `not_found` (exit 3): add a
  `except ValueError as exc: raise CLIError("not_found", str(exc),
  suggestion=...)` around the call, exactly as `osi export` does for an unknown
  model name.

The scaffold generates one ingest-shaped command per `--verb` (so `--verb ingest
--verb export` gives you both stubs); keep the `ingest` one and adapt the
`export` one against `osi.py`.

## 5. Flags

Long flags are `--lower-hyphenated`; booleans are `--flag/--no-flag` (never
`--flag=true`). The reserved names below have fixed meaning — never invent a
synonym (`--output json`, `--max`, etc. are banned):

- Source inputs: one `@click.option` each, `default=None`, help ending
  `Overrides <ENV_VAR>.` Resolved via `resolve(flag, settings.<field>)`.
- `--embeddings/--no-embeddings` (dest `embeddings`, `default=False`) on ingest
  verbs — embeddings are **opt-in everywhere**.
- `--embedding-model` (`default=None`) and, for schema-shaped loads,
  `--embedding-dimensions` (`type=int, default=None`).
- `--dry-run` (`is_flag`, `default=False`).
- `--json` (dest `json_flag`, `is_flag`) — local mirror of the top-level flag.
- `@click.pass_context`; the handler takes `ctx` then **keyword-only** options.

## 6. Config — `config.py`

Promote each new source input to a field on `CLISettings` with a
`validation_alias="<ENV_VAR>"`, and add a one-line entry to the `ENV_VARS` dict
(it is surfaced verbatim by `agent-context`, so it's the agent's env discovery
surface). Secrets use `SecretStr` plus a `require_secret(...)` check; never bind
the unwrapped value to a named local. (The scaffold initially reads the input
from `os.environ` with a TODO — replace that with the settings field.)

## 7. Output & stream discipline

- stdout carries **only** the result (pretty text or JSON). Diagnostics,
  progress spinners, warnings, and errors go to stderr. Zero exceptions.
- JSON auto-enables when stdout is not a TTY. Use `emit_json` for machine output
  and `stdout.print` for pretty.
- Single-result envelopes wrap the body under a key (here `"<source>_<verb>"`),
  never a bare object — leaves room for additive metadata later.
- Field names in JSON are **public API**: `snake_case`, never renamed or
  retyped after release (add + deprecate instead).
- Never `print()`; never emit ANSI when stdout isn't a TTY (honour `NO_COLOR` /
  `FORCE_COLOR`, handled by `make_consoles`).

## 8. Errors & exit codes

The closed exit-code map (in [neocarta/_cli/errors.py](neocarta/_cli/errors.py)):
`success` 0, `general_failure` 1, `usage_error` 2, `not_found` 3, `auth_error`
4, `conflict` 5, `validation_error` 6, `rate_limited` 7, `upstream_error` 8,
`timeout` 124. **Empty results are still exit 0** — never exit non-zero just
because a source had nothing to ingest.

- Library `NeocartaError`s carry a `code` that maps to an exit code via
  `cli_error_from`; wrap connector calls in `try/except NeocartaError`.
- Map any non-`NeocartaError` you must catch (e.g. a plain `ValueError` for "not
  found", as `osi export` does) to an explicit `CLIError(<code>, ...)`.
- Every error message answers two questions: **what went wrong** (name the bad
  input) and **what to do next** (the `suggestion=` field). In JSON mode the
  structured envelope goes to stdout under `{"error": ...}` with `code`,
  `exit_code`, `message`, `retryable`; a one-line summary always goes to stderr.
- Never emit raw tracebacks in normal output — they're gated behind `--debug`.

## 9. Discovery: `agent-context` is automatic

`neocarta agent-context` introspects the live command tree and emits
`schema_version`, `cli_version`, the full `commands` tree (flags + defaults +
choices), `exit_codes`, `error_codes`, and `env_vars`. A correctly registered
command — with its `ENV_VARS` entry — appears with no extra work. Don't
hand-maintain it; just confirm the command shows up (the driver's `verify`
checks this).

## 10. Tests — `tests/unit/_cli/test_<source>.py`

The connector needs a live Neo4j, so unit tests cover CLI plumbing only (the
real ingest is the integration suite's job). Mirror
[tests/unit/_cli/test_csv.py](tests/unit/_cli/test_csv.py), using Click's
`CliRunner`:

- `--help` documents the key flags.
- `--dry-run` emits JSON and touches no clients.
- Missing a required input → exit 2, `error.code == "usage_error"` (stub
  `load_dotenv` so the repo's own `.env` doesn't leak in).
- Success envelope, with `_neo4j_driver` and the connector class patched.
- A parametrized `NeocartaError` → exit-code routing check.

Run with `make test-cli` (note: `make test-unit` **deliberately ignores**
`tests/unit/_cli`). Then `make fmt && make lint` (the CLI is held to ruff
`select = ["ALL"]`), and update `CHANGELOG.md`. The scaffolded command and test
are ruff-clean and the test passes as generated, once the connector class it
wraps is importable.

## 11. Smoke checks before you open the PR

These are exactly what the driver's `verify` automates, but you can run them by
hand against any command:

```bash
uv run neocarta --version                       # fast, clean, exits 0
uv run neocarta <source> <verb> --help          # exits 0, lists flags
uv run neocarta agent-context | python3 -m json.tool >/dev/null   # valid JSON
SOME_ENV=x uv run neocarta --json <source> <verb> --dry-run       # exits 0, plan JSON
uv run neocarta <source> <verb>                 # missing required input → exit 2
```

## 12. Your command extends the public contract

The CLI's output is a public API — agents branch on flag names, verb names,
exit codes, error codes, env-var names, and every key in the JSON envelope.
Adding a connector command adds all of those, so treat them as durable:

- **Additive is a minor release; renames/removals are breaking.** Renaming a
  flag, a verb, a JSON field, or changing an exit code's meaning all break
  agents that already depend on them. Get the names right the first time
  (lean on §2 verbs and §5 flags so they match the rest of the CLI).
- **Envelope keys are forever.** The success/dry-run payload keys
  (`<source>_<verb>`, `status`, `database`, ...) ship as API. Add new keys
  rather than renaming; never change a key's type.
- **`agent-context` is the machine-readable contract.** It's generated from the
  live command tree, so a registered command is automatically part of the
  published surface — there's nothing to hand-maintain, but also nowhere to
  hide an inconsistency.
- **CHANGELOG.** Note the new command under the normal entry; call out any
  change to an *existing* command's flags/fields/exit codes explicitly as a
  contract change so downstream agents notice.

The bar to clear: an agent that has never seen this command, given only
`neocarta <source> --help` and `neocarta agent-context`, can run it end-to-end on
the first try — no tool errors, no hangs, no tokens wasted parsing output.
