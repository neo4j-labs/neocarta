"""Unit tests for the shared graph_rag retrieval-and-prompt seam."""

from __future__ import annotations

from dbxcarta.client.graph_rag import GraphRagContext, build_graph_rag_context
from dbxcarta.client.retriever import ColumnEntry, ContextBundle, Retriever
from dbxcarta.client.settings import ClientSettings


class _StubRetriever(Retriever):
    """Records its call and tracks whether the seam closed it."""

    def __init__(self, bundle: ContextBundle) -> None:
        self._bundle = bundle
        self.closed = False
        self.calls: list[tuple[str, list[float]]] = []

    def retrieve(self, question: str, embedding: list[float]) -> ContextBundle:
        self.calls.append((question, embedding))
        return self._bundle

    def close(self) -> None:
        self.closed = True


def _settings() -> ClientSettings:
    return ClientSettings(
        databricks_secret_scope="dbxcarta-neo4j-test",
        dbxcarta_catalog="main",
        dbxcarta_schemas="s1",
        dbxcarta_summary_volume="/Volumes/cat/schema/vol/runs",
        dbxcarta_summary_table="cat.schema.table",
        databricks_warehouse_id="abc",
        databricks_volume_path="/Volumes/cat/schema/vol",
    )


def _bundle() -> ContextBundle:
    return ContextBundle(
        columns=[
            ColumnEntry(
                table_fqn="`main`.`s1`.`accounts`",
                column_name="account_id",
                data_type="bigint",
                column_id="col-1",
            )
        ],
        col_seed_ids=["col-1"],
        tbl_seed_ids=["tbl-1"],
    )


def test_seam_builds_prompt_containing_rendered_context() -> None:
    bundle = _bundle()
    retriever = _StubRetriever(bundle)

    context = build_graph_rag_context(
        ws=None,  # unused: embedding supplied and retriever supplied
        settings=_settings(),
        question="how many accounts?",
        embedding=[0.1, 0.2, 0.3],
        retriever=retriever,
    )

    assert isinstance(context, GraphRagContext)
    assert context.question == "how many accounts?"
    assert context.context_text == bundle.to_text()
    assert "account_id" in context.context_text
    assert context.context_text in context.prompt
    assert "how many accounts?" in context.prompt
    assert context.seed_ids == bundle.seed_ids
    assert retriever.calls == [("how many accounts?", [0.1, 0.2, 0.3])]


def test_seam_does_not_close_caller_owned_retriever() -> None:
    retriever = _StubRetriever(_bundle())

    build_graph_rag_context(
        ws=None,
        settings=_settings(),
        question="q",
        embedding=[0.0],
        retriever=retriever,
    )

    assert retriever.closed is False
