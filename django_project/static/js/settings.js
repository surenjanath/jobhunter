// settings.js — the Settings page.
async function loadSettings(){
  const msg=$('#settingsStatus'); if(msg) msg.textContent='Loading…';
  try{
    const d=await jfetch('/api/settings/');
    SETTINGS=d;
    const p=d.preferences||{}, f=d.filters||{}, cand=d.candidate||{};
    $('#setShowRemote').checked=p.show_remote!==false;
    $('#setRemoteOnly').checked=p.remote_only===true;
    $('#setShowLinks').checked=p.show_links!==false;
    $('#setShowSalary').checked=p.show_salary!==false;
    $('#setHideBlockers').checked=p.hide_blockers===true;
    $('#setMinScore').value=f.min_score_to_include??35;
    $('#setMaxAge').value=f.max_age_days??30;
    $('#setKeepLocal').checked=f.keep_all_trinidad!==false;
    $('#setTTLimit').value=f.trinidad_limit_per_source??40;
    $('#setSearchTerms').value=(d.search_terms||[]).join(', ');
    $('#setTier1').value=((d.targets||{}).tier_1||[]).join('\n');
    $('#setTier2').value=((d.targets||{}).tier_2||[]).join('\n');
    $('#setWebsite').value=cand.website||'';
    $('#setGithub').value=cand.github||'';
    $('#setLinkedin').value=cand.linkedin||'';
    const sg=$('#sourcesGrid');
    sg.innerHTML=Object.entries(d.sources||{}).filter(([k])=>k!=='hn_whoishiring'||true).map(([k,v])=>`<label style="font-size:12px;display:flex;gap:6px;align-items:center;border:1px solid var(--line);border-radius:8px;padding:6px 9px"><input type="checkbox" data-src="${esc(k)}" ${v?'checked':''}> ${esc(k)}</label>`).join('')||'<span class="co">No sources</span>';
    const L=d.links||{};
    $('#linksPreview').innerHTML=`Links: ${L.sheet_url?`<a href="${esc(L.sheet_url)}" target="_blank">Sheet</a> · `:''}${L.website?`<a href="${esc(L.website)}" target="_blank">Site</a> · `:''}${L.github?`<a href="${esc(L.github)}" target="_blank">GitHub</a> · `:''}${L.linkedin?`<a href="${esc(L.linkedin)}" target="_blank">LinkedIn</a>`:''} <span class="co">(${(d.search_terms||[]).length} terms, ${((d.targets||{}).tier_1||[]).length+((d.targets||{}).tier_2||[]).length} targets)</span>`;
    $('#settingsMeta').textContent=`${Object.values(d.sources||{}).filter(Boolean).length}/${Object.keys(d.sources||{}).length} sources on`;
    if(msg) msg.textContent='Loaded';
  }catch(e){ if(msg) msg.textContent='Failed: '+e.message; const m=$('#settingsMsg'); if(m) m.innerHTML=`<div class="banner w">${esc(e.message)}</div>`; }
}
async function saveSettings(){
  const msg=$('#settingsStatus'); if(msg) msg.textContent='Saving…';
  try{
    const sources={};
    document.querySelectorAll('#sourcesGrid input[data-src]').forEach(el=>{sources[el.dataset.src]=el.checked;});
    const payload={
      preferences:{
        show_remote:$('#setShowRemote').checked,
        remote_only:$('#setRemoteOnly').checked,
        show_links:$('#setShowLinks').checked,
        show_salary:$('#setShowSalary').checked,
        hide_blockers:$('#setHideBlockers').checked,
      },
      filters:{min_score_to_include:+$('#setMinScore').value||35, max_age_days:+$('#setMaxAge').value||30, keep_all_trinidad:$('#setKeepLocal').checked, trinidad_limit_per_source:+$('#setTTLimit').value||40},
      sources,
      search_terms:$('#setSearchTerms').value.split(',').map(s=>s.trim()).filter(Boolean),
      targets:{tier_1:$('#setTier1').value.split('\n').map(s=>s.trim()).filter(Boolean), tier_2:$('#setTier2').value.split('\n').map(s=>s.trim()).filter(Boolean)},
      candidate:{website:$('#setWebsite').value.trim(), github:$('#setGithub').value.trim(), linkedin:$('#setLinkedin').value.trim()},
    };
    const d=await jfetch('/api/settings/',{method:'PUT',headers:{'Content-Type':'application/json'},body:JSON.stringify(payload)});
    SETTINGS=d;
    loadLLM();
    if(msg) msg.textContent='Saved ✓ — display options apply when you open the Ledger; sources and filters apply on the next scan';
    const m=$('#settingsMsg'); if(m) m.innerHTML=`<div class="banner g">Saved. Remote ${d.preferences.show_remote?'enabled':'disabled'}, links ${d.preferences.show_links?'shown':'hidden'}, ${Object.values(d.sources).filter(Boolean).length} sources on.</div>`;
  }catch(e){ if(msg) msg.textContent='Save failed: '+e.message; }
}
const _saveBtn=document.getElementById('settingsSave'); if(_saveBtn) _saveBtn.onclick=saveSettings;
const _reloadBtn=document.getElementById('settingsReload'); if(_reloadBtn) _reloadBtn.onclick=loadSettings;
// ---- site access (who can sign up, whether guests get in) -------------------------------------------------------------
async function loadSiteAccess(){
  const up=$('#siteSignup'), rq=$('#siteSignin'), note=$('#siteNote'); if(!up) return;
  let s; try{ s=await jfetch('/api/site/'); }catch(e){ note.textContent=e.message; return; }
  up.checked=s.allow_signup; rq.checked=s.require_signin;
  up.disabled=rq.disabled=!s.can_edit;
  note.textContent=!s.can_edit?'Only an admin account can change these.'
    :s.is_admin?'You are this site\'s admin.'
    :s.signed_in?'No admin yet: the first change you make here makes your account the admin.'
    :'No admin yet. Sign in (or create an account) before turning on "Require sign-in".';
  const save=async(field,el)=>{
    const want=el.checked;
    try{ const r=await jfetch('/api/site/',{method:'PUT',headers:{'Content-Type':'application/json'},body:JSON.stringify({[field]:want})});
      toast(field==='allow_signup'?(want?'New accounts allowed':'Sign-ups turned off'):(want?'Sign-in now required':'Guests can use the site'));
      if(typeof loadAuth==='function') loadAuth();
      up.checked=r.allow_signup; rq.checked=r.require_signin; loadSiteAccess(); }
    catch(e){ el.checked=!want; toast(e.message,'bad'); }
  };
  up.onchange=()=>save('allow_signup',up);
  rq.onchange=()=>save('require_signin',rq);
}
// ---- AI providers (keys, models, custom endpoint) -------------------------------------------------------------------------
let LLM=null, LLM_SCOPE='';        // '' = the server's pick: your account when signed in, else the site. 'site' = everyone's (admin)
const llmJSON=(url,method,body)=>jfetch(url,{method,headers:{'Content-Type':'application/json'},body:JSON.stringify({...(body||{}),...(LLM_SCOPE?{scope:LLM_SCOPE}:{})})});
function llmUsage(u){
  if(!u||!(u.calls||u.failures)) return '';
  const tok=(u.tokens_in||0)+(u.tokens_out||0), k=n=>n>=1000?(n/1000).toFixed(1)+'k':String(n);
  return [u.calls?`${u.calls} request${u.calls===1?'':'s'}`:'', tok?`${k(tok)} tokens`:'', u.calls?`${(u.ms/u.calls/1000).toFixed(1)}s average`:'',
    u.failures?`${u.failures} failed`:''].filter(Boolean).join(' · ');
}
function llmRow(p,open){
  const ed=LLM.can_edit, dis=ed?'':' disabled', acct=LLM.scope==='account', ownKey=p.key_source===(acct?'account':'saved');
  const keyPh=ownKey?`saved${p.key_hint?' ····'+p.key_hint:''} · type to replace`
    :p.has_key?(acct?'using the site\'s shared key · type to use your own':`set by ${p.key_env}`)
    :(p.key_optional?'API key (optional)':(acct?'your API key':'API key'));
  return `<details class="llm-row" data-p="${esc(p.name)}"${open?' open':''}>
    <summary><b>${esc(p.label)}</b> <span class="flag ${p.available?'g':''}">${p.available?'ready':'not set up'}</span><span class="co">${esc(p.detail)}</span>${llmUsage(p.usage)?`<span class="co llm-use">${esc(llmUsage(p.usage))}</span>`:''}</summary>
    <div class="llm-fields">
      ${p.editable_url?`<label>Base URL <input type="text" data-f="base_url" value="${esc(p.base_url)}" placeholder="${esc(p.default_base_url||'http://localhost:1234/v1')}" spellcheck="false"${dis}></label>`:''}
      ${p.takes_key?`<label>API key <input type="password" data-f="api_key" placeholder="${esc(keyPh)}" autocomplete="off" spellcheck="false"${dis}></label>`:''}
      <label>Model <input type="text" data-f="model" value="${esc(p.model)}" placeholder="${esc(p.default_model||'model id')}" list="llmModels-${esc(p.name)}" spellcheck="false"${dis}></label>
      <datalist id="llmModels-${esc(p.name)}"></datalist>
    </div>
    ${ed?`<div class="actions">
      <button type="button" class="sm" data-act="save">Save</button>
      <button type="button" class="sm" data-act="test">Save and test</button>
      ${p.name!=='claude_code'?'<button type="button" class="sm" data-act="models">List models</button>':''}
      ${p.takes_key&&ownKey?'<button type="button" class="text" data-act="forget">Remove key</button>':''}
      ${p.keys_url?`<a href="${esc(p.keys_url)}" target="_blank" rel="noopener">Get a key</a>`:''}
    </div>`:''}
    <div class="co llm-out" data-out>${esc(p.privacy?`Your text is ${p.privacy}.`:'')}${p.usage&&p.usage.last_error?` Last error (${esc((p.usage.last_error_at||'').replace('T',' '))}): ${esc(p.usage.last_error)}`:''}</div>
  </details>`;
}
function llmRender(keepOpen){
  const box=$('#llmList'); if(!box||!LLM) return;
  const open=new Set(keepOpen||[]);
  box.innerHTML=LLM.providers.map(p=>llmRow(p,open.has(p.name))).join('');
  const ready=LLM.providers.filter(p=>p.available).length;
  $('#llmMeta').textContent=`${ready} of ${LLM.providers.length} ready`;
  const act=LLM.providers.find(p=>p.name===LLM.active);
  $('#llmActive').textContent=act?`Requests go to ${act.label}${act.model||act.default_model?' ('+(act.model||act.default_model)+')':''}.`
    :LLM.provider==='template'?'AI is off: letters use the built-in template.'
    :LLM.provider==='auto'?'Nothing is set up yet, so the built-in template and rules are used.'
    :'This provider is not set up yet, so the built-in template and rules are used.';
  const acct=LLM.scope==='account';
  $('#llmNote').textContent=LLM.can_edit?'':'These are the site-wide settings, which only an admin can change. Sign in to add your own keys.';
  $('#llmWho').textContent=acct?'These are your own keys and choices: only your account uses them, and nobody else can see them. Wherever you set nothing, the site\'s shared settings apply.'
    :LLM.signed_in?'Site-wide: every account that has not set its own, and every guest, uses these.'
    :'Used by everyone on this copy. Create an account to keep keys of your own.';
  const sw=$('#llmScope'); sw.hidden=!(LLM.signed_in&&LLM.can_edit_site);
  sw.querySelectorAll('button').forEach(b=>{ const on=(b.dataset.scope==='site')===(LLM.scope==='site'); b.classList.toggle('on',on); b.setAttribute('aria-pressed',on); });
  const sel=$('#setProvider'), inh=sel.querySelector('option[value=""]');
  inh.hidden=inh.disabled=!acct; inh.textContent=`Site default (${LLM.site_provider||'auto'})`;
  sel.value=acct?LLM.own_provider:LLM.provider; sel.disabled=!LLM.can_edit;
  $('#llmResetUsage').hidden=!LLM.can_edit_site;
  const o=LLM.options||{}, lim=LLM.option_limits||{};
  $('#llmFallback').checked=!!o.fallback;
  [['#llmTemp','temperature'],['#llmMaxTok','max_tokens'],['#llmTimeout','timeout']].forEach(([id,k])=>{ const el=$(id), l=lim[k]||{};
    el.value=o[k]; el.min=l.min; el.max=l.max; el.placeholder=l.default; });
  ['#llmFallback','#llmTemp','#llmMaxTok','#llmTimeout','#llmOptSave','#llmTestAll'].forEach(id=>{ $(id).disabled=!LLM.can_edit; });
  box.querySelectorAll('[data-act]').forEach(b=>b.onclick=()=>llmAct(b.closest('.llm-row'),b.dataset.act,b));
}
async function loadLLM(keepOpen){
  if(!$('#llmList')) return;
  try{ LLM=await jfetch('/api/llm/'+(LLM_SCOPE?'?scope='+LLM_SCOPE:'')); llmRender(keepOpen); }
  catch(e){ $('#llmList').innerHTML=`<span class="co">${esc(e.message)}</span>`; }
}
async function llmAct(row,act,btn){
  const name=row.dataset.p, out=row.querySelector('[data-out]'), say=(t,bad)=>{ out.textContent=t; out.classList.toggle('bad',!!bad); };
  const opened=()=>[...document.querySelectorAll('.llm-row[open]')].map(r=>r.dataset.p);
  const fields={}; row.querySelectorAll('[data-f]').forEach(i=>{ if(i.dataset.f!=='api_key'||i.value.trim()) fields[i.dataset.f]=i.value.trim(); });
  btn.disabled=true;
  try{
    if(act==='forget') LLM={...await llmJSON('/api/llm/','PUT',{providers:{[name]:{api_key:''}}})};
    else LLM={...await llmJSON('/api/llm/','PUT',{providers:{[name]:fields}})};
    AI_STATUS=null;                                   // other panels re-read which provider is live
    if(act==='save'||act==='forget'){ llmRender(opened()); toast(act==='forget'?'Key removed':'Saved'); return; }
    say(act==='test'?'Asking the model…':'Fetching models…');
    const r=await llmJSON(`/api/llm/${act}/`,'POST',{provider:name});
    const was=opened(); await loadLLM(was);          // re-read, so the row shows its fresh usage counts
    const row2=document.querySelector(`.llm-row[data-p="${name}"]`), out2=row2.querySelector('[data-out]');
    if(!r.ok){ out2.textContent=r.error||'Failed'; out2.classList.add('bad'); return; }
    if(act==='test') out2.textContent=`Works (${(r.ms/1000).toFixed(1)}s). It said: “${r.reply}”`;
    else{
      row2.querySelector('datalist').innerHTML=r.models.map(m=>`<option value="${esc(m)}">`).join('');
      out2.textContent=r.models.length?`${r.models.length} models. Click the Model box to pick one: ${r.models.slice(0,6).join(', ')}${r.models.length>6?'…':''}`:'The provider listed no models.';
    }
  }catch(e){ say(e.message,true); }
  finally{ btn.disabled=false; }
}
const llmOpen=()=>[...document.querySelectorAll('.llm-row[open]')].map(r=>r.dataset.p);
async function llmSaveOptions(body,done){
  try{ LLM=await llmJSON('/api/llm/','PUT',{options:body}); AI_STATUS=null; llmRender(llmOpen()); toast(done); }
  catch(e){ toast(e.message,'bad'); loadLLM(llmOpen()); }
}
async function llmTestAll(btn){
  const ready=LLM.providers.filter(p=>p.available); if(!ready.length){ toast('No provider is ready yet','bad'); return; }
  btn.disabled=true; const results={};
  for(const p of ready){
    btn.textContent=`Testing ${p.label}…`;
    try{ results[p.name]=await llmJSON('/api/llm/test/','POST',{provider:p.name}); }catch(e){ results[p.name]={ok:false,error:e.message}; }
  }
  btn.textContent='Test every ready provider';
  await loadLLM(ready.map(p=>p.name));               // open the tested rows, with fresh usage counts
  for(const [name,r] of Object.entries(results)){
    const out=document.querySelector(`.llm-row[data-p="${name}"] [data-out]`); if(!out) continue;
    out.textContent=r.ok?`Works (${(r.ms/1000).toFixed(1)}s). It said: “${r.reply}”`:(r.error||'Failed'); out.classList.toggle('bad',!r.ok);
  }
  const ok=Object.values(results).filter(r=>r.ok), fastest=Object.entries(results).filter(([,r])=>r.ok).sort((a,b)=>a[1].ms-b[1].ms)[0];
  toast(`${ok.length} of ${ready.length} working`+(fastest?`. Fastest: ${LLM.providers.find(p=>p.name===fastest[0]).label}`:''), ok.length===ready.length?'ok':'bad', 6000);
  btn.disabled=false;
}
(()=>{
  const fb=$('#llmFallback'); if(!fb) return;
  fb.onchange=()=>llmSaveOptions({fallback:fb.checked}, fb.checked?'Fallback on':'Fallback off');
  $('#llmOptSave').onclick=()=>llmSaveOptions({temperature:+$('#llmTemp').value, max_tokens:+$('#llmMaxTok').value, timeout:+$('#llmTimeout').value},'Options saved');
  $('#llmTestAll').onclick=e=>llmTestAll(e.currentTarget);
  $('#llmScope').querySelectorAll('button').forEach(b=>b.onclick=()=>{ LLM_SCOPE=b.dataset.scope; loadLLM(); });
  $('#llmResetUsage').onclick=async()=>{ try{ await llmJSON('/api/llm/reset-usage/','POST',{}); await loadLLM(llmOpen()); toast('Usage counts cleared'); }catch(e){ toast(e.message,'bad'); } };
})();
const _provSel=document.getElementById('setProvider');
if(_provSel) _provSel.onchange=async()=>{
  try{ LLM=await llmJSON('/api/llm/','PUT',{provider:_provSel.value}); AI_STATUS=null;
    llmRender([...document.querySelectorAll('.llm-row[open]')].map(r=>r.dataset.p));
    if(LLM.scope==='account'||!LLM.signed_in){ const pv=$('#prov'); if(pv) pv.value=LLM.provider; $('#providerPill').textContent=LLM.provider; }
    toast('Provider set to '+_provSel.selectedOptions[0].textContent); }
  catch(e){ toast(e.message,'bad'); loadLLM(llmOpen()); }
};
// ---- job alerts (email / Telegram) -------------------------------------------------------------------------------------
async function loadAlerts(){
  const el=$('#alertsBody'); if(!el) return;
  let d; try{ d=await jfetch('/api/alerts/'); }catch(e){ el.textContent=e.message; return; }
  const on=Object.entries(d.channels).filter(([,v])=>v).map(([k])=>k);
  const c=d.counts||{};
  el.innerHTML=`<p>${on.length?`Sending to: <b>${on.map(esc).join(' and ')}</b>.`:'No channel set up yet. Alerts can go to email or Telegram: set the environment variables in <code>docs/ALERTS.md</code>, then restart.'}</p>
    <p>Next alert would include: ${c.picks||0} new role${c.picks===1?'':'s'}, ${c.followups||0} follow-up${c.followups===1?'':'s'} due, ${c.closing||0} closing soon.
      ${d.preview?'<button type="button" class="text" id="alPrev">Preview</button>':''}</p>
    <pre id="alPrevBox" class="al-preview" hidden>${esc(d.preview?d.preview.subject+'\n\n'+d.preview.text:'')}</pre>
    ${on.length&&d.can_send?'<div class="actions"><button type="button" class="sm" id="alTest">Send a test alert</button> <button type="button" class="sm" id="alSend">Send now</button></div>':''}`;
  const pv=$('#alPrev'); if(pv) pv.onclick=()=>{ const b=$('#alPrevBox'); b.hidden=!b.hidden; };
  const act=async(action,btn)=>{ btn.disabled=true;
    try{ const r=await jfetch('/api/alerts/',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({action})});
      const res=r.channels||{}; const bad=Object.entries(res).filter(([,v])=>v!=='sent');
      toast(bad.length?`Not sent: ${bad.map(([k,v])=>k+' '+v).join('; ')}`:(action==='test'?'Test alert sent':(r.sent?'Alert sent':r.reason||'Nothing new to send')), bad.length?'bad':'ok');
      loadAlerts(); }
    catch(e){ toast(e.message,'bad'); } btn.disabled=false; };
  const t=$('#alTest'); if(t) t.onclick=()=>act('test',t);
  const s=$('#alSend'); if(s) s.onclick=()=>act('send',s);
}
Object.assign(PAGE_HOOKS,{ init:()=>{ loadSiteAccess(); loadAlerts(); loadLLM(); return loadSettings(); }, refresh:()=>{} });
