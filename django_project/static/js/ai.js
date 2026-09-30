// ai.js — the AI features in the UI: posting summary + red flags, bullet rewriter, interview practice feedback, outreach drafts,
// similar jobs, recommendations, resume review, plain-English search and skill roadmaps. Every feature works without a model;
// the "Polish with AI" switch adds one — and says exactly where the text goes before it is sent.
let AI_STATUS=null, VOICE_STATUS=null;
async function aiStatus(){ if(!AI_STATUS){ try{ AI_STATUS=await jfetch('/api/ai/status/'); }catch(e){ AI_STATUS={providers:{},any:false,privacy:{}}; } } return AI_STATUS; }
async function voiceStatus(){ if(!VOICE_STATUS){ try{ VOICE_STATUS=await jfetch('/api/ai/voice/status/'); }catch(e){ VOICE_STATUS={available:false,detail:'',voices:[]}; } } return VOICE_STATUS; }

// the chosen Kokoro voice (Interview page picker); remembered per browser, harmless if storage is blocked
const voicePref=()=>{ try{ return localStorage.getItem('jh_voice')||''; }catch(e){ return ''; } };
const setVoicePref=v=>{ try{ localStorage.setItem('jh_voice',v); }catch(e){} };
const speakUrl=text=>'/api/ai/voice/speak/?text='+encodeURIComponent(text)+(voicePref()?'&voice='+encodeURIComponent(voicePref()):'');
// ---- speak (Kokoro TTS) and listen (the browser's own speech recognition — no server round trip) -------------------
async function speak(text, btn){
  if(!text) return;
  const orig=btn?btn.innerHTML:''; if(btn){ btn.disabled=true; btn.textContent='…'; }
  try{
    const r=await fetch(speakUrl(text));
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
// Delivery metrics from the raw mic signal. Only summary numbers ever leave the browser — no audio is uploaded or stored.
// Analysis runs on the audio thread (a ScriptProcessor callback per ~43ms buffer), not on a timer: timers get throttled
// (background tabs, a busy page) and every pause/pitch number would silently drift. Time is measured in audio samples.
const SILENCE_RMS=0.015, LONG_PAUSE_SEC=0.8;
function framePitch(buf, rate){
  // normalised autocorrelation over 70–400 Hz; take the FIRST lag within 90% of the best one, which avoids reporting
  // half the real pitch (a peak at twice the period is nearly as strong as the true one)
  const lo=Math.floor(rate/400), hi=Math.min(Math.floor(rate/70), buf.length>>1), r=[];
  let e0=0; for(let i=0;i<buf.length;i++) e0+=buf[i]*buf[i];
  if(!e0) return null;
  let best=0;
  for(let lag=lo;lag<hi;lag++){ let c=0; const n=buf.length-lag; for(let i=0;i<n;i++) c+=buf[i]*buf[i+lag]; r[lag]=c/n/(e0/buf.length); if(r[lag]>best) best=r[lag]; }
  if(best<0.5) return null;   // unvoiced / noise
  for(let lag=lo+1;lag<hi-1;lag++) if(r[lag]>=0.9*best && r[lag]>=r[lag-1] && r[lag]>=r[lag+1]) return rate/lag;
  return null;
}
// The composure cues, from a timeline of {e: RMS volume, f: pitch Hz or null} per audio buffer (dt seconds each).
// Kept separate from the mic plumbing so it can be checked against synthetic signals. Every cue is a coarse, honest
// estimate — see composure_feedback() in jobhunt/src/ai_features.py for how they're read.
function composureCues(frames, dt){
  const med=a=>{ if(!a.length) return null; const b=[...a].sort((x,y)=>x-y), m=b.length>>1; return b.length%2?b[m]:(b[m-1]+b[m])/2; };
  const pct=(a,p)=>{ const b=[...a].sort((x,y)=>x-y); return b[Math.min(b.length-1,Math.floor(p*b.length))]; };
  const st=r=>12*Math.log2(r), out={};
  const voiced=frames.map(fr=>fr.e>=SILENCE_RMS);
  for(let i=0;i+2<frames.length;i++) if(voiced[i]&&voiced[i+1]&&voiced[i+2]){ out.start_latency_sec=+(i*dt).toFixed(1); break; }
  // phrases: voiced stretches split by >=0.25s of silence, at least 0.6s long
  const phrases=[]; let cur=null, gap=0;
  frames.forEach((fr,i)=>{
    if(voiced[i]){ if(!cur) cur=[]; cur.push(fr); gap=0; }
    else if(cur){ gap+=dt; if(gap>=0.25){ if(cur.length*dt>=0.6) phrases.push(cur); cur=null; } }
  });
  if(cur&&cur.length*dt>=0.6) phrases.push(cur);
  let up=0, trail=0, judged=0;
  const jit=[];
  for(const ph of phrases){
    // uptalk: the last ~15% of the phrase against the stretch just before it (40–75%), so the rise isn't diluted
    const end=ph.slice(Math.floor(ph.length*0.85)).map(x=>x.f).filter(Boolean), body=ph.slice(Math.floor(ph.length*0.4),Math.floor(ph.length*0.75)).map(x=>x.f).filter(Boolean);
    const tail=ph.slice(Math.floor(ph.length*0.75)), em=ph.reduce((a,x)=>a+x.e,0)/ph.length, te=tail.reduce((a,x)=>a+x.e,0)/tail.length;
    if(end.length>=2&&body.length>=3){ judged++; if(med(end)>med(body)*1.1) up++; }
    if(te<em*0.55) trail++;
    for(let i=1;i<ph.length;i++){
      const a=ph[i-1], b=ph[i];
      if(a.f&&b.f){ const r=b.f/a.f; if(r<1.6&&r>0.625) jit.push(Math.abs(b.f-a.f)/((a.f+b.f)/2)); }   // skip octave-tracking errors
    }
  }
  out.phrases=phrases.length;
  if(judged) out.uptalk_ratio=+(up/judged).toFixed(2);
  if(phrases.length) out.trail_off_ratio=+(trail/phrases.length).toFixed(2);
  if(jit.length>=10) out.jitter=+med(jit).toFixed(3);
  const all=frames.map(x=>x.f).filter(Boolean);
  if(all.length>=12){
    out.pitch_range_st=+st(pct(all,0.9)/pct(all,0.1)).toFixed(1);
    const third=Math.floor(all.length/3);
    out.pitch_drift_st=+st(med(all.slice(0,third))/med(all.slice(-third))).toFixed(1);
  }
  return out;
}
// opts.record: also keep the raw audio IN THIS PAGE ONLY (MediaRecorder -> a blob URL) so you can hear yourself back.
// It is never uploaded or saved: the returned stop function exposes it as stop.audio (a Promise of a blob: URL).
async function startMetrics(onLevel, opts){
  const stream=await navigator.mediaDevices.getUserMedia({audio:true});
  const ctx=new (window.AudioContext||window.webkitAudioContext)(), src=ctx.createMediaStreamSource(stream);
  const proc=ctx.createScriptProcessor(2048,1,1), mute=ctx.createGain(); mute.gain.value=0;
  if(ctx.state==='suspended') await ctx.resume().catch(()=>{});
  src.connect(proc); proc.connect(mute); mute.connect(ctx.destination);   // must reach the destination to run; muted, so no echo
  const frames=[]; let dt=2048/ctx.sampleRate;
  let recorder=null, chunks=[];
  if(opts&&opts.record&&window.MediaRecorder){ try{ recorder=new MediaRecorder(stream); recorder.ondataavailable=e=>{ if(e.data.size) chunks.push(e.data); }; recorder.start(); }catch(e){ recorder=null; } }
  proc.onaudioprocess=ev=>{
    const buf=ev.inputBuffer.getChannelData(0); dt=buf.length/ctx.sampleRate;
    let e=0; for(let i=0;i<buf.length;i++) e+=buf[i]*buf[i]; e=Math.sqrt(e/buf.length);
    if(onLevel) onLevel(e);
    frames.push({e, f:e>=SILENCE_RMS?framePitch(buf,ctx.sampleRate):null});
  };
  const stop=words=>{
    proc.onaudioprocess=null; try{ src.disconnect(); proc.disconnect(); }catch(e){}
    stop.audio=recorder&&recorder.state!=='inactive'
      ? new Promise(res=>{ recorder.onstop=()=>res(chunks.length?URL.createObjectURL(new Blob(chunks,{type:recorder.mimeType||'audio/webm'})):null); recorder.stop(); })
      : Promise.resolve(null);
    stop.audio.then(()=>{ stream.getTracks().forEach(t=>t.stop()); ctx.close(); });
    const total=frames.length*dt, vol=frames.filter(x=>x.e>=SILENCE_RMS).map(x=>x.e), pitch=frames.map(x=>x.f).filter(Boolean);
    if(total<3||!vol.length) return null;
    let silent=0, run=0, longPauses=0;
    for(const x of frames){ if(x.e<SILENCE_RMS){ silent+=dt; const was=run; run+=dt; if(was<LONG_PAUSE_SEC&&run>=LONG_PAUSE_SEC) longPauses++; } else run=0; }
    const mean=a=>a.reduce((x,y)=>x+y,0)/a.length, sd=a=>{ const m=mean(a); return Math.sqrt(mean(a.map(v=>(v-m)**2))); };
    const v={duration_sec:Math.round(total), pause_ratio:+(silent/total).toFixed(2), long_pauses:longPauses, volume_mean:+mean(vol).toFixed(3), volume_stdev:+sd(vol).toFixed(3)};
    if(words>=5) v.pace_wpm=Math.round(words/(total/60));
    if(pitch.length>=8){ v.pitch_mean_hz=Math.round(mean(pitch)); v.pitch_stdev_hz=Math.round(sd(pitch)); }
    return Object.assign(v, composureCues(frames, dt));
  };
  return stop;
}
const aiPost=(url,body)=>jfetch(url,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body||{})});
function aiSwitch(st){
  if(!st.any) return '<p class="co">No AI model connected, so the built-in rules are doing the work (they are decent). Install <a href="https://ollama.com" target="_blank" rel="noopener">Ollama</a> to add a private local model.</p>';
  const first=st.active||Object.entries(st.providers).filter(([,v])=>v).map(([k])=>k)[0], where=st.privacy[first]||'';
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
    body.innerHTML=`<p class="co">Pick a likely question, answer it — typed or spoken — and get scored on structure (situation, task, action, result), specifics and numbers. For a full spoken mock interview, open the <a href="/interview/?job=${id}">Interview page</a>. Nothing leaves this machine unless you switch AI on${vst.available?' (speech synthesis is local too — Kokoro, no cloud)':''}.</p>
      <div class="pxrow"><select id="pxQ" style="flex:1">${qs.map(q=>`<option>${esc(q.q)}</option>`).join('')||'<option>Tell me about a project you are proud of.</option>'}</select>
      <button type="button" class="sm" id="pxPlayQ" ${vst.available?'':'disabled title="Install Kokoro to hear questions read aloud: pip install kokoro-onnx soundfile, then python -m src.voice --download"'}>🔊 Play question</button></div>
      <textarea id="pxA" rows="7" placeholder="Write your answer here (about 90–200 words)…, or use Speak my answer below" style="width:100%;margin-top:8px"></textarea>
      <div class="aibar">
        <button type="button" class="sm" id="pxMic" ${sttSupported()?'':'disabled title="Your browser does not support speech input — try Chrome or Edge"'}>🎙️ Speak my answer</button>
        ${aiSwitch(st)}<button type="button" class="go sm" id="pxGo">Score my answer</button>
      </div><div id="pxOut"></div><div id="pxSession"></div>`;
    const session=[];
    $('#pxPlayQ').onclick=e=>speak($('#pxQ').value, e.currentTarget);
    let rec=null, before='', stopMetrics=null, voice=null;
    const mic=$('#pxMic');
    mic.onclick=async()=>{
      if(rec){ rec.stop(); return; }
      before=$('#pxA').value.trim(); voice=null; mic.textContent='⏹ Stop (listening…)'; mic.classList.add('on');
      try{ stopMetrics=await startMetrics(); }catch(e){ stopMetrics=null; }   // no mic permission for metrics: transcript still works
      rec=listen(text=>{ $('#pxA').value=(before?before+' ':'')+text; }, ()=>{
        rec=null; mic.textContent='🎙️ Speak my answer'; mic.classList.remove('on');
        if(stopMetrics){ const spoken=$('#pxA').value.trim().slice(before.length).trim(); voice=stopMetrics(spoken?spoken.split(/\s+/).length:0); stopMetrics=null; }
      });
    };
    $('#pxGo').onclick=async()=>{
      const out=$('#pxOut'); out.innerHTML='<span class="co">Scoring…</span>';
      try{
        const d=await aiPost(`/api/jobs/${id}/interview/feedback/`,{question:$('#pxQ').value,answer:$('#pxA').value,ai:aiOn(),voice});
        session.push({...d,question:$('#pxQ').value}); voice=null;
        const star=Object.entries(d.star).map(([k,v])=>`<span class="flag ${v?'g':'b'}">${v?'✓':'○'} ${esc(k)}</span>`).join('');
        out.innerHTML=`<div class="kpi"><div class="box"><b>${d.overall_score}</b><span>${d.delivery?'Overall':'Score'}</span></div><div class="box"><b>${d.words}</b><span>Words</span></div><div class="box"><b>${d.numbers?'yes':'no'}</b><span>Numbers</span></div><div class="box"><b>${esc(d.verdict)}</b><span>Verdict</span></div></div>
          <div style="margin:8px 0">${star}</div><ul class="list">${d.tips.map(t=>`<li>💡 ${esc(t)}</li>`).join('')||'<li class="co">Nothing to fix. Nice.</li>'}</ul>
          ${d.delivery?`<h4>Delivery · ${d.delivery.score}/100</h4><ul class="list">${d.delivery.notes.map(t=>`<li>✓ ${esc(t)}</li>`).join('')}${d.delivery.tips.map(t=>`<li>🎙️ ${esc(t)}</li>`).join('')}</ul>`:''}
          ${d.coach?`<div class="banner"><b>Coach</b> ${providerTag(d.provider)}<br>${esc(d.coach).replace(/\n/g,'<br>')}</div>`:''}
          <div class="actions" style="margin-top:8px"><button type="button" class="sm" id="pxPlayResult" ${vst.available?'':'disabled title="Install Kokoro to hear this read aloud"'}>🔊 Hear my results</button></div>`;
        const pr=$('#pxPlayResult'); if(pr) pr.onclick=e=>speak(d.speech, e.currentTarget);
        $('#pxSession').innerHTML=`<div class="actions" style="margin-top:8px"><button type="button" class="sm" id="pxWrap">Finish session (${session.length} answered)</button></div><div id="pxWrapOut"></div>`;
        $('#pxWrap').onclick=async()=>{
          const w=$('#pxWrapOut'); w.innerHTML='<span class="co">Summing up…</span>';
          try{
            const r=await aiPost('/api/ai/interview/summary/',{results:session,ai:aiOn()});
            w.innerHTML=`<div class="banner"><b>${esc(r.verdict)} · ${r.overall_avg}/100 across ${r.n} question${r.n===1?'':'s'}</b> ${providerTag(r.provider)}${r.delivery_avg!=null?`<br><span class="co">Content ${r.content_avg} · Delivery ${r.delivery_avg}</span>`:''}
              <br><span class="co">Best: “${esc(r.best.question)}” (${r.best.score}) · Weakest: “${esc(r.worst.question)}” (${r.worst.score})</span>
              ${r.coach?`<br>${esc(r.coach).replace(/\n/g,'<br>')}`:''}</div>
              ${r.recurring_tips.length?`<h4>Keep working on</h4><ul class="list">${r.recurring_tips.map(t=>`<li>💡 ${esc(t)}</li>`).join('')}</ul>`:''}
              <button type="button" class="sm" id="pxPlayWrap" ${vst.available?'':'disabled'}>🔊 Hear the wrap-up</button>`;
            const pw=$('#pxPlayWrap'); if(pw) pw.onclick=e=>speak(r.speech, e.currentTarget);
          }catch(e){ w.innerHTML=`<div class="banner w">${esc(e.message)}</div>`; }
        };
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
