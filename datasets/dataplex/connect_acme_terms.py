"""Link Acme Corp BigQuery columns to their Dataplex glossary terms.

Companion to create_acme_glossary.sh: that script creates the
`acme-corp-glossary` (categories + terms); this script creates the
`definition` entry links that tie each BigQuery column to the term that
defines it (the catalog↔glossary edges that back TAGGED_WITH in the graph).

The `definition` entry link this creates is the same shape as connect_terms.py
(the retail example); only the column→term CONFIG below is Acme-specific, and
term IDs match exactly the ones created by create_acme_glossary.sh. Because
there are dozens of links, the creation runs over a shared CatalogServiceClient
(one gRPC channel) and a thread pool rather than the retail script's
client-per-call sequential loop.

Usage:
    python datasets/dataplex/connect_acme_terms.py

Required env vars:
    GCP_PROJECT_ID, GCP_PROJECT_NUMBER, BIGQUERY_LOCATION, DATAPLEX_LOCATION
    BIGQUERY_DATASET_ID   (defaults to "acme_corp")
    DATAPLEX_GLOSSARY_ID  (defaults to "acme-corp-glossary")

Note: BIGQUERY_DATASET_ID / DATAPLEX_GLOSSARY_ID are shared vars — point them at
the Acme dataset/glossary before running (e.g. set them in .env), otherwise the
lookup runs against whatever dataset you're currently working with.
"""

# ---------------------------------------------------------------------------
# Acme column -> glossary term mapping. Keyed by table, then by column; each
# column maps to a single term id or a list of term ids. A column may define
# more than one term (e.g. opportunities.stage backs both the generic
# "pipeline-stage" and the specific "closed-won" state). Pure-derived terms
# with no backing column — tenure, bookings — are intentionally omitted; they
# are computed, not stored.
# ---------------------------------------------------------------------------
CONFIG = {
    # --- Revenue & Billing ---
    "subscriptions": {
        "subscription_id": "subscription",
        "mrr_usd": "monthly-recurring-revenue",
        "arr_usd": "annual-recurring-revenue",
        "billing_cycle": "billing-cycle",
        "renewal_date": "renewal-date",
        "status": "churn",
        "cancelled_date": "churn",
        "seats": "seats",
        "plan_name": "plan",
        "owner_employee_id": "customer-success-manager",
    },
    "orders": {
        "order_id": "order",
        "total_usd": "order-revenue",
    },
    "order_items": {
        "order_item_id": "order-line-item",
    },
    "invoices": {
        "invoice_id": "invoice",
        "status": "outstanding-invoice",
    },
    "payments": {
        "payment_id": "payment",
    },
    # --- Sales & Pipeline ---
    "opportunities": {
        "opportunity_id": "opportunity",
        "stage": ["pipeline-stage", "closed-won"],
        "amount_usd": ["deal-amount", "weighted-pipeline"],
        "probability": "win-probability",
        "close_date": "close-date",
        "loss_reason": "loss-reason",
        "owner_employee_id": "account-executive",
    },
    "quotes": {
        "quote_id": "quote",
        "discount_pct": "discount",
    },
    "sales_activities": {
        "activity_id": "sales-activity",
    },
    # --- Customer & Account ---
    "customers": {
        "customer_id": "customer",
        "segment": "customer-segment",
        "lifetime_value_usd": "lifetime-value",
        "acquired_date": "customer-acquisition-date",
        "health_score": "health-score",
        "status": "account-status",
    },
    "customer_contacts": {
        "contact_id": "customer-contact",
        "is_decision_maker": "decision-maker",
    },
    # --- Marketing & Demand Generation ---
    "leads": {
        "lead_id": "lead",
        "source": "lead-source",
        "score": "lead-score",
        "converted_customer_id": "lead-conversion",
    },
    "campaigns": {
        "campaign_id": "campaign",
        "channel": "campaign-channel",
        "budget_usd": "campaign-budget",
    },
    "web_events": {
        "event_id": "web-event",
    },
    # --- Product ---
    "products": {
        "product_id": "product",
        "list_price_usd": "list-price",
        "cost_usd": "product-cost",
    },
    "product_categories": {
        "category_id": "product-category",
    },
    # --- Customer Success & Support ---
    "support_tickets": {
        "ticket_id": "support-ticket",
        "first_response_at": "first-response-time",
        "resolved_at": "resolution-time",
        "csat_score": "csat-score",
        "priority": "ticket-priority",
    },
    "ticket_comments": {
        "comment_id": "ticket-comment",
    },
    # --- People & HR ---
    "employees": {
        "employee_id": "employee",
        "hire_date": "hire-date",
        "employment_status": "headcount",
    },
    "employee_role_history": {
        "role_history_id": "role-history",
    },
    "departments": {
        "department_id": "department",
    },
    "job_titles": {
        "job_title_id": "job-title",
        "level": "career-level",
        "min_salary": "salary-band",
    },
    "compensation": {
        "compensation_id": "compensation-event",
        "base_salary": "base-salary",
        "equity_grant_usd": "equity-grant",
    },
    "performance_reviews": {
        "review_id": "performance-review",
    },
    "time_off_requests": {
        "request_id": "time-off-request",
    },
    "employee_training": {
        "enrollment_id": "training-completion",
    },
    "offices": {
        "office_id": "office",
    },
    # --- Finance & Procurement ---
    "vendors": {
        "vendor_id": "vendor",
    },
    "vendor_contracts": {
        "contract_id": "vendor-contract",
        "annual_spend_usd": "annual-vendor-spend",
    },
    # --- Operations & Projects ---
    "projects": {
        "project_id": "project",
        "budget_usd": "project-budget",
    },
    "project_assignments": {
        "assignment_id": "project-assignment",
    },
}


if __name__ == "__main__":
    import os
    import uuid
    from concurrent.futures import ThreadPoolExecutor, as_completed

    from dotenv import load_dotenv
    from google.api_core.exceptions import AlreadyExists
    from google.cloud import dataplex_v1

    load_dotenv()

    PROJECT_ID = os.environ["GCP_PROJECT_ID"]
    PROJECT_NUMBER = os.environ["GCP_PROJECT_NUMBER"]
    DATASET_ID = os.getenv("BIGQUERY_DATASET_ID", "acme_corp")
    BQ_LOCATION = os.environ["BIGQUERY_LOCATION"]

    GLOSSARY_LOCATION = os.environ["DATAPLEX_LOCATION"]
    GLOSSARY_ID = os.getenv("DATAPLEX_GLOSSARY_ID", "acme-corp-glossary")

    # Number of concurrent create_entry_link calls. Dozens of links over one
    # channel; keep modest to stay under Dataplex write quotas.
    MAX_WORKERS = 8

    DEFINITION_LINK_TYPE = "projects/dataplex-types/locations/global/entryLinkTypes/definition"
    LINK_PARENT = f"projects/{PROJECT_NUMBER}/locations/{BQ_LOCATION}/entryGroups/@bigquery"

    # --- Flatten CONFIG into one (table, column, term) work item per link ------
    # The BigQuery table entry name is deterministic, so construct it directly
    # rather than paging through search_entries per table (same format as
    # lookup_entry_links.bq_table_entry_name).
    work = []
    for table_id, columns in CONFIG.items():
        table_entry_name = (
            f"projects/{PROJECT_NUMBER}/locations/{BQ_LOCATION}/"
            f"entryGroups/@bigquery/entries/"
            f"bigquery.googleapis.com/projects/{PROJECT_ID}/"
            f"datasets/{DATASET_ID}/tables/{table_id}"
        )
        for col_name, term_ids in columns.items():
            # A column may define one term (str) or several (list).
            term_list = [term_ids] if isinstance(term_ids, str) else term_ids
            for term_id in term_list:
                term_entry_name = (
                    f"projects/{PROJECT_NUMBER}/locations/{GLOSSARY_LOCATION}/"
                    f"entryGroups/@dataplex/entries/"
                    f"projects/{PROJECT_NUMBER}/locations/{GLOSSARY_LOCATION}/"
                    f"glossaries/{GLOSSARY_ID}/terms/{term_id}"
                )
                work.append((table_id, col_name, term_id, table_entry_name, term_entry_name))

    # --- Create all links concurrently over one shared client -----------------
    # gRPC clients are thread-safe, so a single channel is reused across workers
    # instead of opening one per call.
    client = dataplex_v1.CatalogServiceClient()

    def create_link(item: tuple) -> str:
        """Create one definition link; return a human-readable status line."""
        table_id, col_name, term_id, table_entry_name, term_entry_name = item
        entry_link = dataplex_v1.EntryLink(
            entry_link_type=DEFINITION_LINK_TYPE,
            entry_references=[
                dataplex_v1.EntryLink.EntryReference(
                    name=term_entry_name,
                    type_=dataplex_v1.EntryLink.EntryReference.Type.TARGET,
                ),
                dataplex_v1.EntryLink.EntryReference(
                    name=table_entry_name,
                    path=f"Schema.{col_name}",  # targets the specific column
                    type_=dataplex_v1.EntryLink.EntryReference.Type.SOURCE,
                ),
            ],
        )
        request = dataplex_v1.CreateEntryLinkRequest(
            parent=LINK_PARENT,
            entry_link=entry_link,
            entry_link_id=f"el-{uuid.uuid4().hex[:12]}",
        )
        try:
            link = client.create_entry_link(request=request)
            return f"Linked  {table_id}.{col_name} -> '{term_id}': {link.name}"
        except AlreadyExists:
            # Idempotent: a link for this column/term already exists (e.g. a
            # previous run). Skip and continue.
            return f"Skipped {table_id}.{col_name} -> '{term_id}': already linked"

    print(f"Creating {len(work)} entry links with {MAX_WORKERS} workers...")
    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as pool:
        futures = [pool.submit(create_link, item) for item in work]
        for future in as_completed(futures):
            print(future.result())
