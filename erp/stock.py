"""Warehouse stock engine.

Stock is kept completely separate from invoices and purchase bills: it only changes through warehouse
documents. Every quantity is kept in PIECES. Lines are entered as cartons x pieces-per-carton + loose pieces, and the
same item can come in different carton sizes (two lines), so stock is also shown packed: e.g. "10 x 24 + 5 x 12 + 7 loose".
Costs are per piece; the sale value uses the item's sale price per piece.

  OPN  Opening stock      + qty in warehouse
  GRN  Goods receipt      + qty in warehouse
  DC   Goods issue note   - qty from warehouse (goods issued; shown as GIN, not linked to invoices)
  TRF  Stock transfer     - qty from warehouse, + qty in to_warehouse
  ADJ  Adjustment         +/- qty in warehouse (qty is signed)
  CNT  Stock count        + (counted - system) in warehouse (qty holds the difference)
"""
from .db import q

DOC_TYPES = {
    "GRN": {"name": "Goods receipt", "short": "Receipt", "sign": 1, "icon": "download", "party": "Received from",
            "pdf": "GOODS RECEIPT NOTE"},
    "DC": {"name": "Goods issue note", "short": "Issue", "sign": -1, "icon": "truck", "party": "Issued to",
           "pdf": "GOODS ISSUE NOTE"},
    "TRF": {"name": "Stock transfer", "short": "Transfer", "sign": 0, "icon": "layers", "party": "", "pdf": "STOCK TRANSFER NOTE"},
    "ADJ": {"name": "Stock adjustment", "short": "Adjustment", "sign": 1, "icon": "settings", "party": "", "pdf": "STOCK ADJUSTMENT"},
    "CNT": {"name": "Stock count", "short": "Count", "sign": 1, "icon": "list", "party": "", "pdf": "STOCK COUNT SHEET"},
    "OPN": {"name": "Opening stock", "short": "Opening", "sign": 1, "icon": "box", "party": "", "pdf": "OPENING STOCK"},
}

# Every stock movement as (item, warehouse, qty, cost, date, doc) rows.
MOVES = """
  SELECT l.item_id, d.warehouse_id AS wh, CASE d.type WHEN 'DC' THEN -l.qty WHEN 'TRF' THEN -l.qty ELSE l.qty END AS qty,
         l.unit_cost, d.type, d.date, d.id AS doc_id, d.number, d.party, d.ref, d.to_warehouse_id AS other_wh, l.note
    FROM wh_lines l JOIN wh_docs d ON d.id = l.doc_id WHERE d.void = 0
  UNION ALL
  SELECT l.item_id, d.to_warehouse_id, l.qty, l.unit_cost, d.type, d.date, d.id, d.number, d.party, d.ref, d.warehouse_id, l.note
    FROM wh_lines l JOIN wh_docs d ON d.id = l.doc_id WHERE d.void = 0 AND d.type = 'TRF'
"""


PREFIX = {"DC": "GIN"}


def doc_no(t, n):
    return f"{PREFIX.get(t, t)}-{int(n):05d}"


def ppc(item):
    """Pieces per carton for an item row (at least 1)."""
    try:
        v = item["pcs_per_ctn"] or 0
    except (IndexError, KeyError):
        v = 0
    return v if v and v > 0 else 1


def warehouses(active_only=True):
    return q("SELECT * FROM warehouses" + (" WHERE active = 1" if active_only else "") + " ORDER BY is_default DESC, name")


def default_warehouse():
    return q("SELECT * FROM warehouses WHERE active = 1 ORDER BY is_default DESC, id LIMIT 1", one=True)


def levels(as_of=None, warehouse_id=None, exclude_doc=None):
    """{item_id: {on_hand, by_wh {wid: qty}, received, issued, avg_cost, value}} for every stock item."""
    items = q("SELECT id, opening_cost, pcs_per_ctn, price FROM items WHERE kind = 'item' AND track_stock = 1")
    res = {i["id"]: {"on_hand": 0.0, "by_wh": {}, "received": 0.0, "issued": 0.0, "ppc": ppc(i), "price": i["price"] or 0,
                     "std_cost": i["opening_cost"] or 0, "cost_qty": 0.0, "cost_amt": 0} for i in items}
    where, args = [], {}
    if as_of:
        where.append("m.date <= :d")
        args["d"] = as_of
    if exclude_doc:
        where.append("m.doc_id != :x")
        args["x"] = exclude_doc
    sql = f"SELECT m.* FROM ({MOVES}) m" + (" WHERE " + " AND ".join(where) if where else "")
    for m in q(sql, args):
        r = res.get(m["item_id"])
        if r is None:
            continue
        qty = m["qty"] or 0
        r["by_wh"][m["wh"]] = round(r["by_wh"].get(m["wh"], 0) + qty, 3)
        if m["type"] != "TRF":
            if qty > 0:
                r["received"] += qty
            else:
                r["issued"] -= qty
        if m["type"] in ("GRN", "OPN") and m["unit_cost"] and qty > 0:
            r["cost_qty"] += qty
            r["cost_amt"] += qty * m["unit_cost"]
    for r in res.values():
        r["on_hand"] = round(r["by_wh"].get(warehouse_id, 0) if warehouse_id else sum(r["by_wh"].values()), 3)
        r["avg_cost"] = int(round(r["cost_amt"] / r["cost_qty"])) if r["cost_qty"] else r["std_cost"]
        r["value"] = int(round(max(r["on_hand"], 0) * r["avg_cost"]))  # cost value (cost per piece)
        r["pcs"] = r["on_hand"]
        r["sale_value"] = int(round(max(r["pcs"], 0) * r["price"]))  # pieces × sale price per piece
    return res


def line_pcs(ctn, ppc_, loose):
    return round((ctn or 0) * (ppc_ or 1) + (loose or 0), 3)


def packing(warehouse_id=None):
    """{item_id: {ppc: cartons, 0: loose pieces}} - stock by carton size, in date order (a stock count resets it)."""
    rows = q("""SELECT l.item_id, l.qty, l.ctn, l.ppc, l.loose, l.counted, d.type, d.id AS doc_id, d.warehouse_id, d.to_warehouse_id
                FROM wh_lines l JOIN wh_docs d ON d.id = l.doc_id WHERE d.void = 0 ORDER BY d.date, d.id, l.sort""")
    pk = {}  # (item, wh) -> {ppc: ctn, 0: loose}

    def parts(r):
        if r["ctn"] is None and r["loose"] is None:  # older lines: plain pieces
            return {0: abs(r["counted"] if r["type"] == "CNT" else r["qty"]) * (1 if r["type"] == "CNT" or r["qty"] >= 0 else 1)}
        out = {}
        if r["ctn"]:
            out[float(r["ppc"] or 1)] = r["ctn"]
        if r["loose"]:
            out[0] = r["loose"]
        return out

    def add(key, p, sign):
        d = pk.setdefault(key, {})
        for k, v in p.items():
            d[k] = round(d.get(k, 0) + sign * v, 3)

    reset = set()
    for r in rows:
        key = (r["item_id"], r["warehouse_id"])
        p = parts(r)
        t = r["type"]
        if t == "CNT":
            if (r["doc_id"], key) not in reset:
                pk[key] = {}
                reset.add((r["doc_id"], key))
            add(key, p, 1)
        elif t in ("GRN", "OPN"):
            add(key, p, 1)
        elif t == "ADJ":
            sign = 1
            if r["ctn"] is None and r["loose"] is None and r["qty"] < 0:
                sign = -1
            add(key, p, sign)
        elif t == "DC":
            add(key, p, -1)
        elif t == "TRF":
            add(key, p, -1)
            add((r["item_id"], r["to_warehouse_id"]), p, 1)
    out = {}
    for (item, wh), d in pk.items():
        if warehouse_id and wh != warehouse_id:
            continue
        o = out.setdefault(item, {})
        for k, v in _tidy(d).items():
            o[k] = round(o.get(k, 0) + v, 3)
    return out


def _tidy(d):
    """Loose pieces issued from full cartons: open cartons (smallest size first) so nothing shows negative."""
    import math
    d = dict(d)
    loose = d.pop(0, 0)
    for k in [k for k, v in d.items() if v < 0]:
        loose += d.pop(k) * k
    for k in sorted(d):
        if loose >= 0:
            break
        need = min(d[k], math.ceil(-loose / k))
        d[k] -= need
        loose += need * k
    d = {k: v for k, v in d.items() if v}
    if loose:
        d[0] = round(loose, 3)
    return d


def packing_text(p):
    """{24: 10, 12: 5, 0: 7} -> '10 ctn x 24 + 5 ctn x 12 + 7 loose'."""
    if not p:
        return ""
    bits = [f"{v:g} ctn × {k:g}" for k, v in sorted(p.items(), key=lambda kv: -kv[0]) if k and v]
    if p.get(0):
        bits.append(f"{p[0]:g} loose")
    return " + ".join(bits)


def card(item_id, warehouse_id=None):
    """Movements for one item, oldest first, with running quantity (for one warehouse or all)."""
    it = q("SELECT * FROM items WHERE id = ?", (item_id,), one=True)
    args = {"i": item_id}
    extra = ""
    if warehouse_id:
        extra = " AND m.wh = :w"
        args["w"] = warehouse_id
    rows = q(f"""SELECT m.*, w.code AS wh_code, o.code AS other_code FROM ({MOVES}) m
                 LEFT JOIN warehouses w ON w.id = m.wh LEFT JOIN warehouses o ON o.id = m.other_wh
                 WHERE m.item_id = :i {extra} ORDER BY m.date, m.doc_id""", args)
    run, out = 0.0, []
    for r in rows:
        if not warehouse_id and r["type"] == "TRF":
            # across all warehouses a transfer doesn't change the total: show it once, without in/out
            if (r["qty"] or 0) < 0:
                out.append({**dict(r), "qty": 0, "moved": -r["qty"], "balance": run})
            continue
        run = round(run + (r["qty"] or 0), 3)
        out.append({**dict(r), "balance": run})
    return it, out
