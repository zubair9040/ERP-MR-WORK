"""Login, first-run setup, dashboard, settings, users and sales reps."""
from datetime import date, datetime, timedelta

import os

from flask import (Blueprint, abort, current_app, flash, g, redirect, render_template, request, send_file,
                   session, url_for)
from werkzeug.security import check_password_hash, generate_password_hash

from .auth import co_filter, current_company, is_rep, login_failed, login_locked, login_ok, rep_filter, sees_cost
from .db import commit, fmt, now, parse_date, q, set_setting, settings, today, to_paisa, x
from .ledger import customers_with_balance

bp = Blueprint("core", __name__)


def _login(u):
    session.clear()
    session.permanent = True
    session["uid"] = u["id"]
    session["pw"] = u["password_hash"][-12:]


@bp.route("/setup", methods=["GET", "POST"])
def setup():
    if q("SELECT 1 FROM users LIMIT 1"):
        return redirect(url_for("core.login"))
    if request.method == "POST":
        f = request.form
        if len(f.get("password", "")) < 8:
            flash("Password must be at least 8 characters.", "err")
        elif f["password"] != f.get("password2"):
            flash("Passwords don't match.", "err")
        else:
            set_setting("company_name", f.get("company_name", "").strip() or "My Company")
            uid = x("INSERT INTO users (username, name, password_hash, role, created_at) VALUES (?,?,?,?,?)",
                    (f["username"].strip(), f["name"].strip(), generate_password_hash(f["password"]), "admin", now()))
            commit()
            _login(q("SELECT * FROM users WHERE id = ?", (uid,), one=True))
            flash("Welcome! Start by filling in your company details.", "ok")
            return redirect(url_for("core.settings_page"))
    return render_template("setup.html")


@bp.route("/login", methods=["GET", "POST"])
def login():
    if not q("SELECT 1 FROM users LIMIT 1"):
        return redirect(url_for("core.setup"))
    if request.method == "POST":
        uname = request.form.get("username", "").strip()
        if login_locked(uname):
            flash("Too many wrong attempts. Please wait 10 minutes and try again.", "err")
            return render_template("login.html")
        u = q("SELECT * FROM users WHERE username = ? AND active = 1", (uname,), one=True)
        if u and check_password_hash(u["password_hash"], request.form.get("password", "")):
            login_ok(uname)
            _login(u)
            nxt = request.args.get("next", "")
            return redirect(nxt if nxt.startswith("/") and not nxt.startswith("//") else url_for("core.dashboard"))
        login_failed(uname)
        flash("Wrong username or password.", "err")
    return render_template("login.html")


@bp.route("/logout", methods=["POST"])
def logout():
    session.clear()
    return redirect(url_for("core.login"))


PERIODS = [("today", "Today"), ("7d", "7 days"), ("month", "This month"), ("last", "Last month"), ("fy", "This FY")]


def _dash_period():
    t = date.today()
    p = request.args.get("p", "month")
    a, b = parse_date(request.args.get("from")), parse_date(request.args.get("to"))
    if a and b:
        return "custom", min(a, b), max(a, b)
    if p == "today":
        return p, t.isoformat(), t.isoformat()
    if p == "7d":
        return p, (t - timedelta(days=6)).isoformat(), t.isoformat()
    if p == "last":
        end = t.replace(day=1) - timedelta(days=1)
        return p, end.replace(day=1).isoformat(), end.isoformat()
    if p == "fy":  # Pakistan financial year: 1 July to 30 June
        return p, date(t.year if t.month >= 7 else t.year - 1, 7, 1).isoformat(), t.isoformat()
    return "month", t.replace(day=1).isoformat(), t.isoformat()


def _attention(where, args, aging_rows, custs):
    """Things that need someone to act, each with a link to the list."""
    out = []
    today_d = date.today()
    over_n = sum(1 for r in aging_rows if r["total"] - r["buckets"]["Current"] > 0)
    over_amt = sum(r["total"] - r["buckets"]["Current"] for r in aging_rows if r["total"] - r["buckets"]["Current"] > 0)
    if over_n:
        out.append({"cls": "red", "icon": "alert", "n": over_n, "title": "Customers overdue",
                    "sub": f"{fmt(over_amt)} past due date", "url": url_for("reports.aging")})
    limit = [c for c in custs if c["credit_limit"] and c["balance"] > c["credit_limit"]]
    if limit:
        out.append({"cls": "red", "icon": "shield", "n": len(limit), "title": "Over credit limit",
                    "sub": ", ".join(c["name"] for c in limit[:2]) + ("…" if len(limit) > 2 else ""),
                    "url": url_for("sales.customers", due=1)})
    since = (today_d - timedelta(days=45)).isoformat()
    undel = q(f"""SELECT COUNT(*) AS n FROM invoices i JOIN customers c ON c.id = i.customer_id
                  WHERE i.void = 0 AND i.date >= :since AND i.delivered_on = '' {where}""", {**args, "since": since}, one=True)["n"]
    from .perms import has
    if undel and has("invoices.view"):
        out.append({"cls": "blue", "icon": "truck", "n": undel, "title": "Not marked delivered",
                    "sub": "Invoices of the last 45 days", "url": url_for("sales.invoices", delivered="no")})
    if has("approve.voids"):
        from .approvals import pending_count
        pc = pending_count()
        if pc:
            out.insert(0, {"cls": "red", "icon": "shield", "n": pc, "title": "Void requests waiting",
                           "sub": "Staff asked to void / delete", "url": url_for("ap.index")})
    if is_rep():
        return out
    from .stock import levels
    lv = levels()
    low = [i for i in q("SELECT id, reorder_level FROM items WHERE kind = 'item' AND active = 1 AND reorder_level > 0")
           if lv.get(i["id"], {"on_hand": 0})["on_hand"] <= i["reorder_level"]]
    if low and has("warehouse.view"):
        out.append({"cls": "", "icon": "box", "n": len(low), "title": "Low stock", "sub": "At or below minimum",
                    "url": url_for("wh.home", low=1)})
    if not has("purchases.view") and not has("supplier_payments.view"):
        return out
    from .ops import supplier_open_bills, suppliers_with_balance
    due_n, due_amt = 0, 0
    for s_ in suppliers_with_balance(" AND s.active = 1"):
        if s_["balance"] <= 0:
            continue
        bills, opening_left, _ = supplier_open_bills(s_["id"])
        amt = opening_left + sum(b["open"] for b in bills if b["open"] and (b["b"]["due_date"] or b["b"]["date"]) < today_d.isoformat())
        if amt > 0:
            due_n += 1
            due_amt += amt
    if due_n:
        out.append({"cls": "", "icon": "send", "n": due_n, "title": "Supplier bills due",
                    "sub": f"{fmt(due_amt)} past due date", "url": url_for("reports.payables")})
    from .hr import attention as hr_attention
    h = hr_attention()
    if h:
        out.append({"cls": "", "icon": "users", "n": h.get("n", "!"), "title": "Salary", "sub": h["text"],
                    "url": url_for("hr.sheet", month=h["month"]) if q("SELECT 1 FROM payroll_runs WHERE month = ?", (h["month"],))
                    else url_for("hr.home")})
    return out


@bp.route("/")
def dashboard():
    from .ledger import aging
    where, args = rep_filter()
    t = date.today()
    period, start, end = _dash_period()
    custs = customers_with_balance(None, where, args)
    receivable = sum(c["balance"] for c in custs)
    aging_rows, due_buckets, _ = aging(where, dict(args))  # overdue (from due date) drives "Needs attention"
    overdue = sum(v for k, v in due_buckets.items() if k != "Current")
    _, buckets, _ = aging(where, dict(args), basis="invoice")  # the age chart counts from the invoice date

    def total(table, col, a, b):
        return q(f"""SELECT COALESCE(SUM(x.{col}),0) AS s, COUNT(*) AS n FROM {table} x JOIN customers c ON c.id = x.customer_id
                     WHERE x.void = 0 AND x.date BETWEEN :a AND :b {where}""", {"a": a, "b": b, **args}, one=True)

    def plain_total(table, a, b, col="amount"):
        cw, ca = co_filter("company_id")
        return q(f"SELECT COALESCE(SUM({col}), 0) AS s, COUNT(*) AS n FROM {table} WHERE void = 0 AND date BETWEEN :a AND :b {cw}",
                 {"a": a, "b": b, **ca}, one=True)

    sales = total("invoices", "total", start, end)
    received = total("payments", "amount", start, end)
    # same-length period just before, for the up/down arrows
    d0, d1 = date.fromisoformat(start), date.fromisoformat(end)
    span = (d1 - d0).days + 1
    p_end = d0 - timedelta(days=1)
    p_start = p_end - timedelta(days=span - 1)
    if period in ("month", "last"):
        p_start = (d0 - timedelta(days=1)).replace(day=1)
        p_end = min(p_start.replace(day=min(d1.day, p_end.day)), p_end)
    sales_prev = total("invoices", "total", p_start.isoformat(), p_end.isoformat())
    received_prev = total("payments", "amount", p_start.isoformat(), p_end.isoformat())

    def delta(now_, before):
        if not before:
            return None
        return round((now_ - before) * 100 / before)

    K = None
    if sees_cost():
        from .hr import advances_given, salary_paid
        from .ops import suppliers_with_balance
        from .reports import pnl_figures
        F = pnl_figures(start, end)
        purchases = plain_total("purchases", start, end, "total")
        expenses = plain_total("expenses", start, end)
        sup_paid = plain_total("supplier_payments", start, end)
        co = current_company()
        pays_salary = not co or str(co) == settings().get("salary_company")
        sal_paid, adv = (salary_paid(start, end), advances_given(start, end)) if pays_salary else (0, 0)
        cash_in = received["s"]
        cash_out = sup_paid["s"] + expenses["s"] + sal_paid + adv
        K = {"pnl": F, "purchases": purchases, "expenses": F["total_exp"], "salaries": F["salaries"],
             "payable": sum(s_["balance"] for s_ in suppliers_with_balance(" AND s.active = 1")),
             "cash_in": cash_in, "cash_out": cash_out, "flow": cash_in - cash_out}

    months = []
    m = t.replace(day=1)
    for _ in range(6):
        months.insert(0, m)
        m = (m - timedelta(days=1)).replace(day=1)
    series = []
    for m in months:
        end_m = ((m.replace(day=28) + timedelta(days=4)).replace(day=1) - timedelta(days=1)).isoformat()
        series.append({"label": m.strftime("%b"), "sales": total("invoices", "total", m.isoformat(), end_m)["s"],
                       "paid": total("payments", "amount", m.isoformat(), end_m)["s"]})
    peak = max([1] + [s_["sales"] for s_ in series] + [s_["paid"] for s_ in series])
    recent = q(f"""SELECT i.*, c.name AS customer FROM invoices i JOIN customers c ON c.id = i.customer_id
                   WHERE 1 = 1 {where} ORDER BY i.date DESC, i.number DESC LIMIT 6""", args)
    recent_pay = q(f"""SELECT p.*, c.name AS customer FROM payments p JOIN customers c ON c.id = p.customer_id
                       WHERE 1 = 1 {where} ORDER BY p.date DESC, p.number DESC LIMIT 6""", args)
    top = sorted([c for c in custs if c["balance"] > 0], key=lambda c: -c["balance"])[:6]
    hour = datetime.now().hour
    greet = "Good morning" if hour < 12 else ("Good afternoon" if hour < 17 else "Good evening")
    return render_template("dashboard.html", receivable=receivable, overdue=overdue, sales=sales, received=received,
                           sales_delta=delta(sales["s"], sales_prev["s"]), recv_delta=delta(received["s"], received_prev["s"]),
                           series=series, peak=peak, recent=recent, recent_pay=recent_pay, top=top, buckets=buckets,
                           greet=greet, customers_count=len([c for c in custs if c["balance"] > 0]),
                           period=period, start=start, end=end, periods=PERIODS, K=K,
                           attention=_attention(where, args, aging_rows, custs))


SETTING_FIELDS = [
    ("General", [
        ("ui_theme", "Look of the system", "theme"),
        ("company_name", "Group / brand name (shown when 'All companies' is selected)", "text"),
        ("logo", "Default logo (used when a company has no logo of its own)", "image"),
    ]),
    ("Invoices", [
        ("currency", "Currency label", "text"),
        ("next_payment_number", "Next payment receipt number", "text"),
        ("terms", "Terms box picture (e.g. your Urdu bilti terms, as a PNG/JPG)", "image"),
        ("invoice_terms", "Terms box text (used if no picture)", "textarea"),
        ("couriers", "Couriers, one per line: Name | tracking link with {no} where the tracking number goes (used for the Track button)", "textarea"),
        ("invoice_note", "Note printed at the bottom-left of invoices", "text"),
        ("invoice_footer", "Small footer line (optional)", "text"),
        ("print_classic", "Print with the old QuickBooks-style layout instead of the modern design (Admin → Print designer changes the design)", "check"),
    ]),
    ("Email", [
        ("email_dry_run", "Test mode: make the PDF but do NOT send emails", "check"),
        ("smtp_user", "Gmail address that sends the emails", "text"),
        ("smtp_password", "Gmail App Password (Google account → Security → App passwords)", "secret"),
        ("email_from_name", "Sender name shown to customers (blank = company name)", "text"),
        ("email_cc", "Always send a copy to (optional, e.g. your accounts email)", "text"),
        ("email_signature", "Signature at the end of every email", "textarea"),
        ("smtp_host", "Mail server (Gmail: smtp.gmail.com)", "text"),
        ("smtp_port", "Port (Gmail: 587)", "text"),
    ]),
    ("Salary", [
        ("salary_days_basis", "Days in a month for salary: '30' = always 30 days, 'month' = actual days in the month", "text"),
        ("allowance_absent_limit", "Allowance paid in full up to this many absent days; above it, allowance is paid for days present only (basic is always paid for days present)", "text"),
        ("ot_hours_per_day", "Working hours per day (for overtime rate)", "text"),
        ("ot_rate_multiplier", "Overtime pay = hourly rate × this (e.g. 1, 1.5 or 2)", "text"),
    ]),
    ("Warehouse", [
        ("allow_negative_stock", "Allow dispatching more than is in stock (stock can go below zero)", "check"),
    ]),
    ("WhatsApp", [
        ("wa_dry_run", "Test mode: create PDFs but do NOT send", "check"),
        ("auto_send_invoice", "Send invoice on WhatsApp automatically when saved", "check"),
        ("auto_send_receipt", "Send payment receipt on WhatsApp automatically when saved", "check"),
        ("country_code", "Country code for phone numbers", "text"),
        ("wa_phone_number_id", "Meta phone number ID", "text"),
        ("wa_access_token", "Meta permanent access token", "secret"),
        ("wa_api_version", "Graph API version", "text"), ("wa_language", "Template language code", "text"),
        ("wa_invoice_template", "Invoice template name", "text"),
        ("wa_receipt_template", "Payment receipt template name", "text"),
        ("wa_payslip_template", "Payslip template name (employee name, month, net salary)", "text"),
        ("wa_statement_template", "Statement template name", "text"),
        ("wa_balance_template", "Balance message template name", "text"),
        ("wa_supplier_template", "Supplier template name (supplier name, amount, date). Blank = use the statement template", "text"),
    ]),
]


@bp.route("/settings", methods=["GET", "POST"])
def settings_page():
    if request.method == "POST":
        for _, fields in SETTING_FIELDS:
            for key, _, kind in fields:
                if kind == "image":
                    up = request.files.get(key)
                    if request.form.get(key + "_remove"):
                        for ext in IMAGE_EXTS:
                            pth = os.path.join(upload_dir(), key + ext)
                            if os.path.exists(pth):
                                os.remove(pth)
                    if up and up.filename:
                        ext = os.path.splitext(up.filename)[1].lower()
                        if ext not in IMAGE_EXTS:
                            flash("Pictures must be PNG or JPG.", "err")
                            continue
                        for e2 in IMAGE_EXTS:
                            pth = os.path.join(upload_dir(), key + e2)
                            if os.path.exists(pth):
                                os.remove(pth)
                        up.save(os.path.join(upload_dir(), key + ext))
                    continue
                if kind == "check":
                    set_setting(key, "1" if request.form.get(key) else "0")
                elif kind == "secret":
                    v = request.form.get(key, "").strip()
                    if v:
                        set_setting(key, v)
                else:
                    set_setting(key, request.form.get(key, "").strip())
        commit()
        flash("Settings saved.", "ok")
        return redirect(url_for("core.settings_page"))
    return render_template("settings.html", groups=SETTING_FIELDS, s=settings(),
                           images={k: bool(image_path(k)) for k in ("logo", "terms")})


IMAGE_EXTS = (".png", ".jpg", ".jpeg")


def upload_dir():
    d = os.path.join(current_app.config["DATA_DIR"], "uploads")
    os.makedirs(d, exist_ok=True)
    return d


def save_image(key, fs):
    ext = os.path.splitext(fs.filename)[1].lower()
    if ext not in IMAGE_EXTS:
        raise ValueError("Pictures must be PNG or JPG.")
    for e2 in IMAGE_EXTS:
        pth = os.path.join(upload_dir(), key + e2)
        if os.path.exists(pth):
            os.remove(pth)
    dest = os.path.join(upload_dir(), key + ext)
    fs.save(dest)
    try:  # keep logos small so PDFs stay light for WhatsApp
        from PIL import Image
        with Image.open(dest) as im:
            if max(im.size) > 900:
                im.thumbnail((900, 900))
                im.save(dest)
    except Exception:  # noqa: BLE001 - an odd image is still usable as uploaded
        pass


def image_path(key):
    for ext in IMAGE_EXTS:
        p = os.path.join(upload_dir(), key + ext)
        if os.path.exists(p):
            return p
    return None


@bp.route("/settings/image/<key>")
def settings_image(key):
    p = image_path(key) if key in ("logo", "terms") else None
    if not p:
        abort(404)
    return send_file(p)


# ---- users --------------------------------------------------------------------------
@bp.route("/users")
def users():
    rows = q("""SELECT u.*, r.name AS rep_name, ro.name AS role_label FROM users u LEFT JOIN reps r ON r.id = u.rep_id
                LEFT JOIN roles ro ON ro.id = u.role_id ORDER BY u.active DESC, u.name""")
    return render_template("users.html", users=rows)


def _legacy_role(perms):
    """Keeps the old role column filled (the database still requires one of these values)."""
    if "admin.users" in perms and "admin.settings" in perms:
        return "admin"
    if "scope.own_customers" in perms:
        return "rep"
    if "warehouse.view" in perms and not perms & {"customers.view", "invoices.view", "payments.view", "purchases.view"}:
        return "store"
    return "accounts"


@bp.route("/users/new", methods=["GET", "POST"])
@bp.route("/users/<int:uid>/edit", methods=["GET", "POST"])
def user_form(uid=None):
    import json
    u = q("SELECT * FROM users WHERE id = ?", (uid,), one=True) if uid else None
    if uid and not u:
        abort(404)
    reps = q("SELECT * FROM reps WHERE active = 1 ORDER BY name")
    all_roles = q("SELECT * FROM roles ORDER BY sort, name")
    if request.method == "POST":
        f = request.form
        role = q("SELECT * FROM roles WHERE id = ?", (f.get("role_id", type=int),), one=True)
        perms = set(json.loads(role["perms"])) if role else set()
        rep_id = int(f["rep_id"]) if f.get("rep_id") else None
        pw = f.get("password", "")
        if not role:
            flash("Pick a role.", "err")
        elif "scope.own_customers" in perms and not rep_id:
            flash("This role only sees the rep's own customers, so the login must be linked to a sales rep.", "err")
        elif (not u or pw) and len(pw) < 8:
            flash("Password must be at least 8 characters.", "err")
        elif u and u["id"] == g.user["id"] and ("admin.users" not in perms or not f.get("active")):
            flash("You can't remove your own access to Users & roles.", "err")
        else:
            try:
                legacy = _legacy_role(perms)
                if u:
                    x("UPDATE users SET username=?, name=?, role=?, role_id=?, rep_id=?, active=? WHERE id=?",
                      (f["username"].strip(), f["name"].strip(), legacy, role["id"], rep_id, 1 if f.get("active") else 0, uid))
                    if pw:
                        x("UPDATE users SET password_hash=? WHERE id=?", (generate_password_hash(pw), uid))
                else:
                    x("INSERT INTO users (username, name, password_hash, role, role_id, rep_id, created_at) VALUES (?,?,?,?,?,?,?)",
                      (f["username"].strip(), f["name"].strip(), generate_password_hash(pw), legacy, role["id"], rep_id, now()))
                commit()
                flash("User saved.", "ok")
                return redirect(url_for("core.users"))
            except Exception:
                flash("That username is already taken.", "err")
    cur_role = (u["role_id"] if u else None) or request.form.get("role_id", type=int)
    return render_template("user_form.html", u=u, reps=reps, roles=all_roles, cur_role=cur_role,
                           role_perms={r["id"]: json.loads(r["perms"]) for r in all_roles})


@bp.route("/users/roles")
def roles():
    from .perms import roles_page
    return roles_page()


@bp.route("/users/roles/new", methods=["GET", "POST"])
@bp.route("/users/roles/<int:rid>/edit", methods=["GET", "POST"])
def role_form(rid=None):
    from .perms import role_form as rf
    return rf(rid)


@bp.route("/users/roles/<int:rid>/delete", methods=["POST"])
def role_delete(rid):
    from .perms import role_delete as rd
    return rd(rid)


@bp.route("/account/password", methods=["GET", "POST"])
def change_password():
    if request.method == "POST":
        f = request.form
        if not check_password_hash(g.user["password_hash"], f.get("current", "")):
            flash("Current password is wrong.", "err")
        elif len(f.get("new", "")) < 8 or f["new"] != f.get("new2"):
            flash("New password must be at least 8 characters and match.", "err")
        else:
            h = generate_password_hash(f["new"])
            x("UPDATE users SET password_hash = ? WHERE id = ?", (h, g.user["id"]))
            commit()
            session["pw"] = h[-12:]
            flash("Password changed.", "ok")
            return redirect(url_for("core.dashboard"))
    return render_template("password.html")


# ---- sales reps ------------------------------------------------------------------------
@bp.route("/reps", methods=["GET", "POST"])
def reps():
    if request.method == "POST":
        f = request.form
        rid = f.get("id")
        vals = (f["code"].strip().upper(), f["name"].strip(), f.get("phone", "").strip(), 1 if f.get("active") else 0)
        if rid:
            x("UPDATE reps SET code=?, name=?, phone=?, active=? WHERE id=?", vals + (int(rid),))
        else:
            x("INSERT INTO reps (code, name, phone, active) VALUES (?,?,?,?)", vals)
        commit()
        flash("Sales rep saved.", "ok")
        return redirect(url_for("core.reps"))
    rows = q("""SELECT r.*, (SELECT COUNT(*) FROM customers c WHERE c.rep_id = r.id) AS customers
                FROM reps r ORDER BY r.active DESC, r.name""")
    return render_template("reps.html", reps=rows, edit=request.args.get("edit", type=int))


@bp.route("/audit")
def audit_log():
    """Admin-only: who changed what, newest first."""
    who = request.args.get("user", "").strip()
    where, args = " WHERE 1 = 1", []
    if who:
        where += " AND user_name LIKE ?"
        args.append(f"%{who}%")
    rows = q(f"SELECT * FROM audit_log {where} ORDER BY id DESC LIMIT 500", args)
    return render_template("audit.html", rows=rows, who=who)
