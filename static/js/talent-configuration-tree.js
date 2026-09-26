/* System Configuration > Talent & Potential Configuration — Rubric & Competencies TREE.
 *
 * Organization-level Talent configuration is defined here and nowhere else. This
 * module renders the Grade → Competency → competency-owned Rubric → ordered Rubric
 * Levels hierarchy as a semantic, collapsible tree, and drives the right-hand
 * detail editor from an editable Rubric Level selection.
 *
 * Every read and mutation goes through the existing canonical /api/talent/* routes,
 * so backend permission, organization/global scope, Draft-only mutation and
 * revision/concurrency checks all stay authoritative. The UI only reflects
 * server-derived capability; it never re-implements authorization and never
 * duplicates or invents configuration state.
 */
((root, factory) => {
  const api = factory();
  if (typeof module !== 'undefined' && module.exports) module.exports = api;
  if (root) root.TalentConfigurationTree = api;
})(typeof window !== 'undefined' ? window : globalThis, () => {
  'use strict';
  const esc = v => String(v ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));

  const gradeLabel = g => (String(g) === 'KG' ? 'KG' : `Grade ${g}`);

  const chevron = (open) => `<svg class="tpc-tree-chevron${open ? ' is-open' : ''}" viewBox="0 0 24 24" aria-hidden="true" focusable="false"><path d="m9 6 6 6-6 6"></path></svg>`;

  const icon = (name) => {
    const paths = {
      edit: '<path d="M4 20h4L19 9a2.8 2.8 0 0 0-4-4L4 16v4Z"></path><path d="m13.5 6.5 4 4"></path>',
      trash: '<path d="M4 7h16"></path><path d="M9 7V4h6v3"></path><path d="m7 7 1 13h8l1-13"></path>',
      add: '<path d="M12 5v14M5 12h14"></path>',
    };
    return `<svg class="tpc-icon" data-tpc-icon="${name}" viewBox="0 0 24 24" aria-hidden="true" focusable="false">${paths[name] || ''}</svg>`;
  };

  // The "generic" achievement descriptor is the backward-compatible fallback shown
  // for a Competency x Level cell; a grade-specific override wins when present.
  function descriptorFor(descriptors, frameworkCompetencyId, levelId, grade) {
    const match = (d) => Number(d.framework_competency_id) === Number(frameworkCompetencyId)
      && Number(d.rubric_level_id) === Number(levelId);
    return (descriptors || []).find(d => match(d) && String(d.grade_level || '') === String(grade || ''))
      || (descriptors || []).find(d => match(d) && !d.grade_level);
  }

  function rubricFor(memberId, rubrics) {
    return (rubrics || []).find(r => Number(r.framework_competency_id) === Number(memberId)) || null;
  }

  // Group framework competency members by Grade scope. Unscoped members
  // (grade_level == null) are intentional shared criteria, grouped once.
  function groupByGrade(members) {
    const out = [];
    const seen = new Map();
    for (const m of (members || [])) {
      const key = String(m.grade_level ?? '');
      if (!seen.has(key)) { seen.set(key, {grade: m.grade_level ?? null, members: []}); out.push(seen.get(key)); }
      seen.get(key).members.push(m);
    }
    const gradeOrder = g => (String(g) === 'KG' ? -1 : (g == null || g === '' ? 0 : Number(g)));
    return out.sort((a, b) => gradeOrder(a.grade) - gradeOrder(b.grade));
  }

  // ---- HTML builders (exported for focused tests) -------------------------

  function levelNodeHtml(level, {selectedId, editable, canDelete} = {}) {
    const selected = String(level.id) === String(selectedId);
    return `<li class="tpc-tree-level${selected ? ' is-selected' : ''}" role="treeitem" aria-selected="${selected}">`
      + `<div class="tpc-tree-row tpc-tree-row-level">`
      + `<button type="button" class="tpc-tree-select" data-tpc-level-select="${esc(level.id)}" aria-label="Edit Level ${esc(level.label)}">`
      + `<span class="tpc-level-marker" aria-hidden="true">${esc(level.order ?? '')}</span>`
      + `<span class="tpc-level-name">${esc(level.label)}</span>`
      + (level.description ? `<span class="tpc-level-desc">${esc(level.description)}</span>` : '')
      + `</button>`
      + `<span class="tpc-tree-actions">`
      + (editable ? `<button type="button" class="tpc-icon-btn" data-tpc-level-edit="${esc(level.id)}" aria-label="Edit Level ${esc(level.label)}" title="Edit Level">${icon('edit')}</button>` : '')
      + (canDelete ? `<button type="button" class="tpc-icon-btn tpc-danger" data-tpc-level-delete="${esc(level.id)}" aria-label="Delete Level ${esc(level.label)}" title="Delete Level">${icon('trash')}</button>` : '')
      + `</span></div></li>`;
  }

  function rubricNodeHtml(rubric, levels, {competencyId, selectedId, editable, canDelete} = {}) {
    return `<li class="tpc-tree-rubric" role="treeitem">`
      + `<div class="tpc-tree-row tpc-tree-row-rubric">`
      + `<button type="button" class="tpc-tree-toggle" data-tpc-toggle aria-expanded="true" aria-label="Collapse Rubric levels">${chevron(true)}</button>`
      + `<span class="tpc-tree-rubric-label">${esc(rubric.name || 'Rubric')}</span>`
      + `<span class="tpc-tree-count">${levels.length} Level${levels.length === 1 ? '' : 's'}</span>`
      + `</div>`
      + `<ul class="tpc-tree-children" role="group">${levels.map(l => levelNodeHtml(l, {selectedId, editable, canDelete})).join('')}`
      + (editable ? `<li class="tpc-tree-add" role="none"><button type="button" class="tpc-add-btn" data-tpc-level-add="${esc(competencyId)}" aria-label="Add Level">${icon('add')}Add Level</button><div class="tpc-inline-form" data-tpc-level-form="${esc(competencyId)}" hidden></div></li>` : '')
      + `</ul></li>`;
  }

  function competencyNodeHtml(member, {selectedId, editable, canDeleteCompetency, canDeleteLevel} = {}) {
    const rubric = member.rubric || null;
    const levels = rubric?.levels || [];
    return `<li class="tpc-tree-competency" role="treeitem">`
      + `<div class="tpc-tree-row tpc-tree-row-competency">`
      + `<button type="button" class="tpc-tree-toggle" data-tpc-toggle aria-expanded="false" aria-label="Expand ${esc(member.label)}">${chevron(false)}</button>`
      + `<span class="tpc-tree-competency-label">${esc(member.label || 'Unnamed competency')}</span>`
      + `<span class="tpc-tree-count">${rubric ? `${levels.length} Level${levels.length === 1 ? '' : 's'}` : 'No rubric'}</span>`
      + `<span class="tpc-tree-actions">`
      + (editable ? `<button type="button" class="tpc-icon-btn" data-tpc-competency-edit="${esc(member.id)}" aria-label="Edit Competency ${esc(member.label)}" title="Edit Competency">${icon('edit')}</button>` : '')
      + (canDeleteCompetency ? `<button type="button" class="tpc-icon-btn tpc-danger" data-tpc-competency-delete="${esc(member.id)}" aria-label="Delete Competency ${esc(member.label)}" title="Delete Competency">${icon('trash')}</button>` : '')
      + `</span></div>`
      + `<ul class="tpc-tree-children" role="group">${rubric ? rubricNodeHtml(rubric, levels, {competencyId: member.id, selectedId, editable, canDelete: canDeleteLevel}) : `<li class="tpc-tree-empty" role="none"><span>No rubric configured.</span>${editable ? `<button type="button" class="tpc-add-btn" data-tpc-rubric-add="${esc(member.id)}" aria-label="Add KPI">${icon('add')}Add KPI</button>` : ''}</li>`}</ul></li>`;
  }

  function gradeNodeHtml(group, {selectedId, editable, canDeleteCompetency, canDeleteLevel} = {}) {
    const label = group.grade == null || group.grade === '' ? 'All Grades' : gradeLabel(group.grade);
    return `<li class="tpc-tree-grade" role="treeitem">`
      + `<div class="tpc-tree-row tpc-tree-row-grade">`
      + `<button type="button" class="tpc-tree-toggle" data-tpc-toggle aria-expanded="true" aria-label="Collapse ${esc(label)}">${chevron(true)}</button>`
      + `<span class="tpc-tree-grade-label">${esc(label)}</span>`
      + `<span class="tpc-tree-count">${group.members.length} Competenc${group.members.length === 1 ? 'y' : 'ies'}</span>`
      + (editable ? `<span class="tpc-tree-actions"><button type="button" class="tpc-add-btn" data-tpc-competency-add="${esc(group.grade ?? '')}" aria-label="Add Competency to ${esc(label)}">${icon('add')}Add Competency</button><div class="tpc-inline-form" data-tpc-competency-form="${esc(group.grade ?? '')}" hidden></div></span>` : '')
      + `</div>`
      + `<ul class="tpc-tree-children" role="group">${group.members.map(m => competencyNodeHtml(m, {selectedId, editable, canDeleteCompetency, canDeleteLevel})).join('')}</ul></li>`;
  }

  function treeHtml(data, {selectedId, editable, canDeleteCompetency, canDeleteLevel} = {}) {
    const rubrics = data.rubrics || [];
    const grades = (data.grades || []).map(group => ({
      ...group,
      members: group.members.map(m => ({...m, rubric: rubricFor(m.id, rubrics)})),
    }));
    return `<ul class="tpc-tree" role="tree" aria-label="Rubric and competencies">`
      + grades.map(g => gradeNodeHtml(g, {selectedId, editable, canDeleteCompetency, canDeleteLevel})).join('')
      + `</ul>`;
  }

  // ---- Right-side Level detail editor --------------------------------------

  function levelEditorHtml(lc) {
    const l = lc || {};
    return `<form class="tpc-editor" data-tpc-level-editor data-level-id="${esc(l.levelId)}" novalidate>`
      + `<div class="tpc-editor-head"><span class="tpc-level-marker" aria-hidden="true">${esc(l.order ?? '')}</span><h3>Edit Level</h3></div>`
      + `<label class="tpc-editor-field"><span>Level Name</span><input name="label" type="text" value="${esc(l.label)}" required></label>`
      + `<label class="tpc-editor-field"><span>Level Order</span><input name="order" type="text" value="${esc(l.order ?? '')}" disabled></label>`
      + `<label class="tpc-editor-field"><span>Description</span><textarea name="description" rows="3">${esc(l.description)}</textarea></label>`
      + `<label class="tpc-editor-field"><span>Achievement Description</span><textarea name="descriptor" rows="4">${esc(l.descriptor)}</textarea></label>`
      + `<p class="tpc-editor-meta">${l.gradeLabel ? `<span>${esc(l.gradeLabel)}</span> · ` : ''}<span>${esc(l.competencyLabel || '')}</span></p>`
      + `<div class="tpc-editor-actions"><button type="button" class="tpc-secondary" data-tpc-level-cancel>Cancel</button><button type="submit" class="tpc-primary">Save Changes</button></div>`
      + `<p data-feedback role="status" aria-live="polite"></p></form>`;
  }

  function inlineLevelFormHtml() {
    return `<form class="tpc-inline" data-tpc-level-form-body novalidate>`
      + `<label><span>Level Name</span><input name="label" type="text" required></label>`
      + `<label><span>Description</span><textarea name="description" rows="2"></textarea></label>`
      + `<div class="tpc-editor-actions"><button type="button" data-tpc-cancel>Cancel</button><button type="submit" class="tpc-primary">Add Level</button></div>`
      + `<p data-feedback role="status" aria-live="polite"></p></form>`;
  }

  function inlineCompetencyFormHtml() {
    return `<form class="tpc-inline" data-tpc-competency-form-body novalidate>`
      + `<label><span>Competency Name</span><input name="name" type="text" required></label>`
      + `<label><span>Description</span><textarea name="description" rows="2"></textarea></label>`
      + `<div class="tpc-editor-actions"><button type="button" data-tpc-cancel>Cancel</button><button type="submit" class="tpc-primary">Add Competency</button></div>`
      + `<p data-feedback role="status" aria-live="polite"></p></form>`;
  }

  function emptyStateHtml({manage, hasFramework} = {}) {
    if (!hasFramework) {
      return manage
        ? '<p class="tp-empty">No rubric structure yet. Open Criteria / KPI to start the assessment setup for this Program.</p>'
        : '<p class="tp-empty">No rubric structure yet.</p>';
    }
    return '<p class="tp-empty">No competencies yet. Add a Competency to begin building its rubric levels.</p>';
  }

  function drawerEmpty() {
    return '<h3>Details</h3><p class="tp-empty">Select a Level to edit its name, order and achievement description here.</p>';
  }

  return {
    esc, gradeLabel, groupByGrade, rubricFor, descriptorFor,
    levelNodeHtml, rubricNodeHtml, competencyNodeHtml, gradeNodeHtml, treeHtml,
    levelEditorHtml, inlineLevelFormHtml, inlineCompetencyFormHtml, emptyStateHtml, drawerEmpty,
    render: (ctx) => renderTree(ctx),
  };

  // ---- Orchestrator --------------------------------------------------------

  async function renderTree(ctx) {
    const {root, drawer, api, can, programId, program, notify} = ctx;
    if (!root) return;
    const manage = can('talent_programs.manage');
    const canDeleteCompetency = can('talent_programs.delete_competency');
    const canDeleteLevel = can('talent_programs.delete_rubric_level');
    ctx._token = (ctx._token || 0) + 1;
    const token = ctx._token;
    const base = `/api/talent/programs/${programId}`;
    const say = msg => notify ? notify(msg) : undefined;

    root.setAttribute('aria-busy', 'true');
    try {
      const versions = await api(`${base}/frameworks`).catch(() => []);
      const drafts = (versions || []).filter(f => f.status === 'draft').sort((a, b) => (Number(b.version_number) || 0) - (Number(a.version_number) || 0) || (Number(b.id) || 0) - (Number(a.id) || 0));
      const chosen = drafts[0] || (versions || []).find(f => f.status === 'active') || (versions || [])[0];
      if (token !== ctx._token) return;

      if (!chosen) {
        root.innerHTML = emptyStateHtml({manage, hasFramework: false});
        if (drawer) drawer.innerHTML = drawerEmpty();
        return;
      }

      const [framework, config] = await Promise.all([
        api(`${base}/frameworks/${chosen.id}`),
        api(`${base}/frameworks/${chosen.id}/configuration`),
      ]);
      if (token !== ctx._token) return;
      if (!framework || framework.revision !== config.revision) {
        root.innerHTML = '<p class="tp-error" role="alert">This rubric changed while it was loading. Reload the page to open the latest saved version.</p>';
        if (drawer) drawer.innerHTML = drawerEmpty();
        return;
      }

      const members = framework.competencies || [];
      const rubrics = config.rubrics || [];
      const descriptors = config.descriptors || [];
      const editable = manage && framework.status === 'draft' && !framework.in_use_by_assessments;
      const delCompetency = canDeleteCompetency && editable;
      const delLevel = canDeleteLevel && editable;

      const model = {
        programId, frameworkId: framework.id, frameworkRevision: framework.revision,
        frameworkStatus: framework.status, editable,
        grades: groupByGrade(members).map(group => ({
          ...group,
          members: group.members.map(m => ({...m, rubric: rubricFor(m.id, rubrics)})),
        })),
        rubrics, descriptors, programName: program?.name || '',
      };

      root.innerHTML = members.length
        ? treeHtml(model, {selectedId: '', editable, canDeleteCompetency: delCompetency, canDeleteLevel: delLevel})
        : emptyStateHtml({manage, hasFramework: true});
      if (drawer) drawer.innerHTML = drawerEmpty();

      bindTreeEvents(root, model, {api, can, say});
    } catch (error) {
      if (token !== ctx._token) return;
      root.innerHTML = `<p class="tp-error" role="alert">${esc((error && error.userSafe && error.message) || 'Unable to load the rubric.')}</p>`;
    } finally {
      root.removeAttribute('aria-busy');
    }
  }

  function bindTreeEvents(root, model, {api, can, say}) {
    const base = `/api/talent/programs/${model.programId}`;
    const fp = `${base}/frameworks/${model.frameworkId}`;

    const levelCtxFor = (levelId) => {
      for (const group of model.grades) {
        for (const m of group.members) {
          for (const l of (m.rubric?.levels || [])) {
            if (String(l.id) === String(levelId)) {
              const desc = descriptorFor(model.descriptors, m.id, l.id, group.grade);
              return {
                levelId: l.id, order: l.order, label: l.label, description: l.description,
                descriptor: desc?.descriptor || '',
                grade: group.grade, gradeLabel: group.grade == null || group.grade === '' ? 'All Grades' : gradeLabel(group.grade),
                competencyLabel: m.label, competencyId: m.id, rubricId: m.rubric?.id,
              };
            }
          }
        }
      }
      return null;
    };

    const renderDrawer = (levelId) => {
      const doc = root.ownerDocument || (typeof document !== 'undefined' ? document : null);
      const drawer = doc?.getElementById('tpc-drawer');
      if (!drawer) return;
      const lc = levelCtxFor(levelId);
      drawer.innerHTML = lc ? `<h3>Details</h3>${levelEditorHtml(lc)}` : drawerEmpty();
      if (lc && !model.editable) {
        // Locked (active/retired/in-use) rubric: show the level read-only; the backend would reject a write anyway.
        drawer.querySelectorAll('input, textarea').forEach(field => { field.disabled = true; });
        drawer.querySelectorAll('.tpc-editor-actions').forEach(actions => { actions.hidden = true; });
        drawer.insertAdjacentHTML('beforeend', '<p class="tpc-editor-meta">This rubric is locked. Create a new draft version from Criteria / KPI to change it.</p>');
        return;
      }
      if (lc) bindLevelEditor(drawer.querySelector('[data-tpc-level-editor]'), lc, model, {api, say});
    };

    const refresh = async () => {
      if (typeof window !== 'undefined' && window.TalentConfiguration && typeof window.TalentConfiguration.rerenderCenter === 'function') {
        await window.TalentConfiguration.rerenderCenter();
      }
    };

    if (root._tpcTreeHandlers) {
      root.removeEventListener('click', root._tpcTreeHandlers.click);
      root.removeEventListener('submit', root._tpcTreeHandlers.submit);
    }

    const clickHandler = async (event) => {
      const target = event.target;
      const closest = sel => target?.closest?.(sel) || null;

      const toggle = closest('[data-tpc-toggle]');
      if (toggle) {
        const li = toggle.closest('li');
        const children = li?.querySelector(':scope > .tpc-tree-children, :scope > ul');
        if (children) {
          const expanded = children.hidden;
          children.hidden = !expanded;
          toggle.setAttribute('aria-expanded', expanded ? 'true' : 'false');
          const chev = toggle.querySelector('.tpc-tree-chevron');
          if (chev) chev.classList.toggle('is-open', expanded);
        }
        return;
      }

      const select = closest('[data-tpc-level-select]') || closest('[data-tpc-level-edit]');
      if (select) { renderDrawer(select.dataset.tpcLevelSelect || select.dataset.tpcLevelEdit); return; }

      const cancel = closest('[data-tpc-cancel]');
      if (cancel) {
        const form = closest('.tpc-inline');
        if (form) form.hidden = true;
        return;
      }

      const addLevel = closest('[data-tpc-level-add]');
      if (addLevel) {
        const holder = root.querySelector(`[data-tpc-level-form="${addLevel.dataset.tpcLevelAdd}"]`);
        if (holder) { holder.innerHTML = inlineLevelFormHtml(); holder.hidden = false; }
        return;
      }

      const addCompetency = closest('[data-tpc-competency-add]');
      if (addCompetency) {
        const holder = root.querySelector(`[data-tpc-competency-form="${addCompetency.dataset.tpcCompetencyAdd}"]`);
        if (holder) { holder.innerHTML = inlineCompetencyFormHtml(); holder.hidden = false; }
        return;
      }

      const delLevel = closest('[data-tpc-level-delete]');
      if (delLevel) {
        const lc = levelCtxFor(delLevel.dataset.tpcLevelDelete);
        if (!lc) return;
        if (typeof window !== 'undefined' && !window.confirm(`Delete Level ${lc.label}?`)) return;
        try {
          await api(`${fp}/rubric/levels/${lc.levelId}?expected_revision=${model.frameworkRevision}`, {method: 'DELETE'});
          say('Level deleted.');
          await refresh();
        } catch (error) { say((error && error.userSafe && error.message) || 'Unable to delete Level.'); }
        return;
      }

      const delCompetency = closest('[data-tpc-competency-delete]');
      if (delCompetency) {
        const mid = delCompetency.dataset.tpcCompetencyDelete;
        if (typeof window !== 'undefined' && !window.confirm('Delete this Competency? Historical completed assessments remain preserved.')) return;
        try {
          let targetFramework = model.frameworkId;
          if (!model.editable) {
            const created = await api(`${base}/frameworks`, {method: 'POST', body: JSON.stringify({
              title: `${model.programName || 'Program'} updated assessment setup`,
              summary: 'Competency removed from future assessment setup.',
              clone_from_id: model.frameworkId,
              supersedes_framework_version_id: model.frameworkId,
            })});
            targetFramework = created.id;
          }
          await api(`${base}/frameworks/${targetFramework}/competencies/${mid}?expected_revision=${model.frameworkRevision}`, {method: 'DELETE'});
          say('Competency deleted. Historical completed assessments remain preserved.');
          await refresh();
        } catch (error) { say((error && error.userSafe && error.message) || 'Unable to delete Competency.'); }
        return;
      }

      const addRubric = closest('[data-tpc-rubric-add]');
      if (addRubric) {
        const mid = addRubric.dataset.tpcRubricAdd;
        try {
          await api(`${fp}/rubric`, {method: 'PUT', body: JSON.stringify({expected_revision: model.frameworkRevision, framework_competency_id: Number(mid)})});
          say('KPI added.');
          await refresh();
        } catch (error) { say((error && error.userSafe && error.message) || 'Unable to add KPI.'); }
        return;
      }
    };

    const submitHandler = async (event) => {
      const form = event.target;
      if (form.matches?.('[data-tpc-level-form-body]')) {
        event.preventDefault();
        const holder = form.closest('[data-tpc-level-form]');
        const competencyId = holder?.dataset.tpcLevelForm;
        const feedback = form.querySelector('[data-feedback]');
        try {
          const fd = new FormData(form);
          const label = String(fd.get('label') || '').trim();
          if (!label) { if (feedback) feedback.textContent = 'Level Name is required.'; return; }
          // The backend requires a Level code (unlike Competency, it never derives one from
          // the label); generate one the same way the existing Program editor does.
          await api(`${fp}/rubric/levels`, {method: 'POST', body: JSON.stringify({
            expected_revision: model.frameworkRevision, framework_competency_id: Number(competencyId),
            code: `LEVEL_${Date.now()}`, label, description: String(fd.get('description') || '').trim(),
          })});
          say('Level added.');
          await refresh();
        } catch (error) { if (feedback) { feedback.textContent = (error && error.userSafe && error.message) || 'Unable to add Level.'; feedback.setAttribute('role', 'alert'); } }
        return;
      }
      if (form.matches?.('[data-tpc-competency-form-body]')) {
        event.preventDefault();
        const holder = form.closest('[data-tpc-competency-form]');
        const grade = holder?.dataset.tpcCompetencyForm;
        const feedback = form.querySelector('[data-feedback]');
        try {
          const fd = new FormData(form);
          const name = String(fd.get('name') || '').trim();
          if (!name) { if (feedback) feedback.textContent = 'Competency Name is required.'; return; }
          const description = String(fd.get('description') || '').trim();
          const created = await api(`${base}/competencies`, {method: 'POST', body: JSON.stringify({name, description})});
          await api(`${fp}/competencies`, {method: 'POST', body: JSON.stringify({
            expected_revision: model.frameworkRevision, competency_id: created.id, grade_level: grade === '' ? null : grade, label: name, description,
          })});
          say('Competency added.');
          await refresh();
        } catch (error) { if (feedback) { feedback.textContent = (error && error.userSafe && error.message) || 'Unable to add Competency.'; feedback.setAttribute('role', 'alert'); } }
        return;
      }
    };

    root.addEventListener('click', clickHandler);
    root.addEventListener('submit', submitHandler);
    root._tpcTreeHandlers = {click: clickHandler, submit: submitHandler};
  }

  function bindLevelEditor(form, lc, model, {api, say}) {
    if (!form) return;
    form.addEventListener('click', (event) => {
      if (event.target.closest?.('[data-tpc-level-cancel]')) {
        const doc = form.ownerDocument;
        const drawer = doc?.getElementById('tpc-drawer');
        if (drawer) drawer.innerHTML = drawerEmpty();
      }
    });
    form.addEventListener('submit', async (event) => {
      event.preventDefault();
      const feedback = form.querySelector('[data-feedback]');
      const fd = new FormData(form);
      const label = String(fd.get('label') || '').trim();
      const description = String(fd.get('description') || '').trim();
      const descriptor = String(fd.get('descriptor') || '').trim();
      const base = `/api/talent/programs/${model.programId}`;
      const fp = `${base}/frameworks/${model.frameworkId}`;
      const levelChanged = label !== String(lc.label ?? '') || description !== String(lc.description ?? '');
      const descriptorChanged = descriptor !== String(lc.descriptor ?? '');
      if (!levelChanged && !descriptorChanged) { if (feedback) feedback.textContent = 'No changes to save.'; return; }
      if (feedback) feedback.textContent = 'Saving…';
      let revision = model.frameworkRevision;
      try {
        if (levelChanged) {
          const result = await api(`${fp}/rubric/levels/${lc.levelId}`, {method: 'PATCH', body: JSON.stringify({expected_revision: revision, label, description})});
          revision = result.framework_revision ?? revision;
        }
        if (descriptorChanged) {
          await api(`${fp}/rubric/descriptors`, {method: 'PUT', body: JSON.stringify({
            expected_revision: revision, framework_competency_id: Number(lc.competencyId),
            rubric_level_id: Number(lc.levelId), descriptor,
            grade_level: lc.grade == null || lc.grade === '' ? null : lc.grade,
          })});
        }
        say('Level saved.');
        if (typeof window !== 'undefined' && window.TalentConfiguration && typeof window.TalentConfiguration.rerenderCenter === 'function') {
          await window.TalentConfiguration.rerenderCenter();
        }
      } catch (error) {
        if (feedback) { feedback.textContent = (error && error.userSafe && error.message) || 'Unable to save. Your entries are preserved.'; feedback.setAttribute('role', 'alert'); }
      }
    });
  }
});
