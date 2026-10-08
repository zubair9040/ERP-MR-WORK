import json
import os

from erp.db import commit, set_setting
from erp import notify


class _Resp:
    def __init__(self, data):
        self._d, self.status_code, self.text = data, 200, "ok"

    def json(self):
        return self._d


def _live(app, send_as):
    with app.app_context():
        for k, v in (("wa_dry_run", "0"), ("wa_phone_number_id", "123"), ("wa_access_token", "tok"), ("wa_send_as", send_as)):
            set_setting(k, v)
        commit()


def _fake_pdf(tmp_path, pages=1):
    from reportlab.pdfgen import canvas
    p = str(tmp_path / "doc.pdf")
    c = canvas.Canvas(p)
    for n in range(pages):
        c.drawString(100, 700, f"Invoice page {n + 1}")
        c.showPage()
    c.save()
    return p


def test_one_page_pdf_becomes_a_jpeg(tmp_path):
    jpg = notify.pdf_to_jpeg(_fake_pdf(tmp_path))
    assert jpg and open(jpg, "rb").read(3) == b"\xff\xd8\xff"
    assert notify.pdf_to_jpeg(_fake_pdf(tmp_path, pages=2)) is None  # longer documents stay PDF


def test_image_mode_sends_picture_with_image_template_and_pdf_mode_unchanged(app, tmp_path, monkeypatch):
    sent = []

    def fake_post(url, headers=None, json=None, data=None, files=None, timeout=None):
        sent.append({"url": url, "json": json, "data": data})
        return _Resp({"id": "MEDIA1"} if url.endswith("/media") else {"messages": [{"id": "wamid.1"}]})

    monkeypatch.setattr(notify.requests, "post", fake_post)
    pdf = _fake_pdf(tmp_path)
    with app.app_context():
        _live(app, "image")
        assert notify._send_document("923001112233", "invoice_notification", pdf, ["A", "1", "Rs 5", "01-Jan"]) == "wamid.1"
        assert sent[0]["data"]["type"] == "image/jpeg"
        msg = sent[1]["json"]
        assert msg["template"]["name"] == "invoice_notification_img"
        assert msg["template"]["components"][0]["parameters"][0]["type"] == "image"
    sent.clear()
    with app.app_context():  # a fresh request, so the settings are read again
        _live(app, "pdf")
    with app.app_context():
        notify._send_document("923001112233", "invoice_notification", pdf, ["A", "1", "Rs 5", "01-Jan"])
        assert sent[0]["data"]["type"] == "application/pdf" and sent[1]["json"]["template"]["name"] == "invoice_notification"
        assert sent[1]["json"]["template"]["components"][0]["parameters"][0]["type"] == "document"
        set_setting("wa_dry_run", "1")
        commit()


def test_choice_on_the_spot_beats_the_setting_and_statements_stay_pdf(app, tmp_path, monkeypatch):
    sent = []

    def fake_post(url, headers=None, json=None, data=None, files=None, timeout=None):
        sent.append({"url": url, "json": json, "data": data})
        return _Resp({"id": "M1"} if url.endswith("/media") else {"messages": [{"id": "wamid.9"}]})

    monkeypatch.setattr(notify.requests, "post", fake_post)
    pdf = _fake_pdf(tmp_path)
    with app.app_context():
        _live(app, "pdf")
    with app.app_context():  # setting says PDF, but the person pressed "Send picture"
        notify._send_document("923001112233", "invoice_notification", pdf, ["a"], "image")
        assert sent[0]["data"]["type"] == "image/jpeg" and sent[1]["json"]["template"]["name"].endswith("_img")
    sent.clear()
    with app.app_context():
        _live(app, "image")
    with app.app_context():  # setting says picture, but the person pressed "Send PDF"
        notify._send_document("923001112233", "invoice_notification", pdf, ["a"], "pdf")
        assert sent[0]["data"]["type"] == "application/pdf"
    with app.app_context():
        set_setting("wa_dry_run", "1")
        commit()
