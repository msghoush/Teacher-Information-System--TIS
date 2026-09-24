/* Owner-approved Talent interaction refinements: preserve editing state, keep
   internal evaluation provenance out of normal UI, and make rubric analytics
   locally filterable without weakening backend privacy or permissions. */
((root, factory) => {
  const api = factory(root);
  if (typeof module !== 'undefined' && module.exports) module.exports = api;
})(typeof window !== 'undefined' ? window : globalThis, root => {
  'use strict';

  // Shared helpers loaded by the template before this script (and require()'d
  // under Node). Resolved defensively so a missing module degrades instead of
  // aborting the page.
  const apiErrors = (typeof require === 'function' && typeof module !== 'undefined' && module.exports)
    ? require('./talent-api-errors.js')
    : (root && root.TalentApiErrors) || null;
  const rubricRequest = (typeof require === 'function' && typeof module !== 'undefined' && module.exports)
    ? require('./talent-rubric-request.js')
    : (root && root.TalentRubricRequest) || null;

  const PRIVATE_EVALUATION_SUFFIXES = [' · Current rubric', ' · Re-assessment'];
  const esc = value => String(value ?? '').replace(/[&<>"']/g, c => ({
    '&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'
  }[c]));

  function isPrivateEvaluationLabel(value) {
    const label = String(value || '').trim();
    return PRIVATE_EVALUATION_SUFFIXES.some(suffix => label.endsWith(suffix.trim()));
  }

  function publicEvaluationLabel(value) {
    let label = String(value || '').trim();
    for (const suffix of PRIVATE_EVALUATION_SUFFIXES) {
      const normalized = suffix.trim();
      if (label.endsWith(normalized)) label = label.slice(0, -normalized.length).trim();
    }
    return label;
  }

  function persistKey(details) {
    if (!details) return '';
    if (details.dataset?.tpPersistKey) return details.dataset.tpPersistKey;

    if (details.classList?.contains('tp-rubric-competency')) {
      const name = details.querySelector?.('.tp-competency-summary-name')?.textContent?.trim()
        || details.querySelector?.('summary')?.textContent?.trim()
        || '';
      const grade = details.closest?.('details.tp-grade-rubric')
        ?.querySelector?.(':scope > summary strong')?.textContent?.trim() || '';
      return name ? `competency:${grade}:${name}` : '';
    }

    if (details.classList?.contains('tp-grade-rubric')) {
      const grade = details.querySelector?.(':scope > summary strong')?.textContent?.trim()
        || details.querySelector?.('summary strong')?.textContent?.trim()
        || details.querySelector?.('summary')?.textContent?.trim()
        || '';
      return grade ? `grade:${grade}` : '';
    }
    return '';
  }

  function annotateDisclosures(scope) {
    if (!scope?.querySelectorAll) return;
    scope.querySelectorAll('details.tp-grade-rubric, details.tp-rubric-competency').forEach(details => {
      const key = persistKey(details);
      if (key && details.dataset) details.dataset.tpPersistKey = key;
    });
  }

  function snapshotDisclosureState(scope) {
    annotateDisclosures(scope);
    const state = {};
    scope?.querySelectorAll?.('details[data-tp-persist-key]').forEach(details => {
      state[details.dataset.tpPersistKey] = Boolean(details.open);
    });
    return state;
  }

  function restoreDisclosureState(scope, state) {
    if (!scope?.querySelectorAll || !state) return;
    annotateDisclosures(scope);
    scope.querySelectorAll('details[data-tp-persist-key]').forEach(details => {
      const key = details.dataset.tpPersistKey;
      if (Object.prototype.hasOwnProperty.call(state, key)) details.open = Boolean(state[key]);
    });
  }

  function chooseRubricProgramId(programs, requestedId='', globalProgramId='') {
    const items = Array.isArray(programs) ? programs : [];
    const requested = String(requestedId || '');
    const global = String(globalProgramId || '');
    if (requested && items.some(item => String(item.id) === requested)) return requested;
    if (global && items.some(item => String(item.id) === global)) return global;
    return items.length ? String(items[0].id) : '';
  }

  function cleanupAssessmentContexts(scope) {
    if (!scope?.querySelectorAll) return;
    let selectedPublicLabel = '';
    scope.querySelectorAll('.tp-evaluation-group').forEach(group => {
      const label = group.querySelector?.('header h3')?.textContent?.trim() || '';
      if (isPrivateEvaluationLabel(label)) {
        if (group.classList?.contains('is-selected')) selectedPublicLabel = publicEvaluationLabel(label);
        group.remove();
      }
    });
    scope.querySelectorAll('.tp-selected-evaluation').forEach(node => {
      const label = node.querySelector?.('h3')?.textContent?.trim() || '';
      if (!selectedPublicLabel && label) selectedPublicLabel = publicEvaluationLabel(label);
      node.remove();
    });

    let selectedGroups = [...scope.querySelectorAll('.tp-evaluation-group.is-selected')];
    if (!selectedGroups.length && selectedPublicLabel) {
      const fallback = [...scope.querySelectorAll('.tp-evaluation-group')].find(group =>
        publicEvaluationLabel(group.querySelector?.('header h3')?.textContent || '') === selectedPublicLabel
      );
      if (fallback) {
        fallback.classList?.add('is-selected');
        selectedGroups = [fallback];
      }
    }
    selectedGroups.forEach(group => {
      const header = group.querySelector?.(':scope > header') || group.querySelector?.('header');
      const title = header?.querySelector?.('h3')?.textContent?.trim() || 'Evaluation';
      if (header && !header.querySelector('.tp-selected-badge')) {
        const badge = header.ownerDocument.createElement('span');
        badge.className = 'tp-selected-badge';
        badge.setAttribute('aria-label', `${title} is selected`);
        badge.innerHTML = '<span aria-hidden="true">✓</span> Selected';
        header.append(badge);
      }
      group.setAttribute?.('aria-current', 'true');
    });
  }


  function assessmentStatusKey(row) {
    if (row?.querySelector?.('.tp-status-chip.is-warning')?.textContent?.match(/re-evaluation/i)) return 're_evaluation_required';
    const text=row?.querySelector?.('.tp-status-chip')?.textContent?.trim().toLowerCase()||'';
    if (/completed/.test(text)) return 'completed';
    if (/in progress/.test(text)) return 'in_progress';
    if (/insufficient/.test(text)) return 'insufficient_evidence';
    if (/incomplete/.test(text)) return 'incomplete';
    return 'not_started';
  }

  function addAssessmentRosterFilters(scope) {
    if (!scope?.querySelector || document.getElementById('tp-assessment-roster-filters')) return;
    const table=[...scope.querySelectorAll('table')].find(node=>/Assessment Status/i.test(node.querySelector('thead')?.textContent||'')&&/Student/i.test(node.querySelector('thead')?.textContent||''));
    if(!table) return;
    const rows=[...table.querySelectorAll('tbody tr')]; if(!rows.length) return;
    const heads=[...table.querySelectorAll('thead th')].map(th=>th.textContent.trim().toLowerCase());
    const gradeIndex=heads.indexOf('grade'), sectionIndex=heads.indexOf('section');
    if(gradeIndex<0||sectionIndex<0) return;
    const grades=[...new Set(rows.map(row=>row.children[gradeIndex]?.textContent?.trim()).filter(Boolean))].sort((a,b)=>a.localeCompare(b,undefined,{numeric:true}));
    const sections=[...new Set(rows.map(row=>row.children[sectionIndex]?.textContent?.trim()).filter(Boolean))].sort((a,b)=>a.localeCompare(b,undefined,{numeric:true}));
    rows.forEach(row=>{row.dataset.rosterGrade=row.children[gradeIndex]?.textContent?.trim()||'';row.dataset.rosterSection=row.children[sectionIndex]?.textContent?.trim()||'';row.dataset.assessmentStatus=assessmentStatusKey(row);});
    const wrap=document.createElement('div'); wrap.id='tp-assessment-roster-filters'; wrap.className='tp-local-filterbar';
    wrap.innerHTML=`<label>Grade<select data-roster-filter="grade"><option value="">All Grades</option>${grades.map(v=>`<option value="${esc(v)}">${esc(v==='KG'?'KG':`Grade ${v}`)}</option>`).join('')}</select></label><label>Section<select data-roster-filter="section"><option value="">All Sections</option>${sections.map(v=>`<option value="${esc(v)}">${esc(v)}</option>`).join('')}</select></label><label>Assessment Status<select data-roster-filter="status"><option value="">All Statuses</option><option value="not_started">Not started</option><option value="in_progress">In progress</option><option value="completed">Completed</option><option value="re_evaluation_required">Re-evaluation required</option><option value="incomplete">Incomplete</option><option value="insufficient_evidence">Insufficient evidence</option></select></label><span class="tp-local-filter-count" aria-live="polite"></span>`;
    table.closest('.tp-table-wrap')?.before(wrap);
    const apply=()=>{const grade=wrap.querySelector('[data-roster-filter="grade"]').value,section=wrap.querySelector('[data-roster-filter="section"]').value,status=wrap.querySelector('[data-roster-filter="status"]').value;let visible=0;rows.forEach(row=>{const show=(!grade||row.dataset.rosterGrade===grade)&&(!section||row.dataset.rosterSection===section)&&(!status||row.dataset.assessmentStatus===status);row.hidden=!show;if(show)visible++;});wrap.querySelector('.tp-local-filter-count').textContent=`${visible} Student${visible===1?'':'s'} shown`;};
    wrap.addEventListener('change',apply); apply();
  }

  function magnitudeBucket(value) {
    const n=Number(value); if(!Number.isFinite(n)) return 0;
    const p=Math.max(0,Math.min(100,n)); return p<20?1:p<40?2:p<60?3:p<80?4:5;
  }

  function applyAnalyticsMagnitudeColors(scope) {
    if(!scope?.querySelectorAll)return;
    scope.querySelectorAll('.tp-radial,.tp-progress-track,.tp-grade-track,.tp-result-meter').forEach(node=>{
      let value=NaN;const label=node.getAttribute?.('aria-label')||'',percent=label.match(/([0-9]+(?:\.[0-9]+)?)\s*percent/i);
      if(percent)value=Number(percent[1]);
      if(!Number.isFinite(value)){const width=node.querySelector?.('[style*="width"]')?.style?.width||'',match=width.match(/([0-9]+(?:\.[0-9]+)?)%/);if(match)value=Number(match[1]);}
      const bucket=magnitudeBucket(value);if(!bucket)return;for(let i=1;i<=5;i++)node.classList.remove(`tp-magnitude-${i}`);node.classList.add(`tp-magnitude-${bucket}`);
    });
  }

  // Acceptance B: the former legacy Review/Identification
  // empty-state rewrites are removed - those legacy concepts are no longer part of
  // the current Talent workflow, and the current Talented section carries its own
  // explicit backend-driven copy. Kept as a no-op so existing callers and the
  // exported surface stay stable.
  function clarifyAnalyticsEmptyStates(_scope) {}

  function programOptionsFromGlobalSelect() {
    if (typeof document === 'undefined') return [];
    const select = document.getElementById('tp-program');
    if (!select) return [];
    return [...select.options]
      .filter(option => option.value)
      .map(option => ({id:String(option.value), name:String(option.textContent || '').trim()}));
  }

  // Bounded like every other Talent read (see REQUEST_TIMEOUT_MS in talent.js):
  // 25 s is far above normal latency yet ends a hung request in a visible,
  // retryable state instead of an indefinite "Loading ... rubric results" line.
  const RUBRIC_TIMEOUT_MS = 25000;
  function fetchRubric(programId, year, signal, timeoutMs = RUBRIC_TIMEOUT_MS) {
    return new Promise((resolve, reject) => {
      const local = new AbortController();
      let settled = false, timer = null;
      const finish = (settle, value) => {
        if (settled) return;
        settled = true;
        clearTimeout(timer);
        signal?.removeEventListener?.('abort', onParentAbort);
        settle(value);
      };
      function onParentAbort() { local.abort(); finish(reject, Object.assign(new Error('Request cancelled.'), {name:'AbortError'})); }
      if (signal) {
        if (signal.aborted) { reject(Object.assign(new Error('Request cancelled.'), {name:'AbortError'})); return; }
        signal.addEventListener('abort', onParentAbort, {once:true});
      }
      if (timeoutMs > 0) timer = setTimeout(() => { local.abort(); finish(reject, Object.assign(new Error('timeout'), {name:'TimeoutError', userSafe:true})); }, timeoutMs);
      Promise.resolve().then(() => fetch(
        `/api/talent/analytics/programs/${encodeURIComponent(programId)}/academic-years/${encodeURIComponent(year)}/rubric-distribution?assessment_state=completed`,
        {credentials:'same-origin', cache:'no-store', headers:{Accept:'application/json'}, signal: local.signal}
      )).then(async response => {
        if (response.redirected || !response.headers.get('content-type')?.includes('application/json')) {
          throw Object.assign(new Error('Your session may have ended. Sign in again and reopen Results & Analytics.'), {userSafe:true});
        }
        const data = await response.json();
        if (!response.ok) {
          throw (apiErrors && typeof apiErrors.httpError === 'function')
            ? apiErrors.httpError(response.status, data?.code)
            : Object.assign(new Error('Unable to load rubric distributions.'), {userSafe:true});
        }
        return data;
      }).then(value => finish(resolve, value), error => finish(reject, error));
    });
  }

  // Concise, non-technical failure state with a real Retry button. Only messages
  // authored here or mapped from an HTTP response (userSafe) are shown; any other
  // exception text is replaced by the generic sentence.
  function rubricErrorHtml(programName, error) {
    const detail = error?.name === 'TimeoutError'
      ? 'This is taking longer than expected. Check your connection, then retry.'
      : (error?.userSafe === true && error.message) ? error.message : '';
    return `<div class="tp-section-state tp-section-error" role="group" aria-label="Rubric results unavailable"><strong>${esc(programName)} rubric results could not finish loading.</strong>${detail ? `<span>${esc(detail)}</span>` : ''}<button type="button" data-tp-rubric-retry>Retry</button></div>`;
  }

  function rubricDistributionHtml(data, programName) {
    const visual = root?.TalentRubricVisual;
    const distributions = Array.isArray(data?.distributions) ? data.distributions : [];
    if (!distributions.length) {
      return `<p class="tp-empty">No completed rubric results are available for ${esc(programName)} yet.</p>`;
    }
    return distributions.map(d => {
      const title = [d.competency_label, d.rubric_name].filter(Boolean).join(' — ')
        || d.framework_title || 'Assessment setup';
      if (d.state === 'restricted') {
        return `<div class="tp-card"><h4>${esc(title)}</h4><p class="tp-empty">This rubric distribution is not available for this selection.</p></div>`;
      }
      const average = d.average_rank != null
        ? `<div class="tp-competency-average"><span><strong>${Number(d.average_rank).toFixed(1)}</strong>/${esc(d.scale_max)}</span><div class="tp-result-meter" aria-label="Average ${Number(d.average_rank).toFixed(1)} out of ${esc(d.scale_max)}"><i style="width:${Math.max(0,Math.min(100,Number(d.normalized_percent||0)))}%"></i></div></div>`
        : '';
      const chart = visual?.distribution
        ? visual.distribution(d.levels)
        : '<p class="tp-empty">Rubric visualization is unavailable.</p>';
      return `<div class="tp-card"><h4>${esc(title)}</h4>${average}${chart}</div>`;
    }).join('');
  }

  let rubricController = null;
  let rubricRequestSerial = 0;
  let rubricSelectedProgramId = '';

  async function ensureRubricSection(scope, {force=false}={}) {
    if (typeof document === 'undefined') return;
    const workspace = document.getElementById('talent-workspace');
    if (!workspace || workspace.dataset.view !== 'analytics' || !scope || scope.querySelector('.tp-error')) return;

    const programs = programOptionsFromGlobalSelect();
    if (!programs.length) return;

    const query = new URLSearchParams(location.search);
    const globalProgramId = document.getElementById('tp-program')?.value || query.get('program_id') || '';
    const selectedId = chooseRubricProgramId(programs, rubricSelectedProgramId, globalProgramId);
    rubricSelectedProgramId = selectedId;
    if (!selectedId) return;
    const selectedProgram = programs.find(item => String(item.id) === String(selectedId)) || programs[0];
    const year = document.getElementById('tp-year')?.value || query.get('academic_year_id') || '';
    if (!year) return;

    let section = scope.querySelector('[data-tp-rubric-section]');
    const legacySection = scope.querySelector('#tp-rubric-title')?.closest('section');
    if (!section && legacySection) {
      section = legacySection;
      section.dataset.tpRubricSection = 'true';
    }
    if (!section) {
      section = document.createElement('section');
      section.dataset.tpRubricSection = 'true';
      scope.append(section);
    }

    const loadKey = `${year}:${selectedId}`;
    if (!force && section.dataset.tpRubricLoaded === loadKey) return;
    section.dataset.tpRubricLoaded = loadKey;

    const options = programs.map(item =>
      `<option value="${esc(item.id)}" ${String(item.id)===String(selectedId)?'selected':''}>${esc(item.name)}</option>`
    ).join('');

    section.innerHTML = `
      <div class="tp-section-heading tp-rubric-filter-heading">
        <div>
          <p class="tp-eyebrow">Rubrics</p>
          <h3 id="tp-rubric-title">Competency rubric distributions</h3>
          <p>One Program at a time. Completed assessments only; privacy protection remains unchanged.</p>
        </div>
        <label class="tp-rubric-program-filter">Program
          <select id="tp-rubric-program-filter">${options}</select>
        </label>
      </div>
      <div data-tp-rubric-results><p class="tp-empty">Loading ${esc(selectedProgram.name)} rubric results…</p></div>`;

    const select = section.querySelector('#tp-rubric-program-filter');
    select?.addEventListener('change', () => {
      rubricSelectedProgramId = select.value;
      ensureRubricSection(scope, {force:true});
    });

    rubricController?.abort();
    rubricController = new AbortController();
    const serial = ++rubricRequestSerial;
    try {
      // Reuse talent.js's authoritative rubric read for the same Program + Year +
      // assessment_state context (cross-module deduplication). Retry (force) always
      // re-issues its own bounded request. A different Program selected in this
      // section's own filter is a different context and fetches independently.
      const requestKey = (rubricRequest && typeof rubricRequest.key === 'function')
        ? rubricRequest.key(selectedId, year)
        : `${selectedId}|${year}|completed`;
      const shared = !force && rubricRequest && typeof rubricRequest.get === 'function'
        ? rubricRequest.get(requestKey)
        : null;
      const data = shared ? await shared : await fetchRubric(selectedId, year, rubricController.signal);
      if (serial !== rubricRequestSerial || !section.isConnected) return;
      const target = section.querySelector('[data-tp-rubric-results]');
      if (target) target.innerHTML = rubricDistributionHtml(data, selectedProgram.name);
    } catch (error) {
      if (error?.name === 'AbortError' || serial !== rubricRequestSerial || !section.isConnected) return;
      const target = section.querySelector('[data-tp-rubric-results]');
      if (target) {
        target.innerHTML = rubricErrorHtml(selectedProgram.name, error);
        target.querySelector('[data-tp-rubric-retry]')?.addEventListener('click', () => ensureRubricSection(scope, {force:true}));
      }
    }
  }

  function initBrowser() {
    if (typeof document === 'undefined') return;
    const workspace = document.getElementById('talent-workspace');
    const scope = document.getElementById('tp-content');
    if (!workspace || !scope) return;
    document.body?.classList?.toggle('tp-overview-branding', workspace.dataset.view === 'overview');

    let rememberedDisclosureState = snapshotDisclosureState(scope);
    document.addEventListener('submit', event => {
      const form = event.target;
      if (form?.closest?.('.tp-program-workspace')) {
        rememberedDisclosureState = snapshotDisclosureState(scope);
      }
    }, true);
    scope.addEventListener('toggle', event => {
      const details = event.target;
      if (!details?.matches?.('details.tp-grade-rubric, details.tp-rubric-competency')) return;
      annotateDisclosures(scope);
      const key = persistKey(details);
      if (key) rememberedDisclosureState[key] = Boolean(details.open);
    }, true);

    const apply = () => {
      annotateDisclosures(scope);
      restoreDisclosureState(scope, rememberedDisclosureState);
      cleanupAssessmentContexts(scope);
      addAssessmentRosterFilters(scope);
      clarifyAnalyticsEmptyStates(scope);
      applyAnalyticsMagnitudeColors(scope);
      ensureRubricSection(scope).catch(() => {});
    };

    const observer = new MutationObserver(apply);
    observer.observe(scope, {childList:true, subtree:true});
    apply();
  }

  const api = {
    isPrivateEvaluationLabel,
    publicEvaluationLabel,
    persistKey,
    snapshotDisclosureState,
    restoreDisclosureState,
    chooseRubricProgramId,
    cleanupAssessmentContexts,
    clarifyAnalyticsEmptyStates,
    rubricDistributionHtml,
    fetchRubric,
    rubricErrorHtml,
    assessmentStatusKey,
    magnitudeBucket,
  };

  if (typeof document !== 'undefined') {
    if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', initBrowser, {once:true});
    else initBrowser();
  }
  return api;
});