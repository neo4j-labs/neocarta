"""Question input models and loaders for client evaluation runs."""

from __future__ import annotations

import json
from pathlib import Path
from typing import TYPE_CHECKING, Any

from pydantic import BaseModel, ConfigDict, Field, field_validator

if TYPE_CHECKING:
    from pyspark.sql import SparkSession


class Question(BaseModel):
    """Validated client question loaded from JSON or a Delta table."""

    question_id: str
    question: str
    notes: str | None = None
    reference_sql: str | None = None
    schema_: str | None = Field(default=None, alias="schema")

    model_config = ConfigDict(extra="ignore", populate_by_name=True)

    @field_validator("question_id", "question")
    @classmethod
    def _require_non_empty(cls, value: str) -> str:
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("must be non-empty")
        return cleaned

    @field_validator("notes", "reference_sql", "schema_", mode="before")
    @classmethod
    def _blank_to_none(cls, value: Any) -> Any:
        if isinstance(value, str) and not value.strip():
            return None
        return value

    def get(self, key: str, default: Any = None) -> Any:
        """Dict-style compatibility for older demo helpers."""
        if key == "schema":
            return self.schema_
        return getattr(self, key, default)

    def __getitem__(self, key: str) -> Any:
        sentinel = object()
        value = self.get(key, sentinel)
        if value is sentinel:
            raise KeyError(key)
        return value


def is_table_ref(source: str) -> bool:
    """Return True when source looks like a three-part catalog.schema.table name."""
    return len(source.split(".")) == 3 and not source.startswith(("/", "."))


def load_questions(source: str, spark: SparkSession | None = None) -> list[Question]:
    """Load and validate client questions from a Delta table or JSON file."""
    if is_table_ref(source):
        if spark is None:
            raise RuntimeError("spark is required to load questions from a Delta table")
        raw_questions = [row.asDict() for row in spark.table(source).collect()]
    else:
        text = Path(source).read_text()
        raw_questions = json.loads(text)

    if not isinstance(raw_questions, list):
        # ValueError is the deliberate, uniform error contract for an invalid
        # questions file (not a programmer type error).
        raise ValueError(  # noqa: TRY004
            f"questions file must be a JSON array, got {type(raw_questions)}"
        )
    return [Question.model_validate(item) for item in raw_questions]
