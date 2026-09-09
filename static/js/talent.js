/* M11 presentation only: authoritative API projections, never reconstructed metrics. */
(() => {
  'use strict';
  const labels = {
    programs_configured:'Programs configured', active_programs:'Active Programs',
    frozen_eligible_memberships:'Students participating', frozen_eligible:'Students participating',
    completed:'Completed evaluations', completion_coverage:'Completion',
    assessment_started:'Assessments started', started_coverage:'Assessment-started coverage',
    required_period_execution:'Required evaluations run', candidate_membership_count:'Review Candidate activity',
    candidate_count:'Review Candidate activity', candidate_of_eligible:'Review Candidate coverage',
    identified_count:'Official Identification activity', identified_of_eligible:'Identification coverage',
    participation_overlap:'Distinct participating Students',
  };
  const states = {suppressed:'Protected for privacy', complementary_suppressed:'Protected for privacy',
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
  function kpiCard(key, cell, href='', context='') {
    const body=`<article class="tp-kpi${href?' tp-kpi-link':''}"><span class="tp-kpi-label">${esc(labels[key]||human(key))}</span><div class="tp-kpi-value">${metric(cell)}</div>${context?`<p>${esc(context)}</p>`:''}${href?`<a class="tp-card-hit" href="${href}" aria-label="Explore ${esc(labels[key]||human(key))}"><span>Explore</span><span aria-hidden="true">&rarr;</span></a>`:''}</article>`;
    return body;
  }
  const friendlyReason = reason => ({missing_cycle:'An evaluation cycle has not been linked',cycle_not_authoritative:'The linked cycle is not open or closed',cancelled_period:'This evaluation period was cancelled',no_frozen_population:'No frozen Student group is available',metric_unavailable:'This result is not available for the selected measure',framework_changed:'The Program framework changed between these periods',privacy_protected:'One or both results are protected for privacy'}[reason] || 'These periods cannot be compared');
  const errorPanel = error => `<div class="tp-error"><h3>${error.status===403?'Permission denied':error.status===503?'Analytics unavailable':'Unable to load view'}</h3><p>${esc(error.message)}</p><button type="button" id="tp-retry">Retry</button></div>`;
  const lede = (title, text, tone='') => `<div class="tp-section-lede${tone?` tp-tone-${tone}`:''}"><svg aria-hidden="true" viewBox="0 0 24 24" width="22" height="22" fill="none" stroke="currentColor" stroke-width="1.8"><circle cx="12" cy="12" r="9"/><path d="M12 8v5"/><path d="M12 16h.01"/></svg><div><h3>${esc(title)}</h3><p>${esc(text)}</p></div></div>`;
  const initials = name => esc(String(name||'?').trim().split(/\s+/).slice(0,2).map(w=>w[0]||'').join('').toUpperCase() || '?');
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
      <span class="tp-legend-item"><span class="tp-legend-swatch tp-protected-swatch" aria-hidden="true"></span>Protected for privacy (no value or magnitude shown)</span>
      <span class="tp-legend-item"><span class="tp-legend-swatch" style="background:var(--app-surface);border-style:dashed" aria-hidden="true"></span>No data (no authoritative population - not a privacy decision)</span>
    </div>`;
  }
  function matrixCellHtml(cell, rowLabel, colLabel, drill) {
    const state = cell && cell.state;
    const isProtected = state && privacyStates.has(state);
    const isNoData = state === 'no_data' || !cell;
    const heat = (isProtected || isNoData) ? 0 : heatBucket(cell);
    const cls = `tp-matrix-cell tp-heat-${heat}${isProtected?' tp-protected-cell':''}${isNoData?' tp-nodata-cell':''}`;
    const explanation=isProtected?'Protected for privacy; no value is shown':isNoData?'No data is available for this context':'This result is available';
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
    return `<div class="tp-matrix-wrap"><div class="tp-matrix" role="grid" aria-label="Students participating across Programs" style="grid-template-columns:190px repeat(${count-1},minmax(150px,1fr))">${header}${rows}</div></div>`;
  }
  function periodVisual(data) {
    const ratePoints=data.points.filter(p=>p.metric_result?.state==='visible'&&typeof p.metric_result.percentage==='number');
    const plot=ratePoints.length ? `<div class="tp-period-chart" role="img" aria-label="${esc(labels[data.metric])} across visible evaluation periods">${data.points.map(p=>{
      const cell=p.metric_result;
      if(cell?.state!=='visible'||typeof cell.percentage!=='number')return `<div class="tp-chart-slot tp-chart-unavailable"><span>${esc(p.evaluation_period.label)}</span><i aria-hidden="true"></i><small>${esc(states[cell?.state]||'Not available')}</small></div>`;
      const height=Math.max(4,Math.min(100,cell.percentage));
      return `<div class="tp-chart-slot"><span>${esc(p.evaluation_period.label)}</span><i style="height:${height}%" aria-hidden="true"></i><strong>${number(cell.percentage)}%</strong></div>`;
    }).join('')}</div>` : '';
    return plot+`<ol class="tp-sequence tp-period-grid">${data.points.map(p=>`<li class="tp-period"><span class="tp-seq">${esc(p.evaluation_period.sequence)}</span><div><h3>${esc(p.evaluation_period.label)}</h3>${badge(p.evaluation_period.status)}<p>${esc(labels[data.metric])}</p>${metric(p.metric_result)}${p.no_data_reason?`<p class="tp-state-explanation">${esc(friendlyReason(p.no_data_reason))}</p>`:''}</div></li>`).join('')}</ol>`;
  }
  // Small pure boundary exported for privacy and injection regression tests.
  if (typeof module !== 'undefined' && module.exports) module.exports = {metric, esc, heatBucket, matrix, matrixCellHtml, matrixLegend, lede, initials, badge, table, cards, progressVisual, kpiCard, friendlyReason, overlapMatrix, periodVisual, errorPanel};
  if (typeof document === 'undefined') return;
  const configNode = document.getElementById('tp-config');
  if (!configNode) return;
  const config = JSON.parse(configNode.textContent), permissions = config.permissions;
  const root = document.getElementById('tp-content'), status = document.getElementById('tp-status');
  const form = document.getElementById('tp-filters'), year = document.getElementById('tp-year');
  const program = document.getElementById('tp-program'), metricSelect = document.getElementById('tp-metric');
  const dimension = document.getElementById('tp-dimension');
  let params = new URLSearchParams(location.search), generation = 0, controller;
  const can = key => permissions[key] === true;
  const qs = values => new URLSearchParams(Object.entries(values).filter(([,v]) => v !== '' && v != null)).toString();
  const link = (view, text, extra={}) => `<a target="_self" href="/talent/${view}?${esc(qs({academic_year_id:year.value,...extra}))}">${esc(text)} →</a>`;
  function syncNavigation() {
    document.querySelectorAll('.tp-nav a, .tp-results-nav a').forEach(a=>{
      const next=new URL(a.href); next.search=qs({academic_year_id:year.value,program_id:params.get('program_id'),metric:params.get('metric')});a.href=next.href;a.target='_self';
    });
  }
  async function api(path, signal) {
    const response = await fetch(`/api/talent/${path}`,{credentials:'same-origin',cache:'no-store',headers:{Accept:'application/json'},signal});
    if (response.redirected || !response.headers.get('content-type')?.includes('application/json')) throw Object.assign(new Error('Your session may have ended. Sign in again, then reopen this view.'),{status:401});
    const data = await response.json();
    if (!response.ok) {
      const message = response.status === 403 ? 'This view is not available for your permissions or selected scope.' :
        response.status === 404 ? 'This record is unavailable in your authorized scope.' :
        response.status === 503 ? 'Analytics is not available in this environment. Its governed policy configuration must be completed before data can be shown.' :
        response.status === 400 || response.status === 422 ? 'This context cannot be displayed. Check the selected Program and Academic Year.' :
        'This view could not be loaded. Retry, or contact your administrator if the problem continues.';
      throw Object.assign(new Error(message),{status:response.status});
    }
    return data;
  }
  function programCards(items) {
    return items.length ? `<div class="tp-grid">${items.map(p=>`<article class="tp-card">${badge(p.status)}<h3>${esc(p.name)}</h3><p>${esc(p.description || 'Explore the Program framework and annual evaluation context.')}</p>${link('programs','Open Program',{program_id:p.id})}</article>`).join('')}</div>` : empty('No Programs are available. Ask your Program administrator to configure the first Program.');
  }
  function periods(plans) {
    if (!plans.length) return empty('No annual evaluation plan is available for this context.');
    return plans.map(p=>`<article class="tp-card"><h3>Annual Evaluation Plan ${badge(p.status)}</h3><p>${p.period_count} Periods · ${p.required_period_count} required</p>${p.status==='closed'?note('Closing the Plan does not mean every Student assessment is complete.'):''}<ol class="tp-sequence">${p.periods.map(item=>`<li class="tp-period"><span class="tp-seq">${esc(item.sequence)}</span><div><h3>${esc(item.label)}</h3>${badge(item.is_required?'Required':'Optional')} ${badge(item.status)}<p>${esc(item.planned_start_date || 'Start not set')} — ${esc(item.planned_end_date || 'End not set')}</p>${item.cancellation_reason?`<p>Cancellation reason: ${esc(item.cancellation_reason)}</p>`:''}${item.notes?`<p>${esc(item.notes)}</p>`:''}${Object.hasOwn(item,'cycle')?`<p>Execution: ${esc(item.cycle.title)} · ${badge(item.cycle.status)}</p>${can('talent_assessments.view')?link('assessments','Open assessments',{cycle_id:item.cycle.id}):''}`:''}</div></li>`).join('')}</ol>${!p.periods.length?empty('No Planned Evaluation Periods yet.'):''}</article>`).join('');
  }
  async function render(signal) {
    const view=config.view, pid=params.get('program_id'), ay=year.value;
    if (['programs','evaluation-plans','assessments','reviews'].includes(view)) {
      const operationApi=async(path,options={})=>{
        const response=await fetch(path,{credentials:'same-origin',cache:'no-store',...options,
          headers:{Accept:'application/json','Content-Type':'application/json',...(options.headers||{})},
          body:options.body==null?undefined:typeof options.body==='string'?options.body:JSON.stringify(options.body),signal});
        if(response.redirected||!response.headers.get('content-type')?.includes('application/json'))throw new Error('Your session may have ended. Sign in again and reopen this page.');
        const data=await response.json();
        if(!response.ok)throw Object.assign(new Error(typeof data.detail==='string'?data.detail:'Check your entries and try again.'),{status:response.status,code:data.code});
        return data;
      };
      const ctx={root,view,api:operationApi,can,year,params,notify:message=>{status.textContent=message;},
        navigate:(target,extra)=>{location.href=`/talent/${target}?${qs({academic_year_id:year.value,...extra})}`;}};
      const workspace=view==='programs' ? window.TalentProgramWorkspace :
        view==='evaluation-plans' ? window.TalentEvaluationWorkspace : window.TalentOperations;
      await workspace.render(ctx);
      return null;
    }
    if (view==='overview') {
      const routes=[['programs','Programs','Explore the Program intent, lifecycle, and versioned frameworks.','talent_programs.view'],['evaluation-plans','Plan the year','Understand ordered evaluation Periods and their execution context.','talent_evaluation_plans.view'],['assessments','Explore evidence','Read Student assessments in their original frozen context.','talent_assessments.view'],['analytics','Understand activity','Explore privacy-safe participation and coverage.','talent_analytics.view'],['talent-map','Locate patterns','See one factual metric across Programs and Branches.','talent_analytics.view'],['longitudinal','Progress over time','Explore ordered Periods within one Program and Academic Year.','talent_analytics.view']];
      const yearLabel=esc(year.options[year.selectedIndex]?.textContent || '');
      let hero=`<div class="tp-hero"><p class="tp-eyebrow">Academic Year ${yearLabel}</p><h3>Where Talent &amp; Potential stands right now</h3><p>A privacy-safe, factual snapshot of configured Programs and authorized analytics for this Academic Year. Every figure below is exactly what the backend returns - nothing is inferred or estimated here.</p><div class="tp-hero-stats" id="tp-hero-stats"><p class="tp-empty">Loading headline figures…</p></div></div>`;
      if (can('talent_analytics.view')) {
        try {
          const overview=await api(`organization-analytics/overview?${qs({academic_year_id:ay})}`,signal);
          const headline=['programs_configured','active_programs','frozen_eligible_memberships','completion_coverage'].filter(k=>overview.metrics && Object.hasOwn(overview.metrics,k));
          hero=hero.replace('<p class="tp-empty">Loading headline figures…</p>', headline.length ? headline.map(k=>`<div class="tp-hero-stat"><span class="tp-stat-label">${esc(labels[k]||human(k))}</span><span class="tp-stat-value">${metric(overview.metrics[k])}</span></div>`).join('') : '<p class="tp-empty">No headline figures are available for this Academic Year yet.</p>');
        } catch (error) {
          hero=hero.replace('<p class="tp-empty">Loading headline figures…</p>', `<p class="tp-empty">Organization analytics is not available right now (${esc(error.message)}).</p>`);
        }
      } else {
        hero=hero.replace('<p class="tp-empty">Loading headline figures…</p>', '<p class="tp-empty">Headline analytics require the Organization Analytics permission.</p>');
      }
      return hero+`<div class="tp-grid">${routes.filter(r=>can(r[3])).map((r,i)=>`<article class="tp-card"><p class="tp-eyebrow">${String(i+1).padStart(2,'0')}</p><h3>${r[1]}</h3><p>${r[2]}</p>${link(r[0],'Explore')}</article>`).join('')}</div>${note('Begin with a Program, follow its annual plan, then explore assessment evidence and authorized analytics.')}`;
    }
    if (view==='programs') {
      if (!pid) return programCards(await api('programs',signal));
      const p=await api(`programs/${encodeURIComponent(pid)}`,signal);
      const frameworks=await api(`programs/${encodeURIComponent(pid)}/frameworks`,signal);
      return `<article class="tp-card">${badge(p.status)}<h3>${esc(p.name)}</h3><p>${esc(p.description)}</p><div class="tp-actions">${can('talent_evaluation_plans.view')?link('evaluation-plans','Annual Evaluation Plan',{program_id:p.id}):''}${can('talent_analytics.view')?link('longitudinal','Follow Periods',{program_id:p.id}):''}</div></article><h3>Framework versions</h3><div class="tp-grid">${frameworks.map(f=>`<article class="tp-card">${badge(f.status)}<h3>${esc(f.title)}</h3><p>Version ${esc(f.version_number)}</p><p>${esc(f.summary)}</p></article>`).join('')}</div>${!frameworks.length?empty('No framework versions are available.'):''}`;
    }
    if (view==='evaluation-plans') return periods(await api(`evaluation-plans?${qs({academic_year_id:ay,program_id:pid})}`,signal));
    if (view==='assessments' || view==='reviews') {
      if (view==='assessments' && params.get('assessment_id')) {
        const aid=encodeURIComponent(params.get('assessment_id'));
        const assessment=await api(`assessments/${aid}`,signal);
        const results=await api(`assessments/${aid}/competency-results`,signal);
        return `<article class="tp-card"><h3>Assessment evidence ${badge(assessment.status)}</h3><p>Student ${esc(assessment.student_id)} · Cycle ${esc(assessment.cycle_id)} · Framework ${esc(assessment.framework_version_id)}</p>${assessment.kpi_result!=null?`<p>Persisted KPI: ${esc(assessment.kpi_result)}</p>`:''}${can('talent_learner_profiles.view')?link('learner-profile','Open Learner Profile',{student_id:assessment.student_id}):''}</article>`+table('Recorded competency evidence',['Competency','Rubric level','Evidence'],results.map(r=>`<tr><th scope="row">Recorded competency evidence</th><td>Rubric level recorded</td><td>${esc(r.evidence || 'No evidence text recorded')}</td></tr>`))+note('Assessment editing is not available in this stakeholder slice. Existing results and their historical references remain read-only.');
      }
      const endpoint=view==='assessments'?'assessments':'review-candidates';
      const rows=await api(`${endpoint}?${qs({cycle_id:params.get('cycle_id')})}`,signal);
      // Apply an explicit year filter to these already-authorized API rows.
      const visible=rows.filter(r=>!ay || String(r.academic_year_id)===ay);
      if (!visible.length) return empty(view==='reviews'?'No Review Candidates are available for this context.':'No assessments are available for this context.');
      return note('Records below retain their exact Cycle and Framework Version. A Review Candidate is not an Official Identification.')+table(view==='reviews'?'Review Candidates':'Student assessments',['Student reference','Status','Historical context','Evidence / history'],visible.map(r=>`<tr><th scope="row">Student ${esc(r.student_id)}</th><td>${badge(r.status)}</td><td>Cycle ${esc(r.cycle_id)}<br>Framework ${esc(r.framework_version_id)}</td><td>${view==='assessments'?link('assessments','Read evidence',{assessment_id:r.id}):''}${Object.hasOwn(r,'kpi_result')&&r.kpi_result!=null?`<p>Persisted KPI: ${esc(r.kpi_result)}</p>`:''}${can('talent_learner_profiles.view')?link('learner-profile','Open Learner Profile',{student_id:r.student_id}):''}</td></tr>`));
    }
    if (view==='learner-profile') {
      const sid=params.get('student_id');
      if (!sid) return empty('Open a Student Profile from an authorized assessment or the Students view.');
      const data=await api(`learner-profiles/${encodeURIComponent(sid)}`,signal);
      const name=[data.student.first_name,data.student.father_name,data.student.last_name].filter(Boolean).join(' ');
      return `<article class="tp-card"><p class="tp-eyebrow">Learner Profile</p><h3>${esc(name)}</h3><p>Program-specific evidence · Historical context preserved</p></article>`+data.programs.map(p=>`<section class="tp-card"><h3>${esc(p.program.name)}</h3>${p.academic_years.map(y=>`<h4>${esc(y.academic_year.year_name)}</h4>${y.cycles.map(c=>`<details><summary>${esc(c.cycle.title)} · ${esc(human(c.assessment.status))}</summary><p>Framework ${esc(c.framework_version.title)} · Version ${esc(c.framework_version.version_number)}</p>${c.frozen_context?`<p>Historical Branch context recorded · Grade ${esc(c.frozen_context.grade_level)} · ${esc(c.frozen_context.section_name)}</p>`:''}${c.assessment.kpi_result!=null?`<p>Persisted KPI: ${esc(c.assessment.kpi_result)}</p>`:''}${Object.hasOwn(c,'review_candidate')?`<p>Review Candidate: ${esc(c.review_candidate?human(c.review_candidate.status):'No persisted candidate')}</p>`:''}${Object.hasOwn(c,'official_identification')?`<p>Official Identification: ${esc(c.official_identification?human(c.official_identification.decision):'No recorded decision')}</p>`:''}${(c.competency_results||[]).map(r=>`<p>Recorded competency evidence · Rubric level recorded</p><p>${esc(r.evidence)}</p>`).join('')}</details>`).join('')}`).join('')}</section>`).join('')+(!data.programs.length?empty('No authorized Talent assessment history is available.'):'' )+(data.timeline?.length?`<h3>Historical timeline</h3><ol class="tp-sequence">${data.timeline.map(e=>`<li class="tp-period"><span aria-hidden="true">•</span><div><strong>${esc(human(e.event_type))}</strong><p>${esc(e.occurred_at)}</p></div></li>`).join('')}</ol>`:'');
    }
    if (!ay) return empty('Select an Academic Year to explore analytics.');
    const base='organization-analytics/', common={academic_year_id:ay};
    if (params.get('branch_id')) common.branch_id=params.get('branch_id');
    if (pid && !['longitudinal'].includes(view)) common.program_ids=pid;
    if (view==='analytics') {
      const [overview,portfolio,map]=await Promise.all([
        api(`${base}overview?${qs(common)}`,signal),
        api(`${base}program-portfolio?${qs(common)}`,signal),
        api(`${base}talent-map?${qs({...common,metric:'completion_coverage',dimension:'program_branch'})}`,signal),
      ]);
      const m={...(portfolio.totals||{}),...(overview.metrics||{})};
      const kpis=['programs_configured','active_programs','frozen_eligible_memberships','completion_coverage','started_coverage','required_period_execution','candidate_membership_count','identified_count'].filter(k=>Object.hasOwn(m,k));
      const programSummaries=(portfolio.programs||[]).map(row=>`<article class="tp-result-card"><header><div><p class="tp-eyebrow">Program</p><h3>${esc(row.program.name)}</h3></div>${badge(row.program.status)}</header>${progressVisual(row.metrics.completion_coverage,'Completion')}${progressVisual(row.metrics.started_coverage,'Assessments started')}<div class="tp-mini-metrics">${['frozen_eligible','candidate_count','identified_count'].filter(k=>Object.hasOwn(row.metrics,k)).map(k=>`<span><b>${metric(row.metrics[k])}</b>${esc(labels[k])}</span>`).join('')}</div>${link('portfolio','Open Program results',{program_id:row.program.id})}</article>`).join('');
      const branchCards=(map.columns||[]).map(branch=>`<a class="tp-branch-chip" href="/talent/branch?${esc(qs({academic_year_id:ay,branch_id:branch.id}))}"><span>${esc(branch.label)}</span><small>View Branch results &rarr;</small></a>`).join('');
      const previewRows=(map.rows||[]).slice(0,3), previewColumns=(map.columns||[]).slice(0,4);
      const previewCell=(r,c)=>map.cells.find(x=>x.coordinates.program_id===r.id&&x.coordinates.branch_id===c.id);
      const preview=previewRows.length&&previewColumns.length?matrix('Talent Map preview','Program',previewColumns,previewRows,previewCell,r=>map.row_totals.find(x=>x.program_id===r.id),c=>map.column_totals.find(x=>x.branch_id===c.id),map.organization_total,(r,c)=>previewCell(r,c)?.state==='visible'?link('branch','Open',{branch_id:c.id}):null):empty('The Talent Map will appear when Programs have frozen evaluation groups.');
      return lede('Your organization at a glance','See Program activity, Student participation, evaluation progress, and the next places to explore.')+
        `<section aria-labelledby="tp-headline-title"><div class="tp-section-heading"><div><p class="tp-eyebrow">Academic Year ${esc(year.options[year.selectedIndex]?.textContent||'')}</p><h3 id="tp-headline-title">Organization snapshot</h3></div><p>Figures reflect your authorized scope and this Academic Year.</p></div><div class="tp-kpi-grid">${kpis.map(k=>kpiCard(k,m[k],k==='completion_coverage'?`/talent/portfolio?${qs({academic_year_id:ay})}`:k==='candidate_membership_count'?`/talent/reviews?${qs({academic_year_id:ay})}`:k==='identified_count'?`/talent/students?${qs({academic_year_id:ay})}`:'' )).join('')}</div></section>`+
        note('Participation counts Program memberships, so a Student in two Programs can appear twice. Each percentage and total comes directly from the governed analytics service.')+
        `<section aria-labelledby="tp-program-summary"><div class="tp-section-heading"><div><p class="tp-eyebrow">Programs</p><h3 id="tp-program-summary">How Programs are progressing</h3></div>${link('portfolio','View all Program results')}</div><div class="tp-result-grid">${programSummaries||empty('No configured Programs are available for this Academic Year.')}</div></section>`+
        `<section aria-labelledby="tp-branch-summary"><div class="tp-section-heading"><div><p class="tp-eyebrow">Branches</p><h3 id="tp-branch-summary">Explore each Branch</h3></div><p>Each Branch opens in its own context. Branches are never ranked.</p></div><div class="tp-branch-list">${branchCards||empty('No Branch results are available yet.')}</div></section>`+
        `<section aria-labelledby="tp-map-preview"><div class="tp-section-heading"><div><p class="tp-eyebrow">Talent Map</p><h3 id="tp-map-preview">Completion across Programs and Branches</h3></div>${link('talent-map','Open the full Talent Map',{metric:'completion_coverage'})}</div>${preview}</section>`;
    }
    if (view==='portfolio' || view==='branch') {
      if (view==='branch' && !params.get('branch_id')) return empty('Open Branch Results from the Talent Map or Organization Overview.');
      const data=await api(`${base}${view==='portfolio'?'program-portfolio':`branches/${encodeURIComponent(params.get('branch_id'))}`}?${qs(common)}`,signal);
      const framing=view==='portfolio'
        ? lede('How are Programs progressing?','Compare factual participation and evaluation activity for the selected Academic Year. Open a Program to follow its evaluation periods.')
        : lede(`What is happening in ${data.branch?esc(data.branch.name):'this Branch'}?`,'See participation and evaluation activity in this historical Branch context. This view does not rank Branches.','branch');
      const programRows=(data.programs||[]).map(r=>`<article class="tp-result-card"><header><div><p class="tp-eyebrow">${view==='branch'?'Branch Program':'Program'}</p><h3>${esc(r.program.name)}</h3></div>${badge(r.program.status)}</header>${progressVisual(r.metrics.completion_coverage,'Completion')}${progressVisual(r.metrics.started_coverage,'Assessments started')}${Object.hasOwn(r.metrics,'required_period_execution')?progressVisual(r.metrics.required_period_execution,'Required evaluations run'):''}<div class="tp-mini-metrics">${['frozen_eligible','assessment_started','candidate_count','identified_count'].filter(k=>Object.hasOwn(r.metrics,k)).map(k=>`<span><b>${metric(r.metrics[k])}</b>${esc(labels[k])}</span>`).join('')}</div><div class="tp-actions">${link('longitudinal','Progress Over Time',{program_id:r.program.id,...(view==='branch'?{branch_id:data.branch.id}:{})})}${can('talent_analytics.view_students')?link('students','View Students',{program_id:r.program.id,...(view==='branch'?{branch_id:data.branch.id}:{})}):''}</div></article>`).join('');
      return framing+`<div class="tp-context-banner"><strong>${view==='branch'?esc(data.branch.name):'All authorized Programs'}</strong><span>${esc(year.options[year.selectedIndex]?.textContent||'')}</span></div><div class="tp-result-grid">${programRows}</div>`+(!data.programs.length?empty('No configured Programs are available for this context.'):'')+`<section aria-labelledby="tp-context-total"><div class="tp-section-heading"><div><p class="tp-eyebrow">Selected context</p><h3 id="tp-context-total">Summary</h3></div></div>${cards(data.totals)}</section>`;
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
      return lede(`Progress Over Time for ${esc(data.program.name)}`,`Follow ordered evaluation periods in ${esc(data.academic_year.label)}. Each point keeps its own frozen Student group and privacy decision.`)+note('This view presents each period as recorded. It does not calculate improvement, decline, percent change, or Student growth.')+periodVisual(data)+(!data.points.length?empty('No planned evaluation periods are available.'):'')+(comparisons?`<section aria-labelledby="tp-comparison-title"><div class="tp-section-heading"><div><p class="tp-eyebrow">Context check</p><h3 id="tp-comparison-title">Can periods be viewed side by side?</h3></div></div><div class="tp-comparison-list">${comparisons}</div></section>`:'');
    }
    if (view==='students') {
      const [data,contextMap]=await Promise.all([
        api(`${base}students?${qs({...common,offset:params.get('offset')||0})}`,signal),
        api(`${base}talent-map?${qs({...common,metric:'frozen_eligible',dimension:'program_branch'})}`,signal).catch(()=>({rows:[],columns:[]})),
      ]);
      if (data.state && data.state!=='visible') return metric(data);
      const programNames=new Map((contextMap.rows||[]).map(item=>[String(item.id),item.label]));
      const branchNames=new Map((contextMap.columns||[]).map(item=>[String(item.id),item.label]));
      const studentCards=(data.items||[]).map(r=>`<article class="tp-student-card"><header><span class="tp-avatar" aria-hidden="true">${initials(r.display_name)}</span><div><h3>${esc(r.display_name)}</h3>${r.can_view_learner_profile?link('learner-profile','Open Student Profile',{student_id:r.student_id}):''}</div></header><div class="tp-student-contexts">${r.contexts.map(c=>`<section><div class="tp-context-line"><span class="tp-context-chip">${esc(programNames.get(String(c.program_id))||'Program context')}</span><span class="tp-context-chip">${esc(branchNames.get(String(c.branch_id))||'Historical Branch')}</span><span class="tp-context-chip">Grade ${esc(c.grade_level)}</span><span class="tp-context-chip">${esc(c.section_name)}</span><span class="tp-context-chip">${esc(human(c.assessment_state))}</span></div>${Object.hasOwn(c,'candidate_state')?`<p><strong>Review Candidate:</strong> ${esc(c.candidate_state?human(c.candidate_state):'No activity')}</p>`:''}${Object.hasOwn(c,'identification_state')?`<p><strong>Official Identification:</strong> ${esc(c.identification_state?human(c.identification_state):'No recorded decision')}</p>`:''}<small>This context comes from the frozen evaluation group and stays with the original evaluation cycle.</small></section>`).join('')}</div></article>`).join('');
      return lede('Students','Browse Students in the selected authorized, historical Talent context. Open the canonical Student Profile for the full record.')+note('These Students come from frozen evaluation groups. Review Candidate and Official Identification details appear only when your role permits them.')+`<div class="tp-student-grid">${studentCards||empty('No Students are available for this context.')}</div>`+(data.pagination?.has_more?`<nav class="tp-pagination" aria-label="Student pages">${link('students','Next page',{...Object.fromEntries(params),offset:Number(params.get('offset')||0)+data.pagination.limit})}</nav>`:'');
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
  async function load() {
    const run=++generation; controller?.abort(); controller=new AbortController();
    updateBreadcrumb();
    root.innerHTML=empty('Loading this view…'); root.setAttribute('aria-busy','true'); status.textContent='';
    try {const html=await render(controller.signal);if(run===generation){if(html!==null)root.innerHTML=html;status.textContent='View loaded.';}}
    catch(error){if(error.name!=='AbortError'&&run===generation){root.innerHTML=errorPanel(error);document.getElementById('tp-retry').addEventListener('click',load);status.textContent='View could not be loaded.';}}
    finally {if(run===generation)root.setAttribute('aria-busy','false');}
  }
  form.addEventListener('submit',event=>{event.preventDefault();params.set('academic_year_id',year.value);if(!program.parentElement.hidden){program.value?params.set('program_id',program.value):params.delete('program_id');}if(!metricSelect.parentElement.hidden)params.set('metric',metricSelect.value);if(!dimension.parentElement.hidden)params.set('dimension',dimension.value);params.delete('offset');history.replaceState(null,'',`${location.pathname}?${params}`);syncNavigation();updateBreadcrumb();load();});
  async function init() {
    if(config.view==='learner-profile'||params.has('assessment_id'))form.hidden=true;
    if (params.has('academic_year_id') && [...year.options].some(o=>o.value===params.get('academic_year_id'))) year.value=params.get('academic_year_id');
    const metricViews=['talent-map','longitudinal'];
    if(metricViews.includes(config.view)) {
      document.getElementById('tp-metric-field').hidden=false;
      const metrics=['frozen_eligible','completed','completion_coverage','assessment_started','started_coverage'];
      if(can('talent_review_candidates.view'))metrics.push('candidate_count','candidate_of_eligible');
      if(can('talent_official_identifications.view'))metrics.push('identified_count','identified_of_eligible');
      metricSelect.innerHTML=metrics.map(m=>`<option value="${m}">${labels[m]}</option>`).join('');
      metricSelect.value=metrics.includes(params.get('metric'))?params.get('metric'):'completion_coverage';
    }
    if(config.view==='talent-map') {
      document.getElementById('tp-dimension-field').hidden=false;
      dimension.value=params.get('dimension')==='program_grade'?'program_grade':'program_branch';
    }
    if(['programs','evaluation-plans','longitudinal','portfolio','talent-map','students'].includes(config.view)&&can('talent_programs.view')) {
      document.getElementById('tp-program-field').hidden=false;
      try {const items=await api('programs');program.innerHTML='<option value="">Choose a Program</option>'+items.map(p=>`<option value="${esc(p.id)}">${esc(p.name)}</option>`).join('');if(params.has('program_id'))program.value=params.get('program_id');}
      catch {document.getElementById('tp-program-field').hidden=true;}
    }
    syncNavigation();
    await load();
  }
  window.addEventListener('pagehide',()=>{controller?.abort();root.replaceChildren();});
  init();
})();
