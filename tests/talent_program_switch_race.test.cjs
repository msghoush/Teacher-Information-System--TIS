/* Production defect: rapid Program switching in System Configuration > Talent &
 * Potential could leave stale content on screen (the Evaluation Period panel kept
 * showing a previous Program while the header/sidebar already showed the new one)
 * and/or leave "Refreshing Program data…" / aria-busy stuck forever.
 *
 * Root cause traced to static/js/talent-program-workspace.js `render()`:
 * (1) its per-call generation number (`renderToken`) was captured only inside the
 *     non-cached fetch branch, so a `viaHash` (cache-hit) render never bumped it,
 *     and the embedded Evaluation Plan panel call at the end of the function ran
 *     completely unguarded by it - an earlier, still-in-flight Program's embedded
 *     schedule fetch could resolve and paint its own container after a newer
 *     Program had already been selected;
 * (2) the fetch chain had no try/catch, so a rejected request (network error, or
 *     a genuine failure) left `aria-busy`/"Refreshing Program data…" set forever
 *     with no recovery, and propagated as an unhandled promise rejection through
 *     every caller up to the click handler.
 *
 * Fix: one `token = ++renderToken` captured at the very top of every render()
 * call (cache hit or not); the embedded schedule call is now gated by it before
 * and after invocation; the fetch chain is wrapped in try/catch that - only when
 * still current - clears aria-busy and shows a retryable error instead of leaving
 * the stale "Refreshing…" text in place.
 */
const {test} = require('node:test');
const assert = require('node:assert/strict');
const {render} = require('../static/js/talent-program-workspace.js');

function deferred() {
  let resolve, reject;
  const promise = new Promise((res, rej) => { resolve = res; reject = rej; });
  return {promise, resolve, reject};
}

// Models real DOM `innerHTML` reparse semantics closely enough for this race:
// every real assignment to `root.innerHTML` creates a *brand new* child node
// tree, detaching whatever `<div data-embedded-schedule>` a still-in-flight
// earlier render() call had captured a reference to. A write into a detached
// node must never become visible; `visibleScheduleHtml()` reports only the
// content of whichever schedule container is currently attached, exactly
// what a person looking at the real page would see.
function makeRoot() {
  const attrs = {};
  const state = {html: '', scheduleEl: {innerHTML: '', attached: true}};
  const root = {
    get innerHTML() { return state.html; },
    set innerHTML(value) {
      state.html = value;
      state.scheduleEl.attached = false; // detach the previous embedded container
      state.scheduleEl = {innerHTML: '', attached: true};
    },
    dataset: {},
    setAttribute(name, value) { attrs[name] = value; },
    removeAttribute(name) { delete attrs[name]; },
    getAttribute(name) { return attrs[name] ?? null; },
    classList: {add() {}, remove() {}, toggle() {}},
    querySelector(selector) {
      if (selector === '[data-embedded-schedule]') return state.scheduleEl;
      if (selector === '[data-status]') return this._status || (this._status = {textContent: '', setAttribute(){}, getAttribute(){return null;}});
      // "already rendered" detection: pretend a wizard panel exists once we have
      // written real content, so a *second* render() onto the same root takes the
      // "Refreshing Program data…" path instead of the first-load path. Matched by
      // prefix (not an exact string) so this survives the selector list growing,
      // e.g. to also recognise the shell's own [data-tpc-program-loading] placeholder.
      if (selector.startsWith('.tp-wizard-panel,.tp-program-summary,[data-program-row]')) return state.html ? {} : null;
      return null;
    },
    querySelectorAll() { return []; },
    visibleScheduleHtml() { return state.scheduleEl.attached ? state.scheduleEl.innerHTML : ''; },
  };
  return root;
}

// Builds a ctx for `programId` targeting `root` (shared across A/B/C so the test
// reproduces the real production shape: talent-configuration.js always reuses the
// same `content` DOM node across a Program switch). Framework/Plan fetches resolve
// immediately; the *embedded schedule* call is driven by an externally-controlled
// deferred promise so tests can force exact interleavings between two Programs.
function makeCtx(programId, root, {scheduleDeferred, apiDelays = {}} = {}) {
  const scheduleCalls = [];
  const requests = [];
  const base = `/api/talent/programs/${programId}`;
  const framework = {id: 900 + Number(programId), status: 'active', in_use_by_assessments: false, revision: 1, semantic_fingerprint: 'fp', competencies: []};
  const config = {revision: 1, semantic_fingerprint: 'fp', levels: [], descriptors: [], rubric: null, kpi: null, review_candidate_policy: null};
  const api = async (path) => {
    requests.push(path);
    const delay = apiDelays[path];
    if (delay) await delay.promise;
    if (path === base) return {id: Number(programId), name: `Program ${programId}`, status: 'active'};
    if (path === '/api/talent/programs') return [{id: Number(programId), name: `Program ${programId}`, status: 'active'}];
    if (path.startsWith(`${base}/academic-years`)) return [];
    if (path.startsWith(`${base}/frameworks/`) && path.endsWith('/configuration')) return config;
    if (path.startsWith(`${base}/frameworks/`)) return framework;
    if (path === `${base}/frameworks`) return [framework];
    if (path === `${base}/competencies`) return [];
    if (path.startsWith('/api/talent/programs/planning-grades')) return [];
    if (path.startsWith('/api/talent/evaluation-plans')) return [];
    return [];
  };
  const ctx = {
    root, api, can: () => true, year: '2026', yearLabel: '2026-2027',
    hash: '#tp-schedule',
    params: new URLSearchParams({program_id: String(programId), academic_year_id: '2026'}),
    renderSchedule: async (embeddedCtx) => {
      scheduleCalls.push({programId: embeddedCtx.params.get('program_id'), root: embeddedCtx.root});
      if (scheduleDeferred) await scheduleDeferred.promise;
      embeddedCtx.root.innerHTML = `Evaluation Plan for Program ${embeddedCtx.params.get('program_id')}`;
    },
    notify() {},
  };
  return {ctx, root, scheduleCalls, requests};
}

test('A -> B switch: A cannot render its embedded Evaluation Plan content after B is selected', async () => {
  const root = makeRoot(); // ONE shared container, exactly like talent-configuration.js reuses `content`
  const slowA = deferred();
  const {ctx: ctxA, scheduleCalls: callsA} = makeCtx('11', root, {scheduleDeferred: slowA});
  const {ctx: ctxB, scheduleCalls: callsB} = makeCtx('27', root);

  const renderA = render(ctxA); // starts, but its embedded schedule call will hang on slowA
  await new Promise(r => setImmediate(r)); // let A progress up to (and start) its schedule call
  await render(ctxB); // switch to Program B - completes fully, including its own schedule call

  assert.equal(callsB.length, 1);
  assert.equal(callsB[0].programId, '27');
  assert.match(root.visibleScheduleHtml(), /Evaluation Plan for Program 27/);

  // Now let A's stalled request finally resolve.
  slowA.resolve();
  await renderA;

  // A's own embedded call started (it began before B superseded it), but its write
  // must never become visible once B has moved on: B's content stays the one shown.
  assert.equal(callsA.length, 1);
  assert.match(root.visibleScheduleHtml(), /Evaluation Plan for Program 27/);
  assert.doesNotMatch(root.visibleScheduleHtml(), /Program 11/);
});

test('rapid A -> B -> C: only C ends up rendered; A and B never leave visible content', async () => {
  const root = makeRoot();
  const slowA = deferred();
  const slowB = deferred();
  const {ctx: ctxA, scheduleCalls: callsA} = makeCtx('11', root, {scheduleDeferred: slowA});
  const {ctx: ctxB, scheduleCalls: callsB} = makeCtx('22', root, {scheduleDeferred: slowB});
  const {ctx: ctxC, scheduleCalls: callsC} = makeCtx('33', root);

  const renderA = render(ctxA);
  await new Promise(r => setImmediate(r));
  const renderB = render(ctxB);
  await new Promise(r => setImmediate(r));
  await render(ctxC);

  slowA.resolve();
  slowB.resolve();
  await Promise.all([renderA, renderB]);

  assert.equal(callsC.length, 1);
  assert.equal(callsC[0].programId, '33');
  assert.match(root.visibleScheduleHtml(), /Evaluation Plan for Program 33/);
  assert.doesNotMatch(root.visibleScheduleHtml(), /Program 11|Program 22/);
});

test('a stale response cannot overwrite a newer render even when it resolves after', async () => {
  const root = makeRoot();
  const slowA = deferred();
  const {ctx: ctxA} = makeCtx('44', root, {scheduleDeferred: slowA});
  const {ctx: ctxB} = makeCtx('55', root);

  const renderA = render(ctxA);
  await new Promise(r => setImmediate(r));
  await render(ctxB);
  const beforeResolve = root.innerHTML;

  slowA.resolve();
  await renderA;

  assert.equal(root.innerHTML, beforeResolve);
  assert.match(root.innerHTML, /Program 55/);
});

test('loading state (aria-busy) clears on success', async () => {
  const root = makeRoot();
  const {ctx} = makeCtx('66', root);
  await render(ctx);
  assert.equal(root.getAttribute('aria-busy'), null);
});

test('loading state (aria-busy) clears on failure instead of staying stuck, and render() never throws', async () => {
  const root = makeRoot();
  const failing = deferred();
  const {ctx} = makeCtx('77', root, {apiDelays: {'/api/talent/programs/77/frameworks': failing}});
  root.innerHTML = '<div class="tp-wizard-panel">Program 77 previously loaded</div>';
  const pending = render(ctx);
  await new Promise(r => setImmediate(r));
  assert.equal(root.getAttribute('aria-busy'), 'true');
  failing.reject(Object.assign(new Error('Network error.'), {userSafe: true}));
  await assert.doesNotReject(pending);
  assert.equal(root.getAttribute('aria-busy'), null);
  assert.match(root.querySelector('[data-status]').textContent, /Network error/);
});

test('Evaluation Period embedded content is requested for the exact selected Program, not a previous one', async () => {
  const root = makeRoot();
  const {ctx: ctxA} = makeCtx('88', root);
  await render(ctxA);
  const {ctx: ctxB, scheduleCalls} = makeCtx('99', root);
  await render(ctxB);
  assert.equal(scheduleCalls.length, 1);
  assert.equal(scheduleCalls[0].programId, '99');
});

test('switching Program does not accumulate window listeners', async () => {
  const listeners = {beforeunload: [], hashchange: []};
  const priorWindow = global.window;
  global.window = {
    location: {hash: '#tp-schedule'},
    addEventListener(type, fn) { if (listeners[type]) listeners[type].push(fn); },
    removeEventListener(type, fn) {
      if (listeners[type]) listeners[type] = listeners[type].filter(f => f !== fn);
    },
  };
  try {
    const root = makeRoot();
    const {ctx: ctxA} = makeCtx('111', root);
    await render(ctxA);
    const afterFirst = {beforeunload: listeners.beforeunload.length, hashchange: listeners.hashchange.length};
    const {ctx: ctxB} = makeCtx('112', root);
    await render(ctxB);
    assert.equal(listeners.beforeunload.length, afterFirst.beforeunload);
    assert.equal(listeners.hashchange.length, afterFirst.hashchange);
  } finally {
    global.window = priorWindow;
  }
});
