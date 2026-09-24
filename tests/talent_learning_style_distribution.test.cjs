/* Deployment Acceptance Correction C: Learning Style distribution presentation.
 * Structurally verified against the exported renderer (no real browser). */
const {test} = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const {learningStyleDistributionSection} = require('../static/js/talent.js');

const ORDER = ['Visual', 'Auditory', 'Read/Write', 'Kinesthetic', 'Verbal', 'Non-verbal', 'Quantitative', 'Spatial', 'Unassigned'];
const COUNTS = [3, 2, 1, 1, 1, 0, 0, 0, 2];
const level = (label, i) => ({
  key: label === 'Unassigned' ? 'not_specified' : label, label, display_order: i, state: 'visible',
  count: COUNTS[i], percentage: COUNTS[i] * 10,
});
const distribution = {state: 'visible', total_population: 10, total: {state: 'visible', value: 10}, levels: ORDER.map(level)};
const render = d => learningStyleDistributionSection('tp-learning-style', 'Learning Style', 'Learning Style Distribution', 'desc', d);

test('renders label, count, percentage and a backend-percentage bar for every category', () => {
  const html = render(distribution);
  assert.match(html, /10 Students in this selection, including Unassigned/);
  for (const label of ORDER) assert.ok(html.includes(`>${label}</span>`), `${label} row`);
  assert.match(html, /width:30%/);
  assert.match(html, /30%<\/strong><small>3 Students<\/small>/);
  assert.match(html, /1 Student<\/small>/);
  assert.match(html, /aria-label="Visual: 30 percent, 3 Students"/);
  assert.equal((html.match(/class="tp-grade-track"/g) || []).length, 9);
  // accessible table equivalent carries the same backend values
  assert.match(html, /<th scope="row">Visual<\/th><td>3<\/td><td>30%<\/td>/);
});

test('zero categories stay visible as 0 / 0% with an empty bar, never Unavailable', () => {
  const html = render(distribution);
  for (const label of ['Non-verbal', 'Quantitative', 'Spatial']) {
    assert.match(html, new RegExp(`>${label}</span><div class="tp-grade-track" role="img" aria-label="${label}: 0 percent, 0 Students"><span style="width:0%"></span></div><strong>0%</strong><small>0 Students</small>`));
  }
  assert.doesNotMatch(html, /Unavailable|Protected|suppress/i);
});

test('Unassigned is visible with a neutral treatment class', () => {
  const html = render(distribution);
  assert.match(html, /tp-grade-row tp-ls-unassigned"><span class="tp-grade-label">Unassigned/);
  assert.match(html, /20%<\/strong><small>2 Students/);
});

test('frontend never computes percentages: it renders the backend value verbatim', () => {
  const skewed = {...distribution, levels: distribution.levels.map(l => l.label === 'Visual' ? {...l, count: 3, percentage: 41.5} : l)};
  const html = render(skewed);
  assert.match(html, /width:41\.5%/);
  assert.match(html, /41\.5%<\/strong>/);
  assert.doesNotMatch(html, /width:30%/);
});

test('empty authorized population shows an empty state, not 0% bars', () => {
  const html = render({state: 'empty', total_population: 0, levels: ORDER.map((label, i) => ({...level(label, i), count: 0, percentage: null}))});
  assert.match(html, /No Students in the current authorized selection\./);
  assert.doesNotMatch(html, /tp-grade-track|<table/);
});

test('missing/failed distribution shows the neutral not-available state; no per-Student percentage anywhere', () => {
  assert.match(render(null), /not available for this selection/);
  assert.match(render({state: 'restricted', levels: []}), /not available for this selection/);
  const source = fs.readFileSync(path.join(__dirname, '..', 'static', 'js', 'talent.js'), 'utf8');
  assert.doesNotMatch(source, /learning_style_(verbal|non_verbal|quantitative|spatial)_percentage/);
  const html = render(distribution);
  assert.doesNotMatch(html, /Student's percentage|per-Student percentage of/i);
});

test('responsive CSS collapses the Learning Style row at narrow widths', () => {
  const css = fs.readFileSync(path.join(__dirname, '..', 'static', 'css', 'talent.css'), 'utf8');
  assert.match(css, /@media \(max-width: 680px\)[\s\S]*\.tp-ls-chart \.tp-grade-row \{grid-template-columns: 1fr auto auto/);
});
