from __future__ import annotations

from pathlib import Path

from dbxcarta_schemapile_example.candidate_selector import (
    _sanitize_schema_name,
    select_candidates,
)
from dbxcarta_schemapile_example.config import SchemaPileConfig


def _config() -> SchemaPileConfig:
    return SchemaPileConfig(
        repo=Path("/tmp/schemapile"),
        input_filename="schemapile-perm.json",
        target_tables=1000,
        strategy="random",
        seed=42,
        min_tables=2,
        max_tables=100,
        min_fk_edges=1,
        require_self_contained=True,
        require_data=False,
        slice_cache=Path("/tmp/slice.json"),
        candidate_cache=Path("/tmp/candidates.json"),
        candidate_min_tables=2,
        candidate_max_tables=20,
        candidate_min_fk_edges=1,
        candidate_require_data=False,
        candidate_limit=10,
        catalog="schemapile_lakehouse",
        volume_path="/Volumes/dbxcarta-catalog/schemapile_ops/dbxcarta-ops",
        questions_path="/Volumes/dbxcarta-catalog/schemapile_ops/dbxcarta-ops/dbxcarta/questions.json",
        question_model="databricks-meta-llama-3-3-70b-instruct",
        questions_per_schema=6,
        question_temperature=0.2,
    )


def _entry(tables):
    return {
        "TABLES": {
            name: {
                "COLUMNS": {
                    col["name"]: {
                        "TYPE": col["type"],
                        "VALUES": col.get("values"),
                    }
                    for col in table["columns"]
                },
                "PRIMARY_KEYS": table.get("pks", []),
                "FOREIGN_KEYS": table.get("fks", []),
            }
            for name, table in tables.items()
        }
    }


def test_extract_rows_position_alignment():
    from dbxcarta_schemapile_example.candidate_selector import _extract_rows

    columns = {
        "id": {"TYPE": "INT", "VALUES": [1, 2, 3]},
        "name": {"TYPE": "STRING", "VALUES": ["a", "b", "c"]},
    }
    rows = _extract_rows(columns)
    assert rows == ((1, "a"), (2, "b"), (3, "c"))


def test_extract_rows_misaligned_returns_empty():
    from dbxcarta_schemapile_example.candidate_selector import _extract_rows

    columns = {
        "id": {"TYPE": "INT", "VALUES": [1, 2, 3]},
        "name": {"TYPE": "STRING", "VALUES": ["a", "b"]},
    }
    assert _extract_rows(columns) == ()


def test_extract_rows_pads_missing_values_with_null():
    """Columns without VALUES contribute NULL; only VALUES-having columns
    must share a length."""
    from dbxcarta_schemapile_example.candidate_selector import _extract_rows

    columns = {
        "id": {"TYPE": "INT"},
        "name": {"TYPE": "STRING", "VALUES": ["a", "b"]},
    }
    assert _extract_rows(columns) == ((None, "a"), (None, "b"))


def test_extract_rows_no_values_anywhere_returns_empty():
    from dbxcarta_schemapile_example.candidate_selector import _extract_rows

    columns = {
        "id": {"TYPE": "INT"},
        "name": {"TYPE": "STRING"},
    }
    assert _extract_rows(columns) == ()


def test_select_candidates_keeps_schemas_with_fks():
    config = _config()
    slice_data = {
        "ecommerce.sql": _entry(
            {
                "customers": {
                    "columns": [
                        {"name": "id", "type": "INT"},
                        {"name": "name", "type": "VARCHAR(255)"},
                    ],
                    "pks": ["id"],
                    "fks": [],
                },
                "orders": {
                    "columns": [
                        {"name": "id", "type": "INT"},
                        {"name": "customer_id", "type": "INT"},
                    ],
                    "pks": ["id"],
                    "fks": [
                        {
                            "COLUMNS": ["customer_id"],
                            "FOREIGN_TABLE": "customers",
                            "REFERRED_COLUMNS": ["id"],
                        }
                    ],
                },
            }
        ),
        "no_fk.sql": _entry(
            {
                "a": {"columns": [{"name": "x", "type": "INT"}]},
                "b": {"columns": [{"name": "y", "type": "INT"}]},
            }
        ),
    }
    candidates = select_candidates(slice_data, config)
    assert len(candidates) == 1
    assert candidates[0].source_id == "ecommerce.sql"
    assert candidates[0].uc_schema.startswith("sp_")
    assert {t.name for t in candidates[0].tables} == {"customers", "orders"}
    # Column types must propagate from the slice cache's TYPE key. An empty
    # type here means the extraction key drifted and every column would fall
    # back to STRING at materialize.
    customers = next(t for t in candidates[0].tables if t.name == "customers")
    assert dict(customers.columns) == {"id": "INT", "name": "VARCHAR(255)"}


def test_select_candidates_drops_outside_size_window():
    big_tables: dict[str, dict[str, object]] = {
        f"t{i}": {"columns": [{"name": "id", "type": "INT"}], "fks": []} for i in range(50)
    }
    big_tables["t0"]["fks"] = [
        {
            "COLUMNS": ["id"],
            "FOREIGN_TABLE": "t1",
            "REFERRED_COLUMNS": ["id"],
        }
    ]
    slice_data = {"too_big.sql": _entry(big_tables)}
    cfg = _config()
    # candidate_max_tables defaults to 20 in our test config, so 50 should drop
    candidates = select_candidates(slice_data, cfg)
    assert candidates == []


def test_sanitize_schema_name_basic():
    used: set[str] = set()
    assert _sanitize_schema_name("ecommerce.sql", used=used) == "sp_ecommerce"
    used.add("sp_ecommerce")
    assert _sanitize_schema_name("ecommerce.sql", used=used) == "sp_ecommerce_2"


def test_sanitize_schema_name_leading_digit():
    used: set[str] = set()
    assert _sanitize_schema_name("321738_db.sql", used=used) == "sp_321738_db"


def test_sanitize_schema_name_punctuation():
    used: set[str] = set()
    assert _sanitize_schema_name("Some App-Name.sql", used=used) == "sp_some_app_name"
