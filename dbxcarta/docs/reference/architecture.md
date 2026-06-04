# DBxCarta Architecture

Unity Catalog publishes tables, columns, and declared constraints. It does not
publish meaning. It cannot say which tables sit semantically near a question,
which relationships exist beyond the foreign keys someone remembered to declare,
or which medallion layer holds the trustworthy version of an entity. An agent
asked to write SQL over several hundred tables spread across layered catalogs
has names and structure but no navigable model of what any of it means.

DBxCarta builds that model in Neo4j: a semantic layer over Unity Catalog. The
semantic layer turns flat catalog metadata into a graph a question can traverse,
where similarity is an embedding distance, a relationship is a confidence-scored
edge rather than only a declared key, and the medallion layer of every table is
a queryable property. Text-to-SQL is the workload that exercises it, and the
evaluation harness is how the project proves the layer retrieves the right
slice instead of asserting that it does.

The deliverable is the build and the graph it produces: `dbxcarta-spark` reading
Unity Catalog and writing the Neo4j semantic layer, on the `dbxcarta-core`
foundation. The client is how the project proves that layer is worth building,
not part of what ships. That boundary is why the build path and the validation
harness are described separately below: one is the product, the other is the
evidence.

The semantic layer is only useful if it faithfully reflects the catalog it
describes. That fidelity drives the rest of the design: the data being mapped,
the semantic layer derived from it, and the bookkeeping that records what each
run did are kept in three separate storage planes so the layer never indexes
the tool's own exhaust.

## Three storage planes

```
                          UNITY CATALOG (the subject)
   ┌───────────────────────────────────────────────────────────────────┐
   │  graph-enriched-finance-silver   :silver   (DBXCARTA_CATALOG anchor)│
   │  graph-enriched-finance-gold     :gold                             │
   │     information_schema  +  sampled values        read-only         │
   └───────────────────────────────────────────────────────────────────┘
            │ extract metadata across DBXCARTA_CATALOGS
            │ layer = the :layer suffix on each DBXCARTA_CATALOGS entry
            ▼
   ┌──────────────────────────┐        ┌──────────────────────────────┐
   │   dbxcarta-spark         │        │  NEO4J  (the semantic layer)  │
   │   build pipeline         │ write  │  Database─HAS_SCHEMA→Schema    │
   │   preflight → extract →  ├───────►│  ─HAS_TABLE→Table─HAS_COLUMN→  │
   │   graph DFs → embed →    │ fail-  │  Column ; Table.layer (v1.1)   │
   │   sample → FK discover   │ closed │  REFERENCES{confidence}        │
   └────────────┬─────────────┘        │  vector indexes on embeddings │
                │                       └───────────────┬──────────────┘
                │ run summary                  retrieve  │
                ▼                                         ▼
   ┌───────────────────────────────┐        ┌───────────────────────────┐
   │  OPS CATALOG  dbxcarta-catalog │        │   dbxcarta-client          │
   │  (operational metadata only)   │◄───────┤   validation harness       │
   │  dbxcarta_run_summary          │ summary│   arms: reference,         │
   │  client_staging_<arm>  (cache) │  +     │   no_context, schema_dump, │
   │  DBXCARTA_SUMMARY_VOLUME       │  cache │   graph_rag                │
   └───────────────────────────────┘        └───────────────────────────┘
```

The two flows that matter are the downward build path on the left, where Unity
Catalog metadata becomes a semantic graph, and the retrieve path on the right,
where the client queries that graph to answer questions and writes only
operational results back to the ops catalog. The data plane is never written by
DBxCarta. The semantic layer is never polluted by the tool's own records.

### The data plane: Unity Catalog, read-only

The catalogs under evaluation are the source of truth and DBxCarta only reads
them. For a medallion layout each layer is its own catalog. The finance-genie
example uses `graph-enriched-finance-silver` and `-gold`.
`DBXCARTA_CATALOG` names a single anchor catalog used for preflight, verify, and
ops provisioning; `DBXCARTA_CATALOGS` lists every catalog folded into one
semantic layer, where each entry is `catalog` or `catalog:layer` and the
optional `:layer` suffix records which medallion tier each table came from. The build reads
`information_schema` and a bounded sample of values and writes nothing here, so
the meaning the layer encodes stays anchored to what the data team published.

### The semantic layer: Neo4j

The graph is the product. It treats the catalog as meaning rather than as a
list. A `Database` node per catalog fans out through `HAS_SCHEMA`, `HAS_TABLE`,
and `HAS_COLUMN` to `Column` nodes, so structure is traversable instead of
implied by naming. Three enrichments turn that structure into a semantic layer.
Embeddings on table and column nodes, backed by vector indexes, make "near in
meaning" a query a question can run. `REFERENCES` edges carry a confidence score
and are discovered from declared constraints and metadata heuristics, so a join
path the catalog never declared is still navigable and ranked by how much to
trust it. The `layer` property under graph contract v1.1
records each table's medallion tier, so a retriever can prefer the curated gold
table over a rawer silver one when both could answer a question.

This plane is the one the client reads at query time, and it is regenerable by
design. Because Unity Catalog is the source of truth, the semantic layer can be
rebuilt from it at any time, which is why the build write boundary is
fail-closed rather than incremental: a partial graph is a wrong graph, and a
wrong semantic layer is worse than a missing one.

### The ops plane: dbxcarta-catalog

Every artifact DBxCarta produces about its own runs lands in a separate
operational catalog, never in a data catalog and never in the graph. Its
location is derived from the catalog and schema of `DBXCARTA_SUMMARY_TABLE`; for
finance-genie that resolves to `dbxcarta-catalog`. It holds the run summary
table `dbxcarta_run_summary`, the per-arm generation cache tables
`client_staging_<arm>`, and the summary volume named by
`DBXCARTA_SUMMARY_VOLUME`. The isolation protects the semantic layer's fidelity.
Pipeline-owned artifacts record what happened without becoming part of the
subject. Writing a run summary or a generation cache into a data catalog would
inject DBxCarta's own bookkeeping into the `information_schema` that the next
build reads, and the semantic layer would start encoding meaning about its own
exhaust. The ops catalog is the boundary that keeps the layer a model of the
catalog and nothing else.

## Packages and layer responsibilities

DBxCarta is five packages over a shared, Spark-free core, in three tiers. The
product builds and serves the semantic layer; operator tooling runs it on
Databricks; the evaluation and demo tier proves and showcases it. The siblings
each depend on core but never on one another. The README carries the plain-English
summary; this section is the precise component breakdown each layer owns.

**The product**

- **Core** owns identifier and path quoting, the single `catalog:layer` parsing
  rule (`resolve_catalogs`), workspace and secret access, the SQL warehouse
  runner, the preset capability protocols and `StandardPreset`, the `.env`
  overlay loader, and the pure table-materialize SQL builders. It pulls in only
  the Databricks SDK, never Spark, Neo4j, or the job runner. The boundaries are
  enforced by `tests/boundary/test_import_boundaries.py`.
- **Spark** owns the concrete Unity Catalog ingest implementation, the graph
  contract, verification, the Databricks validators, the preset capability
  protocols, and the `dbxcarta` / `dbxcarta-ingest` entrypoints.

**Operator tooling**

- **Submit** builds the wheels, uploads them, and submits the spark, client, and
  materialize jobs. It is the only layer that depends on `databricks-job-runner`,
  runs on the operator's machine, and is never installed on the cluster.

**Evaluation & demo**

- **Client** owns the retrieval primitives, SQL parsing and read-only guards,
  result comparison, `ClientSettings`, and the `dbxcarta.client.eval` harness.
- **Materialize** is the serverless Spark shell that runs core's materialize SQL
  builders: core builds the `CREATE` / `INSERT` / foreign-key SQL as pure
  strings, and this layer owns the `SparkSession` and the bounded thread pool
  that runs them.

## Building the layer

The build path is server-side and runs in Spark. `dbxcarta-spark` reads Unity
Catalog metadata across the resolved catalogs, builds graph-shaped DataFrames,
adds embeddings through `ai_query`, samples values, discovers foreign keys
through declared constraints and metadata inference, and writes the
semantic layer to Neo4j behind a fail-closed boundary, then records its run
summary in the ops catalog. The pipeline internals are documented in
[`pipeline.md`](pipeline.md); the rules that constrain it, including why rule
logic is native Spark and never a Python UDF, are in
[`best-practices.md`](best-practices.md). One current limitation: post-write
verify keys off the single anchor catalog, so in a multi-catalog build the other
catalogs are written but not independently verified.

Three architectural choices shape that path. It is a **single submission**: one
installed wheel entrypoint drives extract, embed, sample, FK discovery, and the
Neo4j write as one Databricks Job, with scope controlled by per-label embedding
flags rather than by separate jobs. It is **materialize-once**: enriched node
DataFrames are written to a Delta staging table between transform and load, so
the failure-rate aggregation and the Neo4j write both read the staged rows
without re-invoking `ai_query`, and each row is embedded exactly once per run.
And the write boundary is **fail-closed**: a partial graph is a wrong graph, so a
failed run leaves no half-written layer rather than a silently incomplete one.
The operational tuning these choices imply, Neo4j connector partitioning and
batch size, preflight grant checks, secret handling, and run observability, is in
[`best-practices.md`](best-practices.md).

### How we validate

A semantic layer is only worth building if a question is answered better by
traversing it than by ignoring it, so `dbxcarta-client` runs a held-out
question set through four arms and scores them the same way: parsed, executed,
non-empty, and matched against a reference result. `graph_rag` is the semantic
layer in use, seeding from vector similarity on the question and expanding along
confidence-ranked `REFERENCES` edges to retrieve a focused subgraph. The other
three are controls. `reference` executes the ground-truth SQL to establish what
a correct answer returns. `no_context` gives the model only the catalog name and
sets the floor. `schema_dump` pastes a bounded schema, capped near two thousand
tokens and pulled from the graph across every resolved catalog, so the control
sees silver and gold rather than only the anchor. `graph_rag` justifies
the build pipeline only if it beats `schema_dump` at this matched token budget
and both clear `no_context`; the cap is what turns `schema_dump` from a "paste
everything" strawman into a real competitor for the same budget.

The harness caches generation so iterating on retrieval and prompts does not pay
model latency every run, hashing the prompts so an unchanged re-run reuses prior
responses and any change forces fresh generation. The cache table layout, the
`_input_hash` rules, the `DBXCARTA_CLIENT_REFRESH` override, and the Delta
retention stance are reference detail in
[`public-api.md`](public-api.md#client-evaluation-harness).

The scores are only trustworthy if the grader is. When a generated query is
correct but the harness grades it wrong, the fix is the grader, never a prompt
instruction that steers the model toward what the grader happens to accept.
Prompt changes must make the SQL better on its own terms; shaping output to
conform to a grader artifact inflates the number while the capability it claims
to measure does not move, which defeats the entire point of running the four
arms against a matched budget. A grader limitation is a grader bug and is
tracked as one.

## What this architecture costs

A semantic layer that lives outside Unity Catalog is only as current as the last
build, and nothing the client does works until that build has run. The
fail-closed write boundary makes the layer a clean rebuild rather than a live
mirror, which is correct when the layer's value is fidelity to a published
catalog and wrong for a system that needs the index to track schema changes in
real time. The single-anchor verify limitation means a multi-catalog build
trusts that the non-anchor catalogs wrote correctly.

The trajectory the architecture is built for is the layer getting richer.
Declared keys give the first edges; metadata inference adds the ones
no one declared, each carrying a confidence the retriever can weigh. Embeddings
make tables findable by meaning rather than by name. The layer property lets the
retriever prefer the curated answer over the raw one. Each build can encode more
of the catalog's meaning than the last, and the validation harness is what keeps
that enrichment honest: a semantic layer is only worth building if a question
can be answered better by traversing it than by ignoring it.
