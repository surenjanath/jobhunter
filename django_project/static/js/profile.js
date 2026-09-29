// profile.js — the Profile view: upload a resume, see what was extracted, correct it, set preferences.
// Classic script; uses the shared helpers in core.js.
let PROFILE=null, PROFILE_STALE=false, RESCORE_TIMER=null;
const WORK_MODE_INFO={
  both:['Both','Rank local and remote roles on merit'],
  local_first:['Local first','Prefer Trinidad & Tobago roles; remote still counts'],
  remote_first:['Remote first','Prefer remote roles; local still counts'],
  local_only:['Local only','Remote roles are treated as blockers'],
  remote_only:['Remote only','On-site / local roles are treated as blockers'],
};
const REGION_CHOICES=['Port of Spain','San Juan / Laventille','Tunapuna / Piarco','Arima / Sangre Grande','Chaguanas / Caroni','Couva / Point Lisas','San Fernando','Penal / Debe / Siparia','Princes Town / Rio Claro','Tobago'];

async function loadProfile(){
  const el=$('#resumeBody'); if(!el) return;
  if(!PROFILE) el.innerHTML='<span class="co">Loading…</span>';
  try{ PROFILE=await jfetch('/api/profile/'); paintProfile(); }
  catch(e){ el.innerHTML=`<div class="banner w">${esc(e.message)}</div>`; }
}
const pmsg=(t,bad)=>{ const m=$('#pfMsg'); if(m){ m.textContent=t||''; m.className=bad?'urgent':'quiet'; } };

function paintProfile(){
  const S=PROFILE, P=S.profile, st=S.status, el=$('#resumeBody');
  if(!el) return;
  const stale=PROFILE_STALE?`<div class="banner"><b>Your profile or preferences changed.</b> Scores are from before that. <button type="button" class="go sm" id="pfRescore">Re-score all jobs</button></div>`:'';
  const acct=!S.own_profile
    ? (P ? `<div class="banner g"><b>${AUTH.authenticated?'This is the shared instance profile.':'You’re trying this anonymously.'}</b> ${AUTH.authenticated?'Upload a resume below and it becomes private to your account instead.':'Like what you see? <button type="button" class="text" id="pfCreateAccount">Create a free account</button> to save this resume, its fit scores and your pipeline — and keep them private to you.'}</div>`
       : '')
    : '';
  const sem=st.semantic?`Semantic + keyword retrieval (${esc(st.embedding_model_index)})`:'Keyword retrieval (BM25)';
  const hint=!st.semantic?(st.embedding_model_available
      ?` An embedding model is installed (<b>${esc(st.embedding_model_available)}</b>) — <button type="button" class="text" id="pfReindex">index with it</button>.`
      :` For semantic matching run <code>ollama pull nomic-embed-text</code>, then <button type="button" class="text" id="pfReindex">re-index</button>.`):'';
  const upload=`
    <div class="dropzone" id="pfDrop" tabindex="0">
      <div><b>${P?'Replace your resume':'Add your resume'}</b></div>
      <div class="co">Drop a PDF, DOCX, Markdown or text file here, or <label class="filelink">choose a file<input type="file" id="pfFile" accept=".pdf,.docx,.doc,.rtf,.md,.txt" hidden></label></div>
      <div class="co">Read locally, nothing leaves this computer. <button type="button" class="text" id="pfPasteToggle">Paste text instead</button></div>
      <div id="pfPaste" hidden><textarea id="pfPasteText" rows="8" placeholder="Paste your resume text"></textarea><div class="actions"><button type="button" class="go" id="pfPasteGo">Use this text</button></div></div>
    </div>`;
  if(!P){ el.innerHTML=`${stale}<p class="quiet">No resume yet. Add one and every job is re-scored against what you have actually done.</p>${upload}<span id="pfMsg" class="quiet"></span>`; wireProfile(); return; }

  const byCat={}; P.skills.forEach(s=>(byCat[s.category]=byCat[s.category]||[]).push(s));
  const catOrder=Object.keys(byCat).sort((a,b)=>byCat[b].length-byCat[a].length);
  const skillsHtml=catOrder.map(cat=>`<div class="skillcat"><div class="co">${esc(cat)}</div>${byCat[cat].map(s=>`<span class="chip ${s.source==='manual'?'have':'neutral'}" title="${s.source==='manual'?'added by you':`${s.mentions} mention${s.mentions>1?'s':''}${s.in_skills_section?' · in your Skills section':''}`}">${esc(s.name)}${s.years?` <i>${s.years}y</i>`:''}<button type="button" class="x" data-rmskill="${esc(s.name)}" aria-label="Remove ${esc(s.name)}">×</button></span>`).join('')}</div>`).join('');
  const removed=(P.overrides.skills_remove||[]);
  const roles=P.roles.map(r=>`<li><b>${esc(r.title||'(untitled role)')}</b> <span class="co">${esc(r.company)}</span><div class="co">${esc(r.start)} – ${r.current?'present':esc(r.end)} · ${(r.months/12).toFixed(1)} yrs · ${r.bullets.length} achievements</div></li>`).join('')||'<li class="co">No dated roles were found. Use a “Month Year – Month Year” format under Experience.</li>';
  const pf=S.prefs, cal=S.calibration;
  const modeCards=S.work_modes.map(m=>`<label class="modecard ${pf.work_mode===m?'on':''}"><input type="radio" name="pfMode" value="${m}" ${pf.work_mode===m?'checked':''}><b>${esc(WORK_MODE_INFO[m][0])}</b><span class="co">${esc(WORK_MODE_INFO[m][1])}</span></label>`).join('');
  const regions=REGION_CHOICES.map(r=>`<label class="pillcheck"><input type="checkbox" data-region="${esc(r)}" ${pf.preferred_regions.includes(r)?'checked':''}> ${esc(r)}</label>`).join('');
  const calRow=(k,label)=>`<div class="calrow"><b>${label}</b> ${cal[k].p*100>=10?cal[k].p*100:(cal[k].p*100).toFixed(1)}% <span class="co">interview chance for an average application · ${esc(cal[k].source)}${cal[k].pending?` · ${cal[k].pending} awaiting reply`:''}</span></div>`;
  const llm=P.llm;
  const provs=Object.entries(S.llm_providers||{}).filter(([k,v])=>v&&k!=='template').map(([k])=>`<option value="${esc(k)}">${esc(k)}</option>`).join('');

  el.innerHTML=`${acct}${stale}
    <div class="figures">
      <div><div class="quiet">Experience</div><div class="mid-num">${P.years_experience}<span class="quiet"> yrs</span></div></div>
      <div><div class="quiet">Level</div><div class="mid-num" style="font-size:22px">${esc(P.seniority||'—')}</div></div>
      <div><div class="quiet">Skills found</div><div class="mid-num">${P.skills.length}</div></div>
      <div><div class="quiet">Roles</div><div class="mid-num">${P.roles.length}</div></div>
      <div><div class="quiet">Education</div><div class="mid-num" style="font-size:22px">${esc(P.highest_education||'—')}</div></div>
    </div>
    <p class="quiet">Reading <b>${esc(st.filename)}</b> · ${st.chunks} evidence passages · ${sem}.${hint} <span id="pfMsg" class="quiet"></span></p>
    <div class="actions" style="margin-top:0"><button type="button" id="pfRescore2">Re-score all jobs</button></div>
    ${upload}

    <div class="stack">
      <div class="block"><h3>Work history</h3><ul class="list plain">${roles}</ul>
        ${P.education.length?`<h3 style="margin-top:14px">Education</h3><ul class="list plain">${P.education.map(e=>`<li>${esc(e.text)}</li>`).join('')}</ul>`:''}
        ${P.domains.length?`<h3 style="margin-top:14px">Domains</h3>${P.domains.map(d=>`<span class="chip have">${esc(d)}</span>`).join('')}`:''}
        ${P.certifications.length?`<h3 style="margin-top:14px">Certifications</h3><ul class="list plain">${P.certifications.map(c=>`<li>${esc(c)}</li>`).join('')}</ul>`:''}
      </div>
      <div class="block"><h3>Achievements found <span class="quiet">(quantified)</span></h3><ul class="list plain">${P.achievements.slice(0,8).map(a=>`<li class="co" style="color:var(--ink)">${esc(a)}</li>`).join('')||'<li class="co">None with numbers. Adding figures (users, hours saved, revenue) strengthens matching and letters.</li>'}</ul>
        <h3 style="margin-top:14px">Correct experience</h3>
        <label>Total years <input type="number" step="0.5" min="0" max="50" id="pfYears" value="${P.years_experience}" style="width:80px"></label>
        <button type="button" class="sm" id="pfYearsSave">Save</button>
      </div>
    </div>

    <div class="block" style="margin-top:18px"><h3>Skills <span class="quiet">— extracted from your resume; remove anything wrong, add anything missing</span></h3>
      ${skillsHtml}
      <div class="addskill"><input id="pfSkillName" placeholder="Add a skill, e.g. Kubernetes" list="pfSkillList"><input id="pfSkillYears" type="number" step="0.5" min="0" placeholder="years" style="width:80px"><button type="button" class="sm" id="pfSkillAdd">Add</button></div>
      ${removed.length?`<div class="co" style="margin-top:8px">Removed by you: ${removed.map(n=>`<button type="button" class="text" data-restore="${esc(n)}">${esc(n)} ↺</button>`).join(' ')}</div>`:''}
    </div>

    <div class="block" style="margin-top:18px"><h3>Search preferences <span class="quiet">— these change fit and odds</span></h3>
      <div class="modecards">${modeCards}</div>
      <div class="two" style="margin-top:14px">
        <div><label>Minimum monthly pay, TT$ <input type="number" min="0" step="500" id="pfMinTTD" value="${pf.min_salary_monthly_ttd||''}" style="width:110px"></label><br>
          <label>Minimum monthly pay, US$ (remote) <input type="number" min="0" step="500" id="pfMinUSD" value="${pf.min_salary_monthly_usd||''}" style="width:110px"></label><br>
          <label><input type="checkbox" id="pfReloc" ${pf.willing_to_relocate?'checked':''}> Open to relocation if a role offers sponsorship</label><br>
          <label><input type="checkbox" id="pfContract" ${pf.open_to_contract?'checked':''}> Open to contract roles</label></div>
        <div><label>Target titles <span class="co">(comma separated)</span><br><input id="pfTitles" style="width:100%" value="${esc((pf.target_titles||[]).join(', '))}" placeholder="Solutions Engineer, Django Developer"></label><br>
          <label>Avoid keywords <span class="co">(roles mentioning these are flagged)</span><br><input id="pfAvoid" style="width:100%" value="${esc((pf.avoid_keywords||[]).join(', '))}" placeholder="commission only, night shift"></label></div>
      </div>
      <h3 style="margin-top:14px">Preferred regions <span class="quiet">(local roles)</span></h3><div>${regions}</div>
      <div class="actions"><button type="button" class="go" id="pfPrefsSave">Save preferences</button></div>
    </div>

    <div class="block" style="margin-top:18px"><h3>How odds are calibrated</h3>
      ${calRow('local','Local')}${calRow('remote','Remote')}
      <p class="co">Odds start from these rates and move with how well you match, seniority gap, where the job can be worked from, freshness and pay. Set jobs to <b>Applied → Interviewing / Rejected</b> on the Pipeline and the rates become yours (an application with no reply after 3 weeks counts as a miss).</p>
    </div>

    <div class="block" style="margin-top:18px"><h3>AI read of your resume <span class="quiet">— optional</span></h3>
      ${llm?`<p><b>${esc(llm.headline)}</b> <span class="co">via ${esc(llm.backend)}</span></p><p class="co" style="color:var(--ink)">${esc(llm.summary)}</p>
        ${llm.target_titles.length?`<div>${llm.target_titles.map(t=>`<span class="chip have">${esc(t)}</span>`).join('')}</div>`:''}
        <div class="two"><div><h4>Strengths</h4><ul class="list">${llm.strengths.map(s=>`<li>✓ ${esc(s)}</li>`).join('')}</ul></div><div><h4>Gaps</h4><ul class="list">${llm.gaps.map(s=>`<li>○ ${esc(s)}</li>`).join('')}</ul></div></div>`:''}
      <div class="actions">${provs?`<select id="pfProv">${provs}</select> <button type="button" id="pfEnrich">${llm?'Refresh':'Ask AI'}</button>`:'<span class="co">No AI provider available (Ollama, Claude Code or an API key).</span>'}
        <span class="co">Ollama stays on this machine; Claude / API providers receive your resume text.</span></div>
    </div>

    <div class="block" style="margin-top:18px"><h3>Resume versions</h3>
      <table class="src-table"><tbody>${S.versions.map(v=>`<tr class="${v.active?'':'off'}"><td>${esc(v.filename)}${v.active?' <b>· active</b>':''}<div class="co">${esc(v.source)} · ${esc(v.created_at.slice(0,10))} · ${v.skills} skills · ${v.years} yrs</div></td>
        <td style="text-align:right;white-space:nowrap">${v.active?'':`<button type="button" class="sm" data-activate="${v.id}">Use this</button> `}<button type="button" class="sm" data-delver="${v.id}">Delete</button></td></tr>`).join('')}</tbody></table></div>`;
  wireProfile();
}

async function pfPost(url,body,method='POST'){ return jfetch(url,{method,headers:{'Content-Type':'application/json'},body:JSON.stringify(body||{})}); }
function markStale(){ PROFILE_STALE=true; paintProfile(); }

function wireProfile(){
  const ca=$('#pfCreateAccount'); if(ca) ca.onclick=()=>openAuthDlg('register');
  const drop=$('#pfDrop'), file=$('#pfFile');
  if(file) file.onchange=()=>{ if(file.files[0]) doUpload(file.files[0]); };
  if(drop){
    ['dragenter','dragover'].forEach(ev=>drop.addEventListener(ev,e=>{e.preventDefault(); drop.classList.add('drag');}));
    ['dragleave','drop'].forEach(ev=>drop.addEventListener(ev,e=>{e.preventDefault(); drop.classList.remove('drag');}));
    drop.addEventListener('drop',e=>{ const f=e.dataTransfer.files[0]; if(f) doUpload(f); });
  }
  const tg=$('#pfPasteToggle'); if(tg) tg.onclick=()=>{ const p=$('#pfPaste'); p.hidden=!p.hidden; };
  const pg=$('#pfPasteGo'); if(pg) pg.onclick=async()=>{ const t=$('#pfPasteText').value.trim(); if(!t) return; await doUpload(null,t); };
  ['#pfRescore','#pfRescore2'].forEach(s=>{ const b=$(s); if(b) b.onclick=()=>startRescore(); });
  const ri=$('#pfReindex'); if(ri) ri.onclick=async()=>{ pmsg('Indexing…'); try{ const r=await pfPost('/api/profile/reindex/'); PROFILE=r; paintProfile(); pmsg(r.semantic?'Semantic index ready':(r.hint||'')); PROFILE_STALE=true; paintProfile(); }catch(e){ pmsg(e.message,true); } };
  document.querySelectorAll('[data-rmskill]').forEach(b=>b.onclick=async()=>{ try{ PROFILE=await pfPost('/api/profile/overrides/',{remove_skills:[b.dataset.rmskill]}); markStale(); }catch(e){ pmsg(e.message,true); } });
  document.querySelectorAll('[data-restore]').forEach(b=>b.onclick=async()=>{ try{ PROFILE=await pfPost('/api/profile/overrides/',{restore_skills:[b.dataset.restore]}); markStale(); }catch(e){ pmsg(e.message,true); } });
  const add=$('#pfSkillAdd'); if(add) add.onclick=async()=>{ const n=$('#pfSkillName').value.trim(); if(!n) return; try{ PROFILE=await pfPost('/api/profile/overrides/',{add_skills:[{name:n,years:+$('#pfSkillYears').value||0}]}); markStale(); }catch(e){ pmsg(e.message,true); } };
  const ys=$('#pfYearsSave'); if(ys) ys.onclick=async()=>{ try{ PROFILE=await pfPost('/api/profile/overrides/',{years_experience:+$('#pfYears').value}); markStale(); }catch(e){ pmsg(e.message,true); } };
  document.querySelectorAll('.modecard input').forEach(r=>r.onchange=()=>document.querySelectorAll('.modecard').forEach(c=>c.classList.toggle('on',c.querySelector('input').checked)));
  const ps=$('#pfPrefsSave'); if(ps) ps.onclick=async()=>{
    const list=v=>v.split(',').map(s=>s.trim()).filter(Boolean);
    const body={work_mode:(document.querySelector('input[name=pfMode]:checked')||{}).value||'both',
      min_salary_monthly_ttd:+$('#pfMinTTD').value||0, min_salary_monthly_usd:+$('#pfMinUSD').value||0,
      willing_to_relocate:$('#pfReloc').checked, open_to_contract:$('#pfContract').checked,
      target_titles:list($('#pfTitles').value), avoid_keywords:list($('#pfAvoid').value),
      preferred_regions:[...document.querySelectorAll('[data-region]:checked')].map(c=>c.dataset.region)};
    try{ const r=await pfPost('/api/profile/prefs/',body,'PUT'); PROFILE.prefs=r.prefs; markStale(); pmsg('Preferences saved'); }catch(e){ pmsg(e.message,true); }
  };
  const en=$('#pfEnrich'); if(en) en.onclick=async()=>{ en.disabled=true; pmsg('Asking '+$('#pfProv').value+'…'); try{ PROFILE=await pfPost('/api/profile/enrich/',{provider:$('#pfProv').value}); PROFILE_STALE=true; paintProfile(); }catch(e){ pmsg(e.message,true); en.disabled=false; } };
  document.querySelectorAll('[data-activate]').forEach(b=>b.onclick=async()=>{ PROFILE=await pfPost(`/api/profile/versions/${b.dataset.activate}/activate/`); markStale(); });
  document.querySelectorAll('[data-delver]').forEach(b=>b.onclick=async()=>{ if(!confirm('Delete this resume version?')) return; PROFILE=await pfPost(`/api/profile/versions/${b.dataset.delver}/`,{}, 'DELETE'); markStale(); });
}

async function doUpload(file,text){
  pmsg('Reading your resume…');
  try{
    let d;
    if(file){ const fd=new FormData(); fd.append('file',file); d=await jfetch('/api/profile/resume/',{method:'POST',body:fd}); }
    else d=await pfPost('/api/profile/resume/',{text,filename:'pasted-resume.txt'});
    PROFILE=d; PROFILE_STALE=false; paintProfile();
    const i=d.import; pmsg(`Found ${i.skills} skills, ${i.roles} roles, ${i.years_experience} years.`);
    await startRescore();
  }catch(e){ pmsg(e.message,true); }
}

async function startRescore(){
  const b1=$('#pfRescore'), b2=$('#pfRescore2'); [b1,b2].forEach(b=>{ if(b){ b.disabled=true; b.textContent='Re-scoring…'; } });
  pmsg('Re-scoring every job against your resume…');
  try{
    await pfPost('/api/rescore/',{});
    clearInterval(RESCORE_TIMER);
    await new Promise((resolve,reject)=>{ RESCORE_TIMER=setInterval(async()=>{ try{ const s=await jfetch('/api/rescore/'); if(!s.running){ clearInterval(RESCORE_TIMER); s.error?reject(new Error(s.error)):resolve(s); } }catch(e){ clearInterval(RESCORE_TIMER); reject(e); } },1200); });
    PROFILE_STALE=false; await loadState(); paintProfile(); pmsg('All jobs re-scored.');
  }catch(e){ pmsg(e.message,true); [b1,b2].forEach(b=>{ if(b){ b.disabled=false; b.textContent='Re-score all jobs'; } }); }
}

Object.assign(PAGE_HOOKS,{ init:()=>{ loadProfile(); paintReview(); }, refresh:()=>{} });
