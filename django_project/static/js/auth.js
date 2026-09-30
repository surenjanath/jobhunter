// auth.js — sign in / create a free account. Loaded on every page; the header reflects AUTH state everywhere.
// Guest mode (no account) keeps working exactly as before accounts existed — this is purely additive.
let AUTH={authenticated:false, email:'', has_profile:false};

async function loadAuth(){
  try{ AUTH=await jfetch('/api/auth/me/'); }catch(e){ AUTH={authenticated:false,email:'',has_profile:false}; }
  paintAuthNav();
}
function paintAuthNav(){
  const el=$('#navAccount'); if(!el) return;
  el.textContent=AUTH.authenticated?AUTH.email:'Sign in';
  el.title=AUTH.authenticated?'Your account':'Sign in, or create a free account to save your resume and pipeline';
}

function openAuthDlg(mode){
  const dlg=$('#authDlg'); if(!dlg) return;
  dlg.dataset.mode=AUTH.authenticated?'account':(mode||'login');
  paintAuthDlg();
  dlg.showModal();
}

function paintAuthDlg(){
  const dlg=$('#authDlg'), body=$('#authBody'), title=$('#authTitle'), mode=dlg.dataset.mode;
  if(mode==='account'){
    title.textContent='Your account';
    body.innerHTML=`<p>Signed in as <b>${esc(AUTH.email)}</b>.</p>
      <p class="co">${AUTH.has_profile?'Your resume, fit scores and pipeline are private to this account.':'You haven’t added a resume to this account yet — the Profile page will let you.'}</p>
      <div class="actions"><button type="button" class="sm" id="authSignOut">Sign out</button></div>`;
    $('#authSignOut').onclick=async()=>{
      try{ await jfetch('/api/auth/logout/',{method:'POST'}); if(AUTH.private){ location.href='/login/'; return; } toast('Signed out'); dlg.close(); AUTH={authenticated:false,email:'',has_profile:false}; paintAuthNav();
        if(typeof refreshPage==='function') refreshPage().catch(()=>{}); }
      catch(e){ toast(e.message,'bad'); }
    };
    return;
  }
  const isRegister=mode==='register';
  title.textContent=isRegister?'Create a free account':'Sign in';
  const migrateRow=isRegister?`<label class="aiopt"><input type="checkbox" id="authMigrate" checked> Keep the resume I’m currently trying, under this account</label>`:'';
  body.innerHTML=`
    <p class="co">${isRegister?'Save your resume, fit scores and pipeline under an email and password so you can pick up where you left off, on any device.':'Access your resume, fit scores and pipeline.'}</p>
    <input id="authEmail" type="email" placeholder="Email" autocomplete="email" style="width:100%">
    <input id="authPassword" type="password" placeholder="Password (min. 8 characters)" autocomplete="${isRegister?'new-password':'current-password'}" style="width:100%;margin-top:8px">
    ${migrateRow}
    <div class="actions" style="margin-top:14px">
      <button type="button" class="go sm" id="authGo">${isRegister?'Create account':'Sign in'}</button>
      ${AUTH.signup_open===false?'':`<button type="button" class="text" id="authSwitch">${isRegister?'Have an account? Sign in':'New here? Create an account'}</button>`}
      <span class="urgent" id="authErr"></span>
    </div>`;
  const sw=$('#authSwitch'); if(sw) sw.onclick=()=>{ dlg.dataset.mode=isRegister?'login':'register'; paintAuthDlg(); };
  $('#authGo').onclick=async()=>{
    const email=$('#authEmail').value.trim(), password=$('#authPassword').value, err=$('#authErr'), go=$('#authGo');
    err.textContent=''; go.disabled=true; go.textContent='Working…';
    try{
      const body={email,password};
      if(isRegister) body.keep_current_resume=$('#authMigrate').checked;
      const d=await jfetch(isRegister?'/api/auth/register/':'/api/auth/login/',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)});
      AUTH={authenticated:true,email:d.email,has_profile:d.has_profile}; paintAuthNav();
      toast(isRegister?(d.migrated_current_resume?'Account created — your resume moved with you':'Account created'):'Signed in');
      dlg.close();
      if(typeof refreshPage==='function') refreshPage().catch(()=>{});
      if(typeof loadProfile==='function') loadProfile().catch(()=>{});
    }catch(e){ err.textContent=e.message; }
    go.disabled=false; go.textContent=isRegister?'Create account':'Sign in';
  };
}

document.addEventListener('DOMContentLoaded',()=>{
  const na=$('#navAccount'); if(na) na.onclick=e=>{ e.preventDefault(); openAuthDlg('login'); };
});
