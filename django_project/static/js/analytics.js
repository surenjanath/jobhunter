// analytics.js — the Analytics page: what the data says about your search, your strengths against the market,
// and where to focus. One call to /api/insights/, ~16 charts (helpers in charts.js).
let AN=null, AN_KEY='';

const panel=(id,title,note,h=240,extra='')=>`<section class="panel"><h3>${title}${note?` <span class="quiet">${note}</span>`:''}</h3><div class="chartbox" style="height:${h}px"><canvas id="${id}"></canvas></div>${extra}</section>`;
const fig=(label,val,sub='')=>`<div><div class="quiet">${label}</div><div class="mid-num">${val}</div>${sub?`<div class="quiet" style="font-size:12px">${sub}</div>`:''}</div>`;
const KIND_ICON={good:'●',warn:'▲',action:'→',info:'○'};

async function loadInsights(){
  const root=$('#anRoot'); if(!root) return;
  if(!AN) root.innerHTML='<p class="quiet">Reading your search…</p>';
  let d; try{ d=await jfetch('/api/insights/'); }catch(e){ root.innerHTML=`<div class="banner w">${esc(e.message)}</div>`; return; }
  const key=JSON.stringify({...d,generated:0});
  if(AN && key===AN_KEY) return;            // the 20s poll must not redraw identical charts
  AN=d; AN_KEY=key; paintInsights();
}

function paintInsights(){
  const d=AN, o=d.overview, root=$('#anRoot'); if(!root||!d) return;
  $('#analyticsMeta').textContent=`${o.scored} of ${o.total} listings scored · updated ${new Date(d.generated).toLocaleTimeString([], {hour:'numeric',minute:'2-digit'})}`;
  const roi=d.gap_roi.slice(0,8), mk_=d.market_skills.slice(0,18);
  root.innerHTML=`
    <div class="figures">
      ${fig('Listings',o.total,`${o.local} local · ${o.remote} remote`)}
      ${fig('Good fit (50+)',o.good_fit,`${o.strong_fit} strong (65+)`)}
      ${fig('Decent odds',o.medium_odds,'Medium or High')}
      ${fig('Avg interview chance',o.avg_chance+'%','across all listings')}
      ${fig('Posted this week',o.new_week)}
      ${fig('Good fit closing ≤7d',o.closing_week)}
      ${fig('Blocked',o.blocked,'US-only, relocation…')}
    </div>
    <nav class="subnav" aria-label="Sections"><a href="#an-says">What it says</a><a href="#an-grid">Strengths &amp; demand</a><a href="#an-market">Market intelligence</a><a href="#an-best">Best opportunities</a></nav>
    <section class="panel wide" id="an-says"><h3>What the data says</h3>
      <ul class="insights">${d.insights.map(i=>`<li class="ins-${esc(i.kind)}"><span>${KIND_ICON[i.kind]||'○'}</span> ${esc(i.text)}</li>`).join('')}</ul></section>

    <div class="pgrid" id="an-grid">
      ${panel('cFit','Fit across all listings','local vs remote vs abroad')}
      ${panel('cOdds','Your odds','by verdict',240)}
      ${panel('cSkills','Your skills vs what listings ask for','top 18 skills · length = listings asking',480,'<p class="legend-note"><i class="sw have"></i> you have it <i class="sw rel"></i> adjacent <i class="sw miss"></i> missing</p>')}
      <div>
        ${panel('cRadar','Coverage by skill area','share of demanded skills you cover',300)}
        <section class="panel"><h3>Learn next <span class="quiet">missing skills that block the most listings</span></h3>
          <table class="mini"><thead><tr><th>Skill</th><th title="Listings where this is the ONLY thing missing">Only gap</th><th>Asked in</th><th>Local / remote</th></tr></thead><tbody>
          ${roi.map(g=>`<tr><td><b>${esc(g.skill)}</b><div class="co">${esc(g.category)}</div></td><td><span class="bar-cell"><i style="width:${Math.min(100,g.sole_gap/Math.max(1,roi[0].sole_gap)*100)}%"></i></span> ${g.sole_gap}</td><td>${g.jobs}</td><td class="co">${g.local} / ${g.remote} <button type="button" class="text tiny" data-road="${esc(g.skill)}" data-j="${g.jobs}" data-s="${g.sole_gap}" title="A learning plan for ${esc(g.skill)}">✦ plan</button></td></tr>`).join('')||'<tr><td colspan="4" class="co">No missing required skills across your listings.</td></tr>'}
          </tbody></table></section>
      </div>
      ${panel('cStrength','Your most marketable skills','how many listings want each',300)}
      ${panel('cMode','Local vs remote','average fit, odds and interview chance',260)}
      ${panel('cScope','Who remote roles are open to','',260)}
      ${panel('cTime','Listings posted, last 30 days','by the date on the posting',240)}
      ${panel('cClose','Closing in the next 14 days','good-fit vs others',240)}
      ${panel('cRegion','Local roles by region','count and average fit',300)}
      ${panel('cCat','By category','count and good fits',300)}
      ${panel('cSrc','Source quality','good-fit roles found',260)}
      ${panel('cSal','Pay stated in listings',`${d.salary.disclosed_share}% state pay`,260,`<p class="legend-note">Median stated: ${d.salary.local.median?`TT$${d.salary.local.median.toLocaleString()}/mo local`:'no local pay data'} · ${d.salary.remote.median?`US$${d.salary.remote.median.toLocaleString()}/mo remote`:'no remote pay data'}${d.salary.floor_ttd?` · your floor TT$${d.salary.floor_ttd.toLocaleString()}`:''}</p>`)}
      ${panel('cFunnel','Application funnel',`${d.funnel.applied} applied · ${d.funnel.interviews} interviews · ${d.funnel.offers} offers`,240,`<p class="legend-note">${esc(d.funnel.hint)}${d.funnel.stale_applied?` <b>${d.funnel.stale_applied} awaiting reply 3+ weeks.</b>`:''}</p>`)}
      ${panel('cWeek','Applications per week','',240)}
      ${panel('cScans','Scan history','jobs kept per scan',220)}
      <section class="panel"><h3>Board health <span class="quiet">latest scan</span></h3>
        <table class="mini"><tbody>${(d.boards||[]).map(b=>`<tr><td>${esc(b.label)}</td><td>${b.ok?(b.count?'●':'○'):'<span class="urgent">✕</span>'} ${b.count} roles</td><td class="co">${(b.ms/1000).toFixed(1)}s${b.error?` · ${esc(b.error.slice(0,60))}`:''}</td></tr>`).join('')||'<tr><td class="co">No scan recorded yet.</td></tr>'}</tbody></table></section>
    </div>
    ${marketBlock(d)}
    <section class="panel wide" id="an-best"><h3>Best opportunities right now <span class="quiet">fit and odds together, blockers removed, not yet applied</span></h3>
      <ul class="compare">${d.top.map(t=>`<li><button type="button" data-details="${esc(t.job_id)}"><span><span class="who">${esc(t.title)}</span><span class="sub">${esc(t.company)} · ${t.mode==='local'?esc(t.region||'Local'):esc(t.mode)} · ${esc(t.advice)}${t.closes?` · closes ${esc(t.closes)}`:''}</span></span><span class="metric">fit ${t.fit} · <span class="pill ${t.verdict==='Long shot'?'Long':esc(t.verdict)}">${esc(t.verdict)}</span> ~${t.chance}%</span></button></li>`).join('')||'<li class="quiet">Nothing qualifies yet — run a scan or relax your preferences.</li>'}</ul></section>`;
  root.querySelectorAll('[data-details]').forEach(n=>n.onclick=()=>openJob(n.dataset.details));
  root.querySelectorAll('[data-road]').forEach(b=>b.onclick=()=>openRoadmap(b.dataset.road,+b.dataset.j,+b.dataset.s));
  drawInsightCharts();
}

// ---- market intelligence (v2): opportunity map, coverage trend, bundles, employers, pay by category, experience, time open --------------
function marketBlock(d){
  const m=d.market||{score:0,raise:[]}, ex=d.experience, to=d.time_open, hist=d.history||[];
  const payL=(d.pay_by_category||{}).local||[], payR=(d.pay_by_category||{}).remote||[];
  const tbl=(rows,head)=>`<table class="mini"><thead><tr>${head.map(h=>`<th>${h}</th>`).join('')}</tr></thead><tbody>${rows}</tbody></table>`;
  return `<h2 class="sheet-title" id="an-market" style="margin-top:34px">Market intelligence <span class="quiet">· Where to spend your effort ·</span></h2>
    <div class="pgrid">
      <section class="panel wide"><h3>Opportunity map <span class="quiet">every unapplied listing: fit across, odds up · click a dot to open it</span></h3>
        <div class="chartbox" style="height:360px"><canvas id="cMap"></canvas></div>
        <p class="legend-note">Top right is where to apply. Bottom right is a good fit that is hard to land (competition, remote, blockers).</p></section>
      <section class="panel"><h3>Market coverage <span class="quiet">how much of what listings ask for your resume covers</span></h3>
        <div class="mid-num" style="font-size:44px">${m.score}%</div>
        ${m.raise.length?`<p class="co">Biggest lifts: ${m.raise.map(r=>`<b>${esc(r.skill)}</b> +${r.gain}%`).join(' · ')}</p>`:''}
        ${hist.length>1?`<div class="chartbox" style="height:190px"><canvas id="cHist"></canvas></div><p class="legend-note">${hist.length} daily snapshots, recorded on every scan.</p>`:'<p class="co">The trend appears after the second day of scanning. One snapshot is stored per day.</p>'}</section>
      <section class="panel"><h3>Skills that come as a pair <span class="quiet">required together</span></h3>
        ${tbl(d.bundles.map(b=>`<tr><td><b>${esc(b.a)}</b> + <b>${esc(b.b)}</b></td><td>${b.jobs}</td><td class="co">${b.have_both?'you have both':b.missing.length?'missing '+esc(b.missing.join(', ')):'partly'}</td></tr>`).join('')||'<tr><td colspan="3" class="co">Not enough scored listings yet.</td></tr>',['Pair','Listings',''])}</section>
      <section class="panel"><h3>Employers worth watching <span class="quiet">most good-fit roles</span></h3>
        ${tbl(d.employers.map(e=>`<tr><td><b>${esc(e.company)}</b></td><td>${e.good} of ${e.roles}</td><td>fit ${e.avg_fit}</td><td class="co">best odds ${e.best_odds}%${e.recent?` · ${e.recent} new`:''}</td></tr>`).join('')||'<tr><td colspan="4" class="co">No employer has a good-fit role yet.</td></tr>',['Employer','Good fit','Avg','']) }</section>
      ${payL.length?panel('cPayL','Local pay by category','median stated, TT$ / month',Math.max(160,payL.length*34+50)):''}
      ${payR.length?panel('cPayR','Remote pay by category','median stated, US$ / month',Math.max(160,payR.length*34+50)):''}
      ${panel('cExp','Experience listings ask for',`you have ${ex.your_years||0} years · ${ex.levels.map(l=>l.count+' '+l.level).join(', ')}`,230)}
      ${panel('cOpen','How long roles stay open',to.n?`median ${to.median} days · ${to.n} listings state both dates`:'no listing states both dates yet',230)}
    </div>`;
}

function drawMarketCharts(d){
  const P=palette();
  const ds=(label,data,color,extra={})=>Object.assign({label,data,backgroundColor:color,borderWidth:0,borderRadius:1},extra);
  const pts=(mode,blocked)=>d.map.filter(p=>p.mode===mode&&p.blocked===blocked).map(p=>({x:p.fit,y:p.odds,...p}));
  const col={local:P.ink,remote:P.mute,abroad:P.faint};
  const sets=['local','remote','abroad'].map(m=>({label:{local:'Local',remote:'Remote',abroad:'On-site abroad'}[m],data:pts(m,false),backgroundColor:col[m],pointRadius:4,pointHoverRadius:7}));
  sets.push({label:'Blocked',data:d.map.filter(p=>p.blocked).map(p=>({x:p.fit,y:p.odds,...p})),backgroundColor:'transparent',borderColor:P.gap,borderWidth:1.5,pointRadius:4,pointStyle:'crossRot'});
  mk('cMap',{type:'scatter',data:{datasets:sets},options:{
    onClick:(e,els,chart)=>{ if(!els.length) return; const p=chart.data.datasets[els[0].datasetIndex].data[els[0].index]; if(p&&p.job_id) openJob(p.job_id); },
    onHover:(e,els)=>{ e.native.target.style.cursor=els.length?'pointer':'default'; },
    scales:{x:{min:30,max:Math.min(100,Math.ceil(Math.max(60,...d.map.map(p=>p.fit))/10)*10+5),title:{display:true,text:'Fit'}},y:{min:0,max:Math.min(100,Math.ceil(Math.max(20,...d.map.map(p=>p.odds))/10)*10+10),title:{display:true,text:'Odds %'}}},
    plugins:{tooltip:{callbacks:{label:c=>`${c.raw.title} · ${c.raw.company} (fit ${c.raw.x}, odds ${c.raw.y})`}}}}});
  if((d.history||[]).length>1){
    const h=d.history;
    mk('cHist',{type:'line',data:{labels:h.map(x=>x.day.slice(5)),datasets:[{label:'Coverage %',data:h.map(x=>x.coverage),borderColor:P.ink,tension:.3,borderWidth:2,pointRadius:2},{label:'Good-fit listings',data:h.map(x=>x.good),borderColor:P.mute,tension:.3,borderWidth:2,pointRadius:2,yAxisID:'y1'}]},
      options:{scales:{x:{grid:{display:false}},y:{beginAtZero:true,max:100},y1:{position:'right',beginAtZero:true,grid:{display:false},ticks:{precision:0}}}}});
  }
  const hbar=(id,rows,color)=>mk(id,{type:'bar',data:{labels:rows.map(r=>`${r.category} (${r.n})`),datasets:[{data:rows.map(r=>r.median),backgroundColor:color,borderWidth:0}]},options:{indexAxis:'y',plugins:{legend:{display:false},tooltip:{callbacks:{label:c=>`median ${c.raw.toLocaleString()} · top ${rows[c.dataIndex].top.toLocaleString()}`}}},scales:{x:{beginAtZero:true},y:{grid:{display:false}}}}});
  const pc=d.pay_by_category||{}; if((pc.local||[]).length) hbar('cPayL',pc.local,P.ink); if((pc.remote||[]).length) hbar('cPayR',pc.remote,P.mute);
  const ex=d.experience, yr=ex.your_years||0, mine=yr<=1?1:yr<=3?2:yr<=5?3:yr<=8?4:5;
  mk('cExp',{type:'bar',data:{labels:ex.bins.map(b=>b.label),datasets:[{data:ex.bins.map(b=>b.count),backgroundColor:ex.bins.map((b,i)=>i===mine?P.ink:P.faint),borderWidth:0}]},options:{plugins:{legend:{display:false},tooltip:{callbacks:{afterLabel:c=>c.dataIndex===mine?'← where you are':''}}},scales:{x:{grid:{display:false}},y:{beginAtZero:true,ticks:{precision:0}}}}});
  const to=d.time_open;
  mk('cOpen',{type:'bar',data:{labels:to.bins.map(b=>b.label+' d'),datasets:[{data:to.bins.map(b=>b.count),backgroundColor:P.mute,borderWidth:0}]},options:{plugins:{legend:{display:false}},scales:{x:{grid:{display:false}},y:{beginAtZero:true,ticks:{precision:0}}}}});
}

function drawInsightCharts(){
  const d=AN, P=palette();
  drawMarketCharts(d);
  const bar=(id,labels,datasets,opt={})=>mk(id,{type:'bar',data:{labels,datasets},options:Object.assign({scales:{x:{grid:{display:false},stacked:!!opt.stacked},y:{beginAtZero:true,stacked:!!opt.stacked,ticks:{precision:0}}}},opt.options||{})});
  const ds=(label,data,color,extra={})=>Object.assign({label,data,backgroundColor:color,borderWidth:0,borderRadius:1},extra);

  bar('cFit',d.fit_hist.map(b=>b.label),[ds('Local',d.fit_hist.map(b=>b.local),P.ink),ds('Remote',d.fit_hist.map(b=>b.remote),P.mute),ds('Abroad (on-site)',d.fit_hist.map(b=>b.abroad),P.faint)],{stacked:true});

  mk('cOdds',{type:'doughnut',data:{labels:d.verdicts.map(v=>v.verdict),datasets:[{data:d.verdicts.map(v=>v.count),backgroundColor:[P.ink,P.mute,P.faint,P.gap+'99'],borderColor:P.dark?'#161615':'#e6e6e4',borderWidth:2}]},options:{cutout:'62%',plugins:{legend:{position:'right'}}}});

  // skills vs demand (horizontal, coloured by whether you have it)
  const ms=d.market_skills.slice(0,18), col={have:P.ink,related:P.mute,missing:P.gap};
  mk('cSkills',{type:'bar',data:{labels:ms.map(s=>s.skill),datasets:[{data:ms.map(s=>s.jobs),backgroundColor:ms.map(s=>col[s.status]),borderWidth:0}]},
    options:{indexAxis:'y',plugins:{legend:{display:false},tooltip:{callbacks:{label:c=>{const s=ms[c.dataIndex];return `${s.jobs} listings · ${s.required} require it · ${s.status==='have'?'you have it'+(s.years?` (${s.years}y)`:''):s.status==='related'?'adjacent skill':'not on your resume'}`;}}}},scales:{x:{beginAtZero:true,ticks:{precision:0}},y:{grid:{display:false}}}}});

  const cc=d.category_coverage;
  mk('cRadar',{type:'radar',data:{labels:cc.map(c=>c.category),datasets:[{label:'Your coverage %',data:cc.map(c=>c.coverage),backgroundColor:P.dark?'rgba(236,236,232,.18)':'rgba(28,28,28,.14)',borderColor:P.ink,pointBackgroundColor:P.ink,borderWidth:2}]},
    options:{scales:{r:{min:0,max:100,ticks:{stepSize:25,backdropColor:'transparent'},grid:{color:P.rule},angleLines:{color:P.rule},pointLabels:{color:P.ink,font:{size:10}}}},plugins:{legend:{display:false}}}});

  const st=d.strengths;
  mk('cStrength',{type:'bar',data:{labels:st.map(s=>s.skill+(s.years?` · ${s.years}y`:'')),datasets:[{data:st.map(s=>s.jobs),backgroundColor:P.ink,borderWidth:0}]},options:{indexAxis:'y',plugins:{legend:{display:false}},scales:{x:{beginAtZero:true,ticks:{precision:0}},y:{grid:{display:false}}}}});

  const mc=d.mode_compare, mlab={local:'Local',remote:'Remote',abroad:'On-site abroad'};
  bar('cMode',mc.map(m=>`${mlab[m.mode]} (${m.count})`),[ds('Avg fit',mc.map(m=>m.avg_fit),P.ink),ds('Avg odds',mc.map(m=>m.avg_odds),P.mute),ds('Interview chance %',mc.map(m=>m.avg_chance),P.faint)]);

  const sc=d.remote_scopes, slab={worldwide:'Worldwide',americas:'Americas',unknown:'Not stated',us_only:'US only',eu_only:'EU/UK only',canada_only:'Canada only'};
  mk('cScope',{type:'doughnut',data:{labels:sc.map(s=>slab[s.scope]),datasets:[{data:sc.map(s=>s.count),backgroundColor:sc.map(s=>s.scope==='worldwide'?P.ink:s.scope==='americas'?P.faint:s.scope==='unknown'?P.mute:P.gap),borderColor:P.dark?'#161615':'#e6e6e4',borderWidth:2}]},options:{cutout:'58%',plugins:{legend:{position:'right'}}}});

  mk('cTime',{type:'line',data:{labels:d.timeline.map(t=>t.date.slice(5)),datasets:[{label:'All posted',data:d.timeline.map(t=>t.local+t.remote),borderColor:P.mute,backgroundColor:P.faint+'55',fill:true,tension:.3,pointRadius:0,borderWidth:2},{label:'Good fit',data:d.timeline.map(t=>t.good),borderColor:P.ink,tension:.3,pointRadius:0,borderWidth:2}]},options:{scales:{x:{grid:{display:false},ticks:{maxTicksLimit:8}},y:{beginAtZero:true,ticks:{precision:0}}}}});
  bar('cClose',d.closing.map(c=>c.date.slice(5)),[ds('Good fit',d.closing.map(c=>c.good),P.ink),ds('Other',d.closing.map(c=>c.count-c.good),P.faint)],{stacked:true});

  const rg=d.regions;
  mk('cRegion',{type:'bar',data:{labels:rg.map(r=>r.region),datasets:[{type:'bar',label:'Listings',data:rg.map(r=>r.count),backgroundColor:P.ink,borderWidth:0,yAxisID:'y'},{type:'line',label:'Avg fit',data:rg.map(r=>r.avg_fit),borderColor:P.gap,pointBackgroundColor:P.gap,borderWidth:2,yAxisID:'y1'}]},options:{scales:{x:{grid:{display:false},ticks:{maxRotation:40,minRotation:40,font:{size:10}}},y:{beginAtZero:true,ticks:{precision:0}},y1:{position:'right',min:0,max:100,grid:{display:false}}}}});
  const ct=d.categories;
  mk('cCat',{type:'bar',data:{labels:ct.map(c=>c.category),datasets:[ds('Listings',ct.map(c=>c.count),P.faint),ds('Good fit',ct.map(c=>c.good),P.ink)]},options:{indexAxis:'y',scales:{x:{beginAtZero:true,ticks:{precision:0}},y:{grid:{display:false}}}}});
  const sr=d.sources;
  bar('cSrc',sr.map(s=>s.source),[ds('Listings',sr.map(s=>s.count),P.faint),ds('Good fit',sr.map(s=>s.good),P.ink)],{options:{scales:{x:{grid:{display:false},ticks:{maxRotation:45,minRotation:45,font:{size:10}}},y:{beginAtZero:true,ticks:{precision:0}}}}});

  const sl=d.salary;
  mk('cSal',{type:'bar',data:{labels:sl.local.hist.map(b=>b.label),datasets:[{label:`Local (${sl.local.unit})`,data:sl.local.hist.map(b=>b.count),backgroundColor:P.ink,borderWidth:0},{label:`Remote (${sl.remote.unit}) — bins of 2k`,data:sl.remote.hist.map(b=>b.count),backgroundColor:P.mute,borderWidth:0}]},options:{scales:{x:{grid:{display:false}},y:{beginAtZero:true,ticks:{precision:0}}},plugins:{tooltip:{callbacks:{title:items=>items.length?`${items[0].dataset.label}: ${(items[0].datasetIndex?sl.remote.hist:sl.local.hist)[items[0].dataIndex].label}`:''}}}}});

  const fs=d.funnel.stages;
  mk('cFunnel',{type:'bar',data:{labels:fs.map(s=>s.stage),datasets:[{data:fs.map(s=>s.count),backgroundColor:fs.map(s=>s.stage==='Rejected'?P.gap:s.stage==='Offer'?P.ok:P.ink),borderWidth:0}]},options:{indexAxis:'y',plugins:{legend:{display:false}},scales:{x:{beginAtZero:true,ticks:{precision:0}},y:{grid:{display:false}}}}});
  bar('cScans',(d.scans||[]).map(s=>(s.started_at||'').slice(5,10)),[ds('Jobs kept',(d.scans||[]).map(s=>s.kept),P.ink)],{options:{plugins:{legend:{display:false}},scales:{x:{grid:{display:false}},y:{beginAtZero:true,ticks:{precision:0}}}}});
  bar('cWeek',d.funnel.weekly.map(w=>w.week.slice(5)),[ds('Applications',d.funnel.weekly.map(w=>w.count),P.ink)],{options:{plugins:{legend:{display:false}},scales:{x:{grid:{display:false}},y:{beginAtZero:true,ticks:{precision:0}}}}});
}
// charts read theme colours when drawn: redraw when the theme flips
document.addEventListener('themechange',()=>{ if(AN) drawInsightCharts(); });

Object.assign(PAGE_HOOKS,{
  init:()=>loadInsights(),
  refresh:()=>loadInsights(),
});
