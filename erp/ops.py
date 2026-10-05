"""Suppliers, purchase bills, supplier payments, sales returns (credit notes), stock and expenses."""
from datetime import date, timedelta

from flask import Blueprint, abort, flash, g, jsonify, redirect, render_template, request, send_file, url_for

from . import stock as stockmod
from .auth import check_customer_access, co_filter, is_rep, rep_filter, roles
from .companies import companies, default_company_id, get_company
from .db import commit, fmt, next_number, nice_date, now, parse_date, plain, q, settings, to_paisa, today, x
from .export import table_response
from .lines import parse_qty

bp = Blueprint("ops", __name__)
METHODS = ["Cash", "Cheque", "Bank transfer", "Online", "Other"]
STAFF = ("admin", "accounts")


# ---- shared helpers -------------------------------------------------------------------------
def item_data(price_field="price"):
    rows = q("SELECT id, code, name, description, unit, price, opening_cost, kind FROM items WHERE active = 1 AND kind IN ('item', 'service') ORDER BY code")
    lv = stockmod.levels()
    out = []
    for i in rows:
        st = lv.get(i["id"])
        cost = st["avg_cost"] if st else i["opening_cost"]
        out.append({"id": i["id"], "code": (i["code"] or i["name"]).upper(), "name": i["name"], "desc": i["description"] or i["name"],
                    "unit": i["unit"] or "", "price": plain(i["price"]), "cost": plain(cost or 0),
                    "stock": (f"{st['on_hand']:g}" if st else "")})
    return out


def read_doc_lines(f, need_qty=True):
    by_code = {r["code"].upper(): r for r in q("SELECT * FROM items WHERE code != ''")}
    lines = []
    cols = [f.getlist(k) for k in ("qty", "unit", "code", "description", "price")]
    for n, (qty, unit, code, desc, price) in enumerate(zip(*cols), start=1):
        if not any(str(v).strip() for v in (qty, code, desc, price)):
            continue
        code = code.strip().upper()
        it = by_code.get(code)
        try:
            qv = parse_qty(qty)
            rate = to_paisa(price)
        except ValueError as e:
            raise ValueError(f"Line {n}: {e}")
        if need_qty and it and it["kind"] == "item" and qv is None:
            raise ValueError(f"Line {n}: enter a quantity for {code}.")
        lines.append({"item_id": it["id"] if it else None, "code": code, "description": desc.strip(), "unit": unit.strip(),
                      "qty": qv, "rate": rate, "amount": int(round((qv if qv is not None else 1) * rate)), "sort": n})
    if not lines:
        raise ValueError("Add at least one line.")
    return lines


def form_lines(f):
    cols = [f.getlist(k) for k in ("qty", "unit", "code", "description", "price")]
    return [dict(zip(("qty", "unit", "code", "description", "price"), r)) for r in zip(*cols)
            if any(str(v).strip() for v in r)]


def db_lines(table, fk, doc_id):
    return [{"qty": "" if l["qty"] is None else f"{l['qty']:g}", "unit": l["unit"] or "", "code": l["code"] or "",
             "description": l["description"] or "", "price": plain(l["rate"])}
            for l in q(f"SELECT * FROM {table} WHERE {fk} = ? ORDER BY sort", (doc_id,))]


# ---- suppliers ------------------------------------------------------------------------------
SUP_BAL = """(CASE WHEN s.opening_date IS NULL OR s.opening_date <= :d THEN s.opening_balance ELSE 0 END)
  + COALESCE((SELECT SUM(total) FROM purchases p WHERE p.supplier_id = s.id AND p.void = 0 AND p.date <= :d), 0)
  - COALESCE((SELECT SUM(amount) FROM supplier_payments y WHERE y.supplier_id = s.id AND y.void = 0 AND y.date <= :d), 0)"""


def suppliers_with_balance(where="", args=None, as_of=None):
    return q(f"SELECT s.*, {SUP_BAL} AS balance FROM suppliers s WHERE 1 = 1 {where} ORDER BY s.name COLLATE NOCASE",
             {"d": as_of or "9999-12-31", **(args or {})})


def supplier_balance(sid):
    return suppliers_with_balance(" AND s.id = :sid", {"sid": sid})[0]["balance"]


def supplier_open_bills(sid):
    """Supplier payments applied to the oldest bills first."""
    s = q("SELECT opening_balance FROM suppliers WHERE id = ?", (sid,), one=True)
    paid = q("SELECT COALESCE(SUM(amount), 0) AS s FROM supplier_payments WHERE supplier_id = ? AND void = 0", (sid,), one=True)["s"]
    ob = s["opening_balance"] or 0
    if ob < 0:
        paid += -ob
    opening_left = max(ob, 0)
    used = min(paid, opening_left)
    opening_left -= used
    paid -= used
    out = []
    for b in q("SELECT * FROM purchases WHERE supplier_id = ? AND void = 0 ORDER BY date, number", (sid,)):
        use = min(paid, b["total"])
        paid -= use
        out.append({"b": b, "open": b["total"] - use})
    return out, opening_left, paid


def get_supplier(sid):
    s = q("SELECT * FROM suppliers WHERE id = ?", (sid,), one=True)
    if not s:
        abort(404)
    return s


@bp.route("/suppliers")
@roles(*STAFF)
def suppliers():
    where, args = "", {}
    if request.args.get("q"):
        where, args = " AND (s.name LIKE :s OR s.phone LIKE :s)", {"s": f"%{request.args['q'].strip()}%"}
    if not request.args.get("inactive"):
        where += " AND s.active = 1"
    rows = suppliers_with_balance(where, args)
    if request.args.get("export") in ("xlsx", "pdf"):
        return table_response(request.args["export"], "Suppliers", ["Supplier", "Contact", "Phone", "Balance"],
                              [[r["name"], r["contact"], r["phone"] or r["whatsapp"], r["balance"]] for r in rows], {3},
                              ["Total", "", "", sum(r["balance"] for r in rows)])
    return render_template("ops/suppliers.html", rows=rows, total=sum(r["balance"] for r in rows))


@bp.route("/suppliers/new", methods=["GET", "POST"])
@bp.route("/suppliers/<int:sid>/edit", methods=["GET", "POST"])
@roles(*STAFF)
def supplier_form(sid=None):
    s = get_supplier(sid) if sid else None
    if request.method == "POST":
        f = request.form
        try:
            vals = dict(name=f["name"].strip(), contact=f.get("contact", "").strip(), phone=f.get("phone", "").strip(),
                        whatsapp=f.get("whatsapp", "").strip(), email=f.get("email", "").strip(),
                        address=f.get("address", "").strip(), terms_days=int(f.get("terms_days") or 0),
                        opening_balance=to_paisa(f.get("opening_balance")), opening_date=parse_date(f.get("opening_date")),
                        notes=f.get("notes", "").strip(), active=1 if f.get("active") else 0)
            if not vals["name"]:
                raise ValueError("Name is required.")
        except ValueError as e:
            flash(str(e), "err")
            return render_template("ops/supplier_form.html", s=s, f=f)
        if s:
            x(f"UPDATE suppliers SET {', '.join(k + ' = :' + k for k in vals)} WHERE id = :id", {**vals, "id": sid})
        else:
            sid = x(f"INSERT INTO suppliers ({', '.join(vals)}, created_at) VALUES ({', '.join(':' + k for k in vals)}, :ca)",
                    {**vals, "ca": now()})
        commit()
        flash("Supplier saved.", "ok")
        return redirect(url_for("ops.supplier_view", sid=sid))
    return render_template("ops/supplier_form.html", s=s, f={})


@bp.route("/suppliers/<int:sid>")
@roles(*STAFF)
def supplier_view(sid):
    s = get_supplier(sid)
    bills, opening_left, advance = supplier_open_bills(sid)
    pays = q("SELECT * FROM supplier_payments WHERE supplier_id = ? ORDER BY date DESC, number DESC", (sid,))
    return render_template("ops/supplier_view.html", s=s, bal=supplier_balance(sid), bills=list(reversed(bills)),
                           opening_left=opening_left, advance=advance, pays=pays)


@bp.route("/api/supplier/<int:sid>")
@roles(*STAFF)
def supplier_api(sid):
    s = get_supplier(sid)
    bills, opening_left, advance = supplier_open_bills(sid)
    return jsonify(id=sid, name=s["name"], terms_days=s["terms_days"], balance=plain(supplier_balance(sid)),
                   open=[{"id": b["b"]["id"], "number": b["b"]["number"], "bill_no": b["b"]["bill_no"],
                          "date": nice_date(b["b"]["date"]), "open": plain(b["open"])} for b in bills if b["open"]])


# ---- purchase bills --------------------------------------------------------------------------
@bp.route("/purchases")
@roles(*STAFF)
def purchases():
    a = request.args
    where, args = co_filter("p.company_id")
    if a.get("q"):
        where += " AND (s.name LIKE :s OR p.bill_no LIKE :s OR CAST(p.number AS TEXT) = :n)"
        args.update(s=f"%{a['q'].strip()}%", n=a["q"].strip())
    if parse_date(a.get("from")):
        where += " AND p.date >= :f"
        args["f"] = a["from"]
    if parse_date(a.get("to")):
        where += " AND p.date <= :t"
        args["t"] = a["to"]
    rows = q(f"""SELECT p.*, s.name AS supplier FROM purchases p JOIN suppliers s ON s.id = p.supplier_id
                 WHERE 1 = 1 {where} ORDER BY p.date DESC, p.number DESC LIMIT 500""", args)
    total = sum(r["total"] for r in rows if not r["void"])
    if a.get("export") in ("xlsx", "pdf"):
        return table_response(a["export"], "Purchase bills", ["#", "Date", "Supplier", "Bill no.", "Total", ""],
                              [[r["number"], nice_date(r["date"]), r["supplier"], r["bill_no"], 0 if r["void"] else r["total"],
                                "VOID" if r["void"] else ""] for r in rows], {4}, ["Total", "", "", "", total, ""])
    return render_template("ops/purchases.html", rows=rows, total=total)


def _doc_form(kind, doc=None):
    """Shared new/edit screen for purchase bills (kind='purchase') and credit notes (kind='credit')."""
    cfg = {
        "purchase": dict(table="purchases", lines="purchase_lines", fk="purchase_id", party="supplier_id",
                         seq="next_purchase_number", title="Purchase bill", view="ops.purchase_view"),
        "credit": dict(table="credit_notes", lines="credit_note_lines", fk="credit_note_id", party="customer_id",
                       seq="next_credit_number", title="Credit note (sales return)", view="ops.credit_view"),
    }[kind]
    if kind == "purchase":
        parties = q("SELECT id, name, terms_days FROM suppliers WHERE active = 1 ORDER BY name COLLATE NOCASE")
    else:
        where, args = rep_filter()
        parties = q(f"SELECT c.id, c.name, c.terms_days FROM customers c WHERE c.active = 1 {where} ORDER BY c.name COLLATE NOCASE", args)
    did = doc["id"] if doc else None
    if request.method == "POST":
        f = request.form
        try:
            pid = int(f.get("party_id") or 0)
            if pid not in {p["id"] for p in parties}:
                raise ValueError("Please choose a " + ("supplier." if kind == "purchase" else "customer."))
            lines = read_doc_lines(f)
            d = parse_date(f.get("date")) or today()
            tax_rate = float((f.get("tax_rate") or "0").replace("%", "") or 0)
            co_id = None
            number = None
            if kind == "purchase":
                co_id = f.get("company_id", type=int) or _purchase_company()
                if not get_company(co_id):
                    raise ValueError("Choose the company this bill is bought under.")
                if f.get("number", "").strip():
                    try:
                        number = int(f["number"].strip())
                    except ValueError:
                        raise ValueError("Bill number must be a whole number.")
                    if q("SELECT 1 FROM purchases WHERE number = ? AND id != ?", (number, did or -1)):
                        raise ValueError(f"Purchase bill number {number} is already used. Leave it as given for the next free number.")
        except ValueError as e:
            flash(str(e), "err")
            return render_template("ops/doc_form.html", kind=kind, cfg=cfg, doc=doc, f=f, parties=parties,
                                   next_no=next_number(cfg["table"], cfg["seq"]),
                                   grid=form_lines(f), items=item_data(), companies=companies(), purchase_co=_purchase_company())
        subtotal = sum(l["amount"] for l in lines)
        tax = int(round(subtotal * tax_rate / 100))
        vals = dict(date=d, party=pid, notes=f.get("notes", "").strip(), subtotal=subtotal, tax_rate=tax_rate, tax=tax,
                    total=subtotal + tax, t=now())
        if kind == "purchase":
            party_row = next(p for p in parties if p["id"] == pid)
            extra = dict(bill_no=f.get("bill_no", "").strip(), company_id=co_id,
                         due_date=parse_date(f.get("due_date")) or (date.fromisoformat(d) + timedelta(days=party_row["terms_days"] or 0)).isoformat())
        else:
            extra = dict(invoice_ref=f.get("invoice_ref", "").strip(), restock=1)
        cols = {**{k: vals[k] for k in ("date", "notes", "subtotal", "tax_rate", "tax", "total")}, cfg["party"]: pid, **extra}
        if doc:
            if kind == "purchase" and number:
                cols["number"] = number
            x(f"UPDATE {cfg['table']} SET {', '.join(k + ' = :' + k for k in cols)}, updated_at = :t WHERE id = :id",
              {**cols, "t": now(), "id": did})
            x(f"DELETE FROM {cfg['lines']} WHERE {cfg['fk']} = ?", (did,))
        else:
            cols["number"] = (number if kind == "purchase" and number else None) or next_number(cfg["table"], cfg["seq"])
            did = x(f"INSERT INTO {cfg['table']} ({', '.join(cols)}, created_by, created_at) VALUES "
                    f"({', '.join(':' + k for k in cols)}, :uid, :t)", {**cols, "uid": g.user["id"], "t": now()})
        for l in lines:
            x(f"""INSERT INTO {cfg['lines']} ({cfg['fk']}, item_id, code, description, unit, qty, rate, amount, sort)
                  VALUES (:d, :item_id, :code, :description, :unit, :qty, :rate, :amount, :sort)""", {**l, "d": did})
        if kind == "credit":
            x("UPDATE credit_notes SET company_id = (SELECT company_id FROM customers c WHERE c.id = credit_notes.customer_id) WHERE id = ?",
              (did,))
        commit()
        flash(f"{cfg['title'].split(' (')[0]} saved: {settings().get('currency', 'Rs')} {fmt(subtotal + tax)}.", "ok")
        if f.get("action") == "save_new":
            return redirect(url_for("ops.purchase_new" if kind == "purchase" else "ops.credit_new"))
        return redirect(url_for(cfg["view"], did=did))
    grid = db_lines(cfg["lines"], cfg["fk"], did) if doc else []
    f = {"party_id": request.args.get("party_id", "")}
    return render_template("ops/doc_form.html", kind=kind, cfg=cfg, doc=doc, f=f, parties=parties, grid=grid, items=item_data(),
                           next_no=next_number(cfg["table"], cfg["seq"]),
                           companies=companies(), purchase_co=(doc["company_id"] if doc and kind == "purchase" else _purchase_company()))


def _purchase_company():
    v = settings().get("default_purchase_company")
    return int(v) if v and v.isdigit() and get_company(int(v)) else default_company_id()


@bp.route("/purchases/new", methods=["GET", "POST"])
@roles(*STAFF)
def purchase_new():
    return _doc_form("purchase")


@bp.route("/purchases/<int:did>/edit", methods=["GET", "POST"])
@roles(*STAFF)
def purchase_edit(did):
    doc = q("SELECT * FROM purchases WHERE id = ?", (did,), one=True) or abort(404)
    if doc["void"]:
        abort(400, "A void bill can't be edited.")
    return _doc_form("purchase", doc)


@bp.route("/purchases/<int:did>")
@roles(*STAFF)
def purchase_view(did):
    doc = q("""SELECT p.*, s.name AS party FROM purchases p JOIN suppliers s ON s.id = p.supplier_id WHERE p.id = ?""",
            (did,), one=True) or abort(404)
    lines = q("SELECT * FROM purchase_lines WHERE purchase_id = ? ORDER BY sort", (did,))
    bills, _, _ = supplier_open_bills(doc["supplier_id"])
    open_amt = next((b["open"] for b in bills if b["b"]["id"] == did), 0)
    receipts = q("SELECT id, number FROM wh_docs WHERE purchase_id = ? AND type = 'GRN' AND void = 0", (did,))
    return render_template("ops/doc_view.html", kind="purchase", doc=doc, lines=lines, open_amt=open_amt, receipts=receipts)


@bp.route("/purchases/<int:did>/void", methods=["POST"])
@roles(*STAFF)
def purchase_void(did):
    doc = q("SELECT * FROM purchases WHERE id = ?", (did,), one=True) or abort(404)
    note = (doc["notes"] + "\n" if doc["notes"] else "") + f"VOIDED {now()} by {g.user['name']}: {request.form.get('reason', '')}"
    x("UPDATE purchases SET void = 1, notes = ? WHERE id = ?", (note, did))
    commit()
    flash(f"Purchase bill {doc['number']} voided.", "ok")
    return redirect(url_for("ops.purchase_view", did=did))


# ---- supplier payments ----------------------------------------------------------------------
@bp.route("/supplier-payments")
@roles(*STAFF)
def supplier_payments():
    where, args = co_filter("y.company_id")
    rows = q(f"""SELECT y.*, s.name AS supplier FROM supplier_payments y JOIN suppliers s ON s.id = y.supplier_id
                WHERE 1 = 1 {where} ORDER BY y.date DESC, y.number DESC LIMIT 500""", args)
    total = sum(r["amount"] for r in rows if not r["void"])
    if request.args.get("export") in ("xlsx", "pdf"):
        return table_response(request.args["export"], "Supplier payments", ["#", "Date", "Supplier", "Method", "Reference", "Amount"],
                              [[r["number"], nice_date(r["date"]), r["supplier"], r["method"], r["reference"],
                                0 if r["void"] else r["amount"]] for r in rows], {5}, ["Total", "", "", "", "", total])
    return render_template("ops/supplier_payments.html", rows=rows, total=total)


@bp.route("/supplier-payments/new", methods=["GET", "POST"])
@roles(*STAFF)
def supplier_payment_new():
    sups = q("SELECT id, name FROM suppliers WHERE active = 1 ORDER BY name COLLATE NOCASE")
    if request.method == "POST":
        f = request.form
        try:
            sid = int(f.get("supplier_id") or 0)
            get_supplier(sid)
            amount = to_paisa(f.get("amount"))
            if amount <= 0:
                raise ValueError("Amount must be more than zero.")
            co_id = f.get("company_id", type=int) or default_company_id()
            if not get_company(co_id):
                raise ValueError("Choose which company is paying.")
        except ValueError as e:
            flash(str(e), "err")
            return render_template("ops/supplier_payment_form.html", sups=sups, methods=METHODS, f=f, companies=companies())
        x("""INSERT INTO supplier_payments (number, date, supplier_id, amount, method, reference, notes, created_by, created_at, company_id)
             VALUES (?,?,?,?,?,?,?,?,?,?)""",
          (next_number("supplier_payments", "next_supplier_payment_number"), parse_date(f.get("date")) or today(), sid, amount,
           f.get("method") if f.get("method") in METHODS else "Other", f.get("reference", "").strip(), f.get("notes", "").strip(),
           g.user["id"], now(), co_id))
        commit()
        flash(f"Payment of {settings().get('currency', 'Rs')} {fmt(amount)} recorded.", "ok")
        if f.get("action") == "save_new":
            return redirect(url_for("ops.supplier_payment_new"))
        return redirect(url_for("ops.supplier_view", sid=sid))
    return render_template("ops/supplier_payment_form.html", sups=sups, methods=METHODS, companies=companies(),
                           f={"supplier_id": request.args.get("supplier_id", ""), "method": "Cash", "company_id": str(default_company_id())})


@bp.route("/supplier-payments/<int:yid>/void", methods=["POST"])
@roles(*STAFF)
def supplier_payment_void(yid):
    from .approvals import void_or_request
    y = q("SELECT * FROM supplier_payments WHERE id = ?", (yid,), one=True) or abort(404)
    flash(*void_or_request("supplier_payment", yid, request.form.get("reason", "").strip()))
    return redirect(url_for("ops.supplier_view", sid=y["supplier_id"]))


# ---- credit notes (sales returns) ------------------------------------------------------------
@bp.route("/credit-notes")
def credit_notes():
    where, args = rep_filter()
    rows = q(f"""SELECT n.*, c.name AS customer FROM credit_notes n JOIN customers c ON c.id = n.customer_id
                 WHERE 1 = 1 {where} ORDER BY n.date DESC, n.number DESC LIMIT 500""", args)
    total = sum(r["total"] for r in rows if not r["void"])
    if request.args.get("export") in ("xlsx", "pdf"):
        return table_response(request.args["export"], "Credit notes", ["#", "Date", "Customer", "Against invoice", "Total", ""],
                              [[r["number"], nice_date(r["date"]), r["customer"], r["invoice_ref"], 0 if r["void"] else r["total"],
                                "VOID" if r["void"] else ""] for r in rows], {4}, ["Total", "", "", "", total, ""])
    return render_template("ops/credit_notes.html", rows=rows, total=total)


@bp.route("/credit-notes/new", methods=["GET", "POST"])
@roles(*STAFF)
def credit_new():
    return _doc_form("credit")


@bp.route("/credit-notes/<int:did>/edit", methods=["GET", "POST"])
@roles(*STAFF)
def credit_edit(did):
    doc = q("SELECT * FROM credit_notes WHERE id = ?", (did,), one=True) or abort(404)
    if doc["void"]:
        abort(400, "A void credit note can't be edited.")
    return _doc_form("credit", doc)


@bp.route("/credit-notes/<int:did>")
def credit_view(did):
    doc = q("""SELECT n.*, c.name AS party, c.rep_id FROM credit_notes n JOIN customers c ON c.id = n.customer_id
               WHERE n.id = ?""", (did,), one=True) or abort(404)
    check_customer_access(q("SELECT * FROM customers WHERE id = ?", (doc["customer_id"],), one=True))
    lines = q("SELECT * FROM credit_note_lines WHERE credit_note_id = ? ORDER BY sort", (did,))
    return render_template("ops/doc_view.html", kind="credit", doc=doc, lines=lines, open_amt=None)


@bp.route("/credit-notes/<int:did>.pdf")
def credit_pdf(did):
    from .pdfs import credit_note
    from .notify import _pdf_path
    doc = q("SELECT * FROM credit_notes WHERE id = ?", (did,), one=True) or abort(404)
    c = check_customer_access(q("SELECT * FROM customers WHERE id = ?", (doc["customer_id"],), one=True))
    lines = q("SELECT * FROM credit_note_lines WHERE credit_note_id = ? ORDER BY sort", (did,))
    from .companies import pdf_settings
    return send_file(credit_note(_pdf_path(f"CreditNote_{doc['number']}.pdf"), pdf_settings(c["company_id"]), doc, lines, c),
                     mimetype="application/pdf")


@bp.route("/credit-notes/<int:did>/void", methods=["POST"])
@roles(*STAFF)
def credit_void(did):
    from .approvals import void_or_request
    q("SELECT 1 FROM credit_notes WHERE id = ?", (did,), one=True) or abort(404)
    flash(*void_or_request("credit", did, request.form.get("reason", "").strip()))
    return redirect(url_for("ops.credit_view", did=did))


# ---- old stock links now live in the warehouse module ---------------------------------------
@bp.route("/stock")
def stock():
    return redirect(url_for("wh.home", **request.args))


@bp.route("/stock/<int:item_id>")
def stock_card(item_id):
    return redirect(url_for("wh.card", item_id=item_id))


# ---- expenses -------------------------------------------------------------------------------
@bp.route("/expenses")
@roles(*STAFF)
def expenses():
    a = request.args
    t = date.today()
    start = parse_date(a.get("from")) or t.replace(day=1).isoformat()
    end = parse_date(a.get("to")) or t.isoformat()
    where, args = co_filter("company_id")
    where += " AND date BETWEEN :a AND :b"
    args.update(a=start, b=end)
    if a.get("category"):
        where += " AND category = :c"
        args["c"] = a["category"]
    rows = q(f"SELECT * FROM expenses WHERE 1 = 1 {where} ORDER BY date DESC, id DESC", args)
    cats = [r["category"] for r in q("SELECT DISTINCT category FROM expenses ORDER BY category")]
    total = sum(r["amount"] for r in rows if not r["void"])
    if a.get("export") in ("xlsx", "pdf"):
        return table_response(a["export"], "Expenses", ["Date", "Category", "Paid to", "Method", "Reference", "Amount"],
                              [[nice_date(r["date"]), r["category"], r["payee"], r["method"], r["reference"],
                                0 if r["void"] else r["amount"]] for r in rows], {5}, ["Total", "", "", "", "", total],
                              f"{nice_date(start)} to {nice_date(end)}")
    return render_template("ops/expenses.html", rows=rows, cats=cats, total=total, start=start, end=end, methods=METHODS,
                           companies=companies(), default_co=default_company_id())


@bp.route("/expenses/new", methods=["POST"])
@roles(*STAFF)
def expense_new():
    f = request.form
    try:
        amount = to_paisa(f.get("amount"))
        if amount <= 0:
            raise ValueError("Amount must be more than zero.")
        if not f.get("category", "").strip():
            raise ValueError("Choose or type a category.")
    except ValueError as e:
        flash(str(e), "err")
        return redirect(url_for("ops.expenses"))
    co_id = f.get("company_id", type=int)
    x("""INSERT INTO expenses (date, category, payee, amount, method, reference, notes, created_by, created_at, company_id)
         VALUES (?,?,?,?,?,?,?,?,?,?)""",
      (parse_date(f.get("date")) or today(), f["category"].strip(), f.get("payee", "").strip(), amount,
       f.get("method") if f.get("method") in METHODS else "Other", f.get("reference", "").strip(), f.get("notes", "").strip(),
       g.user["id"], now(), co_id if co_id and get_company(co_id) else default_company_id()))
    commit()
    flash(f"Expense of {settings().get('currency', 'Rs')} {fmt(amount)} saved.", "ok")
    return redirect(url_for("ops.expenses"))


@bp.route("/expenses/<int:eid>/void", methods=["POST"])
@roles(*STAFF)
def expense_void(eid):
    x("UPDATE expenses SET void = 1 WHERE id = ?", (eid,))
    commit()
    flash("Expense voided.", "ok")
    return redirect(request.referrer or url_for("ops.expenses"))
