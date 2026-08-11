# Merge / idempotency & sparse-row contract

> Delivered by **S1.3** (#294). This is the elaboration of **GUIDE D10** — *"sparse rows are
> supported with a non-clobber merge contract (partial data never erases fuller data)"* —
> from one sentence into an executable, tested specification.
>
> The contract is what lets **multiple connectors, and multiple runs of the same connector,
> contribute to one entity**. `query_log` knows a column's `name`; `bigquery/schema` knows its
> `type`, `description` and key flags. Both address the same `:Column`. Neither may lose the
> other's work, and neither may depend on running first.

## The contract

For any entity addressed by its `id`, a write is:

1. **Non-clobber** — a property the incoming row does not carry never replaces a stored value.
2. **Idempotent** — re-emitting a row that has already been written changes nothing.
3. **Order-independent** — where two rows carry *complementary* properties, feeding
   sparse→full and full→sparse converge on the same entity. This holds *within* a single
   `UNWIND $rows` batch as well as across separate writes: `UNWIND` processes rows sequentially,
   so a sparse and a full row for the same `id` in one batch coalesce onto each other in either
   arrangement, and callers do not have to deduplicate a batch. (`OVERWRITE` has no such
   property — there, the last row in the batch wins outright.)

### Two layers, because "does not carry" has two meanings

A property can be missing from a write in two distinct ways, and both have to be handled or
the contract leaks.

| Layer | Meaning | Mechanism | Owner |
|---|---|---|---|
| **1 — property scope** | *the source has no such concept* | the caller's `properties_list`: a property outside it gets no `SET` clause at all | the connector / normalizer |
| **2 — value coalescing** | *the source has the concept but no value for this row* | `n.p = coalesce(row.p, n.p)` | the writer (`MergePolicy.COALESCE`) |

Layer 2 alone is **not** sufficient, and the reason is concrete. `Column.nullable` is a bare
`bool` defaulting to `True`, so a producer that knows nothing about nullability emits `True` —
indistinguishable from an asserted `True`, and non-`NULL`, so `coalesce` waves it through and it
replaces a stored `False`. Only layer 1 (leaving `nullable` out of `properties_list`, which
`connectors/query_log` already does) keeps that row honest. This is why the normalized models
default `is_primary_key` / `is_foreign_key` to `None` rather than a fabricated `False`
([`normalized_schema`](../../neocarta/etl/metadata_normalizer/normalized_schema/README.md)):
a tri-state field is protected by layer 2 on its own, a two-state field is not.

Layer 1 alone is not sufficient either — it is per *write*, not per *row*, so a batch in which
only some rows know a property still needs layer 2 for the rest. `connectors/jdbc`'s
`get_column_properties()` shows the seam: it admits `description` to the allowlist if **any**
column in the batch has one, which leaves every description-less row in that batch relying on
layer 2.

### The two-state properties a shipped loader actually writes

Exhaustively, across every model any loader can write, these are the fields whose default is a
fabricated value rather than `None`, so **only layer 1 can protect them**:

| Field | Written by | Protected today? |
|---|---|---|
| `Column.nullable` | every tabular schema connector | yes — `query_log` writes `properties_list=["name"]` |
| `Column.is_primary_key` / `is_foreign_key` | tabular schema connectors | yes — `dataplex` narrows to `["name","description","type"]`; `jdbc` and `csv` compute the allowlist |
| **`OsiColumn.is_primary_key` / `is_foreign_key`** | **`load_osi_column_nodes`** | **no — see below** |

`load_osi_column_nodes`' default `properties_list` admits both key flags, and its only producer
(`osi/ingest/transform.py`) emits `field_name in primary_key_columns` — a hard `True`/`False`,
never `None`. So "the semantic model declared no primary key" is indistinguishable from "asserted
not a primary key", and because OSI routes through the same `generate_column_id`, those rows land
on the *same* `:Column` a tabular connector uses to assert the real flag. Under `COALESCE`,
`coalesce(false, true) = false` erases it. Verified live: two OSI models over one source converge
on **different** graphs depending on feed order, which breaks order-independence, not just
non-clobber; and a real BigQuery ingest followed by an OSI ingest downgrades `is_primary_key` from
`True` to `False`. Today's `CREATE_ONLY` default preserves it in both cases.

This one cannot be fixed by the route the rest of this section relies on. The normalized models'
`None` defaults reach the *tabular* connectors at S4, but OSI is the **graph/semantic** paradigm
(GUIDE D11) and never passes through the normalized schema. It needs its own fix before S5 flips
the default: emit `None` when the model declares no key, mirroring what the same transform already
does one grain up (`OsiTable.primary_key` folds `[] → None` and is correctly non-clobbering).
Narrowing the `properties_list` instead would be wrong — it would also discard a genuine `True`.

## Enforcement site (the S1.3 latitude call)

**The writer enforces the merge; the normalized model declares only value semantics.**

`MergePolicy` and the `coalesce` generation live in
[`neocarta/ingest/utils.py`](../../neocarta/ingest/utils.py) — the shared builder every loader
already routes through, and the module GUIDE §5 maps onto `etl/pipeline` + the generic writer
(S5). The normalized models declare *what a value means* (`None` = "the source said nothing",
GUIDE D7/D10) and nothing about writing.

Why not declare the policy on the normalized model:

- **Non-clobber is a property of a write against prior state, not of a row.** A Pydantic row
  model cannot see the stored value, so it could only carry an annotation that the writer must
  then read and act on — two owners of one piece of state, against GUIDE §4.
- **The normalized contract is deliberately graph-agnostic** (D6). Its guards actively reject
  graph identity on a field — with the single reserved, opt-in exception S1.4 added for
  cross-source alignment ([explicit-id-override.md](explicit-id-override.md)), which those same
  guards now enumerate rather than forbid — and require every field annotation to stay a bare
  scalar. A merge policy is a graph-write concern; declaring it there re-couples the contract to
  the ontology it exists to decouple from.
- **The model→writer channel already exists.** Layer 1 *is* `properties_list`, and
  `_validate_properties_list` already checks it against the model's fields. Nothing new is
  needed to express which properties a source speaks about.
- **One owner, and it moves as a unit.** `_build_node_ingest_query` /
  `_build_relationship_ingest_query` are the only *shared* place write semantics are decided, so
  S5 inherits the policy by moving the module (`ingest/` → `etl/pipeline` + generic writer).
  **Seven** hand-written statements sit outside them, and all seven are policy-invariant:
  - the `__neocarta_graph__` singleton upsert (`ingest/metadata.py`), whose `ON CREATE` /
    `ON MATCH` split is already a bespoke per-property policy;
  - `OsiNeo4jLoader.load_business_term_nodes_by_name`, which MERGEs on `name` rather than `id`
    and so is outside this contract's id-addressed scope;
  - five OSI relationship writers (`osi/load.py` `load_has_aspect_relationships`,
    `load_has_expression_relationships`, `load_has_source_table_relationships`,
    `load_has_target_table_relationships`, `load_osi_tagged_with_relationships`) whose
    polymorphic multi-label `MATCH` the shared relationship builder cannot express. They set
    **no** relationship properties at all, so there is nothing for a merge policy to govern —
    they take no policy parameter and none is needed.

  Folding all seven into the generic writer is S5's problem; only the first two would need a
  per-property policy when it does.

## The three policies

`MergePolicy` partitions the space of "what happens on a `MERGE` that matched":

| Policy | Cypher | On match |
|---|---|---|
| `CREATE_ONLY` | `ON CREATE SET n.p = row.p` | nothing — first writer wins |
| `OVERWRITE` | `SET n.p = row.p` | every property written, `NULL` included |
| `COALESCE` | `SET n.p = coalesce(row.p, n.p)` | non-`NULL` values written, `NULL` skipped |

`COALESCE` is the D10 contract. It is never destructive: `coalesce(NULL, 'x') = 'x'` rewrites the
stored value unchanged, and `coalesce(NULL, NULL) = NULL` leaves an already-absent property absent
(Neo4j drops a property set to `NULL`, so a sparse row never mints an empty one — the same
"omit undefined props" outcome the connectors hand-roll today). Secondary labels apply on every
merge under `COALESCE`, as under `OVERWRITE`: adding a label cannot lose information.

The legacy `overwrite_existing` boolean is still accepted in the same argument slot and resolves
to `OVERWRITE` / `CREATE_ONLY`, so every existing call site keeps its byte-identical Cypher.

## Parity: what today's writer actually does

Characterized in `tests/integration/ingest/test_merge_contract_IT.py` against a real Neo4j,
feeding the `query_log`-shaped sparse `:Column` and the `bigquery/schema`-shaped full one through
`Neo4jRDBMSLoader` with its shipped defaults (`CREATE_ONLY`):

| Feed order | `CREATE_ONLY` (today) | `COALESCE` (the contract) |
|---|---|---|
| full → sparse | full row survives ✅ | full row survives ✅ |
| sparse → full | **full row's `type` / `description` / key flags never land** ❌ | full row's values land ✅ |

So today's writer satisfies *non-clobber* — but only degenerately, by never updating anything —
and fails *order-independence*. `COALESCE` agrees with today's behavior in the full→sparse order
and fixes the sparse→full order, which is the whole delta. That order is not hypothetical: every
`examples/*query_log*` script runs a logs connector alone, so any schema ingest that follows one
hits it. (The top-level `README.md`'s "Combined Usage" section prescribes schema-then-logs — the
order that already works — so following it avoids the gap; it is deviating from it that does not.)

Confirmed end to end on real data, not only on synthetic rows: two runs of the production
`CSVConnector` over the shipped `datasets/csv`, one full and one over a CSV that simply omits the
optional columns (so the connector's own allowlist narrows for real), reproduce exactly the table
above — sparse→full under the shipped default leaves `customers.customer_id` with nothing but
`name`, and `COALESCE` converges both orders on the full row.

## Documented limits

Five cases the contract deliberately does not cover, each a different owner:

- **Two sources asserting different non-`NULL` values for the same property** → last write wins.
  D10 is about *loss*, not *disagreement*; arbitrating conflicting authorities is a provenance
  question with no source of truth at this layer. Order-independence is claimed for
  *complementary* rows only.
- **An empty value is a value, not an absence.** `coalesce` only skips `NULL`, so `""` and `[]`
  both count as present and both overwrite. For strings that is decided at the model layer, where
  `coerce_str_or_none` keeps `""` on purpose — a D7 coercion question, not a writer one. For
  **collections** it is a live concern for S5 rather than today. The properties a loader writes as
  **native Neo4j arrays** are `OsiTable.primary_key` and `Join.from_columns` / `to_columns` (both
  `list[str]`, and both in `load_join_nodes`' *default* `properties_list`); `OsiTable.unique_keys`
  is `json.dumps`-encoded to a string before the write (`osi/load.py:125`, because Neo4j cannot
  store nested lists) and so coalesces as a scalar — though `json.dumps([])` is `"[]"`, which is
  still non-`NULL` and still overwrites. A producer emitting `[]` for "no key" instead of `None`
  would therefore clobber a stored list, and for `Join` that would destroy the positional
  `from_columns[i]` ↔ `to_columns[i]` pairing those arrays exist to preserve, which the OSI export
  reads straight back off the node. Today's sole producer is safe — `osi/ingest/transform.py`
  already writes `from_columns or None` — and nothing writes any of them under `COALESCE` (the OSI
  loader is `CREATE_ONLY`). The fix belongs with whichever S5 producer first needs it: normalize
  `[]` → `None` at the model layer, as the tri-state key flags already do, or keep these
  properties out of the coalescing write's scope.
- **Derived state computed from a coalesced property is not invalidated.** `COALESCE` makes a
  property *mutable after create* — `coalesce(row.p, n.p)` returns `row.p` whenever it is non-`NULL`,
  so a later producer **replaces** the stored value. Nothing downstream is told. The live instance is
  `embedding`: `get_nodes_to_embed` fetches only where `n.embedding IS NULL`
  (`enrichment/embeddings/utils.py`) and nothing in the repo ever removes an embedding. That gate is
  sound under `CREATE_ONLY`, where a stored `description` can never change after create; under
  `COALESCE` a node whose `description` was replaced keeps the embedding of the superseded text, so
  the full-text index (which Neo4j maintains automatically) and the vector index disagree, and the
  hybrid MCP search can return a node at top score for a concept it no longer describes. Every ingest
  CLI command runs the embedder right after loading, so the run that changes the description is the
  run that skips re-embedding it. **S5 must ship embedding invalidation alongside the default flip** —
  either drop `embedding` when a coalesced `description` differs from the stored one, or widen the
  fetch gate past `IS NULL`.
- **Idempotency is of graph *state*, not of write counters.** Under `COALESCE` the `SET` executes
  on every merge, so a no-change replay still reports `properties_set > 0` and
  `contains_updates=True` — measured: `created=0, properties_set=3` replaying an identical row
  whose stored properties were byte-identical before and after. Today's `CREATE_ONLY` default
  reports `0` / `False` there, and `OVERWRITE` already behaves as `COALESCE` does. This matters
  because `_run_write` logs that counter at INFO and returns `counters.__dict__`, so after the S5
  flip a no-op re-ingest is no longer distinguishable from a real one by that signal alone.
- **Relationships and labels are additive only.** `MERGE` on the endpoint pair plus type, with
  relationship properties coalesced the same way; nothing removes an edge or a label. Note the
  standing constraint that relationship endpoints are `MATCH`ed, not `MERGE`d, so a row whose
  endpoints do not exist yet is silently dropped — that is a load-ordering property of the
  current writer, unchanged here and out of scope for D10.

## Adoption

Additive, per GUIDE §2. `COALESCE` ships as an opt-in policy on the writer primitive; every
current loader call site keeps `CREATE_ONLY` and no connector's emitted Cypher changes, so both
Layer-B graph goldens and the pinned-Cypher unit tests stay green. Connectors flip to the
normalized contract in **S4** and the generic writer adopts `COALESCE` as its default in **S5**,
each proven at parity against the #291 characterization harness. The S4/S5 flip is where the
`Column.is_primary_key` `False`→`None` reconciliation the `normalized_schema` README already
lists comes due, since it is exactly the tri-state that layer 2 needs.

## Tests

| What | Where |
|---|---|
| Cypher shape per policy, legacy-flag parity (including `numpy.bool_` tolerance and strict rejection of a misspelled policy string), negative controls (`CREATE_ONLY`/`OVERWRITE` must **not** coalesce) | `tests/unit/ingest/test_merge_contract.py` |
| sparse→full, full→sparse, order-independence via `dump_graph` equality, re-emit idempotency, `NULL` never erases, both layers exercised against today's real `query_log` row shape as well as the normalized tri-state shape, `OVERWRITE` erases (sensitivity), today's `CREATE_ONLY` behavior characterized | `tests/integration/ingest/test_merge_contract_IT.py` |

Sensitivity was verified the way the #291 harness's reference pattern demands: `COALESCE` was
degenerated to each of the other two policies, plus five other targeted mutations (swapped
`coalesce` arguments, relationship builder losing its wrapper, inverted legacy-flag mapping,
dropped secondary labels, silenced `ConfigError`). All seven were caught, most at both layers.

Order-independence is asserted as whole-graph equality between the two feed orders using
`dump_graph` from the #291 harness, which is stronger than per-property assertions: it also
catches a stray extra node or edge.
