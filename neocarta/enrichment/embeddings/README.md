# Embeddings

Generates and stores vector embeddings for nodes in the semantic graph, enabling similarity-based retrieval by the MCP server tools.

## Overview

The embeddings module embeds the `description` field of graph nodes using any embedding provider supported by [LiteLLM](https://docs.litellm.ai/) (OpenAI, Azure OpenAI, Cohere, Bedrock, Vertex AI, Gemini, Ollama, HuggingFace, etc.) and writes the resulting vectors back to Neo4j. The vector dimension is auto-detected from the model on first use, the Neo4j vector index is created at that size, and only nodes without an existing `embedding` property are processed — making reruns safe and incremental.

## Process

```
Neo4j (nodes missing embeddings)
        ↓  get_nodes_to_embed()
   DataFrame [id, node_label, description]
        ↓  create_embeddings_in_batches_{sync|async}()
   DataFrame [id, embedding]
        ↓  write_embeddings_to_graph()
Neo4j (embedding property set on each node)
```

1. **Probe** — embed a tiny test string once to discover the model's native vector size
2. **Index** — create the Neo4j vector index at that size (idempotent, skips if it already exists)
3. **Fetch** — queries Neo4j for nodes of a given label where `description IS NOT NULL` and `embedding IS NULL`
4. **Embed** — calls the embeddings API for each description, in batches
5. **Write** — sets the `embedding` vector property on each matched node using `db.create.setNodeVectorProperty`

A cosine-similarity vector index (e.g. `table_vector_index`) is created for each node label before embedding begins, if one does not already exist.


## Usage

### Sync

```python
from neo4j import GraphDatabase
from neocarta import NodeLabel
from neocarta.enrichment.embeddings import LiteLLMEmbeddingsConnector

driver = GraphDatabase.driver(NEO4J_URI, auth=(NEO4J_USER, NEO4J_PASSWORD))

connector = LiteLLMEmbeddingsConnector(
    neo4j_driver=driver,
    embedding_model="text-embedding-3-small",  # dimension auto-detected
    database_name="neo4j",
)
# Enum members are recommended, but exact string values (e.g. "Table", "Column") also work.
connector.run(node_labels=[NodeLabel.TABLE, NodeLabel.COLUMN], batch_size=100)
```

### Async

Within each batch, all embedding API calls are issued concurrently via `asyncio.gather`, making this significantly faster for large graphs:

```python
from neo4j import GraphDatabase
from neocarta import NodeLabel
from neocarta.enrichment.embeddings import LiteLLMEmbeddingsConnector

driver = GraphDatabase.driver(NEO4J_URI, auth=(NEO4J_USER, NEO4J_PASSWORD))

connector = LiteLLMEmbeddingsConnector(
    neo4j_driver=driver,
    embedding_model="text-embedding-3-small",  # dimension auto-detected
)
# Enum members are recommended, but exact string values (e.g. "Table", "Column") also work.
await connector.arun(node_labels=[NodeLabel.TABLE, NodeLabel.COLUMN], batch_size=100)
```

See [examples/sync_embeddings.py](../../../examples/sync_embeddings.py) and [examples/async_embeddings.py](../../../examples/async_embeddings.py) for runnable scripts with CLI argument support.

## Configuration

| Parameter | Default | Description |
|---|---|---|
| `embedding_model` | `"text-embedding-3-small"` | LiteLLM model identifier (provider prefix optional for OpenAI) |
| `dimensions` | `None` | Requested vector dimension for models that support truncation. When set it is sent to the provider; if the model rejects it (doesn't support truncation), the connector drops it and retries, keeping the native dimension. `None` = auto-detect. |
| `litellm_kwargs` | `None` | Extra keyword arguments forwarded to `litellm.embedding` / `litellm.aembedding`. Use this for `api_key` / `api_base` (LiteLLM Proxy or custom endpoints) or `api_version`. |
| `database_name` | `"neo4j"` | Target Neo4j database |
| `node_labels` | `[NodeLabel.TABLE, NodeLabel.COLUMN]` | Node labels to embed |
| `batch_size` | `100` | Nodes processed per batch |

By default the vector dimension is read directly from the model's response on first use. To request a non-default size from a model that supports it (e.g. OpenAI `text-embedding-3-large` truncated to 1024), pass `dimensions=1024`; the probe call then detects 1024 and the index is created at 1024. Models that don't support truncation reject the parameter; the connector then drops it and retries, keeping the model's native dimension, so the index always matches the vectors actually returned.

**Authentication:** Set the appropriate environment variable for your provider, e.g.:

- `OPENAI_API_KEY` for OpenAI
- `GEMINI_API_KEY` for Gemini (AI Studio)
- `COHERE_API_KEY` for Cohere
- `AZURE_API_KEY`, `AZURE_API_BASE`, `AZURE_API_VERSION` for Azure OpenAI
- `AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY`, `AWS_REGION_NAME` for Bedrock

See the [LiteLLM provider docs](https://docs.litellm.ai/docs/providers) for the full list.

## Batch Processing

Nodes are processed in sequential batches of `batch_size`. Within each batch:

- **Sync**: descriptions are embedded one at a time
- **Async**: all descriptions in the batch are embedded concurrently

Failed individual embeddings (e.g. API errors) return `None` and are silently skipped — the node is left without an `embedding` property and will be picked up on the next run.

## Vector Index

`create_vector_index` (from `neocarta.ingest.indexes`) is called once per node label after the dimension probe. It creates a Neo4j vector index using cosine similarity:

```
{node_label.lower()}_vector_index  →  ON (n:{NodeLabel}).embedding
    vector.dimensions: <detected dimension>
    vector.similarity_function: cosine
```

The index creation is idempotent (`IF NOT EXISTS`), so it is safe to call on every run. **If you switch to a model with a different output dimension on an existing graph**, the old index will not be recreated — drop the existing `*_vector_index` constraints first, then rerun.
