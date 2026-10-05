"""Login, roles, CSRF protection and data scoping for sales reps."""
import hmac
import secrets
import time
from functools import wraps

from flask import abort, g, request, session
from markupsafe import Markup

from .db import q

ROLES = {
    "admin": "Admin (everything)",
    "accounts": "Accounts (all customers, void/edit, reports)",
    "rep": "Sales rep (own customers only)",
    "store": "Storekeeper (warehouse only)",
}


def load_user():
    g.user = None
    uid = session.get("uid")
    if uid:
        u = q("SELECT * FROM users WHERE id = ? AND active = 1", (uid,), one=True)
        if u and session.get("pw") == u["password_hash"][-12:]:
            g.user = u
        else:
            session.clear()


def roles(*allowed):
    """Kept for older code: page access is now checked centrally from the user's role permissions (perms.RULES)."""
    def deco(f):
        return f
    return deco


LEGACY_CAN = {"settings": "admin.settings", "users": "admin.users", "import": "admin.import", "warehouse": "warehouse.view",
              "invoice": "invoices.create", "payment": "payments.create", "statement": "statements.send", "send": "invoices.send"}


def can(action):
    """can('invoices.void') checks one permission; old names like can('settings') still work."""
    from .perms import has
    if not g.get("user"):
        return False
    return has(LEGACY_CAN.get(action, action))


def is_store():
    """Warehouse-only users get the slim warehouse menu."""
    from .perms import user_perms
    p = user_perms()
    return bool(g.get("user")) and "warehouse.view" in p and not (p & {"customers.view", "invoices.view", "payments.view",
                                                                        "purchases.view", "reports.sales", "reports.finance"})


def sees_cost():
    """Costs, stock values and profit need the 'See costs' tick."""
    from .perms import has
    return bool(g.get("user")) and has("reports.costs")


def is_rep():
    """Users limited to their own customers (sales rep logins)."""
    from .perms import has
    return bool(g.get("user")) and has("scope.own_customers")


def current_company():
    """The company picked in the company bar (id), or None for 'All companies'."""
    if "co_id" not in g:
        cid = session.get("co")
        ok = cid and q("SELECT 1 FROM companies WHERE id = ? AND active = 1", (cid,))
        g.co_id = cid if ok else None
    return g.co_id


def rep_filter(alias="c"):
    """SQL fragment (named params) limiting customers to the logged-in rep's own and to the company in the company bar."""
    where, args = " ", {}
    if is_rep():
        where += f" AND {alias}.rep_id = :my_rep "
        args["my_rep"] = g.user["rep_id"] or -1
    co = current_company()
    if co:
        where += f" AND {alias}.company_id = :my_co "
        args["my_co"] = co
    return where, args


def co_filter(col):
    """SQL fragment for tables that carry their own company column (purchases, expenses, supplier payments)."""
    co = current_company()
    return (f" AND {col} = :my_co ", {"my_co": co}) if co else (" ", {})


def check_customer_access(customer):
    if customer is None:
        abort(404)
    if is_rep() and customer["rep_id"] != g.user["rep_id"]:
        abort(403)
    return customer


def csrf_token():
    if "csrf" not in session:
        session["csrf"] = secrets.token_urlsafe(24)
    return session["csrf"]


def csrf_field():
    return Markup(f'<input type="hidden" name="_csrf" value="{csrf_token()}">')


def check_csrf():
    if request.method == "POST":
        sent = request.form.get("_csrf") or request.headers.get("X-CSRF")
        if not sent or not hmac.compare_digest(str(sent), str(session.get("csrf", ""))):
            abort(400, "Your session expired. Please go back, refresh the page and try again.")


# ---- login brute-force protection: 5 wrong passwords lock that username + address for 10 minutes ----
_FAILS = {}
MAX_FAILS, LOCK_SECONDS = 5, 600


def _fail_key(username):
    return (request.remote_addr or "", username.lower())


def login_locked(username):
    rec = _FAILS.get(_fail_key(username))
    return bool(rec and rec[0] >= MAX_FAILS and time.time() - rec[1] < LOCK_SECONDS)


def login_failed(username):
    k = _fail_key(username)
    n, t = _FAILS.get(k, (0, 0))
    _FAILS[k] = (1 if time.time() - t > LOCK_SECONDS else n + 1, time.time())


def login_ok(username):
    _FAILS.pop(_fail_key(username), None)
