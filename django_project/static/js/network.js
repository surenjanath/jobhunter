// network.js — the Pipeline page's Contacts and Offers (/api/coach/contacts/, /api/coach/offers/). Private per account.
const npost=(url,body,method)=>jfetch(url,{method:method||'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body||{})});
const KINDS_C={recruiter:'Recruiter',referrer:'Referrer',hiring:'Hiring manager',peer:'Peer',other:'Other'};
const fmtDate=d=>d?new Date(d+'T12:00:00').toLocaleDateString(undefined,{month:'short',day:'numeric'}):'';
const money=n=>'TT$'+Math.round(n||0).toLocaleString();

async function renderContacts(){
  const el=$('#contactsBody'); if(!el) return;
  let d; try{ d=await jfetch('/api/coach/contacts/'); }catch(e){ el.innerHTML=`<div class="banner w">${esc(e.message)}</div>`; return; }
  const companies=[...new Set(JOBS.filter(j=>j.app_status&&j.app_status!=='New').map(j=>j.company))].slice(0,40);
  el.innerHTML=`${d.due.length?`<div class="banner"><b>${d.due.length} to reach out to today:</b> ${d.due.map(c=>`${esc(c.name)} (${esc(c.next_step||'follow up')})`).join(' · ')}</div>`:''}
    ${d.contacts.length?`<table class="src-table net-table"><thead><tr><th>Who</th><th>Company</th><th>Next step</th><th>Last contact</th><th></th></tr></thead><tbody>
      ${d.contacts.map(c=>`<tr class="${c.due?'net-due':''}"><td><b>${esc(c.name)}</b><div class="co">${esc(KINDS_C[c.kind]||c.kind)}${c.role?' · '+esc(c.role):''}${c.how_met?' · met: '+esc(c.how_met):''}</div>
          ${c.email?`<a href="mailto:${esc(c.email)}">${esc(c.email)}</a> `:''}${c.link?`<a href="${esc(/^https?:/.test(c.link)?c.link:'https://'+c.link)}" target="_blank" rel="noopener">profile</a>`:''}
          ${c.notes?`<div class="co">${esc(c.notes)}</div>`:''}</td>
        <td>${esc(c.company)}</td><td>${esc(c.next_step||'—')}${c.next_date?`<div class="co">${fmtDate(c.next_date)}</div>`:''}</td><td>${fmtDate(c.last_contacted)||'—'}</td>
        <td class="iv-rowact"><button type="button" class="text" data-touched="${c.id}" title="I contacted them today; plan the next step">Contacted today</button>
          <button type="button" class="text" data-cdel="${c.id}">✕</button></td></tr>`).join('')}</tbody></table>`
      :'<p class="co">No contacts yet. A referral is the single best way in: add the recruiter or anyone you know at a company you\'re applying to.</p>'}
    <details class="net-add"><summary>Add a contact</summary>
      <div class="net-form">
        <input id="ncName" placeholder="Name"><input id="ncCompany" placeholder="Company" list="ncCompanies"><datalist id="ncCompanies">${companies.map(c=>`<option value="${esc(c)}">`).join('')}</datalist>
        <select id="ncKind">${Object.entries(KINDS_C).map(([k,v])=>`<option value="${k}">${v}</option>`).join('')}</select><input id="ncRole" placeholder="Their role">
        <input id="ncEmail" placeholder="Email"><input id="ncLink" placeholder="LinkedIn URL"><input id="ncHow" placeholder="How you know them">
        <input id="ncNext" placeholder="Next step (e.g. ask for a referral)"><input id="ncDate" type="date" title="When">
        <textarea id="ncNotes" rows="2" placeholder="Notes"></textarea>
        <button type="button" class="go sm" id="ncAdd">Add contact</button></div></details>`;
  const on=(sel,fn)=>el.querySelectorAll(sel).forEach(b=>b.onclick=()=>fn(b));
  on('[data-cdel]',async b=>{ if(b.dataset.sure!=='1'){ b.dataset.sure='1'; b.textContent='Delete?'; return; } await jfetch(`/api/coach/contacts/${b.dataset.cdel}/`,{method:'DELETE'}); renderContacts(); });
  on('[data-touched]',async b=>{ const today=localISO(), in7=localISOIn(7);
    await npost(`/api/coach/contacts/${b.dataset.touched}/`,{last_contacted:today,next_date:in7},'PUT'); toast('Noted. Next check-in in a week.'); renderContacts(); });
  $('#ncAdd').onclick=async()=>{
    try{ await npost('/api/coach/contacts/',{name:$('#ncName').value,company:$('#ncCompany').value,kind:$('#ncKind').value,role:$('#ncRole').value,email:$('#ncEmail').value,
        link:$('#ncLink').value,how_met:$('#ncHow').value,next_step:$('#ncNext').value,next_date:$('#ncDate').value,notes:$('#ncNotes').value}); renderContacts(); }
    catch(e){ toast(e.message,'bad'); } };
}

async function renderOffers(){
  const el=$('#offersBody'); if(!el) return;
  let d; try{ d=await jfetch('/api/coach/offers/'); }catch(e){ el.innerHTML=`<div class="banner w">${esc(e.message)}</div>`; return; }
  const jobFor=o=>(JOBS.find(j=>j.job_id===o.job_id)||JOBS.find(j=>(j.company||'').toLowerCase()===(o.company||'').toLowerCase())||{}).job_id;
  el.innerHTML=`${d.offers.length?`
    ${d.notes.length?`<div class="banner"><ul class="list">${d.notes.map(n=>`<li>▸ ${esc(n)}</li>`).join('')}</ul></div>`:''}
    <table class="src-table net-table"><thead><tr><th>Offer</th><th>Base</th><th>First-year total / month</th><th>Leave</th><th>Remote</th><th>Commute</th><th></th></tr></thead><tbody>
    ${d.offers.map((o,i)=>`<tr><td><b>${esc(o.company)}</b>${i===0&&d.offers.length>1?' <span class="flag g">best value</span>':''}${o.below_floor?' <span class="flag b">below your floor</span>':''}
        <div class="co">${esc(o.title||'')}${o.deadline?` · decide by ${fmtDate(o.deadline)}`:''} · ${esc(o.status)}</div>${o.notes?`<div class="co">${esc(o.notes)}</div>`:''}</td>
      <td>${esc(o.currency)}${Math.round(o.base_monthly).toLocaleString()}${o.currency==='US$'?`<div class="co">${money(o.value.base_ttd)}</div>`:''}</td>
      <td><b>${money(o.value.total_ttd)}</b><div class="co">${o.bonus_pct?`+${o.bonus_pct}% bonus`:''}${o.signing?` + signing`:''}</div></td>
      <td>${o.value.leave_days||'—'} days</td><td>${o.value.remote_days}/5 days</td><td>${o.value.commute_hours_week?o.value.commute_hours_week+' h/week':'—'}</td>
      <td class="iv-rowact">${jobFor(o)?`<a href="/interview/?job=${encodeURIComponent(jobFor(o))}&kind=negotiation&offer=${Math.round(o.base_monthly)}&currency=${encodeURIComponent(o.currency)}" title="Practise negotiating this offer, out loud">Practise negotiating</a> `:''}
        <button type="button" class="text" data-odel="${o.id}">✕</button></td></tr>`).join('')}</tbody></table>
    <p class="co">Bonus and signing bonus are spread over the first year; US$ converted at ${d.fx} TT$ per US$ (change it in your Profile preferences).</p>`
    :'<p class="co">No offers yet. When one arrives, add it here to compare it with others on the whole package, and to practise negotiating it.</p>'}
    <details class="net-add"><summary>Add an offer</summary>
      <div class="net-form">
        <input id="noCompany" placeholder="Company"><input id="noTitle" placeholder="Job title">
        <input id="noBase" type="number" placeholder="Base pay per month"><select id="noCur"><option>TT$</option><option>US$</option></select>
        <input id="noBonus" type="number" placeholder="Bonus % of salary"><input id="noSigning" type="number" placeholder="Signing bonus (one-off)">
        <input id="noLeave" type="number" placeholder="Leave days / year"><input id="noRemote" type="number" min="0" max="5" placeholder="Remote days / week">
        <input id="noCommute" type="number" placeholder="Commute, minutes one way"><input id="noDeadline" type="date" title="Decide by">
        <textarea id="noNotes" rows="2" placeholder="Notes (benefits, pension, health, equity…)"></textarea>
        <button type="button" class="go sm" id="noAdd">Add offer</button></div></details>`;
  el.querySelectorAll('[data-odel]').forEach(b=>b.onclick=async()=>{ if(b.dataset.sure!=='1'){ b.dataset.sure='1'; b.textContent='Delete?'; return; } await jfetch(`/api/coach/offers/${b.dataset.odel}/`,{method:'DELETE'}); renderOffers(); });
  $('#noAdd').onclick=async()=>{
    const co=$('#noCompany').value, match=JOBS.find(j=>(j.company||'').toLowerCase()===co.trim().toLowerCase());
    try{ await npost('/api/coach/offers/',{company:co,title:$('#noTitle').value,job_id:match?match.job_id:'',base_monthly:$('#noBase').value,currency:$('#noCur').value,
        bonus_pct:$('#noBonus').value,signing:$('#noSigning').value,leave_days:$('#noLeave').value,remote_days:$('#noRemote').value,commute_minutes:$('#noCommute').value,
        deadline:$('#noDeadline').value,notes:$('#noNotes').value}); renderOffers(); }
    catch(e){ toast(e.message,'bad'); } };
}

(function(){
  const prev=PAGE_HOOKS.init;
  PAGE_HOOKS.init=async d=>{ if(prev) await prev(d); renderContacts(); renderOffers(); };
})();
