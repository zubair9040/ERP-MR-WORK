"""PDF documents: invoice, payment receipt, account statement."""
from datetime import date
from xml.sax.saxutils import escape

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

from .db import fmt, nice_date

_ss = getSampleStyleSheet()
TITLE = ParagraphStyle("t", parent=_ss["Title"], alignment=2, fontSize=20, spaceAfter=0, textColor=colors.HexColor("#1f4e79"))
CO = ParagraphStyle("co", parent=_ss["Heading2"], spaceAfter=2, spaceBefore=0)
N = ParagraphStyle("n", parent=_ss["Normal"], fontSize=9, leading=12)
SMALL = ParagraphStyle("s", parent=N, textColor=colors.grey)
ACCENT = colors.HexColor("#1f4e79")


def P(text, style=N):
    return Paragraph(escape(str(text or "")).replace("\n", "<br/>"), style)


def _doc(path, title):
    return SimpleDocTemplate(path, pagesize=A4, leftMargin=15 * mm, rightMargin=15 * mm,
                             topMargin=14 * mm, bottomMargin=14 * mm, title=title)


# ---- modern look shared by statements, payslips, credit notes and warehouse documents -----------------
INK, GREY, SOFT, LINE = colors.HexColor("#0f172a"), colors.HexColor("#64748b"), colors.HexColor("#f5f7fb"), colors.HexColor("#e2e8f0")


def _f(bold=False, italic=False):
    from .layout_pdf import font_name
    return font_name("Poppins", bold, italic)


def _accent(s):
    try:
        return colors.HexColor(s.get("company_color") or "#4f46e5")
    except (ValueError, TypeError):
        return colors.HexColor("#4f46e5")


def MS(size=8.5, bold=False, color=INK, align=0, italic=False, leading=None):
    return ParagraphStyle("m", fontName=_f(bold, italic), fontSize=size, leading=leading or size * 1.3, textColor=color, alignment=align)


def MP(text, **kw):
    return Paragraph(escape(str(text or "")).replace("\n", "<br/>"), MS(**kw))


def _header(s, title, info_rows, images=None):
    """Logo + company on the left, title in the company colour and details on the right."""
    ac = _accent(s)
    logo_p = (images or {}).get("logo") or s.get("_logo")
    logo = _image(logo_p, 38 * mm, 24 * mm) if logo_p else None
    co = [MP(s.get("company_name"), size=13, bold=True)]
    info_lines = [v for v in (s.get("company_address", "").replace("\n", ", "),
                              "   ".join(x for x in (s.get("company_phone"), s.get("company_email")) if x),
                              " · ".join(x for x in ((f"NTN {s['company_tax_no']}" if s.get("company_tax_no") else ""),
                                                     (f"GST {s['company_gst_no']}" if s.get("company_gst_no") else "")) if x)) if v]
    co += [MP(v, size=7.5, color=GREY) for v in info_lines]
    meta = Table([[MP(k, size=7.5, color=GREY), MP(v, size=7.5, bold=True, align=2)] for k, v in info_rows],
                 colWidths=[26 * mm, 36 * mm])
    meta.setStyle(TableStyle([("LEFTPADDING", (0, 0), (-1, -1), 0), ("RIGHTPADDING", (0, 0), (-1, -1), 0),
                              ("TOPPADDING", (0, 0), (-1, -1), 0.6), ("BOTTOMPADDING", (0, 0), (-1, -1), 0.6)]))
    right = [MP(title, size=17, bold=True, color=ac, align=2), Spacer(1, 3), meta]
    if logo:
        logo.hAlign = "LEFT"
        t = Table([[logo, co, right]], colWidths=[42 * mm, 76 * mm, 62 * mm])
    else:
        t = Table([[co, right]], colWidths=[118 * mm, 62 * mm])
    t.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "TOP"), ("LEFTPADDING", (0, 0), (-1, -1), 0), ("RIGHTPADDING", (0, 0), (-1, -1), 0),
                           ("LINEBELOW", (0, 0), (-1, 0), 0.6, LINE), ("BOTTOMPADDING", (0, 0), (-1, -1), 8)]))
    return t


def _card(content, width, bg=None, pad=8):
    t = Table([[content]], colWidths=[width])
    t.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, -1), bg or SOFT), ("ROUNDEDCORNERS", [6, 6, 6, 6]),
                           ("LEFTPADDING", (0, 0), (-1, -1), pad), ("RIGHTPADDING", (0, 0), (-1, -1), pad),
                           ("TOPPADDING", (0, 0), (-1, -1), pad - 2), ("BOTTOMPADDING", (0, 0), (-1, -1), pad - 2),
                           ("VALIGN", (0, 0), (-1, -1), "TOP")]))
    return t


def _mgrid(s, data, widths, right_cols, total_rows=0, sub_rows=()):
    """Modern table: coloured heading, light row lines, soft stripes."""
    ac = _accent(s)
    head = [MP(h, size=7.5, bold=True, color=colors.white, align=2 if i in right_cols else 0) for i, h in enumerate(data[0])]
    body = []
    for r_i, r in enumerate(data[1:], start=1):
        is_tot = r_i > len(data) - 1 - total_rows
        body.append([c if not isinstance(c, (str, int, float)) else
                     MP(c, size=8, bold=is_tot, align=2 if i in right_cols else 0) for i, c in enumerate(r)])
    t = Table([head] + body, colWidths=widths, repeatRows=1)
    st = [("BACKGROUND", (0, 0), (-1, 0), ac), ("VALIGN", (0, 0), (-1, -1), "TOP"), ("LINEBELOW", (0, 1), (-1, -1), 0.5, LINE),
          ("TOPPADDING", (0, 0), (-1, -1), 3.5), ("BOTTOMPADDING", (0, 0), (-1, -1), 3.5),
          ("LEFTPADDING", (0, 0), (-1, -1), 4), ("RIGHTPADDING", (0, 0), (-1, -1), 4)]
    for i in range(1, len(data) - total_rows):
        if i % 2 == 0 and i not in sub_rows:
            st.append(("BACKGROUND", (0, i), (-1, i), colors.HexColor("#fafbfd")))
    for i in sub_rows:
        st += [("TOPPADDING", (0, i), (-1, i), 0), ("LINEBELOW", (0, i - 1), (-1, i - 1), 0, colors.white)]
    if total_rows:
        st += [("LINEABOVE", (0, -total_rows), (-1, -total_rows), 1, INK), ("BACKGROUND", (0, -total_rows), (-1, -1), SOFT)]
    t.setStyle(TableStyle(st))
    return t


def _build(path, title, story, s, pagesize=None):
    """Builds the PDF with a thin colour band at the top and a footer with the company line and page number."""
    ac = _accent(s)
    foot = "   ·   ".join(x for x in (s.get("company_name"), s.get("company_phone"), s.get("company_website")) if x)

    pagesize = pagesize or A4
    small = pagesize[0] < A4[0]
    margin = (10 if small else 15) * mm

    def deco(c, d):
        w, h = pagesize
        c.saveState()
        c.setFillColor(ac)
        c.rect(0, h - 3.5 * mm, w, 3.5 * mm, stroke=0, fill=1)
        c.setFillColor(SOFT)
        c.rect(0, 0, w, 11 * mm, stroke=0, fill=1)
        c.setFillColor(ac)
        c.rect(0, 0, w, 1.6 * mm, stroke=0, fill=1)
        c.setFillColor(GREY)
        c.setFont(_f(), 7)
        c.drawString(margin, 5 * mm, foot)
        c.drawRightString(w - margin, 5 * mm, f"Page {d.page}")
        c.restoreState()
    doc = SimpleDocTemplate(path, pagesize=pagesize, leftMargin=margin, rightMargin=margin, topMargin=(9 if small else 12) * mm,
                            bottomMargin=16 * mm, title=title)
    doc.build(story, onFirstPage=deco, onLaterPages=deco)
    return path


def _grid(data, widths, right_cols, total_rows=0):
    t = Table(data, colWidths=widths, repeatRows=1)
    st = [
        ("BACKGROUND", (0, 0), (-1, 0), ACCENT), ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"), ("FONTSIZE", (0, 0), (-1, -1), 9),
        ("LINEBELOW", (0, 1), (-1, -1 - total_rows), 0.25, colors.lightgrey), ("VALIGN", (0, 0), (-1, -1), "TOP"),
    ]
    for c in right_cols:
        st.append(("ALIGN", (c, 0), (c, -1), "RIGHT"))
    if total_rows:
        st += [("FONTNAME", (0, -total_rows), (-1, -1), "Helvetica-Bold"),
               ("LINEABOVE", (0, -total_rows), (-1, -total_rows), 0.75, colors.black)]
    t.setStyle(TableStyle(st))
    return t


def _to_block(customer):
    out = [Paragraph("<b>Bill to</b>", N), P(customer["name"])]
    if customer["address"]:
        out.append(P(customer["address"]))
    if customer["whatsapp"] or customer["phone"]:
        out.append(P(customer["whatsapp"] or customer["phone"]))
    return out


def _image(path, max_w, max_h):
    from reportlab.platypus import Image
    from reportlab.lib.utils import ImageReader
    try:
        iw, ih = ImageReader(path).getSize()
    except Exception:
        return None
    scale = min(max_w / iw, max_h / ih)
    return Image(path, width=iw * scale, height=ih * scale)


def _boxed(rows, widths, bold_header=True, fs=8.5):
    t = Table(rows, colWidths=widths)
    st = [("BOX", (0, 0), (-1, -1), 0.7, colors.black), ("INNERGRID", (0, 0), (-1, -1), 0.7, colors.black),
          ("ALIGN", (0, 0), (-1, -1), "CENTER"), ("VALIGN", (0, 0), (-1, -1), "MIDDLE"), ("FONTSIZE", (0, 0), (-1, -1), fs)]
    if bold_header:
        st.append(("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"))
    t.setStyle(TableStyle(st))
    return t


def invoice(path, s, inv, lines, customer, rep, open_amt=None, images=None):
    """Invoice laid out like the S.Makki Sons QuickBooks template."""
    from .lines import price_text, qty_text
    images = images or {}
    cur = s.get("currency", "Rs")
    B = ParagraphStyle("b", parent=N, fontName="Helvetica-Bold", fontSize=8.5, leading=10.5)
    story = []

    # --- header: logo / company on the left, "Invoice" + date box on the right
    left = []
    logo = _image(images["logo"], 70 * mm, 22 * mm) if images.get("logo") else None
    if logo:
        logo.hAlign = "LEFT"
        left.append(logo)
    else:
        left.append(P(s.get("company_name"), CO))
    if s.get("company_phone"):
        left.append(Paragraph(f"<para alignment='center'><b>{escape(s['company_phone'])}</b></para>",
                              ParagraphStyle("ph", parent=N, fontSize=15, leading=18)))
    if s.get("company_website"):
        left.append(Paragraph(f"<para alignment='center'><b>{escape(s['company_website'])}</b></para>",
                              ParagraphStyle("web", parent=N, fontSize=10, leading=12)))
    if s.get("company_address") and not logo:
        left.append(P(s["company_address"]))
    tax_ids = " · ".join(v for v in ((f"NTN {s['company_tax_no']}" if s.get("company_tax_no") else ""),
                                     (f"GST {s['company_gst_no']}" if s.get("company_gst_no") else "")) if v)
    if tax_ids:
        left.append(Paragraph(f"<para alignment='center'>{escape(tax_ids)}</para>", ParagraphStyle("tx", parent=N, fontSize=8, leading=10)))
    title = "VOID INVOICE" if inv["void"] else ("Sales Tax Invoice" if s.get("company_gst") == "1" and inv["tax"] else "Invoice")
    datebox = _boxed([["Date", "Invoice #"], [nice_date(inv["date"]), str(inv["number"])]], [30 * mm, 26 * mm])
    right = [Paragraph(f"<para alignment='right'><b>{title}</b></para>", ParagraphStyle("it", parent=N, fontSize=18, leading=22)),
             Spacer(1, 3), datebox]
    h = Table([[left, right]], colWidths=[100 * mm, 80 * mm])
    h.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "TOP"), ("ALIGN", (1, 0), (1, 0), "RIGHT"),
                           ("LEFTPADDING", (0, 0), (-1, -1), 0), ("RIGHTPADDING", (0, 0), (-1, -1), 0)]))
    story += [h, Spacer(1, 3 * mm)]

    # --- customer box + terms box
    cust_lines = [Paragraph(escape(customer["name"]).upper(), B)]
    for ln in (customer["address"] or "").splitlines():
        cust_lines.append(Paragraph(escape(ln).upper(), B))
    ph = customer["phone"] or customer["whatsapp"]
    if ph:
        cust_lines.append(Paragraph("PH " + escape(ph), B))
    cbox = Table([[cust_lines]], colWidths=[88 * mm], rowHeights=[26 * mm])
    cbox.setStyle(TableStyle([("BOX", (0, 0), (-1, -1), 0.7, colors.black), ("VALIGN", (0, 0), (-1, -1), "TOP"),
                              ("ROUNDEDCORNERS", [4, 4, 4, 4])]))
    terms = _image(images["terms"], 62 * mm, 24 * mm) if images.get("terms") else None
    if terms is None and s.get("invoice_terms"):
        terms = P(s["invoice_terms"])
    tbox = ""
    if terms is not None:
        tbox = Table([[terms]], colWidths=[66 * mm], rowHeights=[26 * mm])
        tbox.setStyle(TableStyle([("BOX", (0, 0), (-1, -1), 0.7, colors.black), ("ALIGN", (0, 0), (-1, -1), "CENTER"),
                                  ("VALIGN", (0, 0), (-1, -1), "MIDDLE"), ("ROUNDEDCORNERS", [4, 4, 4, 4])]))
    ct = Table([[[P("CUSTOMER NAME", SMALL), cbox], "", tbox]], colWidths=[90 * mm, 22 * mm, 68 * mm])
    ct.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "BOTTOM"), ("LEFTPADDING", (0, 0), (-1, -1), 0),
                            ("RIGHTPADDING", (0, 0), (-1, -1), 0)]))
    story += [ct, Spacer(1, 3 * mm)]

    # --- bilti / via / ref box
    ref = " ".join(x for x in [inv["ref_no"], inv["ctn_count"], ("PO " + inv["po_no"]) if inv["po_no"] else ""] if x)
    bv = _boxed([["BILTI NO:", "Via", "Ref No. &  No. of CTN"],
                 [Paragraph(f"<para alignment='center'>{escape(inv['bilti_no'] or '')}</para>", B),
                  Paragraph(f"<para alignment='center'>{escape(inv['via'] or '')}</para>", B),
                  Paragraph(f"<para alignment='center'>{escape(ref)}</para>", B)]],
                [60 * mm, 42 * mm, 78 * mm])
    story += [bv]

    # --- item grid with vertical lines, padded to a fixed height
    SM = ParagraphStyle("sm", parent=B, fontSize=8, leading=9.5)
    rows = [["QTY.", "U/M", "CTN QTY", "Item Code", "Description", "Price Each", "Amount"]]
    for l in lines:
        rows.append([qty_text(l), P(l["unit"], SM), Paragraph(escape(l["ctn_qty"] or ""), SM), Paragraph(escape(l["code"] or ""), SM),
                     Paragraph(escape(l["description"] or ""), SM), price_text(l).replace("%", ".00%") if l["percent"] is not None and float(l["percent"]).is_integer() else price_text(l),
                     fmt(l["amount"])])
    filler = max(0, 22 - len(rows))
    rows += [[""] * 7 for _ in range(filler)]
    grid = Table(rows, colWidths=[13 * mm, 12 * mm, 15 * mm, 24 * mm, 70 * mm, 22 * mm, 24 * mm], repeatRows=1)
    st = [("BOX", (0, 0), (-1, -1), 0.7, colors.black), ("LINEAFTER", (0, 0), (-2, -1), 0.7, colors.black),
          ("LINEBELOW", (0, 0), (-1, 0), 0.7, colors.black), ("FONTSIZE", (0, 0), (-1, -1), 8),
          ("FONTNAME", (0, 0), (-1, -1), "Helvetica-Bold"), ("ALIGN", (0, 0), (-1, 0), "CENTER"),
          ("ALIGN", (5, 1), (6, -1), "RIGHT"), ("ALIGN", (0, 1), (0, -1), "CENTER"), ("VALIGN", (0, 0), (-1, -1), "TOP"),
          ("TOPPADDING", (0, 1), (-1, -1), 1.5), ("BOTTOMPADDING", (0, 1), (-1, -1), 1.5)]
    for n, l in enumerate(lines, start=1):
        if l["kind"] == "subtotal":
            st.append(("BACKGROUND", (0, n), (-1, n), colors.HexColor("#eeeeee")))
    grid.setStyle(TableStyle(st))
    story.append(grid)

    # --- footer: note + total box
    tot_rows = []
    if inv["tax"]:
        tot_rows.append([f"Sales tax {inv['tax_rate']:g}%", f"{cur} {fmt(inv['tax'])}"])
    tot_rows.append(["Total", f"{cur} {fmt(inv['total'])}"])
    if open_amt is not None and not inv["void"] and 0 < inv["total"] - open_amt:
        tot_rows.append(["Paid", f"{cur} {fmt(inv['total'] - open_amt)}"])
        tot_rows.append(["Balance Due", f"{cur} {fmt(open_amt)}"])
    tt = Table(tot_rows, colWidths=[30 * mm, 50 * mm])
    tt.setStyle(TableStyle([("FONTNAME", (0, 0), (-1, -1), "Helvetica-Bold"), ("FONTSIZE", (0, 0), (-1, -1), 12),
                            ("ALIGN", (1, 0), (1, -1), "RIGHT"), ("VALIGN", (0, 0), (-1, -1), "MIDDLE")]))
    note = s.get("invoice_note") or ""
    msg = inv["customer_message"] or ""
    note_cell = [Paragraph(f"<para alignment='center'>{escape(note)}</para>", ParagraphStyle("nt", parent=N, fontSize=7))] if note else []
    if msg:
        note_cell.insert(0, P(msg))
    f = Table([[note_cell, "", tt]], colWidths=[92 * mm, 8 * mm, 80 * mm])
    f.setStyle(TableStyle([("BOX", (0, 0), (0, 0), 0.7, colors.black), ("BOX", (2, 0), (2, 0), 0.7, colors.black),
                           ("VALIGN", (0, 0), (-1, -1), "MIDDLE"), ("TOPPADDING", (0, 0), (-1, -1), 6),
                           ("BOTTOMPADDING", (0, 0), (-1, -1), 6)]))
    story += [Spacer(1, 3 * mm), f]
    if s.get("invoice_footer"):
        story += [Spacer(1, 4 * mm), P(s["invoice_footer"], SMALL)]
    _doc(path, f"Invoice {inv['number']}").build(story)
    return path


def _brand_header(s, images, title, info_rows):
    """Logo (or company name) on the left, big title and an info box on the right."""
    left = []
    logo = _image(images["logo"], 62 * mm, 22 * mm) if images and images.get("logo") else None
    if logo:
        logo.hAlign = "LEFT"
        left.append(logo)
    else:
        left.append(P(s.get("company_name"), CO))
    contact = " · ".join(v for v in (s.get("company_phone"), s.get("company_website")) if v)
    if s.get("company_address"):
        left.append(P(s["company_address"].replace("\n", ", "), SMALL))
    if contact:
        left.append(P(contact, SMALL))
    if s.get("company_tax_no") or s.get("company_gst_no"):
        left.append(P(" · ".join(v for v in ((f"NTN {s['company_tax_no']}" if s.get("company_tax_no") else ""),
                                            (f"GST {s['company_gst_no']}" if s.get("company_gst_no") else "")) if v), SMALL))
    info = _boxed([[k for k, _ in info_rows], [v for _, v in info_rows]], [28 * mm] * len(info_rows), fs=9)
    right = [Paragraph(f"<para alignment='right'><b>{escape(title)}</b></para>",
                       ParagraphStyle("bt", parent=N, fontSize=19, leading=23, textColor=ACCENT)), Spacer(1, 4), info]
    h = Table([[left, right]], colWidths=[100 * mm, 80 * mm])
    h.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "TOP"), ("ALIGN", (1, 0), (1, 0), "RIGHT"),
                           ("LEFTPADDING", (0, 0), (-1, -1), 0), ("RIGHTPADDING", (0, 0), (-1, -1), 0)]))
    return h


def _signatures(labels):
    n = len(labels)
    w = 180 * mm / n
    sig = Table([[""] * n, labels], colWidths=[w] * n, rowHeights=[16 * mm, 6 * mm])
    st = [("FONTSIZE", (0, 1), (-1, 1), 8.5), ("ALIGN", (0, 1), (-1, 1), "CENTER"),
          ("LEFTPADDING", (0, 0), (-1, -1), 10), ("RIGHTPADDING", (0, 0), (-1, -1), 10)]
    for i in range(n):
        st.append(("LINEABOVE", (i, 1), (i, 1), 0.6, colors.black))
    sig.setStyle(TableStyle(st))
    return sig


def receipt(path, s, p, customer, balance_after, applied=None, images=None, balance_before=None):
    """Payment receipt: amount in big type and words, which bills it paid, balance, signature."""
    cur = s.get("currency", "Rs")
    story = [_brand_header(s, images, "VOID RECEIPT" if p["void"] else "PAYMENT RECEIPT",
                           [("Receipt #", str(p["number"])), ("Date", nice_date(p["date"]))]), Spacer(1, 7 * mm)]
    who = [Paragraph("<font size=8 color='#667085'>RECEIVED WITH THANKS FROM</font>", N),
           Paragraph(f"<b>{escape(customer['name'])}</b>", ParagraphStyle("cn", parent=N, fontSize=13, leading=16))]
    if customer["address"]:
        who.append(P(customer["address"], SMALL))
    amt = [Paragraph("<para alignment='right'><font size=8 color='#667085'>AMOUNT RECEIVED</font></para>", N),
           Paragraph(f"<para alignment='right'><b>{cur} {fmt(p['amount'])}</b></para>",
                     ParagraphStyle("am", parent=N, fontSize=20, leading=24, textColor=ACCENT))]
    top = Table([[who, amt]], colWidths=[105 * mm, 75 * mm])
    top.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "TOP"), ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#f3f6fb")),
                             ("BOX", (0, 0), (-1, -1), 0.6, ACCENT), ("TOPPADDING", (0, 0), (-1, -1), 8),
                             ("BOTTOMPADDING", (0, 0), (-1, -1), 8), ("LEFTPADDING", (0, 0), (-1, -1), 9),
                             ("RIGHTPADDING", (0, 0), (-1, -1), 9)]))
    story += [top, Spacer(1, 2 * mm),
              P(f"Amount in words: {cur} {_words(p['amount'] // 100)}" + (f" and {p['amount'] % 100:02d}/100" if p["amount"] % 100 else "")
                + " only", SMALL), Spacer(1, 5 * mm)]
    det = [["Payment method", "Reference / cheque no.", "Received by"],
           [p["method"] or "", P(p["reference"] or "—"), ""]]
    story += [_grid(det, [50 * mm, 80 * mm, 50 * mm], []), Spacer(1, 5 * mm)]
    if applied:
        rows = [["Bill paid", "Bill date", "Bill amount", "Paid by this receipt", "Still due on bill"]]
        for a in applied:
            rows.append([a["label"], nice_date(a["date"]), fmt(a["total"]) if a["total"] is not None else "", fmt(a["amount"]),
                         fmt(a["left"]) if a["left"] is not None else ""])
        rows.append(["Total", "", "", fmt(sum(a["amount"] for a in applied)), ""])
        story += [Paragraph("<b>Applied to</b>", N), Spacer(1, 1.5 * mm),
                  _grid(rows, [34 * mm, 30 * mm, 38 * mm, 42 * mm, 36 * mm], [2, 3, 4], 1), Spacer(1, 5 * mm)]
    bal = []
    if balance_before is not None:
        bal.append(["Balance before this receipt", f"{cur} {fmt(balance_before)}"])
    bal.append(["Less: this receipt", f"{cur} {fmt(p['amount'])}"])
    if balance_after < 0:
        bal.append(["Advance (credit) after this receipt", f"{cur} {fmt(-balance_after)}"])
    else:
        bal.append(["Balance after this receipt", f"{cur} {fmt(balance_after)}"])
    bt = Table(bal, colWidths=[60 * mm, 45 * mm], hAlign="RIGHT")
    bt.setStyle(TableStyle([("FONTSIZE", (0, 0), (-1, -1), 9.5), ("ALIGN", (1, 0), (1, -1), "RIGHT"),
                            ("FONTNAME", (0, -1), (-1, -1), "Helvetica-Bold"), ("LINEABOVE", (0, -1), (-1, -1), 0.8, colors.black)]))
    story += [bt, Spacer(1, 14 * mm), _signatures(["Customer", "Cashier / Accounts", "Authorised signature"]),
              Spacer(1, 6 * mm), P("This is a computer generated receipt. Cheques are subject to realisation.", SMALL)]
    _doc(path, f"Receipt {p['number']}").build(story)
    return path


def delivery_challan(path, s, inv, lines, customer, images=None):
    """Delivery challan printed from an invoice: quantities only, no prices. Not linked to the warehouse."""
    B = ParagraphStyle("b", parent=N, fontName="Helvetica-Bold", fontSize=8.5, leading=10.5)
    story = [_brand_header(s, images, "DELIVERY CHALLAN", [("DC #", str(inv["number"])), ("Date", nice_date(inv["date"])),
                                                              ("Invoice #", str(inv["number"]))]), Spacer(1, 6 * mm)]
    to = [Paragraph("<font size=8 color='#667085'>DELIVER TO</font>", N), Paragraph(f"<b>{escape(customer['name'])}</b>", B)]
    for ln in (customer["address"] or "").splitlines():
        to.append(P(ln))
    if customer["phone"] or customer["whatsapp"]:
        to.append(P("Ph " + (customer["phone"] or customer["whatsapp"])))
    ship = [["Bilti no.", inv["bilti_no"] or ""], ["Via / transport", inv["via"] or ""], ["Ref no.", inv["ref_no"] or ""],
            ["No. of cartons", inv["ctn_count"] or ""]]
    st_ = Table([[Paragraph(f"<b>{k}</b>", N), P(v)] for k, v in ship], colWidths=[28 * mm, 50 * mm])
    st_.setStyle(TableStyle([("BOX", (0, 0), (-1, -1), 0.6, colors.black), ("INNERGRID", (0, 0), (-1, -1), 0.3, colors.lightgrey),
                             ("FONTSIZE", (0, 0), (-1, -1), 9)]))
    tb = Table([[to, st_]], colWidths=[100 * mm, 80 * mm])
    tb.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "TOP"), ("BOX", (0, 0), (0, 0), 0.6, colors.black),
                            ("LEFTPADDING", (0, 0), (0, 0), 8), ("TOPPADDING", (0, 0), (0, 0), 6),
                            ("LEFTPADDING", (1, 0), (1, 0), 6), ("RIGHTPADDING", (1, 0), (1, 0), 0)]))
    story += [tb, Spacer(1, 5 * mm)]
    rows = [["#", "Description", "Qty", "U/M", "CTN qty"]]
    total_qty, n = 0.0, 0
    for l in lines:
        if l["kind"] not in ("item", None) or not (l["code"] or l["description"]):
            continue
        n += 1
        q_ = l["qty"] or 0
        total_qty += q_
        rows.append([str(n), P(l["description"]), f"{q_:g}" if q_ else "", P(l["unit"]), P(l["ctn_qty"])])
    rows.append(["", f"{n} items", f"{total_qty:g}", "", ""])
    story.append(_grid(rows, [9 * mm, 110 * mm, 20 * mm, 20 * mm, 21 * mm], [2], 1))
    story += [Spacer(1, 6 * mm), P("Received the above goods in good condition.", N), Spacer(1, 16 * mm),
              _signatures(["Prepared by", "Checked / packed by", "Driver", "Received by (sign & stamp)"])]
    _doc(path, f"Delivery challan {inv['number']}").build(story)
    return path


PAY_ABBR = {"Cheque": "CHQ", "Cash": "CASH", "Bank transfer": "BANK", "Online": "ONLINE", "Other": ""}


def _tx_text(l):
    if l["type"] == "Invoice":
        due = f" Due {nice_date(l['due'])}." if l.get("due") else ""
        return f"INV #{l['ref']}.{due}"
    if l["type"] == "Payment":
        m = PAY_ABBR.get(l.get("method"), l.get("method") or "")
        return f"PMT#{m} {l.get('reference') or ''}".strip() + "."
    if l["type"] == "Credit note":
        return f"CR NOTE #{l['ref']}."
    return l["type"] + (f" {l['ref']}" if l.get("ref") else "")


def statement(path, s, customer, st, aging=None, details=None, images=None):
    """Customer statement in the modern ERP style."""
    cur = s.get("currency", "Rs")
    from .ledger import BUCKETS
    ac = _accent(s)
    period = (f"Open items as of {nice_date(st['end'])}" if st.get("open_mode")
              else f"{nice_date(st['start'])} to {nice_date(st['end'])}")
    story = [_header(s, "STATEMENT", [("Date", nice_date(st["end"])), ("Period", period if not st.get("open_mode") else "Unpaid bills")],
                     images), Spacer(1, 5 * mm)]
    phone = customer["whatsapp"] or customer["phone"] or ""
    to = [MP("STATEMENT FOR", size=6.5, bold=True, color=ac), Spacer(1, 2), MP(customer["name"], size=11, bold=True)]
    if customer["address"]:
        to.append(MP(customer["address"], size=8, color=GREY))
    if phone:
        to.append(MP(phone, size=8, color=GREY))
    due = [MP("AMOUNT DUE", size=6.5, bold=True, color=colors.white), Spacer(1, 3),
           MP(f"{cur} {fmt(st['closing'])}", size=16, bold=True, color=colors.white), Spacer(1, 3),
           MP("Amount enclosed: ______________", size=7.5, color=colors.HexColor("#e0e7ff"))]
    cards = Table([[_card(to, 104 * mm), "", _card(due, 70 * mm, ac)]], colWidths=[106 * mm, 4 * mm, 70 * mm])
    cards.setStyle(TableStyle([("LEFTPADDING", (0, 0), (-1, -1), 0), ("RIGHTPADDING", (0, 0), (-1, -1), 0), ("VALIGN", (0, 0), (-1, -1), "TOP")]))
    story += [cards, Spacer(1, 5 * mm), MP(("All unpaid bills" if st.get("open_mode") else "Statement period ") +
                                          ("" if st.get("open_mode") else period), size=8, color=GREY), Spacer(1, 2 * mm)]
    rows = [["Date", "Transaction", "Invoiced", "Paid", "Balance"]]
    subs = []
    if not st.get("open_mode"):
        rows.append([nice_date(st["start"]), MP("Balance brought forward", size=8, italic=True, color=GREY), "", "", fmt(st["brought_forward"])])
    for l in st["lines"]:
        label = _tx_text(l)
        if st.get("open_mode") and l.get("total") and l["total"] != l["debit"]:
            label += f" (bill {fmt(l['total'])}, part paid)"
        rows.append([nice_date(l["date"]), label, fmt(l["debit"]) if l["debit"] else "", fmt(l["credit"]) if l["credit"] else "",
                     fmt(l["balance"])])
        if details and l["type"] == "Invoice" and l.get("id") in details:
            from .lines import price_text, qty_text
            for d in details[l["id"]]:
                txt = " ".join(x for x in [qty_text(d), d["unit"] or "", d["code"] or "", "-", d["description"] or ""] if x)
                pr = price_text(d)
                if pr and d["kind"] != "subtotal":
                    txt += f" @ {pr}"
                rows.append(["", MP(f"{txt} = {fmt(d['amount'])}", size=7, color=GREY), "", "", ""])
                subs.append(len(rows) - 1)
    rows.append(["", "Closing balance", fmt(st.get("invoiced", 0)), fmt(st.get("paid", 0)), f"{cur} {fmt(st['closing'])}"])
    story.append(_mgrid(s, rows, [24 * mm, 80 * mm, 25 * mm, 25 * mm, 26 * mm], {2, 3, 4}, 1, subs))
    if aging is not None:
        keys = list(aging.keys())
        labels = ([f"{k} days old" if k != "180+" else "Over 180 days" for k in keys] if "0-30" in aging
                  else ["Current", "1-30 days", "31-60 days", "61-90 days", "Over 90 days"])
        cells = [_card([MP(lbl, size=6.5, color=GREY), MP(fmt(aging[b]), size=9.5, bold=True, color=colors.HexColor("#b91c1c")
                                                            if b in ("61-90", "90+", "91-180", "180+") and aging[b] > 0 else INK)], 28 * mm, pad=6)
                 for lbl, b in zip(labels, keys)]
        cells.append(_card([MP("Amount due", size=6.5, color=colors.white), MP(f"{cur} {fmt(st['closing'])}", size=9.5, bold=True,
                                                                               color=colors.white)], 34 * mm, ac, pad=6))
        a = Table([cells], colWidths=[29.3 * mm] * 5 + [33.5 * mm])
        a.setStyle(TableStyle([("LEFTPADDING", (0, 0), (-1, -1), 0), ("RIGHTPADDING", (0, 0), (-1, -1), 1.2)]))
        story += [Spacer(1, 5 * mm), MP("AGING", size=6.5, bold=True, color=ac), Spacer(1, 1.5 * mm), a]
    story += [Spacer(1, 6 * mm), MP("Please contact us if anything on this statement doesn't match your records. Thank you for your business.",
                                    size=7.5, color=GREY)]
    return _build(path, f"Statement {customer['name']}", story, s)


def credit_note(path, s, doc, lines, customer):
    cur = s.get("currency", "Rs")
    from .lines import qty_text
    info = [["Credit note #", str(doc["number"])], ["Date", nice_date(doc["date"])]]
    if doc["invoice_ref"]:
        info.append(["Against invoice", doc["invoice_ref"]])
    story = [_header(s, "VOID CREDIT NOTE" if doc["void"] else "CREDIT NOTE", info), Spacer(1, 8 * mm)]
    story += [Paragraph("<b>Customer</b>", N), P(customer["name"])]
    if customer["address"]:
        story.append(P(customer["address"]))
    story.append(Spacer(1, 6 * mm))
    rows = [["QTY", "U/M", "ITEM CODE", "DESCRIPTION", "RATE", "AMOUNT"]]
    for l in lines:
        rows.append([qty_text(l), P(l["unit"]), P(l["code"]), P(l["description"]), fmt(l["rate"]), fmt(l["amount"])])
    totals = []
    if doc["tax"]:
        totals.append(["", "", "", "", f"Tax {doc['tax_rate']:g}%", fmt(doc["tax"])])
    totals.append(["", "", "", "", f"CREDIT {cur}", fmt(doc["total"])])
    story.append(_mgrid(s, rows + totals, [16 * mm, 16 * mm, 28 * mm, 70 * mm, 24 * mm, 26 * mm], [0, 4, 5], len(totals)))
    story += [Spacer(1, 6 * mm), P("This amount has been credited to your account.", SMALL)]
    if doc["notes"]:
        story += [Spacer(1, 3 * mm), P(doc["notes"], SMALL)]
    _build(path, f"Credit note {doc['number']}", story, s)
    return path


def wh_document(path, s, doc, lines, T, number, show_cost=False, values=None):
    """Printable warehouse document: goods receipt, delivery challan, transfer, adjustment, stock count."""
    dtype = doc["type"]
    info = [["Doc no.", number], ["Date", nice_date(doc["date"])]]
    if doc["ref"]:
        info.append(["Reference", doc["ref"]])
    story = [_header(s, T["pdf"] if not doc["void"] else "VOID " + T["pdf"], info), Spacer(1, 6 * mm)]
    left = []
    if dtype == "TRF":
        left += [Paragraph(f"<b>From:</b> {escape(doc['wh_name'])}", N), Paragraph(f"<b>To:</b> {escape(doc['to_name'] or '')}", N)]
    else:
        left.append(Paragraph(f"<b>Warehouse:</b> {escape(doc['wh_name'])}", N))
    if doc["party"]:
        left.append(Paragraph(f"<b>{escape(T['party'] or 'Party')}:</b> {escape(doc['party'])}", N))
    if doc["vehicle"]:
        left.append(Paragraph(f"<b>Vehicle / transport:</b> {escape(doc['vehicle'])}", N))
    story += left + [Spacer(1, 5 * mm)]
    qfmt = lambda v: "" if v is None else f"{v:g}"
    if dtype == "CNT":
        rows = [["#", "ITEM CODE", "DESCRIPTION", "U/M", "SYSTEM", "COUNTED", "DIFFERENCE"]]
        for n, l in enumerate(lines, 1):
            rows.append([n, P(l["code"]), P(l["description"] or l["name"]), P(l["unit"]), qfmt(l["system_qty"]), qfmt(l["counted"]),
                         (f"+{l['qty']:g}" if l["qty"] > 0 else qfmt(l["qty"]))])
        widths, right = [10 * mm, 28 * mm, 70 * mm, 16 * mm, 18 * mm, 18 * mm, 20 * mm], [4, 5, 6]
    else:
        cost = show_cost and dtype in ("GRN", "OPN")
        rows = [["#", "ITEM CODE", "DESCRIPTION", "CTN", "PCS/CTN", "LOOSE", "TOTAL PCS"] + (["COST/PC", "VALUE"] if cost else [])]
        for n, l in enumerate(lines, 1):
            q_ = (f"+{l['qty']:g}" if dtype == "ADJ" and l["qty"] > 0 else qfmt(l["qty"]))
            ks = l.keys()
            ctn_ = l["ctn"] if "ctn" in ks else None
            loose_ = l["loose"] if "loose" in ks else None
            if ctn_ is None and loose_ is None:
                ctn_, ppc_, loose_ = None, None, l["qty"]
            else:
                ppc_ = l["ppc"]
            row = [n, P(l["code"]), P((l["description"] or l["name"]) + (f"  ({l['note']})" if l["note"] else "")),
                   qfmt(ctn_) if ctn_ else "", qfmt(ppc_) if ctn_ else "", qfmt(loose_) if loose_ else "", q_]
            if cost:
                row += [fmt(l["unit_cost"]), fmt(int(round(l["qty"] * l["unit_cost"])))]
            rows.append(row)
        total_q = sum(abs(l["qty"]) for l in lines)
        total_c = sum(abs(l["ctn"] or 0) for l in lines if "ctn" in l.keys())
        tot = ["", "", "Total", f"{total_c:g}" if total_c else "", "", "", f"{total_q:g}"]
        if cost:
            tot += ["", fmt(sum(int(round(l["qty"] * l["unit_cost"])) for l in lines))]
        rows.append(tot)
        widths = ([10 * mm, 28 * mm, 68 * mm, 16 * mm, 18 * mm, 18 * mm, 22 * mm] if not cost else
                  [8 * mm, 22 * mm, 46 * mm, 13 * mm, 16 * mm, 14 * mm, 19 * mm, 19 * mm, 23 * mm])
        right = [3, 4, 5, 6, 7, 8] if cost else [3, 4, 5, 6]
        if dtype == "DC":  # issue notes don't show item codes
            rows = [r[:1] + r[2:] for r in rows]
            widths = [10 * mm, 96 * mm, 18 * mm, 18 * mm, 18 * mm, 20 * mm]
            right = [2, 3, 4, 5]
    story.append(_mgrid(s, rows, widths, right, 0 if dtype == "CNT" else 1))
    if values and dtype != "CNT" and lines:
        cost_v, sale_v = values
        cur = s.get("currency", "Rs")
        boxes = [_card([MP("Total cost value", size=6.5, color=GREY), MP(f"{cur} {fmt(int(round(cost_v)))}", size=10, bold=True)], 86 * mm, pad=6),
                 _card([MP("Total sale value", size=6.5, color=GREY), MP(f"{cur} {fmt(int(round(sale_v)))}", size=10, bold=True)], 86 * mm, pad=6)]
        bt = Table([boxes], colWidths=[90 * mm, 90 * mm])
        bt.setStyle(TableStyle([("LEFTPADDING", (0, 0), (-1, -1), 0), ("RIGHTPADDING", (0, 0), (-1, -1), 0)]))
        story += [Spacer(1, 4 * mm), bt]
    if doc["notes"]:
        story += [Spacer(1, 4 * mm), P(doc["notes"], SMALL)]
    sig = {"GRN": ["Received by (store)", "Delivered by (supplier)", "Checked by"],
           "DC": ["Issued by (store)", "Received by", "Approved by"],
           "TRF": ["Issued by", "Received by", "Approved by"]}.get(dtype, ["Prepared by", "Checked by", "Approved by"])
    sg = Table([["", "", ""], sig], colWidths=[60 * mm] * 3, rowHeights=[16 * mm, 6 * mm])
    sg.setStyle(TableStyle([("LINEABOVE", (0, 1), (0, 1), 0.6, colors.black), ("LINEABOVE", (1, 1), (1, 1), 0.6, colors.black),
                            ("LINEABOVE", (2, 1), (2, 1), 0.6, colors.black), ("FONTSIZE", (0, 1), (-1, 1), 8),
                            ("ALIGN", (0, 1), (-1, 1), "CENTER"), ("LEFTPADDING", (0, 0), (-1, -1), 8), ("RIGHTPADDING", (0, 0), (-1, -1), 8)]))
    story += [Spacer(1, 10 * mm), sg]
    _build(path, number, story, s)
    return path


def _words(n):
    """Whole rupees in words (Pakistani style: thousand, lakh, crore)."""
    ones = ["", "One", "Two", "Three", "Four", "Five", "Six", "Seven", "Eight", "Nine", "Ten", "Eleven", "Twelve", "Thirteen",
            "Fourteen", "Fifteen", "Sixteen", "Seventeen", "Eighteen", "Nineteen"]
    tens = ["", "", "Twenty", "Thirty", "Forty", "Fifty", "Sixty", "Seventy", "Eighty", "Ninety"]

    def two(v):
        return ones[v] if v < 20 else (tens[v // 10] + (" " + ones[v % 10] if v % 10 else ""))

    def three(v):
        return ((ones[v // 100] + " Hundred" + (" " if v % 100 else "")) if v >= 100 else "") + (two(v % 100) if v % 100 else "")

    if n == 0:
        return "Zero"
    parts = []
    for size, name in ((10 ** 7, "Crore"), (10 ** 5, "Lakh"), (1000, "Thousand")):
        if n >= size:
            parts.append(f"{three(n // size) if n // size < 1000 else _words(n // size)} {name}")
            n %= size
    if n:
        parts.append(three(n))
    return " ".join(parts)


def payslip(path, s, run, l, label, adv_balance=None):
    """Salary slip on A5 (148 x 210 mm). adv_balance: number, or {"Loan": x, "Advance": y} still to recover."""
    from reportlab.lib.pagesizes import A5
    cur = s.get("currency", "Rs")
    ac = _accent(s)
    W = 128 * mm
    logo_p = s.get("_logo")
    logo = _image(logo_p, 26 * mm, 16 * mm) if logo_p else None
    co = [MP(s.get("company_name"), size=10.5, bold=True)]
    if s.get("company_address"):
        co.append(MP(s.get("company_address", "").replace("\n", ", "), size=6.5, color=GREY))
    right = [MP("SALARY SLIP", size=12, bold=True, color=ac, align=2), MP(label, size=8, bold=True, align=2),
             MP(("Final" if run["status"] == "final" else "DRAFT") + (f" · paid {nice_date(l['paid_date'])}" if l["paid"] else ""),
                size=6.5, color=GREY, align=2)]
    if logo:
        logo.hAlign = "LEFT"
        h = Table([[logo, co, right]], colWidths=[29 * mm, 55 * mm, 44 * mm])
    else:
        h = Table([[co, right]], colWidths=[84 * mm, 44 * mm])
    h.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "TOP"), ("LEFTPADDING", (0, 0), (-1, -1), 0), ("RIGHTPADDING", (0, 0), (-1, -1), 0),
                           ("LINEBELOW", (0, 0), (-1, 0), 0.6, LINE), ("BOTTOMPADDING", (0, 0), (-1, -1), 5)]))
    story = [h, Spacer(1, 4 * mm)]
    kv = lambda k, v: [MP(k, size=6.5, color=GREY), MP(v or "-", size=7.5, bold=True)]
    emp = Table([kv("Employee", l["name"]) + kv("Code", l["code"]),
                 kv("Designation", l["designation"]) + kv("Department", l["department"]),
                 kv("Days in month", str(run["days"])) + kv("Paid by", l["paid_method"] or l["pay_method"]),
                 kv("Account", " ".join(v for v in (l["bank_name"], l["bank_account"]) if v)) + kv("Joined", nice_date(l["join_date"]))],
                colWidths=[20 * mm, 44 * mm, 20 * mm, 44 * mm])
    emp.setStyle(TableStyle([("LEFTPADDING", (0, 0), (-1, -1), 2), ("RIGHTPADDING", (0, 0), (-1, -1), 2),
                             ("TOPPADDING", (0, 0), (-1, -1), 1.2), ("BOTTOMPADDING", (0, 0), (-1, -1), 1.2), ("VALIGN", (0, 0), (-1, -1), "MIDDLE")]))
    story += [_card(emp, W - 2 * mm, pad=5), Spacer(1, 4 * mm)]
    earn = [["Basic salary", fmt(l["basic"])]]
    if l["allowance"]:
        earn.append(["Allowance", fmt(l["allowance"])])
    if l["ot_amount"]:
        earn.append([f"Overtime ({l['ot_hours']:g} hrs)", fmt(l["ot_amount"])])
    if l["bonus"]:
        earn.append(["Bonus / incentive", fmt(l["bonus"])])
    ded = []
    if l["absent_ded"]:
        ded.append([f"Absent ({l['absent_days']:g} days)", fmt(l["absent_ded"])])
    if l["loan_ded"]:
        ded.append(["Loan instalment", fmt(l["loan_ded"])])
    if l["advance_ded"]:
        ded.append(["Advance recovery", fmt(l["advance_ded"])])
    if l["other_ded"]:
        ded.append(["Other deductions", fmt(l["other_ded"])])
    n = max(len(earn), len(ded), 1)
    earn += [["", ""]] * (n - len(earn))
    ded += [["", ""]] * (n - len(ded))
    gross = l["basic"] + l["allowance"] + l["ot_amount"] + l["bonus"]
    total_ded = l["absent_ded"] + l["loan_ded"] + l["advance_ded"] + l["other_ded"]
    data = [["Earnings", "Amount", "Deductions", "Amount"]] + [e + d for e, d in zip(earn, ded)]
    data.append(["Gross", fmt(gross), "Total deducted", fmt(total_ded)])
    story.append(_mgrid(s, data, [38 * mm, 26 * mm, 38 * mm, 26 * mm], [1, 3], 1))
    net = [MP("NET SALARY", size=6.5, bold=True, color=colors.white),
           MP(f"{cur} {fmt(l['net'])}", size=15, bold=True, color=colors.white),
           MP(f"{cur} {_words(max(l['net'], 0) // 100)} only", size=6.5, color=colors.HexColor("#e0e7ff"))]
    story += [Spacer(1, 4 * mm), _card(net, W - 2 * mm, ac, pad=6)]
    bal = adv_balance if isinstance(adv_balance, dict) else ({"Advance / loan": adv_balance} if adv_balance else {})
    bal = {k: v for k, v in bal.items() if v}
    if bal:
        cells = [_card([MP(f"{k} still to recover", size=6, color=GREY), MP(f"{cur} {fmt(v)}", size=9, bold=True)], 61 * mm, pad=5)
                 for k, v in bal.items()]
        t = Table([cells], colWidths=[64 * mm] * len(cells))
        t.setStyle(TableStyle([("LEFTPADDING", (0, 0), (-1, -1), 0), ("RIGHTPADDING", (0, 0), (-1, -1), 0)]))
        t.hAlign = "LEFT"
        story += [Spacer(1, 3 * mm), t]
    if l["note"]:
        story += [Spacer(1, 2 * mm), MP(f"Note: {l['note']}", size=7, color=GREY)]
    sig = Table([[""] * 5, ["Prepared by", "", "Employee", "", "Authorised"]], colWidths=[36 * mm, 10 * mm, 36 * mm, 10 * mm, 36 * mm],
                rowHeights=[12 * mm, 5 * mm])
    sig.setStyle(TableStyle([("LINEABOVE", (0, 1), (0, 1), 0.5, INK), ("LINEABOVE", (2, 1), (2, 1), 0.5, INK),
                             ("LINEABOVE", (4, 1), (4, 1), 0.5, INK), ("FONTNAME", (0, 1), (-1, 1), _f()), ("FONTSIZE", (0, 1), (-1, 1), 7),
                             ("TEXTCOLOR", (0, 1), (-1, 1), GREY), ("ALIGN", (0, 1), (-1, 1), "CENTER"),
                             ("LEFTPADDING", (0, 0), (-1, -1), 6), ("RIGHTPADDING", (0, 0), (-1, -1), 6)]))
    story += [Spacer(1, 6 * mm), sig]
    _build(path, f"Salary slip {l['name']} {label}", story, s, pagesize=A5)
    return path


def po_invoice(path, s, b, customer, rows, t, lines, draft=False):
    """Combined invoice for head office: every branch invoice of one PO, with delivery and tracking, then an item summary."""
    from reportlab.platypus import PageBreak
    from .lines import price_text, qty_text
    cur = s.get("currency", "Rs")
    ac = _accent(s)
    title = "COMBINED INVOICE" + (" (DRAFT)" if draft else "")
    info = [("Invoice no.", str(b["combined_no"]) if b["combined_no"] else "draft"),
            ("Date", nice_date(b["combined_date"] or date.today().isoformat())), ("PO no.", b["po_no"]), ("PO date", nice_date(b["date"]))]
    story = [_header(s, title, info), Spacer(1, 5 * mm)]
    phone = customer["whatsapp"] or customer["phone"] or ""
    to = [MP("BILL TO (HEAD OFFICE)", size=6.5, bold=True, color=ac), Spacer(1, 2), MP(customer["name"], size=11, bold=True)]
    if customer["address"]:
        to.append(MP(customer["address"], size=8, color=GREY))
    if phone:
        to.append(MP(phone, size=8, color=GREY))
    due = [MP("TOTAL FOR THIS PO", size=6.5, bold=True, color=colors.white), Spacer(1, 3),
           MP(f"{cur} {fmt(t['total'])}", size=16, bold=True, color=colors.white), Spacer(1, 3),
           MP(f"{t['count']} branch invoice(s) · {t['delivered']} delivered", size=7.5, color=colors.HexColor("#e0e7ff"))]
    cards = Table([[_card(to, 104 * mm), "", _card(due, 70 * mm, ac)]], colWidths=[106 * mm, 4 * mm, 70 * mm])
    cards.setStyle(TableStyle([("LEFTPADDING", (0, 0), (-1, -1), 0), ("RIGHTPADDING", (0, 0), (-1, -1), 0), ("VALIGN", (0, 0), (-1, -1), "TOP")]))
    story += [cards, Spacer(1, 5 * mm), MP("BRANCH DELIVERIES", size=7, bold=True, color=GREY), Spacer(1, 1.5 * mm)]
    taxed = bool(t["tax"])
    head = ["#", "Branch", "Invoice", "Delivery / tracking"] + (["Amount", "Tax"] if taxed else []) + ["Total"]
    data, n = [head], 0
    for r in rows:
        for i in r["invoices"]:
            n += 1
            br = r["branch"]
            btxt = [MP(((br["code"] + " · ") if br and br["code"] else "") + (br["name"] if br else "Head office / no branch"), size=8, bold=True)]
            if br and br["address"]:
                btxt.append(MP(br["address"], size=7, color=GREY))
            trk = " ".join(v for v in (i["courier"], i["tracking_no"]) if v) or "-"
            dl = [MP(trk, size=7.5)]
            dl.append(MP(("Delivered " + nice_date(i["delivered_on"])) if i["delivered_on"] else "Not delivered yet", size=7,
                         color=colors.HexColor("#047857") if i["delivered_on"] else colors.HexColor("#b45309")))
            inv = [MP(f"#{i['number']}", size=8, bold=True), MP(nice_date(i["date"]), size=7, color=GREY)]
            data.append([str(n), btxt, inv, dl] + ([fmt(i["subtotal"]), fmt(i["tax"])] if taxed else []) + [fmt(i["total"])])
    tot = ["", "Total", "", ""] + ([fmt(t["subtotal"]), fmt(t["tax"])] if taxed else []) + [f"{cur} {fmt(t['total'])}"]
    extra = []
    if t["paid"] > 0:
        extra = [["", "Paid", "", ""] + (["", ""] if taxed else []) + [fmt(t["paid"])],
                 ["", "Balance due", "", ""] + (["", ""] if taxed else []) + [f"{cur} {fmt(t['open'])}"]]
    widths = ([8 * mm, 58 * mm, 22 * mm, 38 * mm, 18 * mm, 14 * mm, 22 * mm] if taxed
              else [8 * mm, 70 * mm, 24 * mm, 48 * mm, 30 * mm])
    right = {4, 5, 6} if taxed else {4}
    story.append(_mgrid(s, data + [tot] + extra, widths, right, 1 + len(extra)))
    story += [Spacer(1, 3 * mm), MP(f"In words: {cur} {_words(t['total'] // 100)} only", size=8, italic=True, color=GREY)]
    if b["notes"]:
        story += [Spacer(1, 2 * mm), MP(b["notes"], size=8, color=GREY)]
    story += [Spacer(1, 10 * mm), _signatures(["Prepared by", "Checked by", "Received by (head office)"])]
    # item summary: the same item across branches added together
    summ = {}
    for r in rows:
        for i in r["invoices"]:
            for l in lines.get(i["id"], []):
                if l["kind"] != "item":
                    continue
                k = (l["code"] or "", l["description"] or "", l["rate"], l["unit"] or "")
                a = summ.setdefault(k, {"qty": 0.0, "amount": 0, "branches": set(), "l": l})
                a["qty"] += l["qty"] or 0
                a["amount"] += l["amount"] or 0
                a["branches"].add(i["id"])
    if summ:
        story += [PageBreak(), _header(s, "ITEM SUMMARY", [("PO no.", b["po_no"]), ("Branches", str(t["billed_branches"] or t["count"]))]),
                  Spacer(1, 5 * mm), MP("All branches together", size=7, bold=True, color=GREY), Spacer(1, 1.5 * mm)]
        d2 = [["#", "Item code", "Description", "Branches", "Qty", "U/M", "Price", "Amount"]]
        for n, (k, a) in enumerate(sorted(summ.items(), key=lambda kv: (kv[0][0], kv[0][1])), 1):
            d2.append([str(n), k[0], k[1], str(len(a["branches"])), f"{a['qty']:g}", k[3], price_text(a["l"]), fmt(a["amount"])])
        d2.append(["", "", "Total before tax", "", f"{sum(a['qty'] for a in summ.values()):g}", "", "",
                   fmt(sum(a["amount"] for a in summ.values()))])
        story.append(_mgrid(s, d2, [8 * mm, 24 * mm, 66 * mm, 16 * mm, 16 * mm, 14 * mm, 16 * mm, 20 * mm], {3, 4, 6, 7}, 1))
    return _build(path, f"Combined invoice PO {b['po_no']}", story, s)


def _party_cards(s, label, party, right_title, right_amount, right_sub):
    ac = _accent(s)
    phone = party["whatsapp"] or party["phone"] or ""
    to = [MP(label, size=6.5, bold=True, color=ac), Spacer(1, 2), MP(party["name"], size=11, bold=True)]
    if party["address"]:
        to.append(MP(party["address"], size=8, color=GREY))
    if phone:
        to.append(MP(phone, size=8, color=GREY))
    box = [MP(right_title, size=6.5, bold=True, color=colors.white), Spacer(1, 3),
           MP(right_amount, size=16, bold=True, color=colors.white), Spacer(1, 3), MP(right_sub, size=7.5, color=colors.HexColor("#e0e7ff"))]
    t = Table([[_card(to, 104 * mm), "", _card(box, 70 * mm, ac)]], colWidths=[106 * mm, 4 * mm, 70 * mm])
    t.setStyle(TableStyle([("LEFTPADDING", (0, 0), (-1, -1), 0), ("RIGHTPADDING", (0, 0), (-1, -1), 0), ("VALIGN", (0, 0), (-1, -1), "TOP")]))
    return t


def supplier_statement(path, s, sup, st, unpaid=None):
    """Supplier account statement: bills, payments and what we owe (or 'unpaid bills only')."""
    cur = s.get("currency", "Rs")
    owe = st["closing"]
    title_amt = f"{cur} {fmt(abs(owe))}"
    period = "Unpaid bills" if unpaid is not None else f"{nice_date(st['start'])} to {nice_date(st['end'])}"
    story = [_header(s, "SUPPLIER STATEMENT", [("Date", nice_date(st["end"])), ("Period", period), ("Terms", f"{sup['terms_days']} days")]),
             Spacer(1, 5 * mm),
             _party_cards(s, "SUPPLIER", sup, "BALANCE WE OWE" if owe >= 0 else "ADVANCE PAID TO SUPPLIER", title_amt,
                          f"as of {nice_date(st['end'])}"), Spacer(1, 5 * mm)]
    if unpaid is not None:
        rows = [["Bill #", "Date", "Their bill no.", "Due", "Bill amount", "Unpaid"]]
        for b in unpaid["bills"]:
            rows.append([str(b["b"]["number"]), nice_date(b["b"]["date"]), b["b"]["bill_no"] or "", nice_date(b["b"]["due_date"]),
                         fmt(b["b"]["total"]), fmt(b["open"])])
        if unpaid["opening"]:
            rows.append(["", "", "Opening balance", "", "", fmt(unpaid["opening"])])
        if unpaid["advance"]:
            rows.append(["", "", "Advance paid", "", "", "-" + fmt(unpaid["advance"])])
        rows.append(["", "", "Total unpaid", "", "", f"{cur} {fmt(owe)}"])
        story.append(_mgrid(s, rows, [20 * mm, 26 * mm, 40 * mm, 26 * mm, 32 * mm, 36 * mm], {4, 5}, 1))
    else:
        rows = [["Date", "Transaction", "Bill", "Paid", "Balance"],
                [nice_date(st["start"]), MP("Balance brought forward", size=8, italic=True, color=GREY), "", "", fmt(st["brought_forward"])]]
        for l in st["lines"]:
            if l["type"] == "Bill":
                txt = f"Bill #{l['ref']}" + (f". Due {nice_date(l['due'])}" if l.get("due") else "")
            elif l["type"] == "Payment":
                txt = f"Payment #{l['ref']} · {l.get('method') or ''} {l.get('reference') or ''}".strip()
            else:
                txt = l["type"]
            rows.append([nice_date(l["date"]), txt, fmt(l["debit"]) if l["debit"] else "", fmt(l["credit"]) if l["credit"] else "",
                         fmt(l["balance"])])
        rows.append(["", "Closing balance", fmt(st["billed"]), fmt(st["paid"]), f"{cur} {fmt(owe)}"])
        story.append(_mgrid(s, rows, [24 * mm, 80 * mm, 25 * mm, 25 * mm, 26 * mm], {2, 3, 4}, 1))
    story += [Spacer(1, 6 * mm), MP("Please check this statement against your records and let us know of any difference.", size=7.5, color=GREY),
              Spacer(1, 12 * mm), _signatures(["Prepared by", "Checked by", "Supplier"])]
    return _build(path, f"Supplier statement {sup['name']}", story, s)


def purchase_bill(path, s, b, lines, sup, open_amt):
    """Our record of a supplier's bill (purchase bill)."""
    from .lines import qty_text
    cur = s.get("currency", "Rs")
    info = [("Bill #", str(b["number"])), ("Date", nice_date(b["date"])), ("Due date", nice_date(b["due_date"]))]
    if b["bill_no"]:
        info.append(("Their bill no.", b["bill_no"]))
    story = [_header(s, ("VOID " if b["void"] else "") + "PURCHASE BILL", info), Spacer(1, 5 * mm),
             _party_cards(s, "SUPPLIER", sup, "BILL TOTAL", f"{cur} {fmt(b['total'])}",
                          ("Fully paid" if open_amt <= 0 else f"Unpaid {cur} {fmt(open_amt)}")), Spacer(1, 5 * mm)]
    rows = [["#", "QTY", "U/M", "ITEM CODE", "DESCRIPTION", "COST EACH", "AMOUNT"]]
    for n, l in enumerate(lines, 1):
        rows.append([str(n), qty_text(l), l["unit"] or "", l["code"] or "", MP(l["description"] or "", size=8), fmt(l["rate"]), fmt(l["amount"])])
    tot = []
    if b["tax"]:
        tot.append(["", "", "", "", "Sub total", "", fmt(b["subtotal"])])
        tot.append(["", "", "", "", f"Tax {b['tax_rate']:g}%", "", fmt(b["tax"])])
    tot.append(["", "", "", "", "TOTAL", "", f"{cur} {fmt(b['total'])}"])
    story.append(_mgrid(s, rows + tot, [8 * mm, 16 * mm, 14 * mm, 26 * mm, 70 * mm, 22 * mm, 24 * mm], {1, 5, 6}, len(tot)))
    story += [Spacer(1, 3 * mm), MP(f"In words: {cur} {_words(b['total'] // 100)} only", size=8, italic=True, color=GREY)]
    if b["notes"]:
        story += [Spacer(1, 2 * mm), MP(b["notes"], size=8, color=GREY)]
    story += [Spacer(1, 14 * mm), _signatures(["Entered by", "Checked by", "Approved by"])]
    return _build(path, f"Purchase bill {b['number']}", story, s)


def supplier_payment_advice(path, s, y, sup, balance_after, open_bills):
    """Sent to the supplier after we pay: amount, method / cheque and what we still owe."""
    cur = s.get("currency", "Rs")
    story = [_header(s, ("VOID " if y["void"] else "") + "PAYMENT ADVICE", [("Payment #", str(y["number"])), ("Date", nice_date(y["date"]))]),
             Spacer(1, 5 * mm),
             _party_cards(s, "PAID TO", sup, "AMOUNT PAID", f"{cur} {fmt(y['amount'])}", f"{y['method']} {y['reference'] or ''}".strip()),
             Spacer(1, 4 * mm), MP(f"In words: {cur} {_words(y['amount'] // 100)} only", size=8, italic=True, color=GREY), Spacer(1, 5 * mm)]
    rows = [["Payment", "Amount"], ["Paid now", f"{cur} {fmt(y['amount'])}"],
            ["Balance we still owe you after this payment" if balance_after >= 0 else "Advance with you after this payment",
             f"{cur} {fmt(abs(balance_after))}"]]
    story.append(_mgrid(s, rows, [130 * mm, 50 * mm], {1}, 1))
    if open_bills:
        story += [Spacer(1, 5 * mm), MP("BILLS STILL UNPAID", size=7, bold=True, color=GREY), Spacer(1, 1.5 * mm)]
        r2 = [["Bill #", "Date", "Their bill no.", "Unpaid"]] + [[str(b["b"]["number"]), nice_date(b["b"]["date"]), b["b"]["bill_no"] or "",
                                                                  fmt(b["open"])] for b in open_bills[:25]]
        story.append(_mgrid(s, r2, [30 * mm, 40 * mm, 70 * mm, 40 * mm], {3}))
    if y["notes"]:
        story += [Spacer(1, 3 * mm), MP(y["notes"], size=8, color=GREY)]
    story += [Spacer(1, 14 * mm), _signatures(["Paid by", "Approved by", "Received by (supplier)"])]
    return _build(path, f"Payment advice {y['number']}", story, s)
