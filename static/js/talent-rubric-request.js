/* Shared single-flight ownership store for the rubric-distribution read.
 * talent.js owns the request per render generation (it publishes its already
 * memoized promise); talent-experience.js consumes the same promise instead of
 * issuing a duplicate fetch for the same Program + Academic Year + assessment
 * state context. A full navigation reloads the script, so nothing survives
 * navigation; talent.js resets the store at each render generation boundary. */
((root, factory) => {
  const api = factory();
  if (typeof module !== 'undefined' && module.exports) module.exports = api;
  if (root) root.TalentRubricRequest = api;
})(typeof window !== 'undefined' ? window : globalThis, () => {
  'use strict';

  const reads = new Map();

  // The Branch scope is part of the read's identity: a Branch-scoped read must
  // never be reused for another Branch (or for the organization-wide read).
  // talent.js is the single owner of the resolved Branch scope and publishes it
  // here, so every consumer of this store keys and requests the SAME scope without
  // depending on the browser URL.
  let branchScope = '';

  function setBranch(branchId) {
    branchScope = branchId == null ? '' : String(branchId);
  }

  function currentBranch() {
    return branchScope;
  }

  function key(programId, year, branchId = branchScope) {
    const branch = branchId == null || branchId === '' ? '' : `|${String(branchId)}`;
    return `${String(programId)}|${String(year)}|completed${branch}`;
  }

  function publish(k, promise) {
    reads.set(k, promise);
  }

  function get(k) {
    return reads.get(k);
  }

  function reset() {
    reads.clear();
  }

  return {key, publish, get, reset, setBranch, currentBranch};
});
