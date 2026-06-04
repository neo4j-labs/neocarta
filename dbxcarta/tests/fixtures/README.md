# DBxCarta Test Fixtures

This directory contains the canonical test and demo schema for dbxcarta.

## Files

| File | Purpose |
|---|---|
| `setup_test_catalog.sql` | SQL DDL — creates all schemas, tables, PKs, FKs |
| `insert_test_data.sql` | DML — inserts 15–25 FK-respecting rows per table |
| `demo_questions.json` | Six sample questions for the graph_rag demo |

---

## Schema Map

Five schemas, 20 tables, 16 declared FKs (17 column-pair edges):

```
dbxcarta_test_sales          Orders domain
  customers                  PK: id
  orders                     PK: id  FK -> customers, hr.employees
  order_items                PK: id  FK -> orders, inventory.products
  payments                   PK: id  FK -> orders
  promotions                 PK: id

dbxcarta_test_inventory      Product catalog
  categories                 PK: id
  products                   PK: id  FK -> categories  (STRUCT, ARRAY, MAP columns)
  warehouses                 PK: id
  suppliers                  PK: id
  inventory_levels           PK: id  FK -> products, warehouses
  product_suppliers          PK: (product_id, supplier_id)  FK -> products, suppliers

dbxcarta_test_hr             Employee records
  departments                PK: id
  job_titles                 PK: id
  employees                  PK: id  FK -> departments, employees (self-ref manager)
  leave_requests             PK: id  FK -> employees

dbxcarta_test_events         Clickstream / analytics
  user_profiles              PK: id  (MAP, BINARY columns)
  user_sessions              PK: id  FK -> user_profiles  (ARRAY column)
  page_views                 PK: id  FK -> user_sessions  (STRUCT, VARIANT columns)
  ab_experiments             PK: id  FK -> user_profiles

dbxcarta_test_external       External Delta tables (requires UC Volume)
  raw_orders                 LOCATION-based, no FKs
  vendor_price_list          LOCATION-based, no FKs
  geo_reference              LOCATION-based, no FKs (all primitive type coverage)
```

Cross-schema FKs:
- `sales.orders.employee_id` → `hr.employees.id`
- `sales.order_items.product_id` → `inventory.products.id`

---

## Setup

### Option 1 — Demo setup script (recommended)

```bash
DATABRICKS_WAREHOUSE_ID=<id> python scripts/run_demo.py \
  --catalog my_catalog \
  --volume-path /Volumes/my_catalog/default/dbxcarta
```

The `--volume-path` argument (or `DATABRICKS_VOLUME_PATH` env var) is only required for `dbxcarta_test_external`.
Omit it to skip external tables (the script will fail only on those three
`CREATE TABLE ... LOCATION` statements).

To load test data after setup, execute `insert_test_data.sql` using the same
pattern (substituting `${catalog}` with your catalog name).  The three external
table INSERT statements at the bottom of that file require the Volume path to be
writable; skip them if no Volume is available.

### Option 2 — Databricks SDK (Python)

```python
from pathlib import Path
from databricks.sdk import WorkspaceClient

catalog = "my_catalog"
volume_path = "/Volumes/my_catalog/default/dbxcarta"

sql = Path("tests/fixtures/setup_test_catalog.sql").read_text()
sql = sql.replace("${catalog}", catalog).replace("${volume_path}", volume_path)

ws = WorkspaceClient()
for stmt in sql.split(";"):
    lines = [l for l in stmt.splitlines() if not l.strip().startswith("--")]
    body = "\n".join(lines).strip()
    if body:
        ws.statement_execution.execute_statement(
            warehouse_id=warehouse_id, statement=stmt, wait_timeout="60s"
        )
```

### Option 3 — Databricks CLI

```bash
sed -e 's/${catalog}/my_catalog/g' \
    -e 's|${volume_path}|/Volumes/my_catalog/default/dbxcarta|g' \
    tests/fixtures/setup_test_catalog.sql \
  | databricks sql execute --stdin --warehouse-id <id>
```

---

## Teardown

```bash
DATABRICKS_WAREHOUSE_ID=<id> DBXCARTA_CATALOG=my_catalog \
  python scripts/run_demo.py --teardown
```

Or uncomment and run the `TEARDOWN` block at the bottom of `setup_test_catalog.sql`.
The teardown block also includes DROP statements for the legacy `dbxcarta_fk_test`
and `dbxcarta_fk_test_b` schemas, so stale fixtures from older runs are cleaned up.

**The setup script is not idempotent for constraints.** `CREATE TABLE IF NOT EXISTS`
handles re-runs on tables, but `ALTER TABLE ADD CONSTRAINT` will fail if constraints
already exist. Run teardown first before re-running setup.

---

## Running the Demo

After setup, run the dbxcarta pipeline job against the fixture schemas:

```
DBXCARTA_CATALOG=my_catalog
DBXCARTA_SCHEMAS=dbxcarta_test_sales,dbxcarta_test_inventory,dbxcarta_test_hr,dbxcarta_test_events
```

Leave `DBXCARTA_SCHEMAS` blank to include all schemas in the catalog (including
`dbxcarta_test_external`). Cross-schema FK edges (sales→hr, sales→inventory)
only appear in Neo4j when **both** the source and target schemas are in scope.

Upload the demo questions file and build the semantic layer:

```bash
uv run dbxcarta-submit publish-wheels
uv run dbxcarta-submit upload --data tests/fixtures
uv run dbxcarta-submit submit-entrypoint ingest
```

Then run the graph_rag demo client:

```bash
uv run dbxcarta-submit submit-entrypoint client
```

### Demo questions

| ID | Question | Traversal path |
|---|---|---|
| demo_q1 | Most active customers by order count and spend | sales self-join |
| demo_q2 | Revenue by product category (last 30 days) | sales → inventory cross-schema |
| demo_q3 | Account managers for highest-value orders | sales → hr cross-schema |
| demo_q4 | Products below reorder point and their suppliers | inventory multi-hop |
| demo_q5 | A/B experiment conversion rates by variant | events intra-schema |
| demo_q6 | Suppliers by product count and average lead time | composite FK path |

---

## Verifying a Run

Pipeline self-verification lives in `dbxcarta.spark.verify` and is exposed
through the `dbxcarta` CLI from `dbxcarta-spark`.
After a successful run, point at the run summary in your UC Volume to
re-run every structural invariant (node counts, FK accounting, HAS_VALUE
shape, value-id format, run-summary parity):

```bash
uv run dbxcarta verify                    # most recent status='success' summary
uv run dbxcarta verify --run-id <run_id>  # a specific run
```

Expected counts on the four-schema fixture (`dbxcarta_test_sales`,
`dbxcarta_test_inventory`, `dbxcarta_test_hr`, `dbxcarta_test_events`):

- 16 declared FKs / 16 resolved / 17 column-pair REFERENCES edges
  (1 composite contributes 2 column-pair rows)

The `scripts/run_autotest.py` harness runs this end-to-end (DDL + INSERT +
ingest + verify diff) against a live workspace.

---

## Notes

**VARIANT column** — `page_views.raw_payload` requires DBR 15.3+. On older
runtimes, remove that column from the CREATE TABLE before running setup.
`test_complex_types.py` skips the VARIANT family gracefully when no VARIANT
columns are found.

**External tables** — `CREATE TABLE ... LOCATION` requires the Volume path to
be writable by the executing principal. If the path does not exist, Databricks
creates it on first write. If the principal lacks write permission, those three
CREATE statements will fail; the remaining 17 tables are unaffected.
