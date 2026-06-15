# Metadata Data Model

Graph-level bookkeeping that is not tied to any particular source type.

Nodes
* [`NeocartaGraph`](./models.py)
    * A singleton node (label `__neocarta_graph__`) describing the
      Neocarta-managed graph
    * Tracks the `neocarta` library versions that wrote to the graph
      (`initial_version`, `latest_version`) and `create_date` / `last_updated`
      timestamps
    * Used by the MCP server to detect mismatches between the writer and reader
      library versions
