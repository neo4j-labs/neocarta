"""Tests for the synthetic dense-schema generator."""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest
from dbxcarta_dense_schema_example.config import DenseSchemaConfig
from dbxcarta_dense_schema_example.generator import generate_candidates_json
from dbxcarta_dense_schema_example.question_generator import (
    _default_cache_dir,
    _format_sample_rows,
)
from dbxcarta_dense_schema_example.utils import load_dotenv_file


def test_generate_500_table_count():
    result = generate_candidates_json(500, "dense_500")
    schema = result["schemas"][0]
    tables = schema["tables"]
    assert len(tables) == 500


def test_generate_1000_table_count():
    result = generate_candidates_json(1000, "dense-1000")
    schema = result["schemas"][0]
    tables = schema["tables"]
    assert len(tables) == 1000


def test_uc_schema_name():
    result = generate_candidates_json(500, "my_schema")
    assert result["schemas"][0]["uc_schema"] == "my_schema"


def test_all_tables_have_id_pk():
    result = generate_candidates_json(500, "dense_500")
    for table in result["schemas"][0]["tables"]:
        assert "id" in table["primary_keys"], f"{table['name']} missing id PK"


def test_all_tables_have_columns():
    result = generate_candidates_json(500, "dense_500")
    for table in result["schemas"][0]["tables"]:
        assert table["columns"], f"{table['name']} has no columns"


def test_all_tables_have_rows():
    result = generate_candidates_json(500, "dense_500")
    for table in result["schemas"][0]["tables"]:
        assert table["rows"], f"{table['name']} has no rows"
        assert table["has_values"]


def test_rows_match_column_count():
    result = generate_candidates_json(500, "dense_500")
    for table in result["schemas"][0]["tables"]:
        n_cols = len(table["columns"])
        for row in table["rows"]:
            assert len(row) == n_cols, (
                f"{table['name']}: row length {len(row)} != col count {n_cols}"
            )


def test_fk_edges_exist():
    result = generate_candidates_json(500, "dense_500")
    total_fks = sum(len(t["foreign_keys"]) for t in result["schemas"][0]["tables"])
    assert total_fks > 500, f"Expected >500 FK edges, got {total_fks}"


def test_cross_domain_fks_present():
    result = generate_candidates_json(500, "dense_500")
    tables_by_name = {t["name"]: t for t in result["schemas"][0]["tables"]}
    sales_orders = tables_by_name.get("sales_sales_orders")
    assert sales_orders is not None
    fk_targets = {fk["foreign_table"] for fk in sales_orders["foreign_keys"]}
    assert "crm_customers" in fk_targets
    assert "hr_employees" in fk_targets


def test_deterministic_with_same_seed():
    a = generate_candidates_json(500, "dense_500", seed=42)
    b = generate_candidates_json(500, "dense_500", seed=42)
    assert json.dumps(a) == json.dumps(b)


def test_different_seed_different_rows():
    a = generate_candidates_json(500, "dense_500", seed=42)
    b = generate_candidates_json(500, "dense_500", seed=99)
    rows_a = a["schemas"][0]["tables"][0]["rows"]
    rows_b = b["schemas"][0]["tables"][0]["rows"]
    assert rows_a != rows_b


def test_different_seed_changes_table_mix():
    a = generate_candidates_json(500, "dense_500", seed=42)
    b = generate_candidates_json(500, "dense_500", seed=99)
    names_a = {t["name"] for t in a["schemas"][0]["tables"]}
    names_b = {t["name"] for t in b["schemas"][0]["tables"]}

    assert names_a != names_b
    assert {"hr_employees", "crm_customers", "sales_sales_orders"} <= names_a
    assert {"hr_employees", "crm_customers", "sales_sales_orders"} <= names_b


def test_descriptive_values_use_faker_data():
    result = generate_candidates_json(500, "dense_500", seed=42)
    tables_by_name = {t["name"]: t for t in result["schemas"][0]["tables"]}
    employees = tables_by_name["hr_employees"]
    name_idx = [c["name"] for c in employees["columns"]].index("name")
    description_idx = [c["name"] for c in employees["columns"]].index("description")

    assert employees["rows"][0][name_idx] != "Name 1"
    assert not employees["rows"][0][description_idx].startswith("Sample description row")


def test_unsupported_table_count_raises():
    with pytest.raises(ValueError, match="table_count"):
        generate_candidates_json(300, "dense_300")


def test_unique_table_names():
    result = generate_candidates_json(1000, "dense-1000")
    names = [t["name"] for t in result["schemas"][0]["tables"]]
    assert len(names) == len(set(names)), "Duplicate table names found"


def test_format_version():
    result = generate_candidates_json(500, "dense_500")
    assert result["format_version"] == 2


def test_question_cache_dir_defaults_to_table_count():
    config = DenseSchemaConfig(
        catalog="schemapile_lakehouse",
        table_count=1000,
        uc_schema="dense-1000",
        seed=42,
        candidate_cache=Path(".cache/candidates_1000.json"),
        volume_path="/Volumes/dbxcarta-catalog/dense-ops/dbxcarta-ops",
        questions_path="/Volumes/example/questions.json",
        question_model="databricks-meta-llama-3-3-70b-instruct",
        questions_target=60,
        questions_per_batch=3,
        question_temperature=0.2,
    )

    assert _default_cache_dir(config).as_posix() == ".cache/questions_1000"


def test_dotenv_does_not_override_explicit_env(tmp_path, monkeypatch):
    dotenv = tmp_path / ".env"
    dotenv.write_text("DENSE_TABLE_COUNT=500\n")
    monkeypatch.setenv("DENSE_TABLE_COUNT", "1000")

    load_dotenv_file(dotenv)

    assert os.environ["DENSE_TABLE_COUNT"] == "1000"


def test_question_prompt_includes_sample_rows():
    sample = _format_sample_rows(
        [("id", {"type": "INT"}), ("status", {"type": "STRING"})],
        [[1, "approved"], [2, "pending"]],
    )

    assert '"status": "approved"' in sample
    assert '"status": "pending"' in sample
