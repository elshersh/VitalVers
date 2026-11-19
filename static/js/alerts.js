/* Vitalverse Alerts Center (B2): role-filtered alert triage, doctor diagnostics + Chart.js 7d trend, live refresh & Web Push */
(function () {
  var S = window.VV_SHELL || {};
  var esc = S.esc || function (v) {
    return String(v == null ? '' : v).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;');
  };

  var state = {
    role: 'astronaut',
    astronautId: '',
    filter: 'all',
    items: [],
    unreadCount: 0,
    unackDangerCount: 0,
    expandedIds: {},
    charts: {}
  };

  var els = {
    sub: document.getElementById('alSub'),
    astroWrap: document.getElementById('alAstroWrap'),
    astroSelect: document.getElementById('alAstroSelect'),
    predictBtn: document.getElementById('alPredictBtn'),
    advanceBtn: document.getElementById('alAdvanceBtn'),
    pushBtn: document.getElementById('alPushBtn'),
    markAllBtn: document.getElementById('alMarkAllBtn'),
    notice: document.getElementById('alNotice'),
    filterPills: document.getElementById('alFilterPills'),
    summaryCount: document.getElementById('alSummaryCount'),
    list: document.getElementById('alList')
  };

  function getCsrfToken() {
    var sh = window.VV_SHELL || S;
    if (sh && sh.state && sh.state.csrfToken) return Promise.resolve(sh.state.csrfToken);
    if (sh && typeof sh.getSession === 'function') {
      return sh.getSession().then(function (sess) { return (sess && sess.csrf_token) || ''; });
    }
    return Promise.resolve('');
  }

  function showNotice(msg, kind) {
    if (!els.notice) return;
    if (!msg) {
      els.notice.hidden = true;
      return;
    }
    els.notice.hidden = false;
    els.notice.className = 'al-notice ' + (kind === 'err' ? 'al-notice--err' : 'al-notice--ok');
    els.notice.textContent = msg;
  }

  function apiFetch(url, opts) {
    opts = opts || {};
    var headers = Object.assign({}, opts.headers || {});
    var method = (opts.method || 'GET').toUpperCase();
    var prep = (method !== 'GET' && method !== 'HEAD')
      ? getCsrfToken().then(function (tok) { if (tok) headers['X-CSRF-Token'] = tok; })
      : Promise.resolve();
    return prep.then(function () {
      return fetch(url, Object.assign({ credentials: 'same-origin', headers: headers }, opts));
    }).then(function (r) {
      if (r.status === 401) {
        location.href = '/login.html?next=' + encodeURIComponent('/alerts.html');
        throw new Error('Unauthorized');
      }
      return r.json().catch(function () { return {}; }).then(function (data) {
        if (!r.ok) {
          throw new Error((data && data.detail) || ('Request failed (' + r.status + ')'));
        }
        return data;
      });
    });
  }

  function sevLabel(sev) {
    if (sev === 'danger') return 'Danger';
    if (sev === 'danger-confirm') return 'Danger Confirm';
    if (sev === 'warning') return 'Warning';
    return 'Info';
  }

  function sevBadgeClass(sev) {
    if (sev === 'danger' || sev === 'danger-confirm') return 'vv-badge--danger';
    if (sev === 'warning') return 'vv-badge--warn';
    return 'vv-badge--accent';
  }

  function cardClass(item) {
    var cls = 'al-card';
    if (!item.read_at) cls += ' al-card--unread';
    if (item.severity === 'danger' || item.severity === 'danger-confirm') cls += ' al-card--danger';
    else if (item.severity === 'warning') cls += ' al-card--warn';
    return cls;
  }

  function sourceBadgeClass(label) {
    var l = String(label || '').toLowerCase();
    if (l.indexOf('nasa') !== -1 || l.indexOf('physician') !== -1) return 'vv-source-badge--nasa';
    if (l.indexOf('reference') !== -1) return 'vv-source-badge--ref';
    if (l.indexOf('unverified') !== -1) return 'vv-source-badge--unverified';
    return 'vv-source-badge--placeholder';
  }

  function destroyCharts() {
    Object.keys(state.charts).forEach(function (k) {
      try { state.charts[k].destroy(); } catch (_) {}
      delete state.charts[k];
    });
  }

  function renderDoctorCharts() {
    if (state.role !== 'doctor' || typeof window.Chart !== 'function') return;
    state.items.forEach(function (item) {
      if (!state.expandedIds[item.id]) return;
      var det = item.detailed_explanation || {};
      var trend = Array.isArray(det.trend_7d) ? det.trend_7d : [];
      var canvas = document.getElementById('alChart-' + item.id);
      if (!canvas || !trend.length) return;

      var labels = trend.map(function (pt) { return 'Day ' + pt.day; });
      var hrData = trend.map(function (pt) { return pt.heart_rate != null ? Number(pt.heart_rate) : null; });
      var spo2Data = trend.map(function (pt) { return pt.blood_oxygen != null ? Number(pt.blood_oxygen) : null; });
      var stressData = trend.map(function (pt) { return pt.stress_index != null ? Number(pt.stress_index) : null; });

      state.charts[item.id] = new window.Chart(canvas.getContext('2d'), {
        type: 'line',
        data: {
          labels: labels,
          datasets: [
            { label: 'Heart Rate', data: hrData, borderColor: '#ff7a6b', tension: 0.3, pointRadius: 2 },
            { label: 'SpO2 %', data: spo2Data, borderColor: '#7be0ff', tension: 0.3, pointRadius: 2 },
            { label: 'Stress', data: stressData, borderColor: '#f6c177', tension: 0.3, pointRadius: 2 }
          ]
        },
        options: {
          responsive: true,
          maintainAspectRatio: false,
          plugins: { legend: { labels: { color: '#b4c0c4', boxWidth: 10, font: { size: 11 } } } },
          scales: {
            x: { ticks: { color: '#8f9ba0', font: { size: 10 } }, grid: { color: 'rgba(255,255,255,0.06)' } },
            y: { ticks: { color: '#8f9ba0', font: { size: 10 } }, grid: { color: 'rgba(255,255,255,0.06)' } }
          }
        }
      });
    });
  }

  function renderDoctorPanel(item) {
    var det = item.detailed_explanation || {};
    var probs = det.class_probabilities || {};
    var probEntries = Object.keys(probs).map(function (k) { return { name: k, val: Number(probs[k] || 0) }; });
    var vitals = Array.isArray(det.triggered_vitals) ? det.triggered_vitals : [];
    var cms = Array.isArray(det.countermeasures) ? det.countermeasures : [];
    var trend = Array.isArray(det.trend_7d) ? det.trend_7d : [];

    var probHtml = probEntries.length
      ? probEntries.map(function (p) {
          var pct = Math.max(0, Math.min(100, Math.round(p.val * 100)));
          return '<div class="al-prob-row"><span>' + esc(p.name.replace(/_/g, ' ')) + '</span><span class="al-prob-track"><span class="al-prob-fill" style="width:' + pct + '%"></span></span><strong>' + pct + '%</strong></div>';
        }).join('')
      : '<p style="margin:0;color:var(--muted);font-size:12.5px">' + esc(det.summary || 'Source event: ' + item.source) + '</p>';

    var vitalsHtml = vitals.length
      ? '<div class="al-vital-list">' + vitals.map(function (v) {
          var badge = v.source_badge || 'Reference value';
          return '<div class="al-vital-row"><div><strong>' + esc(v.indicator || v.column || 'Metric') + '</strong><div style="font-size:11.5px;color:var(--muted)">Value: ' + esc(v.value) + (v.unit ? ' ' + esc(v.unit) : '') + (v.baseline != null ? ' · Baseline: ' + esc(v.baseline) : '') + (v.z != null ? ' · z=' + esc(v.z) : '') + '</div></div><span class="vv-source-badge ' + sourceBadgeClass(badge) + '">' + esc(badge) + '</span></div>';
        }).join('') + '</div>'
      : '<p style="margin:0;color:var(--muted);font-size:12.5px">' + esc(det.recommended_action || 'Monitor latest trend on Health dashboard.') + '</p>';

    var cmHtml = cms.length
      ? '<ol class="al-cm-list">' + cms.map(function (c, idx) {
          var txt = typeof c === 'string' ? c : (c.title || c.recommendation || JSON.stringify(c));
          var isUrgent = idx === 0 && (item.severity === 'danger' || item.severity === 'danger-confirm') || txt.toLowerCase().indexOf('flight surgeon') !== -1;
          return '<li class="' + (isUrgent ? 'is-urgent' : '') + '">' + esc(txt) + '</li>';
        }).join('') + '</ol>'
      : '<p style="margin:0;color:var(--muted);font-size:12.5px">' + esc(det.recommended_action || 'Follow standard mission care protocol.') + '</p>';

    var chartHtml = trend.length
      ? '<div class="al-panel"><h3>7-Day Telemetry Context</h3><div class="al-chart-box"><canvas id="alChart-' + item.id + '"></canvas></div></div>'
      : '';

    return (
      '<div class="al-details">' +
        '<div class="al-panel"><h3>Model Confidence &amp; Class Probabilities</h3>' + probHtml + '</div>' +
        '<div class="al-panel"><h3>Triggered Indicators &amp; Provenance</h3>' + vitalsHtml + '</div>' +
        '<div class="al-panel"><h3>Prioritized Countermeasures</h3>' + cmHtml + '</div>' +
        chartHtml +
      '</div>'
    );
  }

  function renderList() {
    destroyCharts();
    var items = state.items;
    if (els.summaryCount) {
      els.summaryCount.textContent = items.length + ' shown · ' + state.unreadCount + ' unread · ' + state.unackDangerCount + ' unacknowledged danger';
    }
    if (!items.length) {
      els.list.innerHTML = '<div class="vv-empty">All clear. No alerts match the selected filter.</div>';
      return;
    }

    var isDoc = state.role === 'doctor';
    els.list.innerHTML = items.map(function (item) {
      var isDanger = item.severity === 'danger' || item.severity === 'danger-confirm';
      var det = item.detailed_explanation || {};
      var dashHref = '/health.html?astronaut=' + encodeURIComponent(item.astronaut_id) + (item.mission_day ? '&day=' + encodeURIComponent(item.mission_day) : '');
      var expanded = isDoc && !!state.expandedIds[item.id];
      var baseSev = sevLabel(item.severity);
      var dangerTier = (det.danger_tier && det.danger_tier.toLowerCase() !== baseSev.toLowerCase())
        ? ' · ' + esc(det.danger_tier)
        : '';
      var urgentBox = isDanger
        ? '<div class="al-urgent-box">Contact flight surgeon immediately · ' + esc(item.flight_surgeon || 'Flight Surgeon Desk') + '</div>'
        : (det.recommended_action ? '<p style="margin:8px 0 0;font-size:13px;color:#dbe4e7">' + esc(det.recommended_action) + '</p>' : '');

      var ackBtn = item.acknowledged_at
        ? '<span class="vv-badge">Acknowledged</span>'
        : '<button type="button" class="btn ghost sm" data-ack="' + item.id + '">Acknowledge</button>';

      var toggleBtn = isDoc
        ? '<button type="button" class="btn ghost sm" data-expand="' + item.id + '">' + (expanded ? 'Hide details' : 'Inspect diagnostics') + '</button>'
        : '';

      return (
        '<article class="' + cardClass(item) + '" data-alert-id="' + item.id + '">' +
          '<div class="al-top">' +
            '<div style="flex:1;min-width:240px">' +
              '<div class="al-badges">' +
                '<span class="vv-badge ' + sevBadgeClass(item.severity) + '">' + esc(baseSev) + dangerTier + '</span>' +
                '<span class="vv-badge">' + esc(item.astronaut_name || item.astronaut_id) + ' (' + esc(item.astronaut_id) + ')</span>' +
                (item.mission_day != null ? '<span class="vv-badge">Day ' + esc(item.mission_day) + '</span>' : '') +
                '<span class="vv-badge">' + esc(String(item.source || 'system').toUpperCase()) + '</span>' +
                (!item.read_at ? '<span class="vv-badge vv-badge--accent">Unread</span>' : '') +
              '</div>' +
              '<p class="al-msg">' + esc(item.short_message) + '</p>' +
              '<p class="al-meta">Logged ' + esc((item.created_at || '').replace('T', ' ').replace('+00:00', ' UTC')) + '</p>' +
            '</div>' +
            '<div class="al-card-btns">' +
              toggleBtn +
              '<a class="btn ghost sm" href="' + dashHref + '">Open dashboard</a>' +
              ackBtn +
            '</div>' +
          '</div>' +
          urgentBox +
          (expanded ? renderDoctorPanel(item) : '') +
        '</article>'
      );
    }).join('');

    renderDoctorCharts();
  }

  function loadAlerts() {
    var qs = 'limit=50';
    if (state.filter === 'unread') {
      qs += '&unread=true';
    } else if (state.filter !== 'all') {
      qs += '&severity=' + encodeURIComponent(state.filter);
    }
    return apiFetch('/api/alerts?' + qs).then(function (data) {
      state.role = data.role || state.role;
      state.items = Array.isArray(data.items) ? data.items : [];
      state.unreadCount = Number(data.unread_count || 0);
      state.unackDangerCount = Number(data.unack_danger_count || 0);
      if (state.role === 'doctor') {
        state.items.forEach(function (it, idx) {
          if (idx === 0 && !it.acknowledged_at && (it.severity === 'danger' || it.severity === 'danger-confirm')) {
            state.expandedIds[it.id] = true;
          }
        });
      }
      renderList();
      if (S.refreshSession) S.refreshSession();
    });
  }

  function initRoleAndAstronauts() {
    var sessionReq = S.getSession ? S.getSession() : apiFetch('/api/auth/me');
    return sessionReq.then(function (me) {
      if (!me || !me.authenticated || !me.user) {
        if (!me || me.backendAvailable !== false) {
          location.href = '/login.html?next=' + encodeURIComponent('/alerts.html');
        }
        return false;
      }
      state.role = me.user.role;
      state.astronautId = me.user.astronaut_id || '';
      if (state.role === 'doctor') {
        els.sub.textContent = 'Full doctor diagnostics: AI class probabilities, triggered indicator z-scores, 7-day trends, and countermeasure protocols.';
        return apiFetch('/api/doctor/astronauts').then(function (docData) {
          var rows = Array.isArray(docData.approved) ? docData.approved : (Array.isArray(docData.astronauts) ? docData.astronauts : []);
          if (rows.length && els.astroWrap && els.astroSelect) {
            els.astroWrap.hidden = false;
            els.astroSelect.innerHTML = rows.map(function (a) {
              var aid = a.astronaut_id || a.id;
              return '<option value="' + esc(aid) + '">' + esc(a.name) + ' (' + esc(aid) + ')</option>';
            }).join('');
            state.astronautId = els.astroSelect.value || rows[0].astronaut_id || rows[0].id;
            els.astroSelect.addEventListener('change', function () {
              state.astronautId = els.astroSelect.value;
            });
          } else {
            els.predictBtn.disabled = true;
            els.advanceBtn.disabled = true;
            showNotice('No approved astronauts are currently linked to your doctor account.', 'err');
          }
          return true;
        });
      } else {
        els.sub.textContent = 'Concise crew alert notices with immediate flight surgeon escalation when critical signs appear.';
        return true;
      }
    });
  }

  function urlBase64ToUint8Array(base64String) {
    var padding = '='.repeat((4 - (base64String.length % 4)) % 4);
    var base64 = (base64String + padding).replace(/-/g, '+').replace(/_/g, '/');
    var rawData = window.atob(base64);
    var out = new Uint8Array(rawData.length);
    for (var i = 0; i < rawData.length; i += 1) {
      out[i] = rawData.charCodeAt(i);
    }
    return out;
  }

  function enableBrowserPush() {
    if (!('serviceWorker' in navigator) || !('PushManager' in window)) {
      showNotice('Browser Push is not supported in this browser; live in-app SSE alerts remain active.', 'err');
      return;
    }
    var permPromise = ('Notification' in window) ? window.Notification.requestPermission() : Promise.resolve('granted');
    permPromise.then(function (perm) {
      if (perm !== 'granted') {
        showNotice('Notification permission was not granted (' + perm + ').', 'err');
        return;
      }
      return navigator.serviceWorker.register('/sw.js').then(function (reg) {
        return navigator.serviceWorker.ready.then(function () { return reg; });
      }).then(function (reg) {
        return apiFetch('/api/push/vapid-public-key').then(function (keyData) {
          return reg.pushManager.subscribe({
            userVisibleOnly: true,
            applicationServerKey: urlBase64ToUint8Array(keyData.public_key)
          });
        });
      }).then(function (sub) {
        return apiFetch('/api/push/subscribe', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(sub.toJSON())
        });
      }).then(function () {
        showNotice('Browser Push notifications enabled for this device.', 'ok');
      });
    }).catch(function (err) {
      showNotice(err.message || 'Could not enable Web Push notifications.', 'err');
    });
  }

  if (els.filterPills) {
    els.filterPills.addEventListener('click', function (e) {
      var btn = e.target.closest('button[data-filter]');
      if (!btn) return;
      state.filter = btn.getAttribute('data-filter') || 'all';
      els.filterPills.querySelectorAll('.pill-btn').forEach(function (b) {
        b.classList.toggle('active', b === btn);
      });
      loadAlerts();
    });
  }

  if (els.list) {
    els.list.addEventListener('click', function (e) {
      var expBtn = e.target.closest('button[data-expand]');
      if (expBtn) {
        var id = Number(expBtn.getAttribute('data-expand'));
        state.expandedIds[id] = !state.expandedIds[id];
        renderList();
        return;
      }
      var ackBtn = e.target.closest('button[data-ack]');
      if (ackBtn) {
        var ackId = Number(ackBtn.getAttribute('data-ack'));
        ackBtn.disabled = true;
        apiFetch('/api/alerts/' + ackId + '/acknowledge', { method: 'POST' })
          .then(function () {
            showNotice('Alert #' + ackId + ' acknowledged.', 'ok');
            return loadAlerts();
          })
          .catch(function (err) {
            ackBtn.disabled = false;
            showNotice(err.message || 'Failed to acknowledge alert.', 'err');
          });
      }
    });
  }

  if (els.markAllBtn) {
    els.markAllBtn.addEventListener('click', function () {
      apiFetch('/api/alerts/read-all', { method: 'POST' })
        .then(function (res) {
          showNotice('Marked ' + (res.marked || 0) + ' alert(s) as read.', 'ok');
          return loadAlerts();
        })
        .catch(function (err) { showNotice(err.message || 'Failed to mark alerts read.', 'err'); });
    });
  }

  var readyPromise = null;

  if (els.predictBtn) {
    els.predictBtn.addEventListener('click', function () {
      var run = function () {
        if (!state.astronautId) return Promise.resolve();
        els.predictBtn.disabled = true;
        return apiFetch('/api/predict/' + encodeURIComponent(state.astronautId), { method: 'POST' })
          .then(function (res) {
            showNotice('AI check for ' + state.astronautId + ' Day ' + res.mission_day + ': ' + res.status_label + (res.alert_created ? ' (new alert logged).' : '.'), 'ok');
            return loadAlerts();
          })
          .catch(function (err) { showNotice(err.message || 'Prediction check failed.', 'err'); })
          .finally(function () { els.predictBtn.disabled = false; });
      };
      if (!state.astronautId && readyPromise) {
        readyPromise.then(run);
      } else {
        run();
      }
    });
  }

  if (els.advanceBtn) {
    els.advanceBtn.addEventListener('click', function () {
      var run = function () {
        if (!state.astronautId) return Promise.resolve();
        els.advanceBtn.disabled = true;
        return apiFetch('/api/demo/advance?astronaut_id=' + encodeURIComponent(state.astronautId), { method: 'POST' })
          .then(function (res) {
            showNotice('Simulated DEMO Day ' + res.mission_day + ' appended for ' + state.astronautId + ' — Status: ' + res.status_label + '.', 'ok');
            return loadAlerts();
          })
          .catch(function (err) { showNotice(err.message || 'Demo advance failed.', 'err'); })
          .finally(function () { els.advanceBtn.disabled = false; });
      };
      if (!state.astronautId && readyPromise) {
        readyPromise.then(run);
      } else {
        run();
      }
    });
  }

  if (els.pushBtn) {
    els.pushBtn.addEventListener('click', enableBrowserPush);
  }

  window.addEventListener('vv:alert', function () {
    loadAlerts();
  });

  // ---- live updates (static/js/shell.js): alerts or a flight surgeon's approved astronauts changed ----
  function refreshDoctorAstronauts() {
    return apiFetch('/api/doctor/astronauts').then(function (docData) {
      if (!els.astroSelect || !els.astroWrap) return;
      var rows = Array.isArray(docData.approved) ? docData.approved : [];
      var ids = rows.map(function (a) { return a.astronaut_id || a.id; });
      if (rows.length) {
        els.astroWrap.hidden = false;
        els.astroSelect.innerHTML = rows.map(function (a) {
          var aid = a.astronaut_id || a.id;
          return '<option value="' + esc(aid) + '">' + esc(a.name) + ' (' + esc(aid) + ')</option>';
        }).join('');
        state.astronautId = ids.indexOf(state.astronautId) !== -1 ? state.astronautId : ids[0];
        els.astroSelect.value = state.astronautId;
        els.astroSelect.onchange = function () { state.astronautId = els.astroSelect.value; };
        els.predictBtn.disabled = false;
        els.advanceBtn.disabled = false;
        if (els.notice && /No approved astronauts/.test(els.notice.textContent || '')) showNotice('');
      } else {
        els.astroWrap.hidden = true;
        state.astronautId = '';
        els.predictBtn.disabled = true;
        els.advanceBtn.disabled = true;
        showNotice('No approved astronauts are currently linked to your doctor account.', 'err');
      }
    });
  }

  var liveRunning = false;
  var liveAgain = false;
  document.addEventListener('vv:changed', function onLiveChange(ev) {
    var parts = (ev && ev.detail && ev.detail.parts) || [];
    var wantCrew = state.role === 'doctor' && parts.indexOf('access') !== -1;
    if (!wantCrew && parts.indexOf('alerts') === -1 && parts.indexOf('health') === -1) return;
    if (liveRunning) { liveAgain = true; return; }
    liveRunning = true;
    (wantCrew ? refreshDoctorAstronauts() : Promise.resolve())
      .then(function () { return loadAlerts(); })
      .catch(function () {})
      .then(function () {
        liveRunning = false;
        if (liveAgain) { liveAgain = false; onLiveChange({ detail: { parts: ['access', 'alerts'] } }); }
      });
  });

  readyPromise = initRoleAndAstronauts().then(function (ok) {
    if (ok) return loadAlerts();
  });
})();
