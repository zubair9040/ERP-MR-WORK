"""Admin commands.

  python manage.py demo               fill an empty system with sample data (for trying it out)
  python manage.py reset-password USERNAME NEWPASSWORD
  python manage.py backup             copy the database to data/backups/
"""
import os
import random
import shutil
import sys
from datetime import date, datetime, timedelta

from werkzeug.security import generate_password_hash

from erp import create_app
from erp.db import commit, get_db, now, q, set_setting, x

app = create_app()


def demo():
    if q("SELECT 1 FROM customers LIMIT 1"):
        sys.exit("There is already data. Demo data can only be added to an empty system.")
    random.seed(7)
    set_setting("company_name", "Demo Stationers")
    set_setting("company_address", "Urdu Bazar\nLahore")
    set_setting("company_phone", "042-1112223")
    set_setting("currency", "PKR")
    # three companies: one non-GST (purchases + salaries), two GST-registered
    # cos[0] = the non-GST company (purchases + salaries); cos[1], cos[2] = GST registered
    x("""UPDATE companies SET code = 'MS', name = 'Makkisons', gst_registered = 0, default_tax_rate = 0, ntn = '1234567-8',
         address = 'Urdu Bazar, Lahore', phone = '042-1112223', website = 'www.makkisons.com', color = '#1f6fb5',
         next_invoice_number = 13001, sort = 3 WHERE id = (SELECT id FROM companies ORDER BY id LIMIT 1)""")
    cos = [q("SELECT id FROM companies ORDER BY id LIMIT 1", one=True)["id"]]
    for code, name, color, ntn, gst, nxt, srt in [("MRE-1", "M.R Enterprises", "#1d4ed8", "7654321-0", "32-77-8761-234-56", 5001, 1),
                                                  ("MRE-2", "M.R Enterprises", "#0e7490", "7654329-1", "32-77-8761-999-10", 7001, 2)]:
        cos.append(x("""INSERT INTO companies (code, name, gst_registered, default_tax_rate, ntn, gst_no, address, phone, color,
                        next_invoice_number, sort) VALUES (?,?,1,18,?,?,?,?,?,?,?)""",
                     (code, name, ntn, gst, "Shahalam Market, Lahore", "042-7654321", color, nxt, srt)))
    set_setting("default_purchase_company", str(cos[0]))
    set_setting("salary_company", str(cos[0]))
    if not q("SELECT 1 FROM users LIMIT 1"):
        x("INSERT INTO users (username, name, password_hash, role, created_at) VALUES (?,?,?,?,?)",
          ("admin", "Admin", generate_password_hash("admin12345"), "admin", ""))
    reps = [x("INSERT INTO reps (code, name, phone) VALUES (?,?,?)", r) for r in
            [("RIZ", "Rizwan", "0300-1111111"), ("SB", "Sana Baig", "0301-2222222"), ("IM", "Imran Malik", "0302-3333333")]]
    x("INSERT INTO users (username, name, password_hash, role, rep_id, created_at) VALUES (?,?,?,?,?,?)",
      ("rizwan", "Rizwan", generate_password_hash("rizwan123"), "rep", reps[0], ""))
    items = [x("INSERT INTO items (code, name, description, unit, price) VALUES (?,?,?,?,?)", i) for i in [
        ("SPECIAL BIG", "Gem clip special big", "GEM CLIP THREE FLOWERS 30 MM SPECIAL BIG", "Box", 46000),
        ("TF7950", "Stamp pad TF7950", "STAMP PAD THREE FLOWERS TF7950", "Doz", 60000),
        ("PUSH PIN TF", "Push pin", "PUSH PIN THREE FLOWERS", "Box", 37000),
        ("STAPLER 10", "Stapler No.10", "STAPLER NO. 10 THREE FLOWERS", "Doz", 180000),
        ("PIN 24/6", "Staple pin 24/6", "STAPLE PIN 24/6 THREE FLOWERS", "Box", 25000),
        ("GLUE 35G", "Glue stick 35g", "GLUE STICK 35 GM", "Doz", 42000)]]
    x("INSERT INTO items (code, name, description, kind, percent) VALUES ('5%', '5% discount', '5% SALES DISCOUNT', 'discount', -5)")
    x("INSERT INTO items (code, name, description, kind, percent) VALUES ('10%', '10% discount', '10% SALES DISCOUNT', 'discount', -10)")
    sub_id = q("SELECT id FROM items WHERE kind = 'subtotal'", one=True)["id"]
    names = ["Ahsan Stationers LHR", "Madina Book Depot", "Hassan & Sons", "City Stationers", "Bismillah Traders",
             "Urdu Bazar Wholesale", "Green Valley School Supplies", "Star Stationers", "Rehman Brothers", "Sunrise Paper House"]
    today = date.today()
    start = (today.replace(day=1) - timedelta(days=100)).replace(day=1)
    custs = []
    for n, name in enumerate(names):
        ob = random.choice([0, 0, 2500000, 4500000])
        custs.append(x("""INSERT INTO customers (name, contact, whatsapp, address, rep_id, terms_days, opening_balance,
                          opening_date, credit_limit, created_at, company_id) VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
                       (name, "", f"0300-{1234560 + n}" if n != 7 else "", "Urdu Bazar, Lahore", reps[n % 3],
                        random.choice([15, 30, 30, 45]), ob, (start - timedelta(days=1)).isoformat() if ob else None,
                        random.choice([0, 50000000]), "", cos[0] if n < 5 else cos[1 + n % 2])))
    numbers = {cos[0]: 13001, cos[1]: 5001, cos[2]: 7001}
    d = start
    while d <= today:
        for _ in range(random.randint(0, 2)):
            cid = random.choice(custs)
            c = q("SELECT * FROM customers WHERE id = ?", (cid,), one=True)
            lines = []
            for it in random.sample(items, random.randint(1, 3)):
                r = q("SELECT * FROM items WHERE id = ?", (it,), one=True)
                qty = random.randint(5, 50)
                lines.append(dict(item_id=it, code=r["code"], description=r["description"], unit=r["unit"],
                                  ctn_qty=random.choice(["", "1", "MIX"]), qty=qty, rate=r["price"], percent=None,
                                  kind="item", amount=qty * r["price"]))
            if random.random() < 0.4:
                lines.append(dict(item_id=sub_id, code="SUB TOTAL", description="SUB TOTAL", unit="", ctn_qty="",
                                  qty=None, rate=0, percent=None, kind="subtotal", amount=0))
                lines.append(dict(item_id=None, code="5%", description="5% SALES DISCOUNT", unit="", ctn_qty="",
                                  qty=None, rate=0, percent=-5.0, kind="discount", amount=0))
            from erp.lines import compute
            sub = compute(lines)
            co = c["company_id"]
            number = numbers[co]
            rate = 0 if co == cos[0] else 18
            tax = int(round(sub * rate / 100))
            iid = x("""INSERT INTO invoices (number, date, due_date, customer_id, rep_id, subtotal, tax_rate, tax, total, via, ref_no,
                       ctn_count, bilti_no, created_at, company_id) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                    (number, d.isoformat(), (d + timedelta(days=c["terms_days"])).isoformat(), cid, c["rep_id"], sub, rate, tax,
                     sub + tax, "TRANSPORT", str(12000 + number), f"({random.randint(1, 6)} CTN)",
                     random.choice(["", "NASEEB GOODS 2541", "DAEWOO CARGO"]), "", co))
            for k, l in enumerate(lines):
                x("""INSERT INTO invoice_lines (invoice_id, item_id, code, description, unit, ctn_qty, qty, rate, percent,
                     amount, kind, sort) VALUES (:iid, :item_id, :code, :description, :unit, :ctn_qty, :qty, :rate,
                     :percent, :amount, :kind, :sort)""", {**l, "iid": iid, "sort": k})
            numbers[co] += 1
        d += timedelta(days=1)
    pnum = 1
    for cid in custs:
        owed = q("SELECT COALESCE(SUM(total),0) AS s FROM invoices WHERE customer_id = ?", (cid,), one=True)["s"]
        paid = int(owed * random.choice([0.3, 0.6, 0.8, 1.0]) / 100000) * 100000
        pd = start + timedelta(days=20)
        while paid > 0 and pd < today:
            amt = min(paid, random.choice([5000000, 10000000, 20000000]))
            x("""INSERT INTO payments (number, date, customer_id, amount, method, reference, created_at)
                 VALUES (?,?,?,?,?,?,?)""", (pnum, pd.isoformat(), cid, amt, random.choice(["Cash", "Cheque", "Bank transfer"]),
                                             "", ""))
            pnum += 1
            paid -= amt
            pd += timedelta(days=random.randint(10, 25))
    # --- purchasing, stock, returns, expenses ---
    for it in items:
        price = q("SELECT price FROM items WHERE id = ?", (it,), one=True)["price"]
        x("UPDATE items SET opening_cost = ?, reorder_level = ?, location = ?, barcode = ? WHERE id = ?",
          (int(price * 0.72), random.choice([80, 150, 250]), f"Rack {'ABC'[it % 3]}-{it}", f"89600{it:05d}", it))
    sups = [x("INSERT INTO suppliers (name, contact, phone, terms_days, created_at) VALUES (?,?,?,?,?)", s_) for s_ in [
        ("Three Flowers Industries", "Mr. Kamran", "042-35550000", 30, ""),
        ("Paper Mart Karachi", "Faisal", "021-32220000", 15, ""),
        ("Glue & Co.", "Nadeem", "0300-9998887", 30, "")]]
    pno, yno = 1, 1
    d2 = start
    while d2 <= today:
        for sid in sups:
            if random.random() < 0.5:
                chosen = random.sample(items, 2)
                lines, tot = [], 0
                for it in chosen:
                    r = q("SELECT * FROM items WHERE id = ?", (it,), one=True)
                    qty = random.choice([150, 250, 400])
                    cost = int(r["price"] * random.choice([0.68, 0.7, 0.74]))
                    lines.append((it, r["code"], r["description"], r["unit"], qty, cost, qty * cost))
                    tot += qty * cost
                pid = x("""INSERT INTO purchases (number, bill_no, date, due_date, supplier_id, subtotal, total, created_at)
                           VALUES (?,?,?,?,?,?,?,?)""", (pno, f"TF-{2000 + pno}", d2.isoformat(), (d2 + timedelta(days=30)).isoformat(), sid, tot, tot, ""))
                for k, l in enumerate(lines):
                    x("INSERT INTO purchase_lines (purchase_id, item_id, code, description, unit, qty, rate, amount, sort) VALUES (?,?,?,?,?,?,?,?,?)",
                      (pid,) + l + (k,))
                pno += 1
        if d2.day == 1 or d2.day == 15:
            for sid in sups[:2]:
                x("""INSERT INTO supplier_payments (number, date, supplier_id, amount, method, reference, created_at, company_id)
                     VALUES (?,?,?,?,?,?,?,?)""",
                  (yno, d2.isoformat(), sid, random.choice([100000, 200000, 300000]) * 100 // 100 * 1, "Bank transfer", f"TRF {yno}", "",
                   cos[yno % 3]))
                yno += 1
            for cat, amt in [("Rent", 15000000), ("Electricity", 3500000), ("Transport / cartage", 1800000)]:
                if d2.day == 1 or cat == "Transport / cartage":
                    x("INSERT INTO expenses (date, category, payee, amount, method, created_at) VALUES (?,?,?,?,?,?)",
                      (d2.isoformat(), cat, "", amt // 10, "Cash", ""))
        d2 += timedelta(days=7) if d2.day not in (1, 15) else timedelta(days=1)
    it = items[0]
    r = q("SELECT * FROM items WHERE id = ?", (it,), one=True)
    nid = x("""INSERT INTO credit_notes (number, date, customer_id, invoice_ref, restock, subtotal, total, notes, created_at)
               VALUES (1, ?, ?, '13005', 1, ?, ?, 'Damaged cartons returned', '')""", ((today - timedelta(days=10)).isoformat(), custs[1], 3 * r["price"], 3 * r["price"]))
    x("INSERT INTO credit_note_lines (credit_note_id, item_id, code, description, unit, qty, rate, amount, sort) VALUES (?,?,?,?,?,?,?,?,0)",
      (nid, it, r["code"], r["description"], r["unit"], 3, r["price"], 3 * r["price"]))
    x("UPDATE settings SET value = '2' WHERE key = 'next_credit_number'")
    # --- warehouse: two warehouses, opening stock, receipts from purchase bills, challans for invoices ---
    main = q("SELECT id FROM warehouses WHERE is_default = 1", one=True)["id"]
    x("UPDATE warehouses SET name = 'Main godown', address = 'Plot 12, Industrial Area' WHERE id = ?", (main,))
    shop = x("INSERT INTO warehouses (code, name, address, active) VALUES ('SHOP', 'Urdu Bazar shop', 'Urdu Bazar, Lahore', 1)")
    nums = {}

    def wdoc(t, d, wid, lines, to=None, party="", ref="", inv=None, pur=None, notes=""):
        nums[t] = nums.get(t, 0) + 1
        did = x("""INSERT INTO wh_docs (type, number, date, warehouse_id, to_warehouse_id, party, ref, invoice_id, purchase_id, notes, created_by, created_at)
                   VALUES (?,?,?,?,?,?,?,?,?,?,1,?)""", (t, nums[t], d, wid, to, party, ref, inv, pur, notes, d + " 10:00"))
        for k, (iid_, qty, cost) in enumerate(lines):
            x("INSERT INTO wh_lines (doc_id, item_id, qty, unit_cost, sort) VALUES (?,?,?,?,?)", (did, iid_, qty, cost, k))
        return did
    op_date = (start - timedelta(days=1)).isoformat()
    wdoc("OPN", op_date, main, [(it, 300, q("SELECT opening_cost FROM items WHERE id=?", (it,), one=True)["opening_cost"]) for it in items],
         notes="Opening stock")
    wdoc("OPN", op_date, shop, [(it, 40, q("SELECT opening_cost FROM items WHERE id=?", (it,), one=True)["opening_cost"]) for it in items[:4]],
         notes="Opening stock")
    events = []
    for p in q("SELECT p.*, s.name FROM purchases p JOIN suppliers s ON s.id = p.supplier_id"):
        events.append((p["date"], 0, "GRN", p))
    for i in q("SELECT i.*, c.name FROM invoices i JOIN customers c ON c.id = i.customer_id WHERE i.date <= ?", ((today - timedelta(days=3)).isoformat(),)):
        events.append((i["date"], 1, "DC", i))
    level = {it: 300 for it in items}
    for d_, _, t, r in sorted(events, key=lambda e: (e[0], e[1])):
        if t == "GRN":
            ls = [(l["item_id"], l["qty"], l["rate"]) for l in q("SELECT * FROM purchase_lines WHERE purchase_id = ?", (r["id"],))]
            for a, b, _c in ls:
                level[a] += b
            wdoc("GRN", d_, main, ls, party=r["name"], ref=f"Bill {r['bill_no']}", pur=r["id"])
        else:
            ls = [(l["item_id"], l["qty"], 0) for l in q("SELECT * FROM invoice_lines WHERE invoice_id = ? AND kind = 'item' AND item_id IS NOT NULL", (r["id"],))]
            if all(level[a] >= b for a, b, _c in ls):
                for a, b, _c in ls:
                    level[a] -= b
                wdoc("DC", d_, main, ls, party=r["name"], ref=f"Invoice {r['number']}", inv=r["id"])
    wdoc("TRF", (today - timedelta(days=12)).isoformat(), main, [(items[0], 30, 0), (items[1], 24, 0)], to=shop, notes="Shop refill")
    cnt = wdoc("CNT", (today - timedelta(days=6)).isoformat(), shop, [], notes="Monthly stock count")
    for k, it in enumerate(items[:3]):
        x("INSERT INTO wh_lines (doc_id, item_id, qty, counted, system_qty, sort) VALUES (?,?,?,?,?,?)",
          (cnt, it, -2 if k == 1 else 0, (68 if k == 0 else 62 if k == 1 else 40), (70 if k == 0 else 64 if k == 1 else 40), k))
    x("UPDATE wh_lines SET qty = counted - system_qty WHERE doc_id = ?", (cnt,))
    wdoc("ADJ", (today - timedelta(days=2)).isoformat(), main, [(items[2], -5, 0)], notes="Water damaged cartons")
    # the warehouse works in cartons: give every item a carton size and make receipt costs per carton
    for k, it in enumerate(items):
        x("UPDATE items SET pcs_per_ctn = ? WHERE id = ?", ([12, 24, 48, 6, 10, 20][k % 6], it))
    x("UPDATE wh_docs SET invoice_id = NULL, ref = REPLACE(ref, 'Invoice', 'Order') WHERE type = 'DC'")
    # item groups
    for kw, grp in (("STAPLE", "Staplers & pins"), ("PIN", "Staplers & pins"), ("GLUE", "Glue sticks"), ("GUM", "Glue sticks"),
                    ("CLIP", "Clips"), ("STAMP", "Stamp pads"), ("FILE", "Files")):
        x("UPDATE items SET grp = ? WHERE grp = '' AND kind = 'item' AND (UPPER(name) LIKE ? OR UPPER(description) LIKE ?)",
          (grp, f"%{kw}%", f"%{kw}%"))
    # split every line into full cartons + loose pieces
    for l in q("""SELECT l.id, l.qty, l.counted, d.type, i.pcs_per_ctn FROM wh_lines l JOIN wh_docs d ON d.id = l.doc_id
                  JOIN items i ON i.id = l.item_id"""):
        k = l["pcs_per_ctn"] or 1
        base = l["counted"] if l["type"] == "CNT" else l["qty"]
        ctn = int(abs(base) // k) * (1 if base >= 0 else -1)
        x("UPDATE wh_lines SET ctn = ?, ppc = ?, loose = ? WHERE id = ?", (ctn, k, round(base - ctn * k, 3), l["id"]))
    _demo_salary(today)
    commit()
    print("Demo data added. Log in as admin / admin12345 (or rep: rizwan / rizwan123).")


def _demo_salary(today):
    import random
    from erp.hr import _fill_missing, calc, get_run, month_days
    rnd = random.Random(7)
    first = ["Muhammad", "Ali", "Ahmed", "Bilal", "Usman", "Hamza", "Imran", "Kashif", "Naveed", "Shahid", "Tariq", "Waqas", "Zeeshan",
             "Asif", "Faisal", "Junaid", "Adnan", "Sajid", "Rizwan", "Arshad", "Nadeem", "Sohail"]
    last = ["Khan", "Ahmed", "Iqbal", "Butt", "Malik", "Qureshi", "Sheikh", "Raza", "Hussain", "Akhtar", "Javed", "Aslam"]
    roles = [("Office", "Accountant", 85000), ("Office", "Data entry", 45000), ("Sales", "Salesman", 55000), ("Sales", "Sales manager", 140000),
             ("Warehouse", "Store keeper", 60000), ("Warehouse", "Loader", 37000), ("Warehouse", "Packer", 37000),
             ("Delivery", "Driver", 45000), ("Delivery", "Rider", 38000), ("Office", "Office boy", 37000)]
    ids = []
    for n in range(44):
        dept, desig, base = roles[0 if n < 2 else 3 if n == 2 else rnd.randrange(1, len(roles))]
        basic = base + rnd.randrange(0, 8) * 1000
        allow = rnd.choice([0, 0, 3000, 5000, 8000])
        join = (today - timedelta(days=rnd.randrange(60, 2500))).isoformat()
        name = f"{rnd.choice(first)} {rnd.choice(last)}"
        ids.append(x("""INSERT INTO employees (code, name, father_name, phone, whatsapp, designation, department, join_date, basic, allowance,
                         pay_method, bank_name, bank_account, created_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                     (f"E{n + 1:03d}", name, f"{rnd.choice(first)} {rnd.choice(last)}", f"0300{rnd.randrange(1000000, 9999999)}",
                      f"0321{rnd.randrange(1000000, 9999999)}", desig, dept, join, basic * 100, allow * 100,
                      "Bank transfer" if basic >= 55000 else "Cash", "Meezan Bank" if basic >= 55000 else "",
                      f"PK36MEZN00{rnd.randrange(10 ** 11, 10 ** 12)}" if basic >= 55000 else "", now())))
    # one new joiner this month
    x("UPDATE employees SET join_date = ? WHERE id = ?", ((today.replace(day=1) + timedelta(days=9)).isoformat(), ids[-1]))
    last_m = (today.replace(day=1) - timedelta(days=1))
    for eid, amt, inst, d in [(ids[5], 20000, 5000, 70), (ids[11], 10000, 0, 20), (ids[17], 60000, 10000, 100), (ids[23], 15000, 0, 12),
                              (ids[30], 8000, 0, 5)]:
        x("INSERT INTO emp_advances (employee_id, date, kind, amount, installment, method, created_at) VALUES (?,?,?,?,?,?,?)",
          (eid, (today - timedelta(days=d)).isoformat(), "Loan" if amt >= 20000 else "Advance", amt * 100, inst * 100, "Cash", now()))
    for back in (2, 1):
        m = today.replace(day=1)
        for _ in range(back):
            m = (m - timedelta(days=1)).replace(day=1)
        month = m.strftime("%Y-%m")
        x("INSERT INTO payroll_runs (month, days, created_at) VALUES (?,?,?)", (month, month_days(month), now()))
        run = get_run(month)
        _fill_missing(run)
        for l in q("SELECT * FROM payroll_lines WHERE run_id = ?", (run["id"],)):
            d = dict(l)
            if rnd.random() < .25:
                d["absent_days"] = d["absent_days"] + rnd.choice([1, 1, 2, 3])
            if rnd.random() < .3:
                d["ot_hours"] = rnd.choice([4, 6, 8, 10, 12, 16])
            if rnd.random() < .12:
                d["bonus"] = rnd.choice([2000, 3000, 5000]) * 100
            calc(d, run["days"])
            x("""UPDATE payroll_lines SET absent_days=?, absent_ded=?, ot_hours=?, ot_amount=?, bonus=?, gross=?, net=? WHERE id=?""",
              (d["absent_days"], d["absent_ded"], d["ot_hours"], d["ot_amount"], d["bonus"], d["gross"], d["net"], l["id"]))
        x("UPDATE payroll_runs SET status = 'final', finalized_at = ? WHERE id = ?", (now(), run["id"]))
        pay_day = (m.replace(day=28) + timedelta(days=8)).replace(day=5).isoformat()
        unpaid = 3 if back == 1 else 0
        lines = q("SELECT l.id, e.pay_method FROM payroll_lines l JOIN employees e ON e.id = l.employee_id WHERE run_id = ? ORDER BY l.id", (run["id"],))
        for l in lines[:len(lines) - unpaid]:
            x("UPDATE payroll_lines SET paid = net, paid_date = ?, paid_method = ? WHERE id = ?", (pay_day, l["pay_method"], l["id"]))


def reset_password(username, pw):
    if len(pw) < 8:
        sys.exit("Password must be at least 8 characters.")
    u = q("SELECT id FROM users WHERE username = ?", (username,), one=True)
    if not u:
        sys.exit("No such user.")
    x("UPDATE users SET password_hash = ?, active = 1 WHERE id = ?", (generate_password_hash(pw), u["id"]))
    commit()
    print("Password changed.")


def backup():
    folder = os.path.join(app.config["DATA_DIR"], "backups")
    os.makedirs(folder, exist_ok=True)
    dest = os.path.join(folder, f"erp_{datetime.now():%Y%m%d_%H%M}.sqlite3")
    con = get_db()
    import sqlite3
    out = sqlite3.connect(dest)
    con.backup(out)
    out.close()
    print("Backup saved:", dest)


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else ""
    with app.app_context():
        if cmd == "demo":
            demo()
        elif cmd == "reset-password" and len(sys.argv) == 4:
            reset_password(sys.argv[2], sys.argv[3])
        elif cmd == "backup":
            backup()
        else:
            print(__doc__)
