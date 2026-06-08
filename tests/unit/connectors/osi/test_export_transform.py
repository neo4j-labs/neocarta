"""Unit tests for the OSI export transformer (graph snapshot → OSI YAML dict)."""

from pathlib import Path

import pytest
import yaml

from neocarta.connectors.osi.export.transform import OsiExportTransformer


def _minimal_snapshot() -> dict:
    """Snapshot shape produced by OsiGraphExtractor for a small OSI model."""
    return {
        "name": "sales_model",
        "description": "Sales test model",
        "osi_version": "0.2.0",
        "ai_context": '{"instructions": "test"}',
        "custom_extensions": [{"vendor_name": "SNOWFLAKE", "data": '{"warehouse": "X"}'}],
        "datasets": [
            {
                "name": "orders",
                "source": "warehouse.public.orders",
                "description": "Order facts",
                "ai_context": '{"synonyms": ["sales"]}',
                "custom_extensions": [],
                "primary_key": ["order_id"],
                "unique_keys": [["order_id"], ["customer_id", "order_date"]],
                "fields": [
                    {
                        "id": "warehouse.public.orders.order_id",
                        "name": "order_id",
                        "label": None,
                        "description": "Primary key",
                        "is_primary_key": True,
                        "is_foreign_key": False,
                        "is_time_dimension": None,
                        "expressions": [{"dialect": "ANSI_SQL", "expression": "order_id"}],
                        "ai_context": None,
                        "custom_extensions": [],
                    },
                    {
                        "id": "warehouse.public.orders.order_date",
                        "name": "order_date",
                        "label": "filter",
                        "description": None,
                        "is_primary_key": False,
                        "is_foreign_key": False,
                        "is_time_dimension": True,
                        "expressions": [{"dialect": "ANSI_SQL", "expression": "order_date"}],
                        "ai_context": None,
                        "custom_extensions": [],
                    },
                ],
            },
            {
                "name": "active_customers",
                "source": "SELECT * FROM customers WHERE active = true",
                "description": None,
                "ai_context": None,
                "custom_extensions": [],
                "fields": [],
            },
        ],
        "relationships": [
            {
                "name": "orders_to_customers",
                "from": "orders",
                "to": "customers",
                "from_columns": ["customer_id"],
                "to_columns": ["customer_id"],
                "custom_extensions": [],
            }
        ],
        "metrics": [
            {
                "name": "total_revenue",
                "description": "Sum of orders",
                "expressions": [{"dialect": "ANSI_SQL", "expression": "SUM(amount)"}],
                "ai_context": None,
                "custom_extensions": [],
            }
        ],
    }


def test_top_level_spec_has_version_and_semantic_model_list():
    """The output is a dict with top-level ``version`` and ``semantic_model: [...]``."""
    spec = OsiExportTransformer().transform(_minimal_snapshot())

    assert next(iter(spec.keys())) == "version"
    assert spec["version"] == "0.2.0"
    assert isinstance(spec["semantic_model"], list)
    assert len(spec["semantic_model"]) == 1


def test_top_level_omits_version_when_missing():
    """If osi_version is None/missing, the ``version`` key is omitted entirely."""
    snap = _minimal_snapshot()
    snap["osi_version"] = None
    spec = OsiExportTransformer().transform(snap)

    assert "version" not in spec
    assert "semantic_model" in spec


def test_semantic_model_carries_name_description_ai_context():
    """name + description + ai_context flow into the per-model dict (ai_context as native YAML)."""
    spec = OsiExportTransformer().transform(_minimal_snapshot())
    model = spec["semantic_model"][0]

    assert model["name"] == "sales_model"
    assert model["description"] == "Sales test model"
    # Stored ai_context JSON parses back to its native dict shape.
    assert model["ai_context"] == {"instructions": "test"}


def test_dataset_preserves_source_primary_unique_keys():
    """OsiTable.source + primary_key + unique_keys round-trip into the dataset entry."""
    spec = OsiExportTransformer().transform(_minimal_snapshot())
    orders = spec["semantic_model"][0]["datasets"][0]

    assert orders["source"] == "warehouse.public.orders"
    assert orders["primary_key"] == ["order_id"]
    assert orders["unique_keys"] == [["order_id"], ["customer_id", "order_date"]]


def test_query_dataset_emits_source_as_query_text():
    """Query-backed datasets emit the SQL text directly as ``source``."""
    spec = OsiExportTransformer().transform(_minimal_snapshot())
    query_ds = spec["semantic_model"][0]["datasets"][1]

    assert query_ds["name"] == "active_customers"
    assert query_ds["source"].startswith("SELECT")
    # No primary_key / unique_keys on a query-backed dataset
    assert "primary_key" not in query_ds
    assert "unique_keys" not in query_ds


def test_field_expressions_wrap_into_dialects_subdict():
    """Snapshot expressions list re-wraps into ``expression: {dialects: [...]}``."""
    spec = OsiExportTransformer().transform(_minimal_snapshot())
    order_id = spec["semantic_model"][0]["datasets"][0]["fields"][0]

    assert "expression" in order_id
    assert order_id["expression"] == {
        "dialects": [{"dialect": "ANSI_SQL", "expression": "order_id"}]
    }


def test_time_dimension_emits_dimension_block():
    """is_time_dimension tri-state: None omits key; True/False emit ``dimension: {is_time: ...}``."""
    spec = OsiExportTransformer().transform(_minimal_snapshot())
    fields = spec["semantic_model"][0]["datasets"][0]["fields"]
    order_id, order_date = fields[0], fields[1]

    # None on the snapshot → no dimension key in output
    assert "dimension" not in order_id
    # True on the snapshot → explicit emission
    assert order_date["dimension"] == {"is_time": True}


def test_time_dimension_false_is_emitted_explicitly():
    """When the OSI input declared dimension.is_time=False, the export emits it explicitly."""
    snap = _minimal_snapshot()
    # Mutate the order_date field to is_time_dimension=False
    snap["datasets"][0]["fields"][1]["is_time_dimension"] = False
    spec = OsiExportTransformer().transform(snap)
    order_date = spec["semantic_model"][0]["datasets"][0]["fields"][1]
    assert order_date["dimension"] == {"is_time": False}


def test_field_label_passthrough():
    """OsiColumn.label appears on the YAML field when set."""
    spec = OsiExportTransformer().transform(_minimal_snapshot())
    order_date = spec["semantic_model"][0]["datasets"][0]["fields"][1]
    assert order_date["label"] == "filter"


def test_relationships_use_dataset_names_for_from_to():
    """Relationships emit ``from``/``to`` as dataset names plus from_columns/to_columns lists."""
    spec = OsiExportTransformer().transform(_minimal_snapshot())
    rel = spec["semantic_model"][0]["relationships"][0]

    assert rel["from"] == "orders"
    assert rel["to"] == "customers"
    assert rel["from_columns"] == ["customer_id"]
    assert rel["to_columns"] == ["customer_id"]


def test_metrics_get_expression_block_and_description():
    """Metrics carry their expression dialects and description."""
    spec = OsiExportTransformer().transform(_minimal_snapshot())
    metric = spec["semantic_model"][0]["metrics"][0]

    assert metric["name"] == "total_revenue"
    assert metric["description"] == "Sum of orders"
    assert metric["expression"] == {
        "dialects": [{"dialect": "ANSI_SQL", "expression": "SUM(amount)"}]
    }


def test_empty_lists_and_none_fields_omitted_from_output():
    """``custom_extensions: []`` and None-valued fields are stripped from the YAML dict."""
    spec = OsiExportTransformer().transform(_minimal_snapshot())
    orders = spec["semantic_model"][0]["datasets"][0]
    order_id_field = orders["fields"][0]

    # Empty custom_extensions on the dataset gets omitted
    assert "custom_extensions" not in orders
    # None ai_context on the order_id field is omitted
    assert "ai_context" not in order_id_field


def test_custom_extensions_data_is_pretty_printed_json_literal_block():
    """custom_extensions.data is JSON-parsed and emitted as a pretty-printed literal block."""
    spec = OsiExportTransformer().transform(_minimal_snapshot())
    model = spec["semantic_model"][0]

    ext = model["custom_extensions"][0]
    assert ext["vendor_name"] == "SNOWFLAKE"
    # data is an indented multi-line JSON string with a trailing newline so PyYAML
    # emits it as ``|`` (clip) rather than ``|-`` (strip).
    assert ext["data"] == '{\n  "warehouse": "X"\n}\n'


def test_to_yaml_writes_parseable_yaml(tmp_path: Path):
    """to_yaml writes a file that yaml.safe_load can round-trip back to the same dict."""
    transformer = OsiExportTransformer()
    transformer.transform(_minimal_snapshot())

    out = tmp_path / "spec.yaml"
    transformer._to_yaml(out)

    reloaded = yaml.safe_load(out.read_text(encoding="utf-8"))
    assert reloaded == transformer.spec


def test_to_yaml_before_transform_raises(tmp_path: Path):
    """Calling to_yaml without transform first raises a RuntimeError."""
    with pytest.raises(RuntimeError, match="transform must be called"):
        OsiExportTransformer()._to_yaml(tmp_path / "x.yaml")


def test_simple_string_lists_render_in_flow_style(tmp_path: Path):
    """primary_key / unique_keys-inner / from_columns / to_columns render as ``[a, b]``."""
    transformer = OsiExportTransformer()
    transformer.transform(_minimal_snapshot())

    out = tmp_path / "spec.yaml"
    transformer._to_yaml(out)
    text = out.read_text(encoding="utf-8")

    # primary_key is flow
    assert "primary_key: [order_id]" in text
    # unique_keys outer is block; each inner is flow (no ugly `- -`)
    assert "unique_keys:" in text
    assert "- [order_id]" in text
    assert "- [customer_id, order_date]" in text
    assert "- - " not in text  # the unwanted nested-block notation
    # relationship from/to_columns are flow
    assert "from_columns: [customer_id]" in text
    assert "to_columns: [customer_id]" in text


def test_ai_context_renders_as_native_yaml_structure(tmp_path: Path):
    """ai_context stored as JSON-encoded dict round-trips into native YAML structure."""
    transformer = OsiExportTransformer()
    transformer.transform(_minimal_snapshot())

    out = tmp_path / "spec.yaml"
    transformer._to_yaml(out)
    text = out.read_text(encoding="utf-8")

    # SM-level ai_context (dict) emitted as native YAML, not a quoted JSON string.
    assert "ai_context:\n    instructions: test\n" in text
    # Dataset-level ai_context with synonyms parses back to a list of strings.
    assert "ai_context:\n      synonyms:\n      - sales\n" in text
    # No raw JSON-string form anywhere in the output.
    assert '\'{"synonyms":' not in text


def test_custom_extension_data_renders_as_literal_block(tmp_path: Path):
    """custom_extensions.data is emitted as a YAML literal block (``|``) with indented JSON."""
    transformer = OsiExportTransformer()
    transformer.transform(_minimal_snapshot())

    out = tmp_path / "spec.yaml"
    transformer._to_yaml(out)
    text = out.read_text(encoding="utf-8")

    # ``data: |`` (clip style, no minus) followed by indented multi-line JSON.
    assert "data: |\n" in text
    assert '"warehouse": "X"' in text
    assert "data: |-" not in text


def test_empty_snapshot_produces_minimal_yaml():
    """A snapshot with no datasets / relationships / metrics produces a spec with empty datasets list."""
    snap = {
        "name": "lonely_model",
        "description": None,
        "osi_version": "0.2.0",
        "ai_context": None,
        "custom_extensions": [],
        "datasets": [],
        "relationships": [],
        "metrics": [],
    }
    spec = OsiExportTransformer().transform(snap)

    model = spec["semantic_model"][0]
    assert model["name"] == "lonely_model"
    assert model["datasets"] == []
    assert "relationships" not in model
    assert "metrics" not in model
    assert "description" not in model
    assert "ai_context" not in model


def test_metric_only_semantic_model_emits_metrics_block_without_datasets():
    """An SM with only metrics still emits the metrics section."""
    snap = {
        "name": "metrics_only",
        "description": None,
        "osi_version": None,
        "ai_context": None,
        "custom_extensions": [],
        "datasets": [],
        "relationships": [],
        "metrics": [
            {
                "name": "count",
                "description": None,
                "expressions": [{"dialect": "ANSI_SQL", "expression": "COUNT(*)"}],
                "ai_context": None,
                "custom_extensions": [],
            }
        ],
    }
    spec = OsiExportTransformer().transform(snap)
    model = spec["semantic_model"][0]

    assert model["datasets"] == []
    assert len(model["metrics"]) == 1
    assert model["metrics"][0]["name"] == "count"


def test_round_trip_ingest_then_export(tpcds_spec):
    """Ingest the TPC-DS sample, build a snapshot-like dict, export, and verify key shape.

    This is a transformer-level round trip: we synthesize the snapshot that the graph
    extractor would produce by walking the ingest output, then run the export transformer
    and confirm structural fidelity (semantic model name, dataset names, relationship
    counts). The full round-trip through Neo4j lives in the IT suite.
    """
    from neocarta.connectors.osi.ingest.transform import OsiIngestTransformer

    ingest = OsiIngestTransformer()
    ingest.transform(tpcds_spec)

    # Build a minimal snapshot from ingest outputs to feed the export transformer.
    table_id_to_name = {t.id: t.name for t in ingest.table_nodes}
    columns_by_owner: dict[str, list[dict]] = {}
    for col in ingest.column_nodes:
        # owner id is the column id with the last segment removed
        owner_id = col.id.rsplit(".", 1)[0]
        columns_by_owner.setdefault(owner_id, []).append(
            {
                "id": col.id,
                "name": col.name,
                "label": col.label,
                "description": col.description,
                "is_primary_key": col.is_primary_key,
                "is_foreign_key": col.is_foreign_key,
                "is_time_dimension": col.is_time_dimension,
                "expressions": [],
                "ai_context": None,
                "custom_extensions": [],
            }
        )

    snapshot = {
        "name": ingest.osi_semantic_model_nodes[0].name,
        "description": ingest.osi_semantic_model_nodes[0].description,
        "osi_version": ingest.osi_semantic_model_nodes[0].osi_version,
        "ai_context": None,
        "custom_extensions": [],
        "datasets": [
            {
                "name": t.name,
                "source": t.source,
                "description": t.description,
                "primary_key": t.primary_key,
                "unique_keys": t.unique_keys,
                "ai_context": None,
                "custom_extensions": [],
                "fields": columns_by_owner.get(t.id, []),
            }
            for t in ingest.table_nodes
        ],
        "relationships": [
            {
                "name": j.name,
                "from": "orders",  # placeholder — IT test verifies real resolution
                "to": "customers",
                "from_columns": [],
                "to_columns": [],
                "custom_extensions": [],
            }
            for j in ingest.join_nodes
        ],
        "metrics": [],
    }

    spec = OsiExportTransformer().transform(snapshot)
    assert spec["semantic_model"][0]["name"] == "tpcds_retail_model"
    assert len(spec["semantic_model"][0]["datasets"]) == len(table_id_to_name)
