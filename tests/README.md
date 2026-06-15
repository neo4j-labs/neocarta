# Tests

## Running tests

**All tests:**
```bash
uv run pytest
```

**Unit tests only:**
```bash
uv run pytest tests/unit
```

**Integration tests only:**
```bash
uv run pytest tests/integration
```

**A specific module:**
```bash
uv run pytest tests/unit/connectors/bigquery/schema/
```

Tests are discovered automatically from the `tests/` directory (configured in `pyproject.toml`).

## Unit tests

Unit tests use mocked clients and pre-populated caches — no external services are required.

| Test area | What's covered |
|---|---|
| `bigquery/schema` | Extractor initialization, schema/table/column extraction from mock BQ client; transformer mapping to data model nodes and relationships |
| `bigquery/logs` | Log extractor initialization, SQL query construction, edge cases in log parsing |
| `query_log` | Query log extract, transform, and SQL parsing utilities |
| `connectors/utils` | Deterministic ID generation (`generate_id`) |
| `connectors/test_loader.py` | Generic connector loader behaviour |
| `data_model/metadata` | `NeocartaGraph` metadata node validation |
| `data_model/schema/rdbms` | Relational structural node validation |
| `data_model/schema/lpg` | LPG structural node validation and import warning |
| `data_model/glossary` | Glossary node and relationship models |
| `data_model/instance` | `Value` node coercion and `HasValue` relationship |

## Integration tests

Integration tests spin up a real Neo4j instance using [testcontainers](https://testcontainers-python.readthedocs.io/en/latest/) and run the full connector workflow against it. Docker must be running.

**Covered:** CSV connector — full ingest workflow, custom filenames, ecommerce dataset fixture.

Each test function gets a fresh Neo4j driver; the database is wiped before and after every test. The container starts once per test module and is torn down automatically.

## Dependencies

Install dev dependencies before running tests:

```bash
uv sync --group dev
```

This adds `pytest` and `testcontainers[neo4j]` alongside the main dependencies.

## Adding tests

- **Unit tests** go under `tests/unit/` mirroring the source module path. Use `unittest.mock.Mock` for external clients and pre-populate connector caches via `extractor._cache[...]` / `transformer._node_cache[...]` (see existing conftest files for examples).
- **Integration tests** go under `tests/integration/`. Use the shared `neo4j_driver` fixture from `conftest.py` — it handles container lifecycle and database cleanup automatically.