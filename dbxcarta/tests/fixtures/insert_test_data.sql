-- =============================================================================
-- DBxCarta test catalog — minimal row fixtures
--
-- Inserts 15–25 FK-respecting rows per table so the sample_values pipeline
-- produces Value nodes and the demo queries (demo_questions.json) return
-- meaningful results.
--
-- Prerequisite: setup_test_catalog.sql must have been run first.
--
-- Parameterization — substitute before executing:
--   ${catalog} : same value used in setup_test_catalog.sql
--
-- Insertion order respects FK dependencies:
--   hr  → sales  (cross-schema orders.employee_id)
--   inv → sales  (cross-schema order_items.product_id)
--   Categories and employees with self-referential FKs insert
--   parent/manager rows first within the same statement.
--
-- Usage — Databricks SDK (Python):
--   sql = Path("tests/fixtures/insert_test_data.sql").read_text()
--   sql = sql.replace("${catalog}", catalog)
--   for stmt in sql.split(";"):
--       lines = [l for l in stmt.splitlines() if not l.strip().startswith("--")]
--       body = "\n".join(lines).strip()
--       if body:
--           ws.statement_execution.execute_statement(
--               warehouse_id=warehouse_id, statement=stmt, wait_timeout="60s"
--           )
--
-- NOTE: dbxcarta_test_external rows are included but require the Volume path
-- used in setup_test_catalog.sql to be writable.  Skip those three INSERT
-- statements if no Volume is available.
--
-- TEARDOWN (at the bottom of this file): uncomment TRUNCATE TABLE statements
-- to clear rows before re-running setup + insert.
-- =============================================================================

USE CATALOG ${catalog};

-- =============================================================================
-- SCHEMA: dbxcarta_test_hr
-- Insert order: departments → job_titles → employees (managers first) → leave_requests
-- =============================================================================

INSERT INTO dbxcarta_test_hr.departments
SELECT 1, 'Engineering',  'ENG-01', 'San Francisco' UNION ALL
SELECT 2, 'Sales',        'SAL-01', 'New York'       UNION ALL
SELECT 3, 'Marketing',    'MKT-01', 'Austin'         UNION ALL
SELECT 4, 'Finance',      'FIN-01', 'Chicago'        UNION ALL
SELECT 5, 'Operations',   'OPS-01', 'Seattle';

INSERT INTO dbxcarta_test_hr.job_titles
SELECT 1, 'Software Engineer',        'ic',       TRUE  UNION ALL
SELECT 2, 'Senior Software Engineer', 'ic',       TRUE  UNION ALL
SELECT 3, 'Engineering Manager',      'manager',  TRUE  UNION ALL
SELECT 4, 'Account Executive',        'ic',       TRUE  UNION ALL
SELECT 5, 'Director of Sales',        'director', TRUE  UNION ALL
SELECT 6, 'Data Analyst',             'ic',       TRUE;

-- Employees 1–4 are top-level managers (manager_id NULL); 5–20 report to them.
INSERT INTO dbxcarta_test_hr.employees
SELECT  1, 'EMP-000001', 'Alice',   'Johnson',  'alice.johnson@corp.com',    1, 3, NULL, DATE '2019-03-01', NULL,             145000.00, 'USD', TRUE  UNION ALL
SELECT  2, 'EMP-000002', 'Bob',     'Smith',    'bob.smith@corp.com',        2, 5, NULL, DATE '2018-06-15', NULL,             160000.00, 'USD', TRUE  UNION ALL
SELECT  3, 'EMP-000003', 'Carol',   'White',    'carol.white@corp.com',      3, 3, NULL, DATE '2020-01-10', NULL,             130000.00, 'USD', TRUE  UNION ALL
SELECT  4, 'EMP-000004', 'David',   'Brown',    'david.brown@corp.com',      4, 3, NULL, DATE '2017-09-20', NULL,             155000.00, 'USD', TRUE  UNION ALL
SELECT  5, 'EMP-000005', 'Emma',    'Davis',    'emma.davis@corp.com',       1, 2, 1,    DATE '2021-02-14', NULL,             115000.00, 'USD', TRUE  UNION ALL
SELECT  6, 'EMP-000006', 'Frank',   'Miller',   'frank.miller@corp.com',     1, 1, 1,    DATE '2022-07-01', NULL,              95000.00, 'USD', TRUE  UNION ALL
SELECT  7, 'EMP-000007', 'Grace',   'Wilson',   'grace.wilson@corp.com',     1, 2, 1,    DATE '2020-11-30', NULL,             118000.00, 'USD', TRUE  UNION ALL
SELECT  8, 'EMP-000008', 'Henry',   'Moore',    'henry.moore@corp.com',      2, 4, 2,    DATE '2021-05-10', NULL,              88000.00, 'USD', TRUE  UNION ALL
SELECT  9, 'EMP-000009', 'Isabella','Taylor',   'isabella.taylor@corp.com',  2, 4, 2,    DATE '2022-01-20', NULL,              90000.00, 'USD', TRUE  UNION ALL
SELECT 10, 'EMP-000010', 'James',   'Anderson', 'james.anderson@corp.com',   2, 4, 2,    DATE '2019-08-05', NULL,              92000.00, 'USD', TRUE  UNION ALL
SELECT 11, 'EMP-000011', 'Karen',   'Thomas',   'karen.thomas@corp.com',     3, 6, 3,    DATE '2021-03-15', NULL,              85000.00, 'USD', TRUE  UNION ALL
SELECT 12, 'EMP-000012', 'Liam',    'Jackson',  'liam.jackson@corp.com',     3, 6, 3,    DATE '2022-09-01', NULL,              82000.00, 'USD', TRUE  UNION ALL
SELECT 13, 'EMP-000013', 'Mia',     'Harris',   'mia.harris@corp.com',       4, 6, 4,    DATE '2020-04-20', NULL,              78000.00, 'USD', TRUE  UNION ALL
SELECT 14, 'EMP-000014', 'Noah',    'Martin',   'noah.martin@corp.com',      4, 6, 4,    DATE '2021-10-01', NULL,              80000.00, 'USD', TRUE  UNION ALL
SELECT 15, 'EMP-000015', 'Olivia',  'Garcia',   'olivia.garcia@corp.com',    5, 1, 1,    DATE '2023-01-15', NULL,              98000.00, 'USD', TRUE  UNION ALL
SELECT 16, 'EMP-000016', 'Peter',   'Martinez', 'peter.martinez@corp.com',   5, 2, 1,    DATE '2022-06-10', NULL,             112000.00, 'USD', TRUE  UNION ALL
SELECT 17, 'EMP-000017', 'Quinn',   'Robinson', 'quinn.robinson@corp.com',   1, 1, 1,    DATE '2023-03-20', NULL,              90000.00, 'USD', TRUE  UNION ALL
SELECT 18, 'EMP-000018', 'Rachel',  'Clark',    'rachel.clark@corp.com',     2, 4, 2,    DATE '2021-07-05', NULL,              87000.00, 'USD', TRUE  UNION ALL
SELECT 19, 'EMP-000019', 'Samuel',  'Rodriguez','samuel.rodriguez@corp.com', 3, 6, 3,    DATE '2022-11-15', NULL,              83000.00, 'USD', TRUE  UNION ALL
SELECT 20, 'EMP-000020', 'Tina',    'Lewis',    'tina.lewis@corp.com',       1, 1, 1,    DATE '2023-06-01', DATE '2024-12-31',  94000.00, 'USD', FALSE;

INSERT INTO dbxcarta_test_hr.leave_requests
SELECT  1,  5, 'vacation',    DATE '2024-07-01', DATE '2024-07-10', 10, 'approved',  TIMESTAMP '2024-06-15 09:00:00', 1    UNION ALL
SELECT  2,  6, 'sick',        DATE '2024-03-05', DATE '2024-03-06',  2, 'approved',  TIMESTAMP '2024-03-05 07:30:00', 1    UNION ALL
SELECT  3,  7, 'vacation',    DATE '2024-08-12', DATE '2024-08-23', 12, 'approved',  TIMESTAMP '2024-07-20 14:00:00', 1    UNION ALL
SELECT  4,  8, 'parental',    DATE '2024-04-01', DATE '2024-06-30', 90, 'approved',  TIMESTAMP '2024-02-10 10:00:00', 2    UNION ALL
SELECT  5,  9, 'vacation',    DATE '2024-12-23', DATE '2024-12-31',  9, 'pending',   TIMESTAMP '2024-11-15 11:00:00', NULL UNION ALL
SELECT  6, 10, 'sick',        DATE '2024-09-10', DATE '2024-09-12',  3, 'approved',  TIMESTAMP '2024-09-10 08:00:00', 2    UNION ALL
SELECT  7, 11, 'vacation',    DATE '2024-06-03', DATE '2024-06-07',  5, 'approved',  TIMESTAMP '2024-05-20 09:30:00', 3    UNION ALL
SELECT  8, 12, 'bereavement', DATE '2024-10-14', DATE '2024-10-17',  4, 'approved',  TIMESTAMP '2024-10-14 06:00:00', 3    UNION ALL
SELECT  9, 13, 'vacation',    DATE '2024-11-25', DATE '2024-11-29',  5, 'approved',  TIMESTAMP '2024-11-01 10:00:00', 4    UNION ALL
SELECT 10, 14, 'sick',        DATE '2024-02-19', DATE '2024-02-20',  2, 'approved',  TIMESTAMP '2024-02-19 07:45:00', 4    UNION ALL
SELECT 11, 15, 'vacation',    DATE '2024-05-27', DATE '2024-05-31',  5, 'approved',  TIMESTAMP '2024-05-10 13:00:00', 1    UNION ALL
SELECT 12, 16, 'unpaid',      DATE '2024-09-01', DATE '2024-09-30', 30, 'denied',    TIMESTAMP '2024-08-01 09:00:00', 1    UNION ALL
SELECT 13, 17, 'vacation',    DATE '2024-07-15', DATE '2024-07-19',  5, 'approved',  TIMESTAMP '2024-07-01 10:00:00', 1    UNION ALL
SELECT 14, 18, 'sick',        DATE '2024-04-22', DATE '2024-04-22',  1, 'approved',  TIMESTAMP '2024-04-22 08:30:00', 2    UNION ALL
SELECT 15, 19, 'vacation',    DATE '2024-03-18', DATE '2024-03-22',  5, 'approved',  TIMESTAMP '2024-03-01 11:00:00', 3    UNION ALL
SELECT 16,  1, 'vacation',    DATE '2024-08-05', DATE '2024-08-09',  5, 'approved',  TIMESTAMP '2024-07-15 09:00:00', NULL UNION ALL
SELECT 17,  2, 'sick',        DATE '2024-11-04', DATE '2024-11-05',  2, 'approved',  TIMESTAMP '2024-11-04 07:00:00', NULL UNION ALL
SELECT 18,  3, 'vacation',    DATE '2024-12-02', DATE '2024-12-06',  5, 'pending',   TIMESTAMP '2024-11-18 10:00:00', NULL UNION ALL
SELECT 19,  4, 'vacation',    DATE '2024-01-15', DATE '2024-01-19',  5, 'approved',  TIMESTAMP '2024-01-05 09:00:00', NULL UNION ALL
SELECT 20, 20, 'vacation',    DATE '2024-11-11', DATE '2024-11-15',  5, 'cancelled', TIMESTAMP '2024-10-20 14:00:00', NULL;

-- =============================================================================
-- SCHEMA: dbxcarta_test_inventory
-- Insert order: categories (roots first) → warehouses → suppliers → products
--               → inventory_levels → product_suppliers
-- =============================================================================

-- Roots (parent_id NULL) must appear before children in the dataset.
INSERT INTO dbxcarta_test_inventory.categories
SELECT 1, 'Electronics', 'electronics', NULL, 'Consumer electronics and gadgets'     UNION ALL
SELECT 2, 'Clothing',    'clothing',    NULL, 'Apparel and fashion items'             UNION ALL
SELECT 3, 'Books',       'books',       NULL, 'Physical and digital reference books'  UNION ALL
SELECT 4, 'Smartphones', 'smartphones', 1,    'Mobile phones and accessories'         UNION ALL
SELECT 5, 'Laptops',     'laptops',     1,    'Portable computers and ultrabooks'     UNION ALL
SELECT 6, 'Outerwear',   'outerwear',   2,    'Jackets, coats, and outdoor clothing';

INSERT INTO dbxcarta_test_inventory.warehouses
SELECT 1, 'SEA1', 'Seattle Fulfillment Center', '123 Harbor Ave',   'Seattle',   'US', 47.6062,  -122.3321, TRUE  UNION ALL
SELECT 2, 'ORD2', 'Chicago Distribution Hub',   '456 Lakeshore Dr', 'Chicago',   'US', 41.8781,   -87.6298, TRUE  UNION ALL
SELECT 3, 'JFK3', 'New York Warehouse',          '789 Queens Blvd',  'New York',  'US', 40.7128,   -74.0060, TRUE  UNION ALL
SELECT 4, 'AMS4', 'Amsterdam EU Hub',            '10 Ringweg Zuid',  'Amsterdam', 'NL', 52.3676,     4.9041, TRUE  UNION ALL
SELECT 5, 'SIN5', 'Singapore APAC Center',       '1 Logistics Park', 'Singapore', 'SG',  1.3521,  103.8198, FALSE;

INSERT INTO dbxcarta_test_inventory.suppliers
SELECT 1, 'Apex Electronics Ltd',    'John Park',    'john@apex.com',     'KR', 14, TRUE  UNION ALL
SELECT 2, 'Global Textiles Co',      'Sara Ahmed',   'sara@gtextiles.com','BD', 30, TRUE  UNION ALL
SELECT 3, 'Pacific Books Wholesale', 'Mike Chen',    'mike@pbw.com',      'CN', 21, FALSE UNION ALL
SELECT 4, 'Nordic Components GmbH',  'Anna Schmidt', 'anna@nordic.de',    'DE', 18, TRUE  UNION ALL
SELECT 5, 'FastShip Supplies Inc',   'Tom Williams', 'tom@fastship.com',  'US',  7, FALSE;

-- Products use STRUCT (dimensions), ARRAY (tags), MAP (attributes).
-- All three complex type families are exercised across the 20 rows.
INSERT INTO dbxcarta_test_inventory.products
SELECT  1, 'SKU-0001', 'iPhone 15 Pro',                    4, 'Apple flagship smartphone with titanium frame',          999.99,  650.00, 0.19, STRUCT(14.7 AS length_cm,  7.1 AS width_cm,  0.8 AS height_cm), ARRAY('smartphone','apple','5g'),             MAP('color','black','storage','256GB'),          TRUE,  TIMESTAMP '2024-01-10 08:00:00', NULL            UNION ALL
SELECT  2, 'SKU-0002', 'Samsung Galaxy S24',               4, 'Samsung flagship Android smartphone',                    849.99,  520.00, 0.17, STRUCT(14.7 AS length_cm,  7.1 AS width_cm,  0.8 AS height_cm), ARRAY('smartphone','samsung','android'),      MAP('color','silver','storage','128GB'),         TRUE,  TIMESTAMP '2024-01-15 08:00:00', NULL            UNION ALL
SELECT  3, 'SKU-0003', 'MacBook Pro 14',                   5, 'Apple 14-inch laptop with M3 chip',                     1999.99, 1300.00, 1.61, STRUCT(31.2 AS length_cm, 22.1 AS width_cm,  1.6 AS height_cm), ARRAY('laptop','apple','m3'),                 MAP('color','silver','ram','16GB'),              TRUE,  TIMESTAMP '2024-01-20 08:00:00', NULL            UNION ALL
SELECT  4, 'SKU-0004', 'Dell XPS 15',                      5, 'Dell premium 15-inch laptop',                           1499.99,  950.00, 1.86, STRUCT(34.4 AS length_cm, 23.5 AS width_cm,  1.8 AS height_cm), ARRAY('laptop','dell','windows'),             MAP('color','platinum','ram','32GB'),            TRUE,  TIMESTAMP '2024-02-01 08:00:00', NULL            UNION ALL
SELECT  5, 'SKU-0005', 'Sony WH-1000XM5',                  1, 'Sony noise-cancelling wireless headphones',              349.99,  180.00, 0.25, STRUCT(19.5 AS length_cm, 16.5 AS width_cm,  7.8 AS height_cm), ARRAY('headphones','sony','wireless','anc'),  MAP('color','black','connectivity','bluetooth'), TRUE,  TIMESTAMP '2024-02-10 08:00:00', NULL            UNION ALL
SELECT  6, 'SKU-0006', 'iPad Pro 12.9',                    1, 'Apple iPad Pro with M2 chip',                           1099.99,  720.00, 0.68, STRUCT(28.1 AS length_cm, 21.5 AS width_cm,  0.6 AS height_cm), ARRAY('tablet','apple','m2'),                 MAP('color','space-gray','storage','256GB'),     TRUE,  TIMESTAMP '2024-02-15 08:00:00', NULL            UNION ALL
SELECT  7, 'SKU-0007', 'North Face Puffer Jacket',         6, 'Insulated puffer jacket for cold weather',               229.99,  110.00, 0.72, STRUCT(65.0 AS length_cm, 48.0 AS width_cm,  5.0 AS height_cm), ARRAY('jacket','winter','outdoor'),           MAP('color','navy','size','M'),                  TRUE,  TIMESTAMP '2024-03-01 08:00:00', NULL            UNION ALL
SELECT  8, 'SKU-0008', 'Patagonia Rain Jacket',            6, 'Lightweight waterproof rain jacket',                     179.99,   88.00, 0.41, STRUCT(62.0 AS length_cm, 47.0 AS width_cm,  3.0 AS height_cm), ARRAY('jacket','rain','waterproof'),          MAP('color','green','size','L'),                 TRUE,  TIMESTAMP '2024-03-05 08:00:00', NULL            UNION ALL
SELECT  9, 'SKU-0009', 'Clean Code',                       3, 'Robert C. Martin software craftsmanship guide',           39.99,   18.00, 0.47, STRUCT(23.5 AS length_cm, 18.5 AS width_cm,  2.9 AS height_cm), ARRAY('book','programming','software'),       MAP('format','hardcover','language','English'),  TRUE,  TIMESTAMP '2024-03-10 08:00:00', NULL            UNION ALL
SELECT 10, 'SKU-0010', 'Designing Data-Intensive Apps',    3, 'Martin Kleppmann distributed systems reference',          54.99,   25.00, 0.82, STRUCT(24.0 AS length_cm, 17.8 AS width_cm,  4.2 AS height_cm), ARRAY('book','distributed-systems','data'),   MAP('format','paperback','language','English'),  TRUE,  TIMESTAMP '2024-03-15 08:00:00', NULL            UNION ALL
SELECT 11, 'SKU-0011', 'Google Pixel 8',                   4, 'Google flagship phone with Tensor G3 chip',              699.99,  430.00, 0.19, STRUCT(15.0 AS length_cm,  7.1 AS width_cm,  0.9 AS height_cm), ARRAY('smartphone','google','android','5g'),  MAP('color','obsidian','storage','128GB'),       TRUE,  TIMESTAMP '2024-04-01 08:00:00', NULL            UNION ALL
SELECT 12, 'SKU-0012', 'LG 27" 4K Monitor',               1, '27-inch 4K UHD IPS display',                             449.99,  250.00, 5.20, STRUCT(61.5 AS length_cm, 36.4 AS width_cm,  5.2 AS height_cm), ARRAY('monitor','4k','ips'),                  MAP('resolution','3840x2160','panel','IPS'),     TRUE,  TIMESTAMP '2024-04-05 08:00:00', NULL            UNION ALL
SELECT 13, 'SKU-0013', 'Mechanical Keyboard TKL',          1, 'Compact tenkeyless mechanical keyboard with RGB',        149.99,   72.00, 0.95, STRUCT(32.0 AS length_cm, 13.0 AS width_cm,  3.5 AS height_cm), ARRAY('keyboard','mechanical','rgb'),         MAP('layout','tkl','switches','cherry-red'),     TRUE,  TIMESTAMP '2024-04-10 08:00:00', NULL            UNION ALL
SELECT 14, 'SKU-0014', 'Wool Peacoat',                     6, 'Classic double-breasted wool peacoat',                   299.99,  145.00, 1.20, STRUCT(78.0 AS length_cm, 55.0 AS width_cm,  4.0 AS height_cm), ARRAY('coat','wool','classic'),               MAP('color','charcoal','size','XL'),             TRUE,  TIMESTAMP '2024-04-15 08:00:00', NULL            UNION ALL
SELECT 15, 'SKU-0015', 'Logitech MX Master 3S',            1, 'Advanced wireless ergonomic mouse',                       99.99,   48.00, 0.14, STRUCT(12.4 AS length_cm,  8.5 AS width_cm,  5.1 AS height_cm), ARRAY('mouse','wireless','ergonomic'),        MAP('color','graphite','dpi','8000'),            TRUE,  TIMESTAMP '2024-05-01 08:00:00', NULL            UNION ALL
SELECT 16, 'SKU-0016', 'The Pragmatic Programmer',         3, 'Andrew Hunt and David Thomas developer career guide',     49.99,   22.00, 0.56, STRUCT(23.5 AS length_cm, 19.0 AS width_cm,  3.1 AS height_cm), ARRAY('book','programming','career'),         MAP('format','paperback','edition','20th'),      TRUE,  TIMESTAMP '2024-05-05 08:00:00', NULL            UNION ALL
SELECT 17, 'SKU-0017', 'Samsung 65" QLED TV',              1, '65-inch 4K QLED smart television',                      1199.99,  750.00,24.10, STRUCT(144.8 AS length_cm,83.0 AS width_cm,  8.6 AS height_cm), ARRAY('tv','samsung','qled','4k'),            MAP('size','65-inch','hdr','HDR10+'),            TRUE,  TIMESTAMP '2024-05-10 08:00:00', NULL            UNION ALL
SELECT 18, 'SKU-0018', 'OnePlus 12',                       4, 'OnePlus flagship with Snapdragon 8 Gen 3',               799.99,  490.00, 0.22, STRUCT(16.4 AS length_cm,  7.5 AS width_cm,  0.9 AS height_cm), ARRAY('smartphone','oneplus','android'),      MAP('color','silky-black','storage','256GB'),    TRUE,  TIMESTAMP '2024-05-15 08:00:00', NULL            UNION ALL
SELECT 19, 'SKU-0019', 'Lenovo ThinkPad X1 Carbon',        5, 'Business ultrabook with 14-inch display',               1349.99,  880.00, 1.12, STRUCT(31.5 AS length_cm, 22.2 AS width_cm,  1.5 AS height_cm), ARRAY('laptop','lenovo','business'),          MAP('color','black','ram','16GB'),               TRUE,  TIMESTAMP '2024-05-20 08:00:00', NULL            UNION ALL
SELECT 20, 'SKU-0020', 'Arc\'teryx Alpha Shell',           6, 'Gore-Tex hardshell jacket for mountaineering',           599.99,  350.00, 0.55, STRUCT(68.0 AS length_cm, 53.0 AS width_cm,  3.0 AS height_cm), ARRAY('jacket','goretex','mountaineering'),   MAP('color','black','size','S'),                 FALSE, TIMESTAMP '2024-01-01 08:00:00', DATE '2024-12-31';

INSERT INTO dbxcarta_test_inventory.inventory_levels
SELECT  1,  1, 1, 150,  20,  50, 30, TIMESTAMP '2024-10-01 08:00:00' UNION ALL
SELECT  2,  2, 1, 200,  30,  60, 40, TIMESTAMP '2024-10-01 08:00:00' UNION ALL
SELECT  3,  3, 1,  75,   5,  25, 20, TIMESTAMP '2024-10-01 08:00:00' UNION ALL
SELECT  4,  4, 2,  60,  10,  20, 20, TIMESTAMP '2024-10-01 08:00:00' UNION ALL
SELECT  5,  5, 1, 100,  12,  30, 25, TIMESTAMP '2024-10-01 08:00:00' UNION ALL
SELECT  6,  6, 3,  50,   5,  15, 15, TIMESTAMP '2024-10-01 08:00:00' UNION ALL
SELECT  7,  7, 1,  90,  20,  40, 30, TIMESTAMP '2024-10-01 08:00:00' UNION ALL
SELECT  8,  8, 2,  70,  15,  25, 20, TIMESTAMP '2024-10-01 08:00:00' UNION ALL
SELECT  9,  9, 4, 200,  10,  50, 40, TIMESTAMP '2024-10-01 08:00:00' UNION ALL
SELECT 10, 10, 5, 180,   8,  40, 35, TIMESTAMP '2024-10-01 08:00:00' UNION ALL
SELECT 11, 11, 1, 110,  25,  35, 30, TIMESTAMP '2024-10-01 08:00:00' UNION ALL
SELECT 12, 12, 2,  30,   3,  10, 10, TIMESTAMP '2024-10-01 08:00:00' UNION ALL
SELECT 13, 13, 3,  85,  10,  20, 20, TIMESTAMP '2024-10-01 08:00:00' UNION ALL
SELECT 14, 14, 4,  45,   5,  15, 15, TIMESTAMP '2024-10-01 08:00:00' UNION ALL
-- qty_on_hand below reorder_point — exercises demo_q4 (products below reorder point)
SELECT 15, 15, 1,  18,   4,   8, 25, TIMESTAMP '2024-10-01 08:00:00' UNION ALL
SELECT 16, 16, 5, 300,  20,  80, 60, TIMESTAMP '2024-10-01 08:00:00' UNION ALL
SELECT 17, 17, 2,   5,   2,   3,  8, TIMESTAMP '2024-10-01 08:00:00' UNION ALL
SELECT 18, 18, 1, 120,  15,  30, 25, TIMESTAMP '2024-10-01 08:00:00' UNION ALL
SELECT 19, 19, 4,  10,   3,   5, 20, TIMESTAMP '2024-10-01 08:00:00' UNION ALL
SELECT 20, 20, 2,  40,   8,  10, 15, TIMESTAMP '2024-10-01 08:00:00';

-- Composite PK: no duplicate (product_id, supplier_id) pairs.
INSERT INTO dbxcarta_test_inventory.product_suppliers
SELECT  1, 1,  620.00, 10, 14, TRUE  UNION ALL
SELECT  1, 4,  640.00,  5, 18, FALSE UNION ALL
SELECT  2, 1,  510.00, 10, 14, TRUE  UNION ALL
SELECT  3, 4, 1280.00,  2, 18, TRUE  UNION ALL
SELECT  4, 4,  940.00,  3, 18, TRUE  UNION ALL
SELECT  5, 1,  175.00,  5, 14, TRUE  UNION ALL
SELECT  6, 1,  710.00,  5, 14, TRUE  UNION ALL
SELECT  7, 2,  108.00, 20, 30, TRUE  UNION ALL
SELECT  8, 2,   86.00, 15, 30, TRUE  UNION ALL
SELECT  9, 3,   17.50, 50, 21, TRUE  UNION ALL
SELECT 10, 3,   24.00, 50, 21, TRUE  UNION ALL
SELECT 11, 1,  425.00, 10, 14, TRUE  UNION ALL
SELECT 12, 4,  245.00,  5, 18, TRUE  UNION ALL
SELECT 13, 5,   70.00, 20,  7, TRUE  UNION ALL
SELECT 14, 2,  142.00, 10, 30, TRUE  UNION ALL
SELECT 15, 5,   47.00, 30,  7, TRUE  UNION ALL
SELECT 16, 3,   21.50, 50, 21, TRUE  UNION ALL
SELECT 17, 1,  740.00,  3, 14, TRUE  UNION ALL
SELECT 18, 1,  485.00, 10, 14, TRUE  UNION ALL
SELECT 19, 4,  870.00,  3, 18, TRUE;

-- =============================================================================
-- SCHEMA: dbxcarta_test_events
-- Insert order: user_profiles → user_sessions → page_views → ab_experiments
-- =============================================================================

-- preferences uses MAP<STRING,STRING>; avatar_thumbnail is BINARY (NULL is fine for tests).
INSERT INTO dbxcarta_test_events.user_profiles
SELECT  1, 'usr_a1b001', 'alice_dev',      'alice@example.com',   'en-US', 'America/Los_Angeles', MAP('theme','dark','notifications','on'),   NULL, DATE '2022-03-15', TIMESTAMP '2024-11-20 14:30:00', TRUE  UNION ALL
SELECT  2, 'usr_b2c002', 'bob_codes',      'bob@example.com',     'en-US', 'America/New_York',    MAP('theme','light','notifications','off'),  NULL, DATE '2021-07-22', TIMESTAMP '2024-11-19 10:15:00', TRUE  UNION ALL
SELECT  3, 'usr_c3d003', 'carol_ux',       'carol@example.com',   'fr-FR', 'Europe/Paris',        MAP('theme','dark','language','fr'),         NULL, DATE '2022-11-01', TIMESTAMP '2024-11-18 16:45:00', TRUE  UNION ALL
SELECT  4, 'usr_d4e004', 'david_ops',      'david@example.com',   'en-GB', 'Europe/London',       MAP('theme','light','timezone','London'),    NULL, DATE '2020-05-10', TIMESTAMP '2024-11-17 09:00:00', TRUE  UNION ALL
SELECT  5, 'usr_e5f005', 'emma_data',      'emma@example.com',    'de-DE', 'Europe/Berlin',       MAP('theme','dark','notifications','on'),   NULL, DATE '2023-01-05', TIMESTAMP '2024-11-20 11:20:00', TRUE  UNION ALL
SELECT  6, 'usr_f6g006', 'frank_ml',       'frank@example.com',   'en-US', 'America/Chicago',     MAP('theme','dark','beta','true'),           NULL, DATE '2022-08-18', TIMESTAMP '2024-11-15 13:00:00', TRUE  UNION ALL
SELECT  7, 'usr_g7h007', 'grace_be',       'grace@example.com',   'en-US', 'America/Denver',      MAP('theme','light','notifications','on'),  NULL, DATE '2021-12-01', TIMESTAMP '2024-11-14 08:30:00', FALSE UNION ALL
SELECT  8, 'usr_h8i008', 'henry_fe',       'henry@example.com',   'ja-JP', 'Asia/Tokyo',          MAP('theme','dark','language','ja'),         NULL, DATE '2023-04-20', TIMESTAMP '2024-11-20 06:00:00', TRUE  UNION ALL
SELECT  9, 'usr_i9j009', 'isabella_pm',   'isabella@example.com', 'en-US', 'America/Los_Angeles', MAP('theme','light','notifications','off'),  NULL, DATE '2020-09-14', TIMESTAMP '2024-11-19 15:45:00', TRUE  UNION ALL
SELECT 10, 'usr_j0k010', 'james_qa',       'james@example.com',   'en-AU', 'Australia/Sydney',    MAP('theme','dark','notifications','on'),   NULL, DATE '2022-02-28', TIMESTAMP '2024-11-13 22:00:00', TRUE  UNION ALL
SELECT 11, 'usr_k1l011', 'karen_design',   'karen@example.com',   'en-US', 'America/New_York',    MAP('theme','light','beta','false'),         NULL, DATE '2021-06-07', TIMESTAMP '2024-11-12 10:10:00', TRUE  UNION ALL
SELECT 12, 'usr_l2m012', 'liam_devrel',    'liam@example.com',    'en-US', 'America/Los_Angeles', MAP('theme','dark','notifications','on'),   NULL, DATE '2023-07-11', TIMESTAMP '2024-11-11 14:20:00', TRUE  UNION ALL
SELECT 13, 'usr_m3n013', 'mia_growth',     'mia@example.com',     'es-ES', 'Europe/Madrid',       MAP('theme','light','language','es'),        NULL, DATE '2022-10-30', TIMESTAMP '2024-11-10 09:30:00', TRUE  UNION ALL
SELECT 14, 'usr_n4o014', 'noah_platform',  'noah@example.com',    'en-US', 'America/Chicago',     MAP('theme','dark','beta','true'),           NULL, DATE '2021-03-25', TIMESTAMP '2024-11-09 16:00:00', TRUE  UNION ALL
SELECT 15, 'usr_o5p015', 'olivia_infra',   'olivia@example.com',  'en-US', 'America/Los_Angeles', MAP('theme','dark','notifications','on'),   NULL, DATE '2020-11-19', TIMESTAMP '2024-11-08 11:45:00', TRUE  UNION ALL
SELECT 16, 'usr_p6q016', 'peter_security', 'peter@example.com',   'en-US', 'America/New_York',    MAP('theme','light','notifications','off'),  NULL, DATE '2023-02-14', TIMESTAMP '2024-11-07 08:15:00', FALSE UNION ALL
SELECT 17, 'usr_q7r017', 'quinn_api',      'quinn@example.com',   'pt-BR', 'America/Sao_Paulo',   MAP('theme','dark','language','pt'),         NULL, DATE '2022-05-03', TIMESTAMP '2024-11-06 13:30:00', TRUE  UNION ALL
SELECT 18, 'usr_r8s018', 'rachel_mobile',  'rachel@example.com',  'en-US', 'America/Los_Angeles', MAP('theme','dark','beta','true'),           NULL, DATE '2021-09-08', TIMESTAMP '2024-11-05 10:00:00', TRUE  UNION ALL
SELECT 19, 'usr_s9t019', 'samuel_bi',      'samuel@example.com',  'ko-KR', 'Asia/Seoul',          MAP('theme','light','language','ko'),        NULL, DATE '2022-12-22', TIMESTAMP '2024-11-04 07:00:00', TRUE  UNION ALL
SELECT 20, 'usr_t0u020', 'tina_cx',        'tina@example.com',    'en-US', 'America/Denver',      MAP('theme','light','notifications','on'),  NULL, DATE '2023-08-31', TIMESTAMP '2024-11-03 15:00:00', TRUE;

-- event_sequence uses ARRAY<STRING>.
INSERT INTO dbxcarta_test_events.user_sessions
SELECT  1,  1, 'sess_001', TIMESTAMP '2024-11-20 14:00:00', TIMESTAMP '2024-11-20 14:42:00', 2520, 'desktop', 'macOS 14',     'Chrome 120',  '192.168.1.x', ARRAY('page_view','click','scroll','purchase'),  8, FALSE UNION ALL
SELECT  2,  2, 'sess_002', TIMESTAMP '2024-11-19 10:00:00', TIMESTAMP '2024-11-19 10:08:00',  480, 'mobile',  'iOS 17',       'Safari 17',   '10.0.0.x',    ARRAY('page_view'),                              1, TRUE  UNION ALL
SELECT  3,  3, 'sess_003', TIMESTAMP '2024-11-18 16:30:00', TIMESTAMP '2024-11-18 17:05:00', 2100, 'desktop', 'Windows 11',   'Firefox 120', '172.16.x.x',  ARRAY('page_view','scroll','add_to_cart'),       5, FALSE UNION ALL
SELECT  4,  4, 'sess_004', TIMESTAMP '2024-11-17 09:00:00', TIMESTAMP '2024-11-17 09:25:00', 1500, 'tablet',  'iPadOS 17',    'Safari 17',   '192.168.2.x', ARRAY('page_view','click','video_play'),         4, FALSE UNION ALL
SELECT  5,  5, 'sess_005', TIMESTAMP '2024-11-20 11:00:00', TIMESTAMP '2024-11-20 11:55:00', 3300, 'desktop', 'macOS 14',     'Chrome 120',  '10.1.x.x',    ARRAY('page_view','search','click','purchase'),  10, FALSE UNION ALL
SELECT  6,  6, 'sess_006', TIMESTAMP '2024-11-15 13:00:00', TIMESTAMP '2024-11-15 13:12:00',  720, 'mobile',  'Android 14',   'Chrome 120',  '172.20.x.x',  ARRAY('page_view','click'),                      2, FALSE UNION ALL
SELECT  7,  7, 'sess_007', TIMESTAMP '2024-11-14 08:15:00', TIMESTAMP '2024-11-14 08:50:00', 2100, 'desktop', 'Windows 11',   'Edge 119',    '10.2.x.x',    ARRAY('page_view','scroll','search'),             6, FALSE UNION ALL
SELECT  8,  8, 'sess_008', TIMESTAMP '2024-11-20 06:00:00', TIMESTAMP '2024-11-20 06:20:00', 1200, 'mobile',  'iOS 17',       'Safari 17',   '192.168.3.x', ARRAY('page_view','add_to_cart','checkout'),     3, FALSE UNION ALL
SELECT  9,  9, 'sess_009', TIMESTAMP '2024-11-19 15:30:00', TIMESTAMP '2024-11-19 16:10:00', 2400, 'desktop', 'macOS 14',     'Safari 17',   '10.3.x.x',    ARRAY('page_view','click','scroll','purchase'),   7, FALSE UNION ALL
SELECT 10, 10, 'sess_010', TIMESTAMP '2024-11-13 22:00:00', TIMESTAMP '2024-11-13 22:35:00', 2100, 'desktop', 'Windows 11',   'Chrome 120',  '172.18.x.x',  ARRAY('page_view','search','add_to_cart'),        5, FALSE UNION ALL
SELECT 11, 11, 'sess_011', TIMESTAMP '2024-11-12 10:00:00', TIMESTAMP '2024-11-12 10:05:00',  300, 'mobile',  'Android 14',   'Chrome 120',  '192.168.4.x', ARRAY('page_view'),                               1, TRUE  UNION ALL
SELECT 12, 12, 'sess_012', TIMESTAMP '2024-11-11 14:00:00', TIMESTAMP '2024-11-11 14:48:00', 2880, 'desktop', 'macOS 14',     'Chrome 120',  '10.4.x.x',    ARRAY('page_view','video_play','scroll','click'), 9, FALSE UNION ALL
SELECT 13, 13, 'sess_013', TIMESTAMP '2024-11-10 09:15:00', TIMESTAMP '2024-11-10 09:40:00', 1500, 'tablet',  'Android 14',   'Chrome 120',  '172.22.x.x',  ARRAY('page_view','click','purchase'),             4, FALSE UNION ALL
SELECT 14, 14, 'sess_014', TIMESTAMP '2024-11-09 16:00:00', TIMESTAMP '2024-11-09 16:30:00', 1800, 'desktop', 'Windows 11',   'Firefox 120', '10.5.x.x',    ARRAY('page_view','scroll','search','click'),      6, FALSE UNION ALL
SELECT 15, 15, 'sess_015', TIMESTAMP '2024-11-08 11:30:00', TIMESTAMP '2024-11-08 12:10:00', 2400, 'desktop', 'macOS 14',     'Chrome 120',  '192.168.5.x', ARRAY('page_view','add_to_cart','checkout'),       5, FALSE UNION ALL
SELECT 16, 16, 'sess_016', TIMESTAMP '2024-11-07 08:00:00', TIMESTAMP '2024-11-07 08:04:00',  240, 'mobile',  'iOS 17',       'Safari 17',   '10.6.x.x',    ARRAY('page_view'),                                1, TRUE  UNION ALL
SELECT 17, 17, 'sess_017', TIMESTAMP '2024-11-06 13:00:00', TIMESTAMP '2024-11-06 13:45:00', 2700, 'desktop', 'Linux',        'Firefox 120', '172.24.x.x',  ARRAY('page_view','click','scroll','purchase'),    8, FALSE UNION ALL
SELECT 18, 18, 'sess_018', TIMESTAMP '2024-11-05 10:00:00', TIMESTAMP '2024-11-05 10:22:00', 1320, 'mobile',  'iOS 17',       'Safari 17',   '192.168.6.x', ARRAY('page_view','search','click'),               3, FALSE UNION ALL
SELECT 19, 19, 'sess_019', TIMESTAMP '2024-11-04 07:00:00', TIMESTAMP '2024-11-04 07:35:00', 2100, 'desktop', 'Windows 11',   'Chrome 120',  '10.7.x.x',    ARRAY('page_view','video_play','scroll'),           5, FALSE UNION ALL
SELECT 20, 20, 'sess_020', TIMESTAMP '2024-11-03 15:00:00', TIMESTAMP '2024-11-03 15:18:00', 1080, 'tablet',  'iPadOS 17',    'Safari 17',   '172.26.x.x',  ARRAY('page_view','click','add_to_cart'),           3, FALSE;

-- referrer_parsed uses STRUCT; raw_payload uses VARIANT (PARSE_JSON).
INSERT INTO dbxcarta_test_events.page_views
SELECT  1,  1, '/products/iphone-15',     'iPhone 15 Pro',           'https://google.com/search',   STRUCT('google.com'    AS domain, '/search'     AS path, 'organic'  AS medium, NULL             AS campaign), PARSE_JSON('{"event":"page_view","product_id":1}'),   980, TIMESTAMP '2024-11-20 14:05:00' UNION ALL
SELECT  2,  1, '/cart',                   'Your Cart',               'https://store.example.com',   STRUCT('store.example.com' AS domain, '/products' AS path, 'internal' AS medium, NULL             AS campaign), PARSE_JSON('{"event":"page_view","section":"cart"}'),  640, TIMESTAMP '2024-11-20 14:18:00' UNION ALL
SELECT  3,  2, '/products/macbook-pro',   'MacBook Pro 14',          'https://bing.com/search',     STRUCT('bing.com'      AS domain, '/search'     AS path, 'organic'  AS medium, NULL             AS campaign), PARSE_JSON('{"event":"page_view","product_id":3}'),  1120, TIMESTAMP '2024-11-19 10:02:00' UNION ALL
SELECT  4,  3, '/products/samsung-s24',   'Samsung Galaxy S24',      'https://facebook.com/ad',     STRUCT('facebook.com'  AS domain, '/ad'         AS path, 'paid'     AS medium, 'holiday_sale'   AS campaign), PARSE_JSON('{"event":"page_view","product_id":2}'),   870, TIMESTAMP '2024-11-18 16:33:00' UNION ALL
SELECT  5,  4, '/blog/best-tablets-2024', 'Best Tablets 2024',       'https://twitter.com/post',    STRUCT('twitter.com'   AS domain, '/post'       AS path, 'social'   AS medium, NULL             AS campaign), PARSE_JSON('{"event":"page_view","content":"blog"}'),  760, TIMESTAMP '2024-11-17 09:05:00' UNION ALL
SELECT  6,  5, '/products/dell-xps',      'Dell XPS 15',             'https://google.com/shopping', STRUCT('google.com'    AS domain, '/shopping'   AS path, 'paid'     AS medium, 'laptop_deals'   AS campaign), PARSE_JSON('{"event":"page_view","product_id":4}'),  1350, TIMESTAMP '2024-11-20 11:03:00' UNION ALL
SELECT  7,  6, '/account/orders',         'Order History',           NULL,                           STRUCT(NULL            AS domain, NULL          AS path, 'direct'   AS medium, NULL             AS campaign), PARSE_JSON('{"event":"page_view","section":"account"}'), 520, TIMESTAMP '2024-11-15 13:02:00' UNION ALL
SELECT  8,  7, '/products/sony-wh1000',   'Sony WH-1000XM5',         'https://reddit.com/r/audio',  STRUCT('reddit.com'    AS domain, '/r/audio'    AS path, 'social'   AS medium, NULL             AS campaign), PARSE_JSON('{"event":"page_view","product_id":5}'),   820, TIMESTAMP '2024-11-14 08:18:00' UNION ALL
SELECT  9,  8, '/checkout',               'Checkout',                'https://store.example.com',   STRUCT('store.example.com' AS domain, '/cart'   AS path, 'internal' AS medium, NULL             AS campaign), PARSE_JSON('{"event":"page_view","section":"checkout"}'), 490, TIMESTAMP '2024-11-20 06:10:00' UNION ALL
SELECT 10,  9, '/products/ipad-pro',      'iPad Pro 12.9',           'https://google.com/search',   STRUCT('google.com'    AS domain, '/search'     AS path, 'organic'  AS medium, NULL             AS campaign), PARSE_JSON('{"event":"page_view","product_id":6}'),  1050, TIMESTAMP '2024-11-19 15:33:00' UNION ALL
SELECT 11, 10, '/products/keyboard-tkl',  'Mechanical Keyboard TKL', 'https://duckduckgo.com',      STRUCT('duckduckgo.com' AS domain, '/'          AS path, 'organic'  AS medium, NULL             AS campaign), PARSE_JSON('{"event":"page_view","product_id":13}'),  670, TIMESTAMP '2024-11-13 22:04:00' UNION ALL
SELECT 12, 12, '/products/lg-monitor',    'LG 27" 4K Monitor',       'https://techradar.com',       STRUCT('techradar.com' AS domain, '/reviews'    AS path, 'referral' AS medium, NULL             AS campaign), PARSE_JSON('{"event":"page_view","product_id":12}'), 1200, TIMESTAMP '2024-11-11 14:05:00' UNION ALL
SELECT 13, 13, '/checkout',               'Checkout',                'https://store.example.com',   STRUCT('store.example.com' AS domain, '/products' AS path, 'internal' AS medium, NULL            AS campaign), PARSE_JSON('{"event":"page_view","section":"checkout"}'), 430, TIMESTAMP '2024-11-10 09:28:00' UNION ALL
SELECT 14, 14, '/products/clean-code',    'Clean Code',              'https://goodreads.com',       STRUCT('goodreads.com' AS domain, '/book'       AS path, 'referral' AS medium, NULL             AS campaign), PARSE_JSON('{"event":"page_view","product_id":9}'),   730, TIMESTAMP '2024-11-09 16:05:00' UNION ALL
SELECT 15, 15, '/cart',                   'Your Cart',               'https://store.example.com',   STRUCT('store.example.com' AS domain, '/products' AS path, 'internal' AS medium, NULL            AS campaign), PARSE_JSON('{"event":"page_view","section":"cart"}'),  580, TIMESTAMP '2024-11-08 11:35:00' UNION ALL
SELECT 16, 17, '/products/macbook-pro',   'MacBook Pro 14',          'https://google.com/search',   STRUCT('google.com'    AS domain, '/search'     AS path, 'organic'  AS medium, NULL             AS campaign), PARSE_JSON('{"event":"page_view","product_id":3}'),   990, TIMESTAMP '2024-11-06 13:05:00' UNION ALL
SELECT 17, 18, '/search',                 'Search Results',          'https://google.com/search',   STRUCT('google.com'    AS domain, '/search'     AS path, 'organic'  AS medium, NULL             AS campaign), PARSE_JSON('{"event":"page_view","section":"search"}'), 450, TIMESTAMP '2024-11-05 10:03:00' UNION ALL
SELECT 18, 19, '/products/samsung-tv',    'Samsung 65" QLED TV',     'https://youtube.com/review',  STRUCT('youtube.com'   AS domain, '/watch'      AS path, 'referral' AS medium, NULL             AS campaign), PARSE_JSON('{"event":"page_view","product_id":17}'), 1480, TIMESTAMP '2024-11-04 07:05:00' UNION ALL
SELECT 19, 20, '/products/iphone-15',     'iPhone 15 Pro',           'https://facebook.com/ad',     STRUCT('facebook.com'  AS domain, '/ad'         AS path, 'paid'     AS medium, 'black_friday'   AS campaign), PARSE_JSON('{"event":"page_view","product_id":1}'),   860, TIMESTAMP '2024-11-03 15:03:00' UNION ALL
SELECT 20, 20, '/cart',                   'Your Cart',               'https://store.example.com',   STRUCT('store.example.com' AS domain, '/products' AS path, 'internal' AS medium, NULL            AS campaign), PARSE_JSON('{"event":"page_view","section":"cart"}'),  510, TIMESTAMP '2024-11-03 15:10:00';

-- Experiments cover two keys with three variants each — exercises demo_q5.
INSERT INTO dbxcarta_test_events.ab_experiments
SELECT  1,  1, 'checkout_flow_v2',    'treatment_a', TIMESTAMP '2024-10-01 00:00:00', TRUE,  TIMESTAMP '2024-11-20 14:40:00' UNION ALL
SELECT  2,  2, 'checkout_flow_v2',    'control',     TIMESTAMP '2024-10-01 00:00:00', FALSE, NULL                            UNION ALL
SELECT  3,  3, 'checkout_flow_v2',    'treatment_b', TIMESTAMP '2024-10-01 00:00:00', TRUE,  TIMESTAMP '2024-11-18 16:55:00' UNION ALL
SELECT  4,  4, 'checkout_flow_v2',    'control',     TIMESTAMP '2024-10-01 00:00:00', FALSE, NULL                            UNION ALL
SELECT  5,  5, 'checkout_flow_v2',    'treatment_a', TIMESTAMP '2024-10-01 00:00:00', TRUE,  TIMESTAMP '2024-11-20 11:50:00' UNION ALL
SELECT  6,  6, 'checkout_flow_v2',    'treatment_b', TIMESTAMP '2024-10-01 00:00:00', FALSE, NULL                            UNION ALL
SELECT  7,  7, 'checkout_flow_v2',    'control',     TIMESTAMP '2024-10-01 00:00:00', FALSE, NULL                            UNION ALL
SELECT  8,  8, 'checkout_flow_v2',    'treatment_a', TIMESTAMP '2024-10-01 00:00:00', TRUE,  TIMESTAMP '2024-11-20 06:18:00' UNION ALL
SELECT  9,  9, 'checkout_flow_v2',    'control',     TIMESTAMP '2024-10-01 00:00:00', TRUE,  TIMESTAMP '2024-11-19 16:05:00' UNION ALL
SELECT 10, 10, 'checkout_flow_v2',    'treatment_b', TIMESTAMP '2024-10-01 00:00:00', FALSE, NULL                            UNION ALL
SELECT 11, 11, 'homepage_hero_image', 'control',     TIMESTAMP '2024-09-15 00:00:00', FALSE, NULL                            UNION ALL
SELECT 12, 12, 'homepage_hero_image', 'treatment_a', TIMESTAMP '2024-09-15 00:00:00', TRUE,  TIMESTAMP '2024-11-11 14:30:00' UNION ALL
SELECT 13, 13, 'homepage_hero_image', 'treatment_b', TIMESTAMP '2024-09-15 00:00:00', TRUE,  TIMESTAMP '2024-11-10 09:35:00' UNION ALL
SELECT 14, 14, 'homepage_hero_image', 'control',     TIMESTAMP '2024-09-15 00:00:00', FALSE, NULL                            UNION ALL
SELECT 15, 15, 'homepage_hero_image', 'treatment_a', TIMESTAMP '2024-09-15 00:00:00', FALSE, NULL                            UNION ALL
SELECT 16, 16, 'homepage_hero_image', 'treatment_b', TIMESTAMP '2024-09-15 00:00:00', FALSE, NULL                            UNION ALL
SELECT 17, 17, 'homepage_hero_image', 'control',     TIMESTAMP '2024-09-15 00:00:00', TRUE,  TIMESTAMP '2024-11-06 13:40:00' UNION ALL
SELECT 18, 18, 'homepage_hero_image', 'treatment_a', TIMESTAMP '2024-09-15 00:00:00', FALSE, NULL                            UNION ALL
SELECT 19, 19, 'homepage_hero_image', 'treatment_b', TIMESTAMP '2024-09-15 00:00:00', TRUE,  TIMESTAMP '2024-11-04 07:30:00' UNION ALL
SELECT 20, 20, 'homepage_hero_image', 'control',     TIMESTAMP '2024-09-15 00:00:00', FALSE, NULL;

-- =============================================================================
-- SCHEMA: dbxcarta_test_sales
-- Insert order: customers → promotions → orders → order_items → payments
-- orders.employee_id references hr.employees (must be loaded first).
-- order_items.product_id references inventory.products (must be loaded first).
-- =============================================================================

INSERT INTO dbxcarta_test_sales.customers
SELECT  1, 'CRM-10001', 'James',    'Harrison', 'james.harrison@email.com',  '+1-206-555-0101', 'gold',     12450.00, TIMESTAMP '2021-02-10 10:00:00', TIMESTAMP '2024-10-15 08:00:00', TRUE  UNION ALL
SELECT  2, 'CRM-10002', 'Sofia',    'Nguyen',   'sofia.nguyen@email.com',    '+1-212-555-0102', 'platinum', 28900.00, TIMESTAMP '2020-06-22 10:00:00', TIMESTAMP '2024-11-01 10:00:00', TRUE  UNION ALL
SELECT  3, 'CRM-10003', 'Michael',  'Chen',     'michael.chen@email.com',    '+1-512-555-0103', 'silver',    5200.00, TIMESTAMP '2022-01-14 10:00:00', TIMESTAMP '2024-09-20 10:00:00', TRUE  UNION ALL
SELECT  4, 'CRM-10004', 'Emily',    'Patel',    'emily.patel@email.com',     '+1-312-555-0104', 'gold',      9800.00, TIMESTAMP '2021-09-03 10:00:00', TIMESTAMP '2024-11-10 10:00:00', TRUE  UNION ALL
SELECT  5, 'CRM-10005', 'Daniel',   'Kim',      'daniel.kim@email.com',      '+1-206-555-0105', 'standard',  1100.00, TIMESTAMP '2023-05-17 10:00:00', TIMESTAMP '2024-08-30 10:00:00', TRUE  UNION ALL
SELECT  6, 'CRM-10006', 'Aisha',    'Williams', 'aisha.williams@email.com',  '+1-718-555-0106', 'platinum', 35200.00, TIMESTAMP '2019-11-08 10:00:00', TIMESTAMP '2024-11-18 10:00:00', TRUE  UNION ALL
SELECT  7, 'CRM-10007', 'Lucas',    'Oliveira', 'lucas.oliveira@email.com',  '+1-512-555-0107', 'silver',    3750.00, TIMESTAMP '2022-07-29 10:00:00', TIMESTAMP '2024-10-05 10:00:00', TRUE  UNION ALL
SELECT  8, 'CRM-10008', 'Chloe',    'Johnson',  'chloe.johnson@email.com',   '+1-312-555-0108', 'gold',     11200.00, TIMESTAMP '2021-03-11 10:00:00', TIMESTAMP '2024-11-12 10:00:00', TRUE  UNION ALL
SELECT  9, 'CRM-10009', 'Ethan',    'Brown',    'ethan.brown@email.com',     '+1-206-555-0109', 'standard',   850.00, TIMESTAMP '2023-09-21 10:00:00', TIMESTAMP '2024-07-14 10:00:00', TRUE  UNION ALL
SELECT 10, 'CRM-10010', 'Isabella', 'Garcia',   'isabella.garcia@email.com', '+1-718-555-0110', 'gold',      8600.00, TIMESTAMP '2021-12-05 10:00:00', TIMESTAMP '2024-11-05 10:00:00', TRUE  UNION ALL
SELECT 11, 'CRM-10011', 'Noah',     'Martinez', 'noah.martinez@email.com',   '+1-512-555-0111', 'standard',  1450.00, TIMESTAMP '2023-02-18 10:00:00', TIMESTAMP '2024-06-22 10:00:00', FALSE UNION ALL
SELECT 12, 'CRM-10012', 'Ava',      'Wilson',   'ava.wilson@email.com',      '+1-312-555-0112', 'silver',    4100.00, TIMESTAMP '2022-04-07 10:00:00', TIMESTAMP '2024-10-28 10:00:00', TRUE  UNION ALL
SELECT 13, 'CRM-10013', 'Liam',     'Taylor',   'liam.taylor@email.com',     '+1-206-555-0113', 'platinum', 22700.00, TIMESTAMP '2020-08-14 10:00:00', TIMESTAMP '2024-11-19 10:00:00', TRUE  UNION ALL
SELECT 14, 'CRM-10014', 'Mia',      'Anderson', 'mia.anderson@email.com',    '+1-718-555-0114', 'gold',      7300.00, TIMESTAMP '2021-06-30 10:00:00', TIMESTAMP '2024-11-08 10:00:00', TRUE  UNION ALL
SELECT 15, 'CRM-10015', 'Oliver',   'Thomas',   'oliver.thomas@email.com',   '+1-512-555-0115', 'standard',  2200.00, TIMESTAMP '2023-01-09 10:00:00', TIMESTAMP '2024-09-03 10:00:00', TRUE  UNION ALL
SELECT 16, 'CRM-10016', 'Emma',     'Jackson',  'emma.jackson@email.com',    '+1-312-555-0116', 'silver',    6500.00, TIMESTAMP '2022-10-20 10:00:00', TIMESTAMP '2024-11-14 10:00:00', TRUE  UNION ALL
SELECT 17, 'CRM-10017', 'William',  'White',    'william.white@email.com',   '+1-206-555-0117', 'gold',     14800.00, TIMESTAMP '2020-03-25 10:00:00', TIMESTAMP '2024-11-20 10:00:00', TRUE  UNION ALL
SELECT 18, 'CRM-10018', 'Sophia',   'Harris',   'sophia.harris@email.com',   '+1-718-555-0118', 'platinum', 41500.00, TIMESTAMP '2019-07-16 10:00:00', TIMESTAMP '2024-11-17 10:00:00', TRUE  UNION ALL
SELECT 19, 'CRM-10019', 'Benjamin', 'Martin',   'benjamin.martin@email.com', '+1-512-555-0119', 'standard',  3300.00, TIMESTAMP '2022-11-04 10:00:00', TIMESTAMP '2024-08-11 10:00:00', TRUE  UNION ALL
SELECT 20, 'CRM-10020', 'Charlotte','Thompson', 'charlotte.thompson@email.com','+1-312-555-0120','silver',   5900.00, TIMESTAMP '2022-06-13 10:00:00', TIMESTAMP '2024-11-11 10:00:00', TRUE;

INSERT INTO dbxcarta_test_sales.promotions
SELECT 1, 'WELCOME10', 'New customer 10% off first order',     'percent',  10.00, DATE '2024-01-01', DATE '2024-12-31', 342,  TRUE  UNION ALL
SELECT 2, 'SAVE50',    '$50 off orders over $500',             'fixed',    50.00, DATE '2024-10-01', DATE '2024-10-31', 189,  FALSE UNION ALL
SELECT 3, 'FREESHIP',  'Free shipping on all orders',          'free_shipping', 0.00, DATE '2024-11-01', DATE '2024-11-30', 521, FALSE UNION ALL
SELECT 4, 'HOLIDAY20', 'Holiday season 20% discount',         'percent',  20.00, DATE '2024-12-01', DATE '2024-12-31', 0,    TRUE  UNION ALL
SELECT 5, 'PLATINUM15','Platinum member exclusive 15% off',   'percent',  15.00, DATE '2024-01-01', DATE '2024-12-31', 87,   TRUE  UNION ALL
SELECT 6, 'TECH100',   '$100 off electronics over $1000',     'fixed',   100.00, DATE '2024-09-01', DATE '2024-09-30', 64,   FALSE UNION ALL
SELECT 7, 'SUMMER5',   'Summer sale 5% off apparel',          'percent',   5.00, DATE '2024-06-01', DATE '2024-08-31', 213,  FALSE UNION ALL
SELECT 8, 'LOYALTY25', '25% off for customers with 5+ orders','percent',  25.00, DATE '2024-01-01', DATE '2024-12-31', 156,  TRUE;

-- employee_id FK → hr.employees (ids 1–20, account managers from Sales dept).
-- Spread orders across customers 1–20 to support demo_q1 (top customers by spend).
INSERT INTO dbxcarta_test_sales.orders
SELECT  1,  6,  8, 'delivered', 'USD',  1199.99,    0.00,  96.00,  1295.99, TIMESTAMP '2024-09-05 09:10:00', TIMESTAMP '2024-09-05 09:45:00', TIMESTAMP '2024-09-07 14:00:00', DATE '2024-09-12' UNION ALL
SELECT  2, 18,  9, 'delivered', 'USD',  2849.98,   50.00, 224.00,  3023.98, TIMESTAMP '2024-09-10 11:30:00', TIMESTAMP '2024-09-10 12:00:00', TIMESTAMP '2024-09-12 10:00:00', DATE '2024-09-17' UNION ALL
SELECT  3,  2, 10, 'delivered', 'USD',   999.99,  100.00,  72.00,   971.99, TIMESTAMP '2024-09-15 14:20:00', TIMESTAMP '2024-09-15 15:00:00', TIMESTAMP '2024-09-17 09:00:00', DATE '2024-09-22' UNION ALL
SELECT  4, 13,  8, 'delivered', 'USD',  3499.97,    0.00, 280.00,  3779.97, TIMESTAMP '2024-09-20 16:00:00', TIMESTAMP '2024-09-20 16:30:00', TIMESTAMP '2024-09-22 11:00:00', DATE '2024-09-27' UNION ALL
SELECT  5,  1,  9, 'shipped',   'USD',   849.99,    0.00,  68.00,   917.99, TIMESTAMP '2024-10-01 08:45:00', TIMESTAMP '2024-10-01 09:15:00', TIMESTAMP '2024-10-03 13:00:00', DATE '2024-10-08' UNION ALL
SELECT  6,  8, 10, 'delivered', 'USD',  1349.99,    0.00, 108.00,  1457.99, TIMESTAMP '2024-10-05 10:00:00', TIMESTAMP '2024-10-05 10:45:00', TIMESTAMP '2024-10-07 08:00:00', DATE '2024-10-12' UNION ALL
SELECT  7,  4,  8, 'delivered', 'USD',   229.99,   11.50,  17.47,   235.96, TIMESTAMP '2024-10-08 13:30:00', TIMESTAMP '2024-10-08 14:00:00', TIMESTAMP '2024-10-10 10:00:00', DATE '2024-10-15' UNION ALL
SELECT  8, 17,  9, 'cancelled', 'USD',  1999.99,    0.00,   0.00,     0.00, TIMESTAMP '2024-10-10 15:00:00', NULL,                            NULL,                            NULL              UNION ALL
SELECT  9,  6, 10, 'delivered', 'USD',  2399.98,    0.00, 192.00,  2591.98, TIMESTAMP '2024-10-14 09:00:00', TIMESTAMP '2024-10-14 09:30:00', TIMESTAMP '2024-10-16 12:00:00', DATE '2024-10-21' UNION ALL
SELECT 10, 13,  8, 'delivered', 'USD',   599.99,    0.00,  48.00,   647.99, TIMESTAMP '2024-10-18 11:00:00', TIMESTAMP '2024-10-18 11:30:00', TIMESTAMP '2024-10-20 14:00:00', DATE '2024-10-25' UNION ALL
SELECT 11,  2,  9, 'delivered', 'USD',  3349.97,  250.00, 248.00,  3347.97, TIMESTAMP '2024-10-22 14:00:00', TIMESTAMP '2024-10-22 14:30:00', TIMESTAMP '2024-10-24 09:00:00', DATE '2024-10-29' UNION ALL
SELECT 12,  3, 10, 'shipped',   'USD',  1149.99,    0.00,  92.00,  1241.99, TIMESTAMP '2024-10-28 16:30:00', TIMESTAMP '2024-10-28 17:00:00', TIMESTAMP '2024-10-30 11:00:00', DATE '2024-11-04' UNION ALL
SELECT 13, 10,  8, 'confirmed', 'USD',   449.99,   22.50,  34.20,   461.69, TIMESTAMP '2024-11-01 08:00:00', TIMESTAMP '2024-11-01 08:30:00', NULL,                            DATE '2024-11-08' UNION ALL
SELECT 14, 18,  9, 'delivered', 'USD',  4599.96,    0.00, 368.00,  4967.96, TIMESTAMP '2024-11-04 10:30:00', TIMESTAMP '2024-11-04 11:00:00', TIMESTAMP '2024-11-06 13:00:00', DATE '2024-11-11' UNION ALL
SELECT 15, 14, 10, 'delivered', 'USD',   799.99,    0.00,  64.00,   863.99, TIMESTAMP '2024-11-07 12:00:00', TIMESTAMP '2024-11-07 12:30:00', TIMESTAMP '2024-11-09 10:00:00', DATE '2024-11-14' UNION ALL
SELECT 16,  1,  8, 'pending',   'USD',  1099.99,    0.00,  88.00,  1187.99, TIMESTAMP '2024-11-10 14:00:00', NULL,                            NULL,                            DATE '2024-11-17' UNION ALL
SELECT 17,  7,  9, 'confirmed', 'USD',   349.99,    0.00,  28.00,   377.99, TIMESTAMP '2024-11-12 09:15:00', TIMESTAMP '2024-11-12 09:45:00', NULL,                            DATE '2024-11-19' UNION ALL
SELECT 18,  6, 10, 'delivered', 'USD',  1199.99,   60.00,  91.20,  1231.19, TIMESTAMP '2024-11-14 11:00:00', TIMESTAMP '2024-11-14 11:30:00', TIMESTAMP '2024-11-16 09:00:00', DATE '2024-11-21' UNION ALL
SELECT 19, 16,  8, 'shipped',   'USD',   179.99,    9.00,  13.68,   184.67, TIMESTAMP '2024-11-16 15:30:00', TIMESTAMP '2024-11-16 16:00:00', TIMESTAMP '2024-11-18 12:00:00', DATE '2024-11-23' UNION ALL
SELECT 20,  2,  9, 'confirmed', 'USD',  5099.95,    0.00, 408.00,  5507.95, TIMESTAMP '2024-11-18 10:00:00', TIMESTAMP '2024-11-18 10:30:00', NULL,                            DATE '2024-11-25';

-- product_id FK → inventory.products (ids 1–20) — supports demo_q2 (revenue by category).
INSERT INTO dbxcarta_test_sales.order_items
SELECT  1,  1, 17, 1, 1199.99, 1199.99,  0.00 UNION ALL
SELECT  2,  2,  3, 1, 1999.99, 1999.99,  0.00 UNION ALL
SELECT  3,  2,  5, 1,  349.99,  349.99,  0.00 UNION ALL
SELECT  4,  2, 15, 2,   99.99,  199.98, 25.00 UNION ALL  -- discounted pair
SELECT  5,  3,  1, 1,  999.99,  999.99,  0.00 UNION ALL
SELECT  6,  4,  3, 1, 1999.99, 1999.99,  0.00 UNION ALL
SELECT  7,  4,  4, 1, 1499.99, 1499.99,  0.00 UNION ALL
SELECT  8,  5,  2, 1,  849.99,  849.99,  0.00 UNION ALL
SELECT  9,  6,  3, 1, 1349.99, 1349.99,  0.00 UNION ALL
SELECT 10,  7,  7, 1,  229.99,  229.99,  5.00 UNION ALL
SELECT 11,  9,  6, 1, 1099.99, 1099.99,  0.00 UNION ALL
SELECT 12,  9, 12, 1,  449.99,  449.99,  0.00 UNION ALL
SELECT 13,  9, 15, 2,   99.99,  199.98, 25.00 UNION ALL  -- discounted pair
SELECT 14, 10, 13, 1,  149.99,  149.99,  0.00 UNION ALL
SELECT 15, 11,  1, 1,  999.99,  999.99,  0.00 UNION ALL
SELECT 16, 11,  6, 1, 1099.99, 1099.99,  0.00 UNION ALL
SELECT 17, 11, 13, 1,  149.99,  149.99,  0.00 UNION ALL
SELECT 18, 12,  4, 1, 1149.99, 1149.99,  0.00 UNION ALL
SELECT 19, 13, 12, 1,  449.99,  449.99,  5.00 UNION ALL
SELECT 20, 14,  1, 1,  999.99,  999.99,  0.00 UNION ALL
SELECT 21, 14,  3, 1, 1999.99, 1999.99,  0.00 UNION ALL
SELECT 22, 14, 19, 1, 1349.99, 1349.99,  0.00 UNION ALL
SELECT 23, 15, 15, 1,   99.99,   99.99,  0.00 UNION ALL
SELECT 24, 18,  2, 1, 1199.99, 1199.99,  5.00 UNION ALL
SELECT 25, 20,  3, 1, 1999.99, 1999.99,  0.00 UNION ALL
SELECT 26, 20,  1, 1,  999.99,  999.99,  0.00 UNION ALL
SELECT 27, 20,  6, 1, 1099.99, 1099.99,  0.00 UNION ALL
SELECT 28, 20, 19, 1, 1349.99, 1349.99,  0.00 UNION ALL
SELECT 29, 20,  4, 1,  749.99,  749.99,  0.00;

INSERT INTO dbxcarta_test_sales.payments
SELECT  1,  1, 'card',          'settled',    1295.99, 'USD', 'GW-TXN-00001', TIMESTAMP '2024-09-05 09:20:00' UNION ALL
SELECT  2,  2, 'card',          'settled',    3023.98, 'USD', 'GW-TXN-00002', TIMESTAMP '2024-09-10 11:45:00' UNION ALL
SELECT  3,  3, 'bank_transfer', 'settled',     971.99, 'USD', 'GW-TXN-00003', TIMESTAMP '2024-09-15 15:10:00' UNION ALL
SELECT  4,  4, 'card',          'settled',    3779.97, 'USD', 'GW-TXN-00004', TIMESTAMP '2024-09-20 16:15:00' UNION ALL
SELECT  5,  5, 'card',          'authorized',  917.99, 'USD', 'GW-TXN-00005', TIMESTAMP '2024-10-01 09:00:00' UNION ALL
SELECT  6,  6, 'card',          'settled',    1457.99, 'USD', 'GW-TXN-00006', TIMESTAMP '2024-10-05 10:15:00' UNION ALL
SELECT  7,  7, 'store_credit',  'settled',     235.96, 'USD', 'GW-TXN-00007', TIMESTAMP '2024-10-08 14:10:00' UNION ALL
SELECT  8,  8, 'card',          'refunded',      0.00, 'USD', 'GW-TXN-00008', TIMESTAMP '2024-10-10 16:00:00' UNION ALL
SELECT  9,  9, 'card',          'settled',    2591.98, 'USD', 'GW-TXN-00009', TIMESTAMP '2024-10-14 09:15:00' UNION ALL
SELECT 10, 10, 'bank_transfer', 'settled',     647.99, 'USD', 'GW-TXN-00010', TIMESTAMP '2024-10-18 11:45:00' UNION ALL
SELECT 11, 11, 'card',          'settled',    3347.97, 'USD', 'GW-TXN-00011', TIMESTAMP '2024-10-22 14:15:00' UNION ALL
SELECT 12, 12, 'card',          'authorized', 1241.99, 'USD', 'GW-TXN-00012', TIMESTAMP '2024-10-28 17:15:00' UNION ALL
SELECT 13, 13, 'store_credit',  'pending',     461.69, 'USD', 'GW-TXN-00013', TIMESTAMP '2024-11-01 08:15:00' UNION ALL
SELECT 14, 14, 'card',          'settled',    4967.96, 'USD', 'GW-TXN-00014', TIMESTAMP '2024-11-04 11:15:00' UNION ALL
SELECT 15, 15, 'card',          'settled',     863.99, 'USD', 'GW-TXN-00015', TIMESTAMP '2024-11-07 12:45:00' UNION ALL
SELECT 16, 16, 'card',          'pending',    1187.99, 'USD', 'GW-TXN-00016', TIMESTAMP '2024-11-10 14:30:00' UNION ALL
SELECT 17, 17, 'bank_transfer', 'authorized',  377.99, 'USD', 'GW-TXN-00017', TIMESTAMP '2024-11-12 10:00:00' UNION ALL
SELECT 18, 18, 'card',          'settled',    1231.19, 'USD', 'GW-TXN-00018', TIMESTAMP '2024-11-14 11:45:00' UNION ALL
SELECT 19, 19, 'card',          'authorized',  184.67, 'USD', 'GW-TXN-00019', TIMESTAMP '2024-11-16 16:30:00' UNION ALL
SELECT 20, 20, 'crypto',        'pending',    5507.95, 'USD', 'GW-TXN-00020', TIMESTAMP '2024-11-18 10:45:00';

-- =============================================================================
-- SCHEMA: dbxcarta_test_external
-- External Delta tables at UC Volume paths.
-- Requires the Volume path from setup_test_catalog.sql to be writable.
-- Skip these three INSERT statements if no Volume is available.
-- =============================================================================

INSERT INTO dbxcarta_test_external.raw_orders
SELECT  1, 'ERP-WEST',  '{"order_id":1,"items":3,"total":1295.99}',  TIMESTAMP '2024-09-05 09:00:00', 'orders_20240905.jsonl' UNION ALL
SELECT  2, 'ERP-EAST',  '{"order_id":2,"items":3,"total":3023.98}',  TIMESTAMP '2024-09-10 11:00:00', 'orders_20240910.jsonl' UNION ALL
SELECT  3, 'ERP-WEST',  '{"order_id":3,"items":1,"total":971.99}',   TIMESTAMP '2024-09-15 14:00:00', 'orders_20240915.jsonl' UNION ALL
SELECT  4, 'ERP-EU',    '{"order_id":4,"items":2,"total":3779.97}',  TIMESTAMP '2024-09-20 16:00:00', 'orders_20240920.jsonl' UNION ALL
SELECT  5, 'ERP-WEST',  '{"order_id":5,"items":1,"total":917.99}',   TIMESTAMP '2024-10-01 08:00:00', 'orders_20241001.jsonl' UNION ALL
SELECT  6, 'ERP-EAST',  '{"order_id":6,"items":1,"total":1457.99}',  TIMESTAMP '2024-10-05 10:00:00', 'orders_20241005.jsonl' UNION ALL
SELECT  7, 'ERP-WEST',  '{"order_id":7,"items":1,"total":235.96}',   TIMESTAMP '2024-10-08 13:00:00', 'orders_20241008.jsonl' UNION ALL
SELECT  8, 'ERP-APAC',  '{"order_id":8,"items":1,"total":0.0}',      TIMESTAMP '2024-10-10 15:00:00', 'orders_20241010.jsonl' UNION ALL
SELECT  9, 'ERP-EAST',  '{"order_id":9,"items":2,"total":2591.98}',  TIMESTAMP '2024-10-14 09:00:00', 'orders_20241014.jsonl' UNION ALL
SELECT 10, 'ERP-EU',    '{"order_id":10,"items":1,"total":647.99}',  TIMESTAMP '2024-10-18 11:00:00', 'orders_20241018.jsonl' UNION ALL
SELECT 11, 'ERP-WEST',  '{"order_id":11,"items":2,"total":3347.97}', TIMESTAMP '2024-10-22 14:00:00', 'orders_20241022.jsonl' UNION ALL
SELECT 12, 'ERP-APAC',  '{"order_id":12,"items":1,"total":1241.99}', TIMESTAMP '2024-10-28 16:00:00', 'orders_20241028.jsonl' UNION ALL
SELECT 13, 'ERP-EAST',  '{"order_id":13,"items":1,"total":461.69}',  TIMESTAMP '2024-11-01 08:00:00', 'orders_20241101.jsonl' UNION ALL
SELECT 14, 'ERP-WEST',  '{"order_id":14,"items":2,"total":4967.96}', TIMESTAMP '2024-11-04 10:00:00', 'orders_20241104.jsonl' UNION ALL
SELECT 15, 'ERP-EU',    '{"order_id":15,"items":1,"total":863.99}',  TIMESTAMP '2024-11-07 12:00:00', 'orders_20241107.jsonl';

INSERT INTO dbxcarta_test_external.vendor_price_list
SELECT 1, 'SKU-0001',  949.00, 'USD', DATE '2024-01-01', DATE '2024-06-30' UNION ALL
SELECT 1, 'SKU-0002',  799.00, 'USD', DATE '2024-01-01', DATE '2024-06-30' UNION ALL
SELECT 1, 'SKU-0005',  329.00, 'USD', DATE '2024-01-01', DATE '2024-06-30' UNION ALL
SELECT 2, 'SKU-0007',  209.00, 'USD', DATE '2024-01-01', DATE '2024-06-30' UNION ALL
SELECT 2, 'SKU-0008',  159.00, 'USD', DATE '2024-01-01', DATE '2024-06-30' UNION ALL
SELECT 2, 'SKU-0014',  279.00, 'USD', DATE '2024-01-01', DATE '2024-06-30' UNION ALL
SELECT 3, 'SKU-0009',   35.00, 'USD', DATE '2024-01-01', DATE '2024-06-30' UNION ALL
SELECT 3, 'SKU-0010',   49.00, 'USD', DATE '2024-01-01', DATE '2024-06-30' UNION ALL
SELECT 3, 'SKU-0016',   44.00, 'USD', DATE '2024-01-01', DATE '2024-06-30' UNION ALL
SELECT 4, 'SKU-0003', 1899.00, 'USD', DATE '2024-01-01', DATE '2024-06-30' UNION ALL
SELECT 4, 'SKU-0004', 1399.00, 'USD', DATE '2024-01-01', DATE '2024-06-30' UNION ALL
SELECT 4, 'SKU-0019', 1299.00, 'USD', DATE '2024-01-01', DATE '2024-06-30' UNION ALL
SELECT 5, 'SKU-0013',  139.00, 'USD', DATE '2024-01-01', DATE '2024-06-30' UNION ALL
SELECT 5, 'SKU-0015',   89.00, 'USD', DATE '2024-01-01', DATE '2024-06-30' UNION ALL
SELECT 1, 'SKU-0001',  929.00, 'USD', DATE '2024-07-01', DATE '2024-12-31';

-- flag_image is BINARY — NULL is sufficient for tests.
INSERT INTO dbxcarta_test_external.geo_reference
SELECT  1, 'US', 'United States',  'Americas',    335000000, 9372610.0,  27360000000000.0, FALSE, DATE '1776-07-04', TIMESTAMP '2020-01-15 00:00:00', NULL, 0.3960 UNION ALL
SELECT  2, 'DE', 'Germany',        'Europe',       84000000,  357114.0,   4420000000000.0, TRUE,  DATE '1990-10-03', TIMESTAMP '2022-05-01 00:00:00', NULL, 0.3180 UNION ALL
SELECT  3, 'FR', 'France',         'Europe',       68000000,  551695.0,   3010000000000.0, TRUE,  DATE '1958-10-04', TIMESTAMP '2021-03-01 00:00:00', NULL, 0.3270 UNION ALL
SELECT  4, 'GB', 'United Kingdom', 'Europe',       68000000,  242495.0,   3070000000000.0, FALSE, DATE '1707-05-01', TIMESTAMP '2021-03-21 00:00:00', NULL, 0.3500 UNION ALL
SELECT  5, 'JP', 'Japan',          'Asia-Pacific', 124000000,  377975.0,   4230000000000.0, FALSE, DATE '0660-02-11', TIMESTAMP '2020-10-01 00:00:00', NULL, 0.3210 UNION ALL
SELECT  6, 'CN', 'China',          'Asia-Pacific',1412000000, 9596960.0,  18330000000000.0, FALSE, DATE '1949-10-01', TIMESTAMP '2020-11-01 00:00:00', NULL, 0.3820 UNION ALL
SELECT  7, 'IN', 'India',          'Asia-Pacific',1429000000, 3287263.0,   3730000000000.0, FALSE, DATE '1947-08-15', TIMESTAMP '2011-03-01 00:00:00', NULL, 0.3570 UNION ALL
SELECT  8, 'BR', 'Brazil',         'Americas',    215000000, 8515767.0,   2080000000000.0, FALSE, DATE '1822-09-07', TIMESTAMP '2022-08-01 00:00:00', NULL, 0.5220 UNION ALL
SELECT  9, 'CA', 'Canada',         'Americas',     40000000, 9984670.0,   2140000000000.0, FALSE, DATE '1867-07-01', TIMESTAMP '2021-05-11 00:00:00', NULL, 0.3320 UNION ALL
SELECT 10, 'AU', 'Australia',      'Asia-Pacific',  26000000, 7692024.0,   1710000000000.0, FALSE, DATE '1901-01-01', TIMESTAMP '2021-08-10 00:00:00', NULL, 0.3430 UNION ALL
SELECT 11, 'KR', 'South Korea',    'Asia-Pacific',  52000000,  100210.0,   1670000000000.0, FALSE, DATE '1948-08-15', TIMESTAMP '2020-11-01 00:00:00', NULL, 0.3140 UNION ALL
SELECT 12, 'NL', 'Netherlands',    'Europe',        17000000,   41543.0,   1010000000000.0, TRUE,  DATE '1581-07-26', TIMESTAMP '2021-01-01 00:00:00', NULL, 0.2850 UNION ALL
SELECT 13, 'SG', 'Singapore',      'Asia-Pacific',   6000000,     728.0,    500000000000.0, FALSE, DATE '1965-08-09', TIMESTAMP '2020-06-16 00:00:00', NULL, 0.3740 UNION ALL
SELECT 14, 'SE', 'Sweden',         'Europe',        10000000,  450295.0,    560000000000.0, FALSE, DATE '0992-01-01', TIMESTAMP '2020-11-01 00:00:00', NULL, 0.2870 UNION ALL
SELECT 15, 'BD', 'Bangladesh',     'Asia-Pacific', 170000000,  147570.0,    460000000000.0, FALSE, DATE '1971-03-26', TIMESTAMP '2022-01-01 00:00:00', NULL, 0.3210;

-- =============================================================================
-- TEARDOWN
-- Uncomment to remove all fixture rows before re-running setup + insert.
-- Reverse FK order: children before parents.
-- =============================================================================

-- TRUNCATE TABLE ${catalog}.dbxcarta_test_sales.payments;
-- TRUNCATE TABLE ${catalog}.dbxcarta_test_sales.order_items;
-- TRUNCATE TABLE ${catalog}.dbxcarta_test_sales.orders;
-- TRUNCATE TABLE ${catalog}.dbxcarta_test_sales.promotions;
-- TRUNCATE TABLE ${catalog}.dbxcarta_test_sales.customers;
-- TRUNCATE TABLE ${catalog}.dbxcarta_test_events.ab_experiments;
-- TRUNCATE TABLE ${catalog}.dbxcarta_test_events.page_views;
-- TRUNCATE TABLE ${catalog}.dbxcarta_test_events.user_sessions;
-- TRUNCATE TABLE ${catalog}.dbxcarta_test_events.user_profiles;
-- TRUNCATE TABLE ${catalog}.dbxcarta_test_inventory.product_suppliers;
-- TRUNCATE TABLE ${catalog}.dbxcarta_test_inventory.inventory_levels;
-- TRUNCATE TABLE ${catalog}.dbxcarta_test_inventory.products;
-- TRUNCATE TABLE ${catalog}.dbxcarta_test_inventory.suppliers;
-- TRUNCATE TABLE ${catalog}.dbxcarta_test_inventory.warehouses;
-- TRUNCATE TABLE ${catalog}.dbxcarta_test_inventory.categories;
-- TRUNCATE TABLE ${catalog}.dbxcarta_test_hr.leave_requests;
-- TRUNCATE TABLE ${catalog}.dbxcarta_test_hr.employees;
-- TRUNCATE TABLE ${catalog}.dbxcarta_test_hr.job_titles;
-- TRUNCATE TABLE ${catalog}.dbxcarta_test_hr.departments;
-- TRUNCATE TABLE ${catalog}.dbxcarta_test_external.raw_orders;
-- TRUNCATE TABLE ${catalog}.dbxcarta_test_external.vendor_price_list;
-- TRUNCATE TABLE ${catalog}.dbxcarta_test_external.geo_reference;
