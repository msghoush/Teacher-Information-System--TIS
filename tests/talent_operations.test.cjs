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

test('completed assessment does not expose the removed Check Program Criteria action',async()=>{
  const root=domRoot();
  const ctx={root,year:'2026',view:'assessments',params:new URLSearchParams('assessment_id=9'),can:()=>true,notify(){},
    api:assessmentApi({assessment:{status:'completed',context:{cycle_status:'open',student_name:'Alya',cycle_id:5}}})};
  await withWindow(()=>render(ctx));
  assert.doesNotMatch(root.innerHTML,/Check Program Criteria|data-action="evaluate"/);
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
    {student_id:101,student_name:'No Assessment Yet',grade_level:'3',section_name:'A'},
    {student_id:102,student_name:'Mid Way',grade_level:'3',section_name:'A'},
    {student_id:103,student_name:'All Done',grade_level:'3',section_name:'A'},
  ];
  const rows=[
    {id:501,student_id:102,cycle_population_member_id:102,status:'in_progress',academic_year_id:'2026',program_id:'11'},
    {id:502,student_id:103,cycle_population_member_id:103,status:'completed',academic_year_id:'2026',program_id:'11'},
  ];
  const ctx={root,year:'2026',view:'assessments',params:new URLSearchParams('cycle_id=61&program_id=11'),can:()=>true,notify(){},
    api:async path=>{
      if(path.startsWith('/api/talent/assessments?'))return rows;
      if(path.startsWith('/api/talent/assessments/contexts?'))return [cycle];
      if(path.endsWith('/eligible-students'))return {members};
      throw new Error(`Unexpected ${path}`);
    }};
  await withWindow(()=>render(ctx));
  assert.match(root.innerHTML,/<table class="tp-compact-table">/);
  assert.match(root.innerHTML,/data-action="start"[^>]*data-student="101"[^>]*>Start Assessment/);
  assert.match(root.innerHTML,/assessment_id=501[^"]*">Continue Assessment/);
  assert.match(root.innerHTML,/assessment_id=502[^"]*">View Assessment/);
  assert.match(root.innerHTML,/Assessment Records[\s\S]*<table class="tp-compact-table">/);
  assert.doesNotMatch(root.innerHTML,/Saved assessments/);
  assert.doesNotMatch(root.innerHTML,/Assessment Records[\s\S]*<article class="tp-card"><h3>Mid Way/);
});

test('ADR 0034: Assessment Records offers Delete only when the backend-computed actions array allows it',async()=>{
  const root=domRoot();
  const cycle={id:61,program_id:11,title:'Term 1',status:'open',population_effective_at:'2026-01-01'};
  const members=[{id:103,student_name:'All Done',grade_level:'3',section_name:'A'}];
  const rows=[{id:502,cycle_population_member_id:103,status:'completed',academic_year_id:'2026',program_id:'11',actions:['delete']}];
  const ctx={root,year:'2026',view:'assessments',params:new URLSearchParams('cycle_id=61&program_id=11'),can:()=>true,notify(){},
    api:async path=>{
      if(path.startsWith('/api/talent/assessments?'))return rows;
      if(path.startsWith('/api/talent/assessments/contexts?'))return [cycle];
      if(path.endsWith('/eligible-students'))return {members};
      throw new Error(`Unexpected ${path}`);
    }};
  await withWindow(()=>render(ctx));
  assert.match(root.innerHTML,/data-action="delete-assessment"[^>]*data-id="502"/);
});

test('ADR 0034: Assessment Records omits Delete when the backend-computed actions array does not allow it',async()=>{
  const root=domRoot();
  const cycle={id:61,program_id:11,title:'Term 1',status:'open',population_effective_at:'2026-01-01'};
  const members=[{id:102,student_name:'Mid Way',grade_level:'3',section_name:'A'}];
  const rows=[{id:501,cycle_population_member_id:102,status:'in_progress',academic_year_id:'2026',program_id:'11',actions:[]}];
  const ctx={root,year:'2026',view:'assessments',params:new URLSearchParams('cycle_id=61&program_id=11'),can:()=>true,notify(){},
    api:async path=>{
      if(path.startsWith('/api/talent/assessments?'))return rows;
      if(path.startsWith('/api/talent/assessments/contexts?'))return [cycle];
      if(path.endsWith('/eligible-students'))return {members};
      throw new Error(`Unexpected ${path}`);
    }};
  await withWindow(()=>render(ctx));
  assert.doesNotMatch(root.innerHTML,/data-action="delete-assessment"/);
});

test('arriving on Student Assessments with one Evaluation context shows its enrolled Students directly',async()=>{
  const root=domRoot();
  const cycle={id:61,program_id:11,title:'Term 1',status:'open',population_effective_at:'2026-01-01'};
  const members=[{student_id:501,student_name:'No Assessment Yet',grade_level:'3',section_name:'A'}];
  const ctx={root,year:'2026',view:'assessments',params:new URLSearchParams('program_id=11'),can:()=>true,notify(){},
    api:async path=>{
      if(path.startsWith('/api/talent/assessments?'))return [];
      if(path.startsWith('/api/talent/assessments/contexts?'))return [cycle];
      if(path.endsWith('/eligible-students'))return {members};
      throw new Error(`Unexpected ${path}`);
    }};
  await withWindow(()=>render(ctx));
  assert.match(root.innerHTML,/Students/);
  assert.match(root.innerHTML,/No Assessment Yet/);
  assert.match(root.innerHTML,/Start Assessment/);
});

test('two Evaluation contexts for the same Program remain an explicit choice, not an auto-guess',async()=>{
  const root=domRoot();
  const cycleA={id:61,program_id:11,title:'Term 1',status:'open',population_effective_at:'2026-01-01'};
  const cycleB={id:62,program_id:11,title:'Term 2',status:'open',population_effective_at:'2026-02-01'};
  const ctx={root,year:'2026',view:'assessments',params:new URLSearchParams('program_id=11'),can:()=>true,notify(){},
    api:async path=>{
      if(path.startsWith('/api/talent/assessments?'))return [];
      if(path.startsWith('/api/talent/assessments/contexts?'))return [cycleA,cycleB];
      throw new Error(`Unexpected ${path}`);
    }};
  await withWindow(()=>render(ctx));
  assert.match(root.innerHTML,/View Students/);
  assert.match(root.innerHTML,/<article class="tp-card"><h3>Term 1/);
  assert.match(root.innerHTML,/<article class="tp-card"><h3>Term 2/);
});

test('a Program with no Evaluation context shows an honest message with a link to the Evaluation Plan',async()=>{
  const root=domRoot();
  const ctx={root,year:'2026',view:'assessments',params:new URLSearchParams('program_id=11'),can:()=>true,notify(){},
    api:async path=>{
      if(path.startsWith('/api/talent/assessments?'))return [];
      if(path.startsWith('/api/talent/assessments/contexts?'))return [];
      throw new Error(`Unexpected ${path}`);
    }};
  await withWindow(()=>render(ctx));
  assert.match(root.innerHTML,/No Evaluation Period is available for this Program/);
  assert.match(root.innerHTML,/evaluation-plans\?[^"]*program_id=11/);
  assert.match(root.innerHTML,/No Assessment Records in this context yet\./);
  assert.doesNotMatch(root.innerHTML,/No assessments saved in this context yet\./);
  assert.doesNotMatch(root.innerHTML,/Students/);
});

test('an Evaluation with zero currently eligible Students shows the enrollment-based empty state',async()=>{
  const root=domRoot();
  const cycle={id:61,program_id:11,title:'Term 1',status:'open',population_effective_at:'2026-01-01'};
  const ctx={root,year:'2026',view:'assessments',params:new URLSearchParams('program_id=11'),can:()=>true,notify(){},
    api:async path=>{
      if(path.startsWith('/api/talent/assessments?'))return [];
      if(path.startsWith('/api/talent/assessments/contexts?'))return [cycle];
      if(path.endsWith('/eligible-students'))return {members:[]};
      throw new Error(`Unexpected ${path}`);
    }};
  await withWindow(()=>render(ctx));
  assert.match(root.innerHTML,/Students/);
  assert.match(root.innerHTML,/No currently enrolled Students match this Program and Academic Year\./);
  assert.doesNotMatch(root.innerHTML,/No Evaluation Period is available for this Program/);
});

test('no Program selected keeps the Evaluation card chooser and never guesses a context',async()=>{
  const root=domRoot();
  const cycle={id:61,program_id:11,title:'Term 1',status:'open',population_effective_at:'2026-01-01'};
  const ctx={root,year:'2026',view:'assessments',params:new URLSearchParams(),can:()=>true,notify(){},
    api:async path=>{
      if(path.startsWith('/api/talent/assessments?'))return [];
      if(path.startsWith('/api/talent/assessments/contexts?'))return [cycle];
      throw new Error(`Unexpected ${path}`);
    }};
  await withWindow(()=>render(ctx));
  assert.doesNotMatch(root.innerHTML,/<h3>Students<\/h3>/);
  assert.doesNotMatch(root.innerHTML,/No Evaluation Period is available for this Program/);
  assert.match(root.innerHTML,/<article class="tp-card"><h3>Term 1/);
});

test('a Draft legacy Cycle does not block enrolled Students from assessment',async()=>{
  const root=domRoot();
  const cycle={id:71,program_id:11,title:'Term 1',status:'draft',revision:2,population_effective_at:'2026-01-01'};
  const eligible={cycle_id:71,eligibility_state:'live_academic_placement',count:1,members:[{student_id:501,student_name:'Grade 3 Learner',grade_level:'3',section_name:'A'}]};
  const ctx={root,year:'2026',view:'assessments',params:new URLSearchParams('cycle_id=71&program_id=11'),can:()=>true,notify(){},
    api:async path=>{
      if(path.startsWith('/api/talent/assessments?'))return [];
      if(path.startsWith('/api/talent/assessments/contexts?'))return [cycle];
      if(path.endsWith('/eligible-students'))return eligible;
      throw new Error(`Unexpected ${path}`);
    }};
  await withWindow(()=>render(ctx));
  assert.match(root.innerHTML,/Grade 3 Learner/);
  assert.match(root.innerHTML,/Not started/);
  assert.match(root.innerHTML,/Start Assessment/);
  assert.doesNotMatch(root.innerHTML,/Open Evaluation/);
  assert.doesNotMatch(root.innerHTML,/frozen/i);
});

test('Start Assessment posts cycle_id plus student_id directly without a population-member prerequisite',async()=>{
  const root=domRoot();
  const cycle={id:71,program_id:11,title:'Term 1',status:'draft',revision:2,population_effective_at:'2026-01-01'};
  const eligible={cycle_id:71,eligibility_state:'live_academic_placement',count:1,members:[{student_id:501,student_name:'Grade 3 Learner',grade_level:'3',section_name:'A'}]};
  let startButton,clickHandler;
  startButton={dataset:{student:'501'},addEventListener:(type,cb)=>{if(type==='click')clickHandler=cb;}};
  root.querySelectorAll=selector=>selector==='[data-action="start"]'?[startButton]:[];
  const calls=[]; let navigated=null;
  const ctx={root,year:'2026',view:'assessments',params:new URLSearchParams('cycle_id=71&program_id=11'),can:()=>true,notify(){},
    navigate:(target,extra)=>{navigated={target,extra};},
    api:async(path,options)=>{
      calls.push({path,options});
      if(path.startsWith('/api/talent/assessments?'))return [];
      if(path.startsWith('/api/talent/assessments/contexts?'))return [cycle];
      if(path.endsWith('/eligible-students'))return eligible;
      if(path==='/api/talent/assessments'&&options?.method==='POST')return {id:701,academic_year_id:'2026'};
      throw new Error(`Unexpected ${path}`);
    }};
  await withWindow(()=>render(ctx));
  assert.equal(typeof clickHandler,'function');
  await clickHandler();
  const call=calls.find(item=>item.path==='/api/talent/assessments'&&item.options?.method==='POST');
  assert.deepEqual(call.options.body,{cycle_id:71,student_id:501});
  assert.deepEqual(navigated,{target:'assessments',extra:{assessment_id:701,academic_year_id:'2026',program_id:'11'}});
});

test('starting an assessment carries the current Program forward in the resulting navigation (no ribbon/content mismatch)',async()=>{
  const root=domRoot();
  const cycle={id:61,program_id:11,title:'Term 1',status:'open',population_effective_at:'2026-01-01'};
  const members=[{id:101,student_name:'No Assessment Yet',grade_level:'3',section_name:'A'}];
  let startButton,clickHandler;
  startButton={dataset:{student:'501'},addEventListener:(type,cb)=>{if(type==='click')clickHandler=cb;}};
  root.querySelectorAll=selector=>selector==='[data-action="start"]'?[startButton]:[];
  let navigated=null;
  const ctx={root,year:'2026',view:'assessments',params:new URLSearchParams('program_id=11'),can:()=>true,notify(){},
    navigate:(target,extra)=>{navigated={target,extra};},
    api:async(path,options)=>{
      if(path.startsWith('/api/talent/assessments?'))return [];
      if(path.startsWith('/api/talent/assessments/contexts?'))return [cycle];
      if(path.endsWith('/eligible-students'))return {members};
      if(path==='/api/talent/assessments'&&options?.method==='POST')return {id:701,academic_year_id:'2026'};
      throw new Error(`Unexpected ${path}`);
    }};
  await withWindow(()=>render(ctx));
  assert.equal(typeof clickHandler,'function');
  await clickHandler();
  assert.deepEqual(navigated,{target:'assessments',extra:{assessment_id:701,academic_year_id:'2026',program_id:'11'}});
});
