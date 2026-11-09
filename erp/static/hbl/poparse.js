(function(){
"use strict";
// ---------------------------------------------------------------- PDF reading
  async function readPdf(buf) {
    var pdf = await pdfjsLib.getDocument({ data: buf }).promise;
    var pages = [];
    for (var p = 1; p <= pdf.numPages; p++) {
      var page = await pdf.getPage(p);
      var vp = page.getViewport({ scale: 1 });
      var tc = await page.getTextContent();
      var items = [];
      tc.items.forEach(function (i) {
        var s = (i.str || '').replace(/\s+/g, ' ').trim();
        if (!s) return;
        items.push({ s: s, x: i.transform[4], b: vp.height - i.transform[5] });
      });
      pages.push(items);
    }
    return pages;
  }

  function parsePo(pages) {
    var header = { po: '', date: '', status: '' };
    var rows = [];
    var p0 = pages[0] || [];
    p0.forEach(function (it) {
      if (!header.po && /^\d{5}-\d{3}$/.test(it.s)) header.po = it.s;
      if (!header.status && /^(APPROVED|OPEN|CLOSED|CANCELLED|CANCELED)$/i.test(it.s)) header.status = it.s.toUpperCase();
    });
    var dm = p0.filter(function (it) { return /^\d{1,2}-[A-Z]{3}-$/.test(it.s); })[0];
    if (dm) {
      var yr = p0.filter(function (it) { return /^\d{4}$/.test(it.s) && it.b > dm.b && it.b - dm.b < 30 && Math.abs(it.x - dm.x) < 40; })[0];
      header.date = dm.s + (yr ? yr.s : '');
    }
    var totals = null;

    pages.forEach(function (items, pi) {
      var comments = items.filter(function (i) { return /^Comments/.test(i.s) && i.x < 100; });
      var commentsB = comments.length ? Math.min.apply(null, comments.map(function (i) { return i.b; })) : null;
      var lo = pi === 0 ? 255 : 206;
      var hi = commentsB !== null ? commentsB - 4 : 744;
      var body = items.filter(function (i) { return i.b > lo && i.b < hi; });
      var anchors = body.filter(function (i) { return i.x > 900 && /^\d{6}$/.test(i.s); }).sort(function (a, b) { return a.b - b.b; });
      if (commentsB !== null) {
        var amts = items.filter(function (i) { return i.b >= commentsB && i.x > 700 && /^[\d,]+\.\d\d$/.test(i.s); }).sort(function (a, b) { return a.b - b.b; });
        if (amts.length >= 4) totals = {
          excl: num(amts[0].s), tax: num(amts[1].s), disc: num(amts[2].s), incl: num(amts[3].s)
        };
      }
      if (!anchors.length) return;
      var cur = anchors.map(function () { return []; });
      body.forEach(function (it) {
        var idx = -1;
        for (var k = 0; k < anchors.length; k++) { if (anchors[k].b <= it.b + 0.5) idx = k; }
        if (idx < 0) {
          if (rows.length && it.x > 70 && it.x < 250) rows[rows.length - 1].w.push(it);
          return;
        }
        cur[idx].push(it);
      });
      cur.forEach(function (w) { rows.push({ w: w }); });
    });

    function col(ws, lo, hi) {
      return ws.filter(function (w) { return w.x >= lo && w.x < hi; })
        .sort(function (a, b) { return (Math.round(a.b) - Math.round(b.b)) || (a.x - b.x); })
        .map(function (w) { return w.s; }).join(' ');
    }
    var out = rows.map(function (r) {
      var ws = r.w;
      var d = {
        line: ws.filter(function (w) { return w.x < 70; }).sort(function (a, b) { return a.b - b.b; }).map(function (w) { return w.s; }).join(''),
        loc: col(ws, 70, 188), person: col(ws, 188, 245), phone: col(ws, 245, 309), item: col(ws, 309, 372),
        desc: col(ws, 372, 477), need: col(ws, 477, 556), uom: col(ws, 556, 600), qty: col(ws, 600, 660),
        price: col(ws, 660, 720), tax: col(ws, 720, 790), net: col(ws, 790, 900), req: col(ws, 900, 5000)
      };
      d.person = d.person.replace('MUHAMMA D', 'MUHAMMAD').replace('MOHAMMA D', 'MOHAMMAD');
      return d;
    });
    if (totals) { header.excl = totals.excl; header.tax = totals.tax; header.incl = totals.incl; }
    return { header: header, rows: out };
  }

  function num(s) { return parseFloat(String(s).replace(/,/g, '')); }
  function r2(x) { return Math.round((x + Number.EPSILON) * 100) / 100; }

  function checkRows(header, rows) {
    var warn = [], tot = 0;
    rows.forEach(function (r) {
      var q = num(r.qty), p = num(r.price), n = num(r.net);
      if (isNaN(q) || isNaN(p) || isNaN(n)) { warn.push('Line ' + r.line + ': could not read quantity/price/net'); return; }
      tot += n;
      if (Math.abs(q * p - n) > 0.011) warn.push('Line ' + r.line + ': qty x price does not equal net price');
    });
    if (!rows.length) warn.push('No PO lines found in this PDF');
    if (header.excl != null && Math.abs(tot - header.excl) > 0.011)
      warn.push('Sum of lines ' + tot.toFixed(2) + ' does not match the PDF total ' + header.excl.toFixed(2));
    return { warn: warn, sum: tot };
  }

  
window.POPARSE={readPdf:readPdf,parsePo:parsePo,checkRows:checkRows};
})();
