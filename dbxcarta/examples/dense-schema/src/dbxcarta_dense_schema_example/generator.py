"""Generate a synthetic dense-schema fixture for dbxcarta Phase G evaluation.

Produces a candidates.json file compatible with the schemapile materializer
format. The schema has `table_count` tables (500 or 1000) organized into 10
functional domains with a dense within-domain FK web and sparse cross-domain
connections through shared anchor tables.

Usage:
    uv run dbxcarta-dense-generate --tables 500 --schema dense_500
    uv run dbxcarta-dense-generate --tables 1000 --schema dense-1000
"""

from __future__ import annotations

import argparse
import json
import random
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from faker import Faker

_SUPPORTED_COUNTS = (500, 1000)
_ROWS_PER_TABLE = 10
_CANDIDATE_FORMAT_VERSION = 2
_TERMS_PER_DOMAIN = 10

_ANALYTICS_SUFFIXES = [
    "daily_metrics",
    "weekly_stats",
    "monthly_kpis",
    "quarterly_reports",
    "annual_summaries",
    "trending_data",
    "benchmark_data",
    "forecast_metrics",
    "anomaly_flags",
    "performance_index",
]

# 10 domains with larger entity/event pools. Each generated fixture samples
# 10 entities and 10 events per domain, preserving required FK anchor terms.
_DOMAIN_SPECS: dict[str, dict[str, list[str]]] = {
    "hr": {
        "entities": [
            "employees",
            "departments",
            "positions",
            "locations",
            "cost_centers",
            "job_grades",
            "employment_types",
            "work_schedules",
            "skill_categories",
            "benefit_plans",
            "pay_bands",
            "certifications",
            "office_sites",
            "manager_groups",
            "recruiting_sources",
            "onboarding_tracks",
        ],
        "events": [
            "payroll_runs",
            "leave_requests",
            "performance_reviews",
            "training_sessions",
            "job_applications",
            "disciplinary_actions",
            "expense_reports",
            "time_entries",
            "employee_transfers",
            "exit_interviews",
            "offer_approvals",
            "compensation_changes",
            "succession_reviews",
            "workplace_incidents",
            "policy_acknowledgements",
        ],
    },
    "crm": {
        "entities": [
            "customers",
            "contacts",
            "companies",
            "industries",
            "territories",
            "segments",
            "channels",
            "personas",
            "contact_sources",
            "relationship_types",
            "account_tiers",
            "buying_committees",
            "lead_sources",
            "market_verticals",
            "engagement_models",
        ],
        "events": [
            "opportunities",
            "campaigns",
            "activities",
            "customer_agreements",
            "customer_interactions",
            "campaign_responses",
            "win_loss_analyses",
            "referral_submissions",
            "churn_events",
            "renewal_proposals",
            "lead_qualifications",
            "account_reviews",
            "contact_updates",
            "customer_health_snapshots",
        ],
    },
    "fin": {
        "entities": [
            "accounts",
            "ledgers",
            "currencies",
            "tax_codes",
            "payment_methods",
            "payment_terms",
            "fiscal_periods",
            "exchange_rates",
            "account_types",
            "fiscal_years",
            "cost_allocations",
            "profit_centers",
            "bank_accounts",
            "billing_entities",
            "revenue_streams",
        ],
        "events": [
            "journal_entries",
            "invoices",
            "payments",
            "expense_claims",
            "budget_revisions",
            "bank_statements",
            "asset_depreciation_runs",
            "period_closings",
            "tax_filings",
            "audit_reports",
            "revenue_recognition_runs",
            "collections_cases",
            "refund_batches",
        ],
    },
    "inv": {
        "entities": [
            "products",
            "categories",
            "warehouses",
            "suppliers",
            "units_of_measure",
            "supplier_contracts",
            "stock_locations",
            "quality_standards",
            "product_variants",
            "barcodes",
            "demand_classes",
            "lot_attributes",
            "storage_zones",
            "procurement_groups",
        ],
        "events": [
            "purchase_orders",
            "inventory_movements",
            "stock_adjustments",
            "receiving_logs",
            "quality_inspections",
            "supplier_evaluations",
            "replenishment_orders",
            "cycle_counts",
            "product_returns",
            "inventory_write_offs",
            "lot_reclassifications",
            "transfer_orders",
            "reservation_requests",
            "demand_forecasts",
        ],
    },
    "mfg": {
        "entities": [
            "production_lines",
            "machines",
            "bill_of_materials",
            "operations",
            "routings",
            "maintenance_schedules",
            "bom_versions",
            "quality_checkpoints",
            "operators",
            "shift_patterns",
            "tooling_assets",
            "inspection_plans",
            "work_centers",
            "material_specs",
        ],
        "events": [
            "work_orders",
            "production_runs",
            "quality_checks",
            "maintenance_events",
            "machine_downtimes",
            "setup_events",
            "changeover_records",
            "scrap_events",
            "rework_orders",
            "yield_calculations",
            "material_issues",
            "labor_bookings",
            "calibration_events",
            "capacity_reviews",
        ],
    },
    "sales": {
        "entities": [
            "price_lists",
            "discount_rules",
            "sales_regions",
            "sales_channels",
            "revenue_categories",
            "contract_types",
            "rebate_programs",
            "commission_plans",
            "sales_quotas",
            "product_bundles",
            "order_types",
            "fulfillment_rules",
            "sales_teams",
            "promotion_groups",
        ],
        "events": [
            "sales_orders",
            "quotations",
            "sales_contracts",
            "order_deliveries",
            "sales_returns",
            "credit_notes",
            "rebate_accruals",
            "commission_calculations",
            "forecast_submissions",
            "territory_reviews",
            "pipeline_snapshots",
            "pricing_overrides",
            "deal_approvals",
            "shipment_requests",
        ],
    },
    "proj": {
        "entities": [
            "projects",
            "project_types",
            "milestones",
            "deliverables",
            "resource_pools",
            "skill_requirements",
            "project_phases",
            "risk_categories",
            "budget_categories",
            "project_templates",
            "portfolio_groups",
            "funding_sources",
            "dependency_types",
            "governance_boards",
        ],
        "events": [
            "tasks",
            "proj_time_entries",
            "resource_bookings",
            "risk_assessments",
            "issue_tickets",
            "change_requests",
            "sprint_sessions",
            "retrospectives",
            "stakeholder_reviews",
            "project_closings",
            "scope_reviews",
            "status_updates",
            "budget_forecasts",
            "dependency_reviews",
        ],
    },
    "log": {
        "entities": [
            "carriers",
            "shipping_methods",
            "routes",
            "freight_classes",
            "packaging_types",
            "customs_codes",
            "delivery_zones",
            "log_warehouses",
            "tracking_providers",
            "incoterms",
            "fleet_assets",
            "terminal_locations",
            "service_lanes",
            "rate_cards",
        ],
        "events": [
            "shipments",
            "deliveries",
            "pick_lists",
            "packing_events",
            "customs_declarations",
            "freight_bookings",
            "carrier_bookings",
            "return_shipments",
            "last_mile_events",
            "proof_of_deliveries",
            "route_exceptions",
            "dock_appointments",
            "freight_audits",
            "delivery_attempts",
        ],
    },
    "svc": {
        "entities": [
            "services",
            "service_levels",
            "support_tiers",
            "asset_types",
            "warranty_types",
            "knowledge_categories",
            "escalation_paths",
            "resolution_types",
            "sla_definitions",
            "service_contracts",
            "case_origins",
            "entitlement_rules",
            "service_regions",
            "agent_groups",
        ],
        "events": [
            "service_cases",
            "field_visits",
            "escalations",
            "knowledge_articles",
            "customer_surveys",
            "asset_registrations",
            "warranty_claims",
            "case_resolutions",
            "agent_activities",
            "service_training_events",
            "sla_breaches",
            "dispatch_requests",
            "service_renewals",
            "triage_reviews",
        ],
    },
    "sys": {
        "entities": [
            "users",
            "roles",
            "permissions",
            "modules",
            "features",
            "tenants",
            "api_keys",
            "webhook_configs",
            "integrations",
            "system_parameters",
            "identity_providers",
            "access_policies",
            "data_retention_rules",
            "notification_templates",
        ],
        "events": [
            "user_sessions",
            "audit_events",
            "api_calls",
            "job_executions",
            "error_events",
            "data_exports",
            "batch_jobs",
            "sync_events",
            "feature_flags",
            "health_checks",
            "permission_changes",
            "login_attempts",
            "webhook_deliveries",
            "backup_runs",
        ],
    },
}

_REQUIRED_DOMAIN_TERMS: dict[str, dict[str, list[str]]] = {
    "hr": {
        "entities": ["employees"],
        "events": [],
    },
    "crm": {
        "entities": ["customers", "contacts"],
        "events": ["opportunities"],
    },
    "fin": {
        "entities": ["accounts"],
        "events": ["invoices", "payments"],
    },
    "inv": {
        "entities": ["products", "warehouses", "suppliers"],
        "events": ["purchase_orders"],
    },
    "mfg": {
        "entities": ["production_lines"],
        "events": ["work_orders", "production_runs"],
    },
    "sales": {
        "entities": ["price_lists"],
        "events": ["sales_orders"],
    },
    "proj": {
        "entities": ["projects"],
        "events": ["tasks", "resource_bookings"],
    },
    "log": {
        "entities": ["carriers"],
        "events": ["shipments"],
    },
    "svc": {
        "entities": ["services"],
        "events": ["service_cases", "asset_registrations"],
    },
    "sys": {
        "entities": ["users"],
        "events": [],
    },
}

# Extra FK columns added to specific tables for cross-domain connections.
# Key: full table name. Value: list of (col_name, foreign_table) tuples.
_CROSS_DOMAIN_EXTRA_FKS: dict[str, list[tuple[str, str]]] = {
    "sales_sales_orders": [
        ("customer_id", "crm_customers"),
        ("salesperson_id", "hr_employees"),
    ],
    "fin_invoices": [("order_id", "sales_sales_orders")],
    "fin_payments": [("invoice_id", "fin_invoices")],
    "log_shipments": [
        ("order_id", "sales_sales_orders"),
        ("warehouse_id", "inv_warehouses"),
    ],
    "mfg_work_orders": [("product_id", "inv_products")],
    "mfg_production_runs": [("work_order_id", "mfg_work_orders")],
    "proj_tasks": [("assigned_to_id", "hr_employees")],
    "proj_resource_bookings": [("employee_id", "hr_employees")],
    "svc_service_cases": [("customer_id", "crm_customers")],
    "svc_asset_registrations": [("product_id", "inv_products")],
    "crm_opportunities": [("contact_id", "crm_contacts")],
    "inv_purchase_orders": [("supplier_id", "inv_suppliers")],
}


@dataclass
class ForeignKey:
    columns: list[str]
    foreign_table: str
    referred_columns: list[str]

    def to_dict(self) -> dict[str, Any]:
        return {
            "columns": self.columns,
            "foreign_table": self.foreign_table,
            "referred_columns": self.referred_columns,
        }


@dataclass
class TableSpec:
    name: str
    columns: list[tuple[str, str]]
    primary_keys: list[str]
    foreign_keys: list[ForeignKey] = field(default_factory=list)
    has_values: bool = True
    rows: list[list[Any]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "columns": [{"name": n, "type": t} for n, t in self.columns],
            "primary_keys": self.primary_keys,
            "foreign_keys": [fk.to_dict() for fk in self.foreign_keys],
            "has_values": self.has_values,
            "rows": self.rows,
        }


def generate_candidates_json(
    table_count: int,
    uc_schema: str,
    seed: int = 42,
) -> dict[str, Any]:
    """Return a candidates.json dict for `table_count` tables in `uc_schema`."""
    if table_count not in _SUPPORTED_COUNTS:
        raise ValueError(f"table_count must be one of {_SUPPORTED_COUNTS}, got {table_count}")
    sub_module_count = table_count // (len(_DOMAIN_SPECS) * 10)
    tables = _generate_all_tables(sub_module_count, seed)
    total_fk_edges = sum(len(t.foreign_keys) for t in tables)
    return {
        "format_version": _CANDIDATE_FORMAT_VERSION,
        "source_slice": f"synthetic_{table_count}",
        "selection_params": {"table_count": table_count, "seed": seed},
        "schemas": [
            {
                "source_id": f"synthetic_{table_count}",
                "uc_schema": uc_schema,
                "rationale": (f"tables={len(tables)} synthetic=True fk_edges={total_fk_edges}"),
                "tables": [t.to_dict() for t in tables],
            }
        ],
    }


def _generate_all_tables(sub_module_count: int, seed: int) -> list[TableSpec]:
    """Generate all tables for all domains.

    sub_module_count: 5 for 500-table fixture, 10 for 1000-table fixture.
    """
    tables: list[TableSpec] = []
    rng = random.Random(seed)
    fake = Faker("en_US", use_weighting=False)
    fake.seed_instance(seed)

    for domain, spec in _DOMAIN_SPECS.items():
        required = _REQUIRED_DOMAIN_TERMS.get(domain, {})
        entities = _select_domain_terms(
            spec["entities"],
            required.get("entities", []),
            rng,
        )
        events = _select_domain_terms(
            spec["events"],
            required.get("events", []),
            rng,
        )
        anchor = entities[0]

        for i, entity in enumerate(entities):
            t = _entity_table(domain, entity, rng, fake)
            tables.append(t)

        for i, event in enumerate(events):
            t = _event_table(domain, event, anchor, rng, fake)
            tables.append(t)

        if sub_module_count >= 3:
            for i, event in enumerate(events):
                entity = entities[min(i, len(entities) - 1)]
                t = _item_table(domain, event, entity, rng, fake)
                tables.append(t)

        if sub_module_count >= 4:
            for i, entity in enumerate(entities):
                t = _config_table(domain, entity, rng, fake)
                tables.append(t)

        if sub_module_count >= 5:
            for suffix in _ANALYTICS_SUFFIXES:
                t = _analytics_table(domain, anchor, suffix, rng, fake)
                tables.append(t)

        if sub_module_count >= 6:
            for i, event in enumerate(events):
                t = _approval_table(domain, event, rng, fake)
                tables.append(t)

        if sub_module_count >= 7:
            for i, entity in enumerate(entities):
                t = _notification_table(domain, entity, rng, fake)
                tables.append(t)

        if sub_module_count >= 8:
            for i, event in enumerate(events):
                t = _integration_table(domain, event, rng, fake)
                tables.append(t)

        if sub_module_count >= 9:
            for i, entity in enumerate(entities):
                t = _schedule_table(domain, entity, rng, fake)
                tables.append(t)

        if sub_module_count >= 10:
            for i, entity in enumerate(entities):
                t = _archive_table(domain, entity, rng, fake)
                tables.append(t)

    return tables


def _select_domain_terms(
    terms: list[str],
    required: list[str],
    rng: random.Random,
) -> list[str]:
    """Select a deterministic but seed-varied subset of domain terms."""
    if len(required) > _TERMS_PER_DOMAIN:
        raise ValueError("required domain terms exceed the per-domain term budget")
    missing = [term for term in required if term not in terms]
    if missing:
        raise ValueError(f"required domain terms missing from pool: {missing}")

    available = [term for term in terms if term not in set(required)]
    rng.shuffle(available)
    return [*required, *available[: _TERMS_PER_DOMAIN - len(required)]]


def _entity_table(domain: str, entity: str, rng: random.Random, fake: Faker) -> TableSpec:
    name = f"{domain}_{entity}"
    cols: list[tuple[str, str]] = [
        ("id", "INT"),
        ("name", "STRING"),
        ("code", "STRING"),
        ("description", "STRING"),
        ("parent_id", "INT"),
        ("is_active", "BOOLEAN"),
        ("sort_order", "INT"),
        ("created_at", "TIMESTAMP"),
        ("updated_at", "TIMESTAMP"),
        ("created_by_id", "INT"),
    ]
    fks = [
        ForeignKey(["parent_id"], name, ["id"]),
        ForeignKey(["created_by_id"], "sys_users", ["id"]),
    ]
    return TableSpec(
        name=name,
        columns=cols,
        primary_keys=["id"],
        foreign_keys=fks,
        has_values=True,
        rows=_gen_rows(name, cols, rng, fake),
    )


def _event_table(
    domain: str, event: str, anchor_entity: str, rng: random.Random, fake: Faker
) -> TableSpec:
    name = f"{domain}_{event}"
    anchor_fk_col = f"{anchor_entity}_id"
    cols: list[tuple[str, str]] = [
        ("id", "INT"),
        (anchor_fk_col, "INT"),
        ("event_date", "DATE"),
        ("status", "STRING"),
        ("reference_number", "STRING"),
        ("amount", "DECIMAL(18,4)"),
        ("currency", "STRING"),
        ("notes", "STRING"),
        ("created_at", "TIMESTAMP"),
        ("created_by_id", "INT"),
        ("updated_at", "TIMESTAMP"),
        ("approved_by_id", "INT"),
    ]
    fks = [
        ForeignKey([anchor_fk_col], f"{domain}_{anchor_entity}", ["id"]),
        ForeignKey(["created_by_id"], "sys_users", ["id"]),
    ]
    if domain != "hr":
        fks.append(ForeignKey(["approved_by_id"], "hr_employees", ["id"]))
    for extra_col, extra_table in _CROSS_DOMAIN_EXTRA_FKS.get(name, []):
        cols.append((extra_col, "INT"))
        fks.append(ForeignKey([extra_col], extra_table, ["id"]))
    return TableSpec(
        name=name,
        columns=cols,
        primary_keys=["id"],
        foreign_keys=fks,
        has_values=True,
        rows=_gen_rows(name, cols, rng, fake),
    )


def _item_table(domain: str, event: str, entity: str, rng: random.Random, fake: Faker) -> TableSpec:
    name = f"{domain}_{event}_lines"
    event_fk_col = f"{event}_id"
    entity_fk_col = f"{entity}_id"
    cols: list[tuple[str, str]] = [
        ("id", "INT"),
        (event_fk_col, "INT"),
        (entity_fk_col, "INT"),
        ("quantity", "INT"),
        ("unit_price", "DECIMAL(18,4)"),
        ("total_amount", "DECIMAL(18,4)"),
        ("discount_pct", "DECIMAL(5,2)"),
        ("tax_amount", "DECIMAL(18,4)"),
        ("sequence_number", "INT"),
        ("line_status", "STRING"),
        ("notes", "STRING"),
    ]
    fks = [
        ForeignKey([event_fk_col], f"{domain}_{event}", ["id"]),
        ForeignKey([entity_fk_col], f"{domain}_{entity}", ["id"]),
    ]
    return TableSpec(
        name=name,
        columns=cols,
        primary_keys=["id"],
        foreign_keys=fks,
        has_values=True,
        rows=_gen_rows(name, cols, rng, fake),
    )


def _config_table(domain: str, entity: str, rng: random.Random, fake: Faker) -> TableSpec:
    name = f"{domain}_{entity}_config"
    entity_fk_col = f"{entity}_id"
    cols: list[tuple[str, str]] = [
        ("id", "INT"),
        (entity_fk_col, "INT"),
        ("config_key", "STRING"),
        ("config_value", "STRING"),
        ("data_type", "STRING"),
        ("is_required", "BOOLEAN"),
        ("default_value", "STRING"),
        ("effective_from", "DATE"),
        ("effective_to", "DATE"),
        ("is_active", "BOOLEAN"),
    ]
    fks = [ForeignKey([entity_fk_col], f"{domain}_{entity}", ["id"])]
    return TableSpec(
        name=name,
        columns=cols,
        primary_keys=["id"],
        foreign_keys=fks,
        has_values=True,
        rows=_gen_rows(name, cols, rng, fake),
    )


def _analytics_table(
    domain: str, anchor_entity: str, suffix: str, rng: random.Random, fake: Faker
) -> TableSpec:
    name = f"{domain}_{suffix}"
    entity_fk_col = f"{anchor_entity}_id"
    cols: list[tuple[str, str]] = [
        ("id", "INT"),
        ("period_date", "DATE"),
        ("period_type", "STRING"),
        (entity_fk_col, "INT"),
        ("count_total", "INT"),
        ("count_active", "INT"),
        ("amount_total", "DECIMAL(18,4)"),
        ("amount_avg", "DECIMAL(18,4)"),
        ("created_at", "TIMESTAMP"),
        ("updated_at", "TIMESTAMP"),
    ]
    fks = [ForeignKey([entity_fk_col], f"{domain}_{anchor_entity}", ["id"])]
    return TableSpec(
        name=name,
        columns=cols,
        primary_keys=["id"],
        foreign_keys=fks,
        has_values=True,
        rows=_gen_rows(name, cols, rng, fake),
    )


def _approval_table(domain: str, event: str, rng: random.Random, fake: Faker) -> TableSpec:
    name = f"{domain}_{event}_approvals"
    event_fk_col = f"{event}_id"
    cols: list[tuple[str, str]] = [
        ("id", "INT"),
        (event_fk_col, "INT"),
        ("approver_id", "INT"),
        ("step_number", "INT"),
        ("status", "STRING"),
        ("requested_at", "TIMESTAMP"),
        ("decided_at", "TIMESTAMP"),
        ("decision_notes", "STRING"),
        ("auto_approved", "BOOLEAN"),
        ("escalation_count", "INT"),
    ]
    fks = [
        ForeignKey([event_fk_col], f"{domain}_{event}", ["id"]),
        ForeignKey(["approver_id"], "hr_employees", ["id"]),
    ]
    return TableSpec(
        name=name,
        columns=cols,
        primary_keys=["id"],
        foreign_keys=fks,
        has_values=True,
        rows=_gen_rows(name, cols, rng, fake),
    )


def _notification_table(domain: str, entity: str, rng: random.Random, fake: Faker) -> TableSpec:
    name = f"{domain}_{entity}_alerts"
    entity_fk_col = f"{entity}_id"
    cols: list[tuple[str, str]] = [
        ("id", "INT"),
        (entity_fk_col, "INT"),
        ("recipient_id", "INT"),
        ("channel", "STRING"),
        ("subject", "STRING"),
        ("message_body", "STRING"),
        ("sent_at", "TIMESTAMP"),
        ("read_at", "TIMESTAMP"),
        ("status", "STRING"),
        ("retry_count", "INT"),
    ]
    fks = [
        ForeignKey([entity_fk_col], f"{domain}_{entity}", ["id"]),
        ForeignKey(["recipient_id"], "sys_users", ["id"]),
    ]
    return TableSpec(
        name=name,
        columns=cols,
        primary_keys=["id"],
        foreign_keys=fks,
        has_values=True,
        rows=_gen_rows(name, cols, rng, fake),
    )


def _integration_table(domain: str, event: str, rng: random.Random, fake: Faker) -> TableSpec:
    name = f"{domain}_{event}_sync_logs"
    event_fk_col = f"{event}_id"
    cols: list[tuple[str, str]] = [
        ("id", "INT"),
        (event_fk_col, "INT"),
        ("external_system", "STRING"),
        ("external_id", "STRING"),
        ("sync_status", "STRING"),
        ("last_synced_at", "TIMESTAMP"),
        ("payload_hash", "STRING"),
        ("error_message", "STRING"),
        ("retry_count", "INT"),
        ("created_at", "TIMESTAMP"),
    ]
    fks = [ForeignKey([event_fk_col], f"{domain}_{event}", ["id"])]
    return TableSpec(
        name=name,
        columns=cols,
        primary_keys=["id"],
        foreign_keys=fks,
        has_values=True,
        rows=_gen_rows(name, cols, rng, fake),
    )


def _schedule_table(domain: str, entity: str, rng: random.Random, fake: Faker) -> TableSpec:
    name = f"{domain}_{entity}_schedules"
    entity_fk_col = f"{entity}_id"
    cols: list[tuple[str, str]] = [
        ("id", "INT"),
        (entity_fk_col, "INT"),
        ("scheduled_for", "TIMESTAMP"),
        ("end_time", "TIMESTAMP"),
        ("timezone", "STRING"),
        ("recurrence_type", "STRING"),
        ("status", "STRING"),
        ("attendees_count", "INT"),
        ("location", "STRING"),
        ("created_at", "TIMESTAMP"),
    ]
    fks = [ForeignKey([entity_fk_col], f"{domain}_{entity}", ["id"])]
    return TableSpec(
        name=name,
        columns=cols,
        primary_keys=["id"],
        foreign_keys=fks,
        has_values=True,
        rows=_gen_rows(name, cols, rng, fake),
    )


def _archive_table(domain: str, entity: str, rng: random.Random, fake: Faker) -> TableSpec:
    name = f"{domain}_{entity}_history"
    entity_fk_col = f"{entity}_id"
    cols: list[tuple[str, str]] = [
        ("id", "INT"),
        (entity_fk_col, "INT"),
        ("archived_at", "TIMESTAMP"),
        ("archived_by_id", "INT"),
        ("archive_reason", "STRING"),
        ("old_status", "STRING"),
        ("snapshot_data", "STRING"),
        ("retention_until", "DATE"),
        ("is_deleted", "BOOLEAN"),
        ("original_created_at", "TIMESTAMP"),
    ]
    fks = [
        ForeignKey([entity_fk_col], f"{domain}_{entity}", ["id"]),
        ForeignKey(["archived_by_id"], "sys_users", ["id"]),
    ]
    return TableSpec(
        name=name,
        columns=cols,
        primary_keys=["id"],
        foreign_keys=fks,
        has_values=True,
        rows=_gen_rows(name, cols, rng, fake),
    )


_STATUS_VALUES = ["active", "inactive", "pending", "approved", "rejected"]
_PERIOD_TYPES = ["daily", "weekly", "monthly", "quarterly", "annual"]
_CHANNELS = ["email", "sms", "push", "webhook", "slack"]
_RECURRENCE_TYPES = ["none", "daily", "weekly", "monthly"]
_SYNC_STATUSES = ["synced", "pending", "failed", "skipped"]
_CURRENCIES = ["USD", "EUR", "GBP", "JPY", "CAD"]
_DATA_TYPES = ["string", "integer", "boolean", "decimal", "date"]


def _gen_rows(
    table_name: str,
    columns: list[tuple[str, str]],
    rng: random.Random,
    fake: Faker,
    n: int = _ROWS_PER_TABLE,
) -> list[list[Any]]:
    rows = []
    for row_idx in range(1, n + 1):
        row = []
        for col_name, col_type in columns:
            row.append(_gen_value(table_name, col_name, col_type, row_idx, rng, fake))
        rows.append(row)
    return rows


def _gen_value(
    table_name: str,
    col_name: str,
    col_type: str,
    row_idx: int,
    rng: random.Random,
    fake: Faker,
) -> Any:
    if col_name == "id":
        return row_idx
    if col_name.endswith("_id") and col_name != "id":
        return rng.randint(1, _ROWS_PER_TABLE)
    ct = col_type.upper()
    if "BOOLEAN" in ct:
        return bool((row_idx + rng.randint(0, 1)) % 2)
    if "DATE" in ct and "TIMESTAMP" not in ct:
        month = rng.randint(1, 12)
        day = rng.randint(1, 28)
        return f"2024-{month:02d}-{day:02d}"
    if "TIMESTAMP" in ct:
        month = rng.randint(1, 12)
        day = rng.randint(1, 28)
        hour = rng.randint(0, 23)
        return f"2024-{month:02d}-{day:02d} {hour:02d}:00:00"
    if "INT" in ct or "BIGINT" in ct:
        if "count" in col_name or "quantity" in col_name or "number" in col_name:
            return rng.randint(1, 500)
        if "sort_order" in col_name or "step_number" in col_name or "sequence" in col_name:
            return row_idx
        if "retry" in col_name or "escalation" in col_name:
            return rng.randint(0, 3)
        if "attendees" in col_name:
            return rng.randint(1, 20)
        return rng.randint(1, 1000)
    if "DECIMAL" in ct or "NUMERIC" in ct:
        if "pct" in col_name or "rate" in col_name:
            return round(rng.uniform(0.0, 25.0), 2)
        if "avg" in col_name:
            return round(rng.uniform(100.0, 5000.0), 2)
        return round(rng.uniform(10.0, 50000.0), 2)
    # STRING fallthrough
    if "status" in col_name or "line_status" in col_name or "sync_status" in col_name:
        return rng.choice(_STATUS_VALUES)
    if "period_type" in col_name:
        return rng.choice(_PERIOD_TYPES)
    if "channel" in col_name:
        return rng.choice(_CHANNELS)
    if "recurrence" in col_name:
        return rng.choice(_RECURRENCE_TYPES)
    if "currency" in col_name:
        return rng.choice(_CURRENCIES)
    if "data_type" in col_name:
        return rng.choice(_DATA_TYPES)
    if "timezone" in col_name:
        return rng.choice(["UTC", "US/Eastern", "US/Pacific", "Europe/London"])
    if "external_system" in col_name:
        return rng.choice(["salesforce", "sap", "netsuite", "workday"])
    if "code" in col_name:
        prefix = col_name.replace("_code", "").replace("_", "").upper()[:4]
        return fake.bothify(text=f"{prefix}-####")
    if "reference_number" in col_name:
        return fake.bothify(text="REF-????-####").upper()
    if "external_id" in col_name:
        return fake.uuid4()
    if "payload_hash" in col_name:
        return f"sha256_{row_idx:032d}"
    if "name" in col_name:
        return _fake_name(table_name, fake)
    if "description" in col_name or "notes" in col_name or "snapshot" in col_name:
        return fake.sentence(nb_words=10)
    if "subject" in col_name:
        return fake.sentence(nb_words=5).rstrip(".")
    if "message_body" in col_name:
        return fake.paragraph(nb_sentences=2)
    if "location" in col_name:
        return rng.choice(
            [
                fake.city(),
                fake.street_address(),
                "Remote",
                "Conference Room 1",
            ]
        )
    if "archive_reason" in col_name or "decision_notes" in col_name:
        return fake.sentence(nb_words=8)
    if "error_message" in col_name:
        return None if rng.random() > 0.2 else fake.sentence(nb_words=8)
    if "config_key" in col_name:
        return f"setting.{row_idx}"
    if "config_value" in col_name or "default_value" in col_name:
        return str(rng.randint(0, 100))
    return f"value_{row_idx}"


def _fake_name(table_name: str, fake: Faker) -> str:
    if any(
        token in table_name
        for token in (
            "employees",
            "contacts",
            "operators",
            "users",
        )
    ):
        return fake.name()
    if any(
        token in table_name
        for token in (
            "companies",
            "customers",
            "suppliers",
            "carriers",
            "tenants",
        )
    ):
        return fake.company()
    if "products" in table_name or "product_" in table_name:
        return f"{fake.color_name()} {fake.word().title()}"
    if "projects" in table_name:
        return f"{fake.bs().title()} Initiative"
    if "services" in table_name:
        return f"{fake.catch_phrase()} Service"
    return fake.catch_phrase()


def main() -> int:
    parser = argparse.ArgumentParser(
        prog="dbxcarta-dense-generate",
        description=(
            "Generate a synthetic dense-schema candidates.json for dbxcarta Phase G evaluation."
        ),
    )
    parser.add_argument(
        "--tables",
        type=int,
        choices=list(_SUPPORTED_COUNTS),
        required=True,
        help="Number of tables to generate (500 or 1000).",
    )
    parser.add_argument(
        "--schema",
        type=str,
        default=None,
        help=("UC schema name for the generated schema (default: dense_500 or dense-1000)."),
    )
    parser.add_argument(
        "--seed",
        type=int,
        default=42,
        help="Random seed for deterministic generation (default: 42).",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=None,
        help=("Output path for candidates.json (default: .cache/candidates_<tables>.json)."),
    )
    args = parser.parse_args()

    uc_schema = args.schema or f"dense_{args.tables}"
    output = args.output or Path(f".cache/candidates_{args.tables}.json")
    output.parent.mkdir(parents=True, exist_ok=True)

    payload = generate_candidates_json(args.tables, uc_schema, seed=args.seed)
    output.write_text(json.dumps(payload, indent=2))

    n_tables = len(payload["schemas"][0]["tables"])
    total_fks = sum(len(t["foreign_keys"]) for t in payload["schemas"][0]["tables"])
    print(
        f"[dense] wrote {n_tables} tables ({total_fks} FK edges) to {output}",
        file=sys.stderr,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
