"""Neo4j Spark Connector writer: node and relationship write helpers."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pyspark.sql import DataFrame, SparkSession

_FORMAT = "org.neo4j.spark.DataSource"


@dataclass(frozen=True)
class Neo4jConfig:
    uri: str
    username: str
    password: str
    batch_size: int = 20000

    def _base_opts(self) -> dict[str, str]:
        return {
            "url": self.uri,
            "authentication.type": "basic",
            "authentication.basic.username": self.username,
            "authentication.basic.password": self.password,
            "batch.size": str(self.batch_size),
        }


def write_nodes(df: DataFrame, config: Neo4jConfig, label: str) -> None:
    """MERGE nodes on id, updating all other properties on match."""
    write_nodes_multi(df, config, (label,))


def write_nodes_multi(
    df: DataFrame,
    config: Neo4jConfig,
    labels: tuple[str, ...],
) -> None:
    """MERGE nodes on id with one or more labels.

    Only the single-label form is used (via `write_nodes`). The multi-label
    form is NOT idempotent against an existing single-label node:
    `labels=("Column", "Extra")` compiles to `MERGE (n:Column:Extra {id})`,
    which matches the full label set, so it can never match an existing
    `:Column` node and instead creates a new one, colliding with the
    Column.id uniqueness constraint. Add a second label to already-written
    nodes server-side off a written property, never here.
    """
    label_opt = "".join(f":{name}" for name in labels)
    (
        df.write.format(_FORMAT)
        .mode("Overwrite")
        .options(**config._base_opts())
        .option("labels", label_opt)
        .option("node.keys", "id")
        .save()
    )


def read_query(
    spark: SparkSession,
    config: Neo4jConfig,
    cypher: str,
) -> DataFrame:
    """Run a server-side Cypher read through the connector `query` option.

    The connector executes `cypher` entirely on the Neo4j side and streams
    the result rows back as a DataFrame — no DataFrame rows are pushed into
    the read and nothing is collected to the driver. No bind parameters: the
    Neo4j Spark Connector does not parameterize a `query` read (its only
    documented injection point is the separate `script` option), so any value
    a caller needs in the Cypher must be interpolated upstream as a trusted,
    validated literal. `partitions` / `query.count` are intentionally not
    set: the default single-partition read is correct, and partitioning is
    the only batching lever to add later if a result set ever warrants it.
    """
    return spark.read.format(_FORMAT).options(**config._base_opts()).option("query", cypher).load()


def write_relationship(
    df: DataFrame,
    config: Neo4jConfig,
    rel_type: str,
    source_label: str,
    target_label: str,
    source_col: str = "source_id",
    target_col: str = "target_id",
    properties: tuple[str, ...] = (),
) -> None:
    """MERGE relationship between existing nodes matched by id.

    When `properties` is non-empty, those DataFrame columns are written as
    relationship properties. The Neo4j Spark Connector's `keys` strategy
    requires an explicit `relationship.properties` option — extra columns
    on the DataFrame are otherwise ignored. Keeping the option conditional
    lets simple relationships use only source/target ids while REFERENCES
    edges can persist provenance, confidence, and criteria.
    """
    writer = (
        df.write.format(_FORMAT)
        .mode("Overwrite")
        .options(**config._base_opts())
        .option("relationship", rel_type)
        .option("relationship.save.strategy", "keys")
        .option("relationship.source.labels", f":{source_label}")
        .option("relationship.source.save.mode", "Match")
        .option("relationship.source.node.keys", f"{source_col}:id")
        .option("relationship.target.labels", f":{target_label}")
        .option("relationship.target.save.mode", "Match")
        .option("relationship.target.node.keys", f"{target_col}:id")
    )
    if properties:
        writer = writer.option("relationship.properties", ",".join(properties))
    writer.save()
