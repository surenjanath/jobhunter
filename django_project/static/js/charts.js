// charts.js — Chart.js helpers shared by the Analytics page, the Match tab and Compare: theme-aware palette + mk().
let CHARTS={};

function cssv(n){ return getComputedStyle(document.documentElement).getPropertyValue(n).trim(); }
function palette(){
  const dark=document.documentElement.getAttribute('data-theme')==='dark';
  return {ink:cssv('--ink')||'#1c1c1c', mute:cssv('--mute')||'#8a8a85', faint:cssv('--faint')||'#c4c4be', rule:cssv('--rule')||'#d2d2cc',
          gap:dark?'#e0896e':'#b4533c', ok:dark?'#8fc39c':'#3f7a52', dark};
}
function mk(id,cfg){
  const el=document.getElementById(id); if(!el) return;
  if(CHARTS[id]) CHARTS[id].destroy();
  const P=palette();
  Chart.defaults.color=P.mute; Chart.defaults.font.family=getComputedStyle(document.body).fontFamily; Chart.defaults.font.size=11;
  Chart.defaults.borderColor=P.rule;
  cfg.options=Object.assign({responsive:true,maintainAspectRatio:false,animation:{duration:350}},cfg.options||{});
  cfg.options.plugins=Object.assign({legend:{labels:{boxWidth:10,boxHeight:10,usePointStyle:false}}},cfg.options.plugins||{});
  CHARTS[id]=new Chart(el,cfg);
}
