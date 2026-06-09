<#ftl output_format="plainText" strip_whitespace=true>
<#--
  SchemaCrawler FreeMarker template: renders the crawled catalog as the compact
  JSON shape that JdbcSchemaExtractor parses. Unlike `--command=serialize`, the
  template has full access to the catalog model, so it can emit tables, primary
  keys, and foreign-key source -> target references (which serialize omits).

  Invoked by the connector as:
    schemacrawler.Main --command=template --templating-language=freemarker \
        --template=<this file>
  Requires a FreeMarker JAR on the SchemaCrawler classpath (see the connector README).

  Only imported foreign keys are emitted (one row per FK column reference) so each
  relationship appears exactly once.
-->
<#assign fkrefs = []>
<#list catalog.tables as t>
  <#list t.importedForeignKeys as fk>
    <#list fk.columnReferences as ref>
      <#assign fkrefs = fkrefs + [ref]>
    </#list>
  </#list>
</#list>
{
"schemas": [<#list catalog.schemas as s>{"name": "${((s.name)!"")?json_string}", "remarks": "${((s.remarks)!"")?json_string}"}<#sep>,</#sep></#list>],
"tables": [<#list catalog.tables as t>{"schema": "${((t.schema.name)!"")?json_string}", "name": "${((t.name)!"")?json_string}", "remarks": "${((t.remarks)!"")?json_string}", "columns": [<#list t.columns as c>{"name": "${((c.name)!"")?json_string}", "type": "${((c.columnDataType.name)!"")?json_string}", "nullable": ${(c.nullable!false)?c}, "remarks": "${((c.remarks)!"")?json_string}", "is_primary_key": ${(c.partOfPrimaryKey!false)?c}, "is_foreign_key": ${(c.partOfForeignKey!false)?c}}<#sep>,</#sep></#list>]}<#sep>,</#sep></#list>],
"foreign_keys": [<#list fkrefs as ref>{"source_schema": "${((ref.foreignKeyColumn.parent.schema.name)!"")?json_string}", "source_table": "${((ref.foreignKeyColumn.parent.name)!"")?json_string}", "source_column": "${((ref.foreignKeyColumn.name)!"")?json_string}", "target_schema": "${((ref.primaryKeyColumn.parent.schema.name)!"")?json_string}", "target_table": "${((ref.primaryKeyColumn.parent.name)!"")?json_string}", "target_column": "${((ref.primaryKeyColumn.name)!"")?json_string}"}<#sep>,</#sep></#list>]
}
