"""Users & roles: every user has one role, a role is a set of tick-box permissions (like QuickBooks Users and Roles)."""
import json

from flask import abort, flash, g, redirect, render_template, request, url_for

from .db import commit, q, x

AREAS = [
    ("Customers", [("customers.view", "View customers & balances"), ("customers.edit", "Add / edit customers")]),
    ("Invoices", [("invoices.view", "View"), ("invoices.create", "Create"), ("invoices.edit", "Edit"), ("invoices.void", "Void"),
                  ("invoices.send", "Send (WhatsApp / email)")]),
    ("Payments received", [("payments.view", "View"), ("payments.create", "Receive payments"), ("payments.edit", "Edit"),
                           ("payments.void", "Void")]),
    ("Quotations", [("quotes.view", "View"), ("quotes.create", "Create / edit"), ("quotes.void", "Void")]),
    ("Order booking", [("orders.create", "Take orders (order booker)"), ("orders.view", "View orders"),
                       ("orders.approve", "Approve / reject orders and turn them into invoices"),
                       ("orders.price", "Change price / give discount on orders")]),
    ("Sales returns", [("returns.view", "View"), ("returns.create", "Create / edit"), ("returns.void", "Void")]),
    ("Statements & reminders", [("statements.send", "Send statements, balances, month-end")]),
    ("Items & prices", [("items.view", "View"), ("items.edit", "Add / edit items and prices")]),
    ("Suppliers & purchase bills", [("purchases.view", "View"), ("purchases.create", "Enter bills"), ("purchases.edit", "Edit / void bills")]),
    ("Supplier payments", [("supplier_payments.view", "View"), ("supplier_payments.create", "Pay suppliers"),
                           ("supplier_payments.void", "Void")]),
    ("Expenses", [("expenses.view", "View"), ("expenses.create", "Enter expenses"), ("expenses.void", "Void")]),
    ("Warehouse", [("warehouse.view", "View stock"), ("warehouse.work", "Receive / dispatch / transfer / count"),
                   ("warehouse.manage", "Void documents, manage warehouses")]),
    ("Salary", [("salary.view", "View salaries & employees"), ("salary.run", "Make salary sheets, pay, advances")]),
    ("Reports", [("reports.sales", "Sales & customer reports"), ("reports.finance", "Profit & loss, payables, purchases, expenses"),
                 ("reports.costs", "See costs, stock value & profit")]),
    ("Admin", [("approve.voids", "Approve void / delete requests (others must ask)"), ("admin.users", "Users & roles"), ("admin.settings", "Settings, companies, print designer, sales reps"),
               ("admin.import", "Import data")]),
    ("Limits", [("scope.own_customers", "Only their own customers (sales rep login)")]),
]
ALL = [k for _, ps in AREAS for k, _ in ps]
EVERYTHING = [k for k in ALL if not k.startswith("scope.")]
VIEW_ONLY = [k for k in EVERYTHING if k.endswith(".view")] + ["reports.sales", "reports.finance", "reports.costs"]


def _without(*prefixes):
    return [k for k in EVERYTHING if not k.startswith(prefixes)]


SALES = ["customers.view", "customers.edit", "invoices.view", "invoices.create", "invoices.send", "payments.view",
         "statements.send", "items.view", "warehouse.view", "reports.sales"]
BUILTIN = [
    ("Admin", "Everything, including users, roles and settings.", EVERYTHING),
    ("Full Access", "Everything except users, roles and settings.", _without("admin.", "approve.")),
    ("Accountant", "Bookkeeping: sales, purchases, expenses, salary and all reports. No users or settings.",
     _without("admin.users", "admin.settings", "approve.")),
    ("Accounts Receivable", "Customers, invoices, payments received, returns, statements and sales reports.",
     ["customers.view", "customers.edit", "invoices.view", "invoices.create", "invoices.edit", "invoices.void", "invoices.send",
      "payments.view", "payments.create", "payments.edit", "payments.void", "returns.view", "returns.create", "returns.void",
      "statements.send", "items.view", "warehouse.view", "reports.sales"]),
    ("Accounts Payable", "Suppliers, purchase bills, supplier payments, expenses and their reports.",
     ["purchases.view", "purchases.create", "purchases.edit", "supplier_payments.view", "supplier_payments.create",
      "supplier_payments.void", "expenses.view", "expenses.create", "expenses.void", "items.view", "reports.finance"]),
    ("Sales", "Make invoices and send them; see customers and payments. Cannot edit or void.", SALES),
    ("Sales rep (own customers)", "Like Sales, plus receiving payments, but only for the rep's own customers.",
     SALES + ["payments.create", "scope.own_customers"]),
    ("Payments only", "Receive payments and send receipts / statements. Can view customers and invoices.",
     ["customers.view", "invoices.view", "payments.view", "payments.create", "statements.send"]),
    ("Purchasing", "Enter purchase bills; view suppliers and stock.", ["purchases.view", "purchases.create", "items.view", "warehouse.view"]),
    ("Inventory / Storekeeper", "Warehouse only: receive, dispatch, transfer and count stock. No prices.",
     ["warehouse.view", "warehouse.work", "items.view"]),
    ("Warehouse manager", "All warehouse work, voiding documents and managing warehouses and items.",
     ["warehouse.view", "warehouse.work", "warehouse.manage", "items.view", "items.edit"]),
    ("Payroll", "Employees, advances, salary sheets and payslips.", ["salary.view", "salary.run"]),
    ("Finance", "View everything and all reports, including profit and costs. Cannot change anything.", VIEW_ONLY + ["salary.view"]),
    ("View-Only", "Can look at everything except salaries and costs. Cannot change anything.",
     [k for k in VIEW_ONLY if k not in ("salary.view", "reports.costs")]),
]
LEGACY = {"admin": "Admin", "accounts": "Full Access", "rep": "Sales rep (own customers)", "store": "Inventory / Storekeeper"}


def seed(con):
    """Creates the ready-made roles once and links old-style users to them."""
    if not con.execute("SELECT 1 FROM roles LIMIT 1").fetchone():
        for n, (name, desc, perms) in enumerate(BUILTIN):
            con.execute("INSERT INTO roles (name, description, perms, builtin, sort) VALUES (?,?,?,?,?)",
                        (name, desc, json.dumps(sorted(set(perms))), 1, n))
        salary_ok = (con.execute("SELECT value FROM settings WHERE key = 'salary_accounts_access'").fetchone() or ["0"])[0] == "1"
        if not salary_ok:  # accounts users could not see salaries before, keep it that way
            fa = con.execute("SELECT id, perms FROM roles WHERE name = 'Full Access'").fetchone()
            con.execute("UPDATE roles SET perms = ? WHERE id = ?",
                        (json.dumps([p for p in json.loads(fa[1]) if not p.startswith("salary.")]), fa[0]))
    adm = con.execute("SELECT id, perms FROM roles WHERE name = 'Admin'").fetchone()
    if adm:  # Admin always has every permission, including ones added in later updates
        have = set(json.loads(adm[1]))
        if not set(EVERYTHING) <= have:
            con.execute("UPDATE roles SET perms = ? WHERE id = ?", (json.dumps(sorted(have | set(EVERYTHING))), adm[0]))
    _grant_new(con)
    for legacy, name in LEGACY.items():
        rid = con.execute("SELECT id FROM roles WHERE name = ?", (name,)).fetchone()
        if rid:
            con.execute("UPDATE users SET role_id = ? WHERE role_id IS NULL AND role = ?", (rid[0], legacy))


NEW_GRANTS = {  # role name -> permissions added once (Admin gets everything automatically)
    "quotes_orders_v1": {
        "Full Access": ["quotes.view", "quotes.create", "quotes.void", "orders.view", "orders.create", "orders.approve", "orders.price"],
        "Accountant": ["quotes.view", "quotes.create", "quotes.void", "orders.view", "orders.approve", "orders.price"],
        "Accounts Receivable": ["quotes.view", "quotes.create", "quotes.void", "orders.view", "orders.approve", "orders.price"],
        "Sales": ["quotes.view", "quotes.create", "orders.view", "orders.create"],
        "Sales rep (own customers)": ["quotes.view", "quotes.create", "orders.view", "orders.create"],
        "Finance": ["quotes.view", "orders.view"],
        "View-Only": ["quotes.view", "orders.view"],
    }}


def _grant_new(con):
    for key, grants in NEW_GRANTS.items():
        done = con.execute("SELECT value FROM settings WHERE key = ?", (key,)).fetchone()
        if done:
            continue
        for name, add in grants.items():
            r = con.execute("SELECT id, perms FROM roles WHERE name = ?", (name,)).fetchone()
            if r:
                con.execute("UPDATE roles SET perms = ? WHERE id = ?", (json.dumps(sorted(set(json.loads(r[1])) | set(add))), r[0]))
        con.execute("INSERT OR REPLACE INTO settings (key, value) VALUES (?, '1')", (key,))


# ---- checking --------------------------------------------------------------------------------
def user_perms(user=None):
    user = user if user is not None else g.get("user")
    if not user:
        return frozenset()
    if g.get("perm_cache_uid") == user["id"]:
        return g.perm_cache
    row = None
    if user["role_id"]:
        row = q("SELECT perms FROM roles WHERE id = ?", (user["role_id"],), one=True)
    if not row:
        row = q("SELECT perms FROM roles WHERE name = ?", (LEGACY.get(user["role"], "View-Only"),), one=True)
    try:
        perms = frozenset(json.loads(row["perms"])) if row else frozenset()
    except ValueError:
        perms = frozenset()
    g.perm_cache, g.perm_cache_uid = perms, user["id"]
    return perms


def has(perm):
    return perm in user_perms()


def any_of(*perms):
    p = user_perms()
    return any(x in p for x in perms)


def role_name(user=None):
    user = user if user is not None else g.get("user")
    if not user:
        return ""
    r = q("SELECT name FROM roles WHERE id = ?", (user["role_id"],), one=True) if user["role_id"] else None
    return r["name"] if r else LEGACY.get(user["role"], user["role"])


# Which permission each page needs. (endpoint, method) or endpoint -> permission; a tuple means "any of these".
OPEN = {"core.login", "core.setup", "core.logout", "core.change_password", "static", "co.switch", "core.settings_image", "co.logo",
        "core.dashboard", "core.home_for_user"}
RULES = {
    "sales.customers": "customers.view", "sales.customer_view": "customers.view", "sales.customer_api": ("customers.view", "invoices.view",
                                                                                                          "payments.view"),
    "sales.customer_form": "customers.edit", "sales.statement_pdf": "customers.view", "sales.statement_xlsx": "customers.view",
    "sales.statement_send": "statements.send", "sales.customer_whatsapp": "statements.send",
    "sales.invoices": "invoices.view", "sales.invoice_view": "invoices.view", "sales.invoice_go": "invoices.view",
    "sales.invoice_pdf": "invoices.view", "sales.invoice_dc_pdf": ("invoices.view", "warehouse.work"),
    "sales.invoice_new": "invoices.create", ("sales.invoice_form", "GET"): "invoices.view", ("sales.invoice_form", "POST"): "invoices.edit",
    "sales.invoice_void": "invoices.void", "sales.invoice_send": "invoices.send", "sales.invoice_email": "invoices.send",
    "sales.invoice_delivered": ("invoices.edit", "invoices.create", "warehouse.work"),
    "sales.invoice_import_lines": "invoices.create", "sales.invoice_import_template": "invoices.create",
    "sales.payments": "payments.view", "sales.payment_view": "payments.view", "sales.payment_go": "payments.view",
    "sales.payment_pdf": "payments.view", "sales.payment_new": "payments.create", "sales.payment_edit": "payments.edit",
    "sales.payment_void": "payments.void", "sales.payment_send": ("payments.create", "statements.send"),
    "sales.payment_email": ("payments.create", "statements.send"),
    "po.index": "invoices.view", "po.view": "invoices.view", "po.pdf": "invoices.view", "po.new": "invoices.create",
    "po.edit": "invoices.edit", "po.tracking": ("invoices.edit", "warehouse.work"), "po.combine": "invoices.create",
    "po.send": "invoices.send", "po.void": "invoices.void", "po.pay": "payments.create", "po.attach": "invoices.edit",
    "po.detach": "invoices.edit", "po.branch_save": "customers.edit", "po.branch_import": "customers.edit",
    "quotes.index": "quotes.view", "quotes.view_one": "quotes.view", "quotes.pdf": "quotes.view", "quotes.new": "quotes.create",
    "quotes.status": "quotes.create", "quotes.void": "quotes.void", "quotes.send_whatsapp": "quotes.create", "quotes.send_email": "quotes.create", "quotes.to_invoice": ("invoices.create",),
    "orders.index": ("orders.view", "orders.create"), "orders.view_one": ("orders.view", "orders.create"),
    "orders.new": ("orders.create", "orders.approve"), "orders.approve": "orders.approve",
    "orders.reject": "orders.approve", "orders.cancel": ("orders.create", "orders.approve"), "orders.count": ("orders.view", "orders.create"),
    "sales.items": "items.view", "sales.items_set_group": "items.edit", "sales.item_form": "items.edit",
    "ops.credit_notes": "returns.view", "ops.credit_view": "returns.view", "ops.credit_pdf": "returns.view",
    "ops.credit_new": "returns.create", "ops.credit_edit": "returns.create", "ops.credit_void": "returns.void",
    "ops.suppliers": "purchases.view", "ops.supplier_view": "purchases.view",
    "ops.supplier_api": ("purchases.view", "supplier_payments.view"), "ops.supplier_form": ("purchases.create", "purchases.edit"),
    "sup.supplier_statement_pdf": ("purchases.view", "supplier_payments.view"), "sup.supplier_whatsapp": ("purchases.view", "supplier_payments.view"),
    "sup.purchase_pdf": "purchases.view", "sup.supplier_payment_pdf": "supplier_payments.view",
    "sup.supplier_payment_whatsapp": ("supplier_payments.create", "supplier_payments.view"),
    "ops.purchases": "purchases.view", "ops.purchase_view": "purchases.view", "ops.purchase_new": "purchases.create",
    "ops.purchase_edit": "purchases.edit", "ops.purchase_void": "purchases.edit",
    "ops.supplier_payments": "supplier_payments.view", "ops.supplier_payment_new": "supplier_payments.create",
    "ops.supplier_payment_void": "supplier_payments.void",
    "ops.expenses": "expenses.view", "ops.expense_new": "expenses.create", "ops.expense_void": "expenses.void",
    "ops.stock": "warehouse.view", "ops.stock_card": "warehouse.view",
    "wh.home": "warehouse.view", "wh.api_stock": ("warehouse.view", "invoices.create"), "wh.card": "warehouse.view",
    "wh.movements": "warehouse.view", "wh.docs": "warehouse.view", "wh.doc_view": "warehouse.view", "wh.doc_pdf": "warehouse.view",
    "wh.doc_new": "warehouse.work", "wh.doc_edit": "warehouse.work", "wh.doc_void": "warehouse.manage",
    "wh.warehouses": "warehouse.manage",
    "reports.index": ("reports.sales", "reports.finance"), "reports.sales": "reports.sales", "reports.payments": "reports.sales",
    "reports.balances": "reports.sales", "reports.aging": "reports.sales", "reports.aging_detail": "reports.sales",
    "reports.open_invoices": "reports.sales", "reports.collections": "reports.sales", "reports.transactions": "reports.sales",
    "reports.sales_detail": "reports.sales", "reports.phone_list": "customers.view", "reports.contact_list": "customers.view",
    "reports.item_prices": "items.view", ("reports.month_end", "GET"): ("statements.send", "reports.sales"),
    ("reports.month_end", "POST"): "statements.send", "reports.messages": ("statements.send", "invoices.send", "reports.sales"),
    "reports.profit_loss": "reports.finance", "reports.payables": "reports.finance", "reports.purchases_report": "reports.finance",
    "reports.expenses_report": "reports.finance",
    "core.users": "admin.users", "core.user_form": "admin.users", "core.roles": "admin.users", "core.role_form": "admin.users",
    "core.role_delete": "admin.users", "core.settings_page": "admin.settings", "core.reps": "admin.settings",
    "ap.index": ("invoices.view", "payments.view", "approve.voids"), "ap.decide": "approve.voids",
    "ap.cancel": ("invoices.view", "payments.view", "approve.voids"),
    "sales.transactions": ("invoices.view", "payments.view"), "sales.search": ("customers.view", "invoices.view", "payments.view"),
    "co.manage": "admin.settings", "co.defaults": "admin.settings",
    "pd.editor": "admin.settings", "pd.image": "admin.settings", "pd.save": "admin.settings", "pd.off": "admin.settings",
    "pd.preview": "admin.settings", "pd.templates": "admin.settings", "pd.template_preview": "admin.settings", "importer.index": "admin.import",
}


def needed(endpoint, method):
    if endpoint in OPEN:
        return None
    if (endpoint, method) in RULES:
        return RULES[(endpoint, method)]
    if endpoint in RULES:
        return RULES[endpoint]
    if endpoint.startswith("hr."):
        return "salary.view" if method == "GET" else "salary.run"
    return "admin.users"  # anything not listed is admin-only, to be safe


def allowed(endpoint, method="GET"):
    need = needed(endpoint, method)
    if need is None:
        return True
    return any_of(*need) if isinstance(need, tuple) else has(need)


def home_endpoint():
    """Where a user lands: the dashboard if they can see sales, else the first area they can use."""
    for perm, ep in (("customers.view", "core.dashboard"), ("invoices.view", "core.dashboard"), ("payments.view", "core.dashboard"),
                     ("warehouse.view", "wh.home"), ("purchases.view", "ops.purchases"), ("expenses.view", "ops.expenses"),
                     ("salary.view", "hr.home"), ("reports.sales", "reports.index"), ("reports.finance", "reports.index")):
        if has(perm):
            return ep
    return "core.change_password"


# ---- screens -------------------------------------------------------------------------------------
def roles_page():
    rows = q("SELECT * FROM roles ORDER BY sort, name")
    sel = request.args.get("id", type=int) or (rows[0]["id"] if rows else None)
    cur = next((r for r in rows if r["id"] == sel), None)
    users = q("SELECT name, username, active FROM users WHERE role_id = ? ORDER BY name", (sel,)) if cur else []
    counts = {r["role_id"]: r["n"] for r in q("SELECT role_id, COUNT(*) AS n FROM users GROUP BY role_id")}
    return render_template("roles.html", rows=rows, cur=cur, users=users, counts=counts, areas=AREAS,
                           perms=set(json.loads(cur["perms"])) if cur else set())


def role_form(rid=None):
    r = q("SELECT * FROM roles WHERE id = ?", (rid,), one=True) if rid else None
    if rid and not r:
        abort(404)
    copy_of = request.args.get("copy", type=int)
    src = q("SELECT * FROM roles WHERE id = ?", (copy_of,), one=True) if copy_of else None
    if request.method == "POST":
        f = request.form
        name = f.get("name", "").strip()
        perms = sorted({p for p in f.getlist("perm") if p in ALL})
        if not name:
            flash("Give the role a name.", "err")
        elif q("SELECT 1 FROM roles WHERE name = ? COLLATE NOCASE AND id != ?", (name, rid or -1)):
            flash("There is already a role with that name.", "err")
        elif r and r["name"] == "Admin" and "admin.users" not in perms:
            flash("The Admin role must keep 'Users & roles', otherwise nobody could manage users.", "err")
        elif r and g.user["role_id"] == r["id"] and "admin.users" not in perms:
            flash("You can't remove 'Users & roles' from your own role.", "err")
        else:
            if r:
                x("UPDATE roles SET name = ?, description = ?, perms = ? WHERE id = ?",
                  (name, f.get("description", "").strip(), json.dumps(perms), rid))
            else:
                rid = x("INSERT INTO roles (name, description, perms, builtin, sort) VALUES (?,?,?,0,100)",
                        (name, f.get("description", "").strip(), json.dumps(perms)))
            commit()
            flash(f"Role '{name}' saved.", "ok")
            return redirect(url_for("core.roles", id=rid))
        return render_template("role_form.html", r=r, f=f, areas=AREAS, perms=set(perms))
    base = r or src
    f = {"name": (r["name"] if r else (f"Copy of {src['name']}" if src else "")),
         "description": base["description"] if base else ""}
    return render_template("role_form.html", r=r, f=f, areas=AREAS, perms=set(json.loads(base["perms"])) if base else set())


def role_delete(rid):
    r = q("SELECT * FROM roles WHERE id = ?", (rid,), one=True) or abort(404)
    n = q("SELECT COUNT(*) AS n FROM users WHERE role_id = ?", (rid,), one=True)["n"]
    if r["name"] == "Admin":
        flash("The Admin role can't be deleted.", "err")
    elif n:
        flash(f"{n} user(s) still have this role. Give them another role first.", "err")
    else:
        x("DELETE FROM roles WHERE id = ?", (rid,))
        commit()
        flash(f"Role '{r['name']}' deleted.", "ok")
    return redirect(url_for("core.roles"))
