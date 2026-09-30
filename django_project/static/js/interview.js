// interview.js — the Interview page: a full mock interview, spoken end to end. The interviewer reads each question
// aloud (Kokoro when installed, the browser's own voice otherwise), you answer out loud, and the browser transcribes
// (SpeechRecognition) and measures delivery from the raw mic signal (startMetrics, ai.js). Each answer is scored by
// /api/jobs/<id>/interview/feedback/, a thin answer gets one follow-up probe, and the whole session is summed up (and
// saved to your history) by /api/ai/interview/summary/. No audio ever leaves the page.
const IV={turn:0, job:null, questions:[], i:0, results:[], feedbackEach:false, followUps:true, pending:null,
          rec:null, answering:false, stopMetrics:null, audio:null, t0:0, tick:null,
          kind:'behavioural', offer:null, realistic:false, cam:null, clips:[], replay:{}, nudged:false, nudgeVoice:null,
          interrupt:false, drillIds:null};
const ANSWER_TARGET=120;   // seconds: past two minutes the timer turns into a nudge to wrap up
const INTERRUPT_AT=150;    // realistic mode: the interviewer cuts in here, like a real one would
const SHORT_WORDS=25;      // realistic mode: an answer this short gets "could you say a bit more?"
const KIND_LABEL={behavioural:'Behavioural',screen:'Recruiter screen',technical:'Technical',negotiation:'Salary negotiation',reverse:'Your questions for them'};

// ---- the interviewer's voice: resolves when speech has finished, so the flow can wait on it --------------------------
async function say(text){
  if(!text) return;
  ivSpeaking(true);
  try{
    if((await voiceStatus()).available){
      const r=await fetch(speakUrl(text));
      if(r.ok){
        const a=new Audio(URL.createObjectURL(await r.blob())); IV.audio=a;
        await new Promise(res=>{ a.onended=a.onerror=a.onpause=res; a.play().catch(res); });
        URL.revokeObjectURL(a.src); IV.audio=null; return;
      }
    }
    if(window.speechSynthesis){
      await new Promise(res=>{ const u=new SpeechSynthesisUtterance(text); u.rate=1; u.onend=u.onerror=res; speechSynthesis.cancel(); speechSynthesis.speak(u); });
    }
  }finally{ ivSpeaking(false); }
}
// Kokoro takes ~1.5s per new sentence; the speak endpoint's responses are immutable-cached, so fetching the next
// line early makes it play instantly when its turn comes.
function prefetchSpeech(text){ if(!text||!(VOICE_STATUS&&VOICE_STATUS.available)) return; fetch(speakUrl(text)).catch(()=>{}); }
function hush(){ if(IV.audio) IV.audio.pause(); if(window.speechSynthesis) speechSynthesis.cancel(); }
function ivSpeaking(on){ const s=$('#ivState'); if(s) s.textContent=on?'Interviewer is speaking…':(IV.answering?'Listening…':''); const o=$('#ivOrb'); if(o) o.className='iv-orb'+(on?' talk':IV.answering?' listen':''); }

// ---- listening: recognition restarts itself if the browser ends it mid-answer (Chrome stops after a silence) --------
const fmtTime=s=>`${Math.floor(s/60)}:${String(Math.floor(s%60)).padStart(2,'0')}`;
function startAnswer(){
  if(IV.answering) return;
  const box=$('#ivAnswer'); IV.answering=true; ivControls();
  IV.t0=Date.now(); clearInterval(IV.tick);
  IV.tick=setInterval(()=>{ const t=$('#ivTimer'); if(!t) return; const s=(Date.now()-IV.t0)/1000; t.textContent=fmtTime(s); t.classList.toggle('over',s>ANSWER_TARGET);
    if(IV.realistic && IV.answering && s>INTERRUPT_AT && !IV.interrupt && !IV.pending){ IV.interrupt=true; const d=$('#ivDone'); if(d) d.click(); } },250);
  const lvl=e=>{ const m=$('#ivLevel i'); if(m) m.style.width=Math.min(100,Math.round(e*400))+'%'; };
  startMetrics(lvl,{record:true}).then(stop=>{ if(IV.answering) IV.stopMetrics=stop; else stop(0); }).catch(()=>{ IV.stopMetrics=null; });
  if(IV.cam) IV.cam.resume();
  if(!sttSupported()){ box.focus(); ivSpeaking(false); return; }
  const run=()=>{
    const base=box.value.trim();
    IV.rec=listen(t=>{ box.value=(base?base+' ':'')+t.trim(); }, ()=>{ IV.rec=null; if(IV.answering) run(); });
  };
  run(); ivSpeaking(false);
}
function stopAnswer(){
  IV.answering=false; clearInterval(IV.tick);
  const m=$('#ivLevel i'); if(m) m.style.width='0';
  if(IV.rec){ const r=IV.rec; IV.rec=null; r.onend=r.onerror=null; r.stop(); }
  const box=$('#ivAnswer'), words=box?box.value.trim().split(/\s+/).filter(Boolean).length:0;
  let voice=null;
  if(IV.stopMetrics){ voice=IV.stopMetrics(words); IV.clips.push(IV.stopMetrics.audio); }
  IV.stopMetrics=null;
  if(IV.cam) IV.cam.pause();
  ivSpeaking(false);
  return voice;
}
// an answer plus its follow-up is judged as one exchange. EVERY cue startMetrics() returns has a rule here (a unit test
// checks that), because a key missing from this function silently vanishes before it reaches the server.
const MERGE={
  sum:['duration_sec','long_pauses','phrases'],
  first:['start_latency_sec','pitch_drift_st'],   // how the answer OPENED: the follow-up's opening isn't the same moment
  weighted:['pace_wpm','pitch_mean_hz','pitch_stdev_hz','pause_ratio','volume_mean','volume_stdev','uptalk_ratio','trail_off_ratio','jitter','pitch_range_st'],
};
function mergeVoice(a,b){
  if(!a||!b) return a||b;
  const da=a.duration_sec||0, db=b.duration_sec||0, out={};
  for(const k of MERGE.sum) if(a[k]!=null||b[k]!=null) out[k]=(a[k]||0)+(b[k]||0);
  for(const k of MERGE.first) if(a[k]!=null||b[k]!=null) out[k]=a[k]??b[k];
  for(const k of MERGE.weighted){
    if(a[k]!=null&&b[k]!=null){ const v=(a[k]*da+b[k]*db)/(da+db||1); out[k]=/^p(ace|itch_mean|itch_stdev)/.test(k)?Math.round(v):+v.toFixed(3); }
    else if(a[k]!=null||b[k]!=null) out[k]=a[k]??b[k];
  }
  for(const k of Object.keys({...a,...b})) if(!(k in out)) out[k]=a[k]??b[k];   // unknown future key: keep it rather than lose it
  return out;
}

// ---- camera: on-device face tracking (MediaPipe FaceLandmarker, loaded only when you switch it on) ------------------------
// Only summary numbers leave the page: share of frames with your face in shot, looking at the camera, head movement, smiling.
const MP_VER='0.10.14';
async function startCamera(){
  const stream=await navigator.mediaDevices.getUserMedia({video:{width:640,height:480}});
  const video=document.createElement('video'); video.srcObject=stream; video.muted=true; video.playsInline=true; await video.play();
  const vision=await import(`https://cdn.jsdelivr.net/npm/@mediapipe/tasks-vision@${MP_VER}/vision_bundle.mjs`);
  const files=await vision.FilesetResolver.forVisionTasks(`https://cdn.jsdelivr.net/npm/@mediapipe/tasks-vision@${MP_VER}/wasm`);
  const lm=await vision.FaceLandmarker.createFromOptions(files,{baseOptions:{modelAssetPath:'https://storage.googleapis.com/mediapipe-models/face_landmarker/face_landmarker/float16/1/face_landmarker.task'},
    runningMode:'VIDEO', numFaces:1, outputFaceBlendshapes:true, outputFacialTransformationMatrixes:true});
  let acc=null, on=false, timer=null;
  const reset=()=>{ acc={frames:0, face:0, eye:0, smile:0, yaw:[], pitch:[]}; };
  reset();
  const tick=()=>{
    if(!on||video.readyState<2) return;
    const r=lm.detectForVideo(video, performance.now());
    acc.frames++;
    if(!r.faceLandmarks||!r.faceLandmarks.length) return;
    acc.face++;
    const b=Object.fromEntries(((r.faceBlendshapes||[])[0]||{categories:[]}).categories.map(c=>[c.categoryName,c.score]));
    const m=((r.facialTransformationMatrixes||[])[0]||{}).data;
    const yaw=m?Math.atan2(-m[2],Math.hypot(m[0],m[1]))*180/Math.PI:0, pitch=m?Math.atan2(m[6],m[10])*180/Math.PI:0;
    acc.yaw.push(yaw); acc.pitch.push(pitch);
    const gazeAway=['eyeLookOutLeft','eyeLookOutRight','eyeLookUpLeft','eyeLookDownLeft','eyeLookInLeft'].some(k=>(b[k]||0)>0.55);
    if(Math.abs(yaw)<15 && Math.abs(pitch)<15 && !gazeAway) acc.eye++;
    if(((b.mouthSmileLeft||0)+(b.mouthSmileRight||0))/2>0.35) acc.smile++;
  };
  timer=setInterval(tick,200);
  const sd=a=>{ if(a.length<2) return 0; const mu=a.reduce((x,y)=>x+y,0)/a.length; return Math.sqrt(a.reduce((x,y)=>x+(y-mu)**2,0)/a.length); };
  return {
    stream, resume(){ on=true; }, pause(){ on=false; },
    snapshot(){ if(!acc.frames) return null; return {frames:acc.frames, face_ratio:+(acc.face/acc.frames).toFixed(2), eye_contact_ratio:acc.face?+(acc.eye/acc.face).toFixed(2):0,
      head_motion_deg:+Math.hypot(sd(acc.yaw),sd(acc.pitch)).toFixed(1), smile_ratio:acc.face?+(acc.smile/acc.face).toFixed(2):0}; },
    reset, stop(){ clearInterval(timer); stream.getTracks().forEach(t=>t.stop()); try{ lm.close(); }catch(e){} },
  };
}

// ---- calm-voice baseline: read a short passage once; composure is then judged against YOUR voice --------------------------
async function ivBaselinePanel(){
  const box=$('#ivBase'); if(!box) return;
  let b={}; try{ b=await jfetch('/api/coach/baseline/'); }catch(e){ box.innerHTML=''; return; }
  box.innerHTML=b.baseline
    ?`<span class="co">✓ Calm-voice baseline recorded ${esc(new Date(b.recorded_at).toLocaleDateString())} (${b.baseline.pace_wpm||'—'} wpm, ${b.baseline.pitch_mean_hz||'—'} Hz). Nerves are judged against your own voice.</span> <button type="button" class="text" id="ivBaseRedo">Re-record</button>`
    :`<span class="co"><b>Record your calm-voice baseline</b> (30 seconds, once). Without it, nerves are judged against a generic speaker: a naturally fast or high-pitched voice can look "nervous" when it isn't.</span> <button type="button" class="text" id="ivBaseRedo">Record now</button>`;
  $('#ivBaseRedo').onclick=()=>{
    box.innerHTML=`<div class="iv-basepass"><p class="co">Read this aloud at your normal, relaxed pace. Click Start, read it all, then click Done.</p>
      <blockquote>${esc(b.passage)}</blockquote><div class="actions"><button type="button" class="go sm" id="ivBaseGo">Start</button><span class="co" id="ivBaseState"></span></div></div>`;
    let stop=null;
    $('#ivBaseGo').onclick=async()=>{
      const btn=$('#ivBaseGo');
      if(!stop){ try{ stop=await startMetrics(); }catch(e){ toast('Microphone permission is needed to record a baseline','bad'); return; }
        btn.textContent='Done'; $('#ivBaseState').textContent='Listening… read the passage'; return; }
      const v=stop(b.passage.split(/\s+/).length); stop=null;
      try{ await aiPost('/api/coach/baseline/',{voice:v}); toast('Baseline saved'); ivBaselinePanel(); }
      catch(e){ toast(e.message,'bad'); ivBaselinePanel(); }
    };
  };
}

// ---- setup + history ---------------------------------------------------------------------------------------------------
function sparkline(vals){
  if(vals.length<2) return '';
  const w=160,h=36, lo=Math.max(0,Math.min(...vals)-10), hi=Math.min(100,Math.max(...vals)+10), xs=i=>Math.round(i*(w-4)/(vals.length-1))+2, ys=v=>Math.round(h-2-((v-lo)/(hi-lo||1))*(h-4));
  return `<svg class="iv-spark" viewBox="0 0 ${w} ${h}" width="${w}" height="${h}" aria-label="Overall score, oldest to newest"><polyline fill="none" stroke="currentColor" stroke-width="1.5" points="${vals.map((v,i)=>`${xs(i)},${ys(v)}`).join(' ')}"/>${vals.map((v,i)=>`<circle cx="${xs(i)}" cy="${ys(v)}" r="2" fill="currentColor"/>`).join('')}</svg>`;
}
async function ivHistory(){
  const box=$('#ivHist'); if(!box) return;
  let rows=[]; try{ rows=(await jfetch('/api/ai/interview/sessions/')).sessions||[]; }catch(e){ box.innerHTML=''; return; }
  if(!rows.length){ box.innerHTML='<p class="co">Your finished interviews will be listed here, so you can see yourself improve.</p>'; return; }
  const trend=[...rows].reverse().map(r=>r.overall), first=trend[0], last=trend[trend.length-1];
  box.innerHTML=`<div class="iv-histhead"><div>${sparkline(trend)}</div>
      <div class="co">${rows.length} interview${rows.length>1?'s':''}${trend.length>1?` · ${last>=first?'up':'down'} ${Math.abs(last-first)} since your first`:''}</div></div>
    <table class="src-table iv-hist"><thead><tr><th>When</th><th>Role</th><th>Overall</th><th>Said</th><th>Delivery</th><th>Composure</th><th></th></tr></thead><tbody>
    ${rows.map(r=>`<tr><td>${esc(new Date(r.created_at).toLocaleDateString(undefined,{month:'short',day:'numeric'}))}</td>
      <td>${esc(r.job_title||'—')}<div class="co">${esc(r.company||'')} · ${r.n} answer${r.n===1?'':'s'}</div></td>
      <td><b>${r.overall}</b></td><td>${r.content}</td><td>${r.delivery??'—'}</td><td>${r.composure??'—'}</td>
      <td class="iv-rowact"><button type="button" class="text" data-view="${r.id}">View</button> <button type="button" class="text" data-del="${r.id}" title="Delete this interview">✕</button></td></tr>`).join('')}
    </tbody></table>`;
  box.querySelectorAll('[data-view]').forEach(b=>b.onclick=async()=>{
    try{ const s=await jfetch(`/api/ai/interview/sessions/${b.dataset.view}/`); IV.job=s.job; IV.results=s.results; IV.questions=s.results.map(r=>({q:r.question,why:r.why}));
      renderReport(s.summary, s.results, {saved:s.created_at}); }catch(e){ toast(e.message,'bad'); }
  });
  box.querySelectorAll('[data-del]').forEach(b=>b.onclick=async()=>{
    if(b.dataset.sure!=='1'){ b.dataset.sure='1'; b.textContent='Delete?'; return; }   // two clicks, no browser dialog
    try{ await jfetch(`/api/ai/interview/sessions/${b.dataset.del}/`,{method:'DELETE'}); ivHistory(); }catch(e){ toast(e.message,'bad'); }
  });
}
async function ivSetup(){
  const el=$('#ivBody'), vst=await voiceStatus(), ast=await aiStatus();
  const aiName=ast.active;   // the provider a request will really use (pinned, else first available) — never a guess
  const want=new URLSearchParams(location.search).get('job');
  const jobs=[...JOBS].sort((a,b)=>(b.fit_score||0)-(a.fit_score||0)).slice(0,80);
  if(!jobs.length){ el.innerHTML='<div class="banner w">No roles in the ledger yet. Run a scan, then come back and pick one to interview for.</div><div class="block"><h3>Past interviews</h3><div id="ivHist"></div></div>'; ivHistory(); return; }
  el.innerHTML=`<div class="iv-setup">
      <label>Role<select id="ivJob">${jobs.map(j=>`<option value="${esc(j.job_id)}" ${j.job_id===want?'selected':''}>${esc(j.title)} · ${esc(j.company)} (${j.fit_score??'—'})</option>`).join('')}</select></label>
      <label>Type<select id="ivKind">${Object.entries(KIND_LABEL).map(([k,v])=>`<option value="${k}" ${k===(new URLSearchParams(location.search).get('kind')||'behavioural')?'selected':''}>${v}</option>`).join('')}</select></label>
      <label>Length<select id="ivLen"><option value="3">Short · 3 questions</option><option value="5" selected>Standard · 5 questions</option><option value="99">Full · every question</option></select></label>
      <label class="iv-check"><input type="checkbox" id="ivFollow" checked> Ask follow-up questions when an answer is thin <span class="co">(like a real interviewer would)</span></label>
      <label class="iv-check"><input type="checkbox" id="ivEach"> Tell me how I did after each answer <span class="co">(off = results at the end)</span></label>
      <label class="iv-check"><input type="checkbox" id="ivReal" checked> Realistic interviewer <span class="co">(cuts in if you go past two and a half minutes, asks for more if an answer is very short)</span></label>
      <label class="iv-check"><input type="checkbox" id="ivCamOn" ${navigator.mediaDevices?'':'disabled'}> Camera feedback <span class="co">(eye contact, framing, stillness, smile: analysed on this device, no video is stored or sent; downloads a small face-tracking model the first time)</span></label>
      <label>Interviewer<select id="ivPersona"><option value="friendly">Friendly · encouraging, still wants specifics</option><option value="neutral" selected>Neutral · professional</option><option value="tough">Tough · probes every vague claim</option></select></label>
      <label class="iv-check"><input type="checkbox" id="ivAi" ${aiName?'checked':'disabled'}> AI interviewer
        <span class="co">${aiName?`(${esc(aiName)}: ${esc((ast.privacy||{})[aiName]||'')}) writes questions for this role, reacts to what you say with its own follow-ups, coaches each answer and shows a stronger version built from your own facts`:'(no model connected — install <a href="https://ollama.com" target="_blank" rel="noopener">Ollama</a> to turn this on; the built-in rules still run the interview)'}</span></label>
      ${vst.available?`<label>Interviewer voice <span class="co">(Kokoro, runs on this machine)</span><span class="pxrow"><select id="ivVoice" style="flex:1">${vst.voices.map(v=>`<option value="${esc(v.id)}" ${v.id===(voicePref()||vst.default)?'selected':''}>${esc(v.label)}</option>`).join('')}</select>
        <button type="button" class="sm" id="ivVoiceTry">▶ Preview</button></span></label>`:''}
      <div class="co">${vst.available?'':`Interviewer voice: your browser's built-in voice, which sounds robotic. ${esc(vst.detail||'')}`}
        ${sttSupported()?'':'<br><b>This browser can\'t transcribe speech.</b> Use Chrome or Edge to answer out loud; you can still type answers here, and delivery is still measured if you allow the mic.'}</div>
      <div id="ivBase" class="iv-base"></div>
      <div><button type="button" class="go sm" id="ivStart">Start the interview</button></div>
    </div>
    <div class="block" style="margin-top:28px"><h3>Past interviews</h3><div id="ivHist"><p class="co">Loading…</p></div></div>`;
  const vs=$('#ivVoice');
  if(vs){ vs.onchange=()=>setVoicePref(vs.value); $('#ivVoiceTry').onclick=()=>{ setVoicePref(vs.value); say("Hi, I'll be your interviewer today. Tell me a little about yourself."); }; }
  $('#ivStart').onclick=()=>ivBegin($('#ivJob').value, +$('#ivLen').value, {each:$('#ivEach').checked, ai:$('#ivAi').checked, follow:$('#ivFollow').checked,
    persona:$('#ivPersona').value, kind:$('#ivKind').value, realistic:$('#ivReal').checked, camera:$('#ivCamOn').checked});
  ivHistory(); ivBaselinePanel();
}

// ---- the interview itself ----------------------------------------------------------------------------------------------
function ivStage(sub){
  $('#ivBody').innerHTML=`<div class="iv-stage">
      <div class="iv-head"><span id="ivOrb" class="iv-orb"></span><div><b>${esc(IV.job.title)}</b><div class="co">${esc(sub)} · <span id="ivProg"></span></div></div>
        <span class="spacer"></span><span class="co" id="ivState"></span>${IV.cam?'<video id="ivCamPrev" class="iv-campreview" muted playsinline></video>':''}</div>
      <div class="iv-log" id="ivLog"></div>
      <div class="iv-answer">
        <div class="iv-meter"><span class="iv-level" id="ivLevel" title="Mic level"><i></i></span><span id="ivTimer" class="iv-timer" title="Aim for one to two minutes">0:00</span></div>
        <textarea id="ivAnswer" rows="5" placeholder="Your answer appears here as you speak. You can also type or correct it."></textarea>
        <div class="actions" id="ivCtl"></div>
      </div>
    </div>`;
}
async function ivBegin(jobId, n, opts){
  const el=$('#ivBody');
  el.innerHTML=`<p class="co">${opts.ai?'The AI interviewer is reading the posting and your resume and writing questions… (a local model can take a minute)':'Preparing questions from the posting and your resume…'}</p>`;
  IV.job=JOBS.find(j=>j.job_id===jobId)||{job_id:jobId,title:'this role',company:''};
  IV.persona=opts.persona||'neutral'; IV.feedbackEach=!!opts.each; IV.useAi=!!opts.ai; IV.followUps=opts.follow!==false; IV.i=0; IV.results=[]; IV.pending=null;
  IV.kind=opts.kind||'behavioural'; IV.realistic=!!opts.realistic; IV.offer=null; IV.replay={}; IV.clips=[]; IV.drillIds=opts.drillIds||null;
  if(opts.questions){ IV.questions=opts.questions; }   // drills: the questions are given
  else try{ const r=await aiPost(`/api/jobs/${encodeURIComponent(jobId)}/interview/questions/`,{n:Math.min(n,12),persona:IV.persona,ai:IV.useAi,kind:IV.kind});
       IV.questions=(r.questions||[]).slice(0,n); IV.qProvider=r.provider; IV.offer=r.offer||null; if(r.note) toast(r.note); }
  catch(e){ el.innerHTML=`<div class="banner w">${esc(e.message)}</div>`; return; }
  if(!IV.questions.length){ el.innerHTML='<div class="banner w">No questions could be built for this role.</div>'; return; }
  if(IV.cam){ IV.cam.stop(); IV.cam=null; }
  if(opts.camera){
    el.innerHTML='<p class="co">Starting the camera and loading the face-tracking model (first time only, a few MB)…</p>';
    try{ IV.cam=await startCamera(); }catch(e){ IV.cam=null; toast('Camera feedback is off: '+(e.message||'no camera'),'bad'); }
  }
  prefetchSpeech(IV.questions[0]&&IV.questions[0].q);   // ready by the time the introduction finishes
  ivStage((IV.drillIds?'Drill':KIND_LABEL[IV.kind])+(IV.job.company?' · '+IV.job.company:''));
  if(IV.cam){ const pv=$('#ivCamPrev'); if(pv){ pv.srcObject=IV.cam.stream; pv.play().catch(()=>{}); } }
  window.onbeforeunload=()=>IV.results.length&&IV.i<IV.questions.length?'Leave the interview?':undefined;
  const turn=++IV.turn;
  const hello={friendly:"Hi, lovely to meet you, and thanks for coming in.",neutral:"Hi, thanks for coming in.",tough:"Thanks for coming in. Let's get straight to it."}[IV.persona]||"Hi, thanks for coming in.";
  const intro=IV.drillIds?`Drill time. ${IV.questions.length} question${IV.questions.length>1?'s':''} you've found hard before. Let's go.`:
    IV.kind==='screen'?`${hello} This is a quick screening call for the ${IV.job.title} role${IV.job.company?' at '+IV.job.company:''}. I just have a few questions.`:
    IV.kind==='negotiation'?`Thanks for your time. We've really enjoyed the process for the ${IV.job.title} role, and we'd like to talk about an offer.`:
    IV.kind==='reverse'?`We're nearly at the end of the interview for the ${IV.job.title} role.`:
    `${hello} I'll be interviewing you for the ${IV.job.title} role${IV.job.company?' at '+IV.job.company:''}. I have ${IV.questions.length} ${IV.kind==='technical'?'technical ':''}questions.${IV.persona==='tough'?' I will push back if an answer is vague.':' Take your time, and answer out loud as you would in the real thing.'} Let's begin.`;
  await say(intro);
  if(turn===IV.turn) ivAsk();
}

function logLine(who, html){ const l=$('#ivLog'); if(!l) return; l.insertAdjacentHTML('beforeend',`<div class="iv-msg ${who}"><span class="co">${who==='them'?'Interviewer':'You'}</span><div>${html}</div></div>`); l.scrollTop=l.scrollHeight; }
function ivControls(){
  const c=$('#ivCtl'); if(!c) return;
  c.innerHTML=IV.answering
    ?`<button type="button" class="go sm" id="ivDone">Done answering</button><button type="button" class="sm" id="ivRedo">Start over</button>`
    :`<button type="button" class="go sm" id="ivSpeak">🎙️ Answer</button><button type="button" class="sm" id="ivSubmit">Submit typed answer</button><button type="button" class="sm" id="ivRepeat">Repeat question</button>`;
  c.insertAdjacentHTML('beforeend','<button type="button" class="text" id="ivSkip">Skip</button><span class="spacer"></span><button type="button" class="text" id="ivEnd">End interview</button>');
  const on=(id,fn)=>{ const b=$('#'+id); if(b) b.onclick=fn; };
  on('ivDone',()=>ivSubmit(stopAnswer()));
  on('ivRedo',()=>{ stopAnswer(); $('#ivAnswer').value=''; startAnswer(); });
  on('ivSpeak',()=>{ hush(); startAnswer(); });
  on('ivSubmit',()=>ivSubmit(stopAnswer()));
  on('ivRepeat',async()=>{ const turn=IV.turn; await say(IV.pending?IV.pending.follow:IV.questions[IV.i].q); if(turn===IV.turn) startAnswer(); });
  on('ivSkip',()=>{ IV.turn++; stopAnswer(); hush();
    if(IV.pending){ ivScore(IV.pending.answer, IV.pending.voice, null); return; }   // skipping a follow-up: the first answer stands on its own
    logLine('me','<span class="co">(skipped)</span>'); IV.i++; ivAsk(); });
  on('ivEnd',()=>{ IV.turn++; stopAnswer(); hush(); IV.interrupt=false;
    if(IV.pending){ const p=IV.pending, q=IV.questions[IV.i];   // ended mid-follow-up: the first answer was already scored, keep it
      IV.results.push({...p.first, question:q.q, answer:p.answer, why:q.why, follow_up:p.follow, follow_answer:null}); IV.pending=null; }
    ivReport(); });
}

async function ivAsk(){
  if(IV.i>=IV.questions.length){ await say("That's all my questions. Thank you, that was great. Give me a second to put your results together."); return ivReport(); }
  const q=IV.questions[IV.i], turn=++IV.turn;
  $('#ivProg').textContent=`Question ${IV.i+1} of ${IV.questions.length}`;
  $('#ivAnswer').value=''; $('#ivTimer').textContent='0:00'; $('#ivTimer').classList.remove('over'); IV.answering=false; IV.pending=null; ivControls();
  IV.nudged=false; IV.nudgeVoice=null; IV.interrupt=false; IV.clips=[]; if(IV.cam) IV.cam.reset();
  logLine('them', esc(q.q)+(q.by&&q.by!=='rules'?` <span class="co" title="Written by ${esc(q.by)}">✦</span>`:''));
  await say(q.q);
  prefetchSpeech(IV.questions[IV.i+1]&&IV.questions[IV.i+1].q);   // synthesize the next question while they answer
  if(turn===IV.turn) startAnswer();   // not if they skipped or ended while it was being read
}

async function scoreAnswer(q,answer,voice,interrupted){
  const st=$('#ivState'), o=$('#ivOrb');
  if(st) st.textContent=IV.useAi?'Interviewer is thinking…':'Scoring…'; if(o) o.className='iv-orb think';
  const cur=IV.questions[IV.i]||{};   // drills mix types: a question's own kind/offer wins over the session's
  try{ return await aiPost(`/api/jobs/${encodeURIComponent(IV.job.job_id)}/interview/feedback/`,{question:q,answer,voice,ai:IV.useAi,persona:IV.persona,
         kind:cur.kind||IV.kind, offer:cur.offer||IV.offer, camera:IV.cam?IV.cam.snapshot():null, interrupted:!!interrupted}); }
  finally{ if(st) st.textContent=''; if(o) o.className='iv-orb'; }
}
const ACKS={friendly:['Thank you, that was helpful.','Great, thanks for sharing that.','Lovely, thank you.','Thanks, that gives me a good picture.'],
  neutral:['Thank you.','Okay, thanks.','Got it, thank you.','Great, thanks.'], tough:['Okay.','Noted.','Right. Moving on.','Fine.']};

// Done answering: either the first answer to a question (which may earn a follow-up) or the answer to that follow-up
async function ivSubmit(voice){
  const q=IV.questions[IV.i], answer=$('#ivAnswer').value.trim();
  if(IV.nudgeVoice){ voice=mergeVoice(IV.nudgeVoice,voice); IV.nudgeVoice=null; }
  // realistic: a very short spoken answer gets "could you say more?" once, and the answer continues where it left off
  if(IV.realistic && !IV.pending && !IV.nudged && voice && answer.split(/\s+/).filter(Boolean).length<SHORT_WORDS){
    IV.nudged=true; IV.nudgeVoice=voice;
    const turn=++IV.turn;
    logLine('me', esc(answer));
    logLine('them','Could you say a bit more about that?');
    await say('Could you say a bit more about that?');
    if(turn===IV.turn) startAnswer();
    return;
  }
  const cut=IV.interrupt;
  if(cut && !IV.pending){   // realistic: they talked past the limit; score what was said, then the interviewer cuts in
    const c=$('#ivCtl'); c.innerHTML='<span class="co">…</span>';
    let d; try{ d=await scoreAnswer(q.q,answer,voice,true); }catch(e){ ivControls(); return; }
    logLine('me', esc(answer));
    const follow="Let me stop you there. In one sentence, what was the result?";
    IV.pending={answer, voice, follow, first:d};
    logLine('them', follow); $('#ivAnswer').value=''; ivControls();
    const turn=++IV.turn; await say(follow); if(turn===IV.turn) startAnswer();
    return;
  }
  if(IV.pending){   // this was the follow-up: score the whole exchange as one answer to the original question
    const p=IV.pending;
    logLine('me', esc(answer||'(no answer)'));
    return ivScore([p.answer,answer].filter(Boolean).join(' '), mergeVoice(p.voice,voice), {question:p.follow, answer}, p.first&&p.first.interrupted);
  }
  const c=$('#ivCtl'); c.innerHTML='<span class="co">Scoring…</span>';
  let d;
  try{ d=await scoreAnswer(q.q,answer,voice); }
  catch(e){ toast(e.message.includes('sentences')?'That answer was too short to score. Keep going, or say more.':e.message,'bad'); ivControls(); return; }
  logLine('me', esc(answer));
  if(IV.followUps && d.follow_up){
    IV.pending={answer, voice, follow:d.follow_up, first:d};
    logLine('them', esc(d.follow_up)+(d.follow_up_by&&d.follow_up_by!=='rules'?` <span class="co">✦</span>`:''));
    $('#ivAnswer').value=''; $('#ivTimer').textContent='0:00'; ivControls();
    const turn=++IV.turn;
    await say(d.follow_up);
    if(turn===IV.turn) startAnswer();
    return;
  }
  ivRecord(d, answer, null);
}
async function ivScore(answer, voice, follow, interrupted){
  const q=IV.questions[IV.i], first=IV.pending&&IV.pending.first;
  const c=$('#ivCtl'); if(c) c.innerHTML='<span class="co">Scoring…</span>';
  let d=first;
  try{ if(follow&&follow.answer) d=await scoreAnswer(q.q,answer,voice,interrupted); }catch(e){ /* keep the first answer's score */ }
  ivRecord(d, answer, follow);
}
async function ivRecord(d, answer, follow){
  const q=IV.questions[IV.i];
  IV.pending=null;
  IV.results.push({...d, question:q.q, answer, why:q.why, follow_up:follow?follow.question:null, follow_answer:follow?follow.answer:null});
  IV.replay[IV.results.length-1]=Promise.all(IV.clips).then(a=>a.filter(Boolean)); IV.clips=[];
  if(IV.drillIds && IV.drillIds[q.q]) aiPost(`/api/coach/drills/${IV.drillIds[q.q]}/`,{score:d.overall_score}).catch(()=>{});
  if(IV.feedbackEach) logLine('them', `<span class="co iv-mini">${d.overall_score}/100 · ${esc(d.verdict)}</span>`);
  IV.i++;
  const turn=IV.turn;
  if(IV.feedbackEach) await say(d.speech+(IV.i<IV.questions.length?' Next question.':''));
  else if(IV.i<IV.questions.length) await say((ACKS[IV.persona]||ACKS.neutral)[IV.i%4]);
  if(turn===IV.turn) ivAsk();
}

// ---- the report --------------------------------------------------------------------------------------------------------
const bar=(label,v)=>v==null?'':`<div class="hbar"><span class="hbar-l">${esc(label)}</span><span class="hbar-t"><i style="width:${Math.max(2,v)}%"></i></span><span class="hbar-n">${v}</span></div>`;
function metricLine(m){
  if(!m) return '';
  const parts=[];
  if(m.pace_wpm) parts.push(`${Math.round(m.pace_wpm)} wpm`);
  if(m.pitch_mean_hz) parts.push(`pitch ${m.pitch_mean_hz}±${m.pitch_stdev_hz} Hz`);
  if(m.pause_ratio!=null) parts.push(`${Math.round(m.pause_ratio*100)}% silence`);
  if(m.long_pauses) parts.push(`${m.long_pauses} long pause${m.long_pauses>1?'s':''}`);
  return parts.length?`<div class="co">${esc(parts.join(' · '))}</div>`:'';
}
async function ivReport(){
  window.onbeforeunload=null; IV.answering=false; clearInterval(IV.tick);
  if(IV.cam){ IV.cam.stop(); IV.cam=null; }
  const el=$('#ivBody');
  if(!IV.results.length){ el.innerHTML='<div class="banner w">No answers were scored, so there is nothing to report.</div><div class="actions"><button type="button" class="go sm" id="ivAgain">Start again</button></div>'; $('#ivAgain').onclick=ivSetup; return; }
  el.innerHTML='<p class="co">Putting your results together…</p>';
  let s;
  try{ s=await aiPost('/api/ai/interview/summary/',{results:IV.results,ai:IV.useAi,save:true,job:{job_id:IV.job.job_id,title:IV.job.title,company:IV.job.company}}); }
  catch(e){ el.innerHTML=`<div class="banner w">${esc(e.message)}</div>`; return; }
  renderReport(s, IV.results, {live:true});
  if(s.drills_added) toast(`${s.drills_added} weak question${s.drills_added>1?'s were':' was'} added to your drills`);
  if(typeof coachBadges==='function') coachBadges();
  say(s.speech);
}
function renderReport(s, results, meta){
  const el=$('#ivBody');
  const weakest=results.reduce((a,b)=>b.overall_score<a.overall_score?b:a);
  const asked=Math.max(IV.questions.length, s.n);
  el.innerHTML=`<div class="iv-report">
      <div class="co iv-printhead">${esc(IV.job.title||'')}${IV.job.company?' · '+esc(IV.job.company):''}${meta.saved?' · '+esc(new Date(meta.saved).toLocaleString()):''}</div>
      <div class="figures">
        <div><div class="quiet">Overall</div><div class="mid-num">${s.overall_avg}<span class="quiet">/100</span></div></div>
        <div><div class="quiet">What you said</div><div class="mid-num">${s.content_avg}</div></div>
        <div><div class="quiet">How you said it</div><div class="mid-num">${s.delivery_avg??'—'}</div></div>
        <div><div class="quiet">Composure</div><div class="mid-num">${s.composure_avg??'—'}</div></div>
        <div><div class="quiet">Filler words</div><div class="mid-num">${s.filler_total??0}<span class="quiet">${s.filler_per_100!=null?` · ${s.filler_per_100}/100w`:''}</span></div></div>
        <div><div class="quiet">Answered</div><div class="mid-num">${s.n}<span class="quiet">/${asked}</span></div></div>
      </div>
      <div class="banner iv-ready"><b>${esc(s.readiness||s.verdict)}</b> ${providerTag(s.provider)}
        ${s.nerves?`<br>${esc(s.nerves)}${(s.composure_trend||[]).length>1?` <span class="iv-inline">${sparkline(s.composure_trend)}</span>`:''}`:''}
        ${(s.nerve_cues||[]).length?`<br><span class="co">What gave the nerves away most: ${s.nerve_cues.map(esc).join('; ')}.</span>`:''}
        ${s.coach?`<br>${esc(s.coach).replace(/\n/g,'<br>')}`:''}
        <br><span class="co">Strongest: “${esc(s.best.question)}” (${s.best.score}) · Weakest: “${esc(s.worst.question)}” (${s.worst.score})</span>
        ${(s.top_fillers||[]).length?`<br><span class="co">Your most common fillers: ${s.top_fillers.map(f=>`“${esc(f)}”`).join(', ')}</span>`:''}</div>
      ${s.recurring_tips.length?`<div class="block"><h3>Work on before the real thing</h3><ul class="list">${s.recurring_tips.map(t=>`<li>💡 ${esc(t)}</li>`).join('')}</ul></div>`:''}
      ${s.delivery_avg==null?'<p class="co">No delivery score: answers were typed, or the mic wasn\'t available. Answer out loud next time to get pace, tone, pause and volume feedback.</p>':''}
      <div class="block"><h3>Question by question</h3>
      ${results.map((r,k)=>`<details class="iv-q" ${k===0?'open':''}><summary><b>${r.overall_score}</b> <span>${esc(r.question)}</span> <span class="co">· ${esc(r.composure?r.composure.label:r.verdict)}</span></summary>
        ${r.honest?`<p class="iv-honest">${esc(r.honest)}</p>`:''}
        ${bar('Content',r.score)}${r.delivery?bar('Delivery',r.delivery.score):''}${r.composure?bar('Composure',r.composure.score):''}
        ${r.composure?`<div class="iv-comp"><b>${esc(r.composure.label)}.</b> ${esc(r.composure.honest)}
          ${r.composure.fixes.length?`<ul class="list">${r.composure.fixes.map(f=>`<li>🫁 ${esc(f)}</li>`).join('')}</ul>`:''}
          <div class="co">${esc(r.composure.caveat)}</div></div>`:''}
        ${r.camera?`<div class="iv-comp"><b>On camera · ${r.camera.score}/100.</b> ${r.camera.notes.map(esc).join(' ')}
          ${r.camera.tips.length?`<ul class="list">${r.camera.tips.map(t=>`<li>📷 ${esc(t)}</li>`).join('')}</ul>`:''}<div class="co">${esc(r.camera.caveat)}</div></div>`:''}
        <div style="margin:8px 0">${Object.entries(r.checks||r.star||{}).map(([n,v])=>`<span class="flag ${v?'g':'b'}">${v?'✓':'○'} ${esc(n)}</span>`).join('')}
          <span class="flag">${r.words} words</span><span class="flag ${r.numbers?'g':''}">${r.numbers?'has numbers':'no numbers'}</span>
          ${r.filler_count?`<span class="flag w">${r.filler_count} filler${r.filler_count>1?'s':''}: ${esc(Object.keys(r.filler||{}).join(', '))}</span>`:''}</div>
        <ul class="list">${(r.tips||[]).map(t=>`<li>💡 ${esc(t)}</li>`).join('')}
          ${r.delivery?r.delivery.notes.map(t=>`<li>✓ ${esc(t)}</li>`).join('')+r.delivery.tips.map(t=>`<li>🎙️ ${esc(t)}</li>`).join(''):''}</ul>
        ${r.delivery?metricLine(r.delivery.metrics):''}
        ${r.coach?`<div class="banner"><b>Coach</b> ${providerTag(r.provider)}<br>${esc(r.coach).replace(/\n/g,'<br>')}</div>`:''}
        ${r.stronger?`<div class="iv-stronger"><b>A stronger version, from your own facts</b> ${providerTag(r.provider)}<p>${esc(r.stronger)}</p><button type="button" class="text" data-copy="${esc(r.stronger)}">copy</button> <button type="button" class="text" data-hear="${k}">🔊 hear it</button></div>`:(r.stronger_dropped?`<div class="co">${esc(r.stronger_dropped)}</div>`:'')}
        <div class="co" style="margin-top:6px"><b>Your answer:</b> ${esc(r.follow_up?r.answer.slice(0,r.answer.length-(r.follow_answer||'').length).trim():r.answer)}</div>
        ${r.follow_up?`<div class="co" style="margin-top:6px"><b>Follow-up:</b> ${esc(r.follow_up)}<br><b>You:</b> ${esc(r.follow_answer||'')}</div>`:''}
        <div class="actions iv-noprint" style="margin-top:8px">
          ${meta.live?`<span class="iv-replay" data-replay="${k}"></span>`:''}
          ${(r.kind||'behavioural')==='behavioural'?`<button type="button" class="text" data-story="${k}">${r.overall_score>=60?'★ Save as a story':'Save as a story (improve it first)'}</button>`:''}
        </div>
      </details>`).join('')}</div>
      <div class="actions iv-noprint">
        <button type="button" class="sm" id="ivHear">🔊 Hear the wrap-up</button>
        <button type="button" class="go sm" id="ivRetry">Retry my weakest question</button>
        <button type="button" class="sm" id="ivPrint">Print / save as PDF</button>
        <button type="button" class="sm" id="ivAgain">New interview</button>
      </div>
    </div>`;
  $('#ivHear').onclick=()=>say(s.speech);
  // hear yourself back: the recordings only exist in this page, so a saved report can't replay them
  el.querySelectorAll('[data-replay]').forEach(async sp=>{ const urls=await (IV.replay[+sp.dataset.replay]||Promise.resolve([]));
    sp.innerHTML=urls.length?urls.map((u,i)=>`<audio controls preload="none" src="${u}" title="${i?'Your follow-up answer':'Your answer'}"></audio>`).join(''):''; });
  el.querySelectorAll('[data-story]').forEach(b=>b.onclick=async()=>{
    const r=results[+b.dataset.story];
    try{ await aiPost('/api/coach/stories/',{question:r.question, answer:r.stronger||r.answer, score:r.overall_score, job_id:IV.job.job_id});
      b.textContent='✓ Saved to your stories'; b.disabled=true; }catch(e){ toast(e.message,'bad'); }
  });
  el.querySelectorAll('[data-hear]').forEach(b=>b.onclick=()=>say(results[+b.dataset.hear].stronger));
  if(typeof wireCopy==='function') wireCopy();
  $('#ivAgain').onclick=()=>{ hush(); ivSetup(); };
  $('#ivPrint').onclick=()=>window.print();
  $('#ivRetry').onclick=()=>{ hush();
    const q=IV.questions.find(x=>x.q===weakest.question)||{q:weakest.question};
    IV.questions=[q]; IV.results=[]; IV.i=0; IV.pending=null; ivStage('Retry'); ivAsk(); };
}
// print every question's details, not only the open ones
window.addEventListener('beforeprint',()=>document.querySelectorAll('.iv-q').forEach(d=>{ d.dataset.was=d.open?'1':''; d.open=true; }));
window.addEventListener('afterprint',()=>document.querySelectorAll('.iv-q').forEach(d=>{ d.open=d.dataset.was==='1'; }));

Object.assign(PAGE_HOOKS,{
  init: async()=>{ if(!$('#ivBody').children.length) await ivSetup(); },
  refresh: async()=>{},   // never repaint mid-interview
});
