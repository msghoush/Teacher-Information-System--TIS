const {test}=require('node:test');
const assert=require('node:assert/strict');
const {render}=require('../static/js/talent-evaluation-workspace.js');

function fixture(allowed=true) {
  const calls=[], feedback={textContent:'',setAttribute(){}};
  const root={innerHTML:'',onclick:null,onsubmit:null,oninput:null,querySelector:()=>feedback,querySelectorAll:()=>[]};
  const ctx={root,year:'100',params:new URLSearchParams('program_id=11'),can:()=>allowed,api:async(path,options)=>{
    calls.push({path,options});
    if(path.startsWith('/api/talent/evaluation-plans?'))return [];
    if(path==='/api/talent/programs/11')return {id:11,name:'Performing Arts'};
    if(path==='/api/talent/programs')return [{id:11,name:'Performing Arts'}];
    if(path==='/api/talent/assessment-cycles?academic_year_id=100&program_id=11')return [];
    if(path.endsWith('/academic-years'))return [{id:21,academic_year_id:100,is_enabled:true}];
    if(path.endsWith('/frameworks'))return [{id:31,title:'Arts rubric',version_number:1,status:'active'}];
    if(options)return {};
    throw new Error(`Unexpected ${path}`);
  }};
  return {ctx,root,calls,feedback};
}

test('selected Evaluation Plan loads the Program directly without fetching the full Program catalog',async()=>{
  const {ctx,calls}=fixture();
  await render(ctx);
  assert.ok(calls.some(call=>call.path==='/api/talent/programs/11'),'selected Program endpoint is used');
  assert.equal(calls.filter(call=>call.path==='/api/talent/programs').length,0,'full Program catalog is not fetched for selected Evaluation Plan');
});


test('authorized empty context offers a free-text evaluation name, not a fixed picklist',async()=>{
  const {ctx,root}=fixture();await render(ctx);
  assert.match(root.innerHTML,/Add Evaluation Period/);
  assert.match(root.innerHTML,/Evaluation Period Name/);
  assert.match(root.innerHTML,/<input type="text" name="label"/);
  assert.doesNotMatch(root.innerHTML,/Baseline, Term 1, Term 2, Final/);
  assert.doesNotMatch(root.innerHTML,/How many evaluations this year\?/);
  assert.match(root.innerHTML,/current Academic Placement for eligibility/);
  assert.doesNotMatch(root.innerHTML,/cycle_id|framework_version_id|program_academic_year_configuration_id/);
});

test('read permission gates the workspace',async()=>{
  const {ctx,root,calls}=fixture(false);await render(ctx);
  assert.match(root.innerHTML,/do not have permission/);
  assert.equal(calls.length,0);
});

test('a truly branch-scoped projection explains the read-only schedule before submission',async()=>{
  const {ctx,root}=fixture();
  ctx.can=permission=>permission==='talent_evaluation_plans.view'||permission==='talent_programs.view';
  await render(ctx);
  assert.match(root.innerHTML,/read-only in your current workspace/);
  assert.match(root.innerHTML,/organization-authorized Program manager/);
  assert.doesNotMatch(root.innerHTML,/data-form="add-period"/);
  assert.doesNotMatch(root.innerHTML,/Organization or global scope/);
});

test('organization-authority failures are translated without backend scope jargon',async()=>{
  const {ctx,root,feedback}=fixture();
  const read=ctx.api;ctx.api=async(path,options)=>{if(options){const error=new Error('Organization or global scope is required.');error.code='organization_authority_required';throw error;}return read(path,options);};
  await render(ctx);
  const original=global.FormData;global.FormData=class {constructor(){return new Map([['label','Term 1']]);}};
  try {await root.onsubmit({target:{matches:selector=>selector==='form[data-form="add-period"]',dataset:{},querySelector:()=>feedback},preventDefault(){}});} finally {global.FormData=original;}
  assert.match(feedback.textContent,/don't have access to add or change Evaluation Periods/);
  assert.doesNotMatch(feedback.textContent,/Organization or global scope/);
});

test('Adding an evaluation with a user-entered name creates the plan then the named period',async()=>{
  const {ctx,root,calls}=fixture();await render(ctx);
  const original=global.FormData;global.FormData=class {constructor(){return new Map([['label','Audition']]);}};
  try {root.onsubmit({target:{matches:selector=>selector==='form[data-form="add-period"]',dataset:{},querySelector:()=>({textContent:'',setAttribute(){}})},preventDefault(){}});} finally {global.FormData=original;}
  await new Promise(resolve=>setImmediate(resolve));
  const writes=calls.filter(c=>c.options);
  assert.equal(writes[0].path,'/api/talent/evaluation-plans');
  assert.deepEqual(JSON.parse(writes[0].options.body),{program_academic_year_configuration_id:21});
  assert.equal(writes[1].path,'/api/talent/evaluation-plans/undefined/periods');
  const periodBody=JSON.parse(writes[1].options.body);
  assert.equal(periodBody.label,'Audition');
});

test('normal-path Evaluation Plan uses approved terminology without internal lifecycle vocabulary',async()=>{
  const feedback={textContent:'',setAttribute(){}};
  const period={id:41,label:'Baseline',cycle:{id:61,status:'open'},actions:['edit']};
  const plan={id:21,program_id:11,status:'active',revision:5,periods:[period]};
  const root={innerHTML:'',querySelector:()=>feedback,querySelectorAll:()=>[],classList:{add(){}},onclick:null};
  const ctx={root,year:'100',params:new URLSearchParams('program_id=11'),can:()=>true,api:async path=>{
    if(path.startsWith('/api/talent/evaluation-plans?'))return [plan];
    if(path==='/api/talent/programs')return [{id:11,name:'Arts',status:'active'}];
    if(path.startsWith('/api/talent/assessment-cycles?'))return [];
    if(path.endsWith('/academic-years'))return [{id:51,academic_year_id:100,is_enabled:true}];
    if(path.endsWith('/frameworks'))return [{id:31,status:'active'}];
    throw new Error(`Unexpected ${path}`);
  }};
  await render(ctx);
  const banned=[/Prepared evaluations/,/Ready to link/,/Link an evaluation/,/No Evaluation Plan/,/Frozen population/,
    />Plan</,/>Period</,/>Cycle</,/>Link</];
  for (const pattern of banned) assert.doesNotMatch(root.innerHTML, pattern, `must not render ${pattern}`);
  assert.match(root.innerHTML,/Evaluation Plan/);
  assert.match(root.innerHTML,/Evaluation Period/);
  assert.match(root.innerHTML,/Available/);
});

test('a Period with manage_timeline shows editable, always-visible, accessibly-labeled date inputs',async()=>{
  const feedback={textContent:'',setAttribute(){}};
  const period={id:41,label:'Baseline',cycle:null,actions:['edit','edit_timeline','remove'],planned_start_date:'2026-01-05',planned_end_date:'2026-01-20'};
  const plan={id:21,program_id:11,status:'draft',revision:5,periods:[period]};
  const root={innerHTML:'',querySelector:()=>feedback,querySelectorAll:()=>[],classList:{add(){}},onclick:null};
  const ctx={root,year:'100',params:new URLSearchParams('program_id=11'),can:()=>true,api:async path=>{
    if(path.startsWith('/api/talent/evaluation-plans?'))return [plan];
    if(path==='/api/talent/programs')return [{id:11,name:'Arts',status:'active'}];
    if(path.startsWith('/api/talent/assessment-cycles?'))return [];
    if(path.endsWith('/academic-years'))return [{id:51,academic_year_id:100,is_enabled:true}];
    if(path.endsWith('/frameworks'))return [{id:31,status:'active'}];
    throw new Error(`Unexpected ${path}`);
  }};
  await render(ctx);
  assert.match(root.innerHTML,/data-form="period-timeline"/);
  assert.match(root.innerHTML,/type="date" name="planned_start_date" value="2026-01-05"/);
  assert.match(root.innerHTML,/type="date" name="planned_end_date" value="2026-01-20"/);
  assert.match(root.innerHTML,/aria-label="Baseline start date"/);
  assert.match(root.innerHTML,/aria-label="Baseline end date"/);
});

test('a Period without manage_timeline renders dates read-only but always visible, never hidden',async()=>{
  const feedback={textContent:'',setAttribute(){}};
  const period={id:41,label:'Baseline',cycle:null,actions:['edit','remove'],planned_start_date:'2026-01-05',planned_end_date:null};
  const plan={id:21,program_id:11,status:'draft',revision:5,periods:[period]};
  const root={innerHTML:'',querySelector:()=>feedback,querySelectorAll:()=>[],classList:{add(){}},onclick:null};
  const ctx={root,year:'100',params:new URLSearchParams('program_id=11'),can:()=>true,api:async path=>{
    if(path.startsWith('/api/talent/evaluation-plans?'))return [plan];
    if(path==='/api/talent/programs')return [{id:11,name:'Arts',status:'active'}];
    if(path.startsWith('/api/talent/assessment-cycles?'))return [];
    if(path.endsWith('/academic-years'))return [{id:51,academic_year_id:100,is_enabled:true}];
    if(path.endsWith('/frameworks'))return [{id:31,status:'active'}];
    throw new Error(`Unexpected ${path}`);
  }};
  await render(ctx);
  assert.doesNotMatch(root.innerHTML,/data-form="period-timeline"/);
  assert.match(root.innerHTML,/tp-period-dates/);
  assert.match(root.innerHTML,/2026-01-05/);
  assert.match(root.innerHTML,/No end date/);
});

test('saving a Period timeline PATCHes only the two governed date fields, never mixed with content fields',async()=>{
  const calls=[],feedback={textContent:'',setAttribute(){}};
  const period={id:41,label:'Baseline',cycle:null,actions:['edit','edit_timeline'],planned_start_date:'2026-01-05',planned_end_date:'2026-01-20'};
  const plan={id:21,program_id:11,status:'draft',revision:5,periods:[period]};
  const root={innerHTML:'',querySelector:()=>feedback,querySelectorAll:()=>[],classList:{add(){}},onclick:null};
  const ctx={root,year:'100',params:new URLSearchParams('program_id=11'),can:()=>true,notify(){},api:async(path,options)=>{
    calls.push({path,options});
    if(path.startsWith('/api/talent/evaluation-plans?'))return [plan];
    if(path==='/api/talent/programs')return [{id:11,name:'Arts',status:'active'}];
    if(path.startsWith('/api/talent/assessment-cycles?'))return [];
    if(path.endsWith('/academic-years'))return [{id:51,academic_year_id:100,is_enabled:true}];
    if(path.endsWith('/frameworks'))return [{id:31,status:'active'}];
    if(options)return {plan_revision:6,period:{...period,planned_start_date:null,planned_end_date:'2026-02-01'}};
    throw new Error(`Unexpected ${path}`);
  }};
  await render(ctx);
  const broadBefore={
    programs:calls.filter(call=>!call.options&&call.path==='/api/talent/programs').length,
    annual:calls.filter(call=>!call.options&&call.path.endsWith('/academic-years')).length,
    frameworks:calls.filter(call=>!call.options&&call.path.endsWith('/frameworks')).length,
  };
  const original=global.FormData;global.FormData=class {constructor(){return new Map([['planned_start_date',''],['planned_end_date','2026-02-01']]);}};
  try {await root.onsubmit({target:{matches:selector=>selector==='form[data-form="period-timeline"]',dataset:{period:'41'},querySelector:()=>feedback},preventDefault(){}});}
  finally {global.FormData=original;}
  const write=calls.find(call=>call.options && call.path==='/api/talent/evaluation-periods/41');
  assert.ok(write,'expected a PATCH to the Period');
  const body=JSON.parse(write.options.body);
  assert.deepEqual(Object.keys(body).sort(),['expected_plan_revision','planned_end_date','planned_start_date']);
  assert.equal(body.planned_start_date,null);
  assert.equal(body.planned_end_date,'2026-02-01');
  assert.equal(calls.filter(call=>!call.options&&call.path==='/api/talent/programs').length,broadBefore.programs,'Period save does not refetch Programs');
  assert.equal(calls.filter(call=>!call.options&&call.path.endsWith('/academic-years')).length,broadBefore.annual,'Period save does not refetch annual Program configuration');
  assert.equal(calls.filter(call=>!call.options&&call.path.endsWith('/frameworks')).length,broadBefore.frameworks,'Period save does not refetch Frameworks');
});

test('Evaluation Period presentation stays simple and does not expose Draft/Open gating',()=>{
  const {stateFor}=require('../static/js/talent-evaluation-workspace.js');
  assert.equal(stateFor({status:'draft'},{status:'planned',cycle:null}),'Available');
  assert.equal(stateFor({status:'active'},{status:'planned',cycle:{status:'draft'}}),'Available');
  assert.equal(stateFor({status:'active'},{status:'planned',cycle:{status:'open'}}),'Available');
  assert.equal(stateFor({status:'active'},{status:'planned',cycle:{status:'closed'}}),'Complete');
  assert.equal(stateFor({status:'active'},{status:'cancelled',cycle:null}),'Cancelled');
});

test('Evaluation Period selection is disabled when the dedicated permission is not granted',async()=>{
  const feedback={textContent:'',setAttribute(){}};
  const period={id:41,label:'Baseline',status:'planned',cycle:{id:61,status:'open'},actions:['edit']};
  const plan={id:21,program_id:11,status:'active',revision:5,periods:[period]};
  const root={innerHTML:'',querySelector:()=>feedback,querySelectorAll:()=>[],classList:{add(){}},onclick:null};
  const ctx={root,year:'100',params:new URLSearchParams('program_id=11'),
    can:key=>key!=='talent_evaluation_plans.select_period',
    api:async path=>{
      if(path.startsWith('/api/talent/evaluation-plans?'))return [plan];
      if(path==='/api/talent/programs')return [{id:11,name:'Arts',status:'active'}];
      if(path.startsWith('/api/talent/assessment-cycles?'))return [];
      if(path.endsWith('/academic-years'))return [{id:51,academic_year_id:100,is_enabled:true}];
      if(path.endsWith('/frameworks'))return [{id:31,status:'active'}];
      throw new Error(`Unexpected ${path}`);
    }};
  await render(ctx);
  assert.doesNotMatch(root.innerHTML,/data-assess="41"/);
  assert.match(root.innerHTML,/disabled title="Evaluation Period selection is not permitted for your role"/);
});


test('Open Student Assessments creates/links only the internal context and navigates without Open Evaluation',async()=>{
  const calls=[],feedback={textContent:'',setAttribute(){}},period={id:41,label:'Baseline',status:'planned',cycle:null};
  const plan={id:21,program_id:11,status:'active',revision:5,periods:[period]};
  let navigated=null;
  const root={innerHTML:'',querySelector:()=>feedback,querySelectorAll:()=>[],classList:{add(){}},onclick:null};
  const ctx={root,year:'100',params:new URLSearchParams('program_id=11'),can:()=>true,notify(){},
    navigate:(target,extra)=>{navigated={target,extra};},
    api:async(path,options)=>{
      calls.push({path,options});
      if(path.startsWith('/api/talent/evaluation-plans?'))return [plan];
      if(path==='/api/talent/programs')return [{id:11,name:'Arts',status:'active'}];
      if(path.startsWith('/api/talent/assessment-cycles?'))return [];
      if(path.endsWith('/academic-years'))return [{id:51,academic_year_id:100,is_enabled:true}];
      if(path.endsWith('/frameworks'))return [{id:31,status:'active'}];
      if(path==='/api/talent/assessment-cycles'&&options)return {id:61,revision:1,population_effective_at:'2026-09-09T10:00:00'};
      if(path.endsWith('/link-period')&&options)return {cycle_revision:2,plan_revision:6};
      throw new Error(`Unexpected ${path}`);
    }};
  await render(ctx);
  await root.onclick({target:{closest:()=>({dataset:{assess:'41'},hasAttribute:name=>name==='data-assess'})}});
  const writes=calls.filter(call=>call.options).map(call=>call.path);
  assert.deepEqual(writes,[
    '/api/talent/assessment-cycles',
    '/api/talent/assessment-cycles/61/link-period',
  ]);
  assert.ok(!calls.some(call=>call.path.endsWith('/population/preview')));
  assert.ok(!calls.some(call=>call.path.endsWith('/open')));
  assert.deepEqual(navigated,{target:'assessments',extra:{program_id:11,cycle_id:61,academic_year_id:100}});
});


test('configured draft Framework can open Student Assessments without a separate lifecycle activation gate',async()=>{
  const feedback={textContent:'',setAttribute(){}};
  const period={id:41,label:'Term 1',status:'planned',cycle:null,actions:['edit']};
  const plan={id:21,program_id:11,status:'draft',revision:5,periods:[period]};
  const root={innerHTML:'',querySelector:()=>feedback,querySelectorAll:()=>[],classList:{add(){}},onclick:null};
  const ctx={root,year:'100',params:new URLSearchParams('program_id=11'),can:()=>true,api:async(path,options)=>{
    if(path.startsWith('/api/talent/evaluation-plans?'))return [plan];
    if(path==='/api/talent/programs')return [{id:11,name:'Arts',status:'draft'}];
    if(path.startsWith('/api/talent/assessment-cycles?'))return [];
    if(path.endsWith('/academic-years'))return [{id:51,academic_year_id:100,is_enabled:true}];
    if(path.endsWith('/frameworks'))return [{id:31,status:'draft',title:'Configured rubric'}];
    if(options)return {};
    throw new Error(`Unexpected ${path}`);
  }};
  await render(ctx);
  assert.match(root.innerHTML,/data-assess="41"/);
  assert.doesNotMatch(root.innerHTML,/activate What we assess|Activate the Program/);
});
