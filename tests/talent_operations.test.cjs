const {test}=require('node:test');
const assert=require('node:assert/strict');
const {saveResults,context,esc}=require('../static/js/talent-operations.js');

test('multiple result writes consume each returned assessment revision',async()=>{
  const calls=[],saved=[];
  const api=async(path,options)=>{
    const body=options.body;calls.push({path,body});
    const revision=body.expected_revision+1;
    return {result:{framework_competency_id:Number(path.split('/').at(-1)),rubric_level_id:body.rubric_level_id,evidence:body.evidence},assessment:{id:9,revision}};
  };
  const result=await saveResults(api,{id:9,revision:4},[
    {framework_competency_id:71,rubric_level_id:81,evidence:'First'},
    {framework_competency_id:72,rubric_level_id:82,evidence:'Second'},
  ],(row,assessment)=>saved.push([row.framework_competency_id,assessment.revision]));
  assert.deepEqual(calls.map(c=>c.body.expected_revision),[4,5]);
  assert.deepEqual(saved,[[71,5],[72,6]]);
  assert.equal(result.revision,6);
});

test('a stale write stops the sequence and reports only earlier saved entries',async()=>{
  const calls=[],saved=[];
  const stale=Object.assign(new Error('Assessment changed elsewhere.'),{status:409});
  const api=async(path,options)=>{
    calls.push(options.body.expected_revision);
    if(calls.length===2)throw stale;
    return {result:{framework_competency_id:71},assessment:{id:9,revision:8}};
  };
  await assert.rejects(()=>saveResults(api,{id:9,revision:7},[
    {framework_competency_id:71,rubric_level_id:81,evidence:'Saved'},
    {framework_competency_id:72,rubric_level_id:82,evidence:'Stale'},
    {framework_competency_id:73,rubric_level_id:83,evidence:'Must not run'},
  ],row=>saved.push(row.framework_competency_id)),error=>error===stale);
  assert.deepEqual(calls,[7,8]);
  assert.deepEqual(saved,[71]);
});

test('assessment context uses escaped names and frozen placement labels',()=>{
  const html=context({context:{student_name:'A <Learner>',program_name:'<Arts>',academic_year_name:'2026-27',cycle_title:'Autumn',cycle_status:'open',framework_title:'Rubric',framework_version_number:2,branch_name:'North',grade_level:'1',section_name:'A'}});
  assert.match(html,/&lt;Arts&gt;/);
  assert.match(html,/Historical placement: North .* Grade 1 .* A/);
  assert.doesNotMatch(html,/student_id|cycle_id|framework_competency_id|rubric_level_id/);
  assert.equal(esc('<script>'),'&lt;script&gt;');
});
