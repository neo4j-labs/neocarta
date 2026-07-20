.PHONY: help agent create-graph create-graph-no-embeddings musicbrainz-agent create-graph-from-musicbrainz create-graph-from-musicbrainz-no-embeddings clean

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
	@echo "  make create-graph-from-musicbrainz ............... Load the MusicBrainz schema into Neo4j with embeddings"
	@echo "  make create-graph-from-musicbrainz-no-embeddings  Load the MusicBrainz schema (skip embeddings)"
	@echo "  make musicbrainz-agent ....... Run the MusicBrainz agent"
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

create-graph-from-musicbrainz:
	uv run examples/musicbrainz.py

create-graph-from-musicbrainz-no-embeddings:
	uv run examples/musicbrainz.py --skip-embeddings

musicbrainz-agent:
	uv run agent/musicbrainz_agent.py

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
	mmdc -i assets/mermaid/data_model/glossary-metadata-data-model-1.mmd -o assets/images/data_model/glossary-metadata-data-model-1.png --scale 2 --backgroundColor transparent
	mmdc -i assets/mermaid/data_model/glossary-data-model-1.mmd -o assets/images/data_model/glossary-data-model-1.png --scale 2 --backgroundColor transparent
	mmdc -i assets/mermaid/data_model/sql-graph-data-model-core.mmd -o assets/images/data_model/sql-graph-data-model-core.png --scale 2 --backgroundColor transparent
	mmdc -i assets/mermaid/data_model/sql-graph-data-model-expanded-1.mmd -o assets/images/data_model/sql-graph-data-model-expanded-1.png --scale 2 --backgroundColor transparent
	mmdc -i assets/mermaid/data_model/lpg-graph-data-model.mmd -o assets/images/data_model/lpg-graph-data-model.png --scale 2 --backgroundColor transparent
	mmdc -i assets/mermaid/data_model/task-query-data-model-1.mmd -o assets/images/data_model/task-query-data-model-1.png --scale 2 --backgroundColor transparent
	mmdc -i assets/mermaid/data_model/query-log-data-model-1.mmd -o assets/images/data_model/query-log-data-model-1.png --scale 2 --backgroundColor transparent
	mmdc -i assets/mermaid/data_model/table-views-data-model-1.mmd -o assets/images/data_model/table-views-data-model-1.png --scale 2 --backgroundColor transparent
	mmdc -i assets/mermaid/data_model/osi-data-model-1.mmd -o assets/images/data_model/osi-data-model-1.png --scale 2 --backgroundColor transparent
	mmdc -i assets/mermaid/data_model/governance-data-model-1.mmd -o assets/images/data_model/governance-data-model-1.png --scale 2 --backgroundColor transparent

refresh-mermaid-architecture-images:
	mmdc -i assets/mermaid/architecture/bigquery-connector-architecture.mmd -o assets/images/architecture/bigquery-connector-architecture.png
	mmdc -i assets/mermaid/architecture/embeddings-connector-architecture.mmd -o assets/images/architecture/embeddings-connector-architecture.png
	mmdc -i assets/mermaid/architecture/full-connector-architecture.mmd -o assets/images/architecture/full-connector-architecture.png
	mmdc -i assets/mermaid/architecture/agent-architecture.mmd -o assets/images/architecture/agent-architecture.png
	mmdc -i assets/mermaid/architecture/dataplex-connector-architecture.mmd -o assets/images/architecture/dataplex-connector-architecture.png
	mmdc -i assets/mermaid/architecture/bigquery-full-architecture.mmd -o assets/images/architecture/bigquery-full-architecture.png
	mmdc -i assets/mermaid/architecture/quickstart-flow.mmd -o assets/images/architecture/quickstart-flow.png --scale 2 --backgroundColor transparent

# Test selection is by pytest marker (-m). The path/--ignore args are retained as a
# transitional collection boundary: pytest imports modules at collection time before
# -m deselects, and each CI job installs only a subset of optional deps, so scoping
# collection keeps a target from importing modules whose deps are absent. See S0-3.
test-unit:
	uv run pytest tests/unit -m unit -v --ignore=tests/unit/_mcp --ignore=tests/unit/_cli --ignore=tests/unit/agent

test-it:
	uv run pytest tests/integration -m integration -v --ignore=tests/integration/_mcp --ignore=tests/integration/_cli

test-mcp:
	uv run pytest tests/integration/_mcp -m mcp -v
	uv run pytest tests/unit/_mcp -m mcp -v

test-cli:
	uv run pytest tests/unit/_cli -m cli -v

test-agent:
	uv run pytest tests/unit/agent -m agent -v

test-smoke:
	uv run pytest tests/smoke -m smoke -v

test-all:
	uv run pytest tests/ -v

test-cov:
	uv run pytest tests/unit -m unit -v --ignore=tests/unit/_mcp --ignore=tests/unit/_cli --ignore=tests/unit/agent --cov=neocarta --cov-report=term-missing --cov-report=xml --cov-report=html

# Prove the marker-based selection is identical to the legacy path-based selection
# for every test-* target, and that the markers partition the suite (exactly one per
# test). Needs a full env (uv sync --all-groups + all extras) so every module imports.
check-markers:
	uv run python scripts/check_marker_parity.py

clean:
	find . -type d -name "__pycache__" -exec rm -rf {} + 2>/dev/null || true
	find . -type f -name "*.pyc" -delete 2>/dev/null || true
	find . -type d -name ".pytest_cache" -exec rm -rf {} + 2>/dev/null || true
	find . -type d -name "*.egg-info" -exec rm -rf {} + 2>/dev/null || true
