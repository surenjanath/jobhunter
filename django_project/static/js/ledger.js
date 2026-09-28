// ledger.js — the Ledger page: filters, table, board view. Shared helpers live in core.js / job.js.
let SORT={key:'fit_score',dir:-1}, MODE='all', FOCUS=-1, ROWS=[], KANBAN=false;
function setMode(m){ MODE=m; document.querySelectorAll('#modeSeg button').forEach(b=>b.classList.toggle('on',b.dataset.mode===m)); render(); if(!$('#kanbanWrap').hidden) renderKanban(); }
function filtered(){
  const region=$('#regionSel')?$('#regionSel').value:'', cat=$('#catSel')?$('#catSel').value:'', closing=$('#closingSoon')&&$('#closingSoon').checked, starOnly=$('#starOnly')&&$('#starOnly').checked;
  const q=$('#q').value.toLowerCase().trim(), min= +$('#tier').value||0, src=$('#src').value, status=$('#statusFilter').value, clean=$('#clean').checked, likeMin=+($('#likeSel')?$('#likeSel').value:0)||0, sort=$('#sortSel').value;
  const prefs=SETTINGS.preferences||{};
  const hideRemote=prefs.show_remote===false;
  const remoteOnly=prefs.remote_only===true;
  const hideBlockersByDefault=prefs.hide_blockers===true;
  let rows=JOBS.filter(j=>{
    if(j.fit_score<min) return false;
    if(src && !(j.source||'').startsWith(src)) return false;
    if((clean||hideBlockersByDefault) && BAD.test(j.flags||'')) return false;
    if(status && (j.app_status||'New')!==status) return false;
    if(hideRemote && j.remote) return false;
    if(remoteOnly && !j.remote) return false;
    if(MODE==='local' && !isLocal(j)) return false;
    if(MODE==='remote' && !isRemote(j)) return false;
    if(MODE==='onsite' && (isLocal(j) || isRemote(j))) return false;
    if(likeMin && (likeOf(j)?likeOf(j).likelihood:0)<likeMin) return false;
    if(region && j.region!==region) return false;
    if(cat && j.category!==cat) return false;
    if(closing && !(j.days_left!=null && j.days_left>=0 && j.days_left<=7)) return false;
    if(starOnly && !j.starred) return false;
    if(q){const hay=`${j.title} ${j.company} ${j.location} ${j.region||''} ${j.category||''} ${j.why} ${j.flags} ${j.app_status||''}`.toLowerCase(); if(!hay.includes(q)) return false;}
    return true;
  });
  if(sort==='likelihood'){ rows.sort((a,b)=> (likeOf(b)?likeOf(b).likelihood:-1) - (likeOf(a)?likeOf(a).likelihood:-1) || b.fit_score-a.fit_score); }
  else if(sort==='chance'){ rows.sort((a,b)=> (b.interview_chance||0)-(a.interview_chance||0) || b.fit_score-a.fit_score); }
  else if(sort==='recent'){ rows.sort((a,b)=> (b.posted_at||'').localeCompare(a.posted_at||'')); }
  else if(sort==='new'){ rows.sort((a,b)=> (b.first_seen||'').localeCompare(a.first_seen||'') || b.fit_score-a.fit_score); }
  else if(sort==='closing'){ rows.sort((a,b)=> (a.days_left==null?9999:a.days_left)-(b.days_left==null?9999:b.days_left)); }
  else { rows.sort((a,b)=>{const k=SORT.key; let va=a[k]??'', vb=b[k]??''; if(k==='likelihood'){ va=likeOf(a)?likeOf(a).likelihood:-1; vb=likeOf(b)?likeOf(b).likelihood:-1; } return typeof va==='number' ? (va-vb)*SORT.dir : String(va).localeCompare(String(vb))*SORT.dir;});}
  return rows;
}
function verdictPill(j){
  const l=likeOf(j); if(!l) return `<span class="flag">—</span>`;
  const cls=l.verdict==='Long shot'?'Long':l.verdict;
  return `<span class="pill ${cls}" title="${esc(l.advice||'')}">${esc(l.verdict)}</span><div class="co">~${l.interview_chance}% interview</div>`;
}
function whereCell(j){
  const tags=[];
  if(isLocal(j)) tags.push(`<span class="tag">🇹🇹 ${esc(j.region||'T&T')}</span>`);
  else if(j.work_mode==='remote') tags.push(`<span class="tag ${['us_only','eu_only','canada_only'].includes(j.remote_scope)?'bad':''}">Remote${j.remote_scope&&j.remote_scope!=='unknown'?' · '+esc({worldwide:'worldwide',americas:'Americas',us_only:'US only',eu_only:'EU/UK only',canada_only:'Canada only'}[j.remote_scope]||j.remote_scope):''}</span>`);
  else if(j.work_mode) tags.push(`<span class="tag">${esc(j.work_mode==='onsite'?'On-site':j.work_mode==='hybrid'?'Hybrid':j.work_mode)}</span>`);
  const loc=isLocal(j)?'':`<div class="co">${esc((j.location||'').slice(0,42))}</div>`;
  return `${tags.join('')}${loc}${j.category?`<div class="co">${esc(j.category)}</div>`:''}`;
}
function render(){
  const rows=filtered(); ROWS=rows; FOCUS=-1;
  const cnt=$('#rowCount'); if(cnt) cnt.textContent=JOBS.length?`${rows.length} of ${JOBS.length}`:'';
  if(!JOBS.length){$('#tableWrap').innerHTML=`<div class="empty">No results. <b>Run scan</b> or <code>python -m src.run --dry-run</code></div>`;return;} if(!rows.length){$('#tableWrap').innerHTML=`<div class="empty">No matches. <button type="button" class="text" id="clearFilters">Clear filters</button></div>`; const c=$('#clearFilters'); if(c) c.onclick=clearFilters; return;}
  const th=(k,l,title='')=>`<th data-k="${k}" title="${esc(title)}">${l}${SORT.key===k?(SORT.dir<0?' ↓':' ↑'):''}</th>`;
  const showLinks=(SETTINGS.preferences||{}).show_links!==false;
  $('#tableWrap').innerHTML=`<table><thead><tr><th class="selcol"><input type="checkbox" id="selAll" aria-label="Select all" title="Select all shown"></th><th></th>${th('fit_score','Fit','How well the role matches your resume')}${th('title','Role')}${th('company','Company')}${th('region','Where')}${th('likelihood','Odds','Your chance relative to a typical applicant')}${th('posted_at','Posted')}<th>Status</th><th></th></tr></thead><tbody>${rows.map((j,i)=>{
    const linkBtn=showLinks?` <a href="${esc(j.url)}" target="_blank" rel="noopener"><button class="sm" title="Open posting">↗</button></a>`:'';
    const dl=daysLeftLabel(j);
    const blocked=(likeOf(j)&&likeOf(j).blockers&&likeOf(j).blockers.length)?`<div class="co urgent" title="${esc(likeOf(j).blockers.join(' · '))}">⚠ ${esc(likeOf(j).blockers[0].slice(0,64))}</div>`:'';
    return `<tr data-row="${i}" data-details="${esc(j.job_id)}" class="jrow">
      <td class="selcol"><input type="checkbox" data-sel="${esc(j.job_id)}" aria-label="Select"></td>
      <td><button type="button" class="star ${j.starred?'on':''}" data-star="${esc(j.job_id)}" title="Star (s)" aria-label="Star">${j.starred?'★':'☆'}</button></td>
      <td><span class="fit ${tierClass(j.fit_score)}">${j.fit_score}</span><span class="fitbar"><i style="width:${Math.min(100,j.fit_score)}%"></i></span></td>
      <td><div class="role" data-details="${esc(j.job_id)}">${esc(j.title)}</div><div class="co">${esc((j.why||'').slice(0,96))}</div>${blocked}${j.salary?`<div class="co">💰 ${esc(j.salary)}</div>`:''}</td>
      <td><button type="button" class="linklike" data-company="${esc(j.company)}" title="All roles at this employer">${esc(j.company)}</button><div class="co">${esc((j.source||'').split(':')[0])}</div></td>
      <td>${whereCell(j)}</td>
      <td>${verdictPill(j)}</td>
      <td class="co">${esc(j.posted_at||'—')}${dl?`<div class="co ${j.days_left!=null&&j.days_left<=3?'urgent':''}">${esc(dl)}</div>`:''}</td>
      <td><select class="status-sel" data-status="${esc(j.job_id)}">${["New","Shortlisted","Applied","Interviewing","Offer","Rejected","Passed on it"].map(o=>`<option ${o===(j.app_status||'New')?'selected':''}>${o}</option>`).join('')}</select></td>
      <td style="white-space:nowrap"><button class="sm" data-details="${esc(j.job_id)}">Match</button> <button class="sm" data-cover="${esc(j.job_id)}">Letter</button>${linkBtn}</td>
    </tr>`}).join('')}</tbody></table>`;
  document.querySelectorAll('th[data-k]').forEach(el=>el.onclick=()=>{const k=el.dataset.k; SORT={key:k,dir:SORT.key===k?-SORT.dir:(k==='fit_score'||k==='likelihood'?-1:1)}; $('#sortSel').value='fit'; render();});
  document.querySelectorAll('[data-star]').forEach(el=>el.onclick=e=>{e.stopPropagation(); toggleStar(el.dataset.star,el);});
  document.querySelectorAll('[data-cover]').forEach(el=>el.onclick=e=>{e.stopPropagation(); draftLetter(el.dataset.cover, el);});
  document.querySelectorAll('#tableWrap [data-details]').forEach(el=>el.onclick=e=>{ if(e.target.closest('select,a,[data-star],[data-cover]')) return; openJob(el.dataset.details); });
  document.querySelectorAll('.jrow a').forEach(a=>a.onclick=e=>e.stopPropagation());
  if(typeof wireSelection==='function') wireSelection();
  document.querySelectorAll('[data-status]').forEach(el=>{ el.onclick=e=>e.stopPropagation(); el.onchange=async()=>{const jid=el.dataset.status, st=el.value; el.disabled=true; await jfetch(`/api/jobs/${encodeURIComponent(jid)}/status/`,{method:'PUT',headers:{'Content-Type':'application/json'},body:JSON.stringify({status:st})}); const j=JOBS.find(x=>x.job_id===jid); if(j) j.app_status=st; el.disabled=false;}; });
}
function clearFilters(){ ['q','tier','src','statusFilter','regionSel','catSel','likeSel'].forEach(id=>{const e=document.getElementById(id); if(e) e.value='';}); ['closingSoon','starOnly','clean'].forEach(id=>{const e=document.getElementById(id); if(e) e.checked=false;}); setMode('all'); }
function focusRow(delta){
  const rows=[...document.querySelectorAll('#tableWrap tbody tr')]; if(!rows.length) return;
  FOCUS=Math.max(0,Math.min(rows.length-1,(FOCUS<0?(delta>0?0:0):FOCUS+delta)));
  rows.forEach((r,i)=>r.classList.toggle('focus',i===FOCUS)); rows[FOCUS].scrollIntoView({block:'nearest'});
}
async function renderKanban(){
  const rows=filtered();
  const cols=["New","Shortlisted","Applied","Interviewing","Offer","Rejected","Passed on it"];
  const byStatus={}; cols.forEach(c=>byStatus[c]=[]);
  rows.forEach(j=>{ const s=j.app_status||"New"; (byStatus[s]||byStatus["New"]).push(j);});
  $('#kanbanBoard').innerHTML = cols.map(col=>{
    const items=byStatus[col]||[];
    return `<div class="kanban-col">
      <h3><span>${esc(col)}</span><span class="quiet">${items.length}</span></h3>
      ${items.slice(0,12).map(j=>`<div class="ticket" data-details="${esc(j.job_id)}"><b>${esc(j.title)}</b><span class="co">${esc(j.company)} · ${j.fit_score}</span></div>`).join('')||'<div class="co">None</div>'}
      ${items.length>12?`<div class="co">+${items.length-12} more</div>`:''}
    </div>`;
  }).join('');
  document.querySelectorAll('#kanbanBoard [data-details]').forEach(el=>el.onclick=()=>openJob(el.dataset.details));
}

// ---- wiring + page lifecycle -------------------------------------------------------------------------------------------
const FILTER_PARAMS={q:'q',tier:'tier',src:'source',statusFilter:'status',regionSel:'region',catSel:'category',likeSel:'odds',sortSel:'sort'};

function wireLedger(){
  document.querySelectorAll('#modeSeg button').forEach(b=>b.onclick=()=>setMode(b.dataset.mode));
  const dn=$('#densityBtn');
  if(dn){
    let dense=false; try{ dense=localStorage.getItem('jh_dense')==='1'; }catch(e){}
    if(dense){ document.body.classList.add('dense'); dn.textContent='Comfortable'; }
    dn.onclick=()=>{ const on=document.body.classList.toggle('dense'); try{ localStorage.setItem('jh_dense',on?'1':'0'); }catch(e){} dn.textContent=on?'Comfortable':'Compact'; };
  }
  const cf=$('#clearBtn'); if(cf) cf.onclick=clearFilters;
  ['q','tier','src','statusFilter','sortSel','clean','regionSel','catSel','closingSoon','starOnly','likeSel'].forEach(id=>{
    const el=document.getElementById(id); if(!el) return;
    el.addEventListener(el.type==='search'||el.type==='text'?'input':'change',()=>{ render(); if(!$('#kanbanWrap').hidden) renderKanban(); });
  });
  const vt=$('#viewToggle');
  if(vt) vt.onclick=()=>{ KANBAN=!KANBAN; vt.textContent=KANBAN?'Table':'Board'; $('#tableWrap').hidden=KANBAN; $('#kanbanWrap').hidden=!KANBAN; if(KANBAN) renderKanban(); };
}

// filters can be preset from the URL, e.g. /ledger/?mode=local&region=Port+of+Spain (that's how other pages link here)
function applyUrlFilters(){
  const p=new URLSearchParams(location.search); let any=false;
  Object.entries(FILTER_PARAMS).forEach(([id,key])=>{ if(p.has(key)){ const el=document.getElementById(id); if(el){ el.value=p.get(key); any=true; } } });
  if(p.get('closing')==='1'){ $('#closingSoon').checked=true; any=true; }
  if(p.get('starred')==='1'){ $('#starOnly').checked=true; any=true; }
  if(p.has('mode')){ MODE=p.get('mode'); any=true; }
  return any;
}
// the selects are filled from the data; a value set from the URL must survive that
function fillFilterOptions(){
  const keep=id=>(document.getElementById(id)||{}).value||'';
  const pend={src:keep('src'),regionSel:keep('regionSel'),catSel:keep('catSel')};
  const srcs=[...new Set(JOBS.map(j=>(j.source||'').split(':')[0]))].sort();
  const set=(sel,label,vals,cur)=>{ fillSelect(sel,label,vals); if(cur){ const e=$(sel); if(![...e.options].some(o=>o.value===cur||o.text===cur)) e.insertAdjacentHTML('beforeend',`<option>${esc(cur)}</option>`); e.value=cur; } };
  set('#src','All sources',srcs,pend.src);
  set('#regionSel','All regions',[...new Set(JOBS.map(j=>j.region).filter(Boolean))].sort(),pend.regionSel);
  set('#catSel','All categories',[...new Set(JOBS.map(j=>j.category).filter(Boolean))].sort(),pend.catSel);
}

Object.assign(PAGE_HOOKS,{
  async beforeLoad(){
    wireLedger();
    // default mode from your saved work-mode preference, unless the URL says otherwise
    try{
      const pf=(await jfetch('/api/profile/prefs/')).prefs||{};
      if(pf.work_mode==='local_only'||pf.work_mode==='local_first') MODE='local';
      else if(pf.work_mode==='remote_only'||pf.work_mode==='remote_first') MODE='remote';
    }catch(e){}
    if((SETTINGS.preferences||{}).local_only_default) MODE='local';
  },
  init(){ fillFilterOptions(); applyUrlFilters(); setMode(MODE); },
  refresh(){ fillFilterOptions(); render(); if(!$('#kanbanWrap').hidden) renderKanban(); },
  key(e){
    if(e.key==='j'){ focusRow(1); e.preventDefault(); return true; }
    if(e.key==='k'){ focusRow(-1); e.preventDefault(); return true; }
    if(e.key==='Enter' && FOCUS>=0 && ROWS[FOCUS]){ openJob(ROWS[FOCUS].job_id); return true; }
    if(e.key==='s' && FOCUS>=0 && ROWS[FOCUS]){ toggleStar(ROWS[FOCUS].job_id, document.querySelector(`[data-star="${CSS.escape(ROWS[FOCUS].job_id)}"]`)); return true; }
    if(e.key==='/'){ e.preventDefault(); $('#q').focus(); return true; }
    if(e.key==='1'){ setMode('all'); return true; } if(e.key==='2'){ setMode('local'); return true; } if(e.key==='3'){ setMode('remote'); return true; }
    return false;
  },
});
