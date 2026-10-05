// add_job.js — the Add a job page: read a link, receive a job from the "Save to JobHunter" button, save it.
const aj=id=>document.getElementById(id);
function fillJob(f){
  if(!f) return;
  if(f.url) aj('ajUrl').value=f.url;
  if(f.title) aj('ajTitle').value=f.title;
  if(f.company) aj('ajCompany').value=f.company;
  if(f.location) aj('ajLocation').value=f.location;
  if(f.salary) aj('ajSalary').value=f.salary;
  if(f.description) aj('ajDesc').value=f.description;
  window.__ajDates={posted_at:f.posted_at||'', expires_at:f.expires_at||''};
}
async function readLink(){
  const url=aj('ajUrl').value.trim(), msg=aj('ajMsg'); if(!url){ msg.textContent='Paste a link first.'; return; }
  msg.textContent='Reading the page…';
  try{ const f=await jfetch('/api/jobs/import/',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({url,preview:true})});
    fillJob(f); msg.textContent=f.warning||'Read. Check the details, then add it.'; }
  catch(e){ msg.textContent=e.message; }
}
async function save(){
  const out=aj('ajDone'), btn=aj('ajSave'); btn.disabled=true; out.innerHTML='<p class="co">Scoring against your resume…</p>';
  const body={url:aj('ajUrl').value.trim(),title:aj('ajTitle').value,company:aj('ajCompany').value,location:aj('ajLocation').value,
    salary:aj('ajSalary').value,description:aj('ajDesc').value,...(window.__ajDates||{})};
  try{ const r=await jfetch('/api/jobs/import/',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)});
    out.innerHTML=`<div class="banner ${r.fit_score>=65?'g':r.fit_score>=50?'':'w'}"><b>Added: fit ${r.fit_score}</b> ${esc(r.tier||'')}<br><span class="co">${esc(r.why||'')}</span>
      <br><a href="/ledger/?open=${encodeURIComponent(r.job_id)}">Open it in the ledger</a> · <a href="/resume/${encodeURIComponent(r.job_id)}/" target="_blank" rel="noopener">tailored resume</a></div>`;
    if(typeof refreshPage==='function') refreshPage().catch(()=>{});
  }catch(e){ out.innerHTML=`<div class="banner w">${esc(e.message)}</div>`; }
  btn.disabled=false;
}
// the bookmarklet: runs on the job page, opens this page and hands it what the page says (JSON-LD, or selected text)
function bookmarkletCode(origin){
  const src=`(function(){var o=${JSON.stringify(origin)};var ld=[].map.call(document.querySelectorAll('script[type="application/ld+json"]'),function(s){return s.textContent});`+
    `var sel=String(window.getSelection()).trim();var d={jobhunter:1,url:location.href,title:document.title,ld:ld,text:(sel||document.body.innerText||'').slice(0,20000)};`+
    `var w=window.open(o+'/add-job/?from=button','jobhunter_add');var n=0;var t=setInterval(function(){try{w.postMessage(d,o)}catch(e){}if(++n>25)clearInterval(t)},400);})();`;
  return 'javascript:'+encodeURIComponent(src);
}
let GOT=false;
window.addEventListener('message',async e=>{
  const d=e.data; if(GOT||!d||d.jobhunter!==1) return;
  GOT=true;   // the button sends a few times until this page is ready; take the first
  // shown for you to check and save — nothing is saved from a message alone
  aj('ajUrl').value=d.url||'';
  aj('ajMsg').textContent='From the Save to JobHunter button. Check the details, then add it.';
  for(const block of (d.ld||[])){
    try{ const f=await jfetch('/api/jobs/import/',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({preview:true,ld_json:block,url:d.url})});
      if(f&&f.title){ fillJob(f); return; } }catch(err){}
  }
  fillJob({url:d.url,title:(d.title||'').replace(/\s*[|\-–]\s*[^|\-–]+$/,'').trim(),description:d.text});
});
Object.assign(PAGE_HOOKS,{ init(){
  aj('ajFetch').onclick=readLink; aj('ajSave').onclick=save;
  aj('ajUrl').addEventListener('keydown',e=>{ if(e.key==='Enter') readLink(); });
  const bm=aj('ajBookmarklet'); bm.href=bookmarkletCode(window.JH_ORIGIN||location.origin);
  bm.onclick=e=>{ e.preventDefault(); toast('Drag this link to your bookmarks bar, then click it on a job page.'); };
}, refresh(){} });
