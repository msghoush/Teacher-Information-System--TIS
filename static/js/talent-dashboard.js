(function(global){
  'use strict';
  const charts=global.TalentCharts||(typeof require==='function'?require('./talent-charts.js'):null),{esc,chart}=charts;
  const fields=[['branch','branch_id','Branch'],['grade','grade_level','Grade'],['section','section_id','Section'],['program','program_id','Program'],['period','period_id','Evaluation Period']];
  const classifications=['Needs Improvement','Developing','Meets Expectations','Advanced','Exceptional'];
  function select(name,label,options,params,all=true){return `<label>${esc(label)}<select name="${name}">${all?`<option value="">All ${esc(label)}${label==='Classification'?'s':''}</option>`:''}${options.map(o=>`<option value="${esc(o.id)}" ${String(params.get(name)||'')===String(o.id)?'selected':''}>${esc(o.label)}</option>`).join('')}</select></label>`;}
  const branchOptions=(data,dim,ceiling)=>(data.options?.[dim]||[]).filter(o=>dim!=='branch'||!ceiling||String(o.id)===String(ceiling));
  function filters(data,params,ceiling){
    return `<form class="tp-dashboard-filters" data-dashboard-filters aria-label="Analysis context"><h3>Analysis context</h3><div class="tp-filter-grid">${fields.map(([dim,key,label])=>select(key,label,branchOptions(data,dim,ceiling),params,dim!=='branch'||!ceiling)).join('')}${select('classification','Classification',classifications.map(v=>({id:v,label:v})),params)}${select('competency_id','Competency',data.rubric?.competencies||[],params)}${select('rubric_id','Rubric Indicator',data.rubric?.indicators||[],params)}</div><div class="tp-filter-actions"><button type="submit" class="tp-primary">Refresh analysis</button><button type="button" class="tp-secondary" data-dashboard-clear>Clear analysis filters</button></div></form>`;
  }
  const MAX_COMPARISON_GROUPS=6;
  // Selected Comparisons: ONE section holds the selector (dimension and groups), the
  // up-to-six constraint and the resulting comparison charts, in that order.
  function comparisonControls(data,params,ceiling){
    const axis=params.get('compare_by')||'branch',choices=branchOptions(data,axis,ceiling);
    const picked=params.get('compare_ids')?params.get('compare_ids').split(','):(data.comparison?.groups||[]).map(g=>String(g.id));
    const count=choices.filter(o=>picked.includes(String(o.id))).length;
    return `<form class="tp-comparison-controls" data-dashboard-filters data-comparison-controls aria-label="Comparison selection"><div class="tp-comparison-axis">${select('compare_by','Compare by',fields.map(([id,,label])=>({id,label})),new URLSearchParams({...Object.fromEntries(params),compare_by:axis}),false)}</div><fieldset aria-describedby="tp-comparison-count"><legend>Groups to compare (up to ${MAX_COMPARISON_GROUPS})</legend><div class="tp-comparison-choices">${choices.map(o=>{const on=picked.includes(String(o.id));return `<label><input type="checkbox" name="compare_ids" value="${esc(o.id)}" ${on?'checked':''} ${!on&&count>=MAX_COMPARISON_GROUPS?'disabled':''}>${esc(o.label)}</label>`;}).join('')||'<p class="tp-empty">No groups are available to compare for this selection.</p>'}</div><p class="tp-note" id="tp-comparison-count" data-comparison-count>${count} of ${MAX_COMPARISON_GROUPS} groups selected. Results update automatically.</p></fieldset></form>`;
  }
  function comparisonResults(data){
    const groups=data.comparison?.groups||[];
    if(!groups.length)return '<p class="tp-empty" data-comparison-state="empty">Choose at least one group above to see its comparison.</p>';
    const rate=groups.map(g=>{const b=g.completion?.buckets?.find(b=>b.label==='Completed');const t=g.completion?.total;return {label:g.label,state:b?.state||'restricted',count:b?.count,percentage:b?.percentage,denominator:t?.state==='visible'?t.value:null};});
    const cards=groups.map(g=>`<article class="tp-comparison-group"><h3>${esc(g.label)}</h3>${chart('Completion',g.completion,'completion',{switch:false,mode:'bar'})}${chart('Classification',g.classification,'classification',{switch:false,mode:'bar'})}${results(g.result)}</article>`).join('');
    return `<div class="tp-comparison-results" data-comparison-results>${charts.comparison('Completion rate by group',rate)}<div class="tp-insight-grid">${cards}</div></div>`;
  }
  // A non-visible cell is simply "Unavailable" (M18a): no count, percentage or magnitude.
  const value=cell=>cell?.state==='visible'&&cell.value!=null?esc(cell.value):'Unavailable';
  // Inline SVG glyphs (no emoji, no icon font): decorative only and always paired with text.
  const glyphs={
    users:'<circle cx="9" cy="8" r="3.2"/><path d="M3 20c0-3.4 2.7-6 6-6s6 2.6 6 6"/><path d="M16 5.2a3.2 3.2 0 0 1 0 5.6M18 14.4c1.8.8 3 2.6 3 5.6"/>',
    layers:'<path d="m12 3 9 5-9 5-9-5 9-5Z"/><path d="m3 13 9 5 9-5"/>',
    check:'<circle cx="12" cy="12" r="9"/><path d="m8 12.5 2.7 2.7L16.5 9"/>',
    star:'<path d="m12 3 2.7 5.6 6.1.9-4.4 4.3 1 6.1L12 17l-5.4 2.9 1-6.1-4.4-4.3 6.1-.9L12 3Z"/>',
    chart:'<path d="M4 20V10M10 20V4M16 20v-7M22 20H2"/>',
    clock:'<circle cx="12" cy="12" r="9"/><path d="M12 7v5l3.5 2"/>',
    compare:'<path d="M7 4v16M17 4v16M3 9h8M13 15h8"/>',
    target:'<circle cx="12" cy="12" r="9"/><circle cx="12" cy="12" r="4.5"/><path d="M12 12h.01"/>',
    settings:'<circle cx="12" cy="12" r="3"/><path d="M19.4 15a1.7 1.7 0 0 0 .3 1.9l.1.1-2.8 2.8-.1-.1a1.7 1.7 0 0 0-1.9-.3 1.7 1.7 0 0 0-1 1.6v.2h-4V21a1.7 1.7 0 0 0-1-1.6 1.7 1.7 0 0 0-1.9.3l-.1.1L4.2 17l.1-.1a1.7 1.7 0 0 0 .3-1.9A1.7 1.7 0 0 0 3 14H2.8v-4H3a1.7 1.7 0 0 0 1.6-1 1.7 1.7 0 0 0-.3-1.9L4.2 7 7 4.2l.1.1a1.7 1.7 0 0 0 1.9.3A1.7 1.7 0 0 0 10 3V2.8h4V3a1.7 1.7 0 0 0 1 1.6 1.7 1.7 0 0 0 1.9-.3l.1-.1L19.8 7l-.1.1a1.7 1.7 0 0 0-.3 1.9 1.7 1.7 0 0 0 1.6 1h.2v4H21a1.7 1.7 0 0 0-1.6 1Z"/>'};
  const glyph=name=>`<svg class="tp-glyph" viewBox="0 0 24 24" width="22" height="22" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true" focusable="false">${glyphs[name]||glyphs.chart}</svg>`;
  const kpiIcon={students:'users',participation:'layers',completion:'check',result:'star'};
  const kpi=(label,body,note,tone)=>`<article class="tp-executive-kpi tp-tone-${esc(tone)}" role="listitem"><span class="tp-kpi-icon" aria-hidden="true">${glyph(kpiIcon[tone]||'chart')}</span><span class="tp-stat-label">${esc(label)}</span><strong class="tp-stat-value">${body}</strong><small>${esc(note)}</small></article>`;
  function results(result){return result?.state==='visible'?`<p class="tp-result-headline"><strong>${esc(result.average)} / ${esc(result.scale_max)}</strong><span>Mean Program Result · ${esc(result.normalized_percent)}%</span></p>`:`<p class="tp-note">${result?.reason_code==='incompatible_frameworks'?'Choose one compatible Program and assessment framework to view results.':'A publishable Program result is unavailable for this selection.'}</p>`;}
  const section=(id,icon,title,lead,body)=>`<section class="tp-analytics-section" data-analytics-section="${id}" aria-label="${title}"><header class="tp-analytics-section-head"><span class="tp-section-glyph" aria-hidden="true">${glyph(icon)}</span><div><h2>${title}</h2><p>${lead}</p></div></header>${body}</section>`;
  // Overview: aggregate widgets default to Doughnut where it is semantically valid (a full
  // public partition of at most eight categories); anything else falls back to Bar inside
  // the chart. `animate` adds ONE restrained entrance (CSS, short); it is decided by the
  // caller from prefers-reduced-motion and is never applied to a later chart-type switch.
  function overview(data,opts={}){
    const o={surface:'overview',defaultMode:'doughnut'};
    return `<section class="tp-overview-insights${opts.animate?' tp-motion-enter':''}" aria-label="Executive charts"><div class="tp-insight-grid">${chart('Current Classification',data.classification,'classification',o)}${chart('Learning Style',data.learning_style,'learning-style',{surface:'overview'})}${chart('Assessment completion',data.completion,'completion',o)}</div><p class="tp-note">Classification and completion count Evaluation participations; Learning Style counts distinct Students. Only Exceptional is Talented. Open Results &amp; Analytics for filtered comparisons.</p></section>`;
  }
  function executive(data,params,years,ceiling){
    const opts=(items,name,label,all=true)=>{
      const plurals={'Evaluation Period':'Periods',Branch:'Branches',Grade:'Grades',Program:'Programs'};
      return (all?`<option value="">All ${esc(plurals[label]||label+'s')}</option>`:'')+(items||[]).map(item=>{const id=item.id??item,text=item.label??(label==='Grade'?`Grade ${item}`:item);return `<option value="${esc(id)}" ${String(params.get(name)||'')===String(id)?'selected':''}>${esc(text)}</option>`;}).join('');
    };
    const field=(name,label,items,all=true)=>`<label><span>${esc(label)}</span><select name="${name}">${opts(items,name,label,all)}</select></label>`;
    const metric=cell=>cell?.state==='visible'&&cell.value!=null?esc(cell.value):'Unavailable';
    const completed=data.summary?.completed||{},remaining=data.summary?.remaining||{},expected=data.summary?.expected||{};
    const summary=[
      ['Students in Scope',metric(data.summary?.students),'Distinct Students matching your filters','students'],
      ['Expected Assessments',metric(expected),'Eligible Student × Program × opened Period','expected'],
      ['Assessments Completed',completed.state==='visible'?`${esc(completed.value)} / ${metric(expected)}`:'Unavailable',completed.percentage==null?'Unavailable':`${esc(completed.percentage)}% completed`,'completed'],
      ['Assessments Remaining',metric(remaining),remaining.percentage==null?'Unavailable':`${esc(remaining.percentage)}% remaining`,'remaining'],
    ];
    const programIds=(data.programs||[]).map(p=>String(p.id));
    const studentRows=(data.students||[]).map(student=>{const cells=new Map((student.programs||[]).map(p=>[String(p.program_id),p]));return `<tr data-executive-student data-search="${esc(student.display_name.toLowerCase())}"><th scope="row"><span class="tp-student-name"><i aria-hidden="true">${esc(student.display_name.split(/\s+/).map(v=>v[0]).slice(0,2).join('').toUpperCase())}</i>${esc(student.display_name)}</span></th><td>${esc(student.grade_level)}</td><td>${esc(student.section_name)}</td><td><span class="tp-style-chip">${esc(student.learning_style||'Unassigned')}</span></td>${programIds.map(id=>{const p=cells.get(id);if(!p)return '<td><span class="tp-na">—<small>Not applicable</small></span></td>';const result=p.result_state==='visible'?`<div class="tp-program-result"><span class="tp-chart-track" aria-hidden="true"><i style="width:${Math.max(0,Math.min(100,Number(p.normalized_percent)))}%"></i></span><strong>${esc(p.normalized_percent)}%</strong></div>`:p.result_state==='not_comparable'?'<span class="tp-na">Not comparable</span>':'<span class="tp-na">No result</span>';return `<td>${result}${p.classification?`<span class="tp-program-classification">${esc(p.classification)}</span>`:''}${p.is_talented?'<span class="tp-talented-badge">★ Talented</span>':''}</td>`;}).join('')}<td>${student.talented_program_count?`<span class="tp-talented-badge">★ ${esc(student.talented_program_count)} Program${student.talented_program_count===1?'':'s'}</span>`:'—'}</td></tr>`;}).join('');
    const branches=(data.filters?.branches||[]).filter(o=>!ceiling||String(o.id)===String(ceiling));
    return `<div class="tp-executive" data-tp-executive><header class="tp-executive-pagehead"><div class="tp-executive-title"><span class="tp-executive-mark" aria-hidden="true">${glyph('users')}</span><div><p>Talent &amp; Potential</p><h2>Executive Overview</h2><span>A summary of talent development and assessment progress for your selected scope.</span></div></div>${data.can_configure?`<a class="tp-config-action" href="/talent/programs?academic_year_id=${esc(params.get('academic_year_id')||'')}"><b aria-hidden="true">${glyph('settings')}</b><span><strong>Organization Configuration</strong><small>Programs, Rubrics, KPIs &amp; Evaluation Periods</small></span><i aria-hidden="true">›</i></a>`:''}</header><form class="tp-executive-filterbar" data-executive-filters aria-label="Executive Overview filters">${field('academic_year_id','Academic Year',years,false)}${field('branch_id','Branch',branches,!ceiling)}${field('grade_level','Grade',data.filters?.grades||[],true)}${field('program_id','Program',data.filters?.programs||[],true)}${field('period_id','Evaluation Period',data.filters?.periods||[],true)}<button type="button" data-executive-clear>Clear Filters</button></form><section class="tp-executive-summary" aria-label="Overview summary">${summary.map(([title,count,copy,tone])=>`<article class="tp-summary-card is-${tone}"><span class="tp-summary-icon" aria-hidden="true">${glyph(tone==='students'?'users':tone==='completed'?'check':tone==='remaining'?'clock':'layers')}</span><div><h3>${esc(title)}</h3><strong>${count}</strong><p>${esc(copy)}</p>${['completed','remaining'].includes(tone)&&data.summary?.[tone]?.percentage!=null?`<span class="tp-summary-progress" aria-hidden="true"><i style="width:${Math.max(0,Math.min(100,Number(data.summary[tone].percentage)))}%"></i></span>`:''}</div></article>`).join('')}</section><section class="tp-executive-analytics">${chart('Current Classification',data.classification,'executive-classification',{defaultMode:'bar',surface:'executive'})}${chart('Learning Style',data.learning_style,'executive-learning',{defaultMode:'bar',surface:'executive'})}${chart('Assessment Completion',data.completion,'executive-completion',{defaultMode:'doughnut',surface:'executive'})}</section><section class="tp-card tp-student-progress"><header><h2>Student Progress by Program</h2>${data.student_rows_state==='visible'?'<label class="tp-student-search"><span class="tp-sr-only">Search Students</span><input type="search" data-executive-search placeholder="Search Students…"></label>':''}</header>${data.student_rows_state!=='visible'?'<p class="tp-empty">Student-level progress requires Student analytics permission.</p>':`<div class="tp-table-wrap"><table><thead><tr><th>Student</th><th>Grade</th><th>Section</th><th>Learning Style</th>${(data.programs||[]).map(p=>`<th>${esc(p.label)}</th>`).join('')}<th>Talented Programs</th></tr></thead><tbody>${studentRows||'<tr><td colspan="5">No eligible Students in this scope.</td></tr>'}</tbody></table></div>`}</section></div>`;
  }
  function activeFilters(data,params){
    const chips=[];
    for(const [dim,key,label] of fields){const id=params.get(key);if(!id)continue;const hit=(data.options?.[dim]||[]).find(o=>String(o.id)===String(id));chips.push(`${esc(label)}: ${esc(hit?hit.label:id)}`);}
    if(params.get('classification'))chips.push(`Classification: ${esc(params.get('classification'))}`);
    return `<ul class="tp-active-filters" aria-label="Active analysis filters">${chips.length?chips.map(c=>`<li>${c}</li>`).join(''):'<li>All authorized data</li>'}</ul>`;
  }
  function progressLink(params){
    const program=params.get('program_id');if(!program)return '';
    const next=new URLSearchParams();for(const k of ['academic_year_id','program_id','branch_id','branch_scope','scope_branch_id','grade_level'])if(params.get(k))next.set(k,params.get(k));
    return `<p class="tp-note"><a class="tp-secondary" href="/talent/longitudinal?${esc(next.toString())}">Open Progress Over Time for this Program</a> Counts, coverage and comparability across its Evaluation Periods.</p>`;
  }
  function analytics(data,params,ceiling){
    const trend=data.trend||[];
    const trendRows=trend.map(t=>{const b=t.completion?.buckets?.find(b=>b.label==='Completed');return {label:t.label,state:b?.state||'restricted',count:b?.count,percentage:b?.percentage};});
    const completed=data.completion?.buckets?.find(b=>b.label==='Completed');
    const rate=completed?.state==='visible'&&completed.percentage!=null?`${esc(completed.percentage)}%`:'Unavailable';
    const meanResult=data.result?.state==='visible'?`${esc(data.result.average)} / ${esc(data.result.scale_max)}`:'Unavailable';
    const kpis=`<div class="tp-executive-kpis" role="list">${kpi('Distinct current Students',value(data.distinct_students),'Current Students in this selection','students')}${kpi('Evaluation participations',value(data.participations),'Program evaluation records','participation')}${kpi('Completion rate',rate,'Completed of all participations','completion')}${kpi('Mean Program result',meanResult,'One compatible Program only','result')}</div>`;
    const rubricCompare=(data.rubric?.comparison||[]).length?`<h3>Rubric Indicator comparison</h3><div class="tp-insight-grid">${data.rubric.comparison.map(g=>chart(g.label,g.distribution,'rubric')).join('')}</div>`:'';
    return `<div data-tp-dashboard class="tp-analytics"><div class="tp-refresh-bar" data-dashboard-progress hidden aria-hidden="true"></div><div class="tp-refresh-error" data-dashboard-error role="alert" hidden></div><header class="tp-executive-hero tp-analytics-hero"><div class="tp-executive-heading"><span class="tp-executive-icon" aria-hidden="true">${glyph('chart')}</span><div><p class="tp-eyebrow">Organization intelligence</p><h2>Results &amp; Analytics</h2><p>One authorized population. Backend-governed values, denominators and privacy decisions.</p>${activeFilters(data,params)}</div></div>${kpis}</header>${filters(data,params,ceiling)}`
      +section('completion','check','Completion &amp; participation','How much of the expected evaluation work is complete.',chart('Assessment completion',data.completion,'completion'))
      +section('results','target','Results &amp; Classification','Program-bound results and current Classification. Only Exceptional is Talented; there is no universal Talent score.',`${results(data.result)}${chart('Current Classification',data.classification,'classification')}`)
      +section('style','users','Learning Style','Eight categorical styles plus Unassigned. Denominator: distinct authorized Students in this selection.',chart('Learning Style',data.learning_style,'learning-style'))
      +section('rubric','layers','Rubric Indicator analytics','Program, then Competency, then Indicator. Each indicator retains its saved assessment framework.',data.rubric?.distribution?chart('Rubric level distribution',data.rubric.distribution,'rubric'):'<p class="tp-empty">Choose a Program and Rubric Indicator to view its results.</p>')
      +section('periods','clock','Evaluation Periods','Ordered recorded periods within one Program. No growth or improvement claim is inferred.',(trend.length?chart('Completion by Evaluation Period',{state:'visible',buckets:trendRows},'trend'):'<p class="tp-empty">Select one Program to view its ordered periods.</p>')+progressLink(params))
      +section('compare','compare','Selected comparisons','Choose a dimension and up to six groups. Each group is computed from its underlying population, never from averaged Branch percentages.',comparisonControls(data,params,ceiling)+comparisonResults(data)+rubricCompare)
      +'</div>';
  }
  function change(params,name,value){
    const next=new URLSearchParams(params);value?next.set(name,value):next.delete(name);
    const children={branch_id:['grade_level','section_id','compare_ids'],grade_level:['section_id','compare_ids'],program_id:['period_id','competency_id','rubric_id','compare_ids'],competency_id:['rubric_id'],compare_by:['compare_ids']};
    (children[name]||[]).forEach(k=>next.delete(k));return next;
  }
  global.TalentDashboard={overview,executive,analytics,change};
  if(typeof module!=='undefined')module.exports=global.TalentDashboard;
})(typeof window!=='undefined'?window:globalThis);
