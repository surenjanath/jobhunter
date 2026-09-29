// coach.js — the Interview page's other tabs: story bank, drills, real interviews (prep plan, log, inbox) and weekly
// progress. The mock interview itself is interview.js. Everything here is /api/coach/* (coach/views.py).
const CS={tab:'practice', rendered:{}};
const cpost=(url,body,method)=>jfetch(url,{method:method||'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body||{})});
const dstr=d=>d?new Date(String(d).length<=10?d+'T12:00:00':d).toLocaleDateString(undefined,{weekday:'short',month:'short',day:'numeric'}):'—';
const trackedJobs=()=>{ const t=JOBS.filter(j=>j.app_status&&!['New','Passed on it'].includes(j.app_status)); return (t.length?t:[...JOBS].sort((a,b)=>(b.fit_score||0)-(a.fit_score||0)).slice(0,60)); };
const jobOpts=(sel)=>trackedJobs().map(j=>`<option value="${esc(j.job_id)}" ${j.job_id===sel?'selected':''}>${esc(j.title)} · ${esc(j.company)}${j.app_status&&j.app_status!=='New'?` (${esc(j.app_status)})`:''}</option>`).join('');

function coachTab(t){
  CS.tab=t;
  document.querySelectorAll('#ivTabs [data-tab]').forEach(b=>b.classList.toggle('on',b.dataset.tab===t));
  document.querySelectorAll('[data-pane]').forEach(p=>p.hidden=p.dataset.pane!==t);
  try{ history.replaceState(null,'',t==='practice'?location.pathname+location.search:'#'+t); }catch(e){}
  ({stories:renderStories, drills:renderDrills, real:renderReal, progress:renderProgress})[t]?.();
}
async function coachBadges(){
  try{ const d=await jfetch('/api/coach/drills/'); const b=$('#ivDueBadge'); b.hidden=!d.due.length; b.textContent=d.due.length; }catch(e){}
  try{ const d=await jfetch('/api/coach/inbox/'); const b=$('#ivInboxBadge'); b.hidden=!d.suggestions.length; b.textContent=d.suggestions.length; }catch(e){}
}

// ---- stories ---------------------------------------------------------------------------------------------------------
async function renderStories(){
  const el=$('#csStories'); el.innerHTML='<p class="co">Loading…</p>';
  let d; try{ d=await jfetch('/api/coach/stories/'); }catch(e){ el.innerHTML=`<div class="banner w">${esc(e.message)}</div>`; return; }
  el.innerHTML=`<p class="quiet">Your best answers, kept as reusable STAR stories. Most interview questions are the same five or six stories told
      from different angles. Check a role below to see which of its requirements you already have a story for, and which you'd be improvising.</p>
    <div class="block"><h3>Coverage for a role</h3>
      <div class="pxrow"><select id="csCovJob" style="flex:1">${jobOpts(new URLSearchParams(location.search).get('job'))}</select><button type="button" class="sm" id="csCovGo">Check</button></div>
      <div id="csCov"></div></div>
    <div class="block"><h3>Your stories <span class="quiet">${d.stories.length}</span></h3>
      ${d.stories.map(s=>`<details class="iv-q cs-story" data-id="${s.id}"><summary><b>${s.score??'—'}</b> <span>${esc(s.title)}</span>
          <span class="co">· ${s.skills.slice(0,4).map(esc).join(', ')||'no skills tagged'}</span></summary>
        ${s.question?`<div class="co">Told for: “${esc(s.question)}”</div>`:''}
        <div style="margin:6px 0">${Object.entries(s.star||{}).map(([n,v])=>`<span class="flag ${v?'g':'b'}">${v?'✓':'○'} ${esc(n)}</span>`).join('')}</div>
        <textarea rows="5" style="width:100%">${esc(s.text)}</textarea>
        <div class="actions"><button type="button" class="sm" data-save="${s.id}">Save changes</button><button type="button" class="text" data-hear="${s.id}">🔊 Hear it</button>
          <span class="spacer"></span><button type="button" class="text" data-del="${s.id}">Delete</button></div>
      </details>`).join('')||'<p class="co">No stories yet. Save one from a mock-interview report (★ Save as a story), or write one below.</p>'}</div>
    <div class="block"><h3>Write a story</h3>
      <input id="csNewQ" placeholder="The question it answers (optional), e.g. Tell me about a time you fixed a process" style="width:100%">
      <textarea id="csNewT" rows="5" style="width:100%;margin-top:6px" placeholder="Situation → what you did → the result, with a number"></textarea>
      <div class="actions"><button type="button" class="go sm" id="csNewGo">Add story</button></div></div>`;
  $('#csCovGo').onclick=()=>renderCoverage($('#csCovJob').value);
  if($('#csCovJob').value) renderCoverage($('#csCovJob').value);
  $('#csNewGo').onclick=async()=>{ try{ await cpost('/api/coach/stories/',{question:$('#csNewQ').value,text:$('#csNewT').value}); renderStories(); }catch(e){ toast(e.message,'bad'); } };
  el.querySelectorAll('[data-save]').forEach(b=>b.onclick=async()=>{ const t=b.closest('details').querySelector('textarea').value;
    try{ await cpost(`/api/coach/stories/${b.dataset.save}/`,{text:t},'PUT'); toast('Saved'); renderStories(); }catch(e){ toast(e.message,'bad'); } });
  el.querySelectorAll('[data-hear]').forEach(b=>b.onclick=()=>say(b.closest('details').querySelector('textarea').value));
  el.querySelectorAll('[data-del]').forEach(b=>b.onclick=async()=>{ if(b.dataset.sure!=='1'){ b.dataset.sure='1'; b.textContent='Delete?'; return; }
    try{ await jfetch(`/api/coach/stories/${b.dataset.del}/`,{method:'DELETE'}); renderStories(); }catch(e){ toast(e.message,'bad'); } });
}
async function renderCoverage(jobId){
  const el=$('#csCov'); if(!jobId){ el.innerHTML=''; return; } el.innerHTML='<p class="co">Checking…</p>';
  try{ const c=await jfetch(`/api/coach/coverage/${encodeURIComponent(jobId)}/`);
    el.innerHTML=`<p><b>${c.covered} of ${c.total}</b> of this role's requirements have a story behind them${c.partial?`, and ${c.partial} more partly (a related skill)`:''}.
        ${c.gaps.length?`<span class="co">Write stories for: ${c.gaps.slice(0,5).map(esc).join(', ')}.</span>`:'<span class="co">Every requirement is covered.</span>'}</p>
      <table class="src-table"><tbody>${c.rows.map(r=>`<tr><td>${esc(r.skill||r.requirement)}</td><td>${r.stories.length?r.stories.map(s=>`<span class="flag ${r.partial?'w':'g'}">${r.partial?`~ via ${esc(r.partial)}:`:'✓'} ${esc(s.title)}</span>`).join(' '):'<span class="flag b">no story</span>'}</td></tr>`).join('')}</tbody></table>`;
  }catch(e){ el.innerHTML=`<div class="banner w">${esc(e.message)}</div>`; }
}

// ---- drills ----------------------------------------------------------------------------------------------------------
async function renderDrills(){
  const el=$('#csDrills'); el.innerHTML='<p class="co">Loading…</p>';
  let d; try{ d=await jfetch('/api/coach/drills/'); }catch(e){ el.innerHTML=`<div class="banner w">${esc(e.message)}</div>`; return; }
  const row=x=>`<tr><td>${esc(x.question)}<div class="co">${esc(x.job_title||'')}${x.source==='real'?' · asked in a real interview':''}</div></td>
      <td>${x.last_score??'—'}</td><td>${x.reps}</td><td>${dstr(x.next_due)}</td><td class="iv-rowact"><button type="button" class="text" data-del="${x.id}">✕</button></td></tr>`;
  el.innerHTML=`<p class="quiet">Questions you scored low on in mock interviews, and questions you were asked in real ones, come back on a schedule:
      a weak answer tomorrow, a good one in a few days, a strong one weeks later. Five minutes a day beats one long session a week.</p>
    <div class="block"><h3>Due today <span class="quiet">${d.due.length}</span></h3>
      ${d.due.length?`<table class="src-table"><thead><tr><th>Question</th><th>Last</th><th>Reps</th><th>Due</th><th></th></tr></thead><tbody>${d.due.map(row).join('')}</tbody></table>
        <div class="actions"><button type="button" class="go sm" id="csDrillGo">Start today's drill (${Math.min(5,d.due.length)} question${Math.min(5,d.due.length)>1?'s':''}, spoken)</button></div>`
      :'<p class="co">Nothing due. Weak answers from your mock interviews land here automatically.</p>'}</div>
    <div class="block"><h3>Coming up</h3>${d.upcoming.length?`<table class="src-table"><tbody>${d.upcoming.map(row).join('')}</tbody></table>`:'<p class="co">—</p>'}</div>
    ${d.mastered.length?`<details class="block"><summary><h3 style="display:inline">Mastered <span class="quiet">${d.mastered.length}</span></h3></summary><table class="src-table"><tbody>${d.mastered.map(row).join('')}</tbody></table></details>`:''}
    <div class="block"><h3>Add a question to practise</h3><div class="pxrow"><input id="csDrillQ" style="flex:1" placeholder="e.g. What's your biggest weakness?"><button type="button" class="sm" id="csDrillAdd">Add</button></div></div>`;
  el.querySelectorAll('[data-del]').forEach(b=>b.onclick=async()=>{ try{ await jfetch(`/api/coach/drills/${b.dataset.del}/`,{method:'DELETE'}); renderDrills(); coachBadges(); }catch(e){ toast(e.message,'bad'); } });
  $('#csDrillAdd').onclick=async()=>{ try{ await cpost('/api/coach/drills/',{question:$('#csDrillQ').value}); renderDrills(); }catch(e){ toast(e.message,'bad'); } };
  const go=$('#csDrillGo'); if(go) go.onclick=()=>{
    const pick=d.due.slice(0,5), job=JOBS.find(j=>j.job_id===(pick.find(x=>x.job_id)||{}).job_id)||trackedJobs()[0];
    if(!job){ toast('Add a role to your ledger first','bad'); return; }
    coachTab('practice');
    // each drill keeps its own type; a negotiation drill gets its offer back from the question text
    const offerIn=q=>{ const m=q.match(/(\d[\d,]{2,})/); return m?{amount:+m[1].replace(/,/g,'')}:null; };
    ivBegin(job.job_id, pick.length, {questions:pick.map(x=>({q:x.question, kind:x.kind, offer:x.kind==='negotiation'?offerIn(x.question):null})),
      drillIds:Object.fromEntries(pick.map(x=>[x.question,x.id])),
      follow:true, realistic:true, persona:'neutral', kind:'behavioural'});
  };
}

// ---- real interviews: add, prep plan, log, inbox ------------------------------------------------------------------------
async function renderReal(){
  const el=$('#csReal'); el.innerHTML='<p class="co">Loading…</p>';
  let d, ib; try{ [d,ib]=await Promise.all([jfetch('/api/coach/interviews/'), jfetch('/api/coach/inbox/')]); }catch(e){ el.innerHTML=`<div class="banner w">${esc(e.message)}</div>`; return; }
  const tomorrow=new Date(Date.now()+86400000).toISOString().slice(0,10);
  el.innerHTML=`
    ${ib.suggestions.length?`<div class="block"><h3>From your inbox <span class="quiet">confirm each one</span></h3>
      ${ib.suggestions.map(s=>`<div class="cs-sug"><div><b>${esc(s.kind)}</b> · ${esc(s.subject||'(no subject)')} <span class="co">${esc(s.sender||'')}</span>
          <div class="co">${esc(s.snippet.slice(0,220))}</div>
          <div>Move <b>${esc(s.job_title)} @ ${esc(s.company)}</b> to <b>${esc(s.suggested_status)}</b>?${s.mentions_date?` <span class="co">(mentions ${esc(s.mentions_date)})</span>`:''}</div></div>
        <div class="actions"><button type="button" class="go sm" data-apply="${s.id}" data-job="${esc(s.job_id)}" data-st="${esc(s.suggested_status)}" data-kind="${esc(s.kind)}">Apply</button>
          <button type="button" class="text" data-dismiss="${s.id}">Dismiss</button></div></div>`).join('')}</div>`:''}
    <div class="block"><h3>Upcoming</h3>
      ${d.upcoming.map(r=>`<div class="cs-ri"><div><b>${esc(r.job_title)}</b> · ${esc(r.company)} <span class="co">· ${esc(r.stage)} · ${dstr(r.scheduled_on)}</span></div>
          <div class="co">${r.days_left===0?'Today':r.days_left===1?'Tomorrow':`In ${r.days_left} days`}</div>
          <div class="actions"><button type="button" class="go sm" data-plan="${r.id}">Prep plan</button><button type="button" class="text" data-log="${r.id}">Log it</button>
            <button type="button" class="text" data-rdel="${r.id}">Remove</button></div><div id="csPlan${r.id}"></div></div>`).join('')||'<p class="co">No interviews scheduled. Add one below to get a day-by-day prep plan (also added to your calendar feed).</p>'}
      <div class="pxrow" style="margin-top:12px;flex-wrap:wrap"><select id="csRiJob" style="flex:1;min-width:220px">${jobOpts()}</select>
        <input type="date" id="csRiDate" value="${tomorrow}"><select id="csRiStage"><option value="screen">Recruiter screen</option><option value="technical">Technical</option><option value="onsite">Panel / on-site</option><option value="final">Final</option></select>
        <button type="button" class="sm" id="csRiAdd">Add interview</button></div></div>
    <div class="block"><h3>Past interviews</h3>
      ${d.real_vs_mock?`<p class="banner"><b>${esc(d.real_vs_mock.read)}</b><br><span class="co">Real interviews felt ${d.real_vs_mock.felt_avg}/5 on average; mock average ${d.real_vs_mock.mock_avg}/100; ${d.real_vs_mock.advance_rate??'—'}% advanced.</span></p>`:''}
      ${d.past.map(r=>`<div class="cs-ri"><div><b>${esc(r.job_title)}</b> · ${esc(r.company)} <span class="co">· ${esc(r.stage)} · ${dstr(r.scheduled_on)}</span></div>
          ${r.logged?`<div class="co">Felt ${r.felt??'—'}/5 · ${esc(r.outcome||'waiting')} · ${r.questions.length} question${r.questions.length===1?'':'s'} logged (added to your drills)</div>
            <div class="actions"><button type="button" class="text" data-thanks="${esc(r.job_id)}">Write the thank-you note</button><button type="button" class="text" data-log="${r.id}">Edit log</button></div>`
          :`<div class="actions"><button type="button" class="go sm" data-log="${r.id}">Log how it went</button><button type="button" class="text" data-thanks="${esc(r.job_id)}">Thank-you note</button></div>`}
          <div id="csLog${r.id}"></div></div>`).join('')||'<p class="co">After a real interview, log the questions you were asked and how it felt. They become drills, and over time you can see whether your mocks predict the real thing.</p>'}</div>
    <div class="block"><h3>Paste a recruiter email</h3>
      <p class="co">Paste an email (interview invite, rejection, offer, assessment) and it's matched to a job you're tracking with a suggested status. Nothing changes until you click Apply.
        To check your inbox automatically instead, run <code>python manage.py check_inbox</code> with an IMAP app password (read-only; see docs/API.md).</p>
      <input id="csMailSubj" placeholder="Subject" style="width:100%"><input id="csMailFrom" placeholder="From (e.g. jane@company.com)" style="width:100%;margin-top:6px">
      <textarea id="csMailBody" rows="5" style="width:100%;margin-top:6px" placeholder="Email text"></textarea>
      <div class="actions"><button type="button" class="sm" id="csMailGo">Read it</button></div><div id="csMailOut"></div></div>`;
  const on=(sel,fn)=>el.querySelectorAll(sel).forEach(b=>b.onclick=()=>fn(b));
  on('[data-plan]',b=>renderPlan(+b.dataset.plan));
  on('[data-log]',b=>renderLogForm(+b.dataset.log, [...d.upcoming,...d.past].find(x=>x.id===+b.dataset.log)));
  on('[data-rdel]',async b=>{ if(b.dataset.sure!=='1'){ b.dataset.sure='1'; b.textContent='Remove?'; return; } await jfetch(`/api/coach/interviews/${b.dataset.rdel}/`,{method:'DELETE'}); renderReal(); });
  on('[data-thanks]',b=>{ if(!JOBS.find(j=>j.job_id===b.dataset.thanks)){ toast('That role is no longer in the ledger','bad'); return; } openJob(b.dataset.thanks).then(()=>setTab('outreach')); });
  on('[data-dismiss]',async b=>{ await cpost(`/api/coach/inbox/${b.dataset.dismiss}/`,{action:'dismissed'}); renderReal(); coachBadges(); });
  on('[data-apply]',async b=>{
    try{ await jfetch(`/api/jobs/${encodeURIComponent(b.dataset.job)}/status/`,{method:'PUT',headers:{'Content-Type':'application/json'},body:JSON.stringify({status:b.dataset.st})});
      await cpost(`/api/coach/inbox/${b.dataset.apply}/`,{action:'applied'});
      const j=JOBS.find(x=>x.job_id===b.dataset.job); if(j) j.app_status=b.dataset.st;
      toast(`Moved to ${b.dataset.st}`+(b.dataset.kind==='invite'?'. Add the interview date below to get a prep plan.':''));
      renderReal(); coachBadges(); }catch(e){ toast(e.message,'bad'); }
  });
  $('#csRiAdd').onclick=async()=>{ try{ await cpost('/api/coach/interviews/',{job_id:$('#csRiJob').value,scheduled_on:$('#csRiDate').value,stage:$('#csRiStage').value}); renderReal(); }catch(e){ toast(e.message,'bad'); } };
  $('#csMailGo').onclick=async()=>{
    const out=$('#csMailOut'); out.innerHTML='<span class="co">Reading…</span>';
    try{ const r=await cpost('/api/coach/inbox/parse/',{subject:$('#csMailSubj').value,sender:$('#csMailFrom').value,body:$('#csMailBody').value});
      out.innerHTML=r.suggestion_id?'<div class="banner g">Matched. See the suggestion at the top of this tab.</div>'
        :`<div class="banner">Looks like: <b>${esc(r.kind)}</b>. ${r.suggested_status?(r.matches.length?'':'No tracked job matched it: check the company is in your pipeline (status other than New).'):'No pipeline change suggested.'}</div>`;
      if(r.suggestion_id){ renderReal(); coachBadges(); }
    }catch(e){ out.innerHTML=`<div class="banner w">${esc(e.message)}</div>`; }
  };
}
async function renderPlan(id){
  const box=$('#csPlan'+id); box.innerHTML='<p class="co">Building your plan…</p>';
  const st=await aiStatus();
  const draw=async ai=>{
    let p; try{ p=await jfetch(`/api/coach/interviews/${id}/plan/${ai?'?ai=1':''}`); }catch(e){ box.innerHTML=`<div class="banner w">${esc(e.message)}</div>`; return; }
    const b=p.brief, kind=p.plan.kind;
    box.innerHTML=`<div class="cs-plan">
      <h4>Day by day <span class="quiet">${p.plan.days_left} day${p.plan.days_left===1?'':'s'} to go</span></h4>
      <ul class="list">${p.plan.tasks.map(t=>`<li class="${t.overdue?'cs-over':''}"><label><input type="checkbox" data-task="${t.key}" ${t.done?'checked':''}> <b>${dstr(t.date)}</b> ${esc(t.text)}</label>
        ${t.key.startsWith('mock')?` <button type="button" class="text" data-mock="${kind}">start</button>`:''}${t.key==='drill'?' <button type="button" class="text" data-go="drills">open drills</button>':''}
        ${t.key==='stories'?' <button type="button" class="text" data-go="stories">open stories</button>':''}${t.key==='questions'?' <button type="button" class="text" data-mock="reverse">practise</button>':''}
        ${t.key==='baseline'?' <button type="button" class="text" data-go="practice">record</button>':''}</li>`).join('')}</ul>
      <h4>Research brief ${b.ai_provider?providerTag(b.ai_provider):''}</h4>
      ${b.ai_summary?`<p>${esc(b.ai_summary)}</p>`:''}
      ${b.about.length?`<p class="co">${b.about.map(esc).join(' ')}</p>`:''}
      <div>${b.stack.map(s=>`<span class="chip neutral">${esc(s)}</span>`).join('')}</div>
      ${b.values.length?`<p class="co">They say they value: ${b.values.map(esc).join(', ')}. Have an example ready for each.</p>`:''}
      ${b.ai_likely_questions?`<h4>Likely questions</h4><ul class="list">${b.ai_likely_questions.map(q=>`<li>? ${esc(q)}</li>`).join('')}</ul>`:''}
      ${b.ai_angles?`<h4>What to emphasise</h4><ul class="list">${b.ai_angles.map(q=>`<li>▸ ${esc(q)}</li>`).join('')}</ul>`:''}
      <h4>Questions to ask them</h4><ul class="list">${b.questions_to_ask.map(q=>`<li>? ${esc(q)}</li>`).join('')}</ul>
      <h4>Look up</h4><ul class="list">${b.look_up.map(q=>`<li>🔎 ${esc(q)}</li>`).join('')}</ul>
      <h4>Your stories for this role</h4><p><b>${p.coverage.covered}/${p.coverage.total}</b> requirements covered.${p.coverage.gaps.length?` <span class="co">Missing: ${p.coverage.gaps.slice(0,5).map(esc).join(', ')}</span>`:''}</p>
      ${st.any&&!b.ai_provider?'<button type="button" class="sm" data-aibrief>✦ Deeper brief with AI</button>':''}</div>`;
    box.querySelectorAll('[data-task]').forEach(c=>c.onchange=async()=>{
      const done=[...box.querySelectorAll('[data-task]:checked')].map(x=>x.dataset.task);
      try{ await cpost(`/api/coach/interviews/${id}/`,{done_tasks:done},'PUT'); }catch(e){ toast(e.message,'bad'); } });
    box.querySelectorAll('[data-go]').forEach(x=>x.onclick=()=>coachTab(x.dataset.go));
    box.querySelectorAll('[data-mock]').forEach(x=>x.onclick=()=>{ coachTab('practice'); ivBegin(p.interview.job_id, x.dataset.mock==='reverse'?1:5,
      {kind:x.dataset.mock, follow:true, realistic:true, persona:'tough', ai:!!st.active}); });
    const ab=box.querySelector('[data-aibrief]'); if(ab) ab.onclick=()=>{ ab.disabled=true; ab.textContent='Thinking…'; draw(true); };
  };
  draw(false);
}
function renderLogForm(id, r){
  const box=$('#csLog'+id)||$('#csPlan'+id); if(!box||!r) return;
  box.innerHTML=`<div class="cs-plan"><h4>How did it go?</h4>
    <textarea id="csLogQ${id}" rows="4" style="width:100%" placeholder="The questions they asked, one per line (they'll become drills)">${esc((r.questions||[]).join('\n'))}</textarea>
    <div class="pxrow" style="margin-top:6px;flex-wrap:wrap"><label class="co">How it felt <select id="csLogF${id}">${[1,2,3,4,5].map(n=>`<option value="${n}" ${r.felt===n?'selected':''}>${n} · ${['rough','shaky','okay','good','great'][n-1]}</option>`).join('')}</select></label>
      <label class="co">Outcome <select id="csLogO${id}">${['waiting','advanced','rejected','offer'].map(o=>`<option ${r.outcome===o?'selected':''}>${o}</option>`).join('')}</select></label></div>
    <textarea id="csLogN${id}" rows="2" style="width:100%;margin-top:6px" placeholder="Notes: what went well, what you'd change">${esc(r.notes||'')}</textarea>
    <div class="actions"><button type="button" class="go sm" id="csLogGo${id}">Save log</button></div></div>`;
  $('#csLogGo'+id).onclick=async()=>{
    try{ await cpost(`/api/coach/interviews/${id}/`,{log:{questions:$('#csLogQ'+id).value.split('\n'),felt:$('#csLogF'+id).value,outcome:$('#csLogO'+id).value,notes:$('#csLogN'+id).value}},'PUT');
      toast('Logged. The questions are in your drills.'); renderReal(); coachBadges(); }catch(e){ toast(e.message,'bad'); }
  };
}

// ---- progress --------------------------------------------------------------------------------------------------------
async function renderProgress(){
  const el=$('#csProgress'); el.innerHTML='<p class="co">Loading…</p>';
  let w; try{ w=await jfetch('/api/coach/weekly/'); }catch(e){ el.innerHTML=`<div class="banner w">${esc(e.message)}</div>`; return; }
  const fig=(label,k,suffix='')=>{ const v=w.this[k], dl=w.deltas[k]; return `<div><div class="quiet">${label}</div><div class="mid-num">${v??'—'}${suffix}
      ${dl!=null&&dl!==0?`<span class="quiet cs-delta">${dl>0?'+':''}${dl}</span>`:''}</div></div>`; };
  el.innerHTML=`<p class="quiet">The last seven days against the seven before. Is the search working, not just busy?</p>
    <div class="figures">${fig('Applied','applied')}<div><div class="quiet">Response rate</div><div class="mid-num">${w.response_rate??'—'}${w.response_rate!=null?'%':''}</div></div>
      ${fig('Real interviews','interviews')}${fig('Offers','offers')}${fig('Mock interviews','mocks')}${fig('Mock average','mock_avg')}${fig('Composure','composure_avg')}${fig('Drills done','drills')}${fig('Stories added','stories')}</div>
    <div class="banner"><ul class="list">${w.reads.map(r=>`<li>▸ ${esc(r)}</li>`).join('')}</ul></div>
    ${w.next_interview?`<p>Next interview: <b>${esc(w.next_interview.job_title)} @ ${esc(w.next_interview.company)}</b>, ${dstr(w.next_interview.scheduled_on)}. <button type="button" class="text" data-go="real">Open prep plan</button></p>`:''}
    ${w.due_drills?`<p>${w.due_drills} drill${w.due_drills>1?'s':''} due. <button type="button" class="text" data-go="drills">Do them now</button></p>`:''}`;
  el.querySelectorAll('[data-go]').forEach(x=>x.onclick=()=>coachTab(x.dataset.go));
}

// ---- wiring --------------------------------------------------------------------------------------------------------------
(function(){
  const prev=PAGE_HOOKS.init;
  PAGE_HOOKS.init=async d=>{
    if(prev) await prev(d);
    document.querySelectorAll('#ivTabs [data-tab]').forEach(b=>b.onclick=()=>coachTab(b.dataset.tab));
    const fromHash=()=>{ const want=(location.hash||'').slice(1); if(['stories','drills','real','progress'].includes(want)&&want!==CS.tab) coachTab(want); };
    fromHash(); window.addEventListener('hashchange', fromHash);
    coachBadges();
  };
})();
