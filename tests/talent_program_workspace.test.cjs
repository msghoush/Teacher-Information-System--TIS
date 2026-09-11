const {test}=require('node:test');
const assert=require('node:assert/strict');
const {render,kpiComponents,logoInitials,logoBadge}=require('../static/js/talent-program-workspace.js');
function fixture(allowed=true,status='draft',{logoUrl=null,configuredGrades=['1','2'],step='basics',hash='',complete=false,yearLabel='2026–2027'}={}) {
  const calls=[], feedback={textContent:'',setAttribute(){}}, root={innerHTML:'',querySelector:()=>feedback,querySelectorAll:()=>[]};
  const framework={id:31,title:'Arts & <expression>',status,version_number:2,revision:7,semantic_fingerprint:'fingerprint',competencies:[{id:71,competency_id:61,label:'Expression',description:'<script>unsafe</script>'}]};
  const config={levels:[{id:81,code:'READY',label:'Stage ready',numeric_value:null}],descriptors:complete?[{id:91,framework_competency_id:71,rubric_level_id:81,descriptor:'Ready'}]:[],rubric:{name:'Arts rubric'},kpi:null,review_candidate_policy:null};
  const ctx={root,year:'2026',yearLabel,hash,params:new URLSearchParams(`program_id=11&step=${step}`),can:key=>key==='talent_programs.view'||allowed,api:async(path,options)=>{
    calls.push({path,options});if(options)return {};
    if(path==='/api/talent/programs')return [{id:11,name:'Performing Arts',status,logo_url:logoUrl}];
    if(path.startsWith('/api/talent/programs/planning-grades'))return configuredGrades;
    if(path.startsWith('/api/talent/evaluation-plans?'))return complete?[{id:41,program_id:11,status:'active',periods:[{id:51,label:'Term 1'}]}]:[];
    if(path.endsWith('/academic-years'))return complete?[{academic_year_id:2026,is_enabled:true,eligible_grade_levels:['1','2']}]:[];
    if(path.endsWith('/frameworks'))return [framework];
    if(path.endsWith('/competencies'))return [{id:61,name:'Expression',status:'active'}];
    if(path.endsWith('/configuration'))return config;
    return framework;
  }};
  return {ctx,calls,root,feedback};
}
test('read-only actors get escaped cards and no mutation forms',async()=>{
  const {ctx,root}=fixture(false,'draft',{step:'assess'});await render(ctx);
  assert.match(root.innerHTML,/&lt;script&gt;unsafe/);
  assert.doesNotMatch(root.innerHTML,/<form|data-action=/);
  assert.doesNotMatch(root.innerHTML,/Numeric value:/);
});
test('historical versions remain immutable and navigation uses canonical routes',async()=>{
  const {ctx,root}=fixture(true,'active',{step:'assess'});await render(ctx);
  assert.doesNotMatch(root.innerHTML,/data-form="(?:member:|rubric|kpi|policy)/);
  assert.match(root.innerHTML,/href="#tp-schedule"/);
  assert.match(root.innerHTML,/What we assess/);
  assert.match(root.innerHTML,/Competencies/);
  assert.match(root.innerHTML,/Assessment setup steps/);
  assert.doesNotMatch(root.innerHTML,/Review Candidate rules|Eligible Grades/);
});
test('descriptor save uses stable membership and level IDs plus loaded revision',async()=>{
  const {ctx,root,calls}=fixture();await render(ctx);
  const old=global.FormData;global.FormData=class extends Map {constructor(){super([['descriptor','Consistent expression']]);}};
  try {await root.onsubmit({preventDefault(){},target:{dataset:{form:'descriptor:71:81'},querySelector:()=>null}});}finally{global.FormData=old;}
  const write=calls.find(c=>c.options);
  assert.equal(write.path,'/api/talent/programs/11/frameworks/31/rubric/descriptors');
  assert.deepEqual(JSON.parse(write.options.body),{expected_revision:7,framework_competency_id:71,rubric_level_id:81,descriptor:'Consistent expression',grade_level:null});
});
test('Grade-specific descriptor editor sends the selected Grade and uses exact Grade rows',async()=>{
  const {ctx,root,calls}=fixture(true,'draft',{step:'assess',hash:'#tp-builder-descriptions',complete:true});
  const read=ctx.api;ctx.api=async(path,options)=>{
    if(!options&&path.endsWith('/configuration'))return {
      levels:[{id:81,code:'LEVEL_1',label:'Beginning',numeric_value:null}],
      descriptors:[
        {id:91,descriptor_scope:'grade',framework_competency_id:71,rubric_level_id:81,grade_level:'1',descriptor:'Grade 1 text'},
        {id:92,descriptor_scope:'grade',framework_competency_id:71,rubric_level_id:81,grade_level:'2',descriptor:'Grade 2 text'}
      ],
      rubric:{name:'Mental Math rubric'},kpi:null,review_candidate_policy:null,
      revision:7,semantic_fingerprint:'fingerprint'
    };
    return read(path,options);
  };
  await render(ctx);
  assert.match(root.innerHTML,/Grade 1/);
  assert.match(root.innerHTML,/Grade 2 text/);
  assert.match(root.innerHTML,/data-scope="grade"/);
  const old=global.FormData;global.FormData=class extends Map {constructor(){super([['descriptor','Updated Grade 2']]);}};
  try {await root.onsubmit({preventDefault(){},target:{dataset:{form:'descriptor:71:81:2'},querySelector:()=>null}});}finally{global.FormData=old;}
  const write=calls.filter(c=>c.options).at(-1);
  assert.equal(write.path,'/api/talent/programs/11/frameworks/31/rubric/descriptors');
  assert.deepEqual(JSON.parse(write.options.body),{
    expected_revision:7,framework_competency_id:71,rubric_level_id:81,
    descriptor:'Updated Grade 2',grade_level:'2'
  });
});


test('stale save preserves form and reports failure without success refresh',async()=>{
  const {ctx,root,feedback}=fixture();const read=ctx.api;ctx.api=(path,options)=>options?Promise.reject(new Error('Version changed elsewhere.')):read(path);
  await render(ctx);const initial=root.innerHTML,old=global.FormData;global.FormData=class extends Map {constructor(){super([['name','Changed'],['description','Test']]);}};
  try{await root.onsubmit({preventDefault(){},target:{dataset:{form:'edit-program'},querySelector:()=>feedback}});}finally{global.FormData=old;}
  assert.equal(root.innerHTML,initial);assert.match(feedback.textContent,/entries are preserved/);
});
test('numeric weights serialize exact membership identities in basis points',()=>{
  assert.deepEqual(kpiComponents(new Map([['weight_71','33.33'],['weight_72','66.67'],['weight_73','0']]),[{id:71},{id:72},{id:73}]),[{framework_competency_id:71,weight_basis_points:3333},{framework_competency_id:72,weight_basis_points:6667}]);
});

test('saved descriptor IDs expose the existing precise removal action',async()=>{
  const {ctx,root}=fixture(true,'draft',{step:'assess',hash:'#tp-builder-descriptions'});
  const read=ctx.api;ctx.api=async(path,options)=>{
    if(!options&&path.endsWith('/configuration'))return {levels:[{id:81,code:'READY',label:'Stage ready',numeric_value:null}],descriptors:[{id:91,framework_competency_id:71,rubric_level_id:81,descriptor:'Ready'}],rubric:{name:'Arts rubric'},kpi:null,review_candidate_policy:null,revision:7,semantic_fingerprint:'fingerprint'};
    return read(path,options);
  };
  await render(ctx);
  assert.match(root.innerHTML,/data-action="remove-descriptor" data-key="91"/);
});

test('Program setup no longer exposes Program criteria configuration',async()=>{
  const {ctx,root}=fixture(true,'draft',{step:'assess',hash:'#tp-builder-review'});
  await render(ctx);
  assert.doesNotMatch(root.innerHTML,/Program criteria|Enable Program criteria|data-form="policy"/i);
});

test('Program setup renders one real hash-backed wizard step and one assessment substep',async()=>{
  const {ctx,root}=fixture(true,'draft',{step:'assess',hash:'#tp-builder-review'});await render(ctx);
  assert.equal((root.innerHTML.match(/class="tp-wizard-panel"/g)||[]).length,1);
  assert.match(root.innerHTML,/id="tp-builder" class="tp-wizard-panel"/);
  assert.doesNotMatch(root.innerHTML,/id="tp-basics" class="tp-wizard-panel"|id="tp-ready" class="tp-wizard-panel"/);
  assert.doesNotMatch(root.innerHTML,/<h3>Grades<\/h3>|<h3>Build your evaluation<\/h3>|tp-step-label/);
  assert.match(root.innerHTML,/href="#tp-basics"[^>]*data-step="basics"/);
  assert.match(root.innerHTML,/href="#tp-schedule"[^>]*data-step="schedule"/);
  assert.equal((root.innerHTML.match(/data-assess-panel=/g)||[]).length,1);
  assert.match(root.innerHTML,/data-assess-panel="review"/);
  assert.match(root.innerHTML,/>Back<\/a><a class="tp-primary-link" href="#tp-schedule">Save &amp; Continue/);
});

test('Evaluation Plan is rendered inside the Program wizard without a standalone-page link',async()=>{
  let embedded;
  const {ctx,root}=fixture(true,'draft',{hash:'#tp-schedule'});
  ctx.renderSchedule=async child=>{embedded=child;child.root.innerHTML='<table><tr><th>Evaluation</th><th>Status</th><th>Actions</th></tr></table>';};
  await render(ctx);
  assert.match(root.innerHTML,/id="tp-schedule" class="tp-wizard-panel"/);
  assert.ok(embedded?.embedded);
  assert.doesNotMatch(root.innerHTML,/href="\/talent\/evaluation-plans/);
});

test('a completed Program opens operational summary while Edit reopens the same wizard',async()=>{
  const operational=fixture(true,'active',{complete:true,step:'',yearLabel:'2026–2027'});await render(operational.ctx);
  assert.match(operational.root.innerHTML,/class="tp-program-summary"/);
  assert.match(operational.root.innerHTML,/2026–2027/);
  assert.match(operational.root.innerHTML,/Edit Program/);
  assert.match(operational.root.innerHTML,/Manage Evaluation Plan/);
  assert.doesNotMatch(operational.root.innerHTML,/class="tp-tabs"|class="tp-wizard-panel"/);
  const editing=fixture(true,'active',{complete:true,hash:'#tp-basics'});await render(editing.ctx);
  assert.match(editing.root.innerHTML,/id="tp-basics" class="tp-wizard-panel"/);
  assert.doesNotMatch(editing.root.innerHTML,/class="tp-program-summary"/);
});

test('Basics renders the Academic Year label instead of its internal ID',async()=>{
  const {ctx,root}=fixture(true,'draft',{yearLabel:'2026–2027'});await render(ctx);
  assert.match(root.innerHTML,/Academic Year:<\/strong> 2026–2027/);
  assert.doesNotMatch(root.innerHTML,/Academic Year:<\/strong> 2026<\/p>/);
});


test('Finish Setup on a completed draft setup exits without lifecycle activation writes',async()=>{
  const {ctx,root,calls}=fixture(true,'draft',{complete:true,hash:'#tp-ready'});
  let navigated=null;ctx.navigate=target=>{navigated=target;};
  await render(ctx);
  assert.match(root.innerHTML,/data-action="finish-setup"[^>]*>.*Finish Setup/);
  await root.onclick({target:{closest:()=>({dataset:{action:'finish-setup'}})}});
  assert.equal(calls.filter(c=>c.options?.method==='POST'&&/lifecycle\/active|\/activate$/.test(c.path)).length,0);
  assert.equal(navigated,'programs');
});

test('completed Ready state offers Finish Setup to exit the wizard',async()=>{
  const {ctx,root}=fixture(true,'active',{complete:true,hash:'#tp-ready'});await render(ctx);
  assert.match(root.innerHTML,/data-action="finish-setup"[^>]*>.*Finish Setup/);
});

// Finish Setup must exit to the canonical Programs list - not re-render the
// same workspace ctx (which still carries the current program_id in
// ctx.params and would just redraw the operational summary/wizard again).
// setupComplete (and so the clickable data-action="finish-setup" button,
// as opposed to a plain "finish the next incomplete step" link) requires
// program.status==='active', so a Draft Program's "Finish Setup" is a plain
// href step-link, not this JS handler - covered separately below.
for (const [label, hash] of [
  ['a fully-ready/Active Program', '#tp-ready'],
  // A direct deep-link straight into the Ready step (no prior step-by-step
  // navigation through basics/assess/schedule in this render call).
  ['a direct deep-link straight into the Ready step', '#tp-ready'],
]) {
  test(`Finish Setup on ${label} navigates to the canonical Programs list with no program_id, query state, or hash`,async()=>{
    const {ctx,root}=fixture(true,'active',{complete:true,hash});
    await render(ctx);
    assert.match(root.innerHTML,/data-action="finish-setup"[^>]*>.*Finish Setup/);
    const navigated=[];
    ctx.navigate=(target,extra)=>navigated.push({target,extra});
    await root.onclick({target:{closest:()=>({dataset:{action:'finish-setup'}})}});
    // Exactly one navigation call, to the plain "programs" list target with
    // no extra query params (so ctx.navigate's own URL builder produces
    // /talent/programs?academic_year_id=... with no program_id and no
    // hash - never the operational summary for the just-finished Program).
    assert.deepEqual(navigated,[{target:'programs',extra:undefined}]);
  });
}

test('a fully configured Draft Program can finish setup without an activation prerequisite',async()=>{
  const {ctx,root}=fixture(true,'draft',{complete:true,hash:'#tp-ready'});
  await render(ctx);
  assert.match(root.innerHTML,/data-action="finish-setup"[^>]*>.*Finish Setup/);
  assert.doesNotMatch(root.innerHTML,/data-action="finalize-setup"/);
});

test('Program index is a compact searchable table with primary actions',async()=>{
  const feedback={textContent:'',setAttribute(){}},root={innerHTML:'',querySelector:()=>null,querySelectorAll:()=>[]};
  const ctx={root,year:'2026',params:new URLSearchParams(),can:key=>key==='talent_programs.view'||key==='talent_programs.manage',api:async path=>{
    if(path==='/api/talent/programs')return [{id:11,name:'Performing Arts',status:'draft'}];
    if(path.endsWith('/academic-years'))return [{academic_year_id:2026,is_enabled:true,eligible_grade_levels:['7','8']}];
    if(path.endsWith('/frameworks'))return [{id:31,status:'active'}];
    if(path.endsWith('/configuration'))return {kpi:null};
    throw new Error(`Unexpected ${path}`);
  }};
  await render(ctx);
  assert.match(root.innerHTML,/<table/);
  assert.match(root.innerHTML,/Program<\/th><th>Grades<\/th><th>Scoring Mode<\/th><th>Current Year<\/th><th>Status<\/th><th>Actions/);
  assert.doesNotMatch(root.innerHTML,/<th>Type<\/th>/);
  assert.match(root.innerHTML,/Search Programs/);
  assert.match(root.innerHTML,/New Program/);
  assert.match(root.innerHTML,/>Overview<\/a>/);
  assert.match(root.innerHTML,/>Edit Program<\/a>/);
  assert.match(root.innerHTML,/>Rubric<\/a>/);
  assert.doesNotMatch(root.innerHTML,/Open Program →/);
  // The Create-Program form must not be permanently expanded on the landing
  // screen; it opens only via the "New Program" action (Students' "Add Student"
  // separate-entry-point precedent, applied here as a collapsed panel).
  assert.match(root.innerHTML,/<div data-new-program hidden>/);
});

test('fallback initials are derived generically from the Program name, not hardcoded', () => {
  assert.equal(logoInitials('Mental Math'), 'MM');
  assert.equal(logoInitials('Performing Arts'), 'PA');
  assert.equal(logoInitials('Ghers'), 'GH');
  assert.equal(logoInitials(''), '?');
  assert.equal(logoInitials('  '), '?');
});

test('logoBadge renders an <img> when a logo_url exists and escaped initials otherwise', () => {
  assert.match(logoBadge({name: 'Mental Math', logo_url: '/organization-assets/1/programs/11/logo/a.png'}, 'tp-logo-sm'),
    /<span class="tp-logo-badge tp-logo-sm"><img src="\/organization-assets\/1\/programs\/11\/logo\/a\.png" alt="Mental Math logo"><\/span>/);
  assert.match(logoBadge({name: '<Arts>', logo_url: null}, 'tp-logo-md'),
    /<span class="tp-logo-badge tp-logo-md"><span class="tp-logo-initials" aria-hidden="true">.*<\/span><\/span>/);
  assert.doesNotMatch(logoBadge({name: '<Arts>', logo_url: null}, 'tp-logo-md'), /<Arts>/);
});

test('Program Identity renders the logo on the Programs list (small) and Program header (medium)', async () => {
  const {ctx: listCtx, root: listRoot} = (() => {
    const root={innerHTML:'',querySelector:()=>null,querySelectorAll:()=>[]};
    const ctx={root,year:'2026',params:new URLSearchParams(),can:key=>key==='talent_programs.view'||key==='talent_programs.manage',api:async path=>{
      if(path==='/api/talent/programs')return [{id:11,name:'Mental Math',status:'draft',logo_url:'/organization-assets/1/programs/11/logo/a.png'}];
      if(path.endsWith('/academic-years'))return [];
      if(path.endsWith('/frameworks'))return [];
      throw new Error(`Unexpected ${path}`);
    }};
    return {ctx,root};
  })();
  await render(listCtx);
  assert.match(listRoot.innerHTML, /<th scope="row"><span class="tp-logo-badge tp-logo-sm"><img src="\/organization-assets\/1\/programs\/11\/logo\/a\.png"[^>]*><\/span> Mental Math<\/th>/);

  const {ctx: headerCtx, root: headerRoot} = fixture(true, 'draft', {logoUrl: null});
  await render(headerCtx);
  assert.match(headerRoot.innerHTML, /<header id="tp-overview" class="tp-section-lede"><span class="tp-logo-badge tp-logo-md"><span class="tp-logo-initials"/);
});

test('Program Identity offers Upload Logo with no logo, and Replace/Remove Logo once a logo exists', async () => {
  const {ctx: noLogoCtx, root: noLogoRoot} = fixture(true, 'draft', {logoUrl: null});
  await render(noLogoCtx);
  assert.match(noLogoRoot.innerHTML, /Upload Logo<input type="file"[^>]*data-logo-input/);
  assert.doesNotMatch(noLogoRoot.innerHTML, /Remove Logo/);

  const {ctx: hasLogoCtx, root: hasLogoRoot} = fixture(true, 'draft', {logoUrl: '/organization-assets/1/programs/11/logo/a.png'});
  await render(hasLogoCtx);
  assert.match(hasLogoRoot.innerHTML, /Replace Logo<input type="file"[^>]*data-logo-input/);
  assert.match(hasLogoRoot.innerHTML, /data-action="remove-logo"/);
});

test('a view-only actor sees the Program Identity logo but no Upload/Replace/Remove controls', async () => {
  const {ctx, root} = fixture(false, 'draft', {logoUrl: '/organization-assets/1/programs/11/logo/a.png'});
  await render(ctx);
  assert.match(root.innerHTML, /tp-logo-badge tp-logo-md/);
  assert.doesNotMatch(root.innerHTML, /data-logo-input/);
  assert.doesNotMatch(root.innerHTML, /Remove Logo/);
});

test('Grades fieldset lists only real Planning-configured Grades, not a blanket KG-12 catalog', async () => {
  const {ctx, root} = fixture(true, 'draft', {configuredGrades: ['1', '4']});
  await render(ctx);
  assert.match(root.innerHTML, /Grade 1/);
  assert.match(root.innerHTML, /Grade 4/);
  assert.doesNotMatch(root.innerHTML, />KG</);
  assert.doesNotMatch(root.innerHTML, /Grade 2/);
  assert.doesNotMatch(root.innerHTML, /Grade 12/);
});

test('an empty Planning Grade configuration shows a clear empty state, not an empty or fabricated picker', async () => {
  const {ctx, root} = fixture(true, 'draft', {configuredGrades: []});
  await render(ctx);
  assert.match(root.innerHTML, /No Grades are configured in Planning for this Academic Year\./);
  assert.doesNotMatch(root.innerHTML, /<fieldset><legend>Grades<\/legend>/);
});

// Owner-confirmed defect: the Programs workspace repeatedly flashed
// "Loading Programs..." and re-fetched the entire Program list and this
// Program's full setup graph on every same-page wizard-step navigation
// (Basics/What we assess/Evaluation Plan/Ready, and the assess substeps),
// because each of those is a real `#hash` anchor and the workspace's own
// `hashchange` listener called the full `render(ctx)` fetch chain again on
// every click. These tests exercise `render(ctx, {viaHash:true})` directly,
// exactly as the module's internal `hashGuard` now does, to prove a
// same-Program-context step change reuses the already-fetched bundle while
// every real context change or explicit reload still fetches fresh data.
test('a hash-only step navigation (viaHash) within the same Program/Academic Year reuses the already-fetched bundle: no "Loading Programs..." flash and no duplicate Program-list/setup-graph requests',async()=>{
  const {ctx,root,calls}=fixture(true,'draft',{step:'basics',hash:'#tp-basics'});
  await render(ctx);
  const initialCalls=calls.length;
  assert.ok(calls.some(c=>c.path==='/api/talent/programs'),'initial render fetches the Program catalog');
  root.innerHTML='';
  await render(ctx,{viaHash:true});
  assert.equal(calls.length,initialCalls,'no additional network calls were issued for a same-context hash navigation');
  assert.doesNotMatch(root.innerHTML,/Loading Programs/,'the workspace is never blanked to a loading state for a local step change');
  assert.match(root.innerHTML,/id="tp-basics" class="tp-wizard-panel"/);
});
test('a hash-only (viaHash) navigation still redraws the requested step correctly from cached data',async()=>{
  const {ctx,root}=fixture(true,'draft',{step:'assess',hash:'#tp-basics'});
  await render(ctx);
  assert.match(root.innerHTML,/id="tp-basics" class="tp-wizard-panel"/);
  ctx.hash='#tp-builder';
  await render(ctx,{viaHash:true});
  assert.match(root.innerHTML,/id="tp-builder" class="tp-wizard-panel"/);
  assert.doesNotMatch(root.innerHTML,/id="tp-basics" class="tp-wizard-panel"/);
});
test('viaHash with a different Program/Academic Year context (a real context change) still performs a fresh fetch, not a stale reuse',async()=>{
  const {ctx,root,calls}=fixture(true,'draft',{step:'basics',hash:'#tp-basics'});
  await render(ctx);
  const afterFirst=calls.filter(c=>c.path==='/api/talent/programs').length;
  ctx.params=new URLSearchParams('program_id=11&step=basics&academic_year_id=2027');
  ctx.year='2027';
  await render(ctx,{viaHash:true});
  const afterSecond=calls.filter(c=>c.path==='/api/talent/programs').length;
  assert.equal(afterSecond,afterFirst+1,'a changed Academic Year context is a cache miss and fetches fresh data even when called with viaHash');
});
test('explicit Refresh (a real, non-hash render call) always fetches fresh data even when a matching hash-cache already exists',async()=>{
  const {ctx,root,calls}=fixture(true,'draft',{step:'basics',hash:'#tp-basics'});
  await render(ctx);
  await render(ctx,{viaHash:true});
  const beforeRefresh=calls.filter(c=>c.path==='/api/talent/programs').length;
  await render(ctx);
  const afterRefresh=calls.filter(c=>c.path==='/api/talent/programs').length;
  assert.equal(afterRefresh,beforeRefresh+1,'an explicit (non-hash) render always performs a real Program-list request');
});
test('a save (mutate -> refresh) always reflects freshly saved data on the very next hash-only render, never a pre-save cached value',async()=>{
  const {ctx,root}=fixture(true,'draft',{step:'basics',hash:'#tp-basics'});
  let currentDescription='Original description';
  const read=ctx.api;
  ctx.api=async(path,options)=>{
    if(options&&options.method==='PATCH'&&path==='/api/talent/programs/11'){currentDescription=JSON.parse(options.body).description;return {};}
    if(!options&&path==='/api/talent/programs')return [{id:11,name:'Performing Arts',status:'draft',description:currentDescription}];
    return read(path,options);
  };
  await render(ctx);
  const old=global.FormData;global.FormData=class extends Map {constructor(){super([['name','Performing Arts'],['description','Updated description']]);}};
  try {await root.onsubmit({preventDefault(){},target:{dataset:{form:'edit-program'},querySelector:()=>({textContent:'',setAttribute(){}})}});}
  finally {global.FormData=old;}
  await render(ctx,{viaHash:true});
  assert.match(root.innerHTML,/Updated description/);
  assert.doesNotMatch(root.innerHTML,/Original description/);
});
test('a failed initial fetch never populates the cache, so a subsequent hash-only render safely falls back to a real fetch instead of throwing or reusing a broken bundle',async()=>{
  const {ctx,root}=fixture(true,'draft',{step:'basics',hash:'#tp-basics'});
  const read=ctx.api;
  ctx.api=async(path,options)=>{if(!options&&path==='/api/talent/programs')throw new Error('Network error');return read(path,options);};
  await assert.rejects(render(ctx));
  ctx.api=read;
  await render(ctx,{viaHash:true});
  assert.match(root.innerHTML,/id="tp-basics" class="tp-wizard-panel"/);
});
test('rapid duplicate hash-only navigations do not accumulate duplicate Program-list requests (cache hit on every repeat)',async()=>{
  const {ctx,calls}=fixture(true,'draft',{step:'basics',hash:'#tp-basics'});
  await render(ctx);
  const before=calls.filter(c=>c.path==='/api/talent/programs').length;
  await Promise.all([render(ctx,{viaHash:true}),render(ctx,{viaHash:true}),render(ctx,{viaHash:true})]);
  const after=calls.filter(c=>c.path==='/api/talent/programs').length;
  assert.equal(after,before,'three back-to-back hash-only renders in the same context issue zero additional Program-list requests');
});

// Owner-confirmed Program context-integrity defect: the shared ribbon/context
// Program selector and the Programs workspace must always resolve to the
// SAME canonical Program, identified only by program_id - never by name, and
// never by which Program happens to load/appear first. These tests exercise
// the Programs workspace's own real render(ctx) end to end with two
// distinctly-named fixture Programs, proving it reads (and, across a real
// context change, re-reads) canonical program_id from the shared ctx.params
// object rather than caching an independent "selected Program" of its own.
function programWorkspaceCtx(pid, programs, apiTail = () => Promise.resolve([])) {
  const root = {innerHTML: '', querySelector: () => null, querySelectorAll: () => []};
  const calls = [];
  const api = async (path, options) => {
    calls.push({path, options});
    if (options) return {};
    if (path === '/api/talent/programs') return programs;
    if (path.startsWith('/api/talent/programs/planning-grades')) return [];
    if (path.endsWith('/academic-years')) return [];
    if (path.endsWith('/frameworks')) return [];
    if (path.endsWith('/competencies')) return [];
    if (path.startsWith('/api/talent/evaluation-plans')) return [];
    return apiTail(path, options);
  };
  const ctx = {root, year: '2026', yearLabel: '2026-2027', params: new URLSearchParams(`program_id=${pid}`), can: key => key === 'talent_programs.view', api, notify() {}, navigate() {}};
  return {ctx, root, calls};
}
const mentalMathProgram = {id: 11, name: 'Mental Math', status: 'draft'};
const chessClubProgram = {id: 27, name: 'Chess Club', status: 'draft'};

test('the Programs workspace resolves the canonical Program by program_id only, matching neither the first list item nor by name', async () => {
  const programs = [mentalMathProgram, chessClubProgram];
  const {ctx: ctxA, root: rootA} = programWorkspaceCtx(String(chessClubProgram.id), programs);
  await render(ctxA);
  assert.match(rootA.innerHTML, /<h2>Chess Club<\/h2>/);
  assert.doesNotMatch(rootA.innerHTML, /<h2>Mental Math<\/h2>/);

  const {ctx: ctxB, root: rootB} = programWorkspaceCtx(String(mentalMathProgram.id), programs);
  await render(ctxB);
  assert.match(rootB.innerHTML, /<h2>Mental Math<\/h2>/);
  assert.doesNotMatch(rootB.innerHTML, /<h2>Chess Club<\/h2>/);
});

test('changing canonical program_id on the shared ctx (simulating a ribbon-driven or inner-selector-driven Program change) fully switches the workspace and bypasses the hash-only cache', async () => {
  const programs = [mentalMathProgram, chessClubProgram];
  const {ctx, root, calls} = programWorkspaceCtx(String(mentalMathProgram.id), programs);
  await render(ctx);
  assert.match(root.innerHTML, /<h2>Mental Math<\/h2>/);
  const fetchesAfterFirst = calls.filter(c => c.path === '/api/talent/programs').length;

  // A real Program change updates the same shared ctx.params object the
  // ribbon/applyContext() and the Programs workspace both read - exactly the
  // single canonical program_id source of truth.
  ctx.params = new URLSearchParams(`program_id=${chessClubProgram.id}`);
  await render(ctx);
  assert.match(root.innerHTML, /<h2>Chess Club<\/h2>/);
  assert.doesNotMatch(root.innerHTML, /<h2>Mental Math<\/h2>/);
  const fetchesAfterSecond = calls.filter(c => c.path === '/api/talent/programs').length;
  assert.equal(fetchesAfterSecond, fetchesAfterFirst + 1, 'a real Program change always performs a fresh fetch, never a stale-Program cache reuse');
});

test('a stale in-flight response for a previous Program can never overwrite the currently-rendered newer Program (async/staleness safety)', async () => {
  const programs = [mentalMathProgram, chessClubProgram];
  let releaseStaleProgram;
  const gate = new Promise(resolve => { releaseStaleProgram = resolve; });
  const root = {innerHTML: '', querySelector: () => null, querySelectorAll: () => []};
  const staleCtx = {
    root, year: '2026', yearLabel: '2026-2027', params: new URLSearchParams(`program_id=${mentalMathProgram.id}`),
    can: key => key === 'talent_programs.view', notify() {}, navigate() {},
    api: async (path, options) => { if (options) return {}; if (path === '/api/talent/programs') { await gate; return programs; } return []; },
  };
  // Program A (Mental Math) starts rendering first but its Program-list fetch
  // is deliberately held open ("stale/slow response").
  const stalePromise = render(staleCtx);
  // Program B (Chess Club) is selected next on the very same shared root/ctx
  // shape (simulating the ribbon or inner selector immediately choosing a
  // different Program) and resolves fully before A's held-open fetch returns.
  const freshCtx = {
    root, year: '2026', yearLabel: '2026-2027', params: new URLSearchParams(`program_id=${chessClubProgram.id}`),
    can: key => key === 'talent_programs.view', notify() {}, navigate() {},
    api: async (path, options) => { if (options) return {}; if (path === '/api/talent/programs') return programs; if (path.startsWith('/api/talent/programs/planning-grades')) return []; if (path.endsWith('/academic-years')) return []; if (path.endsWith('/frameworks')) return []; if (path.endsWith('/competencies')) return []; if (path.startsWith('/api/talent/evaluation-plans')) return []; return []; },
  };
  await render(freshCtx);
  assert.match(root.innerHTML, /<h2>Chess Club<\/h2>/, 'the newer Program (B) is fully rendered');
  // Now let the stale Program A response resolve. Its render must detect it
  // has been superseded (the shared module-level renderToken guard) and
  // return WITHOUT overwriting the already-rendered, newer Program B state.
  releaseStaleProgram();
  await stalePromise;
  assert.match(root.innerHTML, /<h2>Chess Club<\/h2>/, 'Program B remains rendered after the stale Program A response resolves');
  assert.doesNotMatch(root.innerHTML, /<h2>Mental Math<\/h2>/, 'the stale Program A response never overwrote the newer Program B state');
});

test('Program index offers Delete only when the backend-computed actions array allows it (ADR 0032), with confirmation and the real DELETE route', async () => {
  const {ctx, root, calls} = (() => {
    const root = {innerHTML: '', querySelector: () => null, querySelectorAll: () => []};
    const c = [];
    const api = async (path, options) => {
      c.push({path, options});
      if (options) return {};
      if (path === '/api/talent/programs') return [{id: 11, name: 'Performing Arts', status: 'draft', actions: ['delete']}];
      if (path.endsWith('/academic-years')) return [];
      if (path.endsWith('/frameworks')) return [];
      throw new Error(`Unexpected ${path}`);
    };
    const ctx = {root, year: '2026', params: new URLSearchParams(), can: key => key === 'talent_programs.view' || key === 'talent_programs.manage', api};
    return {ctx, root, calls: c};
  })();
  await render(ctx);
  assert.match(root.innerHTML, /data-action="delete-program" data-id="11"/);
  const oldConfirm = global.window;
  global.window = {confirm: () => true, scrollY: 0, scrollTo(){}, addEventListener(){}, removeEventListener(){}};
  try {
    await root.onclick({target: {closest: sel => sel.includes('delete-program') ? {dataset: {action: 'delete-program', id: '11'}} : null}});
  } finally { global.window = oldConfirm; }
  const del = calls.find(c => c.path === '/api/talent/programs/11' && c.options && c.options.method === 'DELETE');
  assert.ok(del, 'expected a DELETE call to the Program route');
});

test('Program index omits Delete when the backend-computed actions array does not allow it', async () => {
  const {ctx, root} = (() => {
    const root = {innerHTML: '', querySelector: () => null, querySelectorAll: () => []};
    const api = async path => {
      if (path === '/api/talent/programs') return [{id: 11, name: 'Performing Arts', status: 'active', actions: []}];
      if (path.endsWith('/academic-years')) return [];
      if (path.endsWith('/frameworks')) return [];
      throw new Error(`Unexpected ${path}`);
    };
    const ctx = {root, year: '2026', params: new URLSearchParams(), can: key => key === 'talent_programs.view' || key === 'talent_programs.manage', api};
    return {ctx, root};
  })();
  await render(ctx);
  assert.doesNotMatch(root.innerHTML, /data-action="delete-program"/);
});

test('removing the Program logo requires confirmation and calls the Program-scoped logo DELETE route', async () => {
  const {ctx, root, calls} = fixture(true, 'draft', {logoUrl: '/organization-assets/1/programs/11/logo/a.png'});
  await render(ctx);
  const oldConfirm = global.window;
  global.window = {confirm: () => true, scrollY: 0, scrollTo(){}, addEventListener(){}, removeEventListener(){}};
  try {
    await root.onclick({target: {closest: () => ({dataset: {action: 'remove-logo'}})}});
  } finally { global.window = oldConfirm; }
  const remove = calls.find(c => c.path === '/api/talent/programs/11/logo' && c.options && c.options.method === 'DELETE');
  assert.ok(remove, 'expected a DELETE call to the Program logo route');
});


test('Rubric action renders eligible Grades as independent collapsible Grade accordions',async()=>{
  const {ctx,root}=fixture(true,'draft',{hash:'#tp-rubric',complete:true});
  const read=ctx.api;
  ctx.api=async(path,options)=>{
    if(!options&&/\/frameworks\/31$/.test(path))return {
      id:31,title:'Mental Math rubric',status:'draft',version_number:2,revision:7,semantic_fingerprint:'fingerprint',
      competencies:[
        {id:71,competency_id:61,grade_level:'1',label:'Mental Calculation',description:'Mental strategies'},
        {id:72,competency_id:62,grade_level:'2',label:'Number Flexibility',description:'Number relationships'}
      ]
    };
    if(!options&&path.endsWith('/competencies'))return [
      {id:61,name:'Mental Calculation',status:'active'},
      {id:62,name:'Number Flexibility',status:'active'}
    ];
    if(!options&&path.endsWith('/configuration'))return {
      levels:[
        {id:81,code:'L1',label:'Beginning',description:'Level one',display_order:1},
        {id:82,code:'L2',label:'Meets',description:'Level two',display_order:2}
      ],
      descriptors:[
        {id:91,framework_competency_id:71,rubric_level_id:81,grade_level:'1',descriptor:'Grade 1 beginning'},
        {id:92,framework_competency_id:71,rubric_level_id:82,grade_level:'1',descriptor:'Grade 1 meets'},
        {id:93,framework_competency_id:72,rubric_level_id:81,grade_level:'2',descriptor:'Grade 2 beginning'},
        {id:94,framework_competency_id:72,rubric_level_id:82,grade_level:'2',descriptor:'Grade 2 meets'}
      ],
      rubric:{name:'Mental Math rubric'},kpi:null,review_candidate_policy:null,
      revision:7,semantic_fingerprint:'fingerprint'
    };
    return read(path,options);
  };
  await render(ctx);
  assert.match(root.innerHTML,/id="tp-rubric"/);
  assert.match(root.innerHTML,/<details class="tp-card tp-grade-rubric" open>/);
  assert.match(root.innerHTML,/Grade 1/);
  assert.match(root.innerHTML,/Grade 2/);
  assert.match(root.innerHTML,/Mental Calculation/);
  assert.match(root.innerHTML,/Number Flexibility/);
  assert.match(root.innerHTML,/\+ Add Competency/);
  assert.match(root.innerHTML,/Grade 1 beginning/);
  assert.match(root.innerHTML,/data-action="finish-rubric"/);
});

test('Program creation form asks for eligible Grades and keeps rubric as a separate action',async()=>{
  const root={innerHTML:'',querySelector:()=>null,querySelectorAll:()=>[]};
  const ctx={root,year:'2026',params:new URLSearchParams(),can:key=>key==='talent_programs.view'||key==='talent_programs.manage',api:async path=>{
    if(path==='/api/talent/programs')return [];
    if(path.startsWith('/api/talent/programs/planning-grades'))return ['1','2','3'];
    throw new Error(`Unexpected ${path}`);
  }};
  await render(ctx);
  assert.match(root.innerHTML,/Eligible Grades/);
  assert.match(root.innerHTML,/Grade 1/);
  assert.match(root.innerHTML,/Grade 2/);
  assert.match(root.innerHTML,/Grade 3/);
  assert.doesNotMatch(root.innerHTML,/Rubric Levels|Evaluation Plan/);
});


test('Rubric action renders Grade -> Competency -> Rubric -> Level structure',async()=>{
  const {ctx,root,calls}=fixture(true,'draft',{hash:'#tp-rubric',complete:true});
  const read=ctx.api;
  ctx.api=async(path,options)=>{
    if(!options&&path.endsWith('/frameworks/31'))return {
      id:31,title:'Arts rubric',status:'draft',version_number:2,revision:7,
      semantic_fingerprint:'fingerprint',
      competencies:[{id:71,competency_id:61,grade_level:'1',label:'Reading Fluency',description:'Reads connected text'}]
    };
    if(!options&&path.endsWith('/configuration'))return {
      rubric:null,levels:[],
      rubrics:[{
        id:301,framework_competency_id:71,name:'Oral Reading',description:'Reading rubric',
        levels:[
          {id:401,rubric_id:301,framework_competency_id:71,code:'L1',label:'Beginning',description:'Reads with limited accuracy.',order:1},
          {id:402,rubric_id:301,framework_competency_id:71,code:'L2',label:'Approaching',description:'Reads with some support.',order:2}
        ]
      }],
      descriptors:[],kpi:null,review_candidate_policy:null,
      revision:7,semantic_fingerprint:'fingerprint'
    };
    return read(path,options);
  };
  await render(ctx);
  assert.match(root.innerHTML,/Rubric Structure/);
  assert.match(root.innerHTML,/Grade 1/);
  assert.match(root.innerHTML,/Reading Fluency/);
  assert.match(root.innerHTML,/Oral Reading/);
  assert.match(root.innerHTML,/Beginning/);
  assert.match(root.innerHTML,/Reads with limited accuracy/);
  assert.match(root.innerHTML,/\+ Add Competency/);
  assert.doesNotMatch(root.innerHTML,/<h3>Rubric Levels<\/h3>/);

  const old=global.FormData;
  global.FormData=class extends Map {constructor(){super([['name','Updated Oral Reading'],['description','Updated rubric']]);}};
  try{
    await root.onsubmit({preventDefault(){},target:{dataset:{form:'competency-rubric:71'},querySelector:()=>null}});
  }finally{global.FormData=old;}
  const write=calls.filter(item=>item.options).at(-1);
  assert.equal(write.path,'/api/talent/programs/11/frameworks/31/rubric');
  assert.equal(JSON.parse(write.options.body).framework_competency_id,71);
});


test('Rubric mode selects the newest Draft so Start Editing exposes Add Competency',async()=>{
  const root={innerHTML:'',querySelector:()=>null,querySelectorAll:()=>[]};
  const calls=[];
  const versions=[
    {id:31,status:'draft',version_number:1},
    {id:32,status:'draft',version_number:2},
  ];
  const ctx={
    root,year:'2026',yearLabel:'2026–2027',hash:'#tp-rubric',
    params:new URLSearchParams('program_id=11'),
    can:key=>key==='talent_programs.view'||key==='talent_programs.manage',
    api:async(path,options)=>{
      calls.push({path,options});
      if(options)return {};
      if(path==='/api/talent/programs')return [{id:11,name:'Mental Math',status:'active'}];
      if(path.startsWith('/api/talent/programs/planning-grades'))return ['1','2','3'];
      if(path.endsWith('/academic-years'))return [{academic_year_id:2026,is_enabled:true,eligible_grade_levels:['1','2','3']}];
      if(path.endsWith('/frameworks'))return versions;
      if(path.endsWith('/competencies'))return [];
      if(path.endsWith('/frameworks/31'))return {id:31,status:'draft',version_number:1,revision:3,semantic_fingerprint:'old',in_use_by_assessments:true,competencies:[]};
      if(path.endsWith('/frameworks/32'))return {id:32,status:'draft',version_number:2,revision:1,semantic_fingerprint:'new',in_use_by_assessments:false,competencies:[]};
      if(path.includes('/frameworks/31/configuration'))return {rubric:null,levels:[],rubrics:[],descriptors:[],kpi:null,review_candidate_policy:null,revision:3,semantic_fingerprint:'old'};
      if(path.includes('/frameworks/32/configuration'))return {rubric:null,levels:[],rubrics:[],descriptors:[],kpi:null,review_candidate_policy:null,revision:1,semantic_fingerprint:'new'};
      if(path.startsWith('/api/talent/evaluation-plans?'))return [];
      throw new Error(`Unexpected ${path}`);
    }
  };
  await render(ctx);
  assert.ok(calls.some(call=>call.path==='/api/talent/programs/11/frameworks/32'));
  assert.doesNotMatch(root.innerHTML,/Edit Rubric Structure/);
  assert.match(root.innerHTML,/\+ Add Competency/);
  assert.match(root.innerHTML,/data-action="finish-rubric"/);
});


test('legacy assessed rubric stays historical and is not projected into new Grade authoring',async()=>{
  const {ctx,root}=fixture(true,'draft',{hash:'#tp-rubric',complete:true});
  const read=ctx.api;
  ctx.api=async(path,options)=>{
    if(!options&&path.endsWith('/frameworks/31'))return {
      id:31,title:'Mental Math rubric',status:'draft',version_number:2,revision:7,
      semantic_fingerprint:'fingerprint',in_use_by_assessments:true,
      competencies:[{id:71,competency_id:61,grade_level:null,label:'Mental Calculation',description:'Mental strategies'}]
    };
    if(!options&&path.endsWith('/configuration'))return {
      rubric:{name:'Mental Math rubric',description:'Legacy shared scale'},
      levels:[{id:81,code:'L1',label:'Beginning',description:'Beginning description',display_order:1}],
      rubrics:[],descriptors:[],kpi:null,review_candidate_policy:null,
      revision:7,semantic_fingerprint:'fingerprint'
    };
    return read(path,options);
  };
  await render(ctx);
  assert.match(root.innerHTML,/Grade 1/);
  assert.match(root.innerHTML,/Grade 2/);
  assert.doesNotMatch(root.innerHTML,/Mental Calculation/);
  assert.doesNotMatch(root.innerHTML,/Existing shared rubric/);
  assert.match(root.innerHTML,/Copy the current rubric structure \(optional\)/);
  assert.doesNotMatch(root.innerHTML,/name="clone"[^>]*checked/);
});
