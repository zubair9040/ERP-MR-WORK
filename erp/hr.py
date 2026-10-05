"""Salary / payroll: employees, advances & loans, monthly salary sheet, payment, payslips (PDF + WhatsApp)."""
import calendar
import os
from datetime import date, timedelta

from flask import (Blueprint, abort, current_app, flash, g, redirect, render_template, request, send_file, url_for)

from .db import commit, fmt, nice_date, now, parse_date, q, settings, to_paisa, today, x
from .export import table_response

bp = Blueprint("hr", __name__, url_prefix="/salary")
METHODS = ["Cash", "Bank transfer", "Cheque", "Online"]
MONTHS = ["January", "February", "March", "April", "May", "June", "July", "August", "September", "October",
          "November", "December"]


def allowed():
    """Salary pages need the 'View salaries' tick in the user's role (Users > Roles)."""
    from .perms import has
    return bool(g.get("user")) and has("salary.view")


@bp.before_request
def _guard():
    if not allowed():
        abort(403)


# ---- helpers --------------------------------------------------------------------------------
def month_label(m):
    y, mo = m.split("-")
    return f"{MONTHS[int(mo) - 1]} {y}"


def month_bounds(m):
    y, mo = (int(v) for v in m.split("-"))
    return date(y, mo, 1), date(y, mo, calendar.monthrange(y, mo)[1])


def month_days(m):
    if settings().get("salary_days_basis") == "30":
        return 30
    return month_bounds(m)[1].day


KINDS = {"Loan": "loan_ded", "Advance": "advance_ded"}


def advance_balance(eid, exclude_run=None, as_of=None, kind=None):
    """Loan/advance still owed. kind = 'Loan' (big, monthly instalments), 'Advance' (small) or None for both.
    as_of limits it to amounts given up to that date (e.g. the salary month's last day)."""
    kinds = [kind] if kind else list(KINDS)
    total = 0
    for k in kinds:
        given = q("""SELECT COALESCE(SUM(amount), 0) AS s FROM emp_advances WHERE employee_id = ? AND void = 0 AND date <= ?
                     AND kind = ?""", (eid, as_of or "9999-12-31", k), one=True)["s"]
        back = q(f"""SELECT COALESCE(SUM(l.{KINDS[k]}), 0) AS s FROM payroll_lines l JOIN payroll_runs r ON r.id = l.run_id
                     WHERE l.employee_id = ? AND r.status = 'final' AND r.id != ?""", (eid, exclude_run or -1), one=True)["s"]
        total += given - back
    return total


def default_recovery(eid, balance, kind="Advance"):
    """Loan: the monthly instalment. Advance: the part set per advance (blank = all of it)."""
    if balance <= 0:
        return 0
    per_month = q("""SELECT COALESCE(SUM(CASE WHEN installment > 0 THEN installment ELSE amount END), 0) AS s
                     FROM emp_advances WHERE employee_id = ? AND void = 0 AND kind = ?""", (eid, kind), one=True)["s"]
    return min(balance, per_month or balance)


def calc(l, days):
    """Works out one salary line. l is a dict with basic, allowance, absent_days, ot_hours, bonus, other_ded, advance_ded."""
    s = settings()
    monthly = l["basic"] + l["allowance"]
    per_day = monthly / days if days else 0
    hours = float(s.get("ot_hours_per_day") or 8) or 8
    mult = float(s.get("ot_rate_multiplier") or 1) or 1
    ab = min(max(l["absent_days"] or 0, 0), days or 0)
    # Company rule (month = 30 days): basic is paid for the days present, from the first absent day
    # (basic / 30 x present). The allowance is paid in full up to the allowed absents (Settings: 10); from the next
    # absent day it is also paid for the days present only (allowance / 30 x present).
    limit = float(s.get("allowance_absent_limit") or 0)
    basic_cut = (l["basic"] / days * ab) if days else 0
    allow_cut = (l["allowance"] / days * ab) if days and (not limit or ab > limit) else 0
    l["absent_ded"] = min(monthly, int(round(basic_cut + allow_cut)))
    l["ot_amount"] = int(round(per_day / hours * mult * (l["ot_hours"] or 0)))
    l["gross"] = monthly - l["absent_ded"] + l["ot_amount"] + l["bonus"]
    l["net"] = l["gross"] - l.get("loan_ded", 0) - l["advance_ded"] - l["other_ded"]
    return l


def _num(v, default=0.0):
    try:
        return float(str(v).replace(",", "").strip() or default)
    except ValueError:
        return default


def get_emp(eid):
    e = q("SELECT * FROM employees WHERE id = ?", (eid,), one=True)
    if not e:
        abort(404)
    return e


def get_run(month):
    return q("SELECT * FROM payroll_runs WHERE month = ?", (month,), one=True)


def run_lines(run_id):
    return q("""SELECT l.*, e.code, e.name, e.designation, e.department, e.pay_method, e.bank_name, e.bank_account,
                       e.whatsapp, e.phone, e.father_name, e.cnic, e.join_date
                FROM payroll_lines l JOIN employees e ON e.id = l.employee_id WHERE l.run_id = ?
                ORDER BY e.department, e.code, e.name COLLATE NOCASE""", (run_id,))


def _eligible(month):
    start, end = month_bounds(month)
    return q("""SELECT * FROM employees WHERE active = 1 AND (join_date IS NULL OR join_date = '' OR join_date <= ?)
                AND (leave_date IS NULL OR leave_date = '' OR leave_date >= ?)""", (end.isoformat(), start.isoformat()))


def _fill_missing(run):
    """Adds any eligible employee who isn't on a draft sheet yet (e.g. hired after the sheet was made)."""
    have = {r["employee_id"] for r in q("SELECT employee_id FROM payroll_lines WHERE run_id = ?", (run["id"],))}
    start, end = month_bounds(run["month"])
    added = 0
    for e in _eligible(run["month"]):
        if e["id"] in have:
            continue
        absent = 0
        if e["join_date"] and e["join_date"] > start.isoformat():
            absent += (date.fromisoformat(e["join_date"]) - start).days
        if e["leave_date"] and e["leave_date"] < end.isoformat():
            absent += (end - date.fromisoformat(e["leave_date"])).days
        rec = {k: default_recovery(e["id"], advance_balance(e["id"], run["id"], end.isoformat(), k), k) for k in KINDS}
        l = calc({"basic": e["basic"], "allowance": e["allowance"], "absent_days": min(absent, run["days"]), "ot_hours": 0,
                  "bonus": 0, "other_ded": 0, "advance_ded": rec["Advance"], "loan_ded": rec["Loan"]}, run["days"])
        x("""INSERT INTO payroll_lines (run_id, employee_id, basic, allowance, absent_days, absent_ded, ot_hours, ot_amount, bonus,
             other_ded, advance_ded, loan_ded, gross, net) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
          (run["id"], e["id"], l["basic"], l["allowance"], l["absent_days"], l["absent_ded"], 0, 0, 0, 0, l["advance_ded"],
           l["loan_ded"], l["gross"], l["net"]))
        added += 1
    return added


def run_totals(lines):
    keys = ("basic", "allowance", "absent_ded", "ot_amount", "bonus", "gross", "loan_ded", "advance_ded", "other_ded", "net", "paid")
    return {k: sum(l[k] for l in lines) for k in keys}


def salary_expense(start, end):
    """Salary cost for P&L: gross salary of finalised sheets whose month ends inside the period."""
    total = 0
    for r in q("""SELECT r.month, COALESCE(SUM(l.gross), 0) AS s FROM payroll_runs r JOIN payroll_lines l ON l.run_id = r.id
                  WHERE r.status = 'final' GROUP BY r.id"""):
        if start <= month_bounds(r["month"])[1].isoformat() <= end:
            total += r["s"]
    return total


def salary_paid(start, end):
    return q("SELECT COALESCE(SUM(paid), 0) AS s FROM payroll_lines WHERE paid > 0 AND paid_date BETWEEN ? AND ?",
             (start, end), one=True)["s"]


def advances_given(start, end):
    return q("SELECT COALESCE(SUM(amount), 0) AS s FROM emp_advances WHERE void = 0 AND date BETWEEN ? AND ?",
             (start, end), one=True)["s"]


def attention():
    """For the dashboard: last month's salary not finalised/paid."""
    if not allowed():
        return None
    t = date.today()
    last = (t.replace(day=1) - timedelta(days=1)).strftime("%Y-%m")
    if not q("SELECT 1 FROM employees WHERE active = 1 LIMIT 1"):
        return None
    run = get_run(last)
    if not run or run["status"] != "final":
        return {"month": last, "text": f"{month_label(last)} salary sheet not finalised"}
    unpaid = q("SELECT COUNT(*) AS n FROM payroll_lines WHERE run_id = ? AND net > 0 AND paid < net", (run["id"],), one=True)["n"]
    if unpaid:
        return {"month": last, "text": f"{unpaid} employees not yet paid for {month_label(last)}", "n": unpaid}
    return None


# ---- home -----------------------------------------------------------------------------------
@bp.route("/")
def home():
    runs = q("""SELECT r.*, COUNT(l.id) AS n, COALESCE(SUM(l.gross), 0) AS gross, COALESCE(SUM(l.net), 0) AS net,
                       COALESCE(SUM(l.paid), 0) AS paid, COALESCE(SUM(l.advance_ded + l.loan_ded), 0) AS adv
                FROM payroll_runs r LEFT JOIN payroll_lines l ON l.run_id = r.id GROUP BY r.id ORDER BY r.month DESC""")
    emps = q("SELECT * FROM employees WHERE active = 1")
    outstanding = sum(max(advance_balance(e["id"]), 0) for e in q("SELECT id FROM employees"))
    t = date.today()
    suggest = (t.replace(day=1) - timedelta(days=1)).strftime("%Y-%m") if t.day <= 10 else t.strftime("%Y-%m")
    return render_template("hr/home.html", runs=runs, emp_count=len(emps), monthly=sum(e["basic"] + e["allowance"] for e in emps),
                           outstanding=outstanding, suggest=suggest, month_label=month_label)


# ---- employees ------------------------------------------------------------------------------
@bp.route("/employees")
def employees():
    a = request.args
    where, args = " WHERE 1 = 1", {}
    if a.get("q"):
        where += " AND (name LIKE :s OR code LIKE :s OR designation LIKE :s OR phone LIKE :s OR cnic LIKE :s)"
        args["s"] = f"%{a['q'].strip()}%"
    if a.get("dept"):
        where += " AND department = :d"
        args["d"] = a["dept"]
    show = a.get("show", "active")
    if show == "active":
        where += " AND active = 1"
    elif show == "left":
        where += " AND active = 0"
    rows = []
    for e in q(f"SELECT * FROM employees {where} ORDER BY department, code, name COLLATE NOCASE", args):
        rows.append({"e": e, "adv": advance_balance(e["id"])})
    if a.get("export") in ("xlsx", "pdf"):
        data = [[r["e"]["code"], r["e"]["name"], r["e"]["designation"], r["e"]["department"], r["e"]["phone"] or r["e"]["whatsapp"],
                 nice_date(r["e"]["join_date"]), r["e"]["pay_method"], r["e"]["basic"], r["e"]["allowance"],
                 r["e"]["basic"] + r["e"]["allowance"], r["adv"]] for r in rows]
        return table_response(a["export"], "Employees", ["Code", "Name", "Designation", "Department", "Phone", "Joined", "Paid by",
                                                         "Basic", "Allowance", "Monthly salary", "Advance due"], data, {7, 8, 9, 10},
                              ["Total", f"{len(rows)} employees", "", "", "", "", "", sum(d[7] for d in data), sum(d[8] for d in data),
                               sum(d[9] for d in data), sum(d[10] for d in data)])
    depts = [r["department"] for r in q("SELECT DISTINCT department FROM employees WHERE department != '' ORDER BY 1")]
    return render_template("hr/employees.html", rows=rows, depts=depts,
                           monthly=sum(r["e"]["basic"] + r["e"]["allowance"] for r in rows if r["e"]["active"]),
                           adv=sum(r["adv"] for r in rows))


EMP_TEXT = ("code", "name", "father_name", "cnic", "phone", "whatsapp", "designation", "department", "pay_method",
            "bank_name", "bank_account", "notes")


@bp.route("/employees/new", methods=["GET", "POST"])
@bp.route("/employees/<int:eid>/edit", methods=["GET", "POST"])
def employee_form(eid=None):
    e = get_emp(eid) if eid else None
    if request.method == "POST":
        f = request.form
        try:
            vals = {k: f.get(k, "").strip() for k in EMP_TEXT}
            if not vals["name"]:
                raise ValueError("Please enter the employee's name.")
            vals["basic"] = to_paisa(f.get("basic"))
            vals["allowance"] = to_paisa(f.get("allowance"))
            if vals["basic"] < 0 or vals["allowance"] < 0:
                raise ValueError("Salary can't be negative.")
            vals["join_date"] = parse_date(f.get("join_date")) or None
            vals["leave_date"] = parse_date(f.get("leave_date")) or None
            vals["active"] = 0 if vals["leave_date"] and vals["leave_date"] <= today() else (1 if f.get("active") else 0)
            if vals["code"] and q("SELECT 1 FROM employees WHERE code = ? AND id != ?", (vals["code"], eid or -1)):
                raise ValueError(f"Employee code {vals['code']} is already used.")
        except ValueError as err:
            flash(str(err), "err")
            return render_template("hr/employee_form.html", e=e, f=f, methods=METHODS, depts=_depts())
        cols = list(vals)
        if e:
            x(f"UPDATE employees SET {', '.join(c + ' = ?' for c in cols)} WHERE id = ?", [vals[c] for c in cols] + [eid])
        else:
            if not vals["code"]:
                n = q("SELECT COUNT(*) AS n FROM employees", one=True)["n"] + 1
                while q("SELECT 1 FROM employees WHERE code = ?", (f"E{n:03d}",)):
                    n += 1
                vals["code"] = f"E{n:03d}"
            vals["created_at"] = now()
            cols = list(vals)
            eid = x(f"INSERT INTO employees ({', '.join(cols)}) VALUES ({', '.join('?' * len(cols))})", [vals[c] for c in cols])
        commit()
        flash(f"{vals['name']} saved.", "ok")
        if f.get("next") == "new":
            return redirect(url_for("hr.employee_form"))
        return redirect(url_for("hr.employee_view", eid=eid))
    return render_template("hr/employee_form.html", e=e, f=None, methods=METHODS, depts=_depts())


def _depts():
    return [r["department"] for r in q("SELECT DISTINCT department FROM employees WHERE department != '' ORDER BY 1")] or [
        "Office", "Warehouse", "Sales", "Delivery", "Accounts"]


@bp.route("/employees/<int:eid>")
def employee_view(eid):
    e = get_emp(eid)
    advs = q("SELECT * FROM emp_advances WHERE employee_id = ? ORDER BY date DESC, id DESC", (eid,))
    hist = q("""SELECT l.*, r.month, r.status FROM payroll_lines l JOIN payroll_runs r ON r.id = l.run_id
                WHERE l.employee_id = ? ORDER BY r.month DESC""", (eid,))
    return render_template("hr/employee_view.html", e=e, advs=advs, hist=hist, bal=advance_balance(eid), methods=METHODS,
                           loan_bal=advance_balance(eid, kind="Loan"), adv_bal=advance_balance(eid, kind="Advance"),
                           month_label=month_label)


# ---- advances & loans -----------------------------------------------------------------------
@bp.route("/advances", methods=["GET", "POST"])
def advances():
    if request.method == "POST":
        f = request.form
        try:
            eid = int(f.get("employee_id") or 0)
            get_emp(eid)
            amt = to_paisa(f.get("amount"))
            inst = to_paisa(f.get("installment"))
            if amt <= 0:
                raise ValueError("Enter the amount given.")
            if inst < 0 or inst > amt:
                raise ValueError("Monthly deduction must be between 0 and the amount given.")
        except ValueError as err:
            flash(str(err), "err")
            return redirect(request.referrer or url_for("hr.advances"))
        x("""INSERT INTO emp_advances (employee_id, date, kind, amount, installment, method, notes, created_by, created_at)
             VALUES (?,?,?,?,?,?,?,?,?)""", (eid, parse_date(f.get("date")) or today(), f.get("kind") if f.get("kind") in KINDS else "Advance", amt, inst,
                                           f.get("method") or "Cash", f.get("notes", "").strip(), g.user["id"], now()))
        commit()
        flash(f"{f.get('kind') or 'Advance'} of {fmt(amt)} saved. It will be deducted from salary.", "ok")
        return redirect(request.form.get("back") or url_for("hr.advances"))
    t = date.today()
    start = parse_date(request.args.get("from")) or t.replace(month=1, day=1).isoformat()
    end = parse_date(request.args.get("to")) or t.isoformat()
    rows = q("""SELECT a.*, e.name, e.code FROM emp_advances a JOIN employees e ON e.id = a.employee_id
                WHERE a.date BETWEEN ? AND ? ORDER BY a.date DESC, a.id DESC""", (start, end))
    owing = []
    for e in q("SELECT * FROM employees ORDER BY name COLLATE NOCASE"):
        loan, adv = advance_balance(e["id"], kind="Loan"), advance_balance(e["id"], kind="Advance")
        if loan or adv:
            owing.append({"e": e, "loan": loan, "adv": adv, "bal": loan + adv,
                          "next": default_recovery(e["id"], loan, "Loan") + default_recovery(e["id"], adv, "Advance")})
    if request.args.get("export") in ("xlsx", "pdf"):
        data = [[r["e"]["code"], r["e"]["name"], r["loan"], r["adv"], r["bal"], r["next"]] for r in owing]
        return table_response(request.args["export"], "Loans and advances outstanding",
                              ["Code", "Employee", "Loan", "Advance", "Total due", "Next deduction"],
                              data, {2, 3, 4, 5}, ["Total", ""] + [sum(d[i] for d in data) for i in range(2, 6)])
    return render_template("hr/advances.html", rows=rows, owing=owing, start=start, end=end, methods=METHODS,
                           emps=q("SELECT id, code, name FROM employees WHERE active = 1 ORDER BY name COLLATE NOCASE"))


@bp.route("/advances/<int:aid>/void", methods=["POST"])
def advance_void(aid):
    x("UPDATE emp_advances SET void = 1, notes = notes || ? WHERE id = ?", (f" [voided by {g.user['name']} {now()}]", aid))
    commit()
    flash("Advance voided.", "ok")
    return redirect(request.referrer or url_for("hr.advances"))


# ---- salary sheet ---------------------------------------------------------------------------
def _valid_month(m):
    try:
        y, mo = m.split("-")
        if len(y) == 4 and 1 <= int(mo) <= 12:
            return f"{int(y):04d}-{int(mo):02d}"
    except (ValueError, AttributeError):
        pass
    abort(404)


@bp.route("/sheet", methods=["POST"])
def sheet_create():
    m = _valid_month(request.form.get("month", ""))
    run = get_run(m)
    if not run:
        if not _eligible(m):
            flash("Add your employees first.", "err")
            return redirect(url_for("hr.employee_form"))
        rid = x("INSERT INTO payroll_runs (month, days, created_by, created_at) VALUES (?,?,?,?)",
                (m, month_days(m), g.user["id"], now()))
        _fill_missing(get_run(m))
        commit()
        flash(f"Salary sheet for {month_label(m)} created from your employee list. Enter absents, overtime and bonuses, then Save.", "ok")
    return redirect(url_for("hr.sheet", month=m))


@bp.route("/sheet/<month>", methods=["GET", "POST"])
def sheet(month):
    month = _valid_month(month)
    run = get_run(month)
    if not run:
        abort(404)
    if request.method == "POST":
        if run["status"] != "draft":
            flash("This sheet is final. Reopen it to make changes.", "err")
            return redirect(url_for("hr.sheet", month=month))
        f = request.form
        ids = f.getlist("line_id")
        errors = []
        for i, lid in enumerate(ids):
            old = q("SELECT * FROM payroll_lines WHERE id = ? AND run_id = ?", (lid, run["id"]), one=True)
            if not old:
                continue
            try:
                l = {"basic": old["basic"], "allowance": old["allowance"],
                     "absent_days": max(0.0, min(_num(f.getlist("absent_days")[i]), run["days"])),
                     "ot_hours": max(0.0, _num(f.getlist("ot_hours")[i])),
                     "bonus": to_paisa(f.getlist("bonus")[i]), "other_ded": to_paisa(f.getlist("other_ded")[i]),
                     "advance_ded": to_paisa(f.getlist("advance_ded")[i]), "loan_ded": to_paisa(f.getlist("loan_ded")[i])}
                if "allowance" in f:
                    l["allowance"] = to_paisa(f.getlist("allowance")[i])
            except (ValueError, IndexError) as err:
                errors.append(str(err))
                continue
            as_of = month_bounds(month)[1].isoformat()
            for kind, col in KINDS.items():
                bal = max(advance_balance(old["employee_id"], run["id"], as_of, kind), 0)
                if l[col] > bal:
                    l[col] = bal
            if min(l["bonus"], l["other_ded"], l["advance_ded"], l["loan_ded"], l["allowance"]) < 0:
                errors.append("Amounts can't be negative.")
                continue
            calc(l, run["days"])
            x("""UPDATE payroll_lines SET allowance=?, absent_days=?, absent_ded=?, ot_hours=?, ot_amount=?, bonus=?, other_ded=?,
                 advance_ded=?, loan_ded=?, gross=?, net=?, note=? WHERE id = ?""",
              (l["allowance"], l["absent_days"], l["absent_ded"], l["ot_hours"], l["ot_amount"], l["bonus"], l["other_ded"],
               l["advance_ded"], l["loan_ded"], l["gross"], l["net"], f.getlist("note")[i].strip()[:120], lid))
        x("UPDATE payroll_runs SET notes = ? WHERE id = ?", (f.get("notes", "").strip(), run["id"]))
        if f.get("action") == "final":
            neg = q("SELECT COUNT(*) AS n FROM payroll_lines WHERE run_id = ? AND net < 0", (run["id"],), one=True)["n"]
            if neg:
                errors.append(f"{neg} employee(s) have a negative net salary. Reduce their deductions first.")
            else:
                x("UPDATE payroll_runs SET status = 'final', finalized_at = ? WHERE id = ?", (now(), run["id"]))
        commit()
        for e in errors:
            flash(e, "err")
        if not errors:
            flash("Salary sheet finalised. You can now pay salaries and send payslips." if f.get("action") == "final"
                  else "Salary sheet saved.", "ok")
        return redirect(url_for("hr.sheet", month=month))
    if run["status"] == "draft" and _fill_missing(run):
        commit()
    lines = run_lines(run["id"])
    rows = []
    for l in lines:
        as_of = month_bounds(month)[1].isoformat()
        draft = run["status"] == "draft"
        rows.append({"l": l, "loan_bal": advance_balance(l["employee_id"], run["id"], as_of, "Loan") if draft else None,
                     "adv_bal": advance_balance(l["employee_id"], run["id"], as_of, "Advance") if draft else None})
    if request.args.get("export") in ("xlsx", "pdf"):
        return _sheet_export(run, lines, request.args["export"])
    s = settings()
    return render_template("hr/sheet.html", run=run, rows=rows, t=run_totals(lines), label=month_label(month), methods=METHODS,
                           hours=float(s.get("ot_hours_per_day") or 8), mult=float(s.get("ot_rate_multiplier") or 1),
                           prev=_shift(month, -1), next_=_shift(month, 1))


def _shift(m, n):
    y, mo = (int(v) for v in m.split("-"))
    mo += n
    y, mo = (y - 1, 12) if mo < 1 else ((y + 1, 1) if mo > 12 else (y, mo))
    return f"{y:04d}-{mo:02d}"


def _sheet_export(run, lines, kind):
    if request.args.get("bank"):
        rows = [[l["code"], l["name"], l["bank_name"], l["bank_account"], l["net"]] for l in lines
                if l["pay_method"] != "Cash" and l["net"] > 0]
        return table_response(kind, f"Bank transfer list {month_label(run['month'])}", ["Code", "Employee", "Bank", "Account no.",
                                                                                        "Net salary"],
                              rows, {4}, ["Total", f"{len(rows)} employees", "", "", sum(r[4] for r in rows)])
    headers = ["Code", "Employee", "Designation", "Basic", "Allowance", "Absent", "Absent ded.", "OT hrs", "Overtime", "Bonus",
               "Gross", "Loan inst.", "Advance", "Other ded.", "Net pay", "Paid"]
    rows = [[l["code"], l["name"], l["designation"], l["basic"], l["allowance"], f"{l['absent_days']:g}", l["absent_ded"],
             f"{l['ot_hours']:g}", l["ot_amount"], l["bonus"], l["gross"], l["loan_ded"], l["advance_ded"], l["other_ded"], l["net"],
             l["paid"]] for l in lines]
    t = run_totals(lines)
    totals = ["Total", f"{len(lines)} employees", "", t["basic"], t["allowance"], "", t["absent_ded"], "", t["ot_amount"], t["bonus"],
              t["gross"], t["loan_ded"], t["advance_ded"], t["other_ded"], t["net"], t["paid"]]
    return table_response(kind, f"Salary sheet {month_label(run['month'])}", headers, rows, {3, 4, 6, 8, 9, 10, 11, 12, 13, 14, 15},
                          totals, f"{run['days']} days · {'FINAL' if run['status'] == 'final' else 'DRAFT'}")


@bp.route("/sheet/<month>/reopen", methods=["POST"])
def sheet_reopen(month):
    run = get_run(_valid_month(month)) or abort(404)
    from .perms import has
    if not has("admin.users"):
        abort(403)
    if q("SELECT 1 FROM payroll_lines WHERE run_id = ? AND paid > 0", (run["id"],)):
        flash("Some salaries are already marked paid. Undo those payments first.", "err")
    else:
        x("UPDATE payroll_runs SET status = 'draft', finalized_at = NULL WHERE id = ?", (run["id"],))
        commit()
        flash("Sheet reopened for changes.", "ok")
    return redirect(url_for("hr.sheet", month=month))


@bp.route("/sheet/<month>/delete", methods=["POST"])
def sheet_delete(month):
    run = get_run(_valid_month(month)) or abort(404)
    if run["status"] != "draft":
        abort(400, "Only a draft sheet can be deleted.")
    x("DELETE FROM payroll_runs WHERE id = ?", (run["id"],))
    commit()
    flash(f"Draft salary sheet for {month_label(month)} deleted.", "ok")
    return redirect(url_for("hr.home"))


@bp.route("/sheet/<month>/pay", methods=["POST"])
def sheet_pay(month):
    run = get_run(_valid_month(month)) or abort(404)
    if run["status"] != "final":
        abort(400, "Finalise the salary sheet before paying.")
    f = request.form
    d = parse_date(f.get("date")) or today()
    ids = [int(i) for i in f.getlist("pay") if i.isdigit()]
    if f.get("undo"):
        x("UPDATE payroll_lines SET paid = 0, paid_date = NULL, paid_method = '' WHERE id = ? AND run_id = ?", (int(f["undo"]), run["id"]))
        commit()
        flash("Payment undone.", "ok")
        return redirect(url_for("hr.sheet", month=month))
    n = 0
    for l in q("SELECT l.*, e.pay_method FROM payroll_lines l JOIN employees e ON e.id = l.employee_id WHERE l.run_id = ?", (run["id"],)):
        if l["id"] in ids and l["paid"] < l["net"]:
            x("UPDATE payroll_lines SET paid = net, paid_date = ?, paid_method = ? WHERE id = ?",
              (d, f.get("method") or l["pay_method"] or "Cash", l["id"]))
            n += 1
    commit()
    flash(f"{n} salaries marked as paid on {nice_date(d)}." if n else "Tick the employees you paid.", "ok" if n else "err")
    return redirect(url_for("hr.sheet", month=month))


# ---- payslips -------------------------------------------------------------------------------
def _slip_path(run, l):
    safe = "".join(ch for ch in l["name"] if ch.isalnum() or ch in " -_").strip().replace(" ", "_")
    return os.path.join(current_app.config["PDF_DIR"], f"Payslip_{run['month']}_{l['code'] or l['employee_id']}_{safe}.pdf")


def make_slip(run, l):
    from .pdfs import payslip
    from .companies import pdf_settings
    sc = settings().get("salary_company")
    bal = ({"Loan": advance_balance(l["employee_id"], kind="Loan"), "Advance": advance_balance(l["employee_id"], kind="Advance")}
           if run["status"] == "final" else None)
    return payslip(_slip_path(run, l), pdf_settings(int(sc) if sc and sc.isdigit() else None), run, l, month_label(run["month"]), bal)


@bp.route("/sheet/<month>/slip/<int:lid>.pdf")
def slip_pdf(month, lid):
    run = get_run(_valid_month(month)) or abort(404)
    l = next((r for r in run_lines(run["id"]) if r["id"] == lid), None) or abort(404)
    return send_file(make_slip(run, l), mimetype="application/pdf", download_name=os.path.basename(_slip_path(run, l)))


@bp.route("/sheet/<month>/slips.pdf")
def slips_pdf(month):
    from pypdf import PdfWriter
    run = get_run(_valid_month(month)) or abort(404)
    w = PdfWriter()
    for l in run_lines(run["id"]):
        w.append(make_slip(run, l))
    out = os.path.join(current_app.config["PDF_DIR"], f"Payslips_{month}.pdf")
    with open(out, "wb") as fh:
        w.write(fh)
    return send_file(out, mimetype="application/pdf", download_name=f"Payslips_{month}.pdf")


@bp.route("/sheet/<month>/send", methods=["POST"])
def slips_send(month):
    from .notify import WhatsAppError, _log, _send_document, normalize
    run = get_run(_valid_month(month)) or abort(404)
    if run["status"] != "final":
        abort(400, "Finalise the salary sheet before sending payslips.")
    only = request.form.get("line", type=int)
    s = settings()
    ok = bad = 0
    last_err = ""
    for l in run_lines(run["id"]):
        if only and l["id"] != only:
            continue
        to = normalize(l["whatsapp"] or l["phone"])
        if not to:
            bad += 1
            last_err = f"{l['name']} has no WhatsApp number."
            continue
        try:
            mid = _send_document(to, s.get("wa_payslip_template") or "salary_slip", make_slip(run, l),
                                 [l["name"], month_label(month), f"{s.get('currency', 'Rs')} {fmt(l['net'])}"])
            _log("payslip", None, l["employee_id"], to, "test" if mid is None else "sent",
                 f"{l['name']} · " + ("test mode - not sent" if mid is None else mid), month)
            ok += 1
        except WhatsAppError as err:
            _log("payslip", None, l["employee_id"], to, "failed", f"{l['name']} · {err}", month)
            bad += 1
            last_err = str(err)
    test = " (test mode: not actually sent)" if s.get("wa_dry_run") == "1" else ""
    if ok:
        flash(f"{ok} payslip(s) sent on WhatsApp{test}.", "ok")
    if bad:
        flash(f"{bad} not sent. {last_err}", "err")
    return redirect(url_for("hr.sheet", month=month))


# ---- reports --------------------------------------------------------------------------------
@bp.route("/report")
def report():
    """Salary register for a range of months: one row per employee with totals."""
    t = date.today()
    m1 = request.args.get("m1") or f"{t.year if t.month >= 7 else t.year - 1}-07"
    m2 = request.args.get("m2") or t.strftime("%Y-%m")
    m1, m2 = _valid_month(m1), _valid_month(m2)
    rows = q("""SELECT e.code, e.name, e.designation, COUNT(*) AS months, SUM(l.gross) AS gross, SUM(l.loan_ded) AS loan,
                       SUM(l.advance_ded) AS adv, SUM(l.other_ded) AS other, SUM(l.net) AS net, SUM(l.paid) AS paid
                FROM payroll_lines l JOIN payroll_runs r ON r.id = l.run_id JOIN employees e ON e.id = l.employee_id
                WHERE r.status = 'final' AND r.month BETWEEN ? AND ? GROUP BY e.id ORDER BY e.code, e.name""", (m1, m2))
    headers = ["Code", "Employee", "Designation", "Months", "Gross", "Loan inst.", "Advance ded.", "Other ded.", "Net", "Paid", "Unpaid"]
    data = [[r["code"], r["name"], r["designation"], r["months"], r["gross"], r["loan"], r["adv"], r["other"], r["net"], r["paid"],
             r["net"] - r["paid"]] for r in rows]
    totals = ["Total", f"{len(data)} employees", "", ""] + [sum(d[i] for d in data) for i in range(4, 11)]
    if request.args.get("export") in ("xlsx", "pdf"):
        return table_response(request.args["export"], "Salary register", headers, data, set(range(4, 11)), totals,
                              f"{month_label(m1)} to {month_label(m2)}")
    return render_template("hr/report.html", headers=headers, rows=data, totals=totals, m1=m1, m2=m2)
