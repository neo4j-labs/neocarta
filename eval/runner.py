"""Evaluation pipeline runner."""

import json
import time
from typing import Any

from google.cloud import bigquery
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
from openai import AsyncOpenAI

from eval.datasets.models import EvalSample
from eval.inference_metrics import score_execution_accuracy
from eval.retrieval_metrics import (
    score_retrieval,
    serialize_table_contexts,
)
from eval.retrievers.bigquery_schema_retriever import BigQuerySchemaRetriever
from eval.sql_parser import (
    score_schema_faithfulness,
    score_structural_equivalence,
)
from eval.token_metrics import ContextTokenMeasurement
from neocarta._mcp.models import TableContext

system_prompt = """
You are a SQL expert. Given a natural language question and database schema context, generate a BigQuery SQL query.

Rules:
- Return ONLY the SQL query, no explanations
- Use fully qualified table names (schema.table)
- Ensure the query is syntactically correct for BigQuery"""

user_prompt = """
Database Schema:
{schema_context}

Question: {question}

Generate the SQL query:"""


class EvalRunner:
    """
    Orchestrates the evaluation pipeline.

    Runs both conditions (semantic and full_schema) for each sample
    and scores the results.
    """

    def __init__(
        self,
        semantic_mcp_server_path: str,
        full_schema_retriever: BigQuerySchemaRetriever,
        bq_client: bigquery.Client,
        llm_client: AsyncOpenAI,
        llm: str = "gpt-4o",
        dialect: str = "bigquery",
    ) -> None:
        """
        Initialize evaluation runner.

        Parameters
        ----------
        semantic_mcp_server_path : str
            Path to the semantic layer MCP server script
        full_schema_retriever : BigQuerySchemaRetriever
            Retriever for full schema baseline
        bq_client : bigquery.Client
            BigQuery client for execution scoring
        llm_client : AsyncOpenAI
            OpenAI client for SQL generation
        llm : str
            LLM model to use
        dialect : str
            SQL dialect
        """
        self.semantic_mcp_server_path = semantic_mcp_server_path
        self.full_schema_retriever = full_schema_retriever
        self.bq_client = bq_client
        self.llm_client = llm_client
        self.llm = llm
        self.dialect = dialect

        self.token_measurer = ContextTokenMeasurement(model=llm)

        # Full schema as string (for token counting and LLM context)
        self.full_schema_str = self.full_schema_retriever.as_string()
        self.full_schema_contexts = self.full_schema_retriever.as_table_contexts()

    async def run_semantic_condition(
        self,
        sample: EvalSample,
        mcp_session: ClientSession,
    ) -> dict[str, Any]:
        """
        Run the semantic condition for a sample.

        The LLM agent has access to MCP tools and retrieves what it needs.

        Parameters
        ----------
        sample : EvalSample
            Evaluation sample
        mcp_session : ClientSession
            Active MCP session

        Returns:
        -------
        dict
            Results for semantic condition
        """
        t0 = time.monotonic()

        # Step 1: Agent retrieves relevant schema using MCP tool
        t_mcp_start = time.monotonic()
        result = await mcp_session.call_tool(
            "get_context_by_schema_and_table_vector_search",
            arguments={"query": sample.nl_question, "max_tables": 2},
        )
        mcp_latency_ms = (time.monotonic() - t_mcp_start) * 1000

        # Parse retrieved contexts
        retrieved_contexts = []
        for item in result.content:
            if hasattr(item, "text"):
                data = json.loads(item.text)
                if isinstance(data, list):
                    retrieved_contexts = [TableContext.model_validate(t) for t in data]
                else:
                    retrieved_contexts = [TableContext.model_validate(data)]

        # Step 2: Serialize contexts for LLM
        context_strings = serialize_table_contexts(retrieved_contexts)
        context_str = "\n\n".join(context_strings)

        # Step 3: LLM generates SQL
        t_llm_start = time.monotonic()
        response = await self.llm_client.chat.completions.create(
            model=self.llm,
            messages=[
                {"role": "system", "content": system_prompt},
                {
                    "role": "user",
                    "content": user_prompt.format(
                        schema_context=context_str, question=sample.nl_question
                    ),
                },
            ],
            temperature=0.0,  # Deterministic
        )
        llm_latency_ms = (time.monotonic() - t_llm_start) * 1000

        generated_sql = response.choices[0].message.content.strip()

        # Remove markdown code blocks if present
        if generated_sql.startswith("```"):
            lines = generated_sql.split("\n")
            generated_sql = "\n".join(lines[1:-1]) if len(lines) > 2 else generated_sql
            generated_sql = generated_sql.strip()

        latency_ms = (time.monotonic() - t0) * 1000

        return {
            "retrieved_contexts": retrieved_contexts,
            "generated_sql": generated_sql,
            "latency_ms": latency_ms,
            "mcp_latency_ms": mcp_latency_ms,
            "llm_latency_ms": llm_latency_ms,
            "llm": self.llm,
            "context_str": context_str,
            "context_strings": context_strings,
        }

    async def run_full_schema_condition(
        self,
        sample: EvalSample,
    ) -> dict[str, Any]:
        """
        Run the full_schema condition for a sample.

        The LLM gets the entire BigQuery schema as context.

        Parameters
        ----------
        sample : EvalSample
            Evaluation sample

        Returns:
        -------
        dict
            Results for full_schema condition
        """
        t0 = time.monotonic()

        # Serialize full schema for LLM
        context_strings = serialize_table_contexts(self.full_schema_contexts)
        context_str = "\n\n".join(context_strings)

        # LLM generates SQL with full schema
        t_llm_start = time.monotonic()
        response = await self.llm_client.chat.completions.create(
            model=self.llm,
            messages=[
                {"role": "system", "content": system_prompt},
                {
                    "role": "user",
                    "content": user_prompt.format(
                        schema_context=context_str, question=sample.nl_question
                    ),
                },
            ],
            temperature=0.0,
        )
        llm_latency_ms = (time.monotonic() - t_llm_start) * 1000

        generated_sql = response.choices[0].message.content.strip()

        # Remove markdown code blocks if present
        if generated_sql.startswith("```"):
            lines = generated_sql.split("\n")
            generated_sql = "\n".join(lines[1:-1]) if len(lines) > 2 else generated_sql
            generated_sql = generated_sql.strip()

        latency_ms = (time.monotonic() - t0) * 1000

        return {
            "generated_sql": generated_sql,
            "latency_ms": latency_ms,
            "llm_latency_ms": llm_latency_ms,
            "llm": self.llm,
            "context_str": context_str,
            "context_strings": context_strings,
        }

    async def run_eval(self, samples: list[EvalSample]) -> list[EvalSample]:
        """
        Run evaluation on all samples.

        Parameters
        ----------
        samples : list[EvalSample]
            Evaluation samples

        Returns:
        -------
        list[EvalSample]
            Samples with results populated
        """
        # Start MCP server session
        server_params = StdioServerParameters(
            command="uv",
            args=["run", self.semantic_mcp_server_path],
        )

        async with stdio_client(server_params) as (read, write):
            async with ClientSession(read, write) as mcp_session:
                await mcp_session.initialize()

                for i, sample in enumerate(samples):
                    print(
                        f"\n[{i + 1}/{len(samples)}] Evaluating {sample.question_id}: {sample.nl_question}"
                    )

                    # Run semantic condition
                    print("  Running semantic condition...")
                    sem_result = await self.run_semantic_condition(sample, mcp_session)

                    # Run full schema condition
                    print("  Running full_schema condition...")
                    fs_result = await self.run_full_schema_condition(sample)

                    # Score both conditions
                    print("  Scoring results...")
                    self._score_sample(sample, sem_result, fs_result)

                    print(
                        f"  ✓ Semantic SQL generated in {sem_result['latency_ms']:.0f}ms "
                        f"(MCP: {sem_result['mcp_latency_ms']:.0f}ms, LLM: {sem_result['llm_latency_ms']:.0f}ms)"
                    )
                    print(
                        f"  ✓ Full schema SQL generated in {fs_result['latency_ms']:.0f}ms "
                        f"(LLM: {fs_result['llm_latency_ms']:.0f}ms)"
                    )

        return samples

    def _score_sample(
        self,
        sample: EvalSample,
        sem_result: dict,
        fs_result: dict,
    ) -> None:
        """Score a single sample and populate results."""
        # Semantic condition results
        sem = sample.results_by_condition["semantic"]
        sem["retrieved_contexts"] = sem_result["retrieved_contexts"]
        sem["generated_sql"] = sem_result["generated_sql"]
        sem["latency_ms"] = sem_result["latency_ms"]
        sem["mcp_latency_ms"] = sem_result["mcp_latency_ms"]
        sem["llm_latency_ms"] = sem_result["llm_latency_ms"]
        sem["llm"] = sem_result["llm"]

        # Token metrics
        sem["tokens"] = self.token_measurer.measure(
            mcp_chunks=sem_result["context_strings"],
            full_schema_str=self.full_schema_str,
        )

        # Structural equivalence
        sem["structural"] = score_structural_equivalence(
            sem["generated_sql"],
            sample.ground_truth_sql,
            self.dialect,
        )

        # Faithfulness
        sem["faithfulness"] = score_schema_faithfulness(
            sem["generated_sql"],
            sem_result["context_strings"],
            self.dialect,
        )

        # Execution accuracy
        sem["execution"] = score_execution_accuracy(
            sem["generated_sql"],
            sample.ground_truth_sql,
            self.bq_client,
        )

        # Retrieval metrics
        retrieval_scores = score_retrieval(
            sem_result["retrieved_contexts"],
            sample.required_objects,
        )
        sample.context_precision = retrieval_scores["object_precision"]
        sample.context_recall = retrieval_scores["object_recall"]
        sample.object_recall = retrieval_scores["object_recall"]

        # Full schema condition results
        fs = sample.results_by_condition["full_schema"]
        fs["generated_sql"] = fs_result["generated_sql"]
        fs["latency_ms"] = fs_result["latency_ms"]
        fs["llm_latency_ms"] = fs_result["llm_latency_ms"]
        fs["llm"] = fs_result["llm"]

        fs["tokens"] = self.token_measurer.measure(
            mcp_chunks=[],
            full_schema_str=self.full_schema_str,
        )

        fs["structural"] = score_structural_equivalence(
            fs["generated_sql"],
            sample.ground_truth_sql,
            self.dialect,
        )

        fs["execution"] = score_execution_accuracy(
            fs["generated_sql"],
            sample.ground_truth_sql,
            self.bq_client,
        )
