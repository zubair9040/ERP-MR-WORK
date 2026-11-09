"""HBL PO-to-Bill pack: drop the bank's PO PDF, get the branch DCs / bills / summary pack, using REAL ERP numbers.

The PDF is read and the pack pages are built in the browser (static/hbl/*). The ERP supplies the numbers, keeps every
DC as a normal invoice in the PO batch, and records each billing (summary no + sales tax invoice no) so a PO can be
billed in parts: tick the DCs (and lines / quantities) for this summary now, the rest later."""
import json
import os
from decimal import Decimal

from flask import Blueprint, abort, flash, g, jsonify, redirect, render_template, request, url_for

from .companies import default_company_id, get_company, next_invoice_number
from .db import commit, now, q, rnd, set_setting, settings, today, x

bp = Blueprint("hbl", __name__, url_prefix="/hbl")

SEED = os.path.join(os.path.dirname(__file__), "hbl_data", "hbl_seed.json")


def _dec(v):
    return Decimal(repr(float(v or 0)))


def ensure_items():
    if q("SELECT 1 FROM hbl_items LIMIT 1"):
        return
    seed = json.load(open(SEED, encoding="utf-8"))
    for code, (name, unit, price) in seed["PRICES"].items():
        x("INSERT OR IGNORE INTO hbl_items (code, name, unit, price) VALUES (?,?,?,?)", (code, name, unit or "PCS", price))
    commit()


def customer():
    cid = settings().get("hbl_customer_id")
    return q("SELECT * FROM customers WHERE id = ?", (cid,), one=True) if cid else None


def _batch(po, c, create=False):
    b = q("SELECT * FROM po_batches WHERE customer_id = ? AND po_no = ? AND void = 0 ORDER BY id DESC", (c["id"], po), one=True)
    if not b and create:
        bid = x("INSERT INTO po_batches (company_id, customer_id, po_no, date, created_by, created_at) VALUES (?,?,?,?,?,?)",
                (c["company_id"] or default_company_id(), c["id"], po, today(), g.user["id"], now()))
        b = q("SELECT * FROM po_batches WHERE id = ?", (bid,), one=True)
    return b


# ---- pages ---------------------------------------------------------------------------------
@bp.route("/")
def index():
    ensure_items()
    c = customer()
    custs = q("SELECT id, name FROM customers WHERE active = 1 ORDER BY (name LIKE '%HBL%' OR name LIKE '%Habib%') DESC, name COLLATE NOCASE")
    nb = q("SELECT COUNT(*) AS n FROM customer_branches WHERE customer_id = ?", (c["id"],), one=True)["n"] if c else 0
    s_next, i_next = _next_billing_numbers()
    pos = q("SELECT b.*, (SELECT COUNT(*) FROM hbl_dcs d WHERE d.batch_id = b.id) AS dcs FROM po_batches b WHERE b.customer_id = ? AND b.void = 0 "
            "AND EXISTS (SELECT 1 FROM hbl_dcs d WHERE d.batch_id = b.id) ORDER BY b.id DESC", (c["id"],)) if c else []
    return render_template("hbl/index.html", cust=c, custs=custs, branches=nb, pos=pos, next_dc=next_dc(), next_sumno=s_next, next_sinv=i_next)


@bp.route("/customer", methods=["POST"])
def set_customer():
    set_setting("hbl_customer_id", request.form.get("customer_id", ""))
    commit()
    return redirect(url_for("hbl.index"))


@bp.route("/branches/load", methods=["POST"])
def load_branches():
    """Adds the bank's 2,000+ branches (cost code, name, region, address, phone) to the HBL customer."""
    c = customer() or abort(400)
    seed = json.load(open(SEED, encoding="utf-8"))
    have = {r["code"] for r in q("SELECT code FROM customer_branches WHERE customer_id = ?", (c["id"],))}
    n = 0
    for code, (name, region, address, phone) in seed["ADDR"].items():
        if code in have:
            continue
        x("INSERT INTO customer_branches (customer_id, name, code, address, phone, region, active, created_at) VALUES (?,?,?,?,?,?,1,?)",
          (c["id"], name, code, address, phone, region, now()))
        n += 1
    commit()
    flash(f"{n} HBL branches added.", "ok")
    return redirect(url_for("hbl.index"))


@bp.route("/numbers", methods=["POST"])
def set_numbers():
    """Where the DC / summary / sales tax invoice numbers continue from."""
    for key, field in (("hbl_next_dc", "next_dc"), ("hbl_next_sumno", "next_sumno"), ("hbl_next_sinv", "next_sinv")):
        v = "".join(ch for ch in request.form.get(field, "") if ch.isdigit())
        if v:
            set_setting(key, v)
    commit()
    flash("Numbers saved.", "ok")
    return redirect(url_for("hbl.index"))


@bp.route("/record", methods=["POST"])
def read_record():
    """Reads your old HBL_RECORD Excel only to continue the numbers (last DC, last summary no, last sales tax invoice no)."""
    import openpyxl
    f = request.files.get("record")
    if not f or not f.filename.lower().endswith((".xlsx", ".xlsm")):
        flash("Choose the HBL_RECORD .xlsx file.", "err")
        return redirect(url_for("hbl.index"))
    wb = openpyxl.load_workbook(f, data_only=True, read_only=True)
    ws = next((w for w in wb.worksheets if w.title.strip().upper() == "DATA"), None)
    if not ws:
        flash("That file has no DATA tab.", "err")
        return redirect(url_for("hbl.index"))
    dc = sm = si = 0
    pos = set()
    for row in ws.iter_rows(min_row=2, values_only=True):
        if len(row) < 21:
            continue
        for v, which in ((row[2], "dc"), (row[19], "sm"), (row[20], "si")):
            try:
                n = int(float(str(v).strip()))
            except (TypeError, ValueError):
                continue
            if which == "dc":
                dc = max(dc, n)
            elif which == "sm":
                sm = max(sm, n)
            else:
                si = max(si, n)
        if row[1]:
            pos.add(str(row[1]))
    bw = next((w for w in wb.worksheets if w.title.strip().upper() == "BILLINGS"), None)
    if bw:
        for row in bw.iter_rows(min_row=2, values_only=True):
            for v, which in ((row[16] if len(row) > 16 else None, "sm"), (row[17] if len(row) > 17 else None, "si")):
                try:
                    n = int(float(str(v).strip()))
                except (TypeError, ValueError):
                    continue
                sm, si = (max(sm, n), si) if which == "sm" else (sm, max(si, n))
    if dc:
        set_setting("hbl_next_dc", str(dc + 1))
    if sm:
        set_setting("hbl_next_sumno", str(sm + 1))
    if si:
        set_setting("hbl_next_sinv", str(si + 1))
    commit()
    flash(f"Record read ({len(pos)} PO(s)). Next DC no {dc + 1 if dc else '-'}"
          + (f", next summary no {sm + 1}" if sm else ", no summary numbers in the record yet")
          + (f", next sales tax invoice no {si + 1}." if si else ", no sales tax invoice numbers in the record yet."), "ok")
    return redirect(url_for("hbl.index"))


@bp.route("/app")
def app_page():
    ensure_items()
    return render_template("hbl/app.html", cust=customer())


@bp.route("/items", methods=["GET", "POST"])
def items():
    ensure_items()
    if request.method == "POST":
        f = request.form
        if f.get("new_code", "").strip():
            x("INSERT OR REPLACE INTO hbl_items (code, name, unit, price, active) VALUES (?,?,?,?,1)",
              (f["new_code"].strip().upper(), f.get("new_name", "").strip(), f.get("new_unit", "PCS").strip() or "PCS", float(f.get("new_price") or 0)))
        for code in f.getlist("code"):
            x("UPDATE hbl_items SET name = ?, unit = ?, price = ? WHERE code = ?",
              (f.get("name_" + code, "").strip(), f.get("unit_" + code, "PCS").strip(), float(f.get("price_" + code) or 0), code))
        commit()
        flash("HBL item rates saved.", "ok")
        return redirect(url_for("hbl.items"))
    return render_template("hbl/items.html", rows=q("SELECT * FROM hbl_items ORDER BY code"))


# ---- API for the pack page -----------------------------------------------------------------
@bp.route("/api/lookup")
def api_lookup():
    c = customer()
    names, prices = {}, {}
    seed_names = json.load(open(SEED, encoding="utf-8"))["NAMES"]
    for r in q("SELECT * FROM hbl_items WHERE active = 1"):
        prices[r["code"]] = [r["name"], r["unit"], r["price"]]
    for code, v in seed_names.items():
        names[code] = v
    addr = {}
    if c:
        for b in q("SELECT * FROM customer_branches WHERE customer_id = ? AND code != ''", (c["id"],)):
            addr[str(int(b["code"])) if str(b["code"]).isdigit() else b["code"]] = [b["name"], b["region"] or "", b["address"] or "", b["phone"] or ""]
    return jsonify(NAMES=names, PRICES=prices, ADDR=addr, customer=bool(c))


def next_dc():
    """DC numbers are their own series (continues from the old HBL record); invoice numbers come from the ERP's invoice numbering."""
    seed = int(settings().get("hbl_next_dc") or 0)
    m = q("SELECT MAX(dc_no) AS m FROM hbl_dcs", one=True)["m"] or 0
    return max(seed, m + 1)


def _next_billing_numbers(batch_ids=None):
    s = int(settings().get("hbl_next_sumno") or 1) - 1
    i = int(settings().get("hbl_next_sinv") or 1) - 1
    for r in q("SELECT sumno, sinv FROM hbl_billings"):
        for v, key in ((r["sumno"], "s"), (r["sinv"], "i")):
            digits = "".join(ch for ch in str(v) if ch.isdigit())
            if digits:
                if key == "s":
                    s = max(s, int(digits))
                else:
                    i = max(i, int(digits))
    return s + 1 if s else "", i + 1 if i else ""


@bp.route("/api/pos")
def api_pos():
    c = customer()
    rows = q("SELECT b.po_no FROM po_batches b WHERE b.customer_id = ? AND b.void = 0 AND EXISTS (SELECT 1 FROM hbl_dcs d WHERE d.batch_id = b.id) "
             "ORDER BY b.id", (c["id"],)) if c else []
    return jsonify(pos=[r["po_no"] for r in rows])


@bp.route("/api/next")
def api_next():
    c = customer()
    co = c["company_id"] or default_company_id() if c else default_company_id()
    s, i = _next_billing_numbers()
    return jsonify(next_invoice=next_invoice_number(co), next_dc=next_dc(), next_summary=s, next_sinv=i)


@bp.route("/api/po/<po>")
def api_po(po):
    c = customer() or abort(400)
    b = _batch(po, c)
    s, i = _next_billing_numbers()
    if not b or not q("SELECT 1 FROM hbl_dcs WHERE batch_id = ?", (b["id"],)):
        return jsonify(exists=False, next_summary=s, next_sinv=i)
    dcs, bills = [], []
    for d in q("SELECT d.*, i.number, i.void FROM hbl_dcs d JOIN invoices i ON i.id = d.invoice_id WHERE d.batch_id = ? AND i.void = 0 ORDER BY COALESCE(d.dc_no, i.number)", (b["id"],)):
        lines = [{"code": l["code"], "name": l["name"], "unit": l["unit"], "origQty": l["orig_qty"], "qty": l["qty"], "price": l["price"],
                  "tax": l["tax"], "cancelled": bool(l["cancelled"])} for l in q("SELECT * FROM hbl_lines WHERE invoice_id = ? ORDER BY code, id", (d["invoice_id"],))]
        dcs.append({"dc": d["dc_no"] or d["number"], "inv": d["number"], "req": d["req"], "po": po, "cc": d["cc"], "loc": d["loc"], "person": d["person"],
                    "phone": d["phone"], "date": d["date"], "lines": lines, "iid": d["invoice_id"]})
    for bl in q("SELECT * FROM hbl_billings WHERE batch_id = ? ORDER BY id", (b["id"],)):
        byinv = {}
        for l in q("SELECT * FROM hbl_billing_lines WHERE billing_id = ?", (bl["id"],)):
            byinv.setdefault(l["invoice_id"], []).append({"code": l["code"], "name": l["name"], "unit": l["unit"], "qty": l["qty"], "price": l["price"], "tax": l["tax"]})
        for d in dcs:
            if d["iid"] in byinv:
                bills.append({"date": bl["date"], "po": po, "dc": d["dc"], "inv": d["inv"], "req": d["req"], "cc": d["cc"], "loc": d["loc"],
                              "sumno": bl["sumno"], "sinv": bl["sinv"], "lines": byinv[d["iid"]]})
    return jsonify(exists=True, po=po, header={"excl": b["po_excl"], "tax": b["po_tax"], "incl": b["po_incl"]}, dcs=dcs, bills=bills,
                   next_summary=s, next_sinv=i, batch_id=b["id"], batch_url=url_for("po.view", bid=b["id"]))


def _line_paisa(qty, price):
    return rnd(_dec(qty) * _dec(price) * 100)


def _sync_invoice(iid):
    """The ERP invoice of a DC = what has been billed so far (all summaries); before the first billing = the DC lines as planned."""
    billed = q("SELECT l.* FROM hbl_billing_lines l WHERE l.invoice_id = ? ORDER BY l.id", (iid,))
    if billed:
        agg = {}
        for l in billed:
            k = (l["code"], float(l["price"]))
            a = agg.setdefault(k, {"code": l["code"], "name": l["name"], "unit": l["unit"], "qty": 0.0, "price": l["price"], "tax": l["tax"]})
            a["qty"] += l["qty"]
        lines = [a for a in agg.values() if a["qty"] > 0]
    else:
        lines = [{"code": l["code"], "name": l["name"], "unit": l["unit"], "qty": l["qty"], "price": l["price"], "tax": l["tax"]}
                 for l in q("SELECT * FROM hbl_lines WHERE invoice_id = ? AND cancelled = 0 AND qty > 0 ORDER BY code, id", (iid,))]
    ex = sum(_dec(l["qty"]) * _dec(l["price"]) for l in lines)
    gst = sum(_dec(l["qty"]) * _dec(l["price"]) * _dec(l["tax"]) for l in lines)
    sub, total = rnd(ex * 100), rnd((ex + gst) * 100)
    x("DELETE FROM invoice_lines WHERE invoice_id = ?", (iid,))
    for n, l in enumerate(lines, start=1):
        item = q("SELECT id FROM items WHERE code = ?", (l["code"],), one=True)
        if not item:
            item_id = x("INSERT INTO items (code, name, description, unit, price, kind, grp) VALUES (?,?,?,?,?,'item','HBL')",
                        (l["code"], l["name"], l["name"], l["unit"], rnd(_dec(l["price"]) * 100)))
        else:
            item_id = item["id"]
        x("""INSERT INTO invoice_lines (invoice_id, item_id, code, description, unit, ctn_qty, qty, rate, percent, amount, kind, sort)
             VALUES (?,?,?,?,?,'',?,?,NULL,?,'item',?)""", (iid, item_id, l["code"], l["name"], l["unit"], l["qty"], rnd(_dec(l["price"]) * 100),
                                                          _line_paisa(l["qty"], l["price"]), n))
    rate = 18.0 if gst > 0 else 0.0
    x("UPDATE invoices SET subtotal = ?, tax = ?, total = ?, tax_rate = ?, updated_at = ? WHERE id = ?", (sub, total - sub, total, rate, now(), iid))


@bp.route("/api/import", methods=["POST"])
def api_import():
    """Creates the PO batch and one real invoice (= DC number) per branch request. Safe to repeat: existing requests are kept."""
    c = customer()
    j = request.get_json(silent=True) or {}
    po = str(j.get("po") or "").strip()
    if not c:
        return jsonify(error="Choose the HBL customer first (HBL PO pack page)."), 400
    if not po or not j.get("dcs"):
        return jsonify(error="Nothing to create."), 400
    co = get_company(c["company_id"]) or get_company(default_company_id())
    b = _batch(po, c, create=True)
    h = j.get("header") or {}
    x("UPDATE po_batches SET po_excl = ?, po_tax = ?, po_incl = ? WHERE id = ?", (h.get("excl"), h.get("tax"), h.get("incl"), b["id"]))
    have = {r["req"] for r in q("SELECT req FROM hbl_dcs WHERE batch_id = ?", (b["id"],))}
    date = (j.get("date") or today())[:10]
    created = []
    for d in j["dcs"]:
        req = str(d.get("req") or "")
        if req in have:
            continue
        cc = str(d.get("cc") or "")
        norm = str(int(cc)) if cc.isdigit() else cc  # the bank writes 0627, the branch list keeps 627
        br = q("SELECT * FROM customer_branches WHERE customer_id = ? AND code IN (?, ?) LIMIT 1", (c["id"], cc, norm), one=True)
        number = next_invoice_number(co["id"])
        dc_no = next_dc()
        set_setting("hbl_next_dc", str(dc_no + 1))
        due = date
        iid = x("""INSERT INTO invoices (number, date, due_date, customer_id, rep_id, notes, tax_rate, subtotal, discount, tax, total, created_by, created_at,
                   company_id, branch_id, batch_id, ref_no, po_no, deliver_to) VALUES (?,?,?,?,?,?,0,0,0,0,0,?,?,?,?,?,?,?,?)""",
                  (number, date, due, c["id"], c["rep_id"], f"HBL PO {po} request {req}", g.user["id"], now(), co["id"],
                   br["id"] if br else None, b["id"], req, po,
                   "\n".join(v for v in (br["name"], br["address"], br["phone"]) if v) if br else str(d.get("loc") or "")))
        x("INSERT INTO hbl_dcs (invoice_id, batch_id, po_no, req, cc, loc, person, phone, date, dc_no) VALUES (?,?,?,?,?,?,?,?,?,?)",
          (iid, b["id"], po, req, str(d.get("cc") or ""), str(d.get("loc") or ""), str(d.get("person") or ""), str(d.get("phone") or ""), date, dc_no))
        for n, l in enumerate(d.get("lines") or [], start=1):
            x("INSERT INTO hbl_lines (invoice_id, sort, code, name, unit, orig_qty, qty, price, tax, cancelled) VALUES (?,?,?,?,?,?,?,?,?,0)",
              (iid, n, l["code"], l["name"], l["unit"], float(l.get("origQty") or l["qty"]), float(l["qty"]), float(l["price"]), float(l["tax"])))
        _sync_invoice(iid)
        created.append({"req": req, "dc": dc_no, "inv": number})
    commit()
    return jsonify(ok=True, created=created, skipped=len(j["dcs"]) - len(created), batch_url=url_for("po.view", bid=b["id"]))


@bp.route("/api/bill", methods=["POST"])
def api_bill():
    """Saves one billing (summary no + sales tax invoice no) for the ticked DCs, with the lines / quantities billed now."""
    c = customer()
    j = request.get_json(silent=True) or {}
    po, sumno, sinv = str(j.get("po") or ""), str(j.get("sumno") or "").strip(), str(j.get("sinv") or "").strip()
    b = _batch(po, c) if c else None
    if not b:
        return jsonify(error="This PO has not been created in the ERP yet."), 400
    if not sumno or not sinv:
        return jsonify(error="Type the summary no and the sales tax invoice no."), 400
    other = q("SELECT po_no FROM hbl_billings WHERE (sumno = ? OR sinv = ?) AND NOT (batch_id = ? AND sumno = ? AND sinv = ?) LIMIT 1",
              (sumno, sinv, b["id"], sumno, sinv), one=True)
    if other:
        return jsonify(error=f"Summary no {sumno} or invoice no {sinv} is already used on another billing (PO {other['po_no']}). Use new numbers."), 400
    old = q("SELECT id FROM hbl_billings WHERE batch_id = ? AND sumno = ? AND sinv = ?", (b["id"], sumno, sinv), one=True)
    touched = set()
    if old:  # printing the same billing again: replace its lines
        touched |= {r["invoice_id"] for r in q("SELECT DISTINCT invoice_id FROM hbl_billing_lines WHERE billing_id = ?", (old["id"],))}
        x("DELETE FROM hbl_billing_lines WHERE billing_id = ?", (old["id"],))
        bid = old["id"]
        x("UPDATE hbl_billings SET date = ?, isn = ? WHERE id = ?", (j.get("date") or today(), j.get("isn") or "", bid))
    else:
        bid = x("INSERT INTO hbl_billings (batch_id, po_no, sumno, sinv, isn, date, created_by, created_at) VALUES (?,?,?,?,?,?,?,?)",
                (b["id"], po, sumno, sinv, j.get("isn") or "", j.get("date") or today(), g.user["id"], now()))
    n = 0
    for d in j.get("dcs") or []:
        dc = q("SELECT d.invoice_id FROM hbl_dcs d JOIN invoices i ON i.id = d.invoice_id WHERE d.batch_id = ? AND COALESCE(d.dc_no, i.number) = ?", (b["id"], int(d["dc"])), one=True)
        if not dc:
            return jsonify(error=f"DC {d['dc']} is not in this PO."), 400
        iid = dc["invoice_id"]
        touched.add(iid)
        # remember the live DC lines (cancelled / reduced quantities) on the DC itself
        live = {(l["code"]): l for l in d.get("lines") or []}
        for hl in q("SELECT * FROM hbl_lines WHERE invoice_id = ?", (iid,)):
            lv = live.get(hl["code"])
            x("UPDATE hbl_lines SET qty = ?, cancelled = ? WHERE id = ?", (float(lv["qty"]) if lv else hl["qty"], 0 if lv else 1, hl["id"]))
        for l in d.get("lines") or []:
            if float(l["qty"]) <= 0:
                continue
            x("INSERT INTO hbl_billing_lines (billing_id, invoice_id, code, name, unit, qty, price, tax) VALUES (?,?,?,?,?,?,?,?)",
              (bid, iid, l["code"], l["name"], l["unit"], float(l["qty"]), float(l["price"]), float(l["tax"])))
            n += 1
    for iid in touched:
        _sync_invoice(iid)
    commit()
    return jsonify(ok=True, billing=bid, lines=n)
