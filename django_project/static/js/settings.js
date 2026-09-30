// settings.js — the Settings page.
async function loadSettings(){
  const msg=$('#settingsStatus'); if(msg) msg.textContent='Loading…';
  try{
    const d=await jfetch('/api/settings/');
    SETTINGS=d;
    const p=d.preferences||{}, f=d.filters||{}, cl=d.cover_letter||{}, cand=d.candidate||{};
    $('#setShowRemote').checked=p.show_remote!==false;
    $('#setRemoteOnly').checked=p.remote_only===true;
    $('#setShowLinks').checked=p.show_links!==false;
    $('#setShowSalary').checked=p.show_salary!==false;
    $('#setHideBlockers').checked=p.hide_blockers===true;
    $('#setMinScore').value=f.min_score_to_include??35;
    $('#setMaxAge').value=f.max_age_days??30;
    $('#setKeepLocal').checked=f.keep_all_trinidad!==false;
    $('#setTTLimit').value=f.trinidad_limit_per_source??40;
    $('#setProvider').value=cl.provider||'auto';
    $('#prov').value=cl.provider||'auto'; $('#providerPill').textContent=cl.provider||'auto';
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
      cover_letter:{provider:$('#setProvider').value},
      sources,
      search_terms:$('#setSearchTerms').value.split(',').map(s=>s.trim()).filter(Boolean),
      targets:{tier_1:$('#setTier1').value.split('\n').map(s=>s.trim()).filter(Boolean), tier_2:$('#setTier2').value.split('\n').map(s=>s.trim()).filter(Boolean)},
      candidate:{website:$('#setWebsite').value.trim(), github:$('#setGithub').value.trim(), linkedin:$('#setLinkedin').value.trim()},
    };
    const d=await jfetch('/api/settings/',{method:'PUT',headers:{'Content-Type':'application/json'},body:JSON.stringify(payload)});
    SETTINGS=d;
    $('#prov').value=(d.cover_letter||{}).provider||'auto'; $('#providerPill').textContent=(d.cover_letter||{}).provider||'auto';
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
Object.assign(PAGE_HOOKS,{ init:()=>{ loadSiteAccess(); loadAlerts(); return loadSettings(); }, refresh:()=>{} });
