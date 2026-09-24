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

  function key(programId, year) {
    return `${String(programId)}|${String(year)}|completed`;
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

  return {key, publish, get, reset};
});
