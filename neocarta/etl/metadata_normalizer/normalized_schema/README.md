# Normalized structural core

The flat, standardized, **natural-key-addressed** tabular contract every schema
connector emits — the source-agnostic substrate that decouples connectors from
the ontology (GUIDE §6). This is the connector's **only** public output (D5);
the extractor cache stays private.

Defined in [`models.py`](models.py). Delivered by S1.1 (#292) as a **contract**:
no runtime path uses it yet — connectors flip to it in S4, proven at parity
against the #291 characterization harness.

## What it is

Five row models plus a bundle:

| Model | One row is | Natural key |
|---|---|---|
| `DatabaseRecord` | a database / project / catalog | `database_name` |
| `SchemaRecord` | a schema / dataset | `database_name`, `schema_name` |
| `TableRecord` | a table or view | `database_name`, `schema_name`, `table_name` |
| `ColumnRecord` | a column | `database_name`, `schema_name`, `table_name`, `column_name` |
| `ForeignKeyRecord` | a `REFERENCES` edge | source + target column keys |
| `NormalizedStructuralSchema` | the whole emitted contract | — |

### Design rules (with the decision each honors)

- **Source-derived fields only — no graph IDs, no embeddings** (D6). Identity is
  assigned downstream by the KeySpec-driven ID builder from the raw key segments
  each row carries; the `generate_id` logic is not replicated here.
- **Natural-key-addressed, so containment is implicit.** A `ColumnRecord` already
  carries its full `database/schema/table` path, so `HAS_SCHEMA` / `HAS_TABLE` /
  `HAS_COLUMN` are derivable and are **not** modelled as tables. Only the
  cross-hierarchy foreign-key reference — which cannot be derived — is a table.
- **Sparse rows** (D10). Key metadata (`is_primary_key` / `is_foreign_key`)
  defaults to `None` = "the source said nothing", never a fabricated `False`, so
  a non-clobber merge can't let a partial row erase a fuller one. `nullable`
  keeps the permissive `True` default to match the current graph model.
- **Value coercions, not just renames** (D7). `nullable` folds the standardized
  token vocabulary (`YES`/`NO`, `NULLABLE`/`REQUIRED`, native bools) via
  `coerce_nullable`; `description`/`data_type` scrub NaN → None;
  `platform`/`service` upper-case. Source-specific fallbacks (e.g. Dataplex
  `REPEATED` → not nullable) stay in the connector.

## Standardized vocabulary (proposed; #296 to ratify)

Each canonical token — the field name, and what `model_dump()` emits — accepts
the known source synonyms via `AliasChoices` (canonical listed first), so a
connector's **raw** source row validates directly and a spin-out connector can
always emit canonical names without editing this contract (D17).

| Concept | Canonical token | Source synonyms absorbed |
|---|---|---|
| container | `database_name` | `project_id`, `table_catalog`, `catalog_name`, `database`, `catalog` |
| schema | `schema_name` | `table_schema`, `dataset_id` |
| table | `table_name` | `table_id` (Dataplex identity segment) |
| data type (×4) | `data_type` | `column_data_type`, `type`, `column_type` |
| nullability (×3) | `nullable` | `is_nullable`, `column_mode` |
| description | `description` | `comment`, `table_description`, `column_description` |
| table label | `display_name` | `table_display_name` |

`ForeignKeyRecord` uses **role-scoped** aliases so a connector's FK frame that
names the two sides separately (`table_*` vs `referenced_*`) or shares one
(`constraint_*` / `database_name`) still resolves source and target distinctly.

The synonym sets are collision-free within a single source row (no connector
emits two names for the same concept in one row).

## Connector notes (verified against real connector data)

- **BigQuery** — the real extractor frames carry extra columns
  (`constraint_name`, `table_type`, `creation_time`, `ddl`); these are ignored.
  The graph node id is reproducible from a record's raw natural key via
  `generate_column_id(...)`, so the identity-agnostic contract loses nothing the
  downstream ID builder needs.
- **CSV / MusicBrainz** — the shipped datasets already carry the canonical
  vocabulary: `column_info.csv` has the full `database/schema/table/column` path
  and lowercase `"true"/"false"` flags, and `column_references_info.csv` uses
  `source_*` / `target_* ` / `criteria` verbatim (i.e. `ForeignKeyRecord`'s
  canonical names). The CSV *format* allows optional columns, so a CSV that omits
  the path columns cannot populate the required natural-key fields — that is a
  malformed input for this contract, not something it silently accepts.
- **Dataplex** — currently fabricates `is_primary_key=False` / `is_foreign_key=False`
  (it exposes no key metadata); under this contract those become `None` (honest
  "unknown"). That is a deliberate behavior change to reconcile at the S4 flip
  (with a captured golden first). Its source-specific `column_mode` values beyond
  `NULLABLE`/`REQUIRED` (e.g. `REPEATED`) must be pre-folded by the connector; the
  contract does not silently accept unknown nullability tokens.

## Not precluding a Graph Spec `sources` expression (D14)

Each entity table maps cleanly onto a Neo4j-native Graph Spec (import-spec)
`sources → targets → actions` lineage — the natural-key-addressed tabular shape
*is* a Graph Spec tabular `source`:

```jsonc
// sketch — neutral-but-compatible, not a committed format (Graph Spec is RC; see S1-SPIKE-1)
{
  "sources": [
    { "name": "columns", "type": "table",
      "columns": ["database_name","schema_name","table_name","column_name","data_type","nullable"] }
  ],
  "targets": {
    "nodes": [
      { "source": "columns", "labels": ["Column"],
        "key_properties": ["database_name","schema_name","table_name","column_name"],
        "properties": ["data_type","nullable"] }
    ]
    // ForeignKeyRecord → a relationship target keyed on source/target column columns
  }
}
```

We stay behind our own boundary and adapt (D14: "don't block on it"); the final
substrate is decided by the S1 spike, not here.
