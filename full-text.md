# Plan: Add Full-Text Search to the Databricks Connector

## The problem

Neocarta retrieval is hybrid. It blends three things:

- **Vector search** over embeddings (semantic similarity).
- **Full-text search** over keywords (Lucene matching on names and descriptions).
- A combined ranking of the two.

Every connector except Databricks creates full-text indexes on Schema, Table,
and Column. Those indexes are what let a user's keywords match table and column
**names**. The Databricks connector never creates them. So on a graph built by
the Databricks connector, keyword search over names silently returns nothing,
because the MCP server is querying indexes that do not exist.

This is the bigger half of the "names were never searchable" gap. Embedding the
names (already done) helps semantic search; this plan restores keyword search.

## The goal

Make the Databricks connector create the same full-text indexes as every other
connector, so keyword search over Schema, Table, and Column works on a
Databricks graph too.

## What already exists (so we reuse, not reinvent)

- A shared helper already builds these indexes and names them exactly the way
  the MCP server expects: `schema_full_text_index`, `table_full_text_index`,
  and `column_full_text_index`.
- The Databricks connector already has one place where it bootstraps all of its
  constraints and lookup indexes during ingest. The new indexes go there.
- Every Databricks node already stores both a bare `name` and a readable
  fully-qualified path (`catalog.schema.table`) in a `qualified_name` property.
  Nothing new has to be computed to qualify the index.

## The change, in plain steps

1. In the Databricks connector's index bootstrap step, after the existing
   constraints and lookup indexes are created, also create three full-text
   indexes: one for Schema, one for Table, one for Column.
2. Use the existing shared helper so the index names match what the MCP server
   queries.
3. This runs once per ingest, is safe to re-run (it creates an index only if it
   is missing), and needs no new configuration.

## Decision: what should the full-text index cover?

- **Today's default in the shared helper:** `name` and `description`.
- **Recommended addition:** also include the fully-qualified path
  (`qualified_name`), so users can disambiguate by catalog and schema (for
  example, "sales orders" or "the orders table in finance"). Lucene splits the
  dotted path into separate words, so the bare name still matches exactly while
  the catalog and schema words become searchable too.
- **Trade-off:** including the qualified path adds some recall noise (searching
  "sales" matches every table in that catalog), but the hybrid ranking sorts by
  relevance, so the disambiguation benefit generally outweighs it.

Note: this qualified-path decision is for **full-text only**. Embeddings stay on
the bare `name | type | description` text, to keep every connector embedding
identical text and to avoid diluting the vectors with non-semantic catalog and
schema words.

## How we will verify

- After an ingest, confirm the three full-text indexes exist.
- Run a keyword search for a known table and a known column name and confirm
  results come back. This is a read-only check against the Neo4j instance in
  `.env`.

## Out of scope

- Embeddings. They are a separate concern and are intentionally not qualified.
- A Database-level full-text index. The other connectors do not index Database
  either, so we match that.
