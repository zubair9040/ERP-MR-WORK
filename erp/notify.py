"""Builds PDFs and sends them to customers on WhatsApp (Meta WhatsApp Business Cloud API)."""
import os
import re

import requests
from flask import current_app, g

from . import pdfs
from .db import commit, fmt, nice_date, now, q, settings, x
from .ledger import balance, customer_aging, open_items, open_statement, statement


def normalize(raw, country_code=None):
    """'0300-1234567' / '+92 300 1234567' -> '923001234567'. Returns None if it can't be a phone number."""
    if not raw:
        return None
    cc = country_code or settings().get("country_code", "92") or "92"
    digits = re.sub(r"\D", "", str(raw))
    if digits.startswith("00"):
        digits = digits[2:]
    elif digits.startswith("0"):
        digits = cc + digits[1:]
    elif len(digits) == 10 and not digits.startswith(cc):
        digits = cc + digits
    return digits if 10 <= len(digits) <= 15 else None


def _safe(s):
    return re.sub(r"[^A-Za-z0-9_-]+", "_", str(s)).strip("_")[:50] or "file"


def _pdf_path(name):
    return os.path.join(current_app.config["PDF_DIR"], name)


def invoice_pdf(iid):
    inv = q("SELECT * FROM invoices WHERE id = ?", (iid,), one=True)
    c = q("SELECT * FROM customers WHERE id = ?", (inv["customer_id"],), one=True)
    rep = q("SELECT * FROM reps WHERE id = ?", (inv["rep_id"],), one=True) if inv["rep_id"] else None
    lines = q("SELECT * FROM invoice_lines WHERE invoice_id = ? ORDER BY sort", (iid,))
    open_amt = open_items(inv["customer_id"])[0].get(iid, 0)
    from .companies import co_images, co_settings
    from .docdata import invoice_data
    s, imgs = co_settings(inv["company_id"]), co_images(inv["company_id"])
    name = f"Invoice_{s.get('company_code', '')}_{inv['number']}.pdf"
    return (_designed("invoice", inv["company_id"], name, lambda: invoice_data(s, inv, lines, c, rep, open_amt, imgs))
            or pdfs.invoice(_pdf_path(name), s, inv, lines, c, rep, open_amt, imgs))


def receipt_parts(pid):
    """Customer, which bills the receipt paid, and the balance before / after it."""
    from .ledger import apply_payments
    p = q("SELECT * FROM payments WHERE id = ?", (pid,), one=True)
    c = q("SELECT * FROM customers WHERE id = ?", (p["customer_id"],), one=True)
    ap = apply_payments(p["customer_id"])
    applied = []
    for inv_id, amt in ap["applied"].get(pid, []):
        if inv_id is None:
            applied.append({"label": "Opening balance", "date": c["opening_date"], "total": None, "amount": amt, "left": None})
        else:
            i = q("SELECT number, date, total FROM invoices WHERE id = ?", (inv_id,), one=True)
            applied.append({"label": f"Invoice #{i['number']}", "date": i["date"], "total": i["total"], "amount": amt,
                            "left": ap["open"].get(inv_id, 0)})
    after = balance(p["customer_id"], p["date"])
    before = None if p["void"] else after + p["amount"]
    return c, applied, before, after


def _designed(doc, company_id, name, build):
    """If a designed layout is switched on for this document, print with it."""
    from .docdata import active_layout, preset
    layout = active_layout(doc, company_id)
    if not layout:
        if settings().get("print_classic") == "1":
            return None
        layout = preset("modern", doc)
    from .layout_pdf import add_font_dir, render
    from flask import current_app
    add_font_dir(os.path.join(current_app.config["DATA_DIR"], "fonts"))
    return render(_pdf_path(name), layout, build())


def receipt_pdf(pid):
    from .companies import co_images, co_settings
    from .docdata import receipt_data
    p = q("SELECT * FROM payments WHERE id = ?", (pid,), one=True)
    c, applied, before, after = receipt_parts(pid)
    s, imgs = co_settings(c["company_id"]), co_images(c["company_id"])
    name = f"Receipt_{p['number']}.pdf"
    return (_designed("receipt", c["company_id"], name, lambda: receipt_data(s, p, c, applied, before, after, imgs))
            or pdfs.receipt(_pdf_path(name), s, p, c, after, applied, imgs, before))


def deliver_to(c, inv):
    """For a branch delivery the challan goes to the branch: its name, address and phone replace head office's."""
    if not inv["branch_id"]:
        return c
    b = q("SELECT * FROM customer_branches WHERE id = ?", (inv["branch_id"],), one=True)
    if not b:
        return c
    d = dict(c)
    d.update(name=f"{c['name']} - {b['name']}", address=b["address"] or c["address"],
             phone=b["phone"] or c["phone"], whatsapp=b["phone"] or c["whatsapp"])
    return d


def dc_pdf(iid):
    from .core import image_path
    inv = q("SELECT * FROM invoices WHERE id = ?", (iid,), one=True)
    c = q("SELECT * FROM customers WHERE id = ?", (inv["customer_id"],), one=True)
    lines = q("SELECT * FROM invoice_lines WHERE invoice_id = ? ORDER BY sort", (iid,))
    from .companies import co_images, co_settings
    from .docdata import invoice_data
    s, imgs = co_settings(inv["company_id"]), co_images(inv["company_id"])
    name = f"DC_{s.get('company_code', '')}_{inv['number']}.pdf"
    c = deliver_to(c, inv)
    rep = q("SELECT * FROM reps WHERE id = ?", (inv["rep_id"],), one=True) if inv["rep_id"] else None
    return (_designed("dc", inv["company_id"], name, lambda: invoice_data(s, inv, lines, c, rep, None, imgs, "dc"))
            or pdfs.delivery_challan(_pdf_path(name), s, inv, lines, c, imgs))


def statement_data(cid, start, end, mode="period", opts=None):
    """Everything a statement needs, for PDF, Excel or WhatsApp. opts: aging (bool), details (bool)."""
    opts = {"aging": True, "details": False, **(opts or {})}
    c = q("SELECT * FROM customers WHERE id = ?", (cid,), one=True)
    st = open_statement(cid, end) if mode == "open" else statement(cid, start, end)
    aging = customer_aging(cid, end, basis="invoice") if opts["aging"] else None
    details = None
    if opts["details"]:
        ids = [l["id"] for l in st["lines"] if l["type"] == "Invoice" and l.get("id")]
        details = {}
        if ids:
            for d in q(f"SELECT * FROM invoice_lines WHERE invoice_id IN ({','.join('?' * len(ids))}) ORDER BY invoice_id, sort", ids):
                details.setdefault(d["invoice_id"], []).append(d)
    return c, st, aging, details


def _statement(cid, start, end, mode="period", opts=None):
    c, st, aging, details = statement_data(cid, start, end, mode, opts)
    suffix = "_unpaid" if mode == "open" else ""
    from .companies import co_images, co_settings
    path = pdfs.statement(_pdf_path(f"Statement_{_safe(c['name'])}_{end}{suffix}.pdf"), co_settings(c["company_id"]), c, st, aging,
                          details, co_images(c["company_id"]))
    return c, st, path


def statement_pdf(cid, start, end, mode="period", opts=None):
    return _statement(cid, start, end, mode, opts)[2]


def last_sent(kind, ref_id, period=None):
    sql = "SELECT created_at FROM messages WHERE kind = ? AND ref_id = ? AND status IN ('sent', 'test')"
    args = [kind, ref_id]
    if period:
        sql += " AND period = ?"
        args.append(period)
    r = q(sql + " ORDER BY id DESC LIMIT 1", args, one=True)
    return r["created_at"] if r else None


def _log(kind, customer_id, ref_id, phone, status, detail, period="", channel="whatsapp", supplier_id=None):
    user = g.user["name"] if g.get("user") else "system"
    x("""INSERT INTO messages (created_at, kind, customer_id, ref_id, period, phone, status, detail, user, channel, supplier_id)
         VALUES (?,?,?,?,?,?,?,?,?,?,?)""", (now(), kind, customer_id, ref_id, period, phone or "", status, detail, user, channel, supplier_id))
    commit()


class WhatsAppError(Exception):
    pass


def _send_document(to, template, pdf_path, body_params):
    s = settings()
    if s.get("wa_dry_run") == "1":
        return None
    pnid, token = s.get("wa_phone_number_id", "").strip(), s.get("wa_access_token", "").strip()
    if not (pnid and token):
        raise WhatsAppError("WhatsApp isn't set up yet. Add the phone number ID and access token in Settings.")
    base = f"https://graph.facebook.com/{s.get('wa_api_version') or 'v21.0'}/{pnid}"
    headers = {"Authorization": f"Bearer {token}"}
    filename = os.path.basename(pdf_path) if pdf_path else ""

    def check(r):
        try:
            data = r.json()
        except ValueError:
            data = {}
        if r.status_code >= 400 or "error" in data:
            err = data.get("error", {}) if isinstance(data, dict) else {}
            detail = err.get("error_data", {}).get("details") if isinstance(err.get("error_data"), dict) else None
            raise WhatsAppError("WhatsApp refused: " + (detail or err.get("message") or r.text[:200]))
        return data

    try:
        components = [{"type": "body", "parameters": [{"type": "text", "text": str(p)} for p in body_params]}]
        if pdf_path:
            with open(pdf_path, "rb") as fh:
                up = requests.post(f"{base}/media", headers=headers, timeout=60,
                                   data={"messaging_product": "whatsapp", "type": "application/pdf"},
                                   files={"file": (filename, fh, "application/pdf")})
            media_id = check(up)["id"]
            components.insert(0, {"type": "header", "parameters": [
                {"type": "document", "document": {"id": media_id, "filename": filename}}]})
        payload = {
            "messaging_product": "whatsapp", "to": to, "type": "template",
            "template": {"name": template, "language": {"code": s.get("wa_language") or "en"}, "components": components},
        }
        return check(requests.post(f"{base}/messages", headers=headers, json=payload, timeout=30))["messages"][0]["id"]
    except requests.RequestException as e:
        raise WhatsAppError(f"Couldn't reach WhatsApp (internet problem?): {e}")


def _deliver(kind, customer, ref_id, phone, template, pdf_path, params, label, period=""):
    to = normalize(phone or customer["whatsapp"])
    if not to:
        msg = f"{customer['name']} has no valid WhatsApp number."
        _log(kind, customer["id"], ref_id, phone, "failed", msg, period)
        return False, msg
    try:
        mid = _send_document(to, template, pdf_path, params)
    except WhatsAppError as e:
        _log(kind, customer["id"], ref_id, to, "failed", str(e), period)
        return False, f"{label} not sent to {customer['name']}: {e}"
    if mid is None:
        _log(kind, customer["id"], ref_id, to, "test", "test mode - not sent", period)
        return True, f"{label} ready for +{to} (test mode: not actually sent)."
    _log(kind, customer["id"], ref_id, to, "sent", mid, period)
    return True, f"{label} sent to {customer['name']} on WhatsApp (+{to})."


def send_invoice(iid, phone=None):
    inv = q("SELECT * FROM invoices WHERE id = ?", (iid,), one=True)
    c = q("SELECT * FROM customers WHERE id = ?", (inv["customer_id"],), one=True)
    cur = settings().get("currency", "Rs")
    params = [c["name"], inv["number"], f"{cur} {fmt(inv['total'])}", nice_date(inv["due_date"] or inv["date"])]
    return _deliver("invoice", c, iid, phone, settings().get("wa_invoice_template"), invoice_pdf(iid), params,
                    f"Invoice {inv['number']}")


def send_receipt(pid, phone=None):
    p = q("SELECT * FROM payments WHERE id = ?", (pid,), one=True)
    c = q("SELECT * FROM customers WHERE id = ?", (p["customer_id"],), one=True)
    cur = settings().get("currency", "Rs")
    params = [c["name"], f"{cur} {fmt(p['amount'])}", nice_date(p["date"]), f"{cur} {fmt(balance(c['id']))}"]
    return _deliver("receipt", c, pid, phone, settings().get("wa_receipt_template"), receipt_pdf(pid), params,
                    f"Receipt {p['number']}")


def send_statement(cid, start, end, phone=None, mode="period", opts=None):
    c, st, path = _statement(cid, start, end, mode, opts)
    cur = settings().get("currency", "Rs")
    params = [c["name"], f"{cur} {fmt(st['closing'])}", nice_date(end)]
    return _deliver("statement", c, cid, phone, settings().get("wa_statement_template"), path, params,
                    "Statement", period=f"{start}..{end}")


def default_period(customer):
    """Period used by the one-click statement button: from the 1st of last month to today."""
    from datetime import date, timedelta
    t = date.today()
    start = (t.replace(day=1) - timedelta(days=1)).replace(day=1)
    return start.isoformat(), t.isoformat(), ("open" if customer["statement_mode"] == "open" else "period")


def send_quick_statement(cid, phone=None):
    c = q("SELECT * FROM customers WHERE id = ?", (cid,), one=True)
    start, end, mode = default_period(c)
    return send_statement(cid, start, end, phone, mode)


def send_balance(cid, phone=None):
    """Short balance message (no attachment)."""
    from datetime import date
    c = q("SELECT * FROM customers WHERE id = ?", (cid,), one=True)
    cur = settings().get("currency", "Rs")
    today_s = date.today().isoformat()
    params = [c["name"], f"{cur} {fmt(balance(cid))}", nice_date(today_s)]
    return _deliver("balance", c, cid, phone, settings().get("wa_balance_template") or "balance_reminder", None, params,
                    "Balance message", period=today_s)


# ---- email (Gmail or any SMTP server) ------------------------------------------------------------
class EmailError(Exception):
    pass


EMAIL_RE = re.compile(r"^[^@\s,;]+@[^@\s,;]+\.[^@\s,;]+$")


def valid_emails(raw):
    out = [e.strip() for e in re.split(r"[,;\s]+", raw or "") if e.strip()]
    return [e for e in out if EMAIL_RE.match(e)]


def _send_mail(to_list, subject, body, pdf_paths, s):
    """Returns None in test mode, 'sent' when the server accepted the email."""
    import smtplib
    from email.message import EmailMessage
    from email.utils import formataddr
    if s.get("email_dry_run") == "1":
        return None
    user, pw = (s.get("smtp_user") or "").strip(), (s.get("smtp_password") or "").replace(" ", "").strip()
    if not (user and pw):
        raise EmailError("Email isn't set up yet. Add the Gmail address and App Password in Settings → Email.")
    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = formataddr((s.get("email_from_name") or s.get("company_name") or "", user))
    msg["To"] = ", ".join(to_list)
    cc = valid_emails(s.get("email_cc"))
    if cc:
        msg["Cc"] = ", ".join(cc)
    msg.set_content(body)
    for p in pdf_paths or []:
        with open(p, "rb") as fh:
            msg.add_attachment(fh.read(), maintype="application", subtype="pdf", filename=os.path.basename(p))
    host, port = s.get("smtp_host") or "smtp.gmail.com", int(s.get("smtp_port") or 587)
    try:
        if port == 465:
            server = smtplib.SMTP_SSL(host, port, timeout=40)
        else:
            server = smtplib.SMTP(host, port, timeout=40)
            server.starttls()
        with server:
            server.login(user, pw)
            server.send_message(msg)
    except smtplib.SMTPAuthenticationError:
        raise EmailError("Gmail refused the login. Check the Gmail address, and use an App Password (not your normal password).")
    except (smtplib.SMTPException, OSError) as e:
        raise EmailError(f"Couldn't send the email (internet problem?): {e}")
    return "sent"


def _email_body(s, c, lines):
    sig = s.get("email_signature") or ""
    return f"Dear {c['contact'] or c['name']},\n\n" + "\n".join(lines) + f"\n\n{sig}\n{s.get('company_name', '')}\n{s.get('company_phone', '')}"


def _deliver_email(kind, c, ref_id, to, subject, lines, pdf_path, label, period=""):
    from .companies import co_settings
    s = co_settings(c["company_id"])
    to_list = valid_emails(to or c["email"])
    if not to_list:
        msg = f"{c['name']} has no email address. Add it on the customer's page."
        _log(kind, c["id"], ref_id, to or "", "failed", msg, period, "email")
        return False, msg
    try:
        res = _send_mail(to_list, subject, _email_body(s, c, lines), [pdf_path] if pdf_path else [], s)
    except EmailError as e:
        _log(kind, c["id"], ref_id, ", ".join(to_list), "failed", str(e), period, "email")
        return False, f"{label} not emailed to {c['name']}: {e}"
    shown = ", ".join(to_list)
    if res is None:
        _log(kind, c["id"], ref_id, shown, "test", "test mode - not sent", period, "email")
        return True, f"{label} ready for {shown} (email test mode: not actually sent)."
    _log(kind, c["id"], ref_id, shown, "sent", "sent", period, "email")
    return True, f"{label} emailed to {c['name']} ({shown})."


def email_invoice(iid, to=None):
    from .companies import co_settings
    inv = q("SELECT * FROM invoices WHERE id = ?", (iid,), one=True)
    c = q("SELECT * FROM customers WHERE id = ?", (inv["customer_id"],), one=True)
    s = co_settings(inv["company_id"])
    cur = s.get("currency", "Rs")
    po = f" (PO {inv['po_no']})" if inv["po_no"] else ""
    lines = [f"Please find attached invoice no. {inv['number']}{po} dated {nice_date(inv['date'])}.",
             f"Amount: {cur} {fmt(inv['total'])}. Due date: {nice_date(inv['due_date'] or inv['date'])}."]
    return _deliver_email("invoice", c, iid, to, f"Invoice {inv['number']}{po} from {s.get('company_name', '')}", lines,
                          invoice_pdf(iid), f"Invoice {inv['number']}")


def email_receipt(pid, to=None):
    from .companies import co_settings
    p = q("SELECT * FROM payments WHERE id = ?", (pid,), one=True)
    c = q("SELECT * FROM customers WHERE id = ?", (p["customer_id"],), one=True)
    s = co_settings(c["company_id"])
    cur = s.get("currency", "Rs")
    lines = [f"Thank you for your payment of {cur} {fmt(p['amount'])} received on {nice_date(p['date'])}.",
             f"Your balance now is {cur} {fmt(balance(c['id']))}. The receipt is attached."]
    return _deliver_email("receipt", c, pid, to, f"Payment receipt {p['number']} from {s.get('company_name', '')}", lines,
                          receipt_pdf(pid), f"Receipt {p['number']}")


def email_statement(cid, start, end, to=None, mode="period", opts=None):
    from .companies import co_settings
    c, st, path = _statement(cid, start, end, mode, opts)
    s = co_settings(c["company_id"])
    cur = s.get("currency", "Rs")
    what = "a list of your unpaid bills" if mode == "open" else f"your statement from {nice_date(start)} to {nice_date(end)}"
    lines = [f"Please find attached {what}.", f"Amount due: {cur} {fmt(st['closing'])}."]
    return _deliver_email("statement", c, cid, to, f"Statement of account - {s.get('company_name', '')}", lines, path,
                          "Statement", period=f"{start}..{end}")


def email_balance(cid, to=None):
    from datetime import date
    from .companies import co_settings
    c = q("SELECT * FROM customers WHERE id = ?", (cid,), one=True)
    s = co_settings(c["company_id"])
    cur = s.get("currency", "Rs")
    lines = [f"Your balance with us as of {nice_date(date.today().isoformat())} is {cur} {fmt(balance(cid))}."]
    return _deliver_email("balance", c, cid, to, f"Account balance - {s.get('company_name', '')}", lines, None, "Balance",
                          period=date.today().isoformat())


def send_by(c, whatsapp_fn, email_fn):
    """Sends using the customer's preferred channel(s). Returns a list of (ok, message)."""
    pref = (c["send_by"] if "send_by" in c.keys() else None) or "whatsapp"
    out = []
    if pref in ("whatsapp", "both"):
        out.append(whatsapp_fn())
    if pref in ("email", "both"):
        out.append(email_fn())
    return out
