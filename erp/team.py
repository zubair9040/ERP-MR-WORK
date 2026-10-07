"""Team: active-time tracking, chat and task assignment."""
import time
from datetime import date, datetime, timedelta

from flask import Blueprint, abort, flash, g, jsonify, redirect, render_template, request, url_for

from .db import commit, now, q, x
from .perms import has

bp = Blueprint("team", __name__, url_prefix="/team")

PRIORITIES = ["Low", "Normal", "High", "Urgent"]
STATUSES = ["To do", "In progress", "Done"]
PING_EVERY = 30  # seconds between "still active" pings sent by the page


def _users():
    return q("SELECT id, name FROM users WHERE active = 1 ORDER BY name COLLATE NOCASE")


def _room_ok(room):
    if room == "general":
        return True
    parts = room.split(":")
    return len(parts) == 3 and parts[0] == "dm" and str(g.user["id"]) in parts[1:] and all(p.isdigit() for p in parts[1:])


def dm_room(a, b):
    lo, hi = sorted((int(a), int(b)))
    return f"dm:{lo}:{hi}"


def summary():
    uid = g.user["id"]
    unread = 0
    rooms = ["general"] + [r["room"] for r in q("SELECT DISTINCT room FROM chat_messages WHERE room LIKE 'dm:%'") if _room_ok(r["room"])]
    for r in rooms:
        last = q("SELECT last_id FROM chat_reads WHERE user_id = ? AND room = ?", (uid, r), one=True)
        unread += q("SELECT COUNT(*) AS n FROM chat_messages WHERE room = ? AND id > ? AND sender_id != ?",
                    (r, last["last_id"] if last else 0, uid), one=True)["n"]
    open_tasks = q("SELECT COUNT(*) AS n FROM tasks WHERE assignee_id = ? AND status != 'Done'", (uid,), one=True)["n"]
    return {"chat": unread, "tasks": open_tasks}


# ---- active time ---------------------------------------------------------------------------
@bp.route("/ping", methods=["POST"])
def ping():
    """The page calls this every 30 s while the person is really using it (mouse / keys / scroll, tab visible)."""
    t = time.time()
    day, stamp = date.today().isoformat(), now()
    row = q("SELECT * FROM activity WHERE user_id = ? AND day = ?", (g.user["id"], day), one=True)
    if not row:
        x("INSERT INTO activity (user_id, day, first_at, last_at, last_ts, active_sec) VALUES (?,?,?,?,?,0)", (g.user["id"], day, stamp, stamp, t))
    else:
        gap = t - (row["last_ts"] or 0)
        add = 0 if gap < 20 else min(int(gap), PING_EVERY + 5)  # ignore rapid spam; never count more than one ping interval
        x("UPDATE activity SET last_at = ?, last_ts = ?, active_sec = active_sec + ? WHERE id = ?", (stamp, t, add, row["id"]))
    commit()
    return jsonify(summary())


def _hm(sec):
    sec = int(sec or 0)
    return f"{sec // 3600}h {sec % 3600 // 60:02d}m"


@bp.route("/time")
def time_report():
    a = request.args
    end = a.get("to") or date.today().isoformat()
    start = a.get("from") or (date.today() - timedelta(days=6)).isoformat()
    rows = q("""SELECT a.*, u.name FROM activity a JOIN users u ON u.id = a.user_id
                WHERE a.day BETWEEN ? AND ? ORDER BY a.day DESC, u.name COLLATE NOCASE""", (start, end))
    out, totals = [], {}
    for r in rows:
        span = 0
        try:
            f = datetime.strptime(r["first_at"], "%Y-%m-%d %H:%M")
            l = datetime.strptime(r["last_at"], "%Y-%m-%d %H:%M")
            span = max(int((l - f).total_seconds()), 0)
        except (TypeError, ValueError):
            pass
        idle = max(span - r["active_sec"], 0)
        out.append({"day": r["day"], "name": r["name"], "first": (r["first_at"] or "")[11:], "last": (r["last_at"] or "")[11:],
                    "active": _hm(r["active_sec"]), "idle": _hm(idle)})
        t = totals.setdefault(r["name"], [0, 0, 0])
        t[0] += r["active_sec"]
        t[1] += idle
        t[2] += 1
    tot = sorted(((n, _hm(v[0]), _hm(v[1]), v[2]) for n, v in totals.items()), key=lambda z: z[0].lower())
    return render_template("team/time.html", rows=out, totals=tot, start=start, end=end)


# ---- chat ----------------------------------------------------------------------------------
@bp.route("/chat")
def chat():
    room = request.args.get("room", "general")
    if not _room_ok(room):
        abort(403)
    users = [u for u in _users() if u["id"] != g.user["id"]]
    unread = {}
    for r in ["general"] + [dm_room(g.user["id"], u["id"]) for u in users]:
        last = q("SELECT last_id FROM chat_reads WHERE user_id = ? AND room = ?", (g.user["id"], r), one=True)
        unread[r] = q("SELECT COUNT(*) AS n FROM chat_messages WHERE room = ? AND id > ? AND sender_id != ?",
                      (r, last["last_id"] if last else 0, g.user["id"]), one=True)["n"]
    title = "General" if room == "general" else next((u["name"] for u in users if dm_room(g.user["id"], u["id"]) == room), "Private")
    return render_template("team/chat.html", room=room, users=users, unread=unread, title=title, dm_room=dm_room, me=g.user["id"])


@bp.route("/chat/messages")
def chat_messages():
    room = request.args.get("room", "general")
    if not _room_ok(room):
        abort(403)
    after = request.args.get("after", 0, type=int)
    rows = q("SELECT id, sender_id, sender_name, body, created_at FROM chat_messages WHERE room = ? AND id > ? ORDER BY id LIMIT 200", (room, after))
    if rows:
        x("INSERT INTO chat_reads (user_id, room, last_id) VALUES (?,?,?) ON CONFLICT(user_id, room) DO UPDATE SET last_id = MAX(last_id, excluded.last_id)",
          (g.user["id"], room, rows[-1]["id"]))
        commit()
    return jsonify(messages=[dict(r) for r in rows], me=g.user["id"])


def post_message(room, sender_id, sender_name, body):
    mid = x("INSERT INTO chat_messages (room, sender_id, sender_name, body, created_at) VALUES (?,?,?,?,?)", (room, sender_id, sender_name, body, now()))
    return mid


@bp.route("/chat/send", methods=["POST"])
def chat_send():
    room = request.form.get("room", "general")
    body = request.form.get("body", "").strip()
    if not _room_ok(room):
        abort(403)
    if body:
        mid = post_message(room, g.user["id"], g.user["name"], body[:2000])
        x("INSERT INTO chat_reads (user_id, room, last_id) VALUES (?,?,?) ON CONFLICT(user_id, room) DO UPDATE SET last_id = MAX(last_id, excluded.last_id)",
          (g.user["id"], room, mid))
        commit()
    return jsonify(ok=True)


# ---- tasks ---------------------------------------------------------------------------------
def _can_see(task):
    return has("tasks.assign") or task["assignee_id"] == g.user["id"] or task["created_by"] == g.user["id"]


@bp.route("/tasks")
def tasks():
    scope = request.args.get("scope", "mine")
    where, args = " WHERE 1 = 1", []
    if scope == "all" and has("tasks.assign"):
        pass
    else:
        scope = "mine"
        where += " AND t.assignee_id = ?"
        args.append(g.user["id"])
    if request.args.get("status") in STATUSES:
        where += " AND t.status = ?"
        args.append(request.args["status"])
    elif request.args.get("status") != "all":
        where += " AND t.status != 'Done'"
    rows = q(f"""SELECT t.*, u.name AS assignee FROM tasks t JOIN users u ON u.id = t.assignee_id {where}
                 ORDER BY CASE t.priority WHEN 'Urgent' THEN 0 WHEN 'High' THEN 1 WHEN 'Normal' THEN 2 ELSE 3 END,
                 CASE WHEN t.due_date = '' THEN '9999' ELSE t.due_date END""", args)
    return render_template("team/tasks.html", rows=rows, scope=scope, status=request.args.get("status", ""), today=date.today().isoformat(),
                           can_assign=has("tasks.assign"))


@bp.route("/tasks/new", methods=["GET", "POST"])
def task_new():
    can_assign = has("tasks.assign")
    if request.method == "POST":
        f = request.form
        title = f.get("title", "").strip()
        assignee = f.get("assignee_id", type=int) if can_assign else g.user["id"]
        if not title:
            flash("Give the task a title.", "err")
        elif not q("SELECT 1 FROM users WHERE id = ? AND active = 1", (assignee or -1,)):
            flash("Choose who the task is for.", "err")
        else:
            prio = f.get("priority") if f.get("priority") in PRIORITIES else "Normal"
            tid = x("""INSERT INTO tasks (title, details, assignee_id, created_by, created_by_name, due_date, priority, status, created_at)
                       VALUES (?,?,?,?,?,?,?, 'To do', ?)""",
                    (title, f.get("details", "").strip(), assignee, g.user["id"], g.user["name"], f.get("due_date", "").strip(), prio, now()))
            if assignee != g.user["id"]:
                due = f" · due {f['due_date']}" if f.get("due_date") else ""
                post_message(dm_room(g.user["id"], assignee), g.user["id"], g.user["name"], f"📌 New task for you: {title} ({prio}{due}). Open Tasks to see it.")
            commit()
            flash("Task created.", "ok")
            return redirect(url_for("team.task_view", tid=tid))
    return render_template("team/task_form.html", users=_users(), priorities=PRIORITIES, can_assign=can_assign, me=g.user["id"])


def _task(tid):
    t = q("SELECT t.*, u.name AS assignee FROM tasks t JOIN users u ON u.id = t.assignee_id WHERE t.id = ?", (tid,), one=True) or abort(404)
    if not _can_see(t):
        abort(403)
    return t


@bp.route("/tasks/<int:tid>")
def task_view(tid):
    t = _task(tid)
    return render_template("team/task_view.html", t=t, comments=q("SELECT * FROM task_comments WHERE task_id = ? ORDER BY id", (tid,)),
                           statuses=STATUSES, today=date.today().isoformat())


@bp.route("/tasks/<int:tid>/status", methods=["POST"])
def task_status(tid):
    t = _task(tid)
    st = request.form.get("status")
    if st in STATUSES and (t["assignee_id"] == g.user["id"] or has("tasks.assign") or t["created_by"] == g.user["id"]):
        x("UPDATE tasks SET status = ?, done_at = ? WHERE id = ?", (st, now() if st == "Done" else None, tid))
        if st == "Done" and t["created_by"] != g.user["id"]:
            post_message(dm_room(g.user["id"], t["created_by"]), g.user["id"], g.user["name"], f"✅ Task done: {t['title']}")
        commit()
    return redirect(url_for("team.task_view", tid=tid))


@bp.route("/tasks/<int:tid>/comment", methods=["POST"])
def task_comment(tid):
    _task(tid)
    body = request.form.get("body", "").strip()
    if body:
        x("INSERT INTO task_comments (task_id, user_name, body, created_at) VALUES (?,?,?,?)", (tid, g.user["name"], body[:2000], now()))
        commit()
    return redirect(url_for("team.task_view", tid=tid))
