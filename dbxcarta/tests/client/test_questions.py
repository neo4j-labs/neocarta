"""Unit tests for client question loading and upload shape."""

from __future__ import annotations

import json

from dbxcarta.client.questions import Question, load_questions


def test_question_validates_schema_alias_and_blank_optionals() -> None:
    q = Question.model_validate(
        {
            "question_id": " q1 ",
            "question": " who? ",
            "reference_sql": " ",
            "schema": "s1",
        }
    )

    assert q.question_id == "q1"
    assert q.question == "who?"
    assert q.reference_sql is None
    assert q.schema_ == "s1"
    assert q["schema"] == "s1"


def test_load_questions_from_json_preserves_schema(tmp_path) -> None:
    path = tmp_path / "questions.json"
    path.write_text(
        json.dumps(
            [
                {
                    "question_id": "q1",
                    "question": "Who?",
                    "reference_sql": "SELECT 1",
                    "schema": "target_schema",
                }
            ]
        )
    )

    questions = load_questions(str(path))

    assert len(questions) == 1
    assert questions[0].schema_ == "target_schema"
