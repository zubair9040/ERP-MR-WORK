/* Invoice maths in whole paisa, rounding halves away from zero - the same rule as erp/db.py rnd(), so the screen and the saved invoice agree. */
(function (root) {
  const EPS = 1e-7;
  const halfUp = x => (x < 0 ? -1 : 1) * Math.floor(Math.abs(x) + 0.5 + EPS);
  const num = v => { const n = parseFloat(String(v == null ? '' : v).replace(/,/g, '')); return isNaN(n) ? 0 : n; };
  const toPaisa = txt => halfUp(num(txt) * 100);

  /* rows: [{kind, qty:'text', price:'text', hasText:bool}] -> {amounts:[paisa|null], total, tax, grand}. Mirrors erp/lines.py compute(). */
  function compute(rows, taxRate) {
    let group = 0, prev = 0, total = 0;
    const out = rows.map(r => {
      const priceTxt = String(r.price || '').trim(), qtyTxt = String(r.qty || '').trim();
      let amt = 0, cls = '';
      if (r.kind === 'subtotal') { amt = group; group = 0; cls = 'sub'; }
      else if (priceTxt.endsWith('%')) { amt = halfUp(prev * num(priceTxt.slice(0, -1)) / 100); group += amt; total += amt; cls = 'disc'; }
      else if (priceTxt) { const rate = toPaisa(priceTxt); amt = rate ? halfUp((qtyTxt ? num(qtyTxt) : 1) * rate) : 0; group += amt; total += amt; }
      prev = amt;
      return { amt, cls, show: !!priceTxt || !!qtyTxt || !!r.hasText };
    });
    const tax = halfUp(total * num(taxRate) / 100);
    return { rows: out, total, tax, grand: total + tax };
  }
  const api = { halfUp, toPaisa, compute };
  if (typeof module !== 'undefined' && module.exports) module.exports = api; else root.ErpMoney = api;
})(typeof window !== 'undefined' ? window : this);
