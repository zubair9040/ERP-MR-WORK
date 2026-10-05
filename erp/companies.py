"""Several companies in one system: the company bar, company details, and per-company printing."""
import os

from flask import Blueprint, abort, flash, g, redirect, render_template, request, session, url_for

from .auth import current_company, roles
from .db import commit, q, settings, to_paisa, x

bp = Blueprint("co", __name__)


def companies(active_only=True):
    key = "companies_all" if not active_only else "companies_active"
    if key not in g:
        g.__setattr__(key, q(f"SELECT * FROM companies {'WHERE active = 1' if active_only else ''} ORDER BY sort, id"))
    return g.get(key)


def get_company(cid):
    return q("SELECT * FROM companies WHERE id = ?", (cid,), one=True) if cid else None


def default_company_id():
    cur = current_company()
    if cur:
        return cur
    rows = companies()
    return rows[0]["id"] if rows else None


def co_settings(cid):
    """Global settings with this company's name, address, NTN/GST, phone etc. laid over them (for PDFs)."""
    s = dict(settings())
    c = get_company(cid)
    if c:
        s.update(company_name=c["name"], company_address=c["address"] or "", company_phone=c["phone"] or "",
                 company_email=c["email"] or "", company_website=c["website"] or "", company_tax_no=c["ntn"] or "",
                 company_gst_no=c["gst_no"] or "", company_gst=str(c["gst_registered"]), company_code=c["code"],
                 company_id=str(c["id"]), company_color=c["color"] or "#4f46e5")
        if c["invoice_note"]:
            s["invoice_note"] = c["invoice_note"]
    return s


def pdf_settings(cid=None):
    """Settings for a PDF: the given company, else the one picked in the company bar, else the first company."""
    cid = cid or default_company_id()
    s = co_settings(cid)
    s["_logo"] = co_images(cid).get("logo")
    return s


def co_images(cid):
    from .core import image_path
    return {"logo": (image_path(f"logo_c{cid}") if cid else None) or image_path("logo"), "terms": image_path("terms")}


def next_invoice_number(cid):
    c = get_company(cid)
    start = (c["next_invoice_number"] if c else 1) or 1
    cur = q("SELECT MAX(number) AS m FROM invoices WHERE company_id = ?", (cid,), one=True)["m"] or 0
    return max(start, cur + 1)


def customer_company(customer_id):
    r = q("SELECT company_id FROM customers WHERE id = ?", (customer_id,), one=True)
    return r["company_id"] if r else None


@bp.route("/company/<int:cid>")
def switch(cid):
    if cid and not get_company(cid):
        abort(404)
    session["co"] = cid or None
    back = request.args.get("next") or request.referrer or url_for("core.dashboard")
    if not back.startswith("/") and "://" in back:
        from urllib.parse import urlparse
        u = urlparse(back)
        back = u.path + ("?" + u.query if u.query else "")
    if not back.startswith("/") or back.startswith("//"):
        back = url_for("core.dashboard")
    return redirect(back)


FIELDS = ("code", "name", "ntn", "gst_no", "address", "phone", "email", "website", "invoice_note", "color")


@bp.route("/settings/companies", methods=["GET", "POST"])
@roles("admin")
def manage():
    from .core import save_image
    edit = request.args.get("edit", type=int)
    if request.method == "POST":
        f = request.form
        cid = f.get("id", type=int)
        vals = {k: f.get(k, "").strip() for k in FIELDS}
        if not vals["name"] or not vals["code"]:
            flash("Company name and short code are required.", "err")
            return redirect(request.full_path)
        vals["code"] = vals["code"].upper()[:12]
        vals["gst_registered"] = 1 if f.get("gst_registered") else 0
        try:
            vals["default_tax_rate"] = float(f.get("default_tax_rate") or 0) if vals["gst_registered"] else 0
            vals["next_invoice_number"] = int(f.get("next_invoice_number") or 1)
            vals["sort"] = int(f.get("sort") or 0)
        except ValueError:
            flash("Tax %, next invoice number and order must be numbers.", "err")
            return redirect(request.full_path)
        vals["active"] = 1 if f.get("active") or not cid else 0
        if cid:
            if not vals["active"] and len(companies()) <= 1:
                flash("At least one company must stay active.", "err")
                return redirect(url_for("co.manage"))
            x(f"UPDATE companies SET {', '.join(k + ' = :' + k for k in vals)} WHERE id = :id", {**vals, "id": cid})
        else:
            cid = x(f"INSERT INTO companies ({', '.join(vals)}) VALUES ({', '.join(':' + k for k in vals)})", vals)
        commit()
        fs = request.files.get("logo")
        if fs and fs.filename:
            try:
                save_image(f"logo_c{cid}", fs)
            except ValueError as e:
                flash(str(e), "err")
        if f.get("remove_logo"):
            from .core import image_path
            p = image_path(f"logo_c{cid}")
            if p:
                os.remove(p)
        flash(f"{vals['name']} saved.", "ok")
        return redirect(url_for("co.manage"))
    rows = []
    from .core import image_path
    for c in companies(active_only=False):
        n_c = q("SELECT COUNT(*) AS n FROM customers WHERE company_id = ?", (c["id"],), one=True)["n"]
        n_i = q("SELECT COUNT(*) AS n FROM invoices WHERE company_id = ? AND void = 0", (c["id"],), one=True)["n"]
        rows.append({"c": c, "customers": n_c, "invoices": n_i, "logo": bool(image_path(f"logo_c{c['id']}")),
                     "next": next_invoice_number(c["id"])})
    s = settings()
    return render_template("companies.html", rows=rows, edit=edit, purchase_co=s.get("default_purchase_company"),
                           salary_co=s.get("salary_company"))


@bp.route("/settings/companies/defaults", methods=["POST"])
@roles("admin")
def defaults():
    from .db import set_setting
    for k in ("default_purchase_company", "salary_company"):
        v = request.form.get(k, type=int)
        if v and get_company(v):
            set_setting(k, str(v))
    commit()
    flash("Saved.", "ok")
    return redirect(url_for("co.manage"))


@bp.route("/settings/companies/<int:cid>/logo")
def logo(cid):
    from flask import send_file
    from .core import image_path
    p = image_path(f"logo_c{cid}")
    if not p:
        abort(404)
    return send_file(p)
