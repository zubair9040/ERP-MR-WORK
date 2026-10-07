"""The screen (static/money.js) and the server (erp/lines.py) must give the same invoice amounts, to the paisa."""
import json
import os
import random
import subprocess

from erp.db import mul_rnd, pct_rnd, rnd
from erp.lines import compute, parse_price, parse_qty

NODE_RUNNER = """
const m = require(process.argv[1]);
const cases = JSON.parse(require('fs').readFileSync(0, 'utf8'));
console.log(JSON.stringify(cases.map(c => { const r = m.compute(c.rows, c.tax); return {amts: r.rows.map(x => x.amt), total: r.total, tax: r.tax, grand: r.grand}; })));
"""
MONEY_JS = os.path.join(os.path.dirname(os.path.dirname(__file__)), "erp", "static", "money.js")


def test_ties_round_away_from_zero_not_to_even():
    assert rnd(0.5) == 1 and rnd(1.5) == 2 and rnd(2.5) == 3 and rnd(-0.5) == -1 and rnd(-2.5) == -3
    assert pct_rnd(12345, -5) == -617          # -617.25
    assert pct_rnd(1233, 50) == 617            # 616.5 -> 617 (banker's rounding gave 616)
    assert mul_rnd(2.675, 100) == 268          # float error made round(267.49999) = 267


def _server(rows, tax):
    lines = []
    for r in rows:
        rate, pct = parse_price(r["price"])
        qty = parse_qty(r["qty"])
        lines.append({"kind": r["kind"], "qty": qty, "rate": rate, "percent": pct})
    sub = compute(lines)
    t = pct_rnd(sub, tax)
    return [l["amount"] for l in lines], sub, t, sub + t


def test_screen_and_server_agree_on_random_invoices():
    random.seed(11)
    cases = []
    for _ in range(300):
        rows = []
        for _ in range(random.randint(1, 6)):
            k = random.random()
            if k < 0.12:
                rows.append({"kind": "subtotal", "qty": "", "price": ""})
            elif k < 0.3:
                rows.append({"kind": "discount", "qty": "", "price": random.choice(["-5%", "-2.5%", "-7.5%", "10%", "-0.5%"])})
            else:
                rows.append({"kind": "item", "qty": random.choice(["1", "0.5", "1.5", "2.5", "3", "0.333", "12", "7.25", ""]),
                             "price": random.choice(["460", "12.34", "0.05", "99.995", "1250.5", "3.333", "0.01"])})
        cases.append({"rows": rows, "tax": random.choice([0, 5, 16, 17.5, 18])})
    out = subprocess.run(["node", "-e", NODE_RUNNER, MONEY_JS], input=json.dumps(cases), capture_output=True, text=True, check=True).stdout
    for c, js in zip(cases, json.loads(out)):
        amts, sub, tax, grand = _server(c["rows"], c["tax"])
        assert js["amts"] == amts and js["total"] == sub and js["tax"] == tax and js["grand"] == grand, (c, js, amts, sub, tax)
