"""GraphRetriever: Neo4j vector seed + structural walk for graph_rag arm."""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

try:
    from neo4j import GraphDatabase
except ModuleNotFoundError as exc:  # pragma: no cover - dependency guard
    raise ModuleNotFoundError(
        "dbxcarta-client graph retrieval requires Neo4j. Install the client "
        "package with the 'graph' extra: pip install 'dbxcarta-client[graph]'"
    ) from exc

from dbxcarta.client.ids import schema_from_node_id
from dbxcarta.client.neo4j_utils import neo4j_credentials
from dbxcarta.client.retriever import ColumnEntry, ContextBundle, JoinLine, Retriever

if TYPE_CHECKING:
    from dbxcarta.client.settings import ClientSettings
    from neo4j import Session

_COL_INDEX = "column_embedding"
_TABLE_INDEX = "table_embedding"

_STOP_WORDS = frozenset(
    {
        "a",
        "an",
        "the",
        "in",
        "on",
        "of",
        "by",
        "to",
        "for",
        "from",
        "and",
        "or",
        "is",
        "are",
        "that",
        "this",
        "with",
        "what",
        "how",
        "where",
        "which",
        "all",
        "each",
        "many",
        "have",
        "has",
        "out",
        "who",
        "show",
        "list",
        "get",
        "find",
        "do",
        "did",
        "does",
        "per",
        "avg",
        "sum",
        "any",
        "its",
        "be",
        "been",
    }
)
_MAX_VALUES_PER_COLUMN = 20
_MAX_VALUE_CHARS = 80
_MAX_VALUES_TOTAL = 2000

# OPTIONAL MATCH so deployments with no REFERENCES edges don't trigger
# Neo4j's 01N51 UnknownRelationshipTypeWarning. Exported as a constant so
# the regression guard can import it.
#
# `r` is bound so we can filter on confidence. Edges with no confidence
# property are treated as 1.0 via COALESCE so they are never silently dropped.
_REFERENCES_TABLE_IDS_CYPHER = (
    "UNWIND $col_ids AS cid "
    "OPTIONAL MATCH (c:Column {id: cid})-[r:REFERENCES]-(other:Column)"
    "<-[:HAS_COLUMN]-(t:Table) "
    "WITH t, r WHERE t IS NOT NULL AND COALESCE(r.confidence, 1.0) >= $threshold "
    "RETURN DISTINCT t.id AS tid"
)

# Scored variant: score each expansion table by the max FK confidence among
# edges connecting it to the seed columns. Used when max_expansion_tables > 0
# to rank and cap expansion on dense single-schema fixtures.
# Also used as the first pass in combined FK+cosine re-ranking.
_REFERENCES_SCORED_TABLE_IDS_CYPHER = (
    "UNWIND $col_ids AS cid "
    "OPTIONAL MATCH (c:Column {id: cid})-[r:REFERENCES]-(other:Column)"
    "<-[:HAS_COLUMN]-(t:Table) "
    "WITH t.id AS tid, max(COALESCE(r.confidence, 1.0)) AS max_conf "
    "WHERE tid IS NOT NULL AND max_conf >= $threshold "
    "RETURN tid, max_conf "
    "ORDER BY max_conf DESC"
)

# Fetch join predicates (with source and confidence) for retrieved neighbour
# tables. When ingest did not persist a literal criteria string, the retriever
# renders one from the REFERENCES edge endpoints.
_REFERENCES_CRITERIA_CYPHER = (
    "UNWIND $col_ids AS cid "
    "OPTIONAL MATCH (c:Column {id: cid})-[r:REFERENCES]-(:Column) "
    "WITH r WHERE r IS NOT NULL "
    "  AND COALESCE(r.confidence, 1.0) >= $threshold "
    "RETURN DISTINCT r.criteria AS crit, "
    "       startNode(r).id AS source_col_id, "
    "       endNode(r).id AS target_col_id, "
    "       r.source AS source, r.confidence AS confidence"
)

# Return both endpoints of REFERENCES edges so their values can be fetched.
_JOIN_COLUMN_IDS_CYPHER = (
    "UNWIND $col_ids AS cid "
    "OPTIONAL MATCH (c:Column {id: cid})-[r:REFERENCES]-(other:Column) "
    "WITH other, r WHERE other IS NOT NULL "
    "  AND COALESCE(r.confidence, 1.0) >= $threshold "
    "RETURN DISTINCT other.id AS col_id"
)


def _normalize_id_part(name: str) -> str:
    """Normalize one identifier part to the form ingest stores in node ids.

    Mirrors ``dbxcarta.spark.contract.generate_id``: lowercase, then spaces
    and hyphens to underscores. Node ids are normalized this way while the
    ``.name`` property keeps the true Unity Catalog name, so any comparison
    against an id-derived part must normalize the configured name first.
    """
    return name.lower().replace(" ", "_").replace("-", "_")


def _question_tokens(question: str) -> list[str]:
    tokens = re.findall(r"[a-zA-Z]+", question.lower())
    return [t for t in tokens if len(t) >= 3 and t not in _STOP_WORDS]


def _lexical_table_ids(session: Session, question: str, schemas: list[str]) -> list[str]:
    tokens = _question_tokens(question)
    if not tokens:
        return []
    result = session.run(
        "UNWIND $tokens AS tok "
        "MATCH (s:Schema)-[:HAS_TABLE]->(t:Table) "
        "WHERE toLower(t.name) CONTAINS tok "
        "  AND (size($schemas) = 0 OR s.name IN $schemas) "
        "RETURN DISTINCT t.id AS id",
        tokens=tokens,
        schemas=schemas,
    )
    return [row["id"] for row in result]


def _lexical_column_table_ids(session: Session, question: str, schemas: list[str]) -> list[str]:
    """Return parent table IDs of columns whose name contains a question token.

    Surfaces tables that are only discoverable through a column name (e.g.
    ``account_labels`` via its ``is_fraud`` column) which table-name and
    vector seeding both miss.
    """
    tokens = _question_tokens(question)
    if not tokens:
        return []
    result = session.run(
        "UNWIND $tokens AS tok "
        "MATCH (s:Schema)-[:HAS_TABLE]->(t:Table)-[:HAS_COLUMN]->(c:Column) "
        "WHERE toLower(c.name) CONTAINS tok "
        "  AND (size($schemas) = 0 OR s.name IN $schemas) "
        "RETURN DISTINCT t.id AS id",
        tokens=tokens,
        schemas=schemas,
    )
    return [row["id"] for row in result]


class GraphRetriever(Retriever):
    def __init__(self, settings: ClientSettings) -> None:
        self._settings = settings
        uri, username, password = neo4j_credentials(settings)
        self._driver = GraphDatabase.driver(uri, auth=(username, password))

    def close(self) -> None:
        self._driver.close()

    def retrieve(self, question: str, embedding: list[float]) -> ContextBundle:
        top_k = self._settings.dbxcarta_client_top_k
        threshold = self._settings.dbxcarta_confidence_threshold
        inject_criteria = self._settings.dbxcarta_inject_criteria
        configured_schemas = self._settings.schemas_list
        max_expansion = self._settings.dbxcarta_client_max_expansion_tables

        alpha = self._settings.dbxcarta_client_expansion_alpha

        with self._driver.session() as session:
            raw_col_seed_pairs = _query_vector_seeds(session, _COL_INDEX, embedding, top_k)
            raw_tbl_seed_pairs = _query_vector_seeds(session, _TABLE_INDEX, embedding, top_k)

            col_seed_pairs = _filter_seed_pairs_to_schemas(raw_col_seed_pairs, configured_schemas)
            tbl_seed_pairs = _filter_seed_pairs_to_schemas(raw_tbl_seed_pairs, configured_schemas)
            selected_schemas = _select_schemas(col_seed_pairs, tbl_seed_pairs)
            # _select_schemas returns normalized id parts. Map them back to the
            # configured true names so the `.name`-filtered fetch and lexical
            # queries get the real (possibly hyphenated) schema names.
            _selected_norm = {_normalize_id_part(s) for s in selected_schemas}
            selected_true = (
                [s for s in configured_schemas if _normalize_id_part(s) in _selected_norm]
                if _selected_norm and configured_schemas
                else selected_schemas
            )
            active_col_seed_pairs = (
                _filter_seed_pairs_to_schemas(col_seed_pairs, selected_schemas)
                if selected_schemas
                else col_seed_pairs
            )
            active_tbl_seed_pairs = (
                _filter_seed_pairs_to_schemas(tbl_seed_pairs, selected_schemas)
                if selected_schemas
                else tbl_seed_pairs
            )
            col_seeds = [id_ for id_, _ in col_seed_pairs]
            tbl_seeds = [id_ for id_, _ in tbl_seed_pairs]
            col_seed_scores = [score for _, score in col_seed_pairs]
            tbl_seed_scores = [score for _, score in tbl_seed_pairs]
            active_col_seeds = [id_ for id_, _ in active_col_seed_pairs]
            active_tbl_seeds = [id_ for id_, _ in active_tbl_seed_pairs]

            parent_tbl_ids = _parent_table_ids(session, active_col_seeds)
            ref_tbl_ids = _references_table_ids_ranked(
                session, active_col_seeds, threshold, max_expansion, embedding, alpha
            )
            fetch_schemas = selected_true or configured_schemas
            lexical_tbl_ids = _lexical_table_ids(session, question, fetch_schemas)
            lexical_col_tbl_ids = _lexical_column_table_ids(session, question, fetch_schemas)

            expansion_tbl_ids = list(
                dict.fromkeys(parent_tbl_ids + ref_tbl_ids + lexical_tbl_ids + lexical_col_tbl_ids)
            )
            all_tbl_ids = list(dict.fromkeys(active_tbl_seeds + expansion_tbl_ids))
            columns = _fetch_columns(session, all_tbl_ids, fetch_schemas)

            join_col_ids = _join_column_ids(session, active_col_seeds, threshold)
            retrieved_col_ids = [c.column_id for c in columns if c.column_id]
            value_col_ids = list(dict.fromkeys(active_col_seeds + join_col_ids + retrieved_col_ids))
            values = _fetch_values(session, value_col_ids)

            join_lines = (
                _references_criteria(session, active_col_seeds, threshold)
                if inject_criteria
                else []
            )

        return ContextBundle(
            columns=columns,
            values=values,
            col_seed_ids=col_seeds,
            col_seed_scores=col_seed_scores,
            tbl_seed_ids=tbl_seeds,
            tbl_seed_scores=tbl_seed_scores,
            expansion_tbl_ids=expansion_tbl_ids,
            selected_schemas=selected_true,
            join_lines=join_lines,
        )


def _select_schemas(
    col_seed_pairs: list[tuple[str, float]],
    tbl_seed_pairs: list[tuple[str, float]],
    min_runner_up_score: float = 0.20,
) -> list[str]:
    """Pick the top schema by per-index normalized seed score."""
    raw: dict[str, float] = {}
    for scores in (
        _normalized_schema_scores(col_seed_pairs),
        _normalized_schema_scores(tbl_seed_pairs),
    ):
        for schema, score in scores.items():
            raw[schema] = raw.get(schema, 0.0) + score
    if not raw:
        return []
    total = sum(raw.values()) or 1.0
    normalized = {k: v / total for k, v in raw.items()}
    ranked = sorted(normalized, key=normalized.__getitem__, reverse=True)
    selected = [ranked[0]]
    if len(ranked) > 1 and normalized[ranked[1]] >= min_runner_up_score:
        selected.append(ranked[1])
    return selected


def _filter_seed_pairs_to_schemas(
    seed_pairs: list[tuple[str, float]],
    schemas: list[str],
) -> list[tuple[str, float]]:
    if not schemas:
        return seed_pairs
    # schema_from_node_id returns the normalized id part, so the configured
    # (true) schema names must be normalized to the same space to match.
    allowed = {_normalize_id_part(s) for s in schemas}
    return [
        (node_id, score) for node_id, score in seed_pairs if schema_from_node_id(node_id) in allowed
    ]


def _normalized_schema_scores(
    seed_pairs: list[tuple[str, float]],
) -> dict[str, float]:
    raw: dict[str, float] = {}
    for node_id, score in seed_pairs:
        schema = schema_from_node_id(node_id)
        if schema:
            raw[schema] = raw.get(schema, 0.0) + score
    total = sum(raw.values()) or 1.0
    return {schema: score / total for schema, score in raw.items()}


def _query_vector_seeds(
    session: Session, index: str, embedding: list[float], k: int
) -> list[tuple[str, float]]:
    # Neo4j's procedure API does not support parameterized index names.
    # `index` is always one of the two module-level constants, never user-controlled.
    result = session.run(
        f"CALL db.index.vector.queryNodes('{index}', $k, $vec) "
        "YIELD node, score "
        "RETURN node.id AS id, score",
        k=k,
        vec=list(embedding),
    )
    return [(row["id"], row["score"]) for row in result]


def _parent_table_ids(session: Session, col_ids: list[str]) -> list[str]:
    if not col_ids:
        return []
    result = session.run(
        "UNWIND $col_ids AS cid "
        "MATCH (c:Column {id: cid})<-[:HAS_COLUMN]-(t:Table) "
        "RETURN DISTINCT t.id AS tid",
        col_ids=col_ids,
    )
    return [row["tid"] for row in result]


def _references_table_ids(session: Session, col_ids: list[str], threshold: float) -> list[str]:
    """Follow REFERENCES edges in both directions to find joinable tables."""
    if not col_ids:
        return []
    result = session.run(
        _REFERENCES_TABLE_IDS_CYPHER,
        col_ids=col_ids,
        threshold=threshold,
    )
    return [row["tid"] for row in result]


def _rank_by_combined_score(
    fk_pairs: list[tuple[str, float]],
    cosine_scores: dict[str, float],
    alpha: float,
    max_tables: int,
) -> list[str]:
    """Rank table IDs by alpha*FK_confidence + (1-alpha)*cosine_similarity.

    Pure function — no I/O. Tables absent from cosine_scores receive 0.0
    cosine similarity so they can still rank via FK confidence alone.
    """

    def _score(pair: tuple[str, float]) -> float:
        tid, fk = pair
        return alpha * fk + (1.0 - alpha) * cosine_scores.get(tid, 0.0)

    ranked = sorted(fk_pairs, key=_score, reverse=True)
    return [tid for tid, _ in ranked[:max_tables]]


def _score_candidates_by_cosine(
    session: Session,
    table_ids: list[str],
    embedding: list[float],
) -> dict[str, float]:
    """Return cosine similarity scores for a candidate set of table IDs.

    Queries the table vector index with a generous k so that all candidate
    tables are covered even if they rank outside the top-k by default.
    Tables not returned by the vector query receive 0.0 implicitly.
    """
    if not table_ids or not embedding:
        return {}
    k = max(len(table_ids) * 10, 100)
    tid_set = set(table_ids)
    result = session.run(
        f"CALL db.index.vector.queryNodes('{_TABLE_INDEX}', $k, $vec) "
        "YIELD node, score "
        "RETURN node.id AS tid, score",
        k=k,
        vec=list(embedding),
    )
    return {row["tid"]: row["score"] for row in result if row["tid"] in tid_set}


def _references_table_ids_capped(
    session: Session, col_ids: list[str], threshold: float, max_tables: int
) -> list[str]:
    """Like _references_table_ids but scored and capped at max_tables.

    When max_tables == 0 the behaviour is identical to the uncapped version.
    When max_tables > 0 tables are ranked by max FK confidence among edges
    connecting them to seed columns and the top-max_tables are returned.
    This prevents context explosion on dense single-schema fixtures.
    """
    if not col_ids:
        return []
    if max_tables <= 0:
        return _references_table_ids(session, col_ids, threshold)
    result = session.run(
        _REFERENCES_SCORED_TABLE_IDS_CYPHER,
        col_ids=col_ids,
        threshold=threshold,
    )
    pairs = [(row["tid"], row["max_conf"]) for row in result if row["tid"]]
    return [tid for tid, _ in pairs[:max_tables]]


def _references_table_ids_ranked(
    session: Session,
    col_ids: list[str],
    threshold: float,
    max_tables: int,
    embedding: list[float],
    alpha: float,
) -> list[str]:
    """FK walk + combined FK-confidence/cosine-similarity re-ranking.

    When max_tables == 0 falls through to the uncapped FK-only expansion.
    When max_tables > 0, candidates from the FK walk are scored by:
        combined = alpha * fk_confidence + (1 - alpha) * cosine_similarity
    and the top-max_tables are returned. This surfaces cross-domain join
    targets (e.g. sys_users) that have low FK confidence but high semantic
    relevance to the question.
    """
    if not col_ids:
        return []
    if max_tables <= 0:
        return _references_table_ids(session, col_ids, threshold)
    result = session.run(
        _REFERENCES_SCORED_TABLE_IDS_CYPHER,
        col_ids=col_ids,
        threshold=threshold,
    )
    fk_pairs = [(row["tid"], row["max_conf"]) for row in result if row["tid"]]
    if not fk_pairs:
        return []
    tids = [tid for tid, _ in fk_pairs]
    cosine_scores = _score_candidates_by_cosine(session, tids, embedding)
    return _rank_by_combined_score(fk_pairs, cosine_scores, alpha, max_tables)


def _references_criteria(session: Session, col_ids: list[str], threshold: float) -> list[JoinLine]:
    """Pull join predicates (with source and confidence) off REFERENCES edges above the threshold."""
    if not col_ids:
        return []
    result = session.run(
        _REFERENCES_CRITERIA_CYPHER,
        col_ids=col_ids,
        threshold=threshold,
    )
    return [
        JoinLine(
            predicate=(row["crit"] or f"{row['source_col_id']} = {row['target_col_id']}"),
            source=row["source"],
            confidence=row["confidence"],
        )
        for row in result
        if row["crit"] is not None
        or (row["source_col_id"] is not None and row["target_col_id"] is not None)
    ]


def _join_column_ids(session: Session, col_ids: list[str], threshold: float) -> list[str]:
    """Return the far-side column IDs of REFERENCES edges from seed columns."""
    if not col_ids:
        return []
    result = session.run(
        _JOIN_COLUMN_IDS_CYPHER,
        col_ids=col_ids,
        threshold=threshold,
    )
    return [row["col_id"] for row in result if row["col_id"] is not None]


def _fetch_columns(session: Session, table_ids: list[str], schemas: list[str]) -> list[ColumnEntry]:
    if not table_ids:
        return []
    result = session.run(
        "UNWIND $tids AS tid "
        "MATCH (db:Database)-[:HAS_SCHEMA]->(s:Schema)-[:HAS_TABLE]->"
        "(t:Table {id: tid}) "
        "MATCH (t)-[:HAS_COLUMN]->(c:Column) "
        "WHERE size($schemas) = 0 OR s.name IN $schemas "
        "RETURN db.name AS catalog_name, s.name AS schema_name, "
        "       t.name AS table_name, "
        "       c.id AS col_id, c.name AS col_name, c.type AS data_type, "
        "       c.description AS comment, c.ordinal_position AS pos "
        "ORDER BY schema_name, table_name, pos",
        tids=table_ids,
        schemas=schemas,
    )
    entries: list[ColumnEntry] = []
    for row in result:
        # Catalog, schema, and table come from the authoritative `.name`
        # properties via the Database walk. Node ids are normalized
        # (hyphens to underscores) and would yield a nonexistent catalog;
        # the graph spans multiple catalogs, so Database.name per node is
        # what reconstructs a correct, executable FQN.
        catalog = row["catalog_name"] or ""
        fqt = f"`{catalog}`.`{row['schema_name']}`.`{row['table_name']}`"
        entries.append(
            ColumnEntry(
                table_fqn=fqt,
                column_name=row["col_name"],
                data_type=row["data_type"] or "",
                comment=row["comment"] or "",
                column_id=row["col_id"] or "",
            )
        )
    return entries


def _fetch_values(session: Session, col_ids: list[str]) -> dict[str, list[str]]:
    """Return {col_id: [values]} for the given column IDs.

    Three guards bound prompt growth: per-column cap (categorical columns
    are useful at ~20 distinct values), per-value char cap (long-text columns
    that pass the cardinality threshold can still have multi-KB values), and
    a global cap on rows fetched from Neo4j (defense in depth against fan-out).
    """
    if not col_ids:
        return {}
    result = session.run(
        "UNWIND $col_ids AS cid "
        "MATCH (c:Column {id: cid})-[:HAS_VALUE]->(v:Value) "
        f"RETURN c.id AS col_id, v.value AS val LIMIT {_MAX_VALUES_TOTAL}",
        col_ids=col_ids,
    )
    by_col: dict[str, list[str]] = {}
    for row in result:
        val = row["val"]
        if val is None:
            continue
        text = str(val)
        if len(text) > _MAX_VALUE_CHARS:
            text = text[:_MAX_VALUE_CHARS] + "..."
        bucket = by_col.setdefault(row["col_id"], [])
        if len(bucket) < _MAX_VALUES_PER_COLUMN:
            bucket.append(text)
    return by_col
