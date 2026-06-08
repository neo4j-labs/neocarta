# Finance Genie Integration Test

A plain-English, phased walkthrough for testing the `finance-genie` example end to end: stand up the configuration, ingest the Databricks schema into the Neo4j semantic layer, and then use the neocarta (dbxcarta) client to confirm the ingested graph is correct.

This guide assumes you are working from the `dbxcarta/` directory and using the `aws-partner-rk` Databricks workspace. It describes *what* to do at each phase; the exact commands live in the example `README.md`, the repo `Makefile`, and `dbxcarta-overlay.env`.

---

## Work Log

Run-by-run status of this integration test. Most recent run against the `aws-partner-rk` workspace.

| Phase | Status | Notes |
| --- | --- | --- |
| 0 — Prerequisites | ✅ Done | Confirmed by operator. |
| 1 — Configure env & secrets | ✅ Done | Confirmed by operator. `DATABRICKS_WAREHOUSE_ID` corrected to `b0fffb8e3255bf85` (the previously configured `c37d0438c79ad6c5` did not exist in the workspace). |
| 2 — Confirm source catalogs | ✅ Done | Readiness check: `graph-enriched-finance-silver` and `graph-enriched-finance-gold` both report ready (2/2 present). |
| 3 — Bootstrap ops + upload questions | ✅ Done | Bootstrapped `dbxcarta-catalog.finance_genie_ops` schema + `dbxcarta-ops` volume. `questions.json` (4,480 bytes) uploaded to `/Volumes/dbxcarta-catalog/finance_genie_ops/dbxcarta-ops/dbxcarta/questions.json`. |
| 4 — Ingest schema into Neo4j | ✅ Done | **Attempt 1 ❌** (Run ID `665697372761238`): failed on the cluster connecting to Neo4j — `ServiceUnavailable: Failed to DNS resolve address b4c5ce8f.databases.<aura>.io:7687`. Cause: stale/dead Neo4j host in the secret scope. **Fix:** operator updated `examples/finance-genie/.env` to a new Neo4j instance; `setup_secrets.sh --profile aws-partner-rk --example finance-genie` re-provisioned the `dbxcarta-neo4j-finance-genie` scope. **Attempt 2 ✅** (Run ID `883304391760435`, Result `SUCCESS`): `status=success`. Counts — schemas 2, tables 8, columns 59; inferred FK (`REFERENCES`) edges 5; value nodes 44, `HAS_VALUE` edges 44. (FK accounting: 0 declared, 5 inferred-from-metadata accepted; sampled 12 of 15 candidate columns.) |
| 5 — Verify ingest | ✅ Done | `uv run dbxcarta verify` → `run_id=local OK (0 violations)`. Graph structure, node counts, contract version, ID normalization, and FK accounting all match the run summary. |
| 6 — Validate with client | ✅ Done | Local read-only client (README §11) repointed at the finance ingest. Preflight `config=ok`, warehouse reachable, 12 questions, `graph_schema_lines=33` (graph present & queryable). Graph-RAG `ask` validated retrieval end-to-end: fg_q01 (silver) → `SELECT count(*) FROM accounts` → `25000`, `reference_comparison: correct`; fg_q08 (gold) → `count(*) ... gold_accounts WHERE fraud_risk_tier='high'` → `1253`, `correct`. Retrieved context carried full table/column descriptions, FK comment hints, and sample values across both silver and gold. See reproduction block below. |
| 7 — Client evaluation | ⬜ Not started | |
| 8 — Teardown | ⬜ Not started | Optional. |

### Phase 6 — reproduction

All commands run from the `dbxcarta/` repo root against the `aws-partner-rk` workspace.

One-time config prep in the standalone local-demo file `examples/finance-genie/.env` (this file never layers with the overlay; it holds the demo's own config and the `NEO4J_*` secrets):

- `DATABRICKS_WAREHOUSE_ID=b0fffb8e3255bf85` — the live warehouse (the previous `c37d0438c79ad6c5` did not exist).
- `DATABRICKS_SECRET_SCOPE=dbxcarta-neo4j-finance-genie` — required by `ClientSettings`; value is unused locally because `neo4j_credentials()` falls back to the `NEO4J_*` env vars off-cluster.
- `DBXCARTA_CATALOG=graph-enriched-finance-silver` — repoint the demo from the standalone `graph-enriched-lakehouse` dataset to the finance ingest so it queries the graph Phase 4 built.

The commands (the local demo resolves its `.env` relative to the package, so `--directory` is required):

```bash
# Connectivity + config + graph-content check
uv run --directory examples/finance-genie python -m dbxcarta_finance_genie_example.local_demo preflight

# List the bundled demo questions
uv run --directory examples/finance-genie python -m dbxcarta_finance_genie_example.local_demo questions

# Graph-RAG: retrieve context from Neo4j, generate SQL, execute, grade vs reference
uv run --directory examples/finance-genie python -m dbxcarta_finance_genie_example.local_demo ask --question-id fg_q01 --show-context
uv run --directory examples/finance-genie python -m dbxcarta_finance_genie_example.local_demo ask --question-id fg_q08
```

Output summary:

- **preflight** → `config=ok`, `warehouse=b0fffb8e3255bf85`, `questions=12`, `graph_schema_lines=33`. The non-zero schema-line count confirms the ingested finance schema is present and queryable in Neo4j.
- **questions** → 12 questions listed (fg_q01–fg_q12).
- **ask fg_q01** (silver) → context seeded from vector search across silver+gold nodes; `generated_sql: SELECT count(*) FROM \`graph-enriched-finance-silver\`.\`graph-enriched-schema\`.\`accounts\``; `reference_comparison: correct`; result `25000`.
- **ask fg_q08** (gold) → `SELECT count(*) FROM \`graph-enriched-finance-gold\`.\`graph-enriched-schema\`.\`gold_accounts\` WHERE fraud_risk_tier = 'high'`; `reference_comparison: correct`; result `1253`.

Conclusion: the ingested semantic layer is correct and useful — the client retrieves accurate table/column metadata (including descriptions, FK comment hints, and sample values) from the graph and produces correct SQL for both silver and gold questions.

---

## Phase 0 — Prerequisites

- Confirm you have a running Neo4j instance you can reach (URI, username, password in hand).
- Confirm you can reach the `aws-partner-rk` Databricks workspace and have a SQL warehouse you can use.
- Confirm the upstream Finance Genie data has already been generated — the source catalogs (`graph-enriched-finance-silver` and `graph-enriched-finance-gold`) must already hold their base and gold tables. dbxcarta reads these; it does not create them.
- Make sure the project is installed in development mode so the example, client, and core packages resolve.

---

## Phase 1 — Configure environment and secrets

- Fill in your private credentials in the example's `.env` (Databricks profile/warehouse, Neo4j URI/username/password). This file is local only and is never committed.
- Leave the committed `dbxcarta-overlay.env` as the shared, secret-free configuration — it already points at the silver and gold finance catalogs, the shared ops volume, the question set, and the three evaluation arms.
- Provision the Neo4j secret scope for this example so the Databricks jobs can read the Neo4j credentials at runtime. This pushes your local Neo4j values into the per-example secret scope named in the overlay.
- Sanity-check: the overlay's catalog list, schema name, and ops volume paths should all match what exists in the workspace.

---

## Phase 2 — Confirm the source catalogs are ready

- Run the readiness check against the preset. This confirms the silver and gold catalogs actually contain table schemas before you spend time ingesting.
- If the readiness check reports empty or missing catalogs, stop and resolve the upstream Finance Genie data load first.

---

## Phase 3 — Bootstrap the ops plane and load the questions

- Bootstrap the operational plane. This creates the ops catalog, schema, and volume that hold run summaries and the question fixture.
- Upload the demo question set so the client evaluation can find it on the shared volume later.
- Confirm the question fixture lists the expected set of finance questions (base-table counts, joins, gold-table filters, aggregations) — this is what the client will be graded against.

---

## Phase 4 — Ingest the schema into Neo4j

- Kick off the ingest job. This is the core step: it rebuilds the wheels, bootstraps, and submits the Databricks ingest job.
- During ingest, the pipeline reads table and column metadata from the silver and gold catalogs, infers foreign-key relationships by column-name matching, samples a handful of distinct values per column, generates embeddings, and writes the result into Neo4j.
- The graph it builds is a hierarchy of Database, Schema, Table, Column, and Value nodes, connected by `HAS_SCHEMA`, `HAS_TABLE`, `HAS_COLUMN`, and `HAS_VALUE` relationships, plus inferred `REFERENCES` edges between columns. Tables are tagged with their medallion layer (silver or gold).
- Wait for the Databricks job to finish successfully. Note the run ID — you will use it to verify.

---

## Phase 5 — Verify the ingest matches the run summary

- Run the structured verification step against the completed run. If you don't pass a run ID, it picks up the most recent successful run.
- Verification compares the graph against what the job reported writing and checks, among other things:
  - Node counts in Neo4j match the run summary (schemas, tables, columns, value nodes).
  - Every node carries the expected contract version.
  - There are no orphan nodes and no broken parent links in the hierarchy.
  - Column identifiers sampled from the Databricks `information_schema` actually exist in Neo4j (ID normalization is consistent between the catalog and the graph).
  - Foreign-key edge accounting (declared, resolved, skipped) lines up.
- A clean run reports PASS with zero violations. Any FAIL lists each violation with a code and message — investigate before moving on.

---

## Phase 6 — Use the neocarta client to validate the schema is correct

- Run the client preflight check. This confirms the client can connect to the warehouse and to Neo4j, that the graph actually has content, and that schema context can be retrieved — a direct confirmation that the ingested schema is queryable.
- List the demo questions through the client to confirm the question set is wired up correctly.
- Spot-check the graph through the client by asking it to build context for a question and generate SQL: it pulls relevant tables and columns out of the Neo4j graph, which proves the nodes, relationships, and embeddings landed correctly and are retrievable.
- For a fuller signal, run the read-only "ask" flow on a couple of questions and confirm the generated SQL references the right finance tables (accounts, merchants, transactions, gold accounts, fraud-ring communities) — this only works if the schema graph is complete and correct.

---

## Phase 7 — Run the full client evaluation and judge the result

- Submit the client evaluation job. It runs three arms in progression for every question: no context, schema dump, and graph RAG (context retrieved from the Neo4j graph).
- For each arm it reports how many questions were attempted, parsed, executed, returned rows, and matched the reference answer.
- Success criterion: the graph RAG arm should match or beat the schema dump arm on correctness. That outcome means the ingested semantic layer is not just present but genuinely useful for answering questions.
- Results are persisted as a JSON file per run on the ops volume and appended to the run-summary Delta table, so you can review and compare runs later.

---

## Phase 8 — Teardown (optional)

- When finished, run the teardown step to drop the example's ops schema and clean up the operational artifacts.
- Teardown is scoped to the example's ops schema only — it does not touch the upstream finance catalogs or the Neo4j data unless you choose to clear those separately.

---

## What "passing" looks like overall

- Readiness check confirms the source catalogs hold schemas.
- Ingest job finishes successfully and produces a run summary.
- Verification reports PASS with zero violations.
- Client preflight confirms Neo4j has content and is queryable.
- Client evaluation shows graph RAG matching or beating the schema dump arm on correctness.
