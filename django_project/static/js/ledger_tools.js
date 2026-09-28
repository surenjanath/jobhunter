// ledger_tools.js — Ledger-only workflow tools: multi-select, bulk actions, compare, employer drawer, saved views.
// ---- selection + bulk + compare -----------------------------------------------------------------------------------
const SEL=new Set();
function updateBulk(){
  const bar=$('#bulkBar'); if(!bar) return;
  bar.hidden=SEL.size===0; $('#bulkCount').textContent=`${SEL.size} selected`;
  $('#bulkCompare').disabled=SEL.size<2||SEL.size>4; $('#bulkCompare').title=SEL.size>4?'Pick at most 4 to compare':'';
}
function wireSelection(){
  document.querySelectorAll('#tableWrap [data-sel]').forEach(cb=>{
    cb.checked=SEL.has(cb.dataset.sel);
    cb.onclick=e=>e.stopPropagation();
    cb.onchange=()=>{ cb.checked?SEL.add(cb.dataset.sel):SEL.delete(cb.dataset.sel); updateBulk(); };
  });
  document.querySelectorAll('#tableWrap [data-company]').forEach(b=>b.onclick=e=>{ e.stopPropagation(); openCompany(b.dataset.company); });
  const all=$('#selAll'); if(all){ all.onclick=e=>e.stopPropagation(); all.onchange=()=>{ document.querySelectorAll('#tableWrap [data-sel]').forEach(cb=>{ cb.checked=all.checked; all.checked?SEL.add(cb.dataset.sel):SEL.delete(cb.dataset.sel); }); updateBulk(); }; }
  updateBulk();
}
async function bulkStatus(status){
  if(!status||!SEL.size) return;
  try{ const r=await jfetch('/api/jobs/bulk-status/',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({job_ids:[...SEL],status})});
    JOBS.forEach(j=>{ if(SEL.has(j.job_id)) j.app_status=status; }); toast(`${r.updated} job${r.updated!==1?'s':''} moved to ${status}`); SEL.clear(); render(); }
  catch(e){ toast(e.message,'bad'); }
}
async function bulkStar(){
  for(const id of [...SEL]){ const j=JOBS.find(x=>x.job_id===id); if(j&&!j.starred) await toggleStar(id); }
  toast('Starred'); SEL.clear(); render();
}

const CMP_COLORS=()=>{ const P=palette(); return [P.ink,P.gap,P.ok,P.mute]; };
async function openCompare(){
  const ids=[...SEL].slice(0,4); if(ids.length<2) return;
  const dlg=$('#cmpDlg'); $('#cmpBody').innerHTML='<p class="quiet">Comparing…</p>'; dlg.showModal();
  try{
    const res=await Promise.all(ids.map(id=>jfetch(`/api/jobs/${encodeURIComponent(id)}/match/`).then(d=>({id,m:d.match,rank:d.rank}))));
    const jobs=res.map(r=>({...JOBS.find(j=>j.job_id===r.id),m:r.m,rank:r.rank}));
    const rows=[
      ['Fit',j=>j.m.fit,'max'],['Odds',j=>j.m.likelihood,'max'],['Interview chance',j=>j.m.interview_chance,'max',v=>'~'+v+'%'],
      ['Skills coverage',j=>j.m.skills.coverage,'max',v=>v==null?'—':v+'%'],
      ['Requirements met',j=>{const r=j.m.requirements||[]; return r.length?Math.round(100*r.filter(x=>x.status==='met').length/r.length):null;},'max',v=>v==null?'—':v+'%'],
      ['Work mode',j=>(j.m.job.local?'Local · '+(j.region||''):j.m.job.work_mode+(j.m.job.remote_scope?' · '+j.m.job.remote_scope:'')),null],
      ['Pay',j=>j.m.job.pay?fmtMoney(j.m.job.pay):'not stated',null],
      ['Experience asked',j=>j.m.job.min_years!=null?`${j.m.job.min_years}+ yrs`:'not stated',null],
      ['Missing required',j=>j.m.skills.missing_required.join(', ')||'none',null],
      ['Blockers',j=>j.m.blockers.join(' · ')||'none',null],
      ['Closes',j=>j.expires_at||'—',null],
      ['Advice',j=>j.m.advice,null],
    ];
    const best=(f,mode)=>{ if(mode!=='max') return -1; const vals=jobs.map(j=>f(j)); const mx=Math.max(...vals.map(v=>v==null?-1:v)); return mx; };
    $('#cmpBody').innerHTML=`<div class="cmpgrid">
      <div><div class="mviz-t">Fit profile</div><div class="mbox" style="height:280px"><canvas id="cmpRadar"></canvas></div></div>
      <div><table class="cmp"><thead><tr><th></th>${jobs.map((j,i)=>`<th><i class="sw" style="background:${CMP_COLORS()[i]}"></i>${esc(j.title.slice(0,32))}<div class="co">${esc(j.company)}</div></th>`).join('')}</tr></thead><tbody>
      ${rows.map(([label,f,mode,fmt])=>{ const mx=best(f,mode); return `<tr><td class="co">${label}</td>${jobs.map(j=>{ const v=f(j); const win=mode==='max'&&v!=null&&v===mx&&jobs.length>1; return `<td class="${win?'win':''}">${esc(fmt?fmt(v):v)}</td>`; }).join('')}</tr>`; }).join('')}
      </tbody></table></div></div>`;
    const P=palette(), keys=['skills','evidence','title','experience','domain','preferences'], cols=CMP_COLORS();
    mk('cmpRadar',{type:'radar',data:{labels:['Skills','Evidence','Title','Experience','Domain','Preferences'],datasets:jobs.map((j,i)=>({label:j.title.slice(0,26),data:keys.map(k=>j.m.breakdown[k]??0),borderColor:cols[i],backgroundColor:'transparent',pointBackgroundColor:cols[i],borderWidth:2}))},
      options:{scales:{r:{min:0,max:100,ticks:{display:false,stepSize:25},grid:{color:P.rule},angleLines:{color:P.rule},pointLabels:{color:P.ink,font:{size:10}}}},plugins:{legend:{position:'bottom',labels:{boxWidth:8,font:{size:10}}}}}});
  }catch(e){ $('#cmpBody').innerHTML=`<div class="banner w">${esc(e.message)}</div>`; }
}

// ---- company drawer -----------------------------------------------------------------------------------------------
function openCompany(name){
  const rows=JOBS.filter(j=>j.company===name).sort((a,b)=>b.fit_score-a.fit_score);
  if(!rows.length) return;
  const avg=Math.round(rows.reduce((s,j)=>s+j.fit_score,0)/rows.length), st={};
  rows.forEach(j=>{ const k=j.app_status||'New'; st[k]=(st[k]||0)+1; });
  $('#coTitle').textContent=name;
  $('#coSub').textContent=`${rows.length} role${rows.length!==1?'s':''} · avg fit ${avg} · ${[...new Set(rows.map(j=>j.region||j.work_mode||'').filter(Boolean))].slice(0,4).join(', ')}`;
  $('#coBody').innerHTML=`<div class="co" style="margin-bottom:8px">${Object.entries(st).map(([k,v])=>`${esc(k)} ${v}`).join(' · ')}</div><ul class="compare">${rows.map(j=>{ const l=likeOf(j); return `<li><button type="button" data-details="${esc(j.job_id)}"><span><span class="who">${esc(j.title)}</span><span class="sub">${esc(j.region||j.location||'')} · ${esc(j.app_status||'New')}${daysLeftLabel(j)?' · '+esc(daysLeftLabel(j)):''}</span></span><span class="metric">fit ${j.fit_score}${l?` · ${esc(l.verdict)}`:''}</span></button></li>`; }).join('')}</ul>`;
  $('#coBody').querySelectorAll('[data-details]').forEach(b=>b.onclick=()=>{ $('#coDlg').close(); openJob(b.dataset.details); });
  $('#coDlg').showModal();
}

// ---- saved views --------------------------------------------------------------------------------------------------
const VIEW_IDS=['q','tier','src','statusFilter','regionSel','catSel','likeSel','sortSel'], VIEW_CHECKS=['closingSoon','starOnly','clean'];
function viewState(){ const s={mode:MODE}; VIEW_IDS.forEach(i=>s[i]=(document.getElementById(i)||{}).value||''); VIEW_CHECKS.forEach(i=>s[i]=!!(document.getElementById(i)||{}).checked); return s; }
function applyView(s){ VIEW_IDS.forEach(i=>{ const e=document.getElementById(i); if(e) e.value=s[i]||''; }); VIEW_CHECKS.forEach(i=>{ const e=document.getElementById(i); if(e) e.checked=!!s[i]; }); setMode(s.mode||'all'); }
function loadViews(){
  let v=[]; try{ v=JSON.parse(localStorage.getItem('jh_views')||'null'); }catch(e){}
  if(!Array.isArray(v)||!v.length) v=[
    {name:'Best local roles',state:{mode:'local',sortSel:'likelihood',likeSel:'',clean:true}},
    {name:'Remote worth a shot',state:{mode:'remote',sortSel:'likelihood',likeSel:'20',clean:true}},
    {name:'Closing this week',state:{mode:'all',sortSel:'closing',closingSoon:true,tier:'50'}}];
  return v;
}
function saveViews(v){ try{ localStorage.setItem('jh_views',JSON.stringify(v)); }catch(e){} paintViews(); }
function paintViews(){
  const sel=$('#viewSel'); if(!sel) return; const v=loadViews();
  sel.innerHTML='<option value="">Saved views</option>'+v.map((x,i)=>`<option value="${i}">${esc(x.name)}</option>`).join('');
}
function wireViews(){
  paintViews();
  const sel=$('#viewSel'); if(sel) sel.onchange=()=>{ if(sel.value==='') return; applyView(loadViews()[+sel.value].state); };
  const nm=$('#viewName'), sv=$('#viewSave'), del=$('#viewDel');
  if(sv) sv.onclick=()=>{ nm.hidden=!nm.hidden; if(!nm.hidden) nm.focus(); };
  if(nm) nm.onkeydown=e=>{ if(e.key==='Enter'&&nm.value.trim()){ const v=loadViews(); v.push({name:nm.value.trim(),state:viewState()}); saveViews(v); nm.value=''; nm.hidden=true; toast('View saved'); } if(e.key==='Escape'){ nm.hidden=true; } };
  if(del) del.onclick=()=>{ if(sel.value==='') return; const v=loadViews(); v.splice(+sel.value,1); saveViews(v); toast('View removed'); };
}


Object.assign(PAGE_HOOKS,{});   // (wiring below runs on DOMContentLoaded; the Ledger page hooks live in ledger.js)
document.addEventListener('DOMContentLoaded',()=>{
  const bc=$('#bulkCompare'); if(bc) bc.onclick=openCompare;
  const bs=$('#bulkStatus'); if(bs) bs.onchange=()=>{ bulkStatus(bs.value); bs.value=''; };
  const bst=$('#bulkStar'); if(bst) bst.onclick=bulkStar;
  const bx=$('#bulkClear'); if(bx) bx.onclick=()=>{ SEL.clear(); render(); };
  wireViews();
});
