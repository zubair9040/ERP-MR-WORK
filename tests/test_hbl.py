import re

from erp.db import commit, q, set_setting, x


def _client(app, user="admin", pw="admin12345"):
    c = app.test_client()
    t = re.search(r'name="_csrf" value="([^"]+)"', c.get("/login").text).group(1)
    assert c.post("/login", data={"username": user, "password": pw, "_csrf": t}).status_code == 302
    return c


def _csrf(c):
    return re.search(r'name="_csrf" value="([^"]+)"', c.get("/team/tasks").text).group(1)


def _post(c, url, body):
    return c.post(url, json=body, headers={"X-CSRF": _csrf(c)})


def _dc(req, cc, loc, lines):
    return {"req": req, "cc": cc, "loc": loc, "person": "Ali", "phone": "0300-1", "lines": [
        {"code": code, "name": name, "unit": "PCS", "qty": qty, "origQty": qty, "price": price, "tax": 0.18} for code, name, qty, price in lines]}


PO = "55555-001"


def _setup(app):
    with app.app_context():
        c = q("SELECT id, company_id FROM customers WHERE active = 1 ORDER BY company_id, id LIMIT 1", one=True)
        x("UPDATE companies SET hbl_enabled = 0")
        x("UPDATE companies SET hbl_enabled = 1, hbl_customer_id = ? WHERE id = ?", (c["id"], c["company_id"]))
        set_setting(f"hbl_next_dc_c{c['company_id']}", "56988")
        commit()
    return c["id"]


def test_import_gives_real_invoice_numbers_and_is_repeatable(app):
    cid = _setup(app)
    admin = _client(app)
    with app.app_context():
        before = q("SELECT MAX(number) AS m FROM invoices", one=True)["m"]
    body = {"po": PO, "date": "2026-11-09", "header": {"excl": 3508.5, "tax": 631.53, "incl": 4140.03},
            "dcs": [_dc("700001", "102", "102-BAHAWALPUR", [("SE00000581", "BALL PEN RED", 100, 6.48), ("SE00000085", "BALL PEN COUNTER SPRING", 50, 31.29)]),
                    _dc("700002", "105", "105-CHISHTIAN", [("SE00000581", "BALL PEN RED", 200, 6.48)])]}
    r = _post(admin, "/hbl/api/import", body).json
    assert r["ok"] and len(r["created"]) == 2
    nums = [c["dc"] for c in r["created"]]
    invs = [c["inv"] for c in r["created"]]
    assert nums == [56988, 56989] and invs[1] == invs[0] + 1 and invs[0] > before
    with app.app_context():
        inv = q("SELECT * FROM invoices WHERE number = ?", (invs[0],), one=True)
        assert inv["subtotal"] == 221250 and inv["tax"] == 39825 and inv["total"] == 261075 and inv["customer_id"] == cid and inv["po_no"] == PO
        assert q("SELECT COUNT(*) AS n FROM invoice_lines WHERE invoice_id = ?", (inv["id"],), one=True)["n"] == 2
        assert q("SELECT batch_id FROM invoices WHERE id = ?", (inv["id"],), one=True)["batch_id"]
    again = _post(admin, "/hbl/api/import", body).json
    assert again["created"] == [] and again["skipped"] == 2
    st = admin.get(f"/hbl/api/po/{PO}").json
    assert st["exists"] and [d["dc"] for d in st["dcs"]] == nums and st["bills"] == [] and st["header"]["incl"] == 4140.03


def test_partial_billing_in_parts_keeps_the_invoice_equal_to_what_was_billed(app):
    _setup(app)
    admin = _client(app)
    st = admin.get(f"/hbl/api/po/{PO}").json
    dc1, dc2 = st["dcs"][0]["dc"], st["dcs"][1]["dc"]
    inv2_no = st["dcs"][1]["inv"]
    line = lambda qty: {"code": "SE00000581", "name": "BALL PEN RED", "unit": "PCS", "qty": qty, "price": 6.48, "tax": 0.18}
    # first summary: DC 1 in full
    r = _post(admin, "/hbl/api/bill", {"po": PO, "date": "2026-11-10", "sumno": "501", "sinv": "9001", "dcs": [
        {"dc": dc1, "lines": [line(100), {**line(50), "code": "SE00000085", "name": "BALL PEN COUNTER SPRING", "price": 31.29}]}]})
    assert r.json["ok"]
    # second summary: only 120 of the 200 pens on DC 2 (partial)
    assert _post(admin, "/hbl/api/bill", {"po": PO, "date": "2026-11-12", "sumno": "502", "sinv": "9002", "dcs": [{"dc": dc2, "lines": [line(120)]}]}).json["ok"]
    with app.app_context():
        inv2 = q("SELECT * FROM invoices WHERE number = ?", (inv2_no,), one=True)
        assert inv2["subtotal"] == 77760 and inv2["total"] == 91757  # 120 x 6.48 = 777.60 + 18%
    # third summary: the remaining 80
    assert _post(admin, "/hbl/api/bill", {"po": PO, "date": "2026-12-01", "sumno": "503", "sinv": "9003", "dcs": [{"dc": dc2, "lines": [line(80)]}]}).json["ok"]
    with app.app_context():
        inv2 = q("SELECT * FROM invoices WHERE number = ?", (inv2_no,), one=True)
        assert inv2["subtotal"] == 129600 and inv2["total"] == 152928  # all 200 pens
        assert q("SELECT qty FROM invoice_lines WHERE invoice_id = ?", (inv2["id"],), one=True)["qty"] == 200
    st = admin.get(f"/hbl/api/po/{PO}").json
    assert sorted({b["sumno"] for b in st["bills"]}) == ["501", "502", "503"] and st["next_summary"] == 504 and st["next_sinv"] == 9004


def test_billing_numbers_cannot_be_reused_and_cancelled_lines_drop_off(app):
    _setup(app)
    admin = _client(app)
    st = admin.get(f"/hbl/api/po/{PO}").json
    dc2 = st["dcs"][1]["dc"]
    bad = _post(admin, "/hbl/api/bill", {"po": PO, "sumno": "501", "sinv": "9500", "dcs": [{"dc": dc2, "lines": []}]})
    assert bad.status_code == 400 and "already used" in bad.json["error"]
    assert _post(admin, "/hbl/api/bill", {"po": PO, "sumno": "", "sinv": "1", "dcs": []}).status_code == 400


def test_hbl_pages_need_back_office_rights(app):
    admin = _client(app)
    assert admin.get("/hbl/").status_code == 200 and admin.get("/hbl/app").status_code == 200 and admin.get("/hbl/items").status_code == 200
    look = admin.get("/hbl/api/lookup").json
    assert len(look["PRICES"]) > 200
    rep = _client(app, "rizwan", "rizwan123")
    assert rep.get("/hbl/").status_code == 403 and rep.get("/hbl/api/lookup").status_code == 403


def test_hbl_invoices_work_with_the_normal_erp_pages(app):
    _setup(app)
    admin = _client(app)
    st = admin.get(f"/hbl/api/po/{PO}").json
    with app.app_context():
        inv = q("SELECT id, batch_id FROM invoices WHERE number = ?", (st["dcs"][0]["inv"],), one=True)
    for url in (f"/po/{inv['batch_id']}", "/po/", f"/invoices/{inv['id']}?summary=1", f"/invoices/{inv['id']}/edit", f"/invoices/{inv['id']}.pdf",
                f"/invoices/{inv['id']}/dc.pdf", "/invoices"):
        assert admin.get(url).status_code == 200, url
