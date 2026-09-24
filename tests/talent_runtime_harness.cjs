'use strict';
/* Lightweight, jsdom-free runtime harness for static/js/talent.js.
 *
 * It executes the REAL browser script inside a vm context against a small DOM
 * stub, a scripted fetch, and a manual clock, so the request/render lifecycle
 * (boot, load, sections, timeouts, retry, stale responses) can be exercised
 * without a browser. It is structural verification only: it is not a real
 * browser and does not model layout, CSS, or full DOM semantics.
 */
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

// TALENT_JS_SOURCE lets a reviewer point the same tests at another revision of the script.
const SOURCE = process.env.TALENT_JS_SOURCE || path.join(__dirname, '..', 'static', 'js', 'talent.js');

class Element {
  constructor(id, env) {
    this.id = id; this.env = env; this.attrs = {}; this.listeners = {};
    this.hidden = false; this.value = ''; this.options = []; this.textContent = '';
    this.parentElement = {hidden: false}; this.selectedIndex = 0; this._html = ''; this.slots = new Map();
    this.classList = {add() {}, remove() {}, contains: () => false, toggle() {}};
    this.dataset = {}; this.isConnected = true; this._children = [];
  }
  set innerHTML(value) { this._html = String(value); this.slots = new Map(); this.retryButton = null; if (this.isSelect) this.parseOptions(); }
  get innerHTML() { return this._html; }
  get children() { return this._html ? [{}] : []; }
  parseOptions() {
    this.options = [...this._html.matchAll(/<option value="([^"]*)"[^>]*>([^<]*)/g)].map(match => ({value: match[1], textContent: match[2]}));
  }
  setAttribute(name, value) { this.attrs[name] = String(value); }
  getAttribute(name) { return name in this.attrs ? this.attrs[name] : null; }
  removeAttribute(name) { delete this.attrs[name]; }
  addEventListener(type, fn) { (this.listeners[type] ||= []).push(fn); }
  removeEventListener() {}
  replaceChildren() { this._html = ''; this.slots = new Map(); }
  append(child) { this._children.push(child); }
  closest() { return null; }
  querySelectorAll() { return []; }
  matches(selector) { return selector === 'select' && Boolean(this.isSelect); }
  emit(type, event = {}) { (this.listeners[type] || []).forEach(fn => fn({preventDefault() {}, ...event})); }
  // Serialized view: server markup with each independent slot replaced by the
  // content that section last wrote (or its loading skeleton).
  text() {
    let html = this._html;
    for (const [id, slot] of this.slots) {
      const pattern = new RegExp(`<div[^>]*data-tp-slot="${id}"[^>]*>[\\s\\S]*?</div>`);
      html = html.replace(pattern, slot.hidden ? '' : slot._html);
    }
    return html;
  }
  querySelector(selector) {
    const slot = selector.match(/^\[data-tp-slot="([^"]+)"\]$/);
    if (slot) {
      if (!new RegExp(`data-tp-slot="${slot[1]}"`).test(this._html)) return null;
      if (!this.slots.has(slot[1])) {
        const element = new Element(slot[1], this.env);
        const initial = this._html.match(new RegExp(`data-tp-slot="${slot[1]}"[^>]*>([\\s\\S]*?)</div>`));
        element._html = initial ? initial[1] : '';
        element.attrs['aria-busy'] = 'true';
        this.slots.set(slot[1], element);
      }
      return this.slots.get(slot[1]);
    }
    if (selector === '.tp-empty[data-initial-loading]') return /class="tp-empty"[^>]*data-initial-loading/.test(this._html) ? {} : null;
    if (selector === '#tp-retry') {
      if (!this.text().includes('id="tp-retry"')) return null;
      this.retryButton ||= new Element('tp-retry', this.env);
      return this.retryButton;
    }
    // talent-experience.js rubric section traversal (Results & Analytics).
    if (selector === '[data-tp-rubric-section]') return /data-tp-rubric-section/.test(this._html) ? this._rubricChild('[data-tp-rubric-section]') : null;
    if (selector === '.tp-error') return null;
    if (selector === '#tp-rubric-title') return null;
    if (selector === '#tp-rubric-program-filter') return this._rubricChild('#tp-rubric-program-filter');
    if (selector === '[data-tp-rubric-results]') return this._rubricChild('[data-tp-rubric-results]');
    if (selector === '[data-tp-rubric-retry]') return this._rubricChild('[data-tp-rubric-retry]');
    return null;
  }
  _rubricChild(selector) {
    if (!this._rubricChildren) this._rubricChildren = new Map();
    if (!this._rubricChildren.has(selector)) {
      const element = new Element('rubric' + selector.replace(/[^a-zA-Z0-9]/g, '-'), this.env);
      if (selector === '#tp-rubric-program-filter') element.isSelect = true;
      this._rubricChildren.set(selector, element);
    }
    return this._rubricChildren.get(selector);
  }
}

function createEnv({view = 'overview', permissions = {}, search = '', handler, source = SOURCE, globals = {}, breakInit = false} = {}) {
  const calls = [];
  const timers = [];
  let now = 0, timerSeq = 0;
  const elements = {};
  const env = {calls, elements, reloads: 0};
  const el = (id, extra = {}) => Object.assign(elements[id] = new Element(id, env), extra);
  el('tp-config').textContent = JSON.stringify({view, permissions, year: 1});
  el('tp-content'); elements['tp-content']._html = '<p class="tp-empty" data-initial-loading>Loading your authorized workspace…</p>';
  elements['tp-content'].attrs['aria-busy'] = 'true';
  el('tp-status'); el('tp-filters', {isSelect: false});
  el('tp-year', {isSelect: true, value: '1', options: [{value: '1', textContent: '2026-2027'}]});
  for (const name of ['program', 'branch', 'grade', 'section', 'metric', 'dimension', 'classification']) {
    el(`tp-${name}`, {isSelect: true, options: []});
    const field = el(`tp-${name}-field`, {hidden: name !== 'metric' || false});
    field.hidden = true;
    elements[`tp-${name}`].parentElement = field;
  }
  el('tp-breadcrumb-current');
  el('talent-workspace', {dataset: {view}});
  if (breakInit) delete elements['tp-metric-field'];

  const windowListeners = {};
  const sandbox = {
    console, URL, URLSearchParams, Intl, AbortController, Promise, Object, JSON, Number, String, Math, Map, Set, Array, Error, TypeError,
    location: {search, pathname: `/talent/${view}`, origin: 'http://tis.test', href: `http://tis.test/talent/${view}${search}`, reload() { env.reloads += 1; }},
    history: {replaceState() {}},
    document: {
      title: 'Overview · Talent & Potential | TIS',
      getElementById: id => elements[id] || null,
      querySelectorAll: () => [],
      addEventListener() {},
      readyState: 'complete',
      createElement: tag => new Element('created-' + tag + '-' + ((env.createdSeq = (env.createdSeq || 0) + 1)), env),
      body: {classList: {toggle() {}}},
    },
    setTimeout: (fn, ms) => { const id = ++timerSeq; timers.push({id, at: now + ms, fn}); return id; },
    clearTimeout: id => { const index = timers.findIndex(timer => timer.id === id); if (index >= 0) timers.splice(index, 1); },
    fetch: (url, init = {}) => {
      const call = {url, init, signal: init.signal};
      calls.push(call);
      return new Promise((resolve, reject) => {
        call.resolve = value => resolve(value); call.reject = reject;
        const outcome = handler ? handler(String(url), init, call) : undefined;
        if (outcome === 'hang') return;
        if (outcome instanceof Error) return reject(outcome);
        if (outcome && outcome.defer) { call.settle = () => resolve(response(outcome.status || 200, outcome.body)); return; }
        const status = outcome && outcome.status ? outcome.status : 200;
        resolve(response(status, outcome && 'body' in outcome ? outcome.body : {}));
      });
    },
    MutationObserver: class { constructor(callback) { env.mutationCallback = callback; } observe() {} disconnect() {} },
    ...globals,
  };
  sandbox.window = sandbox;
  sandbox.window.addEventListener = (type, fn) => { (windowListeners[type] ||= []).push(fn); };
  sandbox.window.removeEventListener = () => {};
  env.windowEmit = (type, event = {}) => (windowListeners[type] || []).forEach(fn => fn(event));
  env.root = elements['tp-content'];
  env.status = elements['tp-status'];
  env.text = () => env.root.text();
  env.busy = () => env.root.getAttribute('aria-busy');
  // Let promise continuations run (several turns: async chains are deep).
  env.flush = async () => { for (let i = 0; i < 40; i += 1) await new Promise(resolve => setImmediate(resolve)); };
  env.tick = async ms => {
    await env.flush();
    const target = now + ms;
    for (;;) {
      timers.sort((a, b) => a.at - b.at);
      const next = timers[0];
      if (!next || next.at > target) break;
      timers.shift(); now = next.at; next.fn();
      await env.flush();
    }
    now = target;
    await env.flush();
  };
  env.pendingTimers = () => timers.length;
  env.start = async () => {
    vm.createContext(sandbox);
    const script = (file, name) => vm.runInContext(fs.readFileSync(file, 'utf8'), sandbox, {filename: name});
    const js = file => path.join(__dirname, '..', 'static', 'js', file);
    // Production defer order: shared rubric visual, shared error mapper, shared
    // rubric-read ownership store, then talent.js, then talent-experience.js.
    script(js('talent-rubric-visual.js'), 'talent-rubric-visual.js');
    script(js('talent-api-errors.js'), 'talent-api-errors.js');
    script(js('talent-rubric-request.js'), 'talent-rubric-request.js');
    // Acceptance B: shared Student identity presentation is loaded on every view before talent.js.
    script(js('talent-student-identity.js'), 'talent-student-identity.js');
    script(source, 'talent.js');
    script(js('talent-experience.js'), 'talent-experience.js');
    await env.flush();
    return env;
  };
  // Simulates the MutationObserver fire that follows talent.js's DOM write, so
  // talent-experience.js's ensureRubricSection() runs against the rendered view.
  env.triggerMutation = async () => {
    if (env.mutationCallback) { env.mutationCallback(); await env.flush(); }
  };
  env.callsTo = fragment => calls.filter(call => String(call.url).includes(fragment));
  env.sandbox = sandbox;
  return env;
}

function response(status, body) {
  return {ok: status >= 200 && status < 300, status, redirected: false, headers: {get: () => 'application/json'}, json: async () => body};
}

module.exports = {createEnv, response, SOURCE};
