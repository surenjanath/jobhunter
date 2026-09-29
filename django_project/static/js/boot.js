// boot.js — runs last on every page: wire the shared shell, load state, start the page, poll for changes.
// Page scripts register their behaviour by setting PAGE_HOOKS (see core.js). Nothing page-specific belongs here.
(async function boot(){
  const start=async()=>{
    wireShell();
    loadAuth();   // not awaited: the header updates when it resolves, nothing else waits on sign-in state
    try{ SETTINGS=await jfetch('/api/settings/'); }catch(e){ /* defaults */ }
    if(PAGE_HOOKS.beforeLoad) await PAGE_HOOKS.beforeLoad();
    let d=null;
    try{ d=await loadState(); }catch(e){ const b=$('#banners'); if(b) b.innerHTML=`<div class="banner w">${esc(e.message)}</div>`; }
    if(PAGE_HOOKS.init) await PAGE_HOOKS.init(d);
    loadAlerts();
    setInterval(()=>{ if(!POLL && !document.hidden) refreshPage().catch(()=>{}); },20000);
  };
  if(document.readyState==='loading') document.addEventListener('DOMContentLoaded',start); else start();
})();
