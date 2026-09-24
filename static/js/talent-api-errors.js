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
  const CODE_COPY = {};

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
