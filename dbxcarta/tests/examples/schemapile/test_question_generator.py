from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from dbxcarta_schemapile_example.config import SchemaPileConfig
from dbxcarta_schemapile_example.question_generator import (
    _build_prompt,
    _first_message_text,
)


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


def test_build_prompt_uses_materialized_identifier_names():
    prompt = _build_prompt(
        {
            "uc_schema": "sp_shop",
            "source_id": "shop.sql",
            "tables": [
                {
                    "name": "Order Items",
                    "columns": [
                        {"name": "9th Id", "type": "INT"},
                        {"name": "Product Id", "type": "INT"},
                    ],
                    "primary_keys": ["9th Id"],
                    "foreign_keys": [
                        {
                            "columns": ["Product Id"],
                            "foreign_table": "Product-Catalog",
                            "referred_columns": ["Product Id"],
                        }
                    ],
                }
            ],
        },
        _config(),
    )
    assert "order_items(c_9th_id INT, product_id INT)" in prompt
    assert "PK(c_9th_id)" in prompt
    assert "product_id -> product_catalog(product_id)" in prompt
    assert "Order Items(" not in prompt


def test_first_message_text_accepts_plain_dict():
    response = {"choices": [{"message": {"content": "[{}]"}}]}
    assert _first_message_text(response) == "[{}]"


def test_first_message_text_accepts_sdk_shaped_object():
    @dataclass
    class Message:
        content: str

    @dataclass
    class Choice:
        message: Message

    @dataclass
    class Response:
        choices: list[Choice]

    assert _first_message_text(Response([Choice(Message("[{}]"))])) == "[{}]"
