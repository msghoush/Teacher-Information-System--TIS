/*
 * Progress Over Time comparability closure (ADR 0044, 2026-09-25). Node stub harness only
 * (no real browser). The backend `comparisons` list is the sole authority: a trend line is
 * never drawn across a pair that is not comparable, and the client never derives it.
 */
const {test} = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const charts = require('../static/js/talent-charts.js');
const {createEnv} = require('./talent_runtime_harness.cjs');
const read = file => fs.readFileSync(path.join(__dirname, '..', file), 'utf8');

const pt = (id, label, pct, state = 'visible') => ({id, label, state, percentage: state === 'visible' ? pct : undefined, count: state === 'visible' ? pct : undefined, denominator: state === 'visible' ? 100 : undefined});
const cmp = (a, b, state = 'comparable', reason = null) => ({evaluation_period_ids: [a, b], state, reason_code: state === 'comparable' ? null : reason});
const svgOf = html => html.match(/<svg class="tp-trend"[\s\S]*?<\/svg>/)[0];
const polylines = html => (svgOf(html).match(/<polyline points="([^"]*)"/g) || []).map(m => m.replace(/<polyline points="|"/g, ''));
const dots = html => (svgOf(html).match(/<circle /g) || []).length;
const trend = (points, comparisons) => charts.series('Completion by Evaluation Period', points, {surface: 'longitudinal', ...(comparisons === undefined ? {} : {comparisons})});
// x positions for n rows: 10 + i*280/(n-1)
const X = (i, n) => 10 + i * 280 / Math.max(1, n - 1);

test('C1. comparable visible adjacent Periods connect in one polyline', () => {
  const html = trend([pt(1, 'A', 20), pt(2, 'B', 40)], [cmp(1, 2)]);
  const lines = polylines(html);
  assert.equal(lines.length, 1);
  assert.equal(lines[0].split(' ').length, 2);
  assert.equal(dots(html), 2);
  assert.doesNotMatch(html, /tp-trend-break|not connected/);
});

test('C2. a framework_changed (non-comparable) pair is not connected but both dots render', () => {
  const html = trend([pt(1, 'A', 20), pt(2, 'B', 40)], [cmp(1, 2, 'not_comparable', 'framework_changed')]);
  assert.equal(polylines(html).length, 0, 'no polyline spans the boundary');
  assert.equal(dots(html), 2);
  assert.match(html, /tp-trend-break/);
  assert.match(html, /B: 40% \(40 of 100\) \(not connected: periods are not comparable\)/);
  assert.match(html, /<li>A: 20% \(20 of 100\)<\/li>/, 'the earlier period carries no note');
});

test('C3. suppressed and no-data gaps still break exactly as before (no coordinate, dashed gap marker)', () => {
  const pts = [pt(1, 'A', 20), pt(2, 'B', 0, 'suppressed'), pt(3, 'C', 50), pt(4, 'D', 0, 'no_data'), pt(5, 'E', 60)];
  const html = trend(pts, [cmp(1, 2), cmp(2, 3), cmp(3, 4), cmp(4, 5)]);
  assert.equal(polylines(html).length, 0);
  assert.equal((svgOf(html).match(/tp-trend-gap/g) || []).length, 2);
  assert.equal(dots(html), 3);
  assert.doesNotMatch(html, /tp-trend-break/, 'a gap is not a comparability break');
  assert.match(html, /B: Unavailable/);
  assert.match(html, /D: No data yet/);
});

test('C4. mixed comparable -> non-comparable -> comparable yields the exact separate segments', () => {
  const pts = [pt(1, 'A', 10), pt(2, 'B', 20), pt(3, 'C', 30), pt(4, 'D', 40)];
  const html = trend(pts, [cmp(1, 2), cmp(2, 3, 'not_comparable', 'framework_changed'), cmp(3, 4)]);
  const y = v => 110 - v;
  assert.deepEqual(polylines(html), [`${X(0, 4)},${y(10)} ${X(1, 4)},${y(20)}`, `${X(2, 4)},${y(30)} ${X(3, 4)},${y(40)}`]);
  assert.equal(dots(html), 4);
  assert.equal((svgOf(html).match(/tp-trend-break/g) || []).length, 1);
});

test('C5. a missing comparison record for a pair does not connect (fail toward not connecting)', () => {
  const pts = [pt(1, 'A', 10), pt(2, 'B', 20), pt(3, 'C', 30)];
  const html = trend(pts, [cmp(2, 3)]);
  assert.deepEqual(polylines(html), [`${X(1, 3)},${110 - 20} ${X(2, 3)},${110 - 30}`]);
  assert.equal(polylines(trend(pts, [])).length, 0, 'an empty governed list connects nothing');
  assert.equal(polylines(trend(pts, [cmp(1, 2), {evaluation_period_ids: [2, 3]}])).length, 1, 'an unknown state never connects');
  assert.equal(polylines(trend([{...pt(1, 'A', 10), id: undefined}, pt(2, 'B', 20)], [cmp(1, 2)])).length, 0, 'an unmapped id never connects');
});

test('C6. the backend state decides, not how the points look; the inverse holds too', () => {
  const same = [pt(1, 'A', 50), pt(2, 'B', 50)];
  assert.equal(polylines(trend(same, [cmp(1, 2, 'not_comparable', 'framework_changed')])).length, 0);
  const far = [pt(1, 'A', 5), pt(2, 'B', 95)];
  assert.equal(polylines(trend(far, [cmp(1, 2)])).length, 1);
  assert.equal(polylines(trend(far, [cmp(1, 2, 'not_comparable', 'privacy_protected')])).length, 0);
});

test('C7. without governance (no comparisons supplied) the existing behaviour is unchanged', () => {
  assert.equal(polylines(trend([pt(1, 'A', 20), pt(2, 'B', 40)])).length, 1);
});

test('C8. the table keeps every visible Period value across the break and no hidden value is added', () => {
  const html = trend([pt(1, 'A', 20), pt(2, 'B', 40), pt(3, 'C', 97, 'suppressed')], [cmp(1, 2, 'not_comparable', 'framework_changed'), cmp(2, 3)]);
  assert.match(html, /<th scope="row">A<\/th><td>20<\/td><td>20%<\/td>/);
  assert.match(html, /<th scope="row">B<\/th><td>40<\/td><td>40%<\/td>/);
  assert.doesNotMatch(html, /97/);
  assert.match(html, /data-state="visible" data-link="broken"/);
});

test('C9. the break survives switching chart type and back (state carried in the table)', () => {
  const html = trend([pt(1, 'A', 20), pt(2, 'B', 40), pt(3, 'C', 60)], [cmp(1, 2), cmp(2, 3, 'not_comparable', 'framework_changed')]);
  const rows = Array.from(html.matchAll(/<tr data-chart-row data-state="([^"]*)"([^>]*)>/g)).map(m => /data-link="broken"/.test(m[2]) ? false : /data-link="comparable"/.test(m[2]) ? true : null);
  assert.deepEqual(rows, [null, true, false]);
  const src = read('static/js/talent-charts.js');
  assert.match(src, /link:tr\.dataset\.link==='comparable'\?true:tr\.dataset\.link==='broken'\?false:null/);
});

test('C10. Progress Over Time passes the backend comparisons through and never derives comparability', async () => {
  const cell = (p, n) => ({state: 'visible', percentage: p, numerator: n, denominator: 10});
  const point = (id, label, c, fv) => ({evaluation_period: {id, sequence: id, label, status: 'planned'}, cycle: {id: id * 10, status: 'open', framework_version_id: fv}, metric_result: c});
  const data = {metric: 'completion_coverage', program: {name: 'Math'}, academic_year: {label: '2026'}, points: [
    point(1, 'Autumn', cell(20, 2), 7), point(2, 'Winter', cell(40, 4), 8), point(3, 'Spring', cell(60, 6), 8)],
  comparisons: [cmp(1, 2, 'not_comparable', 'framework_changed'), cmp(2, 3)]};
  const env = createEnv({view: 'longitudinal', permissions: {'talent_analytics.view': true}, search: '?academic_year_id=1&program_id=5', globals: {TalentCharts: charts},
    handler: url => url.includes('/longitudinal') ? {body: data} : {body: []}});
  await env.start();
  const html = env.text();
  assert.equal(polylines(html).length, 1, 'only the comparable Winter-Spring pair is joined');
  assert.equal(dots(html), 3);
  assert.match(html, /Winter: 40% \(4 of 10\) \(not connected: periods are not comparable\)/);
  // Source inspection: no framework/version logic drives this decision.
  const charted = read('static/js/talent-charts.js');
  const periodVisual = read('static/js/talent.js').match(/function periodVisual\(data\) \{[\s\S]*?\n  \}\r?\n/)[0];
  const seriesFn = charted.match(/function series\([\s\S]*?\n  \}\r?\n/)[0];
  for (const src of [seriesFn, periodVisual]) assert.doesNotMatch(src, /framework/i);
  assert.match(periodVisual, /comparisons:data\.comparisons/);
});
