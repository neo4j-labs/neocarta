"""dbxcarta client: retrieval runtime and Text2SQL evaluation harness.

The base install covers question loading, SQL parsing, and result-set
comparison and has no graph-database dependency. Graph retrieval and the
Neo4j schema dump require the ``graph`` extra:
``pip install 'dbxcarta-client[graph]'``. ``build_graph_rag_context`` is the
shared, transport-neutral retrieval-and-prompt seam used by both the
evaluation harness and the local demo; importing it does not pull Neo4j
until a graph retrieval is actually performed.
"""

from dbxcarta.client.compare import compare_result_sets
from dbxcarta.client.graph_rag import GraphRagContext, build_graph_rag_context
from dbxcarta.client.questions import Question, load_questions
from dbxcarta.client.sql import parse_sql

__all__ = [
    "GraphRagContext",
    "Question",
    "build_graph_rag_context",
    "compare_result_sets",
    "load_questions",
    "parse_sql",
]
