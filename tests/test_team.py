import re
import time

from erp.db import commit, q, x


def _client(app, user, pw):
    c = app.test_client()
    t = re.search(r'name="_csrf" value="([^"]+)"', c.get("/login").text).group(1)
    assert c.post("/login", data={"username": user, "password": pw, "_csrf": t}).status_code == 302
    return c


def _tok(c, url="/team/tasks"):
    return re.search(r'name="_csrf" value="([^"]+)"', c.get(url).text).group(1)


def _uid(app, name):
    with app.app_context():
        return q("SELECT id FROM users WHERE username = ?", (name,), one=True)["id"]


def test_active_time_adds_up_but_ignores_spam(app):
    admin = _client(app, "admin", "admin12345")
    h = {"X-CSRF": _tok(admin)}
    admin.post("/team/ping", headers=h)
    admin.post("/team/ping", headers=h)  # immediately again: must not count
    uid = _uid(app, "admin")
    with app.app_context():
        assert q("SELECT active_sec FROM activity WHERE user_id = ?", (uid,), one=True)["active_sec"] == 0
        x("UPDATE activity SET last_ts = ? WHERE user_id = ?", (time.time() - 30, uid))  # pretend the last ping was 30 s ago
        commit()
    r = admin.post("/team/ping", headers=h)
    assert r.status_code == 200 and "chat" in r.json
    with app.app_context():
        assert 25 <= q("SELECT active_sec FROM activity WHERE user_id = ?", (uid,), one=True)["active_sec"] <= 35


def test_time_report_is_admin_only(app):
    admin = _client(app, "admin", "admin12345")
    assert admin.get("/team/time").status_code == 200
    rep = _client(app, "rizwan", "rizwan123")
    assert rep.get("/team/time").status_code == 403


def test_task_assignment_posts_dm_and_assignee_sees_it(app):
    admin = _client(app, "admin", "admin12345")
    rid = _uid(app, "rizwan")
    r = admin.post("/team/tasks/new", data={"_csrf": _tok(admin, "/team/tasks/new"), "title": "Call Ahsan Stationers", "assignee_id": rid,
                                            "priority": "High", "due_date": "2030-01-01"})
    assert r.status_code == 302
    rep = _client(app, "rizwan", "rizwan123")
    assert "Call Ahsan Stationers" in rep.get("/team/tasks").text
    assert rep.get("/team/ping", headers={}).status_code in (200, 405)
    with app.app_context():
        tid = q("SELECT id FROM tasks ORDER BY id DESC", one=True)["id"]
        assert q("SELECT COUNT(*) AS n FROM chat_messages WHERE room LIKE 'dm:%' AND body LIKE '%Call Ahsan%'", one=True)["n"] == 1
    rep.post(f"/team/tasks/{tid}/status", data={"_csrf": _tok(rep, f"/team/tasks/{tid}"), "status": "Done"})
    with app.app_context():
        assert q("SELECT status FROM tasks WHERE id = ?", (tid,), one=True)["status"] == "Done"


def test_staff_cannot_assign_to_others_or_see_everyones_tasks(app):
    admin = _client(app, "admin", "admin12345")
    aid = _uid(app, "admin")
    rep = _client(app, "rizwan", "rizwan123")
    rep.post("/team/tasks/new", data={"_csrf": _tok(rep, "/team/tasks/new"), "title": "My own note", "assignee_id": aid})
    with app.app_context():
        t = q("SELECT * FROM tasks WHERE title = 'My own note'", one=True)
        assert t["assignee_id"] == _uid(app, "rizwan")  # forced to themselves
    admin.post("/team/tasks/new", data={"_csrf": _tok(admin, "/team/tasks/new"), "title": "Admin only job", "assignee_id": aid})
    with app.app_context():
        secret = q("SELECT id FROM tasks WHERE title = 'Admin only job'", one=True)["id"]
    assert rep.get(f"/team/tasks/{secret}").status_code == 403
    assert "Admin only job" not in rep.get("/team/tasks?scope=all").text


def test_chat_general_and_private_rooms(app):
    admin = _client(app, "admin", "admin12345")
    rep = _client(app, "rizwan", "rizwan123")
    a, r = _uid(app, "admin"), _uid(app, "rizwan")
    admin.post("/team/chat/send", data={"_csrf": _tok(admin), "room": "general", "body": "Hello team"})
    assert any(m["body"] == "Hello team" for m in rep.get("/team/chat/messages?room=general").json["messages"])
    room = f"dm:{min(a, r)}:{max(a, r)}"
    admin.post("/team/chat/send", data={"_csrf": _tok(admin), "room": room, "body": "private note"})
    assert any(m["body"] == "private note" for m in rep.get(f"/team/chat/messages?room={room}").json["messages"])
    with app.app_context():  # a third person's private room is closed to everyone else
        other = x("INSERT INTO users (username, name, password_hash, role, created_at) VALUES ('third','Third','x','rep','')")
        commit()
    assert rep.get(f"/team/chat/messages?room=dm:{a}:{other}").status_code == 403
    assert rep.get("/team/chat").status_code == 200
