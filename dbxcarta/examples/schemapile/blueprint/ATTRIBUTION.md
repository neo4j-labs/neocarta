# Attribution

`candidates_random_1000.json` is a curated derivative slice of
[SchemaPile](https://github.com/amsterdata/schemapile), specifically its
permissively licensed subset SchemaPile-Perm. The file selects a small set of
schemas from that corpus and reshapes them into dbxcarta's candidate-table
blueprint format. It is not the original SchemaPile dataset.

## License

Every schema in SchemaPile-Perm is permissively licensed: about 92% under MIT or
Apache-2.0, the remainder under BSD, Unlicense, or CC0. There is no share-alike
clause and no non-commercial restriction, and personally identifying data was
imputed upstream. The one obligation carried forward is this attribution.

## Provenance

Each schema entry keeps its upstream `source_id` (for example
`492424_create-adventuresOverflow.sql`), the identifier SchemaPile assigns to the
originating SQL file. That identifier preserves the link from each schema in this
slice back to its source in the SchemaPile corpus.
