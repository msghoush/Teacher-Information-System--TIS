const {test}=require('node:test');
const assert=require('node:assert/strict');
const {render}=require('../static/js/talent-evaluation-workspace.js');

function fixture(allowed=true) {
  const calls=[], feedback={textContent:'',setAttribute(){}};
  const root={innerHTML:'',onclick:null,onsubmit:null,oninput:null,querySelector:()=>feedback,querySelectorAll:()=>[]};
  const ctx={root,year:'100',params:new URLSearchParams('program_id=11'),can:()=>allowed,api:async(path,options)=>{
    calls.push({path,options});
    if(path.startsWith('/api/talent/evaluation-plans?'))return [];
    if(path==='/api/talent/programs')return [{id:11,name:'Performing Arts'}];
    if(path==='/api/talent/assessment-cycles?academic_year_id=100&program_id=11')return [];
    if(path.endsWith('/academic-years'))return [{id:21,academic_year_id:100,is_enabled:true}];
    if(path.endsWith('/frameworks'))return [{id:31,title:'Arts rubric',version_number:1,status:'active'}];
    if(options)return {};
    throw new Error(`Unexpected ${path}`);
  }};
  return {ctx,root,calls,feedback};
}

test('authorized empty context offers real Plan and evaluation creation',async()=>{
  const {ctx,root}=fixture();await render(ctx);
  assert.match(root.innerHTML,/Create Evaluation Plan/);
  assert.match(root.innerHTML,/Prepare evaluation/);
  assert.match(root.innerHTML,/Student list is fixed/);
  assert.doesNotMatch(root.innerHTML,/cycle_id|framework_version_id|program_academic_year_configuration_id/);
});

test('read permission gates the workspace',async()=>{
  const {ctx,root,calls}=fixture(false);await render(ctx);
  assert.match(root.innerHTML,/do not have permission/);
  assert.equal(calls.length,0);
});

test('Plan creation posts the selected real annual configuration',async()=>{
  const {ctx,root,calls}=fixture();await render(ctx);
  const original=global.FormData;global.FormData=class {constructor(){return new Map();}};
  try {root.onsubmit({target:{matches:()=>true,dataset:{form:'plan'},querySelector:()=>({textContent:'',setAttribute(){}})},preventDefault(){}});} finally {global.FormData=original;}
  await new Promise(resolve=>setImmediate(resolve));
  const write=calls.find(c=>c.options);
  assert.equal(write.path,'/api/talent/evaluation-plans');
  assert.deepEqual(JSON.parse(write.options.body),{program_academic_year_configuration_id:21});
});
