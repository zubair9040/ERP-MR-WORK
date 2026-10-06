"""Quotations: price offers for customers or prospects. Deliberately NOT connected to invoices."""
from datetime import date, timedelta

from flask import Blueprint, abort, flash, g, redirect, render_template, request, send_file, url_for

from .companies import companies, default_company_id, get_company, pdf_settings
from .db import commit, fmt, now, parse_date, q, settings, to_paisa, today, x

bp = Blueprint("quotes", __name__, url_prefix="/quotations")

STATUSES = ["Draft", "Sent", "Accepted", "Declined"]


def _next_number():
    return (q("SELECT MAX(number) AS m FROM quotes", one=True)["m"] or 0) + 1


def _items():
    return q("SELECT id, code, name, description, unit, price FROM items WHERE active = 1 AND kind = 'item' ORDER BY code, name")


def _read_lines(f):
    items = {i["id"]: i for i in _items()}
    cols = [f.getlist(k) for k in ("code", "description", "unit", "qty", "price")]
    lines = []
    for n in range(max((len(c) for c in cols), default=0)):
        code, desc, unit, qty, price = (c[n] if n < len(c) else "" for c in cols)
        if not any(str(v).strip() for v in (code, desc, qty, price)):
            continue
        it = next((i for i in items.values() if i["code"] and i["code"].upper() == code.strip().upper()), None)
        try:
            qn = float(str(qty).replace(",", "").strip() or 1)
        except ValueError:
            raise ValueError(f"Line {len(lines) + 1}: quantity must be a number.")
        rate = to_paisa(price) if str(price).strip() else (it["price"] if it else 0)
        lines.append({"item_id": it["id"] if it else None, "code": code.strip(), "unit": unit.strip() or (it["unit"] if it else ""),
                      "description": desc.strip() or (it["description"] or it["name"] if it else ""), "qty": qn, "rate": rate,
                      "amount": int(round(qn * rate)), "sort": len(lines) + 1})
    if not lines:
        raise ValueError("Add at least one item line.")
    return lines


@bp.route("/")
def index():
    where, args = " WHERE 1 = 1", []
    s = request.args.get("q", "").strip()
    st = request.args.get("status", "")
    if s:
        where += " AND (COALESCE(c.name, q.customer_name) LIKE ? OR CAST(q.number AS TEXT) LIKE ? OR q.subject LIKE ?)"
        args += [f"%{s}%"] * 3
    if st in STATUSES:
        where += " AND q.status = ?"
        args.append(st)
    rows = q(f"""SELECT q.*, COALESCE(c.name, q.customer_name) AS party FROM quotes q LEFT JOIN customers c ON c.id = q.customer_id
                 {where} ORDER BY q.id DESC LIMIT 500""", args)
    return render_template("quotes/index.html", rows=rows, s=s, status=st, statuses=STATUSES, cur=settings().get("currency", "Rs"))


def _form(quote, lines, f):
    return render_template("quotes/form.html", quote=quote, lines=lines, f=f, items=_items(), companies=companies(),
                           customers=q("SELECT id, name, address, whatsapp, company_id FROM customers WHERE active = 1 ORDER BY name COLLATE NOCASE"),
                           cur=settings().get("currency", "Rs"))


@bp.route("/new", methods=["GET", "POST"])
@bp.route("/<int:qid>/edit", methods=["GET", "POST"])
def new(qid=None):
    quote = q("SELECT * FROM quotes WHERE id = ?", (qid,), one=True) if qid else None
    if qid and (not quote or quote["void"]):
        abort(404)
    if request.method == "POST":
        f = request.form
        try:
            lines = _read_lines(f)
            cid = f.get("customer_id", type=int)
            c = q("SELECT * FROM customers WHERE id = ?", (cid,), one=True) if cid else None
            name = (f.get("customer_name") or "").strip()
            if not c and not name:
                raise ValueError("Choose a customer, or type the name of the person or company you are quoting.")
            co_id = f.get("company_id", type=int) or (c["company_id"] if c else None) or default_company_id()
            co = get_company(co_id) or get_company(default_company_id())
            tax_rate = float((f.get("tax_rate") or "0").replace("%", "") or 0) if co["gst_registered"] else 0.0
        except ValueError as e:
            flash(str(e), "err")
            return _form(quote, [], f)
        subtotal = sum(l["amount"] for l in lines)
        tax = int(round(subtotal * tax_rate / 100))
        d = parse_date(f.get("date")) or today()
        valid = parse_date(f.get("valid_until")) or (date.fromisoformat(d) + timedelta(days=int(settings().get("quote_valid_days", "15") or 15))).isoformat()
        vals = (d, valid, co["id"], c["id"] if c else None, name if not c else "", f.get("customer_phone", "").strip(),
                f.get("customer_address", "").strip(), f.get("subject", "").strip(), f.get("notes", "").strip(), f.get("terms", "").strip(),
                subtotal, tax_rate, tax, subtotal + tax)
        if quote:
            x("""UPDATE quotes SET date=?, valid_until=?, company_id=?, customer_id=?, customer_name=?, customer_phone=?, customer_address=?,
                 subject=?, notes=?, terms=?, subtotal=?, tax_rate=?, tax=?, total=?, updated_at=? WHERE id=?""", vals + (now(), qid))
            x("DELETE FROM quote_lines WHERE quote_id = ?", (qid,))
        else:
            qid = x("""INSERT INTO quotes (number, date, valid_until, company_id, customer_id, customer_name, customer_phone, customer_address,
                       subject, notes, terms, subtotal, tax_rate, tax, total, status, created_by, created_at)
                       VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,'Draft',?,?)""", (_next_number(),) + vals + (g.user["id"], now()))
        for l in lines:
            x("""INSERT INTO quote_lines (quote_id, item_id, code, description, unit, qty, rate, amount, sort) VALUES (?,?,?,?,?,?,?,?,?)""",
              (qid, l["item_id"], l["code"], l["description"], l["unit"], l["qty"], l["rate"], l["amount"], l["sort"]))
        commit()
        flash("Quotation saved.", "ok")
        return redirect(url_for("quotes.view_one", qid=qid))
    if quote:
        lines = [{"code": l["code"], "description": l["description"], "unit": l["unit"], "qty": f"{l['qty']:g}", "price": f"{l['rate'] / 100:.2f}"}
                 for l in q("SELECT * FROM quote_lines WHERE quote_id = ? ORDER BY sort", (qid,))]
        f = dict(_get(qid))
        return _form(quote, lines, f)
    return _form(None, [], {"date": today()})


def _get(qid):
    quote = q("""SELECT q.*, COALESCE(c.name, q.customer_name) AS party, COALESCE(c.address, q.customer_address) AS addr,
                 COALESCE(c.whatsapp, q.customer_phone) AS phone FROM quotes q LEFT JOIN customers c ON c.id = q.customer_id WHERE q.id = ?""",
              (qid,), one=True)
    return quote or abort(404)


@bp.route("/<int:qid>")
def view_one(qid):
    quote = _get(qid)
    return render_template("quotes/view.html", quote=quote, lines=q("SELECT * FROM quote_lines WHERE quote_id = ? ORDER BY sort", (qid,)),
                           statuses=STATUSES, cur=settings().get("currency", "Rs"))


@bp.route("/<int:qid>.pdf")
def pdf(qid):
    from .notify import _pdf_path
    from .pdfs import quotation
    quote = _get(qid)
    lines = q("SELECT * FROM quote_lines WHERE quote_id = ? ORDER BY sort", (qid,))
    return send_file(quotation(_pdf_path(f"Quotation_{quote['number']}.pdf"), pdf_settings(quote["company_id"]), quote, lines),
                     mimetype="application/pdf")


@bp.route("/<int:qid>/status", methods=["POST"])
def status(qid):
    st = request.form.get("status")
    if st in STATUSES:
        x("UPDATE quotes SET status = ?, updated_at = ? WHERE id = ?", (st, now(), qid))
        commit()
    return redirect(url_for("quotes.view_one", qid=qid))


@bp.route("/<int:qid>/void", methods=["POST"])
def void(qid):
    x("UPDATE quotes SET void = 1, updated_at = ? WHERE id = ?", (now(), qid))
    commit()
    flash("Quotation voided.", "ok")
    return redirect(url_for("quotes.index"))


@bp.route("/<int:qid>/to-invoice", methods=["POST"])
def to_invoice(qid):
    """Turns this quotation into a real invoice (once). Needs an existing customer."""
    from .orders import make_invoice
    quote = _get(qid)
    if quote["void"]:
        abort(404)
    if quote["invoice_id"]:
        flash("This quotation was already turned into an invoice.", "err")
        return redirect(url_for("sales.invoice_view", iid=quote["invoice_id"]))
    if not quote["customer_id"]:
        flash("This quotation is for someone who is not a customer yet. Add them under Customers, then edit the quotation and pick them.", "err")
        return redirect(url_for("quotes.view_one", qid=qid))
    lines = q("SELECT * FROM quote_lines WHERE quote_id = ? ORDER BY sort", (qid,))
    iid = make_invoice(quote["customer_id"], None, f"From quotation {quote['number']}" + (f"\n{quote['subject']}" if quote["subject"] else ""), lines)
    x("UPDATE quotes SET status = 'Accepted', invoice_id = ?, updated_at = ? WHERE id = ?", (iid, now(), qid))
    commit()
    n = q("SELECT number FROM invoices WHERE id = ?", (iid,), one=True)["number"]
    flash(f"Invoice {n} created from quotation {quote['number']}.", "ok")
    return redirect(url_for("sales.invoice_view", iid=iid))
