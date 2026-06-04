"""Phase 3 wiring guard: every relationship write in `_load` is routed
through `_rel_partition`.

`test_rel_partition.py` proves the helper's coalesce/repartition behavior
in isolation. This test proves the other half the proposal's validation
asks for: that `_load` actually sends *every* relationship DataFrame
(HAS_VALUE, HAS_SCHEMA, HAS_TABLE, HAS_COLUMN, and the declared / metadata
REFERENCES writes — six sites) through that helper with the
configured partition count, and never writes a relationship that bypassed
it. Node writes are stubbed; they intentionally do not use the helper.
"""

from __future__ import annotations

from types import SimpleNamespace

import dbxcarta.spark.run as pipeline
import pytest
from dbxcarta.spark.settings import SparkIngestSettings

_BASE = {
    "databricks_secret_scope": "dbxcarta-neo4j-test",
    "dbxcarta_catalog": "main",
    "dbxcarta_summary_volume": "/Volumes/cat/schema/vol/dbxcarta",
    "dbxcarta_summary_table": "cat.schema.table",
}

# The six relationship DataFrames _load must route through _rel_partition,
# tagged so the test can assert identity end to end.
_EXPECTED_RELS = {
    "has_value_df",
    "has_schema_df",
    "has_table_df",
    "has_column_df",
    "declared_edges_df",
    "metadata_edges_df",
}


@pytest.mark.parametrize("n", [1, 4])
def test_every_relationship_write_is_routed_through_rel_partition(
    monkeypatch,
    n: int,
) -> None:
    settings = SparkIngestSettings(dbxcarta_rel_write_partitions=n, **_BASE)

    rel_partition_calls: list[tuple[str, int]] = []
    write_rel_inputs: list[object] = []

    def fake_rel_partition(df, partitions):
        rel_partition_calls.append((df, partitions))
        return ("routed", df, partitions)

    def fake_write_rel(df, *args, **kwargs):
        write_rel_inputs.append(df)

    monkeypatch.setattr(pipeline, "_rel_partition", fake_rel_partition)
    monkeypatch.setattr(pipeline, "write_rel", fake_write_rel)
    monkeypatch.setattr(pipeline, "write_node", lambda *a, **k: None)
    monkeypatch.setattr(pipeline, "_project", lambda df, label: df)

    extract_result = SimpleNamespace(
        columns_df="columns_df",
        database_df="database_df",
        schema_node_df="schema_node_df",
        table_node_df="table_node_df",
        column_node_df="column_node_df",
        has_schema_df="has_schema_df",
        has_table_df="has_table_df",
        has_column_df="has_column_df",
    )
    fk_result = SimpleNamespace(
        declared_edge_count=1,
        declared_edges_df="declared_edges_df",
        metadata_edge_count=1,
        metadata_edges_df="metadata_edges_df",
    )
    values = SimpleNamespace(
        sample_stats=SimpleNamespace(value_nodes=1, has_value_edges=1),
        value_node_df="value_node_df",
        has_value_df="has_value_df",
    )
    summary = SimpleNamespace(extract=SimpleNamespace(schemas=0, tables=0, columns=0))

    pipeline._load(
        neo4j=object(),
        settings=settings,
        extract_result=extract_result,
        fk_result=fk_result,
        values=values,
        summary=summary,
    )

    # Every relationship write received a _rel_partition result, never a
    # raw DataFrame that bypassed the helper.
    assert len(write_rel_inputs) == len(_EXPECTED_RELS)
    assert all(isinstance(d, tuple) and d[0] == "routed" for d in write_rel_inputs)
    # The helper was called once per relationship DF, each with the
    # configured partition count, covering exactly the seven sites.
    assert {df for df, _ in rel_partition_calls} == _EXPECTED_RELS
    assert all(p == n for _, p in rel_partition_calls)
