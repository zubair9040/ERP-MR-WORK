import io
import re

from openpyxl import load_workbook

from erp.db import commit, q, x


def _client(app):
    c = app.test_client()
    t = re.search(r'name="_csrf" value="([^"]+)"', c.get("/login").text).group(1)
    c.post("/login", data={"username": "admin", "password": "admin12345", "_csrf": t})
    return c


def test_excel_download_lists_and_keeps_rate_decimals(app):
    c = _client(app)
    page = c.get("/excel/")
    assert page.status_code == 200 and "Download Excel" in page.text
    with app.app_context():
        ln = q("SELECT id FROM invoice_lines LIMIT 1", one=True)["id"]
        x("UPDATE invoice_lines SET rate = 24153.45 WHERE id = ?", (ln,))
        commit()
    t = re.search(r'name="_csrf" value="([^"]+)"', page.text).group(1)
    r = c.post("/excel/", data={"_csrf": t, "company": "", "what": ["customers", "invoices", "invoice_lines", "payments", "items", "expenses"]})
    assert r.status_code == 200 and "spreadsheetml" in r.mimetype
    wb = load_workbook(io.BytesIO(r.data))
    assert {"Customers", "Invoices", "Invoice lines", "Payments received", "Items", "Expenses"} <= set(wb.sheetnames)
    rates = [row[6] for row in wb["Invoice lines"].iter_rows(min_row=5, values_only=True)]
    assert 241.5345 in rates
    assert wb["Invoices"].max_row > 4


def test_excel_download_is_admin_only(app):
    c = app.test_client()
    t = re.search(r'name="_csrf" value="([^"]+)"', c.get("/login").text).group(1)
    c.post("/login", data={"username": "rizwan", "password": "rizwan123", "_csrf": t})
    assert c.get("/excel/").status_code in (302, 403)
