"""The values a printed document can show (for the print designer), and the ready-made layouts."""
import copy

from .db import fmt, nice_date, q

DOCS = {"invoice": "Invoice", "dc": "Delivery challan", "receipt": "Payment receipt"}

COMPANY_FIELDS = [
    ("company_name", "Company name"), ("company_address", "Company address"), ("company_phone", "Company phone"),
    ("company_email", "Company email"), ("company_website", "Website"), ("company_ntn", "NTN"), ("company_gst_no", "GST / STRN no."),
    ("company_tax_ids", "NTN + GST line"),
]
FIELDS = {
    "invoice": COMPANY_FIELDS + [
        ("title", "Title (Invoice / Sales Tax Invoice)"), ("number", "Invoice #"), ("date", "Date"), ("due_date", "Due date"),
        ("customer_name", "Customer name"), ("customer_address", "Customer address"), ("customer_phone", "Customer phone"),
        ("customer_block", "Customer name + address + phone"), ("customer_code", "Customer code / ID"), ("bilti_no", "Bilti no."), ("via", "Via"),
        ("ref_no", "Ref no."), ("ctn_count", "No. of CTN"), ("po_no", "PO no."), ("branch", "Ship to (branch)"), ("courier", "Courier"),
        ("tracking_no", "Tracking no."), ("deliver_to", "Deliver to (address)"), ("rep", "Sales rep"), ("total", "Total"), ("balance", "Balance due"),
        ("amount_words", "Total in words"), ("customer_message", "Customer message"), ("invoice_note", "Invoice note"),
        ("terms_text", "Terms text"), ("footer", "Footer line"), ("page", "Page number"),
    ],
    "dc": COMPANY_FIELDS + [
        ("title", "Title"), ("number", "DC / invoice #"), ("date", "Date"), ("customer_name", "Customer name"),
        ("customer_address", "Customer address"), ("customer_phone", "Customer phone"),
        ("customer_block", "Customer name + address + phone"), ("bilti_no", "Bilti no."), ("via", "Via"), ("ref_no", "Ref no."),
        ("ctn_count", "No. of CTN"), ("po_no", "PO no."), ("branch", "Branch"), ("courier", "Courier"), ("tracking_no", "Tracking no."),
        ("deliver_to", "Deliver to (address)"),
        ("rep", "Sales rep"), ("qty_total", "Total quantity"), ("line_count", "Number of items"),
        ("page", "Page number"),
    ],
    "receipt": COMPANY_FIELDS + [
        ("title", "Title"), ("number", "Receipt #"), ("date", "Date"), ("customer_name", "Customer name"),
        ("customer_address", "Customer address"), ("customer_block", "Customer name + address + phone"), ("amount", "Amount received"),
        ("amount_words", "Amount in words"), ("method", "Payment method"), ("reference", "Cheque / reference"),
        ("balance_before", "Balance before"), ("balance_after", "Balance after"), ("notes", "Notes"),
    ],
}
COLUMNS = {
    "invoice": [("sn", "#"), ("qty", "QTY."), ("unit", "U/M"), ("ctn_qty", "CTN QTY"), ("code", "Item Code"),
                ("description", "Description"), ("price", "Price Each"), ("amount", "Amount")],
    "dc": [("sn", "#"), ("description", "Description"), ("qty", "Qty"), ("unit", "U/M"), ("ctn_qty", "CTN qty")],
    "receipt": [("bill", "Bill paid"), ("date", "Bill date"), ("bill_amount", "Bill amount"), ("paid", "Paid now"),
                ("left", "Still due")],
}
TOTAL_ROWS = {
    "invoice": [("subtotal", "Sub total"), ("tax", "Sales tax {tax_rate}%"), ("total", "Total"), ("paid", "Paid"),
                ("balance", "Balance due")],
    "dc": [("qty_total", "Total quantity")],
    "receipt": [("balance_before", "Balance before"), ("amount", "Less: this receipt"), ("balance_after", "Balance after")],
}


def _get(row, key):
    try:
        return row[key] or ""
    except (IndexError, KeyError):
        return ""


def _co_fields(s):
    ids = " · ".join(v for v in ((f"NTN {s['company_tax_no']}" if s.get("company_tax_no") else ""),
                                 (f"GST {s['company_gst_no']}" if s.get("company_gst_no") else "")) if v)
    return {"company_name": s.get("company_name", ""), "company_address": s.get("company_address", ""),
            "company_phone": s.get("company_phone", ""), "company_email": s.get("company_email", ""),
            "company_website": s.get("company_website", ""), "company_ntn": s.get("company_tax_no", ""),
            "company_gst_no": s.get("company_gst_no", ""), "company_tax_ids": ids}


def _cust(c):
    phone = c["phone"] or c["whatsapp"] or ""
    try:
        code = c["code"] or ""
    except (IndexError, KeyError):
        code = ""
    return {"customer_name": c["name"], "customer_address": c["address"] or "", "customer_phone": phone, "customer_code": code,
            "customer_block": "\n".join(v for v in (c["name"], c["address"] or "", ("Ph " + phone) if phone else "") if v)}


def invoice_data(s, inv, lines, customer, rep, open_amt, images, doc="invoice"):
    from .lines import price_text, qty_text
    from .pdfs import _words
    cur = s.get("currency", "Rs")
    f = {**_co_fields(s), **_cust(customer)}
    gst = s.get("company_gst") == "1" and inv["tax"]
    f.update(title=("VOID " if inv["void"] else "") + ("Delivery Challan" if doc == "dc" else ("Sales Tax Invoice" if gst else "Invoice")),
             number=str(inv["number"]), date=nice_date(inv["date"]), due_date=nice_date(inv["due_date"]), bilti_no=inv["bilti_no"] or "",
             via=inv["via"] or "", ref_no=inv["ref_no"] or "", ctn_count=inv["ctn_count"] or "", po_no=inv["po_no"] or "",
             rep=(rep["name"] if rep else ""), total=f"{cur} {fmt(inv['total'])}", tax_rate=f"{inv['tax_rate']:g}",
             balance=f"{cur} {fmt(open_amt if open_amt is not None else inv['total'])}",
             amount_words=f"{cur} {_words(inv['total'] // 100)} only", customer_message=inv["customer_message"] or "",
             invoice_note=s.get("invoice_note", ""), terms_text=s.get("invoice_terms", ""), footer=s.get("invoice_footer", ""),
             courier=_get(inv, "courier"), tracking_no=_get(inv, "tracking_no"), branch="", deliver_to=_get(inv, "deliver_to").strip())
    if doc != "dc" and s.get("company_gst") != "1":  # non-GST firm: PO, branch, courier and delivery address belong on the delivery challan only
        f.update(po_no="", courier="", tracking_no="", deliver_to="")
        inv = {**dict(inv), "branch_id": None}
    if doc == "dc" and f["deliver_to"]:  # the challan goes with the goods: print the delivery address as the address
        f["customer_address"] = f["deliver_to"]
        f["customer_block"] = f["customer_name"] + "\n" + f["deliver_to"]
        f["deliver_to"] = ""
    if _get(inv, "branch_id"):
        b = q("SELECT name, code FROM customer_branches WHERE id = ?", (inv["branch_id"],), one=True)
        f["branch"] = ((b["code"] + " · ") if b and b["code"] else "") + (b["name"] if b else "")
    items, n, qty_total = [], 0, 0.0
    for l in lines:
        if doc == "dc" and (l["kind"] not in ("item", None) or not (l["code"] or l["description"])):
            continue
        if l["kind"] == "item":
            n += 1
            qty_total += l["qty"] or 0
        items.append({"_kind": l["kind"], "sn": str(n) if l["kind"] == "item" else "", "qty": qty_text(l), "unit": l["unit"] or "",
                      "ctn_qty": l["ctn_qty"] or "", "code": l["code"] or "", "description": l["description"] or "",
                      "price": price_text(l), "amount": fmt(l["amount"]) if l["kind"] != "subtotal" or l["amount"] else ""})
    f.update(qty_total=f"{qty_total:g}", line_count=str(n))
    paid = inv["total"] - open_amt if open_amt is not None else 0
    totals = {"subtotal": f"{cur} {fmt(inv['subtotal'])}" if inv["tax"] else None,
              "tax": f"{cur} {fmt(inv['tax'])}" if inv["tax"] else None, "total": f"{cur} {fmt(inv['total'])}",
              "paid": f"{cur} {fmt(paid)}" if paid > 0 and not inv["void"] else None,
              "balance": f"{cur} {fmt(open_amt)}" if paid > 0 and not inv["void"] else None, "qty_total": f"{qty_total:g}"}
    return {"fields": f, "items": items, "totals": totals, "images": images, "accent": s.get("company_color")}


def receipt_data(s, p, customer, applied, balance_before, balance_after, images):
    from .pdfs import _words
    cur = s.get("currency", "Rs")
    f = {**_co_fields(s), **_cust(customer)}
    f.update(title="VOID RECEIPT" if p["void"] else "PAYMENT RECEIPT", number=str(p["number"]), date=nice_date(p["date"]),
             amount=f"{cur} {fmt(p['amount'])}", method=p["method"] or "", reference=p["reference"] or "", notes=p["notes"] or "",
             amount_words=f"{cur} {_words(p['amount'] // 100)} only",
             balance_before=f"{cur} {fmt(balance_before)}" if balance_before is not None else "",
             balance_after=(f"{cur} {fmt(balance_after)}" if balance_after >= 0 else f"Advance {cur} {fmt(-balance_after)}"))
    items = [{"bill": a["label"], "date": nice_date(a["date"]), "bill_amount": fmt(a["total"]) if a["total"] is not None else "",
              "paid": fmt(a["amount"]), "left": fmt(a["left"]) if a["left"] is not None else ""} for a in applied or []]
    totals = {"balance_before": f["balance_before"] or None, "amount": f["amount"], "balance_after": f["balance_after"]}
    return {"fields": f, "items": items, "totals": totals, "images": images, "accent": s.get("company_color")}


def sample_values(doc, company_id=None):
    """Real values from the latest document (so the designer preview looks like your own paperwork)."""
    from .companies import co_images, co_settings
    s = co_settings(company_id)
    if doc in ("invoice", "dc"):
        inv = q("SELECT * FROM invoices WHERE void = 0 {} ORDER BY id DESC LIMIT 1".format("AND company_id = ?" if company_id else ""),
                (company_id,) if company_id else (), one=True)
        if inv:
            from .ledger import open_items
            c = q("SELECT * FROM customers WHERE id = ?", (inv["customer_id"],), one=True)
            rep = q("SELECT * FROM reps WHERE id = ?", (inv["rep_id"],), one=True) if inv["rep_id"] else None
            lines = q("SELECT * FROM invoice_lines WHERE invoice_id = ? ORDER BY sort", (inv["id"],))
            return invoice_data(s, inv, lines, c, rep, open_items(c["id"])[0].get(inv["id"], 0), co_images(company_id), doc)
    if doc == "receipt":
        p = q("""SELECT p.* FROM payments p WHERE void = 0 {} ORDER BY id DESC LIMIT 1""".format(
            "AND company_id = ?" if company_id else ""), (company_id,) if company_id else (), one=True)
        if p:
            from .notify import receipt_parts
            c, applied, before, after = receipt_parts(p["id"])
            return receipt_data(s, p, c, applied, before, after, co_images(company_id))
    fake = {"customer_code": "C-0042", "customer_name": "Sample Customer", "customer_address": "Urdu Bazar, Lahore", "customer_block": "Sample Customer\nUrdu Bazar, Lahore",
            "number": "1001", "date": "30-Sep-2026", "title": DOCS[doc]}
    return {"fields": {**_co_fields(s), **fake}, "items": [], "totals": {}, "images": co_images(company_id),
            "accent": s.get("company_color")}


# ---- ready-made layouts ------------------------------------------------------------------------
def _t(id_, x, y, w, h, text, **style):
    extra = {k: style.pop(k) for k in ("hide_empty", "z", "show_if", "hide_if") if k in style}
    return {"id": id_, "type": "text", "x": x, "y": y, "w": w, "h": h, "text": text, "style": style, **extra}


def _kv(id_, x, y, w, h, rows, **style):
    """Label / value list: rows whose value is empty are not printed."""
    extra = {k: style.pop(k) for k in ("show_if", "hide_if") if k in style}
    return {"id": id_, "type": "kv", "x": x, "y": y, "w": w, "h": h, "rows": [{"label": l, "value": v} for l, v in rows],
            "style": style, **extra}


def _cols(doc, widths, **over):
    out = []
    for key, label in COLUMNS[doc]:
        if key not in widths:
            continue
        a = "right" if key in ("price", "amount", "bill_amount", "paid", "left") else ("center" if key in ("sn", "qty", "unit", "ctn_qty") else "left")
        out.append({"key": key, "label": over.get(key, label), "w": widths[key], "align": a, "show": True})
    return out


def _totals(doc, x, y, w, h, highlight, **kw):
    rows = [{"key": k, "label": l, "show": True} for k, l in TOTAL_ROWS[doc]]
    return {"id": "totals", "type": "totals", "x": x, "y": y, "w": w, "h": h, "rows": rows, "highlight": highlight,
            "hl_bg": kw.pop("hl_bg", "#1f4e79"), "hl_color": kw.pop("hl_color", "#ffffff"), "style": {"size": 10, **kw}}


def preset(name, doc):
    """name: classic | modern | minimal."""
    B = "#1f4e79"
    if doc == "receipt":
        cols = _cols("receipt", {"bill": 30, "date": 22, "bill_amount": 22, "paid": 22, "left": 22})
    elif doc == "dc":
        cols = _cols("dc", {"sn": 6, "description": 64, "qty": 10, "unit": 10, "ctn_qty": 10})
    else:
        cols = _cols("invoice", {"qty": 7, "unit": 7, "ctn_qty": 8, "code": 14, "description": 38, "price": 12, "amount": 14},
                     **({} if name != "modern" else {"qty": "QTY", "description": "DESCRIPTION", "price": "PRICE", "amount": "TOTAL",
                                                      "code": "ITEM", "unit": "U/M", "ctn_qty": "CTN"}))
    info = "Date: {date}\n" + {"invoice": "Invoice #: {number}\nDue: {due_date}", "dc": "DC #: {number}",
                                 "receipt": "Receipt #: {number}"}[doc]
    if name == "modern":
        return _modern(doc, cols)
    if name in VARIANTS:
        return _variant(doc, cols, name)
    if name == "minimal":
        els = [
            _t("coname", 15, 14, 120, 10, "{company_name}", font="Helvetica", size=16, bold=True),
            _t("coinfo", 15, 24, 120, 14, "{company_address}\n{company_phone} · {company_tax_ids}", size=8.5, color="#666666"),
            _t("title", 130, 14, 65, 12, "{title}", size=18, bold=True, align="right", color="#111111"),
            _t("info", 130, 26, 65, 14, info, size=9, align="right"),
            {"id": "l1", "type": "line", "x": 15, "y": 42, "w": 180, "h": 1, "style": {"border": 1.2, "color": "#111111"}},
            _t("billto", 15, 46, 110, 22, "{customer_block}", size=10),
            _t("dl", 130, 46, 65, 22, "DELIVER TO\n{deliver_to}", size=9, show_if="deliver_to"),
        ]
        tb = {"header_bg": "#111111", "header_color": "#ffffff", "grid": "horizontal", "line_color": "#dddddd", "fill_rows": False}
        els.append({"id": "items", "type": "items", "x": 15, "y": 72, "w": 180, "h": 160, "columns": cols, "table": tb, "style": {"size": 8.5}})
        els.append(_totals(doc, 125, 236, 70, 30, "balance" if doc == "invoice" else ("qty_total" if doc == "dc" else "balance_after"),
                           hl_bg="#111111"))
        els.append(_t("note", 15, 236, 100, 20, "{invoice_note}" if doc == "invoice" else "", size=8, color="#666666", hide_empty=True))
        return {"page": "A4", "elements": els}
    # classic: close to the layout you already use
    els = [
        {"id": "logo", "type": "image", "src": "logo", "x": 15, "y": 12, "w": 70, "h": 22, "style": {"align": "left"}},
        _t("phone", 15, 34, 70, 8, "{company_phone}", size=15, bold=True, align="center"),
        _t("web", 15, 42, 70, 5, "{company_website}", size=10, bold=True, align="center", hide_empty=True),
        _t("taxids", 15, 47, 70, 5, "{company_tax_ids}", size=8, align="center", hide_empty=True),
        _t("title", 120, 12, 75, 10, "{title}", size=18, bold=True, align="right"),
        _t("info", 139, 24, 56, 16, info, size=9, align="center", border=0.7),
        _t("cust_l", 15, 55, 88, 4, "CUSTOMER NAME", size=7, color="#777777"),
        _t("cust", 15, 59, 88, 26, "{customer_block}", size=8.5, bold=True, upper=True, border=0.7, radius=1.5),
    ]
    if doc == "invoice":
        els.append({"id": "terms", "type": "image", "src": "terms", "x": 127, "y": 59, "w": 68, "h": 26,
                     "style": {"border": 0.7, "radius": 1.5, "align": "center"}})
    if doc != "receipt":
        els.append(_t("ship", 15, 88, 180, 11, "BILTI NO: {bilti_no}      VIA: {via}      REF NO. & NO. OF CTN: {ref_no} {ctn_count}      PO: {po_no}",
                      size=8.5, bold=True, align="center", border=0.7, valign="middle"))
    tb = {"header_bg": "#ffffff", "header_color": "#000000", "grid": "vertical", "line_color": "#000000", "fill_rows": True}
    els.append({"id": "items", "type": "items", "x": 15, "y": 101, "w": 180, "h": 150, "columns": cols, "table": tb,
                "style": {"size": 8, "bold": True}})
    if doc == "invoice":
        els.append(_t("note", 15, 255, 92, 18, "{customer_message}\n{invoice_note}", size=7, align="center", border=0.7, valign="middle"))
    els.append(_totals(doc, 115, 255, 80, 22, "total" if doc == "invoice" else ("qty_total" if doc == "dc" else "balance_after"),
                       size=11, bold=True, border=0.7, hl_bg="#ffffff", hl_color="#000000"))
    if doc != "invoice":
        els.append(_t("sig", 15, 275, 180, 8, "Prepared by ____________      Checked by ____________      Received by (sign & stamp) ____________",
                      size=8.5, align="center"))
    return {"page": "A4", "elements": els}


def _modern(doc, cols):
    """Clean, modern print that matches the ERP screens. 'accent' = the company's colour (Settings → Companies)."""
    F = "Poppins"
    ink, grey, soft, line = "#0f172a", "#64748b", "#f5f7fb", "#e2e8f0"
    title = {"invoice": "{title}", "dc": "DELIVERY CHALLAN", "receipt": "PAYMENT RECEIPT"}[doc]
    meta = {"invoice": [("Invoice no.", "{number}"), ("Date", "{date}"), ("Due date", "{due_date}"), ("Customer ID", "{customer_code}")],
            "dc": [("Challan no.", "{number}"), ("Date", "{date}"), ("Customer ID", "{customer_code}")],
            "receipt": [("Receipt no.", "{number}"), ("Date", "{date}")]}[doc]
    els = [
        {"id": "band", "type": "box", "x": 0, "y": 0, "w": 210, "h": 3.5, "style": {"bg": "accent"}},
        {"id": "logo", "type": "image", "src": "logo", "x": 15, "y": 10, "w": 40, "h": 26, "style": {"align": "left"}},
        _t("coname", 60, 11, 78, 8, "{company_name}", font=F, size=14, bold=True, color=ink),
        _t("coinfo", 60, 19, 78, 17, "{company_address}\n{company_phone}   {company_email}\n{company_tax_ids}", font=F, size=7.5,
           color=grey, line_height=1.35),
        _t("title", 132, 10, 63, 10, title, font=F, size=18, bold=True, align="right", color="accent", upper=True),
        _kv("meta", 135, 22, 60, 17, meta, font=F, size=7.5, color=ink, label_color=grey),
        {"id": "div", "type": "line", "x": 15, "y": 40, "w": 180, "h": 1, "style": {"border": 0.6, "color": line}},
        {"id": "card1", "type": "box", "x": 15, "y": 44, "w": 105, "h": 28, "style": {"bg": soft, "radius": 2.5}},
        _t("to_l", 19, 46, 90, 5, {"dc": "DELIVER TO", "receipt": "RECEIVED WITH THANKS FROM"}.get(doc, "BILL TO"),
           font=F, size=6.5, bold=True, color="accent"),
        _t("to_n", 19, 51, 97, 7, "{customer_name}", font=F, size=11, bold=True, color=ink, hide_if="deliver_to"),
        _t("to_a", 19, 58, 97, 13, "{customer_address}\n{customer_phone}", font=F, size=8, color=grey, line_height=1.35, hide_if="deliver_to"),
        _t("to_n2", 19, 51, 47, 9, "{customer_name}", font=F, size=8.5, bold=True, color=ink, line_height=1.2, show_if="deliver_to"),
        _t("to_a2", 19, 60, 47, 11, "{customer_address}\n{customer_phone}", font=F, size=7.5, color=grey, line_height=1.3, show_if="deliver_to"),
        {"id": "dl_div", "type": "line", "x": 67.5, "y": 47, "w": 0.3, "h": 22, "style": {"border": 0.5, "color": line}, "show_if": "deliver_to"},
        _t("dl_l", 70, 46, 47, 5, "DELIVER TO", font=F, size=6.5, bold=True, color="accent", show_if="deliver_to"),
        _t("dl_t", 70, 51, 47, 20, "{deliver_to}", font=F, size=7.5, color=ink, line_height=1.3, show_if="deliver_to"),
    ]
    if doc == "receipt":
        els += [{"id": "card2", "type": "box", "x": 125, "y": 44, "w": 70, "h": 28, "style": {"bg": "accent", "radius": 2.5}},
                _t("amt_l", 129, 47, 62, 5, "AMOUNT RECEIVED", font=F, size=6.5, bold=True, color="#ffffff"),
                _t("amt", 129, 53, 62, 10, "{amount}", font=F, size=16, bold=True, color="#ffffff"),
                _t("amt_m", 129, 63, 62, 7, "{method}  {reference}", font=F, size=7.5, color="#e0e7ff"),
                _t("words", 15, 76, 180, 6, "In words: {amount_words}", font=F, size=8, italic=True, color=grey),
                _t("applied_l", 15, 84, 180, 6, "APPLIED TO THESE BILLS", font=F, size=7, bold=True, color=grey)]
        top = 91
    else:
        els += [{"id": "card2", "type": "box", "x": 125, "y": 44, "w": 70, "h": 28, "style": {"bg": soft, "radius": 2.5}},
                _kv("ship", 128, 46, 64, 25, [("PO no.", "{po_no}"), ("Reference", "{ref_no}"),
                                              ("Bilti no.", "{bilti_no}"), ("Via", "{via}"), ("Cartons", "{ctn_count}"),
                                              ("Courier", "{courier}"), ("Tracking no.", "{tracking_no}")],
                                  font=F, size=7.5, color=ink, label_color=grey)]
        top = 78
    tb = {"header_bg": "accent", "header_color": "#ffffff", "grid": "horizontal", "line_color": line, "line_width": 0.7,
          "zebra": "#fafbfd", "fill_rows": False, "row_pad": 2.1, "header_align_cols": True}
    body_h = {"invoice": 142, "dc": 150, "receipt": 120}[doc]
    els.append({"id": "items", "type": "items", "x": 15, "y": top, "w": 180, "h": body_h, "columns": cols, "table": tb,
                "style": {"font": F, "size": 8, "color": ink}})
    ty = top + body_h + 4
    if doc == "invoice":
        els += [_totals("invoice", 125, ty, 70, 38, "last", font=F, size=8.5, lines=True, hl_bg="accent"),
                _t("words", 15, ty, 105, 7, "{amount_words}", font=F, size=7.5, italic=True, color=grey),
                {"id": "note_b", "type": "box", "x": 15, "y": ty + 8, "w": 105, "h": 14, "style": {"bg": soft, "radius": 2}},
                _t("note", 18, ty + 9, 99, 12, "{customer_message}\n{invoice_note}", font=F, size=7, color=grey, valign="middle"),
                {"id": "terms", "type": "image", "src": "terms", "x": 15, "y": ty + 24, "w": 70, "h": 16, "style": {"align": "left"}}]
    elif doc == "dc":
        els += [_totals("dc", 135, ty, 60, 10, "last", font=F, size=9, hl_bg="accent"),
                _t("recv", 15, ty, 110, 8, "Received the above goods in good condition.", font=F, size=8, color=grey)]
    else:
        els.append(_totals("receipt", 100, ty, 95, 26, "last", font=F, size=8.5, lines=True, hl_bg="accent"))
    sy = 266
    sigs = {"invoice": ["Authorised signature"], "dc": ["Prepared by", "Checked by", "Driver", "Received by (sign & stamp)"],
            "receipt": ["Customer", "Cashier / accounts", "Authorised signature"]}[doc]
    w = 180 / len(sigs) if len(sigs) > 1 else 60
    for i, lbl in enumerate(sigs):
        x = 15 + i * w if len(sigs) > 1 else 135
        els += [{"id": f"sl{i}", "type": "line", "x": x + 4, "y": sy, "w": w - 8, "h": 1, "style": {"border": 0.6, "color": "#94a3b8"}},
                _t(f"st{i}", x, sy + 1, w, 5, lbl, font=F, size=7, color=grey, align="center")]
    els += [{"id": "foot", "type": "box", "x": 0, "y": 283, "w": 210, "h": 14, "style": {"bg": soft}},
            {"id": "footband", "type": "box", "x": 0, "y": 295, "w": 210, "h": 2, "style": {"bg": "accent"}},
            _t("foot_t", 15, 285, 180, 8, "{company_name}   ·   {company_phone}   ·   {company_website}      Thank you for your business",
               font=F, size=7, color=grey, align="center", valign="middle")]
    return {"page": "A4", "elements": els}


PRESET_NAMES = {"modern": "Modern", "bold": "Bold header", "elegant": "Elegant", "corporate": "Corporate", "compact": "Compact",
                "classic": "Classic (QuickBooks)", "minimal": "Minimal"}
VARIANTS = ("bold", "elegant", "corporate", "compact")


def _variant(doc, cols, name):
    """Four more ready-made styles. Every one shows the logo, uses the company colour ('accent') and prints
    'Deliver to' only when it is filled."""
    ink, grey, soft, line = "#0f172a", "#64748b", "#f5f7fb", "#e2e8f0"
    font = {"bold": "Poppins", "elegant": "Times", "corporate": "Helvetica", "compact": "DejaVu Sans"}[name]
    title = {"invoice": "{title}", "dc": "DELIVERY CHALLAN", "receipt": "PAYMENT RECEIPT"}[doc]
    meta = {"invoice": [("Invoice no.", "{number}"), ("Date", "{date}"), ("Due date", "{due_date}"), ("Customer ID", "{customer_code}"),
                        ("PO no.", "{po_no}")],
            "dc": [("Challan no.", "{number}"), ("Date", "{date}"), ("Customer ID", "{customer_code}"), ("PO no.", "{po_no}")],
            "receipt": [("Receipt no.", "{number}"), ("Date", "{date}"), ("Method", "{method}"), ("Reference", "{reference}")]}[doc]
    ship = [("Reference", "{ref_no}"), ("Bilti no.", "{bilti_no}"), ("Via", "{via}"), ("Cartons", "{ctn_count}"),
            ("Courier", "{courier}"), ("Tracking no.", "{tracking_no}")]
    to_label = {"dc": "DELIVER TO", "receipt": "RECEIVED FROM"}.get(doc, "BILL TO")
    T = lambda *a, **k: _t(*a, font=font, **k)
    K = lambda *a, **k: _kv(*a, font=font, **k)
    els = []
    if name == "bold":
        # full-width colour header with the logo on a white tile
        els += [{"id": "hdr", "type": "box", "x": 0, "y": 0, "w": 210, "h": 44, "style": {"bg": "accent"}},
                {"id": "logo_bg", "type": "box", "x": 12, "y": 8, "w": 42, "h": 28, "style": {"bg": "#ffffff", "radius": 3}},
                {"id": "logo", "type": "image", "src": "logo", "x": 14, "y": 10, "w": 38, "h": 24, "style": {"align": "center"}},
                T("coname", 60, 9, 80, 8, "{company_name}", size=15, bold=True, color="#ffffff"),
                T("coinfo", 60, 18, 80, 18, "{company_address}\n{company_phone}   {company_email}\n{company_tax_ids}", size=7.5,
                  color="#e0e7ff", line_height=1.35),
                T("title", 135, 9, 62, 10, title, size=17, bold=True, align="right", color="#ffffff", upper=True),
                K("meta", 140, 20, 57, 22, meta, size=7.5, color="#ffffff", label_color="#c7d2fe")]
        y = 50
        els += [T("to_l", 15, y, 85, 5, to_label, size=7, bold=True, color="accent"),
                T("to_b", 15, y + 5, 85, 22, "{customer_name}\n{customer_address}\n{customer_phone}", size=8.5, color=ink, line_height=1.35)]
        if doc != "receipt":
            els += [T("dl_l", 103, y, 45, 5, "DELIVER TO", size=7, bold=True, color="accent", show_if="deliver_to"),
                    T("dl_t", 103, y + 5, 45, 22, "{deliver_to}", size=8, color=ink, line_height=1.3, show_if="deliver_to"),
                    K("ship", 150, y, 45, 26, ship, size=7.5, color=ink, label_color=grey)]
        tb = {"header_bg": ink, "header_color": "#ffffff", "grid": "horizontal", "line_color": line, "zebra": "#f8fafc", "row_pad": 2,
              "fill_rows": False}
        top = y + 30
    elif name == "elegant":
        # centred letterhead, thin rules, no colour fills
        els += [{"id": "logo", "type": "image", "src": "logo", "x": 80, "y": 8, "w": 50, "h": 22, "style": {"align": "center"}},
                T("coname", 15, 31, 180, 8, "{company_name}", size=16, bold=True, align="center", color=ink),
                T("coinfo", 15, 39, 180, 9, "{company_address}  ·  {company_phone}  ·  {company_email}\n{company_tax_ids}", size=8,
                  align="center", color=grey, line_height=1.3),
                {"id": "r1", "type": "line", "x": 15, "y": 50, "w": 180, "h": 1, "style": {"border": 1.2, "color": "accent"}},
                {"id": "r2", "type": "line", "x": 15, "y": 51.4, "w": 180, "h": 1, "style": {"border": 0.4, "color": "accent"}},
                T("title", 15, 54, 180, 9, title, size=15, bold=True, align="center", color="accent", upper=True)]
        y = 66
        els += [T("to_l", 15, y, 70, 5, to_label, size=8, italic=True, color=grey),
                T("to_b", 15, y + 5, 70, 22, "{customer_name}\n{customer_address}\n{customer_phone}", size=9.5, color=ink, line_height=1.3),
                K("meta", 140, y, 55, 26, meta, size=8.5, color=ink, label_color=grey)]
        if doc != "receipt":
            els += [T("dl_l", 88, y, 50, 5, "Deliver to", size=8, italic=True, color=grey, show_if="deliver_to"),
                    T("dl_t", 88, y + 5, 50, 22, "{deliver_to}", size=9, color=ink, line_height=1.3, show_if="deliver_to"),
                    K("ship", 88, y, 50, 24, ship, size=8, color=ink, label_color=grey, hide_if="deliver_to")]
        tb = {"header_bg": "#ffffff", "header_color": "accent", "grid": "horizontal", "line_color": "#cbd5e1", "row_pad": 2.2,
              "fill_rows": False}
        top = y + 32
    elif name == "corporate":
        # colour strip down the left, boxed details
        els += [{"id": "strip", "type": "box", "x": 0, "y": 0, "w": 7, "h": 297, "style": {"bg": "accent"}},
                {"id": "logo", "type": "image", "src": "logo", "x": 15, "y": 10, "w": 45, "h": 26, "style": {"align": "left"}},
                T("coname", 64, 11, 70, 8, "{company_name}", size=14, bold=True, color=ink),
                T("coinfo", 64, 19, 70, 17, "{company_address}\n{company_phone}\n{company_email}\n{company_tax_ids}", size=7.5,
                  color=grey, line_height=1.3),
                {"id": "tbox", "type": "box", "x": 138, "y": 10, "w": 57, "h": 30, "style": {"border": 0.8, "border_color": "accent", "radius": 1.5}},
                {"id": "tband", "type": "box", "x": 138, "y": 10, "w": 57, "h": 8, "style": {"bg": "accent"}},
                T("title", 138, 10, 57, 8, title, size=10, bold=True, align="center", color="#ffffff", upper=True, valign="middle"),
                K("meta", 141, 19, 51, 20, meta, size=7.5, color=ink, label_color=grey)]
        y = 46
        els += [{"id": "c1", "type": "box", "x": 15, "y": y, "w": 88, "h": 27, "style": {"border": 0.6, "border_color": "#cbd5e1"}},
                T("to_l", 18, y + 1.5, 80, 5, to_label, size=7, bold=True, color="accent"),
                T("to_b", 18, y + 6.5, 82, 20, "{customer_name}\n{customer_address}\n{customer_phone}", size=8.5, color=ink, line_height=1.3)]
        if doc != "receipt":
            els += [{"id": "c2", "type": "box", "x": 107, "y": y, "w": 88, "h": 27, "style": {"border": 0.6, "border_color": "#cbd5e1"}},
                    T("dl_l", 110, y + 1.5, 80, 5, "DELIVER TO", size=7, bold=True, color="accent", show_if="deliver_to"),
                    T("dl_t", 110, y + 6.5, 40, 20, "{deliver_to}", size=8, color=ink, line_height=1.3, show_if="deliver_to"),
                    K("ship", 151, y + 2, 42, 24, ship, size=7, color=ink, label_color=grey, show_if="deliver_to"),
                    T("sh_l", 110, y + 1.5, 80, 5, "SHIPPING", size=7, bold=True, color="accent", hide_if="deliver_to"),
                    K("ship2", 110, y + 7, 82, 19, ship, size=7.5, color=ink, label_color=grey, hide_if="deliver_to")]
        tb = {"header_bg": "accent", "header_color": "#ffffff", "grid": "all", "line_color": "#cbd5e1", "row_pad": 1.8, "fill_rows": False}
        top = y + 31
    else:  # compact: everything small so long invoices fit on fewer pages
        els += [{"id": "logo", "type": "image", "src": "logo", "x": 15, "y": 8, "w": 30, "h": 18, "style": {"align": "left"}},
                T("coname", 48, 8, 90, 7, "{company_name}", size=12, bold=True, color=ink),
                T("coinfo", 48, 15, 90, 11, "{company_address} · {company_phone}\n{company_tax_ids}", size=7, color=grey, line_height=1.3),
                T("title", 140, 8, 55, 8, title, size=13, bold=True, align="right", color="accent", upper=True),
                T("num", 140, 17, 55, 6, "No. {number}   ·   {date}", size=8, align="right", color=ink),
                {"id": "bar", "type": "box", "x": 15, "y": 28, "w": 180, "h": 0.8, "style": {"bg": "accent"}}]
        y = 31
        els += [T("to_b", 15, y, 70, 18, to_label.title() + ": {customer_name}\n{customer_address}\n{customer_phone}", size=7.5, color=ink,
                  line_height=1.3),
                K("meta", 145, y, 50, 18, meta[2:] if doc != "receipt" else meta[2:], size=7, color=ink, label_color=grey)]
        if doc != "receipt":
            els += [T("dl_t", 88, y, 55, 18, "Deliver to: {deliver_to}", size=7.5, color=ink, line_height=1.3, show_if="deliver_to"),
                    K("ship", 88, y, 55, 18, ship, size=7, color=ink, label_color=grey, hide_if="deliver_to")]
        tb = {"header_bg": soft, "header_color": ink, "grid": "horizontal", "line_color": line, "zebra": "#fbfcfe", "row_pad": 1.2,
              "fill_rows": False}
        top = y + 21
    if doc == "receipt":
        els += [T("amt_l", 15, top, 90, 5, "AMOUNT RECEIVED", size=7, bold=True, color=grey),
                T("amt", 15, top + 5, 120, 10, "{amount}", size=18, bold=True, color="accent"),
                T("words", 15, top + 16, 180, 6, "{amount_words}", size=8, italic=True, color=grey)]
        top += 25
    body_h = {"invoice": 150, "dc": 160, "receipt": 110}[doc] + (top < 80) * 10 - (top > 95) * 12
    els.append({"id": "items", "type": "items", "x": 15, "y": top, "w": 180, "h": body_h, "columns": copy.deepcopy(cols), "table": tb,
                "style": {"font": font, "size": 7.5 if name == "compact" else 8, "color": ink}})
    ty = top + body_h + 4
    hl = "last" if doc != "dc" else "qty_total"
    if doc == "invoice":
        els += [_totals("invoice", 125, ty, 70, 36, "last", font=font, size=8.5, lines=True, hl_bg="accent"),
                T("words", 15, ty, 105, 7, "{amount_words}", size=7.5, italic=True, color=grey),
                T("note", 15, ty + 8, 105, 12, "{customer_message}\n{invoice_note}", size=7, color=grey, hide_empty=True),
                {"id": "terms", "type": "image", "src": "terms", "x": 15, "y": ty + 21, "w": 70, "h": 14, "style": {"align": "left"}}]
    elif doc == "dc":
        els += [_totals("dc", 135, ty, 60, 10, "last", font=font, size=9, hl_bg="accent"),
                T("recv", 15, ty + 1, 110, 8, "Received the above goods in good condition.", size=8, color=grey)]
    else:
        els.append(_totals("receipt", 100, ty, 95, 26, "last", font=font, size=8.5, lines=True, hl_bg="accent"))
    sigs = {"invoice": ["Authorised signature"], "dc": ["Prepared by", "Checked by", "Driver", "Received by (sign & stamp)"],
            "receipt": ["Customer", "Cashier / accounts", "Authorised signature"]}[doc]
    sy = 272
    w = 180 / len(sigs) if len(sigs) > 1 else 60
    for i, lbl in enumerate(sigs):
        x0 = 15 + i * w if len(sigs) > 1 else 135
        els += [{"id": f"sl{i}", "type": "line", "x": x0 + 4, "y": sy, "w": w - 8, "h": 1, "style": {"border": 0.6, "color": "#94a3b8"}},
                T(f"st{i}", x0, sy + 1, w, 5, lbl, size=7, color=grey, align="center")]
    foot_bg = {"bold": "accent", "elegant": None, "corporate": soft, "compact": None}[name]
    if foot_bg:
        els.append({"id": "foot", "type": "box", "x": 0, "y": 286, "w": 210, "h": 11, "style": {"bg": foot_bg}})
    els.append(T("foot_t", 15, 287, 180, 8, "{company_name}   ·   {company_phone}   ·   {company_website}      Thank you for your business",
                 size=7, color="#ffffff" if name == "bold" else grey, align="center", valign="middle"))
    if name == "elegant":
        els.append({"id": "r3", "type": "line", "x": 15, "y": 286, "w": 180, "h": 1, "style": {"border": 0.4, "color": "accent"}})
    return {"page": "A4", "elements": els}


def presets(doc):
    return {n: preset(n, doc) for n in PRESET_NAMES}


def active_layout(doc, company_id):
    """The layout switched on for this company (or for all companies), or None to use the built-in print."""
    r = q("""SELECT layout FROM print_layouts WHERE doc = ? AND active = 1 AND (company_id = ? OR company_id IS NULL)
             ORDER BY company_id IS NULL, id DESC LIMIT 1""", (doc, company_id))
    if not r:
        return None
    import json
    try:
        return json.loads(r[0]["layout"])
    except ValueError:
        return None


def copy_layout(layout):
    return copy.deepcopy(layout)
