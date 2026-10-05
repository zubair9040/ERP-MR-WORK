"""Warehouse module: stock kept separately from invoices, moved only by warehouse documents."""
from collections import defaultdict
from datetime import date

from flask import Blueprint, abort, flash, g, jsonify, redirect, render_template, request, send_file, url_for

from . import stock as st
from .auth import roles, sees_cost
from .db import commit, fmt, nice_date, now, parse_date, plain, q, settings, to_paisa, today, x
from .export import table_response
from .lines import parse_qty

bp = Blueprint("wh", __name__, url_prefix="/warehouse")
VIEW = ("admin", "accounts", "store", "rep")
WORK = ("admin", "accounts", "store")
MANAGE = ("admin", "accounts")


def qty_fmt(v):
    return "" if v is None else f"{v:g}"


def wh_map():
    return {w["id"]: w for w in st.warehouses(active_only=False)}


def item_rows(lv=None):
    lv = lv if lv is not None else st.levels()
    items = q("""SELECT * FROM items WHERE kind = 'item' AND track_stock = 1 AND active = 1
                 ORDER BY code COLLATE NOCASE, name COLLATE NOCASE""")
    return [(i, lv.get(i["id"])) for i in items if i["id"] in lv]


def grid_items(exclude_doc=None):
    """Item list for the entry grid: code, barcode, description, unit, cost and stock per warehouse."""
    out = []
    show = sees_cost()
    for i, s in item_rows(st.levels(exclude_doc=exclude_doc)):
        out.append({"id": i["id"], "code": (i["code"] or i["name"]).upper(), "barcode": (i["barcode"] or "").strip(),
                    "desc": i["description"] or i["name"], "unit": i["unit"] or "", "loc": i["location"] or "", "ppc": st.ppc(i),
                    "cost": plain(s["avg_cost"]) if show else "", "price": plain(i["price"] or 0) if show else "", "wh": {str(k): v for k, v in s["by_wh"].items()}})
    return out


# ---- stock levels (warehouse home) -----------------------------------------------------------
@bp.route("/")
@roles(*VIEW)
def home():
    whs = st.warehouses()
    wid = request.args.get("w", type=int)
    lv = st.levels(warehouse_id=wid)
    s_ = request.args.get("q", "").strip().lower()
    rows = []
    pk = st.packing(wid)
    for i, s in item_rows(lv):
        if s_ and not any(s_ in (i[k] or "").lower() for k in ("code", "name", "description", "barcode", "location")):
            continue
        low = bool(i["reorder_level"]) and s["on_hand"] <= i["reorder_level"]
        if request.args.get("low") and not low:
            continue
        if request.args.get("instock") and s["on_hand"] <= 0:
            continue
        rows.append({"i": i, "s": s, "low": low, "pk": st.packing_text(pk.get(i["id"]))})
    show_cost = sees_cost()
    if request.args.get("export") in ("xlsx", "pdf"):
        heads = ["Item code", "Description", "U/M", "Location"] + ([w["code"] for w in whs] if not wid else []) + \
                ["Cartons + loose", "Pcs", "Min"] + (["Cost / pc", "Cost value", "Sale value"] if show_cost else [])
        data = []
        for r in rows:
            line = [r["i"]["code"], r["i"]["description"] or r["i"]["name"], r["i"]["unit"], r["i"]["location"]]
            if not wid:
                line += [qty_fmt(r["s"]["by_wh"].get(w["id"], 0)) for w in whs]
            line += [r["pk"], qty_fmt(r["s"]["on_hand"]), qty_fmt(r["i"]["reorder_level"] or 0)]
            if show_cost:
                line += [r["s"]["avg_cost"], r["s"]["value"], r["s"]["sale_value"]]
            data.append(line)
        n = len(heads)
        money = {n - 3, n - 2, n - 1} if show_cost else set()
        totals = (["Total"] + [""] * (n - 3) + [sum(r["s"]["value"] for r in rows), sum(r["s"]["sale_value"] for r in rows)]) if show_cost else None
        wname = next((w["name"] for w in whs if w["id"] == wid), "All warehouses")
        return table_response(request.args["export"], f"Stock levels - {wname}", heads, data, money, totals,
                              f"{wname} · as of {nice_date(today())}")
    recent = q("""SELECT d.*, w.code AS wh_code, t.code AS to_code, (SELECT COUNT(*) FROM wh_lines l WHERE l.doc_id = d.id) AS n
                  FROM wh_docs d JOIN warehouses w ON w.id = d.warehouse_id LEFT JOIN warehouses t ON t.id = d.to_warehouse_id
                  ORDER BY d.date DESC, d.id DESC LIMIT 8""")
    all_lv = lv if not wid else st.levels()
    all_items = item_rows(all_lv)
    return render_template("wh/home.html", rows=rows, whs=whs, wid=wid, show_cost=show_cost, recent=recent,
                           types=st.DOC_TYPES, doc_no=st.doc_no,
                           total_value=sum(r["s"]["value"] for r in rows), total_sale=sum(r["s"]["sale_value"] for r in rows),
                           total_pcs=sum(max(r["s"]["pcs"], 0) for r in rows),
                           total_units=sum(max(r["s"]["on_hand"], 0) for r in rows),
                           low_count=sum(1 for i, s in all_items if i["reorder_level"] and s["on_hand"] <= i["reorder_level"]),
                           out_count=sum(1 for i, s in all_items if s["on_hand"] <= 0))


@bp.route("/api/stock")
@roles(*VIEW)
def api_stock():
    wid = request.args.get("w", type=int)
    return jsonify({str(k): v["on_hand"] for k, v in st.levels(warehouse_id=wid).items()})


# ---- documents list ----------------------------------------------------------------------------
@bp.route("/documents")
@roles(*WORK)
def docs():
    a = request.args
    where, args = "", {}
    if a.get("type") in st.DOC_TYPES:
        where += " AND d.type = :t"
        args["t"] = a["type"]
    if a.get("w", type=int):
        where += " AND (d.warehouse_id = :w OR d.to_warehouse_id = :w)"
        args["w"] = a.get("w", type=int)
    if parse_date(a.get("from")):
        where += " AND d.date >= :f"
        args["f"] = a["from"]
    if parse_date(a.get("to")):
        where += " AND d.date <= :to"
        args["to"] = a["to"]
    if a.get("q"):
        where += " AND (d.party LIKE :s OR d.ref LIKE :s OR d.notes LIKE :s OR CAST(d.number AS TEXT) = :n)"
        args.update(s=f"%{a['q'].strip()}%", n=a["q"].strip().split("-")[-1].lstrip("0") or "0")
    rows = q(f"""SELECT d.*, w.code AS wh_code, t.code AS to_code,
                        (SELECT COUNT(*) FROM wh_lines l WHERE l.doc_id = d.id) AS n,
                        (SELECT COALESCE(SUM(ABS(l.qty)), 0) FROM wh_lines l WHERE l.doc_id = d.id) AS units
                 FROM wh_docs d JOIN warehouses w ON w.id = d.warehouse_id LEFT JOIN warehouses t ON t.id = d.to_warehouse_id
                 WHERE 1 = 1 {where} ORDER BY d.date DESC, d.id DESC LIMIT 1000""", args)
    if a.get("export") in ("xlsx", "pdf"):
        data = [[st.doc_no(r["type"], r["number"]), nice_date(r["date"]), st.DOC_TYPES[r["type"]]["name"],
                 r["wh_code"] + (f" → {r['to_code']}" if r["to_code"] else ""), r["party"], r["ref"], r["n"], qty_fmt(r["units"]),
                 "VOID" if r["void"] else ""] for r in rows]
        return table_response(a["export"], "Warehouse documents", ["Doc no.", "Date", "Type", "Warehouse", "Party", "Reference",
                              "Lines", "Units", ""], data, set())
    return render_template("wh/docs.html", rows=rows, types=st.DOC_TYPES, whs=st.warehouses(), doc_no=st.doc_no)


# ---- document entry ------------------------------------------------------------------------------
def _read_lines(f, dtype):
    """Grid rows: item code, cartons, pieces per carton, loose pieces (total pieces = cartons x pcs/ctn + loose)."""
    by_code, by_bar = {}, {}
    for i in q("SELECT * FROM items WHERE kind = 'item' AND track_stock = 1"):
        if i["code"]:
            by_code[i["code"].upper()] = i
        if i["barcode"]:
            by_bar[i["barcode"].strip()] = i
    cols = [f.getlist(k) for k in ("code", "ctn", "ppc", "loose", "cost", "note")]
    lines = []
    for n, (code, ctn, ppc_, loose, cost, note) in enumerate(zip(*cols), start=1):
        if not (code.strip() or ctn.strip() or loose.strip()):
            continue
        if dtype == "CNT" and not (ctn.strip() or loose.strip()):
            continue  # not counted yet
        it = by_code.get(code.strip().upper()) or by_bar.get(code.strip())
        if not it:
            raise ValueError(f"Line {n}: item code '{code}' not found. Only stock items can be used here.")
        try:
            cv = parse_qty(ctn) or 0
            lv = parse_qty(loose) or 0
            pv = parse_qty(ppc_) or st.ppc(it)
        except ValueError as e:
            raise ValueError(f"Line {n}: {e}")
        if pv <= 0:
            raise ValueError(f"Line {n}: pieces per carton must be more than zero.")
        qv = st.line_pcs(cv, pv, lv)
        if dtype not in ("ADJ", "CNT") and (cv < 0 or lv < 0 or qv <= 0):
            raise ValueError(f"Line {n}: enter the cartons and/or loose pieces for {it['code']}.")
        if dtype == "CNT" and qv < 0:
            raise ValueError(f"Line {n}: counted quantity can't be negative.")
        if dtype == "ADJ" and qv == 0:
            raise ValueError(f"Line {n}: an adjustment of 0 does nothing.")
        try:
            c = to_paisa(cost) if cost and dtype in ("GRN", "OPN") else 0
        except ValueError:
            raise ValueError(f"Line {n}: cost '{cost}' is not a number.")
        lines.append({"item": it, "item_id": it["id"], "qty": qv, "ctn": cv, "ppc": pv, "loose": lv, "cost": c,
                      "note": note.strip(), "sort": n})
    if not lines:
        raise ValueError("Add at least one item.")
    return lines


def _form_rows(f):
    keys = ("code", "ctn", "ppc", "loose", "cost", "note")
    cols = [f.getlist(k) for k in keys]
    return [dict(zip(keys, r)) for r in zip(*cols) if r[0].strip() or r[1].strip() or r[3].strip()]


def _prefill(dtype):
    """Rows copied from a purchase bill (for a goods receipt), split into cartons + loose pieces."""
    head, rows = {}, []
    inv_id, pur_id = request.args.get("invoice", type=int), request.args.get("purchase", type=int)
    if dtype == "GRN" and pur_id:  # goods issue notes are not linked to invoices; receipts can copy a purchase bill
        p = q("""SELECT p.*, s.name AS supplier FROM purchases p JOIN suppliers s ON s.id = p.supplier_id WHERE p.id = ?""",
              (pur_id,), one=True) or abort(404)
        done = defaultdict(float)
        for r in q("""SELECT l.item_id, SUM(l.qty) AS qty FROM wh_lines l JOIN wh_docs d ON d.id = l.doc_id
                      WHERE d.purchase_id = ? AND d.type = 'GRN' AND d.void = 0 GROUP BY l.item_id""", (pur_id,)):
            done[r["item_id"]] = r["qty"]
        for l in q("""SELECT l.item_id, SUM(COALESCE(l.qty, 0)) AS qty, MAX(l.rate) AS rate, it.code, it.pcs_per_ctn FROM purchase_lines l
                      JOIN items it ON it.id = l.item_id WHERE l.purchase_id = ? AND it.kind = 'item' AND it.track_stock = 1
                      GROUP BY l.item_id ORDER BY MIN(l.sort)""", (pur_id,)):
            left = round(l["qty"] - done[l["item_id"]], 3)
            if left > 0:  # the bill is in pieces: split into full cartons + loose pieces
                k = st.ppc(l)
                full = int(left // k) if k > 1 else 0
                rows.append({"code": l["code"], "ctn": qty_fmt(full) if full else "", "ppc": qty_fmt(k),
                             "loose": qty_fmt(round(left - full * k, 3)) if left - full * k else "",
                             "cost": plain(l["rate"]) if sees_cost() else "", "note": ""})
        head = {"party": p["supplier"], "ref": f"Bill {p['bill_no'] or p['number']}", "purchase_id": pur_id}
    return head, rows


def _render_form(dtype, doc, f, rows):
    whs = st.warehouses()
    parties = []
    if dtype == "GRN":
        parties = [r["name"] for r in q("SELECT name FROM suppliers WHERE active = 1 ORDER BY name")]
    elif dtype == "DC":
        parties = [r["name"] for r in q("SELECT name FROM customers WHERE active = 1 ORDER BY name")]
    next_no = (q("SELECT MAX(number) AS m FROM wh_docs WHERE type = ?", (dtype,), one=True)["m"] or 0) + 1
    return render_template("wh/doc_form.html", dtype=dtype, T=st.DOC_TYPES[dtype], doc=doc, f=f, rows=rows, whs=whs,
                           items=grid_items(doc["id"] if doc else None), parties=parties, show_cost=sees_cost(),
                           doc_no=st.doc_no(dtype, doc["number"] if doc else next_no),
                           default_wh=(st.default_warehouse() or {"id": ""})["id"])


def _save(dtype, doc=None):
    f = request.form
    whs = {w["id"]: w for w in st.warehouses()}
    try:
        wid = int(f.get("warehouse_id") or 0)
        if wid not in whs:
            raise ValueError("Choose a warehouse.")
        to_wid = None
        if dtype == "TRF":
            to_wid = int(f.get("to_warehouse_id") or 0)
            if to_wid not in whs:
                raise ValueError("Choose the warehouse the goods are going to.")
            if to_wid == wid:
                raise ValueError("A transfer needs two different warehouses.")
        d = parse_date(f.get("date")) or today()
        lines = _read_lines(f, dtype)
    except ValueError as e:
        flash(str(e), "err")
        return None, _render_form(dtype, doc, f, _form_rows(f))
    did = doc["id"] if doc else None
    lv = st.levels(warehouse_id=wid, exclude_doc=did)
    # stock count: turn counted quantities into differences
    if dtype == "CNT":  # an item may be counted on several lines (different carton sizes): the difference goes on its first line
        lv_date = st.levels(as_of=d, warehouse_id=wid, exclude_doc=did)
        total = defaultdict(float)
        for l in lines:
            total[l["item_id"]] += l["qty"]
        seen = set()
        for l in lines:
            l["counted"] = l["qty"]
            if l["item_id"] in seen:
                l["system"], l["qty"] = None, 0
                continue
            seen.add(l["item_id"])
            l["system"] = lv_date[l["item_id"]]["on_hand"]
            l["qty"] = round(total[l["item_id"]] - l["system"], 3)
    # don't let stock go below zero unless allowed in settings
    if settings().get("allow_negative_stock") != "1" and dtype in ("DC", "TRF", "ADJ"):
        need = defaultdict(float)
        for l in lines:
            if dtype != "ADJ" or l["qty"] < 0:
                need[l["item_id"]] += abs(l["qty"])
        short = [f"{l['item']['code']} (need {qty_fmt(need[l['item_id']])}, have {qty_fmt(lv[l['item_id']]['on_hand'])})"
                 for l in {l["item_id"]: l for l in lines}.values() if need[l["item_id"]] > lv[l["item_id"]]["on_hand"] + 1e-9]
        if short:
            flash(f"Not enough stock in {whs[wid]['name']}: " + ", ".join(short) +
                  ". Receive the goods first, or allow negative stock in Settings.", "err")
            return None, _render_form(dtype, doc, f, _form_rows(f))
    # keep costs a storekeeper can't see when they edit a receipt
    if doc and not sees_cost() and dtype in ("GRN", "OPN"):
        old = {r["item_id"]: r["unit_cost"] for r in q("SELECT item_id, unit_cost FROM wh_lines WHERE doc_id = ?", (did,))}
        for l in lines:
            l["cost"] = old.get(l["item_id"], 0)
    vals = dict(date=d, warehouse_id=wid, to_warehouse_id=to_wid, party=f.get("party", "").strip(), ref=f.get("ref", "").strip(),
                vehicle=f.get("vehicle", "").strip(), notes=f.get("notes", "").strip(),
                invoice_id=None,
                purchase_id=f.get("purchase_id", type=int) if dtype == "GRN" else None)
    if doc:
        x(f"UPDATE wh_docs SET {', '.join(k + ' = :' + k for k in vals)}, updated_at = :t WHERE id = :id", {**vals, "t": now(), "id": did})
        x("DELETE FROM wh_lines WHERE doc_id = ?", (did,))
    else:
        num = (q("SELECT MAX(number) AS m FROM wh_docs WHERE type = ?", (dtype,), one=True)["m"] or 0) + 1
        did = x(f"""INSERT INTO wh_docs (type, number, {', '.join(vals)}, created_by, created_at)
                    VALUES (:type, :number, {', '.join(':' + k for k in vals)}, :uid, :t)""",
                {**vals, "type": dtype, "number": num, "uid": g.user["id"], "t": now()})
    for l in lines:
        x("""INSERT INTO wh_lines (doc_id, item_id, qty, counted, system_qty, unit_cost, note, sort, ctn, ppc, loose)
             VALUES (?,?,?,?,?,?,?,?,?,?,?)""", (did, l["item_id"], l["qty"], l.get("counted"), l.get("system"), l["cost"], l["note"], l["sort"],
                                                l["ctn"], l["ppc"], l["loose"]))
    commit()
    number = q("SELECT number FROM wh_docs WHERE id = ?", (did,), one=True)["number"]
    flash(f"{st.DOC_TYPES[dtype]['name']} {st.doc_no(dtype, number)} saved ({len(lines)} line{'s' if len(lines) != 1 else ''}).", "ok")
    if f.get("action") == "save_new":
        return did, redirect(url_for("wh.doc_new", dtype=dtype))
    return did, redirect(url_for("wh.doc_view", did=did))


@bp.route("/new/<dtype>", methods=["GET", "POST"])
@roles(*WORK)
def doc_new(dtype):
    if dtype not in st.DOC_TYPES:
        abort(404)
    if request.method == "POST":
        return _save(dtype)[1]
    head, rows = _prefill(dtype)
    f = {"warehouse_id": request.args.get("w", "") or "", **head}
    return _render_form(dtype, None, f, rows)


@bp.route("/doc/<int:did>/edit", methods=["GET", "POST"])
@roles(*WORK)
def doc_edit(did):
    doc = q("SELECT * FROM wh_docs WHERE id = ?", (did,), one=True) or abort(404)
    if doc["void"]:
        abort(400, "A void document can't be edited.")
    if request.method == "POST":
        return _save(doc["type"], doc)[1]
    rows = []
    for r in q("""SELECT l.*, it.code, it.pcs_per_ctn FROM wh_lines l JOIN items it ON it.id = l.item_id WHERE l.doc_id = ? ORDER BY l.sort""", (did,)):
        if r["ctn"] is None and r["loose"] is None:  # older line: plain pieces
            pcs = r["counted"] if doc["type"] == "CNT" else r["qty"]
            row = {"ctn": "", "ppc": qty_fmt(st.ppc(r)), "loose": qty_fmt(pcs)}
        else:
            row = {"ctn": qty_fmt(r["ctn"]) if r["ctn"] else "", "ppc": qty_fmt(r["ppc"] or st.ppc(r)), "loose": qty_fmt(r["loose"]) if r["loose"] else ""}
        rows.append({"code": r["code"], **row, "cost": plain(r["unit_cost"]) if r["unit_cost"] and sees_cost() else "", "note": r["note"]})
    return _render_form(doc["type"], doc, dict(doc), rows)


def _doc_values(doc, lines):
    """Total cost value (receipt cost, or average cost for issues) and total sale value (sale price per piece)."""
    lv = st.levels()
    cost = sum(abs(l["qty"]) * ((l["unit_cost"] if doc["type"] in ("GRN", "OPN") and l["unit_cost"] else
                                  lv.get(l["item_id"], {}).get("avg_cost", 0)) or 0) for l in lines)
    sale = sum(abs(l["qty"]) * (l["price"] or 0) for l in lines)
    return int(round(cost)), int(round(sale))


def _get_doc(did):
    doc = q("""SELECT d.*, w.name AS wh_name, w.code AS wh_code, t.name AS to_name, t.code AS to_code, u.name AS by_name
               FROM wh_docs d JOIN warehouses w ON w.id = d.warehouse_id LEFT JOIN warehouses t ON t.id = d.to_warehouse_id
               LEFT JOIN users u ON u.id = d.created_by WHERE d.id = ?""", (did,), one=True)
    if not doc:
        abort(404)
    lines = q("""SELECT l.*, it.code, it.description, it.name, it.unit, it.location, it.pcs_per_ctn, it.price FROM wh_lines l JOIN items it ON it.id = l.item_id
                 WHERE l.doc_id = ? ORDER BY l.sort""", (did,))
    return doc, lines


@bp.route("/doc/<int:did>")
@roles(*WORK)
def doc_view(did):
    doc, lines = _get_doc(did)
    inv = q("SELECT id, number FROM invoices WHERE id = ?", (doc["invoice_id"],), one=True) if doc["invoice_id"] else None
    pur = q("SELECT id, number, bill_no FROM purchases WHERE id = ?", (doc["purchase_id"],), one=True) if doc["purchase_id"] else None
    cost_value, sale_value = _doc_values(doc, lines)
    return render_template("wh/doc_view.html", doc=doc, lines=lines, cost_value=int(round(cost_value)), sale_value=int(round(sale_value)),
                           total_ctn=sum(abs(l["ctn"] or 0) for l in lines), total_pcs=sum(abs(l["qty"]) for l in lines), T=st.DOC_TYPES[doc["type"]], doc_no=st.doc_no(doc["type"], doc["number"]),
                           show_cost=sees_cost(), inv=inv, pur=pur, qty_fmt=qty_fmt,
                           pack=lambda l: st.packing_text({**({float(l["ppc"] or 1): l["ctn"]} if l["ctn"] else {}), **({0: l["loose"]} if l["loose"] else {})}),
                           total_value=sum(int(round(l["qty"] * (l["unit_cost"] or 0))) for l in lines))


@bp.route("/doc/<int:did>.pdf")
@roles(*WORK)
def doc_pdf(did):
    from .notify import _pdf_path
    from .pdfs import wh_document
    doc, lines = _get_doc(did)
    name = st.doc_no(doc["type"], doc["number"])
    from .companies import pdf_settings
    show = sees_cost() and request.args.get("cost") == "1"
    path = wh_document(_pdf_path(f"{name}.pdf"), pdf_settings(), doc, lines, st.DOC_TYPES[doc["type"]], name,
                       show_cost=show, values=_doc_values(doc, lines) if show else None)
    return send_file(path, mimetype="application/pdf")


@bp.route("/doc/<int:did>/void", methods=["POST"])
@roles(*MANAGE)
def doc_void(did):
    doc = q("SELECT * FROM wh_docs WHERE id = ?", (did,), one=True) or abort(404)
    note = (doc["notes"] + "\n" if doc["notes"] else "") + f"VOIDED {now()} by {g.user['name']}: {request.form.get('reason', '')}"
    x("UPDATE wh_docs SET void = 1, notes = ? WHERE id = ?", (note, did))
    commit()
    flash(f"{st.doc_no(doc['type'], doc['number'])} voided. Stock has been put back as it was.", "ok")
    return redirect(url_for("wh.doc_view", did=did))


# ---- stock card ---------------------------------------------------------------------------------
@bp.route("/item/<int:item_id>")
@roles(*VIEW)
def card(item_id):
    wid = request.args.get("w", type=int)
    it, moves = st.card(item_id, wid)
    if not it or it["kind"] != "item":
        abort(404)
    lv = st.levels().get(item_id)
    whs = st.warehouses()
    if request.args.get("export") in ("xlsx", "pdf"):
        data = [[nice_date(m["date"]), st.doc_no(m["type"], m["number"]), st.DOC_TYPES[m["type"]]["short"],
                 m["wh_code"] + (f" → {m['other_code']}" if m.get("moved") else ""), m["party"] or m["note"] or "",
                 qty_fmt(m["qty"]) if m["qty"] > 0 else "", qty_fmt(-m["qty"]) if m["qty"] < 0 else "", qty_fmt(m["balance"])]
                for m in moves]
        return table_response(request.args["export"], f"Stock card {it['code']}", ["Date", "Doc", "Type", "Warehouse", "Party / note",
                              "In", "Out", "Balance"], data, set(), None, it["description"] or it["name"])
    return render_template("wh/card.html", it=it, moves=list(reversed(moves)), lv=lv, whs=whs, wid=wid, show_cost=sees_cost(),
                           pk=st.packing_text(st.packing(wid).get(item_id)),
                           doc_no=st.doc_no, types=st.DOC_TYPES, qty_fmt=qty_fmt)


# ---- movements report -------------------------------------------------------------------------------
@bp.route("/movements")
@roles(*WORK)
def movements():
    t = date.today()
    start = parse_date(request.args.get("from")) or t.replace(day=1).isoformat()
    end = parse_date(request.args.get("to")) or t.isoformat()
    wid = request.args.get("w", type=int)
    from datetime import timedelta
    before = (date.fromisoformat(start) - timedelta(days=1)).isoformat()
    open_lv = st.levels(as_of=before, warehouse_id=wid)
    close_lv = st.levels(as_of=end, warehouse_id=wid)
    args = {"a": start, "b": end}
    wf = ""
    if wid:
        wf = " AND m.wh = :w"
        args["w"] = wid
    moved = defaultdict(lambda: {"in": 0.0, "out": 0.0})
    for m in q(f"SELECT m.* FROM ({st.MOVES}) m WHERE m.date BETWEEN :a AND :b {wf}", args):
        if not wid and m["type"] == "TRF":
            continue
        k = "in" if m["qty"] > 0 else "out"
        moved[m["item_id"]][k] += abs(m["qty"])
    rows = []
    for i, _ in item_rows():
        o, c = open_lv[i["id"]]["on_hand"], close_lv[i["id"]]["on_hand"]
        mv = moved.get(i["id"], {"in": 0, "out": 0})
        if not (o or c or mv["in"] or mv["out"]):
            continue
        rows.append([i["code"], i["description"] or i["name"], i["unit"], qty_fmt(o), qty_fmt(mv["in"]), qty_fmt(mv["out"]), qty_fmt(c)])
    whs = st.warehouses()
    wname = next((w["name"] for w in whs if w["id"] == wid), "All warehouses")
    title = "Stock movements"
    heads = ["Item code", "Description", "U/M", "Opening", "In", "Out", "Closing"]
    if request.args.get("export") in ("xlsx", "pdf"):
        return table_response(request.args["export"], title, heads, rows, set(), None,
                              f"{wname} · {nice_date(start)} to {nice_date(end)}")
    return render_template("report.html", title=title, headers=heads, rows=rows, money_cols=set(), totals=None,
                           filters=["dates", "wh"], whs=whs,
                           note=f"{wname}. Opening = stock on {nice_date(before)}. Transfers between warehouses are not counted "
                                "as in/out when all warehouses are shown.")


# ---- warehouses admin ------------------------------------------------------------------------------
@bp.route("/warehouses", methods=["GET", "POST"])
@roles(*MANAGE)
def warehouses():
    if request.method == "POST":
        f = request.form
        code, name = f.get("code", "").strip().upper()[:10], f.get("name", "").strip()
        if not code or not name:
            flash("Code and name are required.", "err")
            return redirect(url_for("wh.warehouses"))
        wid = f.get("id", type=int)
        dup = q("SELECT id FROM warehouses WHERE code = ? AND id != ?", (code, wid or -1), one=True)
        if dup:
            flash(f"Code {code} is already used.", "err")
            return redirect(url_for("wh.warehouses"))
        vals = (code, name, f.get("address", "").strip(), 1 if f.get("active") else 0)
        if wid:
            x("UPDATE warehouses SET code=?, name=?, address=?, active=? WHERE id=?", vals + (wid,))
        else:
            wid = x("INSERT INTO warehouses (code, name, address, active) VALUES (?,?,?,?)", vals)
        if f.get("is_default"):
            x("UPDATE warehouses SET is_default = CASE WHEN id = ? THEN 1 ELSE 0 END", (wid,))
        commit()
        flash("Warehouse saved.", "ok")
        return redirect(url_for("wh.warehouses"))
    lv = st.levels()
    rows = []
    for w in st.warehouses(active_only=False):
        units = sum(max(v["by_wh"].get(w["id"], 0), 0) for v in lv.values())
        value = sum(int(round(max(v["by_wh"].get(w["id"], 0), 0) * v["avg_cost"])) for v in lv.values())
        items = sum(1 for v in lv.values() if v["by_wh"].get(w["id"], 0) > 0)
        rows.append({"w": w, "units": units, "value": value, "items": items})
    return render_template("wh/warehouses.html", rows=rows, edit=request.args.get("edit", type=int))
