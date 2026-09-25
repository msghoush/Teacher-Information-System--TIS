/* Shared curated, user-safe error mapping for Talent API responses.
 * Backend `detail` strings are NEVER echoed to users: only HTTP status and
 * known stable backend `code` values map to approved copy. Raw exception text,
 * SQL, Python, JS, endpoint names, stack traces and internal configuration text
 * are structurally excluded here and by the renderers' safeMessage() gate. */
((root, factory) => {
  const api = factory();
  if (typeof module !== 'undefined' && module.exports) module.exports = api;
  if (root) root.TalentApiErrors = api;
})(typeof window !== 'undefined' ? window : globalThis, () => {
  'use strict';

  const GENERIC = 'This view could not be loaded. Retry, or contact your administrator if the problem continues.';

  const STATUS_COPY = {
    401: 'Your session may have ended. Sign in again, then reopen this view.',
    403: 'This view is not available for your permissions or selected scope.',
    404: 'This record is unavailable in your authorized scope.',
    400: 'This context cannot be displayed. Check the selected Academic Year, Program, and available assessment data.',
    422: 'This context cannot be displayed. Check the selected Academic Year, Program, and available assessment data.',
    503: 'Analytics cannot be displayed yet because its governed privacy/configuration prerequisites are incomplete. Ask an administrator to complete the required analytics configuration, then retry.',
  };

  // Known stable backend error codes that are intentionally user-facing. Only
  // these exact codes may map to curated copy; arbitrary detail is never shown.
  const CODE_COPY = {
    // Start Assessment: stable business-rule codes whose specific, actionable reason
    // is safe to show (fixed copy; the backend detail text is still never echoed).
    assessment_tool_unavailable: 'The Grade of this Student has no saved assessment criteria in this Program yet. Open the Program, configure the Competencies, KPIs and Levels for that Grade, then start the Assessment.',
    student_not_eligible: 'This Student has no current Academic Placement in the selected Academic Year, so an Assessment cannot be started.',
    invalid_student_context: 'This Student is not available in the selected Evaluation. Reload the Student list and try again.',
    duplicate_assessment: 'An Assessment for this Student already exists in this Evaluation. Reload the Student list.',
    context_mismatch: 'The selected Program or Academic Year no longer matches this Evaluation. Choose the Evaluation Period and Program again.',
    assessment_conflict: 'This Assessment was just changed elsewhere. Reload the Student list and try again.',
  };

  function messageFor(status, code) {
    if (code != null && String(code) !== '' && Object.prototype.hasOwnProperty.call(CODE_COPY, String(code))) {
      return CODE_COPY[String(code)];
    }
    const s = Number(status);
    if (Number.isInteger(s)) {
      if (s >= 500 && s !== 503) return GENERIC;
      if (Object.prototype.hasOwnProperty.call(STATUS_COPY, s)) return STATUS_COPY[s];
    }
    return GENERIC;
  }

  function httpError(status, code) {
    const error = new Error(messageFor(status, code));
    error.userSafe = true;
    if (Number.isInteger(Number(status))) error.status = Number(status);
    if (code != null && code !== '') error.code = code;
    return error;
  }

  return {GENERIC, STATUS_COPY, CODE_COPY, messageFor, httpError};
});
