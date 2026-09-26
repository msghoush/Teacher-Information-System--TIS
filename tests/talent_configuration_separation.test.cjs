'use strict';
/* System Configuration + Operational User Flow Separation, Part 1.
 *
 * (A) The operational Talent pages (talent.js / talent-operations.js) expose NO Program or
 *     Evaluation configuration mutation control - they are read-only and lead into
 *     Program -> Evaluation Period -> Student Assessment. Even an organization
 *     Administrator gets a single non-mutating link to System Configuration.
 * (B) The System Configuration > Talent & Potential shell (talent-configuration.js) lists
 *     real Programs, selects one and mounts the EXISTING canonical editors. No data is
 *     invented. UI visibility never replaces the API gates (403 organization_authority_required).
 * Structural verification against a DOM stub; not a browser. */
const {test} = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const {createEnv} = require('./talent_runtime_harness.cjs');
const grades = require('../static/js/talent-program-grades.js');
const shell = require('../static/js/talent-configuration.js');

const read = file => fs.readFileSync(path.join(__dirname, '..', 'static', 'js', file), 'utf8');
const CONFIG_URL = '/system-configuration/talent-potential';
const MUTATION = /New Program|Edit Program|Save Program|Add Competency|Add Level|Rubric Level|Configure Rubric|Manage Evaluation|data-form=|data-action="(?:new-program|create|edit|delete-program|finish-setup)|name="grade_|Start Setup|Build \/ Edit/;
const OPERATIONAL = {'talent_programs.view': true, 'talent_evaluation_plans.view': true, 'talent_assessments.view': true, 'talent_analytics.view': true,
  // Semantic hints stay for operational use (selecting a planned Period); they never render editors.
  'talent_programs.manage': true, 'talent_evaluation_plans.manage': true, 'talent_assessment_cycles.manage': true};
const summaries = [
  {id: 5, name: 'Mental Math', description: 'Arithmetic fluency', status: 'active', annual: {eligible_grade_levels: ['1', '2', '3']}, actions: ['delete']},
  {id: 6, name: 'Chess <Club>', description: '', status: 'draft', annual: {eligible_grade_levels: ['KG']}, actions: []},
];
const handler = extra => (url) => {
  for (const [fragment, body] of Object.entries(extra || {})) if (url.includes(fragment)) return {body};
  if (url.includes('programs/summaries')) return {body: summaries};
  if (url.includes('/frameworks')) return {body: []};
  if (url.includes('/academic-years')) return {body: [{academic_year_id: 1, is_enabled: true, eligible_grade_levels: ['1', '2', '3']}]};
  if (url.includes('evaluation-plans')) return {body: [{id: 1, program_id: 5, status: 'active', period_count: 2, required_period_count: 1, periods: [{sequence: 1, label: 'Term 1', is_required: true, status: 'planned'}]}]};
  if (/api\/talent\/programs\/\d+$/.test(url)) return {body: summaries[0]};
  return {body: []};
};

test('A1. the operational Programs list is read-only: names, Grades range and flow links, no configuration control', async () => {
  const env = await createEnv({view: 'programs', permissions: OPERATIONAL, handler: handler(), globals: {TalentProgramGrades: grades}, config: {configurationUrl: CONFIG_URL}}).start();
  const html = env.text();
  assert.match(html, /Mental Math/);
  assert.match(html, /Grades 1 - 3/);
  assert.match(html, /Chess &lt;Club&gt;/);
  assert.match(html, /<p class="tp-program-grades">KG<\/p>/);
  assert.match(html, /Open Program/);
  assert.match(html, /href="\/talent\/assessments\?[^"]*program_id=5/, 'Program leads into the Student Assessments flow');
  assert.doesNotMatch(html, MUTATION);
  assert.doesNotMatch(html, /<form|<input|type="submit"/);
  // The lifecycle badge stays absent from normal Program UI (owner directive, V5).
  assert.doesNotMatch(html, /tp-badge/);
  assert.equal(env.callsTo('/programs/summaries').length, 1);
});

test('A2. an organization-level actor gets no editor on the Program detail, only one non-mutating configure link with context', async () => {
  const env = await createEnv({view: 'programs', search: '?program_id=5&academic_year_id=1', permissions: OPERATIONAL, handler: handler(), globals: {TalentProgramGrades: grades}, config: {configurationUrl: CONFIG_URL}}).start();
  const html = env.text();
  assert.match(html, /Mental Math/);
  assert.match(html, /Grades 1 - 3/);
  assert.match(html, new RegExp(`href="${CONFIG_URL}\\?[^"]*program_id=5[^"]*">Configure in System Configuration</a>`));
  assert.match(html, /Evaluation Periods/);
  assert.match(html, /Term 1/);
  assert.match(html, /Student Assessments/);
  assert.doesNotMatch(html, MUTATION);
  assert.doesNotMatch(html, /<form|<input|type="submit"|data-action=/);
});

test('A3. without a server-derived configuration URL (normal or Branch-scoped user) there is no configure link at all', async () => {
  for (const search of ['', '?program_id=5&academic_year_id=1']) {
    const env = await createEnv({view: 'programs', search, permissions: OPERATIONAL, handler: handler(), globals: {TalentProgramGrades: grades}, config: {configurationUrl: ''}}).start();
    const html = env.text();
    assert.doesNotMatch(html, /system-configuration|Configure in System Configuration|tp-configure-link/);
    assert.doesNotMatch(html, MUTATION);
  }
});

test('A4. an empty organization shows an honest empty state (no seeded data); the create hint is a link only for the configuration actor', async () => {
  const empty = () => ({body: []});
  const admin = await createEnv({view: 'programs', permissions: OPERATIONAL, handler: empty, config: {configurationUrl: CONFIG_URL}}).start();
  assert.match(admin.text(), /No Programs are available yet\. Create the first Program in System Configuration\./);
  assert.match(admin.text(), /Configure in System Configuration/);
  const user = await createEnv({view: 'programs', permissions: OPERATIONAL, handler: empty, config: {configurationUrl: ''}}).start();
  assert.match(user.text(), /Ask your organization Administrator/);
  assert.doesNotMatch(user.text(), /system-configuration/);
});

test('A5. the read-only Evaluation Plan list never mounts an editor even for an organization Administrator', async () => {
  const env = await createEnv({view: 'evaluation-plans', search: '?program_id=5&academic_year_id=1', permissions: OPERATIONAL, handler: handler(), config: {configurationUrl: CONFIG_URL}}).start();
  const html = env.text();
  assert.match(html, /Annual Evaluation Plan/);
  assert.match(html, /Term 1/);
  assert.doesNotMatch(html, MUTATION);
  assert.doesNotMatch(html, /<form|<input|type="submit"|data-action=/);
});

test('A6. an old #tp- Program-setup bookmark is forwarded to System Configuration only for an authorized actor', async () => {
  const redirects = [];
  const location = {search: '?program_id=5&academic_year_id=1', pathname: '/talent/programs', hash: '#tp-schedule', origin: 'http://tis.test', href: '', reload() {}, replace(url) { redirects.push(url); }};
  await createEnv({view: 'programs', search: location.search, permissions: OPERATIONAL, handler: handler(), globals: {location, TalentProgramGrades: grades}, config: {configurationUrl: CONFIG_URL}}).start();
  assert.equal(redirects.length, 1);
  assert.match(redirects[0], new RegExp(`^${CONFIG_URL}\\?[^#]*program_id=5[^#]*#tp-schedule$`));
  redirects.length = 0;
  const plain = await createEnv({view: 'programs', search: location.search, permissions: OPERATIONAL, handler: handler(), globals: {location, TalentProgramGrades: grades}, config: {configurationUrl: ''}}).start();
  assert.equal(redirects.length, 0, 'no redirect (and no editor) without configuration authority');
  assert.match(plain.text(), /Mental Math/);
});

test('A7. no operational script contains a Program or Evaluation configuration mutation', () => {
  for (const file of ['talent.js', 'talent-operations.js', 'talent-experience.js', 'talent-dashboard.js', 'talent-charts.js']) {
    const source = read(file);
    assert.doesNotMatch(source, /new-program|create-program|delete-program|finish-setup|TalentProgramWorkspace\.render|TalentEvaluationWorkspace\.render/, file);
    assert.doesNotMatch(source, /['"`]\/?api\/talent\/programs['"`],\s*\{\s*method:\s*'(?:POST|PUT|PATCH|DELETE)'/, file);
  }
  // Assessment materialization (select-planned-evaluation) is operational and is preserved.
  assert.match(read('talent-operations.js'), /select-planned-evaluation/);
});

// ---------------------------------------------------------------- (B) the shell

test('B1. pure helpers: Grades range, tab and sub-tab resolution', () => {
  assert.equal(shell.gradesSummary(['3', '1', '2']), 'Grades 1 - 3');
  assert.equal(shell.gradesSummary(['4']), 'Grade 4');
  assert.equal(shell.gradesSummary(['KG']), 'KG');
  assert.equal(shell.gradesSummary(['KG', '1']), 'Grades KG, 1');
  assert.equal(shell.gradesSummary(['1', '3']), 'Grades 1, 3');
  assert.equal(shell.gradesSummary([]), 'Grades not set');
  assert.equal(grades.gradesSummary(['2', '1']), 'Grades 1 - 2');
  assert.equal(shell.resolveTab('evaluation-periods', true), 'evaluation-periods');
  assert.equal(shell.resolveTab('<x>', true), 'programs');
  assert.equal(shell.resolveTab('programs', false), 'evaluation-periods', 'no Programs read permission falls back to the plan-only surface');
  assert.deepEqual(shell.TABS, ['programs', 'evaluation-periods'], 'only real concepts are top-level tabs');
  assert.deepEqual(shell.SUBTABS.map(t => t.label), ['Program Setup', 'Rubric & Competencies', 'Evaluation Periods', 'Criteria / KPI']);
  assert.equal(shell.subtabFromHash('#tp-rubric'), 'rubric');
  assert.equal(shell.subtabFromHash('#unknown'), '');
});

test('B2. Program card and header escape data and never seed values', () => {
  const card = shell.programCardHtml(summaries[1], {selected: true});
  assert.match(card, /Chess &lt;Club&gt;/);
  assert.doesNotMatch(card, /Chess <Club>/);
  assert.match(card, /is-selected/);
  assert.doesNotMatch(card, /data-tpc-delete/);
  assert.match(shell.programCardHtml(summaries[0], {canDelete: true}), /data-tpc-delete="5"/);
  assert.match(shell.headHtml(summaries[0], summaries[0], true), /data-tpc-edit-program/);
  assert.doesNotMatch(shell.headHtml(summaries[0], summaries[0], false), /data-tpc-edit-program/);
  assert.match(shell.periodsOverviewHtml([summaries[0]], [], {canManage: true}), /No Evaluation Plan for this Academic Year yet/);
});

class El {
  constructor(id) { this.id = id; this.innerHTML = ''; this.textContent = ''; this.hidden = false; this.dataset = {}; this.attrs = {}; this.listeners = {}; this.value = ''; this.options = []; this.selectedIndex = 0; this.classList = {add() {}}; }
  setAttribute(k, v) { this.attrs[k] = String(v); }
  getAttribute(k) { return this.attrs[k] ?? null; }
  addEventListener(type, fn) { (this.listeners[type] ||= []).push(fn); }
  querySelector() { return null; }
}
function mountShell({permissions, search = '', hash = '', plans = [], programs = summaries, workspace, confirm = () => true}) {
  const ids = ['tpc-config', 'tpc-year', 'tpc-status', 'tpc-program-list', 'tpc-search', 'tpc-center-head', 'tpc-subtabs', 'tpc-content', 'tpc-root'];
  const els = Object.fromEntries(ids.map(id => [id, new El(id)]));
  els['tpc-config'].textContent = JSON.stringify({permissions, year: 1});
  els['tpc-year'].value = '1'; els['tpc-year'].options = [{value: '1', textContent: '2026-2027'}];
  const newButton = new El('new'); newButton.hidden = true;
  const doc = {getElementById: id => els[id] || null, querySelectorAll: () => [], querySelector: sel => (sel === '[data-tpc-action="new-program"]' ? newButton : null), listeners: {}, addEventListener(type, fn) { (this.listeners[type] ||= []).push(fn); }};
  const calls = [];
  const win = {
    location: {search, pathname: '/system-configuration/talent-potential', hash},
    history: {replaceState(_s, _t, url) { const u = new URL(url, 'http://t'); win.location.search = u.search; win.location.hash = u.hash; }},
    addEventListener() {}, confirm, TalentApiErrors: require('../static/js/talent-api-errors.js'),
    TalentProgramWorkspace: workspace, TalentEvaluationWorkspace: {render: async () => {}},
  };
  const fetchImpl = async (url, init = {}) => {
    calls.push({url, method: init.method || 'GET'});
    let body = [];
    if (url.includes('programs/summaries')) body = programs;
    else if (url.includes('evaluation-plans')) body = plans;
    return {ok: true, status: 200, redirected: false, headers: {get: () => 'application/json'}, json: async () => body};
  };
  const api = shell.mount(doc, win, {fetch: fetchImpl});
  const click = target => doc.listeners.click.forEach(fn => fn({target: {closest: sel => (target[sel] ? target.el : null)}}));
  return {api, els, calls, win, doc, newButton, click};
}
const ADMIN = {'talent_programs.view': true, 'talent_programs.manage': true, 'talent_evaluation_plans.view': true, 'talent_evaluation_plans.manage': true};
function fakeWorkspace() {
  const rendered = [];
  return {rendered, render: async ctx => { rendered.push(ctx); ctx.root.innerHTML = '<p>editor</p>'; }, newProgramFormHtml: g => `<form data-form="create-program">${g.length}</form>`, submitNewProgram: async () => ({id: 9})};
}

test('B3. the shell lists the real Programs from the canonical summaries API and shows New Program only with manage', async () => {
  const ws = fakeWorkspace();
  const s = mountShell({permissions: ADMIN, workspace: ws});
  await s.api.ready;
  assert.match(s.els['tpc-program-list'].innerHTML, /Mental Math/);
  assert.match(s.els['tpc-program-list'].innerHTML, /Grades 1 - 3/);
  assert.match(s.els['tpc-program-list'].innerHTML, /data-tpc-delete="5"/, 'delete only where the backend row advertises the action');
  assert.equal(s.newButton.hidden, false);
  assert.ok(s.calls.some(c => c.url === '/api/talent/programs/summaries?academic_year_id=1'));
  assert.match(s.els['tpc-content'].innerHTML, /Select a Program/);
  const viewOnly = mountShell({permissions: {'talent_programs.view': true, 'talent_evaluation_plans.manage': true}, workspace: ws});
  await viewOnly.api.ready;
  assert.equal(viewOnly.newButton.hidden, true);
});

test('B4. an empty organization renders empty states, not fabricated Programs', async () => {
  const s = mountShell({permissions: ADMIN, workspace: fakeWorkspace(), programs: []});
  await s.api.ready;
  assert.match(s.els['tpc-program-list'].innerHTML, /No Programs yet\./);
  assert.match(s.els['tpc-content'].innerHTML, /No Programs exist yet\. Use \+ New Program/);
});

test('B5. selecting a Program mounts the existing editor with configuration context, Program Setup first, four sub-tabs', async () => {
  const ws = fakeWorkspace();
  const s = mountShell({permissions: ADMIN, workspace: ws});
  await s.api.ready;
  s.click({'[data-tpc-select]': true, el: {dataset: {tpcSelect: '5'}}});
  await new Promise(r => setImmediate(r));
  const ctx = ws.rendered.at(-1);
  assert.ok(ctx, 'TalentProgramWorkspace.render was called');
  assert.equal(ctx.configuration, true);
  assert.equal(ctx.params.get('program_id'), '5');
  assert.equal(ctx.params.get('academic_year_id'), '1');
  assert.equal(s.win.location.hash, '#tp-basics');
  assert.match(s.win.location.search, /program_id=5/);
  assert.deepEqual([...s.els['tpc-subtabs'].innerHTML.matchAll(/data-tpc-subtab="([a-z]+)"/g)].map(m => m[1]), ['setup', 'rubric', 'periods', 'criteria']);
  assert.match(s.els['tpc-subtabs'].innerHTML, /href="#tp-schedule"/);
  assert.match(s.els['tpc-center-head'].innerHTML, /Mental Math/);
  assert.match(s.els['tpc-center-head'].innerHTML, /data-tpc-edit-program/);
  assert.equal(s.calls.filter(c => c.method !== 'GET').length, 0, 'selecting never mutates');
});

test('B6. deep link opens the requested Program and step; Evaluation Periods overview reads plans through the canonical API', async () => {
  const ws = fakeWorkspace();
  const s = mountShell({permissions: ADMIN, workspace: ws, search: '?program_id=6&academic_year_id=1', hash: '#tp-rubric'});
  await s.api.ready;
  assert.equal(ws.rendered.at(-1).params.get('program_id'), '6');
  assert.equal(s.win.location.hash, '#tp-rubric', 'a supplied step is preserved');
  const periods = mountShell({permissions: ADMIN, workspace: ws, search: '?tab=evaluation-periods', plans: [{program_id: 5, period_count: 2, required_period_count: 1}]});
  await periods.api.ready;
  assert.ok(periods.calls.some(c => c.url === '/api/talent/evaluation-plans?academic_year_id=1'));
  assert.match(periods.els['tpc-content'].innerHTML, /2 Periods · 1 required/);
  assert.match(periods.els['tpc-content'].innerHTML, /data-tpc-open-periods="5"[^>]*>Manage Periods/);
});

test('B7. New Program uses the shared create helper and the canonical delete goes only to the Programs API after confirmation', async () => {
  const ws = fakeWorkspace();
  const s = mountShell({permissions: ADMIN, workspace: ws});
  await s.api.ready;
  s.click({'[data-tpc-action="new-program"]': true, el: {}});
  await new Promise(r => setImmediate(r));
  assert.match(s.els['tpc-content'].innerHTML, /<form data-form="create-program">/);
  const declined = mountShell({permissions: ADMIN, workspace: ws, confirm: () => false});
  await declined.api.ready;
  declined.click({'[data-tpc-delete]': true, el: {dataset: {tpcDelete: '5'}}});
  await new Promise(r => setImmediate(r));
  assert.equal(declined.calls.filter(c => c.method === 'DELETE').length, 0);
  s.click({'[data-tpc-delete]': true, el: {dataset: {tpcDelete: '5'}}});
  await new Promise(r => setImmediate(r));
  assert.deepEqual(s.calls.filter(c => c.method === 'DELETE'), [{url: '/api/talent/programs/5', method: 'DELETE'}]);
});

test('B8. the shell never re-implements editors, validation or authorization', () => {
  const source = read('talent-configuration.js');
  assert.doesNotMatch(source, /method:\s*'(?:POST|PUT|PATCH)'/, 'only the canonical editors / shared helpers write (plus DELETE Program via the Programs API)');
  assert.doesNotMatch(source, /talent_programs\.manage[^;]*=\s*true|permissions\[[^\]]+\]\s*=\s*true/);
  assert.match(source, /TalentProgramWorkspace/);
  assert.match(source, /TalentEvaluationWorkspace/);
});

test('B9. the shared editor helpers exist once and the editor hides its Programs back-link in configuration mode', async () => {
  const workspace = require('../static/js/talent-program-workspace.js');
  assert.equal(typeof workspace.newProgramFormHtml, 'function');
  assert.equal(typeof workspace.submitNewProgram, 'function');
  assert.match(workspace.newProgramFormHtml(['1', 'KG']), /name="grade_1"[\s\S]*name="grade_KG"/);
  const calls = [];
  const formEl = {};
  const OldFormData = global.FormData;
  global.FormData = class extends Map { constructor() { super([['name', 'Robotics'], ['description', 'd'], ['grade_2', 'on']]); } has(k) { return super.has(k); } };
  try {
    await assert.rejects(() => workspace.submitNewProgram(formEl, {api: async () => ({}), year: '1', planningGrades: ['1']}), /Choose at least one eligible Grade\./);
    const created = await workspace.submitNewProgram(formEl, {api: async (p, o) => { calls.push([p, o.method]); return {id: 77}; }, year: '1', planningGrades: ['2']});
    assert.equal(created.id, 77);
    assert.deepEqual(calls, [['/api/talent/programs', 'POST'], ['/api/talent/programs/77/academic-years/1', 'PUT']]);
  } finally { global.FormData = OldFormData; }
});

test('B10. in configuration mode the editor omits its "All Programs" back-link and duplicate step nav (the shell owns them)', async () => {
  const {render} = require('../static/js/talent-program-workspace.js');
  const framework = {id: 31, title: 'Setup', status: 'draft', version_number: 1, revision: 1, semantic_fingerprint: 'f', competencies: []};
  const build = configuration => {
    const root = {innerHTML: '', querySelector: () => null, querySelectorAll: () => [], setAttribute() {}, removeAttribute() {}};
    return {root, ctx: {root, year: '1', yearLabel: '2026', params: new URLSearchParams('program_id=11'), configuration, hash: '', can: () => true,
      api: async path => {
        if (path === '/api/talent/programs/11') return {id: 11, name: 'Arts', status: 'draft'};
        if (path.startsWith('/api/talent/programs/planning-grades')) return ['1'];
        if (path.endsWith('/academic-years')) return [{academic_year_id: 1, is_enabled: true, eligible_grade_levels: ['1']}];
        if (path.endsWith('/frameworks')) return [framework];
        if (path.endsWith('/competencies')) return [];
        if (path.endsWith('/configuration')) return {levels: [], rubrics: [], descriptors: [], rubric: {}, kpi: null};
        if (path.startsWith('/api/talent/evaluation-plans')) return [];
        return framework;
      }}};
  };
  const configuration = build(true);
  await render(configuration.ctx);
  assert.doesNotMatch(configuration.root.innerHTML, /All Programs/);
  assert.match(configuration.root.innerHTML, /Program summary/);
  const operationalLegacy = build(false);
  await render(operationalLegacy.ctx);
  assert.match(operationalLegacy.root.innerHTML, /All Programs/);
});
