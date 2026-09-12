/* Owner-approved Talent interaction refinements: preserve editing state, keep
   internal evaluation provenance out of normal UI, and make rubric analytics
   locally filterable without weakening backend privacy or permissions. */
((root, factory) => {
  const api = factory(root);
  if (typeof module !== 'undefined' && module.exports) module.exports = api;
})(typeof window !== 'undefined' ? window : globalThis, root => {
  'use strict';

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

  function addReviewIdentificationFilter(scope) {
    if(!scope?.querySelector||document.getElementById('tp-identification-filter')) return;
    const table=[...scope.querySelectorAll('table')].find(node=>/Official Identification/i.test(node.querySelector('thead')?.textContent||'')); if(!table)return;
    const heads=[...table.querySelectorAll('thead th')].map(th=>th.textContent.trim().toLowerCase()),index=heads.findIndex(v=>v.includes('official identification')); if(index<0)return;
    const rows=[...table.querySelectorAll('tbody tr')];
    rows.forEach(row=>{const text=row.children[index]?.textContent?.trim().toLowerCase()||'';row.dataset.identificationClass=/not identified/.test(text)?'not_identified':/identified/.test(text)?'identified':'undecided';});
    const wrap=document.createElement('div');wrap.id='tp-identification-filter';wrap.className='tp-local-filterbar tp-review-identification-filter';
    wrap.innerHTML='<label>Identification Classification<select><option value="">All Classifications</option><option value="identified">Identified</option><option value="not_identified">Not Identified</option><option value="undecided">Not yet decided</option></select></label><span class="tp-local-filter-count" aria-live="polite"></span>';
    table.closest('.tp-table-wrap')?.before(wrap);const select=wrap.querySelector('select');
    const apply=()=>{let visible=0;rows.forEach(row=>{const show=!select.value||row.dataset.identificationClass===select.value;row.hidden=!show;if(show)visible++;});wrap.querySelector('.tp-local-filter-count').textContent=`${visible} Student${visible===1?'':'s'} shown`;};select.addEventListener('change',apply);apply();
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

  function clarifyAnalyticsEmptyStates(scope) {
    if (!scope?.querySelector) return;
    const identified = scope.querySelector('.tp-primary-indicator');
    const identifiedState = identified?.querySelector('.tp-radial-state .tp-protected');
    if (identifiedState && /no data/i.test(identifiedState.textContent || '')) {
      identifiedState.textContent = 'No Official Identification result yet';
      const bodyCopy = identified.querySelector('.tp-primary-indicator-body > p');
      if (bodyCopy && !bodyCopy.dataset.tpClarified) {
        bodyCopy.dataset.tpClarified = 'true';
        bodyCopy.insertAdjacentText(
          'beforeend',
          ' Assessed Students are not automatically Officially Identified; that decision is recorded separately in Talent Review.'
        );
      }
    }

    scope.querySelectorAll('.tp-fact-strip > span').forEach(item => {
      if (!/Meets Program Criteria/i.test(item.textContent || '')) return;
      const value = item.querySelector('b .tp-protected, b');
      if (value && /no data/i.test(value.textContent || '')) {
        value.textContent = 'No Program Criteria result yet';
      }
    });
  }

  function programOptionsFromGlobalSelect() {
    if (typeof document === 'undefined') return [];
    const select = document.getElementById('tp-program');
    if (!select) return [];
    return [...select.options]
      .filter(option => option.value)
      .map(option => ({id:String(option.value), name:String(option.textContent || '').trim()}));
  }

  async function fetchRubric(programId, year, signal) {
    const response = await fetch(
      `/api/talent/analytics/programs/${encodeURIComponent(programId)}/academic-years/${encodeURIComponent(year)}/rubric-distribution?assessment_state=completed`,
      {credentials:'same-origin', cache:'no-store', headers:{Accept:'application/json'}, signal}
    );
    if (response.redirected || !response.headers.get('content-type')?.includes('application/json')) {
      throw new Error('Your session may have ended. Sign in again and reopen Results & Analytics.');
    }
    const data = await response.json();
    if (!response.ok) {
      throw new Error(typeof data?.detail === 'string' ? data.detail : 'Unable to load rubric distributions.');
    }
    return data;
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
        return `<div class="tp-card"><h4>${esc(title)}</h4><p class="tp-empty">Protected for privacy; this rubric distribution is not shown.</p></div>`;
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
      const data = await fetchRubric(selectedId, year, rubricController.signal);
      if (serial !== rubricRequestSerial || !section.isConnected) return;
      const target = section.querySelector('[data-tp-rubric-results]');
      if (target) target.innerHTML = rubricDistributionHtml(data, selectedProgram.name);
    } catch (error) {
      if (error?.name === 'AbortError' || serial !== rubricRequestSerial || !section.isConnected) return;
      const target = section.querySelector('[data-tp-rubric-results]');
      if (target) target.innerHTML = `<p class="tp-empty">Unable to load ${esc(selectedProgram.name)} rubric results: ${esc(error?.message || 'Unknown error')}</p>`;
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
      addReviewIdentificationFilter(scope);
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
    assessmentStatusKey,
    magnitudeBucket,
  };

  if (typeof document !== 'undefined') {
    if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', initBrowser, {once:true});
    else initBrowser();
  }
  return api;
});