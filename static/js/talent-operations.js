/* Operational Talent UI. Every mutation is owned and authorized by the real API. */
(() => {
  'use strict';
  const esc = value => String(value ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  const words = value => String(value ?? '').replaceAll('_', ' ');
  const badge = value => `<span class="tp-badge">${esc(words(value))}</span>`;
  const note = value => `<aside class="tp-note">${esc(value)}</aside>`;
  const button = (action, label, extra='') => `<button type="button" data-action="${action}" ${extra}>${esc(label)}</button>`;
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
    const mount=html=>{root.innerHTML=`<div class="tp-operational">${html}<p id="op-message" role="status" aria-live="polite"></p></div>`;};
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
      const decisions=can('talent_official_identifications.view')?await api(`/api/talent/official-identifications?${query({cycle_id:params.get('cycle_id')})}`):[];
      mount(note('A Review Candidate meets the Program’s configured rules. Reviewing a candidate does not identify the Student. Official Identification is a separate, permanent human decision.')+(!rows.length?note('No Review Candidates in this context.'):'')+rows.map(r=>{
        const d=decisions.find(x=>x.review_candidate_id===r.id);
        return `<article class="tp-card"><h3>${esc(r.context?.student_name || 'Student name unavailable')} ${badge(r.status)}</h3>${context(r)}<p>Candidate evaluation recorded ${esc(r.evaluated_at || '')}. This page shows the recorded outcome; detailed rule results are not available here.</p><div class="tp-actions">${can('talent_assessments.view')?link('assessments','Open assessment evidence',{assessment_id:r.assessment_id}):''}${r.status==='pending_review'&&can('talent_review_candidates.manage')?button('review','Mark reviewed',`data-id="${r.id}"`):''}</div>${d?`<h4>Official Identification</h4>${badge(d.decision)}<p>${esc(d.rationale || '')}</p>`:''}${r.status==='reviewed'&&!d&&can('talent_official_identifications.record')?form(`decision-${r.id}`,note('Record one permanent decision. It cannot be edited or replaced.')+select('Decision','decision',[['','Choose a decision'],['identified','Officially identified'],['not_identified','Not identified']])+area('Rationale','rationale'),'Record official decision'):''}</article>`;
      }).join(''));
      on('review',async el=>{if(dirtyForms.size)throw new Error('Save or cancel your unsaved changes first.');if(!window.confirm('Mark this candidate reviewed? This does not record an Official Identification.'))return;await api(`/api/talent/review-candidates/${el.dataset.id}/review`,{method:'POST'});await reload();notify('Review recorded.');});
      rows.forEach(r=>bindForm(`decision-${r.id}`,async(data,el)=>{if(!data.decision){feedback(el,'Choose a decision.',true);return;}if(!window.confirm(`Record “${data.decision==='identified'?'Officially identified':'Not identified'}” permanently? This decision cannot be changed.`))return;const recorded=await api('/api/talent/official-identifications',{method:'POST',body:{review_candidate_id:r.id,...data}});dirtyForms.delete(el);if(can('talent_official_identifications.view'))await reload();else el.outerHTML=`<section><h4>Official Identification</h4>${badge(recorded.decision)}<p>${esc(recorded.rationale||'Decision recorded.')}</p></section>`;notify('Official decision recorded.');}));
      return;
    }
    if(params.get('assessment_id')) {
      let assessment=await api(`/api/talent/assessments/${encodeURIComponent(params.get('assessment_id'))}`);
      const results=await api(`/api/talent/assessments/${assessment.id}/competency-results`);
      if(!can('talent_programs.view')) {mount(`<article class="tp-card"><h3>${esc(assessment.context?.student_name || 'Student name unavailable')}</h3>${context(assessment)}</article>`+note('Program viewing permission is needed to display the competency and rubric labels. Ask your administrator for access.'));return;}
      const base=`/api/talent/programs/${assessment.program_id}/frameworks/${assessment.framework_version_id}`;
      const [framework,configuration]=await Promise.all([api(base),api(`${base}/configuration`)]);
      const editable=assessment.status==='in_progress'&&assessment.context?.cycle_status==='open';
      const saved=new Map(results.map(r=>[r.framework_competency_id,r]));
      const competencies=framework.competencies || [],levels=configuration.levels || [];
      const descriptor=(cid,lid)=>configuration.descriptors?.find(d=>d.framework_competency_id===cid&&d.rubric_level_id===lid)?.descriptor || '';
      let inputs=[];
      if(can('talent_educator_inputs.view')) inputs=await api(`/api/talent/educator-inputs?${query({student_id:assessment.student_id,program_id:assessment.program_id})}`);
      inputs=inputs.filter(r=>r.academic_year_id===assessment.academic_year_id&&r.assessment_id===assessment.id);
      const educatorFields=(r={})=>select('Input category','category',[['observation','Observation'],['context','Context'],['supporting_evidence','Supporting evidence']],r.category || 'observation')+field('Observed at (your local time)','observed_at',r.observed_at?localDate(r.observed_at):'','datetime-local','required')+area('Educator input','content',r.content || '',2000);
      mount(`<article class="tp-card"><p class="tp-eyebrow">Student assessment</p><h3>${esc(assessment.context?.student_name || 'Student name unavailable')} ${badge(assessment.status)}</h3>${context(assessment)}${assessment.kpi_result!=null?`<p>Program result: ${esc(assessment.kpi_result)}</p>`:''}<p>This assessment uses the competencies and rubric saved for this evaluation. Later placement or Program changes do not change this evidence.</p></article><form id="assessment-editor" class="tp-op-form"><div class="tp-actions"><span id="assessment-progress">${results.length} of ${competencies.length} competencies saved</span>${button('reload','Reload saved version')}</div><div class="tp-grid">${competencies.map(c=>{const r=saved.get(c.id);return `<fieldset class="tp-card" data-competency="${c.id}" ${!editable||!can('talent_assessments.manage')?'disabled':''}><legend>${esc(c.label)}</legend><p>${esc(c.description || '')}</p><div class="tp-level-options">${levels.map(l=>`<label class="tp-level-option"><input type="radio" name="level-${c.id}" value="${l.id}" ${r?.rubric_level_id===l.id?'checked':''}><span><strong>${esc(l.label)}</strong><small>${esc(descriptor(c.id,l.id)||l.description||'')}</small></span></label>`).join('')}</div>${area('Evidence',`evidence-${c.id}`,r?.evidence || '')}<p data-save-state>${r?'Saved':'Not yet assessed'}</p></fieldset>`;}).join('')}</div>${editable&&can('talent_assessments.manage')?'<button type="submit" class="tp-primary">Save assessment</button><button type="reset">Cancel assessment changes</button>':''}<p class="tp-op-feedback" role="status" aria-live="polite"></p></form>${!editable?note('This assessment is read-only. Final outcomes cannot be reopened.'):''}<div class="tp-actions">${editable&&can('talent_assessments.complete')?button('complete','Complete assessment')+button('incomplete','Mark incomplete')+button('insufficient-evidence','Mark insufficient evidence'):''}${assessment.status==='completed'&&can('talent_review_candidates.manage')?button('evaluate','Check Review Candidate rules'):''}${can('talent_review_candidates.view')?link('reviews','Review Candidates',{cycle_id:assessment.cycle_id,program_id:assessment.program_id}):''}</div>${can('talent_educator_inputs.view')||can('talent_educator_inputs.add')?`<section class="tp-card"><h3>Educator Input</h3>${note('Separate observations and context. This input does not change rubric results, Review Candidate rules, or Official Identification.')}${can('talent_educator_inputs.add')?form('educator-add',educatorFields(),'Add educator input'):''}${inputs.map(r=>`<article class="tp-card">${badge(r.category)}<p>${esc(r.content)}</p><p>Observed ${esc(r.observed_at)}</p>${button('input-history','View amendment history',`data-id="${r.id}"`)}<div data-history="${r.id}"></div>${can('talent_educator_inputs.amend')?`<details><summary>Amend input</summary>${form(`educator-amend-${r.id}`,educatorFields(r),'Save amendment')}</details>`:''}</article>`).join('')}${!inputs.length&&can('talent_educator_inputs.view')?'<p>No educator input recorded for this assessment.</p>':''}</section>`:''}`);
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
      for(const target of ['complete','incomplete','insufficient-evidence'])on(target,async()=>{if(dirtyForms.size)throw new Error('Save or cancel your unsaved changes first.');if(!window.confirm('Record this final assessment outcome? It cannot be reopened or edited.'))return;await api(`/api/talent/assessments/${assessment.id}/${target}`,{method:'POST',body:{expected_revision:assessment.revision}});await reload();notify('Final assessment outcome recorded.');});
      on('evaluate',async()=>{const result=await api('/api/talent/review-candidates/evaluate',{method:'POST',body:{assessment_id:assessment.id}});notify(result.candidate?'Review Candidate recorded. Official Identification still requires a separate human decision.':result.outcome==='no_policy'?'No enabled Review Candidate rules are configured for this assessment.':'This assessment did not qualify as a Review Candidate.');});
      const binding={student_id:assessment.student_id,program_id:assessment.program_id,academic_year_id:assessment.academic_year_id,cycle_id:assessment.cycle_id,cycle_population_member_id:assessment.cycle_population_member_id,assessment_id:assessment.id};
      const saveInput=path=>async(data)=>{await api(path,{method:'POST',body:{...binding,...data,observed_at:new Date(data.observed_at).toISOString()}});dirtyForms.clear();await reload();notify('Educator input saved separately from assessment results.');};
      bindForm('educator-add',saveInput('/api/talent/educator-inputs'));
      inputs.forEach(r=>bindForm(`educator-amend-${r.id}`,saveInput(`/api/talent/educator-inputs/${r.id}/amend`)));
      on('input-history',async el=>{const history=await api(`/api/talent/educator-inputs/${el.dataset.id}/history`);root.querySelector(`[data-history="${el.dataset.id}"]`).innerHTML=history.map(r=>`<p>${esc(r.observed_at)} · ${esc(words(r.category))}</p><p>${esc(r.content)}</p>`).join('');});
      return;
    }
    const cycleId=params.get('cycle_id'),pid=params.get('program_id');
    const rows=(await api(`/api/talent/assessments?${query({cycle_id:cycleId})}`)).filter(r=>(!year||String(r.academic_year_id)===String(year))&&(!pid||String(r.program_id)===pid));
    const cycles=can('talent_assessment_cycles.view')?await api(`/api/talent/assessment-cycles?${query({program_id:pid,academic_year_id:year})}`):[];
    const cycle=cycles.find(c=>String(c.id)===cycleId);
    const population=cycle&&cycle.status!=='draft'&&can('talent_assessment_cycles.view_population')?await api(`/api/talent/assessment-cycles/${cycle.id}/population`):null;
    mount(`<div class="tp-grid">${cycles.map(c=>`<article class="tp-card"><h3>${esc(c.title)} ${badge(c.status)}</h3><p>Placement snapshot: ${esc(c.population_effective_at || 'Not set')}</p>${link('assessments','Open evaluation students',{cycle_id:c.id,program_id:c.program_id})}</article>`).join('')}</div>${cycle?`<h3>${esc(cycle.title)}</h3>`:''}${population?`<h3>Students in this evaluation</h3>${note('This list uses the placement frozen when the evaluation opened.') }<div class="tp-grid">${population.members.map(m=>{const a=rows.find(r=>r.cycle_population_member_id===m.id);return `<article class="tp-card"><h4>${esc(m.student_name || [m.first_name,m.father_name,m.last_name].filter(Boolean).join(' ') || 'Student name unavailable')}</h4><p>${esc(m.branch_name || 'Branch name unavailable')} · Grade ${esc(m.grade_level)} · ${esc(m.section_name)}</p>${a?link('assessments','Open assessment',{assessment_id:a.id}):cycle.status==='open'&&can('talent_assessments.manage')?button('start','Start assessment',`data-member="${m.id}"`):'<p>No assessment recorded.</p>'}</article>`;}).join('')}</div>`:''}<h3>Saved assessments</h3>${!rows.length?note('No assessments saved in this context yet.'):`<div class="tp-grid">${rows.map(r=>`<article class="tp-card"><h3>${esc(r.context?.student_name || 'Student name unavailable')} ${badge(r.status)}</h3>${context(r)}${link('assessments','Open assessment',{assessment_id:r.id})}</article>`).join('')}</div>`}`);
    on('start',async el=>{const result=await api('/api/talent/assessments',{method:'POST',body:{cycle_id:cycle.id,cycle_population_member_id:Number(el.dataset.member)}});navigate('assessments',{assessment_id:result.id,academic_year_id:result.academic_year_id});});
  }
  function localDate(value) {const d=new Date(value.endsWith('Z')||/[+-]\d\d:\d\d$/.test(value)?value:`${value}Z`);return new Date(d.getTime()-d.getTimezoneOffset()*60000).toISOString().slice(0,16);}
  if(typeof module!=='undefined')module.exports={saveResults,esc,context,localDate,render};
  if(typeof window!=='undefined')window.TalentOperations={render};
})();
