# Changelog of neocarta library

## Upcoming

### Fixed
* Add column data types `["GEOGRAPHY", "JSON", "BIGNUMERIC"]` to skipped list for `Value` node creation. These types will throw an error otherwise.
* Implement `generate_*_id` functions for all ID generation tasks
* Fixed bug where value retrieval would yield empty arrays when all values in column are `NULL`
* Fixed bug where `description='false'` when querying table info due to inaccurate `INFORMATION_SCHEMA.TABLE_OPTIONS` filtering
* Update agent code to use new MCP configuration
* Fixed query parser reading CTEs as real tables
* Fixed query parser reading `.*` projections as a real column named `*`
* Fixed query parser reading self referential joins as real FKs

### Changed
* Replace `RESOLVES_TO` relationship with `TAGGED_WITH` across RDBMS and LPG data models

### Added
* Add `TAGGED_WITH` relationship type to `RelationshipType` enum
* Add `TaggedWith` model to RDBMS expanded data model
* Add `extract_entry_links()` to `DataplexExtractor` — retrieves `TAGGED_WITH` links between BigQuery columns/tables and Dataplex glossary terms via the `lookupEntryLinks` REST API
* Add `transform_to_column_tagged_with_relationships()` and `transform_to_table_tagged_with_relationships()` to `DataplexTransformer`
* Add `load_column_tagged_with_relationships()` and `load_table_tagged_with_relationships()` to Neo4j loader
* `DataplexConnector` now creates `(:Column)-[:TAGGED_WITH]->(:BusinessTerm)` and `(:Table)-[:TAGGED_WITH]->(:BusinessTerm)` relationships when both `include_schema` and `include_glossary` are enabled
* Add acme dataset and update example dataset loader function to accomodate ecommerce and acme datasets
* Add `CTE` node to capture CTEs from queries 
* Add `(:Query)-[:DEFINES]->(:CTE)` relationship

## v0.2.1

### Fixed
* Remove duplicated docstrings in MCP server

### Added
* Update MCP documentation

## v0.2.0

### Changed
* Move MCP server to `neocarta` library
* Change MCP server name to `neocarta-mcp`
* Update MCP server imports in `eval/` module
* Deduplicate embedding code in MCP server. MCP server now uses `neocarta` embeddings class.
* Update Cypher queries in MCP server to follow same traversal patterns and return similar objects
* Update MCP tool documentation
* Lock `fastmcp` version <3.x

### Added
* Add integration tests for MCP server compatibility with neocarta graph
* Add `get_metadata_schema_by_table_semantic_similarity` tool to MCP server
* Add instructions to MCP server so agents are better able to utilize the tooling

## v0.1.0

Initial release