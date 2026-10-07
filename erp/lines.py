"""Invoice line maths, QuickBooks style.

Line kinds:
  item      qty x price (blank qty = price alone)
  subtotal  sum of the lines above it, back to the previous sub total (not counted in the total)
  discount  / any line whose price is a percent: that percent of the line directly above
"""
from .db import mul_rnd, pct_rnd, to_paisa


def parse_price(text):
    """'460' -> (46000, None); '-5%' -> (0, -5.0); '' -> (0, None)."""
    s = str(text or "").replace(",", "").strip()
    if s.endswith("%"):
        try:
            return 0, float(s[:-1] or 0)
        except ValueError:
            raise ValueError(f"'{text}' is not a valid percent")
    return to_paisa(s), None


def parse_qty(text):
    s = str(text or "").replace(",", "").strip()
    if not s:
        return None
    try:
        return float(s)
    except ValueError:
        raise ValueError(f"Quantity '{text}' is not a number")


def compute(lines):
    """Fills in 'amount' for every line and returns the invoice subtotal (sub total lines excluded)."""
    group = 0
    prev = 0
    total = 0
    for l in lines:
        if l["kind"] == "subtotal":
            l["amount"] = group
            group = 0
        elif l.get("percent") is not None:
            l["amount"] = pct_rnd(prev, l["percent"])
            group += l["amount"]
            total += l["amount"]
        else:
            qty = l.get("qty")
            l["amount"] = mul_rnd(qty if qty is not None else 1, l["rate"]) if l["rate"] else 0
            group += l["amount"]
            total += l["amount"]
        prev = l["amount"]
    return total


def price_text(line):
    if line["kind"] == "subtotal":
        return ""
    if line["percent"] is not None:
        return f"{line['percent']:g}%"
    return f"{line['rate'] / 100:.2f}" if line["rate"] else ""


def qty_text(line):
    return "" if line["qty"] is None else f"{line['qty']:g}"
