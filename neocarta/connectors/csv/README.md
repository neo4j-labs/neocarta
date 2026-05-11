# CSV Connector

This document describes the required CSV file formats for ingesting metadata into the semantic graph using the CSV connector.

## Overview

The CSV connector accepts normalized CSV files representing database metadata entities and their relationships. Files can be provided for core database entities (databases, schemas, tables, columns), extended entities (values, glossaries, business terms, queries), and their relationships.

## ID Strategy

The connector automatically computes all entity IDs from the name columns. **Choose one strategy and apply it consistently across all files in the hierarchy.**

### Auto-generated (recommended)

Omit all `*_id` columns. The connector builds deterministic, dot-separated IDs from the name columns:

| Entity | Required name columns | Auto-generated ID |
|---|---|---|
| Database | `database_name` | `{database_name}` |
| Schema | `database_name`, `schema_name` | `{database_name}.{schema_name}` |
| Table | `database_name`, `schema_name`, `table_name` | `{database_name}.{schema_name}.{table_name}` |
| Column | `database_name`, `schema_name`, `table_name`, `column_name` | `{database_name}.{schema_name}.{table_name}.{column_name}` |
| Glossary | `glossary_name` | `{glossary_name}` |
| Category | `glossary_name`, `category_name` | `{glossary_name}.{category_name}` |
| BusinessTerm | `glossary_name`, `category_name`, `term_name` | `{glossary_name}.{category_name}.{term_name}` |

### Explicit IDs

Supply the corresponding `*_id` column (`database_id`, `schema_id`, `table_id`, `column_id`, `value_id`, `glossary_id`, `category_id`, `business_term_id`) in **every** CSV file in the hierarchy. Explicit IDs are used as-is and must be consistent across files — for example, the `glossary_id` value in `category_info.csv` must match the `glossary_id` in `glossary_info.csv`.

> **Warning:** Mixing explicit and auto-generated IDs across files in the same hierarchy is not supported and will produce inconsistent node references.

> **Dataplex compatibility:** If you load glossary data from both the CSV connector and the Dataplex connector into the same graph, you must supply explicit `glossary_id`, `category_id`, and `business_term_id` values in the CSV files that match the Dataplex resource paths (e.g. `projects/.../glossaries/.../terms/...`). Auto-generated IDs use a different format and will not align with Dataplex IDs.

## CSV File Formats

### Core Entity Files

#### 1. `database_info.csv` (Database nodes)

Creates `:Database` nodes in the graph.

**Required columns:**
- `database_name` (string): Database name — used as the node's `name` property and to auto-generate `database_id`

**Optional columns:**
- `database_id` (string): Explicit ID override (see [ID Strategy](#id-strategy))
- `service` (string): Database service (e.g., `"BIGQUERY"`, `"POSTGRES"`)
- `platform` (string): Cloud platform (e.g., `"GCP"`, `"AWS"`, `"AZURE"`)
- `description` (string): Database description

**Example:**
```csv
database_name,platform,service,description
my-project,GCP,BIGQUERY,Production data warehouse
```

---

#### 2. `schema_info.csv` (Schema nodes)

Creates `:Schema` nodes and `(:Database)-[:HAS_SCHEMA]->(:Schema)` relationships.

**Required columns:**
- `database_name` (string): Parent database name
- `schema_name` (string): Schema name — used as the node's `name` property and to auto-generate `schema_id`

**Optional columns:**
- `database_id` (string): Explicit parent database ID override
- `schema_id` (string): Explicit schema ID override
- `description` (string): Schema description

**Example:**
```csv
database_name,schema_name,description
my-project,analytics,Analytics dataset for reporting
my-project,sales,Sales transaction data
```

---

#### 3. `table_info.csv` (Table nodes)

Creates `:Table` nodes and `(:Schema)-[:HAS_TABLE]->(:Table)` relationships.

**Required columns:**
- `database_name` (string): Database name
- `schema_name` (string): Schema name
- `table_name` (string): Table name — used as the node's `name` property and to auto-generate `table_id`

**Optional columns:**
- `database_id` (string): Explicit database ID override
- `schema_id` (string): Explicit schema ID override
- `table_id` (string): Explicit table ID override
- `description` (string): Table description

**Example:**
```csv
database_name,schema_name,table_name,description
my-project,analytics,customer_summary,Aggregated customer metrics
my-project,sales,orders,Order transactions
```

---

#### 4. `column_info.csv` (Column nodes)

Creates `:Column` nodes and `(:Table)-[:HAS_COLUMN]->(:Column)` relationships.

**Required columns:**
- `database_name` (string): Database name
- `schema_name` (string): Schema name
- `table_name` (string): Table name
- `column_name` (string): Column name — used as the node's `name` property and to auto-generate `column_id`

**Optional columns:**
- `database_id` (string): Explicit database ID override
- `schema_id` (string): Explicit schema ID override
- `table_id` (string): Explicit table ID override
- `column_id` (string): Explicit column ID override
- `description` (string): Column description
- `data_type` (string): Data type (e.g., `"STRING"`, `"INTEGER"`, `"TIMESTAMP"`)
- `is_nullable` (boolean): Whether column accepts NULL values (default: `true`)
- `is_primary_key` (boolean): Whether column is a primary key (default: `false`)
- `is_foreign_key` (boolean): Whether column is a foreign key (default: `false`)

**Example:**
```csv
database_name,schema_name,table_name,column_name,data_type,is_nullable,is_primary_key,is_foreign_key,description
my-project,sales,orders,order_id,STRING,false,true,false,Unique order identifier
my-project,sales,orders,customer_id,STRING,false,false,true,Customer reference
my-project,sales,orders,order_date,TIMESTAMP,false,false,false,Order creation timestamp
my-project,sales,orders,total_amount,FLOAT64,true,false,false,Total order amount
```

---

### Relationship Files

#### 5. `column_references_info.csv` (References relationships)

Creates `(:Column)-[:REFERENCES]->(:Column)` relationships representing foreign key constraints and join conditions.

**Required columns:**
- `source_database_name` (string): Source database name
- `source_schema_name` (string): Source schema name
- `source_table_name` (string): Source table name
- `source_column_name` (string): Source column name (foreign key column)
- `target_database_name` (string): Target database name
- `target_schema_name` (string): Target schema name
- `target_table_name` (string): Target table name
- `target_column_name` (string): Target column name (referenced primary key column)

**Optional columns:**
- `source_column_id` (string): Explicit source column ID override
- `target_column_id` (string): Explicit target column ID override
- `criteria` (string): Join condition (e.g., `"orders.customer_id = customers.customer_id"`)

**Example:**
```csv
source_database_name,source_schema_name,source_table_name,source_column_name,target_database_name,target_schema_name,target_table_name,target_column_name,criteria
my-project,sales,orders,customer_id,my-project,sales,customers,customer_id,orders.customer_id = customers.customer_id
my-project,sales,order_items,order_id,my-project,sales,orders,order_id,order_items.order_id = orders.order_id
my-project,sales,order_items,product_id,my-project,sales,products,product_id,order_items.product_id = products.product_id
```

---

### Extended Entity Files

#### 6. `value_info.csv` (Value nodes)

Creates `:Value` nodes and `(:Column)-[:HAS_VALUE]->(:Value)` relationships representing unique or sample values in columns.

**Required columns:**
- `database_name` (string): Database name
- `schema_name` (string): Schema name
- `table_name` (string): Table name
- `column_name` (string): Column name
- `value` (string): The actual value

**Optional columns:**
- `database_id` (string): Explicit database ID override
- `schema_id` (string): Explicit schema ID override
- `column_id` (string): Explicit column ID override
- `value_id` (string): Explicit value ID override (auto-generated IDs include a hash of the value)

**Example:**
```csv
database_name,schema_name,table_name,column_name,value
my-project,sales,orders,status,pending
my-project,sales,orders,status,completed
my-project,sales,orders,status,cancelled
my-project,sales,products,category,Electronics
my-project,sales,products,category,Clothing
```

---

#### 7. `query_info.csv` (Query nodes)

Creates `:Query` nodes representing SQL queries from query logs.

**Required columns:**
- `query_id` (string): Unique identifier for the query
- `content` (string): SQL query content

**Optional columns:**
- `description` (string): Query description

**Example:**
```csv
query_id,content,description
q001,"SELECT * FROM sales.orders WHERE status = 'completed'",Get completed orders
q002,"SELECT customer_id, SUM(total_amount) FROM sales.orders GROUP BY customer_id",Customer revenue summary
```

---

#### 8. `query_table_info.csv` (UsesTable relationships)

Creates `(:Query)-[:USES_TABLE]->(:Table)` relationships.

**Required columns:**
- `query_id` (string): Query identifier
- `table_id` (string): Full table ID — must match the ID computed from `table_info.csv`

**Example:**
```csv
query_id,table_id
q001,my-project.sales.orders
q002,my-project.sales.orders
```

---

#### 9. `query_column_info.csv` (UsesColumn relationships)

Creates `(:Query)-[:USES_COLUMN]->(:Column)` relationships.

**Required columns:**
- `query_id` (string): Query identifier
- `column_id` (string): Full column ID — must match the ID computed from `column_info.csv`

**Example:**
```csv
query_id,column_id
q001,my-project.sales.orders.status
q002,my-project.sales.orders.customer_id
q002,my-project.sales.orders.total_amount
```

---

### Glossary Entity Files

#### 10. `glossary_info.csv` (Glossary nodes)

Creates `:Glossary` nodes representing business glossaries.

**Required columns:**
- `glossary_name` (string): Glossary identifier — used as the node's `name` property and to auto-generate `glossary_id`

**Optional columns:**
- `glossary_id` (string): Explicit ID override (see [ID Strategy](#id-strategy))
- `name` (string): Display name override (defaults to `glossary_name`)
- `description` (string): Glossary description

**Example:**
```csv
glossary_name,name,description
ecommerce_glossary,E-commerce Business Glossary,Standard business terms for e-commerce
```

---

#### 11. `category_info.csv` (Category nodes)

Creates `:Category` nodes and `(:Glossary)-[:HAS_CATEGORY]->(:Category)` relationships.

**Required columns:**
- `glossary_name` (string): Parent glossary identifier
- `category_name` (string): Category identifier — used as the node's `name` property and to auto-generate `category_id`

**Optional columns:**
- `glossary_id` (string): Explicit parent glossary ID override
- `category_id` (string): Explicit category ID override
- `name` (string): Display name override (defaults to `category_name`)
- `description` (string): Category description

**Example:**
```csv
glossary_name,category_name,name,description
ecommerce_glossary,revenue_metrics,Revenue Metrics,Key revenue and financial metrics
ecommerce_glossary,customer_metrics,Customer Metrics,Customer behavior metrics
```

---

#### 12. `business_term_info.csv` (BusinessTerm nodes)

Creates `:BusinessTerm` nodes and `(:Category)-[:HAS_BUSINESS_TERM]->(:BusinessTerm)` relationships.

**Required columns:**
- `glossary_name` (string): Parent glossary identifier
- `category_name` (string): Parent category identifier
- `term_name` (string): Term identifier — used as the node's `name` property and to auto-generate `business_term_id`

**Optional columns:**
- `category_id` (string): Explicit parent category ID override
- `business_term_id` (string): Explicit business term ID override
- `name` (string): Display name override (defaults to `term_name`)
- `description` (string): Business term description

**Example:**
```csv
glossary_name,category_name,term_name,name,description
ecommerce_glossary,revenue_metrics,gmv,Gross Merchandise Value,Total sales value of merchandise sold
ecommerce_glossary,customer_metrics,ltv,Customer Lifetime Value,Total revenue expected from a customer
ecommerce_glossary,customer_metrics,cac,Customer Acquisition Cost,Average cost to acquire a new customer
```

---

## Minimal CSV Set

To get started, you need at minimum:
1. `database_info.csv`
2. `schema_info.csv`
3. `table_info.csv`
4. `column_info.csv`

All other files are optional and can be added to enrich the graph with additional metadata.

## Data Quality Notes

1. **NULL Handling**: Empty cells or cells containing `"NaN"`, `"NULL"`, or `"null"` are treated as `None`
2. **Boolean Values**: Accepted formats: `true/false`, `True/False`, `1/0`
3. **String Normalization**: `service` and `platform` fields are automatically converted to uppercase
4. **ID Uniqueness**: All IDs must be unique within their entity type
5. **Referential Integrity**: Parent name columns (e.g., `database_name` in `schema_info.csv`) must use values consistent with those in the parent CSV file so that auto-generated IDs match across files
6. **Query/Glossary ID references**: `query_table_info.csv` and `query_column_info.csv` reference IDs by their fully-qualified dot-separated form (e.g., `my-project.sales.orders`)

## Connector Configuration

### Custom File Mapping

You can customize CSV file names by providing a `csv_file_map` parameter:

```python
from neocarta import NodeLabel

# Enum members are recommended, but exact string values (e.g. "Database", "Schema") also work.
custom_file_map = {
    NodeLabel.DATABASE: "my_database.csv",
    NodeLabel.SCHEMA: "my_schemas.csv",
    NodeLabel.TABLE: "my_tables.csv",
    # ... other custom filenames
}

connector = CSVConnector(
    csv_directory="datasets/csv",
    neo4j_driver=neo4j_driver,
    database_name=neo4j_database,
    csv_file_map=custom_file_map
)
```

Default file names (if not overridden):
- `database_info.csv`
- `schema_info.csv`
- `table_info.csv`
- `column_info.csv`
- `column_references_info.csv`
- `value_info.csv`
- `query_info.csv`
- `query_table_info.csv`
- `query_column_info.csv`
- `glossary_info.csv`
- `category_info.csv`
- `business_term_info.csv`

### Selective Loading

You can choose which nodes and relationships to load:

```python
from neocarta import NodeLabel as nl, RelationshipType as rt

# Enum members are recommended, but exact string values (e.g. "Database", "HAS_SCHEMA") also work.

# Load only core schema entities
connector.run(
    include_nodes=[nl.DATABASE, nl.SCHEMA, nl.TABLE, nl.COLUMN],
    include_relationships=[rt.HAS_SCHEMA, rt.HAS_TABLE, rt.HAS_COLUMN]
)

# Load schema + column values
connector.run(
    include_nodes=[nl.DATABASE, nl.SCHEMA, nl.TABLE, nl.COLUMN, nl.VALUE],
    include_relationships=[rt.HAS_SCHEMA, rt.HAS_TABLE, rt.HAS_COLUMN, rt.HAS_VALUE, rt.REFERENCES]
)

# Load everything including queries and glossary
connector.run()  # No filters = load all available CSV files
```

## Usage Examples

### Basic Usage

```python
import os
from neo4j import GraphDatabase
from neocarta.connectors.csv import CSVConnector

# Initialize Neo4j driver
neo4j_driver = GraphDatabase.driver(
    uri=os.getenv("NEO4J_URI"),
    auth=(os.getenv("NEO4J_USERNAME"), os.getenv("NEO4J_PASSWORD")),
)
neo4j_database = os.getenv("NEO4J_DATABASE", "neo4j")

# Create connector instance
connector = CSVConnector(
    csv_directory="datasets/csv",
    neo4j_driver=neo4j_driver,
    database_name=neo4j_database
)

# Run the complete connector (loads all available CSV files)
connector.run()

# Cleanup
neo4j_driver.close()
```

### Advanced Usage with Custom Configuration

```python
from neocarta import NodeLabel as nl, RelationshipType as rt

# Custom file mapping and selective loading
# Enum members are recommended, but exact string values (e.g. "Table", "HAS_TABLE") also work.
custom_file_map = {
    nl.TABLE: "custom_tables.csv",
    nl.COLUMN: "custom_columns.csv",
}

connector = CSVConnector(
    csv_directory="path/to/csv/files",
    neo4j_driver=neo4j_driver,
    database_name="neo4j",
    csv_file_map=custom_file_map
)

# Load only specific entities
connector.run(
    include_nodes=[nl.DATABASE, nl.SCHEMA, nl.TABLE, nl.COLUMN, nl.VALUE],
    include_relationships=[rt.HAS_SCHEMA, rt.HAS_TABLE, rt.HAS_COLUMN, rt.HAS_VALUE, rt.REFERENCES]
)
```

### Runtime File Override

File mapping is configured at construction time. To use a different mapping for a specific run, create a new connector instance:

```python
# Use an alternative file mapping for a specific run
connector = CSVConnector(
    csv_directory="path/to/csv/files",
    neo4j_driver=neo4j_driver,
    database_name="neo4j",
    csv_file_map={NodeLabel.TABLE: "alternative_tables.csv"},
)
connector.run(
    include_nodes=[nl.TABLE],
    include_relationships=[rt.HAS_TABLE]
)
```
