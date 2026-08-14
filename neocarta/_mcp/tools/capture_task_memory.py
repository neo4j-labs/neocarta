"""Semantic-memory capture MCP tool.

Writes a user-confirmed question/SQL pair into memory. The SQL is canonicalized
(so surface variants dedupe onto one ``Query``), hashed, and parsed for the
catalog ``Table`` / ``Column`` nodes it uses; the verbatim question is embedded
and attached to the merged ``Task`` as a ``Phrase``. The SQL dialect and the
namespace defaults for unqualified tables come from the server settings
(``SQL_DIALECT`` / ``DEFAULT_PROJECT_ID`` / ``DEFAULT_SCHEMA_ID``), keeping the
tool warehouse-agnostic.

This is the only write tool the MCP server exposes, so it is the one tool that
issues ``RoutingControl.WRITE``.
"""

from fastmcp import FastMCP
from neo4j import AsyncDriver, RoutingControl

from ...connectors.query_log.utils import parse_sql_query
from ...connectors.utils.generate_id import (
    create_query_id,
    generate_phrase_id,
    generate_task_id,
)
from ...connectors.utils.sql_canonicalize import canonicalize_sql
from ...enrichment.embeddings import LiteLLMEmbeddingsConnector
from ...errors import NeocartaError
from ..cypher import capture_task_memory_cypher
from ..models import CaptureMemoryResult


def register(
    server: FastMCP,
    neo4j_driver: AsyncDriver,
    neo4j_database: str,
    embedder: LiteLLMEmbeddingsConnector,
    *,
    sql_dialect: str = "bigquery",
    default_project_id: str | None = None,
    default_schema_id: str | None = None,
) -> None:
    """Register the semantic-memory capture tool on the MCP server.

    ``sql_dialect`` / ``default_project_id`` / ``default_schema_id`` are the
    warehouse-agnostic parse settings (resolved from ``mcp_server_settings`` by
    the server); they are passed in rather than read here so the tool module
    imports without instantiating the server's env-backed ``Settings``.
    """

    @server.tool()
    async def capture_task_memory(
        question: str,
        sql: str,
        description: str,
        name: str,
        observations: list[str] | None = None,
    ) -> CaptureMemoryResult:
        """
        Capture a user-confirmed question/SQL pair into semantic memory.

        Call this ONLY after the user explicitly confirms an answer is correct.
        Never capture comparison runs or rejected answers.

        MERGEs a Task keyed by `name` and attaches the verbatim question as an
        embedded `Phrase` child (HAS_PHRASE). Re-capturing the same `name` with
        differently worded questions attaches more Phrases to the one Task: this
        is how you confirm equivalent phrasings, and every added phrasing raises
        future recall for that question. The SQL is canonicalized before it is
        hashed, so alias-only, formatting, and predicate-order variants of the
        same query dedupe onto a single canonical `Query` (HAS_QUERY). Only the
        Phrase carries an embedding; the Task and Query do not.

        The Query is linked to existing semantic-layer Table/Column nodes parsed
        from the canonical SQL (USES_TABLE / USES_COLUMN). If the result has
        non-empty `unmatched_tables`/`unmatched_columns`, surface them to the
        user: the SQL touches catalog objects the semantic layer does not know
        about.

        Parameters
        ----------
        question: str
            The user's natural-language question, verbatim.
        sql: str
            The exact SQL that produced the confirmed answer (fully qualified
            table names, e.g. `project.dataset.table`).
        description: str
            One-sentence description of what the SQL computes.
        name: str
            CamelCase task name, e.g. WinRateBySegment. This is the merge key:
            reuse the same name to attach a new phrasing or update the SQL.
        observations: list[str] | None
            Analytical choices worth remembering (chosen metric definition,
            join path, weighting).
        """
        canonical_sql = canonicalize_sql(sql.strip(), dialect=sql_dialect)
        query_id = create_query_id(canonical_sql)
        task_id = generate_task_id(name)
        phrase_id = generate_phrase_id(question)

        # Parse the CANONICAL SQL (not the raw text) so the USES_TABLE /
        # USES_COLUMN links line up with the canonical form we hash and store on
        # the Query node. parse_sql_query returns None on a sqlglot failure and
        # raises ConfigError for an unsupported dialect or a table it cannot
        # qualify — surface the latter as an actionable tool error.
        try:
            parsed = (
                parse_sql_query(
                    canonical_sql,
                    query_id,
                    sql_dialect,
                    default_project_id=default_project_id,
                    default_schema_id=default_schema_id,
                )
                or {}
            )
        except NeocartaError as exc:
            raise ValueError(
                f"Could not parse the SQL for memory capture ({exc}). Ensure table names are "
                "fully qualified, or set DEFAULT_PROJECT_ID / DEFAULT_SCHEMA_ID (and a supported "
                "SQL_DIALECT) on the server."
            ) from exc

        table_ids = sorted({t["table_id"] for t in parsed.get("table_info", [])})
        column_ids = sorted({c["column_id"] for c in parsed.get("column_info", [])})

        # Only the Phrase carries an embedding; the question is embedded verbatim.
        phrase_embedding = await embedder._create_embedding_async(question)
        if phrase_embedding is None:
            raise ValueError(
                "Failed to embed the question for memory capture. Check the embedding provider "
                "credentials (e.g. OPENAI_API_KEY) and that EMBEDDING_MODEL is valid."
            )

        observations = [
            f"Question: {question}",
            f"Query description: {description}",
            *(observations or []),
        ]

        records, _, _ = await neo4j_driver.execute_query(
            query_=capture_task_memory_cypher(),
            parameters_={
                "task_id": task_id,
                "name": name,
                "observations": observations,
                "phrase_id": phrase_id,
                "question": question,
                "phrase_embedding": phrase_embedding,
                "query_id": query_id,
                "sql": canonical_sql,
                "description": description,
                "table_ids": table_ids,
                "column_ids": column_ids,
            },
            routing_=RoutingControl.WRITE,
            database_=neo4j_database,
        )

        linked_tables = records[0]["linked_tables"] if records else []
        linked_columns = records[0]["linked_columns"] if records else []
        return CaptureMemoryResult(
            task_id=task_id,
            task_name=name,
            phrase_id=phrase_id,
            query_id=query_id,
            canonical_sql=canonical_sql,
            linked_tables=linked_tables,
            linked_columns=linked_columns,
            unmatched_tables=sorted(set(table_ids) - set(linked_tables)),
            unmatched_columns=sorted(set(column_ids) - set(linked_columns)),
        )
