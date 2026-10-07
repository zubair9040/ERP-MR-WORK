(function () {
  const items = JSON.parse(document.getElementById('itemdata').textContent);
  const grid = JSON.parse(document.getElementById('griddata').textContent);
  const inv = JSON.parse(document.getElementById('invdata').textContent);
  const byCode = {};
  items.forEach(i => { byCode[i.code.toUpperCase()] = i; });
  const body = document.querySelector('#grid tbody');
  const num = v => { const n = parseFloat(String(v == null ? '' : v).replace(/,/g, '')); return isNaN(n) ? 0 : n; };
  const fmt = n => n.toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 });
  const esc = s => String(s == null ? '' : s).replace(/[&<>"]/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]));
  const COLS = ['qty', 'unit', 'ctn_qty', 'code', 'description', 'price'];

  function addRow(d, before) {
    d = d || {};
    const tr = document.createElement('tr');
    tr.innerHTML =
      `<td><input name="qty" class="r" value="${esc(d.qty)}" inputmode="decimal"></td>` +
      `<td><input name="unit" value="${esc(d.unit)}"></td>` +
      `<td><input name="ctn_qty" value="${esc(d.ctn_qty)}"></td>` +
      `<td><input name="code" list="itemcodes" value="${esc(d.code)}" class="code"></td>` +
      `<td><input name="description" value="${esc(d.description)}"></td>` +
      `<td><input name="price" class="r" value="${esc(d.price)}" inputmode="decimal"></td>` +
      `<td class="amt"></td>` +
      `<td style="white-space:nowrap"><button type="button" class="del cp" title="Copy this line (then Paste line)" tabindex="-1" style="margin-right:2px">⧉</button><button type="button" class="del rm" title="Delete line" tabindex="-1">✕</button>` +
      `<input type="hidden" name="item_id" value="${esc(d.item_id)}"><input type="hidden" name="kind" value="${esc(d.kind || 'item')}"></td>`;
    const code = tr.querySelector('[name=code]');
    code.addEventListener('change', () => {
      code.value = code.value.trim().toUpperCase();
      const it = byCode[code.value];
      tr.querySelector('[name=item_id]').value = it ? it.id : '';
      tr.querySelector('[name=kind]').value = it ? it.kind : 'item';
      if (it) {
        tr.querySelector('[name=description]').value = it.desc;
        tr.querySelector('[name=price]').value = it.price;
        if (it.unit && !tr.querySelector('[name=unit]').value) tr.querySelector('[name=unit]').value = it.unit;
        if (it.kind === 'subtotal') { tr.querySelector('[name=qty]').value = ''; tr.querySelector('[name=price]').value = ''; }
      }
      recalc();
    });
    tr.querySelectorAll('input').forEach(i => {
      i.addEventListener('input', () => { recalc(); ensureBlank(); });
      i.addEventListener('keydown', e => {
        if (e.key === 'Enter') {
          e.preventDefault();
          if (i.name === 'code') i.dispatchEvent(new Event('change'));
          let next = tr.nextElementSibling;
          if (!next) next = addRow();
          next.querySelector(`[name=${i.name === 'code' ? 'qty' : i.name}]`).focus();
        } else if (e.key === 'ArrowDown' || e.key === 'ArrowUp') {
          if (i.getAttribute('list') && e.key === 'ArrowDown') return;
          const t = e.key === 'ArrowDown' ? tr.nextElementSibling : tr.previousElementSibling;
          if (t) { e.preventDefault(); t.querySelector(`[name=${i.name}]`).focus(); }
        }
      });
      i.addEventListener('focus', () => i.select && i.select());
    });
    tr.querySelector('.rm').addEventListener('click', () => { tr.remove(); ensureBlank(); recalc(); });
    tr.querySelector('.cp').addEventListener('click', () => copyRow(tr));
    if (before) body.insertBefore(tr, before); else body.appendChild(tr);
    return tr;
  }

  // copy / paste a line
  let clip = null;
  const rowData = tr => ({ qty: tr.querySelector('[name=qty]').value, unit: tr.querySelector('[name=unit]').value, ctn_qty: tr.querySelector('[name=ctn_qty]').value,
    code: tr.querySelector('[name=code]').value, description: tr.querySelector('[name=description]').value, price: tr.querySelector('[name=price]').value,
    item_id: tr.querySelector('[name=item_id]').value, kind: tr.querySelector('[name=kind]').value });
  function copyRow(tr) {
    clip = rowData(tr);
    const msg = document.getElementById('impmsg'); if (msg) msg.textContent = 'Line copied. Click "Paste line" (or Ctrl+Shift+V) to add it.';
    try { navigator.clipboard.writeText(Object.values(clip).slice(0, 6).join('\t')); } catch (e) {}
  }
  function pasteRow(after) {
    if (!clip) return;
    let tr = after;
    if (!tr) { const rows = [...body.querySelectorAll('tr')]; tr = rows.reverse().find(r => !rowEmpty(r)); }
    const nr = addRow(clip, tr ? tr.nextElementSibling : null);
    ensureBlank(); recalc(); dirty = true; nr.querySelector('[name=qty]').focus();
  }
  document.getElementById('pastebtn').addEventListener('click', () => pasteRow(null));
  document.addEventListener('keydown', e => {
    const tr = e.target.closest ? e.target.closest('#grid tbody tr') : null;
    if (e.ctrlKey && e.shiftKey && tr && e.key.toLowerCase() === 'c') { e.preventDefault(); copyRow(tr); }
    else if (e.ctrlKey && e.shiftKey && e.key.toLowerCase() === 'v') { e.preventDefault(); pasteRow(tr); }
    else if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === 'p') {  // Ctrl+P: save and print the invoice
      e.preventDefault();
      const f = document.getElementById('invform'), a = document.createElement('input'); a.type = 'hidden'; a.name = 'action'; a.value = 'save_print'; f.appendChild(a);
      f.requestSubmit ? f.requestSubmit() : f.submit();
    }
  });

  function rowEmpty(tr) {
    return ['qty', 'ctn_qty', 'code', 'description', 'price'].every(n => !tr.querySelector(`[name=${n}]`).value.trim());
  }

  function ensureBlank() {
    const rows = body.querySelectorAll('tr');
    let blanks = 0;
    for (let k = rows.length - 1; k >= 0 && rowEmpty(rows[k]); k--) blanks++;
    for (let k = blanks; k < 3; k++) addRow();
  }

  function recalc() {
    const trs = [...body.querySelectorAll('tr')];
    const res = ErpMoney.compute(trs.map(tr => ({
      kind: tr.querySelector('[name=kind]').value, qty: tr.querySelector('[name=qty]').value, price: tr.querySelector('[name=price]').value,
      hasText: !!tr.querySelector('[name=description]').value.trim() })), document.getElementById('taxrate').value);
    trs.forEach((tr, i) => {
      const r = res.rows[i];
      tr.className = r.cls;
      tr.querySelector('.amt').textContent = (r.show && !rowEmpty(tr)) ? fmt(r.amt / 100) : '';
    });
    const paid = Math.round((inv.paid || 0) * 100);
    document.getElementById('taxrow').style.display = res.tax ? '' : 'none';
    document.getElementById('t_tax').textContent = fmt(res.tax / 100);
    document.getElementById('t_total').textContent = fmt(res.grand / 100);
    document.getElementById('t_paid').textContent = fmt(paid / 100);
    document.getElementById('t_bal').textContent = fmt((res.grand - paid) / 100);
  }

  grid.forEach(r => addRow(r));
  ensureBlank();
  document.getElementById('taxrate').addEventListener('input', recalc);
  recalc();

  // Don't let Enter in header fields submit the form by accident.
  document.querySelectorAll('#invform .qb-fields input, #invform .qb-row2 input, #invform .qb-notes input').forEach(i =>
    i.addEventListener('keydown', e => { if (e.key === 'Enter') e.preventDefault(); }));

  // Warn before leaving with unsaved changes.
  let dirty = false, submitting = false;
  document.getElementById('invform').addEventListener('input', () => { dirty = true; });
  document.getElementById('invform').addEventListener('submit', () => { submitting = true; });
  window.addEventListener('beforeunload', e => { if (dirty && !submitting && !window.__escLeaving) { e.preventDefault(); e.returnValue = ''; } });

  // Import lines from Excel / CSV
  const imp = document.getElementById('impfile');
  if (imp) imp.addEventListener('change', () => {
    if (!imp.files.length) return;
    const msg = document.getElementById('impmsg');
    const fd = new FormData();
    fd.append('file', imp.files[0]);
    msg.textContent = 'Reading file…';
    fetch('/invoices/import-lines', { method: 'POST', body: fd,
      headers: { 'X-CSRF': document.querySelector('#invform [name=_csrf]').value } })
      .then(r => r.json().then(j => ({ ok: r.ok, j })))
      .then(({ ok, j }) => {
        imp.value = '';
        if (!ok) { msg.textContent = j.error || 'Could not read the file.'; return; }
        [...body.querySelectorAll('tr')].reverse().some(tr => { if (rowEmpty(tr)) { tr.remove(); return false; } return true; });
        j.rows.forEach(r => addRow(r));
        ensureBlank(); recalc(); dirty = true;
        msg.textContent = `${j.rows.length} lines added.` + (j.unknown.length ? ` Not in item list: ${j.unknown.join(', ')}` : '') + ' Check them, then Save.';
      })
      .catch(() => { msg.textContent = 'Could not read the file.'; });
  });

  // Customer panel
  const cust = document.getElementById('customer');
  const setText = (id, t) => { document.getElementById(id).textContent = t; };
  function loadCustomer() {
    if (!cust.value) return;
    fetch('/api/customer/' + cust.value).then(r => r.json()).then(c => {
      setText('s_name', c.name);
      setText('s_bal', fmt(num(c.balance)));
      setText('s_limit', num(c.credit_limit) ? fmt(num(c.credit_limit)) : 'none');
      setText('s_terms', c.terms_days + ' days');
      setText('s_wa', c.whatsapp || 'no number');
      document.getElementById('billto').value = [c.name, c.address, c.phone].filter(Boolean).join('\n');
      const wp = document.getElementById('waphone'); if (wp) wp.value = c.whatsapp || '';
      const open = document.getElementById('s_open');
      open.innerHTML = c.open_invoices.length ? c.open_invoices.map(i =>
        `<tr><td>${i.date}</td><td><a href="/invoices/${i.id}">#${i.number}</a></td><td class="n ${i.overdue ? 'red' : ''}">${fmt(num(i.open))}</td></tr>`).join('')
        : '<tr><td class="muted">None</td></tr>';
      document.getElementById('s_recent').innerHTML = c.recent.map(r =>
        `<tr><td>${r.date}</td><td><a href="${r.url}">${r.type}</a></td><td class="n ${r.type === 'Invoice' ? 'red' : ''}">${fmt(num(r.amount))}</td></tr>`).join('')
        || '<tr><td class="muted">None</td></tr>';
      document.getElementById('s_links').innerHTML =
        `<a href="/customers/${c.id}">Customer account &amp; statement →</a><br><a href="/payments/new?customer_id=${c.id}">Receive payment →</a>`;
      const co = c.company, box = document.getElementById('invco');
      if (co) {
        // non-GST firm: PO no., ship-to, courier, tracking and delivery address belong on the delivery challan, so tuck them away
        const dcf = document.getElementById('dcfields'), dcd = document.getElementById('dcdetails');
        if (dcf && dcd) {
          if (!co.gst) { document.getElementById('dcslot-dc').appendChild(dcf); dcd.style.display = ''; }
          else { document.getElementById('dcslot-inline').appendChild(dcf); dcd.style.display = 'none'; }
        }
        if (box) { box.textContent = co.name + ' · ' + (co.gst ? 'GST' : 'non-GST'); box.style.setProperty('--c', co.color); }
        const tr = document.getElementById('taxrate');
        if (!co.gst) { tr.value = '0'; tr.readOnly = true; tr.title = co.name + ' is not GST registered'; }
        else { tr.readOnly = false; if (!inv.id && (tr.value === '' || tr.value === '0')) tr.value = co.tax || 0; }
        const numF = document.querySelector('#invform [name=number]');
        if (!inv.id && numF && !numF.dataset.touched) numF.value = co.next_invoice;
        recalc();
      }
      const rep = document.getElementById('rep');
      if (rep && !rep.value && c.rep_id) rep.value = c.rep_id;
      const br = document.getElementById('branch');
      if (br) {
        const want = br.value || br.dataset.sel;
        br.innerHTML = '<option value="">— head office / no branch —</option>' + (c.branches || []).map(b =>
          `<option value="${b.id}">${(b.code ? b.code + ' · ' : '') + b.name}</option>`).join('');
        if (want && (c.branches || []).some(b => String(b.id) === String(want))) br.value = want;
        br.closest('label').style.display = (c.branches || []).length ? '' : 'none';
        br.dataset.sel = '';
        br.onchange = () => {  // picking a branch fills "Deliver to" (still editable)
          const b = (c.branches || []).find(x => String(x.id) === br.value), dl = document.getElementById('deliver_to');
          if (dl) dl.value = b ? [b.name, b.address, b.phone].filter(Boolean).join('\n') : '';
        };
        const dl = document.getElementById('deliver_to');
        if (dl && !dl.value && br.value) br.onchange();
      }
    }).catch(() => {});
  }
  cust.addEventListener('change', loadCustomer);
  const numField = document.querySelector('#invform [name=number]');
  if (numField) numField.addEventListener('input', () => { numField.dataset.touched = '1'; });
  loadCustomer();
  if (!cust.value) cust.focus();
})();
