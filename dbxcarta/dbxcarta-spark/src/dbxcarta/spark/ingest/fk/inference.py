"""Spark-native metadata FK inference.

Single source of truth for the metadata inferred FK strategy. Everything
runs in Spark DataFrames: no catalog-scale collect to the driver, no Python
all-pairs loop, no UDF. Python builds the plan once; Spark evaluates every
row.

The static rule tables (`_SCORE_TABLE`, `_STEM_SUFFIXES`, `_STOPWORDS`,
`_TYPE_EQUIV`) stay defined in `metadata`/`common` and are imported here so
there is one definition of each rule; this module only expands them into
native `Column` expressions and broadcast-join lookups at plan-construction
time (best-practices Spark §7).

The strategy uses:
  - `build_columns_frame` — the per-column working frame with `col_id`,
    `table_key`, canonicalized type token, and comment-token array.
  - `build_pk_gate` — the PK-like target classification (`pk_evidence`),
    reproducing `common.pk_kind` and `PKIndex.from_constraints` as Spark
    aggregations and joins.
  - `canonicalize_expr` — the native port of `common.canonicalize`.

Production counters are deliberately minimal: only `accepted` (the
load-bearing written-edge count) and `composite_pk_skipped` (the cheap
`build_pk_gate` constraints aggregation) are computed on the hot path. The
former per-strategy `candidates` / `rejected` / `value_corroborated`
counters were removed because each forced an extra Spark action over the
n²-shaped graph; pre-filter effectiveness and value corroboration are now
validated in the `fk_guard` regression test, not on every production run.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

import dbxcarta.spark.ingest.schema_graph as sg
from dbxcarta.spark.contract import EdgeSource
from dbxcarta.spark.ingest.contract_expr import id_expr_from_columns
from dbxcarta.spark.ingest.fk.common import _TYPE_EQUIV
from dbxcarta.spark.ingest.fk.metadata import (
    _SCORE_TABLE,
    _STEM_SUFFIXES,
    _STOPWORDS,
    NameMatchKind,
)

if TYPE_CHECKING:
    from pyspark.sql import Column, DataFrame, SparkSession


# Inference frames are projected onto the canonical REFERENCES schema via
# schema_graph.to_references_rel at each strategy's exit — the schema contract
# lives once in schema_graph, not duplicated here.


@dataclass
class CoarseFKCounts:
    """The two production-path counts for one inferred strategy.

    `accepted` is the post-attenuation, post-anti-join written edge count —
    it is load-bearing because materializing it also materializes the frame
    written to Neo4j. `composite_pk_skipped` is the multi-column-PK
    observation from `build_pk_gate`'s small constraints aggregation, which
    already runs regardless of this field.

    The former `candidates` / `rejected` / `value_corroborated` counters were
    intentionally removed: each was a separate Spark action over the
    n²-shaped graph and nothing in-repo consumes them. Do not reinstate them
    on this path — pre-filter effectiveness and value corroboration are
    validated in the `fk_guard` regression test instead.
    """

    accepted: int = 0
    composite_pk_skipped: int = 0

    def as_summary_dict(self, prefix: str) -> dict[str, int]:
        return {
            f"{prefix}_accepted": self.accepted,
            f"{prefix}_composite_pk_skipped": self.composite_pk_skipped,
        }


# --- Shared expressions -----------------------------------------------------


def canonicalize_expr(data_type: Column) -> Column:
    """Native port of `common.canonicalize`, returning one comparable token.

    `canonicalize` reduces a declared type to `(family, detail)` where detail
    is the DECIMAL scale and None otherwise. Two types are compatible iff the
    tuples are equal. This expression folds the tuple into a single string so
    equality of the derived columns is exactly `types_compatible`:

      - STRING/VARCHAR/CHAR(n)        -> "STRING"
      - DECIMAL|NUMERIC(p[,s])        -> "DECIMAL|<s or 0>"
      - _TYPE_EQUIV integer family    -> "INTEGER"
      - anything else                 -> the upper/trimmed type verbatim

    Order matches `canonicalize`: string check, then decimal, then the
    integer-family map. `_TYPE_EQUIV` is inlined as a chained `when`; it is
    small enough that a broadcast map is unnecessary.
    """
    from pyspark.sql import functions as F

    tt = F.upper(F.trim(data_type))

    # Java regex (Spark rlike/regexp_extract). Mirrors common._STRING_PARAM_RE
    # and common._DECIMAL_RE.
    string_re = r"^(STRING|VARCHAR|CHAR)(\([0-9]+\))?$"
    decimal_re = r"^(DECIMAL|NUMERIC)\(([0-9]+)(,([0-9]+))?\)$"
    # Group 4 is the optional scale; "" when absent -> "0", matching the
    # Python `m.group(2) if ... else "0"`.
    decimal_scale = F.regexp_extract(tt, decimal_re, 4)

    equiv = None
    for raw, fam in _TYPE_EQUIV.items():
        cond = tt == F.lit(raw)
        equiv = F.when(cond, F.lit(fam)) if equiv is None else equiv.when(cond, F.lit(fam))
    if equiv is None:  # _TYPE_EQUIV is non-empty; guards type narrowing below
        raise ValueError("_TYPE_EQUIV must define at least one type-equivalence mapping")

    return (
        F.when(tt.rlike(string_re), F.lit("STRING"))
        .when(
            tt.rlike(decimal_re),
            F.concat(
                F.lit("DECIMAL|"),
                F.when(decimal_scale == F.lit(""), F.lit("0")).otherwise(decimal_scale),
            ),
        )
        .otherwise(equiv.otherwise(tt))
    )


def _comment_tokens_expr(comment: Column) -> Column:
    """Native port of `metadata._comment_tokens`.

    split(lower(comment)) on the non-alphanumeric class, keep tokens with
    length >= 4 that are not stopwords. Null/blank comment -> empty array.
    """
    from pyspark.sql import functions as F

    toks = F.split(F.lower(F.coalesce(comment, F.lit(""))), r"[^a-zA-Z0-9]+")
    stop = F.array(*[F.lit(w) for w in sorted(_STOPWORDS)])
    return F.filter(
        toks,
        lambda t: (F.length(t) >= F.lit(4)) & ~F.array_contains(stop, t),
    )


def build_columns_frame(
    columns_df: DataFrame,
) -> DataFrame:
    """Per-column working frame for metadata FK inference.

    `columns_df` is the cached information_schema.columns snapshot
    (table_catalog/table_schema/table_name/column_name/data_type/comment).
    """
    from pyspark.sql import functions as F

    return (
        columns_df.select(
            F.col("table_catalog").alias("catalog"),
            F.col("table_schema").alias("schema"),
            F.col("table_name").alias("table"),
            F.col("column_name").alias("column"),
            F.col("data_type").alias("data_type"),
            F.col("comment").alias("comment"),
        )
        .withColumn(
            "table_key",
            id_expr_from_columns(F.col("catalog"), F.col("schema"), F.col("table")),
        )
        .withColumn(
            "col_id",
            id_expr_from_columns(
                F.col("catalog"),
                F.col("schema"),
                F.col("table"),
                F.col("column"),
            ),
        )
        .withColumn("canon", canonicalize_expr(F.col("data_type")))
        .withColumn("ctok", _comment_tokens_expr(F.col("comment")))
    )


def build_pk_gate(
    columns_frame: DataFrame,
    constraints_df: DataFrame,
) -> tuple[DataFrame, int]:
    """Classify every column's PK-likeness as a Spark frame.

    Reproduces `PKIndex.from_constraints` + `common.pk_kind` without a
    collect. Returns `(pk_gate, composite_pk_count)` where `pk_gate` has
    `col_id` and a non-null `pk_evidence` ("declared_pk" | "unique_or_heur")
    for every PK-like target; non-PK-like columns are absent from the frame.

    `constraints_df` columns: table_catalog, table_schema, table_name,
    column_name, constraint_type, ordinal_position, constraint_name.
    """
    from pyspark.sql import functions as F

    c = constraints_df.select(
        F.col("table_catalog").alias("catalog"),
        F.col("table_schema").alias("schema"),
        F.col("table_name").alias("table"),
        F.col("column_name").alias("column"),
        F.col("constraint_type").alias("ctype"),
        F.col("ordinal_position").alias("ord"),
        F.col("constraint_name").alias("cname"),
    ).withColumn(
        "table_key",
        id_expr_from_columns(F.col("catalog"), F.col("schema"), F.col("table")),
    )

    # PRIMARY KEY constraints grouped by (catalog, schema, constraint_name);
    # single-column PKs feed the declared-PK set, multi-column PKs are counted
    # only (PKIndex.composite_pk_count).
    pk = c.filter(F.col("ctype") == "PRIMARY KEY")
    pk_grouped = pk.groupBy("catalog", "schema", "cname").agg(
        F.first("table_key").alias("table_key"),
        F.first("column").alias("column"),
        F.count(F.lit(1)).alias("ncols"),
    )
    pk_single = (
        pk_grouped.filter(F.col("ncols") == 1)
        .select("table_key", "column")
        .withColumn("is_pk", F.lit(True))
    )
    composite_pk_count = pk_grouped.filter(F.col("ncols") > 1).count()

    # UNIQUE constraints keep the leftmost (ordinal_position == 1) column.
    uniq_lm = (
        c.filter((F.col("ctype") == "UNIQUE") & (F.col("ord") == 1))
        .select("table_key", "column")
        .distinct()
        .withColumn("is_uq", F.lit(True))
    )

    # Count of `_id`-suffixed columns per table for the `{table}_id` heuristic.
    id_cnt = (
        columns_frame.filter(F.lower(F.col("column")).endswith("_id"))
        .groupBy("table_key")
        .agg(F.count(F.lit(1)).alias("id_cnt"))
    )

    base = columns_frame.select("col_id", "table_key", "table", "column")
    joined = (
        base.join(pk_single, ["table_key", "column"], "left")
        .join(uniq_lm, ["table_key", "column"], "left")
        .join(id_cnt, ["table_key"], "left")
    )

    col_l = F.lower(F.col("column"))
    table_id = F.concat(F.lower(F.col("table")), F.lit("_id"))
    pk_evidence = (
        F.when(F.col("is_pk").isNotNull(), F.lit("declared_pk"))
        .when(F.col("is_uq").isNotNull(), F.lit("unique_or_heur"))
        .when(col_l == F.lit("id"), F.lit("unique_or_heur"))
        .when(
            (col_l == table_id) & (F.coalesce(F.col("id_cnt"), F.lit(0)) == 1),
            F.lit("unique_or_heur"),
        )
        .otherwise(F.lit(None))
    )
    pk_gate = (
        joined.withColumn("pk_evidence", pk_evidence)
        .filter(F.col("pk_evidence").isNotNull())
        .select("col_id", "pk_evidence")
    )
    return pk_gate, composite_pk_count


def _score_table_df(spark: SparkSession) -> DataFrame:
    """Materialize `_SCORE_TABLE` as a tiny broadcastable lookup DataFrame."""
    rows = [
        (kind.value, pk_ev.value, comment_present, score)
        for (kind, pk_ev, comment_present), score in _SCORE_TABLE.items()
    ]
    return spark.createDataFrame(
        rows,
        schema=["name_kind", "pk_evidence", "comment_present", "score"],
    )


def _select_as(df: DataFrame, mapping: dict[str, str]) -> DataFrame:
    """Project `df` to exactly `mapping`'s columns, renaming each old → new.

    One declarative spec for the self-join projections below. Keeping the
    rename map as data (not a hand-written `.alias()` list duplicated per
    call site) removes the duplicated magic strings and the asymmetry traps:
    the source side keeps `lk`/`kind` bare while the target side prefixes
    them, and `col_id` becomes `source_id`/`target_id` rather than a blind
    prefix — a uniform "prefix every column" helper would silently break the
    join. `mapping` is insertion-ordered so column order is preserved, and
    `F.col` accepts nested refs so struct fields like `_k.lk` are valid keys.
    """
    from pyspark.sql import functions as F

    return df.select([F.col(old).alias(new) for old, new in mapping.items()])


# --- Metadata strategy ------------------------------------------------------


def infer_metadata_edges(
    spark: SparkSession,
    columns_frame: DataFrame,
    pk_gate: DataFrame,
    declared_edges_df: DataFrame | None,
    *,
    composite_pk_count: int = 0,
    threshold: float = 0.8,
) -> tuple[DataFrame, CoarseFKCounts, int]:
    """Spark-native metadata FK inference.

    Returns `(edges_df, counts, composite_pk_skipped)` where `edges_df` has
    the canonical REFERENCES columns. `declared_edges_df` is the
    declared-only prior-pair frame (anti-joined last, mirroring Python where
    metadata receives declared edges only). `composite_pk_count` is the
    `build_pk_gate` composite-PK observation, threaded through into the
    coarse counts.
    """
    from pyspark.sql import functions as F
    from pyspark.sql.window import Window

    cf = columns_frame

    # link_key carries the branch in its prefix ("E|" exact, "S|" suffix) so
    # an exact key can never join a suffix key and the matched NameMatchKind
    # is unambiguous. The static suffix loop is unrolled in Python here.
    col_l = F.lower(cf["column"])
    tbl_l = F.lower(cf["table"])

    src_keys = [
        F.struct(
            F.concat(F.lit("E|"), col_l).alias("lk"), F.lit(NameMatchKind.EXACT.value).alias("kind")
        )
    ]
    for suf in _STEM_SUFFIXES:
        applies = col_l.endswith(suf) & (F.length(col_l) > F.lit(len(suf)))
        stem = F.expr(f"substring(lower(column), 1, length(lower(column)) - {len(suf)})")
        src_keys.append(
            F.when(
                applies,
                F.struct(
                    F.concat(F.lit("S|"), stem).alias("lk"),
                    F.lit(NameMatchKind.SUFFIX.value).alias("kind"),
                ),
            )
        )
    src = _select_as(
        cf.withColumn("_k", F.explode(F.array_compact(F.array(*src_keys)))),
        {
            "catalog": "s_catalog",
            "schema": "s_schema",
            "column": "s_column",
            "col_id": "source_id",
            "canon": "s_canon",
            "ctok": "s_ctok",
            "_k.lk": "lk",
            "_k.kind": "kind",
        },
    )

    # tgt exact key for any column; suffix keys (singular + plural-stripped
    # table forms) only when the column is literally `id`, matching
    # _stem_matches_table (t == s | s+'s' | s+'es').
    is_id = col_l == F.lit("id")
    tgt_keys = [
        F.struct(
            F.concat(F.lit("E|"), col_l).alias("lk"), F.lit(NameMatchKind.EXACT.value).alias("kind")
        )
    ]
    tgt_keys.append(
        F.when(
            is_id,
            F.struct(
                F.concat(F.lit("S|"), tbl_l).alias("lk"),
                F.lit(NameMatchKind.SUFFIX.value).alias("kind"),
            ),
        )
    )
    tgt_keys.append(
        F.when(
            is_id & tbl_l.endswith("s"),
            F.struct(
                F.concat(
                    F.lit("S|"), F.expr("substring(lower(table), 1, length(lower(table)) - 1)")
                ).alias("lk"),
                F.lit(NameMatchKind.SUFFIX.value).alias("kind"),
            ),
        )
    )
    tgt_keys.append(
        F.when(
            is_id & tbl_l.endswith("es"),
            F.struct(
                F.concat(
                    F.lit("S|"), F.expr("substring(lower(table), 1, length(lower(table)) - 2)")
                ).alias("lk"),
                F.lit(NameMatchKind.SUFFIX.value).alias("kind"),
            ),
        )
    )
    tgt = _select_as(
        cf.withColumn("_k", F.explode(F.array_compact(F.array(*tgt_keys)))),
        {
            "catalog": "t_catalog",
            "schema": "t_schema",
            "column": "t_column",
            "col_id": "target_id",
            "canon": "t_canon",
            "ctok": "t_ctok",
            "_k.lk": "t_lk",
            "_k.kind": "t_kind",
        },
    )

    # The id↔id term below is a scale prune, NOT a correctness gate: it keeps
    # an id-count x id-count cartesian out of the join/window/dedup. Do not
    # "simplify" it away — attenuation would also suppress generic id→id
    # fanout, and a genuine shared-PK FK is declared and caught by the
    # declared path, so dropping it only adds a large useless intermediate to
    # the heaviest region of the pipeline for zero correctness gain.
    matched = src.join(
        tgt,
        (F.col("s_catalog") == F.col("t_catalog"))
        & (F.col("s_schema") == F.col("t_schema"))
        & (F.col("lk") == F.col("t_lk"))
        & (F.col("kind") == F.col("t_kind"))
        & (F.col("source_id") != F.col("target_id"))
        & ~(
            (F.lower(F.col("s_column")) == F.lit("id"))
            & (F.lower(F.col("t_column")) == F.lit("id"))
        ),
        "inner",
    )

    # One row per (source_id, target_id): a pair can match on several keys
    # (exact + a stem, or several tgt table-forms). EXACT outranks SUFFIX.
    kind_rank = F.when(F.col("kind") == NameMatchKind.EXACT.value, F.lit(0)).otherwise(F.lit(1))
    dedup_w = Window.partitionBy("source_id", "target_id").orderBy(kind_rank.asc())
    deduped = (
        matched.withColumn("_rn", F.row_number().over(dedup_w))
        .filter(F.col("_rn") == 1)
        .drop("_rn")
    )

    # Type compatibility: canonicalized-token equality (no broadcast join).
    typed = deduped.filter(F.col("s_canon") == F.col("t_canon"))

    # PK-like target gate.
    gated = typed.join(
        pk_gate.select(F.col("col_id").alias("_pk_id"), F.col("pk_evidence")),
        F.col("target_id") == F.col("_pk_id"),
        "inner",
    ).drop("_pk_id")

    # Comment-token overlap, then the broadcast _SCORE_TABLE lookup.
    scored_in = gated.withColumn(
        "comment_present",
        F.size(F.array_intersect(F.col("s_ctok"), F.col("t_ctok"))) > 0,
    ).withColumn("name_kind", F.col("kind"))
    score_df = F.broadcast(_score_table_df(spark))
    scored = scored_in.join(
        score_df,
        ["name_kind", "pk_evidence", "comment_present"],
        "inner",
    )

    # Window set = post name-dedup, type, PK, and score>=threshold. cnt over
    # source_id reproduces Python's per_source candidate count.
    above = scored.filter(F.col("score") >= F.lit(threshold))
    att_w = Window.partitionBy("source_id")
    attenuated = (
        above.withColumn("_cnt", F.count(F.lit(1)).over(att_w))
        .withColumn(
            "_att",
            F.col("score") / F.greatest(F.lit(1.0), F.sqrt(F.col("_cnt") - F.lit(1))),
        )
        .filter(F.col("_att") >= F.lit(threshold))
    )

    edges = attenuated.select(
        F.col("source_id"),
        F.col("target_id"),
        F.round(F.col("_att"), 4).alias("confidence"),
        F.lit(EdgeSource.INFERRED_METADATA.value).alias("source"),
        F.lit(None).cast("string").alias("criteria"),
    )

    if declared_edges_df is not None:
        prior = declared_edges_df.select(
            F.col("source_id").alias("_p_s"),
            F.col("target_id").alias("_p_t"),
        )
        edges = edges.join(
            prior,
            (F.col("source_id") == F.col("_p_s")) & (F.col("target_id") == F.col("_p_t")),
            "left_anti",
        )

    edges = sg.to_references_rel(edges)
    accepted = edges.cache().count()
    if accepted == 0:
        edges.unpersist()
    counts = CoarseFKCounts(
        accepted=accepted,
        composite_pk_skipped=composite_pk_count,
    )
    return edges, counts, composite_pk_count
