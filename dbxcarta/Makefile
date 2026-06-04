# dbxcarta developer Makefile.
#
# The e2e-* targets run the Databricks pipeline for one example in two phases:
# the *-ingest target rebuilds+ships the wheels from current source then submits
# ingest; the *-client target submits the client evaluation. Run ingest, let it
# finish, then run client. Use them to test changes to the dbxcarta packages.
#
# Run from the repo root: `make e2e-finance-genie-ingest`.
#
# Each target points DBXCARTA_ENV_FILE at that example's committed dbxcarta
# *overlay* (dbxcarta-overlay.env), NOT the example's standalone ./.env. The
# overlay carries the dbxcarta-scoped config (catalogs, schemas, volume,
# flags) and layers over the shared base .env at the repo root. The standalone
# ./.env is only for the local read-only demo and never reaches this pipeline.
# The path is set inline on every command, so `make` works from the repo root
# with no `export` and no per-shell setup.

.PHONY: help \
	test test-it test-slow test-wheel typecheck \
	e2e-finance-genie-ingest e2e-finance-genie-client e2e-finance-genie-teardown \
	e2e-schemapile-ingest e2e-schemapile-client e2e-schemapile-teardown \
	e2e-dense-schema-ingest e2e-dense-schema-client e2e-dense-schema-teardown

# Phase 1: ensure the catalog/schema/volume exist, rebuild+ship wheels from
# current source, then submit ingest. $(1) is the overlay path. bootstrap is
# idempotent (CREATE ... IF NOT EXISTS), so it does real work only the first
# time and is a no-op on every later run. publish-wheels rebuilds the wheels
# and already uploads the cluster bootstrap script, so no separate
# `upload --all` is needed.
define e2e_ingest
	DBXCARTA_ENV_FILE=$(1) uv run --group dbxcarta dbxcarta-submit bootstrap
	DBXCARTA_ENV_FILE=$(1) uv run --group dbxcarta dbxcarta-submit publish-wheels
	DBXCARTA_ENV_FILE=$(1) uv run --group dbxcarta dbxcarta-submit submit-entrypoint ingest
endef

# Phase 2: submit the client evaluation. $(1) is the overlay path.
define e2e_client
	DBXCARTA_ENV_FILE=$(1) uv run --group dbxcarta dbxcarta-submit submit-entrypoint client
endef

# Teardown: drop this example's DBXCARTA_TEARDOWN_TARGET. $(1) is the overlay
# path. Never chained into ingest; run by hand. Requires --yes-i-mean-it, or it
# only prints what it would drop.
define e2e_teardown
	DBXCARTA_ENV_FILE=$(1) uv run --group dbxcarta dbxcarta-submit teardown --yes-i-mean-it
endef

# All targets run through the neocarta workspace env with `uv run --group
# dbxcarta`, which installs every dbxcarta workspace package plus pyspark/neo4j
# (they arrive transitively and stay out of a base `uv sync`). The pytest flags
# are passed here rather than in a config file, so neocarta's root
# [tool.pytest.ini_options] is untouched and there is no dbxcarta/pyproject.toml:
#   --import-mode=importlib            dbxcarta's import mode (no sys.path tricks)
#   -o consider_namespace_packages=true
#       the dbxcarta packages share the PEP 420 `dbxcarta` namespace across
#       several editable distributions; without this pytest binds `dbxcarta` to a
#       single directory (the subtree shadows it via neocarta's pythonpath=".")
#       and `import dbxcarta.submit` etc. fail to collect.
PYTEST_FLAGS = --import-mode=importlib -o consider_namespace_packages=true

# Fast lane: the default unit/integration-free suite. Runs `tests`, ignoring the
# live integration directory, the slow fk_guard file, and the wheel-bundle smoke
# test so they are never picked up by default (mirrors the previous
# `-m 'not live and not slow'` behavior now that the markers are gone).
test:
	uv run --group dbxcarta pytest tests $(PYTEST_FLAGS) \
		--ignore=tests/integration \
		--ignore=tests/spark/fk_guard/test_single_execution_guard.py \
		--ignore=tests/submit/test_cluster_wheel_bundle_smoke.py

# Live integration suite: needs a live Databricks profile, Neo4j, and a
# previously-loaded catalog. Not part of the default `make test` run.
test-it:
	uv run --group dbxcarta pytest tests/integration $(PYTEST_FLAGS)

# Slow Spark fk_guard regression guard: no credentials, only time. Kept out of
# the default run; invoke explicitly.
test-slow:
	uv run --group dbxcarta pytest tests/spark/fk_guard/test_single_execution_guard.py $(PYTEST_FLAGS)

# Cluster-wheel bundle smoke test: builds the bundled entrypoint wheels and
# asserts each physically carries dbxcarta/core. Needs `uv build` (no live
# creds), but is slow, so it is kept out of the fast lane and invoked here.
test-wheel:
	uv run --group dbxcarta pytest tests/submit/test_cluster_wheel_bundle_smoke.py $(PYTEST_FLAGS)

# Strict mypy, scoped to the dbxcarta packages (neocarta opts in later).
typecheck:
	uv run --group dbxcarta mypy -p dbxcarta.core -p dbxcarta.spark \
		-p dbxcarta.client -p dbxcarta.submit -p dbxcarta.materialize

help:
	@echo "dbxcarta test targets:"
	@echo "  make test       Fast lane: unit suite (excludes integration + slow fk_guard)"
	@echo "  make test-it    Live integration suite (requires live Databricks/Neo4j + loaded catalog)"
	@echo "  make test-slow  Slow Spark fk_guard regression guard (no creds, just time)"
	@echo ""
	@echo "dbxcarta e2e pipeline targets (run from repo root, ingest then client):"
	@echo "  make e2e-finance-genie-ingest    Bootstrap, rebuild wheels, then ingest for finance-genie"
	@echo "  make e2e-finance-genie-client    Client evaluation for finance-genie"
	@echo "  make e2e-finance-genie-teardown  Drop finance-genie's teardown target"
	@echo "  make e2e-schemapile-ingest       Bootstrap, rebuild wheels, then ingest for schemapile"
	@echo "  make e2e-schemapile-client       Client evaluation for schemapile"
	@echo "  make e2e-schemapile-teardown     Drop schemapile's teardown target"
	@echo "  make e2e-dense-schema-ingest     Bootstrap, rebuild wheels, then ingest for dense-schema"
	@echo "  make e2e-dense-schema-client     Client evaluation for dense-schema"
	@echo "  make e2e-dense-schema-teardown   Drop dense-schema's teardown target"
	@echo ""
	@echo "The *-ingest targets bootstrap the catalog/schema/volume (idempotent) and"
	@echo "rebuild wheels from current source, so they reflect local changes to the"
	@echo "dbxcarta packages. The *-teardown targets drop each example's"
	@echo "DBXCARTA_TEARDOWN_TARGET and are only ever run by hand. Prerequisites"
	@echo "(one-time: install the example preset, secrets, questions, upstream UC"
	@echo "tables) are in each example README."

e2e-finance-genie-ingest:
	$(call e2e_ingest,examples/finance-genie/dbxcarta-overlay.env)

e2e-finance-genie-client:
	$(call e2e_client,examples/finance-genie/dbxcarta-overlay.env)

e2e-finance-genie-teardown:
	$(call e2e_teardown,examples/finance-genie/dbxcarta-overlay.env)

e2e-schemapile-ingest:
	$(call e2e_ingest,examples/schemapile/dbxcarta-overlay.env)

e2e-schemapile-client:
	$(call e2e_client,examples/schemapile/dbxcarta-overlay.env)

e2e-schemapile-teardown:
	$(call e2e_teardown,examples/schemapile/dbxcarta-overlay.env)

e2e-dense-schema-ingest:
	$(call e2e_ingest,examples/dense-schema/dbxcarta-overlay.env)

e2e-dense-schema-client:
	$(call e2e_client,examples/dense-schema/dbxcarta-overlay.env)

e2e-dense-schema-teardown:
	$(call e2e_teardown,examples/dense-schema/dbxcarta-overlay.env)
