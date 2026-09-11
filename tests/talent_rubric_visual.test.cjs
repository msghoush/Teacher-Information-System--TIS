const {test}=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const rubric=require('../static/js/talent-rubric-visual.js');

test('shared rubric strength follows arbitrary display order and count',()=>{
  const levels=[{id:7,label:'Seed',display_order:30},{id:8,label:'Flight',display_order:90},{id:9,label:'Spark',display_order:10}];
  assert.deepEqual(rubric.ordered(levels).map(level=>level.label),['Spark','Seed','Flight']);
  assert.equal(rubric.intensity(0,3),0);
  assert.equal(rubric.intensity(2,3),1);
  const low=rubric.badge(levels[2],levels),high=rubric.badge(levels[1],levels,{selected:true});
  assert.match(low,/Spark/); assert.match(low,/1\/3/); assert.match(low,/0\.000/);
  assert.match(high,/Flight/); assert.match(high,/3\/3/); assert.match(high,/1\.000/); assert.match(high,/is-selected/);
  assert.doesNotMatch(low+high,/Beginning|Approaching|Meets|Exceeds/);
});

test('shared rubric treatment is loaded by Talent and Student Profile surfaces',()=>{
  const workspace=fs.readFileSync('templates/talent/workspace.html','utf8');
  const profile=fs.readFileSync('templates/student_profile.html','utf8');
  const reduced=fs.readFileSync('static/css/talent-rubric-visual.css','utf8');
  assert.match(workspace,/talent-rubric-visual\.js/);
  assert.match(profile,/talent-rubric-visual\.js/);
  assert.match(reduced,/@media \(prefers-reduced-motion: reduce\)/);
});


test('compact rubric badge shows only the ordered number while preserving accessible level text',()=>{
  const levels=[
    {id:1,label:'Beginning',display_order:1},
    {id:2,label:'Approaching',display_order:2},
    {id:3,label:'Meets',display_order:3},
    {id:4,label:'Exceeds',display_order:4},
    {id:5,label:'Exceptional',display_order:5},
  ];
  const html=rubric.compactBadge(levels[2],levels);
  assert.match(html,/>3<\/span>/);
  assert.match(html,/Level 3 of 5 — Meets/);
  assert.match(html,/--tp-rubric-intensity:0\.500/);
  assert.doesNotMatch(html,/>Meets</);
});
