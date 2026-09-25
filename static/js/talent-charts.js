/* Privacy-safe views only: the server owns every value and denominator. */
(function(global){
  'use strict';
  const esc=v=>String(v??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  // Stable per-index colours. Learning Style keeps its semantic mapping: the eight
  // styles take the first eight colours and Unassigned always takes the neutral last one.
  const colors=['#237c83','#695ba5','#bc7135','#357449','#a34e75','#417fb2','#807134','#637581','#969ba5'];
  // Neutral, value-free copy (M18a): a non-visible cell is simply unavailable. The
  // only explanatory privacy sentence is the Classification-cohort message owned by
  // the backend reason code `classification_cohort_protected`.
  const protectedText='Unavailable';
  // A structural absence (no authoritative population yet, for example a newly opened
  // Evaluation Period) is NOT a privacy decision and NOT zero.
  const noDataText='No data yet';
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

  // ---- Chart-type semantics (Part 2 D) --------------------------------------
  // The selector switches between genuinely different VISUALIZATION TYPES, never
  // whether percentages are shown: every type keeps its exact count/percentage as
  // text (bar label, legend row, trend legend) and in the accessible table.
  //   * bar      - length-encoded comparison; the only type for ordinal or high-cardinality data.
  //   * doughnut - part-to-whole of a full public partition of a small category set.
  //   * trend    - ordered time series only (line with honest gaps).
  // A pie is a doughnut without a centre (same reading, same legend), so it is not a
  // separate mode. A "percentage" bar was the same picture as the count bar, so it is
  // gone. Circular types are never offered for time series, for more than
  // MAX_CIRCULAR_CATEGORIES categories, for ordinal Rubric levels, or for Learning Style
  // (eight styles plus Unassigned is nine categories: not legible as slices).
  const MAX_CIRCULAR_CATEGORIES=8;
  const CIRCULAR_FAMILIES=['classification','completion'];
  const SERIES_FAMILIES=['trend','series'];
  const RATE_FAMILIES=['trend','series','comparison'];
  const MODE_LABELS={bar:'Bar',doughnut:'Doughnut',trend:'Trend'};
  // Explicit user selections survive a data refetch re-render (presentation state only).
  const chosen=new Map();

  function sanitize(projection){
    if(!projection||!['visible','empty'].includes(projection.state))return [];
    return (projection.buckets||projection.levels||[]).map(b=>({label:String(b.label||b.key||''),state:b.state,
      count:b.state==='visible'&&Number.isFinite(b.count)?b.count:null,
      percentage:b.state==='visible'&&Number.isFinite(b.percentage)?b.percentage:null}));
  }
  const valueOf=r=>r.state!=='visible'?null:(r.percentage!==null&&r.percentage!==undefined?r.percentage:(r.count??null));
  function modesForRows(rows,family){
    if(SERIES_FAMILIES.includes(family))return rows.filter(r=>valueOf(r)!==null).length>=2?['trend','bar']:['bar'];
    const full=rows.length>0&&rows.every(r=>r.state==='visible'&&r.count!==null&&r.percentage!==null);
    const circular=full&&rows.length>=2&&rows.length<=MAX_CIRCULAR_CATEGORIES&&Math.abs(rows.reduce((s,r)=>s+r.percentage,0)-100)<.2;
    return CIRCULAR_FAMILIES.includes(family)&&circular?['bar','doughnut']:['bar'];
  }
  const modes=(projection,family)=>modesForRows(Array.isArray(projection)?projection:sanitize(projection),family);
  const stateText=r=>r.state==='no_data'?noDataText:protectedText;
  const rowText=(r,family)=>{
    if(RATE_FAMILIES.includes(family)&&r.percentage!==null&&r.percentage!==undefined)
      return `${esc(r.percentage)}%${r.denominator!=null?` (${esc(r.count)} of ${esc(r.denominator)})`:r.count!=null?` (${esc(r.count)})`:''}`;
    return `${esc(r.count)}${r.percentage===null||r.percentage===undefined?'':` (${esc(r.percentage)}%)`}`;
  };
  function trendVisual(rows){
    const values=rows.map(valueOf),shown=values.filter(v=>v!==null);
    const pct=rows.every(r=>r.state!=='visible'||(r.percentage!==null&&r.percentage!==undefined));
    const max=pct?100:Math.max(1,...shown);
    const x=i=>10+i*280/Math.max(1,rows.length-1),y=v=>110-Math.max(0,Math.min(100,v/max*100));
    // A non-visible point breaks the line (an honest gap) and carries no coordinate at all.
    // A backend-governed pair that is not comparable ALSO breaks the line between two visible
    // points (row.link===false): TIS never connects or implies continuity across it. Each
    // point keeps its own dot. row.link===null means no governance was supplied (unchanged).
    const runs=[];let run=[];
    values.forEach((v,i)=>{if(v===null){if(run.length)runs.push(run);run=[];}else{if(run.length&&rows[i].link===false){runs.push(run);run=[];}run.push([x(i),y(v)]);}});
    if(run.length)runs.push(run);
    const lines=runs.filter(r=>r.length>1).map(r=>`<polyline points="${r.map(p=>p.join(',')).join(' ')}" fill="none" stroke="currentColor" stroke-width="2"/>`).join('');
    const dots=runs.flat().map(p=>`<circle cx="${p[0]}" cy="${p[1]}" r="3.5" fill="currentColor"/>`).join('');
    const gaps=values.map((v,i)=>v===null?`<line class="tp-trend-gap" x1="${x(i)}" x2="${x(i)}" y1="12" y2="110" stroke="currentColor" stroke-width="1" stroke-dasharray="3 4"/>`:'').join('');
    const broken=i=>i>0&&rows[i].link===false&&values[i]!==null&&values[i-1]!==null;
    const breaks=values.map((v,i)=>broken(i)?`<line class="tp-trend-break" x1="${(x(i-1)+x(i))/2}" x2="${(x(i-1)+x(i))/2}" y1="12" y2="110" stroke="currentColor" stroke-width="1" stroke-dasharray="1 5"/>`:'').join('');
    return `<svg class="tp-trend" viewBox="0 0 300 120" aria-hidden="true" focusable="false"><line x1="6" x2="294" y1="110" y2="110" stroke="currentColor" stroke-opacity=".25"/>${gaps}${breaks}${lines}${dots}</svg><ol class="tp-chart-legend tp-trend-legend">${rows.map((r,i)=>`<li>${esc(r.label)}: ${r.state==='visible'?rowText(r,'series'):stateText(r)}${broken(i)?' (not connected: periods are not comparable)':''}</li>`).join('')}</ol>`;
  }
  function visual(rows,mode,family='classification'){
    if(mode==='doughnut'){
      let start=0;const stops=rows.map((r,i)=>{const end=start+r.percentage;const s=`${colors[i%colors.length]} ${start}% ${end}%`;start=end;return s;});
      return `<div class="tp-chart-round is-doughnut" aria-hidden="true" style="background:conic-gradient(${stops.join(',')})"></div><ul class="tp-chart-legend">${rows.map((r,i)=>`<li><i style="background:${colors[i%colors.length]}" aria-hidden="true"></i>${esc(r.label)}: ${esc(r.count)} (${esc(r.percentage)}%)</li>`).join('')}</ul>`;
    }
    if(mode==='trend')return trendVisual(rows);
    const rate=RATE_FAMILIES.includes(family);
    const max=Math.max(1,...rows.map(r=>r.count||0));
    return `<div class="tp-chart-bars">${rows.map((r,i)=>{
      if(r.state!=='visible'||valueOf(r)===null)return `<div class="tp-chart-row is-unavailable"><span>${esc(r.label)}</span><span class="tp-chart-unavailable">${stateText(r)}</span></div>`;
      const width=rate&&r.percentage!==null&&r.percentage!==undefined?r.percentage:(r.count===null?null:r.count/max*100);
      return `<div class="tp-chart-row"><span>${esc(r.label)}</span>${width===null?'':`<span class="tp-chart-track" aria-hidden="true"><i style="width:${Math.max(0,Math.min(100,width))}%;background:${colors[i%colors.length]}"></i></span>`}<strong>${rowText(r,family)}</strong></div>`;
    }).join('')}</div>`;
  }
  function build(title,rows,family,o){
    const available=modesForRows(rows,family),key=`${family}|${title}|${o.surface||''}`;
    const mode=[o.mode,chosen.get(key),o.defaultMode,available.includes('trend')?'trend':'bar'].find(m=>m&&available.includes(m))||'bar';
    const hasDenominator=rows.some(r=>r.denominator!=null);
    const series=RATE_FAMILIES.includes(family);
    // One available type means nothing to switch: no control is rendered (no duplicate buttons).
    const control=o.switch!==false&&available.length>1?`<div class="tp-chart-switch" role="group" aria-label="${esc(title)} chart type">${available.map(m=>`<button type="button" data-chart-mode="${m}" aria-pressed="${m===mode}">${esc(MODE_LABELS[m]||m)}</button>`).join('')}</div>`:'';
    const cellText=(r,name)=>r[name]===null||r[name]===undefined?(r.state==='visible'?(series?'—':protectedText):stateText(r)):(name==='percentage'?esc(r[name])+'%':esc(r[name]));
    // Keep only sanitized public values in switchable markup. No serialized API payload.
    return `<section class="tp-card tp-chart" data-chart-family="${esc(family)}" data-chart-key="${esc(key)}"><div class="tp-chart-head"><h3>${esc(title)}</h3>${control}</div><div data-chart-visual>${visual(rows,mode,family)}</div>${family==='classification'&&rows.some(r=>r.state!=='visible')?`<p class="tp-note tp-chart-note" data-chart-withheld-note>${esc(withheldNote)}</p>`:''}<details><summary>Exact values and accessible table</summary><div class="tp-table-wrap"><table><caption>${esc(title)}</caption><thead><tr><th scope="col">Category</th><th scope="col">Count</th><th scope="col">Percentage</th>${hasDenominator?'<th scope="col">Total</th>':''}</tr></thead><tbody>${rows.map(r=>`<tr data-chart-row data-state="${esc(r.state)}"${r.link===false?' data-link="broken"':r.link===true?' data-link="comparable"':''}><th scope="row">${esc(r.label)}</th><td>${cellText(r,'count')}</td><td>${cellText(r,'percentage')}</td>${hasDenominator?`<td>${r.denominator==null?(r.state==='visible'?'—':stateText(r)):esc(r.denominator)}</td>`:''}</tr>`).join('')}</tbody></table></div></details></section>`;
  }
  // chart(title, projection, family, mode | {mode, defaultMode, switch, surface})
  function chart(title,projection,family='classification',arg){
    const o=typeof arg==='string'?{mode:arg}:(arg||{});
    const rows=sanitize(projection);
    if(!rows.length){
      const known=messages[projection?.reason_code];
      const withheld=family==='classification'&&['suppressed','coarsened'].includes(projection?.state);
      const text=known||(withheld?withheldWhole:['empty','no_data'].includes(projection?.state)?'No data for this selection.':'This summary is not available for this selection.');
      return `<section class="tp-card tp-chart is-${known?'protected':['empty','no_data'].includes(projection?.state)?'empty':'unavailable'}"><div class="tp-chart-head"><h3>${esc(title)}</h3></div><p class="tp-empty" data-chart-state="${known?'protected':'unavailable'}">${esc(text)}</p></section>`;
    }
    return build(title,rows,family,o);
  }
  // Time series (Progress Over Time): rows are {label,state,count,percentage,denominator}
  // built from backend cells. A row whose state is not `visible` never receives a value.
  // o.comparisons is the backend's adjacent-Period comparability list ({evaluation_period_ids:
  // [earlier,later], state}); each point carries its Period `id`. The backend is the only
  // authority: this module never derives comparability. When o.comparisons is supplied, a pair
  // connects only when its record says `comparable`; a missing or any other record does not
  // connect. When it is not supplied, no governance exists and behaviour is unchanged.
  function series(title,points,o={}){
    const governed=Array.isArray(o.comparisons);
    const linkOf=i=>{
      if(!governed||i===0)return null;
      const c=o.comparisons.find(c=>Array.isArray(c?.evaluation_period_ids)&&c.evaluation_period_ids[0]===points[i-1].id&&c.evaluation_period_ids[1]===points[i].id);
      return !!c&&c.state==='comparable';
    };
    const rows=(points||[]).map((p,i)=>{
      const v=p.state==='visible';
      return {label:String(p.label||''),state:p.state||'no_data',link:linkOf(i),
        count:v&&Number.isFinite(p.count)?p.count:null,
        percentage:v&&Number.isFinite(p.percentage)?p.percentage:null,
        denominator:v&&Number.isFinite(p.denominator)?p.denominator:null};
    });
    if(!rows.length)return `<section class="tp-card tp-chart is-empty"><div class="tp-chart-head"><h3>${esc(title)}</h3></div><p class="tp-empty" data-chart-state="unavailable">No data for this selection.</p></section>`;
    return build(title,rows,'series',o);
  }
  // Comparison of one rate across selected groups; the group value is the backend's
  // own rate for that group, never an average of other groups.
  function comparison(title,groups,o={}){
    const rows=(groups||[]).map(g=>{
      const v=g.state==='visible';
      return {label:String(g.label||''),state:g.state||'restricted',
        count:v&&Number.isFinite(g.count)?g.count:null,
        percentage:v&&Number.isFinite(g.percentage)?g.percentage:null,
        denominator:v&&Number.isFinite(g.denominator)?g.denominator:null};
    });
    if(!rows.length)return '';
    return build(title,rows,'comparison',{...o,switch:false});
  }
  function bind(root){
    root.addEventListener('click',event=>{
      const button=event.target.closest('[data-chart-mode]');if(!button)return;
      const host=button.closest('[data-chart-family]');if(!host)return;
      const rows=Array.from(host.querySelectorAll('[data-chart-row]')).map(tr=>{
        const visible=tr.dataset.state==='visible',cells=tr.children,num=i=>visible&&cells[i]&&/^-?\d+(\.\d+)?%?$/.test(cells[i].textContent.trim())?Number(cells[i].textContent.trim().replace('%','')):null;
        return {label:cells[0].textContent,state:tr.dataset.state,count:num(1),percentage:visible&&cells[2].textContent.endsWith('%')?num(2):null,denominator:cells[3]?num(3):null,link:tr.dataset.link==='comparable'?true:tr.dataset.link==='broken'?false:null};
      });
      const family=host.dataset?.chartFamily||'classification',mode=button.dataset.chartMode;
      host.querySelector('[data-chart-visual]').innerHTML=visual(rows,mode,family);
      host.querySelectorAll('[data-chart-mode]').forEach(b=>b.setAttribute('aria-pressed',String(b===button)));
      if(host.dataset?.chartKey)chosen.set(host.dataset.chartKey,mode);
      // A deliberate switch is not an entrance: stop any Overview entrance animation.
      host.closest?.('.tp-motion-enter')?.classList?.remove('tp-motion-enter');
    });
  }
  const api={chart,series,comparison,sanitize,modes,bind,esc,MAX_CIRCULAR_CATEGORIES,MODE_LABELS};
  if(typeof module!=='undefined')module.exports=api;
  global.TalentCharts=api;
})(typeof window!=='undefined'?window:globalThis);
