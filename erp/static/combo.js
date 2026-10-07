/* Type-to-find box for long <select> lists (customers). Type to filter; Up/Down to move; Enter or Tab picks the highlighted match. */
(function () {
  function enhance(sel) {
    if (sel.dataset.combo) return; sel.dataset.combo = '1';
    const wasRequired = sel.required; sel.required = false;
    const wrap = document.createElement('div'); wrap.className = 'combo-wrap'; wrap.style.cssText = 'position:relative;display:inline-block;min-width:280px';
    const inp = document.createElement('input'); inp.type = 'text'; inp.autocomplete = 'off'; inp.className = 'combo-input';
    inp.placeholder = 'Type to find…'; inp.style.cssText = 'width:100%;font-weight:600;font-size:15px';
    const box = document.createElement('div'); box.className = 'combo-list';
    box.style.cssText = 'display:none;position:absolute;left:0;right:0;top:100%;z-index:60;max-height:300px;overflow:auto;background:#fff;border:1px solid var(--line2);border-radius:10px;box-shadow:0 12px 30px -10px rgba(15,23,42,.3);text-transform:none;letter-spacing:0;font-weight:500';
    sel.parentNode.insertBefore(wrap, sel); wrap.appendChild(inp); wrap.appendChild(box); sel.style.display = 'none'; wrap.appendChild(sel);
    const opts = () => [...sel.options].filter(o => o.value);
    let hi = 0, shown = [];
    const label = () => { const o = sel.options[sel.selectedIndex]; return o && o.value ? o.text : ''; };
    const close = () => { box.style.display = 'none'; };
    function render() {
      const terms = inp.value.trim().toLowerCase().split(/\s+/).filter(Boolean);
      shown = opts().filter(o => terms.every(t => o.text.toLowerCase().includes(t))).slice(0, 60);
      hi = Math.min(hi, Math.max(shown.length - 1, 0));
      box.innerHTML = shown.length ? '' : '<div style="padding:9px 12px;color:#94a3b8">No match</div>';
      shown.forEach((o, i) => { const d = document.createElement('div'); d.textContent = o.text; d.style.cssText = 'padding:8px 12px;cursor:pointer;' + (i === hi ? 'background:var(--accent-soft);color:var(--accent)' : '');
        d.addEventListener('mousedown', e => { e.preventDefault(); pick(o); }); box.appendChild(d); });
      box.style.display = 'block';
    }
    function pick(o) { sel.value = o.value; inp.value = o.text; close(); sel.dispatchEvent(new Event('change', { bubbles: true })); }
    inp.value = label();
    inp.addEventListener('focus', () => inp.select());
    inp.addEventListener('input', () => { hi = 0; render(); });
    inp.addEventListener('keydown', e => {
      if (e.key === 'ArrowDown') { e.preventDefault(); if (box.style.display === 'none') render(); else { hi = Math.min(hi + 1, shown.length - 1); render(); } }
      else if (e.key === 'ArrowUp') { e.preventDefault(); hi = Math.max(hi - 1, 0); render(); }
      else if (e.key === 'Enter') { if (box.style.display !== 'none' && shown[hi]) { e.preventDefault(); pick(shown[hi]); } else e.preventDefault(); }
      else if (e.key === 'Tab') { if (box.style.display !== 'none' && shown[hi] && inp.value.trim() && inp.value !== label()) pick(shown[hi]); else close(); }
      else if (e.key === 'Escape') { if (box.style.display !== 'none') { e.stopPropagation(); e.preventDefault(); inp.value = label(); close(); } }
    });
    inp.addEventListener('blur', () => { setTimeout(() => { close(); if (!sel.value) inp.value = ''; else inp.value = label(); }, 120); });
    sel.addEventListener('change', () => { inp.value = label(); });
    const form = sel.form;
    if (form && wasRequired) form.addEventListener('submit', e => { if (!sel.value) { e.preventDefault(); inp.focus(); inp.style.outline = '2px solid #ef4444'; } });
    sel.focus = () => inp.focus();
  }
  document.addEventListener('DOMContentLoaded', () => document.querySelectorAll('select.combo').forEach(enhance));
})();
