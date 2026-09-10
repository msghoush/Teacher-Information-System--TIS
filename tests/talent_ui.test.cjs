const {test} = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const {metric,esc,heatBucket,matrix,matrixCellHtml,resolveProgramSelection} = require('../static/js/talent.js');

// A realistic Talent Map payload shape (fetched live from the synthetic preview
// harness) covering visible, no_data, and a would-be suppressed coordinate.
const sampleColumns = [{id: 10, label: 'North'}, {id: 11, label: 'South'}];
const sampleRows = [{id: 1, label: 'Arts'}, {id: 2, label: 'STEM'}];
const sampleCells = [
  {coordinates: {program_id: 1, branch_id: 10}, state: 'visible', numerator: 1, denominator: 1, percentage: 100},
  {coordinates: {program_id: 1, branch_id: 11}, state: 'suppressed'},
  {coordinates: {program_id: 2, branch_id: 10}, state: 'visible', numerator: 0, denominator: 1, percentage: 0},
  {coordinates: {program_id: 2, branch_id: 11}, state: 'no_data'},
];
const cellFor = (r, c) => sampleCells.find(x => x.coordinates.program_id === r.id && x.coordinates.branch_id === c.id);

test('authoritative zero is distinct from absent evidence',()=>{
  assert.match(metric({state:'visible',value:0}),/>0</);
  assert.match(metric({state:'no_data',value:0}),/No data/);
  assert.doesNotMatch(metric({state:'no_data',value:0}),/>0</);
});
for(const state of ['suppressed','restricted','coarsened','no_data','unknown']) {
  test(`${state} never leaks sibling values, ratios, or magnitude`,()=>{
    const output=metric({state,value:876543,numerator:765432,denominator:654321,percentage:99.7});
    assert.doesNotMatch(output,/876543|765432|654321|99\.7|width|title=/);
  });
}
test('visible rates use server percentage without recalculation',()=>{
  assert.match(metric({state:'visible',numerator:1,denominator:3,percentage:33.3}),/33\.3%/);
});
test('untrusted text is encoded',()=>{
  assert.equal(esc('<img src=x onerror="alert(1)">'), '&lt;img src=x onerror=&quot;alert(1)&quot;&gt;');
  assert.doesNotMatch(metric({state:'visible',value:'<script>bad</script>'}),/<script>/);
});
test('heat bucket is 0 for every non-visible state regardless of magnitude', () => {
  for (const state of ['suppressed', 'restricted', 'coarsened', 'no_data', 'unknown']) {
    assert.equal(heatBucket({state, percentage: 99.9}), 0);
  }
  assert.equal(heatBucket(null), 0);
  assert.equal(heatBucket({state: 'visible', value: 42}), 0);
});
test('heat bucket only reads an already-visible backend percentage, never a raw count', () => {
  assert.equal(heatBucket({state: 'visible', percentage: 0}), 1);
  assert.equal(heatBucket({state: 'visible', percentage: 10}), 2);
  assert.equal(heatBucket({state: 'visible', percentage: 40}), 3);
  assert.equal(heatBucket({state: 'visible', percentage: 60}), 4);
  assert.equal(heatBucket({state: 'visible', percentage: 90}), 5);
});

test('talent.js source contains no double-encoded UTF-8 (mojibake) text', () => {
  const source = fs.readFileSync(path.join(__dirname, '..', 'static', 'js', 'talent.js'), 'utf8');
  // U+00E2 and U+00C2 are the lead codepoints produced when correct UTF-8 text
  // (an arrow, en/em dash, middle dot, or ellipsis) is misread as
  // Windows-1252/Latin-1 and re-saved as UTF-8. Neither codepoint has any
  // legitimate use in this file, so their presence signals a reintroduced
  // encoding regression like the one this test guards against.
  assert.doesNotMatch(source, new RegExp(String.fromCharCode(0x00e2)), 'found mojibake marker U+00E2 in talent.js');
  assert.doesNotMatch(source, new RegExp(String.fromCharCode(0x00c2)), 'found mojibake marker U+00C2 in talent.js');
});

test('Talent Map matrix uses real ARIA grid semantics and a keyboard-focusable cell per coordinate', () => {
  const html = matrix('Program x Branch', 'Program', sampleColumns, sampleRows, cellFor,
    r => ({state: 'visible', value: 1}), c => ({state: 'visible', value: 1}), {state: 'visible', value: 2});
  assert.match(html, /role="grid"/);
  assert.match(html, /role="columnheader"/);
  assert.match(html, /role="rowheader"/);
  assert.match(html, /role="gridcell"/);
  assert.equal((html.match(/tabindex="0"/g) || []).length, sampleRows.length * sampleColumns.length);
});

test('Talent Map matrix renders a protected (suppressed) cell as a distinct categorical state, never a magnitude cue', () => {
  const html = matrixCellHtml(sampleCells[1], 'Arts', 'South', null);
  assert.match(html, /tp-protected-cell/);
  assert.doesNotMatch(html, /tp-heat-[1-5]/);
  assert.match(html, /Protected for privacy/);
  assert.doesNotMatch(html, /width:|title=/);
});

test('Talent Map matrix keeps no_data visually and textually distinct from a protected/suppressed cell', () => {
  const noData = matrixCellHtml(sampleCells[3], 'STEM', 'South', null);
  const protectedCell = matrixCellHtml(sampleCells[1], 'Arts', 'South', null);
  assert.match(noData, /tp-nodata-cell/);
  assert.doesNotMatch(noData, /tp-protected-cell/);
  assert.notEqual(noData.match(/aria-label="[^"]*"/)[0], protectedCell.match(/aria-label="[^"]*"/)[0]);
});

test('Talent Map matrix drill-down is only offered for a visible cell', () => {
  const drillFor = (r, c) => { const cell = cellFor(r, c); return cell?.state === 'visible' ? '<a href="/talent/branch">Explore Branch</a>' : null; };
  const html = matrix('Program x Branch', 'Program', sampleColumns, sampleRows, cellFor,
    r => ({state: 'visible', value: 1}), c => ({state: 'visible', value: 1}), {state: 'visible', value: 2}, drillFor);
  assert.equal((html.match(/Explore Branch/g) || []).length, 2); // exactly the 2 visible coordinates
});

// M11 raw-ID stakeholder polish: Assessment evidence and Learner Profile must never
// interpolate the raw framework_competency_id/rubric_level_id database identifiers,
// since no approved human-readable label exists yet in the response contract.
test('Assessment evidence and Learner Profile never render raw competency/rubric database IDs', () => {
  const source = fs.readFileSync(path.join(__dirname, '..', 'static', 'js', 'talent.js'), 'utf8');
  assert.doesNotMatch(source, /esc\(r\.framework_competency_id\)/);
  assert.doesNotMatch(source, /esc\(r\.rubric_level_id\)/);
  assert.match(source, /Recorded competency evidence/);
  assert.match(source, /Rubric level recorded/);
});

// M11 stakeholder smoke fix: the B10-B longitudinal contract serializes Academic
// Year as {id, label} (never year_name, which stays descriptive-only per ADR 0027),
// so the Longitudinal view must read data.academic_year.label or its headline and
// context heading silently render blank.
test('Longitudinal view reads the actual academic_year.label contract field', () => {
  const source = fs.readFileSync(path.join(__dirname, '..', 'static', 'js', 'talent.js'), 'utf8');
  assert.doesNotMatch(source, /data\.academic_year\.year_name/);
  assert.match(source, /data\.academic_year\.label/);
});

// Parallel UI/test support: stakeholder-facing nav/page-title copy must use the
// approved friendly terms, never the internal "Longitudinal"/"Participation Overlap"
// names (see routers/talent_ui.py VIEWS and the matching Overview card label).
test('Stakeholder-facing labels use "Progress Over Time" and "Students Across Programs"', () => {
  const routerSource = fs.readFileSync(path.join(__dirname, '..', 'routers', 'talent_ui.py'), 'utf8');
  assert.match(routerSource, /"longitudinal":\s*\("Progress Over Time"/);
  assert.match(routerSource, /"overlap":\s*\("Students Across Programs"/);
  assert.doesNotMatch(routerSource, /"Longitudinal", "talent_analytics\.view"/);
  assert.doesNotMatch(routerSource, /"Participation Overlap"/);
  const jsSource = fs.readFileSync(path.join(__dirname, '..', 'static', 'js', 'talent.js'), 'utf8');
  assert.doesNotMatch(jsSource, /'Follow over time'/);
});

// Student Drill contexts and Learner Profile frozen contexts must never interpolate
// raw program_id/cycle_id/branch_id database identifiers, since no approved label
// for these fields is available in the response contract (talent_org_student_drill.py,
// talent_learner_profile_service.py).
test('Student Drill and Learner Profile never render raw program/cycle/branch database IDs', () => {
  const source = fs.readFileSync(path.join(__dirname, '..', 'static', 'js', 'talent.js'), 'utf8');
  assert.doesNotMatch(source, /esc\(c\.program_id\)/);
  assert.doesNotMatch(source, /esc\(c\.cycle_id\)/);
  assert.doesNotMatch(source, /esc\(c\.branch_id\)/);
  assert.doesNotMatch(source, /esc\(c\.frozen_context\.branch_id\)/);
});

// Owner-confirmed Program context-integrity defect: the shared ribbon/context
// Program selector and the Programs workspace must always resolve to the
// SAME canonical Program, identified only by program_id. These tests exercise
// resolveProgramSelection, the pure resolver init() now uses to populate the
// ribbon <select>'s value, exactly as it is called in production - the same
// contract the DOM-dependent init()/applyContext() wiring cannot be unit
// tested for directly in this repo (no jsdom dependency is available, so the
// live <select> DOM behavior itself is not Node-testable; this pure resolver
// is the testable seam for that exact selection logic).
const mentalMath = {id: 11, name: 'Mental Math'};
const chessClub = {id: 27, name: 'Chess Club'};
const sameNameOtherId = {id: 99, name: 'Mental Math'};

test('canonical Program selection matches by program_id only, never by name', () => {
  assert.equal(resolveProgramSelection([mentalMath, chessClub], '11'), '11');
  assert.equal(resolveProgramSelection([mentalMath, chessClub], 11), '11');
  // A second Program that happens to share a name must never be selected in
  // place of the actual id match, and matching stays exact even when a
  // same-named row exists elsewhere in the list.
  assert.equal(resolveProgramSelection([sameNameOtherId, chessClub], '11'), '');
  assert.equal(resolveProgramSelection([mentalMath, sameNameOtherId], '99'), '99');
});

test('canonical Program selection never defaults to the first Program in the list', () => {
  // A requested id that does not (yet) exist in the loaded list - the classic
  // "list still loading" / stale-id race - must resolve to the neutral ""
  // state, never silently fall back to items[0].
  assert.equal(resolveProgramSelection([mentalMath, chessClub], '404'), '');
  assert.equal(resolveProgramSelection([], '11'), '');
});

test('a valid deep-link program_id resolves correctly once the async Program list arrives, with no overwrite', () => {
  // Simulates init(): the <select> starts with no options loaded (list not
  // yet fetched); once the real Program list resolves, the deep-linked id
  // must resolve to that exact Program - never reset to blank/first-item
  // merely because the list arrived asynchronously.
  const deepLinkedId = String(chessClub.id);
  const loadedList = [mentalMath, chessClub];
  assert.equal(resolveProgramSelection(loadedList, deepLinkedId), String(chessClub.id));
});

test('an absent program_id resolves to the neutral (no Program selected) state, not an arbitrary Program', () => {
  assert.equal(resolveProgramSelection([mentalMath, chessClub], null), '');
  assert.equal(resolveProgramSelection([mentalMath, chessClub], ''), '');
  assert.equal(resolveProgramSelection([mentalMath, chessClub], undefined), '');
});
