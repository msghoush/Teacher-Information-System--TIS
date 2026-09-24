/* Shared Talent Student identity presentation (Deployment Acceptance Correction B).
 *
 * ONE convention for every identifiable Student in Talent & Potential:
 *   Student name / [Learning Style: X] / [Classification: Y] / [Talented]
 *
 * Presentation only. The Classification label and the Talented flag are
 * backend-authoritative fields (talent_classification_service) that this module
 * merely renders: it contains no score, no band boundary, no percentage and no
 * classification arithmetic. "Talented" is rendered only when the backend
 * classification label is Exceptional. Learning Style is the canonical
 * Student.learning_style category supplied by an authorized projection; an
 * absent (undefined) value means "not provided on this surface" and renders
 * nothing, while null/empty means the Student has no assigned category. */
((root, factory) => {
  const api = factory();
  if (typeof module !== 'undefined' && module.exports) module.exports = api;
  if (root) root.TalentStudentIdentity = api;
})(typeof window !== 'undefined' ? window : globalThis, () => {
  'use strict';

  const LEARNING_STYLES = ['Visual', 'Auditory', 'Read/Write', 'Kinesthetic', 'Verbal', 'Non-verbal', 'Quantitative', 'Spatial'];
  // Display allow-list of the five backend labels (never used to derive a label).
  const CLASSIFICATIONS = ['Needs Improvement', 'Developing', 'Meets Expectations', 'Advanced', 'Exceptional'];
  const TALENTED_LABEL = 'Exceptional';

  const esc = value => String(value ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  const slug = value => String(value).toLowerCase().replace(/[^a-z]+/g, '-').replace(/^-|-$/g, '');

  // undefined -> not provided on this surface (omit). null/''/unknown -> Unassigned
  // (never a fabricated category). A recognised category -> its own chip.
  function learningStyleChip(style, options = {}) {
    if (style === undefined) return '';
    const known = LEARNING_STYLES.includes(style);
    if (!known && options.hideUnassigned) return '';
    const text = known ? style : 'Unassigned';
    return `<span class="tp-ls-chip${known ? '' : ' is-unassigned'}" data-learning-style="${esc(text)}"><span class="tp-ls-chip-label">Learning Style:</span> ${esc(text)}</span>`;
  }

  const isTalentedLabel = classification => classification === TALENTED_LABEL;

  // Text always accompanies colour. A missing classification renders the neutral
  // "Not assessed" chip only when the surface asks for it (options.notAssessed).
  function classificationChip(classification, options = {}) {
    if (!classification || !CLASSIFICATIONS.includes(classification)) {
      return options.notAssessed ? '<span class="tp-class-chip is-none">Classification: Not assessed</span>' : '';
    }
    return `<span class="tp-class-chip tp-class-${esc(slug(classification))}" data-classification="${esc(classification)}"><span class="tp-class-chip-label">Classification:</span> ${esc(classification)}</span>`;
  }

  function talentedBadge(classification, isTalented) {
    return isTalentedLabel(classification) && isTalented !== false
      ? '<span class="tp-badge tp-badge-talented">Talented</span>' : '';
  }

  // Compact metadata group (chips only).
  function metaHtml({learningStyle, classification, isTalented, notAssessed = false, showClassification = true, hideUnassigned = false} = {}) {
    const chips = [
      learningStyleChip(learningStyle, {hideUnassigned}),
      showClassification ? classificationChip(classification, {notAssessed}) : '',
      showClassification ? talentedBadge(classification, isTalented) : '',
    ].filter(Boolean);
    return chips.length ? `<span class="tp-identity-meta">${chips.join('')}</span>` : '';
  }

  // Full identity: name (wrapping-safe) + metadata chips.
  function identityHtml({name, learningStyle, classification, isTalented, notAssessed = false, showClassification = true, hideUnassigned = false, extra = ''} = {}) {
    const display = String(name ?? '').trim() || 'Student name unavailable';
    return `<span class="tp-identity"><span class="tp-identity-name">${esc(display)}</span>${extra}${metaHtml({learningStyle, classification, isTalented, notAssessed, showClassification, hideUnassigned})}</span>`;
  }

  return {LEARNING_STYLES, CLASSIFICATIONS, learningStyleChip, classificationChip, talentedBadge, metaHtml, identityHtml, esc};
});
