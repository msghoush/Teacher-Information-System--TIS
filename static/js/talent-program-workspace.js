/* Program-specific configuration; every mutation is authorized and validated by M2/M3. */
(() => {
  'use strict';
  const rubricVisual = () => typeof module !== 'undefined' && module.exports
    ? require('./talent-rubric-visual.js')
    : window.TalentRubricVisual;
  const esc = v => String(v ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  const field = (name, label, value='', type='text', required=false) => `<label>${esc(label)}<input name="${esc(name)}" type="${type}" value="${esc(value)}" ${required?'required':''} ${type==='number'?'step="any"':''}></label>`;
  const area = (name,label,value='') => `<label>${esc(label)}<textarea name="${name}" rows="3">${esc(value)}</textarea></label>`;
  const option = (value,label,selected) => `<option value="${esc(value)}" ${String(value)===String(selected)?'selected':''}>${esc(label)}</option>`;
  const select = (name,label,items,value) => `<label>${esc(label)}<select name="${name}">${items.map(x=>option(x[0],x[1],value)).join('')}</select></label>`;
  const check = (name,label,checked) => `<label class="tp-check"><input type="checkbox" name="${name}" ${checked?'checked':''}> ${esc(label)}</label>`;
  const icon = name => {
    const paths={
      check:'<circle cx="12" cy="12" r="9"></circle><path d="m8.5 12.5 2.2 2.2 4.8-5.4"></path>',
      eye:'<path d="M2 12s3.5-6 10-6 10 6 10 6-3.5 6-10 6S2 12 2 12Z"></path><circle cx="12" cy="12" r="2.5"></circle>',
      edit:'<path d="M4 20h4L19 9a2.8 2.8 0 0 0-4-4L4 16v4Z"></path><path d="m13.5 6.5 4 4"></path>',
      trash:'<path d="M4 7h16"></path><path d="M9 7V4h6v3"></path><path d="m7 7 1 13h8l1-13"></path>',
      upload:'<path d="M12 16V4"></path><path d="m7 9 5-5 5 5"></path><path d="M5 20h14"></path>',
      add:'<path d="M12 5v14M5 12h14"></path>',
      start:'<path d="m8 5 11 7-11 7Z"></path>'
    };
    return `<svg class="shell-icon" data-tis-icon="${name}" viewBox="0 0 24 24" aria-hidden="true">${paths[name]||''}</svg>`;
  };
  const button = (action,label,extra='',iconName='') => `<button type="button" data-action="${action}" ${extra}>${iconName?icon(iconName):''}${esc(label)}</button>`;
  const form = (action,title,body,submitLabel='Save') => `<form class="tp-card tp-editor" data-form="${action}"><h3>${esc(title)}</h3>${body}<div class="tp-actions"><button type="submit">${esc(submitLabel)}</button><button type="reset">Reset changes</button></div><p data-feedback role="status" aria-live="polite"></p></form>`;
  const numeric = v => v === '' ? null : Number(v);
  // Programmatic initials fallback for a Program with no uploaded logo: first
  // letter of each of the first two words, or the first two characters of a
  // single-word name (e.g. "Mental Math"->"MM", "Performing Arts"->"PA",
  // "Ghers"->"GH"). Never hardcoded per-Program.
  function logoInitials(name) {
    const words = String(name || '').trim().split(/\s+/).filter(Boolean);
    if (!words.length) return '?';
    if (words.length === 1) return words[0].slice(0, 2).toUpperCase();
    return (words[0][0] + words[1][0]).toUpperCase();
  }
  const logoBadge = (program, sizeClass) => `<span class="tp-logo-badge ${sizeClass}">${program.logo_url ? `<img src="${esc(program.logo_url)}" alt="${esc(program.name)} logo">` : `<span class="tp-logo-initials" aria-hidden="true">${esc(logoInitials(program.name))}</span>`}</span>`;
  let unloadGuard, hashGuard;
  function kpiComponents(data, members) {
    return members.map(m=>({framework_competency_id:m.id,weight_basis_points:Math.round(Number(data.get(`weight_${m.id}`))*100)})).filter(c=>c.weight_basis_points>0);
  }
  async function render(ctx) {
    const {root,api,can} = ctx, params=ctx.params || new URLSearchParams();
    root.oninput=null; root.onsubmit=null; root.onclick=null; root.onreset=null;
    root.classList?.add('tp-program-workspace');
    if(typeof window!=='undefined' && unloadGuard)window.removeEventListener('beforeunload',unloadGuard);
    if(typeof window!=='undefined' && hashGuard)window.removeEventListener('hashchange',hashGuard);
    const year = ctx.year?.value ?? ctx.year, yearLabel=ctx.yearLabel||ctx.year?.options?.[ctx.year.selectedIndex]?.textContent||String(year||''), pid=params.get('program_id');
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
      // Capture scroll position before the workspace re-renders (root.innerHTML
      // replace) so a save/remove feels local instead of jumping to the top.
      const savedScrollY=typeof window!=='undefined'?window.scrollY:0;
      try {
        const result=await api(path,{method,body:body === undefined?undefined:JSON.stringify(body)});
        dirty=false;dirtyForms.clear();
        try { await refresh(); ctx.notify?.('Saved successfully.'); if(typeof window!=='undefined')window.scrollTo(0,savedScrollY); }
        catch {root.innerHTML='<p role="alert">Saved, but the updated workspace could not be loaded. Reload this page to see the saved result.</p>';}
        return result;
      } catch(error) {
        if(feedback) { feedback.textContent=`${error.message || 'Unable to save.'} Your entries are preserved. If this version changed elsewhere, reload it before trying again.`; feedback.setAttribute('role','alert'); offerReload(feedback); }
      } finally {busy=false;controls.forEach((b,i)=>b.disabled=previous[i]);}
    };
    // Upload/replace the Program Identity logo (multipart, so this bypasses the
    // JSON-only `api` helper and posts directly, same permission-gated route).
    const uploadLogo = async file => {
      if(busy) return;
      busy=true;
      const controls=[...root.querySelectorAll('button,input')], previous=controls.map(b=>b.disabled);
      controls.forEach(b=>b.disabled=true);
      const feedback=root.querySelector('[data-logo-feedback]');
      if(feedback) feedback.textContent='Uploading…';
      const savedScrollY=typeof window!=='undefined'?window.scrollY:0;
      try {
        const body=new FormData(); body.append('logo',file);
        const response=await fetch(`${base}/logo`,{method:'POST',credentials:'same-origin',body});
        const data=await response.json();
        if(!response.ok) throw new Error(typeof data.detail==='string'?data.detail:'Unable to upload this logo.');
        await refresh(); ctx.notify?.('Program logo saved.'); if(typeof window!=='undefined')window.scrollTo(0,savedScrollY);
      } catch(error) {
        if(feedback) { feedback.textContent=error.message||'Unable to upload this logo.'; feedback.setAttribute('role','alert'); }
      } finally {busy=false;controls.filter(el=>el.isConnected).forEach((el,i)=>el.disabled=previous[i]);}
    };
    root.innerHTML='<p role="status">Loading Programs…</p>';
    const programs=await api('/api/talent/programs');
    if(!pid) {
      const summaries=await Promise.all(programs.map(async program=>{
        const programBase=`/api/talent/programs/${program.id}`;
        const [years,frameworks]=await Promise.all([api(`${programBase}/academic-years`),api(`${programBase}/frameworks`)]);
        const current=years.find(item=>String(item.academic_year_id)===String(year));
        const active=frameworks.find(item=>item.status==='active');
        let type='Not set';
        if(active){const configuration=await api(`${programBase}/frameworks/${active.id}/configuration`);type=configuration.kpi?.enabled?'Numeric + rubric':'Rubric';}
        return {program,current,type};
      }));
      const rows=summaries.map(({program,current,type})=>`<tr data-program-row data-search="${esc(program.name.toLowerCase())}"><th scope="row">${logoBadge(program,'tp-logo-sm')} ${esc(program.name)}</th><td>${current?.eligible_grade_levels?.map(g=>g==='KG'?'KG':`Grade ${esc(g)}`).join(', ')||'Not set'}</td><td>${esc(type)}</td><td>${current?.is_enabled?'Enabled':'Not set'}</td><td><span class="tp-badge">${esc(program.status)}</span></td><td><div class="tp-row-actions"><a href="${esc(href('programs',{program_id:program.id}))}">${icon('eye')}Open</a>${manage&&program.status!=='retired'?`<a href="${esc(href('programs',{program_id:program.id}))}#tp-basics">${icon('edit')}Edit</a>`:''}</div></td></tr>`).join('');
      root.innerHTML=`<div class="tp-section-lede"><div><h2>Programs</h2><p>Open a Program to set its grades, assessment rubric, and evaluation schedule.</p></div>${manage?'<button type="button" data-action="new-program">New Program</button>':''}</div><label class="tp-search">Search Programs<input type="search" data-program-search placeholder="Search by Program name"></label><div class="tp-table-wrap"><table class="tp-compact-table"><thead><tr><th>Program</th><th>Grades</th><th>Scoring Mode</th><th>Current Year</th><th>Status</th><th>Actions</th></tr></thead><tbody>${rows||'<tr><td colspan="6">No Programs yet.</td></tr>'}</tbody></table></div>${manage?`<div data-new-program hidden>${form('create-program','New Program',field('name','Program name','', 'text',true)+area('description','What does this Program evaluate?'))}</div>`:''}`;
      root.oninput=event=>{if(event.target.matches('[data-program-search]')){const term=event.target.value.trim().toLowerCase();root.querySelectorAll('[data-program-row]').forEach(row=>{row.hidden=!row.dataset.search.includes(term);});return;}const edited=event.target.closest('form');if(edited){dirtyForms.add(edited);edited.dataset.dirty='true';showDirty();}};
      root.onclick=event=>{if(event.target.closest('[data-action="new-program"]'))root.querySelector('[data-new-program]').hidden=false;};
      root.querySelector('form')?.addEventListener('submit',async event=>{event.preventDefault();const d=new FormData(event.target);await mutate('/api/talent/programs','POST',{name:d.get('name'),description:d.get('description')},event.target);});
      return;
    }
    const program=programs.find(p=>String(p.id)===pid);
    if(!program) {root.innerHTML='<p class="tp-empty">Program unavailable in your organization.</p>';return;}
    const base=`/api/talent/programs/${program.id}`;
    // Real Grades configured in Planning anywhere in the organization for this
    // Academic Year (Program eligibility has no Branch selection) - never a
    // fabricated/blanket KG-12 catalog.
    const configuredGrades=year?await api(`/api/talent/programs/planning-grades?academic_year_id=${encodeURIComponent(year)}`).catch(()=>[]):[];
    const [annual,versions,bank]=await Promise.all([api(`${base}/academic-years`),api(`${base}/frameworks`),api(`${base}/competencies`)]);
    const setupRequested=typeof window!=='undefined'?window.location.hash:(ctx.hash||'');
    const chosen=versions.find(f=>String(f.id)===params.get('framework_id')) || (setupRequested?versions.find(f=>f.status==='draft'):versions.find(f=>f.status==='active')) || versions.find(f=>f.status==='draft') || versions.at(-1);
    if(chosen) [framework,config]=await Promise.all([api(`${base}/frameworks/${chosen.id}`),api(`${base}/frameworks/${chosen.id}/configuration`)]);
    if(framework && config.revision != null && (framework.revision!==config.revision || framework.semantic_fingerprint!==config.semantic_fingerprint)) {
      root.innerHTML='<p role="alert">This version changed while it was loading. Reload the page to open the latest saved version.</p>';return;
    }
    members=framework?.competencies || [];
    const fp=framework?`${base}/frameworks/${framework.id}`:'', editable=manage && framework?.status==='draft';
    const annualYear=annual.find(a=>String(a.academic_year_id)===String(year));
    const levels=config?.levels || [], policy=config?.review_candidate_policy, kpi=config?.kpi;
    const memberName=m=>m.label || bank.find(c=>c.id===m.competency_id)?.name || 'Unnamed competency';
    const descriptorTotal=members.length*levels.length, descriptorSaved=config?.descriptors?.filter(item=>String(item.descriptor||'').trim()).length||0;
    const basicsComplete=Boolean(annualYear?.is_enabled&&annualYear.eligible_grade_levels?.length);
    const assessRemaining=(members.length?0:1)+(levels.length?0:1)+Math.max(0,descriptorTotal-descriptorSaved);
    const assessComplete=Boolean(members.length&&levels.length&&descriptorTotal===descriptorSaved);
    let plans=[];
    if(can('talent_evaluation_plans.view')) { const loaded=await api(`/api/talent/evaluation-plans?${new URLSearchParams({academic_year_id:year||'',program_id:pid})}`).catch(()=>[]); plans=Array.isArray(loaded)?loaded:[]; }
    const scheduleComplete=plans.some(item=>item.periods?.length);
    const hashes={basics:'#tp-basics',assess:'#tp-builder',schedule:'#tp-schedule',ready:'#tp-ready'};
    const requested=typeof window!=='undefined'?window.location.hash:(ctx.hash||(params.get('step')?hashes[params.get('step')]:''));
    const activeStep=requested.startsWith('#tp-builder')?'assess':Object.entries(hashes).find(([,hash])=>hash===requested)?.[0]||'basics';
    const stepState={basics:basicsComplete,assess:assessComplete,schedule:scheduleComplete,ready:basicsComplete&&assessComplete&&scheduleComplete};
    const setupComplete=program.status==='active'&&framework?.status==='active'&&stepState.ready;
    const explicitSetup=Boolean(requested);
    if(setupComplete&&!explicitSetup){
      const grades=(annualYear?.eligible_grade_levels||[]).map(g=>g==='KG'?'KG':`Grade ${esc(g)}`).join(', ');
      const periodCount=plans.reduce((count,item)=>count+(item.periods?.length||0),0);
      const scoringMode=kpi?.enabled?'Numeric + rubric':(levels.length?'Rubric':'Not set');
      root.innerHTML=`<div data-status role="status" aria-live="polite"></div><a href="${esc(href('programs',{program_id:''}))}">← All Programs</a><header id="tp-overview" class="tp-section-lede">${logoBadge(program,'tp-logo-md')}<div><span class="tp-badge">${esc(program.status)}</span><h2>${esc(program.name)}</h2><p>${esc(program.description||'')}</p><p>${esc(yearLabel)} · ${annualYear?.is_enabled?'Enabled':'Not enabled'}</p></div></header><section class="tp-program-summary" aria-label="Program summary"><dl><div><dt>Grades</dt><dd>${grades||'Not configured'}</dd></div><div><dt>Competencies</dt><dd>${members.length}</dd></div><div><dt>Rubric levels</dt><dd>${levels.length}</dd></div><div><dt>Scoring Mode</dt><dd>${esc(scoringMode)}${kpi?.enabled?` <span class="tp-badge">Numeric result enabled</span>`:''}</dd></div><div><dt>Evaluation Periods</dt><dd>${periodCount}</dd></div><div><dt>Assessment setup</dt><dd>Ready</dd></div></dl></section><div class="tp-summary-actions">${manage?`<a href="#tp-basics">${icon('edit')}Edit Program</a><a href="#tp-builder-competencies">${icon('edit')}Edit What we assess</a>`:''}${kpi?.enabled||manage?`<a href="#tp-builder-review">${icon('eye')}${kpi?.enabled?'Numeric result settings':'Set up numeric result'}</a>`:''}${can('talent_evaluation_plans.view')?`<a href="#tp-schedule">Manage Evaluation Plan</a>`:''}${can('talent_assessments.view')?`<a href="${esc(href('assessments'))}">${icon('eye')}Open Assessments</a>`:''}${can('talent_analytics.view')?`<a href="${esc(href('portfolio'))}">${icon('eye')}View Results</a>`:''}</div>`;
      return;
    }
    const stepReason={assess:assessRemaining?`${assessRemaining} item${assessRemaining===1?'':'s'} remaining`:''};
    const nav=[['basics','Basics'],['assess','What we assess'],['schedule','Evaluation Plan'],['ready','Ready']].map(([key,label],index)=>`<a href="${hashes[key]}" data-step="${key}" class="tp-step ${key===activeStep?'tp-step-current':stepState[key]?'tp-step-complete':'tp-step-pending'}" ${key===activeStep?'aria-current="step"':''}><span>${stepState[key]?icon('check'):index+1}</span><b>${label}</b>${stepReason[key]?`<small>${esc(stepReason[key])}</small>`:''}</a>`).join('');
    if(typeof window!=='undefined') { hashGuard=()=>render(ctx); window.addEventListener('hashchange',hashGuard); }
    const substeps={competencies:'#tp-builder-competencies',rubric:'#tp-builder-rubric',descriptions:'#tp-builder-descriptions',review:'#tp-builder-review'};
    const activeSub=Object.entries(substeps).find(([,hash])=>hash===requested)?.[0]||'competencies';
    const subState={competencies:Boolean(members.length),rubric:Boolean(levels.length),descriptions:Boolean(descriptorTotal&&descriptorTotal===descriptorSaved),review:assessComplete};
    const subnav=[['competencies','Competencies'],['rubric','Rubric Levels'],['descriptions','Descriptions'],['review','Review']].map(([key,label],index)=>`<a href="${substeps[key]}" class="tp-substep ${key===activeSub?'is-current':subState[key]?'is-complete':''}" ${key===activeSub?'aria-current="step"':''}><span>${subState[key]?icon('check'):index+1}</span>${label}</a>`).join('');
    const setupVersion = !framework
      ? (manage&&program.status!=='retired'?form('new-version','Start assessment setup',field('title','Setup name',`${program.name} assessment setup`,'text',true)+area('summary','What will this setup assess?'),'Start Setup'):'<p class="tp-empty">Assessment setup has not been created.</p>')
      : (!editable&&manage&&program.status!=='retired'?`<button type="button" data-reveal="new-version">${icon('edit')}Edit assessment setup</button><div data-editor="new-version" hidden>${form('new-version','Create an editable setup',field('title','Setup name',`${program.name} updated setup`,'text',true)+area('summary','What is changing?')+check('clone','Copy the current competencies, rubric, and rules',true),'Create Editable Setup')}</div>`:'');
    const competencyRows=members.map((m,i)=>`<tr><th scope="row">${esc(memberName(m))}</th><td>${esc(m.description||'—')}</td><td><div class="tp-row-actions">${editable?`${button('reveal-editor','Edit',`data-editor-key="member-${m.competency_id}"`,'edit')}${button('remove-member','Remove',`data-key="${m.competency_id}"`,'trash')}`:''}</div><div data-editor="member-${m.competency_id}" hidden>${editable?form(`member:${m.competency_id}`,'Edit competency',field('label','Name',memberName(m),'text',true)+area('description','Description',m.description)):''}</div></td></tr>`).join('');
    const competenciesPanel=`<div data-assess-panel="competencies"><h3>Competencies</h3>${framework?`<div class="tp-table-wrap"><table class="tp-compact-table"><thead><tr><th>Name</th><th>Description</th><th>Actions</th></tr></thead><tbody>${competencyRows||'<tr><td colspan="3">No competencies yet.</td></tr>'}</tbody></table></div>`:setupVersion}${editable?`<p><button type="button" data-reveal="add-competency">+ Add Competency</button></p><div data-editor="add-competency" hidden>${form('create-competency','Add competency',field('code','Short code','','text',true)+field('name','Name','','text',true)+area('description','Description'),'Add Competency')}${bank.some(c=>c.status==='active'&&!members.some(m=>m.competency_id===c.id))?form('add-member','Use an existing competency',select('competency_id','Competency',bank.filter(c=>c.status==='active'&&!members.some(m=>m.competency_id===c.id)).map(c=>[c.id,c.name]),''),'Add Competency'):''}</div>`:''}<div class="tp-wizard-actions"><a href="#tp-basics">Back</a><a class="tp-primary-link" href="${substeps.rubric}">Next: Rubric Levels</a></div></div>`;
    const levelRows=levels.map(l=>`<tr><th scope="row">${rubricVisual().badge(l,levels)}</th><td>${esc(l.description||'—')}</td><td><div class="tp-row-actions">${editable?`${button('reveal-editor','Edit',`data-editor-key="level-${l.id}"`,'edit')}${button('remove-level','Remove',`data-key="${l.id}"`,'trash')}`:''}</div><div data-editor="level-${l.id}" hidden>${editable?form(`level:${l.id}`,'Edit level',field('label','Level name',l.label,'text',true)+area('description','Description',l.description)+field('numeric_value','Numeric value (optional)',l.numeric_value,'number')):''}</div></td></tr>`).join('');
    const rubricPanel=`<div data-assess-panel="rubric"><h3>Rubric Levels</h3>${framework?`<p><strong>${esc(config.rubric?.name||'Rubric')}</strong> ${editable?button('reveal-editor','Edit rubric',`data-editor-key="rubric"`,'edit'):''}</p><div data-editor="rubric" hidden>${editable?form('rubric','Edit rubric',field('name','Rubric name',config.rubric?.name,'text',true)+area('description','How to use this rubric',config.rubric?.description)):''}</div><div class="tp-table-wrap"><table class="tp-compact-table"><thead><tr><th>Level</th><th>Description</th><th>Actions</th></tr></thead><tbody>${levelRows||'<tr><td colspan="3">No rubric levels yet.</td></tr>'}</tbody></table></div>${editable&&config.rubric?`<p><button type="button" data-reveal="add-level">+ Add Level</button></p><div data-editor="add-level" hidden>${form('add-level','Add rubric level',field('code','Short code','','text',true)+field('label','Level name','','text',true)+area('description','Description')+field('numeric_value','Numeric value (optional)','','number'),'Add Level')}</div>`:''}`:setupVersion}<div class="tp-wizard-actions"><a href="${substeps.competencies}">Back</a><a class="tp-primary-link" href="${substeps.descriptions}">Next: Achievement Descriptions</a></div></div>`;
    const descriptionRows=members.flatMap(m=>levels.map(l=>{const d=config?.descriptors?.find(item=>item.framework_competency_id===m.id&&item.rubric_level_id===l.id);const key=`description-${m.id}-${l.id}`;return `<tr><th scope="row">${esc(memberName(m))}</th><td>${rubricVisual().badge(l,levels)}</td><td>${esc(d?.descriptor||'Not described yet.')}</td><td><div class="tp-row-actions">${editable?button('reveal-editor','Edit',`data-editor-key="${key}"`,'edit'):''}${editable&&d?button('remove-descriptor','Remove',`data-key="${d.id}"`,'trash'):''}</div><div data-editor="${key}" hidden>${editable?form(`descriptor:${m.id}:${l.id}`,'Edit achievement description',area('descriptor','Description',d?.descriptor),'Save Description'):''}</div></td></tr>`;})).join('');
    const descriptionsPanel=`<div data-assess-panel="descriptions"><h3>Achievement Descriptions</h3>${members.length&&levels.length?`<div class="tp-table-wrap"><table class="tp-compact-table"><thead><tr><th>Competency</th><th>Level</th><th>Description</th><th>Action</th></tr></thead><tbody>${descriptionRows}</tbody></table></div>`:'<p class="tp-empty">Add competencies and rubric levels first.</p>'}<div class="tp-wizard-actions"><a href="${substeps.rubric}">Back</a><a class="tp-primary-link" href="${substeps.review}">Review &amp; Continue</a></div></div>`;
    const reviewPanel=`<div data-assess-panel="review"><h3>Review</h3><div class="tp-assessment-view">${members.map(m=>`<article class="tp-competency-row"><div><h4>${esc(memberName(m))}</h4><p>${esc(m.description||'')}</p></div><dl>${levels.map(l=>{const d=config?.descriptors?.find(item=>item.framework_competency_id===m.id&&item.rubric_level_id===l.id);return `<div><dt>${rubricVisual().badge(l,levels)}</dt><dd>${esc(d?.descriptor||'Not described yet.')}</dd></div>`;}).join('')}</dl></article>`).join('')||'<p class="tp-empty">Assessment setup is incomplete.</p>'}</div><details class="tp-card"><summary>Advanced setup and history</summary><p>Changes to an active assessment setup create a new saved setup so historical evaluations remain unchanged.</p><div class="tp-actions">${versions.map(v=>`<a class="tp-badge" href="${esc(href('programs',{framework_id:v.id}))}#tp-builder-review">${esc(v.title)} · ${esc(v.status)}</a>`).join('')}</div>${setupVersion}${framework?`<details><summary>Optional numeric result</summary>${editable?form('kpi','Numeric result settings',check('is_enabled','Enable numeric result',kpi?.enabled??false)+field('result_scale_min','Scale minimum',kpi?.scale_min,'number')+field('result_scale_max','Scale maximum',kpi?.scale_max,'number')+area('interpretation','How to interpret the result',kpi?.interpretation)+members.map(m=>field(`weight_${m.id}`,`${memberName(m)} weight (%)`,(kpi?.components.find(c=>c.framework_competency_id===m.id)?.weight_basis_points||0)/100,'number')).join('')):''}</details><details><summary>Program criteria</summary>${editable?form('policy','Program criteria',check('is_enabled','Enable Program criteria',policy?.enabled??false)+select('match_mode','Flag when',[['all','All selected rules match'],['any','Any selected rule matches']],policy?.match_mode||'all')+area('description','Explain the review criteria',policy?.description)+members.map(m=>select(`rule_${m.id}`,`${memberName(m)} at or above`,[['','No rule'],...levels.map(l=>[l.id,l.label])],policy?.rules.find(r=>r.framework_competency_id===m.id)?.rubric_level_id||'')).join('')):''}</details>`:''}</details><div class="tp-wizard-actions"><a href="${substeps.descriptions}">Back</a><a class="tp-primary-link" href="#tp-schedule">Save &amp; Continue</a></div></div>`;
    const assessPanel=`<section id="tp-builder" class="tp-wizard-panel"><h2>What we assess</h2><nav class="tp-substeps" aria-label="Assessment setup steps">${subnav}</nav>${({competencies:competenciesPanel,rubric:rubricPanel,descriptions:descriptionsPanel,review:reviewPanel})[activeSub]}</section>`;
    root.innerHTML=`<div data-status role="status" aria-live="polite"></div><a href="${esc(href('programs',{program_id:''}))}">← All Programs</a><header id="tp-overview" class="tp-section-lede">${logoBadge(program,'tp-logo-md')}<div><span class="tp-badge">${esc(program.status)}</span><h2>${esc(program.name)}</h2><p>${esc(program.description||'Add a description while this Program is a draft.')}</p></div></header><nav class="tp-tabs" aria-label="Program workspace">${nav}</nav>
      ${activeStep==='basics'?`<section id="tp-basics" class="tp-wizard-panel"><h2>Program Basics</h2>${manage&&program.status!=='retired'&&year?`<form class="tp-card tp-editor tp-basics-form" data-form="basics"><div class="tp-identity-row">${logoBadge(program,'tp-logo-md')}<div>${program.status==='draft'?field('name','Program name',program.name,'text',true):`<h3>${esc(program.name)}</h3>`}<div class="tp-actions"><label class="tp-file-action">${icon('upload')}${program.logo_url?'Replace Logo':'Upload Logo'}<input type="file" accept="image/png,image/jpeg,image/webp,image/svg+xml,.png,.jpg,.jpeg,.webp,.svg" data-logo-input hidden></label>${program.logo_url?button('remove-logo','Remove Logo','','trash'):''}</div></div></div>${program.status==='draft'?area('description','What does this Program assess?',program.description):`<p>${esc(program.description||'No description added.')}</p>`}<p><strong>Academic Year:</strong> ${esc(yearLabel)}</p>${check('is_enabled','Program enabled for this year',annualYear?.is_enabled??true)}${configuredGrades.length?`<fieldset><legend>Grades from Planning</legend>${configuredGrades.map(g=>check(`grade_${g}`,g==='KG'?'KG':`Grade ${g}`,annualYear?.eligible_grade_levels.includes(g))).join('')}</fieldset>`:'<p class="tp-inline-empty">No Grades are configured in Planning for this Academic Year.</p>'}<div class="tp-wizard-actions"><button type="reset">Reset</button><button type="submit">Save &amp; Continue</button></div><p data-feedback role="status" aria-live="polite"></p></form>`:`<div class="tp-card"><div class="tp-identity-row">${logoBadge(program,'tp-logo-md')}<div><h3>${esc(program.name)}</h3><p>${esc(program.description||'')}</p></div></div><p><strong>Academic Year:</strong> ${esc(yearLabel||'Not selected')}</p><p>${annualYear?.is_enabled?'Enabled':'Not enabled'} · ${(annualYear?.eligible_grade_levels||[]).join(', ')||'No Grades configured'}</p></div><div class="tp-wizard-actions"><a class="tp-primary-link" href="#tp-builder">Continue</a></div>`}${govern&&program.status!=='retired'?`<div class="tp-actions">${button('program-state',program.status==='draft'?'Activate Program':'Retire Program')}</div>`:''}</section>`:''}
      ${activeStep==='assess'?assessPanel:''}
      ${activeStep==='schedule'?`<section id="tp-schedule" class="tp-wizard-panel"><h2>Evaluation Plan</h2><div data-embedded-schedule><p role="status">Loading Evaluation Plan…</p></div></section>`:''}
      ${activeStep==='ready'?`<section id="tp-ready" class="tp-wizard-panel"><h2>Ready</h2><ul class="tp-ready-list"><li>${basicsComplete?icon('check'):'○'} Program details complete</li><li>${annualYear?.eligible_grade_levels?.length?icon('check'):'○'} Grades configured</li><li>${members.length?icon('check'):'○'} Competencies configured</li><li>${levels.length?icon('check'):'○'} Rubric configured</li><li>${assessComplete?icon('check'):'○'} Achievement descriptions complete</li><li>${scheduleComplete?icon('check'):'○'} Evaluation Plan configured</li></ul><div class="tp-wizard-actions"><a href="#tp-schedule">Back</a>${setupComplete?button('finish-setup','Finish Setup'): `<a class="tp-primary-link" href="${!basicsComplete?'#tp-basics':!assessComplete?'#tp-builder-competencies':'#tp-schedule'}">Finish Setup</a>`}</div></section>`:''}`;
    root.onchange=event=>{
      const fileInput=event.target.closest('[data-logo-input]');
      if(fileInput&&fileInput.files&&fileInput.files[0])uploadLogo(fileInput.files[0]);
    };
    root.onsubmit=async event=>{
      event.preventDefault();const f=event.target,d=new FormData(f),action=f.dataset.form;let path=base,method='PUT',body={},rev={expected_revision:framework?.revision};
      if(action==='basics'){
        if(program.status==='draft')try{await api(base,{method:'PATCH',body:JSON.stringify({name:d.get('name'),description:d.get('description')})});}catch(error){const feedback=f.querySelector('[data-feedback]');if(feedback){feedback.textContent=error.message||'Unable to save Program details.';feedback.setAttribute('role','alert');}return;}
        path+=`/academic-years/${year}`;body={is_enabled:d.has('is_enabled'),eligible_grade_levels:configuredGrades.filter(g=>d.has(`grade_${g}`))};
      }
      else if(action==='edit-program'){method='PATCH';body={name:d.get('name'),description:d.get('description')};}
      else if(action==='annual'){path+=`/academic-years/${year}`;body={is_enabled:d.has('is_enabled'),eligible_grade_levels:configuredGrades.filter(g=>d.has(`grade_${g}`))};}
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
      const saved=await mutate(path,method,body,f);
      if(saved&&(action==='annual'||action==='basics')&&typeof window!=='undefined')window.location.hash=hashes.assess;
    };
    root.onclick=async event=>{
      const reveal=event.target.closest('[data-reveal],[data-action="reveal-editor"]');
      if(reveal&&(reveal.dataset.reveal||reveal.dataset.editorKey)){
        const key=reveal.dataset.reveal||reveal.dataset.editorKey;
        root.querySelectorAll('[data-editor]').forEach(editor=>{editor.hidden=editor.dataset.editor!==key;});
        const editor=root.querySelector(`[data-editor="${key}"]`);if(editor){editor.hidden=false;editor.querySelector('input,textarea,select')?.focus();}
        return;
      }
      const b=event.target.closest('[data-action]');if(!b||busy)return;const a=b.dataset.action;
      if(a==='finish-setup'){
        if(typeof window!=='undefined'){window.history.replaceState(null,'',window.location.pathname+window.location.search);await render(ctx);}
        return;
      }
      if(dirty&&!window.confirm('This action reloads the workspace. Discard unsaved edits?'))return;
      let path=fp,method='POST',body={expected_revision:framework?.revision};
      if(a==='program-state'){if(!window.confirm(program.status==='draft'?'Activate this Program?':'Retire this Program?'))return;path=`${base}/lifecycle/${program.status==='draft'?'active':'retired'}`;body=undefined;}
      else if(a==='remove-logo'){if(!window.confirm('Remove the Program logo? This cannot be undone.'))return;path=`${base}/logo`;method='DELETE';body=undefined;}
      else if(a==='activate-version'){if(!window.confirm('Activate this version for future evaluations? The existing active version will be superseded.'))return;path+='/activate';body.expected_fingerprint=framework.semantic_fingerprint;}
      else if(a==='retire-version'){if(!window.confirm('Retire this version? Existing assessment history is preserved.'))return;path+='/retire';body=undefined;}
      else if(a==='remove-member'||a==='remove-level'||a==='remove-descriptor'){if(!window.confirm('Remove this item from the draft version?'))return;path+=a==='remove-member'?`/competencies/${b.dataset.key}`:a==='remove-level'?`/rubric/levels/${b.dataset.key}`:`/rubric/descriptors/${b.dataset.key}`;path+=`?expected_revision=${framework.revision}`;method='DELETE';body=undefined;}
      else if(a==='remove-kpi'||a==='remove-policy'){if(!window.confirm(a==='remove-kpi'?'Remove the optional numeric result settings?':'Remove all Program criteria from this draft version?'))return;path+=a==='remove-kpi'?'/kpi':'/review-candidate-policy';path+=`?expected_revision=${framework.revision}`;method='DELETE';body=undefined;}
      else if(a==='move-member'||a==='move-level'){const i=Number(b.dataset.index),items=(a==='move-member'?members.map(m=>m.competency_id):levels.map(l=>l.id));if(i<1)return;[items[i-1],items[i]]=[items[i],items[i-1]];method='PUT';path+=a==='move-member'?'/competencies/order':'/rubric/levels/order';body[a==='move-member'?'competency_ids':'level_ids']=items;}
      else return;
      await mutate(path,method,body);
    };
    if(activeStep==='schedule'&&can('talent_evaluation_plans.view')) {
      const scheduleRoot=root.querySelector('[data-embedded-schedule]');
      const scheduleRenderer=ctx.renderSchedule||(typeof window!=='undefined'&&window.TalentEvaluationWorkspace?.render);
      if(scheduleRoot&&scheduleRenderer)await scheduleRenderer({...ctx,root:scheduleRoot,params:new URLSearchParams({academic_year_id:year||'',program_id:pid}),embedded:true});
    }
  }
  if(typeof module!=='undefined'&&module.exports)module.exports={render,esc,kpiComponents,numeric,logoInitials,logoBadge};
  if(typeof window!=='undefined'){window.TalentProgramIdentity={logoInitials,logoBadge};window.TalentProgramWorkspace={render,icon};}
})();
