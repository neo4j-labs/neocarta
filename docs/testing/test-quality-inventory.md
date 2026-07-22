# Test-quality inventory

> **Purpose.** Classify every test module by the *kind* of protection it gives, so the refactor
> (GUIDE §5 moves, S1–S5) knows (a) which suites genuinely guard behavior vs. which only assert shape or
> import, and (b) which areas need **characterization golden-masters** (GUIDE §6) captured *before* the
> code they cover is moved or rewritten. Companion to [coverage-baseline.md](coverage-baseline.md).
> Produced by S0.2 (#288). Classification is **module-level** (per `test_*.py`) — sufficient to target
> characterization work and far more maintainable than a per-test sheet; notable per-test exceptions are
> called out in the Notes column.

## Rubric

| Tier | Meaning | Refactor value |
|---|---|---|
| **REAL** | Asserts on produced behavior/output/error semantics for a concrete input. | High — characterization-worthy; these are the tests a refactor must keep green and often the basis for golden-masters. |
| **CONTRACT** | Asserts a protocol/shape/wiring, not per-source behavior; often near-verbatim across modules. | Medium — real regression guards, but duplicated; dedup/parametrize candidates. |
| **SMOKE** | Import / `isinstance` / `hasattr` / CLI-plumbing (`--help` shape, `--dry-run`); executes code but asserts little about behavior. | Low — does not protect behavior; must not be mistaken for coverage of the thing it imports. |

## Summary

- **REAL** — the behavioral core: connector `*/test_extract.py` · `*/test_transform.py` ·
  `*/test_ingest_transform.py`; `ingest/*`; `data_model` (`schema/lpg`, `glossary`,
  `governance`, `instance`); `_mcp/test_search_strategy` · `test_osi_cypher`; the
  `agent` tool tests; and **all** `tests/integration/*` (real Neo4j).
- **CONTRACT** — the **13 per-connector `test_conformance.py` modules (~173 tests)**, each asserting the
  same `SourceConnectorProtocol` contract (isinstance / callable stage methods / README present /
  context-manager / injected-driver-left-open). Near-identical across ~9 connectors → prime
  dedup/parametrize target.
- **SMOKE / low-value** — all of `tests/smoke/` (13, packaging surface); most of `_cli/*` (plumbing only,
  by design); trivial-getter `data_model/schema/rdbms` + `data_model/metadata`; single-assertion
  micro-modules (`*_warnings`, some `*_logging`, `query_log/test_extract`); and
  isolated `isinstance` guards.

## Module classification

### `tests/unit/connectors/` (REAL core + CONTRACT conformance)

| Module | Tests | Tier | Notes |
|---|---:|---|---|
| `test_loader.py` | 12 | REAL | generic connector loader behavior |
| `utils/test_generate_id.py` | 8 | REAL | deterministic IDs — **characterization target for S3 KeySpec builder** |
| `bigquery/test_errors.py` | 6 | REAL | error mapping |
| `bigquery/logs/test_conformance.py` | 12 | CONTRACT | |
| `bigquery/logs/test_extract.py` | 21 | REAL | |
| `bigquery/schema/test_conformance.py` | 13 | CONTRACT | |
| `bigquery/schema/test_extract.py` | 8 | REAL | |
| `bigquery/schema/test_logging.py` | 2 | REAL | narrow — asserts SQL never logged |
| `bigquery/schema/test_transform.py` | 21 | REAL | per-family transform assertions (customers/orders fixture) |
| `bigquery/schema/test_transform_golden.py` | 2 | REAL | Layer-A golden characterization of the transform + injected-change negative control |
| `csv/test_conformance.py` | 12 | CONTRACT | |
| `csv/test_extract.py` | 51 | REAL | config/filter validation with message matching |
| `databricks/schema/test_conformance.py` | 21 | CONTRACT | |
| `databricks/schema/test_extract.py` | 37 | REAL | |
| `databricks/schema/test_transform.py` | 16 | REAL | **S3 characterization target** |
| `databricks/tags/test_conformance.py` | 12 | CONTRACT | |
| `databricks/tags/test_connector.py` | 9 | REAL | |
| `databricks/tags/test_extract.py` | 17 | REAL | |
| `databricks/tags/test_transform.py` | 5 | REAL | **S3 characterization target** |
| `dataplex/test_utils.py` | 16 | REAL | |
| `dataplex/test_warnings.py` | 1 | SMOKE | single-assertion micro-module |
| `dataplex/glossary/test_conformance.py` | 12 | CONTRACT | |
| `dataplex/schema/test_conformance.py` | 12 | CONTRACT | |
| `jdbc/schema/test_conformance.py` | 12 | CONTRACT | |
| `jdbc/schema/test_connector.py` | 4 | REAL | |
| `jdbc/schema/test_extract.py` | 17 | REAL | |
| `jdbc/schema/test_transform.py` | 12 | REAL | **S3 characterization target** |
| `osi/test_conformance.py` | 12 | CONTRACT | |
| `osi/test_connector_version.py` | 6 | REAL | version validation |
| `osi/test_export_transform.py` | 21 | REAL | |
| `osi/test_ingest_extract.py` | 9 | REAL | |
| `osi/test_ingest_transform.py` | 44 | REAL | strong — asserts output graph nodes/edges/dedup/spec-rejection |
| `osi/test_logging.py` | 1 | SMOKE | micro-module |
| `query_log/test_conformance.py` | 12 | CONTRACT | |
| `query_log/test_extract.py` | 1 | SMOKE | thin (1 test) |
| `query_log/test_transform.py` | 25 | REAL | |
| `query_log/test_utils.py` | 16 | REAL | SQL parsing |
| `snowflake/logs/test_conformance.py` | 12 | CONTRACT | |
| `snowflake/logs/test_extract.py` | 12 | REAL | |
| `snowflake/schema/test_conformance.py` | 21 | CONTRACT | |
| `snowflake/schema/test_extract.py` | 57 | REAL | |
| `snowflake/schema/test_logging.py` | 2 | REAL | asserts SQL never logged |
| `snowflake/schema/test_transform.py` | 16 | REAL | **S3 characterization target** |
| `unity_catalog/schema/test_conformance.py` | 10 | CONTRACT | |
| `unity_catalog/schema/test_extract.py` | 14 | REAL | |
| `unity_catalog/schema/test_transform.py` | 7 | REAL | **S3 characterization target** |

### `tests/unit/data_model/`

| Module | Tests | Tier | Notes |
|---|---:|---|---|
| `normalized/test_models.py` | 28 | REAL | validator behavior (yes/no coercion, int-float) |
| `schema/lpg/test_models.py` | 29 | REAL | |
| `schema/lpg/test_warnings.py` | 1 | SMOKE | micro-module |
| `schema/rdbms/test_models.py` | 3 | SMOKE | 2/3 are trivial getters; 1 real (NaN→None) |
| `glossary/test_models.py` | 6 | REAL | |
| `governance/test_models.py` | 11 | REAL | |
| `instance/test_models.py` | 6 | REAL | `Value` coercion |
| `metadata/test_models.py` | 2 | SMOKE | round-trip echo + required-fields raise |

### `tests/unit/ingest/` — all REAL

| Module | Tests | Tier | Notes |
|---|---:|---|---|
| `test_governance_loader.py` | 5 | REAL | Cypher-token characterization (guards silent zero-edge typos) — strong |
| `test_governance_queries.py` | 5 | REAL | |
| `test_indexes.py` | 6 | REAL | |
| `test_logging.py` | 3 | REAL | |

### `tests/unit/enrichment/` — REAL but heavily mocked

| Module | Tests | Tier | Notes |
|---|---:|---|---|
| `embeddings/test_openai_embeddings.py` | 4 | REAL | batching/ordering real; lifecycle tests patch out the write path |
| `embeddings/test_litellm_embeddings.py` | 7 | REAL | mocked provider |
| `embeddings/test_logging.py` | 8 | REAL | logging (exception-type-only, no PII) |

### `tests/unit/_mcp/` (excluded from `make test-cov`; run by `make test-mcp`)

| Module | Tests | Tier | Notes |
|---|---:|---|---|
| `test_search_strategy.py` | 3 | REAL | parametrized truth-table over the strategy ladder — best-in-class |
| `test_osi_cypher.py` | 6 | REAL | |
| `test_embeddings.py` | 2 | CONTRACT | wiring/mock-assert regression guard (#187) |

### `tests/unit/_cli/` (excluded from `make test-cov`; run by `make test-cli`) — plumbing tier

All 16 modules are **SMOKE (CLI plumbing)** by design — they assert `--help` flag shape, `--dry-run`
side-effect-freeness, JSON envelope shape, and missing-config errors; **no connector behavior is
exercised** (that depth lives in the integration suite). `test_common.py`, `test_config.py`,
`test_errors.py` lean CONTRACT/REAL (they test the shared helper logic: `_apply_neo4j_overrides`, settings
resolution, error→exit-code mapping).
Modules: `test_tool.py` (25), `test_snowflake.py` (18), `test_databricks.py` (14), `test_osi.py` (12),
`test_main.py` (10), `test_bigquery.py` (9), `test_dataplex.py` (9), `test_errors.py` (9),
`test_common.py` (8), `test_config.py` (8), `test_csv.py` (8), `test_jdbc.py` (6), `test_mcp.py` (6),
`test_query_log.py` (6), `test_logging_cli.py` (5), `test_output.py` (2).

### `tests/unit/agent/` (excluded from `make test-cov`; `agent/` is outside coverage `source`)

| Module | Tests | Tier | Notes |
|---|---:|---|---|
| `test_musicbrainz_agent.py` | 5 | REAL | tool tests real (request/params/clamping/error paths); `test_create_agent_returns_compiled_graph` is `isinstance` SMOKE |

### `tests/unit/` (top level)

| Module | Tests | Tier |
|---|---:|---|
| `test_errors.py` | 9 | REAL |
| `test_logging.py` | 13 | REAL |

### `tests/integration/` — all REAL (real Neo4j via testcontainers; Docker required)

| Module | Tests | Notes |
|---|---:|---|
| `_mcp/test_server_IT.py` | 8 | |
| `_mcp/test_osi_server_IT.py` | 10 | |
| `_mcp/test_osi_query_dataset_IT.py` | 4 | |
| `_mcp/test_metadata_validation_IT.py` | 3 | |
| `connectors/csv/test_connector_IT.py` | 16 | |
| `connectors/csv/test_ecommerce_dataset_IT.py` | 5 | |
| `connectors/csv/test_custom_filenames_IT.py` | 2 | |
| `connectors/csv/test_metadata_node_IT.py` | 2 | |
| `connectors/csv/test_name_index_IT.py` | 1 | |
| `connectors/osi/test_connector_IT.py` | 19 | |
| `connectors/databricks/test_connector_IT.py` | 7 | |
| `connectors/jdbc/test_connector_IT.py` | 1 | skip-guarded (Java 11+ / SchemaCrawler jars) |
| `connectors/unity_catalog/test_connector_IT.py` | 1 | |

### `tests/smoke/` — all SMOKE (by design: packaging / public-API surface)

| Module | Tests | Notes |
|---|---:|---|
| `test_imports.py` | 13 | import + `hasattr`/`assert all([...])` over public symbols against the built wheel; `test_databricks_connector_imports` (clean import without the extra) and `test_warnings_module_imports` (`issubclass`) carry the only real intent |

## Test-hygiene observations (recorded, not fixed in S0.2)

- **No pytest marker taxonomy.** Test type is distinguished only by directory + the `_IT.py` filename
  suffix + Makefile path routing (`--ignore`). GUIDE D4 / S0-3 will move selection to markers; until then
  a marker-blind `pytest tests/` collects everything (1,248 tests).
- **`_cli` suite is not hermetic w.r.t. `load_dotenv`.** `neocarta/_cli/config.py::load_dotenv()` mutates
  the real `os.environ`; when a developer has a populated `.env`, the leaked value (e.g. `NEO4J_DATABASE`)
  survives into a later test and fails `test_common.py::test_apply_neo4j_overrides_leaves_env_values_when_
  flags_absent` (passes in CI's clean env and with `NEO4J_DATABASE=neo4j`). Candidate hardening for S0-3.
- **CONTRACT duplication.** 13 near-identical `test_conformance.py` modules (~173 tests). Parametrizing the
  shared contract over the connector list would cut duplication without losing the guard.

## Needs characterization before refactor (feeds #291 / S0-SPIKE-1 / S3 / S5)

Golden-masters (GUIDE §6 — captured snapshots of current output) must be captured **before** the code they
guard is moved/rewritten. Priority = refactor imminence × current coverage weakness. **No golden-masters
are written in S0.2** — this list is the input to the characterization harness (`S0-SPIKE-1`) and the
tickets below.

| # | Area | GUIDE §5 move | Coverage signal | Characterization target | Priority |
|---|---|---|---|---|:--:|
| 1 | per-connector `transform.py` (bigquery/databricks/snowflake/jdbc/unity_catalog schema, osi, query_log) | → **central** `etl/transform` (S3) | REAL transform tests exist per connector, but all collapse into one component | golden-master each connector's transform output (node/rel objects) for a fixed extractor-cache fixture; the central transform must reproduce them byte-for-byte | **HIGH** |
| 2 | `connectors/utils/generate_id.py` | → generic KeySpec ID builder in `etl/transform` (S3) | only 8 tests for ~15 `generate_*_id` functions collapsing to one | golden-master every `generate_*_id` output across all id/node types | **HIGH** |
| 3 | `ingest/` (`Neo4jRDBMSLoader`, governance loaders, indexes) | → `etl/pipeline` + generic writer (S5) | 65.44% line / **37.23% branch** — weakest branch coverage | golden-master the emitted Cypher / merge patterns per node label + relationship (extend the existing Cypher-token approach to a full snapshot) | **HIGH** |
| 4 | `enrichment/` (embeddings connectors + write path) | → `etl/enrichment` + `extensions/enrichments` (S5) | 79.57% / 63.64%, but the driver-lifecycle/write tests are heavily mocked | golden-master the embedding write path (`get_nodes_to_embed` → `write_embeddings_to_graph`) against a captured node set | MED |
| 5 | `connectors/models.py` | → `extensions/connectors/models` **+** `etl/metadata_normalizer/normalized_schema` (S1) | shape relocates and splits into private cache vs shared contract | golden-master the normalized schema each connector emits (the flat records) so the S1 split holds parity | MED |
| 6 | `data_model/*` | → `etl/models` + `etl/ontology` | 99.76% (well covered) | mostly pure Pydantic models; existing tests suffice — capture only if the ontology/KeySpec extraction changes validation | LOW |
