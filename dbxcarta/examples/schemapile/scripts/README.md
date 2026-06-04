# schemapile example scripts

One-off utilities that live alongside the example but are not part of
the published package's entrypoints. Run them with `uv run` from the
example directory so the `.env` is picked up automatically.

## `dump_question_context.py`

Dumps the three context blocks used when iterating on SchemaPile question
generation: a schema dump, an FK list, and a sample-values list. The script
queries the live Neo4j graph that the dbxcarta ingest job populated, so it
always reflects the current state of `schemapile_lakehouse`.

The output is a complete Markdown document that replaces
`docs/schemapile/questions-schema.md`.

### Run

From the example directory:

```bash
uv run python scripts/dump_question_context.py \
    > ../../docs/schemapile/questions-schema.md
```

Or from the repo root:

```bash
uv run --directory examples/schemapile python scripts/dump_question_context.py \
    > docs/schemapile/questions-schema.md
```

### What it queries

- **Schema dump.** Reuses `dbxcarta.client.schema_dump.fetch_schema_dump`,
  which walks `Database -> Schema -> Table -> Column` for the configured
  catalog and renders the same text block the `schema_dump` client arm
  feeds to the LLM.
- **FK list.** Walks `Column -[REFERENCES]-> Column` and keeps edges
  whose `confidence` property meets the floor. Deduplicates on the
  unordered pair so each FK appears once. Annotates each line with
  `source=` (declared, inferred_metadata, semantic) and `confidence=`
  so you can filter further by hand.
- **Sample values.** Walks `Column -[HAS_VALUE]-> Value` for every
  column that the ingest pipeline sampled (low-cardinality columns that
  passed `DBXCARTA_SAMPLE_CARDINALITY_THRESHOLD`). Caps both the
  per-column value count and the per-value character length so the
  resulting block fits comfortably in a prompt.

### Flags

| Flag | Default | Purpose |
|------|---------|---------|
| `--confidence` | `0.8` | Minimum REFERENCES confidence to include. Matches `DBXCARTA_CONFIDENCE_THRESHOLD` used by the `graph_rag` retriever. Raise to `0.95` for a stricter declared-style list, lower if you want to see what semantic inference is producing. |
| `--max-values` | `20` | Max sample values per column. The ingest already caps these, so this is mostly defensive. |
| `--max-value-chars` | `80` | Truncate any single value longer than this with `...`. Prevents long-text columns that slipped through the cardinality filter from blowing up the doc. |

### Required environment

The script uses `dbxcarta.client.ClientSettings`, which reads the same
variables the runtime client uses. The example `.env` is sufficient:

- `examples/schemapile/.env` — workspace credentials, catalog name,
  warehouse id, volume/summary paths, Neo4j credentials. `DBXCARTA_SCHEMAS`
  is blank (schemapile_lakehouse is data-only and auto-discovered), and the
  script's Cypher treats an empty schema list as "all schemas", so the dump
  covers the whole graph.

If `NEO4J_URI` / `NEO4J_USERNAME` / `NEO4J_PASSWORD` are not set in
the env, the script falls back to the Databricks secret scope path in
`dbxcarta.client.neo4j_utils.neo4j_credentials` — useful when running
inside a Databricks job.

### When to regenerate

The dumped block goes stale every time the ingest job runs. Regenerate
before:

- Re-prompting an LLM while iterating on SchemaPile question generation.
- Diagnosing a `graph_rag` retrieval failure (the dump is what the
  retriever would see if it ignored its vector seeds and used the full
  catalog).
- Tuning the FK confidence floor; rerun with `--confidence 0.95` and
  diff against the default to see which edges semantic inference is
  contributing.
