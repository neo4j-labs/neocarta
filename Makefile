.PHONY: help agent create-graph create-graph-no-embeddings clean

help:
	@echo "Available commands:"
	@echo "  make install ................. Install all dependencies"
	@echo "  make install-metadata-graph .. Install dependencies for the metadata graph"
	@echo "  make install-mcp-server ...... Install dependencies for the mcp server"
	@echo "  make install-agent ........... Install dependencies for the agent"
	@echo "  .............................."
	@echo "  make load-ecommerce-dataset .. Load the ecommerce dataset into BigQuery"
	@echo "  make agent ................... Run the Text2SQL agent"
	@echo "  make create-graph ............ Extract BigQuery metadata and load into Neo4j with embeddings"
	@echo "  make create-graph-no-embeddings  Extract BigQuery metadata (skip embeddings)"
	@echo "  .............................."
	@echo "  make clean ................... Remove Python cache files and temporary directories"
	@echo "  make fmt ..................... Format the code with Ruff"
	@echo "  make lint .................... Lint the code with Ruff"
	@echo "  .............................."
	@echo "  make refresh-mermaid-data-model-images .... Refresh the data model images"
	@echo "  make refresh-mermaid-architecture-images .. Refresh the architecture images"

agent:
	uv run run_agent.py

create-graph-from-bigquery:
	uv run examples/bigquery.py

create-graph-from-bigquery-no-embeddings:
	uv run examples/bigquery.py --skip-embeddings

load-ecommerce-dataset-into-bigquery:
	uv run datasets/ecommerce_bigquery.py

fmt:
	uv run ruff format .

lint:
	uv run ruff check .

install:
	uv sync --all-groups

install-metadata-graph:
	uv sync --group metadata-graph

install-mcp-server:
	uv sync --group mcp-server

install-agent:
	uv sync --group agent

refresh-mermaid-data-model-images:
	mmdc -i assets/mermaid/data_model/glossary-metadata-data-model-1.mmd -o assets/images/data_model/glossary-metadata-data-model-1.png
	mmdc -i assets/mermaid/data_model/glossary-data-model-1.mmd -o assets/images/data_model/glossary-data-model-1.png
	mmdc -i assets/mermaid/data_model/sql-graph-data-model-core.mmd -o assets/images/data_model/sql-graph-data-model-core.png
	mmdc -i assets/mermaid/data_model/sql-graph-data-model-expanded-1.mmd -o assets/images/data_model/sql-graph-data-model-expanded-1.png
	mmdc -i assets/mermaid/data_model/lpg-graph-data-model.mmd -o assets/images/data_model/lpg-graph-data-model.png
	mmdc -i assets/mermaid/data_model/task-query-data-model-1.mmd -o assets/images/data_model/task-query-data-model-1.png
	mmdc -i assets/mermaid/data_model/query-log-data-model-1.mmd -o assets/images/data_model/query-log-data-model-1.png
	mmdc -i assets/mermaid/data_model/table-views-data-model-1.mmd -o assets/images/data_model/table-views-data-model-1.png

refresh-mermaid-architecture-images:
	mmdc -i assets/mermaid/architecture/bigquery-connector-architecture.mmd -o assets/images/architecture/bigquery-connector-architecture.png
	mmdc -i assets/mermaid/architecture/embeddings-connector-architecture.mmd -o assets/images/architecture/embeddings-connector-architecture.png
	mmdc -i assets/mermaid/architecture/full-connector-architecture.mmd -o assets/images/architecture/full-connector-architecture.png
	mmdc -i assets/mermaid/architecture/agent-architecture.mmd -o assets/images/architecture/agent-architecture.png
	mmdc -i assets/mermaid/architecture/dataplex-connector-architecture.mmd -o assets/images/architecture/dataplex-connector-architecture.png
	mmdc -i assets/mermaid/architecture/bigquery-full-architecture.mmd -o assets/images/architecture/bigquery-full-architecture.png
	
test-unit:
	uv run pytest tests/unit

test-mcp:
	uv run pytest tests/integration/_mcp -v

clean:
	find . -type d -name "__pycache__" -exec rm -rf {} + 2>/dev/null || true
	find . -type f -name "*.pyc" -delete 2>/dev/null || true
	find . -type d -name ".pytest_cache" -exec rm -rf {} + 2>/dev/null || true
	find . -type d -name "*.egg-info" -exec rm -rf {} + 2>/dev/null || true
