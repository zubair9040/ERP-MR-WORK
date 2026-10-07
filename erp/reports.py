"""Reports, month-end statements and the WhatsApp message log."""
import csv
import io
from datetime import date, timedelta

from flask import Blueprint, Response, flash, redirect, render_template, request, url_for

from . import notify
from .auth import co_filter, is_rep, rep_filter
from .hr import allowed as hr_allowed
from .db import fmt, nice_date, parse_date, q, settings, today
from .export import table_response
from .ledger import BUCKETS, aging as aging_calc, customers_with_balance, open_items

bp = Blueprint("reports", __name__, url_prefix="/reports")


def _period():
    t = date.today()
    start = parse_date(request.args.get("from")) or t.replace(day=1).isoformat()
    end = parse_date(request.args.get("to")) or t.isoformat()
    return start, end


def _table(title, headers, rows, money_cols, totals=None, filters=None, note=""):
    """Renders a report table, or a CSV download with ?csv=1."""
    if request.args.get("export") in ("xlsx", "pdf"):
        sub = ""
        if "dates" in (filters or []):
            s_, e_ = _period()
            sub = f"{nice_date(s_)} to {nice_date(e_)}"
        return table_response(request.args["export"], title, headers, rows, money_cols, totals, sub)
    if request.args.get("csv"):
        buf = io.StringIO()
        w = csv.writer(buf)
        w.writerow(headers)
        for r in rows:
            w.writerow([(r[i] / 100 if i in money_cols and isinstance(r[i], int) else r[i]) for i in range(len(headers))])
        if totals:
            w.writerow([(t / 100 if i in money_cols and isinstance(t, int) else t) for i, t in enumerate(totals)])
        name = title.lower().replace(" ", "_") + ".csv"
        return Response(buf.getvalue(), mimetype="text/csv",
                        headers={"Content-Disposition": f"attachment; filename={name}"})
    extra = {}
    f_ = filters or []
    if "reps" in f_:
        extra["reps"] = q("SELECT * FROM reps ORDER BY code")
    if "city" in f_:
        extra["cities"] = [r["city"] for r in q("SELECT DISTINCT city FROM customers WHERE city != '' ORDER BY city COLLATE NOCASE")]
    if "group" in f_:
        extra["groups"] = [r["grp"] for r in q("SELECT DISTINCT grp FROM items WHERE grp != '' ORDER BY grp COLLATE NOCASE")]
    if "cust" in f_:
        extra["cust_names"] = [r["name"] for r in q("SELECT name FROM customers WHERE active = 1 ORDER BY name COLLATE NOCASE LIMIT 2000")]
    if "item" in f_:
        extra["item_codes"] = [r["code"] for r in q("SELECT code FROM items WHERE kind = 'item' AND active = 1 AND code != '' ORDER BY code")]
    return render_template("report.html", title=title, headers=headers, rows=rows, money_cols=money_cols,
                           totals=totals, filters=filters or [], note=note, scales=AGING_SCALES, sorts=SORTS, **extra)


CUST_F = ["cust", "reps", "city"]   # customer filter boxes
ITEM_F = ["item", "group"]          # item filter boxes


def _cust_where(alias="c"):
    """Customer filters from the report's filter bar: name / code, ticked reps, ticked cities."""
    a = request.args
    w, args = "", {}
    if a.get("cust", "").strip():
        w += f" AND ({alias}.name LIKE :f_cust OR {alias}.code LIKE :f_cust)"
        args["f_cust"] = f"%{a['cust'].strip()}%"
    reps = [int(v) for v in a.getlist("rep") if v.isdigit()]
    if reps and not is_rep():
        w += f" AND {alias}.rep_id IN ({','.join(str(v) for v in reps)})"
    cities = [v for v in a.getlist("city") if v]
    for n, v in enumerate(cities):
        args[f"f_city{n}"] = v
    if cities:
        w += f" AND {alias}.city IN ({','.join(f':f_city{n}' for n in range(len(cities)))})"
    return w, args


def _item_where(line="l", item="it"):
    """Item filters: code / name / description text, ticked item groups."""
    a = request.args
    w, args = "", {}
    if a.get("item", "").strip():
        w += f" AND ({line}.code LIKE :f_item OR {line}.description LIKE :f_item OR {item}.name LIKE :f_item)"
        args["f_item"] = f"%{a['item'].strip()}%"
    groups = [v for v in a.getlist("group") if v]
    for n, v in enumerate(groups):
        args[f"f_grp{n}"] = "" if v == "(none)" else v
    if groups:
        w += f" AND COALESCE({item}.grp, '') IN ({','.join(f':f_grp{n}' for n in range(len(groups)))})"
    return w, args


def _scope(alias="c"):
    where, args = rep_filter(alias)
    w2, a2 = _cust_where(alias)
    return where + w2, {**args, **a2}


@bp.route("/")
def index():
    return render_template("reports.html")


@bp.route("/sales")
def sales():
    start, end = _period()
    by = request.args.get("by", "rep")
    where, args = _scope()
    args.update(a=start, b=end)
    iw, ia = _item_where()
    args.update(ia)
    flt = ["dates", "by"] + CUST_F + ITEM_F
    if by in ("item", "group") or iw:
        # from the invoice lines, so item / group filters work for every grouping
        key = {"item": "COALESCE(NULLIF(l.code, ''), it.name, l.description)", "group": "COALESCE(NULLIF(it.grp, ''), '(no group)')",
               "rep": "COALESCE(r.code || ' · ' || r.name, '(no rep)')", "customer": "c.name"}.get(by, "c.name")
        rows = q(f"""SELECT {key} AS name, MAX(COALESCE(it.name, l.description)) AS descr, SUM(CASE WHEN l.kind = 'item' THEN COALESCE(l.qty, 0) ELSE 0 END) AS qty,
                            SUM(l.amount) AS amt, COUNT(DISTINCT i.id) AS n, COUNT(DISTINCT i.customer_id) AS nc
                     FROM invoice_lines l JOIN invoices i ON i.id = l.invoice_id JOIN customers c ON c.id = i.customer_id
                     LEFT JOIN items it ON it.id = l.item_id LEFT JOIN reps r ON r.id = i.rep_id
                     WHERE i.void = 0 AND l.kind != 'subtotal' AND i.date BETWEEN :a AND :b {where} {iw}
                     GROUP BY {key} ORDER BY amt DESC""", args)
        head = {"item": "Item", "group": "Item group", "rep": "Rep", "customer": "Customer"}.get(by, "Customer")
        cols = [head] + (["Description"] if by == "item" else []) + ["Qty", "Invoices", "Customers", "Amount (before tax)"]
        data = [[r["name"]] + ([r["descr"] if r["descr"] != r["name"] else ""] if by == "item" else []) +
                [f"{r['qty']:g}", r["n"], r["nc"], r["amt"]] for r in rows]
        k = len(cols) - 1
        return _table(f"Sales by {head.lower()}", cols, data, {k},
                      ["Total"] + ([""] if by == "item" else []) + [f"{sum(r['qty'] for r in rows):g}", "", "", sum(r["amt"] for r in rows)], flt,
                      "Amounts are before sales tax." + (" Filtered by item / group." if iw else ""))
    key = {"rep": "COALESCE(r.code || ' · ' || r.name, '(no rep)')", "customer": "c.name"}.get(by, "c.name")
    rows = q(f"""SELECT {key} AS name, COUNT(*) AS n, SUM(i.subtotal - i.discount) AS net, SUM(i.tax) AS tax, SUM(i.total) AS total
                 FROM invoices i JOIN customers c ON c.id = i.customer_id LEFT JOIN reps r ON r.id = i.rep_id
                 WHERE i.void = 0 AND i.date BETWEEN :a AND :b {where}
                 GROUP BY {key} ORDER BY total DESC""", args)
    data = [[r["name"], r["n"], r["net"], r["tax"], r["total"]] for r in rows]
    tot = ["Total", sum(r["n"] for r in rows), sum(r["net"] for r in rows), sum(r["tax"] for r in rows),
           sum(r["total"] for r in rows)]
    title = "Sales by rep" if by == "rep" else "Sales by customer"
    return _table(title, ["Rep" if by == "rep" else "Customer", "Invoices", "Net sales", "Tax", "Total"], data,
                  {2, 3, 4}, tot, flt)


@bp.route("/payments")
def payments():
    start, end = _period()
    where, args = _scope()
    args.update(a=start, b=end)
    by = request.args.get("by", "method")
    key = {"method": "p.method", "day": "p.date", "customer": "c.name"}.get(by, "p.method")
    rows = q(f"""SELECT {key} AS name, COUNT(*) AS n, SUM(p.amount) AS amt FROM payments p
                 JOIN customers c ON c.id = p.customer_id
                 WHERE p.void = 0 AND p.date BETWEEN :a AND :b {where} GROUP BY {key} ORDER BY {key}""", args)
    label = {"method": "Method", "day": "Date", "customer": "Customer"}.get(by, "Method")
    return _table("Payments received", [label, "Payments", "Amount"], [[r["name"], r["n"], r["amt"]] for r in rows],
                  {2}, ["Total", sum(r["n"] for r in rows), sum(r["amt"] for r in rows)], ["dates", "pby"] + CUST_F)


@bp.route("/balances")
def balances():
    as_of = parse_date(request.args.get("as_of")) or today()
    where, args = _scope()
    rows = [c for c in customers_with_balance(as_of, where, args) if c["balance"]]
    rows = _sorted(rows)
    data = [[c["code"] or "", c["name"], c["city"] or "", c["rep_code"] or "", c["whatsapp"] or "", c["balance"]] for c in rows]
    return _table("Customer balances", ["Code", "Customer", "City", "Rep", "WhatsApp", "Balance"], data, {5},
                  ["Total", "", "", "", "", sum(c["balance"] for c in rows)], ["as_of", "sort"] + CUST_F)


SORTS = [("name", "Name A → Z"), ("name_desc", "Name Z → A"), ("bal_desc", "Balance: highest first"), ("bal_asc", "Balance: lowest first"),
         ("code", "Customer code")]


def _sorted(rows, bal="balance", name="name"):
    k = request.args.get("sort", "name")
    if k in ("bal_desc", "bal_asc"):
        return sorted(rows, key=lambda r: r[bal], reverse=k == "bal_desc")
    if k == "code":
        return sorted(rows, key=lambda r: (r["code"] or ""))
    return sorted(rows, key=lambda r: (r[name] or "").lower(), reverse=k == "name_desc")


def _scale(n):
    out, lo = [], 1
    for hi in range(30, n + 1, 30):
        out.append((hi, f"{lo}-{hi}"))
        lo = hi + 1
    return out + [(None, f"{n}+")]


AGING_SCALES = {str(n): _scale(n) for n in (30, 60, 90, 120, 150, 180)}


def _aging_opts():
    a = request.args
    scale = a.get("scale") if a.get("scale") in AGING_SCALES else "180"
    basis = "due" if a.get("basis") == "due" else "invoice"  # days are counted from the invoice date unless asked otherwise
    try:
        min_days = max(0, int(a.get("min") or 0))
    except ValueError:
        min_days = 0
    buckets = ["Current"] + [lbl for _, lbl in AGING_SCALES[scale]]
    return scale, basis, min_days, buckets


def bucket_of(days, scale):
    if days <= 0:
        return "Current"
    for limit, label in AGING_SCALES[scale]:
        if limit is None or days <= limit:
            return label
    return AGING_SCALES[scale][-1][1]


def _age(r, basis):
    return r["age_inv"] if basis == "invoice" else r["days"]


@bp.route("/aging")
def aging():
    where, args = _scope()
    scale, basis, min_days, buckets = _aging_opts()
    by_c = {}
    for r in _open_rows(where, args, with_credit=True):
        c = r["c"]
        e = by_c.setdefault(c["id"], {"c": c, "b": dict.fromkeys(buckets, 0), "oldest": 0})
        age = _age(r, basis)
        e["b"][bucket_of(age, scale)] += r["open"]
        if r["open"] > 0:
            e["oldest"] = max(e["oldest"], age)
    rows = [e for e in by_c.values() if sum(e["b"].values()) and e["oldest"] >= min_days]
    rows.sort(key=lambda e: -sum(e["b"].values()))
    data = [[e["c"]["name"], e["c"]["rep_code"] or ""] + [e["b"][k] for k in buckets] + [sum(e["b"].values()), e["oldest"]]
            for e in rows]
    n = len(buckets)
    totals = ["Total", ""] + [sum(e["b"][k] for e in rows) for k in buckets] + [sum(d[2 + n] for d in data), ""]
    return _table("Aging (overdue by days)", ["Customer", "Rep"] + buckets + ["Total", "Oldest (days)"], data, set(range(2, 3 + n)),
                  totals, ["aging"] + CUST_F,
                  f"Days are counted from each bill's {'invoice date' if basis == 'invoice' else 'due date'}. "
                  "Payments are applied to the oldest bills first." + (f" Showing customers with bills {min_days}+ days old." if min_days else ""))


# ---- month-end -----------------------------------------------------------------------------
def _month_bounds(m):
    try:
        y, mo = map(int, m.split("-"))
        start = date(y, mo, 1)
    except (ValueError, AttributeError):
        start = (date.today().replace(day=1) - timedelta(days=1)).replace(day=1)
    end = (start.replace(day=28) + timedelta(days=4)).replace(day=1) - timedelta(days=1)
    return start.isoformat(), min(end, date.today()).isoformat() if start <= date.today() else end.isoformat()


@bp.route("/month-end", methods=["GET", "POST"])
def month_end():
    month = request.values.get("month") or (date.today().replace(day=1) - timedelta(days=1)).strftime("%Y-%m")
    start, end = _month_bounds(month)
    month = start[:7]
    period = f"{start}..{end}"
    where, args = rep_filter()
    custs = [c for c in customers_with_balance(end, where + " AND c.active = 1", args) if c["balance"] > 0]

    src = request.values
    type_choice = src.get("type", "customer")
    aging_vals = src.getlist("aging")
    opts = {"aging": (aging_vals[-1] if aging_vals else "1") == "1", "details": src.get("details") == "1"}

    def mode_for(c):
        if type_choice in ("period", "open"):
            return type_choice
        return "open" if c["statement_mode"] == "open" else "period"

    action = src.get("action", "")
    if request.method == "POST" and action == "send":
        chosen = {int(i) for i in request.form.getlist("cid")}
        ok_n, fail = 0, []
        for c in custs:
            if c["id"] in chosen:
                for ok, msg in notify.send_by(c, lambda: notify.send_statement(c["id"], start, end, None, mode_for(c), opts),
                                              lambda: notify.email_statement(c["id"], start, end, None, mode_for(c), opts)):
                    if ok:
                        ok_n += 1
                    else:
                        fail.append(msg)
        flash(f"{ok_n} statement(s) processed for {month}.", "ok")
        for m in fail[:10]:
            flash(m, "err")
        if len(fail) > 10:
            flash(f"...and {len(fail) - 10} more failures. See the WhatsApp log.", "err")
        return redirect(url_for("reports.month_end", month=month, type=type_choice, aging="1" if opts["aging"] else "0",
                                details="1" if opts["details"] else ""))

    if action == "all_pdf":
        chosen = {int(i) for i in src.getlist("cid")} or {c["id"] for c in custs}
        from pypdf import PdfWriter
        w = PdfWriter()
        for c in custs:
            if c["id"] in chosen:
                w.append(notify.statement_pdf(c["id"], start, end, mode_for(c), opts))
        buf = io.BytesIO()
        w.write(buf)
        return Response(buf.getvalue(), mimetype="application/pdf",
                        headers={"Content-Disposition": f'attachment; filename="Statements_{month}.pdf"'})

    rows = [{"c": c, "wa": notify.normalize(c["whatsapp"]), "sent": notify.last_sent("statement", c["id"], period),
             "mode": mode_for(c)} for c in custs]
    if src.get("export") in ("xlsx", "pdf"):
        data = [[r["c"]["name"], r["c"]["rep_code"] or "", r["wa"] or "", "Unpaid bills only" if r["mode"] == "open" else "All activity",
                 r["c"]["balance"], r["sent"] or ""] for r in rows]
        return table_response(src["export"], f"Month-end {month}", ["Customer", "Rep", "WhatsApp", "Statement type",
                              f"Balance at {nice_date(end)}", "Sent"], data, {4},
                              ["Total", "", "", "", sum(r["c"]["balance"] for r in rows), ""],
                              f"Statement period {nice_date(start)} to {nice_date(end)}")
    return render_template("month_end.html", rows=rows, month=month, start=start, end=end, type_choice=type_choice,
                           opts=opts, total=sum(c["balance"] for c in custs))


@bp.route("/messages")
def messages():
    where, args = rep_filter()
    from .perms import has
    sup = has("purchases.view") or has("supplier_payments.view")
    if sup:  # supplier messages have no customer: keep them when the customer filter would drop them
        where = f" AND (m.supplier_id IS NOT NULL OR (1 = 1 {where}))"
    status = request.args.get("status", "")
    if status in ("sent", "failed", "test"):
        where += " AND m.status = :st"
        args["st"] = status
    rows = q(f"""SELECT m.*, COALESCE(c.name, sp.name || ' (supplier)', e.name || ' (payslip)') AS customer FROM messages m
                 LEFT JOIN customers c ON c.id = m.customer_id LEFT JOIN employees e ON m.kind = 'payslip' AND e.id = m.ref_id
                 LEFT JOIN suppliers sp ON sp.id = m.supplier_id
                 WHERE 1 = 1 {where} AND (m.kind != 'payslip' OR :hr = 1) AND (m.supplier_id IS NULL OR :sup = 1)
                 ORDER BY m.id DESC LIMIT 500""", {**args, "hr": 1 if hr_allowed() else 0, "sup": 1 if sup else 0})
    return render_template("messages.html", rows=rows)


def pnl_figures(start, end):
    """Profit & loss numbers for a period (used by the P&L report and the dashboard)."""
    from .auth import current_company
    from .hr import salary_expense
    from .stock import levels
    args = {"a": start, "b": end}
    co = current_company()
    cf = lambda col: f" AND {col} = :co" if co else ""  # noqa: E731
    if co:
        args["co"] = co
    sales = q(f"SELECT COALESCE(SUM(subtotal - discount), 0) AS s FROM invoices WHERE void = 0 AND date BETWEEN :a AND :b {cf('company_id')}",
              args, one=True)["s"]
    returns = q(f"SELECT COALESCE(SUM(subtotal), 0) AS s FROM credit_notes WHERE void = 0 AND date BETWEEN :a AND :b {cf('company_id')}",
                args, one=True)["s"]
    lv = levels()
    sold = q(f"""SELECT il.item_id, SUM(COALESCE(il.qty, 0)) AS qty FROM invoice_lines il JOIN invoices i ON i.id = il.invoice_id
                WHERE i.void = 0 AND il.kind = 'item' AND il.item_id IS NOT NULL AND i.date BETWEEN :a AND :b {cf('i.company_id')}
                GROUP BY il.item_id""", args)
    back = q(f"""SELECT cl.item_id, SUM(COALESCE(cl.qty, 0)) AS qty FROM credit_note_lines cl JOIN credit_notes n ON n.id = cl.credit_note_id
                WHERE n.void = 0 AND cl.item_id IS NOT NULL AND n.date BETWEEN :a AND :b {cf('n.company_id')} GROUP BY cl.item_id""", args)
    cogs = sum(int(round(r["qty"] * lv[r["item_id"]]["avg_cost"])) for r in sold if r["item_id"] in lv)
    cogs -= sum(int(round(r["qty"] * lv[r["item_id"]]["avg_cost"])) for r in back if r["item_id"] in lv)
    exp = [dict(e) for e in q(f"""SELECT category, SUM(amount) AS s FROM expenses WHERE void = 0 AND date BETWEEN :a AND :b
                                  {cf('company_id')} GROUP BY category ORDER BY s DESC""", args)]
    salaries = salary_expense(start, end) if (not co or str(co) == settings().get("salary_company")) else 0
    if salaries:
        exp.insert(0, {"category": "Salaries & wages", "s": salaries})
    net_sales = sales - returns
    gross = net_sales - cogs
    total_exp = sum(e["s"] for e in exp)
    return {"sales": sales, "returns": returns, "net_sales": net_sales, "cogs": cogs, "gross": gross, "exp": exp,
            "total_exp": total_exp, "net": gross - total_exp, "salaries": salaries,
            "margin": (gross * 100 / net_sales) if net_sales else 0}


# ---- more QuickBooks-style reports ---------------------------------------------------------
def _open_rows(where, args, with_credit=False):
    """Every unpaid invoice (and unpaid opening balance) for the customers in scope.
    days = days past the due date; age_inv = days since the invoice date."""
    today_d = date.today()
    out = []
    for c in customers_with_balance(None, where, args):
        if c["balance"] <= 0:
            continue
        open_by_inv, opening_left, credit = open_items(c["id"])
        if opening_left:
            od = c["opening_date"]
            age = (today_d - date.fromisoformat(od)).days if od else 999
            out.append({"c": c, "type": "Opening balance", "date": od or "", "num": "", "due": od or "",
                        "days": age, "age_inv": age, "open": opening_left, "total": opening_left})
        if with_credit and credit:
            out.append({"c": c, "type": "Unapplied payment", "date": today_d.isoformat(), "num": "", "due": "", "days": 0,
                        "age_inv": 0, "open": -credit, "total": -credit})
        ids = [k for k, v in open_by_inv.items() if v]
        if ids:
            for i in q(f"SELECT id, number, date, due_date, total FROM invoices WHERE id IN ({','.join('?' * len(ids))}) "
                       "ORDER BY date, number", ids):
                due = i["due_date"] or i["date"]
                out.append({"c": c, "type": "Invoice", "date": i["date"], "num": i["number"], "due": due,
                            "days": (today_d - date.fromisoformat(due)).days, "age_inv": (today_d - date.fromisoformat(i["date"])).days,
                            "open": open_by_inv[i["id"]], "total": i["total"]})
    return out


@bp.route("/aging-detail")
def aging_detail():
    where, args = _scope()
    scale, basis, min_days, buckets = _aging_opts()
    rows = [r for r in _open_rows(where, args) if _age(r, basis) >= min_days]
    order = {b: k for k, b in enumerate(buckets)}
    rows.sort(key=lambda r: (-order[bucket_of(_age(r, basis), scale)], -_age(r, basis), r["c"]["name"].lower()))
    data = [[bucket_of(_age(r, basis), scale), r["c"]["name"], r["type"], nice_date(r["date"]), r["num"], nice_date(r["due"]),
             r["age_inv"], max(r["days"], 0), r["open"]] for r in rows]
    return _table("A/R aging detail", ["Aging", "Customer", "Type", "Date", "Num", "Due date", "Days since bill", "Days overdue",
                                       "Open balance"], data, {8}, ["Total", f"{len(data)} bills", "", "", "", "", "", "",
                                                                    sum(r["open"] for r in rows)], ["aging"] + CUST_F,
                  "Exact days for every bill: days since the invoice date and days past the due date. "
                  f"The Aging column uses the {'invoice date' if basis == 'invoice' else 'due date'}.")


@bp.route("/open-invoices")
def open_invoices():
    """All customers' unpaid bills, grouped by customer with a subtotal for each."""
    where, args = _scope()
    a = request.args
    try:
        min_days = max(0, int(a.get("min") or 0))
    except ValueError:
        min_days = 0
    rows = [r for r in _open_rows(where, args) if r["age_inv"] >= min_days]
    rows.sort(key=lambda r: (r["c"]["name"].lower(), r["date"]))
    data, cur_c, sub_open, sub_n = [], None, 0, 0

    def flush():
        if cur_c is not None and sub_n > 1:
            data.append([f"   Total {cur_c}", "", "", "", "", "", None, sub_open])

    for r in rows:
        if r["c"]["name"] != cur_c:
            flush()
            cur_c, sub_open, sub_n = r["c"]["name"], 0, 0
        sub_open += r["open"]
        sub_n += 1
        data.append([r["c"]["name"], r["type"], nice_date(r["date"]), r["num"], nice_date(r["due"]), r["age_inv"], r["total"], r["open"]])
    flush()
    custs = len({r["c"]["id"] for r in rows})
    return _table("Unpaid bills - all customers", ["Customer", "Type", "Date", "Num", "Due date", "Days old", "Bill amount", "Open balance"],
                  data, {6, 7}, [f"Total · {custs} customers", f"{len(rows)} bills", "", "", "", "", sum(r["total"] for r in rows),
                                 sum(r["open"] for r in rows)], ["min"] + CUST_F,
                  "Every unpaid bill for every customer. Payments are applied to the oldest bills first.")


@bp.route("/collections")
def collections():
    where, args = _scope()
    rows = [r for r in _open_rows(where, args) if r["days"] > 0]
    rows.sort(key=lambda r: (r["c"]["name"].lower(), r["date"]))
    data = [[r["c"]["name"], r["c"]["whatsapp"] or r["c"]["phone"] or "", r["c"]["rep_code"] or "", nice_date(r["date"]),
             r["num"], nice_date(r["due"]), r["days"], r["open"]] for r in rows]
    return _table("Payments due (overdue bills)", ["Customer", "Phone", "Rep", "Date", "Num", "Due date", "Days overdue",
                  "Open balance"], data, {7}, ["Total", "", "", "", "", "", "", sum(r["open"] for r in rows)], CUST_F)


@bp.route("/transactions")
def transactions():
    start, end = _period()
    where, args = _scope()
    args.update(a=start, b=end)
    rows = q(f"""SELECT * FROM (
                   SELECT c.name AS customer, 'Invoice' AS type, i.date, i.number AS num, i.via AS memo, i.total AS amount, i.void
                   FROM invoices i JOIN customers c ON c.id = i.customer_id WHERE i.date BETWEEN :a AND :b {where}
                   UNION ALL
                   SELECT c.name, 'Payment', p.date, p.number, p.method || ' ' || p.reference, -p.amount, p.void
                   FROM payments p JOIN customers c ON c.id = p.customer_id WHERE p.date BETWEEN :a AND :b {where})
                 ORDER BY customer COLLATE NOCASE, date, type""", args)
    data = [[r["customer"], r["type"] + (" (void)" if r["void"] else ""), nice_date(r["date"]), r["num"], r["memo"] or "",
             0 if r["void"] else r["amount"]] for r in rows]
    return _table("Transaction list by customer", ["Customer", "Type", "Date", "Num", "Memo", "Amount"], data, {5},
                  ["Net", "", "", "", "", sum(d[5] for d in data)], ["dates"] + CUST_F)


@bp.route("/sales-detail")
def sales_detail():
    start, end = _period()
    where, args = _scope()
    iw, ia = _item_where()
    args.update(a=start, b=end, **ia)
    by = request.args.get("by", "customer")
    order = {"customer": "c.name COLLATE NOCASE", "item": "l.code", "rep": "r.code",
             "group": "COALESCE(NULLIF(it.grp, ''), 'zzz') COLLATE NOCASE, l.code"}.get(by, "c.name")
    rows = q(f"""SELECT i.date, i.number, c.name AS customer, r.code AS rep, l.code, l.description, l.qty, l.unit, l.rate,
                        l.percent, l.amount, l.kind, COALESCE(NULLIF(it.grp, ''), '(no group)') AS grp
                 FROM invoice_lines l JOIN invoices i ON i.id = l.invoice_id JOIN customers c ON c.id = i.customer_id
                 LEFT JOIN reps r ON r.id = i.rep_id LEFT JOIN items it ON it.id = l.item_id
                 WHERE i.void = 0 AND l.kind != 'subtotal' AND i.date BETWEEN :a AND :b {where} {iw}
                 ORDER BY {order}, i.date, i.number, l.sort""", args)
    data = [[{"customer": x["customer"], "item": x["code"] or "(no code)", "rep": x["rep"] or "(no rep)", "group": x["grp"]}[by if by in ("customer", "item", "rep", "group") else "customer"],
             nice_date(x["date"]), x["number"], x["customer"] if by != "customer" else (x["rep"] or ""), x["description"],
             "" if x["qty"] is None else f"{x['qty']:g} {x['unit'] or ''}".strip(),
             f"{x['percent']:g}%" if x["percent"] is not None else fmt(x["rate"]), x["amount"]] for x in rows]
    title = {"customer": "Sales by customer detail", "item": "Sales by item detail", "rep": "Sales by rep detail",
             "group": "Sales by item group detail"}.get(by, "Sales detail")
    head = {"customer": "Customer", "item": "Item code", "rep": "Rep", "group": "Item group"}.get(by, "Customer")
    qty_total = sum((x["qty"] or 0) for x in rows if x["kind"] == "item")
    # subtotal rows per group (customer / item / rep / group)
    out, cur_k, sub_amt, sub_qty, sub_n = [], None, 0, 0, 0

    def flush():
        if cur_k is not None and sub_n > 1:
            out.append([f"   Total {cur_k}", "", "", "", "", f"{sub_qty:g}", "", sub_amt])
    for d, x in zip(data, rows):
        if d[0] != cur_k:
            flush()
            cur_k, sub_amt, sub_qty, sub_n = d[0], 0, 0, 0
        sub_amt += x["amount"]
        sub_qty += (x["qty"] or 0) if x["kind"] == "item" else 0
        sub_n += 1
        out.append(d)
    flush()
    return _table(title, [head, "Date", "Num", "Rep" if by == "customer" else "Customer", "Description", "Qty", "Price", "Amount"],
                  out, {7}, ["Total", f"{len(rows)} lines", "", "", "", f"{qty_total:g}", "", sum(x["amount"] for x in rows)],
                  ["dates", "dby"] + CUST_F + ITEM_F, "Every invoice line, with a subtotal for each " + head.lower() + ".")


@bp.route("/phone-list")
def phone_list():
    where, args = rep_filter()
    rows = customers_with_balance(None, where + " AND c.active = 1", args)
    return _table("Customer phone list", ["Customer", "WhatsApp", "Phone", "Rep"],
                  [[c["name"], c["whatsapp"] or "", c["phone"] or "", c["rep_code"] or ""] for c in rows], set())


@bp.route("/contact-list")
def contact_list():
    where, args = rep_filter()
    rows = customers_with_balance(None, where + " AND c.active = 1", args)
    return _table("Customer contact list", ["Customer", "Contact", "Address", "WhatsApp", "Phone", "Rep", "Terms", "Balance"],
                  [[c["name"], c["contact"] or "", (c["address"] or "").replace("\n", ", "), c["whatsapp"] or "", c["phone"] or "",
                    c["rep_code"] or "", f"{c['terms_days']} days", c["balance"]] for c in rows], {7},
                  ["Total", "", "", "", "", "", "", sum(c["balance"] for c in rows)])


@bp.route("/item-prices")
def item_prices():
    rows = q("SELECT * FROM items WHERE active = 1 AND kind IN ('item', 'service') ORDER BY code, name")
    return _table("Item price list", ["Item code", "Name", "Description", "U/M", "Price"],
                  [[i["code"], i["name"], i["description"], i["unit"], i["price"]] for i in rows], {4})


# ---- accounts, purchasing and inventory reports -------------------------------------------
def _staff():
    if is_rep():
        from flask import abort
        abort(403)


@bp.route("/profit-loss")
def profit_loss():
    _staff()
    start, end = _period()
    F = pnl_figures(start, end)
    sales, returns, net_sales, cogs, gross, exp, total_exp, net = (F[k] for k in (
        "sales", "returns", "net_sales", "cogs", "gross", "exp", "total_exp", "net"))
    rows = [["Sales (before tax)", sales], ["Less: returns", -returns], ["Net sales", net_sales],
            ["Cost of goods sold", -cogs], ["Gross profit", gross]]
    rows += [[f"   {e['category']}", -e["s"]] for e in exp]
    rows += [["Total expenses", -total_exp], ["NET PROFIT", net]]
    if request.args.get("export") in ("xlsx", "pdf"):
        return table_response(request.args["export"], "Profit and loss", ["", "Amount"], rows, {1}, None,
                              f"{nice_date(start)} to {nice_date(end)}")
    return render_template("pnl.html", sales=sales, returns=returns, net_sales=net_sales, cogs=cogs, gross=gross, exp=exp,
                           total_exp=total_exp, net=net, start=start, end=end,
                           margin=(gross * 100 / net_sales) if net_sales else 0)


@bp.route("/payables")
def payables():
    _staff()
    from .ops import supplier_open_bills, suppliers_with_balance
    today_d = date.today()
    out = []
    for s in suppliers_with_balance(" AND s.active = 1"):
        if not s["balance"]:
            continue
        bills, opening_left, advance = supplier_open_bills(s["id"])
        b = dict.fromkeys(BUCKETS, 0)
        from .ledger import _bucket
        if opening_left:
            b["90+"] += opening_left
        for x_ in bills:
            if x_["open"]:
                due = date.fromisoformat(x_["b"]["due_date"] or x_["b"]["date"])
                b[_bucket((today_d - due).days)] += x_["open"]
        b["Current"] -= advance
        out.append([s["name"]] + [b[k] for k in BUCKETS] + [s["balance"]])
    out.sort(key=lambda r: -r[-1])
    totals = ["Total"] + [sum(r[i] for r in out) for i in range(1, 7)]
    return _table("Payables (what we owe suppliers)", ["Supplier"] + BUCKETS + ["Total"], out, set(range(1, 7)), totals, [],
                  "Days are counted from each bill's due date. Supplier payments pay the oldest bills first.")


@bp.route("/purchases")
def purchases_report():
    _staff()
    start, end = _period()
    by = request.args.get("by", "supplier")
    args = {"a": start, "b": end}
    iw, ia = _item_where("pl", "it")
    sw = ""
    if request.args.get("sup", "").strip():
        sw = " AND s.name LIKE :f_sup"
        args["f_sup"] = f"%{request.args['sup'].strip()}%"
    args.update(ia)
    flt = ["dates", "puby", "sup"] + ITEM_F
    if by in ("item", "group", "detail") or iw:
        cw, ca = co_filter("p.company_id")
        args.update(ca)
        if by == "detail":
            rows = q(f"""SELECT p.date, p.number, p.bill_no, s.name AS sup, pl.code, pl.description, pl.qty, pl.unit, pl.rate, pl.amount,
                                COALESCE(NULLIF(it.grp, ''), '(no group)') AS grp
                         FROM purchase_lines pl JOIN purchases p ON p.id = pl.purchase_id JOIN suppliers s ON s.id = p.supplier_id
                         LEFT JOIN items it ON it.id = pl.item_id
                         WHERE p.void = 0 AND p.date BETWEEN :a AND :b {cw} {sw} {iw} ORDER BY p.date, p.number, pl.sort""", args)
            data = [[nice_date(r["date"]), r["number"], r["sup"], r["bill_no"] or "", r["code"] or "", r["description"] or "", r["grp"],
                     f"{(r['qty'] or 0):g} {r['unit'] or ''}".strip(), fmt(r["rate"]), r["amount"]] for r in rows]
            return _table("Purchases detail", ["Date", "Bill #", "Supplier", "Their bill no.", "Item", "Description", "Group", "Qty", "Cost",
                                                "Amount"], data, {9}, ["Total", f"{len(rows)} lines", "", "", "", "", "",
                                                                       f"{sum((r['qty'] or 0) for r in rows):g}", "", sum(r["amount"] for r in rows)], flt)
        key = {"group": "COALESCE(NULLIF(it.grp, ''), '(no group)')", "supplier": "s.name"}.get(by, "COALESCE(NULLIF(pl.code, ''), pl.description)")
        rows = q(f"""SELECT {key} AS name, SUM(COALESCE(pl.qty, 0)) AS qty, SUM(pl.amount) AS amt, COUNT(DISTINCT p.id) AS n
                     FROM purchase_lines pl JOIN purchases p ON p.id = pl.purchase_id JOIN suppliers s ON s.id = p.supplier_id
                     LEFT JOIN items it ON it.id = pl.item_id
                     WHERE p.void = 0 AND p.date BETWEEN :a AND :b {cw} {sw} {iw} GROUP BY 1 ORDER BY amt DESC""", args)
        head = {"group": "Item group", "supplier": "Supplier"}.get(by, "Item")
        return _table(f"Purchases by {head.lower()}", [head, "Qty", "Bills", "Amount"], [[r["name"], f"{r['qty']:g}", r["n"], r["amt"]] for r in rows],
                      {3}, ["Total", f"{sum(r['qty'] for r in rows):g}", "", sum(r["amt"] for r in rows)], flt)
    rows = q("""SELECT s.name, COUNT(*) AS n, SUM(p.total) AS amt FROM purchases p JOIN suppliers s ON s.id = p.supplier_id
                WHERE p.void = 0 AND p.date BETWEEN :a AND :b {cof} {sw} GROUP BY s.id ORDER BY amt DESC""".replace("{cof}", co_filter("p.company_id")[0]).replace("{sw}", sw),
             {**args, **co_filter("p.company_id")[1]})
    return _table("Purchases by supplier", ["Supplier", "Bills", "Amount"], [[r["name"], r["n"], r["amt"]] for r in rows], {2},
                  ["Total", sum(r["n"] for r in rows), sum(r["amt"] for r in rows)], flt)


@bp.route("/expenses")
def expenses_report():
    _staff()
    start, end = _period()
    cw, ca = co_filter("company_id")
    rows = q(f"""SELECT category, COUNT(*) AS n, SUM(amount) AS amt FROM expenses WHERE void = 0 AND date BETWEEN :a AND :b
                {cw} GROUP BY category ORDER BY amt DESC""", {"a": start, "b": end, **ca})
    return _table("Expenses by category", ["Category", "Entries", "Amount"], [[r["category"], r["n"], r["amt"]] for r in rows], {2},
                  ["Total", sum(r["n"] for r in rows), sum(r["amt"] for r in rows)], ["dates"])
