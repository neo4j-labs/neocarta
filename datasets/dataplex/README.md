# Dataplex glossary datasets

Scripts that build a **business glossary in [Dataplex Universal Catalog](https://cloud.google.com/dataplex)**
and link its terms to the columns of a BigQuery dataset. The result is the
catalog-side input that the neocarta **Dataplex connector** ingests into Neo4j:
`Glossary` → `Category` → `BusinessTerm` nodes, plus `TAGGED_WITH` edges from
columns to the terms that define them.

Two glossaries are provided, one per sample dataset:

| Dataset | BigQuery dataset | Glossary id | Create script | Link script |
|---|---|---|---|---|
| Retail / ecommerce | `demo_ecommerce` (default) | `retail-business-glossary` | [`create_glossary.sh`](create_glossary.sh) | [`connect_terms.py`](connect_terms.py) |
| Acme Corp | `acme_corp` | `acme-corp-glossary` | [`create_acme_glossary.sh`](create_acme_glossary.sh) | [`connect_acme_terms.py`](connect_acme_terms.py) |

> **Why two steps (create, then connect)?** Dataplex models a glossary and the
> column→term tags as separate resources. The `create_*` script defines the
> glossary, categories, and terms; the `connect_*` script creates the
> `definition` **entry links** that attach each term to a specific BigQuery
> column. The links can only be created once *both* the terms and the BigQuery
> table entries exist.

---

## Prerequisites

1. **The BigQuery dataset must already be loaded.** Entry links target BigQuery
   *column* entries, which Dataplex only catalogs after the tables exist. Load
   the matching dataset first, from the repo root:

   ```bash
   uv run datasets/load_bigquery.py --dataset ecommerce   # or: --dataset acme
   ```

2. **`gcloud` CLI**, authenticated and pointed at your project (the `create_*`
   scripts call `gcloud dataplex glossaries ...`):

   ```bash
   gcloud auth login
   gcloud config set project "$GCP_PROJECT_ID"
   ```

3. **Application Default Credentials** for the Python link/lookup scripts
   (they use the `google-cloud-dataplex` client and ADC):

   ```bash
   gcloud auth application-default login
   ```

4. **IAM**: your principal needs permission to manage Dataplex glossaries,
   terms, and entry links (e.g. a Dataplex Catalog editor/admin role), plus read
   access to the BigQuery dataset.

5. **Environment variables** (read from a repo-root `.env`; see
   [`.env.example`](../../.env.example)). The `.sh` scripts `source .env`, and
   the Python scripts load it via `python-dotenv`, so run everything **from the
   repo root**:

   | Variable | Meaning | Example |
   |---|---|---|
   | `GCP_PROJECT_ID` | Project id (string) | `my-project` |
   | `GCP_PROJECT_NUMBER` | Project **number** (numeric) | `123456789012` |
   | `BIGQUERY_DATASET_ID` | Dataset whose columns are tagged | `demo_ecommerce` / `acme_corp` |
   | `BIGQUERY_LOCATION` | Location of the `@bigquery` entry group | `us` |
   | `DATAPLEX_LOCATION` | Glossary location (the scripts create glossaries in `us`) | `us` |
   | `DATAPLEX_GLOSSARY_ID` | Glossary to link against | `retail-business-glossary` / `acme-corp-glossary` |

   Get the project number with:

   ```bash
   gcloud projects describe "$GCP_PROJECT_ID" --format='value(projectNumber)'
   ```

> ⚠️ **`BIGQUERY_DATASET_ID` and `DATAPLEX_GLOSSARY_ID` are shared variables.**
> Point them at the dataset/glossary you are loading **before** running a link
> script, or the links will be created against whichever dataset/glossary is
> currently set in `.env`.

---

## Loading a dataset

Run the steps in order. Examples below use the **retail** dataset; substitute
the Acme scripts and values for the Acme glossary.

### 1. Load the BigQuery dataset

```bash
uv run datasets/load_bigquery.py --dataset ecommerce
```

### 2. Create the glossary (categories + terms)

```bash
bash datasets/dataplex/create_glossary.sh
```

This creates the glossary, its categories, and one term per concept via
`gcloud dataplex glossaries`. Dataplex resource ids must be **kebab-case**
(`[a-z0-9-]`), so term ids are hyphenated (e.g. `gross-merchandise-value`);
display names keep their human-readable form. The Acme script
(`create_acme_glossary.sh`) is data-driven — its categories and terms are
declared in `CATEGORIES` / `TERMS` arrays at the top of the file, so edit those
arrays to change the glossary.

### 3. Link columns to terms (create entry links)

Make sure `.env` points at this dataset/glossary, then:

```bash
uv run datasets/dataplex/connect_terms.py          # retail
# uv run datasets/dataplex/connect_acme_terms.py   # acme
```

Each script holds a `table → {column: term-id}` mapping and creates a
`definition` entry link per pair, in the `@bigquery` entry group, with the
glossary term as the link **TARGET** and the column (`Schema.<column>`) as the
**SOURCE**. The term ids in the mapping must match exactly those created in
step 2.

- `connect_terms.py` looks up each BigQuery table entry via `search_entries`
  and links a small set of retail columns.
- `connect_acme_terms.py` constructs entry names deterministically and creates
  the (many) links concurrently over a shared client. It is **idempotent** —
  links that already exist are skipped (`AlreadyExists`), so it is safe to
  re-run.

> A single column may define more than one term — e.g. Acme's
> `opportunities.stage` backs both `pipeline-stage` and `closed-won`. Purely
> derived concepts with no backing column (e.g. `tenure`, `bookings`) have no
> term mapping by design.

### 4. (Optional) Verify the links

```bash
uv run datasets/dataplex/lookup_entry_links.py
```

Lists the glossary's terms and calls the `lookupEntryLinks` REST endpoint (not
yet in the Python SDK) to show which columns each term is linked to. Use it to
confirm step 3 succeeded before ingesting into Neo4j.

---

## Next: ingest into Neo4j

Once the glossary and entry links exist, run the neocarta **Dataplex connector**
(see [`neocarta/connectors/dataplex/`](../../neocarta/connectors/dataplex/) and
the examples) to extract the glossary and column tags into the graph. Point the
connector at the same `DATAPLEX_GLOSSARY_ID` / `BIGQUERY_DATASET_ID` you loaded
here.

## Files

| File | Purpose |
|---|---|
| `create_glossary.sh` | Create the retail glossary, categories, and terms. |
| `create_acme_glossary.sh` | Create the Acme glossary (data-driven arrays). |
| `connect_terms.py` | Link retail BigQuery columns to glossary terms. |
| `connect_acme_terms.py` | Link Acme BigQuery columns to glossary terms (concurrent, idempotent). |
| `lookup_entry_links.py` | Read-only: verify column↔term links via the REST API. |
</content>
