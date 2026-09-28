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
Object.assign(PAGE_HOOKS,{ init:()=>loadSettings(), refresh:()=>{} });
