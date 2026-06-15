"""Compare neocarta retrieval strategies over a single query.

Runs the *same* natural-language query through every retrieval strategy the
neocarta MCP server exposes (vector, full-text, hybrid, and business-term
hybrid, at both table and column level) and prints the ranked tables each one
returns, plus a comparison matrix so you can see how the strategies differ.

It reuses the exact Cypher the MCP server runs (``neocarta._mcp.cypher``) and the
same embedder (``LiteLLMEmbeddingsConnector``), so this is a faithful local test
of production retrieval against the graph in your ``.env`` Neo4j.

This is read-only: it only runs vector/full-text index lookups.

Embedding consistency
---------------------
For the vector and hybrid strategies to be meaningful, ``EMBEDDING_MODEL`` here
must be the *same model at the same dimension* used to embed the graph at ingest.
A Databricks graph embedded via ``ai_query('openai-text-embedding-3-small', ...)``
lines up with the LiteLLM model ``text-embedding-3-small`` (same underlying
OpenAI model). A different model or dimension makes vector/hybrid results
meaningless; full-text does not use embeddings and is unaffected.

Usage
-----
    # Run every strategy for one question
    uv run examples/databricks/compare_retrievers.py \
        --query "Which account types have the most fraud-labeled accounts?"

    # Only specific strategies, deeper recall, more rows printed
    uv run examples/databricks/compare_retrievers.py \
        --query "fraud labeled accounts" \
        --strategies tbl-vec tbl-ft tbl-hyb \
        --search-top-k 20 --max-tables 10 --top 10

Environment variables required
------------------------------
    - NEO4J_URI, NEO4J_USERNAME, NEO4J_PASSWORD
    - NEO4J_DATABASE (optional, defaults to 'neo4j')
    - EMBEDDING_MODEL (optional, defaults to 'text-embedding-3-small')
    - Provider credentials for that model, e.g. OPENAI_API_KEY
"""

import argparse
import asyncio
import logging
import os
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv
from neo4j import AsyncGraphDatabase, RoutingControl
from neo4j.exceptions import Neo4jError

from neocarta._mcp.cypher import (
    get_context_by_column_business_term_hybrid_search_cypher,
    get_context_by_column_full_text_search_cypher,
    get_context_by_column_hybrid_search_cypher,
    get_context_by_column_vector_search_cypher,
    get_context_by_schema_and_table_vector_search_cypher,
    get_context_by_table_business_term_hybrid_search_cypher,
    get_context_by_table_full_text_search_cypher,
    get_context_by_table_hybrid_search_cypher,
    get_context_by_table_vector_search_cypher,
)
from neocarta._mcp.models import TableContext
from neocarta._mcp.utils import remove_lucene_chars
from neocarta.enrichment.embeddings import LiteLLMEmbeddingsConnector


@dataclass(frozen=True)
class Strategy:
    """A single retrieval strategy and how to invoke its Cypher.

    Parameters
    ----------
    code:
        Short identifier used on the command line and as a column header.
    description:
        One-line human-readable summary.
    cypher:
        Builder returning the Cypher query string the MCP server runs.
    needs_embedding:
        Whether the query passes a ``queryEmbedding`` parameter.
    needs_text:
        Whether the query passes a Lucene-cleaned ``queryText`` parameter.
    """

    code: str
    description: str
    cypher: Callable[[], str]
    needs_embedding: bool
    needs_text: bool


# Every retriever the MCP server registers. Each returns ``list[TableContext]``
# and takes ``searchTopK`` / ``maxTables`` plus the signals flagged below.
STRATEGIES: tuple[Strategy, ...] = (
    Strategy(
        "tbl-vec",
        "Table vector (embedding)",
        get_context_by_table_vector_search_cypher,
        needs_embedding=True,
        needs_text=False,
    ),
    Strategy(
        "tbl-ft",
        "Table full-text (keywords)",
        get_context_by_table_full_text_search_cypher,
        needs_embedding=False,
        needs_text=True,
    ),
    Strategy(
        "tbl-hyb",
        "Table hybrid (vector + full-text)",
        get_context_by_table_hybrid_search_cypher,
        needs_embedding=True,
        needs_text=True,
    ),
    Strategy(
        "tbl-bt",
        "Table business-term hybrid",
        get_context_by_table_business_term_hybrid_search_cypher,
        needs_embedding=True,
        needs_text=True,
    ),
    Strategy(
        "sch-tbl-vec",
        "Schema+table vector (two-stage)",
        get_context_by_schema_and_table_vector_search_cypher,
        needs_embedding=True,
        needs_text=False,
    ),
    Strategy(
        "col-vec",
        "Column vector (embedding)",
        get_context_by_column_vector_search_cypher,
        needs_embedding=True,
        needs_text=False,
    ),
    Strategy(
        "col-ft",
        "Column full-text (keywords)",
        get_context_by_column_full_text_search_cypher,
        needs_embedding=False,
        needs_text=True,
    ),
    Strategy(
        "col-hyb",
        "Column hybrid (vector + full-text)",
        get_context_by_column_hybrid_search_cypher,
        needs_embedding=True,
        needs_text=True,
    ),
    Strategy(
        "col-bt",
        "Column business-term hybrid",
        get_context_by_column_business_term_hybrid_search_cypher,
        needs_embedding=True,
        needs_text=True,
    ),
)

STRATEGIES_BY_CODE = {s.code: s for s in STRATEGIES}


class _NotificationCounter(logging.Handler):
    """Logging handler that tallies notification records for an end-of-run summary."""

    def __init__(self) -> None:
        super().__init__()
        self.count = 0

    def emit(self, _record: logging.LogRecord) -> None:
        self.count += 1


def _configure_notification_logging() -> tuple[Path, _NotificationCounter]:
    """Route the driver's notification warnings to a gitignored log file.

    The neo4j driver logs every server notification through the
    ``neo4j.notifications`` logger (``neo4j/_async/work/result.py``). One of
    these is the harmless ``01N51`` warning emitted whenever an ``OPTIONAL
    MATCH`` references a relationship type no node uses yet (e.g. ``REFERENCES``
    before any foreign keys are loaded). Left unconfigured, Python's last-resort
    handler prints these to stderr and clutter the comparison output.

    Redirect that logger to ``logs/notifications.log`` and stop it propagating to
    the root logger, so the console stays clean while the warnings remain
    available for anyone who needs them. A counting handler is attached
    alongside the file so the run can report whether any were emitted.

    Returns:
    -------
    tuple[Path, _NotificationCounter]
        The log file the notifications are written to, and the handler tracking
        how many were emitted during the run.
    """
    log_dir = Path(__file__).parent / "logs"
    log_dir.mkdir(exist_ok=True)
    log_path = log_dir / "notifications.log"

    handler = logging.FileHandler(log_path)
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
    counter = _NotificationCounter()

    logger = logging.getLogger("neo4j.notifications")
    logger.setLevel(logging.INFO)
    logger.handlers.clear()
    logger.addHandler(handler)
    logger.addHandler(counter)
    logger.propagate = False
    return log_path, counter


def _fqn(table: TableContext) -> str:
    """Fully-qualified ``database.schema.table`` name for a result."""
    return f"{table.database_name}.{table.schema_name}.{table.table_name}"


async def run_strategy(
    strategy: Strategy,
    driver: AsyncGraphDatabase,
    database: str,
    query_text: str,
    embedding: list[float] | None,
    search_top_k: int,
    max_tables: int,
) -> list[TableContext] | None:
    """Run one strategy, returning its ranked tables or ``None`` if it could not run.

    Returns ``None`` (with a printed reason) when the strategy needs an embedding
    that is unavailable, or when its index is missing from the database.
    """
    if strategy.needs_embedding and embedding is None:
        print(f"  [{strategy.code}] skipped: no query embedding available")
        return None

    parameters: dict[str, object] = {
        "searchTopK": search_top_k,
        "maxTables": max_tables,
    }
    if strategy.needs_embedding:
        parameters["queryEmbedding"] = embedding
    if strategy.needs_text:
        parameters["queryText"] = remove_lucene_chars(query_text)

    try:
        results = await driver.execute_query(
            query_=strategy.cypher(),
            parameters_=parameters,
            database_=database,
            routing_=RoutingControl.READ,
            result_transformer_=lambda x: x.data(),
        )
    except Neo4jError as exc:
        # Most commonly a missing vector/full-text index for this label.
        print(f"  [{strategy.code}] skipped: {exc.code} {exc.message}")
        return None

    return [TableContext.model_validate(r["result"]) for r in results]


def print_strategy_results(strategy: Strategy, tables: list[TableContext], top: int) -> None:
    """Print the top ranked tables a strategy returned."""
    header = f"[{strategy.code}] {strategy.description} — {len(tables)} result(s)"
    print(f"\n{header}")
    print("-" * len(header))
    if not tables:
        print("  (no matches)")
        return
    print(f"  {'#':>2}  {'score':>6}  table")
    for rank, table in enumerate(tables[:top], start=1):
        score = table.table_score
        score_text = f"{score:.3f}" if score is not None else "   -  "
        print(f"  {rank:>2}  {score_text:>6}  {_fqn(table)} ({table.num_columns} cols)")


def print_comparison_matrix(results: dict[str, list[TableContext]], top: int) -> None:
    """Print a table-by-strategy matrix of ranks so strategies can be compared.

    Each cell is the rank a strategy gave that table (within ``top``), or ``-``.
    """
    codes = list(results)
    # Rank each table within each strategy's top-N.
    ranks: dict[str, dict[str, int]] = {}
    for code, tables in results.items():
        for rank, table in enumerate(tables[:top], start=1):
            ranks.setdefault(_fqn(table), {})[code] = rank

    if not ranks:
        print("\nNo strategy returned any tables; nothing to compare.")
        return

    fqn_width = max(len("table"), *(len(fqn) for fqn in ranks))
    header = "  ".join([f"{'table':<{fqn_width}}", *(f"{code:>11}" for code in codes)])
    title = f"Comparison matrix (rank within top {top}, '-' = absent)"
    print(f"\n{'=' * 80}\n{title}\n{'=' * 80}\n{header}\n{'-' * len(header)}")
    # Stable order: tables that appear earliest/most often float up.
    ordered = sorted(ranks, key=lambda f: (min(ranks[f].values()), -len(ranks[f])))
    for fqn in ordered:
        cells = [f"{ranks[fqn].get(code, '-'):>11}" for code in codes]
        print("  ".join([f"{fqn:<{fqn_width}}", *(str(c) for c in cells)]))


async def compare(
    query: str,
    strategy_codes: list[str],
    search_top_k: int,
    max_tables: int,
    top: int,
) -> None:
    """Embed the query once, then run it through each selected strategy."""
    load_dotenv()
    notifications_log, notification_counter = _configure_notification_logging()
    uri = os.environ["NEO4J_URI"]
    username = os.environ["NEO4J_USERNAME"]
    password = os.environ["NEO4J_PASSWORD"]
    database = os.environ.get("NEO4J_DATABASE", "neo4j")
    embedding_model = os.environ.get("EMBEDDING_MODEL", "text-embedding-3-small")

    strategies = [STRATEGIES_BY_CODE[code] for code in strategy_codes]
    need_embedding = any(s.needs_embedding for s in strategies)

    print("=" * 80)
    print("neocarta retriever comparison")
    print("=" * 80)
    print(f"  Query        : {query!r}")
    print(f"  Neo4j        : {uri} (database {database!r})")
    print(f"  Strategies   : {', '.join(strategy_codes)}")
    print(f"  Notifications: {notifications_log}")

    async with AsyncGraphDatabase.driver(uri, auth=(username, password)) as driver:
        embedding: list[float] | None = None
        if need_embedding:
            embedder = LiteLLMEmbeddingsConnector(
                neo4j_driver=driver,
                embedding_model=embedding_model,
                database_name=database,
            )
            embedding = await embedder._create_embedding_async(query)
            if embedding is None:
                print("WARNING: embedding failed; vector/hybrid strategies will be skipped.")
            else:
                print(f"Embedded query into a {len(embedding)}-dim vector ({embedding_model}).")

        results: dict[str, list[TableContext]] = {}
        for strategy in strategies:
            tables = await run_strategy(
                strategy, driver, database, query, embedding, search_top_k, max_tables
            )
            if tables is None:
                continue
            results[strategy.code] = tables
            print_strategy_results(strategy, tables, top)

    print_comparison_matrix(results, top)

    warnings = notification_counter.count
    if warnings:
        print(
            f"\n{warnings} driver notification(s) emitted during this run "
            f"(logged to {notifications_log})."
        )
    else:
        print("\nNo driver notifications during this run.")


def main() -> None:
    """Parse arguments and run the comparison."""
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--query",
        required=True,
        help="The natural-language / keyword query to run through every strategy.",
    )
    parser.add_argument(
        "--strategies",
        nargs="+",
        choices=list(STRATEGIES_BY_CODE),
        default=list(STRATEGIES_BY_CODE),
        metavar="CODE",
        help="Subset of strategy codes to run. Default: all. "
        f"Choices: {', '.join(STRATEGIES_BY_CODE)}",
    )
    parser.add_argument(
        "--search-top-k",
        type=int,
        default=10,
        help="Candidates each search branch returns before ranking (default: 10).",
    )
    parser.add_argument(
        "--max-tables",
        type=int,
        default=5,
        help="Maximum tables kept per strategy (default: 5).",
    )
    parser.add_argument(
        "--top",
        type=int,
        default=5,
        help="How many ranked rows to print per strategy and in the matrix (default: 5).",
    )
    args = parser.parse_args()

    asyncio.run(
        compare(
            query=args.query,
            strategy_codes=args.strategies,
            search_top_k=args.search_top_k,
            max_tables=args.max_tables,
            top=args.top,
        )
    )


if __name__ == "__main__":
    main()
