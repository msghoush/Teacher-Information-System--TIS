/* Program-specific configuration; every mutation is authorized and validated by M2/M3. */
(() => {
  'use strict';
  const esc = v => String(v ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  const field = (name, label, value='', type='text', required=false) => `<label>${esc(label)}<input name="${esc(name)}" type="${type}" value="${esc(value)}" ${required?'required':''} ${type==='number'?'step="any"':''}></label>`;
  const area = (name,label,value='') => `<label>${esc(label)}<textarea name="${name}" rows="3">${esc(value)}</textarea></label>`;
  const option = (value,label,selected) => `<option value="${esc(value)}" ${String(value)===String(selected)?'selected':''}>${esc(label)}</option>`;
  const select = (name,label,items,value) => `<label>${esc(label)}<select name="${name}">${items.map(x=>option(x[0],x[1],value)).join('')}</select></label>`;
  const check = (name,label,checked) => `<label class="tp-check"><input type="checkbox" name="${name}" ${checked?'checked':''}> ${esc(label)}</label>`;
  const button = (action,label,extra='') => `<button type="button" data-action="${action}" ${extra}>${esc(label)}</button>`;
  const form = (action,title,body) => `<form class="tp-card tp-editor" data-form="${action}"><h3>${esc(title)}</h3>${body}<div class="tp-actions"><button type="submit">Save</button><button type="reset">Reset changes</button></div><p data-feedback role="status" aria-live="polite"></p></form>`;
  const numeric = v => v === '' ? null : Number(v);
  let unloadGuard;
  function kpiComponents(data, members) {
    return members.map(m=>({framework_competency_id:m.id,weight_basis_points:Math.round(Number(data.get(`weight_${m.id}`))*100)})).filter(c=>c.weight_basis_points>0);
  }
  async function render(ctx) {
    const {root,api,can} = ctx, params=ctx.params || new URLSearchParams();
    root.oninput=null; root.onsubmit=null; root.onclick=null; root.onreset=null;
    root.classList?.add('tp-program-workspace');
    if(typeof window!=='undefined' && unloadGuard)window.removeEventListener('beforeunload',unloadGuard);
    const year = ctx.year?.value ?? ctx.year, pid=params.get('program_id');
    const manage=can('talent_programs.manage'), govern=can('talent_programs.govern');
    if (!can('talent_programs.view')) { root.innerHTML='<p class="tp-empty">You do not have permission to view Programs.</p>'; return; }
    let busy=false, dirty=false, framework=null, config=null, members=[];
    const dirtyForms=new Set();
    const showDirty=()=>{dirty=dirtyForms.size>0;const status=root.querySelector('[data-status]');if(status)status.textContent=dirty?'Unsaved changes':'';};
    root.oninput=event=>{const edited=event.target.closest('form');if(edited){dirtyForms.add(edited);edited.dataset.dirty='true';showDirty();}};
    root.onreset=event=>{dirtyForms.delete(event.target);delete event.target.dataset.dirty;showDirty();};
    if(typeof window!=='undefined') {
      unloadGuard=event=>{if(dirty&&[...dirtyForms].some(f=>root.contains(f))){event.preventDefault();event.returnValue='';}};
      window.addEventListener('beforeunload',unloadGuard);
    }
    const href = (view,extra={}) => `/talent/${view}?${new URLSearchParams({academic_year_id:year||'',...(pid?{program_id:pid}:{}),...extra})}`;
    const refresh = () => render(ctx);
    const offerReload=feedback=>{
      if(!feedback?.ownerDocument)return;
      const reload=feedback.ownerDocument.createElement('button');reload.type='button';reload.textContent='Reload latest saved version';
      reload.addEventListener('click',()=>{if(!dirty||window.confirm('Reload the latest version and discard unsaved edits?'))refresh().catch(()=>{feedback.textContent='Unable to reload. Please try refreshing the page.';});});
      feedback.append(reload);
    };
    const mutate = async (path,method,body,target) => {
      if(busy) return;
      if(target&&[...dirtyForms].some(f=>f!==target)&&!window.confirm('Saving reloads this workspace. Other sections have unsaved edits. Discard those other edits and save this section?'))return;
      busy=true;
      const controls=[...root.querySelectorAll('button')], previous=controls.map(b=>b.disabled);
      controls.forEach(b=>b.disabled=true);
      const feedback=target?.querySelector('[data-feedback]') || root.querySelector('[data-status]');
      if(feedback) feedback.textContent='Saving…';
      try {
        const result=await api(path,{method,body:body === undefined?undefined:JSON.stringify(body)});
        dirty=false;dirtyForms.clear();
        try { await refresh(); ctx.notify?.('Saved successfully.'); }
        catch {root.innerHTML='<p role="alert">Saved, but the updated workspace could not be loaded. Reload this page to see the saved result.</p>';}
        return result;
      } catch(error) {
        if(feedback) { feedback.textContent=`${error.message || 'Unable to save.'} Your entries are preserved. If this version changed elsewhere, reload it before trying again.`; feedback.setAttribute('role','alert'); offerReload(feedback); }
      } finally {busy=false;controls.forEach((b,i)=>b.disabled=previous[i]);}
    };
    root.innerHTML='<p role="status">Loading Programs…</p>';
    const programs=await api('/api/talent/programs');
    if(!pid) {
      root.innerHTML=`<div class="tp-section-lede"><div><h2>Programs</h2><p>Choose what your school evaluates, then build a rubric that fits that Program.</p></div></div><div class="tp-grid">${programs.map(p=>`<article class="tp-card"><span class="tp-badge">${esc(p.status)}</span><h3>${esc(p.name)}</h3><p>${esc(p.description||'No description added.')}</p><a href="${esc(href('programs',{program_id:p.id}))}">Open Program →</a></article>`).join('') || '<p class="tp-empty">No Programs yet. Create your first Program to begin.</p>'}</div>${manage?form('create-program','Create Program',field('name','Program name','', 'text',true)+area('description','What does this Program evaluate?')):''}`;
      root.querySelector('form')?.addEventListener('submit',async event=>{event.preventDefault();const d=new FormData(event.target);await mutate('/api/talent/programs','POST',{name:d.get('name'),description:d.get('description')},event.target);});
      return;
    }
    const program=programs.find(p=>String(p.id)===pid);
    if(!program) {root.innerHTML='<p class="tp-empty">Program unavailable in your organization.</p>';return;}
    const base=`/api/talent/programs/${program.id}`;
    const [annual,versions,bank]=await Promise.all([api(`${base}/academic-years`),api(`${base}/frameworks`),api(`${base}/competencies`)]);
    const chosen=versions.find(f=>String(f.id)===params.get('framework_id')) || versions.find(f=>f.status==='draft') || versions.find(f=>f.status==='active') || versions.at(-1);
    if(chosen) [framework,config]=await Promise.all([api(`${base}/frameworks/${chosen.id}`),api(`${base}/frameworks/${chosen.id}/configuration`)]);
    if(framework && config.revision != null && (framework.revision!==config.revision || framework.semantic_fingerprint!==config.semantic_fingerprint)) {
      root.innerHTML='<p role="alert">This version changed while it was loading. Reload the page to open the latest saved version.</p>';return;
    }
    members=framework?.competencies || [];
    const fp=framework?`${base}/frameworks/${framework.id}`:'', editable=manage && framework?.status==='draft';
    const annualYear=annual.find(a=>String(a.academic_year_id)===String(year));
    const levels=config?.levels || [], policy=config?.review_candidate_policy, kpi=config?.kpi;
    const memberName=m=>m.label || bank.find(c=>c.id===m.competency_id)?.name || 'Unnamed competency';
    const nav=[['overview','Overview'],['setup','Setup'],['builder','Competencies & Rubric']].map(([id,label])=>`<a href="#tp-${id}">${label}</a>`).join('')+
      (can('talent_evaluation_plans.view')?`<a href="${esc(href('evaluation-plans'))}">Evaluation Plan</a>`:'')+
      (can('talent_assessments.view')?`<a href="${esc(href('assessments'))}">Students</a>`:'')+
      (can('talent_review_candidates.view')?`<a href="${esc(href('reviews'))}">Reviews</a>`:'')+
      (can('talent_analytics.view')?`<a href="${esc(href('longitudinal'))}">Results</a>`:'');
    root.innerHTML=`<div data-status role="status" aria-live="polite"></div><a href="${esc(href('programs',{program_id:''}))}">← All Programs</a><header id="tp-overview" class="tp-section-lede"><div><span class="tp-badge">${esc(program.status)}</span><h2>${esc(program.name)}</h2><p>${esc(program.description||'Add a description while this Program is a draft.')}</p></div></header><nav class="tp-tabs" aria-label="Program workspace">${nav}</nav>
      <div class="tp-grid"><article class="tp-card"><h3>Eligible Grades</h3><p>${annualYear?annualYear.eligible_grade_levels.map(g=>`<span class="tp-badge">${g==='KG'?'KG':`Grade ${esc(g)}`}</span>`).join(' '):'Set up eligible Grades for the selected academic year.'}</p><p>${annualYear?(annualYear.is_enabled?'Enabled this academic year':'Disabled this academic year'):''}</p></article><article class="tp-card"><h3>Build your evaluation</h3><ol><li>${members.length?'✓':'○'} Competencies added</li><li>${levels.length?'✓':'○'} Rubric levels added</li><li>${config?.descriptors?.length?'✓':'○'} Descriptions of achievement added</li></ol><p>A numeric result is optional. Qualitative and Performing Arts Programs can use descriptive levels alone.</p></article></div>
      <section id="tp-setup"><h2>Program setup</h2>${manage&&program.status==='draft'?form('edit-program','Program information',field('name','Program name',program.name,'text',true)+area('description','What does this Program evaluate?',program.description)):''}
      ${govern&&program.status!=='retired'?`<div class="tp-actions">${button('program-state',program.status==='draft'?'Activate Program':'Retire Program')}</div>`:''}
      ${manage&&program.status!=='retired'&&year?form('annual','This academic year',check('is_enabled','Enable this Program',annualYear?.is_enabled??true)+`<fieldset><legend>Eligible Grades</legend>${['KG',...Array.from({length:12},(_,i)=>String(i+1))].map(g=>check(`grade_${g}`,g==='KG'?'KG':`Grade ${g}`,annualYear?.eligible_grade_levels.includes(g))).join('')}</fieldset>`):''}</section>
      <section id="tp-builder"><h2>Competencies & Rubric</h2><p>Choose a version to inspect its configuration. Active and historical versions are read-only; copy a version to prepare changes.</p><div class="tp-actions">${versions.map(v=>`<a class="tp-badge" ${v.id===framework?.id?'aria-current="true"':''} href="${esc(href('programs',{framework_id:v.id}))}">${esc(v.title)} · Version ${v.version_number} · ${esc(v.status)}</a>`).join('') || 'No versions yet.'}</div>
      ${manage&&program.status!=='retired'?form('new-version',framework?'Prepare a new version':'Create first version',field('title','Version title','','text',true)+area('summary','What will this version evaluate?')+(framework?check('clone','Copy the selected version’s competencies, rubric and rules',true):'')):''}
      ${framework?`<article class="tp-card"><h3>${esc(framework.title)} <span class="tp-badge">Version ${framework.version_number} · ${esc(framework.status)}</span></h3><p>${esc(framework.summary||'')}</p>${editable?form('version','Version details',field('title','Version title',framework.title,'text',true)+area('summary','Summary',framework.summary)):''}${govern&&framework.status==='draft'&&program.status==='active'?button('activate-version','Activate this version'):''}${framework.status==='draft'&&program.status==='draft'?'<p>Activate the Program before activating this competencies and rubric version.</p>':''}${govern&&framework.status==='active'?button('retire-version','Retire this version'):''}</article>`:''}
      ${framework?`<h3>What competencies are being assessed?</h3><div class="tp-grid">${members.map((m,i)=>`<article class="tp-card"><span class="tp-badge">${i+1}</span><h4>${esc(memberName(m))}</h4><p>${esc(m.description||'')}</p>${editable?`${form(`member:${m.competency_id}`,'Edit competency',field('label','Display name',memberName(m),'text',true)+area('description','What to look for',m.description))}<div class="tp-actions">${button('move-member','Move earlier',`data-index="${i}" ${i===0?'disabled':''}`)}${button('remove-member','Remove from version',`data-key="${m.competency_id}"`)}</div>`:''}</article>`).join('') || '<p class="tp-empty">Add the first competency below.</p>'}</div>`:''}
      ${editable?form('create-competency','Create a competency',field('code','Short code','','text',true)+field('name','Competency name','','text',true)+area('description','What to look for'))+form('add-member','Add an existing competency to this version',select('competency_id','Competency',bank.filter(c=>c.status==='active'&&!members.some(m=>m.competency_id===c.id)).map(c=>[c.id,c.name]),'')):''}
      ${framework?`<h3>What does each level mean?</h3>${editable?form('rubric','Rubric name',field('name','Rubric name',config.rubric?.name,'text',true)+area('description','How to use this rubric',config.rubric?.description)):`<p>${esc(config.rubric?.name||'No rubric configured.')}</p>`}<div class="tp-grid">${levels.map((l,i)=>`<article class="tp-card"><span class="tp-badge">Level ${i+1} · ${esc(l.code)}</span><h4>${esc(l.label)}</h4><p>${esc(l.description||'')}</p>${l.numeric_value!=null?`<p>Numeric value: ${esc(l.numeric_value)}</p>`:''}${editable?form(`level:${l.id}`,'Edit level',field('label','Level name',l.label,'text',true)+area('description','Description',l.description)+field('numeric_value','Numeric value (optional)',l.numeric_value,'number'))+button('move-level','Move earlier',`data-index="${i}" ${i===0?'disabled':''}`)+button('remove-level','Remove level',`data-key="${l.id}"`):''}</article>`).join('')}</div>${editable&&config.rubric?form('add-level','Add a rubric level',field('code','Short code','','text',true)+field('label','Level name','','text',true)+area('description','Description')+field('numeric_value','Numeric value (optional)','','number')):''}`:''}
      ${members.length&&levels.length?`<h3>Descriptions of achievement</h3><p>Describe what each competency looks like at each level.</p><div class="tp-grid">${members.map(m=>`<article class="tp-card"><h4>${esc(memberName(m))}</h4>${levels.map(l=>{const d=config.descriptors.find(d=>d.framework_competency_id===m.id&&d.rubric_level_id===l.id);return editable?form(`descriptor:${m.id}:${l.id}`,l.label,area('descriptor','What does this achievement look like?',d?.descriptor))+(d?button('remove-descriptor','Remove description',`data-key="${d.id}"`):''):`<p><strong>${esc(l.label)}:</strong> ${esc(d?.descriptor||'Not described yet.')}</p>`;}).join('')}</article>`).join('')}</div>`:''}
      ${framework?`<details class="tp-card"><summary>Optional numeric result (KPI)</summary><p>This weighted average applies only within this Program. Leave it unconfigured for a qualitative rubric.</p>${editable?form('kpi','Numeric result settings',check('is_enabled','Enable numeric result',kpi?.enabled??false)+field('result_scale_min','Scale minimum',kpi?.scale_min,'number')+field('result_scale_max','Scale maximum',kpi?.scale_max,'number')+area('interpretation','How to interpret the result',kpi?.interpretation)+members.map(m=>field(`weight_${m.id}`,`${memberName(m)} weight (%)`,(kpi?.components.find(c=>c.framework_competency_id===m.id)?.weight_basis_points||0)/100,'number')).join('')+'<p>Positive weights must total 100%. Every level needs a numeric value within the scale when enabled.</p>')+(kpi?button('remove-kpi','Remove numeric result settings'):''):`<p>${kpi?.enabled?'Numeric result enabled':'No numeric result enabled'}</p><p>${esc(kpi?.interpretation||'')}</p>`}</details>
      <details class="tp-card"><summary>Review Candidate rules</summary><p>These rules flag assessments for human review. A Review Candidate is not an Official Identification.</p>${editable?form('policy','Review rules',check('is_enabled','Enable Review Candidate rules',policy?.enabled??false)+select('match_mode','Flag when', [['all','All selected rules match'],['any','Any selected rule matches']],policy?.match_mode||'all')+area('description','Explain the review criteria',policy?.description)+members.map(m=>select(`rule_${m.id}`,`${memberName(m)} at or above`,[['','No rule'],...levels.map(l=>[l.id,l.label])],policy?.rules.find(r=>r.framework_competency_id===m.id)?.rubric_level_id||'')).join('')+(kpi?.enabled?field('kpi_threshold','Numeric result at or above (optional)',policy?.rules.find(r=>r.type==='kpi_at_or_above')?.threshold_value,'number'):''))+(policy?button('remove-policy','Remove Review Candidate rules'):''):`<p>${policy?.enabled?'Rules enabled':'Rules not enabled'}</p><p>${esc(policy?.description||'')}</p>${(policy?.rules||[]).map(r=>`<p>${r.type==='kpi_at_or_above'?`Numeric result at or above ${esc(r.threshold_value)}`:`${esc(memberName(members.find(m=>m.id===r.framework_competency_id)||{}))} at or above ${esc(levels.find(l=>l.id===r.rubric_level_id)?.label||'Unavailable level')}`}</p>`).join('')}`}</details>`:''}</section>`;
    root.onsubmit=async event=>{
      event.preventDefault();const f=event.target,d=new FormData(f),action=f.dataset.form;let path=base,method='PUT',body={},rev={expected_revision:framework?.revision};
      if(action==='edit-program'){method='PATCH';body={name:d.get('name'),description:d.get('description')};}
      else if(action==='annual'){path+=`/academic-years/${year}`;body={is_enabled:d.has('is_enabled'),eligible_grade_levels:['KG',...Array.from({length:12},(_,i)=>String(i+1))].filter(g=>d.has(`grade_${g}`))};}
      else if(action==='new-version'){path+='/frameworks';method='POST';body={title:d.get('title'),summary:d.get('summary'),...(d.has('clone')?{clone_from_id:framework.id}:{}),supersedes_framework_version_id:versions.find(v=>v.status==='active')?.id||null};}
      else if(action==='create-competency'){path+='/competencies';method='POST';body={code:d.get('code'),name:d.get('name'),description:d.get('description')};}
      else {
        path=fp;body={...rev};
        if(action==='version'){method='PATCH';Object.assign(body,{title:d.get('title'),summary:d.get('summary'),supersedes_framework_version_id:framework.supersedes_framework_version_id});}
        else if(action==='add-member'){path+='/competencies';method='POST';body.competency_id=Number(d.get('competency_id'));}
        else if(action.startsWith('member:')){path+=`/competencies/${action.split(':')[1]}`;method='PATCH';Object.assign(body,{label:d.get('label'),description:d.get('description')});}
        else if(action==='rubric'){path+='/rubric';Object.assign(body,{name:d.get('name'),description:d.get('description')});}
        else if(action==='add-level'||action.startsWith('level:')){path+='/rubric/levels';method=action==='add-level'?'POST':'PATCH';if(method==='PATCH')path+=`/${action.split(':')[1]}`;Object.assign(body,{label:d.get('label'),description:d.get('description'),numeric_value:numeric(d.get('numeric_value'))});if(method==='POST')body.code=d.get('code');}
        else if(action.startsWith('descriptor:')){const [,m,l]=action.split(':');path+='/rubric/descriptors';Object.assign(body,{framework_competency_id:Number(m),rubric_level_id:Number(l),descriptor:d.get('descriptor')});}
        else if(action==='kpi'){path+='/kpi';Object.assign(body,{is_enabled:d.has('is_enabled'),result_scale_min:numeric(d.get('result_scale_min')),result_scale_max:numeric(d.get('result_scale_max')),interpretation:d.get('interpretation'),calculation_method:'weighted_level_average',components:kpiComponents(d,members)});}
        else if(action==='policy'){path+='/review-candidate-policy';const rules=members.filter(m=>d.get(`rule_${m.id}`)).map(m=>({rule_type:'rubric_level_at_or_above',framework_competency_id:m.id,rubric_level_id:Number(d.get(`rule_${m.id}`))}));if(d.get('kpi_threshold'))rules.push({rule_type:'kpi_at_or_above',threshold_value:Number(d.get('kpi_threshold'))});Object.assign(body,{is_enabled:d.has('is_enabled'),match_mode:d.get('match_mode'),description:d.get('description'),rules});}
        else return;
      }
      await mutate(path,method,body,f);
    };
    root.onclick=async event=>{
      const b=event.target.closest('[data-action]');if(!b||busy)return;const a=b.dataset.action;
      if(dirty&&!window.confirm('This action reloads the workspace. Discard unsaved edits?'))return;
      let path=fp,method='POST',body={expected_revision:framework?.revision};
      if(a==='program-state'){if(!window.confirm(program.status==='draft'?'Activate this Program?':'Retire this Program?'))return;path=`${base}/lifecycle/${program.status==='draft'?'active':'retired'}`;body=undefined;}
      else if(a==='activate-version'){if(!window.confirm('Activate this version for future evaluations? The existing active version will be superseded.'))return;path+='/activate';body.expected_fingerprint=framework.semantic_fingerprint;}
      else if(a==='retire-version'){if(!window.confirm('Retire this version? Existing assessment history is preserved.'))return;path+='/retire';body=undefined;}
      else if(a==='remove-member'||a==='remove-level'||a==='remove-descriptor'){if(!window.confirm('Remove this item from the draft version?'))return;path+=a==='remove-member'?`/competencies/${b.dataset.key}`:a==='remove-level'?`/rubric/levels/${b.dataset.key}`:`/rubric/descriptors/${b.dataset.key}`;path+=`?expected_revision=${framework.revision}`;method='DELETE';body=undefined;}
      else if(a==='remove-kpi'||a==='remove-policy'){if(!window.confirm(a==='remove-kpi'?'Remove the optional numeric result settings?':'Remove all Review Candidate rules from this draft version?'))return;path+=a==='remove-kpi'?'/kpi':'/review-candidate-policy';path+=`?expected_revision=${framework.revision}`;method='DELETE';body=undefined;}
      else if(a==='move-member'||a==='move-level'){const i=Number(b.dataset.index),items=(a==='move-member'?members.map(m=>m.competency_id):levels.map(l=>l.id));if(i<1)return;[items[i-1],items[i]]=[items[i],items[i-1]];method='PUT';path+=a==='move-member'?'/competencies/order':'/rubric/levels/order';body[a==='move-member'?'competency_ids':'level_ids']=items;}
      else return;
      await mutate(path,method,body);
    };
  }
  if(typeof module!=='undefined'&&module.exports)module.exports={render,esc,kpiComponents,numeric};
  if(typeof window!=='undefined')window.TalentProgramWorkspace={render};
})();
