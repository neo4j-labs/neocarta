# Neocarta

An end-to-end library for generating metadata knowledge graphs in Neo4j for query generation and routing workflows.

*Note: This library is not a Neo4j product. It is a Neo4j Labs project supported by the Neo4j field team.*

[![Neo4j Labs](https://img.shields.io/badge/Neo4j-Labs-6366F1?logo=neo4j)](https://neo4j.com/labs/)
[![Status: Experimental](https://img.shields.io/badge/Status-Experimental-F59E0B)](https://neo4j.com/labs/)
[![CI](https://github.com/neo4j-field/neocarta/actions/workflows/pr-main-tests.yml/badge.svg)](https://github.com/neo4j-field/neocarta/actions/workflows/pr-main-tests.yml)
[![PyPI version](https://badge.fury.io/py/neocarta.svg)](https://badge.fury.io/py/neocarta)
[![Python versions](https://img.shields.io/pypi/pyversions/neocarta.svg)](https://pypi.org/project/neocarta/)
[![License](https://img.shields.io/badge/License-Apache%202.0-blue.svg)](https://opensource.org/licenses/Apache-2.0)

## Installation

```bash
pip install neocarta
```

Requires Python 3.10 or higher and a running Neo4j instance. Options:
- [Neo4j AuraDB](https://neo4j.com/product/auradb/) — managed cloud (free tier available)
- [Neo4j Desktop](https://neo4j.com/download/) — local GUI-based instance
- [Docker image](https://hub.docker.com/_/neo4j) — lightweight local instance

## Metadata Graph

The metadata graph has the following schema. All connectors must convert their schema information to this graph schema to be compatible with the provided MCP server and ingestion tooling.

```mermaid
---
config:
    layout: elk
---
graph LR
%% Nodes
Database("Database<br/>id: STRING | KEY<br/>name: STRING<br/>description: STRING<br/>embedding: VECTOR")
Schema("Schema<br/>id: STRING | KEY<br/>name: STRING<br/>description: STRING<br/>embedding: VECTOR")
Table("Table<br/>id: STRING | KEY<br/>name: STRING<br/>description: STRING<br/>embedding: VECTOR")
Column("Column<br/>id: STRING | KEY<br/>name: STRING<br/>description: STRING<br/>embedding: VECTOR<br/>type: STRING<br/>nullable: BOOLEAN<br/>isPrimaryKey: BOOLEAN<br/>isForeignKey: BOOLEAN")
Value("Value<br/>id: STRING | KEY<br/>value: STRING")

%% Relationships
Database -->|HAS_SCHEMA| Schema
Schema -->|HAS_TABLE| Table
Table -->|HAS_COLUMN| Column
Column -->|REFERENCES| Column
Column -->|HAS_VALUE| Value


%% Styling
classDef node_0_color fill:#e3f2fd,stroke:#1976d2,stroke-width:3px,color:#000,font-size:12px
class Database node_0_color

classDef node_1_color fill:#fff9c4,stroke:#f57f17,stroke-width:3px,color:#000,font-size:12px
class Schema node_1_color

classDef node_2_color fill:#f3e5f5,stroke:#7b1fa2,stroke-width:3px,color:#000,font-size:12px
class Table node_2_color

classDef node_3_color fill:#e8f5e8,stroke:#388e3c,stroke-width:3px,color:#000,font-size:12px
class Column node_3_color

classDef node_4_color fill:#fff3e0,stroke:#f57c00,stroke-width:3px,color:#000,font-size:12px
class Value node_4_color
```

Nodes
* `Database`
* `Schema`
* `Table`
* `Column`
* `Value`

Relationships
* `(:Database)-[:HAS_SCHEMA]->(:Schema)`
* `(:Schema)-[:HAS_TABLE]->(:Table)`
* `(:Table)-[:HAS_COLUMN]->(:Column)`
* `(:Column)-[:HAS_VALUE]->(:Value)`
* `(:Column)-[:REFERENCES]->(:Column)`


## Graph Generation

This project provides connector classes that organize the ETL process into reusable components:
* **Extractors** - Connect to source data and read metadata tables
* **Transformers** - Transform metadata into defined Neo4j schema
* **Loaders** - Ingest transformed data into Neo4j
* **Connectors** - Orchestrate the extract, transform, and load process

Each connector is implemented as a class that encapsulates its extractor, transformer, and loader components, providing a clean interface for metadata ingestion.

### Connector Class Architecture

All connectors follow a consistent class-based architecture:

```python
class Connector:
    def __init__(self, clients, config):
        # Initialize with required clients and configuration
        self.extractor = Extractor(...)
        self.transformer = Transformer(...)
        self.loader = Loader(...)

    def extract_metadata(self):
        # Extract data from source and cache
        pass

    def transform_metadata(self):
        # Transform extracted data to graph schema and cache
        pass

    def load_metadata(self):
        # Load transformed data into Neo4j
        pass

    def run(self):
        # Orchestrate the full ETL pipeline
        self.extract_metadata()
        self.transform_metadata()
        self.load_metadata()
```

### Connectors

#### **BigQuery Schema Connector**

Connector for reading BigQuery Information Schema tables and ingesting **schema metadata** into Neo4j. Primary and foreign keys must be defined in the Information Schema tables in order for column level relationships to be created in the Neo4j graph.

**What it extracts:**
* Database (GCP project)
* Schemas (datasets)
* Tables with descriptions
* Columns with types, constraints, descriptions
* Column references (foreign keys)
* Column unique values (sample data)

This connector requires the following variables to be set in the `.env` file:
* NEO4J_USERNAME=neo4j-username
* NEO4J_PASSWORD=neo4j-password
* NEO4J_URI=neo4j-uri
* NEO4J_DATABASE=neo4j-database
* GCP_PROJECT_ID=project-id
* BIGQUERY_DATASET_ID=dataset-id

#### **BigQuery Logs Connector**

Connector for extracting **query logs** from BigQuery `INFORMATION_SCHEMA.JOBS_BY_PROJECT`, parsing SQL queries to understand table and column usage, and loading query patterns into Neo4j.

**What it extracts:**
* SQL Queries
* Tables and columns referenced in queries (discovered via SQL parsing)
* Join relationships between tables (from SQL JOINs)
* Query-to-table and query-to-column usage relationships

**Graph schema additions:**
* `Query` nodes with properties:
  - `content` - The query text
  - `query_id` - Hash of query text
* `(:Query)-[:USES_TABLE]->(:Table)` relationships
* `(:Query)-[:USES_COLUMN]->(:Column)` relationships

This connector requires the following variables to be set in the `.env` file:
* NEO4J_USERNAME=neo4j-username
* NEO4J_PASSWORD=neo4j-password
* NEO4J_URI=neo4j-uri
* NEO4J_DATABASE=neo4j-database
* GCP_PROJECT_ID=project-id
* BIGQUERY_DATASET_ID=dataset-id
* BIGQUERY_REGION=region-us (optional, defaults to region-us)


##### Connector Architecture
```mermaid
---
config:
    layout: elk
---
graph LR
    subgraph Schema["Graph Schema"]
        GS(Data Model Definition)
    end

    subgraph Source["Source Repository"]
        BQ(BigQuery Database)        
    end

    subgraph ETL["ETL Processes"]
        QE(Read RDBMS Schema)   
        PM(Validate + Transform<br>with Pydantic) 
    
        QE -->|Raw Data<br/>JSON| PM
    end
    
    subgraph Graph["Database"]
        NEO[(Neo4j Graph)]
    end

    BQ -->|Information Schema| QE
    GS -->|Schema Definition| PM
    PM -->|Ingest Data| NEO
```

##### Code Example - Schema Connector

```python
import os
from neo4j import GraphDatabase
from google.cloud import bigquery
from neocarta.connectors.bigquery import BigQuerySchemaConnector

# Initialize clients
neo4j_driver = GraphDatabase.driver(
    uri=os.getenv("NEO4J_URI"),
    auth=(os.getenv("NEO4J_USERNAME"), os.getenv("NEO4J_PASSWORD")),
)
neo4j_database = os.getenv("NEO4J_DATABASE", "neo4j")
bigquery_client = bigquery.Client(project=os.getenv("GCP_PROJECT_ID"))

# Create connector instance
connector = BigQuerySchemaConnector(
    client=bigquery_client,
    project_id=os.getenv("GCP_PROJECT_ID"),
    dataset_id=os.getenv("BIGQUERY_DATASET_ID"),
    neo4j_driver=neo4j_driver,
    database_name=neo4j_database,
)

# Run the connector to extract, transform, and load BigQuery schema metadata into Neo4j
connector.run()
```

##### Code Example - Logs Connector

```python
import os
from neo4j import GraphDatabase
from google.cloud import bigquery
from neocarta.connectors.bigquery import BigQueryLogsConnector

# Initialize clients
neo4j_driver = GraphDatabase.driver(
    uri=os.getenv("NEO4J_URI"),
    auth=(os.getenv("NEO4J_USERNAME"), os.getenv("NEO4J_PASSWORD")),
)
neo4j_database = os.getenv("NEO4J_DATABASE", "neo4j")
bigquery_client = bigquery.Client(project=os.getenv("GCP_PROJECT_ID"))

# Create connector instance
connector = BigQueryLogsConnector(
    client=bigquery_client,
    project_id=os.getenv("GCP_PROJECT_ID"),
    neo4j_driver=neo4j_driver,
    database_name=neo4j_database,
)

# Run the connector to extract query logs, parse SQL, and load into Neo4j
connector.run(
    dataset_id=os.getenv("BIGQUERY_DATASET_ID"),
    region="region-us",
    start_timestamp="2024-01-01 00:00:00",  # Optional
    end_timestamp="2024-01-31 23:59:59",    # Optional
    limit=100,                               # Optional, default 100
    drop_failed_queries=True,                # Optional, default True
)
```

##### Combined Usage

For the most complete picture, run both connectors:

```python
# 1. Extract schema metadata
schema_connector = BigQuerySchemaConnector(...)
schema_connector.run()

# 2. Extract query logs
logs_connector = BigQueryLogsConnector(...)
logs_connector.run(dataset_id=os.getenv("BIGQUERY_DATASET_ID"))
```

This allows you to compare declared schema vs. actual usage patterns.

#### **GCP Dataplex Universal Catalog**

Connector for reading BigQuery metadata and Glossary information from Dataplex and ingesting into Neo4j. Please see the [Dataplex README](./neocarta/connectors/dataplex/README.md) for more information and caveats of using this connector.

##### Connector Architecture 

```mermaid
---
config:
    layout: elk
---
graph LR
    subgraph Schema["Graph Schema"]
        GS(Data Model Definition)
    end
    subgraph Big["Google Cloud Platform"]
        subgraph SR["Source Repository"]
            BQ(BigQuery Database)  
        end      
    

        subgraph Source["GCP Dataplex Universal Catalog"]
            G(Glossaries)
            MT(Metadata Types)        
        end
    end

    subgraph ETL["ETL Processes"]
        QE(Read Data Catalog)   
        PM(Validate + Transform<br>with Pydantic) 
    
        QE -->|Raw Data<br/>JSON| PM
    end
    
    subgraph Graph["Database"]
        NEO[(Neo4j Graph)]
    end

    BQ -->|BigQuery Metadata|MT
    G -->| Glossary Content| QE
    MT -->|BigQuery Metadata| QE
    GS -->|Schema Definition| PM
    PM -->|Ingest Data| NEO
```

##### Data Model

```mermaid
---
config:
    layout: elk
---
graph LR
%% Database Nodes
Database("Database<br/>id: STRING | KEY<br/>name: STRING<br/>platform: STRING<br/>service: STRING")
Schema("Schema<br/>id: STRING | KEY<br/>name: STRING")
Table("Table<br/>id: STRING | KEY<br/>name: STRING<br/>description: STRING<br/>embedding: VECTOR")
Column("Column<br/>id: STRING | KEY<br/>name: STRING<br/>description: STRING<br/>embedding: VECTOR<br/>type: STRING<br/>nullable: BOOLEAN")

%% Glossary Nodes
Glossary("Glossary<br/>id: STRING | KEY<br/>name: STRING<br/>description: STRING")
Category("Category<br/>id: STRING | KEY<br/>name: STRING<br/>description: STRING")
BusinessTerm("BusinessTerm<br/>id: STRING | KEY<br/>name: STRING<br/>description: STRING<br/>embedding: VECTOR")

%% Database Relationships
Database -->|HAS_SCHEMA| Schema
Schema -->|HAS_TABLE| Table
Table -->|HAS_COLUMN| Column
Column -->|REFERENCES| Column

%% Glossary Relationships
Glossary -->|HAS_CATEGORY| Category
Category -->|HAS_BUSINESS_TERM| BusinessTerm

%% Cross-domain Relationships
Column -->|TAGGED_WITH| BusinessTerm
Table -->|TAGGED_WITH| BusinessTerm
```

#### **Query Logs**

Connector for parsing query log JSON files into Neo4j. Please see the [Query Logs README](./neocarta/connectors/query_log/README.md) for more information and caveats of using this connector.

##### Connector Architecture

```mermaid
---
config:
    layout: elk
---
graph LR
    subgraph Schema["Graph Schema"]
        GS(Data Model Definition)
    end
    subgraph Big["Google Cloud Platform"]
        subgraph Source["Source Repository"]
            BQ(BigQuery Database)
        end

        subgraph Logging["GCP Logging"]
            GL(Logs)
        end
    end

    subgraph ETL["ETL Processes"]
        QL(Read Query Logs)
        PM(Validate + Transform<br>with Pydantic)

        QL -->|Raw Logs<br/>JSON| PM
    end

    subgraph Graph["Database"]
        NEO[(Neo4j Graph)]
    end

    BQ -->|Query Logs| GL
    GL -->|Query Logs| QL
    GS -->|Schema Definition| PM
    PM -->|Ingest Data| NEO
```

#### **CSV Files**

Connector for loading metadata from structured CSV files into Neo4j. This connector is useful for importing metadata from systems that don't have direct API access, or for loading curated metadata that has been manually created or exported from other tools.

The CSV connector supports selective loading - you can choose which node types and relationships to load based on what metadata is available in your CSV files.

**CSV File Structure:**

The connector expects CSV files in a specified directory with the following default naming convention:
* `database_info.csv` - Database nodes
* `schema_info.csv` - Schema nodes
* `table_info.csv` - Table nodes
* `column_info.csv` - Column nodes
* `column_references_info.csv` - Foreign key relationships
* `value_info.csv` - Sample column values
* `query_info.csv` - Query nodes
* `query_table_info.csv` - Query-to-table relationships
* `query_column_info.csv` - Query-to-column relationships
* `glossary_info.csv` - Glossary nodes
* `category_info.csv` - Category nodes
* `business_term_info.csv` - Business term nodes

Custom file names can be specified using the `csv_file_map` parameter.

**ID Strategy:**

Entity IDs are automatically generated from name columns using a dot-separated hierarchy (e.g., `database_name.schema_name.table_name` for tables, `glossary_name.category_name.term_name` for business terms). To use custom IDs instead, supply explicit `*_id` columns in every CSV file in the hierarchy. Do not mix strategies across files. If loading glossary data from both the CSV and Dataplex connectors into the same graph, you must supply explicit IDs in the CSV that match the Dataplex resource paths. See the [CSV Connector README](neocarta/connectors/csv/README.md) for full details.

This connector requires the following variables to be set in the `.env` file:
* NEO4J_USERNAME=neo4j-username
* NEO4J_PASSWORD=neo4j-password
* NEO4J_URI=neo4j-uri
* NEO4J_DATABASE=neo4j-database

##### Connector Architecture

```mermaid
---
config:
    layout: elk
---
graph LR
    subgraph Schema["Graph Schema"]
        GS(Data Model Definition)
    end

    subgraph Source["CSV Files"]
        CSV[(CSV Directory)]
    end

    subgraph ETL["ETL Processes"]
        QE(Read CSV Files)
        PM(Validate + Transform<br>with Pydantic)

        QE -->|Raw Data<br/>DataFrame| PM
    end

    subgraph Graph["Database"]
        NEO[(Neo4j Graph)]
    end

    CSV -->|CSV Files| QE
    GS -->|Schema Definition| PM
    PM -->|Ingest Data| NEO
```

##### Code Example

```python
import os
from neo4j import GraphDatabase
from neocarta import NodeLabel as nl, RelationshipType as rt
from neocarta.connectors.csv import CSVConnector

# Initialize clients
neo4j_driver = GraphDatabase.driver(
    uri=os.getenv("NEO4J_URI"),
    auth=(os.getenv("NEO4J_USERNAME"), os.getenv("NEO4J_PASSWORD")),
)
neo4j_database = os.getenv("NEO4J_DATABASE", "neo4j")

# Create connector instance
connector = CSVConnector(
    csv_directory="datasets/csv",
    neo4j_driver=neo4j_driver,
    database_name=neo4j_database,
)

# Run the connector to load all CSV files into Neo4j
connector.run()

# Alternatively, load specific nodes and relationships
# Enum members are recommended, but exact string values (e.g. "Database", "HAS_SCHEMA") also work.
connector.run(
    include_nodes=[nl.DATABASE, nl.SCHEMA, nl.TABLE, nl.COLUMN, nl.VALUE],
    include_relationships=[rt.HAS_SCHEMA, rt.HAS_TABLE, rt.HAS_COLUMN, rt.HAS_VALUE, rt.REFERENCES]
)

# Or use a custom file mapping (configured at construction time)
custom_file_map = {
    NodeLabel.DATABASE: "my_database.csv",
    NodeLabel.SCHEMA: "my_schema.csv",
    # ... other custom filenames
}
connector = CSVConnector(
    csv_directory="datasets/csv",
    neo4j_driver=neo4j_driver,
    database_name=neo4j_database,
    csv_file_map=custom_file_map,
)
connector.run()
```

##### Sample Dataset

A sample e-commerce dataset is provided in `datasets/csv/` that demonstrates the expected CSV file structure and can be used for testing the CSV connector.


### Embeddings 

Embeddings may be generated for the `description` fields of the following nodes:
* `Database`
* `Schema`
* `Table`
* `Column`
* `BusinessTerm`

This project currently supports the following embeddings Providers:
* OpenAI

This connector requires the following variables to be set in the `.env` file:
* OPENAI_API_KEY=sk-...

#### Connector Architecture

```mermaid
---
config:
    layout: elk
---
graph LR

    subgraph D["Database Preparation"]
        VI(Create Vector Index)
    end

    subgraph ES["Embedding Service"]
        E(OpenAI Embeddings)
    end

    subgraph Graph["Database"]
        NEO[(Neo4j Graph)]
    end

    subgraph EP["Embedding Process"]
        C(Create Embeddings) 
    end
    
    VI-->NEO

    C<-->E

    NEO-->|Unprocessed Node Descriptions|C
    C-->|Embeddings|NEO
```

#### Code Example

```python
import asyncio
import os
from neo4j import GraphDatabase
from openai import AsyncOpenAI
from neocarta import NodeLabel as nl
from neocarta.enrichment.embeddings import OpenAIEmbeddingsConnector

# Initialize clients
neo4j_driver = GraphDatabase.driver(
    uri=os.getenv("NEO4J_URI"),
    auth=(os.getenv("NEO4J_USERNAME"), os.getenv("NEO4J_PASSWORD")),
)
neo4j_database = os.getenv("NEO4J_DATABASE", "neo4j")
embedding_client = AsyncOpenAI(api_key=os.getenv("OPENAI_API_KEY"))

# Create connector instance
connector = OpenAIEmbeddingsConnector(
    async_embedding_client=embedding_client,
    embedding_model="text-embedding-3-small",
    dimensions=768,
    neo4j_driver=neo4j_driver,
    database_name=neo4j_database,
)

# The node labels to generate embeddings for
# Enum members are recommended, but exact string values (e.g. "Database", "Table") also work.
node_labels = [nl.DATABASE, nl.TABLE, nl.COLUMN]

# Run the connector to create embeddings for the nodes
await connector.arun(node_labels=node_labels)
```

### Full Pipeline

The full graph generation pipeline will run the BigQuery connector followed by the embedding generation connector. 

It requires the following variables to be set in the `.env` file:
* NEO4J_USERNAME=neo4j-username
* NEO4J_PASSWORD=neo4j-password
* NEO4J_URI=neo4j-uri
* NEO4J_DATABASE=neo4j-database
* GCP_PROJECT_ID=project-id
* BIGQUERY_DATASET_ID=dataset-id
* OPENAI_API_KEY=sk-...

#### Architecture

The combined BigQuery + Embeddings connector pipeline is seen below.

```mermaid
flowchart LR
    subgraph Schema["Graph Schema"]
        GS(Data Model Definition)
    end

    subgraph Source["Source Repository"]
        BQ(BigQuery Database)        
    end

    subgraph ETL["ETL Processes"]
        QE(Read RDBMS Schema)   
        PM(Validate + Transform<br>with Pydantic) 
    end
    
    subgraph Graph["Database"]
        NEO[(Neo4j Graph)]
    end

    subgraph D["Database Preparation"]
        VI(Create Vector Index)
    end

    subgraph ES["Embedding Service"]
        E(OpenAI Embeddings)
    end

    subgraph EP["Embedding Workflow"]
        C(Create Embeddings) 
    end

    %% BigQuery Flow
    BQ -->|Information Schema| QE
    QE -->|Raw Data JSON| PM
    GS -->|Schema Definition| PM
    PM -->|Ingest Data| NEO

    %% Embeddings Flow
    NEO -->|Database Ready| VI
    VI -->|Vector Index Created| NEO
    NEO -->|Unprocessed Node Descriptions| C
    C <--> E
    C -->|Embeddings| NEO
```

**Running The Full Connector Pipeline**

To run the full connector pipeline, use the following Make command:

```bash
make create-graph
```

---

## Neocarta MCP

The Neocarta MCP server is available via the optional `[mcp]` add-on.

### Overview

This is a metadata retrieval MCP server that provides tools to query the Neo4j semantic layer for relevant schema information using semantic similarity search and graph traversal. It is built for compatibility with the standard data model provided by the `neocarta` library.

**Tools**
* `list_schemas` - List all schemas and their associated databases.
* `list_tables_by_schema` - List all tables for a given schema name.
* `get_metadata_schema_by_column_semantic_similarity` - Find tables by semantic similarity on column embeddings.
* `get_metadata_schema_by_table_semantic_similarity` - Find tables by semantic similarity on table embeddings.
* `get_metadata_schema_by_schema_and_table_semantic_similarity` - Find tables by semantic similarity across both schema and table embeddings.
* `get_full_metadata_schema` - Return complete metadata for all tables. **Warning:** expensive — use only for debugging.

See the [MCP server README](neocarta/_mcp/README.md) for full server documentation.

### Claude Desktop

To connect the `neocarta-mcp` server to Claude Desktop, add the following entry to your `claude_desktop_config.json`:

```json
{
  "mcpServers": {
    "neocarta": {
      "command": "uvx",
      "args": [
        "--from",
        "neocarta[mcp]@0.3.0",
        "neocarta-mcp"
      ],
      "env": {
        "NEO4J_URI": "bolt://localhost:7687",
        "NEO4J_USERNAME": "neo4j",
        "NEO4J_PASSWORD": "your-password",
        "NEO4J_DATABASE": "neo4j",
        "OPENAI_API_KEY": "sk-...",
        "EMBEDDING_MODEL": "text-embedding-3-small",
        "EMBEDDING_DIMENSIONS": "768"
      }
    }
  }
}
```

## Contributing

### Dev Setup

This project uses [uv](https://docs.astral.sh/uv/) for dependency management and requires Python 3.10 or higher.

**[uv](https://docs.astral.sh/uv/)** — Python dependency manager:
```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
```

**Neo4j** — a running Neo4j instance is required. Options:
- [Neo4j AuraDB](https://neo4j.com/product/auradb/) — managed cloud (free tier available)
- [Neo4j Desktop](https://neo4j.com/download/) — local GUI-based instance
- [Docker image](https://hub.docker.com/_/neo4j) — lightweight instance

### Install All Dependencies (Recommended)

For most users, install all dependencies to run the complete workflow:
```bash
make install
```

This installs all dependency groups and allows you to:
- Create the metadata graph from BigQuery
- Run the MCP server
- Run the Text2SQL agent

### Install Specific Components

If you only need specific components, you can install individual dependency groups:

**Metadata Graph Only** (BigQuery ETL + embeddings)
```bash
make install-metadata-graph
```

**MCP Server Only** (neocarta MCP server)
```bash
make install-mcp-server
```

**Agent Only** (Text2SQL agent with MCP servers)
```bash
make install-agent
```
*Note: The agent group automatically includes mcp-server dependencies*

### Dependency Groups

The project is organized into the following dependency groups:

- **metadata-graph**: BigQuery metadata extraction, Neo4j loading, and embedding generation
- **mcp**: neocarta MCP server for metadata retrieval from Neo4j semantic layer
- **agent**: Text2SQL agent with LangChain (includes mcp-server dependencies)
- **dev**: Development tools (Jupyter notebooks)

### Sample Datasets

This repository contains two sample datasets
* ecommerce (4 tables)
* acme dataset (33 tables)

Ensure that the following environment variable is set before running and that you are credentialed via the gcloud cli.

```bash
GCP_PROJECT_ID=project-id
```

To create the dataset in your BigQuery instance, you may run the following command.

```bash
uv run examples/bigquery.py --dataset=acme

# or

uv run examples/bigquery.py --dataset=ecommerce
```

## Agent

This is the Text2SQL agent that converts natural language questions into SQL queries for BigQuery. The agent uses two MCP servers to:
1. Retrieve relevant database metadata from Neo4j using semantic similarity
2. Execute generated SQL queries against BigQuery

The agent architecture can be seen below.

```mermaid
---
config:
    layout: dagre
---

graph LR
    
    subgraph GCP["GCP Environment"]
        BQMCP(BigQuery<br>MCP)

        subgraph DataWarehouse["Data Warehouse"]
            BQData[(BigQuery)]
        end
        
        BQMCP <--> BQData
    end

    subgraph Local["Local Environment"]
        Agent("Text2SQL Agent")
        MetadataMCP("neocarta<br/>MCP")
        
        subgraph Graph["Database"]
            NEO[(Neo4j Graph)]
        end
        
        Agent <--> MetadataMCP
        MetadataMCP <--> NEO
    end
    
    User("User")
    
    subgraph LLM["LLM Service"]
        Model("LLM")
    end
    
    User <--> Agent
    Agent <--> Model
    Agent <--> BQMCP

```

**How it works**
1. User asks a natural language question about the data
2. Agent calls the SQL Metadata MCP server to retrieve relevant table schemas
3. Agent generates a SQL query via an LLM call based on the retrieved metadata context
4. Agent calls `execute_sql` from the BigQuery MCP server to run the query against BigQuery
5. Agent returns formatted results to the user

**BigQuery MCP Server Set Up**

Enable use of the [Bigquery MCP server](https://docs.cloud.google.com/bigquery/docs/reference/mcp) in your project.

Additional information may be found [here](https://docs.cloud.google.com/bigquery/docs/use-bigquery-mcp).

```bash
gcloud beta services mcp enable bigquery.googleapis.com --project=PROJECT_ID
```

To disable again run:

```bash
gcloud beta services mcp disable bigquery.googleapis.com --project=PROJECT_ID
```

You can test the BigQuery server connection with the following curl command

```bash
curl -k \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer $(gcloud auth application-default print-access-token)" \
  -d '{
  "jsonrpc": "2.0",
  "id": 3,
  "method": "tools/call",
  "params": {
    "name": "execute_sql",
    "arguments": {
      "projectId": "<PROJECT_ID>",
      "query": "SELECT table_name FROM `<PROJECT_ID>.<DATASET_ID>.INFORMATION_SCHEMA.TABLES`"
    }
  }
}' \
  https://bigquery.googleapis.com/mcp
```

**Running the Agent**

Use this command to run the agent locally:
```bash
make agent
```

The agent will start an interactive chat session in the terminal where you can ask questions about your data.


**BigQuery MCP Authentication**

The agent uses Google Cloud Application Default Credentials for BigQuery authentication:

```python
class GoogleAuth(httpx.Auth):
    def __init__(self):
        self.credentials, _ = default()

    def auth_flow(self, request):
        self.credentials.refresh(Request())
        request.headers["Authorization"] = f"Bearer {self.credentials.token}"
        yield request
```

Make sure you're authenticated with:
```bash
gcloud auth application-default login
```

**Environment Variables**

Required environment variables (add to `.env` file):

**Neo4j Connection**
* `NEO4J_URI` - Neo4j database URI (e.g., `bolt://localhost:7687`)
* `NEO4J_USERNAME` - Neo4j username (default: `neo4j`)
* `NEO4J_PASSWORD` - Neo4j password
* `NEO4J_DATABASE` - Neo4j database name (default: `neo4j`)

**LLM - OpenAI**
* `OPENAI_API_KEY` - OpenAI API key for embeddings and LLM

**Example Usage**

```
> What are the total sales by product category?

Agent: [Calls get_metadata_schema_by_column_semantic_similarity with query about sales and categories]
Agent: [Generates SQL query using retrieved schema]
Agent: [Calls execute_sql with generated query]
Agent: Here are the total sales by product category:
- Electronics: $15,234.50
- Clothing: $8,912.30
...
```
