"""A distributor login is locked to its own company: it sees its own HBL pack and bills, never ours."""
import re

from werkzeug.security import generate_password_hash

from erp.db import commit, q, set_setting, x

from test_hbl import _client, _csrf, _post, _dc


def _two_companies(app):
    with app.app_context():
        cos = [r["id"] for r in q("SELECT id FROM companies WHERE active = 1 ORDER BY sort, id")]
        ours, theirs = cos[0], cos[1]
        custs = {}
        for cid in (ours, theirs):
            custs[cid] = q("SELECT id FROM customers WHERE company_id = ? AND active = 1 ORDER BY id LIMIT 1", (cid,), one=True)["id"]
            x("UPDATE companies SET hbl_enabled = ?, hbl_customer_id = ? WHERE id = ?", (1 if cid == theirs or cid == ours else 0, custs[cid], cid))
        x("UPDATE companies SET name = 'Rana Traders', ntn = '9999999-9', gst_no = '11-22-3333-444-55', phone = '042-111', hbl_lines = 'MOB: 0300-1' WHERE id = ?", (theirs,))
        role = q("SELECT id FROM roles WHERE name = 'Distributor (HBL billing)'", one=True)["id"]
        if not q("SELECT 1 FROM users WHERE username = 'rana'"):
            x("INSERT INTO users (username, name, password_hash, role, role_id, created_at, company_ids) VALUES ('rana','Rana',?,?,?,'',?)",
              (generate_password_hash("rana-pass-1"), "accounts", role, str(theirs)))
        commit()
    return ours, theirs, custs


def test_hbl_is_switched_on_per_company_and_prints_its_own_name(app):
    ours, theirs, custs = _two_companies(app)
    with app.app_context():
        x("UPDATE companies SET hbl_enabled = 0 WHERE id = ?", (ours,))
        commit()
    dist = _client(app, "rana", "rana-pass-1")
    look = dist.get("/hbl/api/lookup").json
    assert look["company"]["name"] == "Rana Traders" and look["company"]["ntn"] == "9999999-9" and "MOB: 0300-1" in look["company"]["lines"]
    # our rates are not copied to a distributor: it starts at rate 0 and sets its own
    with app.app_context():
        assert q("SELECT COUNT(*) AS n FROM hbl_company_items WHERE company_id = ? AND price != 0", (theirs,), one=True)["n"] == 0
        assert q("SELECT COUNT(*) AS n FROM hbl_company_items WHERE company_id = ?", (theirs,), one=True)["n"] > 200


def test_a_company_without_hbl_gets_no_hbl_pack(app):
    ours, theirs, _ = _two_companies(app)
    with app.app_context():
        x("UPDATE companies SET hbl_enabled = 0 WHERE id = ?", (theirs,))
        commit()
    dist = _client(app, "rana", "rana-pass-1")
    assert dist.get("/hbl/api/lookup").status_code == 403 and dist.get("/hbl/app").status_code == 403
    assert b"drop the PO PDF" not in dist.get("/po/").data
    with app.app_context():
        x("UPDATE companies SET hbl_enabled = 1 WHERE id = ?", (theirs,))
        commit()
    assert b"HBL purchase order" in dist.get("/po/").data


def test_distributor_cannot_see_other_companies_or_staff_areas(app):
    ours, theirs, custs = _two_companies(app)
    dist = _client(app, "rana", "rana-pass-1")
    # the company bar only knows its own company, and switching elsewhere is refused
    page = dist.get("/po/").text
    assert "Rana Traders" in page
    dist.get(f"/company/{ours}")
    assert dist.get("/hbl/api/lookup").json["company"]["name"] == "Rana Traders"
    dist.get("/company/0")
    assert dist.get("/hbl/api/lookup").json["company"]["name"] == "Rana Traders"
    # our customer, our invoices and the team area are closed
    assert dist.get(f"/customers/{custs[ours]}").status_code in (403, 404)
    for url in ("/team/chat", "/team/tasks", "/audit", "/users", "/settings", "/orders/", "/team/time"):
        assert dist.get(url).status_code == 403, url
    assert b"Team chat" not in dist.get("/po/").data
    # their own batch shows; ours does not
    admin = _client(app)
    with app.app_context():
        for cid, po in ((ours, "OUR-PO-1"), (theirs, "THEIR-PO-1")):
            bid = x("INSERT INTO po_batches (company_id, customer_id, po_no, date) VALUES (?,?,?,'2026-11-01')", (cid, custs[cid], po))
        commit()
    html = dist.get("/po/").text
    assert "THEIR-PO-1" in html and "OUR-PO-1" not in html
    assert "OUR-PO-1" in admin.get("/po/").text


def test_distributor_runs_its_own_hbl_billing_with_its_own_numbers(app):
    ours, theirs, custs = _two_companies(app)
    with app.app_context():
        set_setting(f"hbl_next_dc_c{theirs}", "1")
        set_setting(f"hbl_dc_rule_c{theirs}", "series")
        commit()
    dist = _client(app, "rana", "rana-pass-1")
    body = {"po": "77777-001", "date": "2026-11-09", "header": {}, "dcs": [_dc("1", "102", "102-X", [("SE00000581", "BALL PEN RED", 10, 6.48)])]}
    r = _post(dist, "/hbl/api/import", body).json
    assert r["ok"] and r["created"][0]["dc"] == 1
    with app.app_context():
        inv = q("SELECT company_id, customer_id FROM invoices WHERE number = ?", (r["created"][0]["inv"],), one=True)
        assert inv["company_id"] == theirs and inv["customer_id"] == custs[theirs]
    # billing numbers are per company: ours can use the same summary no
    assert _post(dist, "/hbl/api/bill", {"po": "77777-001", "date": "2026-11-10", "sumno": "1", "sinv": "1", "dcs": [
        {"dc": 1, "lines": [{"code": "SE00000581", "name": "BALL PEN RED", "unit": "PCS", "qty": 10, "price": 6.48, "tax": 0.18}]}]}).json["ok"]


def test_locked_user_cannot_be_made_admin(app):
    admin = _client(app)
    ours, theirs, _ = _two_companies(app)
    with app.app_context():
        admin_role = q("SELECT id FROM roles WHERE name = 'Admin'", one=True)["id"]
    r = admin.post("/users/new", data={"_csrf": _csrf(admin), "name": "X", "username": "x-locked", "role_id": admin_role, "password": "longenough1",
                                        "active": "on", "company_ids": str(theirs)}, follow_redirects=True)
    assert b"have an admin role" in r.data
    with app.app_context():
        assert not q("SELECT 1 FROM users WHERE username = 'x-locked'")
