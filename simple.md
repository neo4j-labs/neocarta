# Databricks Connector: Add Optional Inline Spark Embeddings

## Where this work happens

All of this work is done **directly on the `add-databricks-connector-from-dbxcarta` branch**. That branch already holds the migrated connector at `neocarta/connectors/databricks/` that every phase below edits. Do **not** create a new branch — commit changes onto `add-databricks-connector-from-dbxcarta` itself. The inline embedding source being ported (`embeddings.py`, `embed_stage.py`, `staging.py`, `ledger.py`, `setup-openai-endpoint.py`, and the Spark tests) lives under `dbxcarta/` and is brought into the connector on that same branch.

Order of work: implement Phases 1, 2, and 3 on the branch, then Phase 3.5 (write a handoff/test document describing what was done and what still needs live testing), then run live verification against the branch. **All live verification (external and inline end-to-end runs) is this single post-3.5 pass** — the per-phase "verify end to end" notes are deferred to it, because they require a live Databricks cluster and Neo4j. Phases 1-3 ship code plus unit/smoke tests only.

## Summary

The branch `add-databricks-connector-from-dbxcarta` migrated the old `dbxcarta-spark` work into a proper neocarta connector at `neocarta/connectors/databricks/`. During that migration the Spark embedding code was dropped. The new connector now produces the graph with no vectors and expects embeddings to be added later by neocarta's separate enrichment layer. We call this the "external" mode.

This plan does two things:

1. Adds an optional flag so the connector can either generate embeddings inside the Spark job (inline) or leave them to the enrichment layer (external, the current behavior). Both are equal, fully supported modes; external is the default behavior only because the inline flags default to off.
2. Ports the proven inline embedding code from the current `dbxcarta` branch into the new connector.

It also lists the other gaps that must be closed before the connector pipeline can run end to end, regardless of embeddings.

The good news: the inline embedding code already exists, is tested, and uses no extra Python dependencies. It runs embeddings as a native Spark `ai_query()` call against a Databricks model serving endpoint, so the work is mostly porting and re-wiring, not new design.

---

## How embeddings work in each mode

**External mode (current default, keep it):**
- The Spark job writes Database, Schema, Table, Column, and Value nodes with no `embedding` property.
- No vector indexes are created.
- A separate run of `neocarta.enrichment` adds vectors afterward.

**Inline mode (what we are adding back):**
- During the node-write loop, each batch runs `ai_query('<endpoint>', embedding_text, failOnError => false)` natively in Spark. No Python UDFs, no driver-side collection of table data.
- The embedding text per node type comes from a single `EMBEDDING_TEXT_EXPR` map (for example a Column embeds its fully qualified name plus data type plus comment).
- Each node type can be turned on independently (tables, columns, values, schemas, databases). All default to off.
- A per-label cosine vector index named `{Label}_vector_index` is created when that label's flag is on. Value is written but not indexed, matching the original design.
- A failure gate can abort a batch before it is written to Neo4j if too many rows fail to embed.
- An optional cross-run "ledger" cache can skip `ai_query` for unchanged nodes.

**Which mode to pick.** Both modes are fully supported and documented as equals. There is no single recommended path; the choice depends on the environment.
- Pick **inline** when the work already runs on a Databricks cluster and you want one job to produce a fully embedded graph. It embeds in-cluster with `ai_query` against a Databricks serving endpoint, uses Spark's distributed compute, and needs no second process or external embedding provider.
- Pick **external** when you want embeddings decoupled from ingest, want to use the same `neocarta.enrichment` embedding path as the other connectors (for example an OpenAI model), or want to (re)embed without re-running the Spark job. This is a separate step after ingest.

The default behavior is external, because all inline flags default to off. That is a default, not a recommendation: turning inline on is a first-class supported choice.

**Embedding model and dimension consistency.** Each mode owns its own vector index config. Inline mode defaults to the Databricks `databricks-gte-large-en` endpoint at 1024 dimensions; external mode uses whatever `neocarta.enrichment` is pointed at, for example OpenAI `text-embedding-3-small`. These produce different vectors at different dimensions, so two rules apply and must be documented and warned about in the inline path:
- You cannot mix modes against the same graph without rebuilding the vector index, because the index is created at one fixed dimension.
- If this graph holds data from more than one neocarta datasource, the inline embedding model and dimension must match what the rest of neocarta uses, or vector search across sources will be inconsistent. The inline path should warn when its configured dimension is set so the operator notices this.

To make inline match an OpenAI-based neocarta graph, the branch already includes `dbxcarta/scripts/setup-openai-endpoint.py`. It registers a Databricks Mosaic AI "External Models" serving endpoint that proxies OpenAI `text-embedding-3-small` (1536-dim) and is reachable through the same `ai_query` path inline ingest uses. So inline mode is not locked to the Databricks foundation model: point the inline endpoint at this external-model endpoint and inline produces OpenAI vectors that line up with the rest of neocarta. Set the inline dimension to match the chosen endpoint.

---

## What needs to be done

### A. The optional flag and inline embedding (the main request)

- Add embedding settings to `neocarta/connectors/databricks/settings.py`: the five per-label on/off flags, embedding endpoint, embedding dimension, batch size, failure-max gate, and the ledger flags. All default off, so external mode is unchanged.
  - *Settings naming (decided):* the source carries these as `DBXCARTA_*` env vars / `dbxcarta_*` field names, but the target connector's `settings.py` uses `env_prefix="NEOCARTA_DATABRICKS_"` with bare field names (`include_values`, etc.). **Rename every ported embedding setting to that convention**: `include_embeddings_tables`, `embedding_endpoint`, `embedding_dimension`, `embedding_failure_max`, `ledger_enabled`, etc., read from `NEOCARTA_DATABRICKS_*`. No `dbxcarta_`-prefixed field or `DBXCARTA_*` env var survives the port. Update the failure-gate, endpoint, and ledger-path validators to reference the renamed fields/vars.
- Add a cross-field validator so embedding Values requires value sampling to be on (`include_embeddings_values` requires `include_values`).
- Port `embeddings.py` (the `ai_query` primitive, dimension validation, failure stats) into the connector under `ingest/transform/`. Its only external dependency is `validate_serving_endpoint_name`, which **already exists** in the connector at `_platform/identifiers.py`; the import just re-points there, so no validator is rebuilt.
- Port `embed_stage.py` (the per-batch embed-and-write orchestration plus the failure gate). Note that `embedded_batch` calls the ledger functions inline (flag-gated), so the ledger module must be present for this file to import even when the ledger is off (see Phase 3 / Phase 4 below).
- Add the `EmbeddingCounts` dataclass (per-label `attempts`/`successes`/`ledger_hits` plus the derived `failure_rate_per_label`/`aggregate_failure_rate` reporting fields) and an `embeddings` field to the connector's `RunSummary` in `ingest/summary.py`. The source has this; the migrated connector dropped it, and `embedded_batch` accumulates into `summary.embeddings`, so it is a prerequisite for the port — not optional.
- Port `staging.py` (transient Delta write-and-read so `ai_query` runs exactly once per item).
- Port `ledger.py` plus its settings if we want the cross-run cache. The module is ported **inert** in Phase 3 (so `embed_stage.py` imports cleanly) but its flag stays off and its settings wiring + tests land in Phase 4. See the Phase 3 / Phase 4 notes.
- Add `EMBEDDING_TEXT_EXPR`, the `embedding` property, and the default endpoint constant to the connector's `contract.py`, and make the node builders in `schema_graph.py` and `sample_values.py` attach the `embedding_text` column.
- Add the embedding preflight check (ping the endpoint, confirm the returned vector length matches the configured dimension) to `ingest/preflight.py`.
- Create the per-label `{Label}_vector_index` cosine indexes in `ingest/load/neo4j_io.py` when inline mode is on.
- Change the node-write path in `run.py` so that, when embeddings are enabled, writes go through the batched embed-and-write loop; when disabled, the current direct write is used unchanged.
- Port the embedding and ledger tests from `dbxcarta/tests/spark/embeddings/` and `dbxcarta/tests/spark/ledger/` into the connector's test tree.

### B. Other gaps that block the connector pipeline (found during review)

These are independent of embeddings. The pipeline cannot be exercised cleanly without them.

- **No CLI wiring.** There is no `neocarta/_cli/commands/databricks.py` and no `cli.add_command(databricks)` in `_cli/main.py`. **Decision: add a Databricks CLI command scoped to the enrichment hand-off, matching the other connectors.** The schema ingest itself stays a Spark wheel job on a cluster, because it writes through the Neo4j Spark Connector and cannot run in-process off-cluster. The enrichment embedding step is different: it reads nodes from Neo4j, calls an embedding model, and writes vectors back, all in-process, so it fits the CLI cleanly. The new command takes the same flags as CSV (`--embeddings/--no-embeddings`, `--embedding-model`, `--embedding-dimensions`) and runs `neocarta.enrichment.embeddings` against the graph the Spark job produced. This is the external-mode hand-off as a first-class command rather than an undocumented manual step. Update the docs to show the full two-step flow: run the Spark ingest job, then run the CLI embedding command.
  - *Confirmed scope:* this CLI command does external enrichment only and does not launch the Spark ingest. Inline embeddings remain a setting on the Spark job, not a CLI flag.

- **No tests at all.** There is no `tests/unit/connectors/databricks/` directory. The `Makefile` target `test-databricks` points at that missing path and fails immediately. The `pyproject.toml` ruff ignore list also references the missing path.

  *How the other connectors are tested:* each one has a folder under `tests/unit/connectors/<name>/` with a `conftest.py` plus `test_extract.py` and `test_transform.py` that exercise the pure extract/transform logic against fixtures, with no live service. BigQuery adds `test_errors.py`; OSI adds `test_connector_version.py`.

  **Decision: split the tests by what they actually need, and keep as much as possible in the normal pattern.** The honest constraint is that the other connectors transform plain Python data (dicts, pandas), so their tests need no Spark, while the Databricks connector's transform logic *is* Spark, so faithful tests of it need a SparkSession. We do not fake Spark away to dodge the dependency, because a test that mocks out Spark would prove nothing about Spark code. The split:
  - **Pure-Python tests in the normal unit suite (no PySpark):** settings validators, and the `EMBEDDING_TEXT_EXPR` map and contract derivations. These follow the existing connector pattern exactly and run in the default test group.
  - **Spark-logic tests under the `databricks` dependency group:** the embed primitive, failure gate, and ledger join logic. These use a local SparkSession, not a Databricks cluster. `ai_query` cannot run in local Spark, so those specific paths stay covered by the integration suite, exactly as they were in dbxcarta. The `test-databricks` Make target already runs with `--group databricks`, so this split fits the existing tooling.
  - The existing `dbxcarta/tests/spark/embeddings/` and `dbxcarta/tests/spark/ledger/` tests are the source to port for the Spark-logic group.

- **Dangling reference to deleted code.** `ingest/contract_expr.py` claims a `verify.catalog` module enforces id agreement, but that module was deleted and never migrated. The id-agreement guarantee is currently unverified. Either restore a check or correct the docstring.

  *What did this check actually do (in plain terms)?* It ran at the **end** of a run, after the Spark ingest finished, using a SQL warehouse to read the catalog and the Neo4j driver to read the graph. It did two things. First, it grabbed a sample of real columns from the catalog, worked out what each one's node id should be, and confirmed those nodes actually exist in Neo4j, catching "rows we expected never landed in the graph." Second, it built the id for the same rows two ways, once in Python and once in Spark SQL, and confirmed the two strings matched exactly, catching "Python and Spark disagree on how to spell an id," which would silently break relationships. It was a post-run verification step, not a stage of the ingest pipeline itself.

  **Decision: drop it.** It is not part of the Spark ingest pipeline, so it is out of scope. The only required change is to fix the `contract_expr.py` docstring so it no longer points at the deleted `verify.catalog` module. No check is restored; if id-agreement coverage is wanted later, it belongs with the separate verify subsystem as its own feature.

- **Stale, misleading docstrings.** `value_stage.py`, `extract.py`, and `transform/__init__.py` still describe an embed-and-chunk-loop and a settings validator that no longer exist in the new connector.

  *Is this the run-summary feature?* No, and it is not the verify feature either. These are cosmetic docstrings left behind by the embedding removal. Porting embeddings back in Phase 3 makes most of them accurate again; the remainder is a few one-line doc edits.

  **Decision: add a dedicated docs-review stage.** A final pass sweeps every docstring and README in the connector to confirm none still describe removed behavior, so the stale-docstring problem does not survive in a quieter form. This becomes its own step in Phase 5.

- **No automated hand-off to enrichment.** In external mode nothing runs the enrichment pass that adds vectors. Document the required follow-up so a user gets an actual semantic layer rather than a vector-free graph.

  *How the other connectors handle this:* the CSV CLI command takes `--embeddings/--no-embeddings`, `--embedding-model`, and `--embedding-dimensions`, and runs `neocarta.enrichment.embeddings` as an optional post-ingest step inside the same command (OpenAI `text-embedding-3-small`, 768 dims by default).

  **Decision: give Databricks the same CLI embedding step.** The new command runs `neocarta.enrichment.embeddings` and takes the same three flags as CSV. This makes the external-mode hand-off a real, documented command instead of a manual step a user has to know to run. See the CLI decision above for how this command relates to the Spark ingest job. Update the docs to show the two-step external flow.

- **No smoke import coverage.** `tests/smoke/test_imports.py` does not import the Databricks connector. Add it so a broken import is caught early.

  *How the other connectors handle this:* the file has one `test_<name>_connector_imports()` per connector that imports the connector's public classes and asserts they are present.

  **Decision: add it.** A `test_databricks_connector_imports()` imports `DatabricksSparkSchemaConnector` and asserts it is present, matching the existing per-connector smoke tests.

---

## Phased implementation plan

### Phase 0: Scope and decisions (finalized)
- External and inline are two equal, fully supported modes. External is the default behavior because the inline flags default to off.
- All ported embedding settings use the connector's `NEOCARTA_DATABRICKS_*` env prefix / bare field-name convention; no `DBXCARTA_*` env var or `dbxcarta_*` field survives the port.
- `embeddings.py`'s `validate_serving_endpoint_name` dependency already exists in the connector (`_platform/identifiers.py`); it is re-pointed, not rebuilt.
- The connector's `RunSummary` needs the `EmbeddingCounts` shape added back (in Phase 3, as the first step before `embed_stage.py` lands) because `embedded_batch` accumulates into it.
- `ledger.py` is ported inert in Phase 3 so `embed_stage.py` imports cleanly; the ledger flag, settings, and tests are Phase 4.
- All live (cluster + Neo4j) verification is a single pass after Phase 3.5; the per-phase end-to-end checks are deferred to it.
- Add a Databricks CLI command scoped to the external enrichment hand-off (the `--embeddings` flags running `neocarta.enrichment.embeddings`). The Spark ingest itself stays a cluster wheel job, and the CLI does not launch it.
- Drop the id-normalization check; it was a post-run verification step, not part of the Spark pipeline. Only fix the dangling docstring.
- Each mode owns its vector index config; inline must warn about model/dimension consistency and the no-mixing-without-rebuild rule.
- The ledger cache stays a separate, later phase (Phase 4).

### Phase 1: Close the blocking gaps (no inline embeddings yet) — ✅ COMPLETE
- [x] Create `tests/unit/connectors/databricks/` with the pure-Python tests in the normal unit group and the Spark-logic tests under the `databricks` group, so the `test-databricks` Make target and ruff ignore path are valid.
  - Added `__init__.py`, `conftest.py` (ported `local_spark` + `_isolate_environ` fixtures from the dbxcarta root conftest, with pyspark imported lazily so the conftest loads in the default group), `test_settings.py` (8 validator/helper tests), `test_contract.py` (5 derivation tests). All pure-Python (no PySpark), so they run in both `make test-unit` and `make test-databricks`. No Spark-logic tests yet — the embed/ledger Spark tests land in Phase 3/4.
- [x] Add `test_databricks_connector_imports()` to `tests/smoke/test_imports.py` (imports `DatabricksSparkSchemaConnector`).
- [x] Add the Databricks CLI command (`neocarta/_cli/commands/databricks.py` plus `cli.add_command(databricks)`).
  - **Decision (user, deviates from this line):** verb is `embed` (not a `--embeddings`-gated ingest), and the `--embeddings/--no-embeddings` toggle was **dropped** — the command's sole job is embedding, so it always embeds. Flags: `--embedding-model`, `--embedding-dimensions`, `--dry-run`, `--json`. Runs `neocarta.enrichment.embeddings` (via the shared `_build_embedder`) over Database/Schema/Table/Column. External-mode hand-off only; does not launch the Spark ingest.
- [x] Fix the `contract_expr.py` docstring so it no longer references the deleted `verify.catalog` module. Do not restore the check.
  - Done. **Note:** the same docstring's `contract.generate_id`/`generate_value_id` reference may also be stale (ids are produced in `neocarta.connectors.utils` per `contract.py`); left for the Phase 5 docs-review sweep to stay in Phase 1 scope.
- [x] **(Added per user) Port FK tests so the full `test-databricks` target passes.** The target also lists `tests/unit/enrichment/foreign_keys`, which did not exist (a second dangling path the plan text didn't mention).
  - Created `tests/unit/enrichment/foreign_keys/` with `__init__.py` + `test_rules.py` (21 tests). This is a faithful, API-adapted port of the dbxcarta `fk_common` + `fk_metadata` **rule-layer** tests against the migrated Spark-free `neocarta.enrichment.foreign_keys.rules` (canonicalize, types_compatible, comment_tokens, build_id_cols_index, pk_evidence, source/target match keys, score).
  - **Not ported (API changed in migration — flag for follow-up, out of Phase 1 scope):** (a) connector-side Spark `fk_declared`/`fk_discovery`/`fk_guard` tests target `neocarta/connectors/databricks/ingest/fk/declared.py`+`discovery.py` and belong under `tests/unit/connectors/databricks/` as Spark-logic tests; (b) the `fk_metadata` **Spark pipeline** tests (`build_columns_frame`/`build_pk_gate`/`infer_metadata_edges`) and `verify.references` tests target code **deleted** in the migration (Spark evaluation replaced by in-process `infer.py`, verify subsystem dropped). The dbxcarta `fk_common` `PKIndex`/`ConstraintRow`/`pk_kind` API no longer exists (PK-likeness is now an `is_primary_key` boolean), so those could not be ported verbatim. `infer.py` (in-process, neo4j-driver-driven) has no unit test yet.
- *Live verification deferred:* the external-mode end-to-end run (Spark ingest against a test catalog, then the CLI embedding command against the resulting graph) needs a live Databricks cluster + Neo4j and happens in the single post-3.5 live pass, not at the end of this phase. Phase 1 ships code + unit/smoke tests only.

**Phase 1 validation:** `make test-databricks` → 34 passed (13 connector + 21 FK rules). Default-group run (no PySpark) of the same dirs + smoke → 45 passed. `ruff check` clean on all changed files. `ruff format` clean. `neocarta databricks embed --help` / `--dry-run --json` verified.

### Phase 2: Add the embedding settings and contract surface
- Add the embedding settings and the cross-field validator to `settings.py`.
- Add `EMBEDDING_TEXT_EXPR`, the `embedding` property, and the default endpoint to `contract.py`.
- Update the node builders to attach `embedding_text`.
- Add the embedding preflight check.
- These changes are inert while all flags are off, so external mode keeps working.

### Phase 3: Port the inline embedding pipeline
- Add the `EmbeddingCounts` dataclass + `embeddings` field to the connector's `RunSummary` (`ingest/summary.py`) first, since `embed_stage.py` accumulates into it.
- Port `embeddings.py`, `embed_stage.py`, and `staging.py` into `ingest/transform/`.
- Add the batched embed-and-write loop in `run.py`, gated by the flags.
- Create the per-label vector indexes in `neo4j_io.py` when inline mode is on, at the configured dimension. Each mode owns this config.
- Emit a warning when inline is enabled, stating the configured model/dimension and that it must match the rest of neocarta when the graph spans multiple datasources, and that modes cannot be mixed on one graph without rebuilding the index.
- Port `ledger.py` **inert** alongside `embed_stage.py` so the embed stage imports cleanly with the ledger branch present but flag-off. Its settings wiring and tests are Phase 4; do not delete the ledger calls from `embedded_batch`.
- Port the embedding unit tests.
- *Live verification deferred:* inline-mode end-to-end testing against a catalog with a real serving endpoint (one label at a time, covering both the default Databricks `databricks-gte-large-en` endpoint and the OpenAI external-model endpoint from `setup-openai-endpoint.py`) needs a live cluster and is part of the single post-3.5 live pass, not this phase. Phase 3 ships code + unit tests only.

### Phase 4: Optional ledger cache
`ledger.py` was already ported inert in Phase 3 so `embed_stage.py` could import it; Phase 4 turns it on as a supported option.
- Add the renamed `NEOCARTA_DATABRICKS_LEDGER_*` settings (`ledger_enabled`, `ledger_path`) and their validators.
- Confirm the ledger branch in `embedded_batch` is exercised once the flag is on (the call sites already exist from Phase 3).
- Port the ledger tests from `dbxcarta/tests/spark/ledger/`.

**What the ledger cache is:** a cross-run cache that lets the pipeline skip the `ai_query` embedding call for nodes that have not changed since the last run. Each embedded node stores the SHA-256 hash of the exact text that was embedded. The ledger keeps a small Delta table per label holding `id`, that text hash, the resulting vector, the model name, and a timestamp. On the next run, before calling `ai_query`, the pipeline joins against the ledger: a node is a "hit" when its id, model, and text hash all match, in which case the stored vector is reused and no embedding call is made. Only "misses" go to `ai_query`. After a successful batch the new vectors are merged back into the ledger.

The point of it is cost and speed. Embedding calls cost money and time, and most metadata does not change between runs, so a re-run normally re-embeds thousands of identical strings for no reason. The ledger turns a full re-embed into embedding only the rows whose text actually changed. It is gated by its own flag (`NEOCARTA_DATABRICKS_LEDGER_ENABLED`) and is off by default, so it can be deferred to a later phase without affecting correctness. The trade-off is added Delta storage and merge logic, which is why it is optional rather than always on.

**Decision: keep this as its own Phase 4**, after inline embeddings are working, rather than bundling it into the first inline release.

### Phase 5: Cleanup and documentation
- **Docs-review stage:** sweep every docstring and README in the connector and confirm none still describe removed behavior (the embed-and-chunk-loop, removed validators, the unmigrated verify subsystem).
- Document both modes as equals in the connector README, including a "which mode to pick" section and the two-step external flow (Spark ingest job, then the CLI embedding command).
- Update `CHANGELOG.md`.
- Run `make fmt`, `make lint`, and the full test suite.

---

## Notes on the embedding mechanism (for reference)

- Embeddings run as `ai_query('<endpoint>', embedding_text, failOnError => false)` distributed across Spark. No Python UDF and no extra pip dependency.
- The default endpoint is `databricks-gte-large-en` at dimension 1024. The dimension is configurable and is checked against the endpoint at preflight.
- The result is frozen to a transient Delta path and read back so `ai_query` runs exactly once per item, and the same frozen result feeds both the failure gate and the Neo4j write.
- Only the `embedding` vector reaches the graph. All bookkeeping columns (text hash, model, timestamp, error) are stripped by the fail-closed projection before the write.
- Vector indexes use cosine similarity and follow the `{Label}_vector_index` naming the MCP layer already expects.
