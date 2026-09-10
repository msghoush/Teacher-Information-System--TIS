const {test}=require('node:test');
const assert=require('node:assert/strict');
const {saveResults,context,esc,render}=require('../static/js/talent-operations.js');

function domRoot() {
  return {innerHTML:'', querySelector:()=>({textContent:'',setAttribute(){},addEventListener(){}}), querySelectorAll:()=>[]};
}

async function withWindow(work) {
  const previous=global.window;
  global.window={addEventListener(){},removeEventListener(){},confirm:()=>true};
  try {return await work();} finally {global.window=previous;}
}

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

test('Talent Review renders a compact table, not one large card per Student',async()=>{
  const root=domRoot();
  const ctx={root,year:'2026',view:'reviews',params:new URLSearchParams('cycle_id=5&program_id=11'),can:()=>true,notify(){},
    api:async path=>{
      if(path.startsWith('/api/talent/review-candidates?'))return [{id:1,academic_year_id:'2026',program_id:'11',status:'pending_review',evaluated_at:'2026-01-01',assessment_id:9,rubric_level:{id:3,label:'Inventive',display_order:40,position:4,total_levels:5},context:{student_name:'Alya <X>',program_name:'Arts',grade_level:'3',section_name:'A',cycle_title:'Term 1'}}];
      if(path.startsWith('/api/talent/official-identifications'))return [];
      throw new Error(`Unexpected ${path}`);
    }};
  await withWindow(()=>render(ctx));
  assert.match(root.innerHTML,/<table class="tp-compact-table">/);
  assert.doesNotMatch(root.innerHTML,/<article class="tp-card">/);
  assert.match(root.innerHTML,/Alya &lt;X&gt;/);
  assert.match(root.innerHTML,/Meets Program Criteria/);
  assert.match(root.innerHTML,/Inventive/);
  assert.match(root.innerHTML,/4\/5/);
  assert.doesNotMatch(root.innerHTML,/Review Candidate/);
  assert.doesNotMatch(root.innerHTML,/>Candidate</);
  assert.match(root.innerHTML,/review_id=1/);
});

test('opening one Talent Review row (review_id) shows full per-Student detail, not the list',async()=>{
  const root=domRoot();
  const row={id:1,academic_year_id:'2026',program_id:'11',status:'reviewed',evaluated_at:'2026-01-01',assessment_id:9,rubric_level:{id:3,label:'Inventive',display_order:40,position:4,total_levels:5},context:{student_name:'Alya',program_name:'Arts',grade_level:'3',section_name:'A',cycle_title:'Term 1'}};
  const ctx={root,year:'2026',view:'reviews',params:new URLSearchParams('cycle_id=5&program_id=11&review_id=1'),can:()=>true,notify(){},
    api:async path=>{
      if(path.startsWith('/api/talent/review-candidates?'))return [row];
      if(path.startsWith('/api/talent/official-identifications'))return [];
      throw new Error(`Unexpected ${path}`);
    }};
  await withWindow(()=>render(ctx));
  assert.doesNotMatch(root.innerHTML,/<table class="tp-compact-table">/);
  assert.match(root.innerHTML,/Back to Talent Review/);
  assert.match(root.innerHTML,/<article class="tp-card">/);
  assert.match(root.innerHTML,/Highest recorded rubric level/);
  assert.match(root.innerHTML,/Rubric evidence, Program Criteria, and Official Identification remain separate records/);
});

function assessmentApi(overrides={}) {
  const assessment={id:9,status:'in_progress',revision:3,program_id:11,framework_version_id:21,student_id:31,academic_year_id:'2026',kpi_result:null,context:{cycle_status:'open',student_name:'Alya',cycle_id:5},cycle_id:5,...overrides.assessment};
  const results=overrides.results ?? [{framework_competency_id:101,rubric_level_id:201,evidence:'Solid work'}];
  return async path=>{
    if(path===`/api/talent/assessments/${assessment.id}`)return assessment;
    if(path===`/api/talent/assessments/${assessment.id}/competency-results`)return results;
    if(path==='/api/talent/programs/11/frameworks/21')return {competencies:[{id:101,label:'Reading'},{id:102,label:'Writing'}]};
    if(path==='/api/talent/programs/11/frameworks/21/configuration')return {levels:[{id:201,label:'Level 1'}],descriptors:[]};
    if(path.startsWith('/api/talent/educator-inputs'))return [];
    throw new Error(`Unexpected ${path}`);
  };
}

test('an editable assessment shows Clear Result only for competencies with a saved result',async()=>{
  const root=domRoot();
  const ctx={root,year:'2026',view:'assessments',params:new URLSearchParams('assessment_id=9'),can:()=>true,notify(){},api:assessmentApi()};
  await withWindow(()=>render(ctx));
  assert.match(root.innerHTML,/data-action="clear-result"[^>]*data-competency="101"/);
  assert.doesNotMatch(root.innerHTML,/data-competency="102"[\s\S]{0,400}?data-action="clear-result"/);
  assert.match(root.innerHTML,/role="progressbar"/);
  assert.match(root.innerHTML,/tp-rubric-level/);
});

test('a completed (read-only) assessment never shows Clear Result even with a saved result',async()=>{
  const root=domRoot();
  const ctx={root,year:'2026',view:'assessments',params:new URLSearchParams('assessment_id=9'),can:()=>true,notify(){},
    api:assessmentApi({assessment:{status:'completed',context:{cycle_status:'open',student_name:'Alya',cycle_id:5}}})};
  await withWindow(()=>render(ctx));
  assert.doesNotMatch(root.innerHTML,/data-action="clear-result"/);
});

test('without manage permission, Clear Result is never offered even on a saved, editable result',async()=>{
  const root=domRoot();
  const allow=new Set(['talent_programs.view']);
  const ctx={root,year:'2026',view:'assessments',params:new URLSearchParams('assessment_id=9'),can:key=>allow.has(key),notify(){},api:assessmentApi()};
  await withWindow(()=>render(ctx));
  assert.doesNotMatch(root.innerHTML,/data-action="clear-result"/);
});

test('evaluation Student list maps Not started, In progress, and Completed to the three approved actions',async()=>{
  const root=domRoot();
  const cycle={id:61,program_id:11,title:'Term 1',status:'open',population_effective_at:'2026-01-01'};
  const members=[
    {id:101,student_name:'No Assessment Yet',grade_level:'3',section_name:'A'},
    {id:102,student_name:'Mid Way',grade_level:'3',section_name:'A'},
    {id:103,student_name:'All Done',grade_level:'3',section_name:'A'},
  ];
  const rows=[
    {id:501,cycle_population_member_id:102,status:'in_progress',academic_year_id:'2026',program_id:'11'},
    {id:502,cycle_population_member_id:103,status:'completed',academic_year_id:'2026',program_id:'11'},
  ];
  const ctx={root,year:'2026',view:'assessments',params:new URLSearchParams('cycle_id=61&program_id=11'),can:()=>true,notify(){},
    api:async path=>{
      if(path.startsWith('/api/talent/assessments?'))return rows;
      if(path.startsWith('/api/talent/assessment-cycles?'))return [cycle];
      if(path.endsWith('/population'))return {members};
      throw new Error(`Unexpected ${path}`);
    }};
  await withWindow(()=>render(ctx));
  assert.match(root.innerHTML,/<table class="tp-compact-table">/);
  assert.match(root.innerHTML,/data-action="start"[^>]*data-member="101"[^>]*>Start Assessment/);
  assert.match(root.innerHTML,/assessment_id=501[^"]*">Continue Assessment/);
  assert.match(root.innerHTML,/assessment_id=502[^"]*">View Assessment/);
  assert.match(root.innerHTML,/Assessment Records[\s\S]*<table class="tp-compact-table">/);
  assert.doesNotMatch(root.innerHTML,/Saved assessments/);
  assert.doesNotMatch(root.innerHTML,/Assessment Records[\s\S]*<article class="tp-card"><h3>Mid Way/);
});

test('arriving on Student Assessments with a Program but no cycle_id auto-opens the one Open evaluation (no extra click)',async()=>{
  const root=domRoot();
  const cycle={id:61,program_id:11,title:'Term 1',status:'open',population_effective_at:'2026-01-01'};
  const members=[{id:101,student_name:'No Assessment Yet',grade_level:'3',section_name:'A'}];
  const ctx={root,year:'2026',view:'assessments',params:new URLSearchParams('program_id=11'),can:()=>true,notify(){},
    api:async path=>{
      if(path.startsWith('/api/talent/assessments?'))return [];
      if(path.startsWith('/api/talent/assessment-cycles?'))return [cycle];
      if(path.endsWith('/population'))return {members};
      throw new Error(`Unexpected ${path}`);
    }};
  await withWindow(()=>render(ctx));
  assert.match(root.innerHTML,/Students in this evaluation/);
  assert.match(root.innerHTML,/No Assessment Yet/);
  assert.match(root.innerHTML,/Start Assessment/);
});

test('two Open Cycles for the same Program remain an explicit choice, not an auto-guess',async()=>{
  const root=domRoot();
  const cycleA={id:61,program_id:11,title:'Term 1',status:'open',population_effective_at:'2026-01-01'};
  const cycleB={id:62,program_id:11,title:'Term 2',status:'open',population_effective_at:'2026-02-01'};
  const ctx={root,year:'2026',view:'assessments',params:new URLSearchParams('program_id=11'),can:()=>true,notify(){},
    api:async path=>{
      if(path.startsWith('/api/talent/assessments?'))return [];
      if(path.startsWith('/api/talent/assessment-cycles?'))return [cycleA,cycleB];
      throw new Error(`Unexpected ${path}`);
    }};
  await withWindow(()=>render(ctx));
  assert.doesNotMatch(root.innerHTML,/Students in this evaluation/);
  assert.match(root.innerHTML,/<article class="tp-card"><h3>Term 1/);
  assert.match(root.innerHTML,/<article class="tp-card"><h3>Term 2/);
});

test('a Program with no Evaluation Cycle at all shows an honest, distinct no-open-evaluation message with a link to the Evaluation Plan',async()=>{
  const root=domRoot();
  const ctx={root,year:'2026',view:'assessments',params:new URLSearchParams('program_id=11'),can:()=>true,notify(){},
    api:async path=>{
      if(path.startsWith('/api/talent/assessments?'))return [];
      if(path.startsWith('/api/talent/assessment-cycles?'))return [];
      throw new Error(`Unexpected ${path}`);
    }};
  await withWindow(()=>render(ctx));
  assert.match(root.innerHTML,/No Evaluation Period is open for this Program/);
  assert.match(root.innerHTML,/evaluation-plans\?[^"]*program_id=11/);
  assert.match(root.innerHTML,/No Assessment Records in this context yet\./);
  assert.doesNotMatch(root.innerHTML,/No assessments saved in this context yet\./);
  assert.doesNotMatch(root.innerHTML,/Students in this evaluation/);
});

test('an open evaluation with zero frozen Students shows the real reason, not the generic no-assessments message',async()=>{
  const root=domRoot();
  const cycle={id:61,program_id:11,title:'Term 1',status:'open',population_effective_at:'2026-01-01'};
  const ctx={root,year:'2026',view:'assessments',params:new URLSearchParams('program_id=11'),can:()=>true,notify(){},
    api:async path=>{
      if(path.startsWith('/api/talent/assessments?'))return [];
      if(path.startsWith('/api/talent/assessment-cycles?'))return [cycle];
      if(path.endsWith('/population'))return {members:[]};
      throw new Error(`Unexpected ${path}`);
    }};
  await withWindow(()=>render(ctx));
  assert.match(root.innerHTML,/Students in this evaluation/);
  assert.match(root.innerHTML,/No Students were included when this evaluation started\./);
  assert.doesNotMatch(root.innerHTML,/No Evaluation Period is open for this Program/);
});

test('no Program selected (org-wide) keeps the existing multi-Cycle card chooser and never guesses a Cycle',async()=>{
  const root=domRoot();
  const cycle={id:61,program_id:11,title:'Term 1',status:'open',population_effective_at:'2026-01-01'};
  const ctx={root,year:'2026',view:'assessments',params:new URLSearchParams(),can:()=>true,notify(){},
    api:async path=>{
      if(path.startsWith('/api/talent/assessments?'))return [];
      if(path.startsWith('/api/talent/assessment-cycles?'))return [cycle];
      throw new Error(`Unexpected ${path}`);
    }};
  await withWindow(()=>render(ctx));
  assert.doesNotMatch(root.innerHTML,/Students in this evaluation/);
  assert.doesNotMatch(root.innerHTML,/No Evaluation Period is open for this Program/);
  assert.match(root.innerHTML,/<article class="tp-card"><h3>Term 1/);
});
