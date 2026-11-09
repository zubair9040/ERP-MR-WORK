(function(){
const $=id=>document.getElementById(id);
let NAMES={},PRICES={},ADDR={};const SEED_DC=0;
const CSRF=(document.querySelector('meta[name=csrf]')||{}).content||'';
let PREVIEW=false;
async function api(url,body){const r=await fetch(url,body?{method:'POST',credentials:'same-origin',headers:{'Content-Type':'application/json','X-CSRF':CSRF},body:JSON.stringify(body)}:{credentials:'same-origin'});let j={};try{j=await r.json();}catch(e){}if(!r.ok)throw new Error(j.error||('Server error '+r.status));return j;}
const LOGO=location.origin+'/static/hbl/logo.jpg';
const MON=['Jan','Feb','Mar','Apr','May','Jun','Jul','Aug','Sep','Oct','Nov','Dec'];
const FULLMON=['January','February','March','April','May','June','July','August','September','October','November','December'];
let lines=[],contacts={},byPO={};
const val=c=>{let v=c.value;if(v&&typeof v==='object'){if('result' in v)v=v.result;else if(v.richText)v=v.richText.map(t=>t.text).join('');else if(v.text)v=v.text;}return v;};
const cl=s=>String(s==null?'':s).split(/\s+/).join(' ').trim();
const esc=s=>String(s==null?'':s).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;');
const f2=x=>(Math.round((x+Number.EPSILON)*100)/100).toFixed(2);
const fc=x=>Number(f2(x)).toLocaleString('en-US',{minimumFractionDigits:2,maximumFractionDigits:2});
function msg(t,bad){const m=$('msg');m.textContent=t;m.style.color=bad?'var(--bad)':'var(--sub)';}
function pd(d){const x=new Date(d+'T00:00:00');return{d:('0'+x.getDate()).slice(-2),d1:x.getDate(),m:('0'+(x.getMonth()+1)).slice(-2),mon:MON[x.getMonth()],full:FULLMON[x.getMonth()],y:x.getFullYear(),y2:String(x.getFullYear()).slice(-2)};}
function ls(k,v){try{if(v===undefined)return localStorage.getItem(k);localStorage.setItem(k,v);}catch(e){}return null;}

async function load(file){
  if(/\.pdf$/i.test(file.name))return loadPdf(file);
  msg('Please drop the HBL purchase order PDF.',true);return;
  msg('Reading '+file.name+' (a big file can take about half a minute) ...');
  try{
    const wb=new ExcelJS.Workbook();await wb.xlsx.load(await file.arrayBuffer());
    const dw=wb.worksheets.find(w=>w.name.trim().toUpperCase()==='DATA');if(dw)return loadRecord(dw,file.name);
    const bw=wb.worksheets.find(w=>w.name.trim().toUpperCase()==='BILLS');
    const pw=wb.worksheets.find(w=>w.name.trim().toUpperCase().startsWith('PURCHASE ORDER'));
    if(!bw){msg('No tab named BILLS in this file.',true);return;}
    lines=[];contacts={};
    bw.eachRow((row,n)=>{if(n<18)return;
      const po=cl(val(row.getCell(13))),dc=Number(val(row.getCell(10))),q=Number(val(row.getCell(1)));
      if(!po||!dc||!(q>0))return;
      lines.push({qty:q,name:cl(val(row.getCell(2))),unit:cl(val(row.getCell(3))),price:Number(val(row.getCell(4)))||0,tax:Number(val(row.getCell(6)))||0,code:cl(val(row.getCell(9))),dc,req:cl(val(row.getCell(12))),po,loc:cl(val(row.getCell(14))),cc:cl(val(row.getCell(15)))});
    });
    if(pw)pw.eachRow((row,n)=>{if(n<2)return;const rq=cl(val(row.getCell(11)));if(!rq)return;const p=cl(val(row.getCell(12))),t=cl(val(row.getCell(13)));if((p||t)&&!contacts[rq])contacts[rq]={person:p,phone:t};});
    byPO={};
    lines.forEach(l=>{const P=byPO[l.po]||(byPO[l.po]={});const d=P[l.dc]||(P[l.dc]={dc:l.dc,inv:l.dc+1000,req:l.req,po:l.po,loc:l.loc,cc:l.cc,lines:[]});d.lines.push(l);});
    Object.values(byPO).forEach(P=>Object.values(P).forEach(d=>{d.lines.sort((a,b)=>a.code<b.code?-1:a.code>b.code?1:0);tot(d);}));
    const pos=Object.keys(byPO).sort((a,b)=>{const x=parseInt(a.split('-')[1]),y=parseInt(b.split('-')[1]);return isNaN(x)||isNaN(y)?a.localeCompare(b):x-y;});
    if(!pos.length){msg('No bill lines found in BILLS.',true);return;}
    const s=$('po');s.innerHTML='';pos.forEach(p=>{const o=document.createElement('option');o.value=o.textContent=p;s.appendChild(o);});
    s.value=pos.filter(p=>/^\d+-\d+$/.test(p)).slice(-1)[0]||pos[pos.length-1];
    const t=new Date();$('date').value=t.getFullYear()+'-'+('0'+(t.getMonth()+1)).slice(-2)+'-'+('0'+t.getDate()).slice(-2);
    const a=ls('hbl_sumno'),b=ls('hbl_inv');if(a)$('sumno').value=String(parseInt(a)+1);if(b)$('inv').value=String(parseInt(b)+1);
    RECMAX=0;lines.forEach(l=>{if(l.dc>RECMAX)RECMAX=l.dc;});
    const s4=wb.worksheets.find(w=>w.name.trim().toUpperCase()==='SHEET4');if(s4)s4.eachRow((row,n)=>{if(n<2)return;const v=Number(val(row.getCell(6)));if(v>RECMAX&&v<1e7)RECMAX=v;});if(!PARSED)$('dc0').value=String(RECMAX+1);
    $('dcw').style.display='none';$('step2').style.display='block';fillDC();msg(lines.length+' lines, '+pos.length+' POs read. Next DC number: '+(RECMAX+1)+'.');
    if(PARSED){$('dcw').style.display='';afterExcel();}
  }catch(e){msg('Could not read the file: '+e.message,true);}
}


let RECMAX=0,PARSED_BUILT=false,POTOT={};
let BILLS=[];
const billedOn=(po,dc)=>BILLS.filter(b=>b.po===po&&b.dc===dc).map(b=>b.sumno);
function addBilling(d,sumno,sinv,date){
  const lv=liveDC(d);if(!lv.lines.length)return;
  const rec={date,po:d.po,dc:d.dc,inv:d.inv,req:d.req,cc:d.cc,loc:d.loc,sumno:String(sumno),sinv:String(sinv),lines:lv.lines.map(l=>({code:l.code,name:l.name,unit:l.unit,qty:l.qty,price:l.price,tax:l.tax}))};
  const i=BILLS.findIndex(b=>b.po===rec.po&&b.dc===rec.dc&&b.sumno===rec.sumno);
  if(i>=0)BILLS[i]=rec;else BILLS.push(rec);
}
const isoOf=v=>{if(!v)return '';if(v instanceof Date)return v.getUTCFullYear()+'-'+('0'+(v.getUTCMonth()+1)).slice(-2)+'-'+('0'+v.getUTCDate()).slice(-2);const m=/^(\d{4}-\d{2}-\d{2})/.exec(String(v));return m?m[1]:'';};
const mkDate=iso=>{const p=iso.split('-');return new Date(Date.UTC(+p[0],+p[1]-1,+p[2]));};
function liveDC(d){const o=Object.assign({},d,{lines:d.lines.filter(l=>!l.cancelled&&l.qty>0)});tot(o);return o;}
function loadRecord(ws,name){
  msg('Reading record '+name+' ...');
  const P={};let maxS=0,maxI=0,n=0;
  ws.eachRow((row,r)=>{if(r<2)return;const g=i=>val(row.getCell(i));const dc=Number(g(3));if(!dc)return;n++;
    const po=cl(g(2));const PP=P[po]||(P[po]={});
    const d=PP[dc]||(PP[dc]={dc,inv:Number(g(4))||dc+1000,req:cl(g(5)),po,cc:cl(g(6)),loc:cl(g(7)),person:cl(g(8)),phone:cl(g(9)),date:isoOf(g(1)),sumno:cl(g(20)),sinv:cl(g(21)),lines:[]});
    const q0=Number(g(13))||0,q=Number(g(14))||0,st=cl(g(22)).toUpperCase();
    d.lines.push({code:cl(g(10)),name:cl(g(11)),unit:cl(g(12)),origQty:q0||q,qty:st==='CANCELLED'?(q0||q):q,price:Number(g(15))||0,tax:Number(g(17))||0,cancelled:st==='CANCELLED'});
    if(dc>RECMAX)RECMAX=dc;const sn=parseInt(g(20));if(sn>maxS)maxS=sn;const si=parseInt(g(21));if(si>maxI)maxI=si;});
  Object.values(P).forEach(PP=>Object.values(PP).forEach(d=>{d.lines.sort((a,b)=>a.code<b.code?-1:a.code>b.code?1:0);tot(d);contacts[d.req]={person:d.person,phone:d.phone};}));
  if(!n){msg('That file has a DATA tab but no records in it.',true);return;}
  Object.assign(byPO,P);RECPOS=new Set(Object.keys(P));
  BILLS=[];
  const bw=ws.workbook.worksheets.find(w=>w.name.trim().toUpperCase()==='BILLINGS');
  if(bw){const G={};bw.eachRow((row,r)=>{if(r<2)return;const g=i=>val(row.getCell(i));const dc=Number(g(3)),sn=cl(g(17));if(!dc||!sn)return;const po=cl(g(2)),k=po+'|'+dc+'|'+sn;
    const b=G[k]||(G[k]={date:isoOf(g(1)),po,dc,inv:Number(g(4))||dc+1000,req:cl(g(5)),cc:cl(g(6)),loc:cl(g(7)),sumno:sn,sinv:cl(g(18)),lines:[]});
    b.lines.push({code:cl(g(8)),name:cl(g(9)),unit:cl(g(10)),qty:Number(g(11))||0,price:Number(g(12))||0,tax:Number(g(14))||0});});BILLS=Object.values(G);}
  else{Object.values(P).forEach(PP=>Object.values(PP).forEach(d=>{if(!d.sumno)return;const lv=liveDC(d);if(!lv.lines.length)return;BILLS.push({date:d.date,po:d.po,dc:d.dc,inv:d.inv,req:d.req,cc:d.cc,loc:d.loc,sumno:String(d.sumno),sinv:String(d.sinv||''),lines:lv.lines.map(l=>({code:l.code,name:l.name,unit:l.unit,qty:l.qty,price:l.price,tax:l.tax}))});}));}
  const pso=ws.workbook.worksheets.find(w=>w.name==='PO SUMMARY');if(pso)pso.eachRow((row,r)=>{if(r<2)return;const p=cl(val(row.getCell(1))),e=Number(val(row.getCell(7))),i=Number(val(row.getCell(8)));if(p&&e)POTOT[p]={excl:e,incl:i||null};});
  if(maxS&&(!$('sumno').value||parseInt($('sumno').value)<=maxS))$('sumno').value=String(maxS+1);
  if(maxI&&(!$('inv').value||parseInt($('inv').value)<=maxI))$('inv').value=String(maxI+1);
  if(!PARSED)$('dc0').value=String(RECMAX+1);
  const pos=Object.keys(byPO);setupUI(n+' lines from the record, '+pos.length+' POs.');$('po').value=pos[pos.length-1];fillDC();
  msg('Record loaded: '+pos.length+' POs, '+n+' lines. Next DC number: '+(RECMAX+1)+'.');
  afterExcel();
}
let PARSED=null,DCMAP=null,RECPOS=new Set();
function afterExcel(){
  if(!PARSED||!RECMAX)return;
  const po=PARSED.header.po;DCMAP=null;
  if(RECPOS.has(po)){
    if(BILLS.some(b=>b.po===po)){PARSED=null;setupUI('PO '+po+' is already billed in your record, so the saved DCs are shown.');$('po').value=po;fillDC();return;}
    DCMAP={};Object.values(byPO[po]).forEach(d=>DCMAP[d.req]=d);
  }
  $('dc0').value=String(RECMAX+1);
  buildFromPdf();if(DCMAP){$('po').value=po;fillDC();msg('PO '+po+' is in your record but not billed yet: the same DC numbers are kept and the PO ceiling is applied.');return;}msg('DC numbers continue from '+RECMAX+': next DC is '+(RECMAX+1)+'.');
}

function setupUI(note){
  const pos=Object.keys(byPO);const s=$('po');s.innerHTML='';pos.forEach(p=>{const o=document.createElement('option');o.value=o.textContent=p;s.appendChild(o);});
  if(!$('date').value){const t=new Date();$('date').value=t.getFullYear()+'-'+('0'+(t.getMonth()+1)).slice(-2)+'-'+('0'+t.getDate()).slice(-2);}
  $('step2').style.display='block';fillDC();setAll(true);if(note)$('info').textContent=note;
}
function buildFromPdf(){
  const P=PARSED;if(!P)return;
  const start=parseInt($('dc0').value,10);if(!start){return;}
  let nxt=start;
  const po=P.header.po||'PO',warn=[];
  const order=[],map={};
  P.rows.forEach(r=>{if(!map[r.req]){map[r.req]={req:r.req,loc:cl(r.loc),cc:cl(r.loc).split('-')[0],lines:[],person:cl(r.person),phone:cl(r.phone)};order.push(r.req);}});
  const miss=new Set(),RC={},capOn=$('cap').checked;let ex=0;
  P.rows.forEach(r=>{
    const code=cl(r.item),q=Math.round(Number(r.qty)),pr=PRICES[code],bp=Number(String(r.price).replace(/,/g,''));let name,unit,price,mr=null;
    if(pr){name=pr[0];unit=pr[1];mr=pr[2];price=mr;if(capOn&&bp>0&&mr>bp)price=bp;}else{miss.add(code);name=cl(r.desc);unit=cl(r.uom);price=bp;}
    const tx=/(\d+)\s*%/.exec(r.tax||'');const tax=tx?Number(tx[1])/100:0.18;
    map[r.req].lines.push({qty:q,origQty:q,cancelled:false,name,unit,price,tax,code});ex+=q*price;
    if(mr!==null){const k=code+'|'+bp;const e=RC[k]||(RC[k]={code,name,bp,mr,qty:0,uomBad:cl(r.uom)&&unit&&cl(r.uom).toUpperCase()!==unit.toUpperCase()?cl(r.uom)+' vs '+unit:''});e.qty+=q;}
  });
  const P1={};
  order.forEach((rq,i)=>{const d=map[rq];const old=DCMAP&&DCMAP[rq];const dc=old?old.dc:nxt++;
    const o={dc,inv:old?old.inv:dc+1000,req:rq,po,loc:d.loc,cc:d.cc,person:d.person,phone:d.phone,lines:d.lines.sort((a,b)=>a.code<b.code?-1:a.code>b.code?1:0)};tot(o);P1[dc]=o;
    contacts[rq]={person:d.person,phone:d.phone};});
  byPO[po]=P1;POTOT[po]={excl:P.header.excl,tax:P.header.tax,incl:P.header.incl};
  const FIT=capOn?fitToPO(po,P1):[];
  showRates(RC,capOn,FIT);
  if(miss.size)warn.push('No M.R price found for: '+[...miss].join(', ')+' \u2014 the bank\'s price was used for these. Please check.');
  const chk=POPARSE.checkRows(P.header,P.rows);chk.warn.forEach(w=>warn.push('PO PDF: '+w));
  $('warn').innerHTML=warn.map(esc).join('<br>');
  $('info').textContent='';setupUI(P.rows.length+' lines, '+order.length+' DCs ('+start+' to '+(start+order.length-1)+'). M.R total excl. tax '+fc(ex)+' \u00b7 bank PO total '+(P.header.excl!=null?fc(P.header.excl):'?'));
}
async function loadPdf(file){
  msg('Reading '+file.name+' ...');
  try{
    pdfjsLib.GlobalWorkerOptions.workerSrc='/static/hbl/pdf.worker.js';
    const pages=await POPARSE.readPdf(await file.arrayBuffer());
    const P=POPARSE.parsePo(pages);
    if(!P.rows.length){msg('No PO lines found in this PDF. Is it an HBL purchase order?',true);return;}
    const po0=P.header.po;
    const st=await api('/hbl/api/po/'+encodeURIComponent(po0));
    if(st.exists){PARSED=null;await loadServerPO(po0);msg('PO '+po0+' is already in the ERP, so the saved DCs and invoice numbers are shown (nothing new was created).');return;}
    PARSED=P;PREVIEW=true;DCMAP=null;
    const nx=await api('/hbl/api/next');$('dc0').value=String(nx.next_invoice);
    if(nx.next_summary&&!$('sumno').value)$('sumno').value=String(nx.next_summary);if(nx.next_sinv&&!$('inv').value)$('inv').value=String(nx.next_sinv);
    buildFromPdf();
    $('createcard').style.display='block';
    msg('PO '+(po0||'')+' read. Check the rates below, then press "Create DCs & invoices in the ERP" - the ERP gives the real numbers.');
  }catch(e){msg('Could not read the PDF: '+e.message,true);}
}
async function loadServerPO(po){
  const st=await api('/hbl/api/po/'+encodeURIComponent(po));
  if(!st.exists){msg('PO '+po+' is not in the ERP yet.',true);return;}
  PREVIEW=false;$('createcard').style.display='none';$('dcw').style.display='none';
  const P1={};st.dcs.forEach(d=>{d.lines.forEach(l=>{if(l.origQty==null)l.origQty=l.qty;});tot(d);P1[d.dc]=d;contacts[d.req]={person:d.person,phone:d.phone};});
  byPO[po]=P1;POTOT[po]={excl:st.header.excl,tax:st.header.tax,incl:st.header.incl};
  BILLS=BILLS.filter(b=>b.po!==po).concat(st.bills);
  if(st.next_summary&&(!$('sumno').value||parseInt($('sumno').value)<st.next_summary))$('sumno').value=String(st.next_summary);
  if(st.next_sinv&&(!$('inv').value||parseInt($('inv').value)<st.next_sinv))$('inv').value=String(st.next_sinv);
  window.__batchUrl=st.batch_url;
  const sel=$('po');if(![...sel.options].some(o=>o.value===po)){const o=document.createElement('option');o.value=o.textContent=po;sel.appendChild(o);}
  setupUI('PO '+po+': '+st.dcs.length+' DCs from the ERP. DC no = invoice no. <a href="'+st.batch_url+'" target="_top">Open this PO in PO batch billing</a>');
  $('po').value=po;fillDC();$('info').innerHTML=$('info').textContent;
}
async function createInErp(){
  const P=PARSED;if(!P||!PREVIEW)return;const po=P.header.po;const D=byPO[po];if(!D){return;}
  const dcs=Object.values(D).sort((a,b)=>a.dc-b.dc).map(d=>({req:d.req,cc:d.cc,loc:d.loc,person:d.person,phone:d.phone,lines:d.lines.map(l=>({code:l.code,name:l.name,unit:l.unit,qty:l.qty,origQty:l.origQty,price:l.price,tax:l.tax}))}));
  $('create').disabled=true;msg('Creating '+dcs.length+' DCs / invoices in the ERP ...');
  try{
    const r=await api('/hbl/api/import',{po,date:$('date').value,header:{excl:P.header.excl,tax:P.header.tax,incl:P.header.incl},dcs});
    PARSED=null;PREVIEW=false;delete byPO[po];await loadServerPO(po);
    msg(r.created.length+' DCs / invoices created in the ERP (DC no = invoice no, from '+r.created[0].dc+' to '+r.created[r.created.length-1].dc+').'+(r.skipped?(' '+r.skipped+' already existed.'):''));
  }catch(e){msg(e.message,true);}finally{$('create').disabled=false;}
}
async function saveBilling(O,po,date,no,inv,isn){
  try{
    const dcs=O.map(d=>({dc:d.dc,lines:liveDC(d).lines.map(l=>({code:l.code,name:l.name,unit:l.unit,qty:l.qty,price:l.price,tax:l.tax}))})).filter(d=>d.lines.length);
    await api('/hbl/api/bill',{po,date,sumno:no,sinv:inv,isn,dcs});return true;
  }catch(e){msg(e.message,true);return false;}
}

function showRates(RC,capOn,FIT){
  let exact=0,round=0;const bad=[];
  Object.values(RC).forEach(e=>{const d=e.mr-e.bp;if(Math.abs(d)<1e-9)exact++;else if(Math.abs(d)<=0.005)round++;else bad.push(e);});
  const bu=bad.filter(e=>e.mr>e.bp),bl=bad.filter(e=>e.mr<e.bp),um=Object.values(RC).filter(e=>e.uomBad);
  let h='<div class="card" style="border-left-color:'+(bu.length?'var(--bad)':'var(--brand)')+'"><h3>Rate check (PO rate vs your price tab)</h3><div class="tot">'+exact+' rates match exactly, '+round+' differ only by rounding'+(round?(capOn?' (billed at the PO rate so the total never goes above the PO)':' (NOT capped — totals may go above the PO)'):'')+', <b>'+bad.length+' differ</b>.</div>';
  if(bad.length){h+='<div style="overflow:auto;margin-top:8px"><table style="border-collapse:collapse;font-size:13px;width:100%"><tr><th align="left">Item</th><th>Qty</th><th>PO rate</th><th>Your price tab</th><th align="left">What it means</th></tr>';
    bad.sort((a,b)=>(b.mr>b.bp)-(a.mr>a.bp)).forEach(e=>{const up=e.mr>e.bp;h+='<tr style="border-top:1px solid var(--line);'+(up?'color:var(--bad)':'')+'"><td>'+esc(e.code)+' '+esc(e.name)+'</td><td align="center">'+e.qty+'</td><td align="center">'+f2(e.bp)+'</td><td align="center">'+f2(e.mr)+'</td><td>'+(up?(capOn?'Your rate is HIGHER than the PO — billed at the PO rate. Fix the price tab.':'Your rate is HIGHER than the PO — payment can be stopped!'):'Your rate is lower than the PO — bill is lower (OK). Check the price tab.')+'</td></tr>';});
    h+='</table></div>';}
  if(FIT&&FIT.length){const sum=FIT.reduce((a,x)=>a+x.cut,0);h+='<div class="tot" style="font-size:13px">To keep the <b>tax and totals within the PO</b> (the bank rounds its tax to whole rupees), the rate of the biggest line was trimmed by '+f2(sum)+' in total: '+FIT.map(x=>'DC '+x.dc+' '+esc(x.name)).filter((v,i,a)=>a.indexOf(v)===i).join(', ')+'.</div>';}
  if(um.length)h+='<div class="tot" style="font-size:13px">'+um.length+' items have a different unit (PCS/PKT...) on the PO than in your price tab \u2014 bills use the price tab unit.</div>';
  $('rates').innerHTML=h+'</div>';
}
function totalsOf(S){let exU=0,gsU=0,exR=0,gsR=0,nR=0;S.forEach(d=>{const l=liveDC(d);exU+=l.ex;gsU+=l.gst;exR+=Number(f2(l.ex));gsR+=Number(f2(l.gst));nR+=Number(f2(l.net));});
  const r=x=>Math.round(x*100)/100;return {ex:Math.max(r(exU),r(exR)),gs:Math.max(r(gsU),r(gsR)),net:Math.max(r(exU+gsU),r(nR)),exU,gsU};}
function chkTotals(S,po){
  const T=POTOT[po],t=totalsOf(S);
  if(!T||T.excl==null)return {over:false,msg:''};
  const oe=t.ex-T.excl,og=T.tax!=null?t.gs-T.tax:0,oi=T.incl!=null?t.net-T.incl:0;
  const over=oe>0.0049||og>0.0049||oi>0.0049;
  return {over,msg:(over?'ABOVE THE PO AMOUNT — finance will stop the payment. ':'Within the PO amount. ')+'Excl. tax '+fc(t.exU)+' (PO '+fc(T.excl)+') · Tax '+fc(t.gsU)+(T.tax!=null?' (PO '+fc(T.tax)+')':'')+' · Incl. tax '+fc(t.exU+t.gsU)+(T.incl!=null?' (PO '+fc(T.incl)+')':'')};
}
function fitToPO(po,P1){
  const T=POTOT[po];if(!T||T.excl==null)return [];
  const DC=Object.values(P1),notes=[],lines=[];DC.forEach(d=>d.lines.forEach(l=>lines.push({l,d})));
  for(let it=0;it<30;it++){
    const t=totalsOf(DC);
    const oe=t.ex-T.excl,og=T.tax!=null?(t.gs-T.tax)/0.18:0,oi=T.incl!=null?(t.net-T.incl)/1.18:0;
    const worst=Math.max(oe,og,oi);if(worst<=0.0049)break;
    const r=worst+0.004;
    let best=null;lines.forEach(x=>{if(x.l.tax>0&&!x.l.cancelled){const a=x.l.qty*x.l.price;if(!best||a>best.a)best={x,a};}});
    if(!best||best.x.l.qty<=0)break;
    const l=best.x.l;l.price=Math.max(0,l.price-r/l.qty);notes.push({dc:best.x.d.dc,code:l.code,name:l.name,cut:r});
    DC.forEach(tot);
  }
  return notes;
}
function tot(d){let e=0,g=0,tx=0,nt=0;d.lines.forEach(l=>{const a=l.qty*l.price,t=a*l.tax;e+=a;g+=t;if(l.tax>0)tx+=a;else nt+=a;});d.ex=e;d.gst=g;d.net=e+g;d.taxable=tx;d.nontax=nt;}
function dcList(){return Object.values(byPO[$('po').value]||{}).sort((a,b)=>a.dc-b.dc);}
function fillDC(){
  const L=dcList(),h=['<table><thead><tr><th></th><th>DC</th><th>Branch</th><th>Req</th><th style="text-align:right">Net</th><th></th></tr></thead><tbody>'];
  L.forEach(d=>{const lv=liveDC(d);h.push('<tr class="dr"><td><input type="checkbox" class="ck" value="'+d.dc+'"></td><td><input type="text" class="dcn" size="6" readonly inputmode="numeric" data-dc="'+d.dc+'" value="'+d.dc+'" title="Type a different DC number if needed" style="width:72px;font-weight:bold"></td><td>'+esc(d.loc)+(billedOn(d.po,d.dc).length?' <span style="color:var(--sub)">(billed: summary '+esc(billedOn(d.po,d.dc).join(', '))+')</span>':'')+'</td><td>'+esc(d.req)+'</td><td style="text-align:right" id="net'+d.dc+'">'+fc(lv.net)+'</td><td><button type="button" class="alt ed" data-dc="'+d.dc+'">Items</button></td></tr>');
    h.push('<tr class="er" id="er'+d.dc+'" style="display:none"><td></td><td colspan="5">'+d.lines.map((l,k)=>'<label><input type="checkbox" class="lc" data-dc="'+d.dc+'" data-k="'+k+'"'+(l.cancelled?'':' checked')+'> '+esc(l.name)+' <span style="color:var(--sub)">'+esc(l.code)+'</span> &nbsp; Qty <input type="number" min="0" class="lq" data-dc="'+d.dc+'" data-k="'+k+'" value="'+l.qty+'"></label>').join('')+'<div style="font-size:12px;color:var(--sub)">Untick an item to cancel it, or change the quantity.</div></td></tr>');});
  h.push('</tbody></table>');$('dcs').innerHTML=h.join('');
  if(L.length){$('from').value=L[0].dc;$('to').value=L[L.length-1].dc;}
  document.querySelectorAll('.ck').forEach(c=>c.addEventListener('change',upd));
  document.querySelectorAll('.ed').forEach(b=>b.addEventListener('click',()=>{const e=$('er'+b.dataset.dc);e.style.display=e.style.display==='none'?'table-row':'none';}));
  const chg=e=>{const t=e.target,d=(byPO[$('po').value]||{})[t.dataset.dc],l=d.lines[+t.dataset.k];
    if(t.classList.contains('lc'))l.cancelled=!t.checked;else{l.qty=Math.max(0,Math.round(Number(t.value))||0);}
    $('net'+d.dc).textContent=fc(liveDC(d).net);upd();};
  document.querySelectorAll('.lc,.lq').forEach(c=>c.addEventListener('change',chg));
  document.querySelectorAll('.dcn').forEach(inp=>inp.addEventListener('change',()=>{
    const po=$('po').value,P=byPO[po],old=+inp.dataset.dc,nw=parseInt(String(inp.value).replace(/\D/g,''),10);
    if(!nw||nw===old){inp.value=old;return;}
    if(P[nw]){inp.value=old;msg('DC '+nw+' is already used in this PO. Type another number.',true);return;}
    const d=P[old],ticked=new Set([...document.querySelectorAll('.ck:checked')].map(c=>+c.value));
    delete P[old];d.dc=nw;if(d.inv===old+1000)d.inv=nw+1000;P[nw]=d;
    ticked.delete(old);ticked.add(nw);fillDC();
    document.querySelectorAll('.ck').forEach(c=>c.checked=ticked.has(+c.value));upd();
    msg('DC '+old+' changed to '+nw+' (invoice no '+d.inv+').');
  }));
  upd();
}
function sel(){const s=new Set([...document.querySelectorAll('.ck:checked')].map(c=>+c.value));return dcList().filter(d=>s.has(d.dc));}
function upd(){const S=sel();let n=0,sm=new Set(),sv=new Set();S.forEach(d=>{n+=liveDC(d).net;if(d.sumno)sm.add(d.sumno);if(d.sinv)sv.add(d.sinv);});
  $('tot').textContent=S.length+' DCs ticked'+(S.length?' — net '+fc(n):'');
  const c=S.length?chkTotals(S,$('po').value):{over:false,msg:''};$('chk').textContent=c.msg;$('chk').style.color=c.over?'var(--bad)':'var(--sub)';$('chk').style.fontWeight=c.over?'bold':'normal';
  const was=new Set();S.forEach(d=>billedOn(d.po,d.dc).forEach(x=>was.add(x)));
  if(was.size)$('tot').textContent+=' \u2014 already billed on summary '+[...was].join(', ')+'. For a partial / new billing type the NEW summary no and GST no below.';}
function setAll(v){document.querySelectorAll('.ck').forEach(c=>c.checked=v);upd();}

/* ---------- page builders ---------- */
const WA='<svg viewBox="0 0 24 24" style="width:1.15em;height:1.15em;vertical-align:-.2em"><path fill="#25D366" d="M12 0a12 12 0 0 0-10.3 18L0 24l6.2-1.6A12 12 0 1 0 12 0z"/><path fill="#fff" d="M17.5 14.4c-.3-.15-1.7-.85-2-.95s-.45-.15-.65.15-.75.95-.9 1.15-.35.2-.65.05a7.9 7.9 0 0 1-3.9-3.4c-.3-.5.3-.5.85-1.6.1-.2.05-.35 0-.5s-.65-1.6-.9-2.2-.5-.5-.65-.5h-.55a1.05 1.05 0 0 0-.75.35 3.1 3.1 0 0 0-1 2.3 5.4 5.4 0 0 0 1.1 2.9 12.3 12.3 0 0 0 4.7 4.15c1.75.75 2.45.8 3.3.7a2.8 2.8 0 0 0 1.85-1.3 2.3 2.3 0 0 0 .15-1.3c-.05-.1-.25-.2-.55-.35z"/></svg>';
const hdr=t=>'<div class="hd">'+(t?'<div class="ttl">'+t+'</div>':'')+'<img src="'+LOGO+'"><div class="co">M.R ENTERPRISES</div><div class="ad">78/ B1 BLOCK-6 PECHS NEAR IMAM AHMED ROAD KARACHI.</div><div class="l">N.T.NO 1433823-8<br>G.S.T.#. 12-00-4817-172-82</div><div class="r">PTCL : 021-34555883<br>MOB : 0300-2760602<br>'+WA+' 0326-2220447</div></div>';
const pg=h=>'<div class="pg">'+h+'</div>';
const rt=a=>'<div class="rt"><table>'+a.map(x=>'<tr><td class="k">'+x[0]+'</td><td class="v">'+esc(x[1])+'</td></tr>').join('')+'</table></div>';
const chunk=(a,n)=>{const o=[];for(let i=0;i<a.length;i+=n)o.push(a.slice(i,i+n));return o.length?o:[[]];};
function billPages(d,D){
  const out=[],ch=chunk(d.lines,28);
  ch.forEach((c,i)=>{const last=i===ch.length-1;let h=hdr('BILL')+'<div style="text-align:right;margin-top:3mm;font-weight:bold">'+D.d+'-'+D.mon+'-'+D.y2+'</div>'+rt([['INVOICE #',d.inv],['DC #',d.dc],['PO #',d.po],['REQ #',d.req],['BR. CODE #',d.cc]])+'<div class="ms">M/S HBL</div><div class="br">'+esc(d.loc)+'</div>';
    h+='<table class="t"><thead><tr><th style="width:9%">DENO</th><th>NAME OF ITEMS</th><th style="width:7%">UNIT</th><th style="width:9%">PRICE</th><th style="width:12%">AMOUNT<br>EXCL S.Tax</th><th style="width:7%">TAX %</th><th style="width:10%">TAX VALUE</th><th style="width:13%">TOTAL AMOUNT<br>INCLS TAX</th></tr></thead><tbody>';
    c.forEach(l=>{const a=l.qty*l.price,t=a*l.tax;h+='<tr><td class="c"><b>'+l.qty+'</b></td><td>'+esc(l.name)+'</td><td class="c">'+esc(l.unit)+'</td><td class="c">'+f2(l.price)+'</td><td class="c">'+f2(a)+'</td><td class="c">'+Math.round(l.tax*100)+'%</td><td class="c">'+f2(t)+'</td><td class="c">'+f2(a+t)+'</td></tr>';});
    h+='</tbody></table>';
    if(last){h+='<div style="display:flex;justify-content:flex-end;font-size:8pt;margin-top:2mm"><span style="width:28%;text-align:right;padding-right:6mm">'+f2(d.ex)+'</span><span style="width:12%;text-align:center">'+f2(d.gst)+'</span><span style="width:13%;text-align:center">'+f2(d.net)+'</span></div>'+
      '<div class="sbox"><div><span>SUB TOTAL (TAX ITEMS )</span><span>'+fc(d.taxable)+'</span></div><div><span>SUB TOTAL (NON TAX ITEMS )</span><span>'+(d.nontax?fc(d.nontax):'-')+'</span></div><div><span>TOTAL VALUE (EXCLUDING TAX)</span><span>'+fc(d.ex)+'</span></div><div><span>ADD: ( TOTAL TAX AMOUNT )</span><span>'+fc(d.gst)+'</span></div><div class="net"><span>NET AMOUNT (TOTAL INCL. TAX)</span><span>'+fc(d.net)+'</span></div></div>';}
    h+='<div class="foot">Page '+(i+1)+' of '+ch.length+'</div>';out.push(pg(h));});
  return out;
}
function dcPages(d,D,label){
  const out=[],ch=chunk(d.lines,32),ct=(d.person||d.phone)?{person:d.person,phone:d.phone}:(contacts[d.req]||{});
  ch.forEach((c,i)=>{let h=(label?'<div class="cp">'+label+'</div>':'')+hdr('DELIVERY CHALLAN')+'<div style="margin-top:3mm;font-weight:bold;font-style:italic;text-decoration:underline">'+D.d+'-'+D.mon+'-'+D.y2+'</div>'+rt([['DC #',d.dc],['PO NO',d.po],['PR NO',d.req],['BRANCH/COST CODE',d.cc]])+'<div class="ms">M/S HBL</div><div class="br">'+esc(d.loc)+'</div>'+(ct.phone?'<div class="br" style="text-decoration:underline">'+esc(ct.phone)+'</div>':'')+(ct.person?'<div class="br" style="text-decoration:underline">'+esc(ct.person)+'</div>':'');
    h+='<table class="t" style="margin-top:3mm"><thead><tr><th style="width:9%">DENO</th><th style="width:9%">UNIT</th><th>NAME OF ITEMS</th><th style="width:22%">EXP CODE</th></tr></thead><tbody>';
    c.forEach(l=>{h+='<tr><td class="c"><b>'+l.qty+'</b></td><td class="c">'+esc(l.unit)+'</td><td><b>'+esc(l.name)+'</b></td><td><b>'+esc(l.code)+'</b></td></tr>';});
    h+='</tbody></table><div class="sig"><div>COURIER ID <span></span></div><div>Parcel Count <span style="min-width:22mm"></span></div><div>Dispatch Date <span></span></div></div><div class="foot">Page '+(i+1)+' of '+ch.length+'</div>';out.push(pg(h));});
  return out;
}
function summaryPages(S,D,no){
  const ch=chunk(S,20),out=[];let g=[0,0,0];S.forEach(d=>{g[0]+=d.ex;g[1]+=d.gst;g[2]+=d.net;});let sr=0;
  ch.forEach((c,i)=>{const last=i===ch.length-1;
    let h=hdr('SUMMARY')+'<div class="ms" style="margin-top:6mm">M/S HBL</div><div style="display:flex;justify-content:space-between;font-weight:bold;margin:4mm 0 1mm;font-size:10pt"><span>SUMMARY NO : &nbsp;&nbsp;&nbsp;<u>'+esc(no)+'</u></span><span>DATED: &nbsp;&nbsp;&nbsp;&nbsp;<u>'+D.d1+'-'+D.mon+'-'+D.y2+'</u></span></div>';
    h+='<table class="t" style="table-layout:fixed;font-size:8.5pt"><thead><tr><th style="width:3%;font-size:6.5pt">SR.<br>NO.</th><th style="width:5.5%;font-size:6.5pt">BR. /<br>COST<br>CODE</th><th style="width:6%;font-size:6.5pt">DC NO.</th><th style="width:6%;font-size:6.5pt">INOVICE<br>NO.</th><th style="width:6.5%;font-size:6.5pt">RQ. NO.</th><th style="width:9.5%;font-size:6.5pt">P.O NO.</th><th style="font-size:8pt">BRANCH NAME / DEPARTMENT</th><th style="width:6%;font-size:5.5pt">EXEMPTED<br>AMOUNT</th><th style="width:8.5%;font-size:6.5pt">AMOUNT<br>WITHOUT<br>GST</th><th style="width:8%;font-size:6.5pt">GST<br>AMOUNT</th><th style="width:9%;font-size:6.5pt">NET<br>AMOUNT</th></tr></thead><tbody>';
    const bsz=n=>n<=72?'8.5pt':n<=84?'7.6pt':n<=98?'6.9pt':n<=118?'6.1pt':'5.5pt';
    c.forEach(d=>{sr++;h+='<tr><td class="c" style="font-size:8.5pt">'+sr+'</td><td class="c" style="font-size:8.5pt">'+esc(d.cc)+'</td><td class="c" style="font-size:8.5pt">'+d.dc+'</td><td class="c" style="font-size:8.5pt">'+d.inv+'</td><td class="c" style="font-size:8.5pt">'+esc(d.req)+'</td><td class="c" style="white-space:nowrap;font-size:8pt">'+esc(d.po)+'</td><td style="font-weight:bold;font-size:'+bsz(d.loc.length)+';line-height:1.15;height:9mm;padding:.5mm 1.5mm"><div style="display:-webkit-box;-webkit-line-clamp:2;-webkit-box-orient:vertical;overflow:hidden">'+esc(d.loc)+'</div></td><td class="c" style="font-size:8.5pt">'+f2(d.nontax)+'</td><td class="c" style="font-size:8.5pt">'+f2(d.ex)+'</td><td class="c" style="font-size:8.5pt">'+f2(d.gst)+'</td><td class="c" style="font-size:8.5pt">'+f2(d.net)+'</td></tr>';});
    h+='</tbody></table>';
    if(last)h+='<div style="display:flex;border-top:3px double #000;border-bottom:1px solid #000;margin:2mm 0 0 38%;font-weight:bold;font-size:8.5pt;padding:1mm 0"><span style="width:40%;text-align:center">GRAND TOTAL</span><span style="width:14%;text-align:center">0.00</span><span style="width:16%;text-align:center">'+f2(g[0])+'</span><span style="width:14%;text-align:center">'+f2(g[1])+'</span><span style="width:16%;text-align:center">'+f2(g[2])+'</span></div>';
    h+='<div class="foot">Page '+(i+1)+' of '+ch.length+'</div>';out.push(pg(h));});
  return out;
}
function invoicePage(S,D,inv){
  let e=0,g=0;S.forEach(d=>{e+=d.ex;g+=d.gst;});
  const box=(k,v,b)=>'<div style="display:flex;border-bottom:1px solid #000;padding:.6mm 1.5mm;min-height:5.2mm"><span style="width:38%;font-weight:bold;font-size:8pt">'+k+'</span><span style="font-weight:bold;'+(b?'':'font-size:8pt')+'">'+v+'</span></div>';
  let rows='';for(let i=0;i<24;i++)rows+='<tr><td style="height:6.4mm"></td><td></td><td></td><td></td><td></td><td></td><td></td></tr>';
  let h='<div style="position:absolute;right:12mm;top:12mm;border:1px solid #000;width:32mm;font-size:9pt;text-align:center"><div style="border-bottom:1px solid #000;padding:.8mm">Original</div><div style="padding:.8mm">Duplicate</div></div>'+
   '<div style="text-align:center;margin-top:8mm" class="big">SALES TAX INVOICE</div>'+
   '<div style="display:flex;justify-content:space-between;margin:8mm 0 4mm;font-size:11pt"><span>Serial No: &nbsp;&nbsp;<b><u>MR-'+esc(inv)+'</u></b></span><span>Date: &nbsp;&nbsp;<b><u>'+D.d+'.'+D.m+'.'+D.y+'</u></b></span><span>Time of Supply &nbsp;&nbsp;<u>&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;</u></span></div>'+
   '<div style="display:flex;border:1px solid #000;border-width:2px 2px 2px 2px"><div style="width:50%;border-right:1px solid #000">'+box("Supplier's Name",'M.R. ENTERPRISES',1)+box('&amp;','')+box('Address','78-D BLOCK 6 P.E.C.H.S KARACHI')+box('','')+box('','')+box('Telephone No.','')+box('N.T.N. NO.','1433823-8')+box('ST Reg. No.','12-00-4817-172-82')+'</div><div style="width:50%">'+box("Buyer's Name",'M/S HABIB BANK LTD',1)+box('&amp;','')+box('Address','')+box('','')+box('','')+box('Telephone No.','')+box('N.T.N. NO.','0698187-9')+box('ST Reg. No.','')+'</div></div>'+
   '<div style="margin:5mm 0 3mm;font-size:10pt">Terms of Sale: <u>&nbsp;'.concat(' '.repeat(0),'&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;</u></div>')+
   '<table class="t" style="margin-top:2mm"><thead><tr><th style="width:15%;font-size:9pt">Quantity</th><th style="font-size:9pt">Description of Goods</th><th style="width:8%;font-size:9pt">Unit<br>Price</th><th style="width:12%;font-size:8.5pt">Value<br>Excluding<br>Sales Tax</th><th style="width:11%;font-size:8.5pt">S/Tax at<br>Standard<br>Rate of @</th><th style="width:11%;font-size:8.5pt">Total Sales<br>Tax<br>Payable</th><th style="width:12%;font-size:8.5pt">Value<br>Including<br>Sales Tax</th></tr><tr><th>1</th><th>2</th><th>3</th><th>4</th><th>5</th><th>6</th><th>7</th></tr></thead><tbody>'+
   '<tr><td class="c" style="height:6.4mm;font-size:10pt">1 LOT</td><td class="c" style="font-size:10pt">STATIONERY ITEMS</td><td></td><td class="c" style="font-size:10pt">'+f2(e)+'</td><td class="c" style="font-size:10pt">18%</td><td class="c" style="font-size:10pt">'+f2(g)+'</td><td class="c" style="font-size:10pt">'+f2(e+g)+'</td></tr>'+rows+
   '<tr><td style="height:8mm;font-size:10pt">Signature</td><td class="c" style="font-size:10pt;text-align:right;padding-right:20mm">Total</td><td></td><td class="c" style="font-size:10pt;font-weight:bold">'+f2(e)+'</td><td class="c" style="font-size:10pt;font-weight:bold">18%</td><td class="c" style="font-size:10pt;font-weight:bold">'+f2(g)+'</td><td class="c" style="font-size:10pt;font-weight:bold">'+f2(e+g)+'</td></tr></tbody></table>';
  return [pg(h)];
}
function undertakingPage(S,D,no,inv){
  let n=0;S.forEach(d=>n+=d.net);
  const h=hdr('')+'<div style="margin-top:12mm;font-weight:bold;font-size:10pt;line-height:1.5">To,<br>Finance Department<br>Habib Bank Limited,<br>Pakistan.</div><div style="text-align:center;font-weight:bold;text-decoration:underline;font-size:11pt;margin:10mm 0 8mm">UNDERTAKING</div>'+
   '<div style="font-weight:bold;text-decoration:underline;font-size:10pt;line-height:1.6">Invoice No. '+esc(no)+'<br>GST Inv No. MR-'+esc(inv)+'<br>Dated: '+D.d+'. '+D.full+' '+D.y+'<br>Amount: '+f2(n)+'</div>'+
   '<div style="font-size:10pt;line-height:1.55;margin-top:12mm;text-align:justify"><p>Dear Sir,</p><p style="margin-top:6mm">This is to confirm that the supplies made to you against your Purchase Order were imported by us as &ldquo;Commercial Importer&rdquo; and income tax has already been collected by the Government of Pakistan at import stage under section 148 of Income Tax Ordinance 2001. In accordance with the exemption available vide SRO No.97 (1)/2002 dated 12 February 2002, and under clause 47A part 4 2<sup>nd</sup> schedule of Income Tax Ordinance 2001, no further tax under Section 153 of Income Tax Ordinance 2001 Should be deducted from the payment made to us against these supplies.</p><p style="margin-top:5mm">Accordingly, we request you not to deduct withholding tax from payment made by you against the supplies made by us.</p><p style="margin-top:5mm">In case of any objection or demand by the tax authorities resulting from your compliance with our above request, we hereby undertake to pay you the withholding tax plus incidental liabilities that you may holding liable to pay to the Government.</p><p style="margin-top:5mm">Check FBR Link: http://www.fbr.gov.pk/new dt/sros/2002sro97it.htm</p></div>'+
   '<div style="position:absolute;left:12mm;bottom:55mm;font-size:10pt;line-height:1.7">Thanking You,<br>With Best Regards,<br><br><br>For M.R. Enterprises</div>';
  return [pg(h)];
}
function itemPages(S,D,po,isn){
  const m=new Map();
  S.forEach(d=>d.lines.forEach(l=>{let a=m.get(l.code);if(!a){a={code:l.code,name:l.name,unit:l.unit,price:l.price,tax:l.tax,qty:0};m.set(l.code,a);}a.qty+=l.qty;}));
  const items=[...m.values()];items.forEach(a=>{const n=NAMES[a.code];if(n){a.name=n[0];a.unit=n[1]||a.unit;}});
  items.sort((a,b)=>a.code<b.code?-1:a.code>b.code?1:0);
  let tx=0,nt=0,gs=0;items.forEach(a=>{const e=a.qty*a.price;if(a.tax>0)tx+=e;else nt+=e;gs+=e*a.tax;});
  const ch=chunk(items,20),out=[];
  ch.forEach((c,i)=>{const last=i===ch.length-1;
    let h=hdr('ITEM SUMMARY')+'<div style="text-align:right;font-weight:bold;margin-top:3mm">'+D.d+'-'+D.mon+'-'+D.y2+'</div>'+rt([['ITEM SUMMRY #',isn],['PO #',po]])+'<div class="ms">M/S HBL</div>';
    h+='<table class="t"><thead><tr><th style="width:7%">DENO</th><th>NAME OF ITEMS</th><th style="width:7%">UNIT</th><th style="width:9%">PRICE</th><th style="width:11%">AMOUNT<br>EXCL S.Tax</th><th style="width:7%">TAX %</th><th style="width:10%">TAX VALUE</th><th style="width:12%">TOTAL<br>AMOUNT INCLS<br>TAX</th><th style="width:12%">COST CODE</th></tr></thead><tbody>';
    c.forEach(a=>{const e=a.qty*a.price,t=e*a.tax;h+='<tr><td class="c"><b>'+a.qty+'</b></td><td>'+esc(a.name)+'<br><span style="font-size:7pt">'+esc(a.code)+'</span></td><td class="c">'+esc(a.unit)+'</td><td class="c">'+f2(a.price)+'</td><td class="c">'+f2(e)+'</td><td class="c">'+Math.round(a.tax*100)+'%</td><td class="c">'+f2(t)+'</td><td class="c">'+f2(e+t)+'</td><td class="c" style="font-size:7pt">'+esc(a.code)+'</td></tr>';});
    h+='</tbody></table>';
    if(last)h+='<div style="display:flex;font-weight:bold;font-size:8.5pt;margin:2mm 0;justify-content:flex-end"><span style="width:20%;text-align:center">TOTAL</span><span style="width:12%;text-align:center">'+f2(tx+nt)+'</span><span style="width:17%"></span><span style="width:10%;text-align:center">'+f2(gs)+'</span><span style="width:12%;text-align:center">'+f2(tx+nt+gs)+'</span><span style="width:12%"></span></div><div class="sbox" style="width:62%;border:0;border-top:2px solid #000"><div><span>SUB TOTAL (TAX ITEMS )</span><span>'+fc(tx)+'</span></div><div><span>SUB TOTAL (NON TAX ITEMS )</span><span>'+fc(nt)+'</span></div><div><span>TOTAL VALUE (EXCLUDING TAX)</span><span>'+fc(tx+nt)+'</span></div><div><span>ADD: ( TOTAL TAX AMOUNT )</span><span>'+fc(gs)+'</span></div><div class="net"><span>NET AMOUNT (TOTAL INCL. TAX)</span><span>'+fc(tx+nt+gs)+'</span></div></div>';
    h+='<div class="foot">Page '+(i+1)+' of '+ch.length+'</div>';out.push(pg(h));});
  return out;
}

function slipPage(d,st){
  if(st===undefined){const v=parseInt($('slipstyle').value);st=isNaN(v)?0:v;}
  const k=String(parseInt(d.cc,10)),A=ADDR[k]||null,ct=(d.person||d.phone)?{person:d.person,phone:d.phone}:(contacts[d.req]||{});
  const addr=A&&A[2]?A[2]:d.loc,bn=d.loc,no=A&&A[3]&&A[3]!=='-'?A[3]:'',reg=A?A[1]:'',per=ct.person||'',ph=ct.phone||'';
  const L=addr.length,f=st===3?0.82:1,asz=Math.round((L<=60?31:L<=100?26:L<=150?22:18)*f)+'pt',bsz=bn.length<=45?'16pt':bn.length<=80?'13pt':'11pt';
  const lab=(t,sz)=>'<div style="font-size:'+(sz||'9pt')+';font-weight:bold;letter-spacing:.5pt">'+t+'</div>';
  const from='<div style="font-size:8pt;text-align:center;border-top:1.5px solid #000;padding:1mm 2mm;font-weight:bold">FROM: M.R ENTERPRISES, 78/ B1 BLOCK-6 PECHS NEAR IMAM AHMED ROAD KARACHI. &nbsp; PTCL: 021-34555883 &nbsp; MOB: 0300-2760602 &nbsp; '+WA+' 0326-2220447</div>';
  const box='border:1.5px solid #000;';let h='';
  if(st===0){ /* original slip */
    const row=(k2,v,sz)=>'<div class="r"><span class="k">'+k2+'</span><span class="v"'+(sz?' style="font-size:'+sz+'"':'')+'>'+esc(v)+'</span></div>';
    h='<div class="slb"><div class="r" style="justify-content:center;font-size:26pt;font-style:italic;text-decoration:underline;padding:2mm">M/S HBL</div>'+
     row('BRANCH ADDRESS:',addr,addr.length<=70?'19pt':addr.length<=110?'16pt':addr.length<=160?'14pt':'12pt')+row('BRANCH NAME:',bn,bn.length>70?'11pt':'13pt')+row('BRANCH NO:',no)+row('REGION:',reg,'16pt')+
     '<div style="flex:1;display:flex;min-height:0"><div style="flex:1.5;padding:2mm 3mm;display:flex;flex-direction:column;justify-content:space-around"><div style="font-size:15pt">NAME / DEPARTMENT:</div><div style="font-size:15pt;text-decoration:underline;padding-left:6mm">'+esc(per)+'</div><div style="font-size:15pt">CONTACT:</div><div style="font-size:15pt;text-decoration:underline;padding-left:6mm">'+esc(ph)+'</div></div>'+
     '<div style="flex:1;border-left:1.5px solid #000;display:flex;flex-direction:column;text-align:center"><div style="flex:1;border-bottom:1.5px solid #000;display:flex;flex-direction:column;justify-content:center"><div style="font-size:14pt">Branch Code</div><div style="font-size:24pt">'+esc(d.cc)+'</div></div><div style="flex:1;display:flex;flex-direction:column;justify-content:center"><div style="font-size:14pt">DC NO.</div><div style="font-size:24pt">'+d.dc+'</div></div></div></div>'+
     '<div style="border-top:1.5px solid #000;padding:1mm 3mm;font-size:8pt;text-align:center">FROM: M.R ENTERPRISES, 78/ B1 BLOCK-6 PECHS NEAR IMAM AHMED ROAD KARACHI. &nbsp; PTCL: 021-34555883 &nbsp; MOB: 0300-2760602 &nbsp; '+WA+' 0326-2220447</div></div>';
  }else if(st===1){ /* classic, big address */
    h='<div class="slb" style="font-weight:bold"><div style="text-align:center;font-size:24pt;font-style:italic;text-decoration:underline;padding:1.5mm;border-bottom:1.5px solid #000">M/S HBL</div>'+
     '<div style="flex:1;border-bottom:1.5px solid #000;padding:2mm 4mm;display:flex;flex-direction:column;justify-content:center">'+lab('BRANCH ADDRESS:')+'<div style="font-size:'+asz+';line-height:1.15;text-align:center;font-weight:900;margin-top:1mm">'+esc(addr)+'</div></div>'+
     '<div style="display:flex;border-bottom:1.5px solid #000"><div style="flex:2;padding:1.5mm 3mm;border-right:1.5px solid #000">'+lab('BRANCH NAME:')+'<div style="font-size:'+bsz+'">'+esc(bn)+'</div></div><div style="flex:1;padding:1.5mm 3mm">'+lab('REGION / BRANCH NO:')+'<div style="font-size:12pt">'+esc(reg)+(no?' &nbsp;|&nbsp; '+esc(no):'')+'</div></div></div>'+
     '<div style="display:flex"><div style="flex:2;padding:1.5mm 3mm;border-right:1.5px solid #000">'+lab('NAME / DEPARTMENT:')+'<div style="font-size:14pt">'+esc(per)+'</div>'+lab('CONTACT:')+'<div style="font-size:14pt">'+esc(ph)+'</div></div><div style="flex:1;display:flex"><div style="flex:1;text-align:center;border-right:1.5px solid #000;padding:2mm">'+lab('Branch Code','10pt')+'<div style="font-size:24pt">'+esc(d.cc)+'</div></div><div style="flex:1;text-align:center;padding:2mm">'+lab('DC NO.','10pt')+'<div style="font-size:24pt">'+d.dc+'</div></div></div></div>'+from+'</div>';
  }else if(st===2){ /* address first */
    h='<div class="slb" style="font-weight:bold"><div style="display:flex;border-bottom:1.5px solid #000"><div style="flex:1;font-size:26pt;font-style:italic;padding:1.5mm 4mm">M/S HBL</div><div style="width:34mm;text-align:center;border-left:1.5px solid #000;padding:1mm">'+lab('Branch Code')+'<div style="font-size:20pt">'+esc(d.cc)+'</div></div><div style="width:40mm;text-align:center;border-left:1.5px solid #000;padding:1mm">'+lab('DC NO.')+'<div style="font-size:20pt">'+d.dc+'</div></div></div>'+
     '<div style="flex:1;display:flex;flex-direction:column;justify-content:center;padding:2mm 5mm;text-align:center">'+lab('DELIVER TO:','11pt')+'<div style="font-size:'+bsz+';margin:1mm 0 2mm;text-decoration:underline">'+esc(bn)+'</div><div style="'+box+'padding:3mm 4mm;font-size:'+asz+';line-height:1.15;font-weight:900">'+esc(addr)+'</div></div>'+
     '<div style="display:flex;border-top:1.5px solid #000"><div style="flex:1.2;padding:1.5mm 3mm;border-right:1.5px solid #000">'+lab('NAME / DEPARTMENT')+'<div style="font-size:14pt">'+esc(per)+'</div></div><div style="flex:1;padding:1.5mm 3mm;border-right:1.5px solid #000">'+lab('CONTACT')+'<div style="font-size:14pt">'+esc(ph)+'</div></div><div style="flex:1;padding:1.5mm 3mm">'+lab('REGION / BRANCH NO')+'<div style="font-size:11pt">'+esc(reg)+(no?' | '+esc(no):'')+'</div></div></div>'+from+'</div>';
  }else if(st===3){ /* side panel */
    h='<div class="slb" style="font-weight:bold"><div style="flex:1;display:flex;min-height:0"><div style="flex:2.1;display:flex;flex-direction:column;border-right:2px solid #000"><div style="font-size:22pt;font-style:italic;padding:1.5mm 4mm;border-bottom:1.5px solid #000">M/S HBL</div><div style="flex:1;display:flex;flex-direction:column;justify-content:center;padding:2mm 4mm">'+lab('BRANCH NAME','10pt')+'<div style="font-size:'+bsz+';margin-bottom:2mm">'+esc(bn)+'</div>'+lab('BRANCH ADDRESS','10pt')+'<div style="font-size:'+asz+';line-height:1.15;font-weight:900;margin-top:1mm">'+esc(addr)+'</div></div></div>'+
     '<div style="flex:1;display:flex;flex-direction:column;text-align:center"><div style="flex:1;border-bottom:1.5px solid #000;padding:2mm;display:flex;flex-direction:column;justify-content:center">'+lab('Branch Code','10pt')+'<div style="font-size:24pt">'+esc(d.cc)+'</div></div><div style="flex:1;border-bottom:1.5px solid #000;padding:2mm;display:flex;flex-direction:column;justify-content:center">'+lab('DC NO.','10pt')+'<div style="font-size:24pt">'+d.dc+'</div></div><div style="flex:1.2;padding:2mm;display:flex;flex-direction:column;justify-content:center">'+lab('CONTACT')+'<div style="font-size:12pt">'+esc(per)+'</div><div style="font-size:13pt">'+esc(ph)+'</div>'+(reg?'<div style="font-size:9pt;margin-top:1mm">'+esc(reg)+(no?' | '+esc(no):'')+'</div>':'')+'</div></div></div>'+from+'</div>';
  }else{ /* black band */
    h='<div class="slb" style="font-weight:bold"><div style="background:#000;color:#fff;display:flex;justify-content:space-between;align-items:center;padding:2mm 5mm;-webkit-print-color-adjust:exact;print-color-adjust:exact"><span style="font-size:24pt;font-style:italic">M/S HBL</span><span style="font-size:13pt">DC NO. <span style="font-size:22pt">'+d.dc+'</span> &nbsp;&nbsp; CODE <span style="font-size:22pt">'+esc(d.cc)+'</span></span></div>'+
     '<div style="flex:1;display:flex;flex-direction:column;justify-content:center;text-align:center;padding:2mm 5mm">'+lab('DELIVER TO','11pt')+'<div style="font-size:'+bsz+';margin:1mm 0">'+esc(bn)+'</div><div style="font-size:'+asz+';line-height:1.15;font-weight:900;border-top:3px solid #000;border-bottom:3px solid #000;padding:3mm 0">'+esc(addr)+'</div></div>'+
     '<div style="display:flex;border-top:1.5px solid #000"><div style="flex:1.4;padding:1.5mm 3mm;border-right:1.5px solid #000">'+lab('NAME / DEPARTMENT')+'<div style="font-size:14pt">'+esc(per)+'</div></div><div style="flex:1;padding:1.5mm 3mm;border-right:1.5px solid #000">'+lab('CONTACT')+'<div style="font-size:14pt">'+esc(ph)+'</div></div><div style="flex:1;padding:1.5mm 3mm">'+lab('REGION / BRANCH NO')+'<div style="font-size:11pt">'+esc(reg)+(no?' | '+esc(no):'')+'</div></div></div>'+from+'</div>';
  }
  return '<div class="pg sl">'+h+'</div>';
}
function openPrint(){
  const html=$('pages').innerHTML,css='<link rel="stylesheet" href="'+location.origin+'/static/hbl/hbl.css">'+[...document.querySelectorAll('style')].map(x=>x.outerHTML).join('');
  const w=window.open('','_blank');
  if(!w){msg('The browser blocked the new print window. Allow pop-ups for this file, then press Print again.',true);return;}
  w.document.open();w.document.write('<!doctype html><html><head><meta charset="utf-8"><title>M.R Enterprises - print</title>'+css+'<style>body{background:#fff!important;margin:0}#pages{display:block!important}@media screen{.pg{margin:8px auto;box-shadow:0 0 4px #888}}</style></head><body><div id="pages">'+html+'</div></body></html>');
  w.document.close();
  try{w.focus();}catch(e){}
}
async function make(mode){
  const O=sel();if(!O.length){msg('Tick at least one DC.',true);return;}
  const S=O.map(liveDC).filter(d=>d.lines.length);if(!S.length){msg('All items in the ticked DCs are cancelled.',true);return;}
  const inp=$('date').value,no=$('sumno').value.trim(),inv=$('inv').value.trim(),po=$('po').value;
  const M=mode||'all';const want={sum:M==='all'||M==='nodc',inv:M==='all'||M==='nodc',und:M==='all'||M==='nodc',item:M==='all'||M==='nodc',bill:M==='all'||M==='nodc'||M==='bill',dc:M==='all'||M==='dc',slip:M==='slip'};
  const ck=chkTotals(S,po);if(ck.over&&(want.sum||want.bill||want.item||want.inv)){msg('Cannot print: '+ck.msg,true);return;}
  if(PREVIEW){msg('Press "Create DCs & invoices in the ERP" first, so the pages carry the real numbers.',true);return;}
  const needNo=want.sum||want.inv||want.und;
  if(needNo&&(!no||!inv)){msg('Type the SUMMARY NO and the sales tax invoice no first.',true);return;}
  if(needNo){const okb=await saveBilling(O,po,inp,no,inv,$('isn').value.trim());if(!okb)return;}
  O.forEach(o=>{if(!o.date)o.date=inp;if(needNo){o.sumno=no;o.sinv=inv;}});
  const dOf=d=>pd(d.date||inp),D0=dOf(O[0]);
  const copies=Math.max(1,parseInt($('copies').value)||1),LAB=['CUSTOMER COPY','OFFICE COPY','COPY 3'];
  let P=[];
  if(want.slip)S.forEach(d=>{P.push(slipPage(d));});
  const cpy=(arr,l,st)=>arr.map(x=>x.replace(/^(<div class="pg"[^>]*>)/,'$1<div class="cp" style="'+(st||'')+'">'+l+'</div>'));
  if(want.sum){P=P.concat(cpy(summaryPages(S,D0,no),'CUSTOMER COPY'));P=P.concat(cpy(summaryPages(S,D0,no),'OFFICE COPY (return signed)'));}
  if(want.inv){P=P.concat(cpy(invoicePage(S,D0,inv),'CUSTOMER COPY','left:12mm;right:auto'));P=P.concat(cpy(invoicePage(S,D0,inv),'OFFICE COPY (return signed)','left:12mm;right:auto'));}
  if(want.und)P=P.concat(undertakingPage(S,D0,no,inv));
  if(want.item)P=P.concat(itemPages(S,D0,po,$('isn').value.trim()));
  S.forEach(d=>{const D=dOf(d);if(want.bill)P=P.concat(billPages(d,D));if(want.dc)for(let c=0;c<copies;c++)P=P.concat(dcPages(d,D,copies>1?LAB[c]:''));});
  $('pgsize').textContent='@media print{@page{size:'+(want.slip?'A5 landscape':'A4')+';margin:0}}';
  $('pages').innerHTML=P.join('');$('pages').style.display='block';
  if(needNo){S.forEach(d=>addBilling(d,no,inv,inp));ls('hbl_sumno',no);ls('hbl_inv',inv);}
  if(PARSED){const all=dcList();if(all.length)ls('hbl_lastdc',String(all[all.length-1].dc));}
  $('out').innerHTML='<div class="card"><h3>'+P.length+' pages ready</h3><div class="tot">A new window has opened with the pages \u2014 this window stays as it is. In that window press <b>Ctrl+P</b> to print or save as PDF. In the print window pick <b>A4</b> and <b>Margins: None</b>.</div><div class="row" style="margin-top:10px"><button type="button" id="pr">Print again (new window)</button></div></div>';
  $('pr').addEventListener('click',()=>openPrint());
  openPrint();
  $('out').scrollIntoView();
}
async function saveRecord(){
  const wb=new ExcelJS.Workbook(),ds=wb.addWorksheet('DATA');
  const H=['DATE','PO NO','DC NO','INVOICE NO','REQ NO','BRANCH CODE','BRANCH NAME','CONTACT PERSON','PHONE','SE CODE','ITEM','UNIT','PO QTY','QTY','PRICE','AMOUNT EXCL TAX','TAX %','TAX VALUE','TOTAL INCL TAX','SUMMARY NO','SALES TAX INV','STATUS'];
  const hr=ds.addRow(H);hr.font={bold:true,color:{argb:'FFFFFFFF'}};hr.eachCell(c=>c.fill={type:'pattern',pattern:'solid',fgColor:{argb:'FF1F4E78'}});
  const pos=Object.keys(byPO).sort((a,b)=>{const x=parseInt(a.split('-')[1]),y=parseInt(b.split('-')[1]);return isNaN(x)||isNaN(y)?a.localeCompare(b):x-y;});
  const DCs=[];pos.forEach(p=>Object.values(byPO[p]).sort((a,b)=>a.dc-b.dc).forEach(d=>DCs.push(d)));
  const inp=$('date').value;let r=1;const itemAgg=new Map();
  DCs.forEach(d=>{if(!d.date&&d.sumno)d.date=inp;});
  DCs.forEach(d=>d.lines.forEach(l=>{r++;const q=l.cancelled?0:l.qty,amt=q*l.price,tv=amt*l.tax;
    ds.addRow([d.date?mkDate(d.date):'',d.po,d.dc,d.inv,Number(d.req)||d.req,d.cc,d.loc,d.person||'',d.phone||'',l.code,l.name,l.unit,l.origQty,q,l.price,
      {formula:'N'+r+'*O'+r,result:amt},l.tax,{formula:'P'+r+'*Q'+r,result:tv},{formula:'P'+r+'+R'+r,result:amt+tv},d.sumno?(Number(d.sumno)||d.sumno):'',d.sinv?(Number(d.sinv)||d.sinv):'',l.cancelled?'CANCELLED':'DELIVERED']);
    if(!l.cancelled&&q>0){const k=(d.sumno||'PENDING')+'|'+d.po+'|'+l.code;let a=itemAgg.get(k);if(!a){a={sum:d.sumno||'PENDING',po:d.po,code:l.code,name:(NAMES[l.code]&&NAMES[l.code][0])||l.name,unit:l.unit,price:l.price,tax:l.tax,qty:0};itemAgg.set(k,a);}a.qty+=q;}}));
  ds.getColumn(1).numFmt='dd-mmm-yy';[15,16,18,19].forEach(c=>ds.getColumn(c).numFmt='#,##0.00');ds.getColumn(17).numFmt='0%';
  ds.columns.forEach((c,i)=>c.width=[11,11,9,10,9,9,34,16,13,12,34,6,8,8,9,13,7,11,13,10,10,11][i]);
  ds.views=[{state:'frozen',ySplit:1}];ds.autoFilter={from:'A1',to:'V1'};
  const HD=row=>{row.font={bold:true,color:{argb:'FFFFFFFF'}};row.eachCell(c=>c.fill={type:'pattern',pattern:'solid',fgColor:{argb:'FF1F4E78'}});};
  const nz=x=>{const n=Number(x);return x!==''&&!isNaN(n)?n:x;};
  const bsorted=BILLS.slice().sort((x,y)=>(Number(x.sumno)||0)-(Number(y.sumno)||0)||x.dc-y.dc);
  // BILLINGS: one row per line per billing (a DC billed twice shows twice, each with its own summary / GST no)
  const bl=wb.addWorksheet('BILLINGS');HD(bl.addRow(['DATE','PO NO','DC NO','INVOICE NO','REQ NO','BRANCH CODE','BRANCH NAME','SE CODE','ITEM','UNIT','QTY','PRICE','AMOUNT EXCL TAX','TAX %','TAX VALUE','TOTAL INCL TAX','SUMMARY NO','SALES TAX INV']));
  let br=1;
  bsorted.forEach(b=>b.lines.forEach(l=>{br++;const e=l.qty*l.price,t=e*l.tax;bl.addRow([b.date?mkDate(b.date):'',b.po,b.dc,b.inv,Number(b.req)||b.req,b.cc,b.loc,l.code,l.name,l.unit,l.qty,l.price,{formula:'K'+br+'*L'+br,result:e},l.tax,{formula:'M'+br+'*N'+br,result:t},{formula:'M'+br+'+O'+br,result:e+t},nz(b.sumno),nz(b.sinv)]);}));
  bl.getColumn(1).numFmt='dd-mmm-yy';[12,13,15,16].forEach(c=>bl.getColumn(c).numFmt='#,##0.00');bl.getColumn(14).numFmt='0%';
  bl.columns.forEach((c,i)=>c.width=[11,11,9,10,9,9,34,12,34,6,8,9,13,7,11,13,10,10][i]);bl.views=[{state:'frozen',ySplit:1}];bl.autoFilter={from:'A1',to:'R1'};
  const blast=Math.max(2,br);
  // BRANCH SUMMARY: one row per billing (+ DCs not billed yet)
  const bs=wb.addWorksheet('BRANCH SUMMARY');
  HD(bs.addRow(['SUMMARY NO','DATE','BR. / COST CODE','DC NO.','INVOICE NO.','RQ. NO.','P.O NO.','BRANCH NAME / DEPARTMENT','EXEMPTED AMOUNT','AMOUNT WITHOUT GST','GST AMOUNT','NET AMOUNT','SALES TAX INV','STATUS']));
  bsorted.forEach(b=>{const t={lines:b.lines};tot(t);bs.addRow([nz(b.sumno),b.date?mkDate(b.date):'',b.cc,b.dc,b.inv,Number(b.req)||b.req,b.po,b.loc,t.nontax,t.ex,t.gst,t.net,nz(b.sinv),'BILLED']);});
  DCs.forEach(d=>{if(billedOn(d.po,d.dc).length)return;const lv=liveDC(d);bs.addRow(['',d.date?mkDate(d.date):'',d.cc,d.dc,d.inv,Number(d.req)||d.req,d.po,d.loc,lv.nontax,lv.ex,lv.gst,lv.net,'',lv.lines.length?'NOT YET BILLED':'CANCELLED']);});
  bs.getColumn(2).numFmt='dd-mmm-yy';[9,10,11,12].forEach(c=>bs.getColumn(c).numFmt='#,##0.00');bs.columns.forEach((c,i)=>c.width=[11,11,9,9,10,9,11,40,11,14,11,12,10,14][i]);bs.views=[{state:'frozen',ySplit:1}];bs.autoFilter={from:'A1',to:'N1'};
  // ITEM SUMMARY: per summary no / PO / item
  const agg=new Map();
  bsorted.forEach(b=>b.lines.forEach(l=>{const k=b.sumno+'|'+b.po+'|'+l.code+'|'+l.price;let a=agg.get(k);if(!a){a={sum:b.sumno,po:b.po,code:l.code,name:(NAMES[l.code]&&NAMES[l.code][0])||l.name,unit:l.unit,price:l.price,tax:l.tax,qty:0};agg.set(k,a);}a.qty+=l.qty;}));
  const is=wb.addWorksheet('ITEM SUMMARY');
  HD(is.addRow(['SUMMARY NO','P.O NO.','SE CODE','NAME OF ITEMS','UNIT','QTY','PRICE','AMOUNT EXCL TAX','TAX %','TAX VALUE','TOTAL INCL TAX']));
  [...agg.values()].forEach(a=>{const e=a.qty*a.price,t=e*a.tax;is.addRow([nz(a.sum),a.po,a.code,a.name,a.unit,a.qty,a.price,e,a.tax,t,e+t]);});
  [7,8,10,11].forEach(c=>is.getColumn(c).numFmt='#,##0.00');is.getColumn(9).numFmt='0%';is.columns.forEach((c,i)=>c.width=[11,11,12,40,6,8,10,14,7,12,14][i]);is.views=[{state:'frozen',ySplit:1}];is.autoFilter={from:'A1',to:'K1'};
  // PO SUMMARY (live SUMIFS on BILLINGS = what is actually billed)
  const ps=wb.addWorksheet('PO SUMMARY');
  HD(ps.addRow(['P.O NO.','BILLINGS','QTY BILLED','AMOUNT EXCL TAX','TAX VALUE','TOTAL INCL TAX','PO AMOUNT EXCL TAX','PO AMOUNT INCL TAX','NOT YET BILLED (EXCL)']));
  let R=1;const T=[0,0,0,0,0];
  pos.forEach(p=>{R++;const B=BILLS.filter(b=>b.po===p);let q=0,e=0,g=0;B.forEach(b=>{const t={lines:b.lines};tot(t);b.lines.forEach(l=>q+=l.qty);e+=t.ex;g+=t.gst;});
    T[0]+=B.length;T[1]+=q;T[2]+=e;T[3]+=g;T[4]+=e+g;const pe=POTOT[p]&&POTOT[p].excl!=null?POTOT[p].excl:'';
    ps.addRow([p,B.length,{formula:'SUMIFS(BILLINGS!K2:K'+blast+',BILLINGS!B2:B'+blast+',A'+R+')',result:q},{formula:'SUMIFS(BILLINGS!M2:M'+blast+',BILLINGS!B2:B'+blast+',A'+R+')',result:e},{formula:'SUMIFS(BILLINGS!O2:O'+blast+',BILLINGS!B2:B'+blast+',A'+R+')',result:g},{formula:'SUMIFS(BILLINGS!P2:P'+blast+',BILLINGS!B2:B'+blast+',A'+R+')',result:e+g},pe,POTOT[p]&&POTOT[p].incl!=null?POTOT[p].incl:'',pe===''?'':{formula:'G'+R+'-D'+R,result:pe-e}]);});
  R++;const tr=ps.addRow(['TOTAL',{formula:'SUM(B2:B'+(R-1)+')',result:T[0]},{formula:'SUM(C2:C'+(R-1)+')',result:T[1]},{formula:'SUM(D2:D'+(R-1)+')',result:T[2]},{formula:'SUM(E2:E'+(R-1)+')',result:T[3]},{formula:'SUM(F2:F'+(R-1)+')',result:T[4]}]);tr.font={bold:true};
  [4,5,6,7,8,9].forEach(c=>ps.getColumn(c).numFmt='#,##0.00');ps.columns.forEach((c,i)=>c.width=[12,10,11,16,14,16,18,18,20][i]);
  const buf=await wb.xlsx.writeBuffer();const a=document.createElement('a');a.href=URL.createObjectURL(new Blob([buf],{type:'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'}));const nw=new Date(),fn='HBL_RECORD_'+('0'+nw.getDate()).slice(-2)+'-'+MON[nw.getMonth()]+'-'+nw.getFullYear()+'.xlsx';a.download=fn;document.body.appendChild(a);a.click();setTimeout(()=>{URL.revokeObjectURL(a.href);a.remove();},4000);
  msg('Record saved as '+fn+' \u2014 next time load the newest dated record file together with the new PO.');
}
async function xl(){
  const S=sel();if(!S.length){msg('Tick at least one DC.',true);return;}
  const D=$('date').value,no=parseInt($('sumno').value)||'';
  const wb=new ExcelJS.Workbook(),ws=wb.addWorksheet('REGISTER');
  ws.addRow(['SR. NO.','BR. / COST CODE','DC NO.','INOVICE NO.','RQ. NO.','P.O NO.','BRANCH NAME / DEPARTMENT','EXEMPTED AMOUNT','AMOUNT WITHOUT GST','GST AMOUNT','NET AMOUNT','SUM#','SUMMERY DATE','SUMMERY TYPE']).font={bold:true};
  S.forEach((d,i)=>ws.addRow([i+1,d.cc,d.dc,d.inv,Number(d.req)||d.req,d.po,d.loc,d.nontax,d.ex,d.gst,d.net,no,mkDate(D),'STATIONERY']));
  ws.getColumn(13).numFmt='dd-mmm-yy';[8,9,10,11].forEach(c=>ws.getColumn(c).numFmt='0.00');
  ws.columns.forEach((c,i)=>c.width=[7,12,9,12,10,12,44,12,14,12,12,8,13,14][i]);
  const buf=await wb.xlsx.writeBuffer();const a=document.createElement('a');a.href=URL.createObjectURL(new Blob([buf]));a.download='SUMMARY_'+no+'_register_rows.xlsx';document.body.appendChild(a);a.click();setTimeout(()=>a.remove(),3000);
}
async function many(fs){const a=[...fs].sort((x,y)=>(/\.pdf$/i.test(x.name)?1:0)-(/\.pdf$/i.test(y.name)?1:0));for(const f of a)await load(f);}
$('file').addEventListener('change',e=>{if(e.target.files.length)many(e.target.files);});
const dz=$('drop');dz.addEventListener('dragover',e=>{e.preventDefault();dz.classList.add('over');});dz.addEventListener('dragleave',()=>dz.classList.remove('over'));
dz.addEventListener('drop',e=>{e.preventDefault();dz.classList.remove('over');if(e.dataTransfer.files.length)many(e.dataTransfer.files);});
$('po').addEventListener('change',()=>{const v=$('po').value;if(PREVIEW&&PARSED&&PARSED.header.po===v)fillDC();else loadServerPO(v).catch(e=>msg(e.message,true));});$('create').addEventListener('click',createInErp);$('dc0').addEventListener('change',()=>{if(PARSED)buildFromPdf();});$('cap').addEventListener('change',()=>{if(PARSED)buildFromPdf();});$('all').addEventListener('click',()=>setAll(true));$('none').addEventListener('click',()=>setAll(false));
$('rng').addEventListener('click',()=>{const a=+$('from').value,b=+$('to').value;document.querySelectorAll('.ck').forEach(c=>c.checked=(+c.value>=a&&+c.value<=b));upd();});
$('go').addEventListener('click',()=>make());$('goND').addEventListener('click',()=>make('nodc'));$('goSlip').addEventListener('click',()=>make('slip'));$('goDC').addEventListener('click',()=>make('dc'));$('goBill').addEventListener('click',()=>make('bill'));$('xl').addEventListener('click',xl);
window.__t={sel,fillDC,slipPage,dcList};

(async function init(){
  try{
    const L=await api('/hbl/api/lookup');NAMES=L.NAMES;PRICES=L.PRICES;ADDR=L.ADDR;
    if(!L.customer){msg('Choose the HBL customer on the "HBL PO pack" page first.',true);return;}
    const ps=await api('/hbl/api/pos');
    if(ps.pos.length){const s=$('po');s.innerHTML='';ps.pos.forEach(p=>{const o=document.createElement('option');o.value=o.textContent=p;s.appendChild(o);});
      $('date').value=new Date().toISOString().slice(0,10);$('step2').style.display='block';await loadServerPO(ps.pos[ps.pos.length-1]);msg('Saved POs are listed. Drop a new PO PDF to bill a new one.');}
  }catch(e){msg(e.message,true);}
})();
})();