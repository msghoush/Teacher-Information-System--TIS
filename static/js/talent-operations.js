/* Operational Talent UI. Every mutation is owned and authorized by the real API. */
(() => {
  'use strict';
  const rubricVisual = typeof module !== 'undefined' && module.exports
    ? require('./talent-rubric-visual.js')
    : window.TalentRubricVisual;
  const esc = value => String(value ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  const words = value => String(value ?? '').replaceAll('_', ' ');
  const badge = value => `<span class="tp-badge">${esc(words(value))}</span>`;
  const overallResultVisual = result => {
    if(!result) return '<span class="tp-overall-result tp-overall-result-empty">No overall result</span>';
    if(result.available===false) return '<span class="tp-overall-result tp-overall-result-empty">Rubric scale needs alignment</span>';
    const average=Number(result.average),scaleMax=Number(result.scale_max);
    if(!Number.isFinite(average)||!Number.isFinite(scaleMax)||scaleMax<=0) return '<span class="tp-overall-result tp-overall-result-empty">No overall result</span>';
    const percent=Number.isFinite(Number(result.normalized_percent))?Math.max(0,Math.min(100,Number(result.normalized_percent))):Math.round(average/scaleMax*100);
    const value=average.toFixed(1);
    return `<span class="tp-overall-result" style="--tp-overall-score:${percent}" aria-label="Overall Program Result ${value} out of ${scaleMax}"><strong>${value}</strong><span>/${scaleMax}</span><span class="tp-overall-result-track" aria-hidden="true"><i style="width:${percent}%"></i></span></span>`;
  };
  const note = value => `<aside class="tp-note">${esc(value)}</aside>`;
  const button = (action, label, extra='') => `<button type="button" data-action="${action}" ${extra}>${esc(label)}</button>`;
  const programLogo = program => program && typeof window !== 'undefined' && window.TalentProgramIdentity ? window.TalentProgramIdentity.logoBadge(program, 'tp-logo-sm') : '';
  const query = values => new URLSearchParams(Object.entries(values).filter(([,v])=>v !== '' && v != null)).toString();
  const field = (label, name, value='', type='text', attrs='') => `<label>${esc(label)}<input name="${name}" type="${type}" value="${esc(value)}" ${attrs}></label>`;
  const area = (label,name,value='',max=4000) => `<label>${esc(label)}<textarea name="${name}" maxlength="${max}" rows="3">${esc(value)}</textarea></label>`;
  const select = (label,name,options,value='') => `<label>${esc(label)}<select name="${name}">${options.map(([id,text])=>`<option value="${esc(id)}" ${String(id)===String(value)?'selected':''}>${esc(text)}</option>`).join('')}</select></label>`;
  const form = (name,content,save='Save') => `<form data-operation="${name}" class="tp-op-form">${content}<div class="tp-actions"><button type="submit" class="tp-primary">${esc(save)}</button><button type="reset">Cancel changes</button></div><p class="tp-op-feedback" role="status" aria-live="polite"></p></form>`;
  function context(row) {
    const c=row.context || {};
    return `<div class="tp-context-strip"><span>${esc(c.program_name || 'Program name unavailable')}</span><span>${esc(c.academic_year_name || 'Academic Year name unavailable')}</span><span>${esc(c.cycle_title || 'Evaluation name unavailable')}</span><span>${esc(c.framework_title || 'Competencies & rubric')} ${c.framework_version_number?`· Version ${esc(c.framework_version_number)}`:''}</span></div><p>Historical placement: ${esc(c.branch_name || 'Branch name unavailable')} · Grade ${esc(c.grade_level || 'unavailable')} · ${esc(c.section_name || 'Section unavailable')}</p>`;
  }
  // Sequential writes are deliberately not described as an atomic bulk save.
  async function saveResults(api, assessment, pending, onSaved) {
    let current=assessment;
    for (const entry of pending) {
      const response=await api(`/api/talent/assessments/${current.id}/competency-results/${entry.framework_competency_id}`, {
        method:'PUT', body:{rubric_level_id:entry.rubric_level_id,evidence:entry.evidence,expected_revision:current.revision}
      });
      current=response.assessment;
      onSaved(response.result,current);
    }
    return current;
  }
  async function render(ctx) {
    const {root,api,can,params,navigate}=ctx;
    const year=ctx.year?.value ?? ctx.year;
    const dirtyForms=new Set();
    let busy=false, stale=false;
    const notify=message=>{ctx.notify?.(message);const el=root.querySelector('#op-message');if(el)el.textContent=message;};
    const reload=()=>render(ctx);
    const url=(view,values={})=>`/talent/${view}?${query({academic_year_id:year,program_id:params.get('program_id'),...values})}`;
    const link=(view,label,values={})=>`<a href="${esc(url(view,values))}">${esc(label)} →</a>`;
    const mount=html=>{root.innerHTML=`<div class="tp-operational"><p id="op-message" class="tp-op-feedback" role="status" aria-live="polite"></p>${html}</div>`;};
    const guard=event=>{if(dirtyForms.size||busy){event.preventDefault();event.returnValue='';}};
    if (window.__talentUnsavedGuard) window.removeEventListener('beforeunload',window.__talentUnsavedGuard);
    window.__talentUnsavedGuard=guard;window.addEventListener('beforeunload',guard);
    const feedback=(el,message,error=false)=>{const target=el?.querySelector('.tp-op-feedback');if(target){target.textContent=message;target.classList.toggle('tp-error',error);}notify(message);};
    async function action(el,work) {
      if(busy)return;busy=true;
      const controls=[...root.querySelectorAll('button,input,textarea,select')].map(el=>[el,el.disabled]);controls.forEach(([el])=>el.disabled=true);
      try {await work();}
      catch(error){stale=stale||error.status===409;feedback(el,`${error.message}${stale?' Your entries are still here. Reload the saved version before making further changes.':''}`,true);}
      finally{busy=false;controls.filter(([el])=>el.isConnected).forEach(([el,disabled])=>el.disabled=disabled);}
    }
    const bindForm=(name,work)=>{
      const el=root.querySelector(`[data-operation="${name}"]`);if(!el)return;
      el.addEventListener('input',()=>{dirtyForms.add(el);feedback(el,'Unsaved changes');});
      el.addEventListener('reset',()=>{dirtyForms.delete(el);feedback(el,'Changes cancelled.');});
      el.addEventListener('submit',e=>{e.preventDefault();if(stale){feedback(el,'Reload the saved version before retrying.',true);return;}if([...dirtyForms].some(form=>form!==el)){feedback(el,'Save or cancel changes in the other form first.',true);return;}const data=Object.fromEntries(new FormData(el));action(el,()=>work(data,el));});
    };
    const on=(name,work)=>root.querySelectorAll(`[data-action="${name}"]`).forEach(el=>el.addEventListener('click',()=>action(null,()=>work(el))));
    if(ctx.view==='reviews') {
      const workspaceQuery=query({
        cycle_id:params.get('cycle_id'),
        program_id:params.get('program_id'),
        academic_year_id:year,
      });
      const [rows,programs,decisions]=await Promise.all([
        api(`/api/talent/review-candidates/workspace?${workspaceQuery}`),
        can('talent_programs.view')?api('/api/talent/programs').catch(()=>[]):Promise.resolve([]),
        can('talent_official_identifications.view')?api(`/api/talent/official-identifications?${query({cycle_id:params.get('cycle_id')})}`):Promise.resolve([]),
      ]);
      const programById=new Map(programs.map(item=>[String(item.id),item]));
      const reviewId=params.get('review_id');
      const decisionFor=row=>row.candidate?decisions.find(item=>item.review_candidate_id===row.candidate.id):null;
      const candidateLabel=row=>row.candidate
        ? (row.candidate.status==='reviewed'?'Reviewed':'Pending review')
        : 'No Review Candidate';
      const identificationLabel=row=>{
        const decision=decisionFor(row);
        return decision?words(decision.decision):'Not yet decided';
      };
      if(reviewId) {
        const r=rows.find(x=>String(x.id)===String(reviewId));
        if(!r){mount(note('This Student is not available in the current Talent Review context.')+`<p class="tp-actions"><a href="${esc(url('reviews',{}))}">&larr; Back to Talent Review</a></p>`);return;}
        const candidate=r.candidate;
        const d=decisionFor(r);
        mount(`<p class="tp-actions"><a href="${esc(url('reviews',{}))}">&larr; Back to Talent Review</a></p>
          <article class="tp-card tp-review-detail">
            <div class="tp-review-student-head"><div><p class="tp-eyebrow">Talent review</p><h3>${programLogo(programById.get(String(r.program_id)))} ${esc(r.context?.student_name || 'Student name unavailable')}</h3></div><span class="tp-status-chip">${esc(candidateLabel(r))}</span></div>
            ${context(r)}
            ${r.reassessment?.required?note('A newer rubric requires re-evaluation. This completed result remains historical evidence until the replacement assessment is completed.'):''}
            <div class="tp-review-overall"><span>Overall Program Result</span>${overallResultVisual(r.overall_result)}</div>
            <div class="tp-review-state-grid">
              <div><small>Review Candidate</small><strong>${esc(candidate?'Meets configured criteria':'No candidate record')}</strong></div>
              <div><small>Review status</small><strong>${esc(candidateLabel(r))}</strong></div>
              <div><small>Official Identification</small><strong>${esc(d?words(d.decision):'Not yet decided')}</strong></div>
            </div>
            <p>The Program result and competency evidence support educator review. Official Identification remains a separate authorized human decision.</p>
            <div class="tp-actions">${can('talent_assessments.view')?link('assessments','Open assessment evidence',{assessment_id:r.id}):''}${candidate?.status==='pending_review'&&can('talent_review_candidates.manage')?button('review','Mark reviewed',`data-id="${candidate.id}"`):''}</div>
            ${d?`<h4>Official Identification</h4>${badge(d.decision)}<p>${esc(d.rationale || '')}</p>`:''}
            ${candidate?.status==='reviewed'&&!d&&can('talent_official_identifications.record')?form(`decision-${candidate.id}`,note('Record one permanent decision. It cannot be edited or replaced.')+select('Decision','decision',[['','Choose a decision'],['identified','Officially identified'],['not_identified','Not identified']])+area('Rationale','rationale'),'Record official decision'):''}
          </article>`);
        on('review',async el=>{if(dirtyForms.size)throw new Error('Save or cancel your unsaved changes first.');if(!window.confirm('Mark this Student reviewed? This does not record an Official Identification.'))return;await api(`/api/talent/review-candidates/${el.dataset.id}/review`,{method:'POST'});await reload();notify('Review recorded.');});
        if(candidate) bindForm(`decision-${candidate.id}`,async(data,el)=>{if(!data.decision){feedback(el,'Choose a decision.',true);return;}if(!window.confirm(`Record “${data.decision==='identified'?'Officially identified':'Not identified'}” permanently? This decision cannot be changed.`))return;const recorded=await api('/api/talent/official-identifications',{method:'POST',body:{review_candidate_id:candidate.id,...data}});dirtyForms.delete(el);if(can('talent_official_identifications.view'))await reload();else el.outerHTML=`<section><h4>Official Identification</h4>${badge(recorded.decision)}<p>${esc(recorded.rationale||'Decision recorded.')}</p></section>`;notify('Official decision recorded.');});
        return;
      }
      const completedCount=rows.length;
      const resultRows=rows.filter(r=>r.overall_result?.available!==false&&Number.isFinite(Number(r.overall_result?.average)));
      const avg=resultRows.length?(resultRows.reduce((sum,r)=>sum+Number(r.overall_result.average),0)/resultRows.length):null;
      const commonScale=resultRows.length&&resultRows.every(r=>Number(r.overall_result.scale_max)===Number(resultRows[0].overall_result.scale_max))?Number(resultRows[0].overall_result.scale_max):null;
      const candidateCount=rows.filter(r=>r.candidate).length;
      const identifiedCount=rows.filter(r=>decisionFor(r)?.decision==='identified').length;
      const kpis=`<div class="tp-kpi-grid tp-review-kpis">
        <article class="tp-kpi"><span class="tp-kpi-icon" aria-hidden="true">✓</span><span class="tp-kpi-label">Completed Assessments</span><div class="tp-kpi-value">${completedCount}</div></article>
        <article class="tp-kpi"><span class="tp-kpi-icon" aria-hidden="true">★</span><span class="tp-kpi-label">Review Candidates</span><div class="tp-kpi-value">${candidateCount}</div></article>
        <article class="tp-kpi"><span class="tp-kpi-icon" aria-hidden="true">◎</span><span class="tp-kpi-label">Average Program Result</span><div class="tp-kpi-value">${avg!=null&&commonScale?`${avg.toFixed(1)}<small>/${commonScale}</small>`:'—'}</div></article>
        <article class="tp-kpi"><span class="tp-kpi-icon" aria-hidden="true">✦</span><span class="tp-kpi-label">Officially Identified</span><div class="tp-kpi-value">${identifiedCount}</div></article>
      </div>`;
      const tableRows=rows.map(r=>{
        const c=r.context || {};
        const candidate=r.candidate;
        const d=decisionFor(r);
        const status=r.reassessment?.required?'Re-evaluation required':candidateLabel(r);
        return `<tr><th scope="row"><span class="tp-student-cell"><span class="tp-avatar" aria-hidden="true">👤</span><span>${esc(c.student_name || 'Student name unavailable')}<small>Grade ${esc(c.grade_level || '—')} · ${esc(c.section_name || '—')}</small></span></span></th><td>${programLogo(programById.get(String(r.program_id)))} ${esc(c.program_name || 'Program name unavailable')}<small>${esc(c.cycle_title || 'Evaluation unavailable')}</small></td><td>${overallResultVisual(r.overall_result)}</td><td><span class="tp-status-chip ${candidate?'is-candidate':'is-neutral'}">${esc(candidate?'Meets criteria':'No candidate')}</span></td><td><span class="tp-status-chip">${esc(status)}</span></td><td><span class="tp-status-chip ${d?.decision==='identified'?'is-positive':'is-neutral'}">${esc(identificationLabel(r))}</span></td><td><a class="tp-action-link" href="${esc(url('reviews',{review_id:r.id}))}">Open Review →</a></td></tr>`;
      }).join('');
      mount(`${kpis}${note('Talent Review includes every current Completed Assessment. Review Candidate and Official Identification are separate states; an assessment never disappears because it did not materialize a Candidate row.')}${!rows.length?note('No completed Student Assessments are available in this context yet.'):`<div class="tp-table-wrap"><table class="tp-compact-table tp-review-table"><thead><tr><th>Student</th><th>Program / Evaluation</th><th>Overall result</th><th>Review Candidate</th><th>Review status</th><th>Identification</th><th>Action</th></tr></thead><tbody>${tableRows}</tbody></table></div>`}`);
      return;
    }
    if(params.get('assessment_id')) {
      let assessment=await api(`/api/talent/assessments/${encodeURIComponent(params.get('assessment_id'))}`);
      const base=`/api/talent/programs/${assessment.program_id}/frameworks/${assessment.framework_version_id}`;
      const canViewPrograms=can('talent_programs.view');
      const canViewInputs=can('talent_educator_inputs.view');
      const [assessmentProgram,results,framework,configuration,loadedInputs]=await Promise.all([
        canViewPrograms?api(`/api/talent/programs/${assessment.program_id}`).catch(()=>null):Promise.resolve(null),
        api(`/api/talent/assessments/${assessment.id}/competency-results`),
        canViewPrograms?api(base):Promise.resolve(null),
        canViewPrograms?api(`${base}/configuration`):Promise.resolve(null),
        canViewInputs?api(`/api/talent/educator-inputs?${query({student_id:assessment.student_id,program_id:assessment.program_id})}`):Promise.resolve([]),
      ]);
      if(!canViewPrograms) {mount(`<article class="tp-card"><h3>${programLogo(assessmentProgram)} ${esc(assessment.context?.student_name || 'Student name unavailable')}</h3>${context(assessment)}</article>`+note('Program viewing permission is needed to display the competency and rubric labels. Ask your administrator for access.'));return;}
      const editable=assessment.status==='in_progress';
      const saved=new Map(results.map(r=>[r.framework_competency_id,r]));
      const legacyLevels=configuration.levels || [];
      const rubrics=configuration.rubrics || [];
      const rubricForCompetency=cid=>rubrics.find(r=>Number(r.framework_competency_id)===Number(cid)) || null;
      const levelsForCompetency=cid=>rubricForCompetency(cid)?.levels || legacyLevels;
      const assessmentGrade=String(assessment.context?.grade_level || '');
      const allCompetencies=framework.competencies || [];
      const hasExplicitGradeScope=allCompetencies.some(c=>String(c.grade_level || '').trim());
      const gradeScopedDescriptorIds=new Set(
        (configuration.descriptors || [])
          .filter(d=>String(d.grade_level || '')===assessmentGrade)
          .map(d=>d.framework_competency_id)
      );
      const hasAnyGradeScopedDescriptors=(configuration.descriptors || []).some(d=>String(d.grade_level || '').trim());
      // Explicit Framework competency Grade is authoritative. The descriptor
      // inference below is retained only for pre-migration Frameworks that have
      // Grade-specific descriptors but no explicit competency Grade yet.
      const competencies=allCompetencies.filter(c=>{
        if(hasExplicitGradeScope) return !c.grade_level || String(c.grade_level)===assessmentGrade;
        return !hasAnyGradeScopedDescriptors || gradeScopedDescriptorIds.has(c.id);
      });
      const descriptor=(cid,lid)=>configuration.descriptors?.find(d=>d.framework_competency_id===cid&&d.rubric_level_id===lid&&String(d.grade_level||'')===assessmentGrade)?.descriptor || configuration.descriptors?.find(d=>d.framework_competency_id===cid&&d.rubric_level_id===lid&&!d.grade_level)?.descriptor || '';
      let inputs=(loadedInputs||[]).filter(r=>r.academic_year_id===assessment.academic_year_id&&r.assessment_id===assessment.id);
      const educatorFields=(r={})=>select('Input category','category',[['observation','Observation'],['context','Context'],['supporting_evidence','Supporting evidence']],r.category || 'observation')+field('Observed at (your local time)','observed_at',r.observed_at?localDate(r.observed_at):'','datetime-local','required')+area('Educator input','content',r.content || '',2000);
      const reassessmentNotice=assessment.reassessment?.required
        ? note(`The rubric has changed since this assessment was completed. Re-evaluation is required against rubric version ${esc(assessment.reassessment.framework_version_number || '')}.`)
          + ((assessment.actions||[]).includes('reassess')?`<p class="tp-actions">${button('reassess','Re-evaluate Student')}</p>`:'')
        : (assessment.reassessment?.historical?note('This is a historical assessment. A newer reassessment is the current result.'):'');

      mount(`<article class="tp-card"><p class="tp-eyebrow">Student assessment</p><h3>${esc(assessment.context?.student_name || 'Student name unavailable')} ${badge(assessment.status)}</h3>${context(assessment)}${assessment.overall_result?`<div class="tp-assessment-overall"><span>Overall Program Result</span>${overallResultVisual(assessment.overall_result)}</div>`:''}${assessment.kpi?`<p class="tp-note">Configured KPI result: ${esc(assessment.kpi.result)} <span class="tp-badge">Scale ${esc(assessment.kpi.result_scale_min)}–${esc(assessment.kpi.result_scale_max)}</span></p>`:''}<p>This assessment uses the competencies and rubric saved for this evaluation. Later placement or Program changes do not change this evidence.</p>${reassessmentNotice}</article><form id="assessment-editor" class="tp-op-form"><div class="tp-actions"><div class="tp-progress" id="assessment-progress"><div class="tp-progress-head"><span>Assessment progress</span><strong>${results.length} of ${competencies.length}</strong></div><div class="tp-progress-track" role="progressbar" aria-label="Assessment progress" aria-valuemin="0" aria-valuemax="${competencies.length}" aria-valuenow="${results.length}"><span style="width:${competencies.length?Math.round(results.length/competencies.length*100):0}%"></span></div></div>${button('reload','Reload saved version')}</div><div class="tp-grid">${competencies.map(c=>{const r=saved.get(c.id),levels=levelsForCompetency(c.id),rubric=rubricForCompetency(c.id);return `<fieldset class="tp-card" data-competency="${c.id}" ${!editable||!can('talent_assessments.manage')?'disabled':''}><legend>${esc(c.label)}</legend><p>${esc(c.description || '')}</p>${rubric?`<p><strong>${esc(rubric.name)}</strong></p>`:''}<div class="tp-level-options">${levels.map(l=>`<label class="tp-level-option tp-rubric-choice"><input type="radio" name="level-${c.id}" value="${l.id}" ${r?.rubric_level_id===l.id?'checked':''}>${rubricVisual.badge(l,levels,{selected:r?.rubric_level_id===l.id,suffix:descriptor(c.id,l.id)||l.description||''})}</label>`).join('')}</div>${area('Evidence',`evidence-${c.id}`,r?.evidence || '')}<p data-save-state>${r?'Saved':'Not yet assessed'}</p>${r&&editable&&can('talent_assessments.manage')?button('clear-result','Clear Result',`data-competency="${c.id}"`):''}</fieldset>`;}).join('')}</div>${editable&&can('talent_assessments.manage')?'<button type="submit" class="tp-primary">Save assessment</button><button type="reset">Cancel assessment changes</button>':''}<p class="tp-op-feedback" role="status" aria-live="polite"></p></form>${!editable?note('This assessment is read-only. Final outcomes cannot be reopened.'):''}<div class="tp-actions">${editable&&can('talent_assessments.complete')?button('complete','Complete assessment')+button('incomplete','Mark incomplete')+button('insufficient-evidence','Mark insufficient evidence'):''}${can('talent_review_candidates.view')?link('reviews','Talent Review',{cycle_id:assessment.cycle_id,program_id:assessment.program_id}):''}</div>${can('talent_educator_inputs.view')||can('talent_educator_inputs.add')?`<section class="tp-card"><h3>Educator Input</h3>${note('Separate observations and context. This input does not change rubric results, Talent Review, or Official Identification.')}${can('talent_educator_inputs.add')?form('educator-add',educatorFields(),'Add educator input'):''}${inputs.map(r=>`<article class="tp-card">${badge(r.category)}<p>${esc(r.content)}</p><p>Observed ${esc(r.observed_at)}</p>${button('input-history','View amendment history',`data-id="${r.id}"`)}<div data-history="${r.id}"></div>${can('talent_educator_inputs.amend')?`<details><summary>Amend input</summary>${form(`educator-amend-${r.id}`,educatorFields(r),'Save amendment')}</details>`:''}</article>`).join('')}${!inputs.length&&can('talent_educator_inputs.view')?'<p>No educator input recorded for this assessment.</p>':''}</section>`:''}`);
      on('reassess',async()=>{
        if(!window.confirm('Start a new re-evaluation using the updated rubric? The prior completed result will remain preserved.'))return;
        const replacement=await api(`/api/talent/assessments/${assessment.id}/reassess`,{method:'POST'});
        navigate('assessments',{assessment_id:replacement.id,academic_year_id:replacement.academic_year_id,program_id:replacement.program_id});
      });
      const editor=root.querySelector('#assessment-editor');
      function pending() {return competencies.flatMap(c=>{const box=editor.querySelector(`[data-competency="${c.id}"]`), level=box.querySelector('input:checked'), evidence=box.querySelector('textarea').value,old=saved.get(c.id);return level&&(!old||old.rubric_level_id!==Number(level.value)||(old.evidence||'')!==evidence)?[{framework_competency_id:c.id,rubric_level_id:Number(level.value),evidence}]:[];});}
      editor.addEventListener('input',e=>{dirtyForms.add(editor);const p=e.target.closest('fieldset')?.querySelector('[data-save-state]');if(p)p.textContent='Unsaved changes';feedback(editor,'Unsaved changes');});
      editor.addEventListener('reset',e=>{e.preventDefault();for(const c of competencies){const box=editor.querySelector(`[data-competency="${c.id}"]`),old=saved.get(c.id);box.querySelectorAll('input[type="radio"]').forEach(input=>input.checked=Number(input.value)===old?.rubric_level_id);box.querySelector('textarea').value=old?.evidence || '';box.querySelector('[data-save-state]').textContent=old?'Saved':'Not yet assessed';}dirtyForms.delete(editor);feedback(editor,'Assessment changes cancelled.');});
      editor.addEventListener('submit',e=>{e.preventDefault();action(editor,async()=>{
        if(stale)throw new Error('Reload the saved version before retrying.');
        const evidenceOnly=competencies.some(c=>{const box=editor.querySelector(`[data-competency="${c.id}"]`);return box.querySelector('textarea').value.trim()&&!box.querySelector('input:checked');});
        if(evidenceOnly)throw new Error('Choose a rubric level for each competency with evidence.');
        let count=0;
        try {assessment=await saveResults(api,assessment,pending(),(result,current)=>{assessment=current;saved.set(result.framework_competency_id,result);count++;editor.querySelector(`[data-competency="${result.framework_competency_id}"] [data-save-state]`).textContent='Saved';root.querySelector('#assessment-progress').textContent=`${saved.size} of ${competencies.length} competencies saved`;});dirtyForms.delete(editor);feedback(editor,'Assessment saved.');}
        catch(error){error.message=`${count?`${count} competency changes saved. `:''}${error.message}`;throw error;}
      });});
      on('reload',async()=>{if(dirtyForms.size&&!window.confirm('Discard unsaved entries and reload the saved assessment?'))return;dirtyForms.clear();await reload();});
      on('clear-result',async el=>{
        if(dirtyForms.size)throw new Error('Save or cancel your unsaved changes first.');
        if(!window.confirm('Remove this saved competency result? This cannot be undone.'))return;
        const savedScrollY=window.scrollY||0;
        const cid=Number(el.dataset.competency);
        assessment=await api(`/api/talent/assessments/${assessment.id}/competency-results/${cid}?expected_revision=${assessment.revision}`,{method:'DELETE'});
        saved.delete(cid);
        const box=editor.querySelector(`[data-competency="${cid}"]`);
        box.querySelectorAll('input[type="radio"]').forEach(input=>input.checked=false);
        const evidenceBox=box.querySelector('textarea');if(evidenceBox)evidenceBox.value='';
        const state=box.querySelector('[data-save-state]');if(state)state.textContent='Not yet assessed';
        el.remove();
        const progress=root.querySelector('#assessment-progress');if(progress)progress.textContent=`${saved.size} of ${competencies.length} competencies saved`;
        notify('Competency result cleared.');
        window.scrollTo(0,savedScrollY);
      });
      for(const target of ['complete','incomplete','insufficient-evidence'])on(target,async()=>{if(dirtyForms.size)throw new Error('Save or cancel your unsaved changes first.');if(!window.confirm('Record this final assessment outcome? It cannot be reopened or edited.'))return;await api(`/api/talent/assessments/${assessment.id}/${target}`,{method:'POST',body:{expected_revision:assessment.revision}});await reload();notify('Final assessment outcome recorded.');});
      const binding={student_id:assessment.student_id,program_id:assessment.program_id,academic_year_id:assessment.academic_year_id,cycle_id:assessment.cycle_id,cycle_population_member_id:assessment.cycle_population_member_id,assessment_id:assessment.id};
      const saveInput=path=>async(data)=>{await api(path,{method:'POST',body:{...binding,...data,observed_at:new Date(data.observed_at).toISOString()}});dirtyForms.clear();await reload();notify('Educator input saved separately from assessment results.');};
      bindForm('educator-add',saveInput('/api/talent/educator-inputs'));
      inputs.forEach(r=>bindForm(`educator-amend-${r.id}`,saveInput(`/api/talent/educator-inputs/${r.id}/amend`)));
      on('input-history',async el=>{const history=await api(`/api/talent/educator-inputs/${el.dataset.id}/history`);root.querySelector(`[data-history="${el.dataset.id}"]`).innerHTML=history.map(r=>`<p>${esc(r.observed_at)} · ${esc(words(r.category))}</p><p>${esc(r.content)}</p>`).join('');});
      return;
    }
    const cycleId=params.get('cycle_id'),pid=params.get('program_id');
    const [allRows,cycles,programs,plans,explicitEligible]=await Promise.all([
      api(`/api/talent/assessments?${query({})}`),
      api(`/api/talent/assessments/contexts?${query({program_id:pid,academic_year_id:year})}`),
      can('talent_programs.view')?api('/api/talent/programs').catch(()=>[]):Promise.resolve([]),
      can('talent_evaluation_plans.view')
        ?api(`/api/talent/evaluation-plans?${query({program_id:pid,academic_year_id:year})}`).catch(()=>[])
        :Promise.resolve([]),
      cycleId?api(`/api/talent/assessment-cycles/${cycleId}/eligible-students`).catch(()=>null):Promise.resolve(null),
    ]);
    const rows=allRows.filter(r=>(!year||String(r.academic_year_id)===String(year))&&(!pid||String(r.program_id)===pid));
    const currentRows=rows.filter(r=>r.is_current!==false);
    const programById=new Map(programs.map(item=>[String(item.id),item]));
    const explicitCycle=cycles.find(c=>String(c.id)===cycleId);
    const cycle=explicitCycle || (!cycleId && pid && cycles.length===1 ? cycles[0] : undefined);
    const eligible=explicitEligible || (cycle&&!cycleId?await api(`/api/talent/assessment-cycles/${cycle.id}/eligible-students`):null);
    const assessmentFor=(studentId,context)=>{
      if(!context)return null;
      return currentRows.find(r=>{
        const rowContextId=r.evaluation_context_cycle_id || r.cycle_id;
        return String(r.student_id)===String(studentId)
          && String(r.program_id)===String(context.program_id)
          && (rowContextId==null || String(rowContextId)===String(context.id));
      }) || null;
    };

    const eligibleRows=eligible?eligible.members.map(m=>{
      const a=assessmentFor(m.student_id,cycle);
      const studentName=esc(m.student_name || [m.first_name,m.father_name,m.last_name].filter(Boolean).join(' ') || 'Student name unavailable');
      const statusLabel=a?.reassessment?.required?'Re-evaluation required':a?words(a.status):'Not started';
      const resetAllowed=a?.status==='completed'&&(a.actions||[]).includes('reset_for_reassessment');
      const action=a?.reassessment?.required&&(a.actions||[]).includes('reassess')
        ?button('reassess-row','Re-evaluate Student',`data-id="${a.id}"`)
        :a
          ?`<div class="tp-row-actions"><a class="tp-action-link" href="${esc(url('assessments',{assessment_id:a.id,cycle_id:cycle?.id||'',program_id:a.program_id||pid||''}))}">${a.status==='in_progress'?'Continue Assessment':'View Assessment'} →</a>${resetAllowed?button('reset-reassessment','Reset for Re-assessment',`data-id="${a.id}"`):''}</div>`
        :can('talent_assessments.manage')
          ?button('start','Start Assessment',`data-student="${m.student_id}"`)
          :'<span>Not started</span>';
      return `<tr><th scope="row"><span class="tp-student-cell"><span class="tp-avatar" aria-hidden="true">👤</span><span>${studentName}<small>${esc(m.branch_name||'')} · ${esc(m.section_name||'')}</small></span></span></th><td>${esc(m.grade_level)}</td><td>${esc(m.section_name)}</td><td><span class="tp-status-chip ${a?.reassessment?.required?'is-warning':a?.status==='completed'?'is-positive':'is-neutral'}">${esc(statusLabel)}</span></td><td>${action}</td></tr>`;
    }).join(''):'';

    // Evaluation Period -> unique Programs. Planned Periods are the display
    // authority; linked Cycles provide the assessable context when one exists.
    // This prevents duplicate Program cards when multiple physical Cycles
    // represent the same Program/Period and still shows configured Programs
    // before their first Cycle has been materialized.
    const cycleByPeriodProgram=new Map();
    cycles.forEach(context=>{
      const key=context.evaluation_period_id==null?null:`${context.evaluation_period_id}::${context.program_id}`;
      if(key&&!cycleByPeriodProgram.has(key))cycleByPeriodProgram.set(key,context);
    });
    const displayContexts=[];
    plans.forEach(plan=>{
      (plan.periods||[]).forEach(period=>{
        if(period.status==='cancelled')return;
        const linked=cycleByPeriodProgram.get(`${period.id}::${plan.program_id}`) || null;
        displayContexts.push({
          ...(linked||{}),
          id:linked?.id||null,
          program_id:plan.program_id,
          academic_year_id:plan.academic_year_id,
          evaluation_period_id:period.id,
          evaluation_label:period.label,
          evaluation_sequence:period.sequence,
          plan_id:plan.id,
          plan_revision:plan.revision,
          plan_status:plan.status,
        });
      });
    });
    const plannedKeys=new Set(displayContexts.map(context=>context.evaluation_period_id==null?null:`${context.evaluation_period_id}::${context.program_id}`).filter(Boolean));
    cycles.forEach(context=>{
      const key=context.evaluation_period_id==null?null:`${context.evaluation_period_id}::${context.program_id}`;
      if(!key||!plannedKeys.has(key))displayContexts.push(context);
    });

    const groups=new Map();
    displayContexts.forEach(context=>{
      const label=context.evaluation_label || context.title || 'Evaluation';
      const periodKey=`label:${label.trim().toLowerCase()}`;
      if(!groups.has(periodKey))groups.set(periodKey,{label,sequence:context.evaluation_sequence,programs:new Map()});
      const group=groups.get(periodKey);
      const currentSequence=Number(group.sequence);
      const candidateSequence=Number(context.evaluation_sequence);
      if(Number.isFinite(candidateSequence)&&(!Number.isFinite(currentSequence)||candidateSequence<currentSequence)){
        group.sequence=context.evaluation_sequence;
      }
      const programKey=String(context.program_id);
      if(!group.programs.has(programKey) || (!group.programs.get(programKey).id && context.id)){
        group.programs.set(programKey,context);
      }
    });
    const evaluationGroups=[...groups.values()].map(group=>({
      ...group,
      contexts:[...group.programs.values()],
    })).sort((a,b)=>{
      const as=Number.isFinite(Number(a.sequence))?Number(a.sequence):9999;
      const bs=Number.isFinite(Number(b.sequence))?Number(b.sequence):9999;
      return as-bs || a.label.localeCompare(b.label);
    });
    const selectedLabel=cycle?(cycle.evaluation_label||cycle.title||'').trim().toLowerCase():'';
    const cardsHtml=evaluationGroups.length
      ?`<div class="tp-evaluation-groups">${evaluationGroups.map(group=>{const selected=Boolean(selectedLabel&&group.label.trim().toLowerCase()===selectedLabel);return `<section class="tp-evaluation-group${selected?' is-selected':''}" ${selected?'aria-current="true"':''}><header><span class="tp-evaluation-icon" aria-hidden="true">📅</span><div><p class="tp-eyebrow">${selected?'Selected Evaluation Period':'Evaluation Period'}</p><h3>${esc(group.label)}</h3><small>${group.contexts.length} Program${group.contexts.length===1?'':'s'}${selected?' · active':''}</small></div></header><div class="tp-evaluation-programs">${group.contexts.map(context=>{const p=programById.get(String(context.program_id));const title=esc(p?.name || `Program ${context.program_id}`);return context.id
        ?`<a class="tp-evaluation-program-card${String(context.id)===String(cycle?.id)?' is-selected':''}" href="${esc(url('assessments',{cycle_id:context.id,program_id:context.program_id}))}"><span class="tp-program-icon" aria-hidden="true">✦</span><span><strong>${title}</strong><small>${String(context.id)===String(cycle?.id)?'Selected Program · ':''}View eligible Students and assessment status</small></span><span aria-hidden="true">→</span></a>`
        :`<a class="tp-evaluation-program-card" href="${esc(url('evaluation-plans',{program_id:context.program_id}))}"><span class="tp-program-icon" aria-hidden="true">✦</span><span><strong>${title}</strong><small>Evaluation configured · open the plan to start Student Assessments</small></span><span aria-hidden="true">→</span></a>`;}).join('')}</div></section>`;}).join('')}</div>`
      :(pid?note('No Evaluation Period is available for this Program in this Academic Year yet.')+`<p class="tp-actions">${can('talent_evaluation_plans.view')?link('evaluation-plans','Open the Evaluation Plan',{program_id:pid}):''}</p>`:'');

    const selectedHeading=cycle?`<div class="tp-selected-evaluation"><span class="tp-evaluation-icon" aria-hidden="true">📅</span><div><p class="tp-eyebrow">Selected Evaluation</p><h3>${esc(cycle.evaluation_label||cycle.title)}</h3><p>${esc(programById.get(String(cycle.program_id))?.name||'Program')}</p></div></div>`:'';
    mount(`${cardsHtml}${selectedHeading}${eligible?`<div class="tp-section-heading"><div><h3>Students</h3></div><p>Current Academic Placement + Program eligible Grades determine this list.</p></div>${eligible.members.length?`<div class="tp-table-wrap"><table class="tp-compact-table"><thead><tr><th>Student</th><th>Grade</th><th>Section</th><th>Assessment status</th><th>Action</th></tr></thead><tbody>${eligibleRows}</tbody></table></div>`:note('No currently enrolled Students match this Program and Academic Year.')}`:''}`);

    // ADR 0035: Start Assessment uses the Student's current Academic Placement
    // as eligibility authority. The backend captures the historical Placement
    // snapshot when the Assessment is created; no Open Evaluation step exists.
    on('start',async el=>{
      if(!cycle?.id)throw new Error('Choose an Evaluation Period and Program before starting an Assessment.');
      const result=await api('/api/talent/assessments',{method:'POST',body:{cycle_id:cycle.id,student_id:Number(el.dataset.student)}});
      navigate('assessments',{assessment_id:result.id,cycle_id:cycle.id,academic_year_id:result.academic_year_id,program_id:result.program_id||cycle.program_id||pid});
    });
    on('reassess-row',async el=>{
      if(!window.confirm('Start a new re-evaluation using the updated rubric? The prior completed result will remain preserved.'))return;
      const replacement=await api(`/api/talent/assessments/${el.dataset.id}/reassess`,{method:'POST'});
      navigate('assessments',{assessment_id:replacement.id,academic_year_id:replacement.academic_year_id,program_id:replacement.program_id});
    });
    on('reset-reassessment',async el=>{
      if(!window.confirm('Reset this completed Assessment for re-assessment? The completed evidence will be preserved as historical and the Student will return to Not started for this Evaluation.'))return;
      await api(`/api/talent/assessments/${el.dataset.id}/reset-for-reassessment`,{method:'POST'});
      await reload();
      notify('Assessment reset for re-assessment. Prior evidence remains historical.');
    });
    on('delete-assessment',async el=>{
      if(!window.confirm('Permanently delete this Assessment? This cannot be undone.'))return;
      await api(`/api/talent/assessments/${el.dataset.id}`,{method:'DELETE'});
      await reload();
      notify('Assessment deleted.');
    });
  }
  function localDate(value) {const d=new Date(value.endsWith('Z')||/[+-]\d\d:\d\d$/.test(value)?value:`${value}Z`);return new Date(d.getTime()-d.getTimezoneOffset()*60000).toISOString().slice(0,16);}
  if(typeof module!=='undefined')module.exports={saveResults,esc,context,localDate,render};
  if(typeof window!=='undefined')window.TalentOperations={render};
})();
