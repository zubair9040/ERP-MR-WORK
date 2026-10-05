"""Supplier paperwork: account statement, purchase bill and payment advice as PDF, and sending them on WhatsApp."""
from datetime import date

from flask import Blueprint, abort, flash, redirect, request, send_file, url_for

from . import notify
from .db import fmt, nice_date, parse_date, q, settings, today

bp = Blueprint("sup", __name__)


def _sup(sid):
    s = q("SELECT * FROM suppliers WHERE id = ?", (sid,), one=True)
    if not s:
        abort(404)
    return s


def supplier_ledger(sid, start=None, end=None):
    """Opening balance, bills (we owe more) and payments (we owe less) with a running balance."""
    s = _sup(sid)
    end = end or today()
    ev = []
    if s["opening_balance"]:
        ev.append({"date": s["opening_date"] or "2000-01-01", "type": "Opening balance", "ref": "", "debit": max(s["opening_balance"], 0),
                   "credit": max(-s["opening_balance"], 0), "k": 0})
    for b in q("SELECT * FROM purchases WHERE supplier_id = ? AND void = 0", (sid,)):
        ev.append({"date": b["date"], "type": "Bill", "ref": str(b["number"]) + (f" ({b['bill_no']})" if b["bill_no"] else ""),
                   "due": b["due_date"], "debit": b["total"], "credit": 0, "k": 1, "id": b["id"]})
    for p in q("SELECT * FROM supplier_payments WHERE supplier_id = ? AND void = 0", (sid,)):
        ev.append({"date": p["date"], "type": "Payment", "ref": str(p["number"]), "method": p["method"], "reference": p["reference"],
                   "debit": 0, "credit": p["amount"], "k": 2, "id": p["id"]})
    ev.sort(key=lambda e: (e["date"], e["k"]))
    bf, run, lines = 0, 0, []
    for e in ev:
        if e["date"] > end:
            continue
        run += e["debit"] - e["credit"]
        if start and e["date"] < start:
            bf = run
            continue
        lines.append({**e, "balance": run})
    return s, {"start": start or (lines[0]["date"] if lines else end), "end": end, "brought_forward": bf, "lines": lines,
               "closing": run, "billed": sum(l["debit"] for l in lines), "paid": sum(l["credit"] for l in lines)}


def statement_pdf(sid, start=None, end=None, mode="period"):
    from .companies import pdf_settings
    from .ops import supplier_open_bills
    from .pdfs import supplier_statement
    s, st = supplier_ledger(sid, start if mode == "period" else None, end)
    unpaid = None
    if mode == "open":
        bills, opening_left, advance = supplier_open_bills(sid)
        unpaid = {"bills": [b for b in bills if b["open"]], "opening": opening_left, "advance": advance}
    co = settings().get("default_purchase_company")
    path = notify._pdf_path(f"Supplier_{notify._safe(s['name'])}_{st['end']}.pdf")
    return supplier_statement(path, pdf_settings(int(co) if co and str(co).isdigit() else None), s, st, unpaid), s, st


def _period():
    t = date.today()
    start = parse_date(request.values.get("from")) or t.replace(day=1).replace(month=1).isoformat()
    end = parse_date(request.values.get("to")) or t.isoformat()
    mode = request.values.get("mode") if request.values.get("mode") in ("period", "open", "all") else "all"
    if mode == "all":
        return None, end, "period"
    return start, end, mode


@bp.route("/suppliers/<int:sid>/statement.pdf")
def supplier_statement_pdf(sid):
    start, end, mode = _period()
    path, _, _ = statement_pdf(sid, start, end, mode)
    return send_file(path, mimetype="application/pdf")


def _wa(supplier, kind, ref_id, pdf, params, label):
    to = notify.normalize(request.form.get("phone") or supplier["whatsapp"] or supplier["phone"])
    tpl = settings().get("wa_supplier_template") or settings().get("wa_statement_template")
    if not to:
        notify._log(kind, None, ref_id, "", "failed", f"{supplier['name']}: no WhatsApp number", supplier_id=supplier["id"])
        return False, f"{supplier['name']} has no valid WhatsApp number. Add it on the supplier's page."
    try:
        mid = notify._send_document(to, tpl, pdf, params)
    except notify.WhatsAppError as e:
        notify._log(kind, None, ref_id, to, "failed", str(e), supplier_id=supplier["id"])
        return False, f"{label} not sent to {supplier['name']}: {e}"
    if mid is None:
        notify._log(kind, None, ref_id, to, "test", "test mode - not sent", supplier_id=supplier["id"])
        return True, f"{label} ready for +{to} (test mode: not actually sent)."
    notify._log(kind, None, ref_id, to, "sent", mid, supplier_id=supplier["id"])
    return True, f"{label} sent to {supplier['name']} on WhatsApp (+{to})."


@bp.route("/suppliers/<int:sid>/whatsapp", methods=["POST"])
def supplier_whatsapp(sid):
    start, end, mode = _period()
    path, s, st = statement_pdf(sid, start, end, mode)
    cur = settings().get("currency", "Rs")
    ok, msg = _wa(s, "sup_statement", sid, path, [s["name"], f"{cur} {fmt(st['closing'])}", nice_date(st["end"])], "Account statement")
    flash(msg, "ok" if ok else "err")
    back = request.form.get("back", "")
    return redirect(back if back.startswith("/") and not back.startswith("//") else url_for("ops.supplier_view", sid=sid))


@bp.route("/purchases/<int:did>.pdf")
def purchase_pdf(did):
    from .companies import pdf_settings
    from .ops import supplier_open_bills
    from .pdfs import purchase_bill
    b = q("SELECT * FROM purchases WHERE id = ?", (did,), one=True) or abort(404)
    s = _sup(b["supplier_id"])
    lines = q("SELECT * FROM purchase_lines WHERE purchase_id = ? ORDER BY sort", (did,))
    bills, _, _ = supplier_open_bills(s["id"])
    open_amt = next((x["open"] for x in bills if x["b"]["id"] == did), 0)
    path = notify._pdf_path(f"PurchaseBill_{b['number']}.pdf")
    return send_file(purchase_bill(path, pdf_settings(b["company_id"]), b, lines, s, open_amt), mimetype="application/pdf")


def _payment_pdf(yid):
    from .companies import pdf_settings
    from .ops import supplier_balance, supplier_open_bills
    from .pdfs import supplier_payment_advice
    y = q("SELECT * FROM supplier_payments WHERE id = ?", (yid,), one=True) or abort(404)
    s = _sup(y["supplier_id"])
    bills, _, _ = supplier_open_bills(s["id"])
    path = notify._pdf_path(f"PaymentAdvice_{y['number']}.pdf")
    return supplier_payment_advice(path, pdf_settings(y["company_id"]), y, s, supplier_balance(s["id"]),
                                   [b for b in bills if b["open"]]), y, s


@bp.route("/supplier-payments/<int:yid>.pdf")
def supplier_payment_pdf(yid):
    return send_file(_payment_pdf(yid)[0], mimetype="application/pdf")


@bp.route("/supplier-payments/<int:yid>/whatsapp", methods=["POST"])
def supplier_payment_whatsapp(yid):
    path, y, s = _payment_pdf(yid)
    cur = settings().get("currency", "Rs")
    ok, msg = _wa(s, "sup_payment", yid, path, [s["name"], f"{cur} {fmt(y['amount'])}", nice_date(y["date"])], "Payment advice")
    flash(msg, "ok" if ok else "err")
    return redirect(request.referrer or url_for("ops.supplier_view", sid=s["id"]))
