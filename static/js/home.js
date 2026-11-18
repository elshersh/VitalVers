/* Home page controller.
   - Scroll story (large screens): the hero is pinned while the camera flies into the hologram, the suit's
     sensors, then Earth and the orbit; three chapter cards explain each stop; a rail shows progress.
   - Section reveals, number count-ups and the "How it works" progress line. */
(function () {
  'use strict';

  var story = document.getElementById('vvStory');
  var hero = story ? story.querySelector('.hero') : null;
  if (!story || !hero) return;

  var mqStory = window.matchMedia('(min-width: 900px) and (min-aspect-ratio: 5/4) and (prefers-reduced-motion: no-preference)');
  var reduce = window.matchMedia('(prefers-reduced-motion: reduce)').matches;
  var content = hero.querySelector('.content');
  var sideline = hero.querySelector('.sideline');
  var chapters = Array.prototype.slice.call(story.querySelectorAll('.hm-chapter'));
  var rail = story.querySelector('.hm-rail');
  var railFill = story.querySelector('.hm-rail-fill');
  var dots = Array.prototype.slice.call(story.querySelectorAll('.hm-rail-dot'));
  var cue = story.querySelector('.hm-scroll-cue');
  var dim = story.querySelector('.hm-dim');

  // camera stops in the photo "world" (3200x3200 px of the wide NASA shot):
  // [progress, x, y, zoom, screen anchor x, screen anchor y]
  // 1) the whole scene with the solar system  2) zoom in to the astronaut (the close-up photo blends in)
  // 3) the helmet  4) down to Earth below the astronaut
  var STOPS = [
    [0.00, 1565, 1258, 1.10, 0.66, 0.36],   // astronaut to the right of the title, Earth along the bottom
    [0.07, 1565, 1258, 1.10, 0.66, 0.36],
    [0.36, 1565, 1262, 4.00, 0.62, 0.52],   // astronaut, framed right of the chapter card
    [0.50, 1565, 1262, 4.15, 0.62, 0.52],
    [0.62, 1652, 1205, 8.20, 0.60, 0.50],   // helmet and visor
    [0.71, 1652, 1205, 8.50, 0.60, 0.50],
    [0.84, 1547, 1540, 5.10, 0.50, 0.50],   // legs and Earth below
    [0.92, 1547, 1540, 5.25, 0.50, 0.50],
    [1.00, 1547, 1540, 5.40, 0.50, 0.50]
  ];
  // chapter windows: [fade in start, fully in, start fade out, fully out]
  var WINDOWS = [[0.30, 0.37, 0.50, 0.55], [0.57, 0.63, 0.71, 0.75], [0.78, 0.84, 0.92, 0.96]];

  function clamp(v, a, b) { return Math.max(a, Math.min(b, v)); }
  function smooth(t) { return t * t * (3 - 2 * t); }
  function ramp(p, a, b) { return smooth(clamp((p - a) / (b - a), 0, 1)); }
  function windowed(p, w) { return Math.min(ramp(p, w[0], w[1]), 1 - ramp(p, w[2], w[3])); }

  function cameraAt(p) {
    for (var i = 1; i < STOPS.length; i++) {
      if (p <= STOPS[i][0]) {
        var a = STOPS[i - 1], b = STOPS[i];
        var t = smooth((p - a[0]) / Math.max(1e-6, b[0] - a[0]));
        var out = [];
        for (var j = 1; j < 6; j++) {
          out.push(j === 3 ? Math.exp(Math.log(a[j]) + (Math.log(b[j]) - Math.log(a[j])) * t)   // zoom in log space
                           : a[j] + (b[j] - a[j]) * t);
        }
        return out;
      }
    }
    return STOPS[STOPS.length - 1].slice(1);
  }

  var target = 0, shown = 0, active = false, raf = 0;

  function progress() {
    var r = story.getBoundingClientRect();
    var range = story.offsetHeight - window.innerHeight;
    return range > 0 ? clamp(-r.top / range, 0, 1) : 0;
  }

  function render(p) {
    var c = cameraAt(p);
    if (window.VV_HERO) {
      window.VV_HERO.setCamera(c[0], c[1], c[2], c[3], c[4]);
      window.VV_HERO.setHud({
        reticle: 1 - ramp(p, 0.10, 0.2),
        vitals: windowed(p, [0.33, 0.40, 0.50, 0.55]),
        check: windowed(p, [0.60, 0.65, 0.71, 0.75]),
        link: windowed(p, [0.80, 0.85, 0.92, 0.96])
      });
    }

    var out = ramp(p, 0.04, 0.17);                        // hero text leaves as the camera starts moving
    if (content) {
      content.style.opacity = (1 - out).toFixed(3);
      content.style.transform = 'translate3d(0,' + (-60 * out).toFixed(1) + 'px,0)';
      content.style.filter = out > 0.01 ? 'blur(' + (out * 6).toFixed(1) + 'px)' : '';
      content.style.pointerEvents = out > 0.5 ? 'none' : '';
    }
    if (sideline) sideline.style.opacity = (1 - out).toFixed(3);

    chapters.forEach(function (ch, i) {
      var v = windowed(p, WINDOWS[i]);
      ch.style.opacity = v.toFixed(3);
      ch.style.transform = 'translate3d(0, calc(-50% + ' + ((1 - v) * 40).toFixed(1) + 'px), 0)';
      ch.style.visibility = v < 0.01 ? 'hidden' : 'visible';
    });

    var railOn = p > 0.14 && p < 0.97;
    if (rail) rail.classList.toggle('is-on', railOn);
    if (railFill) railFill.style.height = (clamp((p - 0.18) / (0.88 - 0.18), 0, 1) * 100).toFixed(1) + '%';
    dots.forEach(function (d, i) { d.classList.toggle('is-on', p >= WINDOWS[i][0] + 0.04); });

    if (cue) { cue.style.opacity = (1 - ramp(p, 0.0, 0.05)).toFixed(3); cue.style.pointerEvents = p > 0.03 ? 'none' : ''; }
    if (dim) dim.style.opacity = ramp(p, 0.9, 1).toFixed(3);
    hero.style.setProperty('--hm-scrim', ramp(p, 0.08, 0.22).toFixed(3));
  }

  function loop() {
    raf = 0;
    shown += (target - shown) * 0.14;                     // eased so trackpads and wheels both feel smooth
    if (Math.abs(target - shown) < 0.0004) shown = target;
    render(shown);
    if (shown !== target) raf = requestAnimationFrame(loop);
  }
  function onScroll() {
    if (!active) return;
    target = progress();
    if (!raf) raf = requestAnimationFrame(loop);
  }

  function resetStory() {
    // not pinned (phones, tablets, reduced motion): a still framing a little closer to the astronaut
    if (window.VV_HERO) {
      window.VV_HERO.setCamera(1565, 1258, window.innerWidth < 700 ? 1.9 : 1.1, 0.66, 0.36);
      window.VV_HERO.setHud({ reticle: 1, vitals: 0, check: 0, link: 0 });
    }
    [content, sideline].forEach(function (n) {
      if (!n) return;
      n.style.opacity = ''; n.style.transform = ''; n.style.filter = ''; n.style.pointerEvents = '';
    });
    chapters.forEach(function (ch) { ch.style.opacity = ''; ch.style.transform = ''; ch.style.visibility = ''; });
    hero.style.removeProperty('--hm-scrim');
  }

  function setMode() {
    active = mqStory.matches;
    if (active) { target = shown = progress(); render(shown); } else resetStory();
  }
  setMode();
  if (mqStory.addEventListener) mqStory.addEventListener('change', setMode);
  window.addEventListener('scroll', onScroll, { passive: true });
  window.addEventListener('resize', onScroll);

  // the scroll cue jumps past the story to the overview
  if (cue) cue.addEventListener('click', function (e) {
    var to = document.getElementById('overview');
    if (!to) return;
    e.preventDefault();
    to.scrollIntoView({ behavior: reduce ? 'auto' : 'smooth', block: 'start' });
  });

  // ------------------------------------------------------------------ reveals + count-ups
  function countUp(el) {
    var end = parseFloat(el.getAttribute('data-count'));
    var fmt = el.getAttribute('data-format');
    function show(v) {
      el.textContent = fmt === 'pct' ? v.toFixed(1) + '%' : Math.round(v).toLocaleString('en-US');
    }
    if (reduce) { show(end); return; }
    var t0 = performance.now(), dur = 1600;
    (function step(now) {
      var k = clamp((now - t0) / dur, 0, 1);
      show(end * (1 - Math.pow(1 - k, 4)));
      if (k < 1) requestAnimationFrame(step);
    })(t0);
  }

  var items = Array.prototype.slice.call(document.querySelectorAll('[data-rv]'));
  var counters = Array.prototype.slice.call(document.querySelectorAll('[data-count]'));
  if (!('IntersectionObserver' in window) || reduce) {
    items.forEach(function (n) { n.classList.add('is-in'); });
    counters.forEach(countUp);
  } else {
    var io = new IntersectionObserver(function (entries) {
      entries.forEach(function (en) {
        if (!en.isIntersecting) return;
        en.target.classList.add('is-in');
        io.unobserve(en.target);
      });
    }, { rootMargin: '0px 0px -10% 0px', threshold: 0.12 });
    items.forEach(function (n) { io.observe(n); });
    var cio = new IntersectionObserver(function (entries) {
      entries.forEach(function (en) {
        if (!en.isIntersecting) return;
        countUp(en.target);
        cio.unobserve(en.target);
      });
    }, { threshold: 0.6 });
    counters.forEach(function (n) { cio.observe(n); });
  }

  // "How it works" line fills as the section scrolls through the screen
  var steps = document.querySelector('.hm-steps');
  var line = document.querySelector('.hm-steps-line span');
  if (steps && line) {
    var lineTick = function () {
      var r = steps.getBoundingClientRect(), vh = window.innerHeight;
      var k = reduce ? 1 : clamp((vh * 0.85 - r.top) / (vh * 0.55), 0, 1);
      line.style.width = (k * 100).toFixed(1) + '%';
    };
    window.addEventListener('scroll', lineTick, { passive: true });
    lineTick();
  }
})();
