const {test} = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');

const experience = require('../static/js/talent-experience.js');

function fakeDetails({kind, key, open}) {
  return {
    open,
    dataset: key ? {tpPersistKey:key} : {},
    classList:{contains:name=>name===kind},
    matches:selector=>selector.includes(kind),
    querySelector:()=>null,
    closest:()=>null,
  };
}
function fakeScope(details) {
  return {
    querySelectorAll(selector) {
      if (selector === 'details.tp-grade-rubric, details.tp-rubric-competency') return details;
      if (selector === 'details[data-tp-persist-key]') return details.filter(d=>d.dataset.tpPersistKey);
      return [];
    }
  };
}

test('private Current rubric and Re-assessment labels collapse to the visible Evaluation label', () => {
  assert.equal(experience.isPrivateEvaluationLabel('Term 1 · Current rubric'), true);
  assert.equal(experience.isPrivateEvaluationLabel('Term 1 · Re-assessment'), true);
  assert.equal(experience.isPrivateEvaluationLabel('Term 1'), false);
  assert.equal(experience.publicEvaluationLabel('Term 1 · Current rubric'), 'Term 1');
  assert.equal(experience.publicEvaluationLabel('Term 1 · Re-assessment'), 'Term 1');
});

test('rubric distribution local Program filter uses requested selection, then global context, then first Program', () => {
  const programs=[{id:11,name:'Mental Math'},{id:12,name:'Qaaidah Nouraniah'}];
  assert.equal(experience.chooseRubricProgramId(programs,'12','11'),'12');
  assert.equal(experience.chooseRubricProgramId(programs,'999','11'),'11');
  assert.equal(experience.chooseRubricProgramId(programs,'','','11'),'11');
  assert.equal(experience.chooseRubricProgramId(programs,'','',''),'11');
  assert.equal(experience.chooseRubricProgramId([], '', ''), '');
});

test('Grade and Competency disclosure state restores exactly after a save rerender', () => {
  const before=[
    fakeDetails({kind:'tp-grade-rubric',key:'grade:Grade 3',open:true}),
    fakeDetails({kind:'tp-rubric-competency',key:'competency:Grade 3:Mental Calculation',open:true}),
    fakeDetails({kind:'tp-rubric-competency',key:'competency:Grade 3:Number Sense',open:false}),
  ];
  const state=experience.snapshotDisclosureState(fakeScope(before));
  assert.deepEqual(state,{
    'grade:Grade 3':true,
    'competency:Grade 3:Mental Calculation':true,
    'competency:Grade 3:Number Sense':false,
  });
  const after=[
    fakeDetails({kind:'tp-grade-rubric',key:'grade:Grade 3',open:false}),
    fakeDetails({kind:'tp-rubric-competency',key:'competency:Grade 3:Mental Calculation',open:false}),
    fakeDetails({kind:'tp-rubric-competency',key:'competency:Grade 3:Number Sense',open:true}),
  ];
  experience.restoreDisclosureState(fakeScope(after),state);
  assert.equal(after[0].open,true);
  assert.equal(after[1].open,true);
  assert.equal(after[2].open,false);
});

test('rubric empty state names the selected Program and restricted rows remain privacy-protected', () => {
  const empty=experience.rubricDistributionHtml({distributions:[]},'Mental Math');
  assert.match(empty,/No completed rubric results are available for Mental Math yet/);
  const protectedHtml=experience.rubricDistributionHtml({distributions:[{
    competency_label:'Mental Calculation',rubric_name:'KPI 1',state:'restricted',levels:[]
  }]},'Mental Math');
  assert.match(protectedHtml,/Protected for privacy/);
  assert.doesNotMatch(protectedHtml,/percentage|width:/);
});

test('Talent template loads the owner adjustment layer after canonical Talent scripts', () => {
  const template=fs.readFileSync(path.join(__dirname,'..','templates','talent','workspace.html'),'utf8');
  const css=fs.readFileSync(path.join(__dirname,'..','static','css','talent-experience.css'),'utf8');
  assert.match(template,/css\/talent-experience\.css/);
  assert.match(template,/js\/talent\.js[\s\S]*js\/talent-experience\.js/);
  assert.match(css,/body\[data-page-key="talent"\] \.sidebar-tree\s*\{[\s\S]*border-left:\s*0/);
  assert.match(css,/\.sidebar-tree-link\.is-active[\s\S]*box-shadow:\s*none/);
  assert.match(css,/talent-ghars-symbol\.png/);
  assert.match(css,/\.tp-selected-badge/);
  assert.match(css,/\.tp-rubric-program-filter/);
});

test('owner adjustment source keeps the selected Term in-place and adds one-Program rubric filtering', () => {
  const source=fs.readFileSync(path.join(__dirname,'..','static','js','talent-experience.js'),'utf8');
  assert.match(source,/querySelectorAll\('\.tp-selected-evaluation'\)/);
  assert.match(source,/tp-selected-badge/);
  assert.match(source,/rememberedDisclosureState/);
  assert.match(source,/rubricSelectedProgramId/);
  assert.match(source,/assessment_state=completed/);
  assert.match(source,/No Official Identification result yet/);
  assert.match(source,/No Program Criteria result yet/);
});

test('phase-2 owner package wires roster and identification filters plus ordered magnitude colors',()=>{
  const experience=fs.readFileSync(path.join(__dirname,'..','static','js','talent-experience.js'),'utf8');
  const css=fs.readFileSync(path.join(__dirname,'..','static','css','talent-experience.css'),'utf8');
  const api=require('../static/js/talent-experience.js');
  assert.match(experience,/tp-assessment-roster-filters/);
  assert.match(experience,/Identification Classification/);
  assert.match(experience,/tp-overview-branding/);
  assert.equal(api.magnitudeBucket(5),1);assert.equal(api.magnitudeBucket(45),3);assert.equal(api.magnitudeBucket(95),5);
  assert.match(css,/talent-ghars-logo\.svg/);assert.match(css,/body\.tp-overview-branding \.page-title/);assert.match(css,/tp-magnitude-5/);
});
test('phase-2 assessment editor never falls back across Grade and has professional KPI hierarchy',()=>{
  const source=fs.readFileSync(path.join(__dirname,'..','static','js','talent-operations.js'),'utf8');
  assert.doesNotMatch(source,/gradeScoped\.length\?gradeScoped:allCompetencies/);
  assert.match(source,/No assessment criteria for Grade/);assert.match(source,/Reload Saved Rubric/);
  assert.match(source,/tp-assessment-grid/);assert.match(source,/tp-assessment-kpi-label/);
});
test('phase-2 Students keeps protected style categories and removes nested vertical table scrolling',()=>{
  const template=fs.readFileSync(path.join(__dirname,'..','templates','students.html'),'utf8');
  const css=fs.readFileSync(path.join(__dirname,'..','static','css','students.css'),'utf8');
  assert.match(template,/Learning Style categories remain visible below without counts or proportional bar lengths/);
  assert.match(css,/overflow-y: visible/);assert.match(css,/stu-ls-row-label::before/);
});
