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
  assert.deepEqual(JSON.parse(write.options.body),{expected_revision:7,framework_competency_id:71,rubric_level_id:81,descriptor:'Consistent expression'});
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

test('completed Ready state offers Finish Setup to exit the wizard',async()=>{
  const {ctx,root}=fixture(true,'active',{complete:true,hash:'#tp-ready'});await render(ctx);
  assert.match(root.innerHTML,/data-action="finish-setup"[^>]*>.*Finish Setup/);
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
  assert.match(root.innerHTML,/Program<\/th><th>Grades<\/th><th>Type<\/th><th>Current Year<\/th><th>Status<\/th><th>Actions/);
  assert.match(root.innerHTML,/Search Programs/);
  assert.match(root.innerHTML,/New Program/);
  assert.match(root.innerHTML,/>Open<\/a>/);
  assert.match(root.innerHTML,/>Edit<\/a>/);
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
