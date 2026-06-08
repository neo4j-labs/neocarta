# dbxcarta: Neo4j Semantic Layer for Databricks Unity Catalog

## Summary

* dbxcarta builds a Neo4j semantic layer over Databricks Unity Catalog.
* A Spark data pipeline reads Unity Catalog metadata and loads it into a graph a question can traverse.
* The pipeline runs as a batch job, so it scales to large Unity Catalog schemas.
* Similarity becomes an embedding distance, a relationship becomes a confidence-scored edge, and every table carries its medallion layer.
* It is the Databricks counterpart to neocarta.

## How it works

* **Build time:** A single Databricks Spark job reads Unity Catalog metadata, embeds it with a Databricks foundation model, infers foreign keys, and writes the result into Neo4j as typed nodes with vector properties.
* **Query time:** A client embeds a user question, runs a vector search to find the most relevant nodes, then walks the graph edges to expand that seed into a complete schema subgraph for the LLM.
* **Everything runs inside Databricks:** no external orchestrators, no local execution, no service accounts. You build and submit the job from your own machine, but the work happens on the cluster.

## Main components

dbxcarta is five packages in three tiers built on a shared, Spark-free core. The two you actually need to map your own catalog are `dbxcarta-core` and `dbxcarta-spark`. The rest support, run, and demonstrate them.

**The product** (what you need for your own catalog):

* **dbxcarta-core:** The shared foundation every other package builds on. It holds the common building blocks for naming and paths, reading config and secrets, running SQL, and loading settings. It depends only on the Databricks SDK, never Spark or Neo4j.
* **dbxcarta-spark:** The build pipeline. It reads Unity Catalog across one or more catalogs, tags each table with its medallion layer, embeds the metadata, discovers and confidence-scores foreign keys, and writes the semantic-layer graph into Neo4j.

**Operator tooling** (runs the pipeline on Databricks):

* **dbxcarta-submit:** The command you run on your own machine to build the wheels, upload them, and launch the Databricks jobs. It is the only piece that touches the job runner, and it never runs on the cluster.

**Evaluation and demo** (prove and showcase the layer):

* **dbxcarta-client:** Queries the finished graph to retrieve schema context and runs a Text2SQL evaluation that proves the layer earns its place. It scores several arms (reference, no-context, schema-dump, and graph-RAG) so you can see whether the graph actually beats a plain schema paste.
* **dbxcarta-materialize:** A Databricks job that creates the bundled example demo tables from a saved blueprint. It only applies to the examples; against your own catalog the tables already exist.

## Graph schema

The pipeline writes a stable, typed contract: nodes for `Database`, `Schema`, `Table`, `Column`, and `Value`, connected by `HAS_SCHEMA`, `HAS_TABLE`, `HAS_COLUMN`, `HAS_VALUE`, and confidence-scored `REFERENCES` edges between columns. Each node carries a catalog-qualified `id`, a `description`, and an `embedding` where applicable. `Table` nodes also carry their medallion `layer`.

## Examples

dbxcarta ships three companion examples. Each is its own Python package that depends on dbxcarta as a normal dependency and exposes a reusable **preset**: a packaged configuration adapter that bundles the environment overlay, an optional catalog readiness check, and an optional demo-question upload. A preset captures the setup knowledge once so anyone can run dbxcarta against the same upstream project without hand-managing environment variables.

* **Finance Genie:** A two-catalog medallion layout. Curated business tables live in silver, graph-enriched features in gold, and dbxcarta folds both catalogs into one Neo4j semantic layer while tagging each table's tier.
* **SchemaPile:** A reproducible slice of the open SchemaPile dataset materialized as Delta tables in a dedicated, data-only catalog, with a SQL-validated question set generated for evaluation.
* **Dense schema:** A stress test for schema-context retrieval. A synthetic single schema of 500 or 1000 tables checks how well retrieval holds up against very dense schema context.
