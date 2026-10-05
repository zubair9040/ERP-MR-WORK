"""Import customers, items and open invoices from QuickBooks Excel / CSV exports."""
import csv
import io
import json
import os
import re
import secrets
from datetime import date, datetime, timedelta

from flask import Blueprint, current_app, flash, g, redirect, render_template, request, url_for

from .auth import roles
from .db import commit, next_number, now, q, to_paisa, x

bp = Blueprint("importer", __name__, url_prefix="/import")

KINDS = {
    "customers": "Customers (QuickBooks: Reports > List > Customer Contact List)",
    "items": "Items (QuickBooks: Reports > List > Item Price List, or Lists > Item List > Excel)",
    "open_invoices": "Open invoices / bill-wise balances (QuickBooks: Reports > Customers & Receivables > Open Invoices)",
}


# ---- reading files ----------------------------------------------------------------------------
def read_table(file_storage):
    name = (file_storage.filename or "").lower()
    raw = file_storage.read()
    if name.endswith((".xlsx", ".xlsm")):
        import openpyxl
        wb = openpyxl.load_workbook(io.BytesIO(raw), data_only=True, read_only=True)
        ws = wb.worksheets[0]
        return [["" if v is None else v for v in row] for row in ws.iter_rows(values_only=True)]
    if name.endswith(".xls"):
        raise ValueError("Old .xls files aren't supported. In Excel choose File > Save As > Excel Workbook (.xlsx), "
                         "or export from QuickBooks as CSV.")
    for enc in ("utf-8-sig", "cp1252"):
        try:
            text = raw.decode(enc)
            break
        except UnicodeDecodeError:
            continue
    return [row for row in csv.reader(io.StringIO(text))]


def norm(h):
    return re.sub(r"[^a-z0-9/]+", " ", str(h or "").lower()).strip()


def find_header(rows, must_any):
    for n, row in enumerate(rows[:30]):
        cells = [norm(c) for c in row]
        if any(any(m == c or c.startswith(m) for c in cells) for m in must_any):
            return n, cells
    raise ValueError("Couldn't find the column headings in this file. Make sure you picked the right import type.")


def col(cells, *names, exact=False):
    for nm in names:
        for k, c in enumerate(cells):
            if (c == nm) if exact else (c == nm or c.startswith(nm)):
                return k
    return None


def cell(row, k):
    if k is None or k >= len(row):
        return ""
    v = row[k]
    return v.strip() if isinstance(v, str) else v


def money(v):
    if v in ("", None):
        return 0
    if isinstance(v, (int, float)):
        return int(round(v * 100))
    s = str(v).strip().replace(",", "").replace("PKR", "").replace("Rs", "").strip()
    neg = s.startswith("(") and s.endswith(")")
    s = s.strip("()")
    try:
        p = to_paisa(s)
    except ValueError:
        return 0
    return -p if neg else p


def to_date(v):
    if isinstance(v, datetime):
        return v.date().isoformat()
    if isinstance(v, date):
        return v.isoformat()
    if isinstance(v, (int, float)) and 20000 < v < 80000:  # Excel serial date
        return (date(1899, 12, 30) + timedelta(days=int(v))).isoformat()
    s = str(v or "").strip()
    for f in ("%d-%m-%Y", "%d/%m/%Y", "%Y-%m-%d", "%d-%b-%Y", "%d-%b-%y", "%d.%m.%Y", "%d-%m-%y", "%d/%m/%y"):
        try:
            return datetime.strptime(s, f).date().isoformat()
        except ValueError:
            pass
    return None


def terms_days(v):
    m = re.search(r"(\d+)", str(v or ""))
    return int(m.group(1)) if m else None


# ---- parsers --------------------------------------------------------------------------------
def parse_customers(rows):
    h, cells = find_header(rows, ["customer", "name"])
    c_name = col(cells, "customer", "name", "full name")
    addr_cols = [k for k, c in enumerate(cells) if c.startswith("bill to") or c.startswith("billing address")
                 or c in ("address", "street", "street1", "street2", "city")]
    out = []
    for row in rows[h + 1:]:
        name = str(cell(row, c_name) or "").strip()
        if not name or name.lower().startswith("total"):
            continue
        addr = [str(cell(row, k)).strip() for k in addr_cols if str(cell(row, k)).strip()]
        if addr and addr[0].lower() == name.lower():
            addr = addr[1:]
        out.append({
            "name": name,
            "contact": str(cell(row, col(cells, "primary contact", "contact")) or ""),
            "phone": str(cell(row, col(cells, "main phone", "phone")) or ""),
            "whatsapp": str(cell(row, col(cells, "mobile", "whatsapp", "cell", "alt phone")) or ""),
            "email": str(cell(row, col(cells, "main email", "email")) or ""),
            "address": "\n".join(addr),
            "rep": str(cell(row, col(cells, "rep", "sales rep")) or ""),
            "terms": terms_days(cell(row, col(cells, "terms"))),
            "balance": money(cell(row, col(cells, "balance total", "balance", "open balance"))),
        })
    return out


def parse_items(rows):
    h, cells = find_header(rows, ["item", "name"])
    c_item = col(cells, "item", "name")
    c_type = col(cells, "type", exact=True)
    c_price = col(cells, "price", "sales price", "rate", "cost")
    out = []
    for row in rows[h + 1:]:
        code = str(cell(row, c_item) or "").strip()
        if not code or code.lower().startswith("total"):
            continue
        typ = str(cell(row, c_type) or "").lower()
        price_raw = cell(row, c_price)
        kind, pct = "item", 0
        if "subtotal" in typ or code.upper().replace(" ", "") == "SUBTOTAL":
            kind = "subtotal"
        elif "discount" in typ or str(price_raw).strip().endswith("%"):
            kind = "discount"
            m = re.search(r"-?\d+(\.\d+)?", str(price_raw))
            pct = -abs(float(m.group(0))) if m else 0
        elif "service" in typ or "other charge" in typ:
            kind = "service"
        out.append({"code": code.split(":")[-1].strip().upper(), "name": code, "kind": kind, "percent": pct,
                    "description": str(cell(row, col(cells, "description", "sales description")) or ""),
                    "unit": str(cell(row, col(cells, "u/m", "unit", "u m")) or ""),
                    "price": 0 if kind in ("subtotal", "discount") else money(price_raw)})
    return out


def parse_open_invoices(rows):
    h, cells = find_header(rows, ["type"])
    c_type = col(cells, "type", exact=True)
    c_date = col(cells, "date", exact=True)
    c_num = col(cells, "num", "number", "no", exact=True)
    c_due = col(cells, "due date")
    c_open = col(cells, "open balance", "amount due", "balance")
    c_amt = col(cells, "amount", exact=True)
    c_name = col(cells, "name", "customer", exact=True)
    out, customer = [], None
    for row in rows[h + 1:]:
        typ = str(cell(row, c_type) or "").strip()
        if not typ:
            text = next((str(v).strip() for v in row[:max(c_type or 1, 1)] if str(v).strip()), "")
            if text and not text.lower().startswith("total"):
                customer = text
            continue
        name = str(cell(row, c_name) or "").strip() if c_name is not None else ""
        cust = name or customer
        if not cust:
            continue
        amt = money(cell(row, c_open))
        if not amt:
            continue
        out.append({"customer": cust, "type": typ, "date": to_date(cell(row, c_date)), "num": str(cell(row, c_num) or "").strip(),
                    "due": to_date(cell(row, c_due)), "open": amt, "total": money(cell(row, c_amt)) if c_amt is not None else amt})
    return out


PARSERS = {"customers": parse_customers, "items": parse_items, "open_invoices": parse_open_invoices}


# ---- importing ------------------------------------------------------------------------------
def _customer_id(name, create=True):
    r = q("SELECT id FROM customers WHERE name = ? COLLATE NOCASE", (name,), one=True)
    if r:
        return r["id"], False
    if not create:
        return None, False
    from .companies import default_company_id
    return x("INSERT INTO customers (name, company_id, created_at) VALUES (?, ?, ?)", (name, default_company_id(), now())), True


def do_import(kind, rows, opts):
    stats = {"added": 0, "updated": 0, "skipped": 0, "customers_created": 0, "notes": []}
    if kind == "customers":
        reps = {r["code"].upper(): r["id"] for r in q("SELECT id, code FROM reps")}
        for r in rows:
            existing = q("SELECT id FROM customers WHERE name = ? COLLATE NOCASE", (r["name"],), one=True)
            rep_id = reps.get(r["rep"].upper()) if r["rep"] else None
            if r["rep"] and not rep_id:
                rep_id = x("INSERT INTO reps (code, name) VALUES (?, ?)", (r["rep"].upper()[:10], r["rep"]))
                reps[r["rep"].upper()] = rep_id
            ob = r["balance"] if opts.get("use_balance") else 0
            vals = dict(contact=r["contact"], phone=r["phone"], whatsapp=r["whatsapp"] or "", email=r["email"],
                        address=r["address"], rep_id=rep_id, terms_days=r["terms"] if r["terms"] is not None else 30)
            if existing:
                if opts.get("update"):
                    x("""UPDATE customers SET contact=:contact, phone=:phone, whatsapp=CASE WHEN :whatsapp != '' THEN :whatsapp
                         ELSE whatsapp END, email=:email, address=:address, rep_id=COALESCE(:rep_id, rep_id),
                         terms_days=:terms_days WHERE id=:id""", {**vals, "id": existing["id"]})
                    stats["updated"] += 1
                else:
                    stats["skipped"] += 1
                continue
            from .companies import default_company_id
            x("""INSERT INTO customers (name, contact, phone, whatsapp, email, address, rep_id, terms_days, opening_balance,
                 opening_date, company_id, created_at) VALUES (:name, :contact, :phone, :whatsapp, :email, :address, :rep_id,
                 :terms_days, :ob, :od, :co, :ca)""", {**vals, "name": r["name"], "ob": ob, "od": opts.get("cutover") if ob else None,
                                                       "co": default_company_id(), "ca": now()})
            stats["added"] += 1
    elif kind == "items":
        for r in rows:
            existing = q("SELECT id FROM items WHERE code = ?", (r["code"],), one=True)
            if r["kind"] == "subtotal" and q("SELECT 1 FROM items WHERE kind = 'subtotal'"):
                stats["skipped"] += 1
                continue
            if existing:
                if opts.get("update"):
                    x("UPDATE items SET name=?, description=?, unit=?, price=?, kind=?, percent=? WHERE id=?",
                      (r["name"], r["description"], r["unit"], r["price"], r["kind"], r["percent"], existing["id"]))
                    stats["updated"] += 1
                else:
                    stats["skipped"] += 1
                continue
            x("INSERT INTO items (code, name, description, unit, price, kind, percent) VALUES (?,?,?,?,?,?,?)",
              (r["code"], r["name"], r["description"], r["unit"], r["price"], r["kind"], r["percent"]))
            stats["added"] += 1
    elif kind == "open_invoices":
        pay_no = next_number("payments", "next_payment_number")
        for r in rows:
            cid, created = _customer_id(r["customer"])
            stats["customers_created"] += created
            c = q("SELECT terms_days, rep_id FROM customers WHERE id = ?", (cid,), one=True)
            d = r["date"] or opts.get("cutover") or date.today().isoformat()
            if r["open"] < 0 or r["type"].lower() in ("payment", "credit memo"):
                ref = f"QB {r['type']} {r['num']}".strip()
                if q("SELECT 1 FROM payments WHERE customer_id = ? AND reference = ? AND amount = ?", (cid, ref, abs(r["open"]))):
                    stats["skipped"] += 1
                    continue
                x("""INSERT INTO payments (number, date, customer_id, amount, method, reference, notes, apply_mode, created_by,
                     created_at) VALUES (?,?,?,?,?,?,?,?,?,?)""",
                  (pay_no, d, cid, abs(r["open"]), "Other", ref, "Unapplied credit imported from QuickBooks", "manual",
                   g.user["id"], now()))
                pay_no += 1
                stats["added"] += 1
                continue
            from .companies import customer_company, next_invoice_number
            co = customer_company(cid)
            num = int(r["num"]) if r["num"].isdigit() else None
            if num and q("SELECT 1 FROM invoices WHERE number = ? AND company_id = ?", (num, co)):
                stats["skipped"] += 1
                continue
            number = num or next_invoice_number(co)
            due = r["due"] or (date.fromisoformat(d) + timedelta(days=c["terms_days"] or 0)).isoformat()
            label = f"Balance brought forward from QuickBooks {r['type'].lower()} #{r['num']}".strip()
            if r["total"] and r["total"] != r["open"]:
                label += f" (original amount {r['total'] / 100:,.2f})"
            iid = x("""INSERT INTO invoices (number, date, due_date, customer_id, rep_id, notes, subtotal, total, ref_no,
                       created_by, created_at, company_id) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
                    (number, d, due, cid, c["rep_id"], "Imported from QuickBooks", r["open"], r["open"],
                     "" if num else r["num"], g.user["id"], now(), co))
            x("""INSERT INTO invoice_lines (invoice_id, code, description, qty, rate, amount, kind, sort)
                 VALUES (?, '', ?, NULL, ?, ?, 'item', 1)""", (iid, label, r["open"], r["open"]))
            stats["added"] += 1
        if stats["customers_created"]:
            stats["notes"].append(f"{stats['customers_created']} customers weren't in the system yet and were created. "
                                  "Import the Customer Contact List to fill in their phone numbers and addresses.")
    commit()
    return stats


def _stash_path(token):
    d = os.path.join(current_app.config["DATA_DIR"], "imports")
    os.makedirs(d, exist_ok=True)
    return os.path.join(d, re.sub(r"[^A-Za-z0-9_-]", "", token) + ".json")


@bp.route("/", methods=["GET", "POST"])
@roles("admin")
def index():
    if request.method == "POST" and request.form.get("step") == "confirm":
        path = _stash_path(request.form.get("token", ""))
        if not os.path.exists(path):
            flash("That upload has expired. Please upload the file again.", "err")
            return redirect(url_for("importer.index"))
        data = json.load(open(path))
        os.remove(path)
        stats = do_import(data["kind"], data["rows"], data["opts"])
        msg = f"Import finished: {stats['added']} added"
        if stats["updated"]:
            msg += f", {stats['updated']} updated"
        if stats["skipped"]:
            msg += f", {stats['skipped']} skipped (already in the system)"
        flash(msg + ".", "ok")
        for n in stats["notes"]:
            flash(n, "info")
        return redirect(url_for("importer.index"))

    if request.method == "POST":
        kind = request.form.get("kind")
        f = request.files.get("file")
        if kind not in KINDS or not f or not f.filename:
            flash("Choose what you're importing and pick a file.", "err")
            return redirect(url_for("importer.index"))
        try:
            rows = PARSERS[kind](read_table(f))
        except ValueError as e:
            flash(str(e), "err")
            return redirect(url_for("importer.index"))
        except Exception as e:
            flash(f"Couldn't read that file ({e}). Please export it again as Excel (.xlsx) or CSV.", "err")
            return redirect(url_for("importer.index"))
        if not rows:
            flash("No rows found in that file. Check you picked the right import type.", "err")
            return redirect(url_for("importer.index"))
        opts = {"update": bool(request.form.get("update")), "use_balance": bool(request.form.get("use_balance")),
                "cutover": request.form.get("cutover") or date.today().isoformat()}
        token = secrets.token_hex(8)
        json.dump({"kind": kind, "rows": rows, "opts": opts}, open(_stash_path(token), "w"))
        total = sum(r.get("open", r.get("balance", 0)) or 0 for r in rows)
        return render_template("import.html", kinds=KINDS, preview=rows[:200], count=len(rows), kind=kind, token=token,
                               total=total, opts=opts)
    counts = {k: q(f"SELECT COUNT(*) AS n FROM {t}", one=True)["n"] for k, t in
              (("customers", "customers"), ("items", "items"), ("invoices", "invoices"))}
    return render_template("import.html", kinds=KINDS, preview=None, counts=counts)
