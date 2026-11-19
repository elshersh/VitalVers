/*
 * Vitalverse tab accounts + fetch guard. Must load before any other script.
 *
 * Tab accounts: one browser can be signed in to several accounts, one per tab (an astronaut in one tab and a
 * flight surgeon in another). The server keeps this browser's sessions in an HttpOnly cookie and their
 * one-way tags in the readable vv_tags cookie. Each tab remembers which tag it uses (sessionStorage, so a
 * refresh keeps it) and names it on every API request (X-VV-Account header). A new tab starts with the most
 * recent sign-in; signing in or out in a tab changes only that tab. A tab whose account was signed out is
 * shown as signed out, never switched to another account.
 *
 * Fetch guard: the public link can run behind a forwarding relay (GitHub Codespaces) that was seen handing
 * one visitor's answer to another. The server stamps every /api/ answer with the tag of the session it was
 * made for (X-VV-Tag). Answers with another tag are thrown away and asked for again; private photos and
 * audio (/api/media/...) are loaded through the same check.
 *
 * Other tabs of this browser are told right away when this tab changes something (BroadcastChannel), so they
 * can refresh without waiting for their next check (static/js/shell.js).
 * Prototype for research/education only - not for clinical diagnosis.
 */
(function () {
  'use strict';
  if (window.__vvFetchGuard || typeof window.fetch !== 'function') return;
  window.__vvFetchGuard = true;

  var nativeFetch = window.fetch.bind(window);
  var TAG_HEADER = 'X-VV-Tag';
  var ACCOUNT_HEADER = 'X-VV-Account';
  var ACCOUNT_SET_HEADER = 'X-VV-Account-Set';
  var ACCOUNT_KEY = 'vvAccount';
  var ANON = 'anon';
  var TAG_RE = /^[0-9a-f]{20}$/;
  var RETRY_DELAYS = [150, 400, 900, 1600];
  var DASHBOARD_PATHS = ['/health.html', '/astronaut-dashboard.html', '/doctor-dashboard.html'];

  /* ---- which account this tab uses ---- */
  function browserTags() {
    var m = document.cookie.match(/(?:^|;\s*)vv_tags=([^;]+)/);
    if (!m) return [];
    return decodeURIComponent(m[1]).split('.').filter(function (t) { return TAG_RE.test(t); });
  }
  function readPinned() {
    try { return window.sessionStorage.getItem(ACCOUNT_KEY); } catch (e) { return null; }
  }
  function pin(tag) {
    try { window.sessionStorage.setItem(ACCOUNT_KEY, tag); } catch (e) {}
  }
  function chooseAccount() {
    var tags = browserTags();
    var pinned = readPinned();
    if (pinned === ANON) return ANON;                                    // signed out in this tab
    if (pinned && TAG_RE.test(pinned)) return tags.indexOf(pinned) !== -1 ? pinned : ANON;
    var fromLink = null;                                                 // opened from a link of another tab
    try { fromLink = new URL(location.href).searchParams.get('account'); } catch (e) {}
    if (fromLink && tags.indexOf(fromLink) !== -1) { pin(fromLink); return fromLink; }
    if (tags.length) { pin(tags[tags.length - 1]); return tags[tags.length - 1]; }  // new tab: latest sign-in
    return ANON;
  }
  var account = chooseAccount();

  function useAccount(tag) {
    if (tag !== ANON && !TAG_RE.test(tag)) return;
    account = tag;
    pin(tag);
  }

  /* ---- tell this browser's other tabs that something changed ---- */
  var channel = null;
  var lastWriteAt = 0;
  try { if (typeof BroadcastChannel === 'function') channel = new BroadcastChannel('vitalverse-live'); } catch (e) {}
  function announceChange() {
    if (channel) { try { channel.postMessage({ type: 'changed', at: Date.now() }); } catch (e) {} }
  }

  function toUrl(input) {
    try { return new URL(typeof input === 'string' ? input : (input && input.url) || String(input), location.href); }
    catch (e) { return null; }
  }
  function isApi(url) {
    return !!url && url.origin === location.origin && url.pathname.indexOf('/api/') === 0;
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

  function withAccount(input, init, tag) {
    var opts = Object.assign({ credentials: 'same-origin' }, init || {});
    var base = opts.headers || ((input && typeof input === 'object' && input.headers) ? input.headers : undefined);
    var headers = new Headers(base || {});
    headers.set(ACCOUNT_HEADER, tag);
    opts.headers = headers;
    return opts;
  }

  function guardedFetch(input, init) {
    var method = String((init && init.method) || (input && input.method) || 'GET').toUpperCase();
    var url = toUrl(input);
    if (!isApi(url)) return nativeFetch(input, init);

    var expected = account;
    var opts = withAccount(input, init, expected);
    if (method !== 'GET' && method !== 'HEAD') {
      return nativeFetch(input, opts).then(function (resp) {
        var set = resp.headers.get(ACCOUNT_SET_HEADER);
        if (set && resp.ok) useAccount(set);                    // signed in or out in this tab
        if (resp.ok) { lastWriteAt = Date.now(); announceChange(); }
        return resp;
      });
    }

    function attempt(n) {
      var target = n === 0 ? url.href : withNonce(url);
      return nativeFetch(target, opts).then(function (resp) {
        var tag = resp.headers.get(TAG_HEADER);
        // answers without a tag did not come from the Vitalverse app (for example a relay error page)
        if (!tag || tag === expected) return resp;
        if (window.console) console.warn('[Vitalverse] discarded an API answer meant for another visitor:', url.pathname);
        if (n >= RETRY_DELAYS.length) return mixedUpAnswer();
        return wait(RETRY_DELAYS[n]).then(function () { return attempt(n + 1); });
      });
    }
    return attempt(0);
  }

  window.fetch = guardedFetch;

  /* ---- page links: the dashboard page depends on the account, so name this tab's account ---- */
  function pageUrl(href) {
    var u = toUrl(href);
    if (!u || u.origin !== location.origin || DASHBOARD_PATHS.indexOf(u.pathname) === -1) return href;
    if (account === ANON) u.searchParams.delete('account');
    else u.searchParams.set('account', account);
    return u.pathname + u.search + u.hash;
  }
  function nameAccountOnLink(ev) {
    var a = ev.target && ev.target.closest ? ev.target.closest('a[href]') : null;
    if (!a) return;
    var next = pageUrl(a.getAttribute('href'));
    if (next !== a.getAttribute('href')) a.setAttribute('href', next);
  }
  // also for middle-click and "open in new tab", so the new tab opens with this tab's account
  ['click', 'auxclick', 'contextmenu'].forEach(function (type) {
    document.addEventListener(type, nameAccountOnLink, true);
  });

  window.VV_ACCOUNT = {
    current: function () { return account; },
    pageUrl: pageUrl,
    announceChange: announceChange,
    lastWriteAt: function () { return lastWriteAt; },
    channel: channel
  };

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
