# Characterization / Golden-Master Harness

> Built in **S0-SPIKE-1** (#291). This is the harness the refactor GUIDE §4
> (*characterization-first*) points at: **capture current behavior as golden-masters
> *before* refactoring the code they guard**, then keep the goldens green through the
> change. Every later "characterize-before-you-refactor" ticket (S1 / S3 / S5) reuses
> the reference pattern at the bottom of this doc.

## Why it exists

The refactor is *additive dual-path* (GUIDE §2): new components are built beside the
old ones and must be proven **byte-for-byte equivalent** before anything is removed.
That proof is only possible if current behavior is frozen first. This harness provides
the freeze + compare mechanism at two layers.

## The two layers

| Layer | Captures | Runtime | Helper | Determinism |
|---|---|---|---|---|
| **A — transform-level** | the node/relationship model lists a connector's transformer produces (`*_nodes` / `*_relationships` accessors) + the `get_properties` allowlist | **no Docker** (unit) | `serialize_transform` | emission order preserved; `embedding` excluded |
| **B — post-ingest graph** | every node (labels + properties) and relationship (endpoint `id`s + type + properties) after ingest into Neo4j | Docker (`Neo4jContainer`, integration) | `dump_graph` | order normalized; embeddings excluded (or stubbed); metadata node excluded |

Both compare against committed JSON goldens via `assert_matches_golden`. The reusable
code lives in **`tests/support/characterization/`** (not collected as tests); the
per-connector golden tests and their `.json` goldens live next to the connector they
cover.

## Fixed decisions (Latitude items, per GUIDE §9 — recorded here as the PR justification)

1. **Serialization → custom JSON goldens.** Plain `.json` via
   `json.dumps(indent=2, sort_keys=True, ensure_ascii=False)` + trailing newline;
   compared with `difflib`. No snapshot-library dependency (fits the 0.8.1 "safety net,
   zero behavior change" band), fully git-diffable so a reviewer reads the parity delta
   directly, and total control over the two normalization concerns (ordering,
   nondeterminism exclusion). It is the natural scale-up of the in-code
   `_EXPECTED_GRAPH` literal in `test_normalized_parity.py`, which does not scale to the
   full CSV dataset or a post-ingest graph dump.
2. **Connectors → CSV + BigQuery.** Deliberately divergent shapes: CSV
   (`CSVTransformer`, 9 node / 11 rel families + a `get_properties` allowlist) and
   BigQuery (the shared `NormalizedGraphTransformer`, 5 / 5, no allowlist). Both run
   fully offline for Layer A (mock driver + committed `datasets/csv`; seeded extractor
   cache) so the serializer is proven against both shapes.
3. **Edition → characterized against Neo4j Community `5.26.23`** (the testcontainer).
   Layer B goldens are **node/rel data only**, which is identical on Community and
   Enterprise, so the goldens are edition-agnostic. The one edition delta —
   `IS UNIQUE` (Community) vs `NODE KEY` (Enterprise) constraints — is characterized
   **without a second container** by `tests/unit/ingest/test_edition_constraints.py`,
   which stubs `is_enterprise_edition` and records the Cypher `write_neo4j_constraints`
   emits for each branch. A real Enterprise container was judged more than this spike
   needs (CI weight + licensing).
4. **Embeddings → stubbed with `DeterministicEmbeddingsConnector`** (vectors are a pure
   function of the input text via `sha256`). The two mandated layers are embedding-free
   by construction — enrichment is a separate post-load pass — so the stub is used only
   by the optional enriched-graph golden, but it makes "embeddings stubbed" robustly
   true for any path that touches them.
5. **Ordering → asymmetric by design.** Layer A **preserves** emission order (it is
   deterministic connector behavior; sorting would hide an ordering regression). Layer B
   **sorts** (Neo4j return order is not behavior) by `(labels, id)` for nodes and
   `(type, src, dst)` for relationships, with a canonical-JSON tiebreaker.

## Determinism: what is excluded or normalized

| Source of nondeterminism | Handling |
|---|---|
| `embedding` float vectors | Excluded from Layer A and the core Layer B dump. The enriched golden keeps them via the deterministic stub, and read-back floats are rounded (5 dp) to absorb float32 storage drift. A guard (`assert_transform_embeddings_absent`) fails if a future transform starts populating them. |
| `__neocarta_graph__` singleton | Excluded from the Layer B dump — it carries wall-clock `datetime()` timestamps + the release version and has no `id`. Characterized separately by shape invariants (`initial_version == latest_version == neocarta.__version__`, `create_date <= last_updated`). |
| Neo4j internal/element ids | Never read; endpoints use the deterministic application `id`. |
| Neo4j return order / label-list order / dict-key order | Sorted in `dump_graph` and via `sort_keys` at serialization. |
| Edition-dependent constraint *type* | Not in the graph golden (data is edition-agnostic); characterized by the stubbed unit test. |
| MD5/SHA ids, name normalization | Deterministic (`generate_id.py`) — captured as-is; the id literals also guard the id helpers against regression. |

**Known future watch-items** (revisit gate): pandas dtype-inference drift on value
columns is pandas-version sensitive; the `neo4j:5.26.23` image is pinned by tag, not
digest; Layer B assumes single-worker (the container fixture is module-scoped and leaks
via `os.environ`, so do not add `pytest-xdist` to the integration job without
worker-keying the container).

## What's in the tree

```
tests/support/characterization/
  serialize.py       serialize_transform, assert_transform_embeddings_absent   (Layer A)
  graph_dump.py      dump_graph, fetch_metadata_node                           (Layer B)
  golden.py          assert_matches_golden, canonical_json
  embeddings.py      DeterministicEmbeddingsConnector
  bigquery_cache.py  make_mock_bigquery_client, seed_bigquery_schema_cache
  paths.py           repo_root, DATASETS_CSV

tests/unit/connectors/csv/test_transform_golden.py               + golden/csv_transform.json                 (Layer A)
tests/unit/connectors/csv/test_transform_mutation_meta.py                                                    (sensitivity)
tests/unit/connectors/bigquery/schema/test_transform_golden.py   + golden/bigquery_schema_transform.json     (Layer A)
tests/unit/connectors/bigquery/schema/test_transform_mutation_meta.py                                        (sensitivity)
tests/unit/ingest/test_edition_constraints.py                                                                (edition)
tests/integration/connectors/csv/test_graph_golden_IT.py         + golden/csv_graph.json                     (Layer B + sensitivity)
tests/integration/connectors/csv/test_enriched_graph_golden_IT.py + golden/csv_enriched_graph.json           (Layer B, stubbed embeddings)
tests/integration/connectors/bigquery/schema/test_graph_golden_IT.py + golden/bigquery_schema_graph.json     (Layer B)
```

## Self-validation (why the goldens can't falsely pass)

A golden test that cannot fail guards nothing. The mutation **meta-tests** monkeypatch a
real production rule and assert the comparison *raises*:

- **Layer A / CSV** — changing the table-id helper (`generate_table_id`) and blanking the
  `get_properties` allowlist (`_available_properties`).
- **Layer A / BigQuery** — collapsing `generate_value_id`, and removing the
  self-referential-FK drop rule in `NormalizedGraphTransformer` (fed the shared
  `information_schema_table` fixture, whose self-ref artifact must be dropped).
- **Layer B / CSV** — a `generate_table_id` change is caught by the post-ingest graph
  golden too.

Each meta-test also asserts the *unmutated* output stays green, so "PASS on a no-op,
FAIL on an injected change, across ≥2 connectors" is demonstrated and CI-enforced. The
already-in-tree `test_normalized_parity.py` (which froze the pre-#271 bespoke BigQuery
graph and stayed green through the shared-normalizer rewrite) is a real no-op-refactor
this harness generalizes.

## Regenerating goldens

Opt-in and explicit — the harness never writes on failure:

```bash
UPDATE_GOLDENS=1 uv run pytest <path>        # or:  uv run pytest --update-goldens <path>
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
3. **Prove the net catches.** Confirm green on HEAD; make a throwaway behavior tweak and
   confirm the golden goes red with a readable diff; revert. (A committed mutation
   meta-test makes this permanent — see above.)
4. **Refactor under the net.** Change the code, leave the goldens untouched. All-green =
   parity held. Run `make test-unit` (Layer A) / `make test-it` (Layer B).
5. **Intentional changes only.** If output legitimately changes, regenerate in the *same*
   PR, treat the golden diff as the behavior-change record, and update `CHANGELOG.md`.

**Housekeeping the pattern must respect:** new tests live under `tests/unit/**` /
`tests/integration/**` so the S0-3 marker hook auto-tags them (one marker each;
`make check-markers` stays green). Support modules and `.json` goldens are not collected.
New tests only *raise* the collected counts — bump the `[test_count]` floors in
`docs/testing/coverage-baseline.toml` in the same PR (ratchet-up, per S0-4). The harness
lives under `tests/` (outside `coverage source=["neocarta"]`), so it cannot move
production coverage; Layer B only *adds* ingest coverage.

## Revisit gate (re-validate after S3 transform & S5 ingest, per #291)

- Re-run the mutation meta-tests. If a refactor renamed a patched symbol, update the
  seam; if a mutation no longer produces a diff, sensitivity is lost — **hard stop**.
- Re-scan the determinism table for new fields: did S3 start populating `embedding`
  during transform? add ordering/timestamps? change the `get_properties` allowlist? did
  S5 change the edition constraint logic, add labels affecting label order, or fold
  enrichment into `ingest()`?
- Regenerate goldens *intentionally* with `--update-goldens` and review the diff as a
  behavior delta — never auto-update.
- Re-run `tests/unit/ingest/test_edition_constraints.py`.
