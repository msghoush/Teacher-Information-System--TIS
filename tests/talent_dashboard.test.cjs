'use strict';
const {test}=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const charts=require('../static/js/talent-charts.js');
const dashboard=require('../static/js/talent-dashboard.js');
const {createEnv}=require('./talent_runtime_harness.cjs');
const visible={state:'visible',buckets:[{label:'A',state:'visible',count:12,percentage:40},{label:'B',state:'visible',count:18,percentage:60}]};
const protectedProjection={state:'restricted',reason_code:'classification_cohort_protected',total_population:731,total:{state:'restricted',value:731},levels:[{label:'Visual',state:'suppressed',count:731,percentage:91.375}]};
test('protected Learning Style has no totals, buckets, chart magnitudes or hidden numeric output',()=>{
  const html=charts.chart('Learning Style',protectedProjection,'learning-style');
  assert.match(html,/cohort is protected for privacy/);
  for(const token of ['731','91.375','style=','aria-value','data-chart-row','title='])assert.ok(!html.includes(token),token);
  assert.ok(!html.includes('No data'));assert.deepEqual(charts.sanitize(protectedProjection),[]);
});
test('suppressed cell never contributes a magnitude, percentage, tooltip or circular mode',()=>{
  const p={state:'visible',buckets:[...visible.buckets,{label:'Protected band',state:'suppressed',count:847,percentage:87.61}]};
  const html=charts.chart('Classification',p);
  assert.ok(!html.includes('847'));assert.ok(!html.includes('87.61'));
  assert.deepEqual(charts.modes(p,'classification'),['bar']);
  assert.match(html,/Unavailable/);
  // M18a: the generic badge copy is gone; only the Classification-cohort explanation may say "protected for privacy".
  assert.doesNotMatch(html,/protected for privacy/i);
});
// Part 2 D (deliberate update of the old mode pins): the selector switches VISUALIZATION TYPES.
// "percentage" duplicated the count bar and "pie" duplicated doughnut, so both are gone; Learning
// Style (eight styles plus Unassigned) is bar-only because nine slices are not legible.
test('classification and completion offer Bar and Doughnut only for a full public partition',()=>{
  assert.deepEqual(charts.modes(visible,'classification'),['bar','doughnut']);
  assert.deepEqual(charts.modes(visible,'completion'),['bar','doughnut']);
});
test('Learning Style, rubric levels and comparisons are bar-only (high cardinality or ordinal)',()=>{
  for(const family of ['learning-style','rubric','comparison'])assert.deepEqual(charts.modes(visible,family),['bar'],family);
  const nine={state:'visible',buckets:Array.from({length:9},(_,i)=>({label:'S'+i,state:'visible',count:1,percentage:i<8?11.1:11.2}))};
  assert.deepEqual(charts.modes(nine,'classification'),['bar'],'more than eight categories never becomes a circular chart');
  assert.equal(charts.MAX_CIRCULAR_CATEGORIES,8);
});
test('trend offers Trend and Bar only with two public ordered points and never a circular type',()=>{
  assert.deepEqual(charts.modes(visible,'trend'),['trend','bar']);
  assert.deepEqual(charts.modes({state:'visible',buckets:visible.buckets.slice(0,1)},'trend'),['bar']);
  assert.ok(!charts.modes(visible,'trend').includes('doughnut'));
});
test('every offered mode renders exact values and a table, and no two modes render the same picture',()=>{
  for(const family of ['classification','completion','trend']){
    const modes=charts.modes(visible,family),seen=new Set();
    for(const mode of modes){
      const html=charts.chart('Styles',visible,family,mode);
      assert.match(html,/<table>/);assert.match(html,/<caption>Styles/);assert.match(html,/<th scope="row">A/);
      assert.match(html,/>12<\/td>/);assert.match(html,/12/);assert.match(html,/40%/);
      const visual=html.match(/<div data-chart-visual>([\s\S]*?)<\/div><details>/)[1];
      assert.ok(!seen.has(visual),`${family}/${mode} duplicates another mode`);seen.add(visual);
    }
    if(modes.length>1){
      const html=charts.chart('Styles',visible,family);
      assert.equal((html.match(/data-chart-mode=/g)||[]).length,modes.length);
      assert.match(html,/type="button"/);assert.match(html,/aria-pressed="true"/);
    }
  }
});
test('a chart with a single valid type renders no selector at all',()=>{
  const html=charts.chart('Styles',visible,'learning-style');
  assert.ok(!html.includes('data-chart-mode')&&!html.includes('tp-chart-switch'));
  assert.match(html,/<table>/);
});
test('zero population is not a false zero percentage and unsafe modes fall back',()=>{
  const p={state:'empty',levels:[{label:'Visual',state:'visible',count:0,percentage:null}]};
  const html=charts.chart('Style',p,'learning-style','pie');assert.ok(!html.includes('conic-gradient'));assert.ok(!html.includes('(0%)'));assert.match(html,/Unavailable/);
});
test('chart labels are escaped',()=>assert.ok(!charts.chart('<script>',{state:'visible',buckets:[{label:'<img>',state:'visible',count:1,percentage:100}]}).includes('<img>')));
test('dependent filters clear without losing Classification or unrelated filters',()=>{
  const p=new URLSearchParams('program_id=1&period_id=2&competency_id=3&rubric_id=4&classification=Exceptional&branch_id=6');
  const next=dashboard.change(p,'program_id','8');assert.equal(next.get('branch_id'),'6');assert.equal(next.get('classification'),'Exceptional');for(const k of ['period_id','competency_id','rubric_id'])assert.equal(next.has(k),false);
  assert.equal(dashboard.change(new URLSearchParams('grade_level=3&section_id=4'),'grade_level','5').has('section_id'),false);
});
const payload={options:{branch:[{id:'6',label:'B'}],grade:[],section:[],program:[],period:[]},distinct_students:{state:'visible',value:30},participations:{state:'visible',value:60},completion:visible,classification:visible,learning_style:protectedProjection,comparison:{groups:[]},rubric:{competencies:[],indicators:[]},trend:[]};
test('aggregate workspace has six sections and no Student roster',()=>{
  const html=dashboard.analytics(payload,new URLSearchParams(),'6');
  for(const heading of ['Completion &amp; participation','Results &amp; Classification','Learning Style','Rubric Indicator analytics','Evaluation Periods','Selected comparisons'])assert.ok(html.includes(heading));
  assert.ok(!html.includes('731'));assert.ok(!html.includes('All Branch'));assert.ok(!html.includes('Student name'));
});
test('All context options do not cross the Branch ceiling',()=>{
  const html=dashboard.analytics({...payload,options:{...payload.options,branch:[{id:'6',label:'Allowed'},{id:'7',label:'Forbidden'}]}},new URLSearchParams(),'6');
  assert.ok(!html.includes('Forbidden'));assert.match(html,/Allowed/);
});
test('M16 chart bundles remain surface-specific and old duplicate rubric augmentation is disabled',()=>{
  const template=fs.readFileSync('templates/talent/workspace.html','utf8');assert.match(template,/talent_view in \['overview', 'analytics', 'assessments', 'longitudinal'\]/);
  const experience=fs.readFileSync('static/js/talent-experience.js','utf8');assert.match(experience,/window.TalentDashboard\) return/);
});
test('new dashboard loads one unified request without Student previews or old duplicate analytics',async()=>{
  const env=createEnv({view:'analytics',permissions:{'talent_analytics.view':true,'students.view':true},globals:{TalentCharts:charts,TalentDashboard:dashboard},handler:url=>url.includes('/dashboard?')?{body:payload}:{body:[]}});
  await env.start();
  assert.match(env.root.text(),/Selected comparisons/);
  assert.equal(env.calls.filter(c=>String(c.url||c).includes('/dashboard?')).length,1);
  assert.ok(!env.calls.some(c=>String(c.url||c).includes('/students?')));
});

const executivePayload={
  filters:{branches:[{id:'6',label:'Allowed'}],grades:['3'],programs:[{id:'9',label:'Mental Math'}],periods:[{id:'11',label:'Semester 1'}]},
  summary:{students:{state:'visible',value:1},expected:{state:'visible',value:2},completed:{state:'visible',value:1,percentage:50},remaining:{state:'visible',value:1,percentage:50}},
  classification:visible,learning_style:{state:'visible',levels:[{label:'Visual',state:'visible',count:1,percentage:100}]},completion:visible,
  programs:[{id:'9',label:'Mental Math'}],student_rows_state:'visible',can_configure:true,
  students:[{student_id:1,display_name:'Student One',grade_level:'3',section_name:'A',learning_style:'Visual',talented_program_count:1,programs:[{program_id:'9',result_state:'visible',normalized_percent:92,classification:'Exceptional',is_talented:true}]}]
};
test('Executive Overview matches the approved information architecture without legacy or old KPIs',()=>{
  const html=dashboard.executive(executivePayload,new URLSearchParams('academic_year_id=1'),[{id:'1',label:'2026–2027'}],'6');
  for(const text of ['Executive Overview','Organization Configuration','Students in Scope','Expected Assessments','Assessments Completed','Assessments Remaining','Current Classification','Learning Style','Assessment Completion','Student Progress by Program'])assert.match(html,new RegExp(text));
  for(const old of ['Program participations','Programs configured','Legacy Review','Official Identification'])assert.ok(!html.includes(old),old);
  assert.match(html,/Semester 1/);assert.match(html,/★ Talented/);assert.match(html,/Exceptional/);
  assert.ok(!html.includes('All Branches'),'hard Branch ceiling has no All Branches option');
});
test('Executive Overview preserves organization-wide Branch choices and hides configuration without authority',()=>{
  const payload={...executivePayload,can_configure:false,filters:{...executivePayload.filters,branches:[{id:'6',label:'North'},{id:'7',label:'South'}]}};
  const html=dashboard.executive(payload,new URLSearchParams('academic_year_id=1&branch_id=6'),[{id:'1',label:'2026â€“2027'}],'');
  assert.match(html,/All Branches/);assert.match(html,/South/);
  assert.ok(!html.includes('Organization Configuration'));
});
test('Executive chart modes are exactly the approved Bar/Doughnut/Table sets',()=>{
  assert.deepEqual(charts.modes(visible,'executive-classification'),['bar','doughnut','table']);
  assert.deepEqual(charts.modes(visible,'executive-learning'),['bar','doughnut','table']);
  assert.deepEqual(charts.modes(visible,'executive-completion'),['doughnut','bar','table']);
});
test('Executive protected Classification leaks no count, percentage, geometry or ARIA magnitude',()=>{
  const protectedClass={state:'restricted',total:{state:'restricted',value:417},buckets:[{label:'Exceptional',state:'suppressed',count:417,percentage:91.2}]};
  const html=charts.chart('Current Classification',protectedClass,'executive-classification');
  for(const token of ['417','91.2','aria-valuenow','conic-gradient'])assert.ok(!html.includes(token),token);
});
