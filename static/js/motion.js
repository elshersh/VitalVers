/* Vitalverse motion layer (see css/motion.css).
   - one continuous animated sky: the same stars at the same moment on every page (seeded + clock based),
     so the sky never jumps between pages; twinkle, depth layers, mouse/scroll parallax, shooting stars
   - smooth "drift through space" page transitions using cross-document View Transitions: the old page
     dissolves forward into the stars, the stars surge gently and settle, the new page glides in
   - scroll reveal, cursor spotlight on cards, click ripples
   Load this script in <head> WITHOUT defer: it must register its pagereveal listener before first render.
   Purely decorative: nothing here changes data or behaviour of the pages. */
(function () {
  'use strict';

  var root = document.documentElement;
  var mqReduce = window.matchMedia ? window.matchMedia('(prefers-reduced-motion: reduce)') : null;
  var reduce = !!(mqReduce && mqReduce.matches);
  var SKY_KEY = 'vv_sky_state';
  var SEED = 20261118;

  function readSky() {
    try { return JSON.parse(window.sessionStorage.getItem(SKY_KEY) || 'null'); } catch (e) { return null; }
  }
  function writeSky(obj) {
    try { window.sessionStorage.setItem(SKY_KEY, JSON.stringify(obj)); } catch (e) {}
  }

  // ======================================================================== sky state
  var canvas = document.createElement('canvas');
  canvas.id = 'vvStarfield';
  canvas.setAttribute('aria-hidden', 'true');
  var ctx = canvas.getContext('2d');
  var nebula = document.createElement('canvas');
  var nctx = nebula.getContext('2d');
  var glowC = document.createElement('canvas');           // soft glow layers, painted at 1/4 size
  var gctx = glowC.getContext('2d');

  var W = 0, H = 0, DPR = 1;
  var stars = [];
  var meteors = [];
  var sparks = [];
  var mouse = { x: -9999, y: -9999, tx: 0, ty: 0, px: 0, py: 0, active: false };
  var boost = 0;        // extra drift (in seconds of travel) gained during page arrivals; carried across pages
  var travel = 0;       // 0..1 strength of the current "surge forward"
  var skyScroll = 0;    // smoothed scroll offset used for the star parallax; carried across pages
  var running = false;
  var last = 0;
  var nextMeteor = 0;

  var saved = readSky();
  if (saved && Date.now() - (saved.at || 0) < 15000) {
    boost = Number(saved.boost) || 0;
    skyScroll = Number(saved.scroll) || 0;
    mouse.px = mouse.tx = Number(saved.mx) || 0;
    mouse.py = mouse.ty = Number(saved.my) || 0;
  }

  var PALETTE = [
    [255, 255, 255], [255, 255, 255], [255, 255, 255], [255, 255, 255],
    [214, 232, 255], [190, 214, 255],
    [226, 246, 205], [168, 224, 122]
  ];

  // small seeded random generator, so every page builds exactly the same sky
  function mulberry32(a) {
    return function () {
      a |= 0; a = (a + 0x6D2B79F5) | 0;
      var t = Math.imul(a ^ (a >>> 15), 1 | a);
      t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t;
      return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
    };
  }
  var MAX_STARS = 760;
  (function buildSky() {
    var r = mulberry32(SEED);
    for (var i = 0; i < MAX_STARS; i++) {
      var z = Math.pow(r(), 1.8);
      stars.push({
        x0: r(), y0: r(),
        z: 0.15 + z * 0.85,
        r: 0.35 + z * 1.55,
        a: 0.35 + r() * 0.65,
        tw: 0.6 + r() * 1.8,
        ph: r() * Math.PI * 2,
        c: PALETTE[(r() * PALETTE.length) | 0],
        glint: z > 0.82 && r() < 0.5
      });
    }
  })();
  var visibleStars = MAX_STARS;

  function rand(a, b) { return a + Math.random() * (b - a); }
  function frac(v) { return v - Math.floor(v); }
  function clock() { return (Date.now() % 100000000) / 1000; }   // shared clock for every page

  // ------------------------------------------------------------------ deep-space backdrop
  // Painted once per screen size into an off-screen canvas (slightly larger than the screen so it can
  // drift with the mouse and scroll). Built from a fixed seed, so every page shows the very same sky.
  var OV = 0.05;                 // overscan on each side, as a share of the screen size
  var NW = 0, NH = 0;            // backdrop size in CSS pixels

  function blob(c, x, y, r, rgba, a) {
    var g = c.createRadialGradient(x, y, 0, x, y, r);
    g.addColorStop(0, 'rgba(' + rgba + ',' + a + ')');
    g.addColorStop(0.45, 'rgba(' + rgba + ',' + (a * 0.45) + ')');
    g.addColorStop(1, 'rgba(' + rgba + ',0)');
    c.fillStyle = g;
    c.fillRect(x - r, y - r, r * 2, r * 2);
  }

  function paintNebula() {
    NW = Math.round(W * (1 + 2 * OV));
    NH = Math.round(H * (1 + 2 * OV));
    nebula.width = Math.max(1, Math.round(NW * DPR));
    nebula.height = Math.max(1, Math.round(NH * DPR));
    var c = nctx;
    c.setTransform(DPR, 0, 0, DPR, 0, 0);
    // Soft glows are stacked by the hundred; painting them small and scaling up keeps them perfectly
    // smooth (no gradient-dither stripes) and is much faster.
    var GS = 0.25;
    glowC.width = Math.max(1, Math.ceil(NW * GS));
    glowC.height = Math.max(1, Math.ceil(NH * GS));
    var gc = gctx;
    gc.setTransform(GS, 0, 0, GS, 0, 0);
    gc.clearRect(0, 0, NW, NH);
    var r = mulberry32(SEED + 7);
    var S = Math.min(NW, NH), L = Math.max(NW, NH);
    function gauss() { return (r() + r() + r() + r() - 2) / 2; }

    // 1. base: deep blue-black with a faint teal lift in the middle
    c.globalCompositeOperation = 'source-over';
    var g = c.createLinearGradient(0, 0, NW * 0.3, NH);
    g.addColorStop(0, '#02050b');
    g.addColorStop(0.5, '#030a0f');
    g.addColorStop(1, '#010306');
    c.fillStyle = g;
    c.fillRect(0, 0, NW, NH);

    // 2. Milky Way: a soft glowing band from lower left to upper right
    function band(t) {                     // quadratic curve, returns point + unit normal
      var x0 = -0.1 * NW, y0 = 1.0 * NH, cx = 0.42 * NW, cy = 0.42 * NH, x1 = 1.1 * NW, y1 = -0.05 * NH;
      var u = 1 - t;
      var x = u * u * x0 + 2 * u * t * cx + t * t * x1;
      var y = u * u * y0 + 2 * u * t * cy + t * t * y1;
      var dx = 2 * u * (cx - x0) + 2 * t * (x1 - cx), dy = 2 * u * (cy - y0) + 2 * t * (y1 - cy);
      var len = Math.hypot(dx, dy) || 1;
      return { x: x, y: y, nx: -dy / len, ny: dx / len };
    }
    gc.globalCompositeOperation = 'lighter';
    for (var i = 0; i < 230; i++) {
      var t = r(), p = band(t), off = gauss() * S * 0.06;
      var rad = S * (0.07 + r() * 0.16);
      var tint = r();
      var col = tint < 0.55 ? '170,196,255' : (tint < 0.85 ? '168,224,122' : '205,180,255');
      var core = 1 - Math.abs(t - 0.5) * 1.1;   // brighter towards the middle of the sky
      blob(gc, p.x + p.nx * off, p.y + p.ny * off, rad, col, (0.012 + r() * 0.02) * (0.6 + core));
    }
    // bright core of the band
    for (var j = 0; j < 60; j++) {
      var tc = 0.35 + r() * 0.35, pc = band(tc), oc = gauss() * S * 0.025;
      blob(gc, pc.x + pc.nx * oc, pc.y + pc.ny * oc, S * (0.04 + r() * 0.07), '225,235,255', 0.018 + r() * 0.02);
    }

    // 3. dark dust lanes along the band
    gc.globalCompositeOperation = 'source-over';
    for (var d = 0; d < 90; d++) {
      var td = 0.12 + r() * 0.8, pd = band(td), od = S * (0.006 + gauss() * 0.02);
      blob(gc, pd.x + pd.nx * od, pd.y + pd.ny * od, S * (0.02 + r() * 0.05), '2,4,8', 0.22 + r() * 0.25);
    }

    // 5. coloured nebula clouds (green upper right, blue left, violet lower middle)
    gc.globalCompositeOperation = 'lighter';
    [
      [0.82, 0.2, '168,224,122', 0.16, 46, 0.022],
      [0.86, 0.14, '120,220,200', 0.10, 18, 0.018],
      [0.12, 0.55, '92,148,230', 0.18, 40, 0.02],
      [0.6, 0.8, '150,110,230', 0.12, 26, 0.016]
    ].forEach(function (cl) {
      for (var n = 0; n < cl[4]; n++) {
        var bx = NW * cl[0] + gauss() * L * cl[3], by = NH * cl[1] + gauss() * L * cl[3] * 0.7;
        blob(gc, bx, by, L * (0.04 + r() * 0.12), cl[2], cl[5] * (0.4 + r()));
      }
    });
    gc.globalCompositeOperation = 'source-over';
    c.imageSmoothingEnabled = true;
    c.imageSmoothingQuality = 'high';
    c.filter = 'blur(6px)';                                  // melts away any gradient dither pattern
    c.drawImage(glowC, 0, 0, glowC.width, glowC.height, 0, 0, glowC.width / GS, glowC.height / GS);
    c.filter = 'none';

    // 4. star dust: thousands of faint stars, crowded inside the band
    c.globalCompositeOperation = 'source-over';
    for (var k = 0; k < 3200; k++) {
      var inBand = k < 2300, sx, sy;
      if (inBand) {
        var tb = r(), pb = band(tb), ob = gauss() * S * 0.11;
        sx = pb.x + pb.nx * ob; sy = pb.y + pb.ny * ob;
      } else { sx = r() * NW; sy = r() * NH; }
      var a = (inBand ? 0.08 : 0.05) + r() * (inBand ? 0.4 : 0.3);
      var tone = r() < 0.15 ? '214,232,255' : (r() < 0.08 ? '226,246,205' : '255,255,255');
      c.fillStyle = 'rgba(' + tone + ',' + a.toFixed(3) + ')';
      var sz = 0.25 + r() * 0.75;
      c.fillRect(sx, sy, sz, sz);
    }

    // 6. a distant spiral galaxy
    c.globalCompositeOperation = 'lighter';
    var gx = NW * 0.2, gy = NH * 0.2, gr = S * 0.05;
    c.save();
    c.translate(gx, gy);
    c.rotate(-0.45);
    c.scale(1, 0.38);
    blob(c, 0, 0, gr * 1.4, '200,215,255', 0.05);
    blob(c, 0, 0, gr * 0.35, '255,250,235', 0.35);
    for (var s = 0; s < 420; s++) {
      var arm = s % 2, th = r() * 4.2, rad2 = gr * 0.12 * Math.exp(0.42 * th);
      var ang = th + arm * Math.PI + gauss() * 0.25;
      c.fillStyle = 'rgba(210,225,255,' + (0.05 + r() * 0.18).toFixed(3) + ')';
      c.fillRect(Math.cos(ang) * rad2, Math.sin(ang) * rad2, 1.2, 1.2);
    }
    c.restore();

    // 7. the glowing limb of a planet rising from the lower-left corner
    c.globalCompositeOperation = 'source-over';
    var pr = Math.max(NH * 0.62, NW * 0.36), pcx = -pr * 0.18, pcy = NH + pr * 0.62;
    var atm = c.createRadialGradient(pcx, pcy, pr * 0.96, pcx, pcy, pr * 1.12);
    atm.addColorStop(0, 'rgba(168,224,122,0)');
    atm.addColorStop(0.28, 'rgba(150,215,170,0.16)');
    atm.addColorStop(0.45, 'rgba(110,190,220,0.08)');
    atm.addColorStop(1, 'rgba(92,148,210,0)');
    c.fillStyle = atm;
    c.beginPath(); c.arc(pcx, pcy, pr * 1.12, 0, Math.PI * 2); c.fill();
    var body = c.createRadialGradient(pcx + pr * 0.35, pcy - pr * 0.55, pr * 0.1, pcx, pcy, pr);
    body.addColorStop(0, '#0b1a1e');
    body.addColorStop(0.55, '#050c10');
    body.addColorStop(1, '#020508');
    c.fillStyle = body;
    c.beginPath(); c.arc(pcx, pcy, pr, 0, Math.PI * 2); c.fill();
    // sunlit rim, brightest where it faces the upper right
    c.lineWidth = 1.6;
    var rimG = c.createLinearGradient(pcx, pcy - pr, pcx + pr, pcy);
    rimG.addColorStop(0, 'rgba(210,245,190,0.75)');
    rimG.addColorStop(0.5, 'rgba(168,224,122,0.35)');
    rimG.addColorStop(1, 'rgba(168,224,122,0)');
    c.strokeStyle = rimG;
    c.beginPath(); c.arc(pcx, pcy, pr - 0.8, -Math.PI / 2 - 0.05, -0.05); c.stroke();

    // 8. vignette keeps text readable at the edges
    var v = c.createRadialGradient(NW * 0.5, NH * 0.45, S * 0.25, NW * 0.5, NH * 0.5, L * 0.75);
    v.addColorStop(0, 'rgba(1,2,4,0)');
    v.addColorStop(1, 'rgba(1,2,4,0.55)');
    c.fillStyle = v;
    c.fillRect(0, 0, NW, NH);
    c.globalCompositeOperation = 'source-over';
  }

  function resize() {
    DPR = Math.min(window.devicePixelRatio || 1, 2);
    W = window.innerWidth;
    H = window.innerHeight;
    canvas.width = Math.round(W * DPR);
    canvas.height = Math.round(H * DPR);
    ctx.setTransform(DPR, 0, 0, DPR, 0, 0);
    visibleStars = Math.min(MAX_STARS, Math.round((W * H) / 2300));
    paintNebula();
    if (reduce || !running) draw(0);
  }

  function spawnMeteor(now) {
    var fromLeft = Math.random() < 0.5;
    var angle = fromLeft ? rand(0.18, 0.55) : Math.PI - rand(0.18, 0.55);
    var speed = rand(900, 1500);
    meteors.push({
      x: fromLeft ? rand(-0.05, 0.55) * W : rand(0.45, 1.05) * W,
      y: rand(-0.05, 0.35) * H,
      vx: Math.cos(angle) * speed, vy: Math.sin(angle) * speed,
      life: 0, max: rand(0.7, 1.15), len: rand(110, 220)
    });
    nextMeteor = now + rand(3500, 9000);
  }

  function burst(x, y) {
    for (var i = 0; i < 18; i++) {
      var a = Math.random() * Math.PI * 2;
      var s = rand(40, 190);
      sparks.push({ x: x, y: y, vx: Math.cos(a) * s, vy: Math.sin(a) * s, life: 0, max: rand(0.45, 0.9),
                    c: PALETTE[(Math.random() * PALETTE.length) | 0] });
    }
  }

  function draw(dt) {
    var now = performance.now();
    var T = clock() + boost;
    var k = Math.min(1, dt * 2.2);
    mouse.px += (mouse.tx - mouse.px) * k;
    mouse.py += (mouse.ty - mouse.py) * k;
    var scrollY = window.scrollY || window.pageYOffset || 0;
    skyScroll += (scrollY - skyScroll) * Math.min(1, dt * 3.5);
    if (reduce) skyScroll = scrollY;

    // backdrop drifts a little (it is far away): mouse parallax + a slow rise while scrolling
    var ox = W * OV, oy = H * OV;
    var bx = Math.max(-ox, Math.min(ox, -mouse.px * W * 0.012));
    var by = Math.max(-oy, Math.min(oy, -mouse.py * H * 0.012 - Math.min(oy * 0.9, skyScroll * 0.012)));
    ctx.globalCompositeOperation = 'source-over';
    ctx.drawImage(nebula, -ox + bx, -oy + by, NW, NH);

    ctx.globalCompositeOperation = 'lighter';
    var tw0 = clock();
    for (var i = 0; i < visibleStars; i++) {
      var s = stars[i];
      var fx = frac(s.x0 - (reduce ? 0 : T * 0.0035 * s.z));
      var fy = frac(s.y0 + (reduce ? 0 : T * 0.0012 * s.z));
      var x = fx * W + mouse.px * 26 * s.z;
      var y = ((fy * H - skyScroll * 0.12 * s.z) % H + H) % H + mouse.py * 18 * s.z;
      var tw = reduce ? 0.85 : 0.55 + 0.45 * Math.sin(tw0 * s.tw + s.ph);
      var alpha = s.a * tw;

      if (mouse.active && !reduce) {
        var mdx = x - mouse.x, mdy = y - mouse.y;
        var d2 = mdx * mdx + mdy * mdy;
        if (d2 < 19600) {
          var kk = 1 - Math.sqrt(d2) / 140;
          alpha = Math.min(1, alpha + kk * 0.9);
          x += mdx * kk * 0.18;
          y += mdy * kk * 0.18;
        }
      }

      var col = 'rgba(' + s.c[0] + ',' + s.c[1] + ',' + s.c[2] + ',';
      if (travel > 0.02) {
        // soft motion trail opposite to the drift direction while the sky surges forward
        var len = travel * travel * (6 + s.z * 34);
        var g = ctx.createLinearGradient(x, y, x + len * 0.94, y - len * 0.32);
        g.addColorStop(0, col + Math.min(1, alpha + travel * 0.25) + ')');
        g.addColorStop(1, col + '0)');
        ctx.strokeStyle = g;
        ctx.lineCap = 'round';
        ctx.lineWidth = s.r * 1.6;
        ctx.beginPath();
        ctx.moveTo(x, y);
        ctx.lineTo(x + len * 0.94, y - len * 0.32);
        ctx.stroke();
      } else {
        ctx.fillStyle = col + alpha + ')';
        ctx.beginPath();
        ctx.arc(x, y, s.r, 0, Math.PI * 2);
        ctx.fill();
        if (s.glint && alpha > 0.55) {
          var gl = s.r * 5 * (alpha - 0.45);
          ctx.strokeStyle = col + (alpha * 0.45) + ')';
          ctx.lineWidth = 0.6;
          ctx.beginPath();
          ctx.moveTo(x - gl, y); ctx.lineTo(x + gl, y);
          ctx.moveTo(x, y - gl); ctx.lineTo(x, y + gl);
          ctx.stroke();
        }
      }
    }

    if (!reduce) {
      if (now > nextMeteor && travel < 0.05) spawnMeteor(now);
      for (var m = meteors.length - 1; m >= 0; m--) {
        var mt = meteors[m];
        mt.life += dt; mt.x += mt.vx * dt; mt.y += mt.vy * dt;
        var p = mt.life / mt.max;
        if (p >= 1) { meteors.splice(m, 1); continue; }
        var fade = Math.sin(Math.PI * p);
        var sp = Math.hypot(mt.vx, mt.vy);
        var tx = mt.x - (mt.vx / sp) * mt.len, ty = mt.y - (mt.vy / sp) * mt.len;
        var grad = ctx.createLinearGradient(mt.x, mt.y, tx, ty);
        grad.addColorStop(0, 'rgba(255,255,255,' + (0.95 * fade) + ')');
        grad.addColorStop(0.25, 'rgba(200,240,170,' + (0.45 * fade) + ')');
        grad.addColorStop(1, 'rgba(168,224,122,0)');
        ctx.strokeStyle = grad;
        ctx.lineWidth = 1.6;
        ctx.beginPath(); ctx.moveTo(mt.x, mt.y); ctx.lineTo(tx, ty); ctx.stroke();
      }
      for (var q = sparks.length - 1; q >= 0; q--) {
        var sk = sparks[q];
        sk.life += dt;
        if (sk.life >= sk.max) { sparks.splice(q, 1); continue; }
        sk.vx *= 0.94; sk.vy *= 0.94; sk.x += sk.vx * dt; sk.y += sk.vy * dt;
        var fa = 1 - sk.life / sk.max;
        ctx.fillStyle = 'rgba(' + sk.c[0] + ',' + sk.c[1] + ',' + sk.c[2] + ',' + fa + ')';
        ctx.beginPath(); ctx.arc(sk.x, sk.y, 1.4 * fa + 0.3, 0, Math.PI * 2); ctx.fill();
      }
      if (mouse.active) {
        var halo = ctx.createRadialGradient(mouse.x, mouse.y, 0, mouse.x, mouse.y, 160);
        halo.addColorStop(0, 'rgba(168,224,122,0.07)');
        halo.addColorStop(1, 'rgba(168,224,122,0)');
        ctx.fillStyle = halo;
        ctx.fillRect(mouse.x - 160, mouse.y - 160, 320, 320);
      }
    }
    ctx.globalCompositeOperation = 'source-over';
  }

  function frame(now) {
    if (!running) return;
    var dt = Math.min(0.05, (now - (last || now)) / 1000);
    last = now;
    if (travel > 0) {
      boost += dt * travel * 55;              // the surge: the sky flies forward, then eases to rest
      travel = Math.max(0, travel - dt / 1.6);
    }
    draw(dt);
    requestAnimationFrame(frame);
  }
  function start() {
    if (running || reduce) return;
    running = true; last = 0;
    requestAnimationFrame(frame);
  }
  function stop() { running = false; }

  function saveSky() {
    writeSky({ at: Date.now(), boost: boost, scroll: skyScroll, mx: mouse.px, my: mouse.py });
  }

  // ======================================================================== page transitions
  // The content layers are named by CSS (html:active-view-transition ... in css/motion.css).
  // Here we only hand the sky over to the next page and start the gentle surge on arrival.
  window.addEventListener('pageswap', saveSky);
  window.addEventListener('pagehide', saveSky);
  function quiet(vt) {                       // an aborted transition rejects these promises; that is harmless
    var noop = function () {};
    if (vt.ready) vt.ready.catch(noop);
    if (vt.finished) vt.finished.catch(noop);
    if (vt.updateCallbackDone) vt.updateCallbackDone.catch(noop);
  }
  window.addEventListener('pageswap', function (e) { if (e.viewTransition) quiet(e.viewTransition); });
  window.addEventListener('pagereveal', function (e) {
    if (!e.viewTransition) return;
    quiet(e.viewTransition);
    if (reduce) { e.viewTransition.skipTransition(); return; }
    travel = 1;
  });

  function navigate(href) { window.location.href = href; }

  // ======================================================================== interactions
  function initReveal() {
    if (reduce || !('IntersectionObserver' in window)) return;
    var sel = '.card, .glass-card, .team-card, .dash-section, .stats-panel, .chart-box, .progress-card, ' +
              '.warn-card, .media-box, .vv-status-card, section:not(.hero)';
    var vh = window.innerHeight;
    var items = Array.prototype.filter.call(document.querySelectorAll(sel), function (el) {
      if (el.closest('.vv-modal, .vv-modal-overlay, .welcome-overlay, [hidden], nav, header, [data-own-reveal], .vv-story')) return false;
      var r = el.getBoundingClientRect();
      return r.top > vh * 0.92 && r.height > 0;
    });
    items = items.filter(function (el) {
      return !items.some(function (other) { return other !== el && other.contains(el); });
    });
    if (!items.length) return;
    var io = new IntersectionObserver(function (entries) {
      entries.forEach(function (en) {
        if (!en.isIntersecting) return;
        var el = en.target;
        el.classList.add('vv-in');
        io.unobserve(el);
        window.setTimeout(function () {
          el.classList.remove('vv-reveal', 'vv-in');
          el.style.transitionDelay = '';
        }, 1100);
      });
    }, { rootMargin: '0px 0px -8% 0px', threshold: 0.08 });
    items.forEach(function (el, i) {
      el.classList.add('vv-reveal');
      el.style.transitionDelay = ((i % 4) * 70) + 'ms';
      io.observe(el);
    });
  }

  function initSpotlight() {
    if (reduce || !window.matchMedia('(hover: hover)').matches) return;
    var sel = '.card, .glass-card, .team-card, .stats-panel, .progress-card, .vv-status-card, .hm-card, .hm-stat';
    document.addEventListener('pointermove', function (e) {
      var host = e.target && e.target.closest ? e.target.closest(sel) : null;
      if (!host || host.closest('.vv-modal, .vv-modal-overlay')) return;
      if (!host.classList.contains('vv-spot-host')) {
        if (window.getComputedStyle(host).position === 'static') host.style.position = 'relative';
        var spot = document.createElement('span');
        spot.className = 'vv-spot';
        spot.setAttribute('aria-hidden', 'true');
        host.insertBefore(spot, host.firstChild);
        host.classList.add('vv-spot-host');
      }
      var r = host.getBoundingClientRect();
      host.style.setProperty('--vv-mx', (e.clientX - r.left) + 'px');
      host.style.setProperty('--vv-my', (e.clientY - r.top) + 'px');
    }, { passive: true });
  }

  function initRipples() {
    if (reduce) return;
    var sel = 'button, .btn, a.btn, [role="button"]';
    var skip = '.circle, .profile, .vv-modal-close, .close-modal, [aria-haspopup], [data-no-ripple]';
    document.addEventListener('pointerdown', function (e) {
      var el = e.target && e.target.closest ? e.target.closest(sel) : null;
      if (!el || el.matches(skip) || el.disabled) return;
      var cs = window.getComputedStyle(el);
      if (cs.position !== 'static' && cs.position !== 'relative') return;
      var r = el.getBoundingClientRect();
      var size = Math.max(r.width, r.height) * 2.2;
      var dot = document.createElement('span');
      dot.className = 'vv-ripple';
      dot.style.width = dot.style.height = size + 'px';
      dot.style.left = (e.clientX - r.left - size / 2) + 'px';
      dot.style.top = (e.clientY - r.top - size / 2) + 'px';
      var oldPos = el.style.position, oldOverflow = el.style.overflow;
      if (cs.position === 'static') el.style.position = 'relative';
      el.style.overflow = 'hidden';
      el.appendChild(dot);
      window.setTimeout(function () {
        if (dot.parentNode) dot.parentNode.removeChild(dot);
        el.style.position = oldPos;
        el.style.overflow = oldOverflow;
      }, 680);
    }, { passive: true });

    document.addEventListener('click', function (e) {
      if (e.target !== document.body && e.target !== root && !e.target.matches('main, .vv-main, .wrap')) return;
      burst(e.clientX, e.clientY);
    });
  }

  // ======================================================================== boot
  function boot() {
    document.body.insertBefore(canvas, document.body.firstChild);
    resize();
    window.addEventListener('resize', resize);
    window.addEventListener('pointermove', function (e) {
      mouse.x = e.clientX; mouse.y = e.clientY; mouse.active = e.pointerType === 'mouse';
      mouse.tx = (e.clientX / Math.max(1, W)) - 0.5;
      mouse.ty = (e.clientY / Math.max(1, H)) - 0.5;
    }, { passive: true });
    document.addEventListener('pointerleave', function () { mouse.active = false; });
    document.addEventListener('visibilitychange', function () {
      if (document.hidden) stop(); else start();
    });
    if (mqReduce && mqReduce.addEventListener) {
      mqReduce.addEventListener('change', function (e) {
        reduce = e.matches;
        if (reduce) { stop(); travel = 0; resize(); } else { start(); }
      });
    }
    nextMeteor = performance.now() + rand(1500, 4000);
    start();
    initReveal();
    initSpotlight();
    initRipples();
  }

  window.VV_MOTION = { navigate: navigate, burst: function (x, y) { burst(x, y); } };

  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', boot);
  else boot();
})();
