/* Shared, presentation-only Program Grades label ("Grades 1 - 3", "Grade 4", "KG").
 * Used by the operational Programs view and the System Configuration workspace so
 * both describe a Program's eligible Grades identically. Never derives eligibility. */
((root, factory) => {
  const api = factory();
  if (typeof module !== 'undefined' && module.exports) module.exports = api;
  if (root) root.TalentProgramGrades = api;
})(typeof window !== 'undefined' ? window : globalThis, () => {
  'use strict';
  const gradeLabel = g => (String(g) === 'KG' ? 'KG' : `Grade ${g}`);
  const gradeOrder = g => (String(g) === 'KG' ? -1 : Number(g));
  function gradesSummary(levels) {
    const grades = [...new Set((levels || []).map(String))].sort((a, b) => gradeOrder(a) - gradeOrder(b));
    if (!grades.length) return 'Grades not set';
    if (grades.length === 1) return gradeLabel(grades[0]);
    const numeric = grades.every(g => g !== 'KG' && Number.isInteger(Number(g)));
    if (numeric && Number(grades.at(-1)) - Number(grades[0]) === grades.length - 1) return `Grades ${grades[0]} - ${grades.at(-1)}`;
    return `Grades ${grades.join(', ')}`;
  }
  return {gradeLabel, gradesSummary};
});
