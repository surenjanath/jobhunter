// match.js — the "Match" tab in the job dialog: why this fit, why these odds, and the resume evidence behind them.
// Classic script; shares $, jfetch, esc with app.js.
const VERDICT_TXT={High:'Strong odds','Medium':'Decent odds',Low:'Long-ish odds','Long shot':'Long shot'};
const SCOPE_TXT={worldwide:'Open worldwide',americas:'Open to the Americas',us_only:'US residents only',eu_only:'EU/UK residents only',canada_only:'Canada only',unknown:'Location rule not stated'};
const MODE_TXT={remote:'Remote',hybrid:'Hybrid',onsite:'On-site',unknown:'Location unclear'};

function fmtMoney(p){
  if(!p) return '';
  return `TT$${p.monthly_ttd_min.toLocaleString()}${p.monthly_ttd_max>p.monthly_ttd_min?`–${p.monthly_ttd_max.toLocaleString()}`:''}/mo (≈US$${p.monthly_usd_min.toLocaleString()}${p.monthly_usd_max>p.monthly_usd_min?`–${p.monthly_usd_max.toLocaleString()}`:''})`;
}
function meter(label,v,note){
  if(v==null) return `<div class="meter na"><span class="meter-l">${esc(label)}</span><span class="meter-t"><i style="width:0"></i></span><span class="meter-n">n/a</span></div>`;
  return `<div class="meter" title="${esc(note||'')}"><span class="meter-l">${esc(label)}</span><span class="meter-t"><i style="width:${v}%"></i></span><span class="meter-n">${v}</span></div>`;
}
function factorRow(f){
  const w=Math.min(100,Math.abs(f.delta)/2.5*100), pos=f.delta>=0;
  return `<div class="factor"><span class="factor-l">${esc(f.name)}<span class="co"> ${esc(f.note||'')}</span></span>
    <span class="factor-t"><i class="${pos?'pos':'neg'}" style="width:${w/2}%;${pos?'left:50%':'right:50%'}"></i></span>
    <span class="factor-n">${pos?'+':''}${f.delta.toFixed(1)}</span></div>`;
}
function skillChip(s){
  if(s.name!==undefined && s.via) return `<span class="chip neutral" title="counts as partial evidence">${esc(s.name)} <i>via ${esc(s.via)}</i></span>`;
  return `<span class="chip have">${esc(s.name)}${s.years?` <i>${s.years}y</i>`:''}</span>`;
}

function tailorHtml(t){
  if(!t || !(t.lead_with.length||t.add_keywords.length||t.do_not_claim.length)) return '';
  return `<h4>Tailoring this application <span class="co">truthful edits only</span></h4>
    ${t.lead_with.length?`<div class="tailor"><b>Lead with these bullets</b>${t.lead_with.map(l=>`<blockquote class="evid"><span class="co">answers “${esc(l.requirement)}” · ${esc(l.where)}</span><br>${esc(l.bullet)}</blockquote>`).join('')}</div>`:''}
    ${t.add_keywords.length?`<div class="tailor"><b>Wording to consider</b><ul class="list">${t.add_keywords.map(k=>`<li>${esc(k.advice)}</li>`).join('')}</ul></div>`:''}
    ${t.do_not_claim.length?`<div class="tailor"><b>Don't claim</b> <span class="co">(not on your resume)</span><div>${t.do_not_claim.map(k=>`<span class="chip gap">${esc(k)}</span>`).join('')}</div></div>`:''}`;
}
function rankHtml(r,m){
  if(!r) return '';
  const bar=(label,v)=>`<div class="rankrow"><span>${label}</span><span class="meter-t"><i style="width:${v}%"></i></span><b>${v}%</b></div>`;
  return `<div class="rank">${bar('Fit beats',r.fit_pct)}${bar('Odds beat',r.odds_pct)}${bar(`Fit vs other ${esc(r.kind)} roles`,r.kind_fit_pct)}<p class="co">of your ${r.total} listings</p></div>`;
}
function drawMatchCharts(m,d){
  if(typeof Chart==='undefined' || typeof mk!=='function') return;
  const P=palette(), b=m.breakdown||{}, pool=(d.pool||{}).breakdown||{};
  const keys=['skills','evidence','title','experience','domain','preferences'], labels=['Skills','Evidence','Title','Experience','Domain','Preferences'];
  mk('mRadar',{type:'radar',data:{labels,datasets:[
    {label:`Your best ${d.pool?d.pool.n:''} listings (avg)`,data:keys.map(k=>pool[k]??0),borderColor:P.mute,backgroundColor:'transparent',borderDash:[4,3],pointRadius:0,borderWidth:1.5},
    {label:'This job',data:keys.map(k=>b[k]??0),borderColor:P.ink,backgroundColor:P.dark?'rgba(236,236,232,.2)':'rgba(28,28,28,.14)',pointBackgroundColor:P.ink,borderWidth:2}]},
    options:{scales:{r:{min:0,max:100,ticks:{display:false,stepSize:25},grid:{color:P.rule},angleLines:{color:P.rule},pointLabels:{color:P.ink,font:{size:10}}}},plugins:{legend:{position:'bottom',labels:{boxWidth:8,font:{size:10}}}}}});
  const items=(m.skills.items||[]).filter(i=>i.status!=='soft'), col={have:P.ink,related:P.mute,missing:P.gap};
  mk('mSkills',{type:'bar',data:{labels:items.map(i=>i.name+(i.status==='have'&&i.years?` · ${i.years}y`:i.status==='related'?` ≈ ${i.via}`:'')),datasets:[{data:items.map(i=>i.weight),backgroundColor:items.map(i=>col[i.status]),borderWidth:0}]},
    options:{indexAxis:'y',plugins:{legend:{display:false},tooltip:{callbacks:{label:c=>{const i=items[c.dataIndex];return `${i.kind} · ${i.status==='have'?'you have it':i.status==='related'?'adjacent: '+i.via:'not on your resume'}`;}}}},scales:{x:{min:0,max:1,display:false},y:{grid:{display:false},ticks:{font:{size:11}}}}}});
  const rq=m.requirements||[], cnt={met:0,partial:0,gap:0}; rq.forEach(r=>cnt[r.status]++);
  mk('mReq',{type:'bar',data:{labels:['Requirements'],datasets:[{label:'Met',data:[cnt.met],backgroundColor:P.ink},{label:'Partial',data:[cnt.partial],backgroundColor:P.mute},{label:'Gap',data:[cnt.gap],backgroundColor:P.gap}]},
    options:{indexAxis:'y',scales:{x:{stacked:true,display:false},y:{stacked:true,display:false}},plugins:{legend:{position:'bottom',labels:{boxWidth:8,font:{size:10}}}}}});
}
const MATCH_CACHE={};
async function highlightPosting(j){
  const el=$('#postingText'); if(!el) return;
  try{
    const d=MATCH_CACHE[j.job_id]||(MATCH_CACHE[j.job_id]=await jfetch(`/api/jobs/${encodeURIComponent(j.job_id)}/match/`));
    const hl=(d.highlights||[]).slice().sort((a,b)=>b.text.length-a.text.length); if(!hl.length||!$('#postingText')) return;
    const map={}; hl.forEach(h=>{ map[esc(h.text).toLowerCase()]=h.status; });
    const rx=new RegExp('(?<![A-Za-z0-9])('+hl.map(h=>esc(h.text).replace(/[.*+?^${}()|[\]\\]/g,'\\$&')).join('|')+')(?![A-Za-z0-9])','gi');
    el.innerHTML=esc(j.description||'—').slice(0,12000).replace(rx,(m)=>`<mark class="hl ${map[m.toLowerCase()]||'have'}">${m}</mark>`);
    const lg=$('#hlLegend'); if(lg) lg.hidden=false;
  }catch(e){ /* no resume yet: plain text stays */ }
}
function renderMatchTab(j){
  const body=$('#jobBody'); body.innerHTML='<span class="co">Matching against your resume…</span>';
  jfetch(`/api/jobs/${encodeURIComponent(j.job_id)}/match/`).then(d=>{
    if(CURRENT_JOB!==j && CURRENT_JOB && CURRENT_JOB.job_id!==j.job_id) return;
    MATCH_CACHE[j.job_id]=d;
    const m=d.match, b=m.breakdown||{}, jb=m.job||{};
    const sk=m.skills||{matched:[],related:[],missing_required:[],missing_other:[]};
    const priorNote=m.prior_source?`Starting point ${m.prior}% (${esc(m.prior_source)}) → ${m.interview_chance}% after the factors below.`:'';
    const facts=[
      `<span class="flag g">${esc(MODE_TXT[jb.work_mode]||jb.work_mode||'—')}</span>`,
      jb.work_mode==='remote'&&!jb.local?`<span class="flag ${['us_only','eu_only','canada_only'].includes(jb.remote_scope)?'b':'g'}">${esc(SCOPE_TXT[jb.remote_scope]||'—')}</span>`:'',
      jb.local?'<span class="flag g">🇹🇹 Local</span>':'',
      jb.eor?'<span class="flag g">Contractors / EOR welcome</span>':'', jb.sponsorship?'<span class="flag">Sponsorship mentioned</span>':'',
      jb.min_years!=null?`<span class="flag">${jb.min_years}+ yrs asked · you have ${d.profile_years}</span>`:'',
      jb.pay?`<span class="flag">Pay ${esc(fmtMoney(jb.pay))}</span>`:'<span class="flag">Pay not stated</span>',
      jb.age_days!=null?`<span class="flag">${jb.age_days}d old</span>`:''
    ].join('');
    const reqs=(m.requirements||[]).map(r=>`<div class="req ${esc(r.status)}">
        <div class="req-s" title="${esc(r.status)}">${r.status==='met'?'●':r.status==='partial'?'◐':'○'}</div>
        <div class="req-b"><div class="req-t">${esc(r.text)}</div>
        ${r.evidence?`<blockquote class="evid"><span class="co">${esc(r.evidence.label)} · ${esc(r.evidence.section)}${r.evidence.semantic!=null?` · semantic ${Math.round(r.evidence.semantic*100)}%`:''}</span><br>${esc(r.evidence.text)}</blockquote>`:'<div class="co">Nothing in your resume speaks to this.</div>'}</div>
        <div class="req-n">${Math.round(r.score*100)}%</div></div>`).join('')||'<p class="co">The posting states no separable requirements, so the match rests on skills and title.</p>';
    $('#jobBody').innerHTML=`
      <div class="kpi">
        <div class="box"><b>${m.fit}</b><span>Fit</span></div>
        <div class="box"><b>${m.likelihood}</b><span>Odds · ${esc(m.verdict)}</span></div>
        <div class="box"><b>~${m.interview_chance}%</b><span>Interview chance</span></div>
        <div class="box"><b>${esc(m.confidence)}</b><span>Confidence · ${esc(m.method)}</span></div>
      </div>
      <div class="banner ${m.blockers.length?'w':m.verdict==='High'?'g':''}"><b>${esc(m.advice)}</b>${m.blockers.length?`<br><span class="co">${m.blockers.map(esc).join(' · ')}</span>`:''}</div>
      <div style="margin:10px 0">${facts}</div>
      <div class="mviz">
        <div><div class="mviz-t">This job vs your best listings</div><div class="mbox"><canvas id="mRadar"></canvas></div></div>
        <div><div class="mviz-t">What the listing asks for, and what you have</div><div class="mbox" id="mSkillsBox" style="height:${Math.max(150,sk.items.filter(i=>i.status!=='soft').length*24+30)}px"><canvas id="mSkills"></canvas></div>
          <p class="legend-note"><i class="sw have"></i> you have it <i class="sw rel"></i> adjacent <i class="sw miss"></i> missing · bar length = importance to the listing</p></div>
        <div><div class="mviz-t">Where it ranks</div>${rankHtml(d.rank,m)}<div class="mbox" style="height:120px"><canvas id="mReq"></canvas></div><p class="legend-note">requirements: ● met ◐ partial ○ gap</p></div>
      </div>
      <div class="two">
        <div><h4>Fit breakdown</h4>
          ${meter('Skills',b.skills,'share of the posting\'s skills you have (required count fully, nice-to-have less)')}
          ${meter('Requirement evidence',b.evidence,'how well your resume text answers each requirement')}
          ${meter('Title',b.title,'closeness to your target and past titles')}
          ${meter('Experience',b.experience,'years asked vs your years')}
          ${meter('Domain',b.domain,'industry overlap')}
          ${meter('Preferences',b.preferences,'work mode, regions, pay')}
        </div>
        <div><h4>Why these odds</h4>
          ${(m.factors||[]).map(factorRow).join('')||'<span class="co">No adjustments.</span>'}
          <p class="co" style="margin-top:8px">${priorNote}</p>
        </div>
      </div>
      <h4>Skills</h4>
      <div>${sk.matched.map(skillChip).join('')}${sk.related.map(skillChip).join('')}
        ${sk.missing_required.map(n=>`<span class="chip gap" title="asked for, not on your resume">${esc(n)} ○</span>`).join('')}
        ${sk.missing_other.map(n=>`<span class="chip neutral" title="mentioned, not on your resume">${esc(n)}</span>`).join('')||''}
        ${!(sk.matched.length+sk.related.length+sk.missing_required.length+sk.missing_other.length)?'<span class="co">No recognised skills in this posting.</span>':''}</div>
      <h4>Requirements and your evidence <span class="co">● met · ◐ partial · ○ gap</span></h4>${reqs}
      ${tailorHtml(m.tailoring)}
      ${typeof trackHtml==='function'?trackHtml(j):''}
      <div class="two"><div><h4>Strengths</h4><ul class="list">${m.strengths.map(s=>`<li>✓ ${esc(s)}</li>`).join('')||'<li class="co">—</li>'}</ul></div>
        <div><h4>Gaps</h4><ul class="list">${m.gaps.map(s=>`<li>○ ${esc(s)}</li>`).join('')||'<li class="co">—</li>'}</ul></div></div>
      <p class="co">Scored from <b>${esc(d.resume)}</b>. ${m.method==='lexical'?'Evidence is matched by keywords; <a href="#" data-view="resume" id="mtSem">install an embedding model</a> for semantic matching.':'Evidence uses semantic embeddings.'}</p>`;
    const a=$('#mtSem'); if(a) a.onclick=e=>{e.preventDefault(); jobDlg.close(); goto('profile');};
    drawMatchCharts(m,d);
    if(typeof wireTrack==='function') wireTrack(j);
  }).catch(e=>{
    const noResume=/resume/i.test(e.message);
    $('#jobBody').innerHTML=`<div class="banner w">${esc(e.message)}${noResume?' — <a href="#" id="mtGo">open Profile</a>':''}</div>`;
    const g=$('#mtGo'); if(g) g.onclick=ev=>{ev.preventDefault(); jobDlg.close(); goto('profile');};
  });
}
