// ai.js — the AI features in the UI: posting summary + red flags, bullet rewriter, interview practice feedback, outreach drafts,
// similar jobs, recommendations, resume review, plain-English search and skill roadmaps. Every feature works without a model;
// the "Polish with AI" switch adds one — and says exactly where the text goes before it is sent.
let AI_STATUS=null, VOICE_STATUS=null;
async function aiStatus(){ if(!AI_STATUS){ try{ AI_STATUS=await jfetch('/api/ai/status/'); }catch(e){ AI_STATUS={providers:{},any:false,privacy:{}}; } } return AI_STATUS; }
async function voiceStatus(){ if(!VOICE_STATUS){ try{ VOICE_STATUS=await jfetch('/api/ai/voice/status/'); }catch(e){ VOICE_STATUS={available:false,detail:'',voices:[]}; } } return VOICE_STATUS; }

// ---- speak (Kokoro TTS) and listen (the browser's own speech recognition — no server round trip) -------------------
async function speak(text, btn){
  if(!text) return;
  const orig=btn?btn.innerHTML:''; if(btn){ btn.disabled=true; btn.textContent='…'; }
  try{
    const r=await fetch('/api/ai/voice/speak/?text='+encodeURIComponent(text));
    if(!r.ok){ const d=await r.json().catch(()=>({})); throw new Error(d.error||`HTTP ${r.status}`); }
    const audio=new Audio(URL.createObjectURL(await r.blob()));
    audio.onended=()=>URL.revokeObjectURL(audio.src);
    await audio.play();
  }catch(e){ toast(e.message||'Could not play audio','bad'); }
  if(btn){ btn.disabled=false; btn.innerHTML=orig; }
}
const sttSupported=()=>!!(window.SpeechRecognition||window.webkitSpeechRecognition);
function listen(onText, onEnd){
  const SR=window.SpeechRecognition||window.webkitSpeechRecognition, rec=new SR();
  rec.lang='en-US'; rec.interimResults=true; rec.continuous=true;
  let finalText='';
  rec.onresult=e=>{ let interim=''; for(let i=e.resultIndex;i<e.results.length;i++){ const t=e.results[i][0].transcript; if(e.results[i].isFinal) finalText+=t+' '; else interim+=t; } onText(finalText+interim); };
  rec.onerror=e=>{ if(e.error!=='no-speech') toast('Voice input: '+e.error,'bad'); };
  rec.onend=onEnd;
  rec.start();
  return rec;
}
const aiPost=(url,body)=>jfetch(url,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body||{})});
function aiSwitch(st){
  if(!st.any) return '<p class="co">No AI model connected, so the built-in rules are doing the work (they are decent). Install <a href="https://ollama.com" target="_blank" rel="noopener">Ollama</a> to add a private local model.</p>';
  const names=Object.entries(st.providers).filter(([,v])=>v).map(([k])=>k), first=names[0], where=st.privacy[first]||'';
  return `<label class="aiopt"><input type="checkbox" id="aiOn"> Polish with AI <span class="co">(${esc(first)}: ${esc(where)})</span></label>`;
}
const aiOn=()=>{ const el=$('#aiOn'); return !!(el&&el.checked); };
const providerTag=p=>p&&p!=='rules'&&p!=='template'?`<span class="flag g">✦ ${esc(p)}</span>`:'<span class="flag">rules</span>';
const sevCls={3:'b',2:'w',1:''};

async function renderAiTab(j){
  const body=$('#jobBody'), id=encodeURIComponent(j.job_id), st=await aiStatus();
  const fail=e=>{ body.innerHTML=`<div class="banner w">${esc(e.message)}</div>`; };
  if(CURRENT_TAB==='summary'){
    body.innerHTML='<span class="co">Reading the posting…</span>';
    const paint=d=>{
      body.innerHTML=`<div class="banner"><b>${esc(d.tldr)}</b> ${providerTag(d.provider)}</div>
        ${d.red_flags.length?`<h4>Red flags</h4><ul class="list">${d.red_flags.map(f=>`<li><span class="flag ${sevCls[f.severity]||''}">${esc(f.flag)}</span> <span class="co">${esc(f.why)}</span></li>`).join('')}</ul>`:'<div class="banner g"><b>No red flags found</b></div>'}
        ${d.green_flags.length?`<h4>Good signs</h4><div>${d.green_flags.map(g=>`<span class="flag g">${esc(g)}</span>`).join('')}</div>`:''}
        <div class="two"><div><h4>Must have</h4>${d.must_have.map(s=>`<span class="chip neutral">${esc(s)}</span>`).join('')||'<span class="co">Nothing specific</span>'}</div>
        <div><h4>Nice to have</h4>${d.nice_to_have.map(s=>`<span class="chip neutral">${esc(s)}</span>`).join('')||'<span class="co">—</span>'}</div></div>
        ${d.responsibilities.length?`<h4>What you'd do</h4><ul class="list">${d.responsibilities.map(r=>`<li>▸ ${esc(r)}</li>`).join('')}</ul>`:''}
        <h4>Ask them</h4><ul class="list">${d.questions_to_ask.map(q=>`<li>? ${esc(q)}</li>`).join('')}</ul>
        <div id="simBox"></div><div class="aibar">${aiSwitch(st)}${st.any?'<button type="button" class="sm" id="aiRun">Summarise with AI</button>':''}</div>`;
      const run=$('#aiRun'); if(run) run.onclick=async()=>{ run.disabled=true; run.textContent='Working…'; try{ paint(await aiPost(`/api/jobs/${id}/summary/`,{ai:aiOn()})); }catch(e){ fail(e); } };
      loadSimilar(j);
    };
    try{ paint(await jfetch(`/api/jobs/${id}/summary/`)); }catch(e){ fail(e); }
  } else if(CURRENT_TAB==='rewrite'){
    const paint=d=>{
      body.innerHTML=`<p class="co">Your strongest resume bullets for this posting, re-worded. Rewrites never add tools, numbers or claims that your original bullet did not contain. ${providerTag(d.provider)}</p>
        ${d.bullets.map(b=>`<div class="rw"><div class="co">${esc(b.where)} · answers “${esc(b.requirement)}”</div>
          <div class="rw-o"><span class="co">Original</span><br>${esc(b.original)}</div>
          <div class="rw-n"><span class="co">Suggested ${providerTag(b.method)}</span><br><b>${esc(b.rewrite)}</b> <button type="button" class="text" data-copy="${esc(b.rewrite)}">copy</button></div>
          ${b.tips.map(t=>`<div class="co">💡 ${esc(t)}</div>`).join('')}</div>`).join('')||'<p class="co">No bullets to work with yet.</p>'}
        <div class="aibar">${aiSwitch(st)}${st.any?'<button type="button" class="sm" id="aiRun">Rewrite with AI</button>':''}</div>`;
      wireCopy(); const run=$('#aiRun'); if(run) run.onclick=async()=>{ run.disabled=true; run.textContent='Working…'; try{ paint(await aiPost(`/api/jobs/${id}/rewrite/`,{ai:aiOn()})); }catch(e){ fail(e); } };
    };
    body.innerHTML='<span class="co">Finding your best bullets…</span>';
    try{ paint(await aiPost(`/api/jobs/${id}/rewrite/`,{})); }catch(e){ fail(e); }
  } else if(CURRENT_TAB==='practice'){
    let qs=[]; try{ qs=(await jfetch(`/api/jobs/${id}/interview/`)).questions||[]; }catch(e){ /* free text still works */ }
    const vst=await voiceStatus();
    body.innerHTML=`<p class="co">Pick a likely question, answer it — typed or spoken — and get scored on structure (situation, task, action, result), specifics and numbers. Nothing leaves this machine unless you switch AI on${vst.available?' (speech synthesis is local too — Kokoro, no cloud)':''}.</p>
      <div class="pxrow"><select id="pxQ" style="flex:1">${qs.map(q=>`<option>${esc(q.q)}</option>`).join('')||'<option>Tell me about a project you are proud of.</option>'}</select>
      <button type="button" class="sm" id="pxPlayQ" ${vst.available?'':'disabled title="Install Kokoro to hear questions read aloud: pip install kokoro soundfile numpy"'}>🔊 Play question</button></div>
      <textarea id="pxA" rows="7" placeholder="Write your answer here (about 90–200 words)…, or use Speak my answer below" style="width:100%;margin-top:8px"></textarea>
      <div class="aibar">
        <button type="button" class="sm" id="pxMic" ${sttSupported()?'':'disabled title="Your browser does not support speech input — try Chrome or Edge"'}>🎙️ Speak my answer</button>
        ${aiSwitch(st)}<button type="button" class="go sm" id="pxGo">Score my answer</button>
      </div><div id="pxOut"></div>`;
    $('#pxPlayQ').onclick=e=>speak($('#pxQ').value, e.currentTarget);
    let rec=null, before='';
    const mic=$('#pxMic');
    mic.onclick=()=>{
      if(rec){ rec.stop(); return; }
      before=$('#pxA').value.trim(); mic.textContent='⏹ Stop (listening…)'; mic.classList.add('on');
      rec=listen(text=>{ $('#pxA').value=(before?before+' ':'')+text; }, ()=>{ rec=null; mic.textContent='🎙️ Speak my answer'; mic.classList.remove('on'); });
    };
    $('#pxGo').onclick=async()=>{
      const out=$('#pxOut'); out.innerHTML='<span class="co">Scoring…</span>';
      try{
        const d=await aiPost(`/api/jobs/${id}/interview/feedback/`,{question:$('#pxQ').value,answer:$('#pxA').value,ai:aiOn()});
        const star=Object.entries(d.star).map(([k,v])=>`<span class="flag ${v?'g':'b'}">${v?'✓':'○'} ${esc(k)}</span>`).join('');
        out.innerHTML=`<div class="kpi"><div class="box"><b>${d.score}</b><span>Score</span></div><div class="box"><b>${d.words}</b><span>Words</span></div><div class="box"><b>${d.numbers?'yes':'no'}</b><span>Numbers</span></div><div class="box"><b>${esc(d.verdict)}</b><span>Verdict</span></div></div>
          <div style="margin:8px 0">${star}</div><ul class="list">${d.tips.map(t=>`<li>💡 ${esc(t)}</li>`).join('')||'<li class="co">Nothing to fix. Nice.</li>'}</ul>
          ${d.coach?`<div class="banner"><b>Coach</b> ${providerTag(d.provider)}<br>${esc(d.coach).replace(/\n/g,'<br>')}</div>`:''}
          <div class="actions" style="margin-top:8px"><button type="button" class="sm" id="pxPlayResult" ${vst.available?'':'disabled title="Install Kokoro to hear this read aloud"'}>🔊 Hear my results</button></div>`;
        const pr=$('#pxPlayResult'); if(pr) pr.onclick=e=>speak(d.speech, e.currentTarget);
      }catch(e){ out.innerHTML=`<div class="banner w">${esc(e.message)}</div>`; }
    };
  } else if(CURRENT_TAB==='outreach'){
    const kinds=[['follow_up','Follow-up after applying'],['thank_you','Thank-you after an interview'],['recruiter_intro','Message a recruiter'],['referral','Ask for a referral']];
    body.innerHTML=`<div class="chips" id="orKinds">${kinds.map(([k,l],i)=>`<button type="button" class="chipbtn ${i?'':'on'}" data-k="${k}">${l}</button>`).join('')}</div>
      <div id="orOut"></div><div class="aibar">${aiSwitch(st)}</div>`;
    const draft=async k=>{
      $('#orOut').innerHTML='<span class="co">Drafting…</span>';
      try{
        const d=await aiPost(`/api/jobs/${id}/outreach/`,{kind:k,ai:aiOn()});
        $('#orOut').innerHTML=`<div class="co">Subject</div><input id="orSub" value="${esc(d.subject)}" style="width:100%"><textarea id="orBody" rows="10" style="width:100%;margin-top:6px">${esc(d.body)}</textarea>
          <div class="actions"><button type="button" class="go sm" id="orCopy">Copy</button> ${providerTag(d.provider)} <span class="co">${esc(d.provider_note||'Uses your best matching bullet. Edit it, this is a draft.')}</span></div>`;
        $('#orCopy').onclick=async()=>{ await navigator.clipboard.writeText($('#orSub').value+'\n\n'+$('#orBody').value); toast('Copied'); };
      }catch(e){ $('#orOut').innerHTML=`<div class="banner w">${esc(e.message)}</div>`; }
    };
    document.querySelectorAll('#orKinds .chipbtn').forEach(b=>b.onclick=()=>{ document.querySelectorAll('#orKinds .chipbtn').forEach(x=>x.classList.toggle('on',x===b)); draft(b.dataset.k); });
    const on=$('#aiOn'); if(on) on.onchange=()=>draft(document.querySelector('#orKinds .on').dataset.k);
    draft('follow_up');
  }
}
function wireCopy(){ document.querySelectorAll('[data-copy]').forEach(b=>b.onclick=async()=>{ await navigator.clipboard.writeText(b.dataset.copy); toast('Copied'); }); }
async function loadSimilar(j){
  const box=$('#simBox'); if(!box) return;
  try{
    const d=await jfetch(`/api/jobs/${encodeURIComponent(j.job_id)}/similar/`);
    if(!d.similar.length) return;
    box.innerHTML=`<h4>Similar listings</h4><ul class="list">${d.similar.map(s=>`<li><a href="#" data-sim="${esc(s.job_id)}">${esc(s.title)}</a> <span class="co">${esc(s.company)}${s.shared.length?' · both want '+esc(s.shared.slice(0,3).join(', ')):''}${s.fit!=null?' · fit '+s.fit:''}</span></li>`).join('')}</ul>`;
    box.querySelectorAll('[data-sim]').forEach(a=>a.onclick=e=>{ e.preventDefault(); openJob(a.dataset.sim); });
  }catch(e){ /* similar is a bonus */ }
}

// ---- recommendations (Conditions page) ------------------------------------------------------------------------------------
async function paintRecs(){
  const box=$('#recsBox'); if(!box) return;
  try{
    const d=await jfetch('/api/recommendations/'); if(!d.recommendations.length){ box.closest('section').hidden=true; return; }
    $('#recsHint').textContent=d.basis==='similar'?`Untouched listings closest to the ${d.liked} you starred or applied to.`:'Star or apply to a few listings and this learns what you like. For now: your best untouched fits.';
    box.innerHTML=d.recommendations.map(r=>`<li><a href="#" data-rec="${esc(r.job_id)}">${esc(r.title)}</a> <span class="co">${esc(r.company)}${r.because?' · like “'+esc(r.because)+'”':''}${r.fit!=null?' · fit '+r.fit:''}</span></li>`).join('');
    box.querySelectorAll('[data-rec]').forEach(a=>a.onclick=e=>{ e.preventDefault(); openJob(a.dataset.rec); });
  }catch(e){ box.closest('section').hidden=true; }
}

// ---- resume review (Profile page) -----------------------------------------------------------------------------------------
async function paintReview(){
  const box=$('#reviewBox'); if(!box) return;
  try{
    const d=await jfetch('/api/profile/review/');
    box.innerHTML=`<div class="kpi"><div class="box"><b>${d.score}</b><span>Resume score</span></div><div class="box"><b>${d.stats.bullets}</b><span>Bullets</span></div><div class="box"><b>${d.stats.with_numbers}</b><span>With numbers</span></div><div class="box"><b>${esc(d.verdict)}</b><span>Verdict</span></div></div>
      ${d.wins.map(w=>`<div class="rv win">✓ ${esc(w)}</div>`).join('')}
      ${d.issues.map(i=>`<div class="rv"><span class="flag ${sevCls[i.severity]||''}">${esc(i.title)}</span> <span class="co">${esc(i.detail)}</span>${i.examples.map(x=>`<blockquote class="evid">${esc(x)}</blockquote>`).join('')}</div>`).join('')||'<div class="banner g"><b>Nothing to fix.</b></div>'}`;
  }catch(e){ box.innerHTML=`<p class="co">${esc(e.message)}</p>`; }
}

// ---- plain-English search (palette) and skill roadmap ---------------------------------------------------------------------
async function askAndGo(q){
  try{ const d=await aiPost('/api/ai/ask/',{q}); toast(d.explain); goto('jobs',d.params); }catch(e){ toast(e.message,'bad'); }
}
async function openRoadmap(skill,jobs,sole){
  let dlg=$('#roadDlg'); if(!dlg) return;
  $('#roadTitle').textContent=`Learn ${skill}`; $('#roadBody').innerHTML='<span class="co">Planning…</span>'; dlg.showModal();
  const st=await aiStatus();
  const paint=d=>{
    $('#roadBody').innerHTML=`<p class="co">${esc(d.why)} About ${d.weeks} weeks part-time. ${providerTag(d.provider)}</p>
      <ol class="list">${d.steps.map(s=>`<li>${esc(s)}</li>`).join('')}</ol>
      <div class="banner"><b>Portfolio project:</b> ${esc(d.project)}</div>
      <p class="co">Once done, add: <i>${esc(d.resume_line)}</i></p>
      ${d.plan_text?`<h4>AI plan</h4><div class="co" style="white-space:pre-wrap">${esc(d.plan_text)}</div>`:''}
      <div class="aibar">${aiSwitch(st)}${st.any?'<button type="button" class="sm" id="aiRun">Plan with AI</button>':''}</div>`;
    const run=$('#aiRun'); if(run) run.onclick=async()=>{ run.disabled=true; run.textContent='Working…'; try{ paint(await aiPost('/api/ai/roadmap/',{skill,jobs,sole_gap:sole,ai:aiOn()})); }catch(e){ toast(e.message,'bad'); } };
  };
  try{ paint(await aiPost('/api/ai/roadmap/',{skill,jobs,sole_gap:sole})); }catch(e){ $('#roadBody').innerHTML=`<div class="banner w">${esc(e.message)}</div>`; }
}
