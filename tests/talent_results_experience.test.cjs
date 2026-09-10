const {test} = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const {
  progressVisual, radialGauge, gradeBars, gradeGauges, branchBars,
  rubricDistribution, rubricLevelIntensity,
  friendlyReason, overlapMatrix, periodVisual, errorPanel,
} = require('../static/js/talent.js');

test('visible server percentages alone control progress length', () => {
  const visible = progressVisual({state:'visible', percentage:42.5, numerator:17, denominator:40}, 'Completion');
  assert.match(visible, /width:42\.5%/);
  assert.match(visible, /42\.5 percent/);
  for (const state of ['suppressed','complementary_suppressed','restricted','coarsened','no_data']) {
    const protectedHtml = progressVisual({state, percentage:97, numerator:97, denominator:100}, 'Completion');
    assert.doesNotMatch(protectedHtml, /97|width:|progress-track|aria-label=.*percent/);
  }
});

test('Progress Over Time translates every governed comparison reason', () => {
  const governed = ['missing_cycle','cycle_not_authoritative','cancelled_period','no_frozen_population','metric_unavailable','framework_changed','privacy_protected'];
  for (const reason of governed) {
    const copy = friendlyReason(reason);
    assert.ok(copy.length > 20);
    assert.doesNotMatch(copy, /_/);
  }
});

test('Progress Over Time chart never encodes protected magnitude', () => {
  const html = periodVisual({metric:'completion_coverage',points:[
    {evaluation_period:{id:1,sequence:1,label:'Autumn',status:'planned'},metric_result:{state:'visible',percentage:25,numerator:1,denominator:4}},
    {evaluation_period:{id:2,sequence:2,label:'Spring',status:'planned'},metric_result:{state:'suppressed',percentage:99,numerator:99,denominator:100}},
  ]});
  assert.match(html, /height:25%/);
  assert.doesNotMatch(html, /height:99%|>99%|99 of 100/);
  assert.match(html, /Protected for privacy/);
  assert.match(html, /Autumn[\s\S]*Spring/);
  assert.match(html, /tp-period-path/);
  assert.doesNotMatch(html, /Baseline|Final/);
});

test('gauges and comparison bars encode visible percentages only', () => {
  const visible={state:'visible',percentage:42,numerator:21,denominator:50};
  const protectedCell={state:'suppressed',percentage:97,numerator:97,denominator:100};
  assert.match(radialGauge(visible,'Completion'),/stroke-dashoffset/);
  assert.match(radialGauge(visible,'Completion'),/42%/);
  const protectedGauge=radialGauge(protectedCell,'Completion');
  assert.doesNotMatch(protectedGauge,/97|stroke-dashoffset| of /);
  const grades=gradeBars([{label:'Grade 6',cell:visible},{label:'Grade 7',cell:protectedCell}],'Completion');
  assert.match(grades,/width:42%/);
  assert.doesNotMatch(grades,/97|width:97%/);
  const gaugeRow=gradeGauges([{label:'Grade 6',cell:visible},{label:'Grade 7',cell:protectedCell}]);
  assert.match(gaugeRow,/Results by grade/);
  assert.doesNotMatch(gaugeRow,/97/);
  const branches=branchBars([{label:'North',cell:visible,href:'/talent/branch?branch_id=2'},{label:'South',cell:protectedCell,href:'/talent/branch?branch_id=3'}]);
  assert.match(branches,/width:42%/);
  assert.doesNotMatch(branches,/97|width:97%/);
});

test('Students Across Programs has accessible grid semantics and plain meaning', () => {
  const data={programs:[{id:1,name:'Arts'},{id:2,name:'STEM'}],matrix:[
    {program_id:1,cells:[{program_id:1,state:'visible',value:3},{program_id:2,state:'visible',value:1}]},
    {program_id:2,cells:[{program_id:1,state:'visible',value:1},{program_id:2,state:'no_data'}]},
  ]};
  const html=overlapMatrix(data,()=>'<a href="/talent/portfolio">Open Program results</a>');
  assert.match(html,/role="grid"/);
  assert.match(html,/Students in both Arts and STEM/);
  assert.match(html,/In this Program/);
  assert.match(html,/tp-nodata-cell/);
});

test('Results source uses friendly public names and no technical analytics labels', () => {
  const source=fs.readFileSync(path.join(__dirname,'..','static','js','talent.js'),'utf8');
  const router=fs.readFileSync(path.join(__dirname,'..','routers','talent_ui.py'),'utf8');
  assert.match(source,/Students Across Programs/);
  assert.match(source,/Progress Over Time/);
  assert.match(router,/"portfolio": \("Program Results"/);
  assert.match(router,/"branch": \("Branch Results"/);
  assert.match(router,/"students": \("Students"/);
  assert.doesNotMatch(source,/Participation Overlap|Organization Intelligence|metric code|privacy class|provider version/);
});

test('responsive and accessibility invariants are present', () => {
  const css=fs.readFileSync(path.join(__dirname,'..','static','css','talent.css'),'utf8');
  const template=fs.readFileSync(path.join(__dirname,'..','templates','talent','workspace.html'),'utf8');
  assert.match(css,/@media \(max-width: 680px\)/);
  assert.match(css,/@media \(prefers-reduced-motion: reduce\)/);
  assert.match(css,/overflow-x:auto/);
  assert.match(template,/aria-label="Results and Analytics views"/);
  assert.match(template,/for="tp-dimension"/);
  assert.match(template,/for="tp-branch"/);
  assert.match(template,/for="tp-grade"/);
  assert.match(css,/\.tp-grade-gauges/);
  assert.match(css,/\.tp-branch-row/);
  assert.match(css,/\.tp-period-path/);
});

test('analytics source wires supported filters and keeps secondary totals compact', () => {
  const source=fs.readFileSync(path.join(__dirname,'..','static','js','talent.js'),'utf8');
  assert.match(source,/params\.set\('branch_id',branch\.value\)/);
  assert.match(source,/params\.set\('grade_level',grade\.value\)/);
  assert.doesNotMatch(source,/Program patterns/);
  assert.doesNotMatch(source,/Talent Map preview/);
  assert.doesNotMatch(source,/program-portfolio\?\$\{qs\(common\)\}/);
  assert.match(source,/Open Program Results/);
  assert.match(source,/Open Talent Map/);
  assert.match(source,/Assessment progress by Grade/);
  assert.match(source,/Detailed totals/);
  assert.match(source,/Meets Program Criteria:<\/strong>/);
});

test('the shared Grade filter is Planning-driven, not a blanket hardcoded KG-12 catalog', () => {
  const source=fs.readFileSync(path.join(__dirname,'..','static','js','talent.js'),'utf8');
  assert.doesNotMatch(source,/\['KG',\.\.\.Array\.from\(\{length:12\}/);
  assert.match(source,/programs\/planning-grades\?/);
  assert.match(source,/academic_year_id:year\.value/);
  assert.match(source,/programs\/planning-sections\?/);
  assert.match(source,/No Sections configured for this Grade\./);
  assert.match(fs.readFileSync(path.join(__dirname,'..','templates','talent','workspace.html'),'utf8'),/for="tp-section"/);
});

test('Talent navigation has one primary module entry, not a duplicated analytics list', () => {
  const template = fs.readFileSync(path.join(__dirname, '..', 'templates', 'talent', 'workspace.html'), 'utf8');
  const navMatch = template.match(/<nav class="tp-nav"[\s\S]*?<\/nav>/);
  assert.ok(navMatch, 'primary tp-nav markup must exist');
  const primaryNav = navMatch[0];
  const primaryLoopMatch = primaryNav.match(/\{% for key in (\[[^\]]*\]) %\}/);
  assert.ok(primaryLoopMatch, 'primary nav must iterate an explicit view-key list');
  const primaryKeys = primaryLoopMatch[1];
  // The primary nav lists each top-level module once and resolves the whole
  // analytics family to exactly one "Results & Analytics" entry point, never a
  // per-page repeat of every analytics-family view (the sub-nav below already
  // exists to present that family in a compact form once the user is inside it).
  assert.match(primaryNav, /Results &amp; Analytics/);
  for (const key of ['talent-map', 'portfolio', 'overlap', 'longitudinal', 'branch', 'students']) {
    assert.doesNotMatch(primaryKeys, new RegExp(`'${key}'`));
  }
  assert.match(template, /aria-label="Results and Analytics views"/);
});

test('Apply-context ceremony is removed: selections auto-apply, no required confirm click', () => {
  const template = fs.readFileSync(path.join(__dirname, '..', 'templates', 'talent', 'workspace.html'), 'utf8');
  const source = fs.readFileSync(path.join(__dirname, '..', 'static', 'js', 'talent.js'), 'utf8');
  assert.doesNotMatch(template, /Apply context/);
  // A change on any context select schedules the same apply/reload path the old
  // submit-only button used, with a short debounce so rapid multi-select changes
  // collapse into one reload instead of one request per dropdown.
  assert.match(source, /form\.addEventListener\('change'/);
  assert.match(source, /AUTO_APPLY_DEBOUNCE_MS/);
  assert.match(source, /function applyContext\(\)/);
  assert.match(source, /form\.addEventListener\('submit',event=>\{event\.preventDefault\(\);clearTimeout\(autoApplyTimer\);applyContext\(\);\}\)/);
});

test('permission and analytics availability failures have distinct plain-language states', () => {
  assert.match(errorPanel({status:403,message:'This view is not available.'}),/Permission denied/);
  assert.match(errorPanel({status:503,message:'Try later.'}),/Analytics unavailable/);
  assert.doesNotMatch(errorPanel({status:503,message:'Try later.'}),/provider|policy|privacy class/i);
});

test('the Organization Overview primary indicator is sourced from Official Identification, not a candidate/rubric metric', () => {
  const source = fs.readFileSync(path.join(__dirname, '..', 'static', 'js', 'talent.js'), 'utf8');
  // The gauge must come from the "identified_of_eligible" projection, gated
  // by the Official Identification view permission - never from
  // candidate_of_eligible (Meets Program Criteria) or a rubric level, and
  // never computed client-side from raw counts.
  assert.match(source, /identificationAllowed=can\('talent_official_identifications\.view'\)/);
  assert.match(source, /metric:'identified_of_eligible'/);
  assert.match(source, /identifiedCell=identifiedMap&&identifiedMap\.organization_total\?identifiedMap\.organization_total:null/);
  assert.match(source, /radialGauge\(identifiedCell,labels\.identified_of_eligible\)/);
  assert.match(source, /identifiedIndicator\+/);
  assert.match(source, /Official Identification is a separate, permanent human decision/);
});

test('gauges and comparison bars: identified indicator renders the protected state distinctly and never leaks its magnitude', () => {
  const visible = {state:'visible', percentage:37, numerator:37, denominator:100};
  const protectedCell = {state:'suppressed', percentage:91, numerator:91, denominator:100};
  const visibleGauge = radialGauge(visible, 'Officially confirmed share');
  assert.match(visibleGauge, /37%/);
  const protectedGauge = radialGauge(protectedCell, 'Officially confirmed share');
  assert.doesNotMatch(protectedGauge, /91|stroke-dashoffset| of /);
  assert.match(protectedGauge, /Protected for privacy/);
});

test('rubricDistribution builds an order-derived (not value-derived) intensity for any label set and count', () => {
  assert.equal(rubricLevelIntensity(0, 4), 0);
  assert.equal(rubricLevelIntensity(3, 4), 1);
  assert.equal(rubricLevelIntensity(0, 1), 1);
  // Two different level counts/labels - never a hardcoded four-level set.
  const threeLevel = rubricDistribution([
    {label:'Emerging', display_order:1, state:'visible', percentage:20, count:2},
    {label:'Developing', display_order:2, state:'visible', percentage:30, count:3},
    {label:'Mastery', display_order:3, state:'visible', percentage:50, count:5},
  ]);
  assert.match(threeLevel, /Emerging/);
  assert.match(threeLevel, /Mastery/);
  assert.doesNotMatch(threeLevel, /Beginning|Approaching|Meets|Exceeds/);
  const twoLevel = rubricDistribution([
    {label:'Not yet', display_order:1, state:'visible', percentage:60, count:6},
    {label:'Achieved', display_order:2, state:'visible', percentage:40, count:4},
  ]);
  assert.match(twoLevel, /Not yet/);
  assert.match(twoLevel, /Achieved/);
});

test('rubricDistribution and the primary indicator gauge carry accessible chart labeling', () => {
  const html = rubricDistribution([
    {label:'Beginning Mastery', display_order:1, state:'visible', percentage:15, count:1},
    {label:'Full Mastery', display_order:2, state:'visible', percentage:85, count:6},
  ]);
  assert.match(html, /role="group" aria-label="Rubric level distribution"/);
  assert.match(html, /role="img" aria-label="Beginning Mastery: 15 percent"/);
  assert.match(html, /role="img" aria-label="Full Mastery: 85 percent"/);
  const gauge = radialGauge({state:'visible', percentage:60, numerator:6, denominator:10}, 'Officially confirmed share');
  assert.match(gauge, /role="img" aria-label="Officially confirmed share: 60 percent"/);
});

test('rubricDistribution never derives a bar width or numeric text for a protected level, only order-based intensity', () => {
  const html = rubricDistribution([
    {label:'Level A', display_order:1, state:'visible', percentage:10, count:1},
    {label:'Level B', display_order:2, state:'suppressed', percentage:88, count:88},
    {label:'Level C', display_order:3, state:'restricted', percentage:5, count:5},
  ]);
  assert.match(html, /width:10%/);
  assert.doesNotMatch(html, /88|width:88%|width:5%/);
  assert.match(html, /tp-rubric-track-state/);
  assert.match(html, /Protected for privacy/);
  assert.match(html, /Not available for this view/);
  // Intensity is present for every row (order-derived), including protected ones.
  assert.match(html, /--tp-rubric-intensity:0\.000/);
  assert.match(html, /--tp-rubric-intensity:1\.000/);
});
