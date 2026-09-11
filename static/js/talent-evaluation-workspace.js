/* Guided evaluation scheduling over the existing M8 Plan/Period and M4 Cycle APIs. */
(() => {
  'use strict';
  const programLogo = program => typeof window !== 'undefined' && window.TalentProgramIdentity ? window.TalentProgramIdentity.logoBadge(program, 'tp-logo-sm') : '';
  const icon = name => typeof window !== 'undefined' && window.TalentProgramWorkspace?.icon ? window.TalentProgramWorkspace.icon(name) : '';
  const esc = value => String(value ?? '').replace(/[&<>"']/g, character => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[character]));
  const stateFor = (_plan, period) => {
    if (period.status === 'cancelled') return 'Cancelled';
    if (period.cycle?.status === 'closed') return 'Complete';
    return 'Available';
  };
  const link = (view, year, programId, cycleId) => `/talent/${view}?${new URLSearchParams({academic_year_id:year, program_id:programId, ...(cycleId ? {cycle_id:cycleId} : {})})}`;
  let unloadGuard, workspaceCache=null, renderToken=0;

  async function render(ctx, options={}) {
    const {root, api, can} = ctx, params = ctx.params || new URLSearchParams(), year = ctx.year?.value ?? ctx.year, embedded=Boolean(ctx.embedded);
    root.onclick = null; root.onsubmit = null; root.oninput = null; root.onreset = null;
    root.classList?.add('tp-program-workspace');
    if (typeof window !== 'undefined' && unloadGuard) window.removeEventListener('beforeunload', unloadGuard);
    if (!can('talent_evaluation_plans.view')) { root.innerHTML = '<p>You do not have permission to view the Evaluation Plan.</p>'; return; }
    if (!year) { root.innerHTML = '<p>Select an academic year to plan evaluations.</p>'; return; }

    const programId = params.get('program_id');
    const query = new URLSearchParams({academic_year_id:year, ...(programId ? {program_id:programId} : {})});
    const cacheKey=`${year||''}::${programId||''}`;
    const planOnly=options.planOnly===true && workspaceCache?.key===cacheKey;
    const token=++renderToken;
    const alreadyRendered=Boolean(root.querySelector?.('.tp-evaluation-plan,.tp-section-lede,.tp-schedule-table'));
    if(!alreadyRendered) root.innerHTML = '<p role="status">Loading Evaluation Plan...</p>';
    else root.setAttribute?.('aria-busy','true');

    let plans, programs, cycles, annual, frameworks;
    if(planOnly){
      [plans,cycles]=await Promise.all([
        api(`/api/talent/evaluation-plans?${query}`),
        can('talent_assessment_cycles.view') ? api(`/api/talent/assessment-cycles?${query}`) : [],
      ]);
      ({programs,annual,frameworks}=workspaceCache);
    }else{
      const canViewPrograms=can('talent_programs.view');
      const directBase=programId?`/api/talent/programs/${programId}`:null;
      const prefetchedProgram=programId?ctx.programCatalog?.get?.(String(programId)):null;
      const [loadedPlans,loadedPrograms,loadedCycles,loadedAnnual,loadedFrameworks] = await Promise.all([
        api(`/api/talent/evaluation-plans?${query}`),
        canViewPrograms
          ? (prefetchedProgram
              ? Promise.resolve([prefetchedProgram])
              : programId
                ? api(directBase).then(program=>[program]).catch(()=>api('/api/talent/programs'))
                : api('/api/talent/programs'))
          : Promise.resolve([]),
        can('talent_assessment_cycles.view') ? api(`/api/talent/assessment-cycles?${query}`) : Promise.resolve([]),
        canViewPrograms&&programId ? api(`${directBase}/academic-years`) : Promise.resolve([]),
        canViewPrograms&&programId ? api(`${directBase}/frameworks`) : Promise.resolve([]),
      ]);
      plans=loadedPlans;programs=loadedPrograms;cycles=loadedCycles;annual=loadedAnnual;frameworks=loadedFrameworks;
    }
    if(token!==renderToken)return;
    const program = programs.find(item => String(item.id) === String(programId));
    if (!program) {
      workspaceCache=null;
      root.removeAttribute?.('aria-busy');
      root.innerHTML = `<header class="tp-section-lede"><div><h2>Evaluation Plan</h2><p>Choose a Program to plan its Evaluation Periods for this Academic Year.</p></div></header><nav class="tp-tabs" aria-label="Choose a Program">${programs.map(item => `<a href="${esc(link('evaluation-plans', year, item.id))}">${esc(item.name)}</a>`).join('')}</nav>`;
      return;
    }
    const base = `/api/talent/programs/${program.id}`;
    workspaceCache={key:cacheKey,programs,annual,frameworks};
    root.removeAttribute?.('aria-busy');
    const configuration = annual.find(item => String(item.academic_year_id) === String(year) && item.is_enabled);
    const assessmentFramework = frameworks.find(item => item.status === 'active') || [...frameworks].reverse().find(item => item.status !== 'retired') || null;
    const plan = plans.find(item => item.program_id === program.id) || null;
    const periods = plan?.periods || [];
    const managePlan = can('talent_evaluation_plans.manage'), governPlan = can('talent_evaluation_plans.govern');
    const canSelectPeriod = can('talent_evaluation_plans.select_period');
    const manageCycle = can('talent_assessment_cycles.manage');
    const setupReady = Boolean(configuration && assessmentFramework);
    const canAddPeriod = managePlan && plan?.status !== 'closed' && configuration;
    const addForm = canAddPeriod ? `<form class="tp-card tp-editor tp-schedule-form" data-form="add-period"><h3>Add Evaluation Period</h3><label>Evaluation Period Name<input type="text" name="label" placeholder="e.g., Term 1, Audition, Spring Review, Final Performance" maxlength="80" required></label><div class="tp-actions"><button type="submit">${icon('add')}Add Evaluation Period</button></div><p data-feedback role="status" aria-live="polite"></p></form>` : '';
    // Presentation only: renders exactly the server-computed advisory warnings
    // already returned on the Plan payload (no new validation math here).
    const warningLabel = code => ({
      period_window_overlap: 'Evaluation Periods have overlapping planned dates.',
      chronological_inconsistency: 'Evaluation Periods are not in planned date order.',
      cycle_outside_planned_window: "An evaluation's Student list date falls outside its Period's planned window.",
    }[code] || code);
    const periodLabelFor = id => periods.find(item => item.id === id)?.label;
    const warningsNotice = (plan?.warnings || []).length
      ? `<ul class="tp-warnings" aria-label="Evaluation Plan advisory warnings">${(plan.warnings).map(w => `<li class="tp-warning" role="note" aria-label="${esc(warningLabel(w.code))}"><span aria-hidden="true">⚠</span> <span>${esc(warningLabel(w.code))}${(w.period_ids || []).some(periodLabelFor) ? ` (${esc((w.period_ids || []).map(periodLabelFor).filter(Boolean).join(', '))})` : ''}</span></li>`).join('')}</ul>`
      : '';
    const readOnlyNotice = !managePlan
      ? '<p class="tp-callout">This Evaluation Plan is read-only in your current workspace. Ask an organization-authorized Program manager to add or change Evaluation Periods.</p>'
      : '';
    const readiness = !configuration ? 'Enable this Program for the selected academic year first.' : !assessmentFramework ? 'Finish What we assess before starting an evaluation.' : '';
    const readyAction = '';
    const rows = periods.map(period => {
      const state = stateFor(plan, period), cycle = period.cycle;
      const openAssessments = setupReady && can('talent_assessments.view') && canSelectPeriod && (cycle || (manageCycle && managePlan));
      const open = openAssessments
        ? `<button type="button" data-assess="${period.id}">${icon('eye')}Open Student Assessments</button>`
        : (setupReady && can('talent_assessments.view')
          ? '<button type="button" disabled title="Evaluation Period selection is not permitted for your role">Open Student Assessments</button>'
          : '');
      const canRename = (period.actions || []).includes('edit');
      const canRemove = (period.actions || []).includes('remove');
      const canManageTimeline = (period.actions || []).includes('edit_timeline');
      const nameCell = canRename
        ? `<form class="tp-inline-rename" data-form="rename-period" data-period="${period.id}"><input type="text" name="label" value="${esc(period.label)}" maxlength="80" required aria-label="Evaluation Period Name"><button type="submit">Save name</button></form>`
        : esc(period.label);
      const removeButton = canRemove ? `<button type="button" data-remove="${period.id}">${icon('trash')}Remove</button>` : '';
      // Dates stay visible at all times; only the actor whose backend-returned
      // Period actions include "edit_timeline" gets editable date inputs. This
      // mirrors the server's own gate (talent_evaluation_plans.manage_timeline)
      // and never attempts to submit dates alongside label/other content
      // fields, keeping the existing mixed-PATCH-requires-both rule intact.
      const dateCell = canManageTimeline
        ? `<form class="tp-inline-rename" data-form="period-timeline" data-period="${period.id}"><input type="date" name="planned_start_date" value="${esc(period.planned_start_date || '')}" aria-label="${esc(period.label)} start date"><input type="date" name="planned_end_date" value="${esc(period.planned_end_date || '')}" aria-label="${esc(period.label)} end date"><button type="submit">Save dates</button></form>`
        : `<span class="tp-period-dates" aria-label="${esc(period.label)} planned dates">${esc(period.planned_start_date || 'No start date')} – ${esc(period.planned_end_date || 'No end date')}</span>`;
      return `<tr><th scope="row">${nameCell}</th><td><span class="tp-badge tp-state-${esc(state.toLowerCase().replaceAll(' ', '-'))}">${esc(state)}</span></td><td>${dateCell}</td><td><div class="tp-row-actions">${open}${removeButton}</div></td></tr>`;
    }).join('');

    const heading=embedded?'<p>Plan when this Program will be evaluated during the Academic Year.</p>':`<a href="${esc(link('programs', year, program.id))}#tp-schedule">Back to Program setup</a><header class="tp-section-lede">${programLogo(program)}<div><p class="tp-eyebrow">${esc(program.name)}</p><h2>Evaluation Plan</h2><p>Plan when this Program will be evaluated during the Academic Year.</p></div></header>`;
    const navigation=embedded?`<div class="tp-wizard-actions"><a href="#tp-builder-review">Back</a><a class="tp-primary-link" href="#tp-ready">Save &amp; Continue</a></div>`:`<div class="tp-wizard-actions"><a href="${esc(link('programs', year, program.id))}#tp-builder-review">Back</a>${periods.length?`<a class="tp-primary-link" href="${esc(link('programs', year, program.id))}#tp-ready">Finish Setup</a>`:''}</div>`;
    root.innerHTML = `<div class="tp-evaluation-plan" data-feedback role="status" aria-live="polite"></div>${heading}${readiness ? `<p class="tp-callout">${esc(readiness)}</p>` : ''}${readOnlyNotice}${warningsNotice}${periods.length ? `<div class="tp-table-wrap"><table class="tp-compact-table"><thead><tr><th>Evaluation Period</th><th>Status</th><th>Dates</th><th>Actions</th></tr></thead><tbody>${rows}</tbody></table></div>` : `<p class="tp-empty">${managePlan ? 'Add this year\'s Evaluation Periods below.' : 'No Evaluation Periods have been added for this year.'}</p>`}${addForm}${readyAction}<details class="tp-card"><summary>Plan details</summary><p>${plan ? `Evaluation Plan saved with ${periods.length} Period${periods.length === 1 ? '' : 's'}.` : 'No Evaluation Plan saved yet.'}</p><p>Student Assessments use current Academic Placement for eligibility. Historical placement and assessment-tool context are captured when each Assessment starts.</p></details>${navigation}`;

    let busy = false;
    const dirtyForms = new Set();
    root.oninput = event => { const edited = event.target.closest('form'); if (edited) { dirtyForms.add(edited); edited.dataset.dirty = 'true'; } };
    root.onreset = event => { dirtyForms.delete(event.target); delete event.target.dataset.dirty; };
    if (typeof window !== 'undefined') { unloadGuard = event => { if (dirtyForms.size || busy) { event.preventDefault(); event.returnValue = ''; } }; window.addEventListener('beforeunload', unloadGuard); }
    const feedback = target => target?.querySelector?.('[data-feedback]') || root.querySelector('[data-feedback]');
    const setBusy = value => { busy = value; [...root.querySelectorAll('button')].forEach(button => { button.disabled = value; }); };
    const request = (path, method='POST', body) => api(path, {method, body:body === undefined ? undefined : JSON.stringify(body)});
    const fail = (error, target) => { const output = feedback(target); if (output) { const raw=String(error.message||'');const message=error.code==='organization_authority_required'||/organization or global scope/i.test(raw)?"You don't have access to add or change Evaluation Periods for this Program.":raw||'Unable to save the Evaluation Plan.';output.textContent = `${message} Saved steps remain available. Reload before retrying if the Evaluation Plan changed elsewhere.`; output.setAttribute('role', 'alert'); } };
    const refresh = async message => {
      const savedScrollY=typeof window!=='undefined'?window.scrollY:0;
      dirtyForms.clear();
      await render(ctx,{planOnly:true});
      ctx.notify?.(message);
      if(typeof window!=='undefined')window.scrollTo(0,savedScrollY);
    };

    root.onsubmit = async event => {
      const form = event.target;
      if (form.matches('form[data-form="add-period"]')) {
        event.preventDefault(); if (busy) return;
        const label = String(new FormData(form).get('label') || '').trim();
        if (!label) return;
        setBusy(true); feedback(form).textContent = 'Adding evaluation...';
        try {
          let current = plan;
          if (!current) current = await request('/api/talent/evaluation-plans', 'POST', {program_academic_year_configuration_id:configuration.id});
          const shortCode = `E${Date.now().toString(36)}`;
          const created = await request(`/api/talent/evaluation-plans/${current.id}/periods`, 'POST', {expected_plan_revision:current.revision, label, short_code:shortCode, is_required:true});
          if (current.status === 'draft' && governPlan) await request(`/api/talent/evaluation-plans/${current.id}/activate`, 'POST', {expected_plan_revision:created.plan_revision});
          await refresh('Evaluation added.');
        } catch (error) { fail(error, form); } finally { setBusy(false); }
        return;
      }
      if (form.matches('form[data-form="rename-period"]')) {
        event.preventDefault(); if (busy) return;
        const label = String(new FormData(form).get('label') || '').trim();
        if (!label) return;
        setBusy(true); feedback(form).textContent = 'Saving name...';
        try {
          await request(`/api/talent/evaluation-periods/${form.dataset.period}`, 'PATCH', {expected_plan_revision:plan.revision, label});
          await refresh('Evaluation renamed.');
        } catch (error) { fail(error, form); } finally { setBusy(false); }
        return;
      }
      if (form.matches('form[data-form="period-timeline"]')) {
        event.preventDefault(); if (busy) return;
        const data = new FormData(form);
        // Only the two governed timeline fields are ever submitted here, kept
        // deliberately separate from the rename form's content fields, so this
        // never assembles a mixed content+timeline PATCH the actor might lack
        // one of the two required permissions for.
        const startValue = String(data.get('planned_start_date') || '').trim();
        const endValue = String(data.get('planned_end_date') || '').trim();
        setBusy(true); feedback(form).textContent = 'Saving dates...';
        try {
          await request(`/api/talent/evaluation-periods/${form.dataset.period}`, 'PATCH', {expected_plan_revision:plan.revision, planned_start_date: startValue || null, planned_end_date: endValue || null});
          await refresh('Evaluation dates updated.');
        } catch (error) { fail(error, form); } finally { setBusy(false); }
        return;
      }
    };

    root.onclick = async event => {
      const button = event.target.closest('button[data-assess],button[data-remove]'); if (!button || busy) return;
      if (button.hasAttribute('data-remove')) {
        if (typeof window !== 'undefined' && !window.confirm('Remove this evaluation? This cannot be undone.')) return;
        setBusy(true);
        try { await request(`/api/talent/evaluation-periods/${button.dataset.remove}`, 'DELETE', {expected_plan_revision:plan.revision}); await refresh('Evaluation removed.'); }
        catch (error) { fail(error); } finally { setBusy(false); }
        return;
      }
      const period = periods.find(item => String(item.id) === button.dataset.assess); if (!period) return;
      setBusy(true); const output = feedback(); output.textContent = 'Opening Student Assessments...';
      try {
        let cycle = period.cycle;
        if (!cycle) {
          // ADR 0035: Cycle remains an internal compatibility/provenance
          // container. Creating/linking it is not a user-facing lifecycle step
          // and does not open/freeze a roster.
          cycle = await request('/api/talent/assessment-cycles', 'POST', {
            program_id:program.id,
            academic_year_id:Number(year),
            framework_version_id:assessmentFramework.id,
            title:period.label,
            population_effective_at:new Date().toISOString()
          });
          const linked = await request(`/api/talent/assessment-cycles/${cycle.id}/link-period`, 'POST', {
            planned_period_id:period.id,
            expected_plan_revision:plan.revision,
            expected_cycle_revision:cycle.revision
          });
          cycle.revision = linked.cycle_revision;
        }
        ctx.navigate?.('assessments',{program_id:program.id,cycle_id:cycle.id,academic_year_id:Number(year)});
      } catch (error) { fail(error); } finally { setBusy(false); }
    };
  }

  if (typeof module !== 'undefined' && module.exports) module.exports = {render, esc, stateFor};
  if (typeof window !== 'undefined') window.TalentEvaluationWorkspace = {render};
})();
