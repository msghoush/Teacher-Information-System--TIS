/* Privacy-safe views only: the server owns every value and denominator. */
(function(global){
  'use strict';
  const esc=v=>String(v??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  const colors=['#237c83','#695ba5','#bc7135','#357449','#a34e75','#417fb2','#807134','#637581','#969ba5'];
  // Neutral, value-free copy (M18a): a non-visible cell is simply unavailable. The
  // only explanatory privacy sentence is the Classification-cohort message owned by
  // the backend reason code `classification_cohort_protected`.
  const protectedText='Unavailable';
  const messages={
    classification_cohort_protected:'Learning Style summary is unavailable for this Classification filter because the cohort is protected for privacy.',
    permission_required:'Learning Style requires permission to view Students.',
    incompatible_frameworks:'Choose one compatible Program and assessment framework to view results.'
  };
  // Classification is a privacy-closed aggregate (P4, cohort floor and complementary
  // suppression are owned by the backend). One uniform, value-free sentence explains
  // why a group reads Unavailable. It is derived only from cell STATES, never names
  // which cells were primary or complementary suppressed and never states a threshold.
  const withheldNote='Groups marked Unavailable are withheld to protect individual Students. A broader selection may allow more groups to be shown.';
  const withheldWhole='This summary is not available for this selection: Classification is withheld to protect individual Students. A broader selection may allow it to be shown.';
  function sanitize(projection){
    if(!projection||!['visible','empty'].includes(projection.state))return [];
    return (projection.buckets||projection.levels||[]).map(b=>({label:String(b.label||b.key||''),state:b.state,
      count:b.state==='visible'&&Number.isFinite(b.count)?b.count:null,
      percentage:b.state==='visible'&&Number.isFinite(b.percentage)?b.percentage:null}));
  }
  function modes(projection,family){
    const rows=sanitize(projection), full=rows.length&&rows.every(r=>r.state==='visible'&&r.count!==null&&r.percentage!==null);
    const circular=full&&Math.abs(rows.reduce((s,r)=>s+r.percentage,0)-100)<.2;
    return ['bar',...(family==='trend'&&full&&rows.length>1?['trend']:[]),...(family!=='trend'?['percentage']:[]),...(circular&&family==='learning-style'?['pie','doughnut']:circular&&family==='classification'?['doughnut']:[])];
  }
  function visual(rows,mode){
    if(mode==='pie'||mode==='doughnut'){
      let start=0;const stops=rows.map((r,i)=>{const end=start+r.percentage;const s=`${colors[i%colors.length]} ${start}% ${end}%`;start=end;return s;});
      return `<div class="tp-chart-round ${mode==='doughnut'?'is-doughnut':''}" aria-hidden="true" style="background:conic-gradient(${stops.join(',')})"></div><ul class="tp-chart-legend">${rows.map((r,i)=>`<li><i style="background:${colors[i%colors.length]}" aria-hidden="true"></i>${esc(r.label)}: ${esc(r.count)} (${esc(r.percentage)}%)</li>`).join('')}</ul>`;
    }
    if(mode==='trend'){
      const points=rows.map((r,i)=>`${10+i*280/Math.max(1,rows.length-1)},${110-r.percentage}`);
      return `<svg class="tp-trend" viewBox="0 0 300 120" aria-hidden="true"><polyline points="${points.join(' ')}" fill="none" stroke="currentColor" stroke-width="2"/>${points.map(p=>{const [x,y]=p.split(',');return `<circle cx="${x}" cy="${y}" r="3" fill="currentColor"/>`;}).join('')}</svg>`;
    }
    const max=Math.max(1,...rows.map(r=>r.count||0));
    return `<div class="tp-chart-bars">${rows.map((r,i)=>{
      if(r.state!=='visible'||r.count===null)return `<div class="tp-chart-row is-unavailable"><span>${esc(r.label)}</span><span class="tp-chart-unavailable">${protectedText}</span></div>`;
      const width=mode==='percentage'?r.percentage:r.count/max*100;
      return `<div class="tp-chart-row"><span>${esc(r.label)}</span>${width===null?'':`<span class="tp-chart-track" aria-hidden="true"><i style="width:${Math.max(0,Math.min(100,width))}%;background:${colors[i%colors.length]}"></i></span>`}<strong>${esc(r.count)}${r.percentage===null?'':` (${esc(r.percentage)}%)`}</strong></div>`;
    }).join('')}</div>`;
  }
  function chart(title,projection,family='classification',mode='bar'){
    const rows=sanitize(projection);
    if(!rows.length){
      const known=messages[projection?.reason_code];
      const withheld=family==='classification'&&['suppressed','coarsened'].includes(projection?.state);
      const text=known||(withheld?withheldWhole:['empty','no_data'].includes(projection?.state)?'No data for this selection.':'This summary is not available for this selection.');
      return `<section class="tp-card tp-chart is-${known?'protected':['empty','no_data'].includes(projection?.state)?'empty':'unavailable'}"><div class="tp-chart-head"><h3>${esc(title)}</h3></div><p class="tp-empty" data-chart-state="${known?'protected':'unavailable'}">${esc(text)}</p></section>`;
    }
    const available=modes(projection,family);if(!available.includes(mode))mode='bar';
    // Keep only sanitized public values in switchable markup. No serialized API payload.
    return `<section class="tp-card tp-chart" data-chart-family="${esc(family)}"><div class="tp-chart-head"><h3>${esc(title)}</h3><div class="tp-chart-switch" role="group" aria-label="${esc(title)} chart type">${available.map(m=>`<button type="button" data-chart-mode="${m}" aria-pressed="${m===mode}">${esc(m[0].toUpperCase()+m.slice(1))}</button>`).join('')}</div></div><div data-chart-visual>${visual(rows,mode)}</div>${family==='classification'&&rows.some(r=>r.state!=='visible')?`<p class="tp-note tp-chart-note" data-chart-withheld-note>${esc(withheldNote)}</p>`:''}<details><summary>Exact values and accessible table</summary><div class="tp-table-wrap"><table><caption>${esc(title)}</caption><thead><tr><th scope="col">Category</th><th scope="col">Count</th><th scope="col">Percentage</th></tr></thead><tbody>${rows.map(r=>`<tr data-chart-row data-state="${esc(r.state)}"><th scope="row">${esc(r.label)}</th><td>${r.count===null?protectedText:esc(r.count)}</td><td>${r.percentage===null?(r.state==='visible'?'Unavailable':protectedText):esc(r.percentage)+'%'}</td></tr>`).join('')}</tbody></table></div></details></section>`;
  }
  function bind(root){
    root.addEventListener('click',event=>{
      const button=event.target.closest('[data-chart-mode]');if(!button)return;
      const host=button.closest('[data-chart-family]');if(!host)return;
      const rows=Array.from(host.querySelectorAll('[data-chart-row]')).map(tr=>({label:tr.children[0].textContent,state:tr.dataset.state,count:tr.dataset.state==='visible'?Number(tr.children[1].textContent):null,percentage:tr.dataset.state==='visible'&&tr.children[2].textContent.endsWith('%')?Number(tr.children[2].textContent.slice(0,-1)):null}));
      host.querySelector('[data-chart-visual]').innerHTML=visual(rows,button.dataset.chartMode);
      host.querySelectorAll('[data-chart-mode]').forEach(b=>b.setAttribute('aria-pressed',String(b===button)));
    });
  }
  const api={chart,sanitize,modes,bind,esc};
  if(typeof module!=='undefined')module.exports=api;
  global.TalentCharts=api;
})(typeof window!=='undefined'?window:globalThis);
