# Review instructions

Review-only guidance for Neocarta, applied on top of the default Claude Code
review behavior and `CLAUDE.md`. Keep this file short — it is injected at high
priority into every review, and length dilutes the rules that matter.

## The controlling criteria are in the tickets, not only here

This file holds only part of the review criteria. Equal or higher authority is
the **acceptance criteria and stated intent** of the PR and every ticket it
closes; retrieving them (`gh pr view`, `gh issue view <n>`) is a **precondition**
— a review that has not read and applied them is not a review.

Apply them as criteria, not background: produce an **AC-by-AC verdict** — every
acceptance criterion marked met / unmet / unverified against the actual change.
"Is the code correct?" is not the test; "does it do what the ticket asked?" is.
An unmet or unverified AC **is a finding**, Important when it is the ticket's
core deliverable. When an AC demands a **demonstration** (a linked red CI run, a
proven-to-fail gate, a reproduction), that evidence must exist and be linked in
the PR — its absence is Important, not a pass.

## What "Important" (🔴) means here

Reserve Important for findings that would corrupt the graph, leak data or
secrets, or break the connector contract:

- Incorrect ETL logic in a connector's `extract` / `transform` / `load`.
- SQL built by interpolating **identifiers** (database/schema/table/column)
  without quoting + rejecting embedded quotes. Value literals must be bound
  parameters, never string-formatted.
- Secrets leaking: `NEO4J_PASSWORD`, `JDBC_PASSWORD`, `DATABRICKS_TOKEN`,
  `SNOWFLAKE_*` secrets, etc. must be `SecretStr`, **env-only** (never a CLI
  flag), never logged, and never bound to a named local variable.
- Actual table **data** (PII) crossing into Neo4j beyond the sampled `:Value`
  nodes — and value sampling must remain disable-able (e.g. `value_sample_limit=0`).
- Non-idempotent ingest or broken deterministic IDs (same input must yield the
  same `id` via `connectors/utils/generate_id.py`).
- A data-model change that updates only part of the chain: a new node/edge type
  needs `enums.py` + the `data_model/` model + the `ingest/` loader + constraint
  + the emitting transformer + (if searchable) the MCP tool, together.

Style, naming, and refactor suggestions are Nit (🟡) at most.

## Always check

- Behavior-changing code ships tests **in the same PR**: refactors captured in
  the S0 golden-master harness (parity proven before any legacy removal);
  net-new code covered by new tests without lowering the coverage floor. Flag a
  behavior change with no corresponding test add/update.
- New/changed connectors conform to `SourceConnectorProtocol` /
  `FormatConnectorProtocol` in `neocarta/connectors/_base.py` (extract →
  transform → load → ingest, `run`/`close`, context-manager, `_extracted` /
  `_transformed` guards raising `StateError` out of order) **and ship a
  conformance test**.
- Optional connector deps are lazy-imported (heavy imports inside handlers,
  `# noqa: PLC0415`) so the package imports **without** the optional extra;
  don't remove the smoke coverage that proves this.
- `CHANGELOG.md` is updated.
- New CLI commands emit the standard `{ "<command>": {...} }` JSON envelope,
  resolve settings **flag > env > default**, and support `--dry-run`.

## Do not report

- Anything CI already enforces: `ruff format` / `ruff check`, docstring
  (`pydocstyle`, google convention) violations.
- `uv.lock` and other generated files.
- Missing live-warehouse integration tests for cloud connectors — these are
  intentionally excluded from CI and validated manually.

## Nit volume

Post at most ~7 Nits inline; summarize any remainder as a count.
