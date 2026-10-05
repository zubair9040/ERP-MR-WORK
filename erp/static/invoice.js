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
      `<td><button type="button" class="del" title="Delete line" tabindex="-1">✕</button>` +
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
    tr.querySelector('.del').addEventListener('click', () => { tr.remove(); ensureBlank(); recalc(); });
    if (before) body.insertBefore(tr, before); else body.appendChild(tr);
    return tr;
  }

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
    let group = 0, prev = 0, total = 0;
    body.querySelectorAll('tr').forEach(tr => {
      const kind = tr.querySelector('[name=kind]').value;
      const priceTxt = tr.querySelector('[name=price]').value.trim();
      const qtyTxt = tr.querySelector('[name=qty]').value.trim();
      let amt = 0, show = true;
      tr.className = '';
      if (kind === 'subtotal') {
        amt = group; group = 0; tr.className = 'sub';
      } else if (priceTxt.endsWith('%')) {
        amt = Math.round(prev * num(priceTxt.slice(0, -1))) / 100;
        group += amt; total += amt; tr.className = 'disc';
      } else if (priceTxt) {
        amt = Math.round((qtyTxt ? num(qtyTxt) : 1) * num(priceTxt) * 100) / 100;
        group += amt; total += amt;
      } else {
        show = !!qtyTxt || !!tr.querySelector('[name=description]').value.trim();
      }
      tr.querySelector('.amt').textContent = (show && !rowEmpty(tr)) ? fmt(amt) : '';
      prev = amt;
    });
    const tax = Math.round(total * num(document.getElementById('taxrate').value)) / 100;
    document.getElementById('taxrow').style.display = tax ? '' : 'none';
    document.getElementById('t_tax').textContent = fmt(tax);
    document.getElementById('t_total').textContent = fmt(total + tax);
    document.getElementById('t_paid').textContent = fmt(inv.paid || 0);
    document.getElementById('t_bal').textContent = fmt(total + tax - (inv.paid || 0));
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
  window.addEventListener('beforeunload', e => { if (dirty && !submitting) { e.preventDefault(); e.returnValue = ''; } });

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
