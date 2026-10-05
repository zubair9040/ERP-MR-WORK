"""Drag-and-drop print designer for invoices, delivery challans and receipts."""
import json
import os

from flask import Blueprint, abort, current_app, g, jsonify, render_template, request, send_file

from .auth import roles
from .db import commit, now, q, x
from .docdata import COLUMNS, DOCS, FIELDS, PRESET_NAMES, TOTAL_ROWS, preset, presets, sample_values

bp = Blueprint("pd", __name__, url_prefix="/print-designer")


def _co():
    v = request.values.get("co", type=int)
    if v:
        from .companies import get_company
        if not get_company(v):
            abort(404)
    return v or None


def _doc():
    d = request.values.get("doc", "invoice")
    if d not in DOCS:
        abort(404)
    return d


def _row(doc, co):
    return q("SELECT * FROM print_layouts WHERE doc = ? AND company_id IS ? ORDER BY id DESC LIMIT 1", (doc, co), one=True)


@bp.route("/")
@roles("admin")
def editor():
    from .companies import companies
    from .layout_pdf import add_font_dir, font_families
    add_font_dir(os.path.join(current_app.config["DATA_DIR"], "fonts"))
    doc, co = _doc(), _co()
    row = _row(doc, co)
    inherited = None
    if not row and co:
        inherited = _row(doc, None)
    layout = json.loads(row["layout"]) if row else (json.loads(inherited["layout"]) if inherited else preset("modern", doc))
    sample = sample_values(doc, co)
    imgs = {k: bool(v) for k, v in (sample.get("images") or {}).items()}
    cfg = {
        "doc": doc, "co": co or 0, "layout": layout, "presets": presets(doc), "fields": FIELDS[doc], "columns": COLUMNS[doc],
        "totalRows": TOTAL_ROWS[doc], "sample": {"fields": sample["fields"], "items": sample["items"][:30], "totals": sample["totals"]},
        "images": imgs, "fonts": font_families(), "accent": sample.get("accent") or "#4f46e5",
        "presetNames": PRESET_NAMES,
        "status": ("on" if row and row["active"] else ("off" if row else ("inherited" if inherited and inherited["active"] else "builtin"))),
        "saved": row["updated_at"] if row else None,
    }
    return render_template("designer.html", cfg=cfg, docs=DOCS, doc=doc, co=co, companies=companies())


@bp.route("/image/<src>")
@roles("admin")
def image(src):
    from .companies import co_images
    p = co_images(_co()).get(src)
    if not p or not os.path.exists(p):
        abort(404)
    return send_file(p)


def _layout_from_request():
    data = request.get_json(silent=True) or {}
    lay = data.get("layout")
    if not isinstance(lay, dict) or not isinstance(lay.get("elements"), list) or len(json.dumps(lay)) > 400_000:
        abort(400, "Layout is not valid.")
    return data, lay


@bp.route("/save", methods=["POST"])
@roles("admin")
def save():
    data, lay = _layout_from_request()
    doc, co = data.get("doc"), data.get("co") or None
    if doc not in DOCS:
        abort(400, "Unknown document.")
    active = 1 if data.get("active", True) else 0
    row = _row(doc, co)
    if row:
        x("UPDATE print_layouts SET layout = ?, active = ?, updated_at = ?, updated_by = ? WHERE id = ?",
          (json.dumps(lay), active, now(), g.user["name"], row["id"]))
    else:
        x("INSERT INTO print_layouts (company_id, doc, name, layout, active, updated_at, updated_by) VALUES (?,?,?,?,?,?,?)",
          (co, doc, DOCS[doc], json.dumps(lay), active, now(), g.user["name"]))
    commit()
    return jsonify(ok=True, saved=now(), active=active)


@bp.route("/off", methods=["POST"])
@roles("admin")
def off():
    data = request.get_json(silent=True) or {}
    x("UPDATE print_layouts SET active = 0 WHERE doc = ? AND company_id IS ?", (data.get("doc"), data.get("co") or None))
    commit()
    return jsonify(ok=True)


@bp.route("/preview", methods=["POST"])
@roles("admin")
def preview():
    from .layout_pdf import add_font_dir, render
    data, lay = _layout_from_request()
    doc = data.get("doc") if data.get("doc") in DOCS else "invoice"
    add_font_dir(os.path.join(current_app.config["DATA_DIR"], "fonts"))
    path = os.path.join(current_app.config["PDF_DIR"], f"preview_{doc}_{g.user['id']}.pdf")
    render(path, lay, sample_values(doc, data.get("co") or None))
    return send_file(path, mimetype="application/pdf")


PRESET_INFO = {
    "modern": "Clean cards, company colour on the band and table. The default.",
    "bold": "Full-width colour header with the logo on a white tile.",
    "elegant": "Centred letterhead, serif type, thin rules. Good for corporate clients.",
    "corporate": "Colour strip on the left, boxed bill-to / deliver-to, full table grid.",
    "compact": "Small type and tight rows, so long invoices fit on fewer pages.",
    "classic": "Close to your old QuickBooks invoice, with the bilti / via strip.",
    "minimal": "Black and white, no colour.",
}


def _current_preset(doc, co):
    row = _row(doc, co)
    if not row or not row["active"]:
        return None
    try:
        return json.loads(row["layout"]).get("preset") or "custom"
    except ValueError:
        return "custom"


@bp.route("/templates", methods=["GET", "POST"])
@roles("admin")
def templates():
    """Pick a ready-made print style for each company in one click (invoice, delivery challan and receipt together)."""
    from flask import flash, redirect, url_for
    from .companies import companies
    if request.method == "POST":
        name = request.form.get("preset")
        co = request.form.get("co", type=int) or None
        if name not in PRESET_NAMES:
            abort(400, "Unknown template.")
        for doc in DOCS:
            lay = preset(name, doc)
            lay["preset"] = name
            row = _row(doc, co)
            if row:
                x("UPDATE print_layouts SET layout = ?, active = 1, updated_at = ?, updated_by = ? WHERE id = ?",
                  (json.dumps(lay), now(), g.user["name"], row["id"]))
            else:
                x("INSERT INTO print_layouts (company_id, doc, name, layout, active, updated_at, updated_by) VALUES (?,?,?,?,1,?,?)",
                  (co, doc, DOCS[doc], json.dumps(lay), now(), g.user["name"]))
        commit()
        from .companies import get_company
        who = get_company(co)["name"] if co else "all companies"
        flash(f"'{PRESET_NAMES[name]}' is now used for {who}: invoice, delivery challan and receipt. "
              "Open the Print designer to adjust it.", "ok")
        return redirect(url_for("pd.templates"))
    cos = companies()
    current = {c["id"]: _current_preset("invoice", c["id"]) or _current_preset("invoice", None) for c in cos}
    return render_template("print_templates.html", names=PRESET_NAMES, info=PRESET_INFO, companies=cos, current=current,
                           all_current=_current_preset("invoice", None))


@bp.route("/templates/<name>.pdf")
@roles("admin")
def template_preview(name):
    from .layout_pdf import render
    if name not in PRESET_NAMES:
        abort(404)
    doc = request.args.get("doc", "invoice") if request.args.get("doc") in DOCS else "invoice"
    co = request.args.get("co", type=int) or None
    path = os.path.join(current_app.config["PDF_DIR"], f"tpl_{name}_{doc}_{co or 0}.pdf")
    render(path, preset(name, doc), sample_values(doc, co))
    return send_file(path, mimetype="application/pdf")
