'use strict';
/* Production follow-up Part 2: chart-type semantics, Results & Analytics filter UX,
 * Selected Comparisons information architecture, Progress Over Time decision.
 * Node stub harness only (no real browser): behaviour, markup and CSS structure are
 * asserted; pixel appearance and real scroll physics are not claimed. */
const {test} = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const charts = require('../static/js/talent-charts.js');
const dashboard = require('../static/js/talent-dashboard.js');
const {createEnv} = require('./talent_runtime_harness.cjs');
const read = file => fs.readFileSync(path.join(__dirname, '..', file), 'utf8');

const bucket = (label, count, percentage) => ({label, state: 'visible', count, percentage});
const partition = {state: 'visible', total: {state: 'visible', value: 10}, buckets: [bucket('Completed', 6, 60), bucket('In progress', 3, 30), bucket('Not started', 1, 10)]};
const classification = {state: 'visible', buckets: [bucket('Needs Improvement', 1, 10), bucket('Developing', 2, 20), bucket('Meets Expectations', 3, 30), bucket('Advanced', 2, 20), bucket('Exceptional', 2, 20)]};
const styles = {state: 'visible', total_population: 9, levels: Array.from({length: 9}, (_, i) => ({label: `Style ${i}`, state: 'visible', count: 1, percentage: i < 8 ? 11.1 : 11.2}))};
const payload = (mark = 30) => ({
  options: {branch: [{id: '6', label: 'B'}], grade: [{id: '3', label: 'Grade 3'}, {id: '4', label: 'Grade 4'}], section: [], program: [{id: '5', label: 'Math'}], period: []},
  distinct_students: {state: 'visible', value: mark}, participations: {state: 'visible', value: 60},
  completion: partition, classification, learning_style: styles, comparison: {groups: [{id: '3', label: 'Grade 3', completion: partition, classification}, {id: '4', label: 'Grade 4', completion: {state: 'restricted'}, classification: {state: 'restricted'}}]},
  rubric: {competencies: [], indicators: []}, trend: [],
});
const FULL = {'talent_analytics.view': true, 'students.view': true};

// ---------------------------------------------------------------- D. chart types
test('P1. per-metric allowed chart types: Bar/Doughnut for partitions, Bar only for ordinal or high-cardinality, Trend only for series', () => {
  assert.deepEqual(charts.modes(classification, 'classification'), ['bar', 'doughnut']);
  assert.deepEqual(charts.modes(partition, 'completion'), ['bar', 'doughnut']);
  assert.deepEqual(charts.modes(styles, 'learning-style'), ['bar'], 'eight styles plus Unassigned (9) is not legible as slices');
  assert.deepEqual(charts.modes(classification, 'rubric'), ['bar'], 'ordinal levels stay a bar');
  for (const family of ['classification', 'completion', 'learning-style', 'rubric', 'trend', 'series', 'comparison']) {
    for (const projection of [classification, partition, styles]) {
      const offered = charts.modes(projection, family);
      assert.ok(!offered.includes('percentage') && !offered.includes('pie'), `${family}: duplicate visual types are never offered`);
      if (family === 'trend' || family === 'series') assert.ok(!offered.includes('doughnut'), 'no circular chart for a time series');
    }
  }
});

test('P2. no chart renders two switch buttons that produce the same picture, and every type keeps exact values visible', () => {
  for (const [family, projection] of [['classification', classification], ['completion', partition]]) {
    const pictures = new Set();
    for (const mode of charts.modes(projection, family)) {
      const html = charts.chart('X', projection, family, mode);
      const visual = html.match(/<div data-chart-visual>([\s\S]*?)<\/div><details>/)[1];
      assert.ok(!pictures.has(visual), `${family}/${mode}`);
      pictures.add(visual);
      for (const row of projection.buckets) assert.ok(html.includes(`${row.percentage}%`), `${family}/${mode} shows ${row.label} percentage`);
    }
  }
});

test('P3. Overview aggregate widgets default to Doughnut where valid and fall back to Bar otherwise', () => {
  const html = dashboard.overview({classification, learning_style: styles, completion: partition});
  assert.equal((html.match(/is-doughnut/g) || []).length, 2, 'Classification and completion are doughnuts');
  const style = html.split('data-chart-family="learning-style"')[1].split('</section>')[0];
  assert.ok(!style.includes('is-doughnut') && style.includes('tp-chart-bars'), 'Learning Style is a bar');
  const partial = dashboard.overview({classification: {state: 'visible', buckets: [bucket('Developing', 2, 40), {label: 'Advanced', state: 'suppressed'}]}, learning_style: styles, completion: partition});
  assert.equal((partial.match(/is-doughnut/g) || []).length, 1, 'a partly withheld Classification is a bar, never a doughnut');
  assert.ok(!partial.includes('conic-gradient(') || partial.split('conic-gradient(').length === 2);
  const analytics = dashboard.analytics(payload(), new URLSearchParams(), null);
  assert.ok(!analytics.includes('is-doughnut'), 'Results & Analytics keeps Bar as the default');
});

test('P4. accessible tables and legends exist for every type', () => {
  const html = dashboard.overview({classification, learning_style: styles, completion: partition});
  assert.equal((html.match(/<table>/g) || []).length, 3);
  assert.equal((html.match(/<summary>Exact values and accessible table<\/summary>/g) || []).length, 3);
  assert.match(html, /tp-chart-legend/);
  assert.match(html, /aria-hidden="true" style="background:conic-gradient/);
});

test('P5. a deliberate chart-type choice survives a data refresh and never re-triggers the entrance animation', () => {
  const listeners = {};
  const removed = [];
  const rows = charts.sanitize(classification);
  const host = {
    dataset: {chartFamily: 'classification', chartKey: 'classification|Current Classification|overview'}, visual: {innerHTML: ''},
    querySelector: () => host.visual,
    querySelectorAll: selector => selector === '[data-chart-row]'
      ? rows.map(r => ({dataset: {state: r.state}, children: [{textContent: r.label}, {textContent: String(r.count)}, {textContent: `${r.percentage}%`}]}))
      : [],
    closest: selector => selector === '.tp-motion-enter' ? {classList: {remove: name => removed.push(name)}} : null,
  };
  const button = {dataset: {chartMode: 'bar'}, closest: () => host, setAttribute() {}};
  charts.bind({addEventListener: (type, fn) => { listeners[type] = fn; }});
  assert.match(dashboard.overview({classification, learning_style: styles, completion: partition}), /is-doughnut/);
  listeners.click({target: {closest: selector => selector === '[data-chart-mode]' ? button : null}});
  assert.match(host.visual.innerHTML, /tp-chart-bars/);
  assert.deepEqual(removed, ['tp-motion-enter']);
  const again = dashboard.overview({classification, learning_style: styles, completion: partition});
  const classificationChart = again.split('data-chart-family="classification"')[1].split('</section>')[0];
  assert.ok(classificationChart.includes('tp-chart-bars') && !classificationChart.includes('is-doughnut'), 'the choice is remembered');
  // The completion chart was not touched and keeps its own default.
  assert.match(again.split('data-chart-family="completion"')[1], /is-doughnut/);
});

test('P6. final Executive Overview is motion-neutral for every motion preference', async () => {
  const executive = {filters:{branches:[],grades:[],programs:[],periods:[]},summary:{},classification,learning_style:styles,completion:partition,programs:[],students:[],student_rows_state:'restricted'};
  const run = async matchMedia => {
    const globals = matchMedia === undefined ? {} : {matchMedia};
    const env = createEnv({view: 'overview', permissions: FULL, globals: {TalentCharts: charts, TalentDashboard: dashboard, ...globals}, handler: url => url.includes('/executive-overview') ? {body: executive} : {body: []}});
    await env.start();
    return env;
  };
  const animated = await run(() => ({matches: false}));
  assert.doesNotMatch(animated.text(), /tp-motion-enter/);
  assert.match(animated.text(), /Executive Overview/);
  const reduced = await run(() => ({matches: true}));
  assert.doesNotMatch(reduced.text(), /tp-motion-enter/);
  assert.match(reduced.text(), /<table>/, 'values and tables are present regardless of motion');
  const unknown = await run(undefined);
  assert.doesNotMatch(unknown.text(), /tp-motion-enter/);
  const css = read('static/css/talent-experience.css');
  assert.match(css, /\.tp-motion-enter \.tp-chart-round/);
  assert.match(css, /@media \(prefers-reduced-motion:reduce\)[^}]*\{[^}]*\.tp-motion-enter \*[^}]*animation:none!important/);
  assert.doesNotMatch(css.match(/\.tp-motion-enter[^{]*\{[^}]*\}/g).join(''), /opacity:0|visibility:hidden|animation-delay/, 'never hides values or delays usability');
});

// ---------------------------------------------------------------- F. comparisons
test('P7. Selected Comparisons is ONE bottom section: selector, constraint and results are colocated in DOM order', () => {
  const html = dashboard.analytics(payload(), new URLSearchParams('compare_by=grade'), null);
  const at = token => html.indexOf(token);
  const sections = [...html.matchAll(/data-analytics-section="([a-z]+)"/g)].map(m => m[1]);
  assert.equal(sections[sections.length - 1], 'compare', 'it is the last analytical section');
  const start = at('data-analytics-section="compare"');
  const controls = at('data-comparison-controls'), results = at('data-comparison-results'), count = at('data-comparison-count');
  assert.ok(start > 0 && controls > start && count > controls && results > count, 'controls, constraint, then results');
  assert.equal((html.match(/data-comparison-controls/g) || []).length, 1);
  const top = html.slice(0, start);
  assert.ok(!/name="compare_by"|name="compare_ids"/.test(top), 'no comparison selector left at the top');
  assert.match(html.slice(controls, results), /up to 6/);
  assert.match(html.slice(results), /Completion rate by group/);
  assert.match(html.slice(results), /Grade 3/);
});

test('P8. comparison states: empty, protected and the six-group limit stay explicit and value-free', () => {
  const empty = dashboard.analytics({...payload(), comparison: {groups: []}}, new URLSearchParams(), null);
  assert.match(empty, /data-comparison-state="empty"/);
  const html = dashboard.analytics(payload(), new URLSearchParams('compare_by=grade'), null);
  const group4 = html.split('<article class="tp-comparison-group"><h3>Grade 4</h3>')[1];
  assert.match(group4, /This summary is not available for this selection/);
  const many = {...payload(), options: {...payload().options, grade: Array.from({length: 8}, (_, i) => ({id: String(i), label: `G${i}`}))}};
  const limited = dashboard.analytics(many, new URLSearchParams('compare_by=grade&compare_ids=0,1,2,3,4,5'), null);
  assert.equal((limited.match(/name="compare_ids"[^>]*disabled/g) || []).length, 2, 'the seventh group cannot be ticked');
  assert.match(limited, /6 of 6 groups selected/);
});

// ---------------------------------------------------------------- E. filter UX
const dashUrl = url => url.includes('/dashboard?');
async function analyticsEnv(handler, extra = {}) {
  const env = createEnv({view: 'analytics', permissions: FULL, search: '?academic_year_id=1', globals: {TalentCharts: charts, TalentDashboard: dashboard}, handler, ...extra});
  await env.start();
  return env;
}
const slotOf = env => env.root.querySelector('[data-tp-slot="tp-dashboard-slot"]');
const changeEvent = (name, value) => ({target: {name, value, type: 'select-one', closest: selector => selector === '[data-dashboard-filters]' ? {querySelectorAll: () => []} : null}});
const dashCalls = env => env.calls.filter(c => dashUrl(String(c.url)));

test('P9. a filter change never submits, navigates or reloads the document; only history.replaceState and a background fetch', async () => {
  const env = await analyticsEnv(() => ({body: payload()}));
  const href = env.sandbox.location.href, reloadsBefore = env.reloads, replacedBefore = env.replaced.length;
  assert.equal(dashCalls(env).length, 1);
  env.root.emit('change', changeEvent('grade_level', '3'));
  await env.flush();
  assert.equal(dashCalls(env).length, 2, 'one background request');
  assert.match(String(dashCalls(env)[1].url), /grade_level=3/);
  assert.equal(env.sandbox.location.href, href, 'no location assignment');
  assert.equal(env.reloads, reloadsBefore, 'no reload');
  assert.ok(env.replaced.length > replacedBefore && /grade_level=3/.test(env.replaced.at(-1)[2]), 'URL state mirrored with replaceState');
  let prevented = false;
  env.root.emit('submit', {target: {matches: selector => selector === '[data-dashboard-filters]'}, preventDefault() { prevented = true; }});
  assert.ok(prevented, 'the form submit is cancelled');
  const source = read('static/js/talent.js');
  const body = source.slice(source.indexOf('async function refreshDashboard()'), source.indexOf('function programCards'));
  assert.ok(body.length > 200);
  assert.doesNotMatch(body, /location\.(href|assign|replace|reload)|window\.open|scrollIntoView|root\.innerHTML\s*=/);
});

test('P10. scroll position and container height are preserved across a filter refresh; the old analysis stays until the new one is ready', async () => {
  let held = null, requests = 0;
  const env = await analyticsEnv(url => dashUrl(url) ? (++requests > 1 ? {defer: true, body: payload(222)} : {body: payload(111)}) : {body: {}});
  const slot = slotOf(env);
  slot.offsetHeight = 2400; env.sandbox.scrollY = 900;
  // Model the browser clamping scroll when the region collapses below the reader.
  env.onWrite = (element) => { if (element === slot && !element.style.minHeight) env.sandbox.scrollY = Math.min(env.sandbox.scrollY, 120); };
  env.root.emit('change', changeEvent('grade_level', '3'));
  await env.flush();
  held = slot.style.minHeight;
  assert.equal(held, '2400px', 'the region keeps its height while refreshing');
  assert.equal(slot.getAttribute('aria-busy'), 'true', 'busy is announced on the affected region only');
  assert.equal(env.busy(), 'false', 'the page root is not put into a loading state');
  assert.match(env.text(), /tp-stat-value">111/, 'the previous analysis stays on screen');
  dashCalls(env).at(-1).settle();
  await env.flush();
  assert.match(env.text(), /tp-stat-value">222/);
  assert.equal(env.sandbox.scrollY, 900, 'scroll position is preserved');
  assert.deepEqual(env.scrollCalls, [], 'no scrollTo, scrollBy or scrollIntoView was needed or called');
  assert.equal(slot.style.minHeight, '', 'the height hold is released');
  assert.equal(slot.getAttribute('aria-busy'), null);
});

test('P11. if the browser clamps the scroll anyway, the reader position is restored', async () => {
  const env = await analyticsEnv(() => ({body: payload()}));
  const slot = slotOf(env);
  env.sandbox.scrollY = 700;
  env.onWrite = element => { if (element === slot) env.sandbox.scrollY = 50; };
  env.root.emit('change', changeEvent('program_id', '5'));
  await env.flush();
  assert.equal(env.sandbox.scrollY, 700);
  assert.deepEqual(env.scrollCalls, [['scrollTo', 0, 700]]);
});

test('P12. keyboard focus returns to the same control and the layout anchor is compensated without jumping to the top', async () => {
  const env = await analyticsEnv(() => ({body: payload()}));
  const focusCalls = [];
  const target = {name: 'compare_ids', value: '3', focus: options => focusCalls.push(options), getBoundingClientRect: () => ({top: 430})};
  env.sandbox.document.activeElement = {name: 'compare_ids', value: '3', type: 'checkbox', getBoundingClientRect: () => ({top: 400})};
  env.root.querySelectorAll = selector => selector === '[name="compare_ids"]' ? [{name: 'compare_ids', value: '9', focus() { throw new Error('wrong control'); }}, target] : [];
  env.root.emit('change', {target: {name: 'compare_ids', value: '3', type: 'checkbox', closest: () => ({querySelectorAll: () => [{value: '3'}]})}});
  await env.tick(400);
  assert.deepEqual(JSON.parse(JSON.stringify(focusCalls)), [{preventScroll: true}]);
  assert.deepEqual(env.scrollCalls, [['scrollBy', 0, 30]], 'only a relative compensation, never a jump to the top');
});

test('P13. a stale response can never overwrite a newer selection (out-of-order resolution)', async () => {
  let requests = 0;
  const env = await analyticsEnv(url => dashUrl(url) ? (++requests > 1 ? {defer: true, body: payload(/grade_level=3/.test(url) ? 333 : 444)} : {body: payload(1)}) : {body: {}});
  env.root.emit('change', changeEvent('grade_level', '3'));
  await env.flush();
  env.root.emit('change', changeEvent('grade_level', '4'));
  await env.flush();
  const [, first, second] = dashCalls(env);
  assert.match(String(first.url), /grade_level=3/);
  assert.match(String(second.url), /grade_level=4/);
  assert.equal(first.signal.aborted, true, 'the superseded request is cancelled');
  second.settle(); await env.flush();
  first.settle(); await env.flush();
  assert.match(env.text(), /tp-stat-value">444/, 'the newest selection is shown');
  assert.doesNotMatch(env.text(), /tp-stat-value">333/);
  assert.equal(slotOf(env).getAttribute('aria-busy'), null);
});

test('P14. chart-type change is purely client-side: no fetch, no URL change', async () => {
  const env = await analyticsEnv(() => ({body: payload()}));
  const fetchesBefore = env.calls.length, replacedBefore = env.replaced.length;
  const rows = charts.sanitize(classification);
  const host = {dataset: {chartFamily: 'classification', chartKey: 'k'}, visual: {innerHTML: ''}, querySelector: () => host.visual,
    querySelectorAll: selector => selector === '[data-chart-row]' ? rows.map(r => ({dataset: {state: r.state}, children: [{textContent: r.label}, {textContent: String(r.count)}, {textContent: `${r.percentage}%`}]})) : []};
  const button = {dataset: {chartMode: 'doughnut'}, closest: () => host, setAttribute() {}};
  env.root.emit('click', {target: {closest: selector => selector === '[data-chart-mode]' ? button : null}});
  await env.flush();
  assert.match(host.visual.innerHTML, /is-doughnut/);
  assert.equal(env.calls.length, fetchesBefore);
  assert.equal(env.replaced.length, replacedBefore);
});

test('P15. a failed refresh keeps the previous analysis, shows a retryable error in the region, and Retry recovers', async () => {
  let fail = false;
  const env = await analyticsEnv(url => dashUrl(url) ? (fail ? {status: 500, body: {code: 'x', detail: 'Traceback SELECT secret'}} : {body: payload(55)}) : {body: {}});
  fail = true;
  env.root.emit('change', changeEvent('grade_level', '3'));
  await env.flush();
  const banner = slotOf(env).querySelector('[data-dashboard-error]');
  assert.equal(banner.hidden, false);
  assert.match(banner.innerHTML, /data-dashboard-retry/);
  assert.doesNotMatch(banner.innerHTML, /Traceback|SELECT|secret/);
  assert.match(env.text(), /tp-stat-value">55/, 'previous content retained');
  assert.equal(slotOf(env).getAttribute('aria-busy'), null, 'no indefinite loader');
  fail = false;
  const before = dashCalls(env).length;
  env.root.emit('click', {target: {closest: selector => selector === '[data-dashboard-retry]' ? {} : null}});
  await env.flush();
  assert.equal(dashCalls(env).length, before + 1);
});

test('P16. a hung refresh ends in the bounded timeout error, never an endless loader', async () => {
  let requests = 0;
  const env = await analyticsEnv(url => dashUrl(url) ? (++requests > 1 ? 'hang' : {body: payload(7)}) : {body: {}});
  env.root.emit('change', changeEvent('grade_level', '3'));
  await env.flush();
  assert.equal(slotOf(env).getAttribute('aria-busy'), 'true');
  await env.tick(26000);
  assert.equal(slotOf(env).getAttribute('aria-busy'), null);
  assert.match(slotOf(env).querySelector('[data-dashboard-error]').innerHTML, /Taking longer than expected/);
});

test('P17. ticking several comparison groups collapses into one request; the seventh is refused', async () => {
  const env = await analyticsEnv(() => ({body: payload()}));
  const many = n => ({target: {name: 'compare_ids', value: String(n), type: 'checkbox', checked: true, closest: () => ({querySelectorAll: () => Array.from({length: n}, (_, i) => ({value: String(i)}))})}});
  env.root.emit('change', many(1)); env.root.emit('change', many(2)); env.root.emit('change', many(3));
  await env.tick(400);
  assert.equal(dashCalls(env).length, 2);
  const seventh = many(7);
  env.root.emit('change', seventh);
  assert.equal(seventh.target.checked, false);
  assert.match(env.status.textContent, /up to six/);
});

test('P18. rendering code never scrolls, navigates or replaces the page root on a filter change', () => {
  for (const file of ['static/js/talent-dashboard.js', 'static/js/talent-charts.js']) assert.doesNotMatch(read(file), /scrollIntoView|scrollTo|location\.(href|assign|replace)/, file);
  const source = read('static/js/talent.js');
  assert.doesNotMatch(source, /scrollIntoView/);
  assert.doesNotMatch(source, /root\.innerHTML=sectionLoadingHtml\('filtered analysis'\)/, 'the old collapse-to-loader replacement is gone');
  assert.match(source, /new AbortController\(\)/);
  assert.match(source, /dashToken/);
});

// ---------------------------------------------------------------- G. Progress Over Time
const point = (id, label, cell, extra = {}) => ({evaluation_period: {id, sequence: id, label, status: 'active'}, metric_result: cell, ...extra});
test('P19. Progress Over Time is kept as a real per-Program longitudinal trend with honest gaps', async () => {
  const data = {metric: 'completion_coverage', program: {name: 'Math'}, academic_year: {label: '2026-2027'}, comparisons: [], points: [
    point(1, 'Autumn', {state: 'visible', percentage: 25, numerator: 1, denominator: 4}),
    point(2, 'Winter', {state: 'suppressed', percentage: 97, numerator: 97, denominator: 100}),
    point(3, 'Spring', {state: 'visible', percentage: 50, numerator: 2, denominator: 4}),
    point(4, 'Summer', {state: 'no_data'}, {no_data_reason: 'no_frozen_population'}),
  ]};
  const env = createEnv({view: 'longitudinal', permissions: {'talent_analytics.view': true}, search: '?academic_year_id=1&program_id=5', globals: {TalentCharts: charts},
    handler: url => url.includes('/longitudinal') ? {body: data} : {body: []}});
  await env.start();
  const html = env.text();
  assert.match(html, /data-chart-family="series"/);
  assert.match(html, /data-chart-mode="trend"[^>]*aria-pressed="true"/, 'Trend is the default for a series');
  assert.match(html, /data-chart-mode="bar"/);
  assert.doesNotMatch(html, /doughnut|97/, 'no circular type and no suppressed magnitude');
  assert.equal((html.match(/tp-trend-gap/g) || []).length, 2, 'the suppressed and the not-yet-available periods are gaps');
  const svg = html.match(/<svg class="tp-trend"[\s\S]*?<\/svg>/)[0];
  assert.equal((svg.match(/<circle /g) || []).length, 2, 'only visible points get a marker');
  assert.match(html, /Summer: No data yet/, 'a period without a Student result is not 0%');
  assert.match(html, /Winter: Unavailable/);
  assert.doesNotMatch(html, /Summer: 0/);
  assert.match(html, /<caption>Assessment completion by Evaluation Period/);
  assert.equal(env.callsTo('/longitudinal').length, 1, 'reuses the existing authorized read API');
});

test('P20. Progress Over Time count metrics plot counts, never a percentage, and one visible point offers no trend', () => {
  const html = charts.series('Program participations by Evaluation Period', [
    {label: 'A', state: 'visible', count: 12}, {label: 'B', state: 'visible', count: 20}]);
  assert.match(html, /data-chart-mode="trend"/);
  assert.match(html, /<li>A: 12<\/li>/);
  assert.match(charts.series('P', [{label: 'A', state: 'visible', count: 12}, {label: 'B', state: 'visible', count: 20}], {mode: 'bar'}), /<strong>12<\/strong>/);
  assert.doesNotMatch(html, /%/);
  const one = charts.series('X', [{label: 'A', state: 'visible', count: 12}, {label: 'B', state: 'suppressed', count: 5}]);
  assert.ok(!one.includes('data-chart-mode') && !/>5</.test(one));
});

test('P21. the decision is real: nav still lists Progress Over Time, the route stays, and Results links to it for a chosen Program', () => {
  assert.match(read('templates/talent/workspace.html'), /'longitudinal'\]/);
  assert.match(read('routers/talent_ui.py'), /"longitudinal":\s*\("Progress Over Time", "talent_analytics.view"\)/);
  const html = dashboard.analytics(payload(), new URLSearchParams('academic_year_id=1&program_id=5&branch_id=6'), null);
  assert.match(html, /href="\/talent\/longitudinal\?academic_year_id=1&amp;program_id=5&amp;branch_id=6"/);
  assert.doesNotMatch(dashboard.analytics(payload(), new URLSearchParams(), null), /Open Progress Over Time/);
});

// ---------------------------------------------------------------- I. cleanup
test('P22. shared inline SVG chevrons replace raw arrow glyphs in actions', () => {
  for (const file of ['static/js/talent.js', 'static/js/talent-dashboard.js']) assert.doesNotMatch(read(file), /→|&rarr;/, file);
  assert.match(read('static/js/talent.js'), /tp-chevron/);
});
