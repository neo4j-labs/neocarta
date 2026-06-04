"""Client run-summary: stdout, JSON volume file, and Delta table."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING

from dbxcarta.core.identifiers import quote_qualified_name
from dbxcarta.core.volume_io import ensure_volume_subdirs

if TYPE_CHECKING:
    from pyspark.sql import SparkSession


@dataclass
class ArmResult:
    arm: str
    sql: str | None = None
    context_ids: list[str] = field(default_factory=list)
    parsed: bool = False
    executed: bool = False
    non_empty: bool = False
    correct: bool = False
    gradable: bool = False
    error: str | None = None
    # Only set for the graph_rag arm.
    top1_schema_match: bool | None = None
    schema_in_context: bool | None = None
    context_purity: float | None = None


@dataclass
class QuestionResult:
    question_id: str
    question: str
    arm_results: list[ArmResult] = field(default_factory=list)


@dataclass
class ClientRunSummary:
    run_id: str
    job_name: str
    catalog: str
    schemas: list[str]
    arms: list[str]
    started_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    ended_at: datetime | None = None
    status: str = "running"
    error: str | None = None
    question_results: list[QuestionResult] = field(default_factory=list)

    # Per-arm aggregates — populated by finish()
    arm_attempted: dict[str, int] = field(default_factory=dict)
    arm_parsed: dict[str, int] = field(default_factory=dict)
    arm_executed: dict[str, int] = field(default_factory=dict)
    arm_non_empty: dict[str, int] = field(default_factory=dict)
    arm_correct: dict[str, int] = field(default_factory=dict)
    arm_gradable: dict[str, int] = field(default_factory=dict)
    arm_parse_rate: dict[str, float] = field(default_factory=dict)
    arm_execution_rate: dict[str, float] = field(default_factory=dict)
    arm_non_empty_rate: dict[str, float] = field(default_factory=dict)
    arm_correct_rate: dict[str, float] = field(default_factory=dict)
    # Only populated for the graph_rag arm.
    arm_top1_schema_match_rate: dict[str, float] = field(default_factory=dict)
    arm_schema_in_context_rate: dict[str, float] = field(default_factory=dict)
    arm_mean_context_purity: dict[str, float] = field(default_factory=dict)

    def add_result(
        self,
        question_id: str,
        question: str,
        arm: str,
        *,
        sql: str | None = None,
        context_ids: list[str] | None = None,
        parsed: bool = False,
        executed: bool = False,
        non_empty: bool = False,
        correct: bool = False,
        gradable: bool = False,
        error: str | None = None,
        top1_schema_match: bool | None = None,
        schema_in_context: bool | None = None,
        context_purity: float | None = None,
    ) -> None:
        result = ArmResult(
            arm=arm,
            sql=sql,
            context_ids=context_ids or [],
            parsed=parsed,
            executed=executed,
            non_empty=non_empty,
            correct=correct,
            gradable=gradable,
            error=error,
            top1_schema_match=top1_schema_match,
            schema_in_context=schema_in_context,
            context_purity=context_purity,
        )
        for qr in self.question_results:
            if qr.question_id == question_id:
                qr.arm_results.append(result)
                return
        self.question_results.append(
            QuestionResult(
                question_id=question_id,
                question=question,
                arm_results=[result],
            )
        )

    def _compute_aggregates(self) -> None:
        counts: dict[str, dict[str, int]] = {}
        retrieval: dict[str, dict[str, list]] = {}
        for qr in self.question_results:
            for ar in qr.arm_results:
                if ar.arm not in counts:
                    counts[ar.arm] = {
                        "attempted": 0,
                        "parsed": 0,
                        "executed": 0,
                        "non_empty": 0,
                        "correct": 0,
                        "gradable": 0,
                    }
                    retrieval[ar.arm] = {"top1": [], "recall": [], "purity": []}
                counts[ar.arm]["attempted"] += 1
                if ar.parsed:
                    counts[ar.arm]["parsed"] += 1
                if ar.executed:
                    counts[ar.arm]["executed"] += 1
                if ar.non_empty:
                    counts[ar.arm]["non_empty"] += 1
                if ar.correct:
                    counts[ar.arm]["correct"] += 1
                if ar.gradable:
                    counts[ar.arm]["gradable"] += 1
                if ar.top1_schema_match is not None:
                    retrieval[ar.arm]["top1"].append(ar.top1_schema_match)
                if ar.schema_in_context is not None:
                    retrieval[ar.arm]["recall"].append(ar.schema_in_context)
                if ar.context_purity is not None:
                    retrieval[ar.arm]["purity"].append(ar.context_purity)
        for arm, c in counts.items():
            self.arm_attempted[arm] = c["attempted"]
            self.arm_parsed[arm] = c["parsed"]
            self.arm_executed[arm] = c["executed"]
            self.arm_non_empty[arm] = c["non_empty"]
            self.arm_correct[arm] = c["correct"]
            self.arm_gradable[arm] = c["gradable"]
            attempted = c["attempted"] or 1
            self.arm_parse_rate[arm] = round(c["parsed"] / attempted, 3)
            self.arm_execution_rate[arm] = round(c["executed"] / attempted, 3)
            self.arm_non_empty_rate[arm] = round(c["non_empty"] / attempted, 3)
            if c["gradable"] > 0:
                self.arm_correct_rate[arm] = round(c["correct"] / c["gradable"], 3)
            rv = retrieval[arm]
            if rv["top1"]:
                self.arm_top1_schema_match_rate[arm] = round(sum(rv["top1"]) / len(rv["top1"]), 3)
            if rv["recall"]:
                self.arm_schema_in_context_rate[arm] = round(
                    sum(rv["recall"]) / len(rv["recall"]), 3
                )
            if rv["purity"]:
                self.arm_mean_context_purity[arm] = round(sum(rv["purity"]) / len(rv["purity"]), 3)

    def finish(self, *, status: str, error: str | None = None) -> None:
        self.status = status
        self.error = error
        self.ended_at = datetime.now(UTC)
        self._compute_aggregates()

    def _to_delta_dict(self) -> dict:
        return {
            "run_id": self.run_id,
            "job_name": self.job_name,
            "catalog": self.catalog,
            "schemas": self.schemas,
            "arms": self.arms,
            "started_at": self.started_at,
            "ended_at": self.ended_at,
            "status": self.status,
            "error": self.error,
            "arm_attempted": self.arm_attempted,
            "arm_parsed": self.arm_parsed,
            "arm_executed": self.arm_executed,
            "arm_non_empty": self.arm_non_empty,
            "arm_correct": self.arm_correct,
            "arm_gradable": self.arm_gradable,
            "arm_parse_rate": self.arm_parse_rate,
            "arm_execution_rate": self.arm_execution_rate,
            "arm_non_empty_rate": self.arm_non_empty_rate,
            "arm_correct_rate": self.arm_correct_rate,
            "arm_top1_schema_match_rate": self.arm_top1_schema_match_rate,
            "arm_schema_in_context_rate": self.arm_schema_in_context_rate,
            "arm_mean_context_purity": self.arm_mean_context_purity,
        }

    def _to_json_dict(self) -> dict:
        d = self._to_delta_dict()
        d["started_at"] = self.started_at.isoformat()
        d["ended_at"] = self.ended_at.isoformat() if self.ended_at else None
        d["question_results"] = [asdict(qr) for qr in self.question_results]
        return d

    def emit_stdout(self) -> None:
        print(
            f"[dbxcarta_client] run_id={self.run_id} job={self.job_name} "
            f"status={self.status} catalog={self.catalog}"
        )
        for arm in self.arms:
            attempted = self.arm_attempted.get(arm, 0)
            parsed = self.arm_parsed.get(arm, 0)
            executed = self.arm_executed.get(arm, 0)
            non_empty = self.arm_non_empty.get(arm, 0)
            exec_rate = self.arm_execution_rate.get(arm, 0.0)
            non_empty_rate = self.arm_non_empty_rate.get(arm, 0.0)
            correct_rate = self.arm_correct_rate.get(arm, 0.0)
            print(
                f"  {arm}: attempted={attempted} parsed={parsed} "
                f"executed={executed} non_empty={non_empty} "
                f"exec_rate={exec_rate:.1%} non_empty_rate={non_empty_rate:.1%} "
                f"correct_rate={correct_rate:.1%}"
            )
            top1 = self.arm_top1_schema_match_rate.get(arm)
            recall = self.arm_schema_in_context_rate.get(arm)
            purity = self.arm_mean_context_purity.get(arm)
            if top1 is not None and recall is not None and purity is not None:
                print(
                    f"    retrieval: top1_schema_match={top1:.1%} "
                    f"schema_in_context={recall:.1%} "
                    f"context_purity={purity:.1%}"
                )
        if self.error:
            print(f"  error: {self.error}")

    def emit_json(self, volume_path: str) -> None:
        ts = (self.ended_at or self.started_at).strftime("%Y%m%dT%H%M%SZ")
        path = Path(volume_path) / f"{self.job_name}_{self.run_id}_{ts}.json"
        ensure_volume_subdirs(path.parent)
        path.write_text(json.dumps(self._to_json_dict(), indent=2))

    def emit_delta(self, spark: SparkSession, table_name: str) -> None:
        from pyspark.sql import Row
        from pyspark.sql.types import (
            ArrayType,
            DoubleType,
            LongType,
            MapType,
            StringType,
            StructField,
            StructType,
            TimestampType,
        )

        schema = StructType(
            [
                StructField("run_id", StringType(), nullable=False),
                StructField("job_name", StringType()),
                StructField("catalog", StringType()),
                StructField("schemas", ArrayType(StringType())),
                StructField("arms", ArrayType(StringType())),
                StructField("started_at", TimestampType()),
                StructField("ended_at", TimestampType()),
                StructField("status", StringType()),
                StructField("error", StringType()),
                StructField("arm_attempted", MapType(StringType(), LongType())),
                StructField("arm_parsed", MapType(StringType(), LongType())),
                StructField("arm_executed", MapType(StringType(), LongType())),
                StructField("arm_non_empty", MapType(StringType(), LongType())),
                StructField("arm_correct", MapType(StringType(), LongType())),
                StructField("arm_gradable", MapType(StringType(), LongType())),
                StructField("arm_parse_rate", MapType(StringType(), DoubleType())),
                StructField("arm_execution_rate", MapType(StringType(), DoubleType())),
                StructField("arm_non_empty_rate", MapType(StringType(), DoubleType())),
                StructField("arm_correct_rate", MapType(StringType(), DoubleType())),
                StructField("arm_top1_schema_match_rate", MapType(StringType(), DoubleType())),
                StructField("arm_schema_in_context_rate", MapType(StringType(), DoubleType())),
                StructField("arm_mean_context_purity", MapType(StringType(), DoubleType())),
            ]
        )
        quoted = quote_qualified_name(table_name, expected_parts=3)
        row = Row(**self._to_delta_dict())
        (
            spark.createDataFrame([row], schema=schema)
            .write.format("delta")
            .mode("append")
            .option("mergeSchema", "true")
            .saveAsTable(quoted)
        )

    def emit(self, spark: SparkSession, volume_path: str, table_name: str) -> None:
        self.emit_stdout()
        self.emit_json(volume_path)
        self.emit_delta(spark, table_name)
