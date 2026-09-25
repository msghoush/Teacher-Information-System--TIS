const {test} = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const {
  progressVisual, radialGauge, gradeBars, gradeGauges, branchBars,
  rubricDistribution, rubricLevelIntensity,
  friendlyReason, overlapMatrix, periodVisual, errorPanel,
  bucketBars, bucketTable, distributionSection, talentedSection,
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
  // Part 2: the plot is the shared chart (one visible point => Bar; the suppressed period is a gap).
  assert.match(html, /width:25%/);
  assert.doesNotMatch(html, /width:99%|height:99%|>99%|99 of 100|99/);
  assert.match(html, /Unavailable/);
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

test('aggregate dashboard wires shared filters without Student-level clutter',()=>{
 const dashboard=fs.readFileSync(path.join(__dirname,'..','static','js','talent-dashboard.js'),'utf8');
 const source=fs.readFileSync(path.join(__dirname,'..','static','js','talent.js'),'utf8');
 for(const key of ['branch_id','grade_level','section_id','program_id','period_id','classification'])assert.match(dashboard,new RegExp(key));
 assert.match(source,/results-analytics\/academic-years/);
 assert.match(dashboard,/Each group is computed from its underlying population/);
 assert.doesNotMatch(dashboard,/Student preview|Review Candidate|Official Identification|learning_style_dimension/);
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

test('Talent module expands as a permission-aware sidebar tree using the shared sidebar icon system', () => {
  const shellSource = fs.readFileSync(path.join(__dirname, '..', 'ui_shell.py'), 'utf8');
  const base = fs.readFileSync(path.join(__dirname, '..', 'templates', 'base.html'), 'utf8');
  const shellCss = fs.readFileSync(path.join(__dirname, '..', 'static', 'css', 'app-shell.css'), 'utf8');
  // Acceptance B: Talent Review is legacy history and no longer a primary sidebar peer.
  assert.doesNotMatch(shellSource, /"label": "Talent Review"/);
  assert.doesNotMatch(shellSource, /"href": "\/talent\/reviews"/);
  for (const destination of ['/talent/overview','/talent/programs','/talent/assessments','/talent/analytics']) {
    assert.match(shellSource, new RegExp(destination.replaceAll('/','\\/')));
  }
  assert.match(shellSource, /talent_programs\.view/);
  assert.match(shellSource, /talent_assessments\.view/);
  assert.match(shellSource, /talent_analytics\.view/);
  // The Talent entry uses the shared inline-SVG icon macro like every other
  // module (no per-item brand image), and its visible label is never suppressed.
  const talentItem = shellSource.match(/"label": "Talent & Potential",[\s\S]*?\},/)[0];
  assert.match(talentItem, /"icon": "sparkles"/);
  assert.doesNotMatch(talentItem, /brand_logo/);
  assert.match(base, /class="sidebar-brand-symbol shell-icon"/);
  assert.match(base, /item\.brand_logo/);
  assert.match(base, /<span class="sidebar-link-copy">/);
  assert.match(shellCss, /\.sidebar-brand-symbol\s*\{[\s\S]*width:\s*var\(--app-icon-size\)[\s\S]*height:\s*var\(--app-icon-size\)[\s\S]*object-fit:\s*contain/);
  assert.match(base, /class="sidebar-tree"/);
  assert.match(base, /class="sidebar-tree-link/);
  assert.match(shellCss, /\.sidebar-brand-symbol\s*\{/);
  assert.doesNotMatch(shellCss, /\.sidebar-link--brand\s*\{/);
  assert.match(shellCss, /\.sidebar-tree\s*\{/);
  assert.match(shellCss, /\.sidebar-tree-link\.is-active/);
});

test('Talent page does not duplicate the primary sidebar module tree', () => {
  const template = fs.readFileSync(path.join(__dirname, '..', 'templates', 'talent', 'workspace.html'), 'utf8');
  assert.doesNotMatch(template, /<nav class="tp-nav"/);
  assert.match(template, /aria-label="Results and Analytics views"/);
  assert.match(template, /class="tp-results-nav"/);
});


test('top-level Talent navigation resets child context while analytics sub-navigation preserves analysis context', () => {
  const source = fs.readFileSync(path.join(__dirname, '..', 'static', 'js', 'talent.js'), 'utf8');
  assert.match(source, /\.sidebar-tree a\[href\*="\/talent\/"\]/);
  assert.match(source, /next\.search=qs\(\{academic_year_id:year\.value\}\)/);
  assert.match(source, /document\.querySelectorAll\('\.tp-results-nav a'\)/);
  assert.match(source, /program_id:params\.get\('program_id'\)/);
  assert.match(source, /\['programs','evaluation-plans','assessments'/);
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

// M18b-2: the Results & Analytics primary "how many Students are talented"
// indicator is now the backend M17-classification-derived Talented
// (Exceptional-only) family from /api/talent/results-analytics/.../talented
// (M18b-1) - never the legacy Official Identification/candidate_of_eligible/
// identified_of_eligible projection, which the M18b-2 rebuild removes from
// this current-Talent section (the underlying legacy Review/Identification
// services and workspace remain fully preserved elsewhere, untouched).
test('current-Talent chart consumes backend Classification labels without deriving a band or legacy authority',()=>{
 const dashboard=require('../static/js/talent-dashboard.js');
 const html=dashboard.analytics({classification:{state:'visible',buckets:[{label:'Exceptional',state:'visible',count:12,percentage:75},{label:'Advanced',state:'visible',count:4,percentage:25}]}},new URLSearchParams(),null);
 assert.match(html,/Exceptional/);assert.match(html,/75%/);
 assert.match(html,/Only Exceptional is Talented/);
 assert.doesNotMatch(html,/Official Identification|Review Candidate/);
});

test('talentedSection renders the backend Talented (Exceptional) rate and count, and the Organization value is never a client-side average of Branch rates', () => {
  const data = {
    organization: {distribution: {state: 'visible'}, summary: {talented_count: 10, applicable_denominator: 92, talented_rate_percentage: 10.87}},
    branch_breakdown: [
      {branch_id: 1, distribution: {state: 'visible', total: {state: 'visible', value: 2}, buckets: [{label: 'talented', state: 'visible', count: 1, percentage: 50}, {label: 'not_talented', state: 'visible', count: 1, percentage: 50}]}},
      {branch_id: 2, distribution: {state: 'visible', total: {state: 'visible', value: 90}, buckets: [{label: 'talented', state: 'visible', count: 9, percentage: 10}, {label: 'not_talented', state: 'visible', count: 81, percentage: 90}]}},
    ],
    not_currently_classifiable_count: 0,
  };
  const branchNames = new Map([['1', 'Branch A'], ['2', 'Branch B']]);
  const html = talentedSection(data, branchNames);
  // number() formats to one decimal place (existing app-wide convention),
  // so the backend's 10.87 renders as 10.9% - still nowhere near the naive
  // 30% average this proof case guards against.
  assert.match(html, /10\.9%/);
  assert.match(html, /10 of 92/);
  assert.match(html, /width:50%/);
  assert.match(html, /width:10%/);
  assert.match(html, /aria-label="Talented rate by Branch"/);
  // The proof case from M18b-1: Branch A 50% + Branch B 10% must never be
  // averaged into 30% anywhere in this rendered Organization figure.
  assert.doesNotMatch(html, />30%|width:30%/);
  // Batch 1: the count is current completed assessment RESULTS (one per Student per
  // Evaluation Period), not distinct Students, so the card never calls it Students.
  assert.match(html, /Talented \(Exceptional\) results/);
  assert.doesNotMatch(html, /Talented \(Exceptional\) Students/);
  assert.doesNotMatch(html, /Officially Identified|Official Identification is a separate/);
});

test('talentedSection renders a neutral unavailable state, never a fabricated zero or the literal "Protected for privacy"', () => {
  const html = talentedSection({organization: {distribution: {state: 'suppressed'}, summary: {}}, branch_breakdown: [], not_currently_classifiable_count: 0}, new Map());
  assert.match(html, /Unavailable/);
  assert.doesNotMatch(html, /Protected for privacy/i);
  assert.doesNotMatch(html, />0%|width:0%/);
});

test('gauges and comparison bars: talented indicator renders the protected state distinctly and never leaks its magnitude', () => {
  const visible = {state:'visible', percentage:37, numerator:37, denominator:100};
  const protectedCell = {state:'suppressed', percentage:91, numerator:91, denominator:100};
  const visibleGauge = radialGauge(visible, 'Talented (Exceptional) rate');
  assert.match(visibleGauge, /37%/);
  const protectedGauge = radialGauge(protectedCell, 'Talented (Exceptional) rate');
  assert.doesNotMatch(protectedGauge, /91|stroke-dashoffset| of /);
  assert.match(protectedGauge, /Unavailable/);
});

// Family 1/2 (Learning Style / Classification) distribution chart+table pair.
test('bucketBars/bucketTable render backend count and percentage only, with an accessible table equivalent for every chart, and a neutral unavailable state for a protected bucket', () => {
  const buckets = [
    {label: 'Visual', state: 'visible', count: 4, percentage: 40},
    {label: 'Unassigned', state: 'visible', count: 6, percentage: 60},
    {label: 'Auditory', state: 'suppressed', count: 91, percentage: 91},
  ];
  const chart = bucketBars(buckets, 'Learning Style Distribution');
  assert.match(chart, /width:40%/);
  assert.match(chart, /width:60%/);
  assert.doesNotMatch(chart, /91|width:91%/);
  assert.match(chart, /Unavailable/);
  const tableHtml = bucketTable('Learning Style Distribution', buckets);
  assert.match(tableHtml, /<table>/);
  assert.match(tableHtml, /Visual/);
  assert.match(tableHtml, /Unassigned/);
  assert.match(tableHtml, /40%/);
  assert.doesNotMatch(tableHtml, /91%/);
});

test('distributionSection never claims "Protected for privacy" and always renders a neutral unavailable state for a restricted/no-data distribution', () => {
  const html = distributionSection('tp-learning-style', 'Learning Style', 'Learning Style Distribution', 'description', {state: 'restricted', buckets: []});
  assert.doesNotMatch(html, /Protected for privacy/i);
  assert.match(html, /not available for this selection/);
  const empty = distributionSection('tp-classification', 'Classification', 'Classification Distribution', 'description', null);
  assert.match(empty, /not available for this selection/);
});

// M18b-2 contract: the frontend consumes the new backend endpoints for
// Learning Style/Classification/Talented and never reconstructs the
// deprecated four-dimension percentage fields or the dead
// learning_style_dimension parameter (both removed by M14/M18a/M18b-1).
test('Results consumes one governed aggregate endpoint without deprecated Learning Style dimensions',()=>{
 const source=fs.readFileSync(path.join(__dirname,'..','static','js','talent.js'),'utf8');
 const dashboard=fs.readFileSync(path.join(__dirname,'..','static','js','talent-dashboard.js'),'utf8');
 assert.match(source,/results-analytics\/academic-years\/\$\{encodeURIComponent\(ay\)\}\/dashboard/);
 assert.doesNotMatch(dashboard,/learning_style_dimension|visual_percentage|auditory_percentage|kinesthetic_percentage|reading_percentage/);
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

// M18b-2b: full 9-section Results & Analytics information architecture
// reorder (page header, summary cards, Learning Style, Classification,
// Current Talent, Competency Analysis grouped together, Results/Evaluation
// Progress, then Branch/Organization comparison), dedicated page-header
// copy, and the new progressive Classification filter.
test('Results & Analytics page header distinguishes the aggregate workspace from legacy identification',()=>{
 const html=require('../static/js/talent-dashboard.js').analytics({},new URLSearchParams(),null);
 assert.match(html,/<h2>Results &amp; Analytics<\/h2>/);
 assert.match(html,/One authorized population/);
 assert.doesNotMatch(html,/Official Identification|Review Candidate/);
});

test('the aggregate workspace renders six coherent analytical sections in order',()=>{
 const dashboard=require('../static/js/talent-dashboard.js');
 const html=dashboard.analytics({},new URLSearchParams(),null);
 const order=['Completion &amp; participation','Results &amp; Classification','<h2>Learning Style','Rubric Indicator analytics','<h2>Evaluation Periods','Selected comparisons'];
 let previous=-1;
 for(const token of order){const at=html.indexOf(token);assert.ok(at>previous,token);previous=at;}
 assert.doesNotMatch(html,/Student preview|Classification by Program/);
});

test('Classification filters the common backend projection without frontend threshold authority',()=>{
 const dashboard=require('../static/js/talent-dashboard.js');
 const params=dashboard.change(new URLSearchParams('program_id=5'),'classification','Exceptional');
 assert.equal(params.get('classification'),'Exceptional');
 assert.equal(params.get('program_id'),'5');
 const html=dashboard.analytics({options:{}},params,null);
 for(const band of ['Needs Improvement','Developing','Meets Expectations','Advanced','Exceptional'])assert.match(html,new RegExp(band));
 const source=fs.readFileSync(path.join(__dirname,'..','static','js','talent.js'),'utf8');
 assert.match(source,/qs\(Object.fromEntries\(params\)\)/);
});

test('legacy Review/Identification metrics never determine current dashboard Talent',()=>{
 const dashboard=require('../static/js/talent-dashboard.js');
 const html=dashboard.analytics({},new URLSearchParams(),null);
 assert.match(html,/Only Exceptional is Talented/);
 assert.doesNotMatch(html,/Review Candidate|Official Identification|Meets Program Criteria/);
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
  assert.match(html, /Unavailable/);
  assert.match(html, /Not available for this view/);
  // Intensity is present for every row (order-derived), including protected ones.
  assert.match(html, /--tp-rubric-intensity:0\.000/);
  assert.match(html, /--tp-rubric-intensity:1\.000/);
});
