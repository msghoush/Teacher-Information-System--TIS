'use strict';
/* Agent 3 visual-system, action-system, Program Status and chart-switching regression.
 * Structural verification only (no browser): markup, classes and CSS rules are asserted;
 * pixel appearance is intentionally not claimed. */
const {test}=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const path=require('node:path');
const charts=require('../static/js/talent-charts.js');
const dashboard=require('../static/js/talent-dashboard.js');
const read=file=>fs.readFileSync(path.join(__dirname,'..',file),'utf8');
const css=read('static/css/talent-experience.css');

const full={state:'visible',buckets:[{label:'Visual',state:'visible',count:6,percentage:60},{label:'Aural',state:'visible',count:4,percentage:40}]};
const partial={state:'visible',buckets:[{label:'Visual',state:'visible',count:31,percentage:62},{label:'Hidden band',state:'suppressed',count:19,percentage:38}]};

test('V1. chart-type matrix: only valid, materially different modes per family and only for a full public partition',()=>{
  const matrix={classification:['bar','doughnut'],completion:['bar','doughnut'],'learning-style':['bar'],rubric:['bar']};
  for(const [family,expected] of Object.entries(matrix))assert.deepEqual(charts.modes(full,family),expected,family);
  assert.deepEqual(charts.modes(partial,'classification'),['bar'],'a suppressed cell removes every circular mode');
  assert.deepEqual(charts.modes({state:'restricted'},'classification'),['bar']);
});

test('V2. switching chart mode re-renders only sanitized public rows: no protected value reaches geometry, text or attributes',()=>{
  const listeners={};
  const rows=charts.sanitize(partial);
  const host={
    visual:{innerHTML:''},pressed:[],
    querySelector(selector){return selector==='[data-chart-visual]'?this.visual:null;},
    querySelectorAll(selector){
      if(selector==='[data-chart-row]')return rows.map(r=>({dataset:{state:r.state},children:[{textContent:r.label},{textContent:r.count===null?'Unavailable':String(r.count)},{textContent:r.percentage===null?'Unavailable':`${r.percentage}%`}]}));
      if(selector==='[data-chart-mode]')return this.buttons;
      return [];
    },
    buttons:[]
  };
  const button={dataset:{chartMode:'percentage'},closest:selector=>selector==='[data-chart-family]'?host:button,setAttribute(name,value){this.pressed=[name,value];}};
  host.buttons=[button];
  charts.bind({addEventListener:(type,fn)=>{listeners[type]=fn;}});
  listeners.click({target:{closest:selector=>selector==='[data-chart-mode]'?button:null}});
  const html=host.visual.innerHTML;
  assert.match(html,/Visual/);
  assert.ok(!html.includes('19')&&!html.includes('38'),'the suppressed cell has no count or percentage in the switched visual');
  assert.match(html,/Unavailable/);
  assert.ok(!/protected for privacy/i.test(html));
});

test('V3. protected Learning Style leaks no number through payload-derived markup, dataset, ARIA or tooltip',()=>{
  const protectedStyle={state:'restricted',reason_code:'classification_cohort_protected',total:{state:'restricted',value:null},total_population:null,levels:[]};
  const html=charts.chart('Learning Style',protectedStyle,'learning-style');
  assert.match(html,/Learning Style summary is unavailable for this Classification filter because the cohort is protected for privacy\./);
  assert.ok(!/\d/.test(html.replace(/<h3>[^<]*<\/h3>/,'')),'no digit at all outside the title');
  for(const token of ['aria-valuenow','aria-valuemax','data-count','data-value','title=','style=','data-chart-mode','<table'])assert.ok(!html.includes(token),token);
  assert.ok(!html.includes('No data'),'a protected cohort is never presented as zero or no-data');
});

test('V4. the generic "Protected for privacy" copy is absent from every Talent script (M18a)',()=>{
  for(const file of ['talent-charts.js','talent-dashboard.js','talent-operations.js','talent-experience.js','talent-program-workspace.js'])
    assert.ok(!/Protected for privacy/.test(read(`static/js/${file}`)),file);
  const source=read('static/js/talent.js').replace(/\/\/.*never the literal "Protected for privacy"\./,'');
  assert.ok(!/Protected for privacy/.test(source));
});

test('V5. Program Status is not shown in normal Program, Overview, Results or Assessment UI',()=>{
  const source=read('static/js/talent.js');
  assert.ok(!/badge\((?:r\.program|program)\.status\)/.test(source),'no Program lifecycle badge');
  assert.ok(!/\$\{programLogo\(p\)\} \$\{badge\(/.test(source),'Program cards carry no lifecycle badge');
  assert.ok(!/<article class="tp-card">\$\{badge\(p\.status\)\}<h3>\$\{esc\(p\.name\)\}/.test(source),'Program header has no lifecycle badge');
  const list=read('static/js/talent-program-workspace.js');
  assert.ok(!/class="tp-badge">\$\{esc\(program\.status\)\}/.test(list));
  assert.ok(!/<th>Status<\/th>/.test(list));
  assert.doesNotMatch(read('static/js/talent-operations.js'),/program\.status|p\.status\)/);
});

test('V6. professional action system: one primary, secondary and destructive treatment',()=>{
  const html=dashboard.analytics({options:{}},new URLSearchParams(),null);
  assert.match(html,/<button type="submit" class="tp-primary">Refresh analysis<\/button>/);
  assert.match(html,/<button type="button" class="tp-secondary" data-dashboard-clear>/);
  assert.match(css,/\.tp \.tp-primary,\.tp \.tp-primary-link/);
  assert.match(css,/button\[data-action\*="delete"\]/);
  assert.match(css,/button:disabled/);
  assert.match(css,/focus-visible/);
});

test('V7. Student Assessment roster uses initials and inline SVG, not emoji, for avatars and period icons',()=>{
  const operations=read('static/js/talent-operations.js');
  assert.ok(!/\u{1F464}|\u{1F4C5}/u.test(operations));
  assert.match(operations,/initialsOf\(fullName\)/);
});

test('V8. responsive, reduced-motion and forced-colors structure exists and charts never rely on colour alone',()=>{
  assert.match(css,/@media \(max-width:640px\)/);
  assert.match(css,/@media \(max-width:900px\)/);
  assert.match(css,/prefers-reduced-motion:reduce/);
  assert.match(css,/forced-colors:active/);
  const html=charts.chart('Style',full,'learning-style');
  assert.match(html,/<summary>Exact values and accessible table<\/summary>/);
  // Learning Style is bar-only, so no selector is rendered; a switchable family keeps real buttons.
  assert.ok(!html.includes('data-chart-mode'));
  assert.match(charts.chart('Class',full,'classification'),/type="button"/);
});

test('V9. the analytics KPI strip exposes distinct Students, participations, completion and result, each labelled with its grain',()=>{
  const html=dashboard.analytics({options:{},distinct_students:{state:'visible',value:9},participations:{state:'visible',value:12},
    completion:{state:'visible',buckets:[{label:'Completed',state:'visible',count:6,percentage:50}]}},new URLSearchParams(),null);
  for(const label of ['Distinct current Students','Evaluation participations','Completion rate','Mean Program result'])assert.ok(html.includes(label),label);
  assert.match(html,/<strong class="tp-stat-value">9<\/strong>/);
  assert.match(html,/<strong class="tp-stat-value">50%<\/strong>/);
  assert.match(html,/<strong class="tp-stat-value">Unavailable<\/strong>/);
});

test('V10. a non-visible KPI cell renders "Unavailable", never zero',()=>{
  const html=dashboard.analytics({options:{},distinct_students:{state:'suppressed',value:0},participations:{state:'restricted',value:0}},new URLSearchParams(),null);
  assert.ok(!/tp-stat-value">0</.test(html));
});

test('V11. Student Assessment roster: exact small-cohort rows stay visible while a protected Classification cohort shows only the explanation',async()=>{
  const {render}=require('../static/js/talent-operations.js');
  const root={innerHTML:'',querySelector:()=>({textContent:'',setAttribute(){},addEventListener(){}}),querySelectorAll:()=>[]};
  const cycle={id:61,program_id:11,title:'Term 1',status:'open',population_effective_at:'2026-01-01'};
  const members=[{student_id:101,student_name:'Only Student',grade_level:'3',section_name:'A',learning_style:'Visual'}];
  const rows=[{id:502,student_id:101,status:'completed',is_current:true,academic_year_id:'2026',program_id:11,classification:'Exceptional',is_talented:true,actions:[]}];
  const insights={
    learning_style:{state:'restricted',reason_code:'classification_cohort_protected',total:{state:'restricted',value:null},total_population:null,levels:[]},
    classification:{state:'restricted',total:{state:'restricted',value:null},buckets:[]},
  };
  const ctx={root,year:'2026',view:'assessments',params:new URLSearchParams('cycle_id=61&program_id=11&classification=Exceptional'),can:()=>true,notify(){},
    api:async path=>{
      if(path.startsWith('/api/talent/assessments?'))return rows;
      if(path.startsWith('/api/talent/assessments/contexts?'))return [cycle];
      if(path.endsWith('/eligible-students')||path.includes('/eligible-students?'))return {members,insights,filter_options:{grades:['3'],sections:['A']}};
      throw new Error(`Unexpected ${path}`);
    }};
  const previous=global.window;
  global.window={addEventListener(){},removeEventListener(){},confirm:()=>true,TalentCharts:charts};
  try{await render(ctx);}finally{global.window=previous;}
  const html=root.innerHTML;
  assert.match(html,/Only Student/,'the individually authorized row is exact');
  assert.match(html,/Exceptional/);
  assert.match(html,/cohort is protected for privacy/);
  assert.ok(!/\bNo data\b/.test(html.split('Learning Style')[1]||''),'the protected state is never presented as zero or no-data');
});
