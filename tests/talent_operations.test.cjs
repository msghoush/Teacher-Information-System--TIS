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

test('Talent Review includes every completed assessment and keeps Candidate separate',async()=>{
  const root=domRoot();
  const rows=[
    {id:9,academic_year_id:'2026',program_id:11,status:'completed',overall_result:{available:true,average:4.2,scale_max:5,normalized_percent:84,competency_count:3},candidate:{id:1,status:'pending_review'},reassessment:{required:false},context:{student_name:'Alya <X>',program_name:'Arts',grade_level:'3',section_name:'A',cycle_title:'Term 1'}},
    {id:10,academic_year_id:'2026',program_id:11,status:'completed',overall_result:{available:true,average:3.4,scale_max:5,normalized_percent:68,competency_count:3},candidate:null,reassessment:{required:false},context:{student_name:'Omar',program_name:'Arts',grade_level:'3',section_name:'A',cycle_title:'Term 1'}},
  ];
  const ctx={root,year:'2026',view:'reviews',params:new URLSearchParams('cycle_id=5&program_id=11'),can:()=>true,notify(){},
    api:async path=>{
      if(path.startsWith('/api/talent/review-candidates/workspace?'))return rows;
      if(path==='/api/talent/programs')return [];
      if(path.startsWith('/api/talent/official-identifications'))return [];
      throw new Error(`Unexpected ${path}`);
    }};
  await withWindow(()=>render(ctx));
  assert.match(root.innerHTML,/<table class="tp-compact-table tp-review-table">/);
  assert.match(root.innerHTML,/Alya &lt;X&gt;/);
  assert.match(root.innerHTML,/Omar/);
  assert.match(root.innerHTML,/Overall Program Result 4\.2 out of 5/);
  assert.doesNotMatch(root.innerHTML,/Meets criteria|No candidate/);
  assert.match(root.innerHTML,/Review status/);
  assert.match(root.innerHTML,/review_id=9/);
  assert.match(root.innerHTML,/review_id=10/);
});

test('opening one Talent Review assessment shows result and separate human decision boundary',async()=>{
  const root=domRoot();
  const row={id:9,academic_year_id:'2026',program_id:11,status:'completed',overall_result:{available:true,average:4.4,scale_max:5,normalized_percent:88,competency_count:4},candidate:{id:1,status:'reviewed'},reassessment:{required:false},context:{student_name:'Alya',program_name:'Arts',grade_level:'3',section_name:'A',cycle_title:'Term 1'}};
  const ctx={root,year:'2026',view:'reviews',params:new URLSearchParams('cycle_id=5&program_id=11&review_id=9'),can:()=>true,notify(){},
    api:async path=>{
      if(path.startsWith('/api/talent/review-candidates/workspace?'))return [row];
      if(path==='/api/talent/programs')return [];
      if(path.startsWith('/api/talent/official-identifications'))return [];
      throw new Error(`Unexpected ${path}`);
    }};
  await withWindow(()=>render(ctx));
  assert.doesNotMatch(root.innerHTML,/<table class="tp-compact-table/);
  assert.match(root.innerHTML,/Back to Talent Review/);
  assert.match(root.innerHTML,/Overall Program Result 4\.4 out of 5/);
  assert.doesNotMatch(root.innerHTML,/Meets configured criteria/);
  assert.match(root.innerHTML,/Review status/);
  assert.match(root.innerHTML,/Official Identification remains a separate authorized human decision/);
});

function assessmentApi(overrides={}) {
  const assessment={id:9,status:'in_progress',revision:3,program_id:11,framework_version_id:21,student_id:31,academic_year_id:'2026',kpi_result:null,overall_result:null,context:{cycle_status:'open',student_name:'Alya',cycle_id:5},cycle_id:5,...overrides.assessment};
  const results=overrides.results ?? [{framework_competency_id:101,rubric_level_id:201,evidence:'Solid work'}];
  return async path=>{
    if(path===`/api/talent/assessments/${assessment.id}`)return assessment;
    if(path===`/api/talent/assessments/${assessment.id}/continue`)return assessment;
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

test('opened Student Assessment shows a Back to Students action preserving Academic Year, Program, and Evaluation context',async()=>{
  const root=domRoot();
  const ctx={root,year:'2026',view:'assessments',params:new URLSearchParams('assessment_id=9'),can:()=>true,notify(){},
    api:assessmentApi({assessment:{academic_year_id:'2026',program_id:11,cycle_id:5,evaluation_context_cycle_id:5,context:{cycle_status:'open',student_name:'Alya',cycle_id:5}}})};
  await withWindow(()=>render(ctx));
  assert.match(root.innerHTML,/class="tp-back-link"[^>]*>← Back to Students</);
  const [,hrefValue]=root.innerHTML.match(/class="tp-back-link" href="([^"]*)"/)||[];
  assert.ok(hrefValue,'Back to Students link must be present');
  const href=hrefValue.replace(/&amp;/g,'&');
  assert.match(href,/\/talent\/assessments\?/);
  assert.doesNotMatch(href,/assessment_id=/);
  assert.match(href,/academic_year_id=2026/);
  assert.match(href,/program_id=11/);
  assert.match(href,/cycle_id=5/);
});

test('assessment rubric uses the descriptor for the Student historical Grade',async()=>{
  const root=domRoot();
  const base=assessmentApi({assessment:{context:{cycle_status:'open',student_name:'Alya',cycle_id:5,grade_level:'2'}}});
  const ctx={root,year:'2026',view:'assessments',params:new URLSearchParams('assessment_id=9'),can:()=>true,notify(){},
    api:async path=>{
      if(path==='/api/talent/programs/11/frameworks/21/configuration')return {
        levels:[{id:201,label:'Level 1'}],
        descriptors:[
          {framework_competency_id:101,rubric_level_id:201,grade_level:'1',descriptor:'Grade 1 wording'},
          {framework_competency_id:101,rubric_level_id:201,grade_level:'2',descriptor:'Grade 2 wording'},
          {framework_competency_id:102,rubric_level_id:201,grade_level:null,descriptor:'General fallback'}
        ]
      };
      return base(path);
    }};
  await withWindow(()=>render(ctx));
  assert.match(root.innerHTML,/Grade 2 wording/);
  assert.doesNotMatch(root.innerHTML,/Grade 1 wording/);
  // The exact historical-Grade descriptor wins; unrelated fallback content
  // from another competency is intentionally not rendered.
  assert.doesNotMatch(root.innerHTML,/General fallback/);
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
  assert.doesNotMatch(root.innerHTML,/Assessment Records|<p class="tp-eyebrow">History<\/p>/);
});

test('completed Student with a changed rubric is surfaced as Re-evaluation required',async()=>{
  const root=domRoot();
  const cycle={id:61,program_id:11,title:'Term 1',status:'open',population_effective_at:'2026-01-01'};
  const members=[{student_id:103,student_name:'Needs Update',grade_level:'3',section_name:'A'}];
  const rows=[{
    id:502,student_id:103,cycle_population_member_id:103,status:'completed',is_current:true,
    academic_year_id:'2026',program_id:'11',
    reassessment:{required:true,framework_version_id:44,framework_version_number:3,historical:false},
    actions:['reassess']
  }];
  const ctx={root,year:'2026',view:'assessments',params:new URLSearchParams('cycle_id=61&program_id=11'),can:()=>true,notify(){},
    api:async path=>{
      if(path.startsWith('/api/talent/assessments?'))return rows;
      if(path.startsWith('/api/talent/assessments/contexts?'))return [cycle];
      if(path.endsWith('/eligible-students'))return {members};
      throw new Error(`Unexpected ${path}`);
    }};
  await withWindow(()=>render(ctx));
  assert.match(root.innerHTML,/Re-evaluation required/);
  assert.match(root.innerHTML,/data-action="reassess-row"[^>]*data-id="502"/);
  assert.doesNotMatch(root.innerHTML,/data-action="start"[^>]*data-student="103"/);
});

test('completed Student can expose the evidence-preserving Reset for Re-assessment action',async()=>{
  const root=domRoot();
  const cycle={id:61,program_id:11,title:'Term 1',evaluation_label:'Term 1',status:'open'};
  const members=[{student_id:103,student_name:'All Done',grade_level:'3',section_name:'A'}];
  const rows=[{id:502,student_id:103,status:'completed',is_current:true,academic_year_id:'2026',program_id:'11',reassessment:{required:false},actions:['reset_for_reassessment']}];
  const ctx={root,year:'2026',view:'assessments',params:new URLSearchParams('cycle_id=61&program_id=11'),can:()=>true,notify(){},
    api:async path=>{
      if(path.startsWith('/api/talent/assessments?'))return rows;
      if(path.startsWith('/api/talent/assessments/contexts?'))return [cycle];
      if(path.endsWith('/eligible-students'))return {members};
      throw new Error(`Unexpected ${path}`);
    }};
  await withWindow(()=>render(ctx));
  assert.match(root.innerHTML,/Reset for Re-assessment/);
  assert.match(root.innerHTML,/Selected Evaluation Period/);
  assert.match(root.innerHTML,/is-selected/);
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
  assert.match(root.innerHTML,/Evaluation Period/);
  assert.match(root.innerHTML,/Term 1/);
  assert.match(root.innerHTML,/Term 2/);
  assert.match(root.innerHTML,/View eligible Students and assessment status/);
});

test('configured Program inside an Evaluation Period is selectable without leaving Student Assessments',async()=>{
  const root=domRoot();
  let plannedButton,clickHandler;
  plannedButton={
    dataset:{program:'11',period:'51',planRevision:'3',label:'Term 1'},
    addEventListener:(type,cb)=>{if(type==='click')clickHandler=cb;}
  };
  root.querySelectorAll=selector=>selector==='[data-action="select-planned-evaluation"]'?[plannedButton]:[];
  const calls=[];let navigated=null;
  const ctx={root,year:'2026',view:'assessments',params:new URLSearchParams(),can:()=>true,notify(){},
    navigate:(target,extra)=>{navigated={target,extra};},
    api:async(path,options)=>{
      calls.push({path,options});
      if(path.startsWith('/api/talent/assessments?'))return [];
      if(path.startsWith('/api/talent/assessments/contexts?'))return [];
      if(path==='/api/talent/programs')return [{id:11,name:'Qaida Nourania'}];
      if(path.startsWith('/api/talent/evaluation-plans?'))return [{id:41,program_id:11,academic_year_id:2026,revision:3,status:'active',periods:[{id:51,label:'Term 1',sequence:1,status:'planned'}]}];
      if(path==='/api/talent/programs/11/frameworks')return [{id:31,status:'active'}];
      if(path==='/api/talent/assessment-cycles'&&options?.method==='POST')return {id:61,revision:1};
      if(path==='/api/talent/assessment-cycles/61/link-period'&&options?.method==='POST')return {cycle_revision:2};
      throw new Error(`Unexpected ${path}`);
    }};
  await withWindow(()=>render(ctx));
  assert.match(root.innerHTML,/Select this Program for Term 1 and view eligible Students/);
  assert.equal(typeof clickHandler,'function');
  await clickHandler();
  const create=calls.find(item=>item.path==='/api/talent/assessment-cycles'&&item.options?.method==='POST');
  assert.deepEqual(create.options.body,{
    program_id:11,academic_year_id:2026,framework_version_id:31,
    title:'Term 1',population_effective_at:create.options.body.population_effective_at
  });
  const link=calls.find(item=>item.path==='/api/talent/assessment-cycles/61/link-period');
  assert.deepEqual(link.options.body,{planned_period_id:51,expected_plan_revision:3,expected_cycle_revision:1});
  assert.deepEqual(navigated,{target:'assessments',extra:{cycle_id:61,program_id:11,academic_year_id:2026}});
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
  assert.doesNotMatch(root.innerHTML,/Assessment Records|No assessments saved in this context yet\./);
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
  assert.match(root.innerHTML,/Evaluation Period/);
  assert.match(root.innerHTML,/Term 1/);
});

test('same Evaluation label groups multiple Programs under one Period section',async()=>{
  const root=domRoot();
  const contexts=[
    {id:61,program_id:11,title:'Term 1',evaluation_period_id:501,evaluation_label:'Term 1',evaluation_sequence:1},
    {id:63,program_id:11,title:'Term 1 duplicate physical cycle',evaluation_period_id:501,evaluation_label:'Term 1',evaluation_sequence:1},
    {id:71,program_id:12,title:'Term 1',evaluation_period_id:601,evaluation_label:'Term 1',evaluation_sequence:1},
    {id:62,program_id:11,title:'Term 2',evaluation_period_id:502,evaluation_label:'Term 2',evaluation_sequence:2},
  ];
  const ctx={root,year:'2026',view:'assessments',params:new URLSearchParams(),can:()=>true,notify(){},
    api:async path=>{
      if(path.startsWith('/api/talent/assessments?'))return [];
      if(path.startsWith('/api/talent/assessments/contexts?'))return contexts;
      if(path==='/api/talent/programs')return [{id:11,name:'Mental Math'},{id:12,name:'Performing Arts'}];
      throw new Error(`Unexpected ${path}`);
    }};
  await withWindow(()=>render(ctx));
  assert.equal((root.innerHTML.match(/<h3>Term 1<\/h3>/g)||[]).length,1);
  assert.equal((root.innerHTML.match(/<strong>Mental Math<\/strong>/g)||[]).length,2,'Mental Math appears once in Term 1 and once in Term 2, never twice in the same Period');
  assert.match(root.innerHTML,/Performing Arts/);
  assert.match(root.innerHTML,/2 Programs/);
});

test('configured Evaluation Periods appear once per Program even before a physical Cycle exists',async()=>{
  const root=domRoot();
  const contexts=[
    {id:61,program_id:11,title:'Term 1',evaluation_period_id:501,evaluation_label:'Term 1',evaluation_sequence:1},
  ];
  const plans=[
    {id:41,program_id:11,academic_year_id:2026,status:'active',revision:3,periods:[{id:501,label:'Term 1',sequence:1,status:'planned'}]},
    {id:42,program_id:12,academic_year_id:2026,status:'active',revision:2,periods:[{id:601,label:'Term 1',sequence:1,status:'planned'}]},
  ];
  const ctx={root,year:'2026',view:'assessments',params:new URLSearchParams(),can:()=>true,notify(){},
    api:async path=>{
      if(path.startsWith('/api/talent/assessments?'))return [];
      if(path.startsWith('/api/talent/assessments/contexts?'))return contexts;
      if(path.startsWith('/api/talent/evaluation-plans?'))return plans;
      if(path==='/api/talent/programs')return [{id:11,name:'Mental Math'},{id:12,name:'Qaida Nourania'}];
      throw new Error(`Unexpected ${path}`);
    }};
  await withWindow(()=>render(ctx));
  assert.equal((root.innerHTML.match(/<h3>Term 1<\/h3>/g)||[]).length,1);
  assert.equal((root.innerHTML.match(/<strong>Mental Math<\/strong>/g)||[]).length,1);
  assert.equal((root.innerHTML.match(/<strong>Qaida Nourania<\/strong>/g)||[]).length,1);
  assert.match(root.innerHTML,/2 Programs/);
  assert.match(root.innerHTML,/Qaida Nourania[\s\S]*Evaluation configured · open the plan to start Student Assessments/);
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
  assert.deepEqual(navigated,{target:'assessments',extra:{assessment_id:701,cycle_id:71,academic_year_id:'2026',program_id:'11'}});
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
  assert.deepEqual(navigated,{target:'assessments',extra:{assessment_id:701,cycle_id:61,academic_year_id:'2026',program_id:'11'}});
});


test('assessment renders only competencies assigned to the Student historical Grade',async()=>{
  const root=domRoot();
  const base=assessmentApi({assessment:{context:{cycle_status:'open',student_name:'Alya',cycle_id:5,grade_level:'2'}},results:[]});
  const ctx={root,year:'2026',view:'assessments',params:new URLSearchParams('assessment_id=9'),can:()=>true,notify(){},
    api:async path=>{
      if(path==='/api/talent/programs/11/frameworks/21')return {competencies:[
        {id:101,label:'Grade 1 Mental Calculation',grade_level:'1'},
        {id:102,label:'Grade 2 Mental Calculation',grade_level:'2'},
        {id:103,label:'Shared Strategy',grade_level:null}
      ]};
      if(path==='/api/talent/programs/11/frameworks/21/configuration')return {levels:[{id:201,label:'Level 1'}],descriptors:[]};
      return base(path);
    }};
  await withWindow(()=>render(ctx));
  assert.doesNotMatch(root.innerHTML,/Grade 1 Mental Calculation/);
  assert.match(root.innerHTML,/Grade 2 Mental Calculation/);
  assert.match(root.innerHTML,/Shared Strategy/);
});


test('completed assessment shows rubric-scale overall Program result without implying identification',async()=>{
  const root=domRoot();
  const ctx={root,year:'2026',view:'assessments',params:new URLSearchParams('assessment_id=9'),can:()=>true,notify(){},
    api:assessmentApi({assessment:{status:'completed',overall_result:{available:true,average:3.6,scale_max:5,normalized_percent:72,competency_count:3},context:{cycle_status:'open',student_name:'Alya',cycle_id:5}}})};
  await withWindow(()=>render(ctx));
  assert.match(root.innerHTML,/Overall Program Result/);
  assert.match(root.innerHTML,/Overall Program Result 3\.6 out of 5/);
  assert.doesNotMatch(root.innerHTML,/Officially identified/);
});

test('Student roster prefers newest current attempt so Completed is not masked by older In Progress',async()=>{
  const root=domRoot();
  const cycle={id:61,program_id:11,title:'Term 1',evaluation_label:'Term 1',status:'open'};
  const members=[{student_id:103,student_name:'All Done',grade_level:'3',section_name:'A'}];
  const rows=[
    {id:501,student_id:103,status:'in_progress',is_current:true,academic_year_id:'2026',program_id:'11',evaluation_context_cycle_id:61},
    {id:502,student_id:103,status:'completed',is_current:true,academic_year_id:'2026',program_id:'11',evaluation_context_cycle_id:61,reassessment:{required:false},actions:[]},
  ];
  const ctx={root,year:'2026',view:'assessments',params:new URLSearchParams('cycle_id=61&program_id=11'),can:()=>true,notify(){},
    api:async path=>{
      if(path.startsWith('/api/talent/assessments?'))return rows;
      if(path.startsWith('/api/talent/assessments/contexts?'))return [cycle];
      if(path.endsWith('/eligible-students'))return {members};
      throw new Error(`Unexpected ${path}`);
    }};
  await withWindow(()=>render(ctx));
  assert.match(root.innerHTML,/Completed/);
  assert.match(root.innerHTML,/assessment_id=502[^"]*">View Assessment/);
  assert.doesNotMatch(root.innerHTML,/assessment_id=501[^"]*">Continue Assessment/);
});
