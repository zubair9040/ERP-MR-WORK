"""Draws a PDF from a print layout made in the drag-and-drop designer.

A layout is JSON: {"page": "A4", "elements": [...]} with positions in millimetres from the top-left corner.
Element types: text (with {placeholders}), image (logo / terms / stamp), items (the lines table), totals, box, line.
Elements above the items table repeat on every page; elements below it are printed on the last page only.
"""
import os
import re
from xml.sax.saxutils import escape

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_LEFT, TA_RIGHT
from reportlab.lib.pagesizes import A4, A5, landscape
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.lib.utils import ImageReader
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfgen import canvas
from reportlab.platypus import KeepInFrame, Paragraph, Table, TableStyle

HERE = os.path.dirname(__file__)
FONT_DIRS = [os.path.join(HERE, "static", "fonts")]
BUILTIN = {
    "Helvetica": ("Helvetica", "Helvetica-Bold", "Helvetica-Oblique", "Helvetica-BoldOblique"),
    "Times": ("Times-Roman", "Times-Bold", "Times-Italic", "Times-BoldItalic"),
    "Courier": ("Courier", "Courier-Bold", "Courier-Oblique", "Courier-BoldOblique"),
}
TTF = {  # family -> (regular, bold, italic, bold italic) file names; missing styles fall back to regular / bold
    "Poppins": ("Poppins-Regular.ttf", "Poppins-Bold.ttf", "Poppins-Italic.ttf", "Poppins-BoldItalic.ttf"),
    "DejaVu Sans": ("DejaVuSans.ttf", "DejaVuSans-Bold.ttf", None, None),
}
_registered = {}
PAGES = {"A4": A4, "A5": A5, "A4 landscape": landscape(A4)}


def add_font_dir(path):
    if path and os.path.isdir(path) and path not in FONT_DIRS:
        FONT_DIRS.append(path)


def _find(fname):
    for d in FONT_DIRS:
        p = os.path.join(d, fname)
        if os.path.exists(p):
            return p
    return None


def font_families():
    """All font families the designer can offer: built-in, bundled, and any .ttf dropped into data/fonts."""
    fams = list(BUILTIN) + [f for f, files in TTF.items() if _find(files[0])]
    for d in FONT_DIRS[1:]:
        for fn in sorted(os.listdir(d)):
            if fn.lower().endswith(".ttf"):
                fam = os.path.splitext(fn)[0]
                if not any(fam in (files[0] or "") for files in TTF.values()) and fam not in fams:
                    fams.append(fam)
    return fams


def font_name(family, bold=False, italic=False):
    idx = (2 if italic else 0) + (1 if bold else 0)
    if family in BUILTIN:
        return BUILTIN[family][idx]
    files = TTF.get(family)
    if not files:  # a user font: data/fonts/<family>.ttf (regular only)
        files = (family + ".ttf", None, None, None)
    order = [idx, idx & 1, 0]  # wanted style, then bold/regular, then regular
    for i in order:
        fn = files[i]
        if not fn:
            continue
        key = f"{family}#{i}"
        if key in _registered:
            return _registered[key]
        p = _find(fn)
        if p:
            name = re.sub(r"[^A-Za-z0-9]", "", family) + ["", "-Bold", "-Italic", "-BoldItalic"][i]
            try:
                pdfmetrics.registerFont(TTFont(name, p))
            except Exception:  # noqa: BLE001 - a broken font file just falls back
                continue
            _registered[key] = name
            return name
    return BUILTIN["Helvetica"][idx]


ACCENT = {"v": "#4f46e5"}


def hexcolor(v, default=None):
    if not v:
        return default
    if v == "accent":
        v = ACCENT["v"]
    try:
        return colors.HexColor(v)
    except (ValueError, TypeError):
        return default


PH = re.compile(r"\{([a-z0-9_]+)\}")


def fill(template, fields):
    return PH.sub(lambda m: str(fields.get(m.group(1), "") if fields.get(m.group(1)) is not None else ""), template or "")


def _style(st, size=None):
    st = st or {}
    sz = float(size or st.get("size") or 10)
    return ParagraphStyle(
        "x", fontName=font_name(st.get("font") or "Helvetica", st.get("bold"), st.get("italic")), fontSize=sz,
        leading=sz * float(st.get("line_height") or 1.22), textColor=hexcolor(st.get("color"), colors.black),
        alignment={"center": TA_CENTER, "right": TA_RIGHT}.get(st.get("align"), TA_LEFT))


def _para(text, st, size=None):
    t = escape(str(text or ""))
    if (st or {}).get("upper"):
        t = t.upper()
    return Paragraph(t.replace("\n", "<br/>"), _style(st, size))


class Renderer:
    def __init__(self, path, layout, data):
        self.layout = layout or {}
        self.data = data
        self.fields = dict(data.get("fields", {}))
        self.pw, self.ph = PAGES.get(self.layout.get("page") or "A4", A4)
        self.c = canvas.Canvas(path, pagesize=(self.pw, self.ph))
        self.c.setTitle(self.fields.get("title", "Document"))
        self.path = path
        ACCENT["v"] = data.get("accent") or "#4f46e5"

    # geometry helpers: layout uses mm from the top-left, reportlab uses points from the bottom-left
    def box(self, e):
        x, y, w, h = (float(e.get(k) or 0) * mm for k in ("x", "y", "w", "h"))
        return x, self.ph - y - h, w, h

    def frame(self, e):
        st = e.get("style") or {}
        x, y, w, h = self.box(e)
        bg, bw = hexcolor(st.get("bg")), float(st.get("border") or 0)
        if bg or bw:
            self.c.saveState()
            if bg:
                self.c.setFillColor(bg)
            if bw:
                self.c.setStrokeColor(hexcolor(st.get("border_color"), colors.black))
                self.c.setLineWidth(bw)
            r = float(st.get("radius") or 0) * mm
            self.c.roundRect(x, y, w, h, r, stroke=1 if bw else 0, fill=1 if bg else 0)
            self.c.restoreState()
        return x, y, w, h

    def draw_text(self, e):
        text = fill(e.get("text", ""), self.fields)
        if e.get("hide_empty") and not text.strip():
            return
        st = e.get("style") or {}
        x, y, w, h = self.frame(e)
        pad = float(st.get("pad") if st.get("pad") is not None else 1.2) * mm
        para = _para(text, st)
        kif = KeepInFrame(max(w - 2 * pad, 1), max(h - 2 * pad, 1), [para], mode="shrink")
        _, th = kif.wrapOn(self.c, max(w - 2 * pad, 1), max(h - 2 * pad, 1))
        va = st.get("valign") or "top"
        top = y + h - pad
        oy = top - th if va == "top" else (y + pad if va == "bottom" else y + (h - th) / 2)
        kif.drawOn(self.c, x + pad, oy)

    def draw_image(self, e):
        p = (self.data.get("images") or {}).get(e.get("src") or "logo")
        x, y, w, h = self.frame(e)
        if not p or not os.path.exists(p):
            return
        try:
            iw, ih = ImageReader(p).getSize()
        except Exception:  # noqa: BLE001
            return
        s = min(w / iw, h / ih)
        dw, dh = iw * s, ih * s
        al = (e.get("style") or {}).get("align") or "left"
        dx = x if al == "left" else (x + w - dw if al == "right" else x + (w - dw) / 2)
        self.c.drawImage(p, dx, y + (h - dh) / 2, dw, dh, mask="auto", preserveAspectRatio=True)

    def draw_shape(self, e):
        st = e.get("style") or {}
        if e["type"] == "line":
            x, y, w, h = self.box(e)
            self.c.saveState()
            self.c.setStrokeColor(hexcolor(st.get("color"), colors.black))
            self.c.setLineWidth(float(st.get("border") or 0.8))
            if w >= h:
                self.c.line(x, y + h / 2, x + w, y + h / 2)
            else:
                self.c.line(x + w / 2, y, x + w / 2, y + h)
            self.c.restoreState()
        else:
            self.frame(e)

    def _totals_table(self, e, w):
        st = e.get("style") or {}
        T = self.data.get("totals") or {}
        raw = []
        for r in e.get("rows") or []:
            if not r.get("show", True) or T.get(r["key"]) is None:
                continue
            raw.append((r["key"], fill(r.get("label") or r["key"], self.fields), T[r["key"]]))
        if not raw:
            return None
        hl = e.get("highlight")
        if hl == "last":
            hl = raw[-1][0]
        hc = e.get("hl_color") or "#ffffff"
        big = float(st.get("size") or 10) * 1.15
        rows = []
        for k, label, v in raw:
            if k == hl:
                rows.append([_para(label, {**st, "align": "left", "color": hc, "bold": True}, big),
                             _para(v, {**st, "align": "right", "color": hc, "bold": True}, big)])
            else:
                rows.append([_para(label, {**st, "align": "left"}), _para(v, {**st, "align": "right"})])
        t = Table(rows, colWidths=[w * 0.55, w * 0.45])
        ts = [("VALIGN", (0, 0), (-1, -1), "MIDDLE"), ("LEFTPADDING", (0, 0), (-1, -1), 4), ("RIGHTPADDING", (0, 0), (-1, -1), 4),
              ("TOPPADDING", (0, 0), (-1, -1), 2.5), ("BOTTOMPADDING", (0, 0), (-1, -1), 2.5)]
        if st.get("lines"):
            ts.append(("LINEBELOW", (0, 0), (-1, -2), 0.3, colors.HexColor("#cfd4dc")))
        keys = [k for k, _, _ in raw]
        if hl in keys:
            i = keys.index(hl)
            ts.append(("BACKGROUND", (0, i), (-1, i), hexcolor(e.get("hl_bg"), colors.HexColor("#1f4e79"))))
        t.setStyle(TableStyle(ts))
        return t

    def draw_kv(self, e):
        st = e.get("style") or {}
        x, y, w, h = self.frame(e)
        rows = []
        for r in e.get("rows") or []:
            v = fill(r.get("value", ""), self.fields).strip()
            if v:
                rows.append([_para(fill(r.get("label", ""), self.fields), {**st, "bold": False, "color": st.get("label_color") or "#64748b"}),
                             _para(v, {**st, "bold": st.get("value_bold", True), "align": "right"})])
        if not rows:
            return
        lw = float(st.get("label_w") or 42) / 100
        t = Table(rows, colWidths=[w * lw, w * (1 - lw)])
        t.setStyle(TableStyle([("LEFTPADDING", (0, 0), (-1, -1), 1), ("RIGHTPADDING", (0, 0), (-1, -1), 1),
                               ("TOPPADDING", (0, 0), (-1, -1), 0.8), ("BOTTOMPADDING", (0, 0), (-1, -1), 0.8),
                               ("VALIGN", (0, 0), (-1, -1), "TOP")]))
        _, th = t.wrapOn(self.c, w, h)
        if th > h:  # too many rows for the box: shrink to fit instead of spilling over
            from reportlab.platypus import KeepInFrame
            t = KeepInFrame(w, h, [t], mode="shrink")
            _, th = t.wrapOn(self.c, w, h)
        t.drawOn(self.c, x, y + h - th)

    def draw_totals(self, e):
        x, y, w, h = self.frame(e)
        t = self._totals_table(e, w)
        if t is None:
            return
        _, th = t.wrapOn(self.c, w, h)
        t.drawOn(self.c, x, y + h - th)

    # ---- items table ------------------------------------------------------------------------------
    def items_rows(self, e):
        cols = [c for c in (e.get("columns") or []) if c.get("show", True)]
        st = e.get("style") or {}
        tb = e.get("table") or {}
        hs = {**st, "bold": True, "color": tb.get("header_color") or "#ffffff", "align": "center"}
        head = [_para(c.get("label", ""), {**hs, "align": c.get("align") or "left"} if tb.get("header_align_cols") else hs) for c in cols]
        body, kinds = [], []
        for r in self.data.get("items") or []:
            kinds.append(r.get("_kind") or "item")
            row_st = {**st, "bold": st.get("bold") or r.get("_kind") in ("subtotal",)}
            body.append([_para(r.get(c["key"], ""), {**row_st, "align": c.get("align") or "left"}) for c in cols])
        return cols, head, body, kinds

    def items_table(self, e, head, body, kinds, cols, w, filler_to=None):
        st = e.get("style") or {}
        tb = e.get("table") or {}
        tot = sum(float(c.get("w") or 10) for c in cols) or 1
        widths = [w * float(c.get("w") or 10) / tot for c in cols]
        rows = [head] + body
        pad = float(tb.get("row_pad") if tb.get("row_pad") is not None else 1.6)
        ts = [("VALIGN", (0, 0), (-1, -1), "TOP"), ("TOPPADDING", (0, 0), (-1, -1), pad), ("BOTTOMPADDING", (0, 0), (-1, -1), pad),
              ("LEFTPADDING", (0, 0), (-1, -1), 3), ("RIGHTPADDING", (0, 0), (-1, -1), 3),
              ("BACKGROUND", (0, 0), (-1, 0), hexcolor(tb.get("header_bg"), colors.HexColor("#1f4e79"))),
              ("VALIGN", (0, 0), (-1, 0), "MIDDLE")]
        lc = hexcolor(tb.get("line_color"), colors.black)
        lw = float(tb.get("line_width") or 0.6)
        grid = tb.get("grid") or "vertical"
        if grid in ("all", "vertical", "box"):
            ts.append(("BOX", (0, 0), (-1, -1), lw, lc))
        if grid in ("all", "vertical"):
            ts.append(("LINEAFTER", (0, 0), (-2, -1), lw, lc))
        if grid in ("all", "horizontal"):
            ts.append(("LINEBELOW", (0, 0), (-1, -1), lw * 0.6, lc))
        if grid == "horizontal":
            ts.append(("LINEBELOW", (0, 0), (-1, 0), lw, lc))
        zebra = hexcolor(tb.get("zebra"))
        for i, k in enumerate(kinds, start=1):
            if k == "subtotal":
                ts.append(("BACKGROUND", (0, i), (-1, i), colors.HexColor("#eeeeee")))
            elif zebra and i % 2 == 0:
                ts.append(("BACKGROUND", (0, i), (-1, i), zebra))
        t = Table(rows, colWidths=widths, repeatRows=1)
        t.setStyle(TableStyle(ts))
        if filler_to:
            _, th = t.wrapOn(self.c, w, 10 ** 6)
            row_h = float(st.get("size") or 9) * 1.25 + 2 * pad
            n = int((filler_to - th) // row_h)
            if n > 0:
                rows += [[""] * len(cols) for _ in range(n)]
                t = Table(rows, colWidths=widths, repeatRows=1)
                t.setStyle(TableStyle(ts))
        return t

    # ---- pages -----------------------------------------------------------------------------------
    def draw_el(self, e):
        # optional elements: "show_if": "deliver_to" prints only when that field has a value, "hide_if" the opposite
        if e.get("show_if") and not str(self.fields.get(e["show_if"], "")).strip():
            return
        if e.get("hide_if") and str(self.fields.get(e["hide_if"], "")).strip():
            return
        t = e.get("type")
        if t == "text":
            self.draw_text(e)
        elif t == "image":
            self.draw_image(e)
        elif t == "totals":
            self.draw_totals(e)
        elif t == "kv":
            self.draw_kv(e)
        elif t in ("box", "line"):
            self.draw_shape(e)

    def render(self):
        els = [e for e in self.layout.get("elements") or [] if not e.get("hidden")]
        els.sort(key=lambda e: int(e.get("z") or 0))
        items = next((e for e in els if e.get("type") == "items"), None)
        if not items:
            self.fields["page"] = "1"
            for e in els:
                self.draw_el(e)
            self.c.showPage()
            self.c.save()
            return self.path
        iy = float(items.get("y") or 0)
        header = [e for e in els if e is not items and float(e.get("y") or 0) < iy]
        footer = [e for e in els if e is not items and float(e.get("y") or 0) >= iy]
        cols, head, body, kinds = self.items_rows(items)
        x, y, w, h = self.box(items)
        page = 1
        remaining, rkinds = body, kinds
        while True:
            self.fields["page"] = str(page)
            for e in header:
                self.draw_el(e)
            t = self.items_table(items, head, remaining, rkinds, cols, w)
            parts = t.split(w, h)
            if len(parts) <= 1:
                fill_on = (items.get("table") or {}).get("fill_rows", True)
                t = self.items_table(items, head, remaining, rkinds, cols, w, filler_to=h if fill_on else None)
                _, th = t.wrapOn(self.c, w, h)
                t.drawOn(self.c, x, y + h - th)
                for e in footer:
                    self.draw_el(e)
                break
            first = parts[0]
            _, th = first.wrapOn(self.c, w, h)
            first.drawOn(self.c, x, y + h - th)
            shown = len(first._cellvalues) - 1
            if shown <= 0:  # the table box is too small for even one row: print everything below and stop
                t.wrapOn(self.c, w, 10 ** 6)
                t.drawOn(self.c, x, y + h - t._height)
                break
            remaining, rkinds = remaining[shown:], rkinds[shown:]
            self.c.setFont("Helvetica-Oblique", 8)
            self.c.setFillColor(colors.grey)
            self.c.drawRightString(x + w, y - 4 * mm, "continued on next page…")
            self.c.showPage()
            page += 1
        self.c.showPage()
        self.c.save()
        return self.path


def render(path, layout, data):
    return Renderer(path, layout, data).render()
