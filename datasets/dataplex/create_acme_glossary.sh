set -e

# Create the Acme Corp business glossary in Dataplex Universal Catalog.
#
# Mirrors create_glossary.sh (the retail/ecommerce glossary) but is data-driven:
# the glossary, its categories, and its terms are declared in the arrays below
# and created with the same `gcloud dataplex glossaries` commands.
#
# Dataplex resource IDs must be kebab-case ([a-z0-9-]), so the snake_case
# names in datasets/csv/*.csv are written here with hyphens (e.g.
# acme_corp_glossary -> acme-corp-glossary, revenue_and_billing ->
# revenue-and-billing). Display names keep their human-readable form.
#
# After running this, point the connector at the new glossary with
#   DATAPLEX_GLOSSARY_ID=acme-corp-glossary

# Load environment variables
source .env

PROJECT_ID=${GCP_PROJECT_ID}
LOCATION=us
GLOSSARY=acme-corp-glossary

GLOSSARY_PARENT="projects/${PROJECT_ID}/locations/${LOCATION}/glossaries/${GLOSSARY}"

# ---------------------------------------------------------------------------
# 1. Create the glossary
# ---------------------------------------------------------------------------
gcloud dataplex glossaries create ${GLOSSARY} \
    --project=${PROJECT_ID} \
    --location=${LOCATION} \
    --display-name="Acme Corp Business Glossary" \
    --description="Canonical business terms for the Acme Corp semantic layer. Each term maps to one or more tables or columns in the acme_corp schema and is organised into functional categories. Use this glossary to resolve ambiguous field names, align cross-team reporting, and drive NL-to-SQL translation."

# ---------------------------------------------------------------------------
# 2. Create categories
#    Format: category-id|Display Name|Description
# ---------------------------------------------------------------------------
CATEGORIES=(
    "revenue-and-billing|Revenue & Billing|Terms related to how Acme recognises, tracks, and collects revenue from customers across subscription and one-time order motions."
    "sales-and-pipeline|Sales & Pipeline|Terms covering the end-to-end sales process from lead qualification through deal close, including forecasting and quoting."
    "customer-and-account|Customer & Account|Terms describing customer accounts, contacts, segmentation, and lifecycle health."
    "marketing-and-demand-generation|Marketing & Demand Generation|Terms related to campaigns, lead sourcing, and top-of-funnel activity."
    "product|Product|Terms describing Acme's sellable product and service catalogue."
    "customer-success-and-support|Customer Success & Support|Terms related to post-sale customer health, support tickets, and satisfaction measurement."
    "people-and-hr|People & HR|Terms covering employee records, org structure, compensation, performance, and workforce operations."
    "finance-and-procurement|Finance & Procurement|Terms related to invoicing, payments, vendor spend, and financial operations."
    "operations-and-projects|Operations & Projects|Terms covering internal cross-functional projects, budgets, and office facilities."
)

for entry in "${CATEGORIES[@]}"; do
    IFS='|' read -r cat_id display desc <<< "${entry}"
    gcloud dataplex glossaries categories create "${cat_id}" \
        --glossary=${GLOSSARY} \
        --project=${PROJECT_ID} \
        --location=${LOCATION} \
        --display-name="${display}" \
        --description="${desc}" \
        --parent="${GLOSSARY_PARENT}"
done

# ---------------------------------------------------------------------------
# 3. Create terms
#    Format: category-id|term-id|Display Name|Description
# ---------------------------------------------------------------------------
TERMS=(
    # --- Revenue & Billing ---
    "revenue-and-billing|annual-recurring-revenue|Annual Recurring Revenue (ARR)|The annualised value of all active subscription contracts. The primary top-line SaaS metric at Acme. Calculated as MRR × 12. Excludes one-time order revenue."
    "revenue-and-billing|monthly-recurring-revenue|Monthly Recurring Revenue (MRR)|The monthly normalised value of an active subscription. Source of truth is subscriptions.mrr_usd. Summed across active subscriptions to derive total company MRR."
    "revenue-and-billing|subscription|Subscription|A recurring-revenue contract between Acme and a customer for a specific product and plan. The subscriptions table is the source of truth for all MRR/ARR figures. A subscription has a billing cycle (monthly or annual), a seat count, and a status (active, cancelled, past_due, trialing)."
    "revenue-and-billing|churn|Churn|A subscription that has been cancelled, resulting in a reduction of ARR. Identified by subscriptions.status = 'cancelled' and a non-null subscriptions.cancelled_date."
    "revenue-and-billing|renewal-date|Renewal Date|The date on which a subscription is next due for renewal. Used by CSMs to prioritise at-risk accounts and by finance for ARR forecasting."
    "revenue-and-billing|billing-cycle|Billing Cycle|The cadence at which a subscription is billed — either monthly or annual. Annual billing typically carries a discount and improves cash collection."
    "revenue-and-billing|order|Order|A one-time, non-recurring purchase — typically professional services, training, or a perpetual license. Distinct from a subscription. Revenue is recognised at delivery rather than ratably."
    "revenue-and-billing|order-revenue|Order Revenue|The total USD value of delivered or completed one-time orders in a period. Derived from orders.total_usd where status not in ('cancelled', 'returned')."
    "revenue-and-billing|invoice|Invoice|A formal billing document issued to a customer against an order or subscription. Tracks amount due, due date, and payment status. An invoice can be linked to a subscription, an order, or both."
    "revenue-and-billing|outstanding-invoice|Outstanding Invoice|An invoice that has been sent to the customer but not yet paid. Identified by invoices.status = 'sent' or 'overdue'. Key indicator of cash collection risk."
    "revenue-and-billing|payment|Payment|A cash receipt applied against an invoice. Tracks payment method, amount, and processing status."
    "revenue-and-billing|seats|Seats|The number of user licences purchased under a subscription. Used for seat-based pricing and expansion tracking."
    "revenue-and-billing|plan|Plan|The named tier or package of a subscription (e.g. Enterprise Tier 3, Cloud Growth). Determines feature entitlements and pricing."

    # --- Sales & Pipeline ---
    "sales-and-pipeline|opportunity|Opportunity|A qualified sales deal being pursued with a customer or prospect. The core pipeline and forecast record. Each opportunity has a stage, expected value, probability, and expected close date."
    "sales-and-pipeline|pipeline-stage|Pipeline Stage|The current position of a deal in the sales process: discovery → proposal → negotiation → closed_won / closed_lost."
    "sales-and-pipeline|deal-amount|Deal Amount|The expected total contract value of an opportunity in USD, as assessed by the account executive."
    "sales-and-pipeline|win-probability|Win Probability|The estimated likelihood (0.0–1.0) that an open opportunity will close as won. Multiplied by deal amount to produce weighted pipeline."
    "sales-and-pipeline|weighted-pipeline|Weighted Pipeline|A risk-adjusted view of open pipeline calculated as opportunity amount × win probability. Used for revenue forecasting."
    "sales-and-pipeline|closed-won|Closed Won|An opportunity that has been successfully closed as a new booking. Identified by opportunities.stage = 'closed_won'."
    "sales-and-pipeline|bookings|Bookings|The total value of new contracts signed in a period. Derived from closed_won opportunities. Distinct from revenue, which is recognised over the subscription term."
    "sales-and-pipeline|loss-reason|Loss Reason|Free-text explanation of why a deal was lost. Populated only on closed_lost opportunities. Used for competitive and win/loss analysis."
    "sales-and-pipeline|quote|Quote|A formal price proposal generated against an opportunity. Quotes are versioned; the highest-version accepted quote represents the final agreed deal terms."
    "sales-and-pipeline|discount|Discount|The percentage reduction applied from list price on a quote. Tracked per quote for margin and pricing governance analysis."
    "sales-and-pipeline|sales-activity|Sales Activity|A logged touchpoint in the sales process — call, email, meeting, or demo. Linked to an opportunity, lead, or contact. Used to measure rep engagement and pipeline velocity."
    "sales-and-pipeline|account-executive|Account Executive (AE)|The Acme sales representative who owns a deal or customer account. Referenced as owner_employee_id on opportunities and account_owner_id on customers."
    "sales-and-pipeline|close-date|Close Date|The expected or actual date a deal closes. Used as the partition key on the opportunities table and is the basis for quarterly pipeline reporting."

    # --- Customer & Account ---
    "customer-and-account|customer|Customer|A B2B company that has purchased or is being sold to. The customers table is the source of truth for account ownership, segmentation, and lifetime value. One row per company."
    "customer-and-account|customer-segment|Customer Segment|The sales tier a customer belongs to: enterprise, mid_market, or smb. Drives coverage model, pricing, and support SLAs."
    "customer-and-account|lifetime-value|Lifetime Value (LTV)|The cumulative revenue collected from a customer from first contract to date. Stored as customers.lifetime_value_usd."
    "customer-and-account|customer-acquisition-date|Customer Acquisition Date|The date a customer signed their first contract with Acme. Stored as customers.acquired_date. Used for cohort analysis and tenure calculations."
    "customer-and-account|health-score|Health Score|A 0–100 composite score computed by the Customer Success model to indicate account risk. Low scores flag at-risk renewals."
    "customer-and-account|account-status|Account Status|The current lifecycle state of a customer account: active, churned, or prospect."
    "customer-and-account|customer-contact|Customer Contact|An individual person at a customer account. A customer may have many contacts. is_primary identifies the main point of contact; is_decision_maker flags economic buyers."
    "customer-and-account|decision-maker|Decision Maker|A customer contact who holds economic buying authority. Identified by customer_contacts.is_decision_maker = TRUE."
    "customer-and-account|customer-success-manager|Customer Success Manager (CSM)|The Acme employee responsible for post-sale customer health and renewals. Referenced as owner_employee_id on subscriptions."

    # --- Marketing & Demand Generation ---
    "marketing-and-demand-generation|lead|Lead|A top-of-funnel prospect that has not yet been qualified into an opportunity. Captured with source, score, and status. Converts to a customer via converted_customer_id."
    "marketing-and-demand-generation|lead-source|Lead Source|The channel through which a lead was acquired: web, event, referral, outbound, ads, or social."
    "marketing-and-demand-generation|lead-score|Lead Score|A 0–100 score from the marketing automation platform indicating a lead's engagement and fit. Higher scores are prioritised for SDR outreach."
    "marketing-and-demand-generation|lead-conversion|Lead Conversion|The event where a qualified lead becomes a new customer account. Tracked via leads.converted_customer_id and leads.converted_at."
    "marketing-and-demand-generation|campaign|Campaign|A marketing initiative designed to generate leads or pipeline, run across a specific channel (email, event, paid search, etc.) with a defined budget and duration."
    "marketing-and-demand-generation|campaign-channel|Campaign Channel|The medium through which a campaign reaches its audience: email, social, paid_search, event, content, or ads."
    "marketing-and-demand-generation|campaign-budget|Campaign Budget|The planned spend allocated to a marketing campaign. Compared against campaigns.spend_usd to track over/under-spend."
    "marketing-and-demand-generation|web-event|Web Event|A digital interaction captured from the Acme website, such as a page view, form fill, or content download. Linked to a customer or anonymous session."

    # --- Product ---
    "product|product|Product|A sellable software product or service in Acme's catalogue, including on-premise and SaaS offerings, professional services, and training. The products table tracks list price, cost, and active/retired status."
    "product|list-price|List Price|The standard undiscounted price for a product before any negotiated discount is applied."
    "product|product-cost|Product Cost|The internal unit cost of delivering a product, used for gross margin calculations."
    "product|product-category|Product Category|A grouping of related products used for reporting and catalogue organisation."
    "product|order-line-item|Order Line Item|A single product line within an order, capturing quantity and unit price. Multiple line items compose an order."

    # --- Customer Success & Support ---
    "customer-success-and-support|support-ticket|Support Ticket|A customer-reported issue or request tracked through resolution. Classified by priority (low, normal, high, urgent) and category (billing, technical, bug, feature_request)."
    "customer-success-and-support|first-response-time|First Response Time|The elapsed time between a support ticket being created and the first agent response. A key SLA metric. Derived from support_tickets.first_response_at − support_tickets.created_at."
    "customer-success-and-support|resolution-time|Resolution Time|The total time from ticket creation to resolution. Derived from support_tickets.resolved_at − support_tickets.created_at."
    "customer-success-and-support|csat-score|CSAT Score|Customer Satisfaction score (1–5) collected after ticket resolution. NULL if the customer did not respond to the survey."
    "customer-success-and-support|ticket-priority|Ticket Priority|The urgency level of a support ticket: low, normal, high, or urgent. Drives SLA response targets."
    "customer-success-and-support|ticket-comment|Ticket Comment|A message or note added to a support ticket by an agent or customer after initial creation. Tracked in ticket_comments."

    # --- People & HR ---
    "people-and-hr|employee|Employee|An individual who works at Acme, past or present. The employees table stores the current role snapshot; employee_role_history provides the time-series of all role changes."
    "people-and-hr|headcount|Headcount|The count of active employees at a point in time. Derived by filtering employees where employment_status = 'active'."
    "people-and-hr|hire-date|Hire Date|The date an employee started at Acme. Used for tenure calculations, onboarding cohort analysis, and anniversary reporting."
    "people-and-hr|tenure|Tenure|The length of time an employee has been at Acme, calculated from hire_date (or role start_date for role-specific tenure) to the current date or termination_date."
    "people-and-hr|department|Department|An organisational unit within Acme (e.g. Engineering, Sales, Customer Success). Employees and projects are grouped by department."
    "people-and-hr|job-title|Job Title|A canonical role title with an associated level code (IC1–IC8, M1–M5) and salary band. Prevents free-text title drift."
    "people-and-hr|career-level|Career Level|A standardised seniority code: IC1–IC8 for individual contributors, M1–M5 for managers. Drives salary banding and promotion eligibility."
    "people-and-hr|salary-band|Salary Band|The approved minimum and maximum base salary range for a given job title and level."
    "people-and-hr|compensation-event|Compensation Event|A point-in-time change to an employee's compensation package (new_hire, merit, promotion, or adjustment). The compensation table is a full history; the most recent row per employee represents the current package."
    "people-and-hr|base-salary|Base Salary|The annualised fixed cash component of an employee's total compensation."
    "people-and-hr|equity-grant|Equity Grant|The USD value of equity awarded to an employee at grant time. Tracked per compensation event."
    "people-and-hr|performance-review|Performance Review|A half-yearly formal assessment of an employee's performance, resulting in a categorical rating (exceeds, meets, below) and a numeric score (1.0–5.0)."
    "people-and-hr|role-history|Role History|A time-series record of every role an employee has held, including title, department, team, and manager. Used for promotion velocity, reorg, and tenure-in-role analysis."
    "people-and-hr|time-off-request|Time Off Request|An employee's request for leave (vacation, sick, parental, etc.) including approval status and date range."
    "people-and-hr|training-completion|Training Completion|A record of an employee completing a training course, including their final score and completion status."
    "people-and-hr|office|Office|A physical Acme office location worldwide. The offices table is the source of truth for employee work locations and regional headcount capacity planning."

    # --- Finance & Procurement ---
    "finance-and-procurement|vendor|Vendor|An external supplier of goods or services to Acme. Vendors are linked to contracts that track annual spend commitments."
    "finance-and-procurement|vendor-contract|Vendor Contract|A procurement agreement with an external vendor specifying annual committed spend, term dates, and auto-renewal behaviour."
    "finance-and-procurement|annual-vendor-spend|Annual Vendor Spend|The committed or expected annual spend on a vendor contract in USD. Used by FP&A for operating expense planning."

    # --- Operations & Projects ---
    "operations-and-projects|project|Project|An internal cross-functional initiative with a defined budget, lead, timeline, and status. The projects table tracks planned vs. actual spend for budget variance analysis."
    "operations-and-projects|project-budget|Project Budget|The approved USD budget for an internal project. Compared against projects.spend_usd to identify over-runs."
    "operations-and-projects|project-assignment|Project Assignment|An allocation of an employee to a project, specifying their role and the percentage of their time committed."
)

for entry in "${TERMS[@]}"; do
    IFS='|' read -r cat_id term_id display desc <<< "${entry}"
    gcloud dataplex glossaries terms create "${term_id}" \
        --glossary=${GLOSSARY} \
        --project=${PROJECT_ID} \
        --location=${LOCATION} \
        --display-name="${display}" \
        --description="${desc}" \
        --parent="${GLOSSARY_PARENT}/categories/${cat_id}"
done
