"""Unit tests for ``neocarta tool <tool>`` — the MCP tools mirrored on the CLI.

These cover CLI plumbing only (the live Cypher/Neo4j behaviour is exercised by
the MCP integration suite): the command tree and --help shape, the mirrored
argument defaults, the success envelope, embedding/credential failures, and
library- and driver-error → exit-code routing.
"""

import json
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest
from click.testing import CliRunner
from neo4j import RoutingControl
from neo4j.exceptions import AuthError as Neo4jAuthError
from neo4j.exceptions import ClientError

from neocarta._cli import cli
from neocarta._cli.commands.tool import _emit
from neocarta._cli.errors import EXIT_CODES
from neocarta.errors import (
    AuthError,
    ConfigError,
    Neo4jConnectionError,
    NeocartaError,
    RateLimitError,
)

# The full set of tool commands the group must expose (kebab-cased tool names).
_TOOL_COMMANDS = [
    "list-schemas",
    "list-tables-by-schema",
    "get-full-metadata-schema",
    "get-context-by-column-vector-search",
    "get-context-by-table-vector-search",
    "get-context-by-schema-and-table-vector-search",
    "get-context-by-table-full-text-search",
    "get-context-by-column-full-text-search",
    "get-context-by-table-hybrid-search",
    "get-context-by-column-hybrid-search",
    "get-context-by-table-business-term-hybrid-search",
    "get-context-by-column-business-term-hybrid-search",
]

# A minimal valid TableContext payload as the search/full-metadata cypher returns it.
_TABLE_ROW = {
    "result": {
        "table_name": "orders",
        "table_description": "Orders placed by customers",
        "database_name": "my-db",
        "schema_name": "sales",
        "columns": [],
    }
}


@pytest.fixture
def _cli_env(monkeypatch):
    """Populate the Neo4j env vars every tool command needs to start."""
    monkeypatch.setenv("NEO4J_URI", "bolt://localhost:7687")
    monkeypatch.setenv("NEO4J_USERNAME", "neo4j")
    monkeypatch.setenv("NEO4J_PASSWORD", "password")


def _mock_driver(monkeypatch_target="neocarta._cli.commands.tool._neo4j_driver"):
    """Return a ``patch`` for the sync driver context manager yielding a MagicMock driver."""
    return patch(monkeypatch_target)


def _bind(mock_driver_ctx):
    """Wire a patched ``_neo4j_driver`` to yield (and return) a fresh MagicMock driver."""
    driver = MagicMock()
    mock_driver_ctx.return_value.__enter__.return_value = driver
    mock_driver_ctx.return_value.__exit__.return_value = False
    return driver


# --------------------------------------------------------------------------- #
# command tree / --help
# --------------------------------------------------------------------------- #
def test_group_help_lists_every_tool_command():
    result = CliRunner().invoke(cli, ["tool", "--help"])
    assert result.exit_code == 0
    for name in _TOOL_COMMANDS:
        assert name in result.output, f"`tool --help` should list {name}"


def test_search_command_help_documents_mirrored_args_and_docstring():
    result = CliRunner().invoke(cli, ["tool", "get-context-by-table-vector-search", "--help"])
    assert result.exit_code == 0
    for token in ("--text-content", "--max-tables", "--search-top-k"):
        assert token in result.output, f"--help should document {token}"
    # Documentation is mirrored from the MCP tool docstring.
    assert "semantically similar to the provided text" in result.output


def test_list_tables_help_documents_schema_name_and_omits_search_args():
    result = CliRunner().invoke(cli, ["tool", "list-tables-by-schema", "--help"])
    assert result.exit_code == 0
    assert "--schema-name" in result.output
    assert "--max-tables" not in result.output
    assert "--text-content" not in result.output


def test_list_schemas_help_has_no_search_args():
    result = CliRunner().invoke(cli, ["tool", "list-schemas", "--help"])
    assert result.exit_code == 0
    assert "--text-content" not in result.output
    assert "--max-tables" not in result.output


# --------------------------------------------------------------------------- #
# missing required input → usage_error (exit 2)
# --------------------------------------------------------------------------- #
def test_missing_neo4j_settings_fails_with_usage_error(monkeypatch):
    # python-dotenv would otherwise load the repo's own .env, so stub it out.
    monkeypatch.setattr("neocarta._cli.config.load_dotenv", lambda *_a, **_kw: None)
    for key in ("NEO4J_URI", "NEO4J_USERNAME", "NEO4J_PASSWORD"):
        monkeypatch.delenv(key, raising=False)
    result = CliRunner().invoke(cli, ["--json", "tool", "list-schemas"])
    assert result.exit_code == 2, result.stdout + result.stderr
    payload = json.loads(result.stdout)
    assert payload["error"]["code"] == "usage_error"
    assert "neo4j" in payload["error"]["message"].lower()


def test_search_missing_text_content_fails_with_usage_error():
    # --text-content is required *before* any settings/Neo4j work.
    result = CliRunner().invoke(cli, ["--json", "tool", "get-context-by-table-vector-search"])
    assert result.exit_code == 2, result.stdout + result.stderr
    payload = json.loads(result.stdout)
    assert payload["error"]["code"] == "usage_error"
    assert "text-content" in payload["error"]["message"].lower()


@pytest.mark.usefixtures("_cli_env")
def test_list_tables_missing_schema_name_fails_with_usage_error():
    result = CliRunner().invoke(cli, ["--json", "tool", "list-tables-by-schema"])
    assert result.exit_code == 2, result.stdout + result.stderr
    payload = json.loads(result.stdout)
    assert payload["error"]["code"] == "usage_error"
    assert "schema-name" in payload["error"]["message"].lower()


# --------------------------------------------------------------------------- #
# success envelopes
# --------------------------------------------------------------------------- #
@pytest.mark.usefixtures("_cli_env")
def test_list_schemas_success_envelope():
    rows = [
        {"database_name": "my-db", "schema_name": "sales"},
        {"database_name": "my-db", "schema_name": "analytics"},
    ]
    with _mock_driver() as mock_driver_ctx:
        driver = _bind(mock_driver_ctx)
        driver.execute_query.return_value = rows
        result = CliRunner().invoke(cli, ["--json", "tool", "list-schemas"])
    assert result.exit_code == 0, result.output
    out = result.output
    body = json.loads(out[out.index("{") :])["tool_list_schemas"]
    assert body["tool"] == "list_schemas"
    assert body["count"] == 2
    assert body["results"] == rows


@pytest.mark.usefixtures("_cli_env")
def test_list_tables_by_schema_success_echoes_schema_name():
    rows = [{"schema_name": "sales", "table_names": ["orders", "customers"]}]
    with _mock_driver() as mock_driver_ctx:
        driver = _bind(mock_driver_ctx)
        driver.execute_query.return_value = rows
        result = CliRunner().invoke(
            cli, ["--json", "tool", "list-tables-by-schema", "--schema-name", "sales"]
        )
    assert result.exit_code == 0, result.output
    out = result.output
    body = json.loads(out[out.index("{") :])["tool_list_tables_by_schema"]
    assert body["schema_name"] == "sales"
    assert body["results"] == rows
    # count reflects the number of TABLES, not the single aggregated collect() row.
    assert body["count"] == 2
    # The query is parameterised on the schema name.
    assert driver.execute_query.call_args.kwargs["parameters_"] == {"schemaName": "sales"}


@pytest.mark.usefixtures("_cli_env")
def test_table_vector_search_success_envelope_and_sync_embed():
    with (
        _mock_driver() as mock_driver_ctx,
        patch("neocarta._cli.commands.tool._build_embedder") as mock_build,
    ):
        driver = _bind(mock_driver_ctx)
        driver.execute_query.return_value = [_TABLE_ROW]
        embedder = MagicMock()
        embedder._create_embedding_sync.return_value = [0.1, 0.2, 0.3]
        mock_build.return_value = embedder

        result = CliRunner().invoke(
            cli,
            ["--json", "tool", "get-context-by-table-vector-search", "--text-content", "orders"],
        )

    assert result.exit_code == 0, result.output
    out = result.output
    body = json.loads(out[out.index("{") :])["tool_get_context_by_table_vector_search"]
    assert body["tool"] == "get_context_by_table_vector_search"
    assert body["text_content"] == "orders"
    assert body["count"] == 1
    assert body["results"][0]["table_name"] == "orders"
    # The CLI uses the *sync* embedding path, never the async one.
    embedder._create_embedding_sync.assert_called_once_with("orders")
    embedder._create_embedding_async.assert_not_called()
    # The embedding is forwarded to the query.
    assert driver.execute_query.call_args.kwargs["parameters_"]["queryEmbedding"] == [0.1, 0.2, 0.3]


@pytest.mark.parametrize(
    ("command", "expected_max_tables", "expected_search_top_k"),
    [
        ("get-context-by-table-vector-search", 10, 10),
        ("get-context-by-column-vector-search", 5, 10),
        ("get-context-by-schema-and-table-vector-search", 5, 5),
        ("get-context-by-table-full-text-search", 10, 10),
        ("get-context-by-column-full-text-search", 5, 10),
        ("get-context-by-table-hybrid-search", 5, 10),
        ("get-context-by-column-hybrid-search", 5, 10),
        ("get-context-by-table-business-term-hybrid-search", 5, 10),
        ("get-context-by-column-business-term-hybrid-search", 5, 10),
    ],
)
@pytest.mark.usefixtures("_cli_env")
def test_search_default_arg_matrix_is_mirrored(command, expected_max_tables, expected_search_top_k):
    """Each command must forward the exact per-tool max_tables / search_top_k defaults."""
    with (
        _mock_driver() as mock_driver_ctx,
        patch("neocarta._cli.commands.tool._build_embedder") as mock_build,
    ):
        driver = _bind(mock_driver_ctx)
        driver.execute_query.return_value = []
        embedder = MagicMock()
        embedder._create_embedding_sync.return_value = [0.1]
        mock_build.return_value = embedder

        result = CliRunner().invoke(cli, ["tool", command, "--text-content", "x"])

    assert result.exit_code == 0, result.output
    params = driver.execute_query.call_args.kwargs["parameters_"]
    assert params["maxTables"] == expected_max_tables
    assert params["searchTopK"] == expected_search_top_k


@pytest.mark.usefixtures("_cli_env")
def test_full_text_search_sanitises_lucene_and_skips_embedding():
    with (
        _mock_driver() as mock_driver_ctx,
        patch("neocarta._cli.commands.tool._build_embedder") as mock_build,
    ):
        driver = _bind(mock_driver_ctx)
        driver.execute_query.return_value = []
        result = CliRunner().invoke(
            cli,
            ["tool", "get-context-by-table-full-text-search", "--text-content", "a:b* (c)"],
        )
    assert result.exit_code == 0, result.output
    params = driver.execute_query.call_args.kwargs["parameters_"]
    # Lucene special chars are stripped; no embedding is computed for full-text search.
    assert ":" not in params["queryText"]
    assert "*" not in params["queryText"]
    assert "queryEmbedding" not in params
    mock_build.assert_not_called()


# --------------------------------------------------------------------------- #
# failure routing
# --------------------------------------------------------------------------- #
@pytest.mark.usefixtures("_cli_env")
def test_embedding_failure_maps_to_upstream_error():
    with (
        _mock_driver() as mock_driver_ctx,
        patch("neocarta._cli.commands.tool._build_embedder") as mock_build,
    ):
        _bind(mock_driver_ctx)
        embedder = MagicMock()
        embedder._create_embedding_sync.return_value = None  # provider failure is swallowed to None
        mock_build.return_value = embedder
        result = CliRunner().invoke(
            cli, ["tool", "get-context-by-table-vector-search", "--text-content", "orders"]
        )
    assert result.exit_code == EXIT_CODES["upstream_error"]["code"]


@pytest.mark.usefixtures("_cli_env")
def test_missing_search_index_maps_to_not_found():
    with _mock_driver() as mock_driver_ctx:
        driver = _bind(mock_driver_ctx)
        driver.execute_query.side_effect = ClientError(
            "There is no such fulltext schema index: table_full_text_index"
        )
        result = CliRunner().invoke(
            cli, ["tool", "get-context-by-table-full-text-search", "--text-content", "orders"]
        )
    assert result.exit_code == EXIT_CODES["not_found"]["code"], result.output


@pytest.mark.parametrize(
    ("error", "expected_exit_code"),
    [
        (ConfigError("bad config"), EXIT_CODES["validation_error"]["code"]),
        (AuthError("bad credentials"), EXIT_CODES["auth_error"]["code"]),
        (RateLimitError("quota exceeded"), EXIT_CODES["rate_limited"]["code"]),
        (Neo4jConnectionError("cannot reach neo4j"), EXIT_CODES["upstream_error"]["code"]),
    ],
)
@pytest.mark.usefixtures("_cli_env")
def test_library_errors_route_to_exit_codes(error: NeocartaError, expected_exit_code: int):
    """A NeocartaError surfacing from the query is mapped via cli_error_from."""
    with _mock_driver() as mock_driver_ctx:
        driver = _bind(mock_driver_ctx)
        driver.execute_query.side_effect = error
        result = CliRunner().invoke(cli, ["tool", "list-schemas"])
    assert result.exit_code == expected_exit_code, (
        f"{type(error).__name__} should exit {expected_exit_code}, got {result.exit_code}."
    )


# --------------------------------------------------------------------------- #
# agent-context introspection
# --------------------------------------------------------------------------- #
def test_agent_context_enumerates_tool_commands():
    result = CliRunner().invoke(cli, ["agent-context"])
    assert result.exit_code == 0
    payload = json.loads(result.output)
    assert "tool" in payload["commands"]
    subcommands = payload["commands"]["tool"]["subcommands"]
    for name in _TOOL_COMMANDS:
        assert name in subcommands, f"agent-context should enumerate tool {name}"
    # A search command advertises its mirrored text arg and the table-vector defaults. Like the
    # connector commands, --text-content is validated via require() (not Click `required=True`)
    # so the missing-value case yields the structured usage_error envelope.
    flags = subcommands["get-context-by-table-vector-search"]["flags"]
    assert "--text-content" in flags
    assert flags["--max-tables"]["default"] == 10
    assert flags["--search-top-k"]["default"] == 10
    # Catalog commands carry no search args.
    assert "--text-content" not in subcommands["list-schemas"].get("flags", {})


# --------------------------------------------------------------------------- #
# embed / lucene branch wiring (the distinguishing logic of each search tier)
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize(
    ("command", "embed", "lucene"),
    [
        ("get-context-by-table-vector-search", True, False),
        ("get-context-by-column-vector-search", True, False),
        ("get-context-by-schema-and-table-vector-search", True, False),
        ("get-context-by-table-full-text-search", False, True),
        ("get-context-by-column-full-text-search", False, True),
        ("get-context-by-table-hybrid-search", True, True),
        ("get-context-by-column-hybrid-search", True, True),
        ("get-context-by-table-business-term-hybrid-search", True, True),
        ("get-context-by-column-business-term-hybrid-search", True, True),
    ],
)
@pytest.mark.usefixtures("_cli_env")
def test_search_embed_and_lucene_wiring_per_command(command, embed, lucene):
    """queryEmbedding is present iff the tier embeds; queryText iff it uses full-text."""
    with (
        _mock_driver() as mock_driver_ctx,
        patch("neocarta._cli.commands.tool._build_embedder") as mock_build,
    ):
        driver = _bind(mock_driver_ctx)
        driver.execute_query.return_value = []
        embedder = MagicMock()
        embedder._create_embedding_sync.return_value = [0.1]
        mock_build.return_value = embedder
        result = CliRunner().invoke(cli, ["tool", command, "--text-content", "orders"])

    assert result.exit_code == 0, result.output
    params = driver.execute_query.call_args.kwargs["parameters_"]
    assert ("queryEmbedding" in params) is embed
    assert ("queryText" in params) is lucene
    # The embedder is built only when the tier embeds.
    assert mock_build.called is embed


@pytest.mark.usefixtures("_cli_env")
def test_read_query_uses_read_routing_and_configured_database(monkeypatch):
    """Every tool issues a READ query against the configured database."""
    monkeypatch.setenv("NEO4J_DATABASE", "custom_db")
    with _mock_driver() as mock_driver_ctx:
        driver = _bind(mock_driver_ctx)
        driver.execute_query.return_value = []
        result = CliRunner().invoke(cli, ["tool", "list-schemas"])
    assert result.exit_code == 0, result.output
    kwargs = driver.execute_query.call_args.kwargs
    assert kwargs["routing_"] is RoutingControl.READ
    assert kwargs["database_"] == "custom_db"
    assert callable(kwargs["result_transformer_"])


# --------------------------------------------------------------------------- #
# get-full-metadata-schema (the as_table_context path) + TableContext validation
# --------------------------------------------------------------------------- #
_RICH_TABLE_ROW = {
    "result": {
        "table_name": "orders",
        "table_description": "Orders",
        "database_name": "my-db",
        "schema_name": "sales",
        "columns": [
            {
                "column_name": "order_id",
                "data_type": "STRING",
                "nullable": False,
                "key_type": "primary",
                "references": [],
            }
        ],
        "table_score": 0.9,
    }
}


@pytest.mark.usefixtures("_cli_env")
def test_get_full_metadata_schema_validates_table_contexts():
    with _mock_driver() as mock_driver_ctx:
        driver = _bind(mock_driver_ctx)
        driver.execute_query.return_value = [_TABLE_ROW, _RICH_TABLE_ROW]
        result = CliRunner().invoke(cli, ["--json", "tool", "get-full-metadata-schema"])
    assert result.exit_code == 0, result.output
    out = result.output
    body = json.loads(out[out.index("{") :])["tool_get_full_metadata_schema"]
    assert body["tool"] == "get_full_metadata_schema"
    assert body["count"] == 2
    # Nested ColumnContext is serialised through the model.
    assert body["results"][1]["columns"][0]["column_name"] == "order_id"


@pytest.mark.usefixtures("_cli_env")
def test_malformed_graph_row_maps_to_upstream_error():
    """A row that fails TableContext validation must not leak a raw traceback."""
    with _mock_driver() as mock_driver_ctx:
        driver = _bind(mock_driver_ctx)
        # Missing required database_name / schema_name / columns.
        driver.execute_query.return_value = [{"result": {"table_name": "x"}}]
        result = CliRunner().invoke(cli, ["tool", "get-full-metadata-schema"])
    assert result.exit_code == EXIT_CODES["upstream_error"]["code"], result.output


# --------------------------------------------------------------------------- #
# raw neo4j error mapping (_map_neo4j_error) + empty-after-lucene guard
# --------------------------------------------------------------------------- #
@pytest.mark.usefixtures("_cli_env")
def test_raw_neo4j_auth_error_maps_to_auth_error():
    with _mock_driver() as mock_driver_ctx:
        driver = _bind(mock_driver_ctx)
        driver.execute_query.side_effect = Neo4jAuthError("authentication failure")
        result = CliRunner().invoke(cli, ["tool", "list-schemas"])
    assert result.exit_code == EXIT_CODES["auth_error"]["code"], result.output


@pytest.mark.usefixtures("_cli_env")
def test_generic_client_error_maps_to_upstream_error():
    with _mock_driver() as mock_driver_ctx:
        driver = _bind(mock_driver_ctx)
        driver.execute_query.side_effect = ClientError("some unrelated client error")
        result = CliRunner().invoke(cli, ["tool", "list-schemas"])
    assert result.exit_code == EXIT_CODES["upstream_error"]["code"], result.output


@pytest.mark.usefixtures("_cli_env")
def test_full_text_query_reduced_to_empty_is_usage_error():
    """A query of only Lucene special chars sanitises to empty -> structured usage_error."""
    with _mock_driver() as mock_driver_ctx:
        _bind(mock_driver_ctx)
        result = CliRunner().invoke(
            cli,
            ["--json", "tool", "get-context-by-table-full-text-search", "--text-content", ":*()~"],
        )
    assert result.exit_code == 2, result.stdout + result.stderr
    payload = json.loads(result.stdout)
    assert payload["error"]["code"] == "usage_error"


# --------------------------------------------------------------------------- #
# output path + cypher-builder resolution
# --------------------------------------------------------------------------- #
def test_emit_human_path_prints_envelope():
    """When not in JSON mode, _emit renders the tool_<tool> envelope via Rich stdout."""
    stdout = MagicMock()
    ctx = SimpleNamespace(obj={"as_json": False, "stdout": stdout})
    body = {"tool": "list_schemas", "count": 0, "results": []}
    _emit(ctx, tool="list_schemas", json_flag=False, body=body)
    stdout.print.assert_called_once_with({"tool_list_schemas": body})


def test_every_command_resolves_a_cypher_builder():
    """The _cypher(tool) getattr lookup must resolve for all 12 mirrored tools."""
    from neocarta._mcp import cypher

    for name in _TOOL_COMMANDS:
        tool = name.replace("-", "_")
        builder = getattr(cypher, f"{tool}_cypher", None)
        assert callable(builder), f"missing cypher builder for {tool}"
        cypher_str = builder()
        assert isinstance(cypher_str, str), f"cypher for {tool} is not a str"
        assert cypher_str.strip(), f"empty cypher for {tool}"
