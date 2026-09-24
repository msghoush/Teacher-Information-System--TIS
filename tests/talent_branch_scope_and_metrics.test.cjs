'use strict';
/* Deployment Acceptance Batch 1 - stub/structural verification (NOT a real browser).
 *
 * (1) Global Branch context: the active application Branch (rendered by the server
 *     as tp-config.branch) is the default Talent Branch scope, a stale Branch from a
 *     previous global selection can never survive, and an explicit "All Branches"
 *     choice is honored. Backend authorization stays authoritative (Python tests).
 * (2) Metric grain labels: "Students participating" is bound ONLY to the backend
 *     distinct-Student figure; membership counts are "Program participations".
 * (3) The inline never-hangs watchdog turns a still-untouched server loader into an
 *     explicit retryable error.
 */
const {test} = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const {createEnv} = require('./talent_runtime_harness.cjs');

const FULL = {
  'talent_analytics.view': true, 'talent_analytics.view_students': true, 'talent_programs.view': false,
  'students.view': true, 'talent_review_candidates.view': true, 'talent_assessments.view': true,
};
const visible = value => ({state: 'visible', value});
const overviewBody = {metrics: {
  programs_configured: visible(3), active_programs: visible(3),
  distinct_students: visible(9), frozen_eligible_memberships: visible(63),
  completion_coverage: {state: 'visible', percentage: 50, numerator: 31, denominator: 63},
}};
const mapBody = {metric: 'completion_coverage', columns: [], rows: [], cells: [], row_totals: [], column_totals: [], organization_total: null};

function handler(overrides = {}) {
  return (url) => {
    for (const [fragment, outcome] of Object.entries(overrides)) if (url.includes(fragment)) return outcome;
    if (url.includes('organization-analytics/overview')) return {body: overviewBody};
    if (url.includes('talent-map')) return {body: mapBody};
    if (url.includes('program-portfolio')) return {body: {programs: [], totals: {}}};
    if (url.includes('rubric-distribution')) return {body: {distributions: [], program_result_summary: {state: 'no_data'}}};
    if (url.includes('/longitudinal')) return {body: {points: [], comparisons: [], metric: 'completion_coverage', program: {name: 'P'}, academic_year: {label: 'Y'}}};
    if (url.includes('/students?')) return {body: {items: []}};
    if (url.includes('branch-comparison')) return {body: {metric: 'current_overall_progress', rows: []}};
    if (url.includes('learning-style')) return {body: {distribution: {state: 'visible', total_population: 0, total: {state: 'visible', value: 0}, levels: []}}};
    if (url.includes('/classification')) return {body: {distribution: {state: 'visible', buckets: []}}};
    if (url.includes('/talented')) return {body: {organization: {distribution: {state: 'visible'}, summary: {}}, branch_breakdown: []}};
    if (url.includes('planning-branches')) return {body: [{id: 7, name: 'Girls'}, {id: 3, name: 'Boys'}]};
    if (url.includes('planning-grades')) return {body: ['3', '4']};
    return {body: []};
  };
}

const branchParams = env => env.calls
  .map(call => new URL(call.url, 'http://tis.test').searchParams)
  .filter(params => params.has('branch_id'));
const dataCalls = env => env.calls.filter(call => /organization-analytics|results-analytics|analytics\/programs/.test(String(call.url)));

test('B1. the active global Branch is the default scope of every Student-data request', async () => {
  const env = await createEnv({view: 'analytics', permissions: FULL, search: '?program_id=5&academic_year_id=1',
    config: {branch: 7, branchName: 'Girls'}, handler: handler()}).start();
  const withBranch = dataCalls(env);
  assert.ok(withBranch.length >= 5, 'the analytics view issues its independent section requests');
  for (const call of withBranch.filter(c => !/branch-comparison/.test(c.url))) {
    assert.equal(new URL(call.url, 'http://tis.test').searchParams.get('branch_id'), '7', call.url);
  }
  // Persisted for other URL readers with the marker of the Branch that produced it.
  const persisted = env.replaced.map(args => String(args[2])).join(' ');
  assert.match(persisted, /branch_id=7/);
  assert.match(persisted, /scope_branch_id=7/);
});

test('B2. Boys -> Girls: a stale Branch (and its Grade/Section) from the previous global Branch never survives', async () => {
  // URL minted while the global Branch was 3 ("Boys"); the global Branch is now 7 ("Girls").
  const env = await createEnv({view: 'analytics', permissions: FULL,
    search: '?program_id=5&academic_year_id=1&branch_id=3&grade_level=4&planning_section_id=9&scope_branch_id=3',
    config: {branch: 7, branchName: 'Girls'}, handler: handler()}).start();
  const urls = env.calls.map(call => String(call.url));
  assert.ok(urls.length > 5);
  assert.equal(urls.filter(url => /branch_id=3(&|$)/.test(url)).length, 0, 'the previous Branch must never be requested');
  assert.equal(urls.filter(url => /grade_level=4|planning_section_id=9/.test(url)).length, 0, 'Branch-dependent Grade/Section are cleared');
  assert.ok(urls.some(url => /branch_id=7(&|$)/.test(url)), 'the new global Branch is what is requested');
});

test('B3. an explicit Branch chosen inside Talent (drill link) is kept and authorized by the backend', async () => {
  const env = await createEnv({view: 'branch', permissions: FULL, search: '?academic_year_id=1&branch_id=3',
    config: {branch: 7, branchName: 'Girls'}, handler: handler({'/branches/3': {body: {programs: [], branch: {id: 3, name: 'Boys'}}}})}).start();
  assert.ok(env.calls.some(call => String(call.url).includes('/branches/3')), 'explicit Branch drill is honored');
});

test('B4. an explicit "All Branches" choice is honored (no branch filter is sent)', async () => {
  const env = await createEnv({view: 'analytics', permissions: FULL,
    search: '?program_id=5&academic_year_id=1&branch_scope=all&scope_branch_id=7',
    config: {branch: 7, branchName: 'Girls'}, handler: handler()}).start();
  assert.equal(branchParams(env).length, 0);
});

test('B5. without an active Branch no Branch filter is invented', async () => {
  const env = await createEnv({view: 'analytics', permissions: FULL, search: '?program_id=5&academic_year_id=1',
    config: {}, handler: handler()}).start();
  assert.equal(branchParams(env).length, 0);
});

test('B6. switching the Talent Branch selector to All Branches drops the filter and records the explicit choice', async () => {
  const env = await createEnv({view: 'overlap', permissions: FULL, search: '?academic_year_id=1',
    config: {branch: 7, branchName: 'Girls'}, handler: handler()}).start();
  assert.match(String(env.calls.find(c => /participation-overlap/.test(c.url)).url), /branch_id=7/);
  const before = env.calls.length;
  const select = env.elements['tp-branch'];
  select.value = '';
  env.elements['tp-filters'].emit('change', {target: select});
  await env.tick(600);
  const after = env.calls.slice(before).filter(c => /participation-overlap/.test(c.url));
  assert.ok(after.length >= 1);
  assert.ok(after.every(c => !/branch_id=/.test(c.url)), 'All Branches sends no Branch filter');
  assert.match(env.replaced.map(args => String(args[2])).join(' '), /branch_scope=all/);
});

test('B7. the Overview requests the Branch-scoped headline and names the scope', async () => {
  const env = await createEnv({view: 'overview', permissions: FULL, config: {branch: 7, branchName: 'Girls'},
    handler: handler()}).start();
  assert.match(String(env.callsTo('organization-analytics/overview')[0].url), /branch_id=7/);
  assert.match(env.text(), /Academic Year [^<]* · Girls/);
});

test('M1. "Students participating" is the distinct-Student figure; memberships are "Program participations"', async () => {
  const env = await createEnv({view: 'overview', permissions: FULL, config: {branch: 7}, handler: handler()}).start();
  const html = env.text();
  assert.match(html, /Students participating<\/span><span class="tp-stat-value"><strong>9<\/strong>/);
  assert.match(html, /Program participations<\/span><span class="tp-stat-value"><strong>63<\/strong>/);
  assert.doesNotMatch(html, /Students participating<\/span><span class="tp-stat-value"><strong>63/);
});

test('M2. Talent Map / Longitudinal metric options never call a membership count "Students"', async () => {
  for (const view of ['talent-map', 'longitudinal']) {
    const env = await createEnv({view, permissions: FULL, search: '?academic_year_id=1', config: {branch: 7}, handler: handler()}).start();
    const labels = env.elements['tp-metric'].options.map(option => option.textContent);
    assert.ok(labels.includes('Program participations'), `${view}: ${labels}`);
    assert.ok(!labels.some(label => /^Students participating$/.test(label)), `${view}: ${labels}`);
  }
});

function runWatchdog({loaderPresent}) {
  const template = fs.readFileSync(path.join(__dirname, '..', 'templates', 'talent', 'workspace.html'), 'utf8');
  const source = template.match(/<script>\s*\(function\(\)\{[\s\S]*?LIMIT_MS[\s\S]*?\}\)\(\);\s*<\/script>/);
  assert.ok(source, 'inline watchdog script is present in the workspace template');
  const code = source[0].replace(/^<script>/, '').replace(/<\/script>$/, '');
  const timers = [];
  const root = {
    innerHTML: '<p data-server-loader>Loading your authorized workspace…</p>', attrs: {},
    querySelector: selector => (selector === '[data-server-loader]' && loaderPresent ? {} : null),
    setAttribute(name, value) { this.attrs[name] = value; },
  };
  const button = {listeners: {}, addEventListener(type, fn) { this.listeners[type] = fn; }};
  const status = {textContent: ''};
  let reloads = 0;
  const document = {getElementById: id => ({'tp-content': root, 'tp-status': status, 'tp-watchdog-reload': button}[id] || null)};
  vm.runInNewContext(code, {document, setTimeout: (fn, ms) => timers.push({fn, ms}), location: {reload() { reloads += 1; }}});
  return {timers, root, status, button, reloads: () => reloads};
}

test('W1. the watchdog replaces a still-untouched server loader with an explicit retryable error', () => {
  const run = runWatchdog({loaderPresent: true});
  assert.equal(run.timers.length, 1);
  assert.equal(run.timers[0].ms, 15000);
  run.timers[0].fn();
  assert.match(run.root.innerHTML, /could not finish loading/);
  assert.match(run.root.innerHTML, /role="alert"/);
  assert.equal(run.root.attrs['aria-busy'], 'false');
  assert.equal(run.status.textContent, 'View could not be loaded.');
  run.button.listeners.click();
  assert.equal(run.reloads(), 1);
});

test('W2. the watchdog never touches a page whose script already took over', () => {
  const run = runWatchdog({loaderPresent: false});
  const before = run.root.innerHTML;
  run.timers[0].fn();
  assert.equal(run.root.innerHTML, before);
});

test('A1. Talent scripts and styles are cache-busted by content hash', () => {
  const template = fs.readFileSync(path.join(__dirname, '..', 'templates', 'talent', 'workspace.html'), 'utf8');
  const assets = [...template.matchAll(/static', path='((?:js|css)\/talent[^']*)'\) \}\}\?v=\{\{ talent_asset_version\('([^']*)'\) \}\}/g)];
  assert.ok(assets.length >= 10);
  assert.ok(assets.every(match => match[1] === match[2]));
  assert.doesNotMatch(template, /static', path='(?:js|css)\/talent[^']*'\) \}\}(?!\?v=)/);
});

const LOADER = 'Loading your authorized workspace';
const BRANCH_VIEWS = ['overview', 'assessments', 'analytics', 'portfolio', 'talent-map', 'overlap', 'longitudinal', 'students', 'reviews'];

test('L1. the Branch lookup is one request per page load (no per-view waterfall growth)', async () => {
  for (const view of BRANCH_VIEWS) {
    const env = await createEnv({view, permissions: {...FULL, 'talent_programs.view': true, 'talent_assessments.view': true},
      search: '?program_id=5&academic_year_id=1', config: {branch: 7, branchName: 'Girls'}, handler: handler()}).start();
    assert.ok(env.callsTo('planning-branches').length <= 1, `${view}: ${env.callsTo('planning-branches').length}`);
  }
});

test('L2. a hanging Branch lookup can never hold the page on a generic loader (bounded, then content)', async () => {
  for (const view of ['overview', 'analytics', 'portfolio']) {
    const env = await createEnv({view, permissions: FULL, search: '?program_id=5&academic_year_id=1',
      config: {branch: 7, branchName: 'Girls'}, handler: handler({'planning-branches': 'hang'})}).start();
    assert.doesNotMatch(env.text(), new RegExp(LOADER));
    await env.tick(21000);
    assert.doesNotMatch(env.text(), new RegExp(LOADER));
    assert.ok(dataCalls(env).length >= 1, `${view}: data requests were issued after the bounded lookup`);
    // the page ends in content, an empty state, or an explicit retryable error - never an endless loader
    assert.notEqual(env.busy(), 'true', view);
  }
});
