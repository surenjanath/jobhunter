// core.js — code every page shares: DOM/format helpers, page navigation, app state (JOBS, SETTINGS), the header/dock
// status, and the scan/log runner. Page scripts (home.js, ledger.js, analytics.js …) build on this; none of them talk
// to each other except through these globals. Load order is set in templates/layout.html.

const $=s=>document.querySelector(s);
let JOBS=[], POLL=null, CURSOR=0;
let SETTINGS={preferences:{show_remote:true,remote_only:false,show_links:true,show_salary:true,hide_blockers:false,local_only_default:false},sources:{},filters:{},links:{}};
const PAGE=document.body.dataset.page||'home';

// ---- fetch + formatting ---------------------------------------------------------------------------------------------
// Always JSON, never a cryptic "Unexpected token '<'": a non-JSON reply becomes a readable error.
async function jfetch(url, opts){
  const r=await fetch(url, opts);
  const ct=r.headers.get('content-type')||'';
  if(!ct.includes('application/json')){
    const txt=await r.text();
    throw new Error(`Expected JSON from ${url} but got ${r.status} ${ct||'unknown-type'}: ${txt.slice(0,120).replace(/\n/g,' ')} — is Django running? Check /health/`);
  }
  const d=await r.json();
  if(!r.ok) throw new Error(d.error||d.detail||`HTTP ${r.status} from ${url}`);
  return d;
}
const esc=s=>String(s??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const tierClass=n=> n>=65?'t1':n>=50?'t2':'t3';
const GOOD=/good\)/i, BAD=/clearance|citizens only|permanent residency|10\+|PhD|no sponsorship|Non-engineering/i;
const flagClass=f=> GOOD.test(f)?'g':BAD.test(f)?'b':'';
const isLocal=j=> !!j.region || /trinidad|tobago/i.test(j.location||'');
const isRemote=j=> !isLocal(j) && (j.work_mode==='remote' || (!j.work_mode && j.remote));
const likeOf=j=> (j.likelihood && typeof j.likelihood==='object')? j.likelihood : null;
const daysLeftLabel=j=> j.days_left==null?'':(j.days_left<0?'closed':j.days_left===0?'closes today':`${j.days_left}d left`);
function fillSelect(sel,label,values){ const el=$(sel); if(!el) return; const cur=el.value; el.innerHTML=`<option value="">${label}</option>`+values.map(v=>`<option ${v===cur?'selected':''}>${esc(v)}</option>`).join(''); }

// ---- navigation: every page is its own URL (window.URLS comes from the template) -------------------------------------
const URLS=window.URLS||{};
function pageUrl(view, params){
  const qs=params?'?'+new URLSearchParams(Object.fromEntries(Object.entries(params).filter(([,v])=>v!==''&&v!=null&&v!==false))):'';
  return (URLS[view]||'/')+qs;
}
function goto(view, params){ location.href=pageUrl(view, params); }
const showView=goto;                       // older call sites
const CYCLE=['home','jobs','pipeline'];    // ← → keys and the dock arrows

// ---- theme ---------------------------------------------------------------------------------------------------------
function setTheme(t){ document.documentElement.setAttribute('data-theme',t); try{ localStorage.setItem('jh_theme',t); }catch(e){} document.dispatchEvent(new CustomEvent('themechange')); }
(function(){ let t='light'; try{ t=localStorage.getItem('jh_theme')||'light'; }catch(e){} document.documentElement.setAttribute('data-theme',t); })();

// ---- shell state: one call fills the header, banners and dock on every page ------------------------------------------
async function loadAlerts(){
  try{
    const f=await jfetch('/api/followups/'); const c=f.counts||{}; const bits=[];
    if(c.overdue) bits.push(`${c.overdue} follow-up${c.overdue>1?'s':''} overdue`);
    if(c.closing_soon) bits.push(`${c.closing_soon} tracked role${c.closing_soon>1?'s':''} closing within a week`);
    const el=$('#alerts'); if(el) el.innerHTML=bits.length?`<div class="banner">${esc(bits.join(' · '))}. <a href="${pageUrl('pipeline')}">Open pipeline</a></div>`:'';
  }catch(e){}
}
async function loadState(){
  const d=await jfetch('/api/state/'); JOBS=d.jobs||[];
  $('#meta').textContent=d.generated?new Date(d.generated).toLocaleDateString(undefined,{month:'short',day:'numeric'}):'';
  let healthy=false;
  try{ const h=await jfetch('/health/'); healthy=!!h.ok; $('#healthDot').className='health'+(h.ok?'':' bad'); $('#healthDot').title=h.ok?`ok · ${h.jobs} jobs`:'down'; }catch(e){ $('#healthDot').className='health bad'; }
  const bk=d.backends||{};
  $('#backends').innerHTML=Object.entries(bk).filter(([,v])=>v&&typeof v==='object').map(([k,v])=>`${esc(k)} ${v.available?'ready':'off'}`).join('  ·  ');
  if(d.provider) $('#prov').value=d.provider; $('#providerPill').textContent=d.provider||'auto';
  $('#dbInfo').textContent=`DB: ${d.stats?d.stats.total:JOBS.length} jobs`;
  const anyLLM=Object.entries(bk).some(([k,v])=>k!=='template'&&v&&v.available);
  const b=[];
  if(!d.sheet_configured) b.push('<div class="banner">Sheet is not connected. Set SHEET_ID in the environment before sync.</div>');
  if(!anyLLM) b.push('<div class="banner">Letters are in template mode. Choose Ollama or Claude from the provider menu.</div>');
  $('#banners').innerHTML=b.join('');
  if(d.sheet_id){ $('#sheetLink').href=`https://docs.google.com/spreadsheets/d/${d.sheet_id}/edit`; $('#sheetLink').hidden=false; }
  d.counts={roles:JOBS.length, t1:JOBS.filter(j=>j.fit_score>=65).length, t2:JOBS.filter(j=>j.fit_score>=50&&j.fit_score<65).length, blocked:JOBS.filter(j=>BAD.test(j.flags||'')).length};
  const mark=(n,on)=>{ const m=document.querySelector(`[data-mark="${n}"]`); if(m) m.classList.toggle('on',on); };
  mark('block',d.counts.blocked>0); mark('health',healthy); mark('sheet',!!d.sheet_configured); mark('live',anyLLM);
  $('#footStats').textContent=`${JOBS.length} jobs · ${d.counts.t1} tier-1`; $('#navJobs').textContent=JOBS.length;
  setBusy(d.busy);
  return d;
}

// ---- scan / sync / live check / tests: run in the background, stream the log --------------------------------------------
function showLive(title){
  const box=$('#live'); if(box) box.hidden=false;
  const t=$('#liveTitle'); if(t) t.textContent=title;
  const s=$('#liveStatus'); if(s){ s.textContent=title; s.classList.add('busy'); }
}
function setBusy(busy){
  ['#bScan','#bSync','#bLive','#bTests'].forEach(id=>{ const el=$(id); if(el) el.disabled=busy; });
  const s=$('#liveStatus');
  if(s && !busy && !String(s.textContent).startsWith('Failed')){ s.textContent='Idle'; s.classList.remove('busy'); }
  if(busy&&!POLL) POLL=setInterval(pollLogs,700);
}
async function pollLogs(){
  const d=await jfetch('/api/logs/?since='+CURSOR);
  if(d.lines.length){
    CURSOR=d.next;
    const c=$('#console');
    c.insertAdjacentHTML('beforeend',d.lines.map(l=>{const cls=/\[FAIL\]|!!!|Traceback|FAILED|\bERROR\b/.test(l)?'bad':/\[OK  \]|\[PASS\]|passed|finished, exit code 0/.test(l)?'ok':/\[WARN\]|WARN|warning/i.test(l)?'warn':''; return `<span class="${cls}">${esc(l)}</span>\n`;}).join(''));
    c.scrollTop=c.scrollHeight;
    const last=d.lines[d.lines.length-1];
    if(last) showLive(last.slice(0,80));
  }
  if(!d.busy){
    clearInterval(POLL); POLL=null; setBusy(false);
    const label=d.returncode===0?'Finished':'Finished with errors';
    const t=$('#liveTitle'); if(t) t.textContent=label;
    const s=$('#liveStatus'); if(s){ s.textContent=label; s.classList.remove('busy'); }
    await refreshPage();
  }
}
async function launch(url,body,btn){
  const label=url.includes('live')?'Checking sources…':url.includes('tests')?'Running tests…':(body&&body.dry_run===false?'Syncing…':'Scanning…');
  showLive(label);
  $('#console').textContent=label+'\n';
  CURSOR=0;
  if(btn){ btn.dataset.idle=btn.dataset.idle||btn.textContent; btn.textContent='Working…'; }
  try{
    const d=await jfetch(url,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body||{})});
    if(!d.ok) throw new Error(d.error||'Could not start');
    showLive(d.task||label);
    setBusy(true);
  }catch(e){
    showLive('Failed: '+e.message);
    $('#console').textContent+=e.message+'\n';
    const s=$('#liveStatus'); if(s){ s.textContent='Failed'; s.classList.remove('busy'); }
  }finally{
    if(btn && btn.dataset.idle) btn.textContent=btn.dataset.idle;
  }
}

// ---- page lifecycle -------------------------------------------------------------------------------------------------
// A page script defines PAGE_HOOKS = { beforeLoad?(), init(state), refresh?(state) }. boot.js runs them:
//   beforeLoad → loadState() → init(state), then refresh(state) every 20s while nothing is running.
const PAGE_HOOKS={};
async function refreshPage(){
  const d=await loadState();
  if(PAGE_HOOKS.refresh) await PAGE_HOOKS.refresh(d); else if(PAGE_HOOKS.init) await PAGE_HOOKS.init(d);
  loadAlerts();
  return d;
}
function exportCsv(rows){
  const cols=["fit_score","tier","title","company","region","location","category","salary","source","posted_at","expires_at","app_status","url","why","flags"];
  const csv=[cols.join(",")].concat(rows.map(j=>cols.map(k=>`"${String(j[k]||'').replace(/"/g,'""')}"`).join(","))).join("\n");
  const a=document.createElement("a"); a.href=URL.createObjectURL(new Blob([csv],{type:"text/csv"})); a.download=`jobhunt_${new Date().toISOString().slice(0,10)}.csv`; a.click();
}

// header + dock controls that exist on every page
function wireShell(){
  const th=$('#navTheme'); if(th) th.onclick=()=>setTheme(document.documentElement.getAttribute('data-theme')==='dark'?'light':'dark');
  const ex=$('#navExport'); if(ex) ex.onclick=e=>{ e.preventDefault(); exportCsv(typeof filtered==='function'?filtered():JOBS); };
  const pv=$('#prov'); if(pv) pv.onchange=()=>jfetch('/api/provider/',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({provider:pv.value})}).catch(e=>toast(e.message,'bad'));
  const run=(id,url,body)=>{ const b=$(id); if(b) b.onclick=()=>launch(url,body,b); };
  run('#bScan','/api/scan/',{dry_run:true}); run('#bSync','/api/scan/',{dry_run:false}); run('#bLive','/api/live-check/',{}); run('#bTests','/api/tests/',{});
  const step=d=>{ const i=CYCLE.indexOf(PAGE); goto(CYCLE[((i<0?0:i)+d+CYCLE.length)%CYCLE.length]); };
  const pr=$('#cyclePrev'), nx=$('#cycleNext'); if(pr) pr.onclick=()=>step(-1); if(nx) nx.onclick=()=>step(1);
  const logBtn=$('#logToggle'), live=$('#live');
  if(logBtn&&live) logBtn.onclick=()=>{ live.hidden=!live.hidden; if(!live.hidden&&!$('#console').textContent) $('#console').textContent='No run yet. Press Scan.\n'; };
  const lc=$('#liveClose'); if(lc&&live) lc.onclick=()=>{ live.hidden=true; };
  document.addEventListener('keydown',e=>{
    if(e.target&&/INPUT|TEXTAREA|SELECT/.test(e.target.tagName)){ if(e.key==='Escape') e.target.blur(); return; }
    if(document.querySelector('dialog[open]')) return;
    if(typeof PAGE_HOOKS.key==='function' && PAGE_HOOKS.key(e)) return;
    if(e.key==='ArrowRight') step(1);
    if(e.key==='ArrowLeft') step(-1);
  });
}
