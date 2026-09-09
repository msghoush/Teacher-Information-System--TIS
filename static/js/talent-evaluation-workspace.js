/* M8 planning and M4 evaluation entry use the existing authorized APIs. */
(() => {
  'use strict';
  const esc = v => String(v ?? '').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  const input = (name,label,type='text') => `<label>${label}<input name="${name}" type="${type}" required></label>`;
  const options = rows => rows.map(([id,label])=>`<option value="${esc(id)}">${esc(label)}</option>`).join('');
  const form = (action,label,body,extra='') => `<form class="tp-card tp-editor" data-form="${action}" ${extra}><h3>${label}</h3>${body}<div class="tp-actions"><button type="submit">${label}</button><button type="reset">Reset changes</button></div><p data-feedback role="status" aria-live="polite"></p></form>`;
  let unloadGuard;
  async function render(ctx) {
    const {root,api,can}=ctx, params=ctx.params || new URLSearchParams(), year=ctx.year?.value ?? ctx.year;
    root.onclick=null; root.onsubmit=null; root.oninput=null;root.onreset=null;
    root.classList?.add('tp-program-workspace');
    if(typeof window!=='undefined'&&unloadGuard)window.removeEventListener('beforeunload',unloadGuard);
    if(!can('talent_evaluation_plans.view')) {root.innerHTML='<p>You do not have permission to view Evaluation Plans.</p>';return;}
    if(!year) {root.innerHTML='<p>Select an academic year to plan evaluations.</p>';return;}
    root.innerHTML='<p role="status">Loading Evaluation Plans…</p>';
    const pid=params.get('program_id'), query=new URLSearchParams({academic_year_id:year,...(pid?{program_id:pid}:{})});
    const [plans,programs,cycles]=await Promise.all([
      api(`/api/talent/evaluation-plans?${query}`),
      can('talent_programs.view')?api('/api/talent/programs'):[],
      can('talent_assessment_cycles.view')?api(`/api/talent/assessment-cycles?${query}`):[],
    ]);
    const program=programs.find(p=>String(p.id)===pid), base=program?`/api/talent/programs/${program.id}`:null;
    const [annual,frameworks]=base?await Promise.all([api(`${base}/academic-years`),api(`${base}/frameworks`)]):[[],[]];
    const configuration=annual.find(a=>String(a.academic_year_id)===String(year)&&a.is_enabled);
    const linkedCycleIds=new Set(plans.flatMap(p=>p.periods || []).flatMap(period=>period.cycle?[period.cycle.id]:[]));
    const active=frameworks.filter(f=>f.status==='active'), available=cycles.filter(c=>c.status==='draft'&&!linkedCycleIds.has(c.id));
    const title=p=>programs.find(x=>x.id===p.program_id)?.name || 'Program name unavailable';
    const link=c=>`/talent/assessments?${new URLSearchParams({academic_year_id:year,program_id:c.program_id || pid || '',cycle_id:c.id})}`;
    const openButton=c=>c.status==='draft'&&can('talent_assessment_cycles.govern')?`<button type="button" data-open="${c.id}">Open evaluation</button>`:'';
    const cycleCard=c=>`<h4>${esc(c.title)}</h4><p><span class="tp-badge">${esc(c.status)}</span></p>${openButton(c)}${can('talent_assessments.view')&&can('talent_assessment_cycles.view_population')&&c.status!=='draft'?`<a href="${esc(link(c))}">Open Students & Assessments</a>`:''}`;
    root.innerHTML=`<div data-feedback role="status" aria-live="polite"></div><header class="tp-section-lede"><div><h2>${program?esc(program.name)+' · ':''}Evaluation Plan</h2><p>Plan your evaluation periods, prepare an evaluation, then open it to begin assessing Students.</p><button type="button" data-reload>Reload saved view</button></div></header>
      ${!pid&&can('talent_programs.view')?`<nav class="tp-tabs" aria-label="Choose a Program">${programs.map(p=>`<a href="/talent/evaluation-plans?${esc(new URLSearchParams({academic_year_id:year,program_id:p.id}))}">${esc(p.name)}</a>`).join('')}</nav>`:''}
      ${program?`<a href="/talent/programs?${esc(new URLSearchParams({academic_year_id:year,program_id:program.id}))}">Back to Program setup</a>`:''}
      ${plans.length?'':'<p class="tp-empty">No Evaluation Plan for this selection. Enable the Program for this academic year in Program setup, then create its Plan.</p>'}
      ${configuration&&!plans.some(p=>p.program_id===program.id)&&can('talent_evaluation_plans.manage')?form('plan','Create Evaluation Plan','<p>Organize the required and optional evaluations for this academic year.</p>'):''}
      ${plans.map(p=>`<section class="tp-card"><h3>${esc(title(p))}</h3><span class="tp-badge">${esc(p.status)}</span><p>${p.required_period_count} required periods · ${p.period_count} periods in total</p>
        ${(p.warnings||[]).length?'<p>Check all periods before progressing. The server validates readiness when you activate or open an evaluation.</p>':''}
        ${p.actions.includes('activate')?`<button type="button" data-activate="${p.id}">Activate Plan</button>`:''}
        <div class="tp-grid">${p.periods.map(period=>`<article class="tp-card"><h4>${esc(period.label)}</h4><p>${period.is_required?'Required':'Optional'} · ${esc(period.status)}</p><p>${esc(period.planned_start_date||'Start date not set')} — ${esc(period.planned_end_date||'End date not set')}</p>
          ${period.cycle?cycleCard({...period.cycle,program_id:p.program_id}):''}
          ${period.actions.includes('link_cycle')?form('link','Link prepared evaluation',`<label>Evaluation<select name="cycle" required>${options(available.filter(c=>c.program_id===p.program_id).map(c=>[c.id,c.title]))}</select></label>`,`data-plan="${p.id}" data-period="${period.id}"`):''}
        </article>`).join('')}</div>
        ${p.actions.includes('add_period')?form('period','Add evaluation period',input('label','Period name')+'<label><input type="checkbox" name="required" checked> Required evaluation</label>',`data-plan="${p.id}"`):''}
      </section>`).join('')}
      ${program&&configuration&&active.length&&can('talent_assessment_cycles.manage')&&can('talent_assessment_cycles.view')?form('cycle','Prepare evaluation',input('title','Evaluation name')+`<label>Competencies & Rubric version<select name="framework" required>${options(active.map(f=>[f.id,`${f.title} · Version ${f.version_number}`]))}</select></label>`+input('effective','Include Students placed as of','datetime-local')+'<p>The Student list is fixed when the evaluation opens. Later placement changes do not rewrite its historical context.</p>'):''}
      ${available.length?`<section><h3>Prepared evaluations</h3><p>Link an evaluation to an active Plan period above before opening it. Opening fixes its Student list.</p><div class="tp-grid">${available.map(c=>`<article class="tp-card"><h4>${esc(c.title)}</h4><span class="tp-badge">Ready to link</span></article>`).join('')}</div></section>`:''}`;
    let busy=false,stale=false;
    const dirtyForms=new Set();
    root.oninput=event=>{const edited=event.target.closest('form');if(edited){dirtyForms.add(edited);edited.dataset.dirty='true';}};
    root.onreset=event=>{dirtyForms.delete(event.target);delete event.target.dataset.dirty;};
    if(typeof window!=='undefined'){
      unloadGuard=event=>{if(dirtyForms.size||busy){event.preventDefault();event.returnValue='';}};
      window.addEventListener('beforeunload',unloadGuard);
    }
    async function write(path,body,target=root) {
      const feedback=target.querySelector('[data-feedback]')||root.querySelector('[data-feedback]');
      if(stale){feedback.textContent='This saved Plan or evaluation changed elsewhere. Reload the saved view before trying again.';feedback.setAttribute('role','alert');return;}
      if(target!==root&&[...dirtyForms].some(form=>form!==target)){feedback.textContent='Save or reset changes in the other form first.';feedback.setAttribute('role','alert');return;}
      if(busy)return;busy=true;
      const buttons=[...root.querySelectorAll('button')],disabled=buttons.map(b=>b.disabled);
      buttons.forEach(b=>b.disabled=true);
      feedback.textContent='Saving…';
      try {
        await api(path,{method:'POST',body:JSON.stringify(body)});
        dirtyForms.clear();
        try {await render(ctx);const status=root.querySelector('[data-feedback]');if(status)status.textContent='Saved successfully.';}
        catch {root.innerHTML='<p role="alert">Saved, but the updated Plan could not be loaded. Reload this page to see the saved result.</p>';}
      } catch(error) {stale=stale||error.status===409;feedback.textContent=`${error.message||'Unable to save.'} Your entries are preserved.${stale?' Reload the saved view before trying again.':''}`;feedback.setAttribute('role','alert');}
      finally {busy=false;buttons.forEach((b,i)=>b.disabled=disabled[i]);}
    }
    root.onsubmit=event=>{
      const f=event.target;if(!f.matches('form[data-form]'))return;event.preventDefault();
      const d=new FormData(f),p=plans.find(x=>String(x.id)===f.dataset.plan);
      if(f.dataset.form==='plan')return write('/api/talent/evaluation-plans',{program_academic_year_configuration_id:configuration.id},f);
      if(f.dataset.form==='period')return write(`/api/talent/evaluation-plans/${p.id}/periods`,{expected_plan_revision:p.revision,label:d.get('label'),is_required:d.has('required')},f);
      if(f.dataset.form==='cycle')return write('/api/talent/assessment-cycles',{program_id:program.id,academic_year_id:Number(year),framework_version_id:Number(d.get('framework')),title:d.get('title'),population_effective_at:d.get('effective')},f);
      if(f.dataset.form==='link') {
        const c=available.find(x=>String(x.id)===d.get('cycle'));if(!c)return;
        return write(`/api/talent/assessment-cycles/${c.id}/link-period`,{planned_period_id:Number(f.dataset.period),expected_plan_revision:p.revision,expected_cycle_revision:c.revision},f);
      }
    };
    root.onclick=event=>{
      const b=event.target.closest('button');if(!b)return;
      if(b.hasAttribute('data-reload')){if(!dirtyForms.size||window.confirm('Discard unsaved entries and reload the saved view?'))render(ctx);return;}
      if(dirtyForms.size){const feedback=root.querySelector('[data-feedback]');feedback.textContent='Save or reset your unsaved entries before this action.';feedback.setAttribute('role','alert');return;}
      if(b.dataset.activate){const p=plans.find(x=>String(x.id)===b.dataset.activate);return write(`/api/talent/evaluation-plans/${p.id}/activate`,{expected_plan_revision:p.revision});}
      if(b.dataset.open){const c=cycles.find(x=>String(x.id)===b.dataset.open);if(c&&window.confirm('Open this evaluation and fix its Student list? Later placement changes will not alter this historical list.'))return write(`/api/talent/assessment-cycles/${c.id}/open`,{expected_revision:c.revision});}
    };
  }
  if(typeof module!=='undefined'&&module.exports)module.exports={render,esc};
  if(typeof window!=='undefined')window.TalentEvaluationWorkspace={render};
})();
