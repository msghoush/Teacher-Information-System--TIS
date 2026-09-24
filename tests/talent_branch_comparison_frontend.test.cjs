const {test}=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const path=require('node:path');
const {branchComparisonMetricOptions,branchMetricValue,branchComparisonChart}=require('../static/js/talent.js');

const branches=[{id:10,label:'North Campus'},{id:11,label:'A Very Long Branch Name'}];

test('primary Branch chart preserves backend order, labels, visible values, and real zero',()=>{
  const html=branchComparisonChart({metric:'current_overall_progress',rows:[
    {branch_id:11,state:'visible',value:0},{branch_id:10,state:'visible',value:82.5},
  ]},branches);
  assert.ok(html.indexOf('A Very Long Branch Name')<html.indexOf('North Campus'));
  assert.match(html,/A Very Long Branch Name[\s\S]*0%/);
  assert.match(html,/North Campus[\s\S]*82\.5%/);
  assert.match(html,/role="img"[\s\S]*aria-label=/);
});

test('suppressed and no-data Branches remain distinct and never expose supplied hidden values',()=>{
  const html=branchComparisonChart({metric:'current_overall_progress',rows:[
    {branch_id:10,state:'suppressed',value:91,count:4},
    {branch_id:11,state:'no_data',value:73,count:0},
  ]},branches);
  assert.match(html,/Unavailable/);assert.match(html,/No data/);
  assert.doesNotMatch(html,/>91<|>73<|>4<|>0%<|width:/);
});

test('only the four current Branch-comparison metrics are offered; legacy Review/Identification metrics are never a normal option',()=>{
  // Acceptance B (deliberate pinned-expectation update): the former secondary
  // meets_program_criteria / officially_confirmed options (and the M14-removed
  // learning_style option this stale test still listed) are not current metrics.
  const current=['evaluation_period_result','current_overall_progress','assessment_completion','assessments_started'];
  assert.deepEqual(branchComparisonMetricOptions(true,true).map(([value])=>value),current);
  assert.deepEqual(branchComparisonMetricOptions(false,false).map(([value])=>value),current);
});

test('metric families consume only their backend-authoritative value field',()=>{
  assert.equal(branchMetricValue({state:'visible',value:64},'current_overall_progress'),64);
  assert.equal(branchMetricValue({state:'visible',mean_normalized_percent:55},'learning_style'),55);
  assert.equal(branchMetricValue({state:'visible',percentage:40},'assessment_completion'),40);
  assert.equal(branchMetricValue({state:'suppressed',value:99,percentage:99},'assessment_completion'),null);
});

test('Learning Style uses only four current dimensions and preserves null versus zero',()=>{
  const template=fs.readFileSync(path.join(__dirname,'..','templates','talent','workspace.html'),'utf8');
  const values=[...template.matchAll(/<option value="(verbal|non_verbal|quantitative|spatial)">/g)].map(match=>match[1]);
  assert.deepEqual(values,['verbal','non_verbal','quantitative','spatial']);
  assert.doesNotMatch(template,/Auditory|Read-Write|Kinesthetic/);
  assert.equal(branchMetricValue({state:'visible',mean_normalized_percent:null},'learning_style'),null);
  assert.equal(branchMetricValue({state:'visible',mean_normalized_percent:0},'learning_style'),0);
});

test('Evaluation Period bars keep backend period order and framework mismatch fabricates no result',()=>{
  const html=branchComparisonChart({metric:'evaluation_period_result',rows:[{branch_id:10,periods:[
    {label:'Quarter B',state:'visible',mean_normalized_percent:70},
    {label:'Custom Window',state:'visible',mean_normalized_percent:80},
  ]}]},branches);
  assert.ok(html.indexOf('Quarter B')<html.indexOf('Custom Window'));
  const mismatch=branchComparisonChart({metric:'current_overall_progress',comparability_state:'not_comparable',comparability_reason_code:'framework_changed',rows:[{branch_id:10,state:'no_data',value:null}]},branches);
  assert.match(mismatch,/framework changed/);assert.doesNotMatch(mismatch,/width:/);
});

test('M10 frontend requests selected backend metric and contains no governed aggregation or M11 work',()=>{
  const source=fs.readFileSync(path.join(__dirname,'..','static','js','talent.js'),'utf8');
  const implementation=source.slice(source.indexOf('const branchComparisonMetricOptions'),source.indexOf('const rubricLevelIntensity'));
  assert.match(source,/evaluation-progress\/programs\/\$\{encodeURIComponent\(pid\)\}/);
  // M18b-1: learning_style_dimension was a dead backend parameter (removed
  // outright - see talent_evaluation_progress_service.py's M18b-1 note) and
  // was never actually sent by this frontend module; this stale assertion
  // for a non-existent contract is removed rather than left misleading.
  assert.doesNotMatch(implementation,/\.reduce\(|\.sort\(|nominal_weight|minimum_cohort|current_placement/);
  assert.doesNotMatch(source,/students\/roster\/import|students\/roster\/export/);
});
