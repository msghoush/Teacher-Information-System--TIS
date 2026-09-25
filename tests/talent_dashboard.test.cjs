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
  assert.deepEqual(charts.modes(p,'classification'),['bar','percentage']);
  assert.match(html,/Unavailable/);
  // M18a: the generic badge copy is gone; only the Classification-cohort explanation may say "protected for privacy".
  assert.doesNotMatch(html,/protected for privacy/i);
});
test('classification supports only valid bar, percentage, doughnut views',()=>assert.deepEqual(charts.modes(visible,'classification'),['bar','percentage','doughnut']));
test('Learning Style supports pie and doughnut only for a full public partition',()=>assert.deepEqual(charts.modes(visible,'learning-style'),['bar','percentage','pie','doughnut']));
test('completion cannot offer pie and rubric cannot offer meaningless trend',()=>{assert.deepEqual(charts.modes(visible,'completion'),['bar','percentage']);assert.deepEqual(charts.modes(visible,'rubric'),['bar','percentage']);});
test('trend requires multiple public ordered data points',()=>{assert.deepEqual(charts.modes(visible,'trend'),['bar','trend']);assert.deepEqual(charts.modes({state:'visible',buckets:visible.buckets.slice(0,1)},'trend'),['bar']);});
test('all chart modes include equivalent exact tables and keyboard buttons',()=>{
  for(const mode of charts.modes(visible,'learning-style')){
    const html=charts.chart('Styles',visible,'learning-style',mode);
    assert.match(html,/<table>/);assert.match(html,/<caption>Styles/);assert.match(html,/<th scope="row">A/);
    assert.match(html,/type="button"/);assert.match(html,/aria-pressed="true"/);assert.match(html,/>12<\/td>/);
  }
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
  const template=fs.readFileSync('templates/talent/workspace.html','utf8');assert.match(template,/talent_view in \['overview', 'analytics', 'assessments'\]/);
  const experience=fs.readFileSync('static/js/talent-experience.js','utf8');assert.match(experience,/window.TalentDashboard\) return/);
});
test('new dashboard loads one unified request without Student previews or old duplicate analytics',async()=>{
  const env=createEnv({view:'analytics',permissions:{'talent_analytics.view':true,'students.view':true},globals:{TalentCharts:charts,TalentDashboard:dashboard},handler:url=>url.includes('/dashboard?')?{body:payload}:{body:[]}});
  await env.start();
  assert.match(env.root.text(),/Selected comparisons/);
  assert.equal(env.calls.filter(c=>String(c.url||c).includes('/dashboard?')).length,1);
  assert.ok(!env.calls.some(c=>String(c.url||c).includes('/students?')));
});
