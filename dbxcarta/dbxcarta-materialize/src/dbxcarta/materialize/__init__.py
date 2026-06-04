"""dbxcarta materialize: the Spark job that turns a blueprint into Delta tables.

The pure statement builders live in :mod:`dbxcarta.core.materialize`; this
package is the imperative shell that owns the ``SparkSession``, asks core for the
statements, runs them with ``spark.sql``, overlaps the independent table creates
in a bounded thread pool, runs the foreign-key pass serially after, and writes a
run-summary record. Import the entrypoint lazily through the console script so a
plain import of this package does not pull in PySpark.
"""
