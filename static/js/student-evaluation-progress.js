(() => {
  'use strict';

  const esc = value => String(value ?? '').replace(/[&<>"']/g, character => ({
    '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;',
  }[character]));

  const unavailableLabels = {
    pending: 'Pending',
    incomplete: 'Incomplete',
    insufficient_evidence: 'Insufficient evidence',
    unassessed: 'Not yet assessed',
    not_applicable: 'Not applicable',
  };

  const numeric = value => typeof value === 'number' && Number.isFinite(value);

  function periodResult(period) {
    if (period?.result_state === 'available' && numeric(period.normalized_percent)) {
      return `<strong class="stu-evaluation-value" aria-label="${esc(period.label)} result ${esc(period.normalized_percent)} percent">${esc(period.normalized_percent)}%</strong>`;
    }
    return `<span class="stu-evaluation-state">${esc(unavailableLabels[period?.result_state] || 'Unavailable')}</span>`;
  }

  function renderEvaluationProgress(data) {
    const periods = Array.isArray(data?.periods) ? data.periods : [];
    if (!periods.length) {
      return '<div class="stu-evaluation-progress"><h5>Evaluation Progress</h5><p class="stu-hint">No active Evaluation Periods yet.</p></div>';
    }
    const periodItems = periods.map(period => `<li class="stu-evaluation-period"><div><span class="stu-evaluation-sequence">${esc(period.sequence)}</span><strong>${esc(period.label)}</strong></div>${periodResult(period)}</li>`).join('');
    const frameworkMessage = data.comparability_state === 'not_comparable' && data.comparability_reason_code === 'framework_changed'
      ? '<p class="stu-evaluation-explanation" role="status">The Program framework changed between Evaluation Periods. Period results remain available individually, but a combined Overall Result is not comparable.</p>'
      : '';
    const overall = data.comparability_state === 'comparable' && numeric(data.current_overall_result)
      ? `<div class="stu-evaluation-overall" aria-label="Overall Result ${esc(data.current_overall_result)} percent"><span>Overall Result</span><strong>${esc(data.current_overall_result)}%</strong></div>`
      : '';
    return `<section class="stu-evaluation-progress" aria-labelledby="student-evaluation-progress-${esc(data.program_id)}-${esc(data.academic_year_id)}"><h5 id="student-evaluation-progress-${esc(data.program_id)}-${esc(data.academic_year_id)}">Evaluation Progress</h5><ol class="stu-evaluation-periods" aria-label="Evaluation Period results">${periodItems}</ol>${frameworkMessage}${overall}</section>`;
  }

  async function loadProgress(container) {
    const {programId, academicYearId, studentId} = container.dataset;
    try {
      const response = await fetch(`/api/talent/evaluation-progress/programs/${encodeURIComponent(programId)}/academic-years/${encodeURIComponent(academicYearId)}/students/${encodeURIComponent(studentId)}`, {
        headers: {'Accept': 'application/json'}, credentials: 'same-origin',
      });
      if (!response.ok) throw new Error('Evaluation Progress is unavailable.');
      container.innerHTML = renderEvaluationProgress(await response.json());
    } catch (error) {
      container.innerHTML = `<p class="stu-hint" role="status">${esc(error.message || 'Evaluation Progress is unavailable.')}</p>`;
    }
  }

  if (typeof module !== 'undefined' && module.exports) {
    module.exports = {renderEvaluationProgress};
  } else {
    window.addEventListener('DOMContentLoaded', () => {
      document.querySelectorAll('[data-evaluation-progress]').forEach(loadProgress);
    });
  }
})();
