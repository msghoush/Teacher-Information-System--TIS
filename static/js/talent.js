/* M11 presentation only: authoritative API projections, never reconstructed metrics. */
(() => {
  'use strict';
  // Deployment Acceptance Correction A: this global is resolved defensively. The
  // previous eager `rubricVisual.intensity` dereference threw a TypeError at
  // script-evaluation time on every view whose page did not load
  // talent-rubric-visual.js, aborting the whole IIFE before init() ever ran and
  // leaving the server-rendered loader on screen forever. The template now loads
  // the (tiny, shared) module on every view, and a missing module can no longer
  // take the workspace down: each helper below degrades to a neutral fallback.
  const rubricVisual = typeof module !== 'undefined' && module.exports
    ? require('./talent-rubric-visual.js')
    : (typeof window !== 'undefined' && window.TalentRubricVisual) || null;
  // Shared helpers loaded by the template on every view (and require()'d under Node).
  // Both are resolved defensively so a missing module degrades instead of aborting.
  const apiErrors = typeof module !== 'undefined' && module.exports
    ? require('./talent-api-errors.js')
    : (typeof window !== 'undefined' && window.TalentApiErrors) || null;
  const rubricRequest = typeof module !== 'undefined' && module.exports
    ? require('./talent-rubric-request.js')
    : (typeof window !== 'undefined' && window.TalentRubricRequest) || null;
  // Acceptance B: shared Student identity presentation (name / Learning Style /
  // backend Classification / Talented). Presentation only; resolved defensively.
  const studentIdentity = typeof module !== 'undefined' && module.exports
    ? require('./talent-student-identity.js')
    : (typeof window !== 'undefined' && window.TalentStudentIdentity) || null;
  // Shared privacy-safe chart renderer (Progress Over Time trend). Resolved defensively.
  const talentCharts = typeof module !== 'undefined' && module.exports
    ? require('./talent-charts.js')
    : (typeof window !== 'undefined' && window.TalentCharts) || null;
  // Shared chevron for navigation actions (inline SVG, decorative, always paired with text).
  const chevron = '<svg class="tp-chevron" viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true" focusable="false"><path d="m9 6 6 6-6 6"/></svg>';
  const labels = {
    programs_configured:'Programs configured', active_programs:'Active Programs',
    // Batch 1: "Students participating" is DISTINCT current Students only (the
    // backend `distinct_students` figure). The frozen-membership counts are one row
    // per Student per Cycle/Program, so they are labelled as participations.
    distinct_students:'Students participating',
    frozen_eligible_memberships:'Program participations', frozen_eligible:'Program participations',
    completed:'Assessments completed', completion_coverage:'Assessment completion',
    assessment_started:'Assessments started', started_coverage:'Assessments started coverage',
    required_period_execution:'Required evaluations run',
    // Acceptance B: the legacy Review Candidate / Official Identification metric
    // labels are intentionally absent - those legacy counts are no longer a normal
    // current Talent figure, so generic card/mini-metric renderers (which only
    // render keys that have a label) never surface them. The backend metrics and
    // legacy history remain available through the explicit legacy-history view.
    participation_overlap:'Distinct participating Students',
    evaluation_period_result:'Evaluation Period Result', current_overall_progress:'Overall Result',
    assessment_completion:'Assessment Completion', assessments_started:'Assessments Started',
  };
  const states = {suppressed:'Unavailable', complementary_suppressed:'Unavailable',
    restricted:'Not available for this view', no_data:'No data yet', coarsened:'Shown as a broader group'};
  // no_data is a structural absence (no authoritative population/equation), never a
  // privacy decision - it must stay visually and textually distinct from an actual
  // privacy-protected (suppressed/restricted/coarsened) state.
  const privacyStates = new Set(['suppressed', 'complementary_suppressed', 'restricted', 'coarsened']);
  const esc = value => String(value ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  const human = value => String(value ?? '').replaceAll('_',' ');
  const number = value => typeof value === 'number' && Number.isFinite(value) ? new Intl.NumberFormat('en',{maximumFractionDigits:1}).format(value) : esc(value);
  function metric(cell) {
    if (!cell || typeof cell !== 'object') return '<span class="tp-protected">No data</span>';
    if (cell.state !== 'visible') {
      // Coarsened output intentionally remains state-only in this first UI slice.
      // Never inspect sibling values or construct magnitude cues for protected cells.
      return `<span class="tp-protected">${esc(states[cell.state] || 'Unavailable at this level')}</span>`;
    }
    if (typeof cell.percentage === 'number' && Number.isFinite(cell.percentage)) {
      return `<strong>${number(cell.percentage)}%</strong><small>${number(cell.numerator)} / ${number(cell.denominator)}</small>`;
    }
    if (typeof cell.value === 'number' && Number.isFinite(cell.value)) return `<strong>${number(cell.value)}</strong>`;
    return '<span class="tp-protected">No data</span>';
  }
  // Categorical heat bucket for an already-visible, already-percentage-bearing Cell only.
  // Never derived for a suppressed/restricted/coarsened/no_data Cell and never derived
  // from a raw count (only a bounded 0-100 backend percentage), so it cannot encode a
  // protected magnitude and cannot imply cross-Program/Branch ranking from raw counts.
  function heatBucket(cell) {
    if (!cell || cell.state !== 'visible' || typeof cell.percentage !== 'number' || !Number.isFinite(cell.percentage)) return 0;
    const p = cell.percentage;
    return p <= 0 ? 1 : p < 25 ? 2 : p < 50 ? 3 : p < 75 ? 4 : 5;
  }
  const badge = text => `<span class="tp-badge">${esc(human(text))}</span>`;
  const empty = text => `<p class="tp-empty">${esc(text)}</p>`;
  const note = text => `<aside class="tp-note">${esc(text)}</aside>`;
  const table = (title, heads, rows) => `<div class="tp-table-wrap" role="region" aria-label="${esc(title)}" tabindex="0"><table><caption>${esc(title)}</caption><thead><tr>${heads.map(x=>`<th scope="col">${esc(x)}</th>`).join('')}</tr></thead><tbody>${rows.join('')}</tbody></table></div>`;
  const cards = metrics => `<div class="tp-grid">${Object.entries(metrics || {}).filter(([key])=>labels[key]).map(([key,value])=>`<article class="tp-card"><h3>${labels[key]}</h3><div class="tp-number">${metric(value)}</div></article>`).join('')}</div>`;
  function progressVisual(cell, label) {
    if (!cell || cell.state !== 'visible' || typeof cell.percentage !== 'number' || !Number.isFinite(cell.percentage)) {
      return `<div class="tp-progress tp-progress-state"><span>${esc(label)}</span>${metric(cell)}</div>`;
    }
    const width=Math.max(0,Math.min(100,cell.percentage));
    return `<div class="tp-progress"><div class="tp-progress-head"><span>${esc(label)}</span><strong>${number(cell.percentage)}%</strong></div><div class="tp-progress-track" role="img" aria-label="${esc(label)}: ${number(cell.percentage)} percent"><span style="width:${width}%"></span></div><small>${number(cell.numerator)} of ${number(cell.denominator)}</small></div>`;
  }
  // Radial gauge drawn ONLY from an already-visible backend percentage. A protected,
  // restricted, coarsened, or no_data Cell never sets an arc length, so the visual
  // can never encode a hidden magnitude. Count-only Cells keep the numeric treatment.
  function radialGauge(cell, label) {
    if (!cell || cell.state !== 'visible' || typeof cell.percentage !== 'number' || !Number.isFinite(cell.percentage)) {
      return `<div class="tp-radial tp-radial-state" role="img" aria-label="${esc(label)}">${metric(cell)}</div>`;
    }
    const p = Math.max(0, Math.min(100, cell.percentage));
    const circumference = 2 * Math.PI * 50;
    const offset = circumference * (1 - p / 100);
    return `<div class="tp-radial" role="img" aria-label="${esc(label)}: ${number(cell.percentage)} percent"><svg viewBox="0 0 120 120" aria-hidden="true" focusable="false"><circle class="tp-radial-track" cx="60" cy="60" r="50"/><circle class="tp-radial-arc" cx="60" cy="60" r="50" stroke-dasharray="${circumference.toFixed(1)}" stroke-dashoffset="${offset.toFixed(1)}"/></svg><div class="tp-radial-center"><strong>${number(cell.percentage)}%</strong><small>${number(cell.numerator)} of ${number(cell.denominator)}</small></div></div>`;
  }
  // Horizontal grade-level bars from an already-shaped [{label, cell}] list. Bar
  // length is set only by a visible backend percentage; every other state is a
  // distinct categorical treatment, so suppressed magnitude is never implied.
  function gradeBars(items, metricLabel) {
    const rows = (items || []).filter(item => item && item.label != null);
    if (!rows.length) return empty('No grade-level results are available for this context.');
    const body = rows.map(item => {
      const cell = item.cell;
      if (!cell || cell.state !== 'visible' || typeof cell.percentage !== 'number' || !Number.isFinite(cell.percentage)) {
        return `<div class="tp-grade-row"><span class="tp-grade-label">${esc(item.label)}</span><div class="tp-grade-state">${metric(cell)}</div></div>`;
      }
      const width = Math.max(0, Math.min(100, cell.percentage));
      return `<div class="tp-grade-row"><span class="tp-grade-label">${esc(item.label)}</span><div class="tp-grade-track" role="img" aria-label="${esc(item.label)}: ${number(cell.percentage)} percent"><span style="width:${width}%"></span></div><strong>${number(cell.percentage)}%</strong></div>`;
    }).join('');
    return `<div class="tp-grade-chart" role="group" aria-label="${esc(metricLabel || 'Result')} by grade">${body}</div>`;
  }
  // A compact row of radial gauges, one per grade — the Owner's "Grade indicator"
  // concept. Each arc is drawn only from a visible backend percentage; protected
  // grades stay categorical.
  function gradeGauges(items) {
    const rows = (items || []).filter(item => item && item.label != null);
    if (!rows.length) return empty('No grade-level results are available for this context.');
    return `<div class="tp-grade-gauges" role="group" aria-label="Results by grade">${rows.map(item => `<div class="tp-grade-gauge"><span class="tp-grade-gauge-label">${esc(item.label)}</span>${radialGauge(item.cell, item.label)}</div>`).join('')}</div>`;
  }
  // Clickable horizontal bars, one per Branch, for compact visual comparison and
  // drill-down. Bar length is set only by a visible backend percentage.
  function branchBars(items) {
    const rows = (items || []).filter(item => item && item.label != null);
    if (!rows.length) return empty('No Branch results are available yet.');
    const body = rows.map(item => {
      const cell = item.cell;
      const visible = cell && cell.state === 'visible' && typeof cell.percentage === 'number' && Number.isFinite(cell.percentage);
      const visual = visible
        ? `<div class="tp-grade-track" role="img" aria-label="${esc(item.label)}: ${number(cell.percentage)} percent"><span style="width:${Math.max(0, Math.min(100, cell.percentage))}%"></span></div>`
        : `<div class="tp-grade-state">${metric(cell)}</div>`;
      return `<a class="tp-branch-row" href="${esc(item.href)}"><span class="tp-grade-label">${esc(item.label)}</span>${visual}${visible ? `<strong>${number(cell.percentage)}%</strong>` : ''}</a>`;
    }).join('');
    return `<div class="tp-grade-chart tp-branch-chart" role="group" aria-label="Results by Branch">${body}</div>`;
  }
  // M14 owner correction: the 'learning_style' Branch-comparison metric is
  // removed (it averaged the now-deprecated four percentage columns - see
  // talent_evaluation_progress_service.py's APPROVED_BRANCH_METRICS comment).
  // Acceptance B: legacy Review Candidate / Official Identification metrics are no
  // longer offered as normal current metrics; the parameters are kept only so the
  // exported signature stays stable for existing callers.
  const branchComparisonMetricOptions = (_candidateAllowed, _identificationAllowed) => [
    ['evaluation_period_result','Evaluation Period Result'],
    ['current_overall_progress','Overall Result'],
    ['assessment_completion','Assessment Completion'],
    ['assessments_started','Assessments Started'],
  ];
  const branchStateText = state => ({
    suppressed:'Unavailable', complementary_suppressed:'Unavailable',
    restricted:'Not available for this view', no_data:'No data',
    coarsened:'Shown as a broader group',
  }[state] || 'No data');
  const branchMetricValue = (row, metricName) => {
    if (!row || row.state !== 'visible') return null;
    if (metricName === 'current_overall_progress') return typeof row.value === 'number' ? row.value : null;
    if (metricName === 'evaluation_period_result') return typeof row.mean_normalized_percent === 'number' ? row.mean_normalized_percent : null;
    return typeof row.percentage === 'number' ? row.percentage : null;
  };
  function branchComparisonBar(row, metricName, accessibleLabel) {
    const value=branchMetricValue(row,metricName);
    if(value===null)return `<div class="tp-branch-comparison-state is-${esc(row?.state||'no_data')}">${esc(branchStateText(row?.state))}</div>`;
    return `<div class="tp-branch-comparison-value"><div class="tp-branch-comparison-track" role="img" aria-label="${esc(accessibleLabel)}: ${esc(value)} percent"><span style="width:${esc(value)}%"></span></div><strong>${esc(value)}%</strong></div>`;
  }
  function branchComparisonChart(data, branches) {
    const rows=Array.isArray(data?.rows)?data.rows:[];
    const branchNames=new Map((branches||[]).map(branch=>[String(branch.id),branch.label||branch.name]));
    const title=labels[data?.metric]||'Branch result';
    const frameworkMessage=data?.comparability_state==='not_comparable'&&data?.comparability_reason_code==='framework_changed'
      ? '<p class="tp-state-explanation" role="status">Overall Result is unavailable because the Program framework changed between Evaluation Periods. No cross-framework result is calculated.</p>' : '';
    if(!rows.length)return frameworkMessage+empty('No Branch results are available for this Program and Academic Year.');
    const body=rows.map(row=>{
      const branchLabel=branchNames.get(String(row.branch_id))||'Authorized Branch';
      if(data.metric==='evaluation_period_result'){
        const periods=Array.isArray(row.periods)?row.periods:[];
        return `<li class="tp-branch-comparison-row"><h4>${esc(branchLabel)}</h4><div class="tp-branch-period-results">${periods.map(period=>`<div><span>${esc(period.label)}</span>${branchComparisonBar(period,data.metric,`${branchLabel}, ${period.label}`)}</div>`).join('')||`<p class="tp-branch-comparison-state is-no_data">No data</p>`}</div></li>`;
      }
      return `<li class="tp-branch-comparison-row"><h4>${esc(branchLabel)}</h4>${branchComparisonBar(row,data.metric,`${branchLabel}, ${title}`)}</li>`;
    }).join('');
    return frameworkMessage+`<ol class="tp-branch-comparison" aria-label="${esc(title)} by Branch">${body}</ol>`;
  }
  const rubricLevelIntensity = (index, count) => rubricVisual
    ? rubricVisual.intensity(index, count)
    : (count <= 1 ? 1 : Math.max(0, Math.min(1, index / (count - 1))));
  const rubricDistribution = levels => rubricVisual
    ? rubricVisual.distribution(levels)
    : '<p class="tp-empty">Rubric visualization is unavailable.</p>';
  const rubricBadge = (level, levels, options) => rubricVisual ? rubricVisual.badge(level, levels, options) : `<span class="tp-rubric-level">${esc(level && level.label)}</span>`;
  function kpiCard(key, cell, href='', context='') {
    const isRate = cell && cell.state === 'visible' && typeof cell.percentage === 'number' && Number.isFinite(cell.percentage);
    const value = isRate ? radialGauge(cell, labels[key] || human(key)) : `<div class="tp-kpi-value">${metric(cell)}</div>`;
    const body=`<article class="tp-kpi${href?' tp-kpi-link':''}"><span class="tp-kpi-label">${esc(labels[key]||human(key))}</span>${value}${context?`<p>${esc(context)}</p>`:''}${href?`<a class="tp-card-hit" href="${href}" aria-label="Explore ${esc(labels[key]||human(key))}"><span>Explore</span>${chevron}</a>`:''}</article>`;
    return body;
  }
  const friendlyReason = reason => ({missing_cycle:'An evaluation cycle has not been linked',cycle_not_authoritative:'The linked cycle is not open or closed',cancelled_period:'This evaluation period was cancelled',no_frozen_population:'No recorded Student assessment context is available',metric_unavailable:'This result is not available for the selected measure',framework_changed:'The Program framework changed between these periods',privacy_protected:'One or both results are unavailable for this comparison'}[reason] || 'These periods cannot be compared');
  // ---- Request/render lifecycle (Deployment Acceptance Correction A) --------
  // Every read request is bounded. 25 s is deliberately conservative: it is far
  // above normal analytics latency (a p95 well under a few seconds) so a slow but
  // healthy response is never cut off, yet short enough that a hung connection
  // ends in a visible, retryable state instead of an indefinite loader. Small
  // lookup lists that only populate the context selectors use a shorter 15 s
  // bound, and boot never waits longer than 20 s in total for them.
  const REQUEST_TIMEOUT_MS = 25000;
  const CONTEXT_REQUEST_TIMEOUT_MS = 15000;
  const INIT_CONTEXT_DEADLINE_MS = 20000;
  const GENERIC_LOAD_MESSAGE = 'This section could not finish loading.';
  const isAbortError = error => Boolean(error) && error.name === 'AbortError';
  const abortError = () => Object.assign(new Error('Request cancelled.'), {name: 'AbortError'});
  const timeoutError = () => Object.assign(new Error('This is taking longer than expected. Check your connection, then retry.'), {name: 'TimeoutError', code: 'timeout', userSafe: true});
  const userSafeError = (message, extra = {}) => Object.assign(new Error(message), {userSafe: true}, extra);
  // Curated, user-safe mapping for a non-2xx API response. HTTP status + a known
  // stable backend `code` choose the copy; arbitrary backend `detail` is never
  // interpolated, so raw SQL/Python/JS/endpoint/stack/internal text cannot surface.
  const mapHttpError = (status, code) => (apiErrors && typeof apiErrors.httpError === 'function')
    ? apiErrors.httpError(status, code)
    : userSafeError('This view could not be loaded. Retry, or contact your administrator if the problem continues.', {status, code});
  // Only messages this module itself authored (userSafe === true) are shown. Any
  // other exception (a TypeError from a render bug, a JSON parse failure, a network
  // error, or a status-bearing error that was not explicitly curated) is replaced by
  // a generic message so stack fragments, raw exception text and internal names
  // never reach the user.
  const safeMessage = error => (error && error.userSafe === true && typeof error.message === 'string' && error.message.trim())
    ? error.message : GENERIC_LOAD_MESSAGE;
  const errorTitle = error => error && error.status === 403 ? 'Permission denied'
    : error && error.status === 503 ? 'Analytics unavailable'
    : error && error.code === 'timeout' ? 'Taking longer than expected' : 'Unable to load view';
  const errorPanel = error => `<div class="tp-error" role="group" aria-label="This view could not be loaded"><h3>${errorTitle(error)}</h3><p>${esc(safeMessage(error))}</p><button type="button" id="tp-retry">Retry</button></div>`;
  const sectionLoadingHtml = label => `<span class="tp-section-state tp-section-loading"><span class="tp-skel" aria-hidden="true"></span><span class="tp-skel tp-skel-short" aria-hidden="true"></span><span class="tp-section-loading-text">Loading ${esc(label)}…</span></span>`;
  const sectionErrorHtml = (id, error) => {
    const detail = safeMessage(error);
    const title = error && error.code === 'timeout' ? 'Taking longer than expected' : GENERIC_LOAD_MESSAGE;
    return `<div class="tp-section-state tp-section-error" role="group" aria-label="Section unavailable"><strong>${esc(title)}</strong>${detail !== GENERIC_LOAD_MESSAGE && detail !== title ? `<span>${esc(detail)}</span>` : ''}${error && error.status === 403 ? '' : `<button type="button" data-tp-section-retry="${esc(id)}">Retry</button>`}</div>`;
  };
  // An independent, individually-loading region. Kept free of nested <div> so a
  // section can always be replaced by writing to its innerHTML.
  const slotHtml = (id, label, className = '') => `<div class="tp-slot${className ? ` ${esc(className)}` : ''}" data-tp-slot="${esc(id)}" aria-busy="true">${sectionLoadingHtml(label)}</div>`;
  // One bounded request: settles exactly once (response, HTTP error, timeout or
  // abort) regardless of whether the underlying fetch cooperates with abort().
  function boundedRequest(fetchImpl, url, init, parentSignal, consume, timeoutMs) {
    return new Promise((resolve, reject) => {
      const local = new AbortController();
      let settled = false, timer = null;
      const finish = (settle, value) => {
        if (settled) return;
        settled = true;
        clearTimeout(timer);
        if (parentSignal && parentSignal.removeEventListener) parentSignal.removeEventListener('abort', onParentAbort);
        settle(value);
      };
      function onParentAbort() { local.abort(); finish(reject, abortError()); }
      if (parentSignal) {
        if (parentSignal.aborted) { reject(abortError()); return; }
        parentSignal.addEventListener('abort', onParentAbort, {once: true});
      }
      if (timeoutMs > 0) timer = setTimeout(() => { local.abort(); finish(reject, timeoutError()); }, timeoutMs);
      Promise.resolve().then(() => fetchImpl(url, {...init, signal: local.signal})).then(consume).then(value => finish(resolve, value), error => finish(reject, error));
    });
  }
  const lede = (title, text, tone='') => `<div class="tp-section-lede${tone?` tp-tone-${tone}`:''}"><svg aria-hidden="true" viewBox="0 0 24 24" width="22" height="22" fill="none" stroke="currentColor" stroke-width="1.8"><circle cx="12" cy="12" r="9"/><path d="M12 8v5"/><path d="M12 16h.01"/></svg><div><h3>${esc(title)}</h3><p>${esc(text)}</p></div></div>`;
  // Canonical Program-selection resolver shared by the ribbon/context selector
  // and its regression tests. Selection is by program_id ONLY (never by
  // Program name - two Programs could share a name) and NEVER defaults to the
  // first item in an async-loaded list: an absent or unmatched id always
  // resolves to the neutral "" (no Program selected) state, the same state a
  // fresh page load with no program_id shows. This removes any reliance on
  // an unmatched <select>.value assignment silently falling back to the
  // browser's default (first-option) selection.
  function resolveProgramSelection(items, requestedId) {
    const list = Array.isArray(items) ? items : [];
    if (requestedId == null || requestedId === '') return '';
    const match = list.find(item => String(item.id) === String(requestedId));
    return match ? String(match.id) : '';
  }
  // Acceptance B: shared Student identity presentation helpers (thin adapters over
  // TalentStudentIdentity; all Classification/Talented values are backend fields).
  const identityHtml = options => studentIdentity ? studentIdentity.identityHtml(options)
    : `<span class="tp-identity"><span class="tp-identity-name">${esc(options?.name || 'Student name unavailable')}</span></span>`;
  const classificationMeta = (classification, isTalented) => studentIdentity && classification
    ? studentIdentity.metaHtml({classification, isTalented}) : '';
  const initials = name => esc(String(name||'?').trim().split(/\s+/).slice(0,2).map(w=>w[0]||'').join('').toUpperCase() || '?');
  const programLogo = (program, size='tp-logo-sm') => program ? (typeof window!=='undefined'&&window.TalentProgramIdentity ? window.TalentProgramIdentity.logoBadge(program,size) : `<span class="tp-logo-badge ${size}"><span class="tp-logo-initials" aria-hidden="true">${initials(program.name)}</span></span>`) : '';
  const appIcon = name => typeof window!=='undefined'&&window.TalentProgramWorkspace?.icon ? window.TalentProgramWorkspace.icon(name) : '<svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" aria-hidden="true"><path d="M4 20V10h4v10M10 20V4h4v16M16 20v-7h4v7"/></svg>';
  // Real matrix/grid markup (CSS Grid, ARIA grid semantics) for the Talent Map. Every
  // protected/suppressed cell is a distinct categorical pattern + text, never a
  // magnitude-proportional gradient; only an already-visible backend percentage may set
  // a heat class, and heat classes never appear on a non-visible cell. no_data is kept
  // visually and textually distinct from an actual privacy-protected state.
  function matrixLegend() {
    return `<div class="tp-legend" role="note" aria-label="Talent Map legend">
      <span class="tp-legend-item"><span class="tp-legend-swatch tp-heat-1" aria-hidden="true"></span>Lower</span>
      <span class="tp-legend-item"><span class="tp-legend-swatch tp-heat-3" aria-hidden="true"></span>Mid-range</span>
      <span class="tp-legend-item"><span class="tp-legend-swatch tp-heat-5" aria-hidden="true"></span>Higher</span>
      <span class="tp-legend-item"><span class="tp-legend-swatch tp-protected-swatch" aria-hidden="true"></span>Unavailable (no value or magnitude shown)</span>
      <span class="tp-legend-item"><span class="tp-legend-swatch" style="background:var(--app-surface);border-style:dashed" aria-hidden="true"></span>No data (no authoritative population - not a privacy decision)</span>
    </div>`;
  }
  function matrixCellHtml(cell, rowLabel, colLabel, drill) {
    const state = cell && cell.state;
    const isProtected = state && privacyStates.has(state);
    const isNoData = state === 'no_data' || !cell;
    const heat = (isProtected || isNoData) ? 0 : heatBucket(cell);
    const cls = `tp-matrix-cell tp-heat-${heat}${isProtected?' tp-protected-cell':''}${isNoData?' tp-nodata-cell':''}`;
    const explanation=isProtected?'Unavailable; no value is shown':isNoData?'No data is available for this context':'This result is available';
    const label = `${esc(rowLabel)} and ${esc(colLabel)}: ${explanation}`;
    return `<div class="${cls}" role="gridcell" tabindex="0" aria-label="${label}" data-clickable="${drill?'true':'false'}">${metric(cell)}<span class="tp-cell-help">${esc(explanation)}</span>${drill?`<small>${drill}</small>`:''}</div>`;
  }
  function matrix(title, rowLabel, columns, rows, cellFor, rowTotalFor, colTotalFor, orgTotal, drillFor) {
    const colCount = columns.length + 2;
    const head = `<div class="tp-matrix-row" role="row"><div class="tp-matrix-corner" role="columnheader">${esc(rowLabel)}</div>${columns.map(c=>`<div class="tp-matrix-head" role="columnheader">${esc(c.label)}</div>`).join('')}<div class="tp-matrix-head" role="columnheader">Total</div></div>`;
    const body = rows.map(r=>`<div class="tp-matrix-row" role="row"><div class="tp-matrix-rowhead" role="rowheader">${esc(r.label)}</div>${columns.map(c=>matrixCellHtml(cellFor(r,c), r.label, c.label, drillFor?drillFor(r,c):null)).join('')}<div class="tp-matrix-cell tp-matrix-total" role="gridcell">${metric(rowTotalFor(r))}</div></div>`).join('');
    const footer = `<div class="tp-matrix-row" role="row"><div class="tp-matrix-rowhead tp-matrix-total" role="rowheader">Authorized-scope total</div>${columns.map(c=>`<div class="tp-matrix-cell tp-matrix-total" role="gridcell">${metric(colTotalFor(c))}</div>`).join('')}<div class="tp-matrix-cell tp-matrix-total" role="gridcell">${metric(orgTotal)}</div></div>`;
    return `${matrixLegend()}<div class="tp-matrix-wrap"><div class="tp-matrix" role="grid" aria-label="${esc(title)}" style="grid-template-columns:190px repeat(${colCount-1},minmax(150px,1fr))">${head}${body}${footer}</div></div>`;
  }
  function overlapMatrix(data, programHref) {
    const count=data.programs.length+1;
    const header=`<div class="tp-matrix-row" role="row"><div class="tp-matrix-corner" role="columnheader">Program</div>${data.programs.map(p=>`<div class="tp-matrix-head" role="columnheader">${esc(p.name)}</div>`).join('')}</div>`;
    const rows=data.matrix.map(row=>{
      const program=data.programs.find(p=>p.id===row.program_id);
      return `<div class="tp-matrix-row" role="row"><div class="tp-matrix-rowhead" role="rowheader">${esc(program?.name||'Program')}</div>${row.cells.map(cell=>{
        const other=data.programs.find(p=>p.id===cell.program_id);
        const diagonal=cell.program_id===row.program_id;
        const state=cell?.state;
        const cls=privacyStates.has(state)?' tp-protected-cell':state==='no_data'?' tp-nodata-cell':'';
        const meaning=diagonal?'Students in this Program':`Students in both ${program?.name||'Programs'} and ${other?.name||'Programs'}`;
        return `<div class="tp-matrix-cell tp-overlap-cell${diagonal?' tp-overlap-diagonal':''}${cls}" role="gridcell" tabindex="0" aria-label="${esc(meaning)}. ${state==='visible'?'Visible count':states[state]||'Not available'}">${metric(cell)}<small>${esc(diagonal?'In this Program':'In both Programs')}</small>${diagonal&&programHref?programHref(program):''}</div>`;
      }).join('')}</div>`;
    }).join('');
    return `<div class="tp-matrix-wrap"><div class="tp-matrix" role="grid" aria-label="Distinct Students participating across Programs" style="grid-template-columns:190px repeat(${count-1},minmax(150px,1fr))">${header}${rows}</div></div>`;
  }
  // Progress Over Time (ADR 0027 longitudinal projection): one Program, one Academic Year,
  // ordered Evaluation Periods. The trend/bar chart and its exact table come from the shared
  // chart module; a period whose cell is not visible is a gap, never a zero or a magnitude
  // (a newly opened Period with no Student result is "No data yet", not 0%).
  function periodVisual(data) {
    const path=data.points?.length?`<div class="tp-period-path" role="list" aria-label="Evaluation sequence">${data.points.map((point,index)=>`${index?`<span aria-hidden="true">${chevron}</span>`:''}<strong role="listitem">${esc(point.evaluation_period.label)}</strong>`).join('')}</div>`:'';
    const rows=(data.points||[]).map(p=>{
      const cell=p.metric_result||{};
      return {label:p.evaluation_period.label,state:cell.state||'no_data',
        count:typeof cell.numerator==='number'?cell.numerator:cell.value,
        percentage:cell.percentage,denominator:cell.denominator};
    });
    const plot=talentCharts&&rows.length?talentCharts.series(`${labels[data.metric]||'Result'} by Evaluation Period`,rows,{surface:'longitudinal'}):'';
    return path+plot+`<ol class="tp-sequence tp-period-grid">${data.points.map(p=>`<li class="tp-period"><span class="tp-seq">${esc(p.evaluation_period.sequence)}</span><div><h3>${esc(p.evaluation_period.label)}</h3>${badge(p.evaluation_period.status)}<p>${esc(labels[data.metric])}</p>${metric(p.metric_result)}${p.no_data_reason?`<p class="tp-state-explanation">${esc(friendlyReason(p.no_data_reason))}</p>`:''}</div></li>`).join('')}</ol>`;
  }
  // M18b-2 Results & Analytics rebuild: bucket distribution chart/table pair
  // reused by the Learning Style and Classification families of the new
  // /api/talent/results-analytics/... contract. Bar length is set only by an
  // already-visible backend percentage; every other state renders a
  // distinct categorical treatment matching this file's existing privacy
  // contract - never a magnitude cue for a protected/no-data bucket, and
  // never a client-derived band/percentage.
  function bucketBars(buckets, groupLabel) {
    const rows = Array.isArray(buckets) ? buckets : [];
    if (!rows.length) return empty('No results are available for this selection.');
    const body = rows.map(b => {
      const visible = b && b.state === 'visible' && typeof b.percentage === 'number' && Number.isFinite(b.percentage);
      if (!visible) {
        return `<div class="tp-grade-row"><span class="tp-grade-label">${esc(human(b && b.label))}</span><div class="tp-grade-state">${esc(states[b && b.state] || 'Unavailable')}</div></div>`;
      }
      const width = Math.max(0, Math.min(100, b.percentage));
      return `<div class="tp-grade-row"><span class="tp-grade-label">${esc(human(b.label))}</span><div class="tp-grade-track" role="img" aria-label="${esc(human(b.label))}: ${number(b.percentage)} percent"><span style="width:${width}%"></span></div><strong>${number(b.percentage)}%</strong></div>`;
    }).join('');
    return `<div class="tp-grade-chart" role="group" aria-label="${esc(groupLabel || 'Distribution')}">${body}</div>`;
  }
  // Accessible non-visual equivalent for every bucket chart above: a real
  // data table carrying the identical backend count/percentage, never
  // recalculated or reconstructed client-side.
  function bucketTable(title, buckets) {
    const rows = (Array.isArray(buckets) ? buckets : []).map(b => {
      const visible = b && b.state === 'visible';
      const countText = visible && typeof b.count === 'number' ? number(b.count) : esc(states[b && b.state] || 'Unavailable');
      const pctText = visible && typeof b.percentage === 'number' ? `${number(b.percentage)}%` : '—';
      return `<tr><th scope="row">${esc(human(b && b.label))}</th><td>${countText}</td><td>${pctText}</td></tr>`;
    });
    return table(title, ['Category', 'Count', 'Percentage'], rows);
  }
  // One coherent chart+table section for a privacy-closed bucket
  // distribution (Learning Style / Classification). Never derives a band,
  // count, or percentage - every value is exactly what the backend
  // returned for this scope; a non-visible total renders a neutral
  // unavailable state, never the literal "Protected for privacy".
  function distributionSection(id, eyebrow, heading, description, distribution, footnote) {
    const unavailable = !distribution || distribution.state !== 'visible';
    const body = unavailable
      ? empty('This distribution is not available for this selection.')
      : bucketBars(distribution.buckets, heading) + bucketTable(heading, distribution.buckets);
    return `<section aria-labelledby="${id}-title"><div class="tp-section-heading"><div><p class="tp-eyebrow">${esc(eyebrow)}</p><h3 id="${id}-title">${esc(heading)}</h3></div><p>${esc(description)}</p></div>${body}${footnote ? note(footnote) : ''}</section>`;
  }
  // Acceptance C: Learning Style distribution. Authorized Student-domain
  // aggregate (denominator = every authorized Student in the selection,
  // including Unassigned; no Talent small-cell suppression, so a valid
  // category is never "Unavailable"). Renders the backend `levels` exactly:
  // label, count and percentage are backend values, never recomputed here; the
  // bar width is geometry from the backend percentage only. Zero rows stay
  // visible with an empty bar. A failed/forbidden request never reaches this
  // renderer (the section loader shows its own error/retry state).
  const studentsText = n => `${number(n)} Student${n === 1 ? '' : 's'}`;
  function learningStyleBars(levels) {
    const body = levels.map(level => {
      const pct = typeof level.percentage === 'number' && Number.isFinite(level.percentage) ? level.percentage : 0;
      const count = typeof level.count === 'number' ? level.count : 0;
      const width = Math.max(0, Math.min(100, pct));
      const unassigned = level.key === 'not_specified' ? ' tp-ls-unassigned' : '';
      return `<div class="tp-grade-row${unassigned}"><span class="tp-grade-label">${esc(level.label)}</span><div class="tp-grade-track" role="img" aria-label="${esc(level.label)}: ${number(pct)} percent, ${studentsText(count)}"><span style="width:${width}%"></span></div><strong>${number(pct)}%</strong><small>${studentsText(count)}</small></div>`;
    }).join('');
    return `<div class="tp-grade-chart tp-ls-chart" role="group" aria-label="Learning Style distribution">${body}</div>`;
  }
  function learningStyleTable(levels) {
    const rows = levels.map(level => `<tr><th scope="row">${esc(level.label)}</th><td>${number(level.count)}</td><td>${number(level.percentage)}%</td></tr>`);
    return table('Learning Style Distribution', ['Category', 'Students', 'Percentage'], rows);
  }
  function learningStyleDistributionSection(id, eyebrow, heading, description, distribution) {
    const levels = distribution && Array.isArray(distribution.levels) ? distribution.levels : null;
    let body;
    if (!levels || !distribution || (distribution.state !== 'visible' && distribution.state !== 'empty')) {
      body = empty('This distribution is not available for this selection.');
    } else if (distribution.state === 'empty' || !distribution.total_population) {
      body = empty('No Students in the current authorized selection.');
    } else {
      body = `<p class="tp-ls-context">${studentsText(distribution.total_population)} in this selection, including Unassigned.</p>${learningStyleBars(levels)}${learningStyleTable(levels)}`;
    }
    return `<section aria-labelledby="${id}-title"><div class="tp-section-heading"><div><p class="tp-eyebrow">${esc(eyebrow)}</p><h3 id="${id}-title">${esc(heading)}</h3></div><p>${esc(description)}</p></div>${body}</section>`;
  }
  // Family 3 (current Talent): Talented==Exceptional only, exactly the
  // backend's own count/applicable-denominator/rate. The Organization value
  // is never a client-side average of the per-Branch rates below - it is
  // the backend's own raw-count rollup (sum_raw_counts_across_branches).
  function talentedSection(data, branchNames) {
    if (!data) return '';
    const summary = (data.organization && data.organization.summary) || {};
    const rateVisible = data.organization && data.organization.distribution && data.organization.distribution.state === 'visible'
      && typeof summary.talented_rate_percentage === 'number';
    const rateCell = rateVisible
      ? {state: 'visible', percentage: summary.talented_rate_percentage, numerator: summary.talented_count, denominator: summary.applicable_denominator}
      : {state: (data.organization && data.organization.distribution && data.organization.distribution.state) || 'no_data'};
    const gauge = radialGauge(rateCell, 'Talented (Exceptional) rate');
    const context = rateVisible
      ? `<p>${number(summary.talented_count)} of ${number(summary.applicable_denominator)} applicable current, completed assessments are classified Exceptional.</p>`
      : '<p>No current Talented result is available for this selection.</p>';
    const branchRows = (data.branch_breakdown || []).map(item => {
      const bucket = ((item.distribution && item.distribution.buckets) || []).find(b => b.label === 'talented');
      const cell = bucket && bucket.state === 'visible'
        ? {state: 'visible', percentage: bucket.percentage, numerator: bucket.count, denominator: item.distribution.total.value}
        : {state: (item.distribution && item.distribution.state) || 'no_data'};
      return {label: (branchNames && branchNames.get(String(item.branch_id))) || 'Authorized Branch', cell};
    });
    const branchChart = branchRows.length
      ? `<div class="tp-grade-chart" role="group" aria-label="Talented rate by Branch">${branchRows.map(item => {
          const cell = item.cell;
          if (!cell || cell.state !== 'visible' || typeof cell.percentage !== 'number' || !Number.isFinite(cell.percentage)) {
            return `<div class="tp-grade-row"><span class="tp-grade-label">${esc(item.label)}</span><div class="tp-grade-state">${metric(cell)}</div></div>`;
          }
          const width = Math.max(0, Math.min(100, cell.percentage));
          return `<div class="tp-grade-row"><span class="tp-grade-label">${esc(item.label)}</span><div class="tp-grade-track" role="img" aria-label="${esc(item.label)}: ${number(cell.percentage)} percent"><span style="width:${width}%"></span></div><strong>${number(cell.percentage)}%</strong></div>`;
        }).join('')}</div>`
      : empty('No Branch results are available yet.');
    const branchSection = branchRows.length
      ? `<div class="tp-section-heading"><div><p class="tp-eyebrow">Branches</p><h3>Talented rate by Branch</h3></div><p>Each Branch value is the backend's own raw Talented/applicable count. The Organization value above sums every Branch's raw counts - it is never an average of these Branch rates.</p></div>${branchChart}`
      : '';
    return `<section aria-labelledby="tp-talented-title" class="tp-primary-indicator"><div class="tp-section-heading"><div><p class="tp-eyebrow">Current Talent</p><h3 id="tp-talented-title">Talented (Exceptional) results</h3></div></div><div class="tp-primary-indicator-body">${gauge}${context}<p>Talented is the current, automatic Exceptional classification of a completed assessment. Preserved Legacy Review &amp; Identification History is separate audit history and is not part of this current figure.</p></div>${branchSection}${data.not_currently_classifiable_count ? note(`${data.not_currently_classifiable_count} completed assessment(s) use a Program rubric that cannot currently be classified and are excluded from this rate.`) : ''}</section>`;
  }
  // Small pure boundary exported for privacy and injection regression tests.
  if (typeof module !== 'undefined' && module.exports) module.exports = {metric, esc, heatBucket, matrix, matrixCellHtml, matrixLegend, lede, initials, badge, table, cards, progressVisual, kpiCard, radialGauge, gradeBars, gradeGauges, branchBars, branchComparisonMetricOptions, branchMetricValue, branchComparisonChart, rubricDistribution, rubricLevelIntensity, friendlyReason, overlapMatrix, periodVisual, errorPanel, resolveProgramSelection, bucketBars, bucketTable, distributionSection, learningStyleDistributionSection, talentedSection, boundedRequest, safeMessage, sectionErrorHtml, sectionLoadingHtml, slotHtml, REQUEST_TIMEOUT_MS};
  if (typeof document === 'undefined') return;
  const configNode = document.getElementById('tp-config');
  if (!configNode) return;
  const root = document.getElementById('tp-content'), status = document.getElementById('tp-status');
  let config;
  try { config = JSON.parse(configNode.textContent); }
  catch { config = null; }
  if (!config || typeof config !== 'object' || !config.permissions) {
    // Without its server-provided configuration the workspace cannot run. Replace
    // the server-rendered loader with an explicit, non-loading failure state.
    if (root) { root.innerHTML = '<div class="tp-error" role="group"><h3>Unable to load view</h3><p>This page could not be initialized. Reload the page, or contact your administrator if the problem continues.</p></div>'; root.setAttribute('aria-busy', 'false'); }
    if (status) status.textContent = 'View could not be loaded.';
    return;
  }
  const permissions = config.permissions;
  const form = document.getElementById('tp-filters'), year = document.getElementById('tp-year');
  const program = document.getElementById('tp-program'), branch = document.getElementById('tp-branch'), grade = document.getElementById('tp-grade'), section = document.getElementById('tp-section'), metricSelect = document.getElementById('tp-metric');
  const dimension = document.getElementById('tp-dimension');
  // M18b-2b: Classification filter (query param `classification`, restricted
  // to the 5 backend CLASSIFICATION_LABELS) is real, already-supported
  // scope narrowing on the /results-analytics/.../classification route
  // (talent_results_analytics_service.classification_family). It is
  // progressive/conditional: only relevant (and only ever shown) once a
  // Program is selected on the analytics view, since Classification is
  // Program-bound. It can only narrow the returned buckets, never widen
  // authorization - the 5 option values are the exact literal backend labels.
  const classificationSelect = document.getElementById('tp-classification');
  const CLASSIFICATION_LABELS = ['Needs Improvement','Developing','Meets Expectations','Advanced','Exceptional'];
  let params = new URLSearchParams(location.search), generation = 0, controller, programCatalog=new Map(), activeSections = null;
  const can = key => permissions[key] === true;
  // Branch model (owner-directed amendment to the Batch 1 closure). The sidebar
  // "Change Branch / Campus" selector holds REAL Branches only. The server renders
  // the validated active Branch as config.branch:
  //  * organization-authorized actor: it is only the DEFAULT page-level Branch
  //    (defaultBranch). The Talent Branch filter offers All Branches and every
  //    authorized Branch; All Branches is carried by the URL marker branch_scope=all.
  //  * Branch-limited actor (config.branchLocked): it is the hard ceiling
  //    (activeBranch): nothing else is offered, kept in the URL or sent.
  // The server re-authorizes every branch_id (talent_branch_scope); this is
  // presentation, never the security boundary.
  const defaultBranch = config.branch!=null && config.branch!=='' ? String(config.branch) : '';
  const activeBranch = config.branchLocked===true ? defaultBranch : '';
  const qs = values => new URLSearchParams(Object.entries(values)
    .map(([k,v]) => (k==='branch_id' && activeBranch && v!=='' && v!=null ? [k,activeBranch] : [k,v]))
    .filter(([,v]) => v !== '' && v != null)).toString();
  const BRANCH_SCOPED_VIEWS = ['overview','assessments','reviews','analytics','talent-map','portfolio','branch','overlap','students','longitudinal'];
  function reconcileBranchScope() {
    if(!BRANCH_SCOPED_VIEWS.includes(config.view)) return;
    // A URL minted under a DIFFERENT active Branch (another tab, restored history,
    // bookmark) must never override the current global Branch: drop its Branch and
    // every Branch-dependent selection (Grade, Section) so no stale scope survives.
    const marker=params.get('scope_branch_id'), reference=activeBranch||defaultBranch;
    if(marker!==null && marker!==reference) ['branch_id','grade_level','planning_section_id','branch_scope','offset'].forEach(key=>params.delete(key));
    if(reference) params.set('scope_branch_id',reference); else params.delete('scope_branch_id');
    if(activeBranch) {
      // Hard ceiling (Branch-limited actor): the Branch is always exactly theirs. A
      // different branch_id (hand-edited or stale URL) is overwritten, All Branches is gone.
      params.set('branch_id',activeBranch);
      params.delete('branch_scope');
    } else if(params.get('branch_id')) params.delete('branch_scope');
    else if(defaultBranch && params.get('branch_scope')!=='all') params.set('branch_id',defaultBranch);
    // Persist the reconciled scope so every consumer that reads the URL (for
    // example talent-experience.js) sees the same Branch this script requests.
    try { history.replaceState(null,'',`${location.pathname}?${params}${location.hash||''}`); } catch { /* bookkeeping only */ }
  }
  const link = (view, text, extra={}) => `<a target="_self" href="/talent/${view}?${esc(qs({academic_year_id:year.value,...extra}))}">${esc(text)} ${chevron}</a>`;
  function syncNavigation() {
    // Top-level Talent navigation is a context reset boundary. Moving from a
    // selected Program (for example Mental Math) to Programs, Student
    // Assessments, Talent Review, or Results must not silently carry that
    // Program/cycle/assessment context into the destination.
    document.querySelectorAll('.tp-nav a, .sidebar-tree a[href*="/talent/"]').forEach(a=>{
      const next=new URL(a.href,location.origin);
      next.search=qs({academic_year_id:year.value});
      next.hash='';
      a.href=next.href;
      a.target='_self';
    });
    // Inside Results & Analytics, the compact analytics sub-navigation is the
    // one place where staying in the same analysis context is intentional.
    document.querySelectorAll('.tp-results-nav a').forEach(a=>{
      const next=new URL(a.href,location.origin);
      next.search=qs({
        academic_year_id:year.value,
        program_id:params.get('program_id'),
        branch_id:params.get('branch_id'),
        branch_scope:params.get('branch_scope'),
        grade_level:params.get('grade_level'),
        planning_section_id:params.get('planning_section_id'),
        metric:params.get('metric'),
        dimension:params.get('dimension'),
        classification:params.get('classification'),
      });
      next.hash='';
      a.href=next.href;
      a.target='_self';
    });
  }
  // Parses one API response into data or a curated, user-safe error. Runs inside
  // boundedRequest, so reading the body is bounded by the same timeout as the fetch.
  async function parseApiResponse(response) {
    if (response.redirected || !response.headers.get('content-type')?.includes('application/json')) throw userSafeError('Your session may have ended. Sign in again, then reopen this view.', {status: 401});
    const data = await response.json();
    if (!response.ok) throw mapHttpError(response.status, data?.code);
    return data;
  }
  function api(path, signal, timeoutMs = REQUEST_TIMEOUT_MS) {
    return boundedRequest(fetch, `/api/talent/${path}`, {credentials: 'same-origin', cache: 'no-store', headers: {Accept: 'application/json'}}, signal, parseApiResponse, timeoutMs);
  }
  // Independent, individually-terminating page regions. Each section awaits only
  // the (memoized, never duplicated) requests it needs and ends in success, empty,
  // or a local error with its own Retry - one slow or failing request can neither
  // erase nor delay the sections that do not depend on it.
  // Only the CURRENT generation may publish sections: a stale render that finishes
  // late must never replace the sections of the view the user is actually on.
  function registerSections(sections) { if (sections.run === generation) activeSections = sections; }
  function createSections(run, signal) {
    const memo = new Map(), defs = [];
    const request = (key, path) => {
      if (!memo.has(key)) { const pending = api(path, signal); pending.catch(() => {}); memo.set(key, pending); }
      return memo.get(key);
    };
    const current = () => run === generation && !signal.aborted;
    const slotFor = id => root.querySelector(`[data-tp-slot="${id}"]`);
    async function runOne(def) {
      const element = slotFor(def.id);
      if (!element) return true;
      element.setAttribute('aria-busy', 'true');
      let ok = true;
      try {
        const html = await def.build();
        if (!current()) return true;
        element.innerHTML = html; element.hidden = !html;
      } catch (error) {
        if (!current() || isAbortError(error)) return true;
        ok = false;
        if (def.quiet) { element.innerHTML = ''; element.hidden = true; }
        else { element.hidden = false; element.innerHTML = sectionErrorHtml(def.id, error); }
      } finally {
        if (current()) element.removeAttribute('aria-busy');
      }
      return ok;
    }
    return {
      run, request,
      add(def) { defs.push({group: def.id, keys: [], ...def}); },
      start() { return Promise.all(defs.map(runOne)); },
      async retry(id) {
        const target = defs.find(def => def.id === id);
        if (!target || !current()) return;
        const members = defs.filter(def => def.group === target.group);
        members.forEach(def => { def.keys.forEach(key => memo.delete(key)); const element = slotFor(def.id); if (element) { element.hidden = false; element.setAttribute('aria-busy', 'true'); element.innerHTML = sectionLoadingHtml(def.label || 'this section'); } });
        status.textContent = 'Retrying…';
        const results = await Promise.all(members.map(runOne));
        if (current()) status.textContent = results.every(Boolean) ? 'View loaded.' : 'Some sections could not be loaded.';
      },
    };
  }
  // ---- Filter interaction, scroll and focus preservation (Part 2 E) ----------
  // Results & Analytics filters never navigate or reload the document: they update local
  // params, mirror them into the URL with history.replaceState, and refetch in the
  // background. The rendered dashboard stays in place (aria-busy, dimmed, thin progress
  // bar) until the newest response is ready; only that response may render.
  let dashboardReady = false, dashToken = 0, dashController = null, dashTimer = null, overviewAnimated = false;
  // One restrained entrance for the Overview charts, first render only, and never when the
  // user prefers reduced motion (or the preference cannot be read).
  function shouldAnimateEntrance() {
    if (overviewAnimated) return false;
    overviewAnimated = true;
    try {
      const query = typeof window.matchMedia === 'function' ? window.matchMedia('(prefers-reduced-motion: reduce)') : null;
      return Boolean(query) && !query.matches;
    } catch { return false; }
  }
  function captureAnchor(holder) {
    const active = document.activeElement;
    const named = active && active.name && (typeof root.contains !== 'function' || root.contains(active));
    let top = null;
    try { if (named && typeof active.getBoundingClientRect === 'function') top = active.getBoundingClientRect().top; } catch { top = null; }
    const anchor = {x: window.scrollX || 0, y: window.scrollY || 0, top,
      key: named ? {name: active.name, value: active.type === 'checkbox' ? active.value : null} : null,
      height: (holder && holder.offsetHeight) || 0};
    // Holding the region's height stops the browser clamping the scroll position while
    // the content is replaced by something momentarily shorter.
    if (holder && holder.style && anchor.height) holder.style.minHeight = `${anchor.height}px`;
    return anchor;
  }
  function restoreAnchor(anchor, holder) {
    try {
      let target = null;
      if (anchor.key && typeof root.querySelectorAll === 'function') {
        target = Array.from(root.querySelectorAll(`[name="${anchor.key.name}"]`)).find(el => anchor.key.value === null || el.value === anchor.key.value) || null;
      }
      if (target) {
        if (typeof target.focus === 'function') target.focus({preventScroll: true});
        const now = typeof target.getBoundingClientRect === 'function' ? target.getBoundingClientRect().top : null;
        if (anchor.top !== null && now !== null && Math.abs(now - anchor.top) > 1 && typeof window.scrollBy === 'function') window.scrollBy(0, now - anchor.top);
      } else if (Math.abs((window.scrollY || 0) - anchor.y) > 1 && typeof window.scrollTo === 'function') {
        window.scrollTo(anchor.x, anchor.y);
      }
    } catch { /* presentation only */ }
    if (holder && holder.style) holder.style.minHeight = '';
  }
  function cancelDashboard() {
    clearTimeout(dashTimer); dashToken += 1;
    if (dashController) dashController.abort();
    dashController = null;
  }
  const dashboardSlot = () => (config.view === 'analytics' && window.TalentDashboard) ? root.querySelector('[data-tp-slot="tp-dashboard-slot"]') : null;
  function setDashboardBusy(slot, busy) {
    if (busy) slot.setAttribute('aria-busy', 'true'); else slot.removeAttribute('aria-busy');
    if (slot.classList) { if (busy) slot.classList.add('is-refreshing'); else slot.classList.remove('is-refreshing'); }
    const bar = slot.querySelector('[data-dashboard-progress]');
    if (bar) bar.hidden = !busy;
    const banner = slot.querySelector('[data-dashboard-error]');
    if (banner && busy) { banner.hidden = true; banner.innerHTML = ''; }
  }
  function showDashboardError(slot, error) {
    const banner = slot.querySelector('[data-dashboard-error]');
    if (!banner) return;
    banner.hidden = false;
    banner.innerHTML = `<strong>${error && error.code === 'timeout' ? 'Taking longer than expected' : 'The analysis could not be updated.'}</strong> <span>${esc(safeMessage(error))}</span> <button type="button" class="tp-secondary" data-dashboard-retry>Retry</button>`;
  }
  async function refreshDashboard() {
    const slot = dashboardSlot();
    // Nothing rendered yet (first load in flight, or it failed): use the full lifecycle.
    if (!slot || !dashboardReady) return load();
    clearTimeout(dashTimer);
    if (dashController) dashController.abort();
    const token = ++dashToken, controller = dashController = new AbortController();
    const anchor = captureAnchor(slot);
    setDashboardBusy(slot, true);
    status.textContent = 'Updating analysis…';
    try {
      const data = await api(`results-analytics/academic-years/${encodeURIComponent(year.value)}/dashboard?${qs(Object.fromEntries(params))}`, controller.signal);
      if (token !== dashToken) return;
      slot.innerHTML = window.TalentDashboard.analytics(data, params, activeBranch);
      restoreAnchor(anchor, slot);
      status.textContent = 'Analysis updated.';
    } catch (error) {
      if (token !== dashToken || isAbortError(error)) return;
      // Keep the previous analysis on screen and offer an explicit, retryable error.
      showDashboardError(slot, error);
      status.textContent = 'The analysis could not be updated.';
    } finally {
      if (token === dashToken) { setDashboardBusy(slot, false); if (slot.style) slot.style.minHeight = ''; }
    }
  }
  function programCards(items) {
    return items.length ? `<div class="tp-grid">${items.map(p=>`<article class="tp-card">${programLogo(p)}<h3>${esc(p.name)}</h3><p>${esc(p.description || 'Explore the Program framework and annual evaluation context.')}</p>${link('programs','Open Program',{program_id:p.id})}</article>`).join('')}</div>` : empty('No Programs are available. Ask your Program administrator to configure the first Program.');
  }
  function periods(plans) {
    if (!plans.length) return empty('No annual evaluation plan is available for this context.');
    return plans.map(p=>`<article class="tp-card"><h3>Annual Evaluation Plan ${badge(p.status)}</h3><p>${p.period_count} Periods · ${p.required_period_count} required</p>${p.status==='closed'?note('Closing the Plan does not mean every Student assessment is complete.'):''}<ol class="tp-sequence">${p.periods.map(item=>`<li class="tp-period"><span class="tp-seq">${esc(item.sequence)}</span><div><h3>${esc(item.label)}</h3>${badge(item.is_required?'Required':'Optional')} ${badge(item.status)}<p>${esc(item.planned_start_date || 'Start not set')} — ${esc(item.planned_end_date || 'End not set')}</p>${item.cancellation_reason?`<p>Cancellation reason: ${esc(item.cancellation_reason)}</p>`:''}${item.notes?`<p>${esc(item.notes)}</p>`:''}${Object.hasOwn(item,'cycle')?`<p>Execution: ${esc(item.cycle.title)} · ${badge(item.cycle.status)}</p>${can('talent_assessments.view')?link('assessments','Open assessments',{cycle_id:item.cycle.id}):''}`:''}</div></li>`).join('')}</ol>${!p.periods.length?empty('No Planned Evaluation Periods yet.'):''}</article>`).join('');
  }
  async function render(signal, run) {
    const view=config.view, pid=params.get('program_id'), ay=year.value;
    if (['programs','evaluation-plans','assessments','reviews'].includes(view)) {
      // Reads are bounded like every other request; mutations (PUT/POST/PATCH/
      // DELETE) are intentionally not timed out client-side, because aborting a
      // write that may already have been committed would mislead the user.
      const operationApi=(path,options={})=>{
        const method=String(options.method||'GET').toUpperCase();
        const init={credentials:'same-origin',cache:'no-store',...options,
          headers:{Accept:'application/json','Content-Type':'application/json',...(options.headers||{})},
          body:options.body==null?undefined:typeof options.body==='string'?options.body:JSON.stringify(options.body)};
        return boundedRequest(fetch,path,init,signal,async response=>{
          if(response.redirected||!response.headers.get('content-type')?.includes('application/json'))throw userSafeError('Your session may have ended. Sign in again and reopen this page.');
          const data=await response.json();
          if(!response.ok)throw mapHttpError(response.status,data.code);
          return data;
        },method==='GET'?REQUEST_TIMEOUT_MS:0);
      };
      const ctx={root,view,api:operationApi,can,year,params,programCatalog,notify:message=>{status.textContent=message;},
        navigate:(target,extra)=>{location.href=`/talent/${target}?${qs({academic_year_id:year.value,...extra})}`;}};
      // A direct/bookmarked evaluation-plans deep link resolves into the
      // equivalent Program-workspace context (same program_id/academic_year_id,
      // landing on the embedded #tp-schedule step) client-side only, so it
      // never forces an extra authorization round-trip against a different
      // permission key. A user who cannot also access Programs (holds only
      // talent_evaluation_plans.* permissions, never talent_programs.view)
      // keeps the pre-existing standalone Evaluation Plan workspace exactly
      // as before - this is a real, still-supported access pattern, not a
      // fallback for an error.
      const mergeIntoProgram=view==='evaluation-plans'&&Boolean(pid)&&can('talent_programs.view');
      if(mergeIntoProgram)history.replaceState(null,'',`/talent/programs?${qs({academic_year_id:ay,program_id:pid})}#tp-schedule`);
      const workspace=(view==='programs'||mergeIntoProgram) ? window.TalentProgramWorkspace :
        view==='evaluation-plans' ? window.TalentEvaluationWorkspace : window.TalentOperations;
      if(!workspace||typeof workspace.render!=='function')throw userSafeError('A required page component did not load. Reload the page, or contact your administrator if the problem continues.',{code:'dependency_missing'});
      await workspace.render(ctx);
      return null;
    }
    if (view==='overview') {
      // Evaluation Plan is intentionally not a card here: it is configured
      // only inside a Program's own guided setup (embedded Step 3), never as
      // a second top-level entry point duplicating that configuration.
      const routes=[['programs','Programs','Configure Programs and assessment setup.','talent_programs.view','edit'],['assessments','Assessments','Continue evidence entry in open evaluations.','talent_assessments.view','check'],['analytics','Results & Analytics','Open the executive summary and detailed result views.','talent_analytics.view','eye']];
      const yearLabel=esc(year.options[year.selectedIndex]?.textContent || '');
      const scopedBranchId=params.get('branch_id');
      const scopedBranchName=scopedBranchId&&String(scopedBranchId)===(activeBranch||defaultBranch)?config.branchName:(branch.options?.find?.(o=>String(o.value)===String(scopedBranchId))?.textContent||'');
      const branchLabel=scopedBranchId&&scopedBranchName?` · ${esc(scopedBranchName)}`:'';
      // The page shell (hero copy + action cards) never waits on organization
      // analytics: the headline figures are an independent section with their own
      // loading, empty, unavailable and error states.
      const headlineHtml=can('talent_analytics.view')
        ? slotHtml('tp-hero-stats','headline figures','tp-hero-stats')
        : '<div class="tp-hero-stats"><p class="tp-empty">Headline analytics require the Organization Analytics permission.</p></div>';
      const hero=`<section class="tp-executive-hero"><div class="tp-executive-heading"><span class="tp-executive-icon" aria-hidden="true">${appIcon('eye')}</span><div><p class="tp-eyebrow">Talent &amp; Potential · Academic Year ${yearLabel}${branchLabel}</p><h2>Executive Overview</h2><p>Current, privacy-safe Talent signals for your authorized scope. Open a workspace to act on the detail.</p></div></div>${headlineHtml}</section>`;
      if (can('talent_analytics.view')) {
        const sections=createSections(run,signal);
        sections.add({id:'tp-hero-stats',label:'headline figures',keys:['overview'],build:async()=>{
          const overview=await sections.request('overview',`organization-analytics/overview?${qs({academic_year_id:ay,branch_id:params.get('branch_id')})}`);
          const headline=['distinct_students','frozen_eligible_memberships','completion_coverage','programs_configured'].filter(k=>overview.metrics && Object.hasOwn(overview.metrics,k));
          const icons={distinct_students:'users',frozen_eligible_memberships:'layers',completion_coverage:'check',active_programs:'star',programs_configured:'star'};
          return headline.length ? `<div class="tp-executive-kpis">${headline.map(k=>`<article class="tp-executive-kpi tp-kpi-${esc(k)}"><span class="tp-kpi-icon" aria-hidden="true">${appIcon(icons[k]||'eye')}</span><span class="tp-stat-label">${esc(k==='distinct_students'?'Distinct current Students':labels[k]||human(k))}</span><strong class="tp-stat-value">${metric(overview.metrics[k])}</strong><small>${esc(k==='frozen_eligible_memberships'?'Program participations':'Backend-authoritative')}</small></article>`).join('')}</div>` : '<p class="tp-empty">No headline figures are available for this Academic Year yet.</p>';
        }});
        if(window.TalentDashboard)sections.add({id:'tp-overview-charts',label:'executive charts',keys:['dashboard'],build:async()=>{
          const data=await sections.request('dashboard',`results-analytics/academic-years/${encodeURIComponent(ay)}/dashboard?${qs({branch_id:params.get('branch_id')})}`);
          return window.TalentDashboard.overview(data,{animate:shouldAnimateEntrance()});
        }});
        registerSections(sections);
      }
      return hero+(can('talent_analytics.view')&&window.TalentDashboard?slotHtml('tp-overview-charts','executive charts'):'')+`<section class="tp-overview-command" aria-label="Open a Talent workspace"><div><p class="tp-eyebrow">Continue work</p><h3>Take the next useful action</h3></div><div class="tp-overview-actions">${routes.filter(r=>can(r[3])).map((r,index)=>`<a class="tp-dashboard-action ${index===0?'is-primary':''}" href="${esc(`/talent/${r[0]}?${qs({academic_year_id:ay})}`)}"><span aria-hidden="true">${appIcon(r[4])}</span><span><strong>${esc(r[1])}</strong><small>${esc(r[2])}</small></span><b aria-hidden="true">${chevron}</b></a>`).join('')}</div></section>${can('talent_review_candidates.view')?`<p class="tp-legacy-link">${link('reviews','Legacy Review & Identification History')} <span>Preserved audit history only; not part of the current workflow.</span></p>`:''}`;
    }
    if (view==='programs') {
      if (!pid) return programCards(await api('programs',signal));
      const p=await api(`programs/${encodeURIComponent(pid)}`,signal);
      const frameworks=await api(`programs/${encodeURIComponent(pid)}/frameworks`,signal);
      return `<article class="tp-card"><h3>${esc(p.name)}</h3><p>${esc(p.description)}</p><div class="tp-actions">${can('talent_evaluation_plans.view')?link('evaluation-plans','Evaluation Plan',{program_id:p.id}):''}${can('talent_analytics.view')?link('longitudinal','Follow Periods',{program_id:p.id}):''}</div></article><h3>Assessment setup history</h3><div class="tp-grid">${frameworks.map(f=>`<article class="tp-card">${badge(f.status)}<h3>${esc(f.title)}</h3><p>Saved setup ${esc(f.version_number)}</p><p>${esc(f.summary)}</p></article>`).join('')}</div>${!frameworks.length?empty('No saved assessment setup is available.'):''}`;
    }
    if (view==='evaluation-plans') return periods(await api(`evaluation-plans?${qs({academic_year_id:ay,program_id:pid})}`,signal));
    if (view==='learner-profile') {
      const sid=params.get('student_id');
      if (!sid) return empty('Open a Student Profile from an authorized assessment or the Students view.');
      const data=await api(`learner-profiles/${encodeURIComponent(sid)}`,signal);
      const name=[data.student.first_name,data.student.father_name,data.student.last_name].filter(Boolean).join(' ');
      const titled=value=>human(value).replace(/^./,c=>c.toUpperCase());
      const currentCompleted=a=>a&&a.status==='completed'&&a.is_current!==false;
      const resultText=a=>a&&a.overall_result&&a.overall_result.available!==false&&Number.isFinite(Number(a.overall_result.average))?`${Number(a.overall_result.average).toFixed(1)} / ${esc(a.overall_result.scale_max)}`:'';
      const cycleHtml=c=>{
        const a=c.assessment||{};
        const current=currentCompleted(a);
        const meta=current&&studentIdentity?studentIdentity.metaHtml({classification:a.classification,isTalented:a.is_talented}):'';
        const result=a.status==='completed'&&resultText(a)?`<p>Program result: <strong>${resultText(a)}</strong></p>`:'';
        return `<details><summary>${esc(c.cycle.title)} · ${esc(titled(a.status))}</summary><p>Assessment setup: ${esc(c.framework_version.title)} · Version ${esc(c.framework_version.version_number)}</p>${c.frozen_context?`<p>Historical Branch context recorded · Grade ${esc(c.frozen_context.grade_level)} · ${esc(c.frozen_context.section_display||c.frozen_context.section_name)}</p>`:''}${result}${meta}${(c.competency_results||[]).map(r=>`<div><strong>${esc(r.competency_label||'Competency')}</strong> ${rubricBadge(r.rubric_level)}<p>${esc(r.evidence||'Recorded evidence')}</p></div>`).join('')}</details>`;
      };
      // Legacy Review Candidate / Official Identification history: kept for audit
      // in ONE clearly secondary section, never beside current Classification.
      const legacyRows=data.programs.flatMap(p=>p.academic_years.flatMap(y=>y.cycles.filter(c=>Object.hasOwn(c,'review_candidate')||Object.hasOwn(c,'official_identification')).map(c=>`<li><strong>${esc(p.program.name)} · ${esc(c.cycle.title)}</strong>${Object.hasOwn(c,'review_candidate')?`<p>Legacy review status: ${esc(c.review_candidate?human(c.review_candidate.status):'No recorded result')}</p>`:''}${Object.hasOwn(c,'official_identification')?`<p>Legacy Official Identification decision: ${esc(c.official_identification?human(c.official_identification.decision):'No recorded decision')}</p>`:''}</li>`)));
      const legacySection=legacyRows.length?`<details class="tp-legacy-history"><summary>Legacy Review &amp; Identification History</summary><p>Preserved historical records for audit only. They are not the Student's current Classification or Talented state.</p><ul>${legacyRows.join('')}</ul></details>`:'';
      return `<article class="tp-card"><p class="tp-eyebrow">Learner Profile</p><h3 class="tp-identity-heading">${studentIdentity?studentIdentity.identityHtml({name,learningStyle:data.student.learning_style,showClassification:false}):esc(name)}</h3><p>Program-specific evidence · Historical context preserved</p></article>`+data.programs.map(p=>`<section class="tp-card"><h3>${programLogo(programCatalog.get(String(p.program.id))||p.program)} ${esc(p.program.name)}</h3>${p.academic_years.map(y=>`<h4>${esc(y.academic_year.year_name)}</h4>${y.cycles.map(cycleHtml).join('')}`).join('')}</section>`).join('')+(!data.programs.length?empty('No authorized Talent assessment history is available.'):'')+legacySection+(data.timeline?.length?`<h3>Historical timeline</h3><ol class="tp-sequence">${data.timeline.map(e=>`<li class="tp-period"><span aria-hidden="true">•</span><div><strong>${esc(human(e.event_type))}</strong><p>${esc(e.occurred_at)}</p></div></li>`).join('')}</ol>`:'');
    }
    if (!ay) return empty('Select an Academic Year to explore analytics.');
    const base='organization-analytics/', common={academic_year_id:ay};
    if (params.get('branch_id')) common.branch_id=params.get('branch_id');
    if (params.get('grade_level')) common.grade_level=params.get('grade_level');
    if (view==='longitudinal' && params.get('planning_section_id')) common.planning_section_id=params.get('planning_section_id');
    if (pid && !['longitudinal'].includes(view)) common.program_ids=pid;
    if (view==='analytics') {
      if(!window.TalentDashboard)throw userSafeError('The analytics component did not load. Reload this page.',{code:'dependency_missing'});
      const sections=createSections(run,signal);
      sections.add({id:'tp-dashboard-slot',label:'filtered analysis',keys:['dashboard'],build:async()=>{
        const data=await sections.request('dashboard',`results-analytics/academic-years/${encodeURIComponent(ay)}/dashboard?${qs(Object.fromEntries(params))}`);
        const html=window.TalentDashboard.analytics(data,params,activeBranch);
        if(run===generation)dashboardReady=true;
        return html;
      }});
      registerSections(sections);
      return '<div data-tp-dashboard>'+slotHtml('tp-dashboard-slot','filtered analysis')+'</div>';
    }
    if (view==='portfolio' || view==='branch') {
      if (view==='branch' && !params.get('branch_id')) return empty('Open Branch Results from the Talent Map or Organization Overview.');
      // The primary payload gates the page (failure -> page-level Retry); the two
      // secondary breakdown requests are issued in parallel with it but only their
      // own "patterns" section depends on them, so a slow/failing breakdown never
      // blocks the Program/Branch results themselves.
      const sections=createSections(run,signal);
      const dataReq=sections.request('data',`${base}${view==='portfolio'?'program-portfolio':`branches/${encodeURIComponent(params.get('branch_id'))}`}?${qs(common)}`);
      const gradeMapReq=()=>sections.request('gradeMap',`${base}talent-map?${qs({...common,metric:'completion_coverage',dimension:'program_grade'})}`);
      const branchMapReq=()=>view==='portfolio'?sections.request('branchMap',`${base}talent-map?${qs({...common,metric:'completion_coverage',dimension:'program_branch'})}`):Promise.resolve(null);
      gradeMapReq(); branchMapReq();
      const data=await dataReq;
      const framing=view==='portfolio'
        ? lede('How are Programs progressing?','Compare factual participation and evaluation activity for the selected Academic Year. Open a Program to follow its evaluation periods.')
        : lede(`What is happening in ${data.branch?esc(data.branch.name):'this Branch'}?`,'See participation and evaluation activity in this historical Branch context. This view does not rank Branches.','branch');
      const programRows=(data.programs||[]).map(r=>`<article class="tp-result-card"><header>${programLogo(programCatalog.get(String(r.program.id))||r.program)}<div><p class="tp-eyebrow">${view==='branch'?'Branch Program':'Program'}</p><h3>${esc(r.program.name)}</h3></div></header>${progressVisual(r.metrics.completion_coverage,'Completion')}${progressVisual(r.metrics.started_coverage,'Assessments started')}${Object.hasOwn(r.metrics,'required_period_execution')?progressVisual(r.metrics.required_period_execution,'Required evaluations run'):''}<div class="tp-mini-metrics">${['frozen_eligible','assessment_started'].filter(k=>Object.hasOwn(r.metrics,k)).map(k=>`<span><b>${metric(r.metrics[k])}</b>${esc(labels[k])}</span>`).join('')}</div><div class="tp-actions">${link('longitudinal','Progress Over Time',{program_id:r.program.id,...(view==='branch'?{branch_id:data.branch.id}:{})})}${can('talent_analytics.view_students')?link('students','View Students',{program_id:r.program.id,...(view==='branch'?{branch_id:data.branch.id}:{})}):''}</div></article>`).join('');
      sections.add({id:'tp-patterns-slot',label:'grade and Branch breakdowns',keys:['gradeMap','branchMap'],build:async()=>{
        const [gradeMap,branchMap]=await Promise.all([gradeMapReq(),branchMapReq()]);
        const gradeItems=(gradeMap.columns||[]).map(item=>({label:item.label,cell:(gradeMap.column_totals||[]).find(total=>String(total.grade_level)===String(item.id))}));
        const branchItems=(branchMap?.columns||[]).map(item=>({label:item.label,cell:(branchMap.column_totals||[]).find(total=>String(total.branch_id)===String(item.id)),href:`/talent/branch?${qs({academic_year_id:ay,branch_id:item.id,...(pid?{program_id:pid}:{})})}`}));
        return `<div class="tp-pattern-grid"><section><div class="tp-section-heading"><div><p class="tp-eyebrow">Grades</p><h3>Assessment progress by Grade</h3></div></div>${gradeBars(gradeItems,'Assessment progress')}</section>${branchMap?`<section><div class="tp-section-heading"><div><p class="tp-eyebrow">Branches</p><h3>Assessment progress by Branch</h3></div></div>${branchBars(branchItems)}</section>`:''}</div>`;
      }});
      registerSections(sections);
      return framing+`<div class="tp-context-banner"><strong>${view==='branch'?esc(data.branch.name):'All authorized Programs'}</strong><span>${esc(year.options[year.selectedIndex]?.textContent||'')}</span></div>${slotHtml('tp-patterns-slot','grade and Branch breakdowns')}<div class="tp-result-grid">${programRows}</div>`+(!data.programs.length?empty('No configured Programs are available for this context.'):'')+`<details class="tp-card tp-detail-summary"><summary>Detailed totals</summary>${cards(data.totals)}</details>`;
    }
    if (view==='talent-map') {
      const selectedDimension=dimension.value;
      const data=await api(`${base}talent-map?${qs({...common,metric:metricSelect.value,dimension:selectedDimension})}`,signal);
      const byBranch=selectedDimension==='program_branch';
      const coordinateKey=byBranch?'branch_id':'grade_level';
      const title=`Programs by ${byBranch?'Branch':'Grade'}: ${labels[data.metric]||'Selected result'}`;
      const cellFor=(r,c)=>data.cells.find(x=>x.coordinates.program_id===r.id&&String(x.coordinates[coordinateKey])===String(c.id));
      const drillFor=(r,c)=>byBranch&&cellFor(r,c)?.state==='visible'?link('branch','Open Branch',{branch_id:c.id}):null;
      return lede('Talent Map',`See one factual result across Programs and ${byBranch?'Branches':'Grades'}. Choose a visible Branch cell to continue.`)+note('Color strength is used only for visible percentages. Zero, no data, and privacy-protected results each have a separate label and appearance. Protected values never shape color or size.')+matrix(title,'Program',data.columns,data.rows,cellFor,r=>data.row_totals.find(x=>x.program_id===r.id),c=>data.column_totals.find(x=>String(x[coordinateKey])===String(c.id)),data.organization_total,drillFor);
    }
    if (view==='overlap') {
      const data=await api(`${base}participation-overlap?${qs(common)}`,signal);
      return lede('Students Across Programs','See how many distinct Students participate in each pair of Programs. Read across a row and down a column to find the shared count.','overlap')+note('The diagonal shows Students in one Program. Other cells show Students participating in both Programs. These counts do not show similarity, correlation, ability, or a combined score.')+overlapMatrix(data,p=>link('portfolio','Open Program results',{program_id:p.id}));
    }
    if (view==='longitudinal') {
      if (!pid) return empty('Choose one Program to view its evaluation periods within this Academic Year.');
      const data=await api(`${base}programs/${encodeURIComponent(pid)}/longitudinal?${qs({...common,metric:metricSelect.value})}`,signal);
      const labelsById=new Map(data.points.map(p=>[p.evaluation_period.id,p.evaluation_period.label]));
      const comparisons=(data.comparisons||[]).map(c=>`<article class="tp-comparison ${c.state==='comparable'?'is-comparable':'is-limited'}"><span aria-hidden="true">${c.state==='comparable'?'&#10003;':'i'}</span><div><strong>${esc(labelsById.get(c.evaluation_period_ids[0])||'Earlier period')} to ${esc(labelsById.get(c.evaluation_period_ids[1])||'Later period')}</strong><p>${c.state==='comparable'?'These results can be viewed side by side. No change claim is calculated.':esc(friendlyReason(c.reason_code))}</p></div></article>`).join('');
      return lede(`Progress Over Time for ${esc(data.program.name)}`,`Follow ordered evaluation periods in ${esc(data.academic_year.label)}. Each point keeps its own recorded assessment context and privacy decision.`)+note('This view presents each period as recorded. It does not calculate improvement, decline, percent change, or Student growth.')+periodVisual(data)+(!data.points.length?empty('No planned evaluation periods are available.'):'')+(comparisons?`<section aria-labelledby="tp-comparison-title"><div class="tp-section-heading"><div><p class="tp-eyebrow">Context check</p><h3 id="tp-comparison-title">Can periods be viewed side by side?</h3></div></div><div class="tp-comparison-list">${comparisons}</div></section>`:'');
    }
    if (view==='students') {
      const [data,contextMap]=await Promise.all([
        api(`${base}students?${qs({...common,offset:params.get('offset')||0})}`,signal),
        api(`${base}talent-map?${qs({...common,metric:'frozen_eligible',dimension:'program_branch'})}`,signal).catch(()=>({rows:[],columns:[]})),
      ]);
      if (data.state && data.state!=='visible') return metric(data);
      const programNames=new Map((contextMap.rows||[]).map(item=>[String(item.id),item.label]));
      const branchNames=new Map((contextMap.columns||[]).map(item=>[String(item.id),item.label]));
      const items=data.items||[];
      const matrixPrograms=[...new Set(items.flatMap(r=>r.contexts.map(c=>String(c.program_id))))].map(id=>({id,label:programNames.get(id)||`Program ${id}`}));
      const currentResultFor=(student,programId)=>{
        const matches=student.contexts.filter(c=>String(c.program_id)===String(programId)&&c.overall_result&&c.assessment_state==='completed');
        return matches.length?matches[matches.length-1]:null;
      };
      const crossProgramMatrix=matrixPrograms.length
        ? `<section aria-labelledby="tp-cross-program-title"><div class="tp-section-heading"><div><p class="tp-eyebrow">Students Across Programs</p><h3 id="tp-cross-program-title">Program results by Student</h3></div><p>Each cell is one Program result with its own automatic Classification. TIS never combines these cells into a universal Talent score or label.</p></div><div class="tp-table-wrap"><table class="tp-compact-table tp-cross-program-matrix"><thead><tr><th>Student</th>${matrixPrograms.map(p=>`<th>${esc(p.label)}</th>`).join('')}</tr></thead><tbody>${items.map(student=>`<tr><th scope="row">${identityHtml({name:student.display_name,learningStyle:student.learning_style,showClassification:false})}</th>${matrixPrograms.map(p=>{const row=currentResultFor(student,p.id);if(!row)return '<td><span class="tp-no-result">—</span></td>';const result=row.overall_result;const pct=Math.max(0,Math.min(100,Number(result.normalized_percent||0)));return `<td><a class="tp-result-cell" style="--tp-result-pct:${pct}" href="/talent/students?academic_year_id=${encodeURIComponent(ay)}&program_id=${encodeURIComponent(p.id)}" aria-label="${esc(p.label)} result ${Number(result.average).toFixed(1)} out of ${esc(result.scale_max)}"><strong>${Number(result.average).toFixed(1)}</strong><span>/${esc(result.scale_max)}</span><i aria-hidden="true"></i></a>${classificationMeta(row.classification,row.is_talented)}</td>`;}).join('')}</tr>`).join('')}</tbody></table></div></section>`
        : '';
      const studentCards=items.map(r=>`<article class="tp-student-card"><header><span class="tp-avatar" aria-hidden="true">${initials(r.display_name)}</span><div><h3>${identityHtml({name:r.display_name,learningStyle:r.learning_style,showClassification:false})}</h3>${r.can_view_learner_profile?link('learner-profile','Open Student Profile',{student_id:r.student_id}):''}</div></header><div class="tp-student-contexts">${r.contexts.map(c=>`<section><div class="tp-context-line"><span class="tp-context-chip">${esc(programNames.get(String(c.program_id))||'Program context')}</span><span class="tp-context-chip">${esc(branchNames.get(String(c.branch_id))||'Historical Branch')}</span><span class="tp-context-chip">Grade ${esc(c.grade_level)}</span><span class="tp-context-chip">${esc(c.section_name)}</span><span class="tp-context-chip">${esc(human(c.assessment_state))}</span></div>${c.overall_result?`<div class="tp-student-program-result"><strong>${Number(c.overall_result.average).toFixed(1)} / ${esc(c.overall_result.scale_max)}</strong><div class="tp-result-meter"><i style="width:${Math.max(0,Math.min(100,Number(c.overall_result.normalized_percent||0)))}%"></i></div></div>`:''}${classificationMeta(c.classification,c.is_talented)}<small>This context comes from the recorded Assessment and stays with that historical Evaluation.</small></section>`).join('')}</div></article>`).join('');
      return lede('Students Across Programs','Browse Students across authorized Program contexts and compare each Program result without combining different Talent domains.')+note('A Student may have separate results in Mental Math, Performing Arts, Reading, or other Programs. Each remains its own evidence and Classification context.')+crossProgramMatrix+`<div class="tp-student-grid">${studentCards||empty('No Students are available for this context.')}</div>`+(data.pagination?.has_more?`<nav class="tp-pagination" aria-label="Student pages">${link('students','Next page',{...Object.fromEntries(params),offset:Number(params.get('offset')||0)+data.pagination.limit})}</nav>`:'');
    }
    return empty('This view is unavailable.');
  }
  const breadcrumbCurrent = document.getElementById('tp-breadcrumb-current');
  function updateBreadcrumb() {
    if (!breadcrumbCurrent) return;
    const base = document.title.split(' · ')[0] || config.view;
    const chosenProgram = !program.parentElement.hidden && program.value ? program.options[program.selectedIndex]?.textContent : '';
    breadcrumbCurrent.textContent = chosenProgram ? `${base} · ${chosenProgram}` : base;
  }
  function showPageError(error, retry = load) {
    root.innerHTML = errorPanel(error);
    root.setAttribute('aria-busy', 'false'); root.classList.remove('is-refreshing');
    const button = root.querySelector('#tp-retry');
    if (button) button.addEventListener('click', () => (error && error.code === 'dependency_missing') ? location.reload() : retry());
    status.textContent = 'View could not be loaded.';
  }
  // load() ALWAYS drives the current generation to a terminal state: rendered
  // content, an explicit empty/unavailable state, or the page error panel with
  // Retry. Only a superseded (stale) generation returns silently - the newer
  // generation owns the placeholder, aria-busy and status from that point on.
  async function load() {
    const run=++generation; controller?.abort(); controller=new AbortController();
    cancelDashboard(); dashboardReady=false; let anchor=null;
    // New render generation invalidates any prior rubric read ownership so a
    // Program/Academic-Year change can never reuse a stale shared promise.
    if(rubricRequest && typeof rubricRequest.reset==='function') rubricRequest.reset();
    const signal=controller.signal; activeSections=null;
    try {
      updateBreadcrumb();
      const hasRenderedContent=Boolean(root.children?.length && !root.querySelector?.('.tp-empty[data-initial-loading]'));
      // A refresh over rendered content keeps the region's height and restores the reader's
      // position (and focused control) so re-rendering never throws the page to the top.
      anchor=hasRenderedContent?captureAnchor(root):null;
      if(!hasRenderedContent) root.innerHTML=`<div class="tp-empty" data-initial-loading role="presentation">${sectionLoadingHtml('this view')}</div>`;
      root.setAttribute('aria-busy','true'); root.classList.add('is-refreshing'); status.textContent='Refreshing view…';
      const html=await render(signal,run);
      if(run!==generation) return;
      if(html!==null)root.innerHTML=html;
      root.classList.remove('is-refreshing');
      const sections=activeSections;
      if(sections && sections.run===run){
        const results=await sections.start();
        if(run===generation)status.textContent=results.every(Boolean)?'View loaded.':'View loaded. Some sections could not be loaded.';
      } else status.textContent='View loaded.';
    } catch(error) {
      if(run===generation) showPageError(error);
    } finally {
      if(run===generation){
        root.setAttribute('aria-busy','false');root.classList.remove('is-refreshing');
        if(anchor)restoreAnchor(anchor,root);
      }
    }
  }
  // Selections auto-apply (no required "Apply context" click); a short debounce
  // collapses rapid multi-dropdown changes into one reload. The visible Refresh
  // button (form submit) applies immediately, bypassing the debounce.
  const AUTO_APPLY_DEBOUNCE_MS = 250;
  // Ticking several comparison groups in a row collapses into one background request.
  const COMPARISON_DEBOUNCE_MS = 350;
  let autoApplyTimer = null;
  function applyContext() {
    // Results & Analytics: the dashboard refetches in the background (no page-wide reload).
    if(config.view==='analytics'&&window.TalentDashboard&&dashboardReady){params.set('academic_year_id',year.value);history.replaceState(null,'',`${location.pathname}?${params}`);refreshDashboard();return;}
    try {
      params.set('academic_year_id',year.value);
      if(!program.parentElement.hidden){program.value?params.set('program_id',program.value):params.delete('program_id');}
      if(!branch.parentElement.hidden){
        // Under a single-Branch global scope the Branch can only be that Branch;
        // otherwise the blank option is "All Branches" (organization-wide scope).
        if(activeBranch){params.set('branch_id',activeBranch);params.delete('branch_scope');}
        else if(branch.value){params.set('branch_id',branch.value);params.delete('branch_scope');}
        else{params.delete('branch_id');params.set('branch_scope','all');}
      }
      if(BRANCH_SCOPED_VIEWS.includes(config.view)){if(activeBranch||defaultBranch)params.set('scope_branch_id',activeBranch||defaultBranch);else params.delete('scope_branch_id');}
      if(!grade.parentElement.hidden){grade.value?params.set('grade_level',grade.value):params.delete('grade_level');}
      if(!section.parentElement.hidden){section.value?params.set('planning_section_id',section.value):params.delete('planning_section_id');}
      if(!metricSelect.parentElement.hidden)params.set('metric',metricSelect.value);
      if(!dimension.parentElement.hidden)params.set('dimension',dimension.value);
      if(!classificationSelect.parentElement.hidden){classificationSelect.value?params.set('classification',classificationSelect.value):params.delete('classification');}
      else if(!window.TalentDashboard||config.view!=='analytics')params.delete('classification');
      params.delete('offset');
      history.replaceState(null,'',`${location.pathname}?${params}`);
      syncNavigation();
    } catch {
      // URL/navigation bookkeeping must never prevent the reload itself.
    }
    load();
  }
  // Classification is Program-bound (talent_results_analytics_service's
  // classification route requires a program_id path segment), so its filter
  // control is progressively shown only once a Program is selected on the
  // analytics view and cleared/hidden otherwise - it can never be submitted
  // for a stale/no-longer-selected Program.
  function updateClassificationVisibility() {
    const field=document.getElementById('tp-classification-field');
    if(!field)return;
    const show=config.view==='analytics' && Boolean(program.value);
    field.hidden=!show;
    if(!show){classificationSelect.value='';params.delete('classification');}
  }
  // Event wiring lives in bindEvents() so that a failure here is caught by boot()
  // and shown as a retryable error instead of aborting the script before init().
  let eventsBound = false;
  function bindEvents() {
    if (eventsBound) return;
    eventsBound = true;
    window.TalentCharts?.bind(root);
    const publishDashboard=(next,delay=0)=>{
      if(activeBranch)next.set('branch_id',activeBranch);
      else{
        // Organization actor: keep the default-Branch marker; a blank Branch is an explicit All Branches.
        if(defaultBranch)next.set('scope_branch_id',defaultBranch);
        if(!next.get('branch_id'))next.set('branch_scope','all');else next.delete('branch_scope');
      }
      next.set('academic_year_id',year.value);
      for(const k of [...params.keys()])params.delete(k);
      for(const [k,v] of next)params.set(k,v);
      history.replaceState(null,'',`${location.pathname}?${params}`);
      // Never replace the root: refresh in the background, keeping what is on screen.
      clearTimeout(dashTimer);
      if(delay>0)dashTimer=setTimeout(refreshDashboard,delay);else refreshDashboard();
    };
    root.addEventListener('change',event=>{
      const f=event.target.closest?.('[data-dashboard-filters]');
      if(!f||!event.target.name)return;
      const el=event.target;
      if(el.name==='compare_ids'){
        const chosen=Array.from(f.querySelectorAll('input[name="compare_ids"]:checked')).map(i=>i.value);
        if(chosen.length>6){el.checked=false;status.textContent='Choose up to six comparison groups.';return;}
        publishDashboard(window.TalentDashboard.change(params,el.name,chosen.join(',')),COMPARISON_DEBOUNCE_MS);
      }else publishDashboard(window.TalentDashboard.change(params,el.name,el.value));
    });
    root.addEventListener('submit',event=>{
      if(!event.target.matches?.('[data-dashboard-filters]'))return;
      event.preventDefault();publishDashboard(new URLSearchParams(params));
    });
    root.addEventListener('click',event=>{
      if(event.target.closest?.('[data-dashboard-retry]')){refreshDashboard();return;}
      if(!event.target.closest?.('[data-dashboard-clear]'))return;
      publishDashboard(new URLSearchParams({academic_year_id:year.value}));
    });
    form.addEventListener('submit',event=>{event.preventDefault();clearTimeout(autoApplyTimer);applyContext();});
    form.addEventListener('change',async event=>{
      if(!event.target.matches('select'))return;
      try {
        if(event.target===year&&config.view==='analytics'&&window.TalentDashboard){
          publishDashboard(new URLSearchParams({academic_year_id:year.value}));return;
        }
        if(event.target===year && !branch.parentElement.hidden) await refreshPlanningBranches();
        else if(event.target===branch && !grade.parentElement.hidden) await refreshPlanningGrades();
        else if(event.target===grade && !section.parentElement.hidden) await refreshPlanningSections();
        else if(event.target===program && config.view==='analytics') updateClassificationVisibility();
      } catch {
        // A failed selector refresh must never swallow the requested reload.
      }
      clearTimeout(autoApplyTimer);
      autoApplyTimer=setTimeout(applyContext,AUTO_APPLY_DEBOUNCE_MS);
    });
    // Section-level Retry (delegated: sections are re-rendered independently).
    root.addEventListener('click',event=>{
      const button=event.target && event.target.closest ? event.target.closest('[data-tp-section-retry]') : null;
      if(!button)return;
      event.preventDefault();
      if(activeSections)activeSections.retry(button.getAttribute('data-tp-section-retry'));
    });
    window.addEventListener('pagehide',()=>{controller?.abort();cancelDashboard();root.replaceChildren();});
    // A page restored from the back/forward cache was emptied by pagehide above.
    window.addEventListener('pageshow',event=>{if(event.persisted)load();});
  }
  async function refreshPlanningSections() {
    if(section.parentElement.hidden)return;
    const previous=params.get('planning_section_id')||section.value;
    if(!branch.value||!grade.value){section.disabled=true;section.innerHTML='<option value="">Choose a Branch and Grade first</option>';params.delete('planning_section_id');return;}
    try {
      const items=await api(`programs/planning-sections?${qs({academic_year_id:year.value,branch_id:branch.value,grade_level:grade.value})}`,undefined,CONTEXT_REQUEST_TIMEOUT_MS);
      section.innerHTML=items.length?'<option value="">All Sections</option>'+items.map(item=>`<option value="${esc(item.id)}">${esc(item.section_display||item.section_name)}</option>`).join(''):'<option value="">No Sections configured for this Grade.</option>';
      section.disabled=!items.length;
      if(previous&&items.some(item=>String(item.id)===String(previous)))section.value=previous;else params.delete('planning_section_id');
    } catch {section.disabled=true;section.innerHTML='<option value="">No Sections configured for this Grade.</option>';params.delete('planning_section_id');}
  }
  async function refreshPlanningGrades() {
    const previous=params.get('grade_level')||grade.value;
    try {
      const configuredGrades=await api(`programs/planning-grades?${qs({academic_year_id:year.value,...(branch.value?{branch_id:branch.value}:{})})}`,undefined,CONTEXT_REQUEST_TIMEOUT_MS);
      grade.innerHTML='<option value="">All Grades</option>'+configuredGrades.map(item=>`<option value="${item}">${item==='KG'?'KG':`Grade ${item}`}</option>`).join('');
      if(previous&&configuredGrades.includes(previous))grade.value=previous;else params.delete('grade_level');
    } catch {grade.innerHTML='<option value="">All Grades</option>';params.delete('grade_level');}
    await refreshPlanningSections();
  }
  async function refreshPlanningBranches() {
    const previous=params.get('branch_id')||branch.value;
    try {
      const items=await api(`programs/planning-branches?${qs({academic_year_id:year.value})}`,undefined,CONTEXT_REQUEST_TIMEOUT_MS);
      // Under a single-Branch global scope only that Branch is offered (no All Branches).
      const offered=activeBranch?items.filter(item=>String(item.id)===activeBranch):items;
      branch.innerHTML=(!activeBranch&&offered.length>1?'<option value="">All Branches</option>':'')+offered.map(item=>`<option value="${esc(item.id)}">${esc(item.name)}</option>`).join('');
      if(activeBranch){branch.value=activeBranch;params.set('branch_id',activeBranch);}
      else if(previous&&items.some(item=>String(item.id)===String(previous)))branch.value=previous;
      else if(params.get('branch_scope')==='all'&&items.length>1){branch.value='';params.delete('branch_id');}
      else if(items.length===1){branch.value=String(items[0].id);params.set('branch_id',String(items[0].id));}
      else params.delete('branch_id');
    } catch {
      if(activeBranch){branch.innerHTML=`<option value="${esc(activeBranch)}">${esc(config.branchName||'Active Branch')}</option>`;branch.value=activeBranch;params.set('branch_id',activeBranch);}
      else{branch.innerHTML='<option value="">All Branches</option>';params.delete('branch_id');}
    }
    if(!grade.parentElement.hidden)await refreshPlanningGrades();
  }
  async function init() {
    reconcileBranchScope();
    if(config.view==='learner-profile'||params.has('assessment_id'))form.hidden=true;
    if (params.has('academic_year_id') && [...year.options].some(o=>o.value===params.get('academic_year_id'))) year.value=params.get('academic_year_id');
    const metricViews=['talent-map','longitudinal'];
    if(metricViews.includes(config.view)) {
      document.getElementById('tp-metric-field').hidden=false;
      const metrics=['frozen_eligible','completed','completion_coverage','assessment_started','started_coverage'];
      metricSelect.innerHTML=metrics.map(m=>`<option value="${m}">${labels[m]}</option>`).join('');
      metricSelect.value=metrics.includes(params.get('metric'))?params.get('metric'):'completion_coverage';
    }
    if(config.view==='analytics' && !window.TalentDashboard) {
      document.getElementById('tp-metric-field').hidden=false;
      const metrics=branchComparisonMetricOptions(can('talent_review_candidates.view'),can('talent_official_identifications.view'));
      metricSelect.innerHTML=metrics.map(([value,label])=>`<option value="${value}">${label}</option>`).join('');
      metricSelect.value=metrics.some(([value])=>value===params.get('metric'))?params.get('metric'):'current_overall_progress';
    }
    if(config.view==='talent-map') {
      document.getElementById('tp-dimension-field').hidden=false;
      dimension.value=params.get('dimension')==='program_grade'?'program_grade':'program_branch';
    }
    // Selector context (Branch/Grade/Section lookups and the Program list) is
    // loaded in parallel and can never hold the page hostage: each lookup is
    // individually bounded and boot proceeds after INIT_CONTEXT_DEADLINE_MS at the
    // latest. A lookup that fails simply leaves its selector at its neutral default.
    const planningContext=async()=>{
      if(['overview','assessments','portfolio','talent-map','overlap','longitudinal','students','reviews'].includes(config.view)) {
        document.getElementById('tp-branch-field').hidden=false;
        await refreshPlanningBranches();
      }
      if(['talent-map','longitudinal','students','reviews'].includes(config.view)) {
        document.getElementById('tp-grade-field').hidden=false;
        if(['longitudinal','reviews'].includes(config.view))document.getElementById('tp-section-field').hidden=false;
        await refreshPlanningGrades();
      }
    };
    const programContext=async()=>{
      if(['programs','evaluation-plans','assessments','reviews','branch','longitudinal','portfolio','talent-map','students','learner-profile'].includes(config.view)&&can('talent_programs.view')) {
        // Programs uses its in-content searchable list as the selection surface
        // until a Program is explicitly opened. Student Assessments and the
        // other Program-aware views use this compact selector as their own local
        // filter; top-level navigation never inherits a Program from a previous
        // page.
        const showProgramField = config.view!=='programs' || Boolean(params.get('program_id'));
        document.getElementById('tp-program-field').hidden=!showProgramField;
        if(showProgramField){
          try {const items=await api('programs',undefined,CONTEXT_REQUEST_TIMEOUT_MS);programCatalog=new Map(items.map(item=>[String(item.id),item]));program.innerHTML='<option value="">Choose a Program</option>'+items.map(p=>`<option value="${esc(p.id)}">${esc(p.name)}</option>`).join('');program.value=resolveProgramSelection(items,params.get('program_id'));}
          catch {document.getElementById('tp-program-field').hidden=true;}
        }else{
          programCatalog=new Map();
        }
      }
      applyAnalyticsClassification();
    };
    let deadline;
    await Promise.race([
      Promise.all([planningContext().catch(()=>{}),programContext().catch(()=>{})]),
      new Promise(resolve=>{deadline=setTimeout(resolve,INIT_CONTEXT_DEADLINE_MS);}),
    ]);
    clearTimeout(deadline);
    applyAnalyticsClassification();
    syncNavigation();
    await load();
  }
  function applyAnalyticsClassification() {
    if(config.view!=='analytics'||window.TalentDashboard)return;
    classificationSelect.value=CLASSIFICATION_LABELS.includes(params.get('classification'))?params.get('classification'):'';
    updateClassificationVisibility();
  }
  // Outermost guarded boot. The server-rendered "Loading your authorized
  // workspace" placeholder is replaced deterministically as soon as this script
  // runs, and any failure of event wiring or initialization (including a
  // synchronous exception) ends in an explicit error state with Retry - it can
  // never escape as an unhandled rejection and leave the original loader behind.
  async function boot() {
    try {
      root.innerHTML=`<div class="tp-empty" data-initial-loading role="presentation">${sectionLoadingHtml('this view')}</div>`;
      root.setAttribute('aria-busy','true');
      bindEvents();
      await init();
    } catch(error) {
      generation++; controller?.abort();
      showPageError(error, boot);
    }
  }
  boot();
})();
