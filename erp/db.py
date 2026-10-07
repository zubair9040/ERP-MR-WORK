"""Database access. SQLite, one file. All money is stored as whole paisa (integers)."""
import os
import sqlite3
from datetime import date, datetime
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP

from flask import current_app, g

SCHEMA = """
CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT);

CREATE TABLE IF NOT EXISTS companies (
  id INTEGER PRIMARY KEY, code TEXT NOT NULL, name TEXT NOT NULL, gst_registered INTEGER DEFAULT 0, ntn TEXT DEFAULT '',
  gst_no TEXT DEFAULT '', default_tax_rate REAL DEFAULT 0, address TEXT DEFAULT '', phone TEXT DEFAULT '', email TEXT DEFAULT '',
  website TEXT DEFAULT '', next_invoice_number INTEGER DEFAULT 1, invoice_note TEXT DEFAULT '', color TEXT DEFAULT '#6366f1',
  active INTEGER DEFAULT 1, sort INTEGER DEFAULT 0);

CREATE TABLE IF NOT EXISTS reps (
  id INTEGER PRIMARY KEY, code TEXT NOT NULL, name TEXT NOT NULL, phone TEXT DEFAULT '',
  active INTEGER DEFAULT 1);

CREATE TABLE IF NOT EXISTS users (
  id INTEGER PRIMARY KEY, username TEXT UNIQUE NOT NULL COLLATE NOCASE, name TEXT NOT NULL,
  password_hash TEXT NOT NULL, role TEXT NOT NULL CHECK (role IN ('admin','accounts','rep','store')),
  rep_id INTEGER REFERENCES reps(id), active INTEGER DEFAULT 1, created_at TEXT);

CREATE TABLE IF NOT EXISTS customer_branches (
  id INTEGER PRIMARY KEY, customer_id INTEGER NOT NULL REFERENCES customers(id), name TEXT NOT NULL, code TEXT DEFAULT '',
  address TEXT DEFAULT '', contact TEXT DEFAULT '', phone TEXT DEFAULT '', email TEXT DEFAULT '', active INTEGER DEFAULT 1,
  created_at TEXT);
CREATE INDEX IF NOT EXISTS ix_branch_cust ON customer_branches(customer_id);

CREATE TABLE IF NOT EXISTS po_batches (
  id INTEGER PRIMARY KEY, company_id INTEGER, customer_id INTEGER NOT NULL REFERENCES customers(id), po_no TEXT NOT NULL,
  date TEXT NOT NULL, notes TEXT DEFAULT '', combined_no INTEGER, combined_date TEXT, void INTEGER DEFAULT 0,
  created_by INTEGER, created_at TEXT);
CREATE INDEX IF NOT EXISTS ix_po_cust ON po_batches(customer_id);

CREATE TABLE IF NOT EXISTS void_requests (
  id INTEGER PRIMARY KEY, kind TEXT NOT NULL, ref_id INTEGER NOT NULL, reason TEXT DEFAULT '', requested_by INTEGER,
  requested_name TEXT, requested_at TEXT, status TEXT DEFAULT 'pending', decided_by TEXT, decided_at TEXT, decision_note TEXT DEFAULT '');

CREATE TABLE IF NOT EXISTS roles (
  id INTEGER PRIMARY KEY, name TEXT UNIQUE NOT NULL COLLATE NOCASE, description TEXT DEFAULT '',
  perms TEXT NOT NULL DEFAULT '[]', builtin INTEGER DEFAULT 0, sort INTEGER DEFAULT 100);

CREATE TABLE IF NOT EXISTS customers (
  id INTEGER PRIMARY KEY, name TEXT NOT NULL, contact TEXT DEFAULT '', whatsapp TEXT DEFAULT '',
  phone TEXT DEFAULT '', email TEXT DEFAULT '', address TEXT DEFAULT '', rep_id INTEGER REFERENCES reps(id),
  terms_days INTEGER DEFAULT 30, credit_limit INTEGER DEFAULT 0, opening_balance INTEGER DEFAULT 0,
  opening_date TEXT, notes TEXT DEFAULT '', active INTEGER DEFAULT 1, created_at TEXT);

CREATE TABLE IF NOT EXISTS items (
  id INTEGER PRIMARY KEY, code TEXT DEFAULT '', name TEXT NOT NULL, description TEXT DEFAULT '',
  unit TEXT DEFAULT '', price INTEGER DEFAULT 0, active INTEGER DEFAULT 1);

CREATE TABLE IF NOT EXISTS invoices (
  id INTEGER PRIMARY KEY, number INTEGER NOT NULL, date TEXT NOT NULL, due_date TEXT,
  customer_id INTEGER NOT NULL REFERENCES customers(id), rep_id INTEGER REFERENCES reps(id),
  notes TEXT DEFAULT '', tax_rate REAL DEFAULT 0, subtotal INTEGER DEFAULT 0, discount INTEGER DEFAULT 0,
  tax INTEGER DEFAULT 0, total INTEGER DEFAULT 0, void INTEGER DEFAULT 0,
  created_by INTEGER, created_at TEXT, updated_at TEXT);

CREATE TABLE IF NOT EXISTS invoice_lines (
  id INTEGER PRIMARY KEY, invoice_id INTEGER NOT NULL REFERENCES invoices(id) ON DELETE CASCADE,
  item_id INTEGER REFERENCES items(id), description TEXT DEFAULT '', qty REAL DEFAULT 0,
  rate INTEGER DEFAULT 0, amount INTEGER DEFAULT 0, sort INTEGER DEFAULT 0);

CREATE TABLE IF NOT EXISTS payments (
  id INTEGER PRIMARY KEY, number INTEGER UNIQUE NOT NULL, date TEXT NOT NULL,
  customer_id INTEGER NOT NULL REFERENCES customers(id), amount INTEGER NOT NULL,
  method TEXT DEFAULT 'Cash', reference TEXT DEFAULT '', notes TEXT DEFAULT '', void INTEGER DEFAULT 0,
  created_by INTEGER, created_at TEXT);

CREATE TABLE IF NOT EXISTS payment_allocations (
  id INTEGER PRIMARY KEY, payment_id INTEGER NOT NULL REFERENCES payments(id) ON DELETE CASCADE,
  invoice_id INTEGER REFERENCES invoices(id), amount INTEGER NOT NULL);
CREATE INDEX IF NOT EXISTS ix_alloc_pay ON payment_allocations(payment_id);
CREATE INDEX IF NOT EXISTS ix_alloc_inv ON payment_allocations(invoice_id);

CREATE TABLE IF NOT EXISTS suppliers (
  id INTEGER PRIMARY KEY, name TEXT NOT NULL, contact TEXT DEFAULT '', phone TEXT DEFAULT '', whatsapp TEXT DEFAULT '',
  email TEXT DEFAULT '', address TEXT DEFAULT '', terms_days INTEGER DEFAULT 30, opening_balance INTEGER DEFAULT 0,
  opening_date TEXT, notes TEXT DEFAULT '', active INTEGER DEFAULT 1, created_at TEXT);

CREATE TABLE IF NOT EXISTS purchases (
  id INTEGER PRIMARY KEY, number INTEGER UNIQUE NOT NULL, bill_no TEXT DEFAULT '', date TEXT NOT NULL, due_date TEXT,
  supplier_id INTEGER NOT NULL REFERENCES suppliers(id), notes TEXT DEFAULT '', subtotal INTEGER DEFAULT 0,
  tax_rate REAL DEFAULT 0, tax INTEGER DEFAULT 0, total INTEGER DEFAULT 0, void INTEGER DEFAULT 0,
  created_by INTEGER, created_at TEXT, updated_at TEXT);

CREATE TABLE IF NOT EXISTS purchase_lines (
  id INTEGER PRIMARY KEY, purchase_id INTEGER NOT NULL REFERENCES purchases(id) ON DELETE CASCADE,
  item_id INTEGER REFERENCES items(id), code TEXT DEFAULT '', description TEXT DEFAULT '', unit TEXT DEFAULT '',
  qty REAL, rate INTEGER DEFAULT 0, amount INTEGER DEFAULT 0, sort INTEGER DEFAULT 0);

CREATE TABLE IF NOT EXISTS supplier_payments (
  id INTEGER PRIMARY KEY, number INTEGER UNIQUE NOT NULL, date TEXT NOT NULL,
  supplier_id INTEGER NOT NULL REFERENCES suppliers(id), amount INTEGER NOT NULL, method TEXT DEFAULT 'Cash',
  reference TEXT DEFAULT '', notes TEXT DEFAULT '', void INTEGER DEFAULT 0, created_by INTEGER, created_at TEXT);

CREATE TABLE IF NOT EXISTS credit_notes (
  id INTEGER PRIMARY KEY, number INTEGER UNIQUE NOT NULL, date TEXT NOT NULL,
  customer_id INTEGER NOT NULL REFERENCES customers(id), invoice_ref TEXT DEFAULT '', notes TEXT DEFAULT '',
  restock INTEGER DEFAULT 1, subtotal INTEGER DEFAULT 0, tax_rate REAL DEFAULT 0, tax INTEGER DEFAULT 0,
  total INTEGER DEFAULT 0, void INTEGER DEFAULT 0, created_by INTEGER, created_at TEXT, updated_at TEXT);

CREATE TABLE IF NOT EXISTS credit_note_lines (
  id INTEGER PRIMARY KEY, credit_note_id INTEGER NOT NULL REFERENCES credit_notes(id) ON DELETE CASCADE,
  item_id INTEGER REFERENCES items(id), code TEXT DEFAULT '', description TEXT DEFAULT '', unit TEXT DEFAULT '',
  qty REAL, rate INTEGER DEFAULT 0, amount INTEGER DEFAULT 0, sort INTEGER DEFAULT 0);

CREATE TABLE IF NOT EXISTS stock_adjustments (
  id INTEGER PRIMARY KEY, date TEXT NOT NULL, item_id INTEGER NOT NULL REFERENCES items(id), qty REAL NOT NULL,
  reason TEXT DEFAULT '', created_by INTEGER, created_at TEXT);

CREATE TABLE IF NOT EXISTS expenses (
  id INTEGER PRIMARY KEY, date TEXT NOT NULL, category TEXT NOT NULL, payee TEXT DEFAULT '', amount INTEGER NOT NULL,
  method TEXT DEFAULT 'Cash', reference TEXT DEFAULT '', notes TEXT DEFAULT '', void INTEGER DEFAULT 0,
  created_by INTEGER, created_at TEXT);

CREATE INDEX IF NOT EXISTS ix_pur_sup ON purchases(supplier_id, date);
CREATE INDEX IF NOT EXISTS ix_pl_pur ON purchase_lines(purchase_id);
CREATE INDEX IF NOT EXISTS ix_pl_item ON purchase_lines(item_id);
CREATE INDEX IF NOT EXISTS ix_spay_sup ON supplier_payments(supplier_id, date);
CREATE INDEX IF NOT EXISTS ix_cn_cust ON credit_notes(customer_id, date);
CREATE INDEX IF NOT EXISTS ix_cnl ON credit_note_lines(credit_note_id);
CREATE INDEX IF NOT EXISTS ix_il_item ON invoice_lines(item_id);

CREATE TABLE IF NOT EXISTS warehouses (
  id INTEGER PRIMARY KEY, code TEXT NOT NULL, name TEXT NOT NULL, address TEXT DEFAULT '', is_default INTEGER DEFAULT 0,
  active INTEGER DEFAULT 1);

CREATE TABLE IF NOT EXISTS wh_docs (
  id INTEGER PRIMARY KEY, type TEXT NOT NULL CHECK (type IN ('OPN','GRN','DC','TRF','ADJ','CNT')), number INTEGER NOT NULL,
  date TEXT NOT NULL, warehouse_id INTEGER NOT NULL REFERENCES warehouses(id), to_warehouse_id INTEGER REFERENCES warehouses(id),
  party TEXT DEFAULT '', ref TEXT DEFAULT '', invoice_id INTEGER REFERENCES invoices(id), purchase_id INTEGER REFERENCES purchases(id),
  vehicle TEXT DEFAULT '', notes TEXT DEFAULT '', void INTEGER DEFAULT 0, created_by INTEGER, created_at TEXT, updated_at TEXT,
  UNIQUE (type, number));

CREATE TABLE IF NOT EXISTS wh_lines (
  id INTEGER PRIMARY KEY, doc_id INTEGER NOT NULL REFERENCES wh_docs(id) ON DELETE CASCADE,
  item_id INTEGER NOT NULL REFERENCES items(id), qty REAL NOT NULL, counted REAL, system_qty REAL,
  unit_cost INTEGER DEFAULT 0, note TEXT DEFAULT '', sort INTEGER DEFAULT 0);

CREATE INDEX IF NOT EXISTS ix_whd ON wh_docs(type, date);
CREATE INDEX IF NOT EXISTS ix_whd_inv ON wh_docs(invoice_id);
CREATE INDEX IF NOT EXISTS ix_whl_doc ON wh_lines(doc_id);
CREATE INDEX IF NOT EXISTS ix_whl_item ON wh_lines(item_id);

CREATE TABLE IF NOT EXISTS employees (
  id INTEGER PRIMARY KEY, code TEXT DEFAULT '', name TEXT NOT NULL, father_name TEXT DEFAULT '', cnic TEXT DEFAULT '',
  phone TEXT DEFAULT '', whatsapp TEXT DEFAULT '', designation TEXT DEFAULT '', department TEXT DEFAULT '',
  join_date TEXT, leave_date TEXT, basic INTEGER DEFAULT 0, allowance INTEGER DEFAULT 0, pay_method TEXT DEFAULT 'Cash',
  bank_name TEXT DEFAULT '', bank_account TEXT DEFAULT '', notes TEXT DEFAULT '', active INTEGER DEFAULT 1, created_at TEXT);

CREATE TABLE IF NOT EXISTS emp_advances (
  id INTEGER PRIMARY KEY, employee_id INTEGER NOT NULL REFERENCES employees(id), date TEXT NOT NULL, kind TEXT DEFAULT 'Advance',
  amount INTEGER NOT NULL, installment INTEGER DEFAULT 0, method TEXT DEFAULT 'Cash', notes TEXT DEFAULT '', void INTEGER DEFAULT 0,
  created_by INTEGER, created_at TEXT);

CREATE TABLE IF NOT EXISTS payroll_runs (
  id INTEGER PRIMARY KEY, month TEXT UNIQUE NOT NULL, days INTEGER NOT NULL, status TEXT DEFAULT 'draft',
  notes TEXT DEFAULT '', created_by INTEGER, created_at TEXT, finalized_at TEXT);

CREATE TABLE IF NOT EXISTS payroll_lines (
  id INTEGER PRIMARY KEY, run_id INTEGER NOT NULL REFERENCES payroll_runs(id) ON DELETE CASCADE,
  employee_id INTEGER NOT NULL REFERENCES employees(id), basic INTEGER DEFAULT 0, allowance INTEGER DEFAULT 0,
  absent_days REAL DEFAULT 0, absent_ded INTEGER DEFAULT 0, ot_hours REAL DEFAULT 0, ot_amount INTEGER DEFAULT 0,
  bonus INTEGER DEFAULT 0, other_ded INTEGER DEFAULT 0, advance_ded INTEGER DEFAULT 0, gross INTEGER DEFAULT 0,
  net INTEGER DEFAULT 0, paid INTEGER DEFAULT 0, paid_date TEXT, paid_method TEXT DEFAULT '', note TEXT DEFAULT '',
  UNIQUE (run_id, employee_id));

CREATE INDEX IF NOT EXISTS ix_adv_emp ON emp_advances(employee_id);
CREATE INDEX IF NOT EXISTS ix_pl_run ON payroll_lines(run_id);
CREATE INDEX IF NOT EXISTS ix_pl_emp ON payroll_lines(employee_id);

CREATE TABLE IF NOT EXISTS print_layouts (
  id INTEGER PRIMARY KEY, company_id INTEGER, doc TEXT NOT NULL, name TEXT DEFAULT '', layout TEXT NOT NULL,
  active INTEGER DEFAULT 1, updated_at TEXT, updated_by TEXT);

CREATE TABLE IF NOT EXISTS messages (
  id INTEGER PRIMARY KEY, created_at TEXT, kind TEXT, customer_id INTEGER, ref_id INTEGER,
  period TEXT DEFAULT '', phone TEXT, status TEXT, detail TEXT, user TEXT);

CREATE TABLE IF NOT EXISTS audit_log (
  id INTEGER PRIMARY KEY, at TEXT, user_id INTEGER, user_name TEXT, ip TEXT, method TEXT, endpoint TEXT, path TEXT,
  status INTEGER, detail TEXT DEFAULT '');

CREATE TABLE IF NOT EXISTS quotes (
  id INTEGER PRIMARY KEY, number INTEGER UNIQUE NOT NULL, date TEXT NOT NULL, valid_until TEXT DEFAULT '',
  company_id INTEGER, customer_id INTEGER, customer_name TEXT DEFAULT '', customer_phone TEXT DEFAULT '', customer_address TEXT DEFAULT '',
  subject TEXT DEFAULT '', notes TEXT DEFAULT '', terms TEXT DEFAULT '', status TEXT DEFAULT 'Draft',
  subtotal INTEGER DEFAULT 0, tax_rate REAL DEFAULT 0, tax INTEGER DEFAULT 0, total INTEGER DEFAULT 0,
  void INTEGER DEFAULT 0, created_by INTEGER, created_at TEXT, updated_at TEXT);

CREATE TABLE IF NOT EXISTS quote_lines (
  id INTEGER PRIMARY KEY, quote_id INTEGER NOT NULL REFERENCES quotes(id) ON DELETE CASCADE,
  item_id INTEGER, code TEXT DEFAULT '', description TEXT DEFAULT '', unit TEXT DEFAULT '',
  qty REAL, rate INTEGER DEFAULT 0, amount INTEGER DEFAULT 0, sort INTEGER DEFAULT 0);

CREATE TABLE IF NOT EXISTS orders (
  id INTEGER PRIMARY KEY, number INTEGER UNIQUE NOT NULL, date TEXT NOT NULL, customer_id INTEGER NOT NULL REFERENCES customers(id),
  rep_id INTEGER, notes TEXT DEFAULT '', status TEXT DEFAULT 'Pending', total INTEGER DEFAULT 0,
  lat REAL, lng REAL, created_by INTEGER, created_by_name TEXT DEFAULT '', created_at TEXT,
  decided_by TEXT DEFAULT '', decided_at TEXT, reject_reason TEXT DEFAULT '', invoice_id INTEGER, seen INTEGER DEFAULT 0);

CREATE TABLE IF NOT EXISTS order_lines (
  id INTEGER PRIMARY KEY, order_id INTEGER NOT NULL REFERENCES orders(id) ON DELETE CASCADE,
  item_id INTEGER, code TEXT DEFAULT '', description TEXT DEFAULT '', unit TEXT DEFAULT '',
  qty REAL, rate INTEGER DEFAULT 0, amount INTEGER DEFAULT 0, sort INTEGER DEFAULT 0);

CREATE TABLE IF NOT EXISTS activity (
  id INTEGER PRIMARY KEY, user_id INTEGER NOT NULL, day TEXT NOT NULL, first_at TEXT, last_at TEXT, last_ts REAL DEFAULT 0,
  active_sec INTEGER DEFAULT 0, UNIQUE (user_id, day));

CREATE TABLE IF NOT EXISTS chat_messages (
  id INTEGER PRIMARY KEY, room TEXT NOT NULL, sender_id INTEGER NOT NULL, sender_name TEXT, body TEXT NOT NULL, created_at TEXT);
CREATE INDEX IF NOT EXISTS ix_chat_room ON chat_messages(room, id);

CREATE TABLE IF NOT EXISTS chat_reads (
  user_id INTEGER NOT NULL, room TEXT NOT NULL, last_id INTEGER DEFAULT 0, PRIMARY KEY (user_id, room));

CREATE TABLE IF NOT EXISTS tasks (
  id INTEGER PRIMARY KEY, title TEXT NOT NULL, details TEXT DEFAULT '', assignee_id INTEGER NOT NULL, created_by INTEGER NOT NULL,
  created_by_name TEXT, due_date TEXT DEFAULT '', priority TEXT DEFAULT 'Normal', status TEXT DEFAULT 'To do',
  created_at TEXT, done_at TEXT);
CREATE INDEX IF NOT EXISTS ix_tasks_assignee ON tasks(assignee_id, status);

CREATE TABLE IF NOT EXISTS task_comments (
  id INTEGER PRIMARY KEY, task_id INTEGER NOT NULL REFERENCES tasks(id) ON DELETE CASCADE, user_name TEXT, body TEXT, created_at TEXT);

CREATE INDEX IF NOT EXISTS ix_orders_status ON orders(status, date);
CREATE INDEX IF NOT EXISTS ix_inv_cust ON invoices(customer_id, date);
CREATE INDEX IF NOT EXISTS ix_pay_cust ON payments(customer_id, date);
CREATE INDEX IF NOT EXISTS ix_lines_inv ON invoice_lines(invoice_id);
CREATE INDEX IF NOT EXISTS ix_msg ON messages(kind, ref_id);
"""

DEFAULT_SETTINGS = {
    "company_name": "My Company",
    "company_address": "",
    "company_phone": "",
    "company_email": "",
    "company_tax_no": "",
    "currency": "Rs",
    "ui_theme": "nova",
    "country_code": "92",
    "next_invoice_number": "1001",
    "next_payment_number": "1",
    "next_purchase_number": "1",
    "next_credit_number": "1",
    "next_supplier_payment_number": "1",
    "allow_negative_stock": "0",
    "default_tax_rate": "0",
    "invoice_footer": "",
    "company_website": "",
    "invoice_note": "NOTE: GOODS ONCE SOLD CANNOT BE TAKEN BACK OR EXCHANGED",
    "invoice_terms": "",
    "wa_dry_run": "1",
    "wa_api_version": "v21.0",
    "wa_phone_number_id": "",
    "wa_access_token": "",
    "wa_language": "en",
    "wa_invoice_template": "invoice_notification",
    "wa_quotation_template": "quotation_notification",
    "wa_receipt_template": "payment_receipt",
    "wa_statement_template": "statement_notification",
    "wa_balance_template": "balance_reminder",
    "auto_send_invoice": "0",
    "auto_send_receipt": "0",
    "print_classic": "0",
    "smtp_host": "smtp.gmail.com",
    "smtp_port": "587",
    "smtp_user": "",
    "smtp_password": "",
    "email_from_name": "",
    "email_cc": "",
    "email_dry_run": "1",
    "email_signature": "Regards,\nAccounts Department",
    "couriers": "TCS | https://www.tcsexpress.com/track/{no}\nLCS (Leopards) | https://www.leopardscourier.com/tracking?cn={no}\nM&P | \nTrax | \nBy hand / own vehicle | ",
    "salary_days_basis": "30",
    "allowance_absent_limit": "10",
    "wa_supplier_template": "",
    "ot_hours_per_day": "8",
    "ot_rate_multiplier": "1",
    "salary_accounts_access": "0",
    "wa_payslip_template": "salary_slip",
}


def get_db():
    if "db" not in g:
        con = sqlite3.connect(current_app.config["DATABASE"], timeout=15)
        con.row_factory = sqlite3.Row
        con.execute("PRAGMA foreign_keys = ON")
        g.db = con
    return g.db


def close_db(_e=None):
    con = g.pop("db", None)
    if con is not None:
        con.close()


MIGRATIONS = {
    "invoices": [("deliver_to", "TEXT DEFAULT ''"), ("branch_id", "INTEGER"), ("batch_id", "INTEGER"), ("courier", "TEXT DEFAULT ''"), ("tracking_no", "TEXT DEFAULT ''"),
                 ("shipped_on", "TEXT DEFAULT ''"), ("po_no", "TEXT DEFAULT ''"), ("company_id", "INTEGER"), ("delivered_on", "TEXT DEFAULT ''"), ("delivered_by", "TEXT DEFAULT ''"), ("bilti_no", "TEXT DEFAULT ''"), ("via", "TEXT DEFAULT ''"), ("ref_no", "TEXT DEFAULT ''"),
                 ("ctn_count", "TEXT DEFAULT ''"), ("customer_message", "TEXT DEFAULT ''")],
    "invoice_lines": [("unit", "TEXT DEFAULT ''"), ("ctn_qty", "TEXT DEFAULT ''"), ("code", "TEXT DEFAULT ''"),
                      ("kind", "TEXT DEFAULT 'item'"), ("percent", "REAL")],
    "items": [("grp", "TEXT DEFAULT ''"), ("pcs_per_ctn", "REAL DEFAULT 0"), ("kind", "TEXT DEFAULT 'item'"), ("percent", "REAL DEFAULT 0"), ("reorder_level", "REAL DEFAULT 0"),
              ("opening_qty", "REAL DEFAULT 0"), ("opening_cost", "INTEGER DEFAULT 0"), ("track_stock", "INTEGER DEFAULT 1"),
              ("barcode", "TEXT DEFAULT ''"), ("location", "TEXT DEFAULT ''")],
    "payments": [("company_id", "INTEGER"), ("apply_mode", "TEXT DEFAULT 'auto'"), ("updated_at", "TEXT")],
    "payroll_lines": [("loan_ded", "INTEGER DEFAULT 0")],
    "wh_lines": [("ctn", "REAL"), ("ppc", "REAL"), ("loose", "REAL")],
    "credit_notes": [("company_id", "INTEGER")],
    "quotes": [("invoice_id", "INTEGER"), ("customer_email", "TEXT DEFAULT ''")],
    "purchases": [("company_id", "INTEGER")],
    "supplier_payments": [("company_id", "INTEGER")],
    "expenses": [("company_id", "INTEGER")],
    "messages": [("channel", "TEXT DEFAULT 'whatsapp'"), ("supplier_id", "INTEGER")],
    "users": [("role_id", "INTEGER")],
    "customers": [("code", "TEXT DEFAULT ''"), ("city", "TEXT DEFAULT ''"), ("send_by", "TEXT DEFAULT 'whatsapp'"), ("company_id", "INTEGER"), ("payment_mode", "TEXT DEFAULT 'fifo'"), ("statement_mode", "TEXT DEFAULT 'activity'")],
}


def init_db(path):
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    con = sqlite3.connect(path)
    con.execute("PRAGMA journal_mode = WAL")
    con.executescript(SCHEMA)
    for table, cols in MIGRATIONS.items():
        have = {r[1] for r in con.execute(f"PRAGMA table_info({table})")}
        for name, decl in cols:
            if name not in have:
                con.execute(f"ALTER TABLE {table} ADD COLUMN {name} {decl}")
    if not con.execute("SELECT 1 FROM items WHERE kind = 'subtotal'").fetchone():
        con.execute("INSERT INTO items (code, name, description, kind) VALUES ('SUB TOTAL', 'Sub total', 'SUB TOTAL', 'subtotal')")
    for k, v in DEFAULT_SETTINGS.items():
        con.execute("INSERT OR IGNORE INTO settings (key, value) VALUES (?, ?)", (k, v))
    _migrate_roles(con)
    _migrate_warehouse(con)
    _migrate_companies(con)
    from .perms import seed
    seed(con)
    _backfill_customers(con)
    if not con.execute("SELECT 1 FROM settings WHERE key = 'salary_rule_v3'").fetchone():
        con.execute("UPDATE settings SET value = '10' WHERE key = 'allowance_absent_limit' AND value = '12'")
        con.execute("INSERT INTO settings (key, value) VALUES ('salary_rule_v3', '1')")
    if not con.execute("SELECT 1 FROM settings WHERE key = 'salary_rule_v2'").fetchone():
        # your rule: every month counts as 30 days (set once; you can still change it in Settings → Salary)
        con.execute("UPDATE settings SET value = '30' WHERE key = 'salary_days_basis'")
        con.execute("INSERT INTO settings (key, value) VALUES ('salary_rule_v2', '1')")
    con.commit()
    con.close()


CITIES = ["Lahore", "Karachi", "Islamabad", "Rawalpindi", "Faisalabad", "Multan", "Peshawar", "Quetta", "Sialkot", "Gujranwala",
          "Hyderabad", "Bahawalpur", "Sargodha", "Sukkur", "Sheikhupura", "Gujrat", "Sahiwal", "Okara", "Kasur", "Abbottabad",
          "Mardan", "Rahim Yar Khan", "Jhelum", "Mirpur", "Muzaffarabad", "Dera Ghazi Khan", "Larkana", "Wah Cantt", "Attock", "Kharian"]


def guess_city(address):
    a = (address or "").lower()
    hits = [(a.rfind(c.lower()), c) for c in CITIES if c.lower() in a]
    return max(hits)[1] if hits else ""


def _backfill_customers(con):
    """Customer codes C-0001… for everyone without one, and the city read from the address where it's obvious."""
    rows = con.execute("SELECT id, code, city, address FROM customers ORDER BY id").fetchall()
    used = {r[1] for r in rows if r[1]}
    n = 0
    for cid, code, city, addr in rows:
        if not code:
            n += 1
            while f"C-{n:04d}" in used:
                n += 1
            used.add(f"C-{n:04d}")
            con.execute("UPDATE customers SET code = ? WHERE id = ?", (f"C-{n:04d}", cid))
        if not city and addr:
            g = guess_city(addr)
            if g:
                con.execute("UPDATE customers SET city = ? WHERE id = ?", (g, cid))


def next_customer_code():
    rows = q("SELECT code FROM customers WHERE code LIKE 'C-%'")
    nums = [int(r["code"][2:]) for r in rows if r["code"][2:].isdigit()]
    return f"C-{(max(nums) + 1) if nums else 1:04d}"


def _migrate_roles(con):
    """Older databases only allowed admin/accounts/rep; rebuild the users table to allow the storekeeper role."""
    sql = con.execute("SELECT sql FROM sqlite_master WHERE type = 'table' AND name = 'users'").fetchone()[0]
    if "'store'" in sql:
        return
    con.execute("PRAGMA foreign_keys = OFF")
    con.execute("ALTER TABLE users RENAME TO users_old")
    con.execute(sql.replace("'rep')", "'rep','store')").replace("TABLE users", "TABLE users", 1)
                .replace("CREATE TABLE \"users\"", "CREATE TABLE users"))
    cols = ", ".join(r[1] for r in con.execute("PRAGMA table_info(users_old)"))
    con.execute(f"INSERT INTO users ({cols}) SELECT {cols} FROM users_old")
    con.execute("DROP TABLE users_old")
    con.execute("PRAGMA foreign_keys = ON")


def _migrate_companies(con):
    """Three-company support: one default company from the old settings; invoice numbers become per company."""
    if not con.execute("SELECT 1 FROM companies").fetchone():
        st = dict(con.execute("SELECT key, value FROM settings").fetchall())
        try:
            tax = float(st.get("default_tax_rate") or 0)
        except ValueError:
            tax = 0
        try:
            nxt = int(st.get("next_invoice_number") or 1)
        except ValueError:
            nxt = 1
        con.execute("""INSERT INTO companies (code, name, gst_registered, ntn, default_tax_rate, address, phone, email, website,
                       next_invoice_number, invoice_note, sort) VALUES (?,?,?,?,?,?,?,?,?,?,?,1)""",
                    ("C1", st.get("company_name") or "My Company", 1 if tax else 0, st.get("company_tax_no", ""), tax,
                     st.get("company_address", ""), st.get("company_phone", ""), st.get("company_email", ""),
                     st.get("company_website", ""), nxt, st.get("invoice_note", "")))
    first = con.execute("SELECT id FROM companies ORDER BY sort, id LIMIT 1").fetchone()[0]
    for t in ("customers", "invoices", "payments", "credit_notes", "purchases", "supplier_payments", "expenses"):
        con.execute(f"UPDATE {t} SET company_id = ? WHERE company_id IS NULL", (first,))
    # invoices from other companies may reuse the same number, so the old "number is unique" rule is replaced
    sql = con.execute("SELECT sql FROM sqlite_master WHERE type = 'table' AND name = 'invoices'").fetchone()[0]
    if "number INTEGER UNIQUE NOT NULL" in sql:
        con.commit()
        con.execute("PRAGMA foreign_keys = OFF")
        cols = ", ".join(r[1] for r in con.execute("PRAGMA table_info(invoices)"))
        con.execute(sql.replace("number INTEGER UNIQUE NOT NULL", "number INTEGER NOT NULL")
                    .replace("CREATE TABLE invoices", "CREATE TABLE invoices_new", 1)
                    .replace('CREATE TABLE "invoices"', "CREATE TABLE invoices_new", 1))
        con.execute(f"INSERT INTO invoices_new ({cols}) SELECT {cols} FROM invoices")
        con.execute("DROP TABLE invoices")
        con.execute("ALTER TABLE invoices_new RENAME TO invoices")
        con.execute("PRAGMA foreign_keys = ON")
        for ix in ("CREATE INDEX IF NOT EXISTS ix_inv_cust ON invoices(customer_id, date)",):
            con.execute(ix)
    con.execute("CREATE UNIQUE INDEX IF NOT EXISTS ux_inv_co_num ON invoices(company_id, number)")
    for k, v in (("default_purchase_company", str(first)), ("salary_company", str(first))):
        con.execute("INSERT OR IGNORE INTO settings (key, value) VALUES (?, ?)", (k, v))
    # Safety net: anything saved without a company gets the customer's company (sales) or the default company.
    first_sql = "(SELECT id FROM companies WHERE active = 1 ORDER BY sort, id LIMIT 1)"
    buy_sql = f"COALESCE((SELECT CAST(value AS INTEGER) FROM settings WHERE key = 'default_purchase_company'), {first_sql})"
    for t in ("invoices", "payments", "credit_notes"):
        con.execute(f"""CREATE TRIGGER IF NOT EXISTS tg_{t}_co AFTER INSERT ON {t} WHEN NEW.company_id IS NULL BEGIN
                        UPDATE {t} SET company_id = COALESCE((SELECT company_id FROM customers WHERE id = NEW.customer_id), {first_sql})
                        WHERE id = NEW.id; END""")
    con.execute(f"""CREATE TRIGGER IF NOT EXISTS tg_customers_co AFTER INSERT ON customers WHEN NEW.company_id IS NULL BEGIN
                    UPDATE customers SET company_id = {first_sql} WHERE id = NEW.id; END""")
    for t in ("purchases", "supplier_payments", "expenses"):
        con.execute(f"""CREATE TRIGGER IF NOT EXISTS tg_{t}_co AFTER INSERT ON {t} WHEN NEW.company_id IS NULL BEGIN
                        UPDATE {t} SET company_id = {buy_sql} WHERE id = NEW.id; END""")


def _migrate_warehouse(con):
    """One-time move from the old invoice-linked stock to the separate warehouse module."""
    if not con.execute("SELECT 1 FROM warehouses").fetchone():
        con.execute("INSERT INTO warehouses (code, name, is_default) VALUES ('MAIN', 'Main warehouse', 1)")
    if con.execute("SELECT value FROM settings WHERE key = 'wh_migrated'").fetchone():
        return
    wid = con.execute("SELECT id FROM warehouses WHERE is_default = 1 ORDER BY id LIMIT 1").fetchone()[0]
    stamp = datetime.now().strftime("%Y-%m-%d %H:%M")
    opening = con.execute("SELECT id, opening_qty, opening_cost FROM items WHERE kind = 'item' AND opening_qty != 0").fetchall()
    if opening and not con.execute("SELECT 1 FROM wh_docs").fetchone():
        cur = con.execute("INSERT INTO wh_docs (type, number, date, warehouse_id, notes, created_at) VALUES ('OPN', 1, ?, ?, ?, ?)",
                          (date.today().isoformat(), wid, "Opening stock brought over from item settings", stamp))
        for n, (iid, qty, cost) in enumerate(opening):
            con.execute("INSERT INTO wh_lines (doc_id, item_id, qty, unit_cost, sort) VALUES (?,?,?,?,?)", (cur.lastrowid, iid, qty, cost or 0, n))
    num = 0
    for d_, iid, qty, reason in con.execute("SELECT date, item_id, qty, reason FROM stock_adjustments ORDER BY id").fetchall():
        num += 1
        cur = con.execute("INSERT INTO wh_docs (type, number, date, warehouse_id, notes, created_at) VALUES ('ADJ', ?, ?, ?, ?, ?)",
                          (num, d_, wid, reason or "", stamp))
        con.execute("INSERT INTO wh_lines (doc_id, item_id, qty, sort) VALUES (?,?,?,0)", (cur.lastrowid, iid, qty))
    con.execute("INSERT INTO settings (key, value) VALUES ('wh_migrated', '1')")


def q(sql, args=(), one=False):
    cur = get_db().execute(sql, args)
    rows = cur.fetchall()
    return (rows[0] if rows else None) if one else rows


def x(sql, args=()):
    cur = get_db().execute(sql, args)
    return cur.lastrowid


def commit():
    get_db().commit()


def settings():
    if "settings" not in g:
        g.settings = {r["key"]: r["value"] for r in q("SELECT key, value FROM settings")}
    return g.settings


def set_setting(key, value):
    x("INSERT INTO settings (key, value) VALUES (?, ?) ON CONFLICT(key) DO UPDATE SET value = excluded.value",
      (key, value))
    g.pop("settings", None)


def next_number(table, setting_key):
    start = int(settings().get(setting_key) or 1)
    cur_max = q(f"SELECT MAX(number) AS m FROM {table}", one=True)["m"] or 0
    return max(start, cur_max + 1)


# ---- money & dates --------------------------------------------------------------
def to_paisa(value):
    """'1,250.50' -> 125050. Blank -> 0. Raises ValueError on junk."""
    s = str(value or "").replace(",", "").strip()
    if not s:
        return 0
    try:
        return int((Decimal(s) * 100).quantize(Decimal("1"), rounding=ROUND_HALF_UP))
    except InvalidOperation:
        raise ValueError(f"'{value}' is not a valid amount")


def fmt(paisa, blank_zero=False):
    if paisa is None:
        paisa = 0
    if blank_zero and paisa == 0:
        return ""
    neg = paisa < 0
    s = f"{abs(paisa) / 100:,.2f}"
    return f"-{s}" if neg else s


def plain(paisa):
    """For form fields: 125050 -> '1250.50'."""
    return f"{(paisa or 0) / 100:.2f}"


def today():
    return date.today().isoformat()


def now():
    return datetime.now().strftime("%Y-%m-%d %H:%M")


def parse_date(s, default=None):
    try:
        return date.fromisoformat(str(s)).isoformat()
    except (TypeError, ValueError):
        return default


def nice_date(s):
    try:
        return date.fromisoformat(s).strftime("%d-%b-%Y")
    except (TypeError, ValueError):
        return s or ""
