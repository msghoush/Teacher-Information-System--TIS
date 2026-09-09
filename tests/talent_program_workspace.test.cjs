const {test}=require('node:test');
const assert=require('node:assert/strict');
const {render,kpiComponents}=require('../static/js/talent-program-workspace.js');
function fixture(allowed=true,status='draft') {
  const calls=[], feedback={textContent:'',setAttribute(){}}, root={innerHTML:'',querySelector:()=>feedback,querySelectorAll:()=>[]};
  const framework={id:31,title:'Arts & <expression>',status,version_number:2,revision:7,semantic_fingerprint:'fingerprint',competencies:[{id:71,competency_id:61,label:'Expression',description:'<script>unsafe</script>'}]};
  const config={levels:[{id:81,code:'READY',label:'Stage ready',numeric_value:null}],descriptors:[],rubric:{name:'Arts rubric'},kpi:null,review_candidate_policy:null};
  const ctx={root,year:'2026',params:new URLSearchParams('program_id=11'),can:key=>key==='talent_programs.view'||allowed,api:async(path,options)=>{
    calls.push({path,options});if(options)return {};
    if(path==='/api/talent/programs')return [{id:11,name:'Performing Arts',status:'draft'}];
    if(path.endsWith('/academic-years'))return [];
    if(path.endsWith('/frameworks'))return [framework];
    if(path.endsWith('/competencies'))return [{id:61,name:'Expression',status:'active'}];
    if(path.endsWith('/configuration'))return config;
    return framework;
  }};
  return {ctx,calls,root,feedback};
}
test('read-only actors get escaped cards and no mutation forms',async()=>{
  const {ctx,root}=fixture(false);await render(ctx);
  assert.match(root.innerHTML,/Arts &amp; &lt;expression&gt;/);
  assert.match(root.innerHTML,/&lt;script&gt;unsafe/);
  assert.doesNotMatch(root.innerHTML,/<form|data-action=/);
  assert.doesNotMatch(root.innerHTML,/Numeric value:/);
});
test('historical versions remain immutable and navigation uses canonical routes',async()=>{
  const {ctx,root}=fixture(true,'active');await render(ctx);
  assert.doesNotMatch(root.innerHTML,/data-form="(?:member:|rubric|kpi|policy)/);
  assert.match(root.innerHTML,/\/talent\/evaluation-plans\?/);
  assert.match(root.innerHTML,/\/talent\/assessments\?/);
  assert.match(root.innerHTML,/\/talent\/longitudinal\?/);
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
  const {ctx,root}=fixture();
  const read=ctx.api;ctx.api=async(path,options)=>{
    if(!options&&path.endsWith('/configuration'))return {levels:[{id:81,code:'READY',label:'Stage ready',numeric_value:null}],descriptors:[{id:91,framework_competency_id:71,rubric_level_id:81,descriptor:'Ready'}],rubric:{name:'Arts rubric'},kpi:null,review_candidate_policy:null,revision:7,semantic_fingerprint:'fingerprint'};
    return read(path,options);
  };
  await render(ctx);
  assert.match(root.innerHTML,/data-action="remove-descriptor" data-key="91"/);
});
