import os
import re


def _login(app):
    c = app.test_client()
    t = re.search(r'name="_csrf" value="([^"]+)"', c.get("/login").text).group(1)
    r = c.post("/login", data={"username": "admin", "password": "admin12345", "_csrf": t})
    assert r.status_code == 302
    return c


def test_audit_log_records_saves_and_page_loads(app):
    c = _login(app)
    page = c.get("/audit")
    assert page.status_code == 200
    t = re.search(r'name="_csrf" value="([^"]+)"', c.get("/settings").text).group(1)
    r = c.post("/settings", data={"_csrf": t, "company_name": "Demo Stationers"})
    assert r.status_code < 400
    assert "core.settings" in c.get("/audit").text


def test_rep_cannot_open_audit_log(app):
    c = app.test_client()
    t = re.search(r'name="_csrf" value="([^"]+)"', c.get("/login").text).group(1)
    c.post("/login", data={"username": "rizwan", "password": "rizwan123", "_csrf": t})
    assert c.get("/audit").status_code == 403


def test_backup_file_is_created_and_readable(app, tmp_path):
    import sqlite3
    from erp.backup import make_backup
    dest = make_backup(app.config["DATABASE"], str(tmp_path))
    assert os.path.exists(dest)
    assert sqlite3.connect(dest).execute("SELECT COUNT(*) FROM customers").fetchone()[0] > 0
