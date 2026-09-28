// pipeline.js — the Pipeline page: tracked jobs, follow-up dates, notes, recent edits.
async function saveFollowup(job, date, notes){
  await jfetch(`/api/jobs/${encodeURIComponent(job.job_id)}/status/`,{method:'PUT',headers:{'Content-Type':'application/json'},body:JSON.stringify({status:job.app_status||'New', followup_date:date, notes})});
  job.followup_date=date; job.notes=notes;
}
async function paintPipeline(force){
  const body=$('#pipelineBody'); if(!body) return;
  if(!force && document.activeElement && document.activeElement.closest && document.activeElement.closest('#pipelineBody')) return;
  const tracked=JOBS.filter(j=>(j.app_status||'New')!=='New' || j.starred);
  const today=new Date().toISOString().slice(0,10);
  body.innerHTML=`<div>${tracked.map(j=>{
    const due=j.followup_date && j.followup_date<=today && !/Rejected|Passed|Offer/.test(j.app_status||'');
    return `<div class="pipe-row ${due?'due':''}">
      <button type="button" data-details="${esc(j.job_id)}" style="text-align:left"><span class="who">${esc(j.company)}</span><span class="sub co">${esc(j.title)} · ${esc(j.app_status||'New')}</span></button>
      <select class="status-sel" data-status="${esc(j.job_id)}">${["Shortlisted","Applied","Interviewing","Offer","Rejected","Passed on it","New"].map(o=>`<option ${o===(j.app_status||'New')?'selected':''}>${o}</option>`).join('')}</select>
      <input type="date" data-follow="${esc(j.job_id)}" value="${esc(j.followup_date||'')}">
      <input type="text" data-note="${esc(j.job_id)}" value="${esc(j.notes||'')}" placeholder="Note">
    </div>`;
  }).join('')||'<p class="quiet">Nothing in the pipeline. Shortlist a role from the ledger.</p>'}</div>
  <div class="activity"><h2 class="sheet-title">Recent edits</h2><ul id="activityList"><li class="quiet">Loading</li></ul></div>`;
  body.querySelectorAll('[data-details]').forEach(el=>el.onclick=()=>openJob(el.dataset.details));
  body.querySelectorAll('[data-status]').forEach(el=>el.onchange=async()=>{
    const jid=el.dataset.status, st=el.value;
    await jfetch(`/api/jobs/${encodeURIComponent(jid)}/status/`,{method:'PUT',headers:{'Content-Type':'application/json'},body:JSON.stringify({status:st})});
    const j=JOBS.find(x=>x.job_id===jid); if(j) j.app_status=st;
    paintPipeline(true);
  });
  body.querySelectorAll('[data-follow]').forEach(el=>el.onchange=async()=>{
    const j=JOBS.find(x=>x.job_id===el.dataset.follow); if(!j) return;
    const note=body.querySelector(`[data-note="${CSS.escape(j.job_id)}"]`);
    await saveFollowup(j, el.value, note?note.value:'');
  });
  body.querySelectorAll('[data-note]').forEach(el=>el.onchange=async()=>{
    const j=JOBS.find(x=>x.job_id===el.dataset.note); if(!j) return;
    const date=body.querySelector(`[data-follow="${CSS.escape(j.job_id)}"]`);
    await saveFollowup(j, date?date.value:'', el.value);
  });
  try{
    const d=await jfetch('/api/activity/');
    const ul=$('#activityList'); if(!ul) return;
    ul.innerHTML=(d.events||[]).length?(d.events||[]).map(ev=>`<li><b>${esc(ev.company||ev.title||ev.job_id)}</b> ${esc(ev.from_status||'New')} to ${esc(ev.to_status)}${ev.note?` · ${esc(ev.note)}`:''}</li>`).join(''):'<li class="quiet">No edits yet.</li>';
  }catch(e){ const ul=$('#activityList'); if(ul) ul.innerHTML=`<li>${esc(e.message)}</li>`; }
}

// the funnel numbers across the top (from /api/pipeline/)
async function paintPipeFigures(){
  const el=$('#pipeFigures'); if(!el) return;
  try{
    const p=await jfetch('/api/pipeline/'), by=Object.fromEntries(p.stages.map(s=>[s.status,s.count]));
    const fig=(l,v,sub='')=>`<div class="fig"><div class="fig-label">${esc(l)}</div><div class="fig-value">${v}</div>${sub?`<div class="quiet" style="font-size:12px">${esc(sub)}</div>`:''}</div>`;
    el.innerHTML=fig('Shortlisted',by.Shortlisted||0)+fig('Applied',by.Applied||0)+fig('Interviewing',by.Interviewing||0)+fig('Offer',by.Offer||0)+fig('Starred',p.starred||0)+fig('Interview rate',p.applied?p.interview_rate+'%':'—',p.applied?`of ${p.applied} applied`:'no applications yet');
  }catch(e){ el.innerHTML=''; }
}
const _pipePaint=()=>Promise.all([paintPipeFigures(),paintPipeline()]);
Object.assign(PAGE_HOOKS,{ init:_pipePaint, refresh:()=>paintPipeline() });
