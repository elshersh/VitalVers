/*
 * Vitalverse fetch guard - makes sure every API answer shown on this page belongs to this browser's session.
 *
 * The public link can run behind a forwarding relay (GitHub Codespaces) that was seen handing one visitor's
 * answer to another. The server stamps every /api/ answer with the tag of the session it was made for
 * (header X-VV-Tag); this browser knows its own tag from the readable vv_tag cookie set at sign-in.
 * Answers with someone else's tag are thrown away and asked for again; private photos and audio
 * (/api/media/...) are loaded through the same check. Must load before any other script.
 * Prototype for research/education only - not for clinical diagnosis.
 */
(function () {
  'use strict';
  if (window.__vvFetchGuard || typeof window.fetch !== 'function') return;
  window.__vvFetchGuard = true;

  var nativeFetch = window.fetch.bind(window);
  var TAG_HEADER = 'X-VV-Tag';
  var RETRY_DELAYS = [150, 400, 900, 1600];

  function myTag() {
    var m = document.cookie.match(/(?:^|;\s*)vv_tag=([^;]+)/);
    return m ? decodeURIComponent(m[1]) : 'anon';
  }

  function toUrl(input) {
    try { return new URL(typeof input === 'string' ? input : (input && input.url) || String(input), location.href); }
    catch (e) { return null; }
  }

  function isGuarded(url, method) {
    return !!url && url.origin === location.origin && url.pathname.indexOf('/api/') === 0 &&
      (method === 'GET' || method === 'HEAD');
  }

  function withNonce(url) {
    var u = new URL(url.href);
    u.searchParams.set('_vv', Date.now().toString(36) + Math.random().toString(36).slice(2, 8));
    return u.href;
  }

  function wait(ms) { return new Promise(function (r) { setTimeout(r, ms); }); }

  function mixedUpAnswer() {
    var body = JSON.stringify({
      detail: 'This answer got mixed up with another visitor\'s on the way, so it was not shown. Please try again.'
    });
    return new Response(body, { status: 503, headers: { 'Content-Type': 'application/json' } });
  }

  function guardedFetch(input, init) {
    var method = String((init && init.method) || (input && input.method) || 'GET').toUpperCase();
    var url = toUrl(input);
    if (!isGuarded(url, method)) return nativeFetch(input, init);

    var opts = Object.assign({ credentials: 'same-origin' }, init || {});
    function attempt(n) {
      var target = n === 0 ? url.href : withNonce(url);
      return nativeFetch(target, opts).then(function (resp) {
        var tag = resp.headers.get(TAG_HEADER);
        // answers without a tag did not come from the Vitalverse app (for example a relay error page)
        if (!tag || tag === myTag()) return resp;
        if (window.console) console.warn('[Vitalverse] discarded an API answer meant for another visitor:', url.pathname);
        if (n >= RETRY_DELAYS.length) return mixedUpAnswer();
        return wait(RETRY_DELAYS[n]).then(function () { return attempt(n + 1); });
      });
    }
    return attempt(0);
  }

  window.fetch = guardedFetch;

  /* ---- private photos and audio: load /api/media/... through the checked fetch ---- */
  var MEDIA_SELECTOR = 'img[src*="/api/media/"], audio[src*="/api/media/"], video[src*="/api/media/"], source[src*="/api/media/"]';
  var blobCache = {};

  function loadChecked(el) {
    var src = el.getAttribute('src') || '';
    if (src.indexOf('/api/media/') === -1) return;
    el.removeAttribute('src');               // never show bytes that were not checked
    el.setAttribute('data-vv-src', src);
    if (el.hasAttribute('alt')) {            // keep the alt text from flashing while the checked copy loads
      el.setAttribute('data-vv-alt', el.getAttribute('alt'));
      el.removeAttribute('alt');
    }
    function current() { return el.getAttribute('data-vv-src') === src; }
    function restoreAlt() {
      if (el.hasAttribute('data-vv-alt')) {
        el.setAttribute('alt', el.getAttribute('data-vv-alt'));
        el.removeAttribute('data-vv-alt');
      }
    }
    var cached = blobCache[src];
    var job = cached ? Promise.resolve(cached) : guardedFetch(src).then(function (r) {
      if (!r.ok) return null;
      return r.blob().then(function (b) { var u = URL.createObjectURL(b); blobCache[src] = u; return u; });
    });
    job.catch(function () { return null; }).then(function (blobUrl) {
      if (!current()) return;
      restoreAlt();
      if (!blobUrl) {                        // same signal as a broken image, so the page's fallbacks still run
        el.dispatchEvent(new Event('error'));
        return;
      }
      el.setAttribute('src', blobUrl);
      var media = el.tagName === 'SOURCE' ? el.parentElement : null;
      if (media && typeof media.load === 'function') media.load();
    });
  }

  function scan(node) {
    if (!node || node.nodeType !== 1) return;
    if (node.matches && node.matches(MEDIA_SELECTOR)) loadChecked(node);
    if (node.querySelectorAll) {
      var found = node.querySelectorAll(MEDIA_SELECTOR);
      for (var i = 0; i < found.length; i++) loadChecked(found[i]);
    }
  }

  if (typeof MutationObserver === 'function') {
    new MutationObserver(function (records) {
      for (var i = 0; i < records.length; i++) {
        var rec = records[i];
        if (rec.type === 'attributes') { scan(rec.target); continue; }
        for (var j = 0; j < rec.addedNodes.length; j++) scan(rec.addedNodes[j]);
      }
    }).observe(document.documentElement, { childList: true, subtree: true, attributes: true, attributeFilter: ['src'] });
  }
  document.addEventListener('DOMContentLoaded', function () { scan(document.documentElement); });
})();
