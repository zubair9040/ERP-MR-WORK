"""Download any part of the books to Excel: pick the company, the dates and the lists you want; one workbook, one sheet per list."""
import io
import re
from datetime import datetime

from flask import Blueprint, Response, render_template, request
from openpyxl import Workbook
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter

from .auth import allowed_companies
from .db import q

bp = Blueprint("xl", __name__, url_prefix="/excel")

MONEY = '#,##0.00;[Red]-#,##0.00'
HEAD = PatternFill("solid", fgColor="1F4E79")

# key -> (sheet title, SQL with {co} for the company test and {dt} for the date test, money columns, rate columns)
# Rates keep every decimal they were typed with; amounts are shown to 2 places.
SETS = {
    "customers": ("Customers", """SELECT c.id AS ID, c.code AS Code, c.name AS Name, c.contact AS Contact, c.phone AS Phone, c.whatsapp AS WhatsApp,
        c.email AS Email, c.city AS City, c.address AS Address, c.terms_days AS "Terms (days)", c.credit_limit AS "Credit limit",
        c.opening_balance AS "Opening balance", c.opening_date AS "Opening date", r.name AS Rep, co.name AS Company, c.active AS Active
        FROM customers c LEFT JOIN reps r ON r.id = c.rep_id LEFT JOIN companies co ON co.id = c.company_id WHERE {co:c.company_id} ORDER BY c.name""",
        {"Credit limit", "Opening balance"}, set()),
    "items": ("Items", "SELECT id AS ID, code AS Code, name AS Name, description AS Description, unit AS Unit, price AS Price, active AS Active FROM items ORDER BY name",
              set(), {"Price"}),
    "invoices": ("Invoices", """SELECT i.number AS "Invoice no", i.date AS Date, i.due_date AS "Due date", c.name AS Customer, co.name AS Company,
        i.po_no AS "PO no", i.subtotal AS Subtotal, i.discount AS Discount, i.tax_rate AS "Tax %", i.tax AS Tax, i.total AS Total,
        CASE i.void WHEN 1 THEN 'VOID' ELSE '' END AS Void, i.delivered_on AS Delivered, i.notes AS Notes
        FROM invoices i JOIN customers c ON c.id = i.customer_id LEFT JOIN companies co ON co.id = c.company_id
        WHERE {co:c.company_id} AND {dt:i.date} ORDER BY i.date, i.number""", {"Subtotal", "Discount", "Tax", "Total"}, set()),
    "invoice_lines": ("Invoice lines", """SELECT i.number AS "Invoice no", i.date AS Date, c.name AS Customer, it.code AS Code,
        COALESCE(NULLIF(l.description, ''), it.name) AS Item, l.qty AS Qty, l.rate AS Rate, l.amount AS Amount,
        CASE i.void WHEN 1 THEN 'VOID' ELSE '' END AS Void
        FROM invoice_lines l JOIN invoices i ON i.id = l.invoice_id JOIN customers c ON c.id = i.customer_id LEFT JOIN items it ON it.id = l.item_id
        WHERE {co:c.company_id} AND {dt:i.date} ORDER BY i.date, i.number, l.sort, l.id""", {"Amount"}, {"Rate"}),
    "payments": ("Payments received", """SELECT p.number AS "Receipt no", p.date AS Date, c.name AS Customer, co.name AS Company, p.amount AS Amount,
        p.method AS Method, p.reference AS Reference, p.notes AS Notes, CASE p.void WHEN 1 THEN 'VOID' ELSE '' END AS Void
        FROM payments p JOIN customers c ON c.id = p.customer_id LEFT JOIN companies co ON co.id = c.company_id
        WHERE {co:c.company_id} AND {dt:p.date} ORDER BY p.date, p.number""", {"Amount"}, set()),
    "allocations": ("Payment against invoices", """SELECT p.number AS "Receipt no", p.date AS Date, c.name AS Customer, i.number AS "Invoice no", a.amount AS Amount
        FROM payment_allocations a JOIN payments p ON p.id = a.payment_id JOIN customers c ON c.id = p.customer_id LEFT JOIN invoices i ON i.id = a.invoice_id
        WHERE p.void = 0 AND {co:c.company_id} AND {dt:p.date} ORDER BY p.date, p.number""", {"Amount"}, set()),
    "credits": ("Sales returns", """SELECT n.number AS "Credit note", n.date AS Date, c.name AS Customer, n.invoice_ref AS "Against invoice",
        n.subtotal AS Subtotal, n.tax AS Tax, n.total AS Total, CASE n.void WHEN 1 THEN 'VOID' ELSE '' END AS Void
        FROM credit_notes n JOIN customers c ON c.id = n.customer_id WHERE {co:c.company_id} AND {dt:n.date} ORDER BY n.date, n.number""",
        {"Subtotal", "Tax", "Total"}, set()),
    "suppliers": ("Suppliers", """SELECT id AS ID, name AS Name, contact AS Contact, phone AS Phone, email AS Email, address AS Address,
        terms_days AS "Terms (days)", opening_balance AS "Opening balance", active AS Active FROM suppliers ORDER BY name""", {"Opening balance"}, set()),
    "purchases": ("Purchase bills", """SELECT p.number AS "No", p.bill_no AS "Supplier bill", p.date AS Date, s.name AS Supplier, co.name AS Company,
        p.subtotal AS Subtotal, p.tax AS Tax, p.total AS Total, CASE p.void WHEN 1 THEN 'VOID' ELSE '' END AS Void, p.notes AS Notes
        FROM purchases p JOIN suppliers s ON s.id = p.supplier_id LEFT JOIN companies co ON co.id = p.company_id
        WHERE {co:p.company_id} AND {dt:p.date} ORDER BY p.date, p.number""", {"Subtotal", "Tax", "Total"}, set()),
    "purchase_lines": ("Purchase lines", """SELECT p.number AS "No", p.date AS Date, s.name AS Supplier, l.code AS Code, l.description AS Item,
        l.qty AS Qty, l.rate AS Rate, l.amount AS Amount
        FROM purchase_lines l JOIN purchases p ON p.id = l.purchase_id JOIN suppliers s ON s.id = p.supplier_id
        WHERE p.void = 0 AND {co:p.company_id} AND {dt:p.date} ORDER BY p.date, p.number, l.sort, l.id""", {"Amount"}, {"Rate"}),
    "supplier_payments": ("Supplier payments", """SELECT p.number AS "No", p.date AS Date, s.name AS Supplier, p.amount AS Amount, p.method AS Method,
        p.reference AS Reference, CASE p.void WHEN 1 THEN 'VOID' ELSE '' END AS Void
        FROM supplier_payments p JOIN suppliers s ON s.id = p.supplier_id WHERE {co:p.company_id} AND {dt:p.date} ORDER BY p.date, p.number""", {"Amount"}, set()),
    "expenses": ("Expenses", """SELECT e.date AS Date, e.category AS Category, e.payee AS Payee, e.amount AS Amount, e.method AS Method,
        e.reference AS Reference, e.notes AS Notes, CASE e.void WHEN 1 THEN 'VOID' ELSE '' END AS Void
        FROM expenses e WHERE {co:e.company_id} AND {dt:e.date} ORDER BY e.date, e.id""", {"Amount"}, set()),
}
PICKS = [("customers", "Customers"), ("items", "Items & prices"), ("invoices", "Invoices"), ("invoice_lines", "Invoice lines (every item on every invoice)"),
         ("payments", "Payments received"), ("allocations", "Which invoices each payment paid"), ("credits", "Sales returns"),
         ("suppliers", "Suppliers"), ("purchases", "Purchase bills"), ("purchase_lines", "Purchase lines"),
         ("supplier_payments", "Supplier payments"), ("expenses", "Expenses")]


def _scope(cid):
    allowed = allowed_companies()
    if allowed:
        cid = cid if cid in allowed else min(allowed)
    return cid


def _sql(sql, cid, d1, d2):
    """Fills {co:col} (this company only) and {dt:col} (date range) and returns the SQL with its arguments, in order."""
    args = []

    def fill(m):
        col = m.group(2)
        if m.group(1) == "co":
            if not cid:
                return "1 = 1"
            args.append(cid)
            return f"{col} = ?"
        parts = []
        if d1:
            args.append(d1)
            parts.append(f"{col} >= ?")
        if d2:
            args.append(d2)
            parts.append(f"{col} <= ?")
        return "(" + " AND ".join(parts) + ")" if parts else "1 = 1"

    return re.sub(r"\{(co|dt):([a-z_.]+)\}", fill, sql), args


def _xl(v, col, money, rates):
    if isinstance(v, int) and col in money:
        return v / 100
    if col in rates and isinstance(v, (int, float)):
        return v / 100      # rates are stored in paisa; any decimals typed are kept
    return v


def build(keys, cid, d1="", d2=""):
    wb = Workbook()
    wb.remove(wb.active)
    cname = (q("SELECT name FROM companies WHERE id = ?", (cid,), one=True) or {"name": ""})["name"] if cid else "All companies"
    for key in keys:
        title, sql, money, rates = SETS[key]
        s, args = _sql(sql, cid, d1, d2)
        rows = q(s, args)
        ws = wb.create_sheet(title[:31])
        ws.append([f"{cname} - {title}" + (f"   ({d1 or 'start'} to {d2 or 'today'})" if d1 or d2 else "")])
        ws["A1"].font = Font(bold=True, size=13)
        ws.append([f"Downloaded {datetime.now():%d-%b-%Y %H:%M}"])
        ws.append([])
        cols = list(rows[0].keys()) if rows else [c[0] for c in _cols(s, args)]
        ws.append(cols)
        hr = ws.max_row
        for k in range(1, len(cols) + 1):
            c = ws.cell(row=hr, column=k)
            c.font = Font(bold=True, color="FFFFFF")
            c.fill = HEAD
            c.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
        for r in rows:
            ws.append([_xl(r[c], c, money, rates) for c in cols])
        for k, c in enumerate(cols, 1):
            L = get_column_letter(k)
            w = max([len(str(c))] + [len(str(r[c])) for r in rows[:300] if r[c] is not None]) if rows else len(str(c))
            ws.column_dimensions[L].width = min(max(w + 2, 9), 48)
            if c in money:
                for row in range(hr + 1, ws.max_row + 1):
                    ws.cell(row=row, column=k).number_format = MONEY
            elif c in rates:
                for row in range(hr + 1, ws.max_row + 1):
                    ws.cell(row=row, column=k).number_format = "#,##0.00##"
        ws.freeze_panes = ws.cell(row=hr + 1, column=1)
        if rows:
            ws.auto_filter.ref = f"A{hr}:{get_column_letter(len(cols))}{ws.max_row}"
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue(), cname


def _cols(sql, args):
    from .db import get_db
    cur = get_db().execute(sql, args)
    return cur.description or []


@bp.route("/", methods=["GET", "POST"])
def index():
    from .auth import current_company
    comps = q("SELECT id, name, code FROM companies WHERE active = 1 ORDER BY id")
    allowed = allowed_companies()
    if allowed:
        comps = [c for c in comps if c["id"] in allowed]
    if request.method == "POST":
        keys = [k for k, _ in PICKS if k in request.form.getlist("what")]
        if not keys:
            return render_template("xlall.html", picks=PICKS, comps=comps, cur=current_company(), err="Tick at least one list.", allowed=allowed, f=request.form)
        cid = request.form.get("company", type=int) or None
        cid = _scope(cid)
        data, cname = build(keys, cid, request.form.get("d1", ""), request.form.get("d2", ""))
        name = re.sub(r"[^A-Za-z0-9]+", "_", cname).strip("_") or "ERP"
        return Response(data, mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                        headers={"Content-Disposition": f'attachment; filename="{name}_{datetime.now():%Y%m%d_%H%M}.xlsx"'})
    return render_template("xlall.html", picks=PICKS, comps=comps, cur=current_company(), err="", allowed=allowed, f={})
