// job.js — the job dialog (Match / Overview / Tech / … tabs) and cover-letter drafting. Used by every page that lists jobs.
async function toggleStar(jid,el){ try{ const r=await jfetch(`/api/jobs/${encodeURIComponent(jid)}/star/`,{method:'POST',headers:{'Content-Type':'application/json'},body:'{}'}); const j=JOBS.find(x=>x.job_id===jid); if(j) j.starred=r.starred; if(el){ el.classList.toggle('on',r.starred); el.textContent=r.starred?'★':'☆'; } }catch(e){ toast(e.message,'bad'); } }
let CURRENT_JOB=null, CURRENT_TAB='overview';
document.querySelectorAll('#jobTabs .tab').forEach(el=>el.onclick=()=>{document.querySelectorAll('#jobTabs .tab').forEach(x=>x.classList.remove('active')); el.classList.add('active'); CURRENT_TAB=el.dataset.tab; if(CURRENT_JOB) renderJobTab(CURRENT_JOB);});
async function openJob(jobId){
  const j=JOBS.find(x=>x.job_id===jobId); if(!j) return;
  $('#jobTitle').textContent=j.title; $('#jobSub').textContent=`${j.company} · ${j.location||'—'} · ${j.source}`; $('#jobApply').href=j.url||'#'; $('#jobNote').textContent=`Fit ${j.fit_score} · ${j.tier} · ${j.posted_at||'—'}`; $('#jobBody').innerHTML='<span class="co">Analyzing…</span>'; jobDlg.showModal(); CURRENT_JOB=j; CURRENT_TAB='match'; document.querySelectorAll('#jobTabs .tab').forEach(x=>x.classList.toggle('active',x.dataset.tab==='match'));
  try{const d=await jfetch(`/api/jobs/${encodeURIComponent(jobId)}/`); if(d.error) throw new Error(d.error); CURRENT_JOB={...j, ...d.job, details:d.details, likelihood:d.likelihood}; Object.assign(j, CURRENT_JOB); renderJobTab(CURRENT_JOB);}catch(e){$('#jobBody').innerHTML=`<div class="banner w">${esc(e.message)}</div><pre class="co">${esc(j.description||'').slice(0,3000)}</pre>`;}
}
function renderJobTab(j){
  const d=j.details, like=j.likelihood; let html='';
  if(CURRENT_TAB==='match'){ renderMatchTab(j); return; }
  if(['summary','rewrite','practice','outreach'].includes(CURRENT_TAB)){ renderAiTab(j); return; }
  if(CURRENT_TAB==='overview'){
    const src=(j.source||'').split(':')[0]; const isTT=isLocal(j);
    html=`<div class="kpi"><div class="box"><b>${j.fit_score}</b><span>Fit</span></div><div class="box"><b>${like?like.likelihood:'—'}</b><span>Likelihood</span></div><div class="box"><b>${esc(j.tier||'—').split('—')[0]}</b><span>Tier</span></div><div class="box"><b>${esc(src)}</b><span>Source</span></div></div>
      <div style="display:flex;gap:6px;flex-wrap:wrap;margin-bottom:10px"><span class="flag ${j.fit_score>=65?'g':j.fit_score>=50?'':'b'}">Fit ${j.fit_score}</span>${like?`<span class="flag ${like.verdict==='High'?'g':like.verdict==='Medium'?'':'b'}">Likelihood ${like.likelihood}% · ${like.verdict}</span>`:''}${isTT?'<span class="flag g">🇹🇹 Local</span>':''}${j.remote?'<span class="flag g">Remote</span>':''}<span class="flag">Posted ${esc(j.posted_at||'—')}</span>${j.salary?`<span class="flag">💰 ${esc(j.salary)}</span>`:''}</div>
      <div class="banner ${like&&like.verdict==='High'?'g':like&&like.verdict==='Long shot'?'w':''}"><b>${like?esc(like.verdict)+' — ':''}${like?esc(like.advice):esc(j.why||'')}</b>${like&&like.blockers.length?`<br><span class="co">Blockers: ${esc(like.blockers.join(' · '))}</span>`:''}</div>
      <h4 style="margin:12px 0 6px">Why matched</h4><div class="co">${esc(j.why||'—')}</div>
      <h4 style="margin:12px 0 6px">Flags</h4><div>${(j.flags||'').split('|').filter(Boolean).map(f=>`<span class="flag ${flagClass(f)}">${esc(f.trim())}</span>`).join('')||'<span class="co">None</span>'}</div>
      <h4 style="margin:12px 0 6px">Facts</h4><div style="display:grid;grid-template-columns:1fr 1fr;gap:8px" class="co"><div><b>Company:</b> ${esc(j.company)}</div><div><b>Location:</b> ${esc(j.location||'—')}</div><div><b>Source:</b> ${esc(j.source)}</div><div><b>Posted:</b> ${esc(j.posted_at||'—')}</div><div><b>URL:</b> <a href="${esc(j.url)}" target="_blank">Open</a></div><div><b>Alt:</b> ${esc(j.alt_urls||'—').slice(0,70)}</div></div>`;
  } else if(CURRENT_TAB==='tech'){
    if(!d) html='<span class="co">No tech data</span>'; else {
      const techs=d.technologies_with_status||{}; let total=d.summary?`${d.summary.have}/${d.summary.total_techs} you have (${d.summary.coverage}%)`:'';
      html=`<div class="banner g"><b>Coverage: ${esc(total)}</b> — green have, amber gap</div>`;
      for(const [cat,items] of Object.entries(techs)){ html+=`<h4 style="margin:12px 0 6px">${esc(cat)} <span class="co">(${items.length})</span></h4>`; html+=items.map(it=>`<span class="chip ${it.have?'have':'gap'}">${esc(it.tech)} ${it.have?'✓':'○'}</span>`).join('');}
      if(!Object.keys(techs).length) html+='<div class="co">Generalist role — no specific tech</div>';
      html+=`<div style="margin-top:12px" class="bar ${d.summary.coverage>=60?'good':d.summary.coverage>=35?'warn':'bad'}"><i style="width:${d.summary.coverage}%"></i></div>`;
    }
  } else if(CURRENT_TAB==='needs'){
    if(!d) html='<span class="co">No data</span>'; else {
      const req=d.requirements||{};
      html=`<div class="kpi"><div class="box"><b>${esc(req.experience_raw||'—')}</b><span>Experience</span></div><div class="box"><b>${esc(req.education_raw||'—')}</b><span>Education</span></div><div class="box"><b>${esc(req.remote_raw||'—')}</b><span>Remote</span></div><div class="box"><b>${esc(req.employment_raw||'—')}</b><span>Type</span></div></div>
        <h4>What they want</h4><ul class="list">${(req.needs||[]).map(n=>`<li>▸ ${esc(n)}</li>`).join('')||'<li class="co">See Description tab</li>'}</ul>${req.is_non_eng?'<div class="banner w">Non-engineering title</div>':''}`;
    }
  } else if(CURRENT_TAB==='likelihood'){
    if(!like) html='<span class="co">No likelihood</span>'; else {
      const b=like.breakdown||{};
      html=`<div class="verdict ${esc(like.verdict)}">${esc(like.verdict)} — ${like.likelihood}%</div><div class="banner">${esc(like.advice)}</div>
        <h4>Breakdown</h4><div class="kpi">${Object.entries(b).map(([k,v])=>`<div class="box"><b>${v}</b><span>${esc(k.replace('_',' '))}</span><div class="bar ${v>=70?'good':v>=45?'warn':'bad'}"><i style="width:${v}%"></i></div></div>`).join('')}</div>
        <div style="display:grid;grid-template-columns:1fr 1fr;gap:12px;margin-top:10px"><div><h4>Strengths</h4><ul class="list">${like.strengths.map(s=>`<li>✓ ${esc(s)}</li>`).join('')||'<li class="co">—</li>'}</ul></div><div><h4>Gaps</h4><ul class="list">${like.gaps.map(s=>`<li>○ ${esc(s)}</li>`).join('')||'<li class="co">—</li>'}</ul></div></div>
        ${like.blockers.length?`<h4>Blockers</h4><div>${like.blockers.map(b=>`<span class="flag b">${esc(b)}</span>`).join('')}</div>`:''}`;
    }
  } else if(CURRENT_TAB==='ats'){
    html='<span class="co">Loading ATS…</span>';
    $('#jobBody').innerHTML=html;
    jfetch(`/api/jobs/${encodeURIComponent(j.job_id)}/ats/`).then(d=>{
      if(d.error) throw new Error(d.error);
      const ats=d;
      html=`<div class="kpi"><div class="box"><b>${ats.score}%</b><span>ATS Score</span></div><div class="box"><b>${ats.breakdown.keywords}%</b><span>Keywords</span></div><div class="box"><b>${ats.breakdown.format}%</b><span>Format</span></div><div class="box"><b>${ats.words}</b><span>Words</span></div></div>
        <div class="verdict ${ats.score>=80?'High':ats.score>=65?'Medium':ats.score>=50?'Low':'Long'}">${esc(ats.verdict)}</div>
        <h4>Must-have keywords (JD)</h4><div>${ats.must_have.map(k=>`<span class="chip ${ats.have.includes(k)?'have':'gap'}">${esc(k)} ${ats.have.includes(k)?'✓':'○'}</span>`).join('')||'<span class="co">—</span>'}</div>
        ${ats.missing.length?`<div class="banner w" style="margin-top:10px"><b>Missing in resume:</b> ${esc(ats.missing.join(', '))}</div>`:''}
        <h4>Advice</h4><ul class="list">${ats.advice.map(a=>`<li>💡 ${esc(a)}</li>`).join('')}</ul>
        <h4>Nice to have</h4><div>${ats.nice_to_have.map(k=>`<span class="chip neutral">${esc(k)}</span>`).join('')||'<span class="co">—</span>'}</div>
        <h4>Resume format checks</h4><ul class="list">${(ats.checks||[]).map(c=>`<li>${c.ok?'✓':'○'} ${esc(c.check)}${c.ok?'':` <span class="co">— ${esc(c.fix)}</span>`}</li>`).join('')}</ul>`;
      $('#jobBody').innerHTML=html;
    }).catch(e=>{ $('#jobBody').innerHTML=`<div class="banner w">${esc(e.message)}</div>`;});
    return;
  } else if(CURRENT_TAB==='interview'){
    html='<span class="co">Loading prep…</span>';
    $('#jobBody').innerHTML=html;
    jfetch(`/api/jobs/${encodeURIComponent(j.job_id)}/interview/`).then(d=>{
      if(d.error) throw new Error(d.error);
      html=`<h4>Interview Questions (${d.questions.length})</h4><ul class="list">${d.questions.map((q,i)=>`<li><b>${i+1}. ${esc(q.q)}</b><br><span class="co">Why: ${esc(q.why)}</span><br><span class="co">STAR: ${esc(q.star)}</span></li>`).join('')}</ul>
        <h4>Prep Checklist</h4><ul class="list">${d.checklist.map(c=>`<li>▸ ${esc(c)}</li>`).join('')}</ul>
        <div class="banner g"><b>Tip:</b> ${esc(d.tip)}</div>`;
      $('#jobBody').innerHTML=html;
    }).catch(e=>{ $('#jobBody').innerHTML=`<div class="banner w">${esc(e.message)}</div>`;});
    return;
  } else if(CURRENT_TAB==='salary'){
    html='<span class="co">Loading salary…</span>';
    $('#jobBody').innerHTML=html;
    jfetch(`/api/jobs/${encodeURIComponent(j.job_id)}/salary/`).then(d=>{
      const peers=d.peers||{n:0}, money=n=>n==null?'—':n.toLocaleString();
      const peerLine=peers.n?`<p class="co">Similar ${esc(peers.basis)} you've collected (${peers.n} state pay): median <b>${esc(peers.unit.split('/')[0]==='TT$'?'TT$':'US$')}${money(peers.median)}</b>/mo, middle half ${money(peers.p25)}–${money(peers.p75)}.</p>`:'<p class="co">Not enough comparable listings with stated pay yet.</p>';
      if(!d.has_salary){
        html=`<div class="banner">This posting does not state pay.</div>${peerLine}${d.floor_ttd?`<p class="co">Your floor: TT$${money(d.floor_ttd)}/mo (≈US$${money(Math.round(d.floor_ttd/d.fx))}). Ask for the range before investing in an application.</p>`:'<p class="co">Set a minimum pay on the Profile page to compare against it.</p>'}`;
      } else {
        const vs={above:['g','Above your floor'],meets:['','Meets your floor'],below:['w','Below your floor']}[d.vs_floor]||['','No floor set'];
        html=`<div class="kpi">
          <div class="box"><b>TT$${money(d.monthly_ttd_min)}${d.monthly_ttd_max>d.monthly_ttd_min?'–'+money(d.monthly_ttd_max):''}</b><span>per month</span></div>
          <div class="box"><b>US$${money(d.monthly_usd_min)}${d.monthly_usd_max>d.monthly_usd_min?'–'+money(d.monthly_usd_max):''}</b><span>per month</span></div>
          <div class="box"><b>${esc(d.currency)}</b><span>listed in</span></div>
          <div class="box"><b>${esc(d.position||'—')}</b><span>vs similar</span></div></div>
          <div class="banner ${vs[0]}"><b>${vs[1]}</b>${d.floor_ttd?` — your floor is TT$${money(d.floor_ttd)}/mo`:''}</div>${peerLine}
          <p class="co">Converted at TT$${d.fx}/US$. Annual and hourly figures are normalised to monthly.</p>`;
      }
      $('#jobBody').innerHTML=html;
    }).catch(e=>{ $('#jobBody').innerHTML=`<div class="banner w">${esc(e.message)}</div>`;});
    return;
  } else if(CURRENT_TAB==='ai'){
    html='<span class="co">Scoring AI match…</span>';
    $('#jobBody').innerHTML=html;
    jfetch(`/api/jobs/${encodeURIComponent(j.job_id)}/ai-match/`).then(d=>{
      html=`<div class="kpi"><div class="box"><b>${d.score}%</b><span>Resume ↔ posting</span></div><div class="box"><b>${esc(d.method)}</b><span>Method</span></div><div class="box"><b>${d.cosine}</b><span>Similarity</span></div></div>
        <div class="banner ${d.score>=70?'g':d.score>=50?'':'w'}"><b>${esc(d.explanation)}</b></div>
        ${(d.top_terms||[]).length?`<div class="co">Skills the posting names: ${d.top_terms.map(t=>`<span class="chip neutral">${esc(t)}</span>`).join('')}</div>`:''}
        <h4>Best resume passage for each requirement</h4>
        ${(d.passages||[]).map(p=>`<div class="req ${p.score>=.5?'met':p.score>=.3?'partial':'gap'}"><div class="req-s">${p.score>=.5?'●':p.score>=.3?'◐':'○'}</div><div class="req-b"><div class="req-t">${esc(p.requirement)}</div><blockquote class="evid"><span class="co">${esc(p.where)}</span><br>${esc(p.passage)}</blockquote></div><div class="req-n">${Math.round(p.score*100)}%</div></div>`).join('')||'<p class="co">No requirements to compare.</p>'}
        ${d.method==='bm25'?'<p class="co">Keyword retrieval. <a href="'+pageUrl('profile')+'">Install an embedding model</a> for semantic matching.</p>':''}`;
      $('#jobBody').innerHTML=html;
    }).catch(e=>{ $('#jobBody').innerHTML=`<div class="banner w">${esc(e.message)}</div>`;});
    return;
  } else if(CURRENT_TAB==='tailor'){
    html='<span class="co">Tailoring resume…</span>';
    $('#jobBody').innerHTML=html;
    jfetch(`/api/jobs/${encodeURIComponent(j.job_id)}/tailor/`).then(d=>{
      html=`<div class="banner g"><b>Lead with:</b> ${esc(d.lead_with)}</div>
        <div class="co" style="margin:8px 0"><b>Cover open:</b> “${esc(d.cover_open)}”</div>
        <h4>Missing keywords (JD has, resume not)</h4><div>${d.missing_keywords.length? d.missing_keywords.map(k=>`<span class="chip gap">${esc(k)} ○</span>`).join('') : '<span class="co">None — well aligned</span>'}</div>
        <h4>Suggestions</h4><ul class="list">${d.injections.map(s=>`<li>💡 ${esc(s)}</li>`).join('')||'<li class="co">—</li>'}</ul>
        <h4>Bullets to use</h4><ul class="list">${d.bullets.map(b=>`<li>▸ ${esc(b)}</li>`).join('')}</ul>`;
      $('#jobBody').innerHTML=html;
    }).catch(e=>{ $('#jobBody').innerHTML=`<div class="banner w">${esc(e.message)}</div>`;});
    return;
  } else if(CURRENT_TAB==='raw'){
    const showLinks=(SETTINGS.preferences||{}).show_links!==false;
    html=`<div class="legend-note" id="hlLegend" hidden><i class="sw have"></i> you have it <i class="sw rel"></i> adjacent <i class="sw miss"></i> missing</div><pre id="postingText" style="white-space:pre-wrap;font-size:13px;line-height:1.6">${esc(j.description||'—').slice(0,12000)}</pre><div class="co" style="margin-top:10px">Source: ${esc(j.source)} · ${showLinks?`<a href="${esc(j.url)}" target="_blank">Open original</a><br>Apply link: <code style="word-break:break-all">${esc(j.url||'—')}</code>${j.alt_urls?`<br>Alt links: <code style="word-break:break-all">${esc(j.alt_urls)}</code>`:''}`:'<span class="co">Links hidden — enable in Settings</span>'}</div>`;
  }
  $('#jobBody').innerHTML=html;
  if(CURRENT_TAB==='raw' && typeof highlightPosting==='function') highlightPosting(j);
}
$('#jobCopy').onclick=async()=>{if(!CURRENT_JOB) return; await navigator.clipboard.writeText(CURRENT_JOB.url||''); $('#jobCopy').textContent='Copied'; setTimeout(()=>$('#jobCopy').textContent='Copy Link',1200);};
$('#jobCoverBtn').onclick=()=>{ if(!CURRENT_JOB) return; const id=CURRENT_JOB.job_id; jobDlg.close(); draftLetter(id, $('#jobCoverBtn')); };
async function draftLetter(jobId, btn){
  const old=btn?btn.textContent:'';
  if(btn){ btn.disabled=true; btn.textContent='Drafting…'; }
  $('#dlgTitle').textContent='Drafting letter';
  $('#letter').textContent='Writing the letter. If a model is running, this can take a minute. This window stays open.';
  $('#dlgNote').textContent=jobId;
  $('#dlgApply').href='#';
  if(typeof dlg.showModal==='function' && !dlg.open) dlg.showModal();
  showLive('Drafting letter…');
  try{
    const d=await jfetch('/api/cover/',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({job_id:jobId})});
    if(!d.ok) throw new Error(d.error||'Letter failed');
    let done=d;
    if(d.pending){
      for(let i=0;i<150;i++){
        await new Promise(r=>setTimeout(r,800));
        const s=await jfetch('/api/cover/');
        $('#letter').textContent=s.busy?`Still writing… ${i+1}`:(s.error||s.text||'');
        if(!s.busy){ done=s; break; }
      }
      if(done.busy) throw new Error('The draft is still running. Check back in a moment.');
      if(done.error) throw new Error(done.error);
    }
    const job=done.job||d.job||{};
    $('#dlgTitle').textContent=`${job.title||'Letter'} — ${job.company||''}`;
    $('#letter').textContent=done.text||'(empty letter)';
    $('#dlgNote').textContent=`${done.backend||'draft'} · ${done.path||''}`;
    $('#dlgApply').href=job.url||'#';
    showLive('Letter ready');
    const s=$('#liveStatus'); if(s) s.classList.remove('busy');
  }catch(e){
    $('#dlgTitle').textContent='Letter failed';
    $('#letter').textContent=e.message;
    $('#dlgNote').textContent='Nothing was saved.';
    showLive('Failed: '+e.message);
    const s=$('#liveStatus'); if(s){ s.textContent='Failed'; s.classList.remove('busy'); }
  }finally{
    if(btn){ btn.textContent=old||'Draft letter'; btn.disabled=false; }
  }
}
$('#bCopy').onclick=async()=>{await navigator.clipboard.writeText($('#letter').textContent); $('#bCopy').textContent='Copied'; setTimeout(()=>$('#bCopy').textContent='Copy',1200);};
