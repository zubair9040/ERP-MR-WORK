"""Money-logic checks run against the demo data: balances, payment allocation, invoice totals."""
from erp.db import q
from erp.ledger import apply_payments, balance, customers_with_balance


def test_every_customer_balance_matches_open_bills(ctx):
    """Customer balance must equal what is still open on bills + opening balance left - unapplied credit."""
    for c in customers_with_balance():
        r = apply_payments(c["id"])
        expected = sum(r["open"].values()) + r["opening_left"] - r["credit"]
        assert c["balance"] == expected, f"{c['name']}: balance {c['balance']} != open {expected}"


def test_payments_never_allocate_more_than_paid(ctx):
    for c in q("SELECT id FROM customers"):
        r = apply_payments(c["id"])
        for p in q("SELECT id, amount FROM payments WHERE customer_id = ? AND void = 0", (c["id"],)):
            assert sum(a for _, a in r["applied"].get(p["id"], [])) <= p["amount"]


def test_no_bill_goes_negative(ctx):
    for c in q("SELECT id FROM customers"):
        assert all(v >= 0 for v in apply_payments(c["id"])["open"].values())


def test_invoice_total_matches_lines(ctx):
    """subtotal = sum of real lines (sub-total lines excluded); total = subtotal - discount + tax."""
    bad = []
    for i in q("SELECT * FROM invoices WHERE void = 0"):
        sub = q("""SELECT COALESCE(SUM(l.amount), 0) AS s FROM invoice_lines l LEFT JOIN items it ON it.id = l.item_id
                   WHERE l.invoice_id = ? AND COALESCE(it.kind, '') != 'subtotal'""", (i["id"],), one=True)["s"]
        if sub != i["subtotal"] or i["subtotal"] - i["discount"] + i["tax"] != i["total"]:
            bad.append((i["number"], sub, i["subtotal"], i["discount"], i["tax"], i["total"]))
    assert not bad, bad[:5]


def test_balance_as_of_today_equals_total_balance(ctx):
    from datetime import date
    for c in customers_with_balance()[:5]:
        assert balance(c["id"], date.today().isoformat()) == c["balance"]
