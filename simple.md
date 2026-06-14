# Databricks Connector: Add Optional Inline Spark Embeddings

## Where this work happens

All of this work is done **directly on the `add-databricks-connector-from-dbxcarta` branch**, and **every new or changed file lands inside the `neocarta/connectors/databricks/` directory** (plus that connector's test tree). That branch already holds the migrated connector at `neocarta/connectors/databricks/` that every phase below edits. Do **not** create a new branch — commit changes onto `add-databricks-connector-from-dbxcarta` itself. The single goal of this plan is to update that one connector to add embeddings; nothing outside `neocarta/connectors/databricks/` (and its tests) should change.

**Where the embedding code comes from, and how to copy it.** The inline embedding source (`embeddings.py`, `embed_stage.py`, `staging.py`, `ledger.py`, the `EmbeddingCounts`/`RunSummary` shape, the `run.py` write loop, the `neo4j_io.py` index creation, the settings/contract/preflight additions, and the Spark tests) is **not present on this branch** — it was dropped during the migration and now lives only on the separate **`dbxcarta` branch**, under `dbxcarta/dbxcarta-spark/src/dbxcarta/spark/` (tests under `dbxcarta/tests/spark/embeddings/` and `dbxcarta/tests/spark/ledger/`). Read each source file from that branch with `git show dbxcarta:<path>` and write the adapted version directly into `neocarta/connectors/databricks/`. This is the cleanest method because every file needs renaming, re-pathing, and import re-pointing anyway; `git checkout dbxcarta -- <path>` is avoided because it would restore files at their original `dbxcarta/dbxcarta-spark/...` paths and stage them, forcing an extra move. The `setup-openai-endpoint.py` helper script also lives on the `dbxcarta` branch and is copied the same way.

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

### Phase 2: Add the embedding settings and contract surface — ✅ COMPLETE

All files in this phase live under `neocarta/connectors/databricks/`; the source for each is read from the `dbxcarta` branch with `git show dbxcarta:<path>` (see "Where the embedding code comes from" above).

**How settings are added (native integration, no new file).** The connector already manages its own configuration in `neocarta/connectors/databricks/settings.py`: a single `SparkIngestSettings(BaseSettings)` class built on `pydantic_settings.BaseSettings`, with `model_config = SettingsConfigDict(env_prefix="NEOCARTA_DATABRICKS_")`, bare field names (`include_values`, `sample_limit`, …), and `@field_validator` methods. This is the established neocarta pattern for this connector. The embedding settings are therefore **added as new fields on that existing class**, not as a new settings module: each ported `DBXCARTA_*` setting becomes a bare field read from `NEOCARTA_DATABRICKS_*` (`include_embeddings_tables`, `embedding_endpoint`, `embedding_dimension`, `embedding_failure_max`, …), and the cross-field/endpoint validators become `@field_validator`/`@model_validator` methods on the same class. No `DBXCARTA_*` env var or `dbxcarta_*` field name survives.

- [x] Add the embedding settings (the five per-label flags, endpoint, dimension, batch size, failure-max gate) and the cross-field validator (`include_embeddings_values` requires `include_values`) as new fields/validators on `SparkIngestSettings` in `settings.py`. Source: `dbxcarta` branch `…/spark/settings.py`.
  - Added `include_embeddings_{tables,columns,values,schemas,databases}` (all `False`), `embedding_endpoint` (defaults to `DEFAULT_EMBEDDING_ENDPOINT`), `embedding_dimension` (1024), `embedding_batch_tables` (200), `embedding_failure_max` (0), all read from `NEOCARTA_DATABRICKS_*`. Validators ported and renamed: `_validate_embedding_batch_tables` (>= 1), `_validate_embedding_failure_max` (>= 0), `_validate_embedding_endpoint` (re-points to the connector's `validate_serving_endpoint_name`), and the `@model_validator` `_validate_feature_coherence` (value embeddings require `include_values`). **Ledger fields are NOT added here — correctly deferred to Phase 4.**
  - **Added (small, not literally in the plan):** an `any_embeddings_enabled()` helper on `SparkIngestSettings` (mirrors the existing `resolved_catalogs()`/`layer_map()` helpers). It is the single external/inline switch consumed by the new preflight check and by run.py in Phase 3, replacing the source's inlined `any([...])`.
- [x] Add `EMBEDDING_TEXT_EXPR`, the `embedding` property, and the default endpoint to `contract.py`. Source: `dbxcarta` branch `…/spark/contract.py`.
  - Added `DEFAULT_EMBEDDING_ENDPOINT = "databricks-gte-large-en"` and the `EMBEDDING_TEXT_EXPR` map (one expr per managed label, catalog-leading for Table/Column/Schema). **The `embedding` property was already present** — the migrated connector derives `NODE_PROPERTIES` from the Pydantic models, and every core model (plus `DatabricksValue`) already declares `embedding`, so no contract change was needed for it. A test now pins this.
- [x] Update the node builders in `ingest/schema_graph.py` and `ingest/transform/sample_values.py` to attach `embedding_text`. Source: `dbxcarta` branch `…/spark/ingest/schema_graph.py` and `…/spark/ingest/transform/sample_values.py`.
  - All four `schema_graph` builders and the `sample_values` Value builder now attach a transient `embedding_text` column. The `run.py:_project` write boundary already strips any column not in `NODE_PROPERTIES`, so attaching it unconditionally is inert in external mode (verified by a test).
- [x] Add the embedding preflight check to `ingest/preflight.py`. Source: `dbxcarta` branch `…/spark/ingest/preflight.py`.
  - Added `_assert_embedding_endpoint`, gated on `settings.any_embeddings_enabled()`: it sends a trivial `ai_query` and fails the run if the endpoint is unreachable, errors, or returns a vector whose length ≠ `embedding_dimension`. Only the embedding check was ported; the source's summary-volume/table provisioning is not part of this migrated connector and stays out of scope.
- [x] These changes are inert while all flags are off, so external mode keeps working. (Confirmed: default-group + databricks-group suites pass with flags off; `_project` strips `embedding_text`.)
- **Tests added:** `test_settings.py` +7 (embedding validators, coherence, `any_embeddings_enabled`, external-default), `test_contract.py` +5 (`EMBEDDING_TEXT_EXPR` coverage/transience, `embedding` declared per label, default endpoint). **New Spark-logic file** `test_schema_graph.py` (6 tests, `importorskip` guarded) verifies the builders actually attach `embedding_text` against a local SparkSession — this is the first Spark-logic test (Phase 1 deferred them to "Phase 3/4"); added here because it directly validates this phase's builder change and is faithful (real Spark, no mocks).

**Phase 2 validation:** `make test-databricks` equivalent (`tests/unit/connectors/databricks` + `tests/unit/enrichment/foreign_keys`, `--group databricks`) → 51 passed. Default-group (no PySpark) of the connector tests + smoke → 41 passed (Spark-logic module skipped cleanly). `ruff check` + `ruff format` clean on all changed files. Live endpoint-reachability preflight is exercised in the single post-3.5 live pass.

### Phase 3: Port the inline embedding pipeline — ✅ COMPLETE

All files in this phase live under `neocarta/connectors/databricks/` (and its test tree); the source for each is read from the `dbxcarta` branch with `git show dbxcarta:<path>` (see "Where the embedding code comes from" above). Apply the Phase-0 renames and re-point the `validate_serving_endpoint_name` import to the connector's existing `_platform/identifiers.py`.

**Drift resolved (user-approved before implementation).** Two settings the plan assumed survived the migration did not, and both are required to port inline faithfully:
- *Staging volume.* The transient per-batch Delta materialization (`staging.py`) needs a writable UC Volume path, which `dbxcarta` derived from the now-dropped `DBXCARTA_SUMMARY_VOLUME` (the whole `summary_io` machinery was dropped and is **not** restored — it served the unmigrated `verify`/`materialize`/`client` jobs, not embeddings). Added a single new setting `NEOCARTA_DATABRICKS_EMBEDDING_STAGING_VOLUME` (the transient root directly), validated as a `/Volumes/<cat>/<schema>/<vol>/<subdir>` subpath **only when inline is on** (external mode never reads it).
- *Ledger fields.* `embed_stage`/`staging` read `ledger_enabled`/`ledger_path` at runtime; added them as plain `False`/`""` fields now (no validators/tests) so the inert ledger branch runs with the flag off. Validators + tests remain Phase 4.

- [x] Add the `EmbeddingCounts` dataclass + `embeddings` field to the connector's `RunSummary` (`ingest/summary.py`) first, since `embed_stage.py` accumulates into it. Source: `dbxcarta` branch `…/spark/ingest/summary.py`.
  - Ported `EmbeddingCounts` (per-label model/threshold/flags/attempts/successes/failure-rate/ledger-hits with `as_*_map` flatteners) and added the `embeddings` field (default-empty). `to_dict()` now emits the flat `embedding_*` keys; external-mode runs carry an all-null embedding view.
- [x] Port `embeddings.py`, `embed_stage.py`, and `staging.py` into `ingest/transform/`. Source: `dbxcarta` branch `…/spark/ingest/transform/{embeddings,embed_stage,staging}.py`.
  - `embeddings.py` re-points `validate_serving_endpoint_name` to `_platform/identifiers.py`. `staging.py` re-points `uc_volume_parent` there, and `resolve_transient_root` now returns `embedding_staging_volume` directly (no summary-volume sibling math). `embed_stage.py` renamed all settings refs and the failure-gate error message to the `NEOCARTA_DATABRICKS_*` convention. Log prefixes `[dbxcarta]` → `[neocarta]`.
- [x] Add the batched embed-and-write loop in `run.py`, gated by the flags. Source: `dbxcarta` branch `…/spark/run.py`.
  - External mode keeps the existing single-pass `_write_nodes` unchanged. Inline mode (`any_embeddings_enabled()`) routes through ported `_embed_and_write_nodes` → `_embed_and_write_node_chunks` (Table/Column batched by table range) + `_write_label_nodes`; Database/Schema embed-and-write once; Value nodes write un-embedded via `_write_value_nodes`. `finalize_embedding_summary` runs after. `_build_summary` records the embedding config in inline mode. (Value embedding was removed in the Phase 3 quality review — see below.)
- [x] Create the per-label vector indexes in `neo4j_io.py` when inline mode is on, at the configured dimension. Each mode owns this config.
  - Added `create_vector_indexes(driver, settings)` reusing neocarta's shared `neocarta.ingest.indexes.create_vector_index` (native integration; produces the `{label}_vector_index` cosine name the MCP server expects). Value excluded, matching the source. Called from `run.py` right after `bootstrap_constraints` in inline mode.
- [x] Emit a warning when inline is enabled (model/dimension; must match the rest of neocarta across datasources; no mixing modes without rebuilding the index). Added `_log_embedding_consistency_warning` in `run.py`.
- [x] Port `ledger.py` **inert** alongside `embed_stage.py`. Ported with `[neocarta]` log prefixes; the `embedded_batch`/`_embed_with_ledger` ledger branches are present but gated on `settings.ledger_enabled` (default False). Settings wiring + tests remain Phase 4.
- [x] Port the embedding unit tests from `dbxcarta/tests/spark/embeddings/` into the connector test tree.
  - Ported `test_transform_unit.py` → `tests/unit/connectors/databricks/test_embeddings.py` (14 Spark-logic tests: `_validate_embedding` paths, failure stats, per-batch gate, ledger split hit/miss, sha256 hash), `importorskip`-guarded. Renamed the gate stub field/error match to the new convention. Existing `test_settings.py` updated (inline cases now pass a staging volume) + 3 new staging-volume validator tests.
- *Live verification deferred:* inline-mode end-to-end testing against a catalog with a real serving endpoint (one label at a time, covering both the default Databricks `databricks-gte-large-en` endpoint and the OpenAI external-model endpoint from `setup-openai-endpoint.py`) needs a live cluster and is part of the single post-3.5 live pass, not this phase. Phase 3 ships code + unit tests only.

**Phase 3 validation:** `make test-databricks` equivalent (`tests/unit/connectors/databricks` + `tests/unit/enrichment/foreign_keys`, `--group databricks`) → 65 passed. Default-group full unit suite → 494 passed (no regressions; Spark-logic modules skip cleanly). `ruff check` + `ruff format` clean on all changed files.

**Phase 3 quality review (post-implementation, user-approved fixes).** Reviewed the whole inline path end-to-end (builders → embed stage → projection → Neo4j write) and verified correctness. Three findings actioned:
- *Removed Value embedding.* Investigation confirmed no neocarta path embeds Value nodes — the enrichment layer embeds only Table/Column (its docstrings: "must be one of: Database, Table, Column") and `_VECTOR_INDEX_LABELS` never indexed Value. So the inline-only `include_embeddings_values` flag embedded vectors that were never indexed and unsupported everywhere else. Removed it fully: the setting + its `any_embeddings_enabled`/coherence wiring (`settings.py`), the `EmbeddingCounts` flag entry and the per-chunk Value embed branch (`run.py`), the `EMBEDDING_TEXT_EXPR[VALUE]` entry (`contract.py`), and the dead `embedding_text` column on the Value frame (`sample_values.py`). Value nodes now write through one shared `_write_value_nodes` helper (un-embedded, run-stamped) in both modes. Value keeps its declared `embedding` graph property (the contract-wide "every label declares embedding, may be absent" rule is unchanged).
- *Normalized log prefixes.* The ported transform modules used `[neocarta]`; their package siblings (`sample_values`, `value_stage`, `extract`, `neo4j_io`, …) use `[databricks]`. Changed the 6 occurrences in `embed_stage.py`/`staging.py`/`ledger.py` to `[databricks]`. (`run.py` was already all-`[neocarta]` pre-Phase-3 — left as-is, internally consistent; out of Phase 3 scope.)
- *Added pure-Python tests.* New `test_embedding_summary.py` (default `test-unit` group, no Spark) covers `finalize_embedding_summary` rate arithmetic, `EmbeddingCounts.as_*_map`, `RunSummary.to_dict` embedding keys (external null view + inline populated), and `resolve_transient_root`/`resolve_ledger_path` path resolution. Updated `test_contract.py` (embedding-text map now covers embeddable labels only) and removed the obsolete value-embedding coherence test from `test_settings.py`.

**Post-review validation:** default-group full unit suite → 501 passed; `--group databricks` connector suite → 51 passed; `ruff check` + `ruff format` clean.

### Phase 4: Optional ledger cache — ✅ COMPLETE
`ledger.py` was already ported inert in Phase 3 so `embed_stage.py` could import it; Phase 4 turns it on as a supported option.
- [x] Add the renamed `NEOCARTA_DATABRICKS_LEDGER_*` settings (`ledger_enabled`, `ledger_path`) and their validators.
  - The `ledger_enabled`/`ledger_path` fields already existed (added inert in Phase 3). Added the `_validate_ledger_path` field validator (the faithful rename of the source's `_validate_optional_volume_subpath`): blank stays blank (derive a staging-volume sibling at runtime via `resolve_ledger_path`), and a set path must be a `/Volumes/<cat>/<schema>/<vol>/<subdir>` subpath, validated by the connector's `validate_uc_volume_subpath` with the `NEOCARTA_DATABRICKS_LEDGER_PATH` label and trailing slash trimmed. Updated the field comment to describe the live feature instead of "ported inert". **No new coherence check was added** — the dbxcarta source has none (a `ledger_enabled=True` with embeddings off is inert, not an error), so adding one would be drift; `ledger_enabled` stays a plain bool exactly as in the source.
- [x] Confirm the ledger branch in `embedded_batch` is exercised once the flag is on (the call sites already exist from Phase 3).
  - Confirmed by reading the wired path: `run.py:_embed_and_write_nodes` computes `resolve_ledger_path(settings)` and passes it through `_write_label_nodes`/`_embed_and_write_node_chunks` into `embedded_batch`, which calls `_embed_with_ledger` (ledger read + `split_by_ledger`) and `upsert_ledger`, both gated on `settings.ledger_enabled`. The hit/miss join logic is unit-tested (`test_embeddings.py` `split_by_ledger` tests, ported in Phase 3). The full `embedded_batch` round-trip (Delta MERGE upsert + `ai_query` on misses) needs Delta + a serving endpoint and stays in the single post-3.5 live pass, exactly as it was integration-only in dbxcarta.
- [x] Port the ledger tests from `dbxcarta/tests/spark/ledger/`.
  - `test_staging.py` → `tests/unit/connectors/databricks/test_staging.py` (pure-Python, default group): the two `_is_missing_path_error` tests (FileNotFoundException text matches; permission error propagates).
  - `test_read_ledger.py` → `tests/unit/connectors/databricks/test_ledger.py` (Spark-logic, `importorskip`-guarded): the `read_ledger` missing-path test, kept `@pytest.mark.skip(reason="requires Delta JAR on local Spark classpath")` exactly as in the source (the local-Spark suite has no Delta JAR). The non-skipped ledger split coverage already lives in `test_embeddings.py`.
  - Added 4 pure-Python `ledger_path` validator tests to `test_settings.py` (off-by-default blank path, explicit path trailing-slash trim, non-`/Volumes` rejection, `..` traversal rejection).

**Phase 4 validation:** `--group databricks` (`tests/unit/connectors/databricks` + `tests/unit/enrichment/foreign_keys`) → 78 passed, 1 skipped (the Delta-JAR `read_ledger` skip). Default-group full unit suite → 507 passed, 1 skipped (+6 pure-Python tests vs Phase 3's 501). `ruff check` + `ruff format` clean on all changed files. Live ledger round-trip (Delta MERGE + ai_query) is part of the single post-3.5 live pass.

**What the ledger cache is:** a cross-run cache that lets the pipeline skip the `ai_query` embedding call for nodes that have not changed since the last run. Each embedded node stores the SHA-256 hash of the exact text that was embedded. The ledger keeps a small Delta table per label holding `id`, that text hash, the resulting vector, the model name, and a timestamp. On the next run, before calling `ai_query`, the pipeline joins against the ledger: a node is a "hit" when its id, model, and text hash all match, in which case the stored vector is reused and no embedding call is made. Only "misses" go to `ai_query`. After a successful batch the new vectors are merged back into the ledger.

The point of it is cost and speed. Embedding calls cost money and time, and most metadata does not change between runs, so a re-run normally re-embeds thousands of identical strings for no reason. The ledger turns a full re-embed into embedding only the rows whose text actually changed. It is gated by its own flag (`NEOCARTA_DATABRICKS_LEDGER_ENABLED`) and is off by default, so it can be deferred to a later phase without affecting correctness. The trade-off is added Delta storage and merge logic, which is why it is optional rather than always on.

**Decision: keep this as its own Phase 4**, after inline embeddings are working, rather than bundling it into the first inline release.

### Phase 5: Cleanup and documentation — ✅ COMPLETE
- [x] **Docs-review stage:** swept every docstring/comment in the connector for descriptions of removed behavior. Five files carried stale text and were fixed (no code logic changed):
  - `ingest/transform/value_stage.py` — module + `ValueResult` + `transform_sample_values` docstrings still said the Value embed+write was "folded into the table-range chunk loop." Value is never embedded; rewritten to point at `run.py:_write_value_nodes`. Also dropped the stale reference to the removed value-embedding cross-field validator.
  - `ingest/contract_expr.py` — module docstring + a comment claimed the Python id builders live in `neocarta.connectors.databricks.contract.generate_id`/`generate_value_id` (no such functions). Re-pointed to `neocarta.connectors.utils.generate_id` (`compose_id`/`generate_value_id`). (This was the Phase 1 deferred docstring.)
  - `ingest/extract.py` — module docstring ("embedding enrichment happens later, before the Neo4j load") and `ExtractResult` ("fields mutable because enrichment replaces the node DataFrames in place after staging") described a mechanism that no longer exists; inline mode filters and embeds the frames per batch without reassigning them. Also fixed `unpersist_cached`'s reference to the dropped "verification steps."
  - `ingest/load/neo4j_io.py` — `create_vector_indexes` docstring said Value's "flag embeds Value nodes"; the value-embedding flag was removed. Now reads "Value is never embedded or indexed."
- [x] Document both modes as equals in the connector README, including a "which mode to pick" section and the two-step external flow (Spark ingest job, then the CLI embedding command). Created `neocarta/connectors/databricks/README.md` (execution model, external/inline modes, which-mode-to-pick, model/dimension consistency, the two-step external flow with `neocarta databricks embed`, the run-report capture via `SUMMARY_VOLUME`, the ledger cache, and a full `NEOCARTA_DATABRICKS_*` settings reference).
- [x] Update `CHANGELOG.md`. Added four `Added` entries under `Upcoming`: inline embeddings + settings, the cross-run ledger, `SUMMARY_VOLUME` (with the `embedding_failure_max` output-key note), and the `neocarta databricks embed` CLI verb.
- [x] Run `make fmt`, `make lint`, and the test suites.
- **Post-Phase-4 quality-review changes that still need documenting (done in code/tests, not yet in README/CHANGELOG):** — ✅ now documented in the README and CHANGELOG entries above.
  - **`NEOCARTA_DATABRICKS_SUMMARY_VOLUME` (new optional setting).** When set to a `/Volumes/<cat>/<schema>/<vol>/<subdir>` subpath, each run writes `summary_<run_id>.json` (the flattened `RunSummary`) there; blank (default) disables it and the summary is only returned in memory + Neo4j counts logged. Mode-independent (both external and inline), durable (never deleted), best-effort (a write failure is logged, never raised, so it cannot mask the run outcome). Closes the "detached cluster job leaves no durable artifact" gap. Persistence lives inside `run_ingest`, so any caller — including the Phase 7 cluster entrypoint — gets it for free by setting the env var. Document it in the README's two-step external flow as the way to capture the run report.
  - **Run-summary key rename `embedding_failure_threshold` → `embedding_failure_max`.** This is a change to the connector's **public output shape** (the `RunSummary.to_dict()` JSON), so it needs a CHANGELOG note. The field held a per-batch failure *count* gate but was named/typed like a rate threshold; it is now `failure_max: int | None` emitted as `embedding_failure_max`, consistent with the `NEOCARTA_DATABRICKS_EMBEDDING_FAILURE_MAX` setting. No in-repo consumer read the old key, but an external operator script that calls `to_dict()` would see the new key.
  - **Minor cleanups (no doc impact, listed for completeness):** removed a dead `label` parameter from `add_embedding_column`; refreshed the `ledger.py` module docstring (dropped the stale "ported inert / tests land later" wording and the obsolete value-embedding mention); collapsed a redundant dual `except` in `staging.delete_transient`.

**Phase 5 validation:** `make fmt` → 233 files unchanged; `make lint` → all checks passed. Default unit suite → 513 passed, 1 skipped. `--group databricks` (`tests/unit/connectors/databricks` + `tests/unit/enrichment/foreign_keys`) → 84 passed, 1 skipped. `make test-smoke` → 11 passed. Docstring-only/doc edits, so no test counts moved vs Phase 4's post-doc baseline. Live (cluster + Neo4j) verification remains the single post-3.5 pass.

### Phase 6: Build and version the connector wheel (neocarta side)

**Goal:** produce the single handoff artifact from `cli.md` — a versioned neocarta wheel that carries the connector and declares the `databricks-spark` extra. This phase is entirely in the neocarta repo and needs no cluster. The external dbxcarta project consuming the wheel is Phase 7; publishing to an index is Phase 8.

**This phase is independent of the inline-embedding phases (3/4/5).** The connector is already packaged on the branch, and `uv build` already emits a wheel that bundles `neocarta/connectors/databricks/` and declares the `databricks-spark` extra, so Phase 6 can be exercised first. Settled decisions:
- The extra is named `databricks-spark` (no rename); the install target is `neocarta[databricks-spark]`.
- The test version stays at the current `0.6.0`; the bump to `0.8.0` is a publish-time step in Phase 8.

**Work:**
- Confirm `uv build` produces `dist/neocarta-<version>-py3-none-any.whl` plus the sdist. (Verified: the wheel bundles the connector and declares `Provides-Extra: databricks-spark` and `Requires-Dist: pyspark>=3.5; extra == 'databricks-spark'`.)
- Add a clean-room install check. In a fresh virtualenv, `pip install "neocarta[databricks-spark] @ file://…/dist/neocarta-<version>-py3-none-any.whl"`, import `DatabricksSparkSchemaConnector`, and run the smoke suite plus the `databricks` unit group against the installed wheel rather than editable source. This catches packaging gaps (a module or data file missing from the wheel) that the editable tree hides.
- Pin the connector's runtime dependencies to the versions the pipeline was tested against (`cli.md` "In Neocarta"), so the wheel resolves the same way locally and on a cluster. **This is now a confirmed gap:** the clean-room install above resolved `pyspark 4.1.2` from the unpinned `pyspark>=3.5` floor, not the 3.5.x line the pipeline was tested on. Pin before the Phase 8 publish. This pinned set is also what Phase 7 needs for the cluster `pinned_closure`.

**Run it locally right now (no cluster needed).** These steps work today on the branch at version `0.6.0`:

```bash
# 1. Build the wheel + sdist into ./dist
uv build

# 2. Inspect the artifact: connector bundled + extra declared
unzip -l dist/neocarta-0.6.0-py3-none-any.whl | grep -c "connectors/databricks"   # -> 22
unzip -p dist/neocarta-0.6.0-py3-none-any.whl "*/METADATA" \
  | grep -iE "Provides-Extra: databricks-spark|Requires-Dist: pyspark"

# 3. Clean-room install from the wheel (not editable source) and import-check
python3 -m venv /tmp/wheeltest
/tmp/wheeltest/bin/pip install "neocarta[databricks-spark] @ file://$(pwd)/dist/neocarta-0.6.0-py3-none-any.whl"
/tmp/wheeltest/bin/python -c "from neocarta.connectors.databricks import DatabricksSparkSchemaConnector; print('ok')"
/tmp/wheeltest/bin/python -c "import pyspark; print(pyspark.__version__)"
```

Step 3 downloads pyspark (large), so the first install takes a few minutes.

**Status and progress (Phase 6):**
- ✅ **Wheel build verified.** `uv build` emits `dist/neocarta-0.6.0-py3-none-any.whl`; it bundles all 22 `neocarta/connectors/databricks/` modules and declares `Provides-Extra: databricks-spark` + `Requires-Dist: pyspark>=3.5; extra == 'databricks-spark'`.
- ✅ **Clean-room install verified.** Fresh-venv install of `neocarta[databricks-spark]` from the wheel imports `DatabricksSparkSchemaConnector` and resolves pyspark (got 4.1.2).
- ⬜ **Pin runtime dependencies** (pyspark and the rest) to tested versions, since the clean-room install proved the floor resolves to an untested pyspark 4.x. Do before Phase 8; this set feeds the Phase 7 `pinned_closure`.
- ⬜ **Add the clean-room install + `databricks` unit group + smoke run as a repeatable check** (script or Make target), so the packaging test is not a one-off manual run.

### Phase 7: Repoint the dbxcarta operator tooling onto the neocarta wheel (external repo)

**Goal:** make the external dbxcarta project consume the prebuilt neocarta wheel for the ingest path instead of building `dbxcarta-spark` from local source. This is the `cli.md` split. All work is in the external repo `/Users/ryanknight/projects/databricks/dbxcarta` (its own branch and PR), and it ends in the on-cluster ingest run. No package index yet: the wheel source is a local path or `--find-links` against neocarta's `dist/`. Parameterizing the wheel source as "local path now, index-by-version later" is what keeps Phase 8 small.

**Why this is its own phase (grounded in the dbxcarta code):** the repoint is five distinct pieces, not a one-line source swap. The cluster bootstrap installs the application wheel with `--force-reinstall --no-deps` and installs dependencies separately from a pre-resolved `pinned_closure`, so dependencies do not ride in from the wheel's metadata.

**Work (external repo):**
- **Fetch instead of build.** Change `dbxcarta-submit`'s `_handle_publish_wheels` so the *ingest* entrypoint stages the prebuilt neocarta wheel (local path / `--find-links`) instead of `uv build`-ing `dbxcarta-spark`. This is the `databricks_job_runner` `publish_wheel_stable` / `find_latest_wheel` seam, which today builds from `project_dir/dist` local source. The *client* entrypoint stays as-is.
- **Rebuild the `pinned_closure`.** Because the cluster installs `--no-deps`, regenerate the ingest job's pinned dependency closure to be the neocarta connector's closure (pyspark, neo4j, pydantic-settings, databricks-sdk, ...) rather than dbxcarta-spark's. This consumes the pinned set from Phase 6.
- **Drop the core-bundling path for ingest.** `_core_bundled_into` and `_assert_wheel_bundles_core` exist so the entrypoint wheel physically carries `dbxcarta/core` under `--no-deps`. For the ingest path that is obsolete: the connector ships as ordinary modules inside the neocarta wheel. Remove or bypass that guard for ingest.
- **Repoint the entrypoint.** Point the SparkPythonTask at the neocarta connector's ingest entry point, not the dbxcarta module.
- **Possibly `databricks_job_runner` itself.** The build-from-source logic lives in that installed package, not the repo. If the repoint cannot be done entirely from the `dbxcarta-submit` caller, that package needs a change too.

**Test (live pass; needs a live cluster):**
- Stage the local neocarta wheel onto the UC Volume through the repointed dbxcarta path, then submit the ingest entrypoint on a classic cluster (Neo4j Spark Connector attached) against a test catalog and Neo4j.

### Phase 8: Publish the versioned wheel to a package index

**Decision: publish to a private index, not public PyPI.** A private index is the right release target because it is controllable and not public. A private index is not the easiest option for pure local testing, which is why Phases 6 and 7 use neocarta's local `dist/`; Phase 8 is where the real index enters.

- Bump the version to `0.8.0` (Monday's release), update `CHANGELOG.md`, build, and publish the wheel plus sdist to the private index as the release artifact of record.
- Flip the Phase 7 dbxcarta wheel source from the local path to "pull `neocarta[databricks-spark]==<version>` from the private index," and update operator config and docs to reference the connector wheel version rather than a local build (`cli.md` "In the external dbxcarta project").
- Verify the full index path: dbxcarta pulls the published `0.8.0` wheel by version from the private index, stages it on the Volume, and the ingest job runs on a classic cluster.
- **Shared contract (`cli.md`):** the wheel name `neocarta` plus the `databricks-spark` extra and the version scheme are the one handoff between the two projects. Record the chosen private index so both projects point at the same place.

---

## Notes on the embedding mechanism (for reference)

- Embeddings run as `ai_query('<endpoint>', embedding_text, failOnError => false)` distributed across Spark. No Python UDF and no extra pip dependency.
- The default endpoint is `databricks-gte-large-en` at dimension 1024. The dimension is configurable and is checked against the endpoint at preflight.
- The result is frozen to a transient Delta path and read back so `ai_query` runs exactly once per item, and the same frozen result feeds both the failure gate and the Neo4j write.
- Only the `embedding` vector reaches the graph. All bookkeeping columns (text hash, model, timestamp, error) are stripped by the fail-closed projection before the write.
- Vector indexes use cosine similarity and follow the `{Label}_vector_index` naming the MCP layer already expects.
