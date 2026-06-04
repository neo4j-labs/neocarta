"""Shared, Spark-free foundation for the dbxcarta layers.

``dbxcarta-core`` sits underneath ``dbxcarta-spark``, ``dbxcarta-client``, and
``dbxcarta-submit``. It holds the helpers all three need and pulls in only the
Databricks SDK, never Spark: identifier and path helpers (:mod:`identifiers`),
the catalog-list rule (:mod:`catalogs`), workspace/secret access
(:mod:`workspace`), the SQL warehouse runner (:mod:`executor`), the example
preset (:mod:`presets`), the env-file overlay loader (:mod:`env`), the shared
table-materialize plumbing (:mod:`materialize`), and the question-generation
shapes (:mod:`questions`).

Submodules are imported directly (``from dbxcarta.core.identifiers import
quote_identifier``); this package root deliberately re-exports nothing so that
importing it pulls in no Spark, client, or Neo4j code.
"""
