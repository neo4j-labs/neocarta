# Characterization / Golden-Master Harness

> Built in **S0-SPIKE-1** (#291). This is the harness the refactor GUIDE §4
> (*characterization-first*) points at: **capture current behavior as golden-masters
> *before* refactoring the code they guard**, then keep the goldens green through the
> change. Every later "characterize-before-you-refactor" ticket (S1/S3/S5) reuses the
> reference pattern at the bottom of this doc.

## Why it exists

The refactor is *additive dual-path* (GUIDE §2): new components are built beside the old
ones and must be proven **byte-for-byte equivalent** before anything is removed. That
proof is only possible if current behavior is frozen first. This harness provides the
freeze + compare mechanism at two layers. Milestone **0.8.1** → test-infra only, **zero
production behavior change**.

## The three layers

| Layer | Captures | Runtime | Helper |
|---|---|---|---|
| **A — transform-level** | the node/relationship model lists a connector's transformer produces (`*_nodes` / `*_relationships` families) + the `get_properties` allowlist | **no Docker** (unit) | `serialize_transform` |
| **R — normalized records** | the flat normalized records a connector emits, *before* any graph shaping | **no Docker** (unit) | `dump_records` |
| **B — post-ingest graph** | every node (labels + properties) and relationship (endpoint `id`s + type + properties) after ingest into Neo4j | Docker (`Neo4jContainer`, integration) | `dump_graph` |

All three compare against committed JSON goldens via `assert_matches_golden`. The reusable
code lives in **`tests/support/characterization/`** (not collected as tests — no marker,
outside `coverage source`); the per-connector golden tests and their `.json` goldens
live next to the connector they cover.

**Layer R** was added by S1.6 (#297) — the S1-band target
[`test-quality-inventory.md`](test-quality-inventory.md) reserves ("golden-master the normalized
schema each connector emits (the flat records) so the S1 split holds parity"). Pick it when the
change touches what a connector *emits* rather than how it is shaped: a Layer A diff says the
graph changed, a Layer R diff says whether the connector stopped supplying a field or the
record→graph mapping changed meaning. During the S4 cutover, when connectors are rewritten one
at a time, that is the difference between a local fix and bisecting a pipeline.

> **Family discovery covers both conventions.** `serialize_transform` finds `*_nodes` /
> `*_relationships` exposed as `@property` accessors **and** as plain list attributes assigned in
> `__init__`. Both are common — BigQuery/CSV/JDBC/query-log use properties; Unity Catalog, both
> Dataplex connectors and Databricks tags use attributes. Until S1.6 only properties were found,
> so those four serialized to `{}`, which compares equal to an empty golden: the failure mode was
> a golden that passed while guarding nothing. All ten counts are pinned in
> `tests/unit/etl/test_characterization_discovery.py`; if you add a transformer, add it there.

## Decisions (Latitude items, per GUIDE §9 — recorded here as the PR justification)

1. **Serialization → custom JSON goldens.** Plain `.json` via
   `json.dumps(indent=2, sort_keys=True, ensure_ascii=False)` + trailing newline,
   compared with `difflib`. No snapshot-library dependency (fits the 0.8.1 safety-net
   band), fully git-diffable so a reviewer reads the parity delta directly, and total
   control over ordering + nondeterminism exclusion. It is the natural scale-up of the
   in-code expected-graph literals a hand-written parity test uses, which do not scale
   to the full CSV dataset or a post-ingest graph dump.
2. **Connectors → CSV + BigQuery.** Deliberately divergent shapes: CSV (`CSVTransformer`,
   glossary/query/tagging families + a `get_properties` allowlist) and BigQuery (the
   `BigQuerySchemaTransformer`, relational family, no allowlist). Both run fully
   offline for Layer A (mock driver + committed `datasets/csv`; seeded extractor cache).
3. **Edition → Community `neo4j:5.26.23`** (the testcontainer). The Layer B goldens are
   **node/rel data only**, which is identical on Community and Enterprise (they differ
   only in constraint *declarations*, which are not part of the graph), so the goldens
   are edition-agnostic. Enterprise **constraint-parity** (`IS UNIQUE` vs `NODE KEY`) is
   the ticket's explicitly-optional latitude ("if constraint-parity is in scope"); it is
   **out of scope** for this safety-net ticket and deferred to the S5 generic-writer work
   (which would characterize it by stubbing `is_enterprise_edition`).
4. **Ordering → asymmetric by design.** Layer A **preserves** emission order (it is
   deterministic connector behavior; sorting would hide an ordering regression) and only
   sorts dict keys. Layer B **sorts** each node/relationship by its own canonical JSON
   (Neo4j does not guarantee return order).

## Determinism: what is excluded or normalized

| Source of nondeterminism | Handling |
|---|---|
| `embedding` | Dropped in Layer A (`None` today; the known nondeterminism source). Never present in the Layer B graph — ingest writes no embeddings (enrichment is a separate post-load pass), so the post-ingest graph is embedding-free by construction. |
| `__neocarta_graph__` singleton | Excluded from the Layer B dump — wall-clock `datetime()` timestamps + release version. |
| Neo4j internal/element ids | Never read; endpoints use the deterministic application `id`. |
| Neo4j return order / label-list order / dict-key order | Sorted in `dump_graph` (by canonical JSON) and via `sort_keys` at serialization. |
| MD5/SHA ids, name normalization | Deterministic (`generate_id.py`) — captured as-is; the id literals also guard the id helpers against regression. |

## What's in the tree

```
tests/support/characterization/
  serialize.py        serialize_transform                      (Layer A)
  normalized_dump.py  dump_records                             (Layer R)
  graph_dump.py       dump_graph                               (Layer B)
  golden.py           assert_matches_golden, canonical_json
  bigquery_cache.py   make_mock_bigquery_client, seed_bigquery_schema_cache
  __init__.py         public re-exports + DATASETS_CSV

tests/unit/connectors/csv/test_transform_golden.py               + golden/csv_transform.json              (Layer A)
tests/unit/connectors/bigquery/schema/test_transform_golden.py   + golden/bigquery_schema_transform.json  (Layer A)
tests/integration/connectors/csv/test_graph_golden_IT.py         + golden/csv_graph.json                  (Layer B)
tests/integration/connectors/bigquery/schema/test_graph_golden_IT.py + golden/bigquery_schema_graph.json  (Layer B)
tests/unit/etl/mapping_spike/test_normalized_records.py          + golden/*_records.json                  (Layer R)
```

## Self-validation (why the goldens can't falsely pass)

A golden test that cannot fail guards nothing. Each **Layer A** test pairs a
"matches-golden" assertion (PASS on a no-op) with a second test that monkeypatches a real
production rule (an id helper — `generate_table_id` for CSV, `generate_value_id` for
BigQuery) and asserts the comparison **raises** (FAIL on an injected change). That
demonstrates "PASS on a no-op, FAIL on an injected change, across ≥2 connectors" and is
CI-enforced. S1.6 (#297) is the worked example of what that buys: it swapped the entire
connector→graph mechanism for three connectors and proved parity against these goldens
*unchanged* (`tests/unit/etl/mapping_spike/test_parity.py`).

## Regenerating goldens

Opt-in and explicit — the harness never writes on failure:

```bash
UPDATE_GOLDENS=1 uv run pytest <path>
```

Layer B needs Docker (set `DOCKER_HOST` + `TESTCONTAINERS_RYUK_DISABLED=true` locally
when using colima). **Review hygiene:** a golden diff *with* a matching code change is an
intended behavior change (regenerate in the same PR, update `CHANGELOG.md`, treat the
diff as the reviewable record). A golden diff with *no* code change — or a code change
that produces *no* golden diff where one was expected — is a suspected regression or a
coverage gap. Never hand-edit a golden.

## Reference pattern — characterize before you refactor

1. **Pick the seam.** Transform-only change → Layer A (`serialize_transform`). Anything
   touching load / ingest / graph state → add Layer B (`dump_graph`). Cross ≥1 connector
   if the seam is shared.
2. **Freeze.** Add a golden test that feeds a fixed offline input, calls the layer helper
   + `assert_matches_golden(<golden>, ...)`, generate with `UPDATE_GOLDENS=1`, and
   **commit the `.json`**.
3. **Prove the net catches.** Add a sibling test that monkeypatches the rule you are about
   to refactor and asserts `assert_matches_golden(..., update=False)` raises (a golden
   that can't fail guards nothing).
4. **Refactor under the net.** Change the code, leave the goldens untouched. All-green =
   parity held. Run `make test-unit` (Layer A) / `make test-it` (Layer B).
5. **Intentional changes only.** If output legitimately changes, regenerate in the *same*
   PR, treat the golden diff as the behavior-change record, and update `CHANGELOG.md`.

**Housekeeping the pattern must respect:** new tests live under `tests/unit/**` /
`tests/integration/**` so the S0-3 marker hook auto-tags them (one marker each;
`make check-markers` stays green). Support modules and `.json` goldens are not collected.
New tests only *raise* the collected counts — bump the `[test_count]` floors in
`docs/testing/coverage-baseline.toml` in the same PR (ratchet-up, per S0-4). The harness
lives under `tests/` (outside `coverage source`), so it cannot move production coverage;
Layer B only *adds* ingest coverage.

## Revisit gate (re-validate after S3 transform & S5 ingest, per #291)

- Re-run the injected-change tests. If a refactor renamed a patched symbol, update the
  seam; if a mutation no longer produces a diff, sensitivity is lost — **hard stop**.
- Re-scan the determinism table for new fields: did S3 start populating `embedding` during
  transform, or change the `get_properties` allowlist? did S5 change the edition
  constraint logic, add labels, or fold enrichment into `ingest()` (which would make the
  graph no longer embedding-free — add embedding handling to `dump_graph` then)?
- Regenerate goldens *intentionally* with `UPDATE_GOLDENS=1` and review the diff as a
  behavior delta — never auto-update.
