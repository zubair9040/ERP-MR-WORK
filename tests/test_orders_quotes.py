import re

from erp.db import q


def _client(app, user, pw):
    c = app.test_client()
    t = re.search(r'name="_csrf" value="([^"]+)"', c.get("/login").text).group(1)
    assert c.post("/login", data={"username": user, "password": pw, "_csrf": t}).status_code == 302
    return c


def _tok(c, url):
    return re.search(r'name="_csrf" value="([^"]+)"', c.get(url).text).group(1)


def _first_customer_of_rep(app):
    with app.app_context():
        rep = q("SELECT rep_id FROM users WHERE username = 'rizwan'", one=True)["rep_id"]
        return q("SELECT id FROM customers WHERE rep_id = ? AND active = 1 LIMIT 1", (rep,), one=True)["id"]


def _codes(app, ids):
    with app.app_context():
        return [q("SELECT code FROM items WHERE id = ?", (i,), one=True)["code"] for i in ids]


def _two_items(app):
    with app.app_context():
        return [r["id"] for r in q("SELECT id FROM items WHERE kind = 'item' AND active = 1 LIMIT 2")]


def test_booker_order_needs_approval_then_becomes_invoice(app):
    cid = _first_customer_of_rep(app)
    a, b = _two_items(app)
    codes = _codes(app, (a, b))
    booker = _client(app, "rizwan", "rizwan123")
    r = booker.post("/orders/new", data={"_csrf": _tok(booker, "/orders/new"), "customer_id": cid,
                                         "code": codes, "qty": ["3", "2"], "price": ["", ""], "ctn_qty": ["", ""], "notes": "test"})
    assert r.status_code == 302
    with app.app_context():
        o = q("SELECT * FROM orders ORDER BY id DESC", one=True)
        assert o["status"] == "Pending" and o["invoice_id"] is None and o["total"] > 0
        n_inv = q("SELECT COUNT(*) AS n FROM invoices", one=True)["n"]
        oid = o["id"]
    # the booker may not approve their own order
    assert booker.post(f"/orders/{oid}/approve", data={"_csrf": _tok(booker, f"/orders/{oid}")}).status_code == 403
    admin = _client(app, "admin", "admin12345")
    assert admin.get("/orders/count").json["pending"] >= 1
    r = admin.post(f"/orders/{oid}/approve", data={"_csrf": _tok(admin, f"/orders/{oid}")})
    assert r.status_code == 302
    with app.app_context():
        o = q("SELECT * FROM orders WHERE id = ?", (oid,), one=True)
        assert o["status"] == "Approved" and o["invoice_id"]
        assert q("SELECT COUNT(*) AS n FROM invoices", one=True)["n"] == n_inv + 1
        inv = q("SELECT * FROM invoices WHERE id = ?", (o["invoice_id"],), one=True)
        assert inv["subtotal"] == o["total"] and inv["customer_id"] == cid
        assert q("SELECT COUNT(*) AS n FROM invoice_lines WHERE invoice_id = ?", (inv["id"],), one=True)["n"] == 2
    # approving twice does not make a second invoice
    admin.post(f"/orders/{oid}/approve", data={"_csrf": _tok(admin, "/orders/")})
    with app.app_context():
        assert q("SELECT COUNT(*) AS n FROM invoices", one=True)["n"] == n_inv + 1


def test_booker_cannot_order_for_another_reps_customer(app):
    with app.app_context():
        rep = q("SELECT rep_id FROM users WHERE username = 'rizwan'", one=True)["rep_id"]
        other = q("SELECT id FROM customers WHERE rep_id != ? AND active = 1 LIMIT 1", (rep,), one=True)["id"]
        n = q("SELECT COUNT(*) AS n FROM orders", one=True)["n"]
    a, _ = _two_items(app)
    booker = _client(app, "rizwan", "rizwan123")
    booker.post("/orders/new", data={"_csrf": _tok(booker, "/orders/new"), "customer_id": other, "code": _codes(app, (a,)), "qty": ["1"], "price": [""]})
    with app.app_context():
        assert q("SELECT COUNT(*) AS n FROM orders", one=True)["n"] == n


def test_reject_keeps_reason_and_makes_no_invoice(app):
    cid = _first_customer_of_rep(app)
    a, _ = _two_items(app)
    booker = _client(app, "rizwan", "rizwan123")
    booker.post("/orders/new", data={"_csrf": _tok(booker, "/orders/new"), "customer_id": cid, "code": _codes(app, (a,)), "qty": ["1"], "price": [""]})
    with app.app_context():
        oid = q("SELECT id FROM orders ORDER BY id DESC", one=True)["id"]
        n_inv = q("SELECT COUNT(*) AS n FROM invoices", one=True)["n"]
    admin = _client(app, "admin", "admin12345")
    admin.post(f"/orders/{oid}/reject", data={"_csrf": _tok(admin, f"/orders/{oid}"), "reason": "out of stock"})
    with app.app_context():
        o = q("SELECT * FROM orders WHERE id = ?", (oid,), one=True)
        assert o["status"] == "Rejected" and o["reject_reason"] == "out of stock"
        assert q("SELECT COUNT(*) AS n FROM invoices", one=True)["n"] == n_inv


def test_quotation_is_standalone_and_has_pdf(app):
    admin = _client(app, "admin", "admin12345")
    with app.app_context():
        n_inv = q("SELECT COUNT(*) AS n FROM invoices", one=True)["n"]
        bal = q("SELECT SUM(opening_balance) AS s FROM customers", one=True)["s"]
    r = admin.post("/quotations/new", data={"_csrf": _tok(admin, "/quotations/new"), "customer_name": "New Prospect Traders", "customer_id": "",
                                            "code": ["", ""], "description": ["Gem clips", "Stapler"], "unit": ["Box", "Doz"],
                                            "qty": ["10", "2"], "price": ["460", "1800"], "subject": "Test offer"})
    assert r.status_code == 302
    with app.app_context():
        qt = q("SELECT * FROM quotes ORDER BY id DESC", one=True)
        assert qt["total"] == (10 * 46000 + 2 * 180000) and qt["customer_name"] == "New Prospect Traders"
        assert q("SELECT COUNT(*) AS n FROM invoices", one=True)["n"] == n_inv
        assert q("SELECT SUM(opening_balance) AS s FROM customers", one=True)["s"] == bal
        qid = qt["id"]
    pdf = admin.get(f"/quotations/{qid}.pdf")
    assert pdf.status_code == 200 and pdf.data[:4] == b"%PDF"
    assert admin.get(f"/quotations/{qid}").status_code == 200
    assert admin.get(f"/quotations/{qid}/edit").status_code == 200
    assert admin.get("/quotations/").status_code == 200


def test_pages_load_for_booker(app):
    booker = _client(app, "rizwan", "rizwan123")
    for url in ("/orders/", "/orders/new", "/quotations/"):
        assert booker.get(url).status_code == 200, url


def test_quotation_converts_to_invoice_once(app):
    admin = _client(app, "admin", "admin12345")
    with app.app_context():
        cid = q("SELECT id FROM customers WHERE active = 1 LIMIT 1", one=True)["id"]
        n_inv = q("SELECT COUNT(*) AS n FROM invoices", one=True)["n"]
    admin.post("/quotations/new", data={"_csrf": _tok(admin, "/quotations/new"), "customer_id": cid, "customer_name": "x",
                                        "code": [""], "description": ["Gem clips"], "unit": ["Box"], "qty": ["4"], "price": ["460"]})
    with app.app_context():
        qt = q("SELECT * FROM quotes ORDER BY id DESC", one=True)
        qid = qt["id"]
    assert "Convert to invoice" in admin.get(f"/quotations/{qid}").text
    r = admin.post(f"/quotations/{qid}/to-invoice", data={"_csrf": _tok(admin, f"/quotations/{qid}")})
    assert r.status_code == 302
    admin.post(f"/quotations/{qid}/to-invoice", data={"_csrf": _tok(admin, f"/quotations/{qid}")})
    with app.app_context():
        qt = q("SELECT * FROM quotes WHERE id = ?", (qid,), one=True)
        assert qt["invoice_id"] and qt["status"] == "Accepted"
        assert q("SELECT COUNT(*) AS n FROM invoices", one=True)["n"] == n_inv + 1
        inv = q("SELECT * FROM invoices WHERE id = ?", (qt["invoice_id"],), one=True)
        assert inv["subtotal"] == 4 * 46000 and inv["customer_id"] == cid


def test_prospect_quotation_cannot_convert_until_customer_chosen(app):
    admin = _client(app, "admin", "admin12345")
    admin.post("/quotations/new", data={"_csrf": _tok(admin, "/quotations/new"), "customer_name": "Walk-in Prospect", "customer_id": "",
                                        "code": [""], "description": ["Pens"], "unit": [""], "qty": ["1"], "price": ["10"]})
    with app.app_context():
        qid = q("SELECT id FROM quotes ORDER BY id DESC", one=True)["id"]
        n_inv = q("SELECT COUNT(*) AS n FROM invoices", one=True)["n"]
    admin.post(f"/quotations/{qid}/to-invoice", data={"_csrf": _tok(admin, f"/quotations/{qid}")})
    with app.app_context():
        assert q("SELECT COUNT(*) AS n FROM invoices", one=True)["n"] == n_inv


def test_installable_app_files_are_public(app):
    c = app.test_client()
    m = c.get("/manifest.webmanifest")
    assert m.status_code == 200 and m.json["display"] == "standalone"
    assert c.get("/sw.js").status_code == 200
    ic = c.get("/pwa-icon-192.png")
    assert ic.status_code == 200 and ic.data[:4] == b"\x89PNG"


def test_quotation_send_by_whatsapp_and_email_in_test_mode(app):
    from erp.db import commit, set_setting
    with app.app_context():  # an earlier test saved the settings form, which can switch test mode off
        set_setting("wa_dry_run", "1")
        set_setting("email_dry_run", "1")
        commit()
    admin = _client(app, "admin", "admin12345")
    admin.post("/quotations/new", data={"_csrf": _tok(admin, "/quotations/new"), "customer_name": "Prospect Mart", "customer_id": "",
                                        "customer_phone": "0300-5551234", "customer_email": "buyer@example.com",
                                        "code": [""], "description": ["Files"], "unit": ["Doz"], "qty": ["3"], "price": ["100"]})
    with app.app_context():
        qid = q("SELECT id FROM quotes ORDER BY id DESC", one=True)["id"]
    page = admin.get(f"/quotations/{qid}").text
    assert "buyer@example.com" in page and "0300-5551234" in page
    for route, data in (("send-whatsapp", {}), ("send-email", {})):
        r = admin.post(f"/quotations/{qid}/{route}", data={"_csrf": _tok(admin, f"/quotations/{qid}"), **data}, follow_redirects=True)
        assert r.status_code == 200 and "test mode" in r.text, route
    with app.app_context():
        kinds = {(m["kind"], m["channel"], m["status"]) for m in q("SELECT * FROM messages WHERE ref_id = ? AND kind = 'quotation'", (qid,))}
        assert ("quotation", "whatsapp", "test") in kinds and ("quotation", "email", "test") in kinds
        assert q("SELECT status FROM quotes WHERE id = ?", (qid,), one=True)["status"] == "Sent"
    assert admin.get("/reports/messages").status_code == 200


def test_non_gst_invoice_pdf_hides_delivery_fields_but_dc_shows_them(app):
    import re as _re
    admin = _client(app, "admin", "admin12345")
    with app.app_context():
        c = q("SELECT c.id FROM customers c JOIN companies co ON co.id = c.company_id WHERE co.gst_registered = 0 AND c.active = 1 LIMIT 1", one=True)
        it = q("SELECT code FROM items WHERE kind = 'item' AND active = 1 LIMIT 1", one=True)["code"]
    admin.post("/invoices/new", data={"_csrf": _tok(admin, "/invoices/new"), "customer_id": c["id"], "date": "2026-10-01", "po_no": "PO-777",
                                      "courier": "TCS", "tracking_no": "TRK123", "deliver_to": "Branch Road 5", "code": [it], "qty": ["2"], "price": ["100"],
                                      "unit": [""], "ctn_qty": [""], "description": [""], "item_id": [""], "kind": ["item"], "tax_rate": "0"})
    with app.app_context():
        iid = q("SELECT id FROM invoices ORDER BY id DESC", one=True)["id"]
    assert admin.get(f"/invoices/{iid}.pdf").status_code == 200
    assert admin.get(f"/invoices/{iid}/dc.pdf").status_code == 200
    from erp.docdata import invoice_data
    from erp.companies import co_settings, co_images
    with app.app_context():
        inv = q("SELECT * FROM invoices WHERE id = ?", (iid,), one=True)
        cust = q("SELECT * FROM customers WHERE id = ?", (inv["customer_id"],), one=True)
        lines = q("SELECT * FROM invoice_lines WHERE invoice_id = ?", (iid,))
        s, imgs = co_settings(inv["company_id"]), co_images(inv["company_id"])
        inv_f = invoice_data(s, inv, lines, cust, None, 0, imgs)
        dc_f = invoice_data(s, inv, lines, cust, None, None, imgs, "dc")
    flat = lambda d: " ".join(str(v) for v in (d.values() if isinstance(d, dict) else []))
    assert "PO-777" not in flat(inv_f) and "TRK123" not in flat(inv_f)
    assert "PO-777" in flat(dc_f) and "TRK123" in flat(dc_f)


def test_logout_button_is_on_every_page_and_signs_out(app):
    admin = _client(app, "admin", "admin12345")
    page = admin.get("/orders/").text
    assert "Log out" in page and "/logout" in page
    r = admin.post("/logout", data={"_csrf": _tok(admin, "/orders/")})
    assert r.status_code == 302
    assert admin.get("/orders/").status_code == 302  # back to the sign-in page


def test_invoice_and_receipt_send_buttons_accept_pdf_or_picture(app):
    from erp.db import commit, set_setting
    with app.app_context():
        set_setting("wa_dry_run", "1")
        commit()
        iid = q("SELECT i.id FROM invoices i JOIN customers c ON c.id = i.customer_id WHERE i.void = 0 AND c.whatsapp != '' LIMIT 1", one=True)["id"]
        pid = q("SELECT p.id FROM payments p JOIN customers c ON c.id = p.customer_id WHERE p.void = 0 AND c.whatsapp != '' LIMIT 1", one=True)["id"]
    admin = _client(app, "admin", "admin12345")
    for how in ("pdf", "image"):
        r = admin.post(f"/invoices/{iid}/send", data={"_csrf": _tok(admin, f"/invoices/{iid}"), "phone": "0300-1234560", "fmt": how}, follow_redirects=True)
        assert r.status_code == 200 and "test mode" in r.text, how
        r = admin.post(f"/payments/{pid}/send", data={"_csrf": _tok(admin, f"/payments/{pid}"), "phone": "0300-1234560", "fmt": how}, follow_redirects=True)
        assert r.status_code == 200 and "test mode" in r.text, how
