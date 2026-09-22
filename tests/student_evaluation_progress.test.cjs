const {test}=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const path=require('node:path');
const {renderEvaluationProgress}=require('../static/js/student-evaluation-progress.js');

const payload=(periods,overrides={})=>({
  program_id:11,academic_year_id:100,comparability_state:'comparable',
  comparability_reason_code:null,current_overall_result:80,periods,...overrides,
});
const period=(sequence,label,value,state='available')=>({
  sequence,label,result_state:state,normalized_percent:value,
  lifecycle_state:'active',framework_version_id:21,nominal_weight:1,
});

test('one active period renders its result and backend Overall Result',()=>{
  const html=renderEvaluationProgress(payload([period(1,'Term 1',80)]));
  assert.match(html,/Term 1/);assert.match(html,/80%/);assert.match(html,/Overall Result/);
});

test('two and three configured periods retain backend order and arbitrary names without weighting arithmetic',()=>{
  const html=renderEvaluationProgress(payload([
    period(1,'Semester Alpha',70),period(2,'Quarter Two',80),period(3,'Custom Review Window',90),
  ],{current_overall_result:84.67}));
  assert.ok(html.indexOf('Semester Alpha')<html.indexOf('Quarter Two'));
  assert.ok(html.indexOf('Quarter Two')<html.indexOf('Custom Review Window'));
  assert.match(html,/84\.67%/);
  assert.doesNotMatch(html,/33\.33|weighted|denominator/i);
});

test('pending is visible, is not zero, and has no numeric progress semantics',()=>{
  const html=renderEvaluationProgress(payload([
    period(1,'Term 1',75),period(2,'Term 2',null,'pending'),
  ],{current_overall_result:75}));
  const pending=html.slice(html.indexOf('Term 2'));
  assert.match(pending,/Pending/);assert.doesNotMatch(pending,/0%|aria-valuenow/);
});

test('an available backend result of exactly zero remains a real zero',()=>{
  const html=renderEvaluationProgress(payload([period(1,'Term 1',0)],{current_overall_result:0}));
  assert.match(html,/Term 1[\s\S]*0%/);assert.match(html,/Overall Result[\s\S]*0%/);
  assert.doesNotMatch(html,/Pending/);
});

test('framework mismatch preserves periods and suppresses combined number with explanation',()=>{
  const html=renderEvaluationProgress(payload([
    period(1,'Term 1',60),{...period(2,'Term 2',90),framework_version_id:22},
  ],{comparability_state:'not_comparable',comparability_reason_code:'framework_changed',current_overall_result:null}));
  assert.match(html,/Term 1[\s\S]*60%/);assert.match(html,/Term 2[\s\S]*90%/);
  assert.match(html,/framework changed/);assert.doesNotMatch(html,/aria-label="Overall Result/);
});

test('M9 frontend consumes the explicit Student contract and introduces no aggregate or governed arithmetic',()=>{
  const source=fs.readFileSync(path.join(__dirname,'..','static','js','student-evaluation-progress.js'),'utf8');
  assert.match(source,/evaluation-progress\/programs\/\$\{encodeURIComponent\(programId\)\}/);
  assert.doesNotMatch(source,/nominal_weight|\.reduce\(|branch-comparison|\/branches\/|\/organization/);
  assert.doesNotMatch(source,/\.sort\(|current_overall_result\s*=|normalized_percent\s*=/);
  const template=fs.readFileSync(path.join(__dirname,'..','templates','student_profile.html'),'utf8');
  assert.match(template,/c\.frozen_context\.section_display/);
  assert.doesNotMatch(source,/section_display|current_placement/);
});
