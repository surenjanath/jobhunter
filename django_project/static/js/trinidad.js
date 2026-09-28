// trinidad.js — the Trinidad page: local market summary, board health, custom sites.
const barRow=(label,n,max,onclick)=>`<div class="hbar" ${onclick?`data-filter="${esc(onclick)}"`:''}><span class="hbar-l">${esc(label)}</span><span class="hbar-t"><i style="width:${max?Math.max(2,Math.round(n/max*100)):0}%"></i></span><span class="hbar-n">${n}</span></div>`;
const STATUS_TXT={healthy:'Healthy',error:'Failing',empty:'No postings','never run':'Not run yet'};
async function renderTrinidad(){
  const el=$('#trinidadBody'); if(!el) return;
  el.innerHTML='<p class="quiet">Reading the local market…</p>';
  let L={}, S={sources:[],summary:{}};
  try{ [L,S]=await Promise.all([jfetch('/api/local/').catch(e=>({error:e.message})), jfetch('/api/sources/').catch(e=>({sources:[],summary:{},error:e.message}))]); }catch(e){ el.innerHTML=`<div class="banner w">${esc(e.message)}</div>`; return; }
  const rows=JOBS.filter(isLocal);
  const maxR=Math.max(1,...(L.by_region||[]).map(r=>r.count)), maxC=Math.max(1,...(L.by_category||[]).map(r=>r.count)), maxE=Math.max(1,...(L.top_employers||[]).map(r=>r.count));
  const sum=S.summary||{};
  el.innerHTML=`
    <div class="figures">
      <div><div class="quiet">Local roles</div><div class="mid-num">${L.total??rows.length}</div></div>
      <div><div class="quiet">New this week</div><div class="mid-num">${L.new_7d??'—'}</div></div>
      <div><div class="quiet">Closing in 7 days</div><div class="mid-num">${L.closing_7d??'—'}</div></div>
      <div><div class="quiet">Fit 50+</div><div class="mid-num">${L.relevant??'—'}</div></div>
      <div><div class="quiet">Boards healthy</div><div class="mid-num">${sum.healthy??'—'}<span class="quiet">/${sum.enabled??'—'}</span></div></div>
    </div>
    <div class="stack">
      <div class="block"><h3>By region <span class="quiet">click to filter</span></h3>${(L.by_region||[]).map(r=>barRow(r.region,r.count,maxR,'region:'+r.region)).join('')||'<p class="quiet">No data yet.</p>'}</div>
      <div class="block"><h3>By category</h3>${(L.by_category||[]).map(r=>barRow(r.category,r.count,maxC,'category:'+r.category)).join('')||'<p class="quiet">No data yet.</p>'}</div>
    </div>
    <div class="block" style="margin-top:18px"><h3>Top employers</h3>${(L.top_employers||[]).map(r=>barRow(r.company,r.count,maxE,'search:'+r.company)).join('')||'<p class="quiet">No data yet.</p>'}</div>
    <div class="block" style="margin-top:18px"><h3>Job boards <span class="quiet">${sum.total||0} sources · last scan health</span></h3>
      ${S.error?`<div class="banner w">${esc(S.error)}</div>`:''}
      <table class="src-table"><thead><tr><th>Board</th><th>Status</th><th>Roles</th><th>Last run</th><th></th></tr></thead><tbody>
      ${(S.sources||[]).map(x=>`<tr class="${x.enabled?'':'off'}">
        <td><a href="${esc(x.url)}" target="_blank" rel="noopener">${esc(x.label)}</a><div class="co">${esc(x.kind)}${x.custom?' · custom':''}</div></td>
        <td><span class="sdot ${esc(x.status.replace(' ','-'))}"></span> ${esc(x.enabled?STATUS_TXT[x.status]||x.status:'Disabled')}${x.error?`<div class="co urgent">${esc(x.error.slice(0,140))}</div>`:''}</td>
        <td>${x.jobs}</td>
        <td class="co">${x.last_run?esc(new Date(x.last_run).toLocaleString(undefined,{month:'short',day:'numeric',hour:'numeric',minute:'2-digit'})):'—'}${x.ms?` · ${(x.ms/1000).toFixed(1)}s`:''}</td>
        <td style="white-space:nowrap"><button class="sm" data-test="${esc(x.name)}">Test</button>${x.custom?` <button class="sm" data-rm="${esc(x.name)}">Remove</button>`:''}<div class="co" data-testout="${esc(x.name)}"></div></td>
      </tr>`).join('')}</tbody></table>
      <details class="addsite" open><summary>Add an employer from its careers page</summary>
        <p class="quiet">Paste a careers URL (a Greenhouse, Lever, Workday, SmartRecruiters, Workable, Recruitee or Ashby board, or an employer site that links to one). Only jobs located in Trinidad &amp; Tobago are kept.</p>
        <div class="addgrid"><input id="dtUrl" placeholder="https://company.com/careers or https://boards.greenhouse.io/company"><input id="dtName" placeholder="Short name (letters/digits), e.g. massy"></div>
        <div class="actions"><button type="button" id="dtGo">Detect</button><span class="quiet" id="dtMsg"></span></div>
        <div id="dtOut"></div>
      </details>
      <details class="addsite"><summary>Add another Trinidad site (sitemap)</summary>
        <p class="quiet">Works for any site that publishes schema.org JobPosting data (most job boards and many employer career pages do). Give it a sitemap of job pages.</p>
        <div class="addgrid">
          <input id="csName" placeholder="Short name, e.g. massy">
          <input id="csSitemap" placeholder="Sitemap URL, e.g. https://example.tt/job-sitemap.xml">
          <input id="csPattern" placeholder="Job URL pattern (regex), e.g. /jobs?/" value="/jobs?/">
          <input id="csCompany" placeholder="Company (optional)">
        </div>
        <div class="actions"><button type="button" id="csTest">Test</button><button type="button" class="go" id="csAdd">Add site</button><span class="quiet" id="csMsg"></span></div>
      </details>
    </div>
    <div class="block" style="margin-top:18px"><h3>Newest local postings</h3>
      <ul class="compare">${rows.slice().sort((a,b)=>(b.first_seen||'').localeCompare(a.first_seen||'')||(b.posted_at||'').localeCompare(a.posted_at||'')).slice(0,25).map(j=>`<li><button type="button" data-details="${esc(j.job_id)}"><span><span class="who">${esc(j.title)}</span><span class="sub">${esc(j.company)} · ${esc(j.region||j.location||'')}${j.category?' · '+esc(j.category):''}${daysLeftLabel(j)?' · '+esc(daysLeftLabel(j)):''}</span></span><span class="metric">${j.fit_score}</span></button></li>`).join('')||'<li class="quiet">No Trinidad postings in this scan. Run a scan.</li>'}</ul>
      <button type="button" class="text tiny" id="ttOpenLedger">Open all local roles in the ledger</button>
    </div>`;
  el.querySelectorAll('[data-details]').forEach(n=>n.onclick=()=>openJob(n.dataset.details));
  const toLedger=(kind,val)=>goto('jobs',{mode:'local',region:kind==='region'?val:'',category:kind==='category'?val:'',q:kind==='search'?val:''});
  el.querySelectorAll('[data-filter]').forEach(n=>n.onclick=()=>{ const [k,...v]=n.dataset.filter.split(':'); toLedger(k,v.join(':')); });
  const openL=$('#ttOpenLedger'); if(openL) openL.onclick=()=>toLedger('all','');
  el.querySelectorAll('[data-test]').forEach(b=>b.onclick=async()=>{
    const out=el.querySelector(`[data-testout="${CSS.escape(b.dataset.test)}"]`); b.disabled=true; b.textContent='Testing…'; if(out) out.textContent='';
    try{ const r=await jfetch(`/api/sources/${encodeURIComponent(b.dataset.test)}/test/`,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({limit:3})});
      if(out) out.innerHTML=r.ok?`${r.count} found in ${(r.ms/1000).toFixed(1)}s${r.sample[0]?': '+esc(r.sample[0].title):''}`:`<span class="urgent">${esc(r.error||'no postings')}</span>`;
    }catch(e){ if(out) out.innerHTML=`<span class="urgent">${esc(e.message)}</span>`; }
    b.disabled=false; b.textContent='Test';
  });
  el.querySelectorAll('[data-rm]').forEach(b=>b.onclick=async()=>{ if(!confirm(`Remove ${b.dataset.rm}?`)) return; try{ await jfetch('/api/sources/custom/',{method:'DELETE',headers:{'Content-Type':'application/json'},body:JSON.stringify({name:b.dataset.rm})}); renderTrinidad(); }catch(e){ toast(e.message,'bad'); } });
  const dtGo=$('#dtGo');
  if(dtGo) dtGo.onclick=async()=>{
    const msg=$('#dtMsg'), out=$('#dtOut'); msg.textContent='Looking…'; out.innerHTML='';
    try{
      const r=await jfetch('/api/sources/detect/',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({url:$('#dtUrl').value.trim()})});
      msg.textContent=r.candidates.length?`Found ${r.candidates.length} board${r.candidates.length>1?'s':''}`:(r.hint||'Nothing found');
      out.innerHTML=r.candidates.map((c,i)=>c.ats?`<div class="cand"><b>${esc(c.ats)}</b> <code>${esc(c.slug||c.tenant+'/'+c.site)}</code> · ${c.error?`<span class="urgent">${esc(c.error)}</span>`:`${c.sample} Trinidad &amp; Tobago job${c.sample!==1?'s':''} right now`} <button type="button" class="sm" data-addcand="${i}">Add</button></div>`:`<div class="cand co">${esc(c.note)}</div>`).join('');
      out.querySelectorAll('[data-addcand]').forEach(b=>b.onclick=async()=>{
        const c=r.candidates[+b.dataset.addcand]; const name=($('#dtName').value.trim()||c.slug||c.tenant||'').toLowerCase().replace(/[^a-z0-9_]/g,'');
        try{ await jfetch('/api/sources/custom/',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({...c,name,label:$('#dtName').value.trim()||name,force:true})}); toast('Employer added — included from the next scan'); renderTrinidad(); }
        catch(e){ toast(e.message,'bad'); }
      });
    }catch(e){ msg.textContent=e.message; }
  };
  const csBody=()=>({name:$('#csName').value.trim(), sitemap:$('#csSitemap').value.trim(), url_pattern:$('#csPattern').value.trim(), company:$('#csCompany').value.trim()});
  const csMsg=t=>{ const m=$('#csMsg'); if(m) m.textContent=t; };
  const csTest=$('#csTest'); if(csTest) csTest.onclick=async()=>{ csMsg('Testing…'); try{ const r=await jfetch('/api/sources/custom/test/',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(csBody())}); csMsg(r.ok?`Found ${r.count} postings, e.g. “${(r.sample[0]||{}).title||''}”`:(r.error||'Nothing found')); }catch(e){ csMsg(e.message); } };
  const csAdd=$('#csAdd'); if(csAdd) csAdd.onclick=async()=>{ csMsg('Adding…'); try{ await jfetch('/api/sources/custom/',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(csBody())}); csMsg('Added. It will be included in the next scan.'); setTimeout(renderTrinidad,900); }catch(e){ csMsg(e.message); } };
}

Object.assign(PAGE_HOOKS,{ init:()=>renderTrinidad(), refresh:()=>renderTrinidad() });
