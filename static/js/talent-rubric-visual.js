/* Shared, order-derived rubric presentation for every Talent surface. */
((root, factory) => {
  const api = factory();
  if (typeof module !== 'undefined' && module.exports) module.exports = api;
  if (root) root.TalentRubricVisual = api;
})(typeof window !== 'undefined' ? window : globalThis, () => {
  'use strict';
  const esc = value => String(value ?? '').replace(/[&<>"']/g, character => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[character]));
  const intensity = (index, count) => count <= 1 ? 1 : Math.max(0, Math.min(1, index / (count - 1)));
  const ordered = levels => [...(levels || [])].sort((a, b) => Number(a.display_order || 0) - Number(b.display_order || 0));
  const position = (level, levels) => {
    const rows = ordered(levels);
    const index = rows.findIndex(item => String(item.id ?? item.label) === String(level?.id ?? level?.label));
    return {index: index < 0 ? 0 : index, count: Math.max(rows.length, 1)};
  };
  function badge(level, levels, {selected=false, suffix=''}={}) {
    if (!level) return '<span class="tp-rubric-level tp-rubric-level-empty">No rubric level recorded</span>';
    const pos = level.position && level.total_levels
      ? {index:Number(level.position)-1, count:Number(level.total_levels)}
      : position(level, levels);
    const strength = intensity(pos.index, pos.count);
    return `<span class="tp-rubric-level${selected?' is-selected':''}" style="--tp-rubric-intensity:${strength.toFixed(3)}" data-rubric-order="${pos.index + 1}"${selected?' aria-current="true"':''}><span class="tp-rubric-order" aria-label="Rubric position ${pos.index + 1} of ${pos.count}">${pos.index + 1}/${pos.count}</span><span>${esc(level.label)}</span>${selected?'<span aria-hidden="true">✓</span>':''}${suffix?`<small>${esc(suffix)}</small>`:''}</span>`;
  }
  function distribution(levels) {
    const rows = ordered(levels);
    if (!rows.length) return '<p class="tp-empty">No rubric levels are configured.</p>';
    return `<div class="tp-rubric-chart" role="group" aria-label="Rubric level distribution">${rows.map((level,index)=>{
      const strength=intensity(index,rows.length);
      const visible=level.state==='visible'&&Number.isFinite(level.percentage);
      const state=level.state==='no_data'?'No data yet':level.state==='restricted'?'Not available for this view':'Protected for privacy';
      const track=visible?`<div class="tp-rubric-track" role="img" aria-label="${esc(level.label)}: ${level.percentage} percent"><span style="width:${Math.max(0,Math.min(100,level.percentage))}%"></span></div>`:`<div class="tp-rubric-track tp-rubric-track-state" role="img" aria-label="${esc(level.label)}: ${state}"></div>`;
      const value=visible?`<strong>${level.percentage}%</strong><small>${level.count ?? ''}</small>`:`<span class="tp-protected">${state}</span>`;
      return `<div class="tp-rubric-row" style="--tp-rubric-intensity:${strength.toFixed(3)}">${badge({...level,position:index+1,total_levels:rows.length},rows)}${track}${value}</div>`;
    }).join('')}</div>`;
  }
  return {esc, intensity, ordered, position, badge, distribution};
});
