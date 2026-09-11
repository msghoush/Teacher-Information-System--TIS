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
  // Bounded, same-Program-context cache for the wizard data fetch chain
  // (Program record, annual config, framework versions, competency bank,
  // active/draft framework+configuration, Evaluation Plans). Keyed on
  // exactly the inputs that select which data to show (Program, Academic
  // Year, requested framework version) - never on the wizard step hash,
  // which only changes which already-fetched panel is displayed. Only a
  // same-page wizard-step (hash-only) navigation may reuse it; every real
  // navigation/context change/explicit Refresh/post-save reload always
  // fetches fresh data and refreshes the cache. renderToken guards the
  // fetch path itself so a superseded in-flight render can never overwrite
  // the screen with a stale response.
  let bundleCache = null, renderToken = 0;
  function kpiComponents(data, members) {
    return members.map(m=>({framework_competency_id:m.id,weight_basis_points:Math.round(Number(data.get(`weight_${m.id}`))*100)})).filter(c=>c.weight_basis_points>0);
  }
  async function render(ctx, options = {}) {
    const viaHash = options.viaHash === true;
    const {root,api,can} = ctx, params=ctx.params || new URLSearchParams();
    root.oninput=null; root.onsubmit=null; root.onclick=null; root.onreset=null;
    root.classList?.add('tp-program-workspace');
    if(typeof window!=='undefined' && unloadGuard)window.removeEventListener('beforeunload',unloadGuard);
    if(typeof window!=='undefined' && hashGuard)window.removeEventListener('hashchange',hashGuard);
    const year = ctx.year?.value ?? ctx.year, yearLabel=ctx.yearLabel||ctx.year?.options?.[ctx.year.selectedIndex]?.textContent||String(year||''), pid=params.get('program_id');
    const bundleKey = pid?`${pid}::${year||''}::${params.get('framework_id')||''}`:'';
    const manage=can('talent_programs.manage'), govern=can('talent_programs.govern');
    const canDeleteCompetency=can('talent_programs.delete_competency');
    const canDeleteRubricLevel=can('talent_programs.delete_rubric_level');
    if (!can('talent_programs.view')) { bundleCache=null; root.innerHTML='<p class="tp-empty">You do not have permission to view Programs.</p>'; return; }
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
    let program, base, configuredGrades, annual, versions, bank, plans;
    const fullRefresh = () => render(ctx);
    const redrawFromCache = async () => {
      if(pid && bundleCache && bundleCache.key===bundleKey) return render(ctx,{viaHash:true});
      return fullRefresh();
    };
    const refreshSelectedProgram = async (scope='framework') => {
      if(!pid || !bundleCache || bundleCache.key!==bundleKey || !base) return fullRefresh();
      const data=bundleCache.data;
      if(scope==='framework'||scope==='framework-bank'){
        if(!framework) return fullRefresh();
        const requests=[
          api(`${base}/frameworks/${framework.id}`),
          api(`${base}/frameworks/${framework.id}/configuration`),
        ];
        if(scope==='framework-bank') requests.push(api(`${base}/competencies`));
        const [nextFramework,nextConfig,nextBank]=await Promise.all(requests);
        data.framework=nextFramework; data.config=nextConfig;
        framework=nextFramework; config=nextConfig;
        if(scope==='framework-bank'){data.bank=nextBank;bank=nextBank;}
      }else if(scope==='program'){
        const [nextProgram,nextAnnual]=await Promise.all([
          api(base),
          api(`${base}/academic-years`),
        ]);
        if(nextProgram){data.program=nextProgram;program=nextProgram;}
        data.annual=nextAnnual;annual=nextAnnual;
      }else if(scope==='plans'){
        const loaded=await api(`/api/talent/evaluation-plans?${new URLSearchParams({academic_year_id:year||'',program_id:pid})}`).catch(()=>[]);
        const nextPlans=Array.isArray(loaded)?loaded:[];
        data.plans=nextPlans;plans=nextPlans;
      }else{
        return fullRefresh();
      }
      return redrawFromCache();
    };
    const offerReload=feedback=>{
      if(!feedback?.ownerDocument)return;
      const reload=feedback.ownerDocument.createElement('button');reload.type='button';reload.textContent='Reload latest saved version';
      reload.addEventListener('click',()=>{if(!dirty||window.confirm('Reload the latest version and discard unsaved edits?'))fullRefresh().catch(()=>{feedback.textContent='Unable to reload. Please try refreshing the page.';});});
      feedback.append(reload);
    };
    const mutate = async (path,method,body,target,refreshMode='framework') => {
      if(busy) return;
      if(target&&[...dirtyForms].some(f=>f!==target)&&!window.confirm('Saving this section will discard unsaved edits in another section. Continue?'))return;
      busy=true;
      const controls=[...root.querySelectorAll('button')], previous=controls.map(b=>b.disabled);
      controls.forEach(b=>b.disabled=true);
      const feedback=target?.querySelector('[data-feedback]') || root.querySelector('[data-status]');
      if(feedback) feedback.textContent='Saving…';
      const savedScrollY=typeof window!=='undefined'?window.scrollY:0;
      try {
        const result=await api(path,{method,body:body === undefined?undefined:JSON.stringify(body)});
        dirty=false;dirtyForms.clear();
        try {
          if(refreshMode==='none'){
            if(feedback) feedback.textContent='Saved.';
          }else if(refreshMode==='full'){
            await fullRefresh();
          }else{
            await refreshSelectedProgram(refreshMode);
          }
          ctx.notify?.('Saved successfully.');
          if(typeof window!=='undefined')window.scrollTo(0,savedScrollY);
        } catch {
          if(feedback) {
            feedback.textContent='Saved. The latest data could not be refreshed automatically; use Refresh if needed.';
            feedback.setAttribute('role','status');
          }
        }
        return result;
      } catch(error) {
        if(feedback) { feedback.textContent=`${error.message || 'Unable to save.'} Your entries are preserved. If this version changed elsewhere, reload it before trying again.`; feedback.setAttribute('role','alert'); offerReload(feedback); }
      } finally {busy=false;controls.filter(b=>b.isConnected!==false).forEach((b,i)=>b.disabled=previous[i]);}
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
        await refreshSelectedProgram('program'); ctx.notify?.('Program logo saved.'); if(typeof window!=='undefined')window.scrollTo(0,savedScrollY);
      } catch(error) {
        if(feedback) { feedback.textContent=error.message||'Unable to upload this logo.'; feedback.setAttribute('role','alert'); }
      } finally {busy=false;controls.filter(el=>el.isConnected).forEach((el,i)=>el.disabled=previous[i]);}
    };
    // Only a same-page wizard-step (hash-only) navigation - the exact
    // trigger behind the Owner-confirmed repeated "Loading Programs..."
    // defect - may reuse an already-fetched, still-current bundle instead
    // of blanking the workspace and re-fetching the entire Program list
    // and this Program's full setup graph just to switch which already-
    // loaded step panel is shown. Every other caller (initial load, the
    // shared "Refresh" control, an Academic Year/Program context change,
    // and every post-save reload through refresh()) always fetches fresh
    // data and refreshes the cache below.
    if (viaHash && pid && bundleCache && bundleCache.key === bundleKey) {
      ({program, base, configuredGrades, annual, versions, bank, plans} = bundleCache.data);
      framework = bundleCache.data.framework; config = bundleCache.data.config;
    } else {
      const token = ++renderToken;
      const alreadyRendered=Boolean(root.querySelector?.('.tp-wizard-panel,.tp-program-summary,[data-program-row]'));
      const existingStatus=root.querySelector?.('[data-status]');
      if(alreadyRendered){
        root.setAttribute?.('aria-busy','true');
        if(existingStatus) existingStatus.textContent='Refreshing Program data…';
      }else{
        root.innerHTML='<p role="status">Loading Programs…</p>';
      }
      if(!pid) {
        const programs=await api('/api/talent/programs');
        if (token !== renderToken) return;
        const [planningGrades,summaryRows]=await Promise.all([
          year?api(`/api/talent/programs/planning-grades?academic_year_id=${encodeURIComponent(year)}`).catch(()=>[]):Promise.resolve([]),
          year?api(`/api/talent/programs/summaries?academic_year_id=${encodeURIComponent(year)}`).catch(()=>programs.map(program=>({...program,annual:null,assessment_type:'Not set'}))):Promise.resolve(programs.map(program=>({...program,annual:null,assessment_type:'Not set'}))),
        ]);
        const summaries=summaryRows.map(program=>({
          program,
          current:program.annual,
          type:program.assessment_type || 'Not set',
        }));
        if (token !== renderToken) return;
        // ADR 0032: "delete" only ever appears in a Program row's own
        // backend-computed `actions` array (talent_programs.py's
        // `_with_actions`) when it is actually Draft with zero related rows
        // AND the actor holds talent_programs.delete plus organization
        // scope - never a client-side status-only guess. Reusing the same
        // window.confirm + mutate() pattern already used by every other
        // destructive action in this module (remove-logo, remove-member,
        // remove-level, remove-descriptor, remove-kpi, remove-policy) so
        // confirmation and error-feedback behavior stay consistent.
        const rows=summaries.map(({program,current,type})=>`<tr data-program-row data-search="${esc(program.name.toLowerCase())}"><th scope="row">${logoBadge(program,'tp-logo-sm')} ${esc(program.name)}</th><td>${current?.eligible_grade_levels?.map(g=>g==='KG'?'KG':`Grade ${esc(g)}`).join(', ')||'Not set'}</td><td>${esc(type)}</td><td>${current?.is_enabled?'Enabled':'Not set'}</td><td><span class="tp-badge">${esc(program.status)}</span></td><td><div class="tp-row-actions"><a href="${esc(href('programs',{program_id:program.id}))}">${icon('eye')}Open Program</a>${(program.actions||[]).includes('delete')?button('delete-program','Delete',`data-id="${program.id}"`,'trash'):''}</div></td></tr>`).join('');
        const newProgramFields=field('name','Program name','', 'text',true)+area('description','Program description')+(planningGrades.length?`<fieldset><legend>Eligible Grades</legend>${planningGrades.map(g=>check(`grade_${g}`,g==='KG'?'KG':`Grade ${g}`,false)).join('')}</fieldset>`:'<p class="tp-inline-empty">No Grades are configured in Planning for this Academic Year.</p>');
        root.innerHTML=`<div data-status role="status" aria-live="polite"></div><div class="tp-section-lede"><div><h2>Programs</h2><p>Create the Program and align it with eligible Grades. Configure the rubric separately from the Program row.</p></div>${manage?'<button type="button" data-action="new-program">New Program</button>':''}</div><label class="tp-search">Search Programs<input type="search" data-program-search placeholder="Search by Program name"></label><div class="tp-table-wrap"><table class="tp-compact-table"><thead><tr><th>Program</th><th>Grades</th><th>Scoring Mode</th><th>Current Year</th><th>Status</th><th>Actions</th></tr></thead><tbody>${rows||'<tr><td colspan="6">No Programs yet.</td></tr>'}</tbody></table></div>${manage?`<div data-new-program hidden>${form('create-program','New Program',newProgramFields,'Save Program')}</div>`:''}`;
        root.oninput=event=>{if(event.target.matches('[data-program-search]')){const term=event.target.value.trim().toLowerCase();root.querySelectorAll('[data-program-row]').forEach(row=>{row.hidden=!row.dataset.search.includes(term);});return;}const edited=event.target.closest('form');if(edited){dirtyForms.add(edited);edited.dataset.dirty='true';showDirty();}};
        root.onclick=async event=>{
          if(event.target.closest('[data-action="new-program"]')){root.querySelector('[data-new-program]').hidden=false;return;}
          const del=event.target.closest('[data-action="delete-program"]');
          if(del){
            if(!window.confirm('Permanently delete this Draft Program? This cannot be undone.'))return;
            await mutate(`/api/talent/programs/${del.dataset.id}`,'DELETE',undefined);
          }
        };
        root.querySelector('form')?.addEventListener('submit',async event=>{
          event.preventDefault();
          const formEl=event.target,d=new FormData(formEl);
          const feedback=formEl.querySelector('[data-feedback]');
          const grades=planningGrades.filter(g=>d.has(`grade_${g}`));
          if(!grades.length){if(feedback){feedback.textContent='Choose at least one eligible Grade.';feedback.setAttribute('role','alert');}return;}
          try{
            const created=await api('/api/talent/programs',{method:'POST',body:JSON.stringify({name:d.get('name'),description:d.get('description')})});
            await api(`/api/talent/programs/${created.id}/academic-years/${year}`,{method:'PUT',body:JSON.stringify({is_enabled:true,eligible_grade_levels:grades})});
            ctx.notify?.('Program saved. Add its rubric when you are ready.');
            await fullRefresh();
          }catch(error){
            if(feedback){feedback.textContent=error.message||'Unable to save Program.';feedback.setAttribute('role','alert');}
          }
        });
        return;
      }
      base=`/api/talent/programs/${pid}`;
      const prefetchedProgram=ctx.programCatalog?.get?.(String(pid)) || null;
      let [selectedProgram,nextGrades,nextAnnual,nextVersions,nextBank,loadedPlans]=await Promise.all([
        prefetchedProgram?Promise.resolve(prefetchedProgram):api(base).catch(()=>null),
        year?api(`/api/talent/programs/planning-grades?academic_year_id=${encodeURIComponent(year)}`).catch(()=>[]):Promise.resolve([]),
        api(`${base}/academic-years`),
        api(`${base}/frameworks`),
        api(`${base}/competencies`),
        can('talent_evaluation_plans.view')
          ? api(`/api/talent/evaluation-plans?${new URLSearchParams({academic_year_id:year||'',program_id:pid})}`).catch(()=>[])
          : Promise.resolve([]),
      ]);
      if (token !== renderToken) return;
      if(!selectedProgram || String(selectedProgram.id)!==String(pid) || !selectedProgram.name){
        const programs=await api('/api/talent/programs');
        if (token !== renderToken) return;
        selectedProgram=programs.find(item=>String(item.id)===String(pid));
      }
      if(!selectedProgram){bundleCache=null;root.innerHTML='<p class="tp-empty">Program unavailable in your organization.</p>';return;}
      program=selectedProgram;
      configuredGrades=nextGrades;
      annual=nextAnnual;
      versions=nextVersions;
      bank=nextBank;
      plans=Array.isArray(loadedPlans)?loadedPlans:[];
      const setupRequested=typeof window!=='undefined'?window.location.hash:(ctx.hash||'');
      const drafts=versions.filter(f=>f.status==='draft').sort((a,b)=>(Number(b.version_number)||0)-(Number(a.version_number)||0)||(Number(b.id)||0)-(Number(a.id)||0));
      const chosen=versions.find(f=>String(f.id)===params.get('framework_id'))
        || (setupRequested?drafts[0]:versions.find(f=>f.status==='active'))
        || drafts[0]
        || versions.at(-1);
      framework=null; config=null;
      if(chosen) [framework,config]=await Promise.all([api(`${base}/frameworks/${chosen.id}`),api(`${base}/frameworks/${chosen.id}/configuration`)]);
      if (token !== renderToken) return;
      if(framework && config.revision != null && (framework.revision!==config.revision || framework.semantic_fingerprint!==config.semantic_fingerprint)) {
        bundleCache=null; root.innerHTML='<p role="alert">This version changed while it was loading. Reload the page to open the latest saved version.</p>';return;
      }
      bundleCache={key:bundleKey,data:{program,base,configuredGrades,annual,versions,bank,framework,config,plans}};
      root.removeAttribute?.('aria-busy');
    }
    members=framework?.competencies || [];
    const fp=framework?`${base}/frameworks/${framework.id}`:'';
    const mutableFramework=framework?.status==='draft' && !framework?.in_use_by_assessments;
    const editable=manage && mutableFramework;
    const deletableCompetency=canDeleteCompetency && mutableFramework;
    const deletableRubricLevel=canDeleteRubricLevel && mutableFramework;
    const annualYear=annual.find(a=>String(a.academic_year_id)===String(year));
    const currentPlan=plans.find(p=>String(p.program_id)===String(program.id)&&String(p.academic_year_id)===String(year)) || null;
    const currentPeriods=currentPlan?.periods || [];
    const evaluationSummary=currentPeriods.length
      ? currentPeriods.map(period=>`<span class="tp-evaluation-chip"><span aria-hidden="true">📅</span>${esc(period.label)}</span>`).join('')
      : '<span class="tp-muted">No Evaluation Periods configured yet.</span>';
    const levels=config?.levels || [], rubrics=config?.rubrics || [], kpi=config?.kpi;
    const descriptorGrades=annualYear?.eligible_grade_levels || [];
    const memberName=m=>m.label || bank.find(c=>c.id===m.competency_id)?.name || 'Unnamed competency';
    const rubricForCompetency=mid=>rubrics.find(r=>Number(r.framework_competency_id)===Number(mid)) || null;
    const levelsForCompetency=mid=>rubricForCompetency(mid)?.levels || [];
    const descriptorFor=(mid,lid,grade)=>config?.descriptors?.find(item=>item.framework_competency_id===mid&&item.rubric_level_id===lid&&String(item.grade_level||'')===String(grade||'')) || config?.descriptors?.find(item=>item.framework_competency_id===mid&&item.rubric_level_id===lid&&!item.grade_level);
    const membersForGrade=grade=>members.filter(m=>!m.grade_level||String(m.grade_level)===String(grade||''));
    const descriptorCells=(descriptorGrades.length?descriptorGrades:[null]).flatMap(grade=>membersForGrade(grade).flatMap(m=>levelsForCompetency(m.id).map(l=>({grade,m,l,d:descriptorFor(m.id,l.id,grade),text:descriptorFor(m.id,l.id,grade)?.descriptor||l.description||''}))));
    const descriptorTotal=descriptorCells.length, descriptorSaved=descriptorCells.filter(cell=>String(cell.text||'').trim()).length;
    const basicsComplete=Boolean(annualYear?.is_enabled&&annualYear.eligible_grade_levels?.length);
    const rubricReady=Boolean(members.length&&members.every(m=>rubricForCompetency(m.id)?.levels?.length || levels.length));
    const assessRemaining=(members.length?0:1)+(rubricReady?0:1)+Math.max(0,descriptorTotal-descriptorSaved);
    const assessComplete=Boolean(members.length&&rubricReady&&descriptorTotal===descriptorSaved);
    const scheduleComplete=plans.some(item=>item.periods?.length);
    const hashes={basics:'#tp-basics',assess:'#tp-builder',schedule:'#tp-schedule'};
    const requested=typeof window!=='undefined'?window.location.hash:(ctx.hash||(params.get('step')?hashes[params.get('step')]:''));
    const rubricMode=requested==='#tp-rubric';
    const activeStep=rubricMode?'rubric':requested.startsWith('#tp-builder')?'assess':Object.entries(hashes).find(([,hash])=>hash===requested)?.[0]||'basics';
    const setupComplete=Boolean(basicsComplete&&assessComplete&&scheduleComplete);
    const stepState={basics:basicsComplete,assess:assessComplete,schedule:scheduleComplete};
    const explicitSetup=Boolean(requested);
    if(typeof window!=='undefined') {
      hashGuard=()=>render(ctx,{viaHash:true});
      window.addEventListener('hashchange',hashGuard);
    }
    if(!explicitSetup){
      const grades=(annualYear?.eligible_grade_levels||[]).map(g=>g==='KG'?'KG':`Grade ${esc(g)}`).join(', ');
      const periodCount=plans.reduce((count,item)=>count+(item.periods?.length||0),0);
      const scoringMode=kpi?.enabled?'Numeric result + assessment criteria':(rubricReady?'Assessment criteria':'Not set');
      const gradeRubricSummary=(annualYear?.eligible_grade_levels||[]).map(g=>{
        const label=g==='KG'?'KG':`Grade ${g}`;
        const gradeMembers=members.filter(m=>String(m.grade_level||'')===String(g));
        const summary=gradeMembers.map(m=>{
          const rubric=rubricForCompetency(m.id);
          const count=rubric?.levels?.length || levels.length;
          return `<li><strong>${esc(memberName(m))}</strong> — ${esc(rubric?.name||config?.rubric?.name||'Rubric not configured')} · ${count} level${count===1?'':'s'}</li>`;
        }).join('');
        return `<details class="tp-card tp-grade-rubric"><summary><strong>${esc(label)}</strong><span>${gradeMembers.length} competenc${gradeMembers.length===1?'y':'ies'}</span></summary><div class="tp-grade-rubric-body">${gradeMembers.length?`<ul>${summary}</ul>`:'<p class="tp-empty">No competencies configured yet.</p>'}</div></details>`;
      }).join('');
      root.innerHTML=`<div data-status role="status" aria-live="polite"></div><a href="${esc(href('programs',{program_id:''}))}">← All Programs</a><header id="tp-overview" class="tp-section-lede">${logoBadge(program,'tp-logo-md')}<div><span class="tp-badge">${esc(program.status)}</span><h2>${esc(program.name)}</h2><p>${esc(program.description||'')}</p><p>${esc(yearLabel)} · ${annualYear?.is_enabled?'Enabled':'Not enabled'}</p></div></header><section class="tp-program-summary" aria-label="Program summary"><div class="tp-readiness-banner ${setupComplete?'is-ready':'is-incomplete'}"><strong>${setupComplete?'✓ Ready':'Setup incomplete'}</strong><span>${setupComplete?'Program, assessment criteria, and Evaluation Plan are configured.':'Complete the missing Program, assessment criteria, and Evaluation Plan items before starting.'}</span></div><dl><div><dt>Grades</dt><dd>${grades||'Not configured'}</dd></div><div><dt>Competencies</dt><dd>${members.length}</dd></div><div><dt>Assessment criteria</dt><dd>${rubrics.filter(r=>r.framework_competency_id!=null).length || (levels.length?1:0)}</dd></div><div><dt>Scoring Mode</dt><dd>${esc(scoringMode)}${kpi?.enabled?` <span class="tp-badge">Numeric result enabled</span>`:''}</dd></div><div><dt>Evaluation Periods</dt><dd>${periodCount}</dd></div><div><dt>Assessment setup</dt><dd>${assessComplete?'Complete':'Needs setup'}</dd></div></dl></section>${gradeRubricSummary?`<section><h3>Assessment criteria overview</h3><div class="tp-grade-accordion">${gradeRubricSummary}</div></section>`:''}<div class="tp-summary-actions">${manage?`<a href="#tp-basics">${icon('edit')}Edit Program</a><a href="#tp-rubric">${icon('edit')}Build / Edit Assessment Criteria</a>`:''}${can('talent_evaluation_plans.view')?`<a href="#tp-schedule">Manage Evaluation Plan</a>`:''}${setupComplete&&govern?button('finish-setup','Finish Setup'):''}${can('talent_assessments.view')?`<a href="${esc(href('assessments'))}">${icon('eye')}Open Assessments</a>`:''}${can('talent_analytics.view')?`<a href="${esc(href('portfolio'))}">${icon('eye')}View Results</a>`:''}</div>`;
      return;
    }
    const stepReason={assess:assessRemaining?`${assessRemaining} item${assessRemaining===1?'':'s'} remaining`:''};
    const nav=(activeStep==='basics'||activeStep==='rubric')?'':[['assess','What we assess'],['schedule','Evaluation Plan']].map(([key,label],index)=>`<a href="${hashes[key]}" data-step="${key}" class="tp-step ${key===activeStep?'tp-step-current':stepState[key]?'tp-step-complete':'tp-step-pending'}" ${key===activeStep?'aria-current="step"':''}><span>${stepState[key]?icon('check'):index+1}</span><b>${label}</b>${stepReason[key]?`<small>${esc(stepReason[key])}</small>`:''}</a>`).join('');
    const substeps={competencies:'#tp-builder-competencies',rubric:'#tp-builder-rubric',descriptions:'#tp-builder-descriptions',review:'#tp-builder-review'};
    const activeSub=Object.entries(substeps).find(([,hash])=>hash===requested)?.[0]||'competencies';
    const subState={competencies:Boolean(members.length),rubric:Boolean(levels.length),descriptions:Boolean(descriptorTotal&&descriptorTotal===descriptorSaved),review:assessComplete};
    const subnav=[['competencies','Competencies'],['rubric','Rubric Levels'],['descriptions','Descriptions'],['review','Review']].map(([key,label],index)=>`<a href="${substeps[key]}" class="tp-substep ${key===activeSub?'is-current':subState[key]?'is-complete':''}" ${key===activeSub?'aria-current="step"':''}><span>${subState[key]?icon('check'):index+1}</span>${label}</a>`).join('');
    const requestedGrade=params.get('rubric_grade');
    const selectedGrade=descriptorGrades.includes(requestedGrade)?requestedGrade:(descriptorGrades[0]||'');
    const gradePicker=descriptorGrades.length?`<label class="tp-grade-picker">Grade<select data-rubric-grade>${descriptorGrades.map(g=>option(g,g==='KG'?'KG':`Grade ${g}`,selectedGrade)).join('')}</select></label>`:'';
    const rubricGradeSections=(selectedGrade?[selectedGrade]:[]).map((grade)=>{
      const gradeMembers=members.filter(m=>String(m.grade_level||'')===String(grade));
      const gradeLabel=grade==='KG'?'KG':`Grade ${grade}`;
      const competencyCards=gradeMembers.map(m=>{
        const rubric=rubricForCompetency(m.id);
        const memberLevels=rubric?.levels || [];
        const levelRows=memberLevels.map(l=>`
          <div class="tp-rubric-level-node">
            <div class="tp-level-number" aria-label="Level ${l.order || memberLevels.indexOf(l)+1}">${l.order || memberLevels.indexOf(l)+1}</div>
            <div class="tp-level-copy">
              <strong>${l.order || memberLevels.indexOf(l)+1}. ${esc(l.label)}</strong>
              <p>${esc(l.description||'No description yet.')}</p>
            </div>
            ${editable||deletableRubricLevel?`<div class="tp-row-actions">${editable?button('reveal-editor','Edit',`data-editor-key="level-${l.id}"`,'edit'):''}${deletableRubricLevel?button('remove-level','Delete Level',`data-key="${l.id}"`,'trash'):''}</div>${editable?`<div data-editor="level-${l.id}" hidden>${form(`level:${l.id}`,'Edit Level',field('label','Level name',l.label,'text',true)+area('description','Level description',l.description),'Save Level')}</div>`:''}`:''}
          </div>`
        ).join('');
        const copySources=members.filter(source=>source.id!==m.id&&(rubricForCompetency(source.id)?.levels||[]).length).map(source=>[source.id,`${memberName(source)}${source.grade_level?` · ${source.grade_level==='KG'?'KG':`Grade ${source.grade_level}`}`:''}`]);
        const copyLevelForm=editable&&memberLevels.length===0&&copySources.length
          ? `<button type="button" data-reveal="level-copy-${m.id}">${icon('copy')}Copy Levels From…</button><div data-editor="level-copy-${m.id}" hidden>${form(`copy-levels:${m.id}`,'Copy Level Structure',select('source_framework_competency_id','Copy from Competency',copySources,'')+check('include_descriptions','Copy level descriptions too',false),'Copy Levels')}</div>`
          : '';
        const rubricBody=rubric
          ? `<div class="tp-rubric-node"><div class="tp-rubric-node-head"><div><span class="tp-node-label">Rubric</span><strong>${esc(rubric.name)}</strong>${rubric.description?`<p>${esc(rubric.description)}</p>`:''}</div>${editable?button('reveal-editor','Edit Rubric',`data-editor-key="rubric-${m.id}"`,'edit'):''}</div>${editable?`<div data-editor="rubric-${m.id}" hidden>${form(`competency-rubric:${m.id}`,'Edit Rubric',field('name','Rubric name',rubric.name,'text',true)+area('description','Rubric description',rubric.description),'Save Rubric')}</div>`:''}<div class="tp-rubric-level-list">${levelRows||'<p class="tp-empty">No levels yet. Add them manually or copy a completed level structure from another Competency.</p>'}</div>${editable?`<div class="tp-rubric-build-actions"><button type="button" data-reveal="level-add-${m.id}">+ Add Level</button>${copyLevelForm}</div><div data-editor="level-add-${m.id}" hidden>${form(`competency-level:${m.id}`,'Add Level',field('label','Level name','','text',true)+area('description','Level description'),'Add Level')}</div>`:''}</div>`
          : editable
            ? `<button type="button" data-reveal="rubric-add-${m.id}">+ Add Rubric</button><div data-editor="rubric-add-${m.id}" hidden>${form(`competency-rubric:${m.id}`,'Add Rubric',field('name','Rubric name','', 'text',true)+area('description','Rubric description'),'Add Rubric')}</div>`
            : '<p class="tp-empty">No rubric configured.</p>';
        return `<article class="tp-card tp-rubric-competency"><div class="tp-competency-node-head"><div><span class="tp-node-label">Competency</span><h4>${esc(memberName(m))}</h4><p>${esc(m.description||'')}</p></div>${deletableCompetency?button('remove-member','Delete Competency',`data-key="${m.competency_id}"`,'trash'):''}</div>${rubricBody}</article>`;
      }).join('');
      const addCompetencyForm=editable?form(`create-grade-competency:${grade}`,'Add Competency',field('name','Competency name','','text',true)+area('description','Competency description'),'Add Competency'):'';
      return `<details class="tp-card tp-grade-rubric" open><summary><strong>${esc(gradeLabel)}</strong><span>${gradeMembers.length} competenc${gradeMembers.length===1?'y':'ies'}</span></summary><div class="tp-grade-rubric-body">${competencyCards||'<p class="tp-empty">No competencies yet for this Grade.</p>'}${editable?`<button type="button" data-reveal="grade-add-${grade}">+ Add Competency</button><div data-editor="grade-add-${grade}" hidden>${addCompetencyForm}</div>`:''}</div></details>`;
    }).join('');
    const rubricSetupControls=!framework
      ? (manage?form('new-version','Create Rubric Structure',field('title','Rubric setup name',`${program.name} rubric`,'text',true)+area('summary','Optional note'),'Create Rubric Structure'):'<p class="tp-empty">Rubric setup has not been created.</p>')
      : (!editable&&manage?form('new-version','Edit Rubric Structure',field('title','Rubric setup name',`${program.name} updated rubric`,'text',true)+area('summary','What is changing?')+check('clone','Copy the current rubric structure (optional)',false),'Start Editing'):'');
    const rubricWorkspace=`<section id="tp-rubric" class="tp-wizard-panel"><div class="tp-section-lede"><div><h2>Assessment Criteria</h2><p>Choose one Grade, then build Competency → criteria → Levels. Each competency remains independent.</p></div></div>${rubricSetupControls}${framework?`${gradePicker}<div class="tp-grade-accordion">${rubricGradeSections||'<p class="tp-empty">Assign eligible Grades to this Program first.</p>'}</div><div class="tp-wizard-actions"><a href="#tp-basics">Edit Program Grades</a>${editable?button('finish-rubric','Save'):''}</div>`:''}</section>`;

    const setupVersion = !framework
      ? (manage&&program.status!=='retired'?form('new-version','Start assessment setup',field('title','Setup name',`${program.name} assessment setup`,'text',true)+area('summary','What will this setup assess?'),'Start Setup'):'<p class="tp-empty">Assessment setup has not been created.</p>')
      : (!editable&&manage&&program.status!=='retired'?`<button type="button" data-reveal="new-version">${icon('edit')}Edit assessment setup</button><div data-editor="new-version" hidden>${form('new-version','Create an editable setup',field('title','Setup name',`${program.name} updated setup`,'text',true)+area('summary','What is changing?')+check('clone','Copy the current competencies, rubric, and rules',true),'Create Editable Setup')}</div>`:'');
    const gradeOptions=[['','All eligible Grades'],...descriptorGrades.map(g=>[g,g==='KG'?'KG':`Grade ${g}`])];
    const competencyRows=members.filter(m=>!selectedGrade||String(m.grade_level||'')===String(selectedGrade)).map(m=>`<tr><th scope="row">${esc(memberName(m))}</th><td>${esc(m.description||'—')}</td><td><div class="tp-row-actions">${editable||deletableCompetency?`${editable?button('reveal-editor','Edit',`data-editor-key="member-${m.competency_id}"`,'edit'):''}${deletableCompetency?button('remove-member','Delete Competency',`data-key="${m.competency_id}"`,'trash'):''}`:''}</div><div data-editor="member-${m.competency_id}" hidden>${editable?form(`member:${m.competency_id}`,'Edit competency',select('grade_level','Grade',gradeOptions,m.grade_level||'')+field('label','Name',memberName(m),'text',true)+area('description','Description',m.description)):''}</div></td></tr>`).join('');
    const competenciesPanel=`<div data-assess-panel="competencies"><h3>Competencies</h3><p class="tp-note">Choose one Grade, then manage its competencies without repeating the Grade on every row.</p>${gradePicker}${framework?`<div class="tp-table-wrap"><table class="tp-compact-table"><thead><tr><th>Name</th><th>Description</th><th>Actions</th></tr></thead><tbody>${competencyRows||'<tr><td colspan="3">No competencies yet for this Grade.</td></tr>'}</tbody></table></div>`:setupVersion}${editable?`<p><button type="button" data-reveal="add-competency">+ Add Competency</button></p><div data-editor="add-competency" hidden>${form('create-competency','Add competency',field('code','Short code','','text',true)+field('name','Name','','text',true)+area('description','Description'),'Add Competency')}${bank.some(c=>c.status==='active'&&!members.some(m=>m.competency_id===c.id))?form('add-member','Use an existing competency',select('grade_level','Grade',gradeOptions,'')+select('competency_id','Competency',bank.filter(c=>c.status==='active'&&!members.some(m=>m.competency_id===c.id)).map(c=>[c.id,c.name]),''),'Add Competency'):''}</div>`:''}<div class="tp-wizard-actions"><a href="#tp-basics">Back</a><a class="tp-primary-link" href="${substeps.rubric}">Next: Rubric Levels</a></div></div>`;
    const levelRows=levels.map(l=>`<tr><th scope="row">${rubricVisual().badge(l,levels)}</th><td>${esc(l.description||'—')}</td><td><div class="tp-row-actions">${editable||deletableRubricLevel?`${editable?button('reveal-editor','Edit',`data-editor-key="level-${l.id}"`,'edit'):''}${deletableRubricLevel?button('remove-level','Delete Level',`data-key="${l.id}"`,'trash'):''}`:''}</div><div data-editor="level-${l.id}" hidden>${editable?form(`level:${l.id}`,'Edit level',field('label','Level name',l.label,'text',true)+area('description','Description',l.description)+field('numeric_value','Numeric value (optional)',l.numeric_value,'number')):''}</div></td></tr>`).join('');
    const rubricPanel=`<div data-assess-panel="rubric"><h3>Rubric Levels</h3>${framework?`<p><strong>${esc(config.rubric?.name||'Rubric')}</strong> ${editable?button('reveal-editor','Edit rubric',`data-editor-key="rubric"`,'edit'):''}</p><div data-editor="rubric" hidden>${editable?form('rubric','Edit rubric',field('name','Rubric name',config.rubric?.name,'text',true)+area('description','How to use this rubric',config.rubric?.description)):''}</div><div class="tp-table-wrap"><table class="tp-compact-table"><thead><tr><th>Level</th><th>Description</th><th>Actions</th></tr></thead><tbody>${levelRows||'<tr><td colspan="3">No rubric levels yet.</td></tr>'}</tbody></table></div>${editable&&config.rubric?`<p><button type="button" data-reveal="add-level">+ Add Level</button></p><div data-editor="add-level" hidden>${form('add-level','Add rubric level',field('code','Short code','','text',true)+field('label','Level name','','text',true)+area('description','Description')+field('numeric_value','Numeric value (optional)','','number'),'Add Level')}</div>`:''}`:setupVersion}<div class="tp-wizard-actions"><a href="${substeps.competencies}">Back</a><a class="tp-primary-link" href="${substeps.descriptions}">Next: Achievement Descriptions</a></div></div>`;
    const gradeSections=(descriptorGrades.length?descriptorGrades:[null]).map(grade=>{
      const gradeMembers=membersForGrade(grade);
      const heading=grade?(grade==='KG'?'KG':`Grade ${grade}`):'All Grades';
      const competencySections=gradeMembers.map(m=>{
        const rows=levels.map(l=>{
          const d=descriptorFor(m.id,l.id,grade);
          const exact=config?.descriptors?.find(item=>item.framework_competency_id===m.id&&item.rubric_level_id===l.id&&String(item.grade_level||'')===String(grade||''));
          const key=`description-${grade||'general'}-${m.id}-${l.id}`;
          return `<tr><td>${rubricVisual().badge(l,levels)}</td><td>${esc(d?.descriptor||'Not described yet.')}${grade&&d&&!exact?'<small class="tp-muted">General descriptor fallback</small>':''}</td><td><div class="tp-row-actions">${editable?button('reveal-editor','Edit',`data-editor-key="${key}"`,'edit'):''}${editable&&exact?button('remove-descriptor','Remove',`data-key="${exact.id}" data-scope="grade"`,'trash'):''}</div><div data-editor="${key}" hidden>${editable?form(`descriptor:${m.id}:${l.id}:${grade||''}`,'Edit achievement description',area('descriptor','Description',d?.descriptor),'Save Description'):''}</div></td></tr>`;
        }).join('');
        return `<article class="tp-card tp-rubric-competency"><h4>${esc(memberName(m))}</h4><p>${esc(m.description||'')}</p><div class="tp-table-wrap"><table class="tp-compact-table"><thead><tr><th>Level</th><th>Achievement description</th><th>Action</th></tr></thead><tbody>${rows}</tbody></table></div></article>`;
      }).join('');
      return `<section class="tp-grade-rubric"><h4>${esc(heading)}</h4>${competencySections||'<p class="tp-empty">No competencies assigned to this Grade yet.</p>'}</section>`;
    }).join('');
    const descriptionsPanel=`<div data-assess-panel="descriptions"><h3>Achievement Descriptions</h3><p class="tp-note">For each Grade, define every Competency across the ordered rubric Levels. Student assessments use only the competencies assigned to the Student’s recorded Grade.</p>${members.length&&levels.length?gradeSections:'<p class="tp-empty">Add Grade-scoped competencies and rubric levels first.</p>'}<div class="tp-wizard-actions"><a href="${substeps.rubric}">Back</a><a class="tp-primary-link" href="${substeps.review}">Review &amp; Continue</a></div></div>`;
    const reviewPanel=`<div data-assess-panel="review"><h3>Review</h3><div class="tp-assessment-view">${(descriptorGrades.length?descriptorGrades:[null]).map(grade=>`<section class="tp-card"><h4>${esc(grade?(grade==='KG'?'KG':`Grade ${grade}`):'All Grades')}</h4>${membersForGrade(grade).map(m=>`<article class="tp-competency-row"><div><h4>${esc(memberName(m))}</h4><p>${esc(m.description||'')}</p></div><dl>${levels.map(l=>{const d=descriptorFor(m.id,l.id,grade);return `<div><dt>${rubricVisual().badge(l,levels)}</dt><dd>${esc(d?.descriptor||'Not described yet.')}</dd></div>`;}).join('')}</dl></article>`).join('')||'<p class="tp-empty">No competencies assigned to this Grade.</p>'}</section>`).join('')||'<p class="tp-empty">Assessment setup is incomplete.</p>'}</div><details class="tp-card"><summary>Advanced setup and history</summary><p>Changes to an active assessment setup create a new saved setup so historical evaluations remain unchanged.</p><div class="tp-actions">${versions.map(v=>`<a class="tp-badge" href="${esc(href('programs',{framework_id:v.id}))}#tp-builder-review">${esc(v.title)} · ${esc(v.status)}</a>`).join('')}</div>${setupVersion}${framework?`<details><summary>Key Performance Indicator (KPI)</summary>${editable?form('kpi',kpi?'Edit KPI':'Add KPI',check('is_enabled','Enable KPI numeric result',kpi?.enabled??false)+field('result_scale_min','Scale minimum',kpi?.scale_min,'number')+field('result_scale_max','Scale maximum',kpi?.scale_max,'number')+area('interpretation','How to interpret the KPI result',kpi?.interpretation)+members.map(m=>field(`weight_${m.id}`,`${memberName(m)} weight (%)`,(kpi?.components.find(c=>c.framework_competency_id===m.id)?.weight_basis_points||0)/100,'number')).join(''),kpi?'Save KPI':'Add KPI'):''}${editable&&kpi?`<p class="tp-actions">${button('remove-kpi','Delete KPI','','trash')}</p>`:''}</details>`:''}</details><div class="tp-wizard-actions"><a href="${substeps.descriptions}">Back</a><a class="tp-primary-link" href="#tp-schedule">Save &amp; Continue</a></div></div>`;
    const assessPanel=`<section id="tp-builder" class="tp-wizard-panel"><h2>What we assess</h2><nav class="tp-substeps" aria-label="Assessment setup steps">${subnav}</nav>${({competencies:competenciesPanel,rubric:rubricPanel,descriptions:descriptionsPanel,review:reviewPanel})[activeSub]}</section>`;
    root.innerHTML=`<div data-status role="status" aria-live="polite"></div><a href="${esc(href('programs',{program_id:''}))}">← All Programs</a><header id="tp-overview" class="tp-section-lede">${logoBadge(program,'tp-logo-md')}<div><span class="tp-badge">${esc(program.status)}</span><h2>${esc(program.name)}</h2><p>${esc(program.description||'')}</p></div></header>${nav?`<nav class="tp-tabs" aria-label="Program workspace">${nav}</nav>`:''}
      ${activeStep==='basics'?`<section id="tp-basics" class="tp-wizard-panel"><h2>Program Basics</h2>${manage&&program.status!=='retired'&&year?`<form class="tp-card tp-editor tp-basics-form" data-form="basics"><div class="tp-identity-row">${logoBadge(program,'tp-logo-md')}<div>${program.status==='draft'?field('name','Program name',program.name,'text',true):`<h3>${esc(program.name)}</h3>`}<div class="tp-actions"><label class="tp-file-action">${icon('upload')}${program.logo_url?'Replace Logo':'Upload Logo'}<input type="file" accept="image/png,image/jpeg,image/webp,image/svg+xml,.png,.jpg,.jpeg,.webp,.svg" data-logo-input hidden></label>${program.logo_url?button('remove-logo','Remove Logo','','trash'):''}</div></div></div>${program.status==='draft'?area('description','What does this Program assess?',program.description):`<p>${esc(program.description||'No description added.')}</p>`}<p><strong>Academic Year:</strong> ${esc(yearLabel)}</p>${configuredGrades.length?`<fieldset><legend>Eligible Grades</legend>${configuredGrades.map(g=>check(`grade_${g}`,g==='KG'?'KG':`Grade ${g}`,annualYear?.eligible_grade_levels.includes(g))).join('')}</fieldset>`:'<p class="tp-inline-empty">No Grades are configured in Planning for this Academic Year.</p>'}<section class="tp-program-evaluations"><div class="tp-section-heading"><div><p class="tp-eyebrow">Assessment periods</p><h3>Evaluation Periods</h3></div><a class="tp-action-link" href="#tp-schedule">Manage Evaluations →</a></div><p>Choose the user-defined periods when this Program will be assessed during the Academic Year.</p><div class="tp-evaluation-chip-list">${evaluationSummary}</div></section><div class="tp-wizard-actions"><button type="reset">Reset</button><button type="submit">Save Program</button></div><p data-feedback role="status" aria-live="polite"></p></form>`:`<div class="tp-card"><div class="tp-identity-row">${logoBadge(program,'tp-logo-md')}<div><h3>${esc(program.name)}</h3><p>${esc(program.description||'')}</p></div></div><p><strong>Academic Year:</strong> ${esc(yearLabel||'Not selected')}</p><p>${annualYear?.is_enabled?'Enabled':'Not enabled'} · ${(annualYear?.eligible_grade_levels||[]).join(', ')||'No Grades configured'}</p><div class="tp-evaluation-chip-list">${evaluationSummary}</div></div><div class="tp-wizard-actions"><a href="#tp-schedule">Manage Evaluations</a><a class="tp-primary-link" href="#tp-builder">Continue</a></div>`}</section>`:''}
      ${activeStep==='rubric'?rubricWorkspace:''}
      ${activeStep==='assess'?assessPanel:''}
      ${activeStep==='schedule'?`<section id="tp-schedule" class="tp-wizard-panel"><h2>Evaluation Plan</h2><div data-embedded-schedule><p role="status">Loading Evaluation Plan…</p></div></section>`:''}
      `;
    root.onchange=async event=>{
      const gradeInput=event.target.closest('[data-rubric-grade]');
      if(gradeInput){params.set('rubric_grade',gradeInput.value);await render(ctx,{viaHash:true});return;}
      const fileInput=event.target.closest('[data-logo-input]');
      if(fileInput&&fileInput.files&&fileInput.files[0])uploadLogo(fileInput.files[0]);
    };
    root.onsubmit=async event=>{
      event.preventDefault();const f=event.target,d=new FormData(f),action=f.dataset.form;let path=base,method='PUT',body={},rev={expected_revision:framework?.revision};
      if(action==='basics'){
        if(program.status==='draft')try{await api(base,{method:'PATCH',body:JSON.stringify({name:d.get('name'),description:d.get('description')})});}catch(error){const feedback=f.querySelector('[data-feedback]');if(feedback){feedback.textContent=error.message||'Unable to save Program details.';feedback.setAttribute('role','alert');}return;}
        path+=`/academic-years/${year}`;body={is_enabled:true,eligible_grade_levels:configuredGrades.filter(g=>d.has(`grade_${g}`))};
      }
      else if(action==='edit-program'){method='PATCH';body={name:d.get('name'),description:d.get('description')};}
      else if(action==='annual'){path+=`/academic-years/${year}`;body={is_enabled:d.has('is_enabled'),eligible_grade_levels:configuredGrades.filter(g=>d.has(`grade_${g}`))};}
      else if(action==='new-version'){path+='/frameworks';method='POST';body={title:d.get('title'),summary:d.get('summary'),...(d.has('clone')?{clone_from_id:framework.id}:{}),supersedes_framework_version_id:versions.find(v=>v.status==='active')?.id||null};}
      else if(action==='create-competency'){path+='/competencies';method='POST';body={code:d.get('code'),name:d.get('name'),description:d.get('description')};}
      else if(action.startsWith('create-grade-competency:')){
        if(!framework){return;}
        const grade=action.split(':')[1];
        try{
          const name=String(d.get('name')||'').trim();
          const created=await api(`${base}/competencies`,{method:'POST',body:JSON.stringify({name,description:d.get('description')})});
          await api(`${fp}/competencies`,{method:'POST',body:JSON.stringify({expected_revision:framework.revision,competency_id:created.id,grade_level:grade,label:d.get('name'),description:d.get('description')})});
          ctx.notify?.('Competency added.');
          await refreshSelectedProgram('framework-bank');
        }catch(error){
          const feedback=f.querySelector('[data-feedback]');
          if(feedback){feedback.textContent=error.message||'Unable to add competency.';feedback.setAttribute('role','alert');}
        }
        return;
      }
      else {
        path=fp;body={...rev};
        if(action==='version'){method='PATCH';Object.assign(body,{title:d.get('title'),summary:d.get('summary'),supersedes_framework_version_id:framework.supersedes_framework_version_id});}
        else if(action==='add-member'){path+='/competencies';method='POST';body.competency_id=Number(d.get('competency_id'));body.grade_level=d.get('grade_level')||null;}
        else if(action.startsWith('member:')){path+=`/competencies/${action.split(':')[1]}`;method='PATCH';Object.assign(body,{grade_level:d.get('grade_level')||null,label:d.get('label'),description:d.get('description')});}
        else if(action==='rubric'){path+='/rubric';Object.assign(body,{name:d.get('name'),description:d.get('description')});}
        else if(action.startsWith('competency-rubric:')){
          const memberId=Number(action.split(':')[1]);path+='/rubric';Object.assign(body,{framework_competency_id:memberId,name:d.get('name'),description:d.get('description')});
        }
        else if(action.startsWith('competency-level:')){
          const memberId=Number(action.split(':')[1]);path+='/rubric/levels';method='POST';Object.assign(body,{framework_competency_id:memberId,code:`LEVEL_${Date.now()}`,label:d.get('label'),description:d.get('description')});
        }
        else if(action.startsWith('copy-levels:')){
          const memberId=Number(action.split(':')[1]);path+='/rubric/levels/copy';method='POST';Object.assign(body,{
            source_framework_competency_id:Number(d.get('source_framework_competency_id')),
            target_framework_competency_id:memberId,
            include_descriptions:d.has('include_descriptions'),
          });
        }
        else if(action==='add-level'||action.startsWith('level:')){path+='/rubric/levels';method=action==='add-level'?'POST':'PATCH';if(method==='PATCH')path+=`/${action.split(':')[1]}`;Object.assign(body,{label:d.get('label'),description:d.get('description'),numeric_value:numeric(d.get('numeric_value'))});if(method==='POST')body.code=d.get('code');}
        else if(action.startsWith('descriptor:')){const [,m,l,g]=action.split(':');path+='/rubric/descriptors';Object.assign(body,{framework_competency_id:Number(m),rubric_level_id:Number(l),descriptor:d.get('descriptor'),grade_level:g||null});}
        else if(action==='kpi'){path+='/kpi';Object.assign(body,{is_enabled:d.has('is_enabled'),result_scale_min:numeric(d.get('result_scale_min')),result_scale_max:numeric(d.get('result_scale_max')),interpretation:d.get('interpretation'),calculation_method:'weighted_level_average',components:kpiComponents(d,members)});}
        else return;
      }
      const refreshMode=action==='new-version'?'none':(action==='basics'||action==='annual'||action==='edit-program'?'program':action==='create-competency'?'framework-bank':'framework');
      const saved=await mutate(path,method,body,f,refreshMode);
      if(saved&&action==='new-version'){
        if(typeof window!=='undefined'&&window.location.hash!=='#tp-rubric')window.location.hash='#tp-rubric';
        await fullRefresh();
        ctx.notify?.('Rubric is ready to edit.');
        return;
      }
      if(saved&&(action==='annual'||action==='basics')&&typeof window!=='undefined')window.location.hash='';
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
      if(a==='finish-rubric'){
        if(typeof window!=='undefined'){window.location.hash='';}
        await redrawFromCache();
        ctx.notify?.('Rubric saved.');
        return;
      }
      if(a==='finish-setup'){
        const status=root.querySelector('[data-status]');
        try{
          if(program.status==='draft'){
            if(!govern)throw new Error('You need Program governance permission to finish and activate this setup.');
            if(status)status.textContent='Activating Program…';
            await api(`${base}/lifecycle/active`,{method:'POST'});
          }
          if(framework?.status==='draft'){
            if(!govern)throw new Error('You need Program governance permission to activate this rubric.');
            if(status)status.textContent='Activating rubric…';
            await api(`${fp}/activate`,{method:'POST',body:JSON.stringify({
              expected_revision:framework.revision,
              expected_fingerprint:framework.semantic_fingerprint,
            })});
          }
          ctx.notify?.('Program setup finished and activated.');
          if(typeof window!=='undefined')window.location.hash='';
          if(ctx.navigate)ctx.navigate('programs',{program_id:pid});
          else await fullRefresh();
        }catch(error){
          if(status){status.textContent=error.message||'Unable to finish setup.';status.setAttribute('role','alert');}
        }
        return;
      }
      if(dirty&&!window.confirm('This action reloads the workspace. Discard unsaved edits?'))return;
      let path=fp,method='POST',body={expected_revision:framework?.revision};
      if(a==='program-state'){if(!window.confirm(program.status==='draft'?'Activate this Program?':'Retire this Program?'))return;path=`${base}/lifecycle/${program.status==='draft'?'active':'retired'}`;body=undefined;}
      else if(a==='remove-logo'){if(!window.confirm('Remove the Program logo? This cannot be undone.'))return;path=`${base}/logo`;method='DELETE';body=undefined;}
      else if(a==='activate-version'){if(!window.confirm('Activate this version for future evaluations? The existing active version will be superseded.'))return;path+='/activate';body.expected_fingerprint=framework.semantic_fingerprint;}
      else if(a==='retire-version'){if(!window.confirm('Retire this version? Existing assessment history is preserved.'))return;path+='/retire';body=undefined;}
      else if(a==='remove-member'||a==='remove-level'||a==='remove-descriptor'){const message=a==='remove-member'?'Delete this Competency from the editable rubric?':a==='remove-level'?'Delete this Rubric Level from the editable rubric?':'Remove this item from the draft version?';if(!window.confirm(message))return;path+=a==='remove-member'?`/competencies/${b.dataset.key}`:a==='remove-level'?`/rubric/levels/${b.dataset.key}`:b.dataset.scope==='grade'?`/rubric/grade-descriptors/${b.dataset.key}`:`/rubric/descriptors/${b.dataset.key}`;path+=`?expected_revision=${framework.revision}`;method='DELETE';body=undefined;}
      else if(a==='remove-kpi'){if(!window.confirm('Delete this KPI configuration? Historical completed Assessment evidence remains unchanged.'))return;path+='/kpi';path+=`?expected_revision=${framework.revision}`;method='DELETE';body=undefined;}
      else if(a==='move-member'||a==='move-level'){const i=Number(b.dataset.index),items=(a==='move-member'?members.map(m=>m.competency_id):levels.map(l=>l.id));if(i<1)return;[items[i-1],items[i]]=[items[i],items[i-1]];method='PUT';path+=a==='move-member'?'/competencies/order':'/rubric/levels/order';body[a==='move-member'?'competency_ids':'level_ids']=items;}
      else return;
      const refreshMode=a==='program-state'?'full':a==='remove-logo'?'program':'framework';
      await mutate(path,method,body,undefined,refreshMode);
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
