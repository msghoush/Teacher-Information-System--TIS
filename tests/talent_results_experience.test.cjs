const {test} = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const {
  progressVisual, friendlyReason, overlapMatrix, periodVisual, errorPanel,
} = require('../static/js/talent.js');

test('visible server percentages alone control progress length', () => {
  const visible = progressVisual({state:'visible', percentage:42.5, numerator:17, denominator:40}, 'Completion');
  assert.match(visible, /width:42\.5%/);
  assert.match(visible, /42\.5 percent/);
  for (const state of ['suppressed','complementary_suppressed','restricted','coarsened','no_data']) {
    const protectedHtml = progressVisual({state, percentage:97, numerator:97, denominator:100}, 'Completion');
    assert.doesNotMatch(protectedHtml, /97|width:|progress-track|aria-label=.*percent/);
  }
});

test('Progress Over Time translates every governed comparison reason', () => {
  const governed = ['missing_cycle','cycle_not_authoritative','cancelled_period','no_frozen_population','metric_unavailable','framework_changed','privacy_protected'];
  for (const reason of governed) {
    const copy = friendlyReason(reason);
    assert.ok(copy.length > 20);
    assert.doesNotMatch(copy, /_/);
  }
});

test('Progress Over Time chart never encodes protected magnitude', () => {
  const html = periodVisual({metric:'completion_coverage',points:[
    {evaluation_period:{id:1,sequence:1,label:'Autumn',status:'planned'},metric_result:{state:'visible',percentage:25,numerator:1,denominator:4}},
    {evaluation_period:{id:2,sequence:2,label:'Spring',status:'planned'},metric_result:{state:'suppressed',percentage:99,numerator:99,denominator:100}},
  ]});
  assert.match(html, /height:25%/);
  assert.doesNotMatch(html, /height:99%|>99%|99 of 100/);
  assert.match(html, /Protected for privacy/);
});

test('Students Across Programs has accessible grid semantics and plain meaning', () => {
  const data={programs:[{id:1,name:'Arts'},{id:2,name:'STEM'}],matrix:[
    {program_id:1,cells:[{program_id:1,state:'visible',value:3},{program_id:2,state:'visible',value:1}]},
    {program_id:2,cells:[{program_id:1,state:'visible',value:1},{program_id:2,state:'no_data'}]},
  ]};
  const html=overlapMatrix(data,()=>'<a href="/talent/portfolio">Open Program results</a>');
  assert.match(html,/role="grid"/);
  assert.match(html,/Students in both Arts and STEM/);
  assert.match(html,/In this Program/);
  assert.match(html,/tp-nodata-cell/);
});

test('Results source uses friendly public names and no technical analytics labels', () => {
  const source=fs.readFileSync(path.join(__dirname,'..','static','js','talent.js'),'utf8');
  const router=fs.readFileSync(path.join(__dirname,'..','routers','talent_ui.py'),'utf8');
  assert.match(source,/Students Across Programs/);
  assert.match(source,/Progress Over Time/);
  assert.match(router,/"portfolio": \("Program Results"/);
  assert.match(router,/"branch": \("Branch Results"/);
  assert.match(router,/"students": \("Students"/);
  assert.doesNotMatch(source,/Participation Overlap|Organization Intelligence|metric code|privacy class|provider version/);
});

test('responsive and accessibility invariants are present', () => {
  const css=fs.readFileSync(path.join(__dirname,'..','static','css','talent.css'),'utf8');
  const template=fs.readFileSync(path.join(__dirname,'..','templates','talent','workspace.html'),'utf8');
  assert.match(css,/@media \(max-width: 680px\)/);
  assert.match(css,/@media \(prefers-reduced-motion: reduce\)/);
  assert.match(css,/overflow-x:auto/);
  assert.match(template,/aria-label="Results and Analytics views"/);
  assert.match(template,/for="tp-dimension"/);
});

test('permission and analytics availability failures have distinct plain-language states', () => {
  assert.match(errorPanel({status:403,message:'This view is not available.'}),/Permission denied/);
  assert.match(errorPanel({status:503,message:'Try later.'}),/Analytics unavailable/);
  assert.doesNotMatch(errorPanel({status:503,message:'Try later.'}),/provider|policy|privacy class/i);
});
