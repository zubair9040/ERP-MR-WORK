(function () {
  const cfg = JSON.parse(document.getElementById('pdcfg').textContent);
  const page = document.getElementById('page');
  const props = document.getElementById('props');
  let layout = JSON.parse(JSON.stringify(cfg.layout));
  let S = 3.4;               // pixels per millimetre
  let sel = null;            // selected element id
  let dirty = false;
  const history = [];
  const PAGE = { 'A4': [210, 297], 'A5': [148, 210], 'A4 landscape': [297, 210] };
  const FONTCSS = { 'Helvetica': 'Helvetica, Arial, sans-serif', 'Times': '"Times New Roman", Times, serif', 'Courier': '"Courier New", monospace' };
  const esc = s => String(s == null ? '' : s).replace(/[&<>"]/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]));
  const fill = t => String(t || '').replace(/\{([a-z0-9_]+)\}/g, (m, k) => cfg.sample.fields[k] == null ? '' : cfg.sample.fields[k]);
  const byId = id => layout.elements.find(e => e.id === id);
  const uid = p => p + Math.random().toString(36).slice(2, 7);
  const r1 = v => Math.round(v * 10) / 10;
  const C = (v, d) => (!v ? d : (v === 'accent' ? cfg.accent : v));

  function snapshot() { history.push(JSON.stringify(layout)); if (history.length > 60) history.shift(); dirty = true; status(); }
  function status() {
    const st = document.getElementById('pdStatus');
    const labels = { on: ['This layout is in use', 'on'], off: ['Saved but not in use (standard print is used)', 'off'],
      inherited: ['Using the "All companies" layout', 'on'], builtin: ['Default design in use. Save to use your changes', 'off'] };
    const [t, c] = dirty ? ['Unsaved changes', 'warn'] : labels[cfg.status] || labels.builtin;
    st.textContent = t; st.className = 'pd-status ' + c;
  }

  // ---------- drawing the page ----------
  function styleCss(st, isText) {
    st = st || {};
    const pt = (st.size || 10) * 0.3528 * S;
    let css = `font-family:${FONTCSS[st.font] || `"${st.font || 'Helvetica'}", Arial, sans-serif`};font-size:${pt}px;` +
      `font-weight:${st.bold ? 700 : 400};font-style:${st.italic ? 'italic' : 'normal'};color:${C(st.color, '#000')};` +
      `text-align:${st.align || 'left'};line-height:${st.line_height || 1.22};`;
    if (st.upper) css += 'text-transform:uppercase;';
    if (st.bg) css += `background:${C(st.bg)};`;
    if (st.border) css += `border:${Math.max(st.border * 0.3528 * S, 1)}px solid ${C(st.border_color, '#000')};`;
    if (st.radius) css += `border-radius:${st.radius * S}px;`;
    if (isText) {
      const pad = (st.pad == null ? 1.2 : st.pad) * S;
      css += `padding:${pad}px;display:flex;flex-direction:column;justify-content:${{ middle: 'center', bottom: 'flex-end' }[st.valign] || 'flex-start'};`;
    }
    return css;
  }

  function itemsHtml(e) {
    const st = e.style || {}, tb = e.table || {};
    const cols = (e.columns || []).filter(c => c.show !== false);
    const tot = cols.reduce((a, c) => a + (+c.w || 10), 0) || 1;
    const pt = (st.size || 9) * 0.3528 * S, lc = C(tb.line_color, '#000');
    const grid = tb.grid || 'vertical';
    const vline = (grid === 'all' || grid === 'vertical') ? `border-right:1px solid ${lc};` : '';
    const hline = (grid === 'all' || grid === 'horizontal') ? `border-bottom:1px solid ${lc};` : '';
    const pad = `${(tb.row_pad == null ? 1.6 : tb.row_pad) * 0.3528 * S + 1}px 3px`;
    let h = `<table style="width:100%;border-collapse:collapse;font-size:${pt}px;font-family:${FONTCSS[st.font] || `"${st.font}",Arial`};` +
      `font-weight:${st.bold ? 700 : 400};${grid !== 'none' && grid !== 'horizontal' ? `border:1px solid ${lc};` : ''}"><tr>`;
    cols.forEach(c => h += `<th style="width:${100 * (+c.w || 10) / tot}%;background:${C(tb.header_bg, '#1f4e79')};color:${C(tb.header_color, '#fff')};` +
      `padding:${pad};${vline}border-bottom:1px solid ${lc};font-weight:700;text-align:${tb.header_align_cols ? (c.align || 'left') : 'center'}">${esc(c.label)}</th>`);
    h += '</tr>';
    const rows = cfg.sample.items.length ? cfg.sample.items.slice(0, 12) : [{}, {}, {}];
    rows.forEach((r, i) => {
      const bg = r._kind === 'subtotal' ? 'background:#eee;' : (tb.zebra && i % 2 ? `background:${C(tb.zebra)};` : '');
      h += '<tr>' + cols.map(c => `<td style="padding:${pad};${vline}${hline}${bg}text-align:${c.align || 'left'};vertical-align:top">${esc(r[c.key] || '')}</td>`).join('') + '</tr>';
    });
    return h + '</table>';
  }

  function totalsHtml(e) {
    const st = e.style || {};
    const T = cfg.sample.totals || {};
    let h = `<table style="width:100%;border-collapse:collapse">`;
    (e.rows || []).forEach(r => {
      if (r.show === false || T[r.key] == null) return;
      const shown = (e.rows || []).filter(x => x.show !== false && T[x.key] != null);
      const hl = r.key === e.highlight || (e.highlight === 'last' && shown.length && shown[shown.length - 1].key === r.key);
      const s = hl ? `background:${C(e.hl_bg, '#1f4e79')};color:${C(e.hl_color, '#fff')};font-weight:700;font-size:1.15em` : (st.lines ? 'border-bottom:1px solid #d5d9e0' : '');
      h += `<tr><td style="padding:2px 4px;${s}">${esc(fill(r.label))}</td><td style="padding:2px 4px;text-align:right;${s}">${esc(T[r.key])}</td></tr>`;
    });
    return h + '</table>';
  }

  function draw() {
    const [pw, ph] = PAGE[layout.page || 'A4'];
    page.style.width = pw * S + 'px'; page.style.height = ph * S + 'px';
    page.style.backgroundSize = `${5 * S}px ${5 * S}px`;
    page.innerHTML = '';
    const items = layout.elements.find(e => e.type === 'items');
    if (items) {
      const ln = document.createElement('div');
      ln.className = 'pd-zone'; ln.style.top = items.y * S + 'px';
      ln.title = 'Above this line: repeats on every page'; page.appendChild(ln);
    }
    [...layout.elements].sort((a, b) => (a.z || 0) - (b.z || 0)).forEach(e => {
      const d = document.createElement('div');
      d.className = 'pd-el t-' + e.type + (e.id === sel ? ' sel' : '') + (e.hidden ? ' hid' : '');
      d.dataset.id = e.id;
      d.style.cssText = `left:${e.x * S}px;top:${e.y * S}px;width:${e.w * S}px;height:${e.h * S}px;`;
      const st = e.style || {};
      if (e.type === 'text') {
        let t = fill(e.text);
        const empty = !t.trim();
        d.style.cssText += styleCss(st, true);
        d.innerHTML = `<div class="pd-txt">${esc(empty ? e.text : t).replace(/\n/g, '<br>')}</div>`;
        if (empty) d.classList.add('ghost');
      } else if (e.type === 'image') {
        d.style.cssText += styleCss(st);
        d.style.justifyContent = { left: 'flex-start', right: 'flex-end' }[st.align] || 'center';
        d.innerHTML = cfg.images[e.src] ? `<img src="/print-designer/image/${e.src}?co=${cfg.co}" alt="">` :
          `<span class="pd-ph">${e.src === 'terms' ? 'Terms picture' : 'Logo'} (add it in ${e.src === 'terms' ? 'Settings' : 'Companies'})</span>`;
      } else if (e.type === 'items') {
        d.style.cssText += 'overflow:hidden;background:#fff;';
        d.innerHTML = itemsHtml(e);
      } else if (e.type === 'totals') {
        d.style.cssText += styleCss(st);
        d.innerHTML = totalsHtml(e);
      } else if (e.type === 'kv') {
        d.style.cssText += styleCss(st);
        const lw = st.label_w || 42;
        d.innerHTML = '<table style="width:100%;border-collapse:collapse">' + (e.rows || []).map(r => {
          const v = fill(r.value).trim();
          return v ? `<tr><td style="width:${lw}%;color:${C(st.label_color, '#64748b')};font-weight:400;padding:0 1px">${esc(fill(r.label))}</td>` +
            `<td style="text-align:right;font-weight:${st.value_bold === false ? 400 : 700};padding:0 1px">${esc(v)}</td></tr>` : '';
        }).join('') + '</table>';
      } else if (e.type === 'box') {
        d.style.cssText += styleCss(st);
      } else if (e.type === 'line') {
        const horiz = e.w >= e.h;
        d.innerHTML = `<div style="position:absolute;${horiz ? 'left:0;right:0;top:50%' : 'top:0;bottom:0;left:50%'};` +
          `${horiz ? 'border-top' : 'border-left'}:${Math.max((st.border || 0.8) * 0.3528 * S, 1)}px solid ${C(st.color, '#000')}"></div>`;
      }
      const hdl = document.createElement('span'); hdl.className = 'pd-h'; d.appendChild(hdl);
      page.appendChild(d);
      if (e.type === 'text') {  // shrink text that doesn't fit, like the PDF does
        const t = d.querySelector('.pd-txt');
        let fs = parseFloat(d.style.fontSize), n = 0;
        while (n++ < 14 && (t.scrollHeight > d.clientHeight + 1 || t.scrollWidth > d.clientWidth + 1) && fs > 4) {
          fs *= 0.92; d.style.fontSize = fs + 'px';
        }
      }
    });
  }

  // ---------- mouse: select, move, resize ----------
  let drag = null;
  page.addEventListener('pointerdown', ev => {
    const el = ev.target.closest('.pd-el');
    if (!el) { select(null); return; }
    const e = byId(el.dataset.id);
    select(e.id);
    drag = { e, mode: ev.target.classList.contains('pd-h') ? 'size' : 'move', sx: ev.clientX, sy: ev.clientY,
             x: e.x, y: e.y, w: e.w, h: e.h, before: JSON.stringify(layout), moved: false };
    page.setPointerCapture(ev.pointerId);
    ev.preventDefault();
  });
  page.addEventListener('pointermove', ev => {
    if (!drag) return;
    const dx = (ev.clientX - drag.sx) / S, dy = (ev.clientY - drag.sy) / S;
    if (Math.abs(dx) + Math.abs(dy) > 0.2) drag.moved = true;
    const snap = document.getElementById('showGrid').checked ? v => Math.round(v * 2) / 2 : r1;
    if (drag.mode === 'move') { drag.e.x = snap(drag.x + dx); drag.e.y = snap(drag.y + dy); }
    else { drag.e.w = Math.max(2, snap(drag.w + dx)); drag.e.h = Math.max(1, snap(drag.h + dy)); }
    const d = page.querySelector(`[data-id="${drag.e.id}"]`);
    if (drag.e.type === 'items' || drag.e.type === 'line') { draw(); }
    else if (d) { d.style.left = drag.e.x * S + 'px'; d.style.top = drag.e.y * S + 'px'; d.style.width = drag.e.w * S + 'px'; d.style.height = drag.e.h * S + 'px'; }
  });
  page.addEventListener('pointerup', () => {
    if (drag && drag.moved) { history.push(drag.before); dirty = true; status(); draw(); showProps(); }
    drag = null;
  });

  document.addEventListener('keydown', ev => {
    if ((ev.ctrlKey || ev.metaKey) && ev.key === 'z') { ev.preventDefault(); undo(); return; }
    if (!sel || /INPUT|TEXTAREA|SELECT/.test(document.activeElement.tagName)) return;
    const e = byId(sel); if (!e) return;
    const step = ev.shiftKey ? 5 : 1;
    const mv = { ArrowLeft: [-step, 0], ArrowRight: [step, 0], ArrowUp: [0, -step], ArrowDown: [0, step] }[ev.key];
    if (mv) { ev.preventDefault(); snapshot(); e.x = r1(e.x + mv[0]); e.y = r1(e.y + mv[1]); draw(); showProps(); }
    if (ev.key === 'Delete' || ev.key === 'Backspace') { ev.preventDefault(); remove(); }
  });

  function select(id) { sel = id; draw(); showProps(); }
  function remove() {
    if (!sel) return;
    snapshot(); layout.elements = layout.elements.filter(e => e.id !== sel); sel = null; draw(); showProps();
  }
  function undo() {
    if (!history.length) return;
    layout = JSON.parse(history.pop()); if (sel && !byId(sel)) sel = null; draw(); showProps(); dirty = true; status();
  }

  // ---------- properties panel ----------
  const fonts = cfg.fonts;
  function inp(label, key, val, type, extra) {
    if (type === 'color') val = C(val, '#000000');
    return `<label class="pd-f"><span>${label}</span><input data-k="${key}" type="${type || 'text'}" value="${esc(val == null ? '' : val)}" ${extra || ''}></label>`;
  }
  function chk(label, key, val) { return `<label class="pd-c"><input type="checkbox" data-k="${key}" ${val ? 'checked' : ''}> ${label}</label>`; }
  function sel_(label, key, val, opts) {
    return `<label class="pd-f"><span>${label}</span><select data-k="${key}">` +
      opts.map(o => { const [v, t] = Array.isArray(o) ? o : [o, o]; return `<option value="${esc(v)}" ${String(val) === String(v) ? 'selected' : ''}>${esc(t)}</option>`; }).join('') + '</select></label>';
  }
  function styleBlock(st, textish) {
    let h = '<div class="pd-g">';
    if (textish) {
      h += sel_('Font', 'style.font', st.font || 'Helvetica', fonts) + inp('Size (pt)', 'style.size', st.size || 10, 'number', 'step="0.5" min="4" max="72"');
      h += '<div class="pd-row">' + chk('<b>Bold</b>', 'style.bold', st.bold) + chk('<i>Italic</i>', 'style.italic', st.italic) + chk('CAPITALS', 'style.upper', st.upper) + '</div>';
      h += sel_('Align', 'style.align', st.align || 'left', [['left', 'Left'], ['center', 'Centre'], ['right', 'Right']]);
      h += inp('Text colour', 'style.color', st.color || '#000000', 'color');
    }
    h += inp('Background', 'style.bg', st.bg || '#ffffff', 'color') + `<button class="link small" data-clear="style.bg">no background</button>`;
    h += inp('Border (pt)', 'style.border', st.border || 0, 'number', 'step="0.1" min="0" max="6"') + inp('Border colour', 'style.border_color', st.border_color || '#000000', 'color');
    h += inp('Round corners (mm)', 'style.radius', st.radius || 0, 'number', 'step="0.5" min="0" max="20"');
    return h + '</div>';
  }
  function showProps() {
    const e = sel && byId(sel);
    if (!e) {
      props.innerHTML = `<h3>Page</h3>` + sel_('Paper', 'page', layout.page || 'A4', ['A4', 'A5', 'A4 landscape']) +
        `<p class="muted" style="font-size:12.5px">Click any item on the page to change its text, font, colour or size. Use the buttons above the page to add more.</p>`;
      bindProps(null); return;
    }
    const st = e.style || {};
    const names = { text: 'Text', image: 'Picture', items: 'Items table', totals: 'Totals', box: 'Box', line: 'Line', kv: 'Label / value list' };
    let h = `<h3>${names[e.type]}</h3><div class="pd-g pos">` + inp('Left', 'x', e.x, 'number', 'step="0.5"') + inp('Top', 'y', e.y, 'number', 'step="0.5"') +
      inp('Width', 'w', e.w, 'number', 'step="0.5"') + inp('Height', 'h', e.h, 'number', 'step="0.5"') + '</div>';
    if (e.type === 'text') {
      h += `<label class="pd-f wide"><span>Text (fields in {curly brackets} are filled in)</span><textarea data-k="text" rows="3">${esc(e.text)}</textarea></label>`;
      h += `<label class="pd-f wide"><span>Insert field</span><select id="insField"><option value="">Choose…</option>${cfg.fields.map(([k, t]) => `<option value="${k}">${esc(t)}</option>`).join('')}</select></label>`;
      h += sel_('Vertical', 'style.valign', st.valign || 'top', [['top', 'Top'], ['middle', 'Middle'], ['bottom', 'Bottom']]);
      h += inp('Padding (mm)', 'style.pad', st.pad == null ? 1.2 : st.pad, 'number', 'step="0.5" min="0"');
      h += chk('Hide when empty', 'hide_empty', e.hide_empty);
      h += styleBlock(st, true);
    } else if (e.type === 'image') {
      h += sel_('Picture', 'src', e.src, [['logo', 'Company logo'], ['terms', 'Terms picture']]);
      h += sel_('Align', 'style.align', st.align || 'left', [['left', 'Left'], ['center', 'Centre'], ['right', 'Right']]);
      h += styleBlock(st, false);
    } else if (e.type === 'items') {
      const tb = e.table || {};
      h += '<h4>Columns</h4><div class="pd-cols">';
      (e.columns || []).forEach((c, i) => {
        h += `<div class="pd-col" data-i="${i}"><input type="checkbox" data-ck="show" ${c.show !== false ? 'checked' : ''} title="Show">` +
          `<input data-ck="label" value="${esc(c.label)}" title="Heading"><input data-ck="w" type="number" value="${c.w}" title="Width" min="2" max="100">` +
          `<select data-ck="align" title="Align">${['left', 'center', 'right'].map(a => `<option ${c.align === a ? 'selected' : ''}>${a}</option>`).join('')}</select>` +
          `<button class="link" data-mv="-1" title="Move left">↑</button><button class="link" data-mv="1" title="Move right">↓</button></div>`;
      });
      const missing = cfg.columns.filter(([k]) => !(e.columns || []).some(c => c.key === k));
      if (missing.length) h += `<select id="addCol"><option value="">+ Add column…</option>${missing.map(([k, t]) => `<option value="${k}">${esc(t)}</option>`).join('')}</select>`;
      h += '</div><h4>Look</h4><div class="pd-g">';
      h += inp('Heading background', 'table.header_bg', tb.header_bg || '#1f4e79', 'color') + inp('Heading text', 'table.header_color', tb.header_color || '#ffffff', 'color');
      h += sel_('Lines', 'table.grid', tb.grid || 'vertical', [['vertical', 'Column lines'], ['all', 'All lines'], ['horizontal', 'Row lines only'], ['box', 'Outside only'], ['none', 'No lines']]);
      h += inp('Line colour', 'table.line_color', tb.line_color || '#000000', 'color') + inp('Stripe colour', 'table.zebra', tb.zebra || '#ffffff', 'color');
      h += `<button class="link small" data-clear="table.zebra">no stripes</button>`;
      h += inp('Row spacing', 'table.row_pad', tb.row_pad == null ? 1.6 : tb.row_pad, 'number', 'step="0.2" min="0"') + chk('Fill empty rows to the bottom', 'table.fill_rows', tb.fill_rows !== false);
      h += sel_('Font', 'style.font', st.font || 'Helvetica', fonts) + inp('Size (pt)', 'style.size', st.size || 9, 'number', 'step="0.5" min="5"') + chk('<b>Bold</b>', 'style.bold', st.bold);
      h += '</div>';
    } else if (e.type === 'totals') {
      h += '<h4>Rows</h4><div class="pd-cols">';
      (e.rows || []).forEach((r, i) => {
        h += `<div class="pd-col" data-ri="${i}"><input type="checkbox" data-rk="show" ${r.show !== false ? 'checked' : ''}><input data-rk="label" value="${esc(r.label)}" style="flex:1"></div>`;
      });
      h += '</div>' + sel_('Highlight row', 'highlight', e.highlight || '', [['', 'None'], ['last', 'Last row shown']].concat((e.rows || []).map(r => [r.key, r.label])));
      h += inp('Highlight colour', 'hl_bg', e.hl_bg || '#1f4e79', 'color') + inp('Highlight text', 'hl_color', e.hl_color || '#ffffff', 'color');
      h += chk('Lines between rows', 'style.lines', st.lines);
      h += styleBlock(st, true);
    } else if (e.type === 'kv') {
      h += '<h4>Rows (empty values are not printed)</h4><div class="pd-cols">';
      (e.rows || []).forEach((r, i) => {
        h += `<div class="pd-col" data-kv="${i}"><input data-kk="label" value="${esc(r.label)}" style="width:40%"><input data-kk="value" value="${esc(r.value)}" style="flex:1">` +
          `<button class="link" data-kvdel="${i}" title="Remove">✕</button></div>`;
      });
      h += `<select id="kvAdd"><option value="">+ Add row…</option>${cfg.fields.map(([k, t]) => `<option value="${k}">${esc(t)}</option>`).join('')}</select></div>`;
      h += '<div class="pd-g">' + inp('Label width %', 'style.label_w', st.label_w || 42, 'number', 'min="10" max="90"') +
        inp('Label colour', 'style.label_color', st.label_color || '#64748b', 'color') + '</div>';
      h += styleBlock(st, true);
    } else if (e.type === 'line') {
      h += inp('Thickness (pt)', 'style.border', st.border || 0.8, 'number', 'step="0.1" min="0.1"') + inp('Colour', 'style.color', st.color || '#000000', 'color');
    } else {
      h += styleBlock(st, false);
    }
    h += `<div class="pd-row" style="margin-top:10px"><button class="btn light small" id="dup">Duplicate</button><button class="btn light small" id="front">Bring to front</button>` +
      `<button class="btn light small" id="back">Send back</button><button class="btn bad small" id="del">Delete</button></div>`;
    props.innerHTML = h;
    bindProps(e);
  }

  function setPath(obj, path, v) {
    const ks = path.split('.'); let o = obj;
    for (let i = 0; i < ks.length - 1; i++) { o[ks[i]] = o[ks[i]] || {}; o = o[ks[i]]; }
    o[ks[ks.length - 1]] = v;
  }
  function bindProps(e) {
    props.querySelectorAll('[data-k]').forEach(i => {
      const ev = i.type === 'checkbox' || i.tagName === 'SELECT' || i.type === 'color' ? 'change' : 'input';
      i.addEventListener(ev, () => {
        snapshot();
        let v = i.type === 'checkbox' ? i.checked : (i.type === 'number' ? parseFloat(i.value || 0) : i.value);
        if (!e) { layout[i.dataset.k] = v; draw(); return; }
        setPath(e, i.dataset.k, v);
        draw();
        if (i.dataset.k === 'highlight' || i.dataset.k === 'src') showProps();
      });
    });
    props.querySelectorAll('[data-clear]').forEach(b => b.addEventListener('click', () => { snapshot(); setPath(e, b.dataset.clear, ''); draw(); showProps(); }));
    const ins = document.getElementById('insField');
    if (ins) ins.addEventListener('change', () => {
      if (!ins.value) return;
      const ta = props.querySelector('textarea[data-k=text]');
      const pos = ta.selectionStart || ta.value.length;
      ta.value = ta.value.slice(0, pos) + `{${ins.value}}` + ta.value.slice(pos);
      ta.dispatchEvent(new Event('input')); ins.value = '';
    });
    props.querySelectorAll('.pd-col[data-i]').forEach(row => {
      const c = e.columns[+row.dataset.i];
      row.querySelectorAll('[data-ck]').forEach(i => i.addEventListener(i.type === 'checkbox' || i.tagName === 'SELECT' ? 'change' : 'input', () => {
        snapshot(); c[i.dataset.ck] = i.type === 'checkbox' ? i.checked : (i.type === 'number' ? parseFloat(i.value || 1) : i.value); draw();
      }));
      row.querySelectorAll('[data-mv]').forEach(b => b.addEventListener('click', () => {
        const i = +row.dataset.i, j = i + (+b.dataset.mv);
        if (j < 0 || j >= e.columns.length) return;
        snapshot(); [e.columns[i], e.columns[j]] = [e.columns[j], e.columns[i]]; draw(); showProps();
      }));
    });
    const addCol = document.getElementById('addCol');
    if (addCol) addCol.addEventListener('change', () => {
      const f = cfg.columns.find(([k]) => k === addCol.value); if (!f) return;
      snapshot(); e.columns.push({ key: f[0], label: f[1], w: 10, align: ['price', 'amount', 'paid', 'left', 'bill_amount'].includes(f[0]) ? 'right' : 'left', show: true });
      draw(); showProps();
    });
    props.querySelectorAll('.pd-col[data-ri]').forEach(row => {
      const r = e.rows[+row.dataset.ri];
      row.querySelectorAll('[data-rk]').forEach(i => i.addEventListener(i.type === 'checkbox' ? 'change' : 'input', () => {
        snapshot(); r[i.dataset.rk] = i.type === 'checkbox' ? i.checked : i.value; draw();
      }));
    });
    props.querySelectorAll('.pd-col[data-kv]').forEach(row => {
      const r = e.rows[+row.dataset.kv];
      row.querySelectorAll('[data-kk]').forEach(i => i.addEventListener('input', () => { snapshot(); r[i.dataset.kk] = i.value; draw(); }));
    });
    props.querySelectorAll('[data-kvdel]').forEach(b => b.addEventListener('click', () => { snapshot(); e.rows.splice(+b.dataset.kvdel, 1); draw(); showProps(); }));
    const kvAdd = document.getElementById('kvAdd');
    if (kvAdd) kvAdd.addEventListener('change', () => {
      const f = cfg.fields.find(([k]) => k === kvAdd.value); if (!f) return;
      snapshot(); e.rows.push({ label: f[1], value: `{${f[0]}}` }); draw(); showProps();
    });
    const on = (id, fn) => { const b = document.getElementById(id); if (b) b.addEventListener('click', fn); };
    on('del', remove);
    on('dup', () => { snapshot(); const c = JSON.parse(JSON.stringify(e)); c.id = uid(e.type); c.x += 4; c.y += 4; layout.elements.push(c); select(c.id); });
    on('front', () => { snapshot(); e.z = Math.max(0, ...layout.elements.map(x => x.z || 0)) + 1; draw(); });
    on('back', () => { snapshot(); e.z = Math.min(0, ...layout.elements.map(x => x.z || 0)) - 1; draw(); });
  }

  // ---------- adding things ----------
  const fieldSel = document.getElementById('addField');
  cfg.fields.forEach(([k, t]) => { const o = document.createElement('option'); o.value = k; o.textContent = t; fieldSel.appendChild(o); });
  function add(el) { snapshot(); layout.elements.push(el); select(el.id); }
  fieldSel.addEventListener('change', () => {
    if (!fieldSel.value) return;
    add({ id: uid('t'), type: 'text', x: 20, y: 20, w: 70, h: 8, text: `{${fieldSel.value}}`, style: { size: 10 } });
    fieldSel.value = '';
  });
  document.querySelectorAll('[data-add]').forEach(b => b.addEventListener('click', () => {
    const t = b.dataset.add;
    if (t === 'text') add({ id: uid('t'), type: 'text', x: 20, y: 20, w: 70, h: 10, text: 'Your text', style: { size: 11 } });
    if (t === 'image') add({ id: uid('img'), type: 'image', src: 'logo', x: 15, y: 15, w: 50, h: 20, style: { align: 'left' } });
    if (t === 'box') add({ id: uid('box'), type: 'box', x: 20, y: 20, w: 60, h: 25, style: { border: 0.8, radius: 2 } });
    if (t === 'kv') add({ id: uid('kv'), type: 'kv', x: 130, y: 20, w: 65, h: 20, rows: [{ label: 'PO no.', value: '{po_no}' }], style: { size: 8, label_color: '#64748b' } });
    if (t === 'line') add({ id: uid('ln'), type: 'line', x: 15, y: 60, w: 180, h: 2, style: { border: 0.8 } });
    if (t === 'items') {
      if (layout.elements.some(e => e.type === 'items')) { alert('There is already an items table on the page.'); return; }
      const p = cfg.presets.classic.elements.find(e => e.type === 'items');
      add(Object.assign(JSON.parse(JSON.stringify(p)), { id: uid('items') }));
    }
    if (t === 'totals') {
      const p = cfg.presets.classic.elements.find(e => e.type === 'totals');
      add(Object.assign(JSON.parse(JSON.stringify(p)), { id: uid('tot') }));
    }
  }));
  const psel = document.getElementById('presetSel');
  if (psel) psel.addEventListener('change', () => {
    const k = psel.value; if (!k) return;
    const name = (cfg.presetNames || {})[k] || k;
    if (confirm(`Replace the page with the "${name}" template? (You can undo.)`)) {
      snapshot(); layout = JSON.parse(JSON.stringify(cfg.presets[k])); layout.preset = k; sel = null; draw(); showProps();
    }
    psel.value = '';
  });
  document.getElementById('undo').addEventListener('click', undo);
  document.getElementById('showGrid').addEventListener('change', ev => page.classList.toggle('grid', ev.target.checked));
  document.getElementById('zoom').addEventListener('input', ev => { S = parseFloat(ev.target.value); draw(); });

  // ---------- save / preview ----------
  function post(url, body) {
    return fetch(url, { method: 'POST', headers: { 'Content-Type': 'application/json', 'X-CSRF': window.PD_CSRF }, body: JSON.stringify(body) });
  }
  document.getElementById('preview').addEventListener('click', () => {
    const w = window.open('', '_blank');
    post('/print-designer/preview', { doc: cfg.doc, co: cfg.co, layout }).then(r => r.blob()).then(b => {
      const u = URL.createObjectURL(b); if (w) w.location = u; else window.open(u);
    });
  });
  document.getElementById('save').addEventListener('click', () => {
    post('/print-designer/save', { doc: cfg.doc, co: cfg.co, layout, active: true }).then(r => r.json()).then(j => {
      if (j.ok) { dirty = false; cfg.status = 'on'; status(); flash('Saved. Printing now uses this layout.'); }
    }).catch(() => flash('Could not save. Check your connection and try again.', true));
  });
  document.getElementById('turnoff').addEventListener('click', () => {
    if (!confirm('Go back to the standard print for this document? Your design stays saved and you can switch it on again.')) return;
    post('/print-designer/off', { doc: cfg.doc, co: cfg.co }).then(() => { cfg.status = 'off'; status(); flash('The standard print is used again.'); });
  });
  function flash(t, bad) {
    const d = document.createElement('div'); d.className = 'pd-toast' + (bad ? ' bad' : ''); d.textContent = t;
    document.body.appendChild(d); setTimeout(() => d.remove(), 3200);
  }
  window.addEventListener('beforeunload', ev => { if (dirty) { ev.preventDefault(); ev.returnValue = ''; } });

  draw(); showProps(); status();
})();
