'use strict';
/* Deployment Acceptance Correction B: Student identity (name / Learning Style /
 * automatic Classification / Talented) across the Talent & Potential module, and
 * the removal of Review Candidate / Official Identification from the current
 * workflow. Structural verification against a DOM stub (not a real browser). */
const {test} = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const identity = require('../static/js/talent-student-identity.js');
const {render} = require('../static/js/talent-operations.js');
const {createEnv} = require('./talent_runtime_harness.cjs');

const JS = name => fs.readFileSync(path.join(__dirname, '..', 'static', 'js', name), 'utf8');
const LEARNING_STYLES = ['Visual', 'Auditory', 'Read/Write', 'Kinesthetic', 'Verbal', 'Non-verbal', 'Quantitative', 'Spatial'];
const CLASSIFICATIONS = ['Needs Improvement', 'Developing', 'Meets Expectations', 'Advanced', 'Exceptional'];

function domRoot() {
  return {innerHTML: '', querySelector: () => ({textContent: '', setAttribute() {}, addEventListener() {}}), querySelectorAll: () => []};
}
async function withWindow(work) {
  const previous = global.window;
  global.window = {addEventListener() {}, removeEventListener() {}, confirm: () => true};
  try { return await work(); } finally { global.window = previous; }
}

// ---- shared helper ---------------------------------------------------------
test('shared identity renders every approved Learning Style category as text, never inventing one', () => {
  for (const style of LEARNING_STYLES) {
    const html = identity.identityHtml({name: 'Ada', learningStyle: style, showClassification: false});
    assert.match(html, new RegExp(`Learning Style:</span> ${style.replace('/', '\\/')}`));
  }
  const unassigned = identity.identityHtml({name: 'Ada', learningStyle: null, showClassification: false});
  assert.match(unassigned, /Learning Style:<\/span> Unassigned/);
  const invented = identity.identityHtml({name: 'Ada', learningStyle: 'Musical', showClassification: false});
  assert.doesNotMatch(invented, /Musical/);
  assert.match(invented, /Unassigned/);
  // undefined = not provided on this surface: omitted entirely.
  assert.doesNotMatch(identity.identityHtml({name: 'Ada', showClassification: false}), /Learning Style/);
});

test('Classification chip is text-labelled; Talented appears when and only when Exceptional', () => {
  for (const label of CLASSIFICATIONS) {
    const html = identity.identityHtml({name: 'Ada', learningStyle: 'Visual', classification: label, isTalented: label === 'Exceptional'});
    assert.match(html, new RegExp(`Classification:</span> ${label}`));
    if (label === 'Exceptional') assert.match(html, /tp-badge-talented">Talented</);
    else assert.doesNotMatch(html, /Talented/);
  }
});

test('missing or unknown classification is never fabricated; Not assessed is opt-in and neutral', () => {
  assert.doesNotMatch(identity.identityHtml({name: 'Ada', classification: null}), /Classification/);
  assert.match(identity.identityHtml({name: 'Ada', classification: null, notAssessed: true}), /Classification: Not assessed/);
  assert.doesNotMatch(identity.identityHtml({name: 'Ada', classification: 'Legend', isTalented: true}), /Legend|Talented/);
  // Legacy states are never an input to the helper.
  assert.doesNotMatch(identity.identityHtml({name: 'Ada', classification: 'identified', isTalented: true}), /identified|Talented/);
});

test('shared identity escapes markup in a Student name', () => {
  const html = identity.identityHtml({name: '<img src=x onerror=1>'});
  assert.doesNotMatch(html, /<img/);
  assert.match(html, /&lt;img/);
});

// ---- Student Assessments roster -------------------------------------------
function rosterCtx(rows, members, calls) {
  const cycle = {id: 61, program_id: 11, title: 'Term 1', evaluation_label: 'Term 1', status: 'open'};
  return {root: domRoot(), year: '2026', view: 'assessments', params: new URLSearchParams('cycle_id=61&program_id=11'), can: () => true, notify() {},
    api: async path => {
      calls.push(path);
      if (path.startsWith('/api/talent/assessments?')) return rows;
      if (path.startsWith('/api/talent/assessments/contexts?')) return [cycle];
      if (path.endsWith('/eligible-students')) return {members};
      throw new Error(`Unexpected ${path}`);
    }};
}
const current = (id, student, status, extra = {}) => ({id, student_id: student, status, is_current: true, academic_year_id: '2026', program_id: '11', evaluation_context_cycle_id: 61, reassessment: {required: false}, actions: [], ...extra});

test('roster shows Learning Style, backend Classification and Talented only where applicable', async () => {
  const members = [
    {student_id: 1, can_start: true, student_name: 'Exceptional Ella', learning_style: 'Visual', grade_level: '3', section_name: 'A', branch_name: 'Main'},
    {student_id: 2, can_start: true, student_name: 'Advanced Adam', learning_style: 'Read/Write', grade_level: '3', section_name: 'A', branch_name: 'Main'},
    {student_id: 3, can_start: true, student_name: 'Working Wes', learning_style: null, grade_level: '3', section_name: 'B', branch_name: 'Main'},
    {student_id: 4, can_start: true, student_name: 'Fresh Fay', learning_style: 'Spatial', grade_level: '3', section_name: 'B', branch_name: 'Main'},
  ];
  const rows = [
    current(11, 1, 'completed', {classification: 'Exceptional', is_talented: true}),
    current(12, 2, 'completed', {classification: 'Advanced', is_talented: false}),
    // in progress rows never carry a classification, even if a stale field were present
    current(13, 3, 'in_progress', {classification: null, is_talented: false}),
  ];
  const calls = [];
  const ctx = rosterCtx(rows, members, calls);
  await withWindow(() => render(ctx));
  const html = ctx.root.innerHTML;
  const rowFor = name => html.split('<tr>').find(r => r.includes(name));
  assert.match(rowFor('Exceptional Ella'), /Learning Style:<\/span> Visual/);
  assert.match(rowFor('Exceptional Ella'), /Classification:<\/span> Exceptional/);
  assert.match(rowFor('Exceptional Ella'), /Talented/);
  assert.match(rowFor('Advanced Adam'), /Learning Style:<\/span> Read\/Write/);
  assert.match(rowFor('Advanced Adam'), /Classification:<\/span> Advanced/);
  assert.doesNotMatch(rowFor('Advanced Adam'), /Talented/);
  assert.match(rowFor('Working Wes'), /Learning Style:<\/span> Unassigned/);
  assert.match(rowFor('Working Wes'), /In progress/);
  assert.doesNotMatch(rowFor('Working Wes'), /Classification:<\/span>/);
  assert.match(rowFor('Working Wes'), /Not assessed/);
  assert.doesNotMatch(rowFor('Fresh Fay'), /Classification:<\/span>|Talented/);
  assert.match(rowFor('Fresh Fay'), /Not started/);
  assert.match(rowFor('Fresh Fay'), /Start Assessment/);
  // Roster: no legacy columns/actions; exactly the required columns.
  assert.match(html, /<th>Student<\/th><th>Grade<\/th><th>Section<\/th><th>Assessment Status<\/th><th>Classification<\/th><th>Action<\/th>/);
  assert.doesNotMatch(html, /Review Status|Review status|Official Identification|Open Review|Officially|Meets Program Criteria/);
  // Structural N+1 guard: one call per bulk endpoint, none per Student.
  assert.equal(calls.filter(c => c.endsWith('/eligible-students')).length, 1);
  assert.equal(calls.filter(c => c.startsWith('/api/talent/assessments?')).length, 1);
  assert.ok(calls.length <= 5, `bounded bulk requests only, got ${calls.length}`);
  assert.equal(calls.filter(c => /\/(students?|learning-style|classification)/i.test(c)).length, 0);
});

test('a historical (non-current) completed assessment never supplies the roster classification', async () => {
  const members = [{student_id: 1, can_start: true, student_name: 'Hist Hana', learning_style: 'Auditory', grade_level: '3', section_name: 'A'}];
  const rows = [current(11, 1, 'completed', {is_current: false, classification: 'Exceptional', is_talented: true})];
  const ctx = rosterCtx(rows, members, []);
  await withWindow(() => render(ctx));
  assert.doesNotMatch(ctx.root.innerHTML, /Classification:<\/span>|tp-badge-talented/);
});

// ---- Assessment detail header ----------------------------------------------
function detailCtx(assessment) {
  return {root: domRoot(), year: '2026', view: 'assessments', params: new URLSearchParams(`assessment_id=${assessment.id}&program_id=11`),
    can: key => key === 'talent_programs.view' || key === 'talent_assessments.view' || key === 'talent_assessments.manage',
    notify() {}, navigate() {},
    api: async p => {
      if (p === `/api/talent/assessments/${assessment.id}` || p === `/api/talent/assessments/${assessment.id}/continue`) return assessment;
      if (p.endsWith('/competency-results')) return [];
      if (p.endsWith('/configuration')) return {levels: [], rubrics: [], descriptors: []};
      if (/\/api\/talent\/programs\/11\/frameworks\/\d+$/.test(p)) return {competencies: []};
      if (p === '/api/talent/programs/11') return {id: 11, name: 'Arts'};
      throw new Error(`Unexpected ${p}`);
    }};
}
test('assessment header shows identity, status, Program result and Classification; Exceptional is Talented', async () => {
  const base = {id: 9, program_id: 11, framework_version_id: 3, cycle_id: 5, academic_year_id: 1, revision: 1, is_current: true, reassessment: {required: false}, actions: [],
    context: {student_name: 'Ella E', student_learning_style: 'Kinesthetic', grade_level: '3'}};
  const done = {...base, status: 'completed', overall_result: {available: true, average: 4.8, scale_max: 5, normalized_percent: 96}, classification: 'Exceptional', is_talented: true};
  const ctx = detailCtx(done);
  await withWindow(() => render(ctx));
  assert.match(ctx.root.innerHTML, /Ella E/);
  assert.match(ctx.root.innerHTML, /Learning Style:<\/span> Kinesthetic/);
  assert.match(ctx.root.innerHTML, /Classification:<\/span> Exceptional/);
  assert.match(ctx.root.innerHTML, /Talented/);
  assert.match(ctx.root.innerHTML, /Overall Program Result 4\.8 out of 5/);
  const draft = {...base, status: 'in_progress', overall_result: {available: true, average: 4.8, scale_max: 5}, classification: null, is_talented: false};
  const ctx2 = detailCtx(draft);
  await withWindow(() => render(ctx2));
  assert.match(ctx2.root.innerHTML, /Learning Style:<\/span> Kinesthetic/);
  assert.doesNotMatch(ctx2.root.innerHTML, /Classification:<\/span>|Talented|Overall Program Result/);
  assert.doesNotMatch(ctx.root.innerHTML, /Official Identification|Review Status/);
});

// ---- Legacy history view ----------------------------------------------------
test('legacy history remains reachable, explicitly labeled, and separate from current Classification', async () => {
  const row = {id: 9, academic_year_id: '2026', program_id: 11, status: 'completed', classification: 'Advanced', is_talented: false,
    overall_result: {available: true, average: 4.0, scale_max: 5}, candidate: {id: 1, status: 'reviewed'}, reassessment: {required: false},
    context: {student_name: 'Alya', student_learning_style: 'Verbal', program_name: 'Arts', grade_level: '3', section_name: 'A', cycle_title: 'Term 1'}};
  const root = domRoot();
  const ctx = {root, year: '2026', view: 'reviews', params: new URLSearchParams('cycle_id=5&program_id=11'), can: () => true, notify() {},
    api: async p => {
      if (p.startsWith('/api/talent/review-candidates/workspace?')) return [row];
      if (p === '/api/talent/programs') return [];
      if (p.startsWith('/api/talent/official-identifications')) return [{review_candidate_id: 1, decision: 'identified'}];
      throw new Error(`Unexpected ${p}`);
    }};
  await withWindow(() => render(ctx));
  assert.match(root.innerHTML, /Legacy Review &amp; Identification History/);
  assert.match(root.innerHTML, /Legacy review status/);
  assert.match(root.innerHTML, /Legacy identification decision/);
  assert.match(root.innerHTML, /Learning Style:<\/span> Verbal/);
  assert.doesNotMatch(root.innerHTML, /Open Review/);
  // Legacy "identified" never produces the Talented badge.
  assert.doesNotMatch(root.innerHTML, /tp-badge-talented/);
});

// ---- Students Across Programs (talent.js, runtime harness) -----------------
const FULL = {'talent_analytics.view': true, 'talent_analytics.view_students': true, 'talent_programs.view': false, 'students.view': true,
  'talent_review_candidates.view': true, 'talent_official_identifications.view': true, 'talent_learner_profiles.view': true};

function studentsHandler(items) {
  return url => {
    if (url.includes('organization-analytics/students')) return {body: {items, pagination: {has_more: false, limit: 25}}};
    if (url.includes('talent-map')) return {body: {rows: [{id: 5, label: 'Arts'}, {id: 6, label: 'Chess'}], columns: [{id: 1, label: 'Main'}]}};
    return {body: []};
  };
}
const drillItems = [{
  student_id: 7, display_name: 'Ella Exceptional', learning_style: 'Visual', can_view_learner_profile: true,
  contexts: [
    {program_id: 5, cycle_id: 1, branch_id: 1, grade_level: '3', section_name: 'A', assessment_state: 'completed',
      overall_result: {average: 4.8, scale_max: 5, normalized_percent: 96}, classification: 'Exceptional', classification_score: '4.80', is_talented: true,
      candidate_state: 'reviewed', identification_state: 'identified'},
    {program_id: 6, cycle_id: 2, branch_id: 1, grade_level: '3', section_name: 'A', assessment_state: 'completed',
      overall_result: {average: 3.0, scale_max: 4, normalized_percent: 75}, classification: 'Advanced', classification_score: '3.67', is_talented: false,
      candidate_state: 'pending_review', identification_state: null},
  ],
}, {
  student_id: 8, display_name: 'Nora Notstarted', learning_style: null, can_view_learner_profile: true,
  contexts: [{program_id: 5, cycle_id: 1, branch_id: 1, grade_level: '3', section_name: 'B', assessment_state: 'unassessed', candidate_state: null, identification_state: null}],
}];

test('Students Across Programs shows Learning Style and per-Program Classification; Talented only for Exceptional; no legacy states', async () => {
  const env = await createEnv({view: 'students', permissions: FULL, search: '?academic_year_id=1', handler: studentsHandler(drillItems)}).start();
  const html = env.text();
  assert.match(html, /Ella Exceptional/);
  assert.match(html, /Learning Style:<\/span> Visual/);
  assert.match(html, /Learning Style:<\/span> Unassigned/);
  assert.match(html, /Classification:<\/span> Exceptional/);
  assert.match(html, /Classification:<\/span> Advanced/);
  assert.equal((html.match(/tp-badge-talented/g) || []).length >= 1, true);
  // Talented badge count equals the number of Exceptional chips (matrix cell + card context).
  assert.equal((html.match(/tp-badge-talented/g) || []).length, (html.match(/data-classification="Exceptional"/g) || []).length);
  assert.doesNotMatch(html, /Review Candidate|Official Identification|candidate_state|identification_state|Meets Program Criteria|pending review|>reviewed</);
  // The not-assessed Student has no fabricated classification chip.
  const noraRow = html.split('<tr>').find(r => r.includes('Nora Notstarted')).split('</tr>')[0];
  assert.doesNotMatch(noraRow, /Classification:<\/span>/);
  // No universal cross-Program classification label.
  assert.doesNotMatch(html, /Overall Classification|Universal Classification/i);
  assert.equal(env.callsTo('learning-style').length, 0);
  assert.equal(env.callsTo('/classification').length, 0);
});

test('aggregate dashboard never requests or renders individual Student previews', async () => {
  const env = await createEnv({view: 'analytics', permissions: FULL, search: '?program_id=5&academic_year_id=1', handler: url => {
    if (url.includes('organization-analytics/students')) return {body: {items: drillItems}};
    if (url.includes('organization-analytics/overview')) return {body: {metrics: {}}};
    if (url.includes('talent-map')) return {body: {metric: 'completion_coverage', columns: [], rows: [], cells: [], row_totals: [], column_totals: [], organization_total: null}};
    if (url.includes('rubric-distribution')) return {body: {distributions: []}};
    if (url.includes('branch-comparison')) return {body: {metric: 'current_overall_progress', rows: []}};
    return {body: {distribution: {state: 'visible', buckets: []}}};
  }}).start();
  const html = env.text();
  assert.match(html, /Results &amp; Analytics/);
  assert.equal(env.callsTo('organization-analytics/students').length, 0);
  assert.doesNotMatch(html, /Ella|Learning Style:<\/span> Visual|Classification by Program/);
  assert.doesNotMatch(html, /Review \/ Identification|No candidate/);
});

// ---- Learner Profile -------------------------------------------------------
const profile = {
  student: {id: 7, first_name: 'Ella', father_name: '', last_name: 'Exceptional', learning_style: 'Visual'},
  placements: [],
  programs: [{program: {id: 5, name: 'Arts'}, academic_years: [{academic_year: {id: 1, year_name: '2026-2027'}, cycles: [
    {cycle: {id: 1, title: 'Term 1'}, framework_version: {title: 'Rubric', version_number: 1}, frozen_context: {grade_level: '3', section_display: 'A'},
      assessment: {status: 'completed', is_current: true, overall_result: {available: true, average: 4.8, scale_max: 5}, classification: 'Exceptional', is_talented: true},
      competency_results: [], review_candidate: {status: 'reviewed'}, official_identification: {decision: 'identified'}},
    {cycle: {id: 2, title: 'Term 2'}, framework_version: {title: 'Rubric', version_number: 1}, frozen_context: null,
      assessment: {status: 'in_progress', is_current: true, overall_result: null, classification: null, is_talented: false},
      competency_results: [], review_candidate: null, official_identification: null},
  ]}]}],
  timeline: [],
};
test('Learner Profile shows Learning Style, Program result, Classification and Talented; legacy history is secondary and labeled', async () => {
  const env = await createEnv({view: 'learner-profile', permissions: FULL, search: '?student_id=7&academic_year_id=1', handler: url => url.includes('learner-profiles/7') ? {body: profile} : {body: []}}).start();
  const html = env.text();
  assert.match(html, /Learning Style:<\/span> Visual/);
  assert.match(html, /Program result: <strong>4\.8 \/ 5<\/strong>/);
  assert.match(html, /Classification:<\/span> Exceptional/);
  assert.match(html, /tp-badge-talented">Talented</);
  // The in-progress cycle carries no classification.
  const term2 = html.slice(html.indexOf('Term 2'));
  assert.doesNotMatch(term2.slice(0, term2.indexOf('</details>')), /Classification:<\/span>/);
  // Legacy records appear only inside the explicit legacy section, after current history.
  const legacyStart = html.indexOf('tp-legacy-history');
  assert.ok(legacyStart > 0);
  assert.match(html.slice(legacyStart), /Legacy Review &amp; Identification History/);
  assert.match(html.slice(legacyStart), /Legacy Official Identification decision: identified/);
  const current = html.slice(0, legacyStart);
  assert.doesNotMatch(current, /Official Identification|Meets Program Criteria|Review Candidate/);
});

test('Learner Profile without legacy permission never renders a legacy section', async () => {
  const noLegacy = JSON.parse(JSON.stringify(profile));
  for (const y of noLegacy.programs[0].academic_years) for (const c of y.cycles) { delete c.review_candidate; delete c.official_identification; }
  const env = await createEnv({view: 'learner-profile', permissions: FULL, search: '?student_id=7&academic_year_id=1', handler: url => url.includes('learner-profiles/7') ? {body: noLegacy} : {body: []}}).start();
  assert.doesNotMatch(env.text(), /Legacy Review|tp-legacy-history/);
});

// ---- Static guards ----------------------------------------------------------
test('frontend contains no classification-band computation', () => {
  for (const file of ['talent.js', 'talent-operations.js', 'talent-experience.js', 'talent-student-identity.js', 'talent-program-workspace.js', 'talent-evaluation-workspace.js']) {
    const source = JS(file);
    assert.doesNotMatch(source, /\b(3\.75|4\.49|4\.5|3\.74|2\.99|1\.99)\b/, `${file} contains a classification band threshold`);
    assert.doesNotMatch(source, /classification_score\s*[<>]=?/, `${file} compares a classification score`);
    assert.doesNotMatch(source, /normalized_percent[^;\n]{0,40}(Exceptional|Advanced|Developing)/, `${file} derives a band from normalized_percent`);
  }
  // The identity helper never computes: it only renders the backend label.
  assert.doesNotMatch(JS('talent-student-identity.js'), /average|normalized_percent|scale_max/);
});

test('current Talent UX no longer surfaces legacy Review/Identification as a current concept', () => {
  const stale = /Open Review|Review Status|Meets Program Criteria|Officially Confirmed|Identification Classification/;
  for (const file of ['talent.js', 'talent-operations.js', 'talent-experience.js']) assert.doesNotMatch(JS(file), stale, file);
  const ops = JS('talent-operations.js');
  assert.doesNotMatch(ops, /<th>Review status<\/th>|<th>Official Identification<\/th>/);
  const talent = JS('talent.js');
  assert.doesNotMatch(talent, /candidate_state|identification_state/);
  assert.doesNotMatch(talent, /'reviews','Talent Review'/);
});

test('every Student-identifiable renderer uses the shared identity helper (no ad-hoc per-page identity logic)', () => {
  const talent = JS('talent.js'), ops = JS('talent-operations.js');
  assert.ok((talent.match(/identityHtml\(/g) || []).length >= 4);
  assert.ok((ops.match(/identityHtml\(/g) || []).length >= 4);
  assert.doesNotMatch(talent + ops, /getLearningStyle|fetch\([^)]*learning-style/);
});
