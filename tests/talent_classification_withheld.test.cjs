'use strict';
/* Classification aggregate honesty (production follow-up, Part 1 C). Stub/structural
 * verification only. The browser never decides publishability: it explains a backend
 * non-visible state with ONE uniform sentence and renders no hidden value anywhere. */
const {test} = require('node:test');
const assert = require('node:assert/strict');
const charts = require('../static/js/talent-charts.js');

const bucket = (label, state, count, percentage) => ({label, state, count: state === 'visible' ? count : null, percentage: state === 'visible' ? percentage : null});
const mixed = {state: 'visible', total: {state: 'visible', value: 22}, buckets: [
  bucket('Needs Improvement', 'visible', 7, 31.82), bucket('Developing', 'suppressed'), bucket('Meets Expectations', 'suppressed'),
  bucket('Advanced', 'visible', 5, 22.73), bucket('Exceptional', 'visible', 6, 27.27)]};
const allHidden = {state: 'visible', total: {state: 'visible', value: 6}, buckets: ['Needs Improvement', 'Developing', 'Meets Expectations', 'Advanced', 'Exceptional'].map(l => bucket(l, 'suppressed'))};

test('C1. hidden Classification groups read Unavailable and one uniform sentence explains why', () => {
  for (const projection of [mixed, allHidden]) {
    const html = charts.chart('Current Classification', projection, 'classification');
    assert.match(html, /data-chart-withheld-note/);
    assert.match(html, /withheld to protect individual Students/);
    assert.match(html, /Unavailable/);
    // The sentence never names a threshold or which groups were hidden for which reason.
    const note = html.match(/data-chart-withheld-note>([^<]*)</)[1];
    assert.doesNotMatch(note, /fewer than|minimum|\d|complementary|below|small/i);
  }
});

test('C2. the explanation adds no hidden value (no total, count, percentage or geometry for a hidden group)', () => {
  const html = charts.chart('Current Classification', allHidden, 'classification');
  for (const token of ['22', '31.82', 'width:', 'aria-valuenow', 'data-value']) assert.ok(!html.includes(token), token);
  assert.equal((html.match(/data-chart-row/g) || []).length, 5);
  assert.ok(!/data-count|dataset|title="/.test(html));
});

test('C3. a fully visible Classification shows no withheld note, and other families never get it', () => {
  const visible = {state: 'visible', buckets: [bucket('Developing', 'visible', 9, 100)]};
  assert.doesNotMatch(charts.chart('Current Classification', visible, 'classification'), /withheld/);
  assert.doesNotMatch(charts.chart('Completion', mixed, 'completion'), /withheld/);
  assert.doesNotMatch(charts.chart('Learning Style', mixed, 'learning-style'), /withheld/);
});

test('C4. a suppressed Classification total is explained precisely and renders no rows or numbers', () => {
  const html = charts.chart('Current Classification', {state: 'suppressed', total: {state: 'suppressed', value: null}, buckets: allHidden.buckets}, 'classification');
  assert.match(html, /not available for this selection: Classification is withheld to protect individual Students/);
  assert.ok(!html.includes('data-chart-row'));
  assert.doesNotMatch(html.replace(/<[^>]*>/g, ''), /\d/);
});

test('C5. restricted (fail-closed configuration) keeps the neutral message and the M18a copy rules', () => {
  const html = charts.chart('Current Classification', {state: 'restricted', total: {state: 'restricted', value: null}, buckets: []}, 'classification');
  assert.match(html, /This summary is not available for this selection\./);
  assert.doesNotMatch(html, /protected for privacy|Protected for privacy|withheld/);
});

test('C6. chart mode switching keeps the explanation and never exposes hidden magnitudes', () => {
  // Part 2 D: the old "percentage" mode was the same picture as the count bar and is gone;
  // a partially withheld Classification can only be a bar (no circular type for a partial partition).
  assert.deepEqual(charts.modes(mixed, 'classification'), ['bar']);
  const html = charts.chart('Current Classification', mixed, 'classification', 'doughnut');
  assert.match(html, /data-chart-withheld-note/);
  assert.ok(!html.includes('conic-gradient'));
});
