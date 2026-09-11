/* Operational Talent UI. Every mutation is owned and authorized by the real API. */
(() => {
  'use strict';
  const rubricVisual = typeof module !== 'undefined' && module.exports
    ? require('./talent-rubric-visual.js')
    : window.TalentRubricVisual;
  const esc = value => String(value ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  const words = value => String(value ?? '').replaceAll('_', ' ');
  const badge = value => `<span class="tp-badge">${esc(words(value))}</span>`;
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
      const rows=(await api(`/api/talent/review-candidates?${query({cycle_id:params.get('cycle_id')})}`)).filter(r=>(!year||String(r.academic_year_id)===String(year))&&(!params.get('program_id')||String(r.program_id)===params.get('program_id')));
      const programs=can('talent_programs.view')?await api('/api/talent/programs').catch(()=>[]):[];
      const programById=new Map(programs.map(item=>[String(item.id),item]));
      const decisions=can('talent_official_identifications.view')?await api(`/api/talent/official-identifications?${query({cycle_id:params.get('cycle_id')})}`):[];
      const reviewId=params.get('review_id');
      if(reviewId) {
        const r=rows.find(x=>String(x.id)===String(reviewId));
        if(!r){mount(note('This Student is not available in the current Talent Review context.')+`<p class="tp-actions"><a href="${esc(url('reviews',{}))}">&larr; Back to Talent Review</a></p>`);return;}
        const d=decisions.find(x=>x.review_candidate_id===r.id);
        mount(`<p class="tp-actions"><a href="${esc(url('reviews',{}))}">&larr; Back to Talent Review</a></p><article class="tp-card"><h3>${programLogo(programById.get(String(r.program_id)))} ${esc(r.context?.student_name || 'Student name unavailable')} ${badge(r.status)}</h3>${context(r)}<p><strong>Highest recorded rubric level</strong> ${rubricVisual.badge(r.rubric_level)}</p><p>This Student met the Program’s configured evaluation criteria, recorded ${esc(r.evaluated_at || '')}. Rubric evidence, Program Criteria, and Official Identification remain separate records.</p><div class="tp-actions">${can('talent_assessments.view')?link('assessments','Open assessment evidence',{assessment_id:r.assessment_id}):''}${r.status==='pending_review'&&can('talent_review_candidates.manage')?button('review','Mark reviewed',`data-id="${r.id}"`):''}</div>${d?`<h4>Official Identification</h4>${badge(d.decision)}<p>${esc(d.rationale || '')}</p>`:''}${r.status==='reviewed'&&!d&&can('talent_official_identifications.record')?form(`decision-${r.id}`,note('Record one permanent decision. It cannot be edited or replaced.')+select('Decision','decision',[['','Choose a decision'],['identified','Officially identified'],['not_identified','Not identified']])+area('Rationale','rationale'),'Record official decision'):''}</article>`);
        on('review',async el=>{if(dirtyForms.size)throw new Error('Save or cancel your unsaved changes first.');if(!window.confirm('Mark this Student reviewed? This does not record an Official Identification.'))return;await api(`/api/talent/review-candidates/${el.dataset.id}/review`,{method:'POST'});await reload();notify('Review recorded.');});
        bindForm(`decision-${r.id}`,async(data,el)=>{if(!data.decision){feedback(el,'Choose a decision.',true);return;}if(!window.confirm(`Record “${data.decision==='identified'?'Officially identified':'Not identified'}” permanently? This decision cannot be changed.`))return;const recorded=await api('/api/talent/official-identifications',{method:'POST',body:{review_candidate_id:r.id,...data}});dirtyForms.delete(el);if(can('talent_official_identifications.view'))await reload();else el.outerHTML=`<section><h4>Official Identification</h4>${badge(recorded.decision)}<p>${esc(recorded.rationale||'Decision recorded.')}</p></section>`;notify('Official decision recorded.');});
        return;
      }
      const identLabel=r=>{const d=decisions.find(x=>x.review_candidate_id===r.id);return d?badge(d.decision):'Not yet decided';};
      const tableRows=rows.map(r=>{
        const c=r.context || {};
        const canOpen=r.status==='pending_review'&&can('talent_review_candidates.manage');
        return `<tr><th scope="row">${esc(c.student_name || 'Student name unavailable')}</th><td>${programLogo(programById.get(String(r.program_id)))} ${esc(c.program_name || 'Program name unavailable')}</td><td>${esc(c.grade_level || 'Unavailable')}</td><td>${esc(c.section_name || 'Unavailable')}</td><td>${esc(c.cycle_title || 'Evaluation name unavailable')}</td><td><span>Meets Program Criteria</span> ${rubricVisual.compactBadge(r.rubric_level)}</td><td>${badge(r.status)}</td><td>${identLabel(r)}</td><td><div class="tp-row-actions"><a href="${esc(url('reviews',{review_id:r.id}))}">${canOpen?'Review':'Open'}</a></div></td></tr>`;
      }).join('');
      mount(note('A Student appears in Talent Review when they meet the Program’s configured evaluation criteria. Appearing here does not identify the Student. Official Identification is a separate, permanent human decision.')+(!rows.length?note('No Students meeting Program criteria in this context.'):`<div class="tp-table-wrap"><table class="tp-compact-table"><thead><tr><th>Student</th><th>Program</th><th>Grade</th><th>Section</th><th>Evaluation</th><th>Result</th><th>Review status</th><th>Identification status</th><th>Action</th></tr></thead><tbody>${tableRows}</tbody></table></div>`));
      return;
    }
    if(params.get('assessment_id')) {
      let assessment=await api(`/api/talent/assessments/${encodeURIComponent(params.get('assessment_id'))}`);
      const assessmentProgram=can('talent_programs.view')?await api(`/api/talent/programs/${assessment.program_id}`).catch(()=>null):null;
      const results=await api(`/api/talent/assessments/${assessment.id}/competency-results`);
      if(!can('talent_programs.view')) {mount(`<article class="tp-card"><h3>${programLogo(assessmentProgram)} ${esc(assessment.context?.student_name || 'Student name unavailable')}</h3>${context(assessment)}</article>`+note('Program viewing permission is needed to display the competency and rubric labels. Ask your administrator for access.'));return;}
      const base=`/api/talent/programs/${assessment.program_id}/frameworks/${assessment.framework_version_id}`;
      const [framework,configuration]=await Promise.all([api(base),api(`${base}/configuration`)]);
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
      let inputs=[];
      if(can('talent_educator_inputs.view')) inputs=await api(`/api/talent/educator-inputs?${query({student_id:assessment.student_id,program_id:assessment.program_id})}`);
      inputs=inputs.filter(r=>r.academic_year_id===assessment.academic_year_id&&r.assessment_id===assessment.id);
      const educatorFields=(r={})=>select('Input category','category',[['observation','Observation'],['context','Context'],['supporting_evidence','Supporting evidence']],r.category || 'observation')+field('Observed at (your local time)','observed_at',r.observed_at?localDate(r.observed_at):'','datetime-local','required')+area('Educator input','content',r.content || '',2000);
      const reassessmentNotice=assessment.reassessment?.required
        ? note(`The rubric has changed since this assessment was completed. Re-evaluation is required against rubric version ${esc(assessment.reassessment.framework_version_number || '')}.`)
          + ((assessment.actions||[]).includes('reassess')?`<p class="tp-actions">${button('reassess','Re-evaluate Student')}</p>`:'')
        : (assessment.reassessment?.historical?note('This is a historical assessment. A newer reassessment is the current result.'):'');

      mount(`<article class="tp-card"><p class="tp-eyebrow">Student assessment</p><h3>${esc(assessment.context?.student_name || 'Student name unavailable')} ${badge(assessment.status)}</h3>${context(assessment)}${assessment.kpi?`<p>Program result: ${esc(assessment.kpi.result)} <span class="tp-badge">Scale ${esc(assessment.kpi.result_scale_min)}–${esc(assessment.kpi.result_scale_max)}</span></p>`:''}<p>This assessment uses the competencies and rubric saved for this evaluation. Later placement or Program changes do not change this evidence.</p>${reassessmentNotice}</article><form id="assessment-editor" class="tp-op-form"><div class="tp-actions"><div class="tp-progress" id="assessment-progress"><div class="tp-progress-head"><span>Assessment progress</span><strong>${results.length} of ${competencies.length}</strong></div><div class="tp-progress-track" role="progressbar" aria-label="Assessment progress" aria-valuemin="0" aria-valuemax="${competencies.length}" aria-valuenow="${results.length}"><span style="width:${competencies.length?Math.round(results.length/competencies.length*100):0}%"></span></div></div>${button('reload','Reload saved version')}</div><div class="tp-grid">${competencies.map(c=>{const r=saved.get(c.id),levels=levelsForCompetency(c.id),rubric=rubricForCompetency(c.id);return `<fieldset class="tp-card" data-competency="${c.id}" ${!editable||!can('talent_assessments.manage')?'disabled':''}><legend>${esc(c.label)}</legend><p>${esc(c.description || '')}</p>${rubric?`<p><strong>${esc(rubric.name)}</strong></p>`:''}<div class="tp-level-options">${levels.map(l=>`<label class="tp-level-option tp-rubric-choice"><input type="radio" name="level-${c.id}" value="${l.id}" ${r?.rubric_level_id===l.id?'checked':''}>${rubricVisual.badge(l,levels,{selected:r?.rubric_level_id===l.id,suffix:descriptor(c.id,l.id)||l.description||''})}</label>`).join('')}</div>${area('Evidence',`evidence-${c.id}`,r?.evidence || '')}<p data-save-state>${r?'Saved':'Not yet assessed'}</p>${r&&editable&&can('talent_assessments.manage')?button('clear-result','Clear Result',`data-competency="${c.id}"`):''}</fieldset>`;}).join('')}</div>${editable&&can('talent_assessments.manage')?'<button type="submit" class="tp-primary">Save assessment</button><button type="reset">Cancel assessment changes</button>':''}<p class="tp-op-feedback" role="status" aria-live="polite"></p></form>${!editable?note('This assessment is read-only. Final outcomes cannot be reopened.'):''}<div class="tp-actions">${editable&&can('talent_assessments.complete')?button('complete','Complete assessment')+button('incomplete','Mark incomplete')+button('insufficient-evidence','Mark insufficient evidence'):''}${can('talent_review_candidates.view')?link('reviews','Talent Review',{cycle_id:assessment.cycle_id,program_id:assessment.program_id}):''}</div>${can('talent_educator_inputs.view')||can('talent_educator_inputs.add')?`<section class="tp-card"><h3>Educator Input</h3>${note('Separate observations and context. This input does not change rubric results, Talent Review, or Official Identification.')}${can('talent_educator_inputs.add')?form('educator-add',educatorFields(),'Add educator input'):''}${inputs.map(r=>`<article class="tp-card">${badge(r.category)}<p>${esc(r.content)}</p><p>Observed ${esc(r.observed_at)}</p>${button('input-history','View amendment history',`data-id="${r.id}"`)}<div data-history="${r.id}"></div>${can('talent_educator_inputs.amend')?`<details><summary>Amend input</summary>${form(`educator-amend-${r.id}`,educatorFields(r),'Save amendment')}</details>`:''}</article>`).join('')}${!inputs.length&&can('talent_educator_inputs.view')?'<p>No educator input recorded for this assessment.</p>':''}</section>`:''}`);
      on('reassess',async()=>{
        if(!window.confirm('Start a new re-evaluation using the updated rubric? The completed assessment will remain in history.'))return;
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
    // Load the Program/Academic-Year assessment history, not only the selected
    // Cycle, so a Student whose current result moved to a reassessment Cycle
    // never falls back to "Not started" when the original Evaluation is open.
    const rows=(await api(`/api/talent/assessments?${query({})}`)).filter(r=>(!year||String(r.academic_year_id)===String(year))&&(!pid||String(r.program_id)===pid));
    const currentRows=rows.filter(r=>r.is_current!==false);
    const cycles=await api(`/api/talent/assessments/contexts?${query({program_id:pid,academic_year_id:year})}`);
    const explicitCycle=cycles.find(c=>String(c.id)===cycleId);
    // ADR 0035: Evaluation Period/Cycle state is context, not an assessment
    // eligibility gate. When one context is unambiguous, show its Students
    // directly regardless of legacy Draft/Open status.
    const cycle=explicitCycle || (!cycleId && pid && cycles.length===1 ? cycles[0] : undefined);
    const eligible=cycle?await api(`/api/talent/assessment-cycles/${cycle.id}/eligible-students`):null;

    const eligibleRows=eligible?eligible.members.map(m=>{
      const a=currentRows.find(r=>String(r.student_id)===String(m.student_id));
      const studentName=esc(m.student_name || [m.first_name,m.father_name,m.last_name].filter(Boolean).join(' ') || 'Student name unavailable');
      const statusLabel=a?.reassessment?.required?'Re-evaluation required':a?words(a.status):'Not started';
      const action=a?.reassessment?.required&&(a.actions||[]).includes('reassess')
        ?button('reassess-row','Re-evaluate',`data-id="${a.id}"`)
        :a
          ?`<a href="${esc(url('assessments',{assessment_id:a.id}))}">${a.status==='in_progress'?'Continue Assessment':'View Assessment'}</a>`
        :can('talent_assessments.manage')
          ?button('start','Start Assessment',`data-student="${m.student_id}"`)
          :'<span>Not started</span>';
      return `<tr><th scope="row">${studentName}</th><td>${esc(m.grade_level)}</td><td>${esc(m.section_name)}</td><td>${esc(statusLabel)}</td><td>${action}</td></tr>`;
    }).join(''):'';

    const savedRows=rows.map(r=>`<tr><th scope="row">${esc(r.context?.student_name || 'Student name unavailable')}</th><td>${esc(r.context?.program_name || 'Program name unavailable')}</td><td>${esc(r.context?.grade_level || 'Unavailable')}</td><td>${esc(r.context?.section_name || 'Unavailable')}</td><td>${r.reassessment?.required?badge('re-evaluation required'):r.is_current===false?badge('historical'):badge(r.status)}</td><td>${link('assessments',r.status==='in_progress'?'Continue Assessment':'View Assessment',{assessment_id:r.id})} ${(r.actions||[]).includes('reassess')?button('reassess-row','Re-evaluate',`data-id="${r.id}"`):''} ${(r.actions||[]).includes('delete')?button('delete-assessment','Delete',`data-id="${r.id}"`):''}</td></tr>`).join('');

    const cardsHtml=cycles.length
      ?`<div class="tp-grid">${cycles.map(c=>`<article class="tp-card"><h3>${esc(c.title)}</h3>${link('assessments','View Students',{cycle_id:c.id,program_id:c.program_id})}</article>`).join('')}</div>`
      :(pid?note('No Evaluation Period is available for this Program in this Academic Year yet.')+`<p class="tp-actions">${can('talent_evaluation_plans.view')?link('evaluation-plans','Open the Evaluation Plan',{program_id:pid}):''}</p>`:'');

    mount(`${cardsHtml}${cycle?`<h3>${esc(cycle.title)}</h3>`:''}${eligible?`<h3>Students</h3>${note('Students are shown from their current Academic Placement. If the Program includes their Grade and an assessment tool is ready, they can be assessed directly.')}${eligible.members.length?`<div class="tp-table-wrap"><table class="tp-compact-table"><thead><tr><th>Student</th><th>Grade</th><th>Section</th><th>Assessment status</th><th>Action</th></tr></thead><tbody>${eligibleRows}</tbody></table></div>`:note('No currently enrolled Students match this Program and Academic Year.')}`:''}<h3>Assessment Records</h3>${!rows.length?note('No Assessment Records in this context yet.'):`<div class="tp-table-wrap"><table class="tp-compact-table"><thead><tr><th>Student</th><th>Program</th><th>Grade</th><th>Section</th><th>Status</th><th>Action</th></tr></thead><tbody>${savedRows}</tbody></table></div>`}`);

    // ADR 0035: Start Assessment uses the Student's current Academic Placement
    // as eligibility authority. The backend captures the historical Placement
    // snapshot when the Assessment is created; no Open Evaluation step exists.
    on('start',async el=>{
      const result=await api('/api/talent/assessments',{method:'POST',body:{cycle_id:cycle.id,student_id:Number(el.dataset.student)}});
      navigate('assessments',{assessment_id:result.id,academic_year_id:result.academic_year_id,program_id:pid});
    });
    on('reassess-row',async el=>{
      if(!window.confirm('Start a new re-evaluation using the updated rubric? The completed assessment will remain in history.'))return;
      const replacement=await api(`/api/talent/assessments/${el.dataset.id}/reassess`,{method:'POST'});
      navigate('assessments',{assessment_id:replacement.id,academic_year_id:replacement.academic_year_id,program_id:replacement.program_id});
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
