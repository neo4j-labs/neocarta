"""Prompt templates for each retrieval arm."""

from __future__ import annotations

_SQL_INSTRUCTION = (
    "Return ONLY the SQL query — no explanation, no markdown code fences, no preamble.\n"
    "Output format rules:\n"
    "- SELECT only the columns and aggregations the question explicitly asks for.\n"
    "- Do not add ID columns to SELECT or GROUP BY unless the question asks for IDs.\n"
    "- Do not add ORDER BY unless the question asks for ordering."
)


def no_context_prompt(question: str, catalog: str, schemas: list[str]) -> str:
    schema_hint = (
        f"schema '{schemas[0]}'"
        if len(schemas) == 1
        else "schemas " + ", ".join(f"'{s}'" for s in schemas)
    )
    return (
        f"You are a SQL expert. Write a single SQL SELECT query to answer the following question.\n"
        f"The data lives in Databricks Unity Catalog: catalog '{catalog}', {schema_hint}.\n"
        f"{_SQL_INSTRUCTION}\n\n"
        f"Question: {question}"
    )


def schema_dump_prompt(question: str, catalog: str, schemas: list[str], schema_text: str) -> str:
    schema_hint = (
        f"schema '{schemas[0]}'"
        if len(schemas) == 1
        else "schemas " + ", ".join(f"'{s}'" for s in schemas)
    )
    return (
        f"You are a SQL expert. Write a single SQL SELECT query to answer the following question.\n"
        f"The data lives in Databricks Unity Catalog: catalog '{catalog}', {schema_hint}.\n\n"
        f"Available tables and columns:\n{schema_text}\n\n"
        f"{_SQL_INSTRUCTION}\n\n"
        f"Question: {question}"
    )


def graph_rag_prompt(question: str, catalog: str, schemas: list[str], context_text: str) -> str:
    schema_hint = (
        f"schema '{schemas[0]}'"
        if len(schemas) == 1
        else "schemas " + ", ".join(f"'{s}'" for s in schemas)
    )
    return (
        f"You are a SQL expert. Write a single SQL SELECT query to answer the following question.\n"
        f"The retrieved context below lists the available Databricks Unity Catalog "
        f"tables for {schema_hint}. Some contexts can span multiple catalogs; "
        f"treat the full three-part table names in the context as authoritative.\n"
        f"Use ONLY the exact tables and columns listed in the context. "
        f"Do not invent, guess, or rename any table name or column name.\n"
        f"Use the full backtick-quoted three-part names exactly as shown in the context "
        f"(catalog and schema identifiers contain hyphens and require backtick quoting).\n"
        f"Table selection: for graph-derived metrics (risk score, similarity score, "
        f"community membership, ring/fraud-ring topology) prefer the curated "
        f"`gold_`-prefixed table when both a `gold_`-prefixed table and a non-`gold_` "
        f"table expose the needed columns. Use plain base business tables only for "
        f"questions about raw entities (account counts, account/merchant attributes, "
        f"transactions, transfers, ground-truth fraud labels).\n"
        f"If the question asks for the highest/top/largest (or lowest/smallest/bottom) "
        f"rows without naming a count, ORDER BY the relevant metric and LIMIT 10.\n"
        f"For a 'share', 'ratio', 'proportion', or 'percentage ... by X' question, "
        f"SELECT exactly the grouping column(s) and one ratio expression written as a "
        f"fraction (count_if(condition) / count(*)); do not multiply by 100 and do not "
        f"add extra count columns.\n\n"
        f"Relevant schema context retrieved from the knowledge graph:\n{context_text}\n\n"
        f"{_SQL_INSTRUCTION}\n\n"
        f"Question: {question}"
    )
