// home.js — the Conditions page: figures, hero odds, coach brief, comparison list, and the Today block.
async function loadCoach(force=false){
  const el=$('#coach'); if(!el) return;
  if(force) el.hidden=false;
  $('#coachText').textContent='Thinking…';
  try{
    const d=await jfetch('/api/coach/brief/'+(force?'?ai=1':''));
    if(d.error) throw new Error(d.error);
    $('#coachText').textContent=d.text;
    $('#coachMeta').textContent=`· ${d.source} · ${new Date(d.generated).toLocaleTimeString()}`;
    let ul=$('#coachActions'); if(!ul){ ul=document.createElement('ul'); ul.id='coachActions'; ul.className='list'; el.appendChild(ul); }
    ul.innerHTML=(d.actions||[]).map(a=>`<li><b>${esc(a.title)}</b> <span class="quiet">· ${esc(a.effort)} · ${esc(a.impact)} impact</span><br><span class="quiet">${esc(a.why)}</span></li>`).join('');
  }catch(e){ $('#coachText').textContent='Could not build the brief: '+e.message; }
}
function paintFigures(items){
  const el=$('#stats'); if(!el) return;
  el.innerHTML=(items||[]).map(f=>`<div class="fig"><div class="fig-label">${esc(f.label)}</div><div class="fig-value">${esc(f.value)}${f.detail?` <span class="fig-detail">${esc(f.detail)}</span>`:''}</div></div>`).join('');
}
function arcPath(cx,cy,r,start,end){
  const p=(a)=>[cx+r*Math.cos(a), cy+r*Math.sin(a)];
  const [x1,y1]=p(start), [x2,y2]=p(end);
  const large=end-start>Math.PI?1:0;
  return `M ${x1} ${y1} A ${r} ${r} 0 ${large} 1 ${x2} ${y2}`;
}
function paintRadial(likelihood){
  const svg=$('#radial'); if(!svg) return;
  const pct=Math.max(0, Math.min(100, Number(likelihood)||0))/100;
  const sweep=0.45+pct*1.7;
  const start=-0.2;
  const parts=`<circle cx="140" cy="140" r="108" fill="none" stroke="var(--faint)" stroke-width="8"/>
    <path d="${arcPath(140,140,108,start,start+sweep)}" fill="none" stroke="var(--ink)" stroke-width="12"/>`;
  const ticks=Array.from({length:12},(_,i)=>{
    const t=-Math.PI/2+i*Math.PI/6;
    const i1=118, o1=126;
    return `<line x1="${140+i1*Math.cos(t)}" y1="${140+i1*Math.sin(t)}" x2="${140+o1*Math.cos(t)}" y2="${140+o1*Math.sin(t)}" stroke="var(--faint)" stroke-width="1"/>`;
  }).join('');
  svg.innerHTML=`<circle cx="140" cy="140" r="78" fill="none" stroke="var(--rule)" stroke-width="1"/>
    <path d="M70 150 C90 90, 130 80, 160 110 C190 70, 230 100, 210 160 C240 190, 180 230, 140 200 C90 230, 50 190, 70 150 Z" fill="none" stroke="var(--faint)" stroke-width="1"/>
    ${ticks}${parts}`;
}
let LAST_BRIEF=null;
function paintBrief(d){
  LAST_BRIEF=d;
  if(d.conditions) paintFigures(d.conditions);
  const pct=$('#heroPct');
  if(pct) pct.textContent=d.hero&&d.hero.likelihood!=null?`${d.hero.likelihood}%`:'—';
  const sub=$('#heroSub');
  if(sub){
    const prior=d.hero&&d.hero.prior!=null?`${d.hero.prior}%`:'—';
    const avg=d.hero&&d.hero.average!=null?`${d.hero.average}%`:'—';
    sub.innerHTML=`<span>next <b>${esc(prior)}</b></span><span>avg <b>${esc(avg)}</b></span>`;
  }
  const warn=$('#heroWarn');
  if(warn) warn.textContent=(d.warning&&d.warning.text)||'';
  const mark=$('#warnMark');
  if(mark) mark.style.visibility=(d.warning&&d.warning.on)?'visible':'hidden';
  const list=$('#compareList');
  if(list){
    const rows=d.compare||[];
    const waiting=rows.length<3?`<li><button type="button" disabled><span><span class="who">Compare</span><span class="sub">waiting on the next scan</span></span></button></li>`:'';
    list.innerHTML=rows.map(j=>`<li><button type="button" data-details="${esc(j.job_id)}"><span><span class="who">Compare ${esc(j.company)}</span><span class="sub">${esc(j.title)}${j.posted_at?` · ${esc(j.posted_at)}`:''}</span></span><span class="metric">${j.likelihood}% ${esc(j.verdict)}</span></button></li>`).join('')+waiting;
    list.querySelectorAll('[data-details]').forEach(el=>el.onclick=()=>openJob(el.dataset.details));
  }
  const detail=$('#compareDetail');
  if(detail && !detail.hidden) fillCompare(d);
  const ext=d.extended||{};
  paintRadial(d.hero&&d.hero.likelihood);
  if($('#highCount')) $('#highCount').textContent=d.hero&&d.hero.high_count!=null?d.hero.high_count:'—';
  if($('#dueCount')) $('#dueCount').textContent=ext.due??'—';
  (d.odds||[]).forEach(o=>{ const j=JOBS.find(x=>x.job_id===o.job_id); if(j) j.likelihood={...(j.likelihood||{}),likelihood:o.likelihood,verdict:o.verdict,advice:o.advice,blockers:(j.likelihood&&j.likelihood.blockers)||[]}; });
  if($('#dueNote')) $('#dueNote').textContent=ext.due?`${ext.due} follow-up${ext.due===1?'':'s'}`:'none due';
  if($('#motionCount')) $('#motionCount').textContent=ext.in_motion??'—';
  if($('#motionNote')) $('#motionNote').textContent=`${ext.letters||0} letters`;
  if($('#sourceList')){
    const src=ext.sources||[];
    $('#sourceList').innerHTML=src.length?src.map(s=>`<li><b>${s.count}</b> ${esc(s.source)} <span class="quiet">avg ${s.avg}</span></li>`).join(''):'<li class="quiet">No sources yet</li>';
  }
  if($('#nextAction')) $('#nextAction').textContent=d.next_action||'';
}
function fillCompare(d){
  const detail=$('#compareDetail'); if(!detail) return;
  const rows=(d&&d.compare)||[];
  detail.innerHTML=rows.map(j=>`<div><h3>${esc(j.company)}</h3><div>${esc(j.advice||j.verdict)}</div><div class="quiet" style="margin-top:6px">${(j.gaps||[]).map(esc).join(' · ')||'No listed gap'}</div></div>`).join('')||'<div class="quiet">Nothing to compare yet.</div>';
}
async function loadBrief(){
  try{
    const d=await jfetch('/api/brief/');
    paintBrief(d);
  }catch(e){ /* counts from the scan stay on screen */ }
}

// ---- "Today" block on the Conditions page --------------------------------------------------------------------------
async function loadToday(){
  const el=$('#todayBlock'); if(!el) return;
  try{
    const [dg,fu]=await Promise.all([jfetch('/api/digest/?days=2&min_fit=50&limit=5'),jfetch('/api/followups/?days=7')]);
    const li=(j,extra)=>`<li><button type="button" data-details="${esc(j.job_id)}"><span><span class="who">${esc(j.title)}</span><span class="sub">${esc(j.company)} · ${extra}</span></span></button></li>`;
    const picks=dg.picks.map(p=>li(p,`fit ${p.fit} · ${esc(p.verdict||'')} · ${esc(p.where||'')}`)).join('')||'<li class="quiet">Nothing new that fits, and unblocked, in the last 2 days.</li>';
    const closing=(fu.closing_soon||[]).slice(0,5).map(j=>li(j,`${esc(daysLeftLabel(j))} · ${esc(j.app_status)}`)).join('')||'<li class="quiet">No tracked or starred roles closing this week.</li>';
    const due=[...(fu.overdue||[]),...(fu.upcoming||[])].slice(0,5).map(j=>li(j,`follow up ${esc(j.followup_date)}${(fu.overdue||[]).includes(j)?' · overdue':''}`)).join('')||'<li class="quiet">No follow-ups due.</li>';
    el.innerHTML=`<div><h3>New and worth your time <span class="quiet">last 2 days</span></h3><ul class="compare">${picks}</ul>${dg.blocked.length?`<div class="co" style="margin-top:6px">${dg.blocked.length} more fit well but are blocked (US-only, relocation…).</div>`:''}<button type="button" class="text tiny" onclick="window.open('/api/digest/?days=7&fmt=md','_blank')">Open the weekly digest</button></div>
      <div><h3>Closing soon <span class="quiet">tracked or starred</span></h3><ul class="compare">${closing}</ul></div>
      <div><h3>Follow-ups</h3><ul class="compare">${due}</ul></div>`;
    el.querySelectorAll('[data-details]').forEach(b=>b.onclick=()=>openJob(b.dataset.details));
  }catch(e){ el.innerHTML=''; }
}

// ---- page lifecycle ----------------------------------------------------------------------------------------------------
function paintHome(d){
  const c=(d&&d.counts)||{roles:JOBS.length,t1:0,t2:0,blocked:0};
  paintFigures([{label:'Roles',value:c.roles},{label:'Tier 1',value:c.t1},{label:'Tier 2',value:c.t2},{label:'Blocked',value:c.blocked}]);
  loadBrief(); loadToday();
}
Object.assign(PAGE_HOOKS,{
  init(d){
    const exp=$('#compareExpand'); if(exp) exp.onclick=()=>{ const x=$('#compareDetail'); if(!x) return; x.hidden=!x.hidden; if(!x.hidden) fillCompare(LAST_BRIEF||{compare:[]}); };
    const cr=$('#coachRefresh'); if(cr) cr.onclick=()=>{ const el=$('#coach'); if(!el) return; el.hidden=!el.hidden; if(!el.hidden) loadCoach(true); };
    paintHome(d); paintRecs();
  },
  refresh:d=>{ paintHome(d); paintRecs(); },
});
