import os
import secrets

from flask import Flask, abort, g, redirect, render_template, request, session, url_for

from . import db
from .hr import allowed as hr_allowed
from .auth import can, check_csrf, csrf_field, csrf_token, is_rep, is_store, load_user, sees_cost
from .perms import role_name


def create_app(test_config=None):
    app = Flask(__name__, instance_relative_config=True)
    data_dir = os.environ.get("ERP_DATA_DIR", os.path.join(app.root_path, "..", "data"))
    os.makedirs(data_dir, exist_ok=True)

    secret = os.environ.get("ERP_SECRET_KEY")
    if not secret:
        key_file = os.path.join(data_dir, ".secret_key")
        if not os.path.exists(key_file):
            with open(key_file, "w") as f:
                f.write(secrets.token_hex(32))
        secret = open(key_file).read().strip()

    app.config.update(
        SECRET_KEY=secret,
        DATABASE=os.path.join(data_dir, "erp.sqlite3"),
        DATA_DIR=data_dir,
        PDF_DIR=os.path.join(data_dir, "pdfs"),
        SESSION_COOKIE_HTTPONLY=True,
        SESSION_COOKIE_SAMESITE="Lax",
        SESSION_COOKIE_SECURE=os.environ.get("ERP_HTTPS", "0") == "1",
        PERMANENT_SESSION_LIFETIME=60 * 60 * 12,
        MAX_CONTENT_LENGTH=25 * 1024 * 1024,
    )
    if test_config:
        app.config.update(test_config)
    os.makedirs(app.config["PDF_DIR"], exist_ok=True)
    db.init_db(app.config["DATABASE"])
    app.teardown_appcontext(db.close_db)
    if not test_config and os.environ.get("ERP_NO_AUTO_BACKUP") != "1":
        from .backup import start_auto_backup
        start_auto_backup(app)

    open_endpoints = {"core.login", "core.setup", "static"}

    @app.before_request
    def before():
        load_user()
        check_csrf()
        if request.endpoint in open_endpoints or request.endpoint is None:
            return
        if not db.q("SELECT 1 FROM users LIMIT 1"):
            return redirect(url_for("core.setup"))
        if not g.user:
            return redirect(url_for("core.login", next=request.full_path))
        from .perms import allowed, home_endpoint, any_of
        if request.endpoint == "core.dashboard" and not any_of("customers.view", "invoices.view", "payments.view"):
            return redirect(url_for(home_endpoint()))
        if not allowed(request.endpoint, request.method):
            abort(403)

    SKIP_AUDIT = {"static", "core.login"}

    @app.after_request
    def audit(resp):
        """Who changed what: every save / delete / void (POST) is recorded with user, time and address."""
        try:
            if request.method == "POST" and request.endpoint not in SKIP_AUDIT and g.get("user") and resp.status_code < 400:
                ids = {k: v for k, v in (request.view_args or {}).items()}
                db.x("INSERT INTO audit_log (at, user_id, user_name, ip, method, endpoint, path, status, detail) VALUES (?,?,?,?,?,?,?,?,?)",
                     (db.now(), g.user["id"], g.user["name"], request.remote_addr or "", request.method,
                      request.endpoint or "", request.path, resp.status_code, str(ids) if ids else ""))
                db.commit()
        except Exception:  # noqa: BLE001 - never block a real save because logging failed
            pass
        return resp

    @app.after_request
    def security_headers(resp):
        resp.headers.setdefault("X-Content-Type-Options", "nosniff")
        resp.headers.setdefault("X-Frame-Options", "SAMEORIGIN")
        resp.headers.setdefault("Referrer-Policy", "same-origin")
        if request.endpoint != "static":
            resp.headers.setdefault("Cache-Control", "no-store")
        if app.config.get("SESSION_COOKIE_SECURE"):
            resp.headers.setdefault("Strict-Transport-Security", "max-age=31536000")
        return resp

    def _companies():
        from .companies import companies
        return companies()

    def _co_tag(cid):
        from markupsafe import Markup, escape
        for c in _companies_all():
            if c["id"] == cid:
                return Markup(f'<span class="co-tag" style="background:{escape(c["color"])}" title="{escape(c["name"])}">{escape(c["code"])}</span>')
        return ""

    def _co_logo(cid):
        from flask import url_for
        from .core import image_path
        return url_for("co.logo", cid=cid) if image_path(f"logo_c{cid}") else None

    def _companies_all():
        from .companies import companies
        return companies(active_only=False)

    def _cur_company():
        from .auth import current_company
        from .companies import get_company
        cid = current_company()
        return get_company(cid) if cid else None

    def _void_pending(kind, ref_id):
        from .approvals import pending_for
        return pending_for(kind, ref_id)

    def _pending_count():
        from .approvals import pending_count
        return pending_count()

    @app.context_processor
    def ctx():
        s = db.settings()
        return dict(csrf_field=csrf_field, csrf_token=csrf_token, can=can, is_rep=is_rep, is_store=is_store, sees_cost=sees_cost, role_name=role_name, void_pending=_void_pending, pending_count=_pending_count, S=s,
                    cur=s.get("currency", "Rs"), today=db.today(), hr_allowed=hr_allowed,
                    all_companies=_companies, cur_company=_cur_company, co_tag=_co_tag, co_logo=_co_logo)

    app.jinja_env.filters["money"] = db.fmt
    app.jinja_env.filters["plain"] = db.plain
    app.jinja_env.filters["d"] = db.nice_date
    from .icons import icon
    app.jinja_env.globals["icon"] = icon
    app.jinja_env.filters["initials"] = lambda s: "".join(w[0] for w in str(s or "?").replace(".", " ").split()[:2]).upper() or "?"

    from .core import bp as core_bp
    from .sales import bp as sales_bp
    from .reports import bp as reports_bp
    from .importer import bp as importer_bp
    from .ops import bp as ops_bp
    from .wh import bp as wh_bp
    from .hr import bp as hr_bp
    from .companies import bp as co_bp
    app.register_blueprint(co_bp)
    from .supdocs import bp as sup_bp
    app.register_blueprint(sup_bp)
    from .approvals import bp as ap_bp
    app.register_blueprint(ap_bp)
    from .batch import bp as po_bp
    app.register_blueprint(po_bp)
    from .designer import bp as pd_bp
    app.register_blueprint(pd_bp)
    app.register_blueprint(hr_bp)
    app.register_blueprint(ops_bp)
    app.register_blueprint(wh_bp)
    app.register_blueprint(importer_bp)
    app.register_blueprint(core_bp)
    app.register_blueprint(sales_bp)
    app.register_blueprint(reports_bp)

    @app.errorhandler(403)
    def forbidden(e):
        return render_template("message.html", title="Not allowed",
                               text="You don't have permission for this page."), 403

    @app.errorhandler(404)
    def not_found(e):
        return render_template("message.html", title="Not found", text="That page or record doesn't exist."), 404

    @app.errorhandler(400)
    def bad(e):
        return render_template("message.html", title="Please try again", text=e.description), 400

    return app
