"""Order booking: the order booker takes an order at the shop on a phone; the office approves it and it becomes an invoice."""
from datetime import date, timedelta

from flask import Blueprint, abort, flash, g, jsonify, redirect, render_template, request, url_for

from .auth import check_customer_access, is_rep, rep_filter
from .companies import default_company_id, get_company, next_invoice_number
from .db import commit, mul_rnd, now, pct_rnd, parse_date, q, settings, to_paisa, today, x
from .perms import has

bp = Blueprint("orders", __name__, url_prefix="/orders")

STATUSES = ["Pending", "Approved", "Rejected", "Cancelled"]


def _next_number():
    return (q("SELECT MAX(number) AS m FROM orders", one=True)["m"] or 0) + 1


def pending_count():
    return q("SELECT COUNT(*) AS n FROM orders WHERE status = 'Pending'", one=True)["n"]


def _visible(alias="o"):
    """Order bookers (own-customers scope) only see their own orders."""
    if is_rep():
        return f" AND {alias}.created_by = {int(g.user['id'])} "
    return " "


def _customers():
    where, args = rep_filter("c")
    return q(f"SELECT c.id, c.name, c.address FROM customers c WHERE c.active = 1 {where} ORDER BY c.name COLLATE NOCASE", args)


def _items():
    return q("SELECT id, code, name, description, unit, price FROM items WHERE active = 1 AND kind = 'item' ORDER BY code, name")


def _read_lines(f, items_by_code, can_price):
    """Lines come from the invoice-style grid: code, qty, price (price only changes if the user may change prices)."""
    lines = []
    cols = [f.getlist(k) for k in ("code", "qty", "price", "ctn_qty")]
    for n in range(max((len(c) for c in cols), default=0)):
        code, qty, price, ctn = (c[n].strip() if n < len(c) else "" for c in cols)
        if not code and not qty:
            continue
        it = items_by_code.get(code.upper())
        if not it:
            raise ValueError(f"Line {len(lines) + 1}: '{code}' is not an item code. Choose an item from the list.")
        try:
            qn = float(qty.replace(",", "") or 0)
        except ValueError:
            raise ValueError(f"Line {len(lines) + 1}: quantity must be a number.")
        if qn <= 0:
            raise ValueError(f"Line {len(lines) + 1}: quantity must be more than zero.")
        rate = to_paisa(price) if (can_price and price) else it["price"]
        lines.append({"item_id": it["id"], "code": it["code"], "description": it["description"] or it["name"], "unit": it["unit"] or "",
                      "ctn_qty": ctn, "qty": qn, "rate": rate, "amount": mul_rnd(qn, rate), "sort": len(lines) + 1})
    if not lines:
        raise ValueError("Add at least one item.")
    return lines


@bp.route("/")
def index():
    status = request.args.get("status", "Pending" if has("orders.approve") else "")
    where, args = " WHERE 1 = 1" + _visible("o"), []
    if status in STATUSES:
        where += " AND o.status = ?"
        args.append(status)
    s = request.args.get("q", "").strip()
    if s:
        where += " AND (c.name LIKE ? OR CAST(o.number AS TEXT) LIKE ? OR o.created_by_name LIKE ?)"
        args += [f"%{s}%"] * 3
    rows = q(f"""SELECT o.*, c.name AS customer FROM orders o JOIN customers c ON c.id = o.customer_id
                 {where} ORDER BY (o.status = 'Pending') DESC, o.id DESC LIMIT 300""", args)
    counts = {r["status"]: r["n"] for r in q(f"SELECT status, COUNT(*) AS n FROM orders o WHERE 1 = 1 {_visible('o')} GROUP BY status")}
    return render_template("orders/index.html", rows=rows, status=status, s=s, counts=counts, statuses=STATUSES,
                           cur=settings().get("currency", "Rs"))


@bp.route("/count")
def count():
    """Polled by the page every half minute so the office is told when a new order arrives."""
    last = q("SELECT MAX(id) AS m FROM orders WHERE status = 'Pending'", one=True)["m"] or 0
    newest = q("""SELECT o.number, o.created_by_name, c.name AS customer FROM orders o JOIN customers c ON c.id = o.customer_id
                  WHERE o.status = 'Pending' ORDER BY o.id DESC LIMIT 1""", one=True)
    return jsonify(pending=pending_count(), last_id=last,
                   latest=({"number": newest["number"], "by": newest["created_by_name"], "customer": newest["customer"]} if newest else None))


def _form(order, lines, f=None):
    return render_template("orders/form.html", order=order, lines=lines, f=f or {}, customers=_customers(), items=_items(),
                           items_json=[{"id": i["id"], "code": i["code"], "desc": i["description"] or i["name"], "unit": i["unit"] or "", "price": i["price"] / 100} for i in _items()],
                           existing=[{"code": l["code"], "qty": f"{l['qty']:g}", "ctn_qty": l["ctn_qty"] if "ctn_qty" in l.keys() else "", "price": f"{l['rate'] / 100:.2f}"} for l in lines],
                           can_price=has("orders.price"), cur=settings().get("currency", "Rs"))


@bp.route("/new", methods=["GET", "POST"])
@bp.route("/<int:oid>/edit", methods=["GET", "POST"])
def new(oid=None):
    order = q("SELECT * FROM orders WHERE id = ?", (oid,), one=True) if oid else None
    if oid:
        if not order:
            abort(404)
        if order["status"] != "Pending":
            flash("Only a pending order can be changed.", "err")
            return redirect(url_for("orders.view_one", oid=oid))
        if is_rep() and order["created_by"] != g.user["id"]:
            abort(403)
    if request.method == "POST":
        f = request.form
        try:
            cid = int(f.get("customer_id") or 0)
            c = q("SELECT * FROM customers WHERE id = ? AND active = 1", (cid,), one=True)
            if not c:
                raise ValueError("Choose the customer (shop) from the list.")
            check_customer_access(c)
            lines = _read_lines(f, {i["code"].upper(): i for i in _items() if i["code"]}, has("orders.price"))
        except ValueError as e:
            flash(str(e), "err")
            return _form(order, [], f)
        total = sum(l["amount"] for l in lines)
        lat = f.get("lat", type=float)
        lng = f.get("lng", type=float)
        if order:
            x("UPDATE orders SET customer_id = ?, notes = ?, total = ? WHERE id = ?", (cid, f.get("notes", "").strip(), total, oid))
            x("DELETE FROM order_lines WHERE order_id = ?", (oid,))
        else:
            oid = x("""INSERT INTO orders (number, date, customer_id, rep_id, notes, status, total, lat, lng, created_by, created_by_name, created_at)
                       VALUES (?,?,?,?,?,'Pending',?,?,?,?,?,?)""",
                    (_next_number(), today(), cid, c["rep_id"] or (g.user["rep_id"] if is_rep() else None), f.get("notes", "").strip(),
                     total, lat, lng, g.user["id"], g.user["name"], now()))
        for l in lines:
            x("""INSERT INTO order_lines (order_id, item_id, code, description, unit, ctn_qty, qty, rate, amount, sort)
                 VALUES (?,?,?,?,?,?,?,?,?,?)""", (oid, l["item_id"], l["code"], l["description"], l["unit"], l["ctn_qty"], l["qty"], l["rate"], l["amount"], l["sort"]))
        commit()
        n = q("SELECT number FROM orders WHERE id = ?", (oid,), one=True)["number"]
        flash(f"Order {n} sent to the office for approval.", "ok")
        return redirect(url_for("orders.view_one", oid=oid))
    if order:
        c = q("SELECT name FROM customers WHERE id = ?", (order["customer_id"],), one=True)
        lines = q("SELECT * FROM order_lines WHERE order_id = ? ORDER BY sort", (oid,))
        return _form(order, lines, {"customer_id": order["customer_id"], "customer_name": c["name"], "notes": order["notes"]})
    return _form(None, [], {})


def _get(oid):
    o = q("""SELECT o.*, c.name AS customer, c.address AS customer_address, c.whatsapp AS customer_phone, c.rep_id AS cust_rep
             FROM orders o JOIN customers c ON c.id = o.customer_id WHERE o.id = ?""", (oid,), one=True) or abort(404)
    if is_rep() and o["created_by"] != g.user["id"]:
        abort(403)
    return o


@bp.route("/<int:oid>")
def view_one(oid):
    o = _get(oid)
    lines = q("SELECT * FROM order_lines WHERE order_id = ? ORDER BY sort", (oid,))
    inv = q("SELECT id, number FROM invoices WHERE id = ?", (o["invoice_id"],), one=True) if o["invoice_id"] else None
    return render_template("orders/view.html", o=o, lines=lines, inv=inv, cur=settings().get("currency", "Rs"))


def make_invoice(customer_id, rep_id, note, lines):
    """Creates a normal invoice (same numbering, due date and tax as a hand-made one) from plain lines. Used by orders and quotations."""
    c = q("SELECT * FROM customers WHERE id = ?", (customer_id,), one=True)
    co = get_company(c["company_id"]) or get_company(default_company_id())
    d = today()
    due = (date.fromisoformat(d) + timedelta(days=c["terms_days"] or 0)).isoformat()
    tax_rate = float(co["default_tax_rate"] or 0) if co["gst_registered"] else 0.0
    subtotal = sum(l["amount"] for l in lines)
    tax = pct_rnd(subtotal, tax_rate)
    iid = x("""INSERT INTO invoices (number, date, due_date, customer_id, rep_id, notes, tax_rate, subtotal, discount, tax, total,
               created_by, created_at, company_id) VALUES (?,?,?,?,?,?,?,?,0,?,?,?,?,?)""",
            (next_invoice_number(co["id"]), d, due, customer_id, rep_id or c["rep_id"], note,
             tax_rate, subtotal, tax, subtotal + tax, g.user["id"], now(), co["id"]))
    for n, l in enumerate(lines, start=1):
        ctn = l["ctn_qty"] if "ctn_qty" in l.keys() else ""
        x("""INSERT INTO invoice_lines (invoice_id, item_id, code, description, unit, ctn_qty, qty, rate, percent, amount, kind, sort)
             VALUES (?,?,?,?,?,?,?,?,NULL,?,'item',?)""", (iid, l["item_id"], l["code"], l["description"], l["unit"], ctn or "", l["qty"], l["rate"], l["amount"], n))
    return iid


def create_invoice(o, lines):
    return make_invoice(o["customer_id"], o["rep_id"], f"From order {o['number']} taken by {o['created_by_name']}" + (f"\nRequest: {o['notes']}" if o["notes"] else ""), lines)


@bp.route("/<int:oid>/approve", methods=["POST"])
def approve(oid):
    o = _get(oid)
    if o["status"] != "Pending":
        flash("This order was already dealt with.", "err")
        return redirect(url_for("orders.view_one", oid=oid))
    lines = q("SELECT * FROM order_lines WHERE order_id = ? ORDER BY sort", (oid,))
    iid = create_invoice(o, lines)
    x("UPDATE orders SET status = 'Approved', decided_by = ?, decided_at = ?, invoice_id = ? WHERE id = ?", (g.user["name"], now(), iid, oid))
    commit()
    n = q("SELECT number FROM invoices WHERE id = ?", (iid,), one=True)["number"]
    flash(f"Order {o['number']} approved. Invoice {n} created.", "ok")
    return redirect(url_for("sales.invoice_view", iid=iid))


@bp.route("/<int:oid>/reject", methods=["POST"])
def reject(oid):
    o = _get(oid)
    if o["status"] == "Pending":
        x("UPDATE orders SET status = 'Rejected', decided_by = ?, decided_at = ?, reject_reason = ? WHERE id = ?",
          (g.user["name"], now(), request.form.get("reason", "").strip(), oid))
        commit()
        flash(f"Order {o['number']} rejected.", "ok")
    return redirect(url_for("orders.view_one", oid=oid))


@bp.route("/<int:oid>/cancel", methods=["POST"])
def cancel(oid):
    o = _get(oid)
    if o["status"] == "Pending":
        x("UPDATE orders SET status = 'Cancelled', decided_by = ?, decided_at = ? WHERE id = ?", (g.user["name"], now(), oid))
        commit()
        flash(f"Order {o['number']} cancelled.", "ok")
    return redirect(url_for("orders.index"))
