"""Customer balances, open invoices (payments applied oldest-first), statements and aging."""
from datetime import date, timedelta

from .db import q

BAL_SQL = """
  (CASE WHEN c.opening_date IS NULL OR c.opening_date <= :d THEN c.opening_balance ELSE 0 END)
  + COALESCE((SELECT SUM(total) FROM invoices i WHERE i.customer_id = c.id AND i.void = 0 AND i.date <= :d), 0)
  - COALESCE((SELECT SUM(amount) FROM payments p WHERE p.customer_id = c.id AND p.void = 0 AND p.date <= :d), 0)
  - COALESCE((SELECT SUM(total) FROM credit_notes n WHERE n.customer_id = c.id AND n.void = 0 AND n.date <= :d), 0)
"""


def customers_with_balance(as_of=None, where=" ", args=None, order="c.name COLLATE NOCASE"):
    """All customers matching `where` (SQL using alias c, named params) with a `balance` column."""
    params = {"d": as_of or "9999-12-31"}
    params.update(args or {})
    return q(f"""SELECT c.*, r.code AS rep_code, r.name AS rep_name, {BAL_SQL} AS balance
                 FROM customers c LEFT JOIN reps r ON r.id = c.rep_id
                 WHERE 1 = 1 {where} ORDER BY {order}""", params)


def balance(customer_id, as_of=None):
    row = q(f"SELECT {BAL_SQL} AS b FROM customers c WHERE c.id = :cid",
            {"d": as_of or "9999-12-31", "cid": customer_id}, one=True)
    return row["b"] if row else 0


def apply_payments(customer_id, exclude_payment=None):
    """Works out which bills each payment paid.

    Bill-wise payments (apply_mode 'manual') pay exactly the bills they were allocated to; anything
    left over stays as unapplied credit. Auto payments (FIFO) then pay the oldest open amounts first,
    starting with any opening balance.

    Returns dict: open (invoice_id -> open amount), opening_left, credit,
    applied (payment_id -> list of (invoice_id or None for opening balance, amount)).
    """
    c = q("SELECT opening_balance FROM customers WHERE id = ?", (customer_id,), one=True)
    ob = c["opening_balance"] or 0
    invs = q("SELECT id, total FROM invoices WHERE customer_id = ? AND void = 0 ORDER BY date, number", (customer_id,))
    open_ = {i["id"]: i["total"] for i in invs}
    order = [i["id"] for i in invs]
    opening_left = max(ob, 0)
    pool_credit = max(-ob, 0) + q("SELECT COALESCE(SUM(total), 0) AS s FROM credit_notes WHERE customer_id = ? AND void = 0",
                                  (customer_id,), one=True)["s"]
    credit = 0
    applied = {}
    pays = q("SELECT id, amount, apply_mode FROM payments WHERE customer_id = ? AND void = 0 AND id != ? "
             "ORDER BY date, number", (customer_id, exclude_payment or -1))
    manual_ids = [p["id"] for p in pays if p["apply_mode"] == "manual"]
    allocs = {}
    if manual_ids:
        marks = ",".join("?" * len(manual_ids))
        for a in q(f"SELECT payment_id, invoice_id, amount FROM payment_allocations WHERE payment_id IN ({marks}) ORDER BY id",
                   manual_ids):
            allocs.setdefault(a["payment_id"], []).append(a)
    for p in pays:
        if p["apply_mode"] != "manual":
            continue
        used, lst = 0, []
        for a in allocs.get(p["id"], []):
            room = opening_left if a["invoice_id"] is None else open_.get(a["invoice_id"], 0)
            amt = max(0, min(a["amount"], room, p["amount"] - used))
            if not amt:
                continue
            if a["invoice_id"] is None:
                opening_left -= amt
            else:
                open_[a["invoice_id"]] -= amt
            used += amt
            lst.append((a["invoice_id"], amt))
        applied[p["id"]] = lst
        credit += p["amount"] - used

    def fifo(amount):
        nonlocal opening_left
        lst = []
        if opening_left and amount:
            amt = min(amount, opening_left)
            opening_left -= amt
            amount -= amt
            lst.append((None, amt))
        for iid in order:
            if not amount:
                break
            if open_[iid]:
                amt = min(amount, open_[iid])
                open_[iid] -= amt
                amount -= amt
                lst.append((iid, amt))
        return lst, amount

    if pool_credit:
        _, left = fifo(pool_credit)
        credit += left
    for p in pays:
        if p["apply_mode"] == "manual":
            continue
        lst, left = fifo(p["amount"])
        applied[p["id"]] = lst
        credit += left
    return {"open": open_, "opening_left": opening_left, "credit": credit, "applied": applied}


def open_items(customer_id, exclude_payment=None):
    """Returns (open_by_invoice_id, opening_left, unapplied_credit)."""
    r = apply_payments(customer_id, exclude_payment)
    return r["open"], r["opening_left"], r["credit"]


def statement(customer_id, start, end):
    day_before = (date.fromisoformat(start) - timedelta(days=1)).isoformat()
    brought_forward = balance(customer_id, day_before)
    c = q("SELECT opening_balance, opening_date FROM customers WHERE id = ?", (customer_id,), one=True)
    lines = []
    if c["opening_date"] and start <= c["opening_date"] <= end and c["opening_balance"]:
        lines.append({"date": c["opening_date"], "type": "Opening balance", "ref": "", "sort": 0,
                      "debit": max(c["opening_balance"], 0), "credit": max(-c["opening_balance"], 0)})
    for i in q("""SELECT id, number, date, due_date, total FROM invoices
                  WHERE customer_id = ? AND void = 0 AND date BETWEEN ? AND ?""", (customer_id, start, end)):
        lines.append({"date": i["date"], "type": "Invoice", "ref": str(i["number"]), "sort": 1,
                      "debit": i["total"], "credit": 0, "due": i["due_date"], "id": i["id"]})
    for p in q("""SELECT id, number, date, amount, method, reference FROM payments
                  WHERE customer_id = ? AND void = 0 AND date BETWEEN ? AND ?""", (customer_id, start, end)):
        ref = p["method"] + (f" {p['reference']}" if p["reference"] else "")
        lines.append({"date": p["date"], "type": "Payment", "ref": ref, "sort": 2, "debit": 0,
                      "method": p["method"], "reference": p["reference"],
                      "credit": p["amount"], "id": p["id"]})
    for n in q("""SELECT id, number, date, total, invoice_ref FROM credit_notes
                  WHERE customer_id = ? AND void = 0 AND date BETWEEN ? AND ?""", (customer_id, start, end)):
        lines.append({"date": n["date"], "type": "Credit note", "ref": str(n["number"]) + (f" (inv {n['invoice_ref']})" if n["invoice_ref"] else ""),
                      "sort": 3, "debit": 0, "credit": n["total"], "id": n["id"]})
    lines.sort(key=lambda l: (l["date"], l["sort"], l["ref"]))
    run = brought_forward
    for l in lines:
        run += l["debit"] - l["credit"]
        l["balance"] = run
    return {
        "start": start, "end": end, "brought_forward": brought_forward, "lines": lines, "closing": run,
        "invoiced": sum(l["debit"] for l in lines), "paid": sum(l["credit"] for l in lines),
    }


BUCKETS = ["Current", "1-30", "31-60", "61-90", "90+"]


def _bucket(days_overdue):
    if days_overdue <= 0:
        return "Current"
    if days_overdue <= 30:
        return "1-30"
    if days_overdue <= 60:
        return "31-60"
    if days_overdue <= 90:
        return "61-90"
    return "90+"


AGE_BUCKETS = ["0-30", "31-60", "61-90", "91-180", "180+"]


def _age_bucket(days):
    for hi, k in ((30, "0-30"), (60, "31-60"), (90, "61-90"), (180, "91-180")):
        if days <= hi:
            return k
    return "180+"


def customer_aging(customer_id, as_of=None, basis="due"):
    """Buckets for one customer's open amounts (unapplied credit reduces the newest bucket).
    basis 'due': days overdue (Current, 1-30 …); basis 'invoice': days since the invoice date (0-30, 31-60 …)."""
    if basis == "invoice":
        return _invoice_age(customer_id, as_of)
    as_of_d = date.fromisoformat(as_of) if as_of else date.today()
    open_by_inv, opening_left, credit = open_items(customer_id)
    b = dict.fromkeys(BUCKETS, 0)
    if opening_left:
        od = q("SELECT opening_date FROM customers WHERE id = ?", (customer_id,), one=True)["opening_date"]
        b[_bucket((as_of_d - date.fromisoformat(od)).days if od else 999)] += opening_left
    ids = [k for k, v in open_by_inv.items() if v]
    if ids:
        marks = ",".join("?" * len(ids))
        for inv in q(f"SELECT id, date, due_date FROM invoices WHERE id IN ({marks})", ids):
            due = date.fromisoformat(inv["due_date"] or inv["date"])
            b[_bucket((as_of_d - due).days)] += open_by_inv[inv["id"]]
    if credit:
        b["Current"] -= credit
    return b


def _invoice_age(customer_id, as_of=None):
    as_of_d = date.fromisoformat(as_of) if as_of else date.today()
    open_by_inv, opening_left, credit = open_items(customer_id)
    b = dict.fromkeys(AGE_BUCKETS, 0)
    if opening_left:
        od = q("SELECT opening_date FROM customers WHERE id = ?", (customer_id,), one=True)["opening_date"]
        b[_age_bucket((as_of_d - date.fromisoformat(od)).days if od else 999)] += opening_left
    ids = [k for k, v in open_by_inv.items() if v]
    if ids:
        for inv in q(f"SELECT id, date FROM invoices WHERE id IN ({','.join('?' * len(ids))})", ids):
            b[_age_bucket((as_of_d - date.fromisoformat(inv["date"])).days)] += open_by_inv[inv["id"]]
    if credit:
        b["0-30"] -= credit
    return b


def aging(where=" ", args=None, as_of=None, basis="due"):
    rows = []
    for c in customers_with_balance(None, where + " AND c.active = 1", args):
        if not c["balance"]:
            continue
        b = customer_aging(c["id"], as_of, basis)
        rows.append({"customer": c, "buckets": b, "total": sum(b.values())})
    totals = {k: sum(r["buckets"][k] for r in rows) for k in (AGE_BUCKETS if basis == "invoice" else BUCKETS)}
    return rows, totals, sum(totals.values())


def open_statement(customer_id, as_of=None):
    """'All open transactions' statement: every bill still unpaid, plus any advance."""
    open_by_inv, opening_left, credit = open_items(customer_id)
    lines = []
    c = q("SELECT opening_date FROM customers WHERE id = ?", (customer_id,), one=True)
    if opening_left:
        lines.append({"date": c["opening_date"] or "", "type": "Opening balance", "ref": "", "debit": opening_left,
                      "credit": 0})
    ids = [k for k, v in open_by_inv.items() if v]
    if ids:
        marks = ",".join("?" * len(ids))
        for i in q(f"SELECT id, number, date, due_date, total FROM invoices WHERE id IN ({marks}) ORDER BY date, number", ids):
            lines.append({"date": i["date"], "type": "Invoice", "ref": str(i["number"]), "due": i["due_date"],
                          "debit": open_by_inv[i["id"]], "credit": 0, "id": i["id"], "total": i["total"]})
    if credit:
        lines.append({"date": as_of or date.today().isoformat(), "type": "Unapplied payment", "ref": "advance",
                      "debit": 0, "credit": credit})
    run = 0
    for l in lines:
        run += l["debit"] - l["credit"]
        l["balance"] = run
    return {"start": None, "end": as_of or date.today().isoformat(), "brought_forward": 0, "lines": lines,
            "closing": run, "invoiced": sum(l["debit"] for l in lines), "paid": sum(l["credit"] for l in lines),
            "open_mode": True}
