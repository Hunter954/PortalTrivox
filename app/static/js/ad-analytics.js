/* GA4 banner measurement: >=50% visible for 1 continuous second, once per
 * creative/placement/page. Rotation, scrolling back and tab changes do not
 * multiply impressions. Existing Google-tag consent settings remain in force. */
(() => {
  'use strict';
  if (window.__trivoxAdAnalytics || typeof window.gtag !== 'function' ||
      typeof IntersectionObserver !== 'function') return;
  window.__trivoxAdAnalytics = true;
  const seen = new Set();
  const records = new Map();
  const timers = new Map();

  function ready(slide) {
    const img = slide.querySelector('img');
    const rect = slide.getBoundingClientRect();
    const style = getComputedStyle(slide);
    return !document.hidden && !slide.closest('[hidden]') &&
      slide.getAttribute('aria-hidden') !== 'true' &&
      rect.width > 0 && rect.height > 0 && style.visibility !== 'hidden' &&
      style.display !== 'none' && style.opacity !== '0' &&
      (!slide.checkVisibility || slide.checkVisibility({checkOpacity:true, checkVisibilityCSS:true})) &&
      img && img.complete && img.naturalWidth > 0;
  }

  function emit(event, slide) {
    const data = slide.dataset;
    const name = data.adPromotionName || 'Publicidade';
    const id = data.adPromotionId;
    const slot = data.adPlacement || data.adSlot;
    const promotion = {promotion_id:id, promotion_name:name,
      creative_name:`${name} / ${id.slice(-8)}`.slice(0,100), creative_slot:slot};
    try {
      window.gtag('event', event, {...promotion, transport_type:'beacon',
        items:[{item_id:`${id}:${data.adSlot}`, item_name:name, ...promotion, quantity:1}]});
      return true;
    } catch (_) { return false; } // Measurement must never block the ad link.
  }

  function stop(slide) {
    if (timers.has(slide)) window.clearTimeout(timers.get(slide));
    timers.delete(slide);
  }

  function evaluate(slide) {
    const record = records.get(slide);
    if (!record) return;
    if (seen.has(record.key) || record.ratio < .5 || !ready(slide)) {
      stop(slide); return;
    }
    if (timers.has(slide)) return;
    timers.set(slide, window.setTimeout(() => {
      timers.delete(slide);
      if (!seen.has(record.key) && record.ratio >= .5 && ready(slide) && emit('view_promotion', slide)) {
        seen.add(record.key);
      }
    }, 1000));
  }

  const observer = new IntersectionObserver(entries => {
    for (const entry of entries) {
      const record = records.get(entry.target);
      if (!record) continue;
      record.ratio = entry.isIntersecting ? entry.intersectionRatio : 0;
      evaluate(entry.target);
    }
  }, {threshold:[0,.5,1]});

  document.querySelectorAll('[data-ad-slide][data-ad-promotion-id]').forEach(slide => {
    records.set(slide, {key:`${slide.dataset.adPromotionId}:${slide.dataset.adSlot}`, ratio:0});
    observer.observe(slide);
    const img = slide.querySelector('img');
    if (img) img.addEventListener('load', () => evaluate(slide));
    slide.addEventListener('click', () => {if (ready(slide)) emit('select_promotion', slide);});
    slide.addEventListener('auxclick', event => {if (event.button===1 && ready(slide)) emit('select_promotion', slide);});
    new MutationObserver(() => {
      // A new rotation needs a fresh intersection observation before timing.
      stop(slide); records.get(slide).ratio=0;
      observer.unobserve(slide); observer.observe(slide);
    }).observe(slide, {attributes:true, attributeFilter:['hidden','aria-hidden','class','style']});
  });
  document.addEventListener('visibilitychange', () => {
    for (const slide of records.keys()) evaluate(slide);
  });
})();
