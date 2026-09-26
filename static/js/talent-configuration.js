/* System Configuration > Talent & Potential Configuration workspace shell.
 *
 * Organization-level Talent configuration is defined here and nowhere else in the UI.
 * This shell owns only layout and navigation (Programs list | selected Program |
 * detail drawer placeholder). Every editor is the existing, canonical
 * TalentProgramWorkspace / TalentEvaluationWorkspace, and every read and mutation
 * goes through the existing /api/talent/* routes, which keep enforcing their
 * semantic permission AND organization/global access scope. UI visibility never
 * replaces those gates. No data is invented: an empty organization shows empty states.
 */
(() => {
  'use strict';
  const esc = v => String(v ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  const logoBadge = (program, size) => (typeof window !== 'undefined' && window.TalentProgramIdentity)
    ? window.TalentProgramIdentity.logoBadge(program, size)
    : `<span class="tp-logo-badge ${size}"><span class="tp-logo-initials" aria-hidden="true">${esc(String(program.name || '?').slice(0, 2).toUpperCase())}</span></span>`;

  const TABS = ['programs', 'evaluation-periods'];
  // Center sub-tabs map onto the existing editor steps of TalentProgramWorkspace
  // (its hash-driven steps), so no editor capability is lost or duplicated.
  const SUBTABS = [
    {key: 'setup', label: 'Program Setup', hash: '#tp-basics'},
    {key: 'rubric', label: 'Rubric & Competencies', hash: '#tp-rubric'},
    {key: 'periods', label: 'Evaluation Periods', hash: '#tp-schedule'},
    {key: 'criteria', label: 'Criteria / KPI', hash: '#tp-builder'},
  ];
  const STATUS_LABELS = {draft: 'Draft', active: 'Active', retired: 'Retired'};

  // Shared Grades label ("Grades 1 - 3") - same helper the operational Programs view uses.
  const gradesSummary = levels => (typeof module !== 'undefined' && module.exports
    ? require('./talent-program-grades.js') : window.TalentProgramGrades).gradesSummary(levels);
  const subtabFromHash = hash => SUBTABS.find(item => item.hash === hash)?.key || '';
  const resolveTab = (value, canViewPrograms = true) => (!canViewPrograms ? 'evaluation-periods' : TABS.includes(value) ? value : 'programs');

  function programCardHtml(summary, {selected = false, canDelete = false} = {}) {
    const annual = summary.annual || null;
    return `<article class="tpc-program${selected ? ' is-selected' : ''}" data-program-row data-search="${esc(String(summary.name || '').toLowerCase())}">`
      + `<button type="button" class="tpc-program-select" data-tpc-select="${esc(summary.id)}" ${selected ? 'aria-current="true"' : ''}>${logoBadge(summary, 'tp-logo-sm')}<span class="tpc-program-text"><strong>${esc(summary.name)}</strong><small>${esc(gradesSummary(annual?.eligible_grade_levels))}</small></span></button>`
      + (canDelete ? `<button type="button" class="tpc-program-delete" data-tpc-delete="${esc(summary.id)}" aria-label="Delete ${esc(summary.name)}" title="Delete ${esc(summary.name)}">Delete</button>` : '')
      + '</article>';
  }

  function headHtml(program, summary, canManage) {
    const annual = summary?.annual || null;
    const status = STATUS_LABELS[program.status] || '';
    return `<div class="tpc-program-head">${logoBadge(program, 'tp-logo-md')}<div class="tpc-program-title"><h3>${esc(program.name)}</h3><p>${esc(gradesSummary(annual?.eligible_grade_levels))}${status ? ` <span class="tpc-status-badge" data-status="${esc(program.status)}">${esc(status)}</span>` : ''}</p></div>`
      + (canManage && program.status !== 'retired' ? '<button type="button" class="tpc-secondary" data-tpc-edit-program>Edit Program</button>' : '') + '</div>';
  }

  function programLoadingHtml(program) {
    const name = program?.name || 'Program';
    return `<section class="tpc-program-loading" data-tpc-program-loading aria-label="Loading ${esc(name)}">`
      + `<div class="tpc-loading-identity">${logoBadge(program || {name}, 'tp-logo-md')}<div><h3>${esc(name)}</h3><p data-status role="status" aria-live="polite">Loading ${esc(name)} data…</p></div></div>`
      + '<div class="tpc-loading-skeleton" aria-hidden="true"><span></span><span></span><span></span></div></section>';
  }

  function periodsOverviewHtml(programs, plans, {canManage}) {
    const byProgram = new Map((plans || []).map(plan => [String(plan.program_id), plan]));
    if (!programs.length) return '<p class="tp-empty">No Programs exist yet. Create a Program first, then plan its Evaluation Periods.</p>';
    const rows = programs.map(program => {
      const plan = byProgram.get(String(program.id));
      const summary = plan ? `${esc(plan.period_count ?? (plan.periods || []).length)} Periods · ${esc(plan.required_period_count ?? 0)} required` : 'No Evaluation Plan for this Academic Year yet';
      return `<li class="tpc-period-row">${logoBadge(program, 'tp-logo-sm')}<div><strong>${esc(program.name)}</strong><small>${summary}</small></div><button type="button" class="tpc-secondary" data-tpc-open-periods="${esc(program.id)}">${canManage ? 'Manage Periods' : 'View Periods'}</button></li>`;
    }).join('');
    return `<section class="tpc-periods-overview"><header class="tpc-section-head"><h3>Evaluation Periods</h3><p>Each Program plans its Evaluation Periods once per Academic Year. Choose a Program to configure them.</p></header><ul class="tpc-period-list">${rows}</ul></section>`;
  }

  function mount(doc, win, options = {}) {
    const $ = id => doc.getElementById(id);
    const configNode = $('tpc-config');
    if (!configNode) return null;
    const config = JSON.parse(configNode.textContent || '{}');
    const permissions = config.permissions || {};
    const can = key => permissions[key] === true;
    const yearSelect = $('tpc-year'), status = $('tpc-status'), list = $('tpc-program-list'), search = $('tpc-search');
    const head = $('tpc-center-head'), subtabs = $('tpc-subtabs'), content = $('tpc-content'), rootEl = $('tpc-root');
    const canViewPrograms = can('talent_programs.view');
    const canManage = can('talent_programs.manage');
    const apiErrors = win.TalentApiErrors;
    const state = {tab: 'programs', programId: '', programs: [], token: 0};
    const params = new URLSearchParams(win.location.search || '');
    const fetchImpl = options.fetch || win.fetch.bind(win);

    const mapError = (statusCode, code) => (apiErrors && apiErrors.httpError ? apiErrors.httpError(statusCode, code)
      : Object.assign(new Error('This view could not be loaded. Retry, or contact your administrator if the problem continues.'), {userSafe: true}));
    // Reads are bounded; writes are intentionally not timed out client-side because
    // aborting a write that may already be committed would mislead the user.
    async function api(path, init = {}) {
      const method = String(init.method || 'GET').toUpperCase();
      const controller = typeof AbortController === 'function' ? new AbortController() : null;
      const timer = controller && method === 'GET' ? setTimeout(() => controller.abort(), 20000) : null;
      try {
        const response = await fetchImpl(path, {
          credentials: 'same-origin', cache: 'no-store', ...init, signal: controller?.signal,
          headers: {Accept: 'application/json', 'Content-Type': 'application/json', ...(init.headers || {})},
        });
        if (response.redirected || !String(response.headers?.get?.('content-type') || '').includes('application/json')) {
          throw Object.assign(new Error('Your session may have ended. Sign in again and reopen this page.'), {userSafe: true});
        }
        const data = await response.json();
        if (!response.ok) throw mapError(response.status, data?.code);
        return data;
      } catch (error) {
        if (error?.name === 'AbortError') throw Object.assign(new Error('This view took too long to load. Retry, or contact your administrator if the problem continues.'), {userSafe: true});
        throw error;
      } finally { if (timer) clearTimeout(timer); }
    }
    const say = message => { if (status) status.textContent = message; };
    const yearValue = () => yearSelect.value;
    const yearLabel = () => yearSelect.options?.[yearSelect.selectedIndex]?.textContent || String(yearValue() || '');
    const errorHtml = (message, retry) => `<div class="tp-error" role="alert"><h3>This section could not be loaded</h3><p>${esc(message)}</p>${retry ? '<p><button type="button" data-tpc-retry>Retry</button></p>' : ''}</div>`;
    const safe = error => (error && error.userSafe && error.message) || 'This view could not be loaded. Retry, or contact your administrator if the problem continues.';

    function syncUrl() {
      const next = new URLSearchParams();
      if (state.tab !== 'programs') next.set('tab', state.tab);
      if (state.programId) next.set('program_id', state.programId);
      if (yearValue()) next.set('academic_year_id', yearValue());
      const query = next.toString();
      win.history?.replaceState?.(null, '', `${win.location.pathname}${query ? `?${query}` : ''}${win.location.hash || ''}`);
    }
    function setHash(hash) {
      win.history?.replaceState?.(null, '', `${win.location.pathname}${win.location.search || ''}${hash || ''}`);
    }
    const selectedSummary = () => state.programs.find(p => String(p.id) === String(state.programId)) || null;

    function renderTabs() {
      rootEl.dataset.tab = state.tab;
      doc.querySelectorAll?.('[data-tpc-tab]').forEach(button => {
        const on = button.dataset.tpcTab === state.tab;
        button.setAttribute('aria-selected', on ? 'true' : 'false');
        button.tabIndex = on ? 0 : -1;
      });
    }
    function renderList() {
      if (!canViewPrograms) { list.innerHTML = '<p class="tp-empty">You do not have permission to view Programs.</p>'; return; }
      const term = String(search?.value || '').trim().toLowerCase();
      const rows = state.programs.filter(p => !term || String(p.name || '').toLowerCase().includes(term));
      list.innerHTML = rows.length
        ? rows.map(p => programCardHtml(p, {selected: String(p.id) === String(state.programId), canDelete: (p.actions || []).includes('delete')})).join('')
        : `<p class="tp-empty">${state.programs.length ? 'No Programs match your search.' : 'No Programs yet.'}</p>`;
      const add = doc.querySelector?.('[data-tpc-action="new-program"]');
      if (add) add.hidden = !canManage;
    }
    function renderSubtabs(active) {
      if (!state.programId) { subtabs.hidden = true; subtabs.innerHTML = ''; return; }
      subtabs.hidden = false;
      subtabs.innerHTML = SUBTABS.map(item => `<a href="${item.hash}" data-tpc-subtab="${item.key}" class="${item.key === active ? 'is-current' : ''}" ${item.key === active ? 'aria-current="page"' : ''}>${esc(item.label)}</a>`).join('');
    }
    function renderHead() {
      const summary = selectedSummary();
      head.innerHTML = state.programId && summary ? headHtml(summary, summary, canManage) : '';
    }

    async function loadPrograms() {
      if (!canViewPrograms) { state.programs = []; renderList(); return; }
      const year = yearValue();
      list.innerHTML = '<p class="tp-empty">Loading Programs…</p>';
      try {
        state.programs = year
          ? await api(`/api/talent/programs/summaries?academic_year_id=${encodeURIComponent(year)}`).catch(() => api('/api/talent/programs'))
          : await api('/api/talent/programs');
        if (!Array.isArray(state.programs)) state.programs = [];
        renderList();
      } catch (error) {
        list.innerHTML = errorHtml(safe(error), true);
      }
    }
    async function refreshCatalog() {
      if (!canViewPrograms) return;
      try {
        const year = yearValue();
        const next = year ? await api(`/api/talent/programs/summaries?academic_year_id=${encodeURIComponent(year)}`) : await api('/api/talent/programs');
        if (Array.isArray(next)) { state.programs = next; renderList(); renderHead(); }
      } catch { /* the editor keeps its own result; the list refreshes on the next action */ }
    }

    function workspaceContext(root, programId) {
      return {
        root, api, can, year: yearSelect, yearLabel: yearLabel(),
        params: new URLSearchParams({academic_year_id: yearValue() || '', ...(programId ? {program_id: programId} : {})}),
        programCatalog: new Map(state.programs.map(p => [String(p.id), p])),
        configuration: true,
        notify: message => { say(message); refreshCatalog(); },
        navigate: (target, extra = {}) => {
          if (target === 'programs' && extra.program_id) { setHash(''); return selectProgram(String(extra.program_id), {hash: ''}); }
          win.location.href = `/talent/${target}?${new URLSearchParams({academic_year_id: yearValue() || '', ...extra})}`;
          return undefined;
        },
      };
    }

    async function renderCenter() {
      const token = ++state.token;
      renderTabs(); renderList(); renderHead();
      if (!canViewPrograms) {
        // A role holding only Evaluation Plan configuration keeps the canonical standalone editor.
        head.innerHTML = ''; subtabs.hidden = true;
        const ws = win.TalentEvaluationWorkspace;
        if (ws?.render) await ws.render(workspaceContext(content, params.get('program_id') || ''));
        else content.innerHTML = errorHtml('A required page component did not load. Reload the page.', false);
        return;
      }
      if (!state.programId) {
        renderSubtabs('');
        if (state.tab === 'evaluation-periods') {
          if (!can('talent_evaluation_plans.view')) { content.innerHTML = '<p class="tp-empty">You do not have permission to view Evaluation Periods.</p>'; return; }
          content.innerHTML = '<p class="tp-empty">Loading Evaluation Periods…</p>';
          try {
            const plans = await api(`/api/talent/evaluation-plans?${new URLSearchParams({academic_year_id: yearValue() || ''})}`);
            if (token !== state.token) return;
            content.innerHTML = periodsOverviewHtml(state.programs, Array.isArray(plans) ? plans : [], {canManage: can('talent_evaluation_plans.manage')});
          } catch (error) { if (token === state.token) content.innerHTML = errorHtml(safe(error), true); }
          return;
        }
        content.innerHTML = state.programs.length
          ? '<p class="tp-empty">Select a Program to configure its setup, rubric, criteria and Evaluation Periods.</p>'
          : `<p class="tp-empty">${canManage ? 'No Programs exist yet. Use + New Program to create the first Program.' : 'No Programs exist yet.'}</p>`;
        return;
      }
      renderSubtabs(subtabFromHash(win.location.hash));
      const ws = win.TalentProgramWorkspace;
      if (subtabFromHash(win.location.hash) === 'rubric' && win.TalentConfigurationTree) {
        // Grade > Competency > Rubric Level tree with the right-hand Level editor. It reads and
        // writes only through the canonical /api/talent/* routes (revision-guarded, Draft-only).
        if (ws?.dispose) ws.dispose();
        state.treeShown = true;
        content.oninput = null; content.onsubmit = null; content.onclick = null; content.onreset = null;
        await win.TalentConfigurationTree.render({root: content, drawer: $('tpc-drawer'), api, can, programId: state.programId, program: selectedSummary(), notify: say});
        return;
      }
      state.treeShown = false;
      if (!ws?.render) { content.innerHTML = errorHtml('A required page component did not load. Reload the page.', false); return; }
      try {
        await ws.render(workspaceContext(content, state.programId));
      } catch (error) {
        // Defense in depth: the editor guards its own fetch chain against a
        // superseded Program switch, but a stale render() call must never be
        // allowed to leave this shell showing a stuck loading state either.
        if (token !== state.token) return;
        content.removeAttribute?.('aria-busy');
        content.innerHTML = errorHtml(safe(error), true);
      }
    }

    async function selectProgram(id, {hash} = {}) {
      const previousProgramId = state.programId;
      state.programId = String(id || '');
      if (state.programId) {
        const wanted = hash !== undefined ? hash : (win.location.hash || (state.tab === 'evaluation-periods' ? '#tp-schedule' : '#tp-basics'));
        setHash(wanted);
      }
      syncUrl();
      if (state.programId && String(previousProgramId) !== state.programId) {
        const nextProgram = selectedSummary();
        const ws = win.TalentProgramWorkspace;
        if (ws?.dispose) ws.dispose();
        content.oninput = null; content.onsubmit = null; content.onclick = null; content.onreset = null;
        content.setAttribute('aria-busy', 'true');
        content.innerHTML = programLoadingHtml(nextProgram);
        const drawer = $('tpc-drawer');
        if (drawer) drawer.innerHTML = '<h3>Details</h3><p class="tp-empty">Program details will be available when loading finishes.</p>';
      }
      await renderCenter();
    }
    async function showNewProgram() {
      if (!canManage) return;
      state.programId = ''; syncUrl(); setHash('');
      renderTabs(); renderList(); renderHead(); renderSubtabs('');
      content.innerHTML = '<p class="tp-empty">Loading…</p>';
      try {
        const year = yearValue();
        const grades = year ? await api(`/api/talent/programs/planning-grades?academic_year_id=${encodeURIComponent(year)}`).catch(() => []) : [];
        const ws = win.TalentProgramWorkspace;
        content.innerHTML = `<section class="tpc-new-program"><header class="tpc-section-head"><h3>New Program</h3><p>Create the Program and align it with eligible Grades. Build its rubric next.</p></header>${ws.newProgramFormHtml(grades)}</section>`;
        content.onsubmit = async event => {
          event.preventDefault();
          const formEl = event.target, feedback = formEl.querySelector?.('[data-feedback]');
          try {
            const created = await ws.submitNewProgram(formEl, {api, year: yearValue(), planningGrades: grades});
            say('Program saved. Add its rubric when you are ready.');
            await refreshCatalog();
            await selectProgram(String(created.id), {hash: '#tp-rubric'});
          } catch (error) {
            if (feedback) { feedback.textContent = error?.validation ? error.message : safe(error); feedback.setAttribute('role', 'alert'); }
          }
        };
      } catch (error) { content.innerHTML = errorHtml(safe(error), false); }
    }
    async function switchTab(tab) {
      state.tab = resolveTab(tab, canViewPrograms);
      if (state.programId) {
        const current = win.location.hash;
        if (state.tab === 'evaluation-periods') setHash('#tp-schedule');
        else if (current === '#tp-schedule' || !current) setHash('#tp-basics');
      }
      syncUrl();
      await renderCenter();
    }
    async function deleteProgram(id) {
      if (!win.confirm('Permanently delete this Draft Program? This cannot be undone.')) return;
      try {
        await api(`/api/talent/programs/${encodeURIComponent(id)}`, {method: 'DELETE'});
        say('Program deleted.');
        if (String(state.programId) === String(id)) state.programId = '';
        await loadPrograms(); syncUrl(); await renderCenter();
      } catch (error) { say(safe(error)); }
    }

    doc.addEventListener('click', event => {
      const target = event.target;
      const closest = selector => target?.closest?.(selector) || null;
      const tab = closest('[data-tpc-tab]');
      if (tab) { switchTab(tab.dataset.tpcTab); return; }
      const select = closest('[data-tpc-select]');
      if (select) { selectProgram(select.dataset.tpcSelect); return; }
      if (closest('[data-tpc-action="new-program"]')) { showNewProgram(); return; }
      const del = closest('[data-tpc-delete]');
      if (del) { deleteProgram(del.dataset.tpcDelete); return; }
      const openPeriods = closest('[data-tpc-open-periods]');
      if (openPeriods) { state.tab = 'evaluation-periods'; selectProgram(openPeriods.dataset.tpcOpenPeriods, {hash: '#tp-schedule'}); return; }
      // A real hash change: the editor (and the sub-tab highlight) re-render on hashchange.
      if (closest('[data-tpc-edit-program]')) { win.location.hash = '#tp-basics'; return; }
      if (closest('[data-tpc-retry]')) { loadPrograms().then(renderCenter); }
    });
    search?.addEventListener('input', renderList);
    yearSelect.addEventListener('change', async () => { syncUrl(); await loadPrograms(); await renderCenter(); });
    win.addEventListener('hashchange', () => {
      // The editor re-renders itself on hashchange; the shell only keeps the sub-tab highlight in step.
      if (!state.programId) return;
      renderSubtabs(subtabFromHash(win.location.hash));
      // Entering or leaving the Rubric tree is owned by the shell; the editor's own listener
      // is released by ws.dispose() when the tree opens and re-armed by its next render.
      if (state.treeShown || subtabFromHash(win.location.hash) === 'rubric') renderCenter();
    });

    async function init() {
      const wantedYear = params.get('academic_year_id');
      if (wantedYear && [...(yearSelect.options || [])].some(o => String(o.value) === String(wantedYear))) yearSelect.value = wantedYear;
      state.tab = resolveTab(params.get('tab'), canViewPrograms);
      await loadPrograms();
      const wantedProgram = params.get('program_id');
      if (wantedProgram && state.programs.some(p => String(p.id) === String(wantedProgram))) {
        state.programId = String(wantedProgram);
        if (!win.location.hash) setHash(state.tab === 'evaluation-periods' ? '#tp-schedule' : '#tp-basics');
      }
      syncUrl();
      await renderCenter();
    }
    const ready = init().catch(error => { content.innerHTML = errorHtml(safe(error), false); });
    // The Rubric tree asks the shell to reload the center after a saved change.
    if (win.TalentConfiguration) win.TalentConfiguration.rerenderCenter = () => renderCenter();
    return {ready, state, selectProgram, switchTab, refreshCatalog};
  }

  const api = {gradesSummary, programCardHtml, headHtml, programLoadingHtml, periodsOverviewHtml, subtabFromHash, resolveTab, mount, SUBTABS, TABS};
  if (typeof module !== 'undefined' && module.exports) module.exports = api;
  if (typeof window !== 'undefined') {
    window.TalentConfiguration = api;
    if (typeof document !== 'undefined' && document.getElementById('tpc-config')) mount(document, window);
  }
})();
