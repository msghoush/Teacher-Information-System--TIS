'use strict';
// System Configuration > Talent & Potential: Grade > Competency > Rubric Level tree.
const test = require('node:test');
const assert = require('node:assert/strict');
const tree = require('../static/js/talent-configuration-tree.js');

const members = [
  {id: 1, label: 'Number Recognition', grade_level: '1'},
  {id: 2, label: 'Basic Operations', grade_level: '1'},
  {id: 3, label: 'Reading Fluency', grade_level: '2'},
];
const rubrics = [
  {id: 10, framework_competency_id: 1, name: 'Number Recognition', levels: [
    {id: 100, order: 1, label: 'Beginning', description: 'Starting'}, {id: 101, order: 2, label: 'Developing', description: ''}]},
];
const grades = tree.groupByGrade(members).map(g => ({...g, members: g.members.map(m => ({...m, rubric: tree.rubricFor(m.id, rubrics)}))}));

test('T1. groups competencies by Grade in numeric order and nests Competency > Rubric > Levels', () => {
  const html = tree.treeHtml({grades, rubrics}, {editable: true, canDeleteCompetency: true, canDeleteLevel: true});
  assert.match(html, /role="tree"/);
  assert.ok(html.indexOf('Grade 1') < html.indexOf('Grade 2'));
  assert.ok(html.indexOf('Grade 1') < html.indexOf('Number Recognition'));
  assert.ok(html.indexOf('Number Recognition') < html.indexOf('Beginning'));
  assert.ok(html.indexOf('Beginning') < html.indexOf('Developing'));
  assert.doesNotMatch(html, /Reading Fluency[\s\S]*Beginning/);
  assert.match(html, /2 Levels/);
  assert.match(html, /No rubric/);
});

test('T2. expandable nodes expose aria-expanded and accessible names', () => {
  const html = tree.treeHtml({grades, rubrics}, {editable: true, canDeleteCompetency: true, canDeleteLevel: true});
  assert.match(html, /data-tpc-toggle aria-expanded="true" aria-label="Collapse Grade 1"/);
  assert.match(html, /aria-expanded="false" aria-label="Expand Number Recognition"/);
  assert.match(html, /aria-label="Edit Level Beginning"/);
  assert.match(html, /aria-label="Delete Level Beginning"/);
});

test('T3. a locked (non-editable) rubric exposes no edit, add or delete controls', () => {
  const html = tree.treeHtml({grades, rubrics}, {editable: false, canDeleteCompetency: false, canDeleteLevel: false});
  assert.doesNotMatch(html, /data-tpc-level-edit|data-tpc-level-delete|data-tpc-competency-delete|data-tpc-level-add|data-tpc-competency-add|data-tpc-rubric-add/);
  assert.match(html, /data-tpc-level-select/); // still readable
});

test('T4. delete controls follow the server-derived capability separately from edit', () => {
  const html = tree.treeHtml({grades, rubrics}, {editable: true, canDeleteCompetency: false, canDeleteLevel: false});
  assert.match(html, /data-tpc-level-edit/);
  assert.doesNotMatch(html, /data-tpc-level-delete|data-tpc-competency-delete/);
});

test('T5. Level editor shows only existing canonical fields with Cancel and Save Changes', () => {
  const html = tree.levelEditorHtml({levelId: 100, order: 1, label: 'Beginning', description: 'Starting', descriptor: 'Can count to 10', gradeLabel: 'Grade 1', competencyLabel: 'Number Recognition'});
  assert.match(html, /name="label"[^>]*value="Beginning"/);
  assert.match(html, /name="order"[^>]*disabled/);
  assert.match(html, /name="description"/);
  assert.match(html, /name="descriptor"/);
  assert.match(html, /data-tpc-level-cancel[^>]*>Cancel</);
  assert.match(html, /type="submit"[^>]*>Save Changes</);
  assert.doesNotMatch(html, /Achievement Indicators|Add Indicator/);
});

test('T6. Level editor escapes stored text', () => {
  const html = tree.levelEditorHtml({levelId: 1, label: '<img src=x onerror=1>', description: '"><script>', descriptor: ''});
  assert.doesNotMatch(html, /<img src=x|<script>/);
});

test('T7. render() loads the Draft framework via canonical routes and never writes on load', async () => {
  const calls = [];
  const root = {innerHTML: '', attrs: {}, setAttribute(k, v) { this.attrs[k] = v; }, removeAttribute(k) { delete this.attrs[k]; }, addEventListener() {}};
  const drawer = {innerHTML: ''};
  const api = async (path, init) => {
    calls.push([path, init?.method || 'GET']);
    if (path.endsWith('/frameworks')) return [{id: 7, status: 'draft', version_number: 2}, {id: 6, status: 'active', version_number: 1}];
    if (path.endsWith('/frameworks/7')) return {id: 7, revision: 4, status: 'draft', competencies: members};
    if (path.endsWith('/configuration')) return {revision: 4, rubrics, descriptors: []};
    throw new Error('unexpected ' + path);
  };
  await tree.render({root, drawer, api, can: key => key === 'talent_programs.manage', programId: 5, program: {name: 'Mental Math'}, notify() {}});
  assert.ok(calls.every(([, method]) => method === 'GET'));
  assert.deepEqual(calls.map(c => c[0]), [
    '/api/talent/programs/5/frameworks', '/api/talent/programs/5/frameworks/7', '/api/talent/programs/5/frameworks/7/configuration']);
  assert.match(root.innerHTML, /Number Recognition/);
  assert.match(root.innerHTML, /data-tpc-level-edit/);
  assert.equal(root.attrs['aria-busy'], undefined);
  assert.match(drawer.innerHTML, /Select a Level/);
});

test('T8. an active (locked) framework renders read-only even for a manager', async () => {
  const root = {innerHTML: '', attrs: {}, setAttribute() {}, removeAttribute() {}, addEventListener() {}};
  const api = async path => {
    if (path.endsWith('/frameworks')) return [{id: 6, status: 'active', version_number: 1}];
    if (path.endsWith('/frameworks/6')) return {id: 6, revision: 2, status: 'active', competencies: members};
    return {revision: 2, rubrics, descriptors: []};
  };
  await tree.render({root, drawer: {innerHTML: ''}, api, can: () => true, programId: 5, program: {}, notify() {}});
  assert.doesNotMatch(root.innerHTML, /data-tpc-level-edit|data-tpc-level-add|data-tpc-competency-add|data-tpc-level-delete/);
});

test('T9. a revision mismatch between framework and configuration is reported, not rendered', async () => {
  const root = {innerHTML: '', attrs: {}, setAttribute() {}, removeAttribute() {}, addEventListener() {}};
  const api = async path => {
    if (path.endsWith('/frameworks')) return [{id: 7, status: 'draft', version_number: 1}];
    if (path.endsWith('/frameworks/7')) return {id: 7, revision: 5, status: 'draft', competencies: members};
    return {revision: 4, rubrics, descriptors: []};
  };
  await tree.render({root, drawer: {innerHTML: ''}, api, can: () => true, programId: 5, program: {}, notify() {}});
  assert.match(root.innerHTML, /role="alert"/);
  assert.doesNotMatch(root.innerHTML, /role="tree"/);
});

test('T10. rerender replaces delegated tree handlers instead of accumulating them', async () => {
  const listeners = {click: [], submit: []};
  const removed = {click: [], submit: []};
  const root = {
    innerHTML: '', attrs: {}, setAttribute() {}, removeAttribute() {},
    addEventListener(type, handler) { listeners[type].push(handler); },
    removeEventListener(type, handler) { removed[type].push(handler); },
  };
  const api = async path => {
    if (path.endsWith('/frameworks')) return [{id: 7, status: 'draft', version_number: 1}];
    if (path.endsWith('/frameworks/7')) return {id: 7, revision: 4, status: 'draft', competencies: members};
    return {revision: 4, rubrics, descriptors: []};
  };
  const context = {root, drawer: {innerHTML: ''}, api, can: () => true, programId: 5, program: {}, notify() {}};

  await tree.render(context);
  const first = root._tpcTreeHandlers;
  await tree.render(context);

  assert.deepEqual(removed.click, [first.click]);
  assert.deepEqual(removed.submit, [first.submit]);
  assert.equal(listeners.click.length, 2);
  assert.equal(listeners.submit.length, 2);
});
