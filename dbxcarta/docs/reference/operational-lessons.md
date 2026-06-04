# Operational lessons

## Dropping a data catalog on a Default-Storage account is not round-trippable through the tooling

On 2026-06-03, clearing the example catalogs for a pipeline re-run surfaced a gap. `dbxcarta-submit teardown` dropped the dense and schemapile data catalogs with `DROP CATALOG ... CASCADE`, but the follow-up `dbxcarta-submit bootstrap` could not recreate them. This workspace runs on a Databricks account with Default Storage enabled and no metastore storage root URL. On such an account, a SQL `CREATE CATALOG` without an explicit `MANAGED LOCATION` fails, and the Unity Catalog catalogs API fails the same way. `bootstrap`'s `ensure_uc_catalog` only runs `CREATE CATALOG` when the catalog is missing, so it works for an existing catalog by skipping the create, but it cannot rebuild one that was dropped.

What this means in practice:

- `teardown` of a data catalog is effectively irreversible from the CLI on this account. Recreating the catalog requires the Databricks UI "Default Storage" flow, or a `CREATE CATALOG ... MANAGED LOCATION` pointed at a real storage location.
- Ops schemas are safe to drop and recreate. `bootstrap` rebuilds the ops schema and volume inside the shared `dbxcarta-catalog`, which is never dropped.
- finance-genie was unaffected. Its teardown target is ops only, so its data catalog stayed in place and bootstrap took the skip path.

Guidance:

- Do not run `teardown` against a data catalog on a Default-Storage account unless you are prepared to recreate that catalog in the UI. Prefer clearing schema and table contents over dropping the catalog itself.
- Follow-up worth making: give `bootstrap` a managed-location or default-storage create path so that teardown plus bootstrap is genuinely round-trippable, matching the Phase 1 intent recorded in `planner.md`.
