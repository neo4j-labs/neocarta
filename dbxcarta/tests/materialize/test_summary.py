from __future__ import annotations

import json
from typing import TYPE_CHECKING

from dbxcarta.core.materialize import MaterializeStats
from dbxcarta.materialize.summary import JOB_NAME, MaterializeRunSummary

if TYPE_CHECKING:
    from pathlib import Path


def _summary() -> MaterializeRunSummary:
    return MaterializeRunSummary(
        run_id="r1",
        job_name=JOB_NAME,
        catalog="cat",
        schemas=["shop"],
    )


def test_apply_stats_records_tally() -> None:
    s = _summary()
    s.apply_stats(
        MaterializeStats(
            schemas_created=1,
            tables_created=3,
            rows_inserted=9,
            tables_skipped=1,
            type_fallbacks=2,
            pk_constraints_added=3,
            fk_constraints_added=2,
        )
    )
    assert s.stats.tables_created == 3
    assert s.stats.rows_inserted == 9
    assert s.stats.tables_skipped == 1
    assert s.stats.type_fallbacks == 2
    assert s.stats.pk_constraints_added == 3
    assert s.stats.fk_constraints_added == 2


def test_finish_stamps_status_and_end() -> None:
    s = _summary()
    assert s.status == "running"
    assert s.ended_at is None
    s.finish(status="success")
    assert s.status == "success"
    assert s.ended_at is not None


def test_delta_dict_carries_identity_and_counts() -> None:
    s = _summary()
    s.apply_stats(MaterializeStats(tables_created=2))
    s.finish(status="success")
    d = s._to_delta_dict()
    assert d["run_id"] == "r1"
    assert d["job_name"] == JOB_NAME
    assert d["catalog"] == "cat"
    assert d["schemas"] == ["shop"]
    assert d["status"] == "success"
    assert d["tables_created"] == 2


def test_json_dict_uses_iso_timestamps() -> None:
    s = _summary()
    s.finish(status="failure", error="boom")
    d = s._to_json_dict()
    assert isinstance(d["started_at"], str)
    assert isinstance(d["ended_at"], str)
    assert d["error"] == "boom"


def test_emit_json_writes_prefixed_file(tmp_path: Path) -> None:
    s = _summary()
    s.finish(status="success")
    s.emit_json(str(tmp_path))
    files = list(tmp_path.glob(f"{JOB_NAME}_r1_*.json"))
    assert len(files) == 1
    payload = json.loads(files[0].read_text())
    assert payload["run_id"] == "r1"
    assert payload["job_name"] == JOB_NAME
