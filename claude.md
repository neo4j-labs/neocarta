# Neocarta Agent Guidelines

## General
Use `uv` to manage this project.
Always use `uv run` to execute code in the managed environment.

## Style
Use [numpy style guidelines](https://numpydoc.readthedocs.io/en/latest/format.html#documenting-classes) for this project.

## Contributing
To install the project in development mode, run the following `uv` command:

```bash
uv sync --all-groups
```

A PR must have the following before it can be reviewed and merged:
* Tests added or updated appropriately 
* All tests are successful
* Ruff formatting is run
* Ruff linting is successful
* CHANGELOG.md is updated

In order to run tests, use the following Make commands:
* Run unit tests -> `make test-unit`
* Run integration tests  -> `make test-it` (Requires Docker to run locally)
* Run MCP specific tests -> `make test-mcp` (Requires Docker to run locally)
* Run smoke tests -> `make test-smoke`
* Run all tests -> `make test-all` (Requires Docker to run locally)

Use the following Make commands for Ruff formatting and linting:
* Formatting -> `make fmt`
* Linting -> `make lint`

## Project Architecture Overview

Neocarta builds a semantic layer in Neo4j by integrating database metadata with business logic. It extracts schema and structural information from data sources, transforms it into a unified graph data model, and links it to business terminology — giving AI agents and users systemic familiarity with how data is organized and what it means. An optional MCP server exposes the graph to AI agents via tools.

**Key packages:**
- `neocarta/connectors/` — source-specific ETL pipelines (BigQuery, CSV, Dataplex, Pinecone)
- `neocarta/data_model/` — Pydantic models for the graph schema
- `neocarta/ingest/` — Neo4j load operations
- `neocarta/enrichment/` — embedding generation and metadata enrichment
- `neocarta/_mcp/` — MCP server exposing graph tools to AI agents
- `agent/` — LangChain/LangGraph Text2SQL agent (separate concern from the core library)
- `eval/` — evaluation framework for agent retrieval and SQL accuracy
- `datasets/` — sample dataset loaders (ecommerce, acme)
- `examples/` — runnable scripts demonstrating connector workflows
