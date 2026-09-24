'use strict';
/* Deployment Acceptance Correction A: Talent & Potential runtime loading
 * reliability. These tests run the real static/js/talent.js against a DOM stub
 * (see talent_runtime_harness.cjs) - structural verification, not a browser. */
const {test} = require('node:test');
const assert = require('node:assert/strict');
const {createEnv, response} = require('./talent_runtime_harness.cjs');

const LOADER = 'Loading your authorized workspace';
const ALL_VIEWS = ['overview', 'programs', 'evaluation-plans', 'assessments', 'reviews', 'learner-profile',
  'analytics', 'talent-map', 'portfolio', 'branch', 'overlap', 'students', 'longitudinal'];
const FULL = {
  'talent_analytics.view': true, 'talent_analytics.view_students': true, 'talent_programs.view': false,
  'students.view': true, 'talent_review_candidates.view': true, 'talent_assessments.view': true,
};

const mapBody = {metric: 'completion_coverage', columns: [], rows: [], cells: [], row_totals: [], column_totals: [], organization_total: null};
const overviewBody = {metrics: {completion_coverage: {state: 'visible', percentage: 50, numerator: 1, denominator: 2}, programs_configured: {state: 'visible', value: 3}}};
const distribution = {distribution: {state: 'visible', buckets: [{label: 'Visual', state: 'visible', count: 1, percentage: 100}]}};

// Default scripted API: every analytics endpoint succeeds with a minimal valid payload.
function okHandler(overrides = {}) {
  return (url, init, call) => {
    for (const [fragment, outcome] of Object.entries(overrides)) {
      if (url.includes(fragment)) return typeof outcome === 'function' ? outcome(url, init, call) : outcome;
    }
    if (url.includes('organization-analytics/overview')) return {body: overviewBody};
    if (url.includes('talent-map')) return {body: mapBody};
    if (url.includes('program-portfolio')) return {body: {programs: [], totals: {}}};
    if (url.includes('rubric-distribution')) return {body: {distributions: [], program_result_summary: {state: 'no_data'}}};
    if (url.includes('/longitudinal')) return {body: {points: [], comparisons: [], metric: 'completion_coverage', program: {name: 'P'}, academic_year: {label: 'Y'}}};
    if (url.includes('/students?')) return {body: {items: []}};
    if (url.includes('branch-comparison')) return {body: {metric: 'current_overall_progress', rows: []}};
    if (url.includes('learning-style')) return {body: distribution};
    if (url.includes('/classification')) return {body: distribution};
    if (url.includes('/talented')) return {body: {organization: {distribution: {state: 'visible'}, summary: {talented_count: 1, applicable_denominator: 2, talented_rate_percentage: 50}}, branch_breakdown: [], not_currently_classifiable_count: 0}};
    return {body: []};
  };
}

const ANALYTICS_SEARCH = '?program_id=5&academic_year_id=1';

test('1. successful bootstrap replaces the server-rendered loader and clears aria-busy', async () => {
  const env = await createEnv({view: 'overview', permissions: FULL, handler: okHandler()}).start();
  assert.doesNotMatch(env.text(), new RegExp(LOADER));
  assert.match(env.text(), /Where Talent &amp; Potential stands right now/);
  assert.equal(env.busy(), 'false');
  assert.equal(env.status.textContent, 'View loaded.');
});

test('1b. the placeholder is replaced deterministically even while every request hangs', async () => {
  const env = await createEnv({view: 'portfolio', permissions: FULL, handler: () => 'hang'}).start();
  assert.doesNotMatch(env.text(), new RegExp(LOADER));
  assert.match(env.text(), /Loading this view/);
  assert.equal(env.busy(), 'true');
});

test('2. a synchronous init exception cannot leave permanent loading; Retry re-boots', async () => {
  const env = createEnv({view: 'analytics', permissions: FULL, search: ANALYTICS_SEARCH, handler: okHandler(), breakInit: true});
  await env.start();
  assert.doesNotMatch(env.text(), new RegExp(LOADER));
  assert.match(env.text(), /Unable to load view/);
  assert.match(env.text(), /id="tp-retry"/);
  // Raw exception text must never reach the user.
  assert.doesNotMatch(env.text(), /Cannot read|TypeError|undefined|null/);
  assert.equal(env.busy(), 'false');
  assert.equal(env.status.textContent, 'View could not be loaded.');
  // Repair the missing node and retry: boot runs again and the view renders.
  env.elements['tp-metric-field'] = env.elements['tp-program-field'];
  env.root.querySelector('#tp-retry').emit('click');
  await env.flush();
  assert.match(env.text(), /Results &amp; Analytics|Results & Analytics/);
  assert.equal(env.busy(), 'false');
});

test('3. a rejected essential request ends in an explicit error state with Retry, never the loader', async () => {
  const env = await createEnv({view: 'portfolio', permissions: FULL, handler: okHandler({'program-portfolio': new TypeError('Failed to fetch')})}).start();
  assert.doesNotMatch(env.text(), new RegExp(LOADER));
  assert.doesNotMatch(env.text(), /Loading this view/);
  assert.match(env.text(), /Unable to load view/);
  assert.match(env.text(), /This section could not finish loading\./);
  assert.doesNotMatch(env.text(), /Failed to fetch/);
  assert.match(env.text(), /<button type="button" id="tp-retry">Retry<\/button>/);
  assert.equal(env.busy(), 'false');
});

test('4. a request timeout cannot leave permanent loading and offers a retryable state', async () => {
  const env = await createEnv({view: 'portfolio', permissions: FULL, handler: okHandler({'program-portfolio': 'hang'})}).start();
  assert.equal(env.busy(), 'true');
  await env.tick(24999);
  assert.equal(env.busy(), 'true', 'still within the 25 s bound');
  await env.tick(2);
  assert.equal(env.busy(), 'false');
  assert.match(env.text(), /Taking longer than expected/);
  assert.match(env.text(), /id="tp-retry"/);
  assert.doesNotMatch(env.text(), /Loading this view/);
  assert.ok(env.callsTo('program-portfolio')[0].signal.aborted, 'the timed-out request is aborted');
});

test('5. an aborted stale response never replaces newer content, and busy tracks the current generation', async () => {
  let first = true;
  const env = createEnv({view: 'portfolio', permissions: FULL, handler: (url, init, call) => {
    if (url.includes('program-portfolio')) {
      if (first) { first = false; return {defer: true, body: {programs: [{program: {id: 1, name: 'OLD-CONTEXT', status: 'active'}, metrics: {}}], totals: {}}}; }
      return {body: {programs: [{program: {id: 2, name: 'NEW-CONTEXT', status: 'active'}, metrics: {}}], totals: {}}};
    }
    return okHandler()(url, init, call);
  }});
  await env.start();
  const stale = env.callsTo('program-portfolio')[0];
  env.elements['tp-filters'].emit('submit');     // a new context supersedes the first load
  await env.flush();
  assert.ok(stale.signal.aborted, 'the obsolete request is aborted');
  assert.match(env.text(), /NEW-CONTEXT/);
  stale.settle();                                   // the old response now arrives late
  await env.flush();
  assert.match(env.text(), /NEW-CONTEXT/);
  assert.doesNotMatch(env.text(), /OLD-CONTEXT/);
  assert.equal(env.busy(), 'false');
});

test('6/7/8. Organization landing: primary content renders when organization analytics fails, with a LOCAL retryable failure', async () => {
  const env = await createEnv({view: 'overview', permissions: FULL, handler: okHandler({'organization-analytics/overview': {status: 500, body: {detail: 'x'}}})}).start();
  const text = env.text();
  assert.match(text, /Where Talent &amp; Potential stands right now/);
  assert.match(text, /tp-overview-actions/);
  assert.match(text, /tp-section-error/);
  assert.match(text, /data-tp-section-retry="tp-hero-stats"/);
  assert.doesNotMatch(text, /Loading headline figures|Unable to load view/);
  assert.equal(env.busy(), 'false');
  assert.equal(env.status.textContent, 'View loaded. Some sections could not be loaded.');
});

test('7b. a hanging organization analytics request times out locally while the page stays usable', async () => {
  const env = await createEnv({view: 'overview', permissions: FULL, handler: okHandler({'organization-analytics/overview': 'hang'})}).start();
  assert.match(env.text(), /tp-overview-actions/);
  assert.match(env.text(), /Loading headline figures/);
  assert.equal(env.busy(), 'true');
  await env.tick(25001);
  assert.match(env.text(), /Taking longer than expected/);
  assert.match(env.text(), /tp-overview-actions/);
  assert.equal(env.busy(), 'false');
});

test('9/13. Results & Analytics: one secondary failure never erases or blocks the others, and no request is duplicated', async () => {
  const env = await createEnv({view: 'analytics', permissions: FULL, search: ANALYTICS_SEARCH, handler: okHandler({
    'learning-style': {status: 503, body: {detail: 'privacy configuration incomplete'}},
    'program_grade': 'hang',
  })}).start();
  const text = env.text();
  // failed section: local error; hung section: still its own skeleton
  assert.match(text, /data-tp-section-retry="tp-learning-style-slot"/);
  assert.match(text, /Loading grade results/);
  // unrelated sections rendered from their own successful requests
  assert.match(text, /Classification Distribution/);
  assert.match(text, /Talented \(Exceptional\) Students/);
  assert.match(text, /Organization snapshot/);
  assert.match(text, /Branch comparison/);
  assert.equal(env.busy(), 'true', 'the hung grade section is still pending within its bound');
  await env.tick(25001);
  assert.match(env.text(), /Taking longer than expected/);
  assert.equal(env.busy(), 'false');
  const urls = env.calls.map(call => call.url);
  assert.equal(new Set(urls).size, urls.length, `duplicate identical requests: ${urls}`);
});

test('9b. Results & Analytics: a failing snapshot request does not erase Classification / Talent sections', async () => {
  const env = await createEnv({view: 'analytics', permissions: FULL, search: ANALYTICS_SEARCH, handler: okHandler({'organization-analytics/overview': {status: 500, body: {}}})}).start();
  assert.match(env.text(), /data-tp-section-retry="tp-snapshot-slot"/);
  assert.match(env.text(), /Classification Distribution/);
  assert.match(env.text(), /Learning Style Distribution/);
  assert.equal(env.busy(), 'false');
});

test('12. section Retry performs a fresh bounded request for that section only', async () => {
  let failing = true;
  const env = await createEnv({view: 'analytics', permissions: FULL, search: ANALYTICS_SEARCH, handler: okHandler({
    'learning-style': () => failing ? {status: 500, body: {}} : {body: distribution},
  })}).start();
  assert.equal(env.callsTo('learning-style').length, 1);
  const totalBefore = env.calls.length;
  failing = false;
  env.root.emit('click', {target: {closest: () => ({getAttribute: () => 'tp-learning-style-slot'})}});
  await env.flush();
  assert.equal(env.callsTo('learning-style').length, 2, 'a fresh request is issued');
  assert.equal(env.calls.length, totalBefore + 1, 'no other section is re-requested');
  assert.match(env.text(), /Learning Style Distribution/);
  assert.doesNotMatch(env.text(), /data-tp-section-retry="tp-learning-style-slot"/);
  assert.equal(env.status.textContent, 'View loaded.');
});

test('12b. page-level Retry performs a fresh request', async () => {
  let failing = true;
  const env = await createEnv({view: 'portfolio', permissions: FULL, handler: okHandler({'program-portfolio': () => failing ? new TypeError('Failed to fetch') : {body: {programs: [], totals: {}}}})}).start();
  assert.equal(env.callsTo('program-portfolio').length, 1);
  failing = false;
  env.root.querySelector('#tp-retry').emit('click');
  await env.flush();
  assert.equal(env.callsTo('program-portfolio').length, 2);
  assert.doesNotMatch(env.text(), /Unable to load view/);
  assert.equal(env.busy(), 'false');
});

test('10. Talent Review: a failed workspace request renders an explicit error state, never the loader', async () => {
  const globals = {TalentOperations: {render: async ctx => { await ctx.api('/api/talent/review-candidates/workspace?'); }}};
  const env = await createEnv({view: 'reviews', permissions: FULL, globals, handler: okHandler({'review-candidates/workspace': {status: 500, body: {detail: 'boom'}}})}).start();
  assert.doesNotMatch(env.text(), new RegExp(LOADER));
  assert.match(env.text(), /Unable to load view/);
  assert.match(env.text(), /id="tp-retry"/);
  assert.equal(env.busy(), 'false');
});

test('10b. Talent Review: a hanging workspace request times out into a retryable state', async () => {
  const globals = {TalentOperations: {render: async ctx => { await ctx.api('/api/talent/review-candidates/workspace?'); }}};
  const env = await createEnv({view: 'reviews', permissions: FULL, globals, handler: okHandler({'review-candidates/workspace': 'hang'})}).start();
  await env.tick(25001);
  assert.match(env.text(), /Taking longer than expected/);
  assert.equal(env.busy(), 'false');
});

test('10c. a missing operational delegate global yields a safe reload state, not the loader or a raw TypeError', async () => {
  for (const view of ['assessments', 'reviews', 'programs', 'evaluation-plans']) {
    const env = await createEnv({view, permissions: FULL, handler: okHandler()}).start();
    assert.doesNotMatch(env.text(), new RegExp(LOADER), view);
    assert.match(env.text(), /A required page component did not load/, view);
    assert.doesNotMatch(env.text(), /Cannot read|is not a function|undefined/, view);
    assert.equal(env.busy(), 'false', view);
    env.root.querySelector('#tp-retry').emit('click');
    assert.equal(env.reloads, 1, `${view}: Retry reloads the page when a script is missing`);
  }
});

test('11. Program/Branch/Grade context lookups that fail or hang cannot strand the page', async () => {
  const env = await createEnv({view: 'talent-map', permissions: {...FULL, 'talent_programs.view': true}, handler: okHandler({
    'planning-branches': new TypeError('Failed to fetch'),
    'planning-grades': 'hang',
    'api/talent/programs': (url) => url.endsWith('/programs') ? 'hang' : {body: []},
  })}).start();
  assert.equal(env.callsTo('talent-map').length, 0, 'still waiting on the bounded context lookups');
  await env.tick(15001);
  assert.equal(env.callsTo('talent-map').length, 1, 'the data load starts once the lookups are bounded');
  assert.doesNotMatch(env.text(), new RegExp(LOADER));
  assert.equal(env.busy(), 'false');
  assert.match(env.text(), /Talent Map/);
});

test('11b. the boot never waits longer than the 20 s context deadline for selector lookups', async () => {
  // Chain several hanging lookups so the sum would exceed 20 s without the deadline.
  const env = await createEnv({view: 'reviews', permissions: {...FULL, 'talent_programs.view': true}, globals: {TalentOperations: {render: async ctx => { ctx.root.innerHTML = '<p>OPERATIONS-RENDERED</p>'; }}}, handler: okHandler({
    'planning-branches': 'hang', 'planning-grades': 'hang', 'planning-sections': 'hang', 'api/talent/programs': 'hang',
  })}).start();
  await env.tick(15001);
  await env.tick(5000);
  assert.match(env.text(), /OPERATIONS-RENDERED/);
  assert.equal(env.busy(), 'false');
});

test('6b/14. filter changes debounce into one reload and abort the obsolete request', async () => {
  const env = await createEnv({view: 'portfolio', permissions: FULL, handler: okHandler()}).start();
  const before = env.callsTo('program-portfolio').length;
  const select = env.elements['tp-year'];
  env.elements['tp-filters'].emit('change', {target: select});
  env.elements['tp-filters'].emit('change', {target: select});
  await env.tick(200);
  assert.equal(env.callsTo('program-portfolio').length, before, 'debounced: nothing fired yet');
  await env.tick(100);
  assert.equal(env.callsTo('program-portfolio').length, before + 1, 'two rapid changes collapse into one load');
  assert.equal(env.busy(), 'false');
});

test('15. script bootstrap does not depend on optional globals: every view boots with no Talent globals present', async () => {
  for (const view of ALL_VIEWS) {
    const env = await createEnv({view, permissions: FULL, search: ANALYTICS_SEARCH, handler: () => 'hang'}).start();
    assert.doesNotMatch(env.text(), new RegExp(LOADER), `${view} still shows the server-rendered loader`);
    // The four operational views legitimately need their delegate module; when it is
    // absent they must show the explicit reload state (covered by test 10c) - every
    // other view must boot and render with no optional Talent global present at all.
    if (!['programs', 'evaluation-plans', 'assessments', 'reviews'].includes(view)) {
      assert.doesNotMatch(env.text(), /Unable to load view/, `${view} failed to boot without optional globals`);
    }
  }
});

test('16. every terminal state leaves aria-busy false and status set (no permanent busy)', async () => {
  const scenarios = [
    ['portfolio', okHandler()],
    ['portfolio', okHandler({'program-portfolio': {status: 403, body: {detail: 'nope'}}})],
    ['portfolio', okHandler({'program-portfolio': new TypeError('offline')})],
    ['overview', okHandler({'organization-analytics/overview': {status: 500, body: {}}})],
    ['analytics', okHandler({'talent-map': {status: 500, body: {}}})],
  ];
  for (const [view, handler] of scenarios) {
    const env = await createEnv({view, permissions: FULL, search: ANALYTICS_SEARCH, handler}).start();
    assert.equal(env.busy(), 'false', `${view}`);
    assert.ok(env.status.textContent.length > 0);
    assert.notEqual(env.status.textContent, 'Refreshing view…');
  }
});

test('17. permission-denied section errors show no Retry (retrying cannot help) and expose no internals', async () => {
  const env = await createEnv({view: 'analytics', permissions: FULL, search: ANALYTICS_SEARCH, handler: okHandler({'learning-style': {status: 403, body: {detail: 'Not permitted for this scope.'}}})}).start();
  assert.match(env.text(), /Not permitted for this scope\./);
  assert.doesNotMatch(env.text(), /data-tp-section-retry="tp-learning-style-slot"/);
});

// talent-experience.js owns the Program-filtered rubric section on Results & Analytics.
test('18. the rubric section request is bounded and its failure state is concise with a Retry button', async () => {
  const experience = require('../static/js/talent-experience.js');
  const realFetch = global.fetch;
  try {
    global.fetch = () => new Promise(() => {});           // never settles, ignores abort
    await assert.rejects(experience.fetchRubric(5, 1, undefined, 20), error => error.name === 'TimeoutError');
    const controller = new AbortController();
    const pending = experience.fetchRubric(5, 1, controller.signal, 0);
    controller.abort();
    await assert.rejects(pending, error => error.name === 'AbortError');
    global.fetch = async () => response(500, {detail: 'A safe backend message.'});
    await assert.rejects(experience.fetchRubric(5, 1, undefined, 1000), error => error.userSafe === true && /safe backend message/.test(error.message));
  } finally { global.fetch = realFetch; }
  const timeoutHtml = experience.rubricErrorHtml('Reading', {name: 'TimeoutError'});
  assert.match(timeoutHtml, /could not finish loading/);
  assert.match(timeoutHtml, /<button type="button" data-tp-rubric-retry>Retry<\/button>/);
  const leakHtml = experience.rubricErrorHtml('Reading', new TypeError('Cannot read properties of undefined'));
  assert.doesNotMatch(leakHtml, /Cannot read|TypeError|undefined/);
});

test('19. pure lifecycle helpers: bounded request settles on timeout even when fetch ignores abort; messages never leak internals', async () => {
  const {boundedRequest, safeMessage, sectionErrorHtml, errorPanel} = require('../static/js/talent.js');
  await assert.rejects(boundedRequest(() => new Promise(() => {}), '/x', {}, undefined, async () => 1, 15), error => error.code === 'timeout' && error.userSafe === true);
  const controller = new AbortController();
  const pending = boundedRequest(() => new Promise(() => {}), '/x', {}, controller.signal, async () => 1, 0);
  controller.abort();
  await assert.rejects(pending, error => error.name === 'AbortError');
  assert.equal(safeMessage(new TypeError('boom internals')), 'This section could not finish loading.');
  assert.equal(safeMessage({status: 403, message: 'Not permitted.'}), 'Not permitted.');
  assert.doesNotMatch(sectionErrorHtml('s', new Error('SELECT * FROM secret')), /SELECT|secret/);
  assert.doesNotMatch(errorPanel(new Error('/api/internal/endpoint failed')), /internal|endpoint/);
});
