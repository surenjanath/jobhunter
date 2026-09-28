// ui.js — shared UI: toasts, command palette (⌘/Ctrl-K), shortcut help, and the tracking strip in the job dialog.
// ---- toasts -------------------------------------------------------------------------------------------------------
function toast(msg,kind='ok',ms=3600){
  let box=document.getElementById('toasts'); if(!box){ box=document.createElement('div'); box.id='toasts'; document.body.appendChild(box); }
  const t=document.createElement('div'); t.className='toast '+kind; t.setAttribute('role','status'); t.textContent=msg; box.appendChild(t);
  setTimeout(()=>{ t.classList.add('out'); setTimeout(()=>t.remove(),300); },ms);
}

// ---- command palette ----------------------------------------------------------------------------------------------
let PAL_ITEMS=[], PAL_I=0;
function palCommands(){
  const go=(v,l)=>({label:`Go to ${l}`,hint:'view',run:()=>goto(v)});
  return [go('home','Conditions'),go('jobs','Ledger'),go('pipeline','Pipeline'),go('analytics','Analytics'),go('profile','Profile'),go('trinidad','Trinidad'),go('settings','Settings'),
    {label:'Ledger: local roles',hint:'mode',run:()=>goto('jobs',{mode:'local'})},{label:'Ledger: remote roles',hint:'mode',run:()=>goto('jobs',{mode:'remote'})},
    {label:'Ledger: all roles',hint:'mode',run:()=>goto('jobs')},{label:'Clear all filters',hint:'ledger',run:()=>goto('jobs')},
    {label:'Run scan',hint:'action',run:()=>launch('/api/scan/',{dry_run:true},$('#bScan'))},{label:'Re-score all jobs',hint:'action',run:async()=>{ toast('Re-scoring…'); await jfetch('/api/rescore/',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({wait:true})}); await refreshPage(); toast('Re-scored'); }},
    {label:'Open today’s digest',hint:'report',run:()=>window.open('/api/digest/?days=1&fmt=md','_blank')},{label:'Download calendar (.ics)',hint:'export',run:()=>{ location.href='/api/calendar.ics'; }},
    {label:'Toggle theme',hint:'ui',run:()=>$('#navTheme').click()},{label:'Keyboard shortcuts',hint:'help',run:()=>$('#helpDlg').showModal()}];
}
function palRender(q){
  const ql=q.toLowerCase().trim();
  const cmds=palCommands().filter(c=>!ql||c.label.toLowerCase().includes(ql));
  const jobs=ql.length>=2?JOBS.filter(j=>`${j.title} ${j.company}`.toLowerCase().includes(ql)).slice(0,8).map(j=>({label:j.title,sub:`${j.company} · fit ${j.fit_score}`,hint:'job',run:()=>{ openJob(j.job_id); }})):[];
  const ask=ql.length>=4?[{label:`Search: “${q.trim()}”`,sub:'plain English, e.g. “remote python roles worth applying”',hint:'ask',run:()=>askAndGo(q.trim())}]:[];
  const wordy=ql.split(/\s+/).length>=3||ql.startsWith('?');
  PAL_ITEMS=wordy?[...ask,...cmds.slice(0,8),...jobs]:[...cmds.slice(0,9),...jobs,...ask]; PAL_I=0;
  $('#palList').innerHTML=PAL_ITEMS.map((c,i)=>`<li class="${i===0?'on':''}" data-i="${i}"><span>${esc(c.label)}${c.sub?`<span class="co"> · ${esc(c.sub)}</span>`:''}</span><span class="co">${esc(c.hint)}</span></li>`).join('')||'<li class="co">No matches</li>';
  document.querySelectorAll('#palList li[data-i]').forEach(li=>li.onclick=()=>palRun(+li.dataset.i));
}
function palRun(i){ const it=PAL_ITEMS[i]; if(!it) return; $('#palDlg').close(); setTimeout(it.run,30); }
function palMove(d){ if(!PAL_ITEMS.length) return; PAL_I=(PAL_I+d+PAL_ITEMS.length)%PAL_ITEMS.length; document.querySelectorAll('#palList li').forEach((li,i)=>li.classList.toggle('on',i===PAL_I)); const on=document.querySelector('#palList li.on'); if(on) on.scrollIntoView({block:'nearest'}); }
function openPalette(){ const d=$('#palDlg'); if(d.open) return; $('#palInput').value=''; palRender(''); d.showModal(); setTimeout(()=>$('#palInput').focus(),20); }

// ---- tracking strip in the job dialog -----------------------------------------------------------------------------
function trackHtml(j){
  const st=["New","Shortlisted","Applied","Interviewing","Offer","Rejected","Passed on it"];
  const reason=j.dismiss_reason||'', known=DISMISS_REASONS.includes(reason), passed=(j.app_status||'New')==='Passed on it';
  return `<div class="track"><h4>Track this application</h4>
    <div class="trackrow">
      <select id="trStatus">${st.map(o=>`<option ${o===(j.app_status||'New')?'selected':''}>${o}</option>`).join('')}</select>
      <label class="co">Follow up <input type="date" id="trFollow" value="${esc(j.followup_date||'')}"></label>
      <span class="co">in <button type="button" class="text" data-fu="3">3d</button> <button type="button" class="text" data-fu="7">1w</button> <button type="button" class="text" data-fu="14">2w</button></span>
    </div>
    <div class="trackrow" id="trReasonRow" ${passed?'':'hidden'}>
      <label class="co">Why passing? <select id="trReason">${DISMISS_REASONS.map(o=>`<option ${o===reason||(!known&&o==='Other')?'selected':''}>${o}</option>`).join('')}</select></label>
      <input id="trReasonOther" placeholder="Say more…" value="${esc(!known&&reason?reason:'')}" ${(known||!reason)&&reason!=='Other'?'hidden':''}>
    </div>
    <textarea id="trNotes" rows="2" placeholder="Notes: contact, referral, what to mention…">${esc(j.notes||'')}</textarea>
    <div class="actions" style="margin-top:6px"><button type="button" class="go sm" id="trSave">Save</button><span class="co" id="trMsg"></span></div></div>`;
}
function wireTrack(j){
  const save=$('#trSave'); if(!save) return;
  document.querySelectorAll('[data-fu]').forEach(b=>b.onclick=()=>{ const d=new Date(); d.setDate(d.getDate()+ +b.dataset.fu); $('#trFollow').value=d.toISOString().slice(0,10); });
  const statusEl=$('#trStatus'), reasonRow=$('#trReasonRow'), reasonSel=$('#trReason'), reasonOther=$('#trReasonOther');
  const syncReason=()=>{ reasonRow.hidden=statusEl.value!=='Passed on it'; reasonOther.hidden=reasonSel.value!=='Other'; };
  statusEl.onchange=syncReason; reasonSel.onchange=syncReason;
  save.onclick=async()=>{
    const body={status:statusEl.value,followup_date:$('#trFollow').value,notes:$('#trNotes').value};
    if(body.status==='Applied' && !j.applied_date) body.applied_date=new Date().toISOString().slice(0,10);
    if(body.status==='Passed on it') body.dismiss_reason=reasonSel.value==='Other'?(reasonOther.value.trim()||'Other'):reasonSel.value;
    try{ await jfetch(`/api/jobs/${encodeURIComponent(j.job_id)}/status/`,{method:'PUT',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)});
      const row=JOBS.find(x=>x.job_id===j.job_id); if(row) Object.assign(row,{app_status:body.status,followup_date:body.followup_date,notes:body.notes,dismiss_reason:body.dismiss_reason??row.dismiss_reason}); Object.assign(j,{app_status:body.status,followup_date:body.followup_date,notes:body.notes,dismiss_reason:body.dismiss_reason??j.dismiss_reason});
      toast('Saved'); if(typeof render==='function') render(); loadAlerts(); }
    catch(e){ toast(e.message,'bad'); }
  };
}

// ---- wiring -------------------------------------------------------------------------------------------------------
document.addEventListener('DOMContentLoaded',()=>{
  const np=$('#navPalette'); if(np) np.onclick=e=>{ e.preventDefault(); openPalette(); };
  const nh=$('#navHelp'); if(nh) nh.onclick=e=>{ e.preventDefault(); $('#helpDlg').showModal(); };
  const pi=$('#palInput'); if(pi){ pi.oninput=()=>palRender(pi.value); pi.onkeydown=e=>{ if(e.key==='ArrowDown'){ e.preventDefault(); palMove(1); } else if(e.key==='ArrowUp'){ e.preventDefault(); palMove(-1); } else if(e.key==='Enter'){ e.preventDefault(); palRun(PAL_I); } }; }
});
document.addEventListener('keydown',e=>{
  if((e.metaKey||e.ctrlKey)&&e.key.toLowerCase()==='k'){ e.preventDefault(); openPalette(); return; }
  if(e.key==='?' && !/INPUT|TEXTAREA|SELECT/.test((e.target||{}).tagName||'') && !document.querySelector('dialog[open]')){ e.preventDefault(); $('#helpDlg').showModal(); }
});
