// interview.js — the Interview page: a full mock interview, spoken end to end. The interviewer reads each question
// aloud (Kokoro when installed, the browser's own voice otherwise), you answer out loud, and the browser transcribes
// (SpeechRecognition) and measures delivery from the raw mic signal (startMetrics, ai.js). Each answer is scored by
// /api/jobs/<id>/interview/feedback/, a thin answer gets one follow-up probe, and the whole session is summed up (and
// saved to your history) by /api/ai/interview/summary/. No audio ever leaves the page.
const IV={turn:0, job:null, questions:[], i:0, results:[], feedbackEach:false, followUps:true, pending:null,
          rec:null, answering:false, stopMetrics:null, audio:null, t0:0, tick:null};
const ANSWER_TARGET=120;   // seconds: past two minutes the timer turns into a nudge to wrap up

// ---- the interviewer's voice: resolves when speech has finished, so the flow can wait on it --------------------------
async function say(text){
  if(!text) return;
  ivSpeaking(true);
  try{
    if((await voiceStatus()).available){
      const r=await fetch('/api/ai/voice/speak/?text='+encodeURIComponent(text));
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
function hush(){ if(IV.audio) IV.audio.pause(); if(window.speechSynthesis) speechSynthesis.cancel(); }
function ivSpeaking(on){ const s=$('#ivState'); if(s) s.textContent=on?'Interviewer is speaking…':(IV.answering?'Listening…':''); const o=$('#ivOrb'); if(o) o.className='iv-orb'+(on?' talk':IV.answering?' listen':''); }

// ---- listening: recognition restarts itself if the browser ends it mid-answer (Chrome stops after a silence) --------
const fmtTime=s=>`${Math.floor(s/60)}:${String(Math.floor(s%60)).padStart(2,'0')}`;
function startAnswer(){
  if(IV.answering) return;
  const box=$('#ivAnswer'); IV.answering=true; ivControls();
  IV.t0=Date.now(); clearInterval(IV.tick);
  IV.tick=setInterval(()=>{ const t=$('#ivTimer'); if(!t) return; const s=(Date.now()-IV.t0)/1000; t.textContent=fmtTime(s); t.classList.toggle('over',s>ANSWER_TARGET); },250);
  const lvl=e=>{ const m=$('#ivLevel i'); if(m) m.style.width=Math.min(100,Math.round(e*400))+'%'; };
  startMetrics(lvl).then(stop=>{ if(IV.answering) IV.stopMetrics=stop; else stop(0); }).catch(()=>{ IV.stopMetrics=null; });
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
  const voice=IV.stopMetrics?IV.stopMetrics(words):null; IV.stopMetrics=null;
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
      <label>Length<select id="ivLen"><option value="3">Short · 3 questions</option><option value="5" selected>Standard · 5 questions</option><option value="99">Full · every question</option></select></label>
      <label class="iv-check"><input type="checkbox" id="ivFollow" checked> Ask follow-up questions when an answer is thin <span class="co">(like a real interviewer would)</span></label>
      <label class="iv-check"><input type="checkbox" id="ivEach"> Tell me how I did after each answer <span class="co">(off = results at the end)</span></label>
      <label>Interviewer<select id="ivPersona"><option value="friendly">Friendly · encouraging, still wants specifics</option><option value="neutral" selected>Neutral · professional</option><option value="tough">Tough · probes every vague claim</option></select></label>
      <label class="iv-check"><input type="checkbox" id="ivAi" ${aiName?'checked':'disabled'}> AI interviewer
        <span class="co">${aiName?`(${esc(aiName)}: ${esc((ast.privacy||{})[aiName]||'')}) writes questions for this role, reacts to what you say with its own follow-ups, coaches each answer and shows a stronger version built from your own facts`:'(no model connected — install <a href="https://ollama.com" target="_blank" rel="noopener">Ollama</a> to turn this on; the built-in rules still run the interview)'}</span></label>
      <div class="co">${vst.available?'Interviewer voice: Kokoro, local.':'Interviewer voice: your browser\'s built-in voice. Install Kokoro for a natural one (<code>pip install kokoro soundfile numpy</code>).'}
        ${sttSupported()?'':'<br><b>This browser can\'t transcribe speech.</b> Use Chrome or Edge to answer out loud; you can still type answers here, and delivery is still measured if you allow the mic.'}</div>
      <div><button type="button" class="go sm" id="ivStart">Start the interview</button></div>
    </div>
    <div class="block" style="margin-top:28px"><h3>Past interviews</h3><div id="ivHist"><p class="co">Loading…</p></div></div>`;
  $('#ivStart').onclick=()=>ivBegin($('#ivJob').value, +$('#ivLen').value, {each:$('#ivEach').checked, ai:$('#ivAi').checked, follow:$('#ivFollow').checked, persona:$('#ivPersona').value});
  ivHistory();
}

// ---- the interview itself ----------------------------------------------------------------------------------------------
function ivStage(sub){
  $('#ivBody').innerHTML=`<div class="iv-stage">
      <div class="iv-head"><span id="ivOrb" class="iv-orb"></span><div><b>${esc(IV.job.title)}</b><div class="co">${esc(sub)} · <span id="ivProg"></span></div></div>
        <span class="spacer"></span><span class="co" id="ivState"></span></div>
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
  try{ const r=await aiPost(`/api/jobs/${encodeURIComponent(jobId)}/interview/questions/`,{n:Math.min(n,12),persona:IV.persona,ai:IV.useAi});
       IV.questions=(r.questions||[]).slice(0,n); IV.qProvider=r.provider; if(r.note) toast(r.note); }
  catch(e){ el.innerHTML=`<div class="banner w">${esc(e.message)}</div>`; return; }
  if(!IV.questions.length){ el.innerHTML='<div class="banner w">No questions could be built for this role.</div>'; return; }
  ivStage(IV.job.company||'Mock interview');
  window.onbeforeunload=()=>IV.results.length&&IV.i<IV.questions.length?'Leave the interview?':undefined;
  const turn=++IV.turn;
  const hello={friendly:"Hi, lovely to meet you, and thanks for coming in.",neutral:"Hi, thanks for coming in.",tough:"Thanks for coming in. Let's get straight to it."}[IV.persona]||"Hi, thanks for coming in.";
  await say(`${hello} I'll be interviewing you for the ${IV.job.title} role${IV.job.company?' at '+IV.job.company:''}. I have ${IV.questions.length} questions.${IV.persona==='tough'?' I will push back if an answer is vague.':' Take your time, and answer out loud as you would in the real thing.'} Let's begin.`);
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
  on('ivEnd',()=>{ IV.turn++; stopAnswer(); hush();
    if(IV.pending){ const p=IV.pending, q=IV.questions[IV.i];   // ended mid-follow-up: the first answer was already scored, keep it
      IV.results.push({...p.first, question:q.q, answer:p.answer, why:q.why, follow_up:p.follow, follow_answer:null}); IV.pending=null; }
    ivReport(); });
}

async function ivAsk(){
  if(IV.i>=IV.questions.length){ await say("That's all my questions. Thank you, that was great. Give me a second to put your results together."); return ivReport(); }
  const q=IV.questions[IV.i], turn=++IV.turn;
  $('#ivProg').textContent=`Question ${IV.i+1} of ${IV.questions.length}`;
  $('#ivAnswer').value=''; $('#ivTimer').textContent='0:00'; $('#ivTimer').classList.remove('over'); IV.answering=false; IV.pending=null; ivControls();
  logLine('them', esc(q.q)+(q.by&&q.by!=='rules'?` <span class="co" title="Written by ${esc(q.by)}">✦</span>`:''));
  await say(q.q);
  if(turn===IV.turn) startAnswer();   // not if they skipped or ended while it was being read
}

async function scoreAnswer(q,answer,voice){
  const st=$('#ivState'), o=$('#ivOrb');
  if(st) st.textContent=IV.useAi?'Interviewer is thinking…':'Scoring…'; if(o) o.className='iv-orb think';
  try{ return await aiPost(`/api/jobs/${encodeURIComponent(IV.job.job_id)}/interview/feedback/`,{question:q,answer,voice,ai:IV.useAi,persona:IV.persona}); }
  finally{ if(st) st.textContent=''; if(o) o.className='iv-orb'; }
}
const ACKS={friendly:['Thank you, that was helpful.','Great, thanks for sharing that.','Lovely, thank you.','Thanks, that gives me a good picture.'],
  neutral:['Thank you.','Okay, thanks.','Got it, thank you.','Great, thanks.'], tough:['Okay.','Noted.','Right. Moving on.','Fine.']};

// Done answering: either the first answer to a question (which may earn a follow-up) or the answer to that follow-up
async function ivSubmit(voice){
  const q=IV.questions[IV.i], answer=$('#ivAnswer').value.trim();
  if(IV.pending){   // this was the follow-up: score the whole exchange as one answer to the original question
    const p=IV.pending;
    logLine('me', esc(answer||'(no answer)'));
    return ivScore([p.answer,answer].filter(Boolean).join(' '), mergeVoice(p.voice,voice), {question:p.follow, answer});
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
async function ivScore(answer, voice, follow){
  const q=IV.questions[IV.i], first=IV.pending&&IV.pending.first;
  const c=$('#ivCtl'); if(c) c.innerHTML='<span class="co">Scoring…</span>';
  let d=first;
  try{ if(follow&&follow.answer) d=await scoreAnswer(q.q,answer,voice); }catch(e){ /* keep the first answer's score */ }
  ivRecord(d, answer, follow);
}
async function ivRecord(d, answer, follow){
  const q=IV.questions[IV.i];
  IV.pending=null;
  IV.results.push({...d, question:q.q, answer, why:q.why, follow_up:follow?follow.question:null, follow_answer:follow?follow.answer:null});
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
  const el=$('#ivBody');
  if(!IV.results.length){ el.innerHTML='<div class="banner w">No answers were scored, so there is nothing to report.</div><div class="actions"><button type="button" class="go sm" id="ivAgain">Start again</button></div>'; $('#ivAgain').onclick=ivSetup; return; }
  el.innerHTML='<p class="co">Putting your results together…</p>';
  let s;
  try{ s=await aiPost('/api/ai/interview/summary/',{results:IV.results,ai:IV.useAi,save:true,job:{job_id:IV.job.job_id,title:IV.job.title,company:IV.job.company}}); }
  catch(e){ el.innerHTML=`<div class="banner w">${esc(e.message)}</div>`; return; }
  renderReport(s, IV.results, {});
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
        <div style="margin:8px 0">${Object.entries(r.star||{}).map(([n,v])=>`<span class="flag ${v?'g':'b'}">${v?'✓':'○'} ${esc(n)}</span>`).join('')}
          <span class="flag">${r.words} words</span><span class="flag ${r.numbers?'g':''}">${r.numbers?'has numbers':'no numbers'}</span>
          ${r.filler_count?`<span class="flag w">${r.filler_count} filler${r.filler_count>1?'s':''}: ${esc(Object.keys(r.filler||{}).join(', '))}</span>`:''}</div>
        <ul class="list">${(r.tips||[]).map(t=>`<li>💡 ${esc(t)}</li>`).join('')}
          ${r.delivery?r.delivery.notes.map(t=>`<li>✓ ${esc(t)}</li>`).join('')+r.delivery.tips.map(t=>`<li>🎙️ ${esc(t)}</li>`).join(''):''}</ul>
        ${r.delivery?metricLine(r.delivery.metrics):''}
        ${r.coach?`<div class="banner"><b>Coach</b> ${providerTag(r.provider)}<br>${esc(r.coach).replace(/\n/g,'<br>')}</div>`:''}
        ${r.stronger?`<div class="iv-stronger"><b>A stronger version, from your own facts</b> ${providerTag(r.provider)}<p>${esc(r.stronger)}</p><button type="button" class="text" data-copy="${esc(r.stronger)}">copy</button> <button type="button" class="text" data-hear="${k}">🔊 hear it</button></div>`:(r.stronger_dropped?`<div class="co">${esc(r.stronger_dropped)}</div>`:'')}
        <div class="co" style="margin-top:6px"><b>Your answer:</b> ${esc(r.follow_up?r.answer.slice(0,r.answer.length-(r.follow_answer||'').length).trim():r.answer)}</div>
        ${r.follow_up?`<div class="co" style="margin-top:6px"><b>Follow-up:</b> ${esc(r.follow_up)}<br><b>You:</b> ${esc(r.follow_answer||'')}</div>`:''}
      </details>`).join('')}</div>
      <div class="actions iv-noprint">
        <button type="button" class="sm" id="ivHear">🔊 Hear the wrap-up</button>
        <button type="button" class="go sm" id="ivRetry">Retry my weakest question</button>
        <button type="button" class="sm" id="ivPrint">Print / save as PDF</button>
        <button type="button" class="sm" id="ivAgain">New interview</button>
      </div>
    </div>`;
  $('#ivHear').onclick=()=>say(s.speech);
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
