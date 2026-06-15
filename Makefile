.PHONY: help agent create-graph create-graph-no-embeddings musicbrainz-agent create-graph-from-musicbrainz create-graph-from-musicbrainz-no-embeddings clean test-databricks build databricks-wheel-test

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
	@echo "  make test-databricks ......... Run the Databricks connector unit tests"
	@echo "  make build ................... Build the neocarta wheel + sdist into dist/"
	@echo "  make databricks-wheel-test ... Clean-room install the wheel and run smoke tests"
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

refresh-mermaid-architecture-images:
	mmdc -i assets/mermaid/architecture/bigquery-connector-architecture.mmd -o assets/images/architecture/bigquery-connector-architecture.png
	mmdc -i assets/mermaid/architecture/embeddings-connector-architecture.mmd -o assets/images/architecture/embeddings-connector-architecture.png
	mmdc -i assets/mermaid/architecture/full-connector-architecture.mmd -o assets/images/architecture/full-connector-architecture.png
	mmdc -i assets/mermaid/architecture/agent-architecture.mmd -o assets/images/architecture/agent-architecture.png
	mmdc -i assets/mermaid/architecture/dataplex-connector-architecture.mmd -o assets/images/architecture/dataplex-connector-architecture.png
	mmdc -i assets/mermaid/architecture/bigquery-full-architecture.mmd -o assets/images/architecture/bigquery-full-architecture.png
	
test-unit:
	uv run pytest tests/unit -v --ignore=tests/unit/_mcp --ignore=tests/unit/_cli --ignore=tests/unit/agent

test-it:
	uv run pytest tests/integration -v --ignore=tests/integration/_mcp --ignore=tests/integration/_cli

test-mcp:
	uv run pytest tests/integration/_mcp -v
	uv run pytest tests/unit/_mcp -v

test-cli:
	uv run pytest tests/unit/_cli -v

test-agent:
	uv run pytest tests/unit/agent -v

test-smoke:
	uv run pytest tests/smoke -v

test-all:
	uv run pytest tests/ -v

# --- Databricks connector ---------------------------------------------------
# The Databricks connector lives under neocarta/connectors/databricks/ and its
# Spark-agnostic FK inference under neocarta/enrichment/foreign_keys/. Its local
# (no-cluster) Spark tests run with the `databricks` group, which pulls pyspark
# via the `databricks-spark` extra.
test-databricks:
	uv run --group databricks pytest tests/unit/connectors/databricks tests/unit/enrichment/foreign_keys -v

# Build the neocarta wheel + sdist into dist/. This is the single artifact that
# carries the Databricks connector; stage the wheel on a UC Volume to run the
# Spark ingest job on a cluster.
build:
	uv build

# Clean-room packaging check: build the wheel, install neocarta[databricks-spark]
# into a fresh empty virtualenv (NOT the editable source tree), then import the
# connector and run the smoke suite against the installed wheel. Catches modules
# missing from the wheel and undeclared dependencies that the editable tree hides
# — the exact failures a fresh install / cluster would hit. Smoke tests are copied
# to a temp dir and run from there so the source `neocarta/` package cannot shadow
# the installed distribution.
databricks-wheel-test:
	@set -eu; \
	rm -rf dist; \
	uv build; \
	WHEEL="$$(ls dist/neocarta-*-py3-none-any.whl)"; \
	WORK="$$(mktemp -d)"; \
	trap 'rm -rf "$$WORK"' EXIT; \
	python3 -m venv "$$WORK/venv"; \
	"$$WORK/venv/bin/pip" install --quiet --upgrade pip; \
	"$$WORK/venv/bin/pip" install --quiet "neocarta[databricks-spark] @ file://$(CURDIR)/$$WHEEL" pytest; \
	cp -R tests/smoke "$$WORK/smoke"; \
	echo ">>> importing connector from installed wheel"; \
	(cd "$$WORK" && ./venv/bin/python -c "from neocarta.connectors.databricks import DatabricksSparkSchemaConnector; import pyspark; print('import ok; pyspark', pyspark.__version__)"); \
	echo ">>> running smoke suite against installed wheel"; \
	(cd "$$WORK" && ./venv/bin/pytest smoke -v)

clean:
	find . -type d -name "__pycache__" -exec rm -rf {} + 2>/dev/null || true
	find . -type f -name "*.pyc" -delete 2>/dev/null || true
	find . -type d -name ".pytest_cache" -exec rm -rf {} + 2>/dev/null || true
	find . -type d -name "*.egg-info" -exec rm -rf {} + 2>/dev/null || true
