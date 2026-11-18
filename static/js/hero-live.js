/* Home hero scene + crew vitals monitor (index.html only).

   SCENE: two real NASA photos of the same 1984 spacewalk (STS-41-B, public domain): a wide shot and a
   close-up, aligned in one "world" (the wide photo's 3200x3200 pixels). The photo layer is screen-blended
   over a copy of the site's animated sky, so the stars and the Milky Way run straight through the picture.
   A code-drawn solar system (Sun, Saturn, Jupiter, Mars, Moon) sits at different depths, a reticle tracks
   the astronaut, and holographic tags show the crew vitals pinned to the suit. js/home.js drives the camera
   (window.VV_HERO.setCamera) and the HUD (window.VV_HERO.setHud) while you scroll.

   MONITOR: the "Crew vitals monitor" section: sweeping ECG, heart rate, SpO2 ring, blood pressure, body
   temperature. It shows the signed-in astronaut's latest reading; otherwise a simulated demo feed that is
   labelled as such. The photo shows a real astronaut, so every reading on it is labelled as simulated. */
(function () {
  'use strict';

  var hero = document.querySelector('.hero');
  var scene = hero ? hero.querySelector('.hx-scene') : null;
  if (!hero || !scene) return;

  var reduce = !!(window.matchMedia && window.matchMedia('(prefers-reduced-motion: reduce)').matches);
  var WORLD = 3200;
  // the close-up, placed so its astronaut sits exactly on the wide shot's astronaut (measured from the photos)
  var CLOSE = { left: 1224.8, top: 1065.2, w: 645.1, h: 650.0 };
  var ASTRO = { x: 1565, y: 1258, x0: 1440, y0: 1110, x1: 1690, y1: 1402 };
  var PTS = {                                   // points on the astronaut / scene, in world pixels
    chest: [1586, 1241], helmet: [1657, 1192], hand: [1663, 1312], visor: [1655, 1197], earth: [1560, 1650]
  };

  var sky = scene.querySelector('.hx-sky'), skyCtx = sky.getContext('2d');
  var pl = scene.querySelector('.hx-planets'), plCtx = pl.getContext('2d');
  var world = scene.querySelector('.hx-world');
  var closeImg = scene.querySelector('.hx-close');
  var lines = scene.querySelector('.hx-lines');
  var hud = scene.querySelector('.hx-hud');
  closeImg.style.left = CLOSE.left + 'px'; closeImg.style.top = CLOSE.top + 'px';
  closeImg.style.width = CLOSE.w + 'px'; closeImg.style.height = CLOSE.h + 'px';

  var W = 0, H = 0, DPR = 1;

  // ------------------------------------------------------------------ vitals (shared by HUD + monitor)
  var vitals = { hr: 72, spo2: 98, sys: 117, dia: 76, temp: 36.8 };
  var shown = { hr: 72 };
  var demo = true;
  var status = { label: 'Normal', note: 'demo' };

  function $(id) { return document.getElementById(id); }
  function txt(id, v) { var n = $(id); if (n) n.textContent = v; }
  function fmtBp() { return isFinite(vitals.sys) ? Math.round(vitals.sys) + '/' + Math.round(vitals.dia) : '--/--'; }

  // ------------------------------------------------------------------ HUD elements
  var NS = 'http://www.w3.org/2000/svg';
  function svgEl(name, attrs, parent) {
    var n = document.createElementNS(NS, name);
    for (var k in attrs) n.setAttribute(k, attrs[k]);
    if (parent) parent.appendChild(n);
    return n;
  }
  var reticle = document.createElement('div');
  reticle.className = 'hx-reticle';
  reticle.innerHTML = '<span class="hx-reticle-ring"></span><i></i><i></i><i></i><i></i>' +
    '<div class="hx-reticle-label">Live tracking<span>EVA · <b>♥</b> <b id="hxRetHr">72</b> bpm · simulated</span></div>';
  hud.appendChild(reticle);

  var HEART = '<svg class="hx-heart" viewBox="0 0 24 24"><path fill="currentColor" d="M12 21s-7.5-4.6-9.6-9.3C.9 8.3 3 4.5 6.7 4.5c2 0 3.6 1.1 5.3 3 1.7-1.9 3.3-3 5.3-3 3.7 0 5.8 3.8 4.3 7.2C19.5 16.4 12 21 12 21z"/></svg>';
  var TAGS = [
    { group: 'vitals', anchor: 'chest', dx: 190, dy: 40,
      html: '<small>Heart rate</small><div class="hx-row">' + HEART + '<strong id="hxHr">72</strong><em>bpm</em></div><canvas id="hxEcg"></canvas>' },
    { group: 'vitals', anchor: 'helmet', dx: 170, dy: -150,
      html: '<small>Oxygen saturation</small><strong id="hxSpo2">98</strong><em>%</em><div class="hx-sub">vs. personal baseline</div>' },
    { group: 'vitals', anchor: 'hand', dx: 150, dy: 170,
      html: '<small>Blood pressure</small><strong id="hxBp">117/76</strong><em>mmHg</em>' },
    { group: 'check', anchor: 'visor', dx: 250, dy: -60,
      html: '<small>AI daily check</small><strong id="hxStatus">Normal</strong><div><span class="hx-chip" id="hxStatusNote">simulated demo feed</span></div>' +
            '<div class="hx-sub">Sleep · mood · alertness test</div>' },
    { group: 'link', anchor: 'earth', dx: 220, dy: -120,
      html: '<small>Ground link</small><strong>Flight surgeon</strong><div class="hx-sub">Alerts escalate to Earth · on-board AI works offline</div>' }
  ];
  TAGS.forEach(function (t) {
    t.el = document.createElement('div');
    t.el.className = 'hx-tag';
    t.el.innerHTML = t.html;
    hud.appendChild(t.el);
    t.line = svgEl('path', { fill: 'none', stroke: '#a8e07a', 'stroke-width': '1.3', opacity: '0' }, lines);
    t.dot = svgEl('circle', { r: '4', fill: '#a8e07a', opacity: '0' }, lines);
    t.halo = svgEl('circle', { r: '10', fill: 'none', stroke: '#a8e07a', 'stroke-width': '1', opacity: '0' }, lines);
  });
  var hudW = { reticle: 1, vitals: 0, check: 0, link: 0 };
  var hxEcg = $('hxEcg'), hxEcgCtx = hxEcg ? hxEcg.getContext('2d') : null, hxEcgHist = [];

  // ------------------------------------------------------------------ solar system sprites
  var PLANETS = [
    { name: 'sun', x: 2780, y: 330, r: 70, depth: 0.10 },
    { name: 'saturn', x: 2330, y: 1520, r: 44, depth: 0.28 },
    { name: 'jupiter', x: 640, y: 1980, r: 18, depth: 0.18 },
    { name: 'mars', x: 2240, y: 930, r: 10, depth: 0.22 },
    { name: 'moon', x: 2020, y: 1930, r: 24, depth: 0.42 }
  ];
  function sphere(c, r, base, dark, light, atmo) {
    var g = c.createRadialGradient(-r * 0.45, -r * 0.45, r * 0.1, 0, 0, r);
    g.addColorStop(0, light); g.addColorStop(0.55, base); g.addColorStop(1, dark);
    c.fillStyle = g; c.beginPath(); c.arc(0, 0, r, 0, Math.PI * 2); c.fill();
    var sh = c.createLinearGradient(-r, -r, r * 0.9, r * 0.9);       // night side, lit from the Sun (upper right)
    sh.addColorStop(0, 'rgba(0,0,0,0.75)'); sh.addColorStop(0.45, 'rgba(0,0,0,0.25)'); sh.addColorStop(0.7, 'rgba(0,0,0,0)');
    c.save(); c.scale(-1, 1); c.fillStyle = sh; c.beginPath(); c.arc(0, 0, r, 0, Math.PI * 2); c.fill(); c.restore();
    if (atmo) {
      var a = c.createRadialGradient(0, 0, r * 0.92, 0, 0, r * 1.25);
      a.addColorStop(0, atmo); a.addColorStop(1, 'rgba(0,0,0,0)');
      c.fillStyle = a; c.beginPath(); c.arc(0, 0, r * 1.25, 0, Math.PI * 2); c.fill();
    }
  }
  function makeSprite(p) {
    var size = Math.ceil(p.r * (p.name === 'saturn' ? 5.2 : p.name === 'sun' ? 9 : 3.2));
    var cv = document.createElement('canvas');
    cv.width = cv.height = size * 2;
    var c = cv.getContext('2d');
    c.translate(size, size);
    var r = p.r;
    if (p.name === 'sun') {
      var g = c.createRadialGradient(0, 0, 0, 0, 0, size);
      g.addColorStop(0, 'rgba(255,255,245,1)'); g.addColorStop(0.06, 'rgba(255,246,214,0.95)');
      g.addColorStop(0.16, 'rgba(255,214,150,0.35)'); g.addColorStop(0.45, 'rgba(255,190,120,0.08)'); g.addColorStop(1, 'rgba(255,190,120,0)');
      c.fillStyle = g; c.fillRect(-size, -size, size * 2, size * 2);
      c.globalCompositeOperation = 'lighter';
      for (var i = 0; i < 12; i++) {                                 // faint rays
        c.save(); c.rotate(i * Math.PI / 6 + 0.2);
        var rg = c.createLinearGradient(0, 0, size, 0);
        rg.addColorStop(0, 'rgba(255,240,210,0.22)'); rg.addColorStop(1, 'rgba(255,240,210,0)');
        c.fillStyle = rg; c.fillRect(0, -1.2, size, 2.4); c.restore();
      }
    } else if (p.name === 'saturn') {
      var ring = function (front) {
        c.save(); c.rotate(-0.38); c.scale(1, 0.3);
        for (var k = 0; k < 26; k++) {
          var rr = r * (1.35 + k * 0.045);
          c.strokeStyle = 'rgba(230,210,170,' + (k % 5 === 3 ? 0.08 : 0.26 + (k % 3) * 0.06) + ')';
          c.lineWidth = r * 0.04;
          c.beginPath(); c.arc(0, 0, rr, front ? 0 : Math.PI, front ? Math.PI : Math.PI * 2); c.stroke();
        }
        c.restore();
      };
      ring(false);
      sphere(c, r, '#c9a56a', '#2a1d0c', '#f3dfb0', 'rgba(240,215,160,0.18)');
      c.save(); c.beginPath(); c.arc(0, 0, r, 0, Math.PI * 2); c.clip();           // bands
      for (var b = -4; b <= 4; b++) { c.fillStyle = 'rgba(120,85,40,' + (0.08 + Math.abs(b % 2) * 0.06) + ')'; c.fillRect(-r, b * r * 0.2, r * 2, r * 0.09); }
      c.restore();
      ring(true);
    } else if (p.name === 'jupiter') {
      sphere(c, r, '#c79a6e', '#2b170b', '#f2d6b4', 'rgba(240,200,160,0.15)');
      c.save(); c.beginPath(); c.arc(0, 0, r, 0, Math.PI * 2); c.clip();
      for (var j = -5; j <= 5; j++) { c.fillStyle = 'rgba(110,60,30,' + (0.1 + (j % 2 ? 0.08 : 0)) + ')'; c.fillRect(-r, j * r * 0.18, r * 2, r * 0.08); }
      c.fillStyle = 'rgba(170,70,40,0.35)'; c.beginPath(); c.ellipse(r * 0.25, r * 0.3, r * 0.18, r * 0.1, 0, 0, Math.PI * 2); c.fill();
      c.restore();
    } else if (p.name === 'mars') {
      sphere(c, r, '#c2552d', '#2a0c04', '#f0a070', 'rgba(255,140,90,0.18)');
    } else {
      sphere(c, r, '#9a9a98', '#141414', '#e9e8e2', null);
      c.save(); c.beginPath(); c.arc(0, 0, r, 0, Math.PI * 2); c.clip();
      [[0.3, -0.2, 0.22], [-0.2, 0.3, 0.16], [0.1, 0.45, 0.1], [-0.35, -0.3, 0.12]].forEach(function (m) {
        c.fillStyle = 'rgba(40,40,40,0.25)'; c.beginPath(); c.arc(m[0] * r, m[1] * r, m[2] * r, 0, Math.PI * 2); c.fill();
      });
      c.restore();
    }
    p.sprite = cv; p.half = size;
  }
  PLANETS.forEach(makeSprite);

  // ------------------------------------------------------------------ camera
  var cam = { x: ASTRO.x, y: ASTRO.y, z: 1.1, ax: 0.66, ay: 0.36 };
  var camT = { x: ASTRO.x, y: ASTRO.y, z: 1.1, ax: 0.66, ay: 0.36 };
  var cs = { S: 1, tx: 0, ty: 0, k: 1 };                  // current world -> screen mapping

  function baseK() { return Math.max(W / WORLD, H / (WORLD * 9 / 16)); }
  function computeMapping(fx, fy) {
    var k = baseK(), S = k * cam.z;
    var tx = W * cam.ax - S * cam.x + fx, ty = H * cam.ay - S * cam.y + fy;
    ty = Math.max(H - WORLD * S, ty);                       // never show below the photo
    cs.S = S; cs.tx = tx; cs.ty = ty; cs.k = k;
  }
  function toScreen(p) { return [cs.tx + p[0] * cs.S, cs.ty + p[1] * cs.S]; }
  function smooth01(v) { v = Math.max(0, Math.min(1, v)); return v * v * (3 - 2 * v); }

  function sizeAll() {
    DPR = Math.min(window.devicePixelRatio || 1, 2);
    W = scene.clientWidth; H = scene.clientHeight;
    [sky, pl].forEach(function (cv) { cv.width = Math.round(W * DPR); cv.height = Math.round(H * DPR); });
    skyCtx.setTransform(DPR, 0, 0, DPR, 0, 0);
    plCtx.setTransform(DPR, 0, 0, DPR, 0, 0);
    lines.setAttribute('viewBox', '0 0 ' + W + ' ' + H);
    if (hxEcg) {
      var r = hxEcg.getBoundingClientRect();
      hxEcg.width = Math.max(1, Math.round((r.width || 150) * DPR)); hxEcg.height = Math.max(1, Math.round((r.height || 30) * DPR));
      hxEcgCtx.setTransform(DPR, 0, 0, DPR, 0, 0);
    }
  }

  function copySky() {
    var g = document.getElementById('vvStarfield');
    skyCtx.fillStyle = '#020407';
    skyCtx.fillRect(0, 0, W, H);
    if (!g || !g.width) return;
    var r = scene.getBoundingClientRect();
    var gd = g.width / Math.max(1, window.innerWidth);
    try {
      skyCtx.drawImage(g, Math.max(0, r.left * gd), Math.max(0, r.top * gd), r.width * gd, r.height * gd, 0, 0, W, H);
    } catch (e) {}
  }

  var closeOpen = 0;                                        // 0..1, how far the close-up's Earth is revealed
  var CLOSE_HORIZON = CLOSE.top + 0.545 * CLOSE.h;          // Earth's edge in the close-up, world y
  function drawPlanets(t) {
    plCtx.clearRect(0, 0, W, H);
    var k = cs.k;
    plCtx.save();
    if (closeOpen > 0.01) {                                  // planets are behind Earth: never draw below its horizon
      var hy = cs.ty + CLOSE_HORIZON * cs.S;
      plCtx.beginPath(); plCtx.rect(0, 0, W, Math.max(0, hy)); plCtx.clip();
    }
    PLANETS.forEach(function (p) {
      var zp = Math.pow(cam.z, p.depth);                     // far away: barely grows while we zoom
      var S = k * zp;
      var cx = W * cam.ax - S * cam.x, cy = H * cam.ay - S * cam.y;
      var x = cx + p.x * S, y = cy + p.y * S;
      var size = p.half * zp * Math.max(0.55, k / (1440 / WORLD));
      if (x + size < -50 || x - size > W + 50 || y + size < -50 || y - size > H + 50) return;
      plCtx.globalAlpha = p.name === 'sun' ? 0.95 : 0.92;
      plCtx.globalCompositeOperation = p.name === 'sun' ? 'lighter' : 'source-over';
      plCtx.drawImage(p.sprite, x - size, y - size, size * 2, size * 2);
      if (p.name === 'sun') {                                 // lens flare ghosts toward the screen centre
        plCtx.globalCompositeOperation = 'lighter';
        var vx = W / 2 - x, vy = H / 2 - y;
        [[0.35, 26, 'rgba(168,224,122,0.10)'], [0.6, 14, 'rgba(255,220,170,0.12)'], [0.85, 40, 'rgba(120,170,255,0.06)'], [1.15, 18, 'rgba(255,240,210,0.08)']]
          .forEach(function (f) {
            var gx = x + vx * f[0], gy = y + vy * f[0];
            var gg = plCtx.createRadialGradient(gx, gy, 0, gx, gy, f[1]);
            gg.addColorStop(0, f[2]); gg.addColorStop(1, 'rgba(0,0,0,0)');
            plCtx.fillStyle = gg; plCtx.beginPath(); plCtx.arc(gx, gy, f[1], 0, Math.PI * 2); plCtx.fill();
          });
        var pulse = 0.85 + 0.15 * Math.sin(t * 0.7);
        var core = plCtx.createRadialGradient(x, y, 0, x, y, size * 0.22 * pulse);
        core.addColorStop(0, 'rgba(255,255,250,0.5)'); core.addColorStop(1, 'rgba(255,255,250,0)');
        plCtx.fillStyle = core; plCtx.beginPath(); plCtx.arc(x, y, size * 0.22 * pulse, 0, Math.PI * 2); plCtx.fill();
      }
    });
    plCtx.globalAlpha = 1;
    plCtx.globalCompositeOperation = 'source-over';
    plCtx.restore();
  }

  function placeHud(t, pulse) {
    // reticle around the astronaut (fades as we get close)
    var a = toScreen([ASTRO.x0, ASTRO.y0]), b = toScreen([ASTRO.x1, ASTRO.y1]);
    var pad = 16, rw = b[0] - a[0] + pad * 2, rh = b[1] - a[1] + pad * 2;
    var rOp = hudW.reticle * (1 - smooth01((cam.z - 1.5) / 0.9));
    reticle.style.opacity = rOp.toFixed(3);
    reticle.style.width = rw.toFixed(1) + 'px'; reticle.style.height = rh.toFixed(1) + 'px';
    reticle.style.transform = 'translate(' + (a[0] - pad).toFixed(1) + 'px,' + (a[1] - pad).toFixed(1) + 'px)';

    TAGS.forEach(function (tg, i) {
      var w = hudW[tg.group] || 0;
      if (w < 0.01) {
        tg.el.style.opacity = '0'; tg.line.setAttribute('opacity', '0'); tg.dot.setAttribute('opacity', '0'); tg.halo.setAttribute('opacity', '0');
        return;
      }
      var p = toScreen(PTS[tg.anchor]);
      var bob = Math.sin(t * 1.1 + i) * 4;
      var tw = tg.el.offsetWidth || 190, th = tg.el.offsetHeight || 80;
      var x = Math.min(W - tw - 20, Math.max(16, p[0] + tg.dx)), y = Math.min(H - th - 30, Math.max(90, p[1] + tg.dy + bob));
      var slide = (1 - w) * 24;
      tg.el.style.opacity = w.toFixed(3);
      tg.el.style.transform = 'translate(' + (x + slide).toFixed(1) + 'px,' + y.toFixed(1) + 'px)';
      var ex = x + slide, ey = y + th / 2;
      var mx = p[0] + (ex - p[0]) * 0.55;
      tg.line.setAttribute('d', 'M' + p[0].toFixed(1) + ' ' + p[1].toFixed(1) + ' L' + mx.toFixed(1) + ' ' + ey.toFixed(1) + ' L' + ex.toFixed(1) + ' ' + ey.toFixed(1));
      tg.line.setAttribute('opacity', (w * 0.8).toFixed(3));
      tg.dot.setAttribute('cx', p[0].toFixed(1)); tg.dot.setAttribute('cy', p[1].toFixed(1));
      tg.dot.setAttribute('opacity', w.toFixed(3));
      tg.halo.setAttribute('cx', p[0].toFixed(1)); tg.halo.setAttribute('cy', p[1].toFixed(1));
      tg.halo.setAttribute('r', (8 + pulse * 8).toFixed(1));
      tg.halo.setAttribute('opacity', (w * (0.7 - pulse * 0.4)).toFixed(3));
    });
  }

  // ------------------------------------------------------------------ monitor section
  var monHr = $('vvTeleHr'), monHeart = document.querySelector('.hm-hr-heart'), ecgCanvas = $('vvTeleEcg');
  var monitor = document.querySelector('.hm-monitor');
  var ecgCtx = ecgCanvas ? ecgCanvas.getContext('2d') : null;

  function renderVitals() {
    txt('vvTeleSpo2', isFinite(vitals.spo2) ? Math.round(vitals.spo2) : '--');
    txt('vvTeleBp', fmtBp());
    txt('vvTeleTemp', isFinite(vitals.temp) ? vitals.temp.toFixed(1) : '--');
    txt('hxSpo2', isFinite(vitals.spo2) ? Math.round(vitals.spo2) : '--');
    txt('hxBp', fmtBp());
    txt('hxStatus', status.label);
    txt('hxStatusNote', status.note);
    var ring = $('vvSpo2Ring');
    if (ring && isFinite(vitals.spo2)) {
      var c = 2 * Math.PI * 40, f = Math.max(0, Math.min(1, (vitals.spo2 - 85) / 15));
      ring.style.strokeDasharray = c.toFixed(1);
      ring.style.strokeDashoffset = (c * (1 - f)).toFixed(1);
    }
    var bp = $('vvBpBar');
    if (bp && isFinite(vitals.sys)) {
      var lo = (vitals.dia - 40) / 140, hi = (vitals.sys - 40) / 140;
      bp.style.left = (lo * 100).toFixed(1) + '%';
      bp.style.width = Math.max(2, (hi - lo) * 100).toFixed(1) + '%';
    }
    var tm = $('vvTempMarker');
    if (tm && isFinite(vitals.temp)) tm.style.left = (Math.max(0, Math.min(1, (vitals.temp - 35) / 4)) * 100).toFixed(1) + '%';
  }
  function demoTick() {
    if (!demo) return;
    function walk(v, lo, hi, step) { return Math.min(hi, Math.max(lo, v + (Math.random() - 0.5) * step)); }
    vitals.hr = walk(vitals.hr, 66, 80, 3.2);
    vitals.spo2 = walk(vitals.spo2, 97, 99.4, 0.9);
    vitals.sys = walk(vitals.sys, 112, 122, 2.4);
    vitals.dia = walk(vitals.dia, 72, 80, 1.8);
    vitals.temp = walk(vitals.temp, 36.6, 36.95, 0.08);
    renderVitals();
  }
  renderVitals();

  function lastOf(series, key, ch) {
    try {
      var chans = series[key].channels;
      var c = ch ? chans.filter(function (x) { return x.key === ch; })[0] : chans[0];
      var vals = (c && c.values) || [];
      for (var i = vals.length - 1; i >= 0; i--) if (vals[i] != null) return Number(vals[i]);
    } catch (e) {}
    return NaN;
  }
  function loadRealReading() {
    if (!window.VV_SHELL || !window.VV_SHELL.getSession) return;
    window.VV_SHELL.getSession().then(function (sess) {
      if (!sess || !sess.authenticated || sess.role !== 'astronaut' || !sess.user || !sess.user.astronaut_id) return;
      return fetch('/api/health/' + encodeURIComponent(sess.user.astronaut_id) + '/dashboard', { credentials: 'same-origin' })
        .then(function (r) { return r.ok ? r.json() : null; })
        .then(function (d) {
          if (!d || !d.series) return;
          var hr = lastOf(d.series, 'hr');
          if (!isFinite(hr)) return;
          demo = false;
          vitals = { hr: hr, spo2: lastOf(d.series, 'spo2'), sys: lastOf(d.series, 'bp', 'sys'),
                     dia: lastOf(d.series, 'bp', 'dia'), temp: lastOf(d.series, 'temp') };
          shown.hr = hr;
          var day = d.astronaut && d.astronaut.missionDay;
          txt('vvTeleSource', 'Your latest reading' + (day ? ' · Mission day ' + day : ''));
          var latest = d.prediction && d.prediction.latest;
          if (latest && latest.status_label) {
            status = { label: latest.status_label, note: 'your data · day ' + (latest.mission_day || day || '') };
            var st = $('vvTeleStatus');
            if (st) {
              st.textContent = latest.status_label; st.hidden = false;
              var ui = String(latest.ui_status || '').toLowerCase();
              st.classList.toggle('is-watch', /monitor|warn|watch/.test(ui));
              st.classList.toggle('is-alert', /danger|alert|critical/.test(ui));
            }
          }
          renderVitals();
        });
    }).catch(function () {});
  }

  function beatPulse(ph) {
    return Math.exp(-Math.pow((ph - 0.22) / 0.035, 2)) + 0.55 * Math.exp(-Math.pow((ph - 0.38) / 0.045, 2));
  }
  function ecgWave(ph) {
    return 0.12 * Math.exp(-Math.pow((ph - 0.1) / 0.03, 2)) -
           0.15 * Math.exp(-Math.pow((ph - 0.2) / 0.008, 2)) +
           1.0 * Math.exp(-Math.pow((ph - 0.22) / 0.01, 2)) -
           0.28 * Math.exp(-Math.pow((ph - 0.245) / 0.01, 2)) +
           0.22 * Math.exp(-Math.pow((ph - 0.42) / 0.05, 2));
  }

  var ecgBuf = [], ecgHead = 0, ecgW = 0, ecgH = 0;
  function sizeEcg() {
    if (!ecgCanvas) return;
    var r = ecgCanvas.getBoundingClientRect();
    var d = Math.min(window.devicePixelRatio || 1, 2);
    ecgW = Math.max(1, Math.round(r.width)); ecgH = Math.max(1, Math.round(r.height));
    ecgCanvas.width = ecgW * d; ecgCanvas.height = ecgH * d;
    ecgCtx.setTransform(d, 0, 0, d, 0, 0);
    var old = ecgBuf; ecgBuf = new Array(ecgW);
    for (var i = 0; i < ecgW; i++) ecgBuf[i] = old.length ? old[Math.floor(i * old.length / ecgW)] : null;
    ecgHead = Math.min(ecgHead, ecgW - 1);
  }
  function drawEcg() {
    if (!ecgCtx || !ecgW) return;
    ecgCtx.clearRect(0, 0, ecgW, ecgH);
    var gap = 26, base = ecgH * 0.62, amp = ecgH * 0.5;
    ecgCtx.lineJoin = 'round'; ecgCtx.lineCap = 'round';
    ecgCtx.strokeStyle = '#a8e07a'; ecgCtx.shadowColor = 'rgba(168,224,122,0.8)'; ecgCtx.shadowBlur = 8; ecgCtx.lineWidth = 2;
    ecgCtx.beginPath();
    var pen = false;
    for (var x = 0; x < ecgW; x++) {
      var dist = (x - ecgHead + ecgW) % ecgW, v = ecgBuf[x];
      if (v == null || (dist > 0 && dist < gap)) { pen = false; continue; }
      var y = base - v * amp;
      if (!pen) { ecgCtx.moveTo(x, y); pen = true; } else ecgCtx.lineTo(x, y);
    }
    ecgCtx.stroke();
    ecgCtx.shadowBlur = 16;
    var hv = ecgBuf[ecgHead];
    if (hv != null) { ecgCtx.fillStyle = '#eaffdc'; ecgCtx.beginPath(); ecgCtx.arc(ecgHead, base - hv * amp, 2.6, 0, Math.PI * 2); ecgCtx.fill(); }
    ecgCtx.shadowBlur = 0;
  }
  function drawTagEcg() {
    if (!hxEcgCtx || (hudW.vitals || 0) < 0.01) return;
    var w = hxEcg.clientWidth || 150, h = hxEcg.clientHeight || 30;
    hxEcgCtx.clearRect(0, 0, w, h);
    hxEcgCtx.strokeStyle = '#a8e07a'; hxEcgCtx.lineWidth = 1.5; hxEcgCtx.shadowColor = 'rgba(168,224,122,0.8)'; hxEcgCtx.shadowBlur = 6;
    hxEcgCtx.beginPath();
    for (var i = 0; i < hxEcgHist.length; i++) {
      var x = (i / (hxEcgHist.length - 1)) * w, y = h * 0.7 - hxEcgHist[i] * h * 0.6;
      if (i === 0) hxEcgCtx.moveTo(x, y); else hxEcgCtx.lineTo(x, y);
    }
    hxEcgCtx.stroke(); hxEcgCtx.shadowBlur = 0;
  }

  // ------------------------------------------------------------------ loop
  var par = { x: 0, y: 0, tx: 0, ty: 0 };
  hero.addEventListener('pointermove', function (e) {
    var r = hero.getBoundingClientRect();
    par.tx = (e.clientX - r.left) / r.width - 0.5;
    par.ty = (e.clientY - r.top) / r.height - 0.5;
  }, { passive: true });
  hero.addEventListener('pointerleave', function () { par.tx = 0; par.ty = 0; });

  var beatPhase = 0, ecgSpeed = 120, ecgAcc = 0;
  var heroVisible = true, monVisible = false, last = 0, snap = true;

  function updateScene(t, dt, pulse) {
    var k = Math.min(1, dt * 2.5);
    par.x += (par.tx - par.x) * k; par.y += (par.ty - par.y) * k;
    var ck = snap || reduce ? 1 : Math.min(1, dt * 5);
    snap = false;
    var lzc = Math.log(cam.z), lzt = Math.log(camT.z);       // zoom eases in log space: constant-feeling speed
    cam.z = Math.exp(lzc + (lzt - lzc) * ck);
    cam.x += (camT.x - cam.x) * ck; cam.y += (camT.y - cam.y) * ck;
    cam.ax += (camT.ax - cam.ax) * ck; cam.ay += (camT.ay - cam.ay) * ck;
    var calm = reduce ? 0 : 1 / cam.z;                        // zero-g float, less when zoomed in
    computeMapping(-par.x * W * 0.018 * calm, (-par.y * 0.012 + Math.sin(t / 3.4) * 0.004) * H * calm);
    world.style.transform = 'translate(' + cs.tx.toFixed(2) + 'px,' + cs.ty.toFixed(2) + 'px) scale(' + cs.S.toFixed(5) + ')';
    var co = smooth01((cam.z - 2.3) / 1.3);
    closeImg.style.opacity = co.toFixed(3);
    var open = smooth01((cam.z - 4.4) / 0.6);              // the photo covers the screen from about z = 5
    closeOpen = open;
    closeImg.style.setProperty('--hx-rx', (72 + 160 * open).toFixed(1) + '%');
    closeImg.style.setProperty('--hx-ry', (64 + 160 * open).toFixed(1) + '%');
    closeImg.style.setProperty('--hx-b0', (47 + 80 * open).toFixed(1) + '%');
    closeImg.style.setProperty('--hx-b1', (54 + 80 * open).toFixed(1) + '%');
    closeImg.classList.toggle('is-full', open > 0.999);
    copySky();
    drawPlanets(t);
    placeHud(t, pulse);
    txt('hxRetHr', Math.round(shown.hr));
    var hrEl = $('hxHr'); if (hrEl) hrEl.textContent = Math.round(shown.hr);
    var hh = hud.querySelector('.hx-heart'); if (hh) hh.style.transform = 'scale(' + (1 + pulse * 0.22).toFixed(3) + ')';
    hxEcgHist.push(ecgWave(beatPhase));
    while (hxEcgHist.length > 90) hxEcgHist.shift();
    drawTagEcg();
  }

  function frame(now) {
    var dt = Math.min(0.05, (now - (last || now)) / 1000);
    last = now;
    if (document.hidden || (!heroVisible && !monVisible)) { requestAnimationFrame(frame); return; }
    var t = now / 1000;
    var bpm = Math.max(40, Math.min(160, vitals.hr || 72));
    shown.hr += (bpm - shown.hr) * Math.min(1, dt * 1.5);
    beatPhase = (beatPhase + dt * shown.hr / 60) % 1;
    var pulse = beatPulse(beatPhase);
    if (heroVisible) updateScene(t, dt, pulse);
    if (monVisible) {
      if (monHr) monHr.textContent = Math.round(shown.hr);
      if (monHeart) monHeart.style.transform = 'scale(' + (1 + pulse * 0.2).toFixed(3) + ')';
      ecgAcc += dt * ecgSpeed;
      var phStep = shown.hr / 60 / ecgSpeed, ph0 = beatPhase - ecgAcc * phStep;
      while (ecgAcc >= 1 && ecgW) {
        ecgAcc -= 1; ecgHead = (ecgHead + 1) % ecgW; ph0 += phStep;
        ecgBuf[ecgHead] = ecgWave(((ph0 % 1) + 1) % 1);
      }
      drawEcg();
    }
    requestAnimationFrame(frame);
  }

  function tickClock() {
    var d = new Date();
    var p = function (n) { return (n < 10 ? '0' : '') + n; };
    txt('vvTeleClock', p(d.getUTCHours()) + ':' + p(d.getUTCMinutes()) + ':' + p(d.getUTCSeconds()));
  }

  window.VV_HERO = {
    world: WORLD, astro: ASTRO, points: PTS, close: CLOSE,
    /* x, y: world point to look at; z: zoom (1 = whole scene); ax, ay: where that point sits on screen (0..1) */
    setCamera: function (x, y, z, ax, ay) {
      camT.x = x; camT.y = y; camT.z = Math.max(1, z);
      camT.ax = ax == null ? 0.5 : ax; camT.ay = ay == null ? 0.5 : ay;
    },
    setHud: function (w) { for (var key in w) hudW[key] = w[key]; },
    renderOnce: function () { updateScene(performance.now() / 1000, 1, 0); }
  };

  function boot() {
    sizeAll(); sizeEcg();
    window.addEventListener('resize', function () { sizeAll(); sizeEcg(); if (reduce) window.VV_HERO.renderOnce(); });
    tickClock();
    window.setInterval(tickClock, 1000);
    loadRealReading();
    if ('IntersectionObserver' in window) {
      new IntersectionObserver(function (en) { heroVisible = en[0].isIntersecting; }).observe(hero);
      if (monitor) new IntersectionObserver(function (en) { monVisible = en[0].isIntersecting; }).observe(monitor);
    } else { monVisible = true; }
    if (reduce) {
      if (monHr) monHr.textContent = Math.round(vitals.hr);
      // draw a still frame once the sky canvas exists
      window.setTimeout(function () { window.VV_HERO.renderOnce(); }, 120);
      if (ecgW) { for (var x = 0; x < ecgW; x++) ecgBuf[x] = ecgWave((x / 90) % 1); ecgHead = ecgW - 1; drawEcg(); }
      return;
    }
    window.setInterval(demoTick, 2600);
    requestAnimationFrame(frame);
  }
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', boot);
  else boot();
})();
