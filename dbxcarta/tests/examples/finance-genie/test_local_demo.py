from __future__ import annotations

import json

import pytest
from dbxcarta_finance_genie_example import preset
from dbxcarta_finance_genie_example.local_demo import (
    DEFAULT_QUESTIONS,
    _ensure_read_only_sql,
    _print_context,
    _print_rows,
    _resolve_question,
    main,
)


def test_default_questions_points_at_the_bundled_example_root_file() -> None:
    # The bundled questions.json lives at the example root, the same place the
    # dbxcarta preset reads it from. Guard the default so moving the file can
    # never again leave the demo pointing at a path that does not exist.
    assert DEFAULT_QUESTIONS.is_file()
    assert preset.questions_file == DEFAULT_QUESTIONS


def test_ensure_read_only_sql_accepts_select_with_and_explain() -> None:
    _ensure_read_only_sql("SELECT 1")
    _ensure_read_only_sql("WITH x AS (SELECT 1) SELECT * FROM x")
    _ensure_read_only_sql("EXPLAIN SELECT 1")


def test_ensure_read_only_sql_rejects_mutation() -> None:
    with pytest.raises(ValueError, match="Only SELECT"):
        _ensure_read_only_sql("DELETE FROM table")


def test_ensure_read_only_sql_rejects_compound_statement() -> None:
    with pytest.raises(ValueError, match="Only one"):
        _ensure_read_only_sql("SELECT 1; DROP TABLE x")


def test_ensure_read_only_sql_rejects_explain_mutation() -> None:
    with pytest.raises(ValueError, match="Only SELECT"):
        _ensure_read_only_sql("EXPLAIN DELETE FROM table")


def test_resolve_question_uses_ad_hoc_text() -> None:
    row = _resolve_question("How many accounts?", None, "unused.json")

    assert row.question_id == "adhoc"
    assert row.question == "How many accounts?"


def test_resolve_question_finds_question_id(tmp_path) -> None:
    questions_path = tmp_path / "questions.json"
    questions_path.write_text(
        json.dumps(
            [
                {
                    "question_id": "q1",
                    "question": "How many accounts?",
                    "reference_sql": "SELECT COUNT(*) FROM accounts",
                }
            ]
        )
    )

    row = _resolve_question(None, "q1", str(questions_path))

    assert row.question == "How many accounts?"
    assert row.reference_sql == "SELECT COUNT(*) FROM accounts"


def test_questions_command_lists_questions(tmp_path, capsys) -> None:
    questions_path = tmp_path / "questions.json"
    questions_path.write_text(
        json.dumps(
            [
                {"question_id": "q1", "question": "How many accounts?"},
                {"question_id": "q2", "question": "Which merchants?"},
            ]
        )
    )

    code = main(["questions", "--questions", str(questions_path)])

    out = capsys.readouterr().out
    assert code == 0
    assert "q1\tHow many accounts?" in out
    assert "q2\tWhich merchants?" in out


def test_print_rows_limit_zero_without_columns(capsys) -> None:
    _print_rows([], [[1, "A"]], limit=0)

    out = capsys.readouterr().out
    assert "col_1" in out
    assert "... 1 more row(s)" in out


def test_print_context_explains_ids_and_prompt_context(capsys) -> None:
    _print_context(
        ["catalog.schema.table.column"],
        "Table: catalog.schema.table\n  column (STRING)",
    )

    out = capsys.readouterr().out
    assert "context_ids are vector-search seed nodes" in out
    assert "model receives the expanded retrieved_context" in out
    assert "catalog.schema.table.column" in out
    assert "Table: catalog.schema.table" in out
