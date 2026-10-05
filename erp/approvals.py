"""Void / delete with admin approval.

Staff who press Void (or Delete) on an invoice, payment, return or supplier payment don't change anything: a request
goes to the admin. When the admin approves, the document is voided (it leaves every balance but stays in the history,
so nothing can be erased without a trace). Users whose role has "Approve voids" void directly.
"""
from flask import Blueprint, abort, flash, g, redirect, render_template, request, url_for

from .db import commit, fmt, now, q, x

bp = Blueprint("ap", __name__, url_prefix="/approvals")

KINDS = {
    "invoice": ("Invoice", "invoices", "number", "total", "sales.invoice_view", "iid"),
    "payment": ("Payment received", "payments", "number", "amount", "sales.payment_view", "pid"),
    "credit": ("Sales return", "credit_notes", "number", "total", "ops.credit_view", "did"),
    "supplier_payment": ("Supplier payment", "supplier_payments", "id", "amount", "ops.supplier_payments", None),
}


def can_approve():
    from .perms import has
    return has("approve.voids")


def doc_row(kind, ref_id):
    label, table, num, amt, ep, arg = KINDS[kind]
    return q(f"SELECT * FROM {table} WHERE id = ?", (ref_id,), one=True)


def doc_url(kind, ref_id):
    label, table, num, amt, ep, arg = KINDS[kind]
    return url_for(ep, **({arg: ref_id} if arg else {}))


def pending_for(kind, ref_id):
    return q("SELECT * FROM void_requests WHERE kind = ? AND ref_id = ? AND status = 'pending'", (kind, ref_id), one=True)


def pending_count():
    return q("SELECT COUNT(*) AS n FROM void_requests WHERE status = 'pending'", one=True)["n"]


def _do_void(kind, ref_id, reason, by_name):
    label, table, *_ = KINDS[kind]
    row = doc_row(kind, ref_id)
    if not row or row["void"]:
        return False
    tag = f"VOIDED {now()} by {by_name}: {reason}"
    note = (row["notes"] + "\n" if row["notes"] else "") + tag
    if table == "invoices":
        x("UPDATE invoices SET void = 1, notes = ?, updated_at = ? WHERE id = ?", (note, now(), ref_id))
    else:
        x(f"UPDATE {table} SET void = 1, notes = ? WHERE id = ?", (note, ref_id))
    return True


def void_or_request(kind, ref_id, reason):
    """Called by every Void button. Returns the flash message shown to the user."""
    label = KINDS[kind][0]
    row = doc_row(kind, ref_id) or abort(404)
    number = row[KINDS[kind][2]]
    if row["void"]:
        return f"{label} {number} is already void.", "err"
    if can_approve():
        _do_void(kind, ref_id, reason, g.user["name"])
        x("UPDATE void_requests SET status = 'approved', decided_by = ?, decided_at = ?, decision_note = 'voided directly' "
          "WHERE kind = ? AND ref_id = ? AND status = 'pending'", (g.user["name"], now(), kind, ref_id))
        commit()
        return f"{label} {number} voided.", "ok"
    if pending_for(kind, ref_id):
        return f"A void request for {label.lower()} {number} is already waiting for the admin.", "err"
    x("""INSERT INTO void_requests (kind, ref_id, reason, requested_by, requested_name, requested_at, status)
         VALUES (?,?,?,?,?,?, 'pending')""", (kind, ref_id, reason, g.user["id"], g.user["name"], now()))
    commit()
    return f"Void request for {label.lower()} {number} sent to the admin for approval. Nothing changes until it is approved.", "ok"


@bp.route("/")
def index():
    if not can_approve():
        rows = q("SELECT * FROM void_requests WHERE requested_by = ? ORDER BY id DESC LIMIT 200", (g.user["id"],))
    else:
        st = request.args.get("status", "pending")
        rows = q("SELECT * FROM void_requests WHERE (? = 'all' OR status = ?) ORDER BY status = 'pending' DESC, id DESC LIMIT 300", (st, st))
    out = []
    for r in rows:
        kind = KINDS.get(r["kind"])
        d = doc_row(r["kind"], r["ref_id"]) if kind else None
        cust = ""
        if d is not None and "customer_id" in d.keys():
            c = q("SELECT name FROM customers WHERE id = ?", (d["customer_id"],), one=True)
            cust = c["name"] if c else ""
        elif d is not None and "supplier_id" in d.keys():
            c = q("SELECT name FROM suppliers WHERE id = ?", (d["supplier_id"],), one=True)
            cust = c["name"] if c else ""
        out.append({"r": r, "label": kind[0] if kind else r["kind"], "doc": d, "party": cust,
                    "number": d[kind[2]] if d is not None else "?", "amount": d[kind[3]] if d is not None else 0,
                    "date": d["date"] if d is not None else "", "url": doc_url(r["kind"], r["ref_id"]) if d is not None else "#"})
    return render_template("approvals.html", rows=out, approver=can_approve(), status=request.args.get("status", "pending"))


@bp.route("/<int:rid>/<decision>", methods=["POST"])
def decide(rid, decision):
    if not can_approve():
        abort(403)
    r = q("SELECT * FROM void_requests WHERE id = ? AND status = 'pending'", (rid,), one=True)
    if not r:
        flash("That request was already handled.", "err")
        return redirect(url_for("ap.index"))
    note = request.form.get("note", "").strip()
    label = KINDS[r["kind"]][0]
    if decision == "approve":
        _do_void(r["kind"], r["ref_id"], f"{r['reason']} (requested by {r['requested_name']}, approved by {g.user['name']})", g.user["name"])
        x("UPDATE void_requests SET status = 'approved', decided_by = ?, decided_at = ?, decision_note = ? WHERE id = ?",
          (g.user["name"], now(), note, rid))
        flash(f"Approved: {label.lower()} voided.", "ok")
    else:
        x("UPDATE void_requests SET status = 'rejected', decided_by = ?, decided_at = ?, decision_note = ? WHERE id = ?",
          (g.user["name"], now(), note, rid))
        flash("Request rejected. Nothing was changed.", "ok")
    commit()
    return redirect(url_for("ap.index"))


@bp.route("/<int:rid>/cancel", methods=["POST"])
def cancel(rid):
    r = q("SELECT * FROM void_requests WHERE id = ? AND status = 'pending'", (rid,), one=True) or abort(404)
    if r["requested_by"] != g.user["id"] and not can_approve():
        abort(403)
    x("UPDATE void_requests SET status = 'cancelled', decided_by = ?, decided_at = ? WHERE id = ?", (g.user["name"], now(), rid))
    commit()
    flash("Request cancelled.", "ok")
    return redirect(request.referrer or url_for("ap.index"))
