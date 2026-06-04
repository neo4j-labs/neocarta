-- =============================================================================
-- DBxCarta test catalog setup
--
-- Creates 5 schemas covering all dbxcarta pipeline dimensions:
--   - Managed Delta tables with declared PKs and FKs
--   - External Delta tables (LOCATION-based)
--   - Cross-schema foreign keys
--   - Self-referential foreign key (employees.manager_id)
--   - Composite primary key (product_suppliers)
--   - Complex column types: STRUCT, ARRAY, MAP, VARIANT, BINARY
--   - All primitive types: STRING, INT, BIGINT, FLOAT, DOUBLE, DECIMAL,
--     BOOLEAN, DATE, TIMESTAMP, BINARY
--   - Column and table COMMENTs on every object (for embedding quality)
--
-- FK inventory after a full pipeline run (all 5 schemas in scope):
--   16 declared FKs → 16 column-pair rows
--
--   dbxcarta_test_sales (5 FKs):
--     orders.customer_id           -> sales.customers.id
--     orders.employee_id           -> hr.employees.id          [cross-schema]
--     order_items.order_id         -> sales.orders.id
--     order_items.product_id       -> inventory.products.id    [cross-schema]
--     payments.order_id            -> sales.orders.id
--
--   dbxcarta_test_inventory (5 FKs, composite contributes 2 column-pair rows):
--     products.category_id         -> categories.id
--     inventory_levels.product_id  -> products.id
--     inventory_levels.warehouse_id-> warehouses.id
--     product_suppliers.product_id -> products.id              [composite col 1]
--     product_suppliers.supplier_id-> suppliers.id             [composite col 2]
--
--   dbxcarta_test_hr (3 FKs, 1 self-referential):
--     employees.department_id      -> departments.id
--     employees.manager_id         -> employees.id             [self-ref]
--     leave_requests.employee_id   -> employees.id
--
--   dbxcarta_test_events (3 FKs):
--     user_sessions.user_id        -> user_profiles.id
--     page_views.session_id        -> user_sessions.id
--     ab_experiments.user_id       -> user_profiles.id
--
-- Parameterization — substitute before executing:
--   ${catalog}     : target UC catalog name (e.g. main, my_catalog)
--   ${volume_path} : UC Volume base path for external tables
--                    (e.g. /Volumes/main/default/dbxcarta)
--                    Required only for dbxcarta_test_external schema.
--
-- Usage — Python (Databricks SDK):
--   from pathlib import Path
--   from databricks.sdk import WorkspaceClient
--
--   sql = Path("tests/fixtures/setup_test_catalog.sql").read_text()
--   sql = sql.replace("${catalog}", catalog).replace("${volume_path}", volume_path)
--   ws = WorkspaceClient()
--   for stmt in sql.split(";"):
--       lines = [l for l in stmt.splitlines() if not l.strip().startswith("--")]
--       body = "\n".join(lines).strip()
--       if body:
--           ws.statement_execution.execute_statement(
--               warehouse_id=warehouse_id, statement=stmt, wait_timeout="60s"
--           )
--
-- Usage — Python (Spark):
--   sql = Path("tests/fixtures/setup_test_catalog.sql").read_text()
--   sql = sql.replace("${catalog}", catalog).replace("${volume_path}", volume_path)
--   for stmt in sql.split(";"):
--       lines = [l for l in stmt.splitlines() if not l.strip().startswith("--")]
--       body = "\n".join(lines).strip()
--       if body:
--           spark.sql(stmt)
--
-- Usage — Databricks CLI:
--   sed -e 's/${catalog}/main/g' \
--       -e 's|${volume_path}|/Volumes/main/default/dbxcarta|g' \
--       tests/fixtures/setup_test_catalog.sql \
--     | databricks sql execute --stdin --warehouse-id <id>
--
-- NOTE: This script is designed for FRESH schemas. ALTER TABLE ADD CONSTRAINT
-- statements will fail if constraints already exist from a previous run.
-- Run the teardown block first to reset, then re-run setup.
--
-- NOTE: dbxcarta_test_external requires a writable UC Volume path. If no
-- volume is available, stop before that schema or remove the LOCATION clauses.
--
-- NOTE: The VARIANT column in dbxcarta_test_events.page_views requires
-- DBR 15.3+. Remove that column on older runtimes; test_complex_types.py
-- skips the VARIANT family when no VARIANT columns are found.
-- =============================================================================

USE CATALOG ${catalog};

-- =============================================================================
-- SCHEMA: dbxcarta_test_sales
-- Orders domain: customers, orders, order_items, payments, promotions.
-- Cross-schema FKs to dbxcarta_test_hr and dbxcarta_test_inventory are
-- added after those schemas' PKs are established (see cross-schema FK block).
-- =============================================================================

CREATE SCHEMA IF NOT EXISTS dbxcarta_test_sales
  COMMENT 'Sales domain: customers, orders, line items, payments, promotions';

CREATE TABLE IF NOT EXISTS dbxcarta_test_sales.customers (
  id              BIGINT NOT NULL    COMMENT 'Surrogate primary key',
  external_id     STRING             COMMENT 'External CRM identifier',
  first_name      STRING             COMMENT 'Customer first name',
  last_name       STRING             COMMENT 'Customer last name',
  email           STRING             COMMENT 'Primary contact email',
  phone           STRING             COMMENT 'Primary contact phone number',
  tier            STRING             COMMENT 'Loyalty tier: standard, silver, gold, platinum',
  lifetime_value  DECIMAL(14, 2)     COMMENT 'Cumulative revenue attributed to this customer',
  created_at      TIMESTAMP          COMMENT 'Account creation timestamp (UTC)',
  updated_at      TIMESTAMP          COMMENT 'Last profile update timestamp (UTC)',
  is_active       BOOLEAN            COMMENT 'Whether the account is currently active'
)
USING DELTA
COMMENT 'Customer master records for the sales domain';

CREATE TABLE IF NOT EXISTS dbxcarta_test_sales.orders (
  id              BIGINT NOT NULL    COMMENT 'Surrogate primary key',
  customer_id     BIGINT             COMMENT 'FK to customers',
  employee_id     BIGINT             COMMENT 'FK to dbxcarta_test_hr.employees (account manager)',
  status          STRING             COMMENT 'Order status: pending, confirmed, shipped, delivered, cancelled',
  currency        STRING             COMMENT 'ISO 4217 currency code',
  subtotal        DECIMAL(14, 2)     COMMENT 'Pre-discount, pre-tax subtotal',
  discount_amt    DECIMAL(14, 2)     COMMENT 'Total discount amount applied',
  tax_amt         DECIMAL(14, 2)     COMMENT 'Total tax applied',
  total_amt       DECIMAL(14, 2)     COMMENT 'Final order total',
  placed_at       TIMESTAMP          COMMENT 'Timestamp when order was placed (UTC)',
  confirmed_at    TIMESTAMP          COMMENT 'Timestamp when order was confirmed (UTC)',
  shipped_at      TIMESTAMP          COMMENT 'Timestamp when order shipped (UTC)',
  delivery_date   DATE               COMMENT 'Expected or actual delivery date'
)
USING DELTA
COMMENT 'Customer orders: one row per submitted order';

CREATE TABLE IF NOT EXISTS dbxcarta_test_sales.order_items (
  id              BIGINT NOT NULL    COMMENT 'Surrogate primary key',
  order_id        BIGINT             COMMENT 'FK to orders',
  product_id      BIGINT             COMMENT 'FK to dbxcarta_test_inventory.products',
  quantity        INT                COMMENT 'Units ordered',
  unit_price      DECIMAL(12, 2)     COMMENT 'Price per unit at time of order',
  line_total      DECIMAL(14, 2)     COMMENT 'quantity * unit_price',
  discount_pct    DECIMAL(5, 2)      COMMENT 'Per-line discount percentage (0–100)'
)
USING DELTA
COMMENT 'Line items within an order; one row per product per order';

CREATE TABLE IF NOT EXISTS dbxcarta_test_sales.payments (
  id              BIGINT NOT NULL    COMMENT 'Surrogate primary key',
  order_id        BIGINT             COMMENT 'FK to orders',
  method          STRING             COMMENT 'Payment method: card, bank_transfer, crypto, store_credit',
  status          STRING             COMMENT 'Payment status: pending, authorized, settled, refunded, failed',
  amount          DECIMAL(14, 2)     COMMENT 'Payment amount in order currency',
  currency        STRING             COMMENT 'ISO 4217 currency code',
  gateway_ref     STRING             COMMENT 'Payment gateway transaction reference',
  processed_at    TIMESTAMP          COMMENT 'Timestamp when payment was processed (UTC)'
)
USING DELTA
COMMENT 'Payment transactions linked to orders';

CREATE TABLE IF NOT EXISTS dbxcarta_test_sales.promotions (
  id              BIGINT NOT NULL    COMMENT 'Surrogate primary key',
  code            STRING             COMMENT 'Promotional coupon code',
  description     STRING             COMMENT 'Human-readable promotion description',
  discount_type   STRING             COMMENT 'Discount type: percent, fixed, free_shipping',
  discount_val    DECIMAL(10, 2)     COMMENT 'Discount value (percent or fixed amount)',
  valid_from      DATE               COMMENT 'First date the promotion is valid',
  valid_until     DATE               COMMENT 'Last date the promotion is valid (inclusive)',
  usage_count     INT                COMMENT 'Number of times this promotion has been applied',
  is_active       BOOLEAN            COMMENT 'Whether the promotion is currently active'
)
USING DELTA
COMMENT 'Promotional codes and discount definitions';

-- PKs: all within-schema PKs before any FKs
ALTER TABLE dbxcarta_test_sales.customers
  ADD CONSTRAINT sales_customers_pk PRIMARY KEY (id);
ALTER TABLE dbxcarta_test_sales.orders
  ADD CONSTRAINT sales_orders_pk PRIMARY KEY (id);
ALTER TABLE dbxcarta_test_sales.order_items
  ADD CONSTRAINT sales_order_items_pk PRIMARY KEY (id);
ALTER TABLE dbxcarta_test_sales.payments
  ADD CONSTRAINT sales_payments_pk PRIMARY KEY (id);
ALTER TABLE dbxcarta_test_sales.promotions
  ADD CONSTRAINT sales_promotions_pk PRIMARY KEY (id);

-- Intra-schema FKs for sales
ALTER TABLE dbxcarta_test_sales.orders
  ADD CONSTRAINT sales_orders_customer_fk
  FOREIGN KEY (customer_id) REFERENCES dbxcarta_test_sales.customers (id);
ALTER TABLE dbxcarta_test_sales.order_items
  ADD CONSTRAINT sales_order_items_order_fk
  FOREIGN KEY (order_id) REFERENCES dbxcarta_test_sales.orders (id);
ALTER TABLE dbxcarta_test_sales.payments
  ADD CONSTRAINT sales_payments_order_fk
  FOREIGN KEY (order_id) REFERENCES dbxcarta_test_sales.orders (id);

-- =============================================================================
-- SCHEMA: dbxcarta_test_inventory
-- Product catalog domain: products, categories, warehouses, suppliers,
-- inventory_levels, product_suppliers (composite PK).
-- =============================================================================

CREATE SCHEMA IF NOT EXISTS dbxcarta_test_inventory
  COMMENT 'Inventory domain: products, categories, warehouses, suppliers';

CREATE TABLE IF NOT EXISTS dbxcarta_test_inventory.categories (
  id              BIGINT NOT NULL    COMMENT 'Surrogate primary key',
  name            STRING             COMMENT 'Category display name',
  slug            STRING             COMMENT 'URL-safe category identifier',
  parent_id       BIGINT             COMMENT 'FK to parent category (self-ref; null for root)',
  description     STRING             COMMENT 'Detailed category description'
)
USING DELTA
COMMENT 'Hierarchical product category tree';

CREATE TABLE IF NOT EXISTS dbxcarta_test_inventory.products (
  id              BIGINT NOT NULL    COMMENT 'Surrogate primary key',
  sku             STRING             COMMENT 'Stock-keeping unit code (unique)',
  name            STRING             COMMENT 'Product display name',
  category_id     BIGINT             COMMENT 'FK to categories',
  description     STRING             COMMENT 'Full product description',
  price           DECIMAL(12, 2)     COMMENT 'Retail price',
  cost            DECIMAL(12, 2)     COMMENT 'Unit procurement cost',
  weight_kg       DOUBLE             COMMENT 'Product weight in kilograms',
  dimensions      STRUCT<length_cm: DOUBLE, width_cm: DOUBLE, height_cm: DOUBLE>
                                     COMMENT 'Physical dimensions in cm (STRUCT type coverage)',
  tags            ARRAY<STRING>      COMMENT 'Search and filter tags (ARRAY type coverage)',
  attributes      MAP<STRING, STRING>
                                     COMMENT 'Freeform product attributes, e.g. color, material (MAP type coverage)',
  is_active       BOOLEAN            COMMENT 'Whether the product is available for sale',
  created_at      TIMESTAMP          COMMENT 'Record creation timestamp (UTC)',
  discontinued_at DATE               COMMENT 'Date product was discontinued; null if active'
)
USING DELTA
COMMENT 'Product catalog master records';

CREATE TABLE IF NOT EXISTS dbxcarta_test_inventory.warehouses (
  id              BIGINT NOT NULL    COMMENT 'Surrogate primary key',
  code            STRING             COMMENT 'Short warehouse code, e.g. SEA1, ORD2',
  name            STRING             COMMENT 'Warehouse display name',
  address_line    STRING             COMMENT 'Street address',
  city            STRING             COMMENT 'City',
  country_code    STRING             COMMENT 'ISO 3166-1 alpha-2 country code',
  latitude        DOUBLE             COMMENT 'Geographic latitude',
  longitude       DOUBLE             COMMENT 'Geographic longitude',
  is_active       BOOLEAN            COMMENT 'Whether the warehouse is currently operational'
)
USING DELTA
COMMENT 'Warehouse locations for inventory management';

CREATE TABLE IF NOT EXISTS dbxcarta_test_inventory.suppliers (
  id              BIGINT NOT NULL    COMMENT 'Surrogate primary key',
  name            STRING             COMMENT 'Supplier company name',
  contact_name    STRING             COMMENT 'Primary contact person',
  email           STRING             COMMENT 'Primary contact email',
  country_code    STRING             COMMENT 'ISO 3166-1 alpha-2 country code of headquarters',
  lead_days       INT                COMMENT 'Average procurement lead time in calendar days',
  is_preferred    BOOLEAN            COMMENT 'Whether this is a preferred supplier'
)
USING DELTA
COMMENT 'Supplier directory for procurement';

CREATE TABLE IF NOT EXISTS dbxcarta_test_inventory.inventory_levels (
  id              BIGINT NOT NULL    COMMENT 'Surrogate primary key',
  product_id      BIGINT             COMMENT 'FK to products',
  warehouse_id    BIGINT             COMMENT 'FK to warehouses',
  qty_on_hand     INT                COMMENT 'Current units on hand',
  qty_reserved    INT                COMMENT 'Units reserved against open orders',
  qty_incoming    INT                COMMENT 'Units expected from open purchase orders',
  reorder_point   INT                COMMENT 'Reorder trigger threshold in units',
  updated_at      TIMESTAMP          COMMENT 'Timestamp of last inventory update (UTC)'
)
USING DELTA
COMMENT 'Real-time inventory levels by product and warehouse';

CREATE TABLE IF NOT EXISTS dbxcarta_test_inventory.product_suppliers (
  product_id      BIGINT NOT NULL    COMMENT 'FK to products (part of composite PK)',
  supplier_id     BIGINT NOT NULL    COMMENT 'FK to suppliers (part of composite PK)',
  unit_cost       DECIMAL(12, 2)     COMMENT 'Negotiated unit cost from this supplier',
  min_order_qty   INT                COMMENT 'Minimum order quantity',
  lead_days       INT                COMMENT 'Supplier-specific lead time override',
  is_primary      BOOLEAN            COMMENT 'Whether this is the primary source for the product'
)
USING DELTA
COMMENT 'Many-to-many mapping of products to suppliers with cost details';

-- PKs for inventory (composite PK on product_suppliers produces 2 column-pair rows per FK)
ALTER TABLE dbxcarta_test_inventory.categories
  ADD CONSTRAINT inv_categories_pk PRIMARY KEY (id);
ALTER TABLE dbxcarta_test_inventory.products
  ADD CONSTRAINT inv_products_pk PRIMARY KEY (id);
ALTER TABLE dbxcarta_test_inventory.warehouses
  ADD CONSTRAINT inv_warehouses_pk PRIMARY KEY (id);
ALTER TABLE dbxcarta_test_inventory.suppliers
  ADD CONSTRAINT inv_suppliers_pk PRIMARY KEY (id);
ALTER TABLE dbxcarta_test_inventory.inventory_levels
  ADD CONSTRAINT inv_inventory_levels_pk PRIMARY KEY (id);
ALTER TABLE dbxcarta_test_inventory.product_suppliers
  ADD CONSTRAINT inv_product_suppliers_pk PRIMARY KEY (product_id, supplier_id);

-- Intra-schema FKs for inventory
ALTER TABLE dbxcarta_test_inventory.products
  ADD CONSTRAINT inv_products_category_fk
  FOREIGN KEY (category_id) REFERENCES dbxcarta_test_inventory.categories (id);
ALTER TABLE dbxcarta_test_inventory.inventory_levels
  ADD CONSTRAINT inv_levels_product_fk
  FOREIGN KEY (product_id) REFERENCES dbxcarta_test_inventory.products (id);
ALTER TABLE dbxcarta_test_inventory.inventory_levels
  ADD CONSTRAINT inv_levels_warehouse_fk
  FOREIGN KEY (warehouse_id) REFERENCES dbxcarta_test_inventory.warehouses (id);
ALTER TABLE dbxcarta_test_inventory.product_suppliers
  ADD CONSTRAINT inv_ps_product_fk
  FOREIGN KEY (product_id) REFERENCES dbxcarta_test_inventory.products (id);
ALTER TABLE dbxcarta_test_inventory.product_suppliers
  ADD CONSTRAINT inv_ps_supplier_fk
  FOREIGN KEY (supplier_id) REFERENCES dbxcarta_test_inventory.suppliers (id);

-- =============================================================================
-- SCHEMA: dbxcarta_test_hr
-- Employee records: employees (self-ref manager FK), departments, job titles,
-- leave requests.
-- =============================================================================

CREATE SCHEMA IF NOT EXISTS dbxcarta_test_hr
  COMMENT 'HR domain: employees, departments, job titles, leave requests';

CREATE TABLE IF NOT EXISTS dbxcarta_test_hr.departments (
  id              BIGINT NOT NULL    COMMENT 'Surrogate primary key',
  name            STRING             COMMENT 'Department name',
  cost_center     STRING             COMMENT 'Financial cost center code',
  location        STRING             COMMENT 'Office location or campus'
)
USING DELTA
COMMENT 'Organizational departments';

CREATE TABLE IF NOT EXISTS dbxcarta_test_hr.job_titles (
  id              BIGINT NOT NULL    COMMENT 'Surrogate primary key',
  title           STRING             COMMENT 'Official job title',
  level           STRING             COMMENT 'Seniority level: ic, manager, director, vp, c_suite',
  is_active       BOOLEAN            COMMENT 'Whether this title is still in active use'
)
USING DELTA
COMMENT 'Catalog of recognized job titles';

CREATE TABLE IF NOT EXISTS dbxcarta_test_hr.employees (
  id                BIGINT NOT NULL    COMMENT 'Surrogate primary key',
  employee_number   STRING             COMMENT 'Human-readable identifier, e.g. EMP-001234',
  first_name        STRING             COMMENT 'Given name',
  last_name         STRING             COMMENT 'Family name',
  email             STRING             COMMENT 'Corporate email address',
  department_id     BIGINT             COMMENT 'FK to departments',
  job_title_id      BIGINT             COMMENT 'FK to job_titles',
  manager_id        BIGINT             COMMENT 'FK to employees.id (self-ref; null for top-level managers)',
  hire_date         DATE               COMMENT 'Date employment began',
  termination_date  DATE               COMMENT 'Date employment ended; null for active employees',
  salary            DECIMAL(12, 2)     COMMENT 'Annual base salary',
  currency          STRING             COMMENT 'ISO 4217 currency code for salary',
  is_active         BOOLEAN            COMMENT 'Whether the employee is currently employed'
)
USING DELTA
COMMENT 'Employee master records including management hierarchy via self-referential FK';

CREATE TABLE IF NOT EXISTS dbxcarta_test_hr.leave_requests (
  id              BIGINT NOT NULL    COMMENT 'Surrogate primary key',
  employee_id     BIGINT             COMMENT 'FK to employees',
  leave_type      STRING             COMMENT 'Leave type: vacation, sick, parental, bereavement, unpaid',
  start_date      DATE               COMMENT 'First day of requested leave',
  end_date        DATE               COMMENT 'Last day of requested leave (inclusive)',
  days_taken      INT                COMMENT 'Calendar days covered by this request',
  status          STRING             COMMENT 'Request status: pending, approved, denied, cancelled',
  submitted_at    TIMESTAMP          COMMENT 'Timestamp when the request was submitted (UTC)',
  approved_by     BIGINT             COMMENT 'FK to employees (approver); null if not yet decided'
)
USING DELTA
COMMENT 'Employee leave requests and approval status';

-- PKs for HR
ALTER TABLE dbxcarta_test_hr.departments
  ADD CONSTRAINT hr_departments_pk PRIMARY KEY (id);
ALTER TABLE dbxcarta_test_hr.job_titles
  ADD CONSTRAINT hr_job_titles_pk PRIMARY KEY (id);
ALTER TABLE dbxcarta_test_hr.employees
  ADD CONSTRAINT hr_employees_pk PRIMARY KEY (id);
ALTER TABLE dbxcarta_test_hr.leave_requests
  ADD CONSTRAINT hr_leave_requests_pk PRIMARY KEY (id);

-- Intra-schema FKs for HR
ALTER TABLE dbxcarta_test_hr.employees
  ADD CONSTRAINT hr_employees_dept_fk
  FOREIGN KEY (department_id) REFERENCES dbxcarta_test_hr.departments (id);
-- Self-referential FK: manager hierarchy within the same table
ALTER TABLE dbxcarta_test_hr.employees
  ADD CONSTRAINT hr_employees_manager_fk
  FOREIGN KEY (manager_id) REFERENCES dbxcarta_test_hr.employees (id);
ALTER TABLE dbxcarta_test_hr.leave_requests
  ADD CONSTRAINT hr_leave_employee_fk
  FOREIGN KEY (employee_id) REFERENCES dbxcarta_test_hr.employees (id);

-- =============================================================================
-- Cross-schema FKs: sales -> hr and sales -> inventory.
-- Both target schemas' PKs must exist before these can be added.
-- For REFERENCES edges to appear in Neo4j, DBXCARTA_SCHEMAS must include
-- both the source and target schema (or be left blank for all schemas).
-- =============================================================================

ALTER TABLE dbxcarta_test_sales.orders
  ADD CONSTRAINT sales_orders_employee_fk
  FOREIGN KEY (employee_id) REFERENCES dbxcarta_test_hr.employees (id);

ALTER TABLE dbxcarta_test_sales.order_items
  ADD CONSTRAINT sales_order_items_product_fk
  FOREIGN KEY (product_id) REFERENCES dbxcarta_test_inventory.products (id);

-- =============================================================================
-- SCHEMA: dbxcarta_test_events
-- Clickstream / analytics domain. Covers complex column types:
--   STRUCT  -> page_views.referrer_parsed
--   ARRAY   -> user_sessions.event_sequence
--   MAP     -> user_profiles.preferences
--   VARIANT -> page_views.raw_payload   (requires DBR 15.3+)
--   BINARY  -> user_profiles.avatar_thumbnail
-- =============================================================================

CREATE SCHEMA IF NOT EXISTS dbxcarta_test_events
  COMMENT 'Events domain: clickstream, user sessions, profiles, A/B experiments';

CREATE TABLE IF NOT EXISTS dbxcarta_test_events.user_profiles (
  id                BIGINT NOT NULL    COMMENT 'Surrogate primary key',
  external_user_id  STRING             COMMENT 'Application-level user identifier',
  display_name      STRING             COMMENT 'User display name or handle',
  email             STRING             COMMENT 'User email address',
  locale            STRING             COMMENT 'BCP 47 locale code, e.g. en-US, fr-FR',
  timezone          STRING             COMMENT 'IANA timezone, e.g. America/Los_Angeles',
  preferences       MAP<STRING, STRING>
                                       COMMENT 'User preference key-value pairs (MAP type coverage)',
  avatar_thumbnail  BINARY             COMMENT 'PNG thumbnail stored inline (BINARY type coverage)',
  signup_date       DATE               COMMENT 'Date the user created their account',
  last_seen_at      TIMESTAMP          COMMENT 'Timestamp of most recent activity (UTC)',
  is_verified       BOOLEAN            COMMENT 'Whether the email address has been verified'
)
USING DELTA
COMMENT 'User profile records for analytics and personalization';

CREATE TABLE IF NOT EXISTS dbxcarta_test_events.user_sessions (
  id              BIGINT NOT NULL    COMMENT 'Surrogate primary key',
  user_id         BIGINT             COMMENT 'FK to user_profiles',
  session_token   STRING             COMMENT 'Opaque session identifier',
  started_at      TIMESTAMP          COMMENT 'Session start timestamp (UTC)',
  ended_at        TIMESTAMP          COMMENT 'Session end timestamp (UTC); null if still active',
  duration_sec    INT                COMMENT 'Session duration in seconds',
  device_type     STRING             COMMENT 'Device category: desktop, tablet, mobile',
  os              STRING             COMMENT 'Operating system, e.g. iOS 17, Android 14, Windows 11',
  browser         STRING             COMMENT 'Browser name and major version',
  ip_address      STRING             COMMENT 'Client IP address (masked for PII)',
  event_sequence  ARRAY<STRING>      COMMENT 'Ordered list of event names fired in this session (ARRAY type coverage)',
  page_count      INT                COMMENT 'Number of distinct pages viewed',
  bounce          BOOLEAN            COMMENT 'True if the session had only one page view'
)
USING DELTA
COMMENT 'User session records aggregating per-visit activity';

-- VARIANT column requires DBR 15.3+. Remove raw_payload on older runtimes.
-- test_complex_types.py skips the VARIANT family when no VARIANT columns are found.
CREATE TABLE IF NOT EXISTS dbxcarta_test_events.page_views (
  id              BIGINT NOT NULL    COMMENT 'Surrogate primary key',
  session_id      BIGINT             COMMENT 'FK to user_sessions',
  page_path       STRING             COMMENT 'URL path of the viewed page',
  page_title      STRING             COMMENT 'HTML title of the viewed page',
  referrer        STRING             COMMENT 'Raw HTTP Referer header value',
  referrer_parsed STRUCT<domain: STRING, path: STRING, medium: STRING, campaign: STRING>
                                     COMMENT 'Structured referrer attribution (STRUCT type coverage)',
  raw_payload     VARIANT            COMMENT 'Full raw event payload (VARIANT type coverage; DBR 15.3+)',
  load_time_ms    INT                COMMENT 'Page load time in milliseconds',
  viewed_at       TIMESTAMP          COMMENT 'Timestamp when the page was viewed (UTC)'
)
USING DELTA
COMMENT 'Individual page view events; one row per page view';

CREATE TABLE IF NOT EXISTS dbxcarta_test_events.ab_experiments (
  id              BIGINT NOT NULL    COMMENT 'Surrogate primary key',
  user_id         BIGINT             COMMENT 'FK to user_profiles',
  experiment_key  STRING             COMMENT 'Machine-readable experiment identifier',
  variant         STRING             COMMENT 'Assigned variant: control, treatment_a, treatment_b',
  assigned_at     TIMESTAMP          COMMENT 'Timestamp when variant was assigned (UTC)',
  converted       BOOLEAN            COMMENT 'Whether the user triggered the conversion event',
  converted_at    TIMESTAMP          COMMENT 'Timestamp of conversion; null if not converted'
)
USING DELTA
COMMENT 'A/B experiment assignments and conversion outcomes';

-- PKs for events
ALTER TABLE dbxcarta_test_events.user_profiles
  ADD CONSTRAINT evt_user_profiles_pk PRIMARY KEY (id);
ALTER TABLE dbxcarta_test_events.user_sessions
  ADD CONSTRAINT evt_user_sessions_pk PRIMARY KEY (id);
ALTER TABLE dbxcarta_test_events.page_views
  ADD CONSTRAINT evt_page_views_pk PRIMARY KEY (id);
ALTER TABLE dbxcarta_test_events.ab_experiments
  ADD CONSTRAINT evt_ab_experiments_pk PRIMARY KEY (id);

-- Intra-schema FKs for events
ALTER TABLE dbxcarta_test_events.user_sessions
  ADD CONSTRAINT evt_sessions_user_fk
  FOREIGN KEY (user_id) REFERENCES dbxcarta_test_events.user_profiles (id);
ALTER TABLE dbxcarta_test_events.page_views
  ADD CONSTRAINT evt_page_views_session_fk
  FOREIGN KEY (session_id) REFERENCES dbxcarta_test_events.user_sessions (id);
ALTER TABLE dbxcarta_test_events.ab_experiments
  ADD CONSTRAINT evt_ab_user_fk
  FOREIGN KEY (user_id) REFERENCES dbxcarta_test_events.user_profiles (id);

-- =============================================================================
-- SCHEMA: dbxcarta_test_external
-- External Delta tables registered against UC Volume paths.
-- table_type = EXTERNAL in information_schema.tables — what dbxcarta reads.
-- Covers all remaining primitive types not present above: FLOAT, BIGINT count.
-- Tables start empty; no data upload is required.
-- =============================================================================

CREATE SCHEMA IF NOT EXISTS dbxcarta_test_external
  COMMENT 'External table fixtures: registered against UC Volume paths';

-- Raw inbound orders from a file-based feed
CREATE TABLE IF NOT EXISTS dbxcarta_test_external.raw_orders (
  raw_order_id    BIGINT NOT NULL    COMMENT 'Source system order identifier',
  source_system   STRING             COMMENT 'Originating source system name',
  payload_json    STRING             COMMENT 'Full raw JSON payload from the source feed',
  received_at     TIMESTAMP          COMMENT 'Ingest timestamp (UTC)',
  file_name       STRING             COMMENT 'Source file name'
)
USING DELTA
LOCATION '${volume_path}/external/raw_orders'
COMMENT 'External Delta table: raw inbound order payloads from file-based feeds';

-- Vendor price lists refreshed by scheduled ETL
CREATE TABLE IF NOT EXISTS dbxcarta_test_external.vendor_price_list (
  vendor_id       BIGINT NOT NULL    COMMENT 'Vendor identifier',
  sku             STRING             COMMENT 'Stock-keeping unit code',
  price           DECIMAL(12, 2)     COMMENT 'Vendor quoted price',
  currency        STRING             COMMENT 'ISO 4217 currency code',
  effective_date  DATE               COMMENT 'Date from which this price is valid',
  expiry_date     DATE               COMMENT 'Date after which this price is no longer valid'
)
USING DELTA
LOCATION '${volume_path}/external/vendor_price_list'
COMMENT 'External Delta table: vendor price lists refreshed by scheduled ETL';

-- Geography reference table covering all remaining primitive types
CREATE TABLE IF NOT EXISTS dbxcarta_test_external.geo_reference (
  geo_id            BIGINT NOT NULL    COMMENT 'Surrogate primary key',
  country_code      STRING             COMMENT 'ISO 3166-1 alpha-2 code',
  country_name      STRING             COMMENT 'Full English country name',
  region            STRING             COMMENT 'Continent or region grouping',
  population        BIGINT             COMMENT 'Approximate population (BIGINT non-key coverage)',
  area_km2          FLOAT              COMMENT 'Total land area in km squared (FLOAT type coverage)',
  gdp_usd           DOUBLE             COMMENT 'GDP in USD (DOUBLE type coverage)',
  is_eu_member      BOOLEAN            COMMENT 'EU membership flag',
  independence_date DATE               COMMENT 'Date of national independence',
  last_census       TIMESTAMP          COMMENT 'Timestamp of most recent census data load (UTC)',
  flag_image        BINARY             COMMENT 'PNG flag image stored inline (BINARY type coverage)',
  gini_coeff        DECIMAL(5, 4)      COMMENT 'Gini coefficient of income inequality'
)
USING DELTA
LOCATION '${volume_path}/external/geo_reference'
COMMENT 'External Delta table: geography reference covering all primitive column types';

-- =============================================================================
-- TEARDOWN
-- Uncomment and execute to remove all fixture schemas and their objects.
-- Also drops legacy backward-compat schemas if present from earlier runs.
-- =============================================================================

-- DROP SCHEMA IF EXISTS ${catalog}.dbxcarta_test_sales CASCADE;
-- DROP SCHEMA IF EXISTS ${catalog}.dbxcarta_test_inventory CASCADE;
-- DROP SCHEMA IF EXISTS ${catalog}.dbxcarta_test_hr CASCADE;
-- DROP SCHEMA IF EXISTS ${catalog}.dbxcarta_test_events CASCADE;
-- DROP SCHEMA IF EXISTS ${catalog}.dbxcarta_test_external CASCADE;
-- DROP SCHEMA IF EXISTS ${catalog}.dbxcarta_fk_test CASCADE;
-- DROP SCHEMA IF EXISTS ${catalog}.dbxcarta_fk_test_b CASCADE;
