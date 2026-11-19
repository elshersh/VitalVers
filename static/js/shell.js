/* Vitalverse shared navbar/footer/modal/security shell helper */
(function () {
  'use strict';

  function esc(str) {
    return String(str == null ? '' : str).replace(/[&<>"']/g, function (c) {
      return {
        '&': '&amp;',
        '<': '&lt;',
        '>': '&gt;',
        '"': '&quot;',
        "'": '&#39;'
      }[c];
    });
  }

  function safeUrl(url) {
    if (!url) return '';
    try {
      var u = new URL(String(url), window.location.origin);
      return (u.protocol === 'https:' || u.protocol === 'http:') ? u.href : '';
    } catch (e) {
      return '';
    }
  }

  var state = {
    authenticated: false,
    user: null,
    role: null,
    csrfToken: null,
    todoPercent: 0,
    unreadAlerts: 0,
    unackDanger: 0,
    alerts: []
  };

  function currentPage() {
    var path = (window.location.pathname || '/').split('/').pop() || 'index.html';
    return path.toLowerCase();
  }

  function initActiveMenu() {
    var page = currentPage();
    var map = {
      '': 'index.html',
      'index.html': 'index.html',
      'health.html': 'health.html',
      'astronaut-dashboard.html': 'health.html',
      'doctor-dashboard.html': 'health.html',
      'chatbot.html': 'chatbot.html',
      'mental.html': 'mental.html',
      'mental_astronaut.html': 'mental.html',
      'mental_doctor.html': 'mental.html',
      'about.html': 'about.html'
    };
    var target = map[page] || '';
    document.querySelectorAll('#vvNavMenu a').forEach(function (a) {
      var href = (a.getAttribute('href') || '').toLowerCase();
      if (target && href === target) {
        a.classList.add('active');
      } else {
        a.classList.remove('active');
      }
    });
  }

  function setTodoProgress(pct) {
    var ring = document.getElementById('vvTodoRing');
    var circle = document.getElementById('vvTodoRingArc');
    var clamped = Math.max(0, Math.min(100, Number(pct) || 0));
    state.todoPercent = clamped;
    if (!ring || !circle) return;
    if (clamped <= 0) {
      ring.setAttribute('hidden', '');
      return;
    }
    var r = 18;
    var c = 2 * Math.PI * r;
    circle.style.strokeDasharray = c.toFixed(2);
    circle.style.strokeDashoffset = (c * (1 - clamped / 100)).toFixed(2);
    ring.removeAttribute('hidden');
  }

  function updateBell(unread, unackDanger) {
    var dot = document.getElementById('vvBellDot');
    state.unreadAlerts = Number(unread) || 0;
    state.unackDanger = Number(unackDanger) || 0;
    if (!dot) return;
    if (state.unreadAlerts <= 0 && state.unackDanger <= 0) {
      dot.setAttribute('hidden', '');
      dot.classList.remove('is-danger');
      return;
    }
    dot.removeAttribute('hidden');
    if (state.unackDanger > 0) {
      dot.classList.add('is-danger');
    } else {
      dot.classList.remove('is-danger');
    }
  }

  function ensureSubpageWelcomeModal() {
    var existing = document.getElementById('welcomeOverlay') || document.getElementById('vvWelcomeOverlay');
    if (existing) return existing;

    var wrap = document.createElement('div');
    wrap.id = 'vvWelcomeOverlay';
    wrap.className = 'vv-modal-overlay';
    wrap.setAttribute('role', 'dialog');
    wrap.setAttribute('aria-modal', 'true');
    wrap.setAttribute('aria-labelledby', 'vvWelcomeTitle');
    wrap.innerHTML =
      '<div class="vv-modal">' +
        '<button class="vv-modal-close" type="button" aria-label="Close modal">&times;</button>' +
        '<h2 id="vvWelcomeTitle">Welcome to <span>Vitalverse</span></h2>' +
        '<p>Sign in with your astronaut or flight-surgeon account, or create a new mission profile.</p>' +
        '<div class="vv-modal-actions">' +
          '<a class="vv-modal-primary" href="signup.html">Create an Account</a>' +
          '<a class="vv-modal-secondary" href="login.html">Log In</a>' +
        '</div>' +
      '</div>';
    document.body.appendChild(wrap);

    var closeBtn = wrap.querySelector('.vv-modal-close');
    if (closeBtn) {
      closeBtn.addEventListener('click', function () {
        wrap.classList.remove('show');
      });
    }
    wrap.addEventListener('click', function (e) {
      if (e.target === wrap) wrap.classList.remove('show');
    });
    return wrap;
  }

  function openWelcomeModal() {
    var modal = ensureSubpageWelcomeModal();
    if (modal) modal.classList.add('show');
  }

  function closeAllMenus() {
    document.querySelectorAll('.vv-dropdown').forEach(function (d) {
      d.setAttribute('hidden', '');
    });
    var profBtn = document.getElementById('profileBtn');
    var bellBtn = document.getElementById('bellBtn');
    if (profBtn) profBtn.setAttribute('aria-expanded', 'false');
    if (bellBtn) bellBtn.setAttribute('aria-expanded', 'false');
  }

  function wireControls() {
    var todoBtn = document.getElementById('todoBtn');
    if (todoBtn && todoBtn.tagName !== 'A') {
      todoBtn.addEventListener('click', function () {
        window.location.href = 'todo.html';
      });
    }

    var bellBtn = document.getElementById('bellBtn');
    var bellDrop = document.getElementById('vvBellDropdown');
    if (bellBtn) {
      bellBtn.addEventListener('click', function (e) {
        e.stopPropagation();
        if (!state.authenticated || !bellDrop) {
          closeAllMenus();
          openWelcomeModal();
          return;
        }
        var isOpen = !bellDrop.hasAttribute('hidden');
        closeAllMenus();
        if (!isOpen) {
          bellDrop.removeAttribute('hidden');
          bellBtn.setAttribute('aria-expanded', 'true');
          refreshBellDropdown();
        }
      });
    }

    var profileBtn = document.getElementById('profileBtn');
    var profDrop = document.getElementById('vvProfileDropdown');
    if (profileBtn) {
      profileBtn.addEventListener('click', function (e) {
        e.stopPropagation();
        if (!state.authenticated || !profDrop) {
          closeAllMenus();
          openWelcomeModal();
          return;
        }
        var isOpen = !profDrop.hasAttribute('hidden');
        closeAllMenus();
        if (!isOpen) {
          profDrop.removeAttribute('hidden');
          profileBtn.setAttribute('aria-expanded', 'true');
        }
      });
    }

    var homeOverlay = document.getElementById('welcomeOverlay');
    if (homeOverlay) {
      ['closeModal', 'closeWelcome'].forEach(function (cid) {
        var closeHome = document.getElementById(cid);
        if (closeHome) {
          closeHome.addEventListener('click', function () {
            homeOverlay.classList.remove('show');
          });
        }
      });
      homeOverlay.addEventListener('click', function (e) {
        if (e.target === homeOverlay) homeOverlay.classList.remove('show');
      });
    }

    var launchBtn = document.getElementById('launchMissionBtn');
    if (launchBtn) {
      launchBtn.addEventListener('click', function (e) {
        e.preventDefault();
        window.location.href = state.authenticated ? accountPageUrl('/health.html') : 'login.html';
      });
    }

    document.addEventListener('click', function (e) {
      if (!e.target.closest || !e.target.closest('.tools')) {
        closeAllMenus();
      }
    });

    document.addEventListener('keydown', function (e) {
      if (e.key === 'Escape') {
        closeAllMenus();
        var ov1 = document.getElementById('welcomeOverlay');
        var ov2 = document.getElementById('vvWelcomeOverlay');
        if (ov1) ov1.classList.remove('show');
        if (ov2) ov2.classList.remove('show');
      }
    });
  }

  function toast(title, message, severity, href) {
    var stack = document.getElementById('vvToastStack');
    if (!stack) {
      stack = document.createElement('div');
      stack.id = 'vvToastStack';
      stack.className = 'vv-toast-stack';
      document.body.appendChild(stack);
    }
    var sev = String(severity || 'info').toLowerCase();
    var cls = 'vv-toast';
    if (sev === 'danger' || sev === 'danger-confirm') cls += ' vv-toast--danger';
    else if (sev === 'warning') cls += ' vv-toast--warn';

    var el = document.createElement('div');
    el.className = cls;
    el.innerHTML =
      '<div style="flex:1;min-width:0">' +
        '<p class="vv-toast-title">' + esc(title || 'Notice') + '</p>' +
        '<a class="vv-toast-body" href="' + esc(href || '/alerts.html') + '">' + esc(message || '') + '</a>' +
      '</div>' +
      '<button type="button" class="vv-toast-close" aria-label="Dismiss">&times;</button>';

    var closeBtn = el.querySelector('.vv-toast-close');
    if (closeBtn) {
      closeBtn.addEventListener('click', function () {
        if (el.parentNode) el.parentNode.removeChild(el);
      });
    }
    stack.appendChild(el);
    while (stack.children.length > 4) {
      stack.removeChild(stack.firstChild);
    }
    window.setTimeout(function () {
      if (el.parentNode) el.parentNode.removeChild(el);
    }, 6500);
  }

  function renderBanner(unackDanger, latestDanger) {
    var existing = document.getElementById('vvDangerBanner');
    var count = Number(unackDanger) || 0;
    if (!state.authenticated || count <= 0) {
      if (existing && existing.parentNode) existing.parentNode.removeChild(existing);
      return;
    }
    if (!existing) {
      var nav = document.querySelector('header.vv-nav');
      if (!nav || !nav.parentNode) return;
      existing = document.createElement('div');
      existing.id = 'vvDangerBanner';
      existing.className = 'vv-banner';
      nav.parentNode.insertBefore(existing, nav.nextSibling);
    }
    var detail = latestDanger && latestDanger.short_message
      ? latestDanger.short_message
      : (count + ' unacknowledged medical danger alert(s). Contact your flight surgeon immediately.');
    existing.innerHTML =
      '<span><strong>MEDICAL DANGER:</strong> ' + esc(detail) + '</span>' +
      '<a href="/alerts.html">Review in Alerts Center</a>';
  }

  function refreshBellDropdown(announce) {
    if (!state.authenticated) return Promise.resolve();
    var bellDrop = document.getElementById('vvBellDropdown');
    var bellList = document.getElementById('vvBellList');
    return fetch('/api/alerts?limit=6', { credentials: 'same-origin' })
      .then(function (res) {
        if (!res.ok) return null;
        return res.json();
      })
      .then(function (data) {
        if (!data) return;
        updateBell(data.unread_count || 0, data.unack_danger_count || 0);
        var items = Array.isArray(data.items) ? data.items : [];
        announceNewAlerts(items, announce);
        var unackDangerItem = null;
        for (var i = 0; i < items.length; i += 1) {
          if (!items[i].acknowledged_at && (items[i].severity === 'danger' || items[i].severity === 'danger-confirm')) {
            unackDangerItem = items[i];
            break;
          }
        }
        renderBanner(data.unack_danger_count || 0, unackDangerItem);

        if (bellDrop) {
          var head = bellDrop.querySelector('.vv-dropdown-head');
          if (head) {
            head.innerHTML =
              '<strong>Alerts (' + Number(data.unread_count || 0) + ' unread)</strong>' +
              '<span class="vv-dropdown-actions">' +
                '<button type="button" class="vv-dropdown-btn" id="vvBellMarkAllBtn">Mark all read</button>' +
                '<a class="vv-dropdown-link" href="/alerts.html">View all</a>' +
              '</span>';
            var markBtn = document.getElementById('vvBellMarkAllBtn');
            if (markBtn) {
              markBtn.addEventListener('click', function (ev) {
                ev.stopPropagation();
                var headers = {};
                if (state.csrfToken) headers['X-CSRF-Token'] = state.csrfToken;
                fetch('/api/alerts/read-all', {
                  method: 'POST',
                  headers: headers,
                  credentials: 'same-origin'
                }).then(function () {
                  refreshBellDropdown();
                  window.dispatchEvent(new CustomEvent('vv:alert', { detail: { refreshed: true } }));
                });
              });
            }
          }
        }

        if (bellList) {
          if (!items.length) {
            bellList.innerHTML = '<div class="vv-dropdown-empty">All clear. No alerts.</div>';
          } else {
            bellList.innerHTML = items.map(function (it) {
              var mod = (it.severity === 'danger' || it.severity === 'danger-confirm')
                ? ' vv-dropdown-item--danger'
                : (it.severity === 'warning' ? ' vv-dropdown-item--warn' : '');
              return (
                '<a class="vv-dropdown-item' + mod + '" href="/alerts.html" style="display:block;text-decoration:none">' +
                  '<strong>' + esc(String(it.severity || 'info').toUpperCase()) + (it.mission_day != null ? ' · Day ' + esc(it.mission_day) : '') + '</strong>' +
                  '<small>' + esc(it.short_message || '') + '</small>' +
                '</a>'
              );
            }).join('');
          }
        }
      })
      .catch(function () {});
  }

  function accountPageUrl(href) {
    return (window.VV_ACCOUNT && window.VV_ACCOUNT.pageUrl) ? window.VV_ACCOUNT.pageUrl(href) : href;
  }

  /* ---- live updates: open pages refresh when data they show changes (another tab, account or device) ---- */
  var LIVE_VISIBLE_MS = 4000;
  var LIVE_HIDDEN_MS = 20000;
  var live = { started: false, parts: null, timer: null, busy: false, again: false, lastAlertId: null };

  function announceNewAlerts(items, announce) {
    var maxId = 0;
    items.forEach(function (it) { maxId = Math.max(maxId, Number(it.id) || 0); });
    if (announce && live.lastAlertId != null) {
      items.filter(function (it) {
        // access requests are for the astronaut to decide; flight surgeons are not notified of them
        return (Number(it.id) || 0) > live.lastAlertId && !(state.role === 'doctor' && it.source === 'access');
      }).slice(0, 2).forEach(function (it) {
        toast(String(it.severity || 'new').toUpperCase() + ' ALERT', it.short_message || 'New mission health alert received.', it.severity || 'info');
      });
    }
    if (live.lastAlertId == null || maxId > live.lastAlertId) live.lastAlertId = maxId;
  }

  function refreshShellCounters() {
    return fetch('/api/auth/me', { credentials: 'same-origin' })
      .then(function (res) { return res.ok ? res.json() : null; })
      .then(function (data) {
        if (!data || !data.authenticated) return;
        state.csrfToken = data.csrf_token || state.csrfToken;
        setTodoProgress(data.todo_percent || 0);
        updateBell(data.unread_alert_count || 0, data.unack_danger_count || 0);
        renderProfileMenu(data);
      })
      .catch(function () {});
  }

  function scheduleLive(ms) {
    if (!live.started) return;
    if (live.timer) window.clearTimeout(live.timer);
    live.timer = window.setTimeout(checkLive, ms != null ? ms : (document.hidden ? LIVE_HIDDEN_MS : LIVE_VISIBLE_MS));
  }

  function signedOutElsewhere() {
    live.started = false;
    toast('SIGNED OUT', 'This tab\'s account was signed out (in another tab, or the session ended).', 'warning', '/login.html');
    window.setTimeout(function () { window.location.reload(); }, 1800);
  }

  function liveChanged(changed) {
    refreshShellCounters();
    // alerts that only became visible because access changed are not new: list them, do not pop them up
    if (changed.indexOf('alerts') !== -1) refreshBellDropdown(changed.indexOf('access') === -1);
    var ownChange = window.VV_ACCOUNT && (Date.now() - window.VV_ACCOUNT.lastWriteAt()) < 6000;
    if (changed.indexOf('access') !== -1 && state.role === 'doctor' && !ownChange) {
      toast('ACCESS UPDATED', 'Your astronaut access changed. This page now shows the latest list.', 'info', '/profile.html');
    }
    document.dispatchEvent(new CustomEvent('vv:changed', { detail: { parts: changed } }));
  }

  function checkLive() {
    live.timer = null;
    if (!live.started) return;
    if (live.busy) { live.again = true; return; }
    live.busy = true;
    fetch('/api/live', { credentials: 'same-origin' })
      .then(function (res) { return res.ok ? res.json() : null; })
      .then(function (data) {
        if (!data || !live.started) return;
        if (!data.authenticated) { signedOutElsewhere(); return; }
        var prev = live.parts;
        live.parts = data.parts || {};
        if (!prev) return;
        var changed = Object.keys(live.parts).filter(function (k) { return prev[k] !== live.parts[k]; });
        if (changed.length) liveChanged(changed);
      })
      .catch(function () {})
      .then(function () {
        live.busy = false;
        if (live.again) { live.again = false; scheduleLive(250); } else { scheduleLive(); }
      });
  }

  function startLiveUpdates() {
    if (live.started || !state.authenticated || window.location.protocol === 'file:') return;
    live.started = true;
    var channel = window.VV_ACCOUNT && window.VV_ACCOUNT.channel;
    if (channel) {
      // another tab of this browser changed something: check now instead of waiting
      channel.addEventListener('message', function () { scheduleLive(150); });
    }
    document.addEventListener('visibilitychange', function () {
      if (!document.hidden) scheduleLive(100);
    });
    checkLive();
  }

  function renderProfileMenu(data) {
    var avatar = document.getElementById('vvAvatar');
    var profDrop = document.getElementById('vvProfileDropdown');
    var u = (data && data.user) || {};
    if (avatar) {
      var avUrl = safeUrl(u.avatar_url || '');
      if (avUrl) {
        avatar.innerHTML = '<img src="' + esc(avUrl) + '" alt="' + esc(u.name || 'Avatar') + '" />';
        var img = avatar.querySelector('img');
        if (img) {
          var fallbackToGradient = function () {
            avatar.textContent = u.initials || '';
          };
          img.addEventListener('error', fallbackToGradient);
          if (img.complete && img.naturalWidth === 0) {
            fallbackToGradient();
          }
        }
      } else {
        avatar.textContent = u.initials || '';
      }
    }
    if (!profDrop) return;

    var roleLabel = data.role === 'doctor' ? 'Doctor / Flight Surgeon' : 'Astronaut';
    var subMeta = u.astronaut_id ? esc(u.vitalverse_id + ' · ' + u.astronaut_id) : esc(u.vitalverse_id || '');
    var pendingCount = Number(data.pending_access_count || data.pending_access_requests || 0);
    var roleItems = data.role === 'doctor'
      ? '<a class="vv-profile-item" href="/doctor-dashboard.html">My astronauts</a>'
      : '<a class="vv-profile-item" href="/profile.html#access">Access requests' + (pendingCount > 0 ? '<span class="vv-count-pill">' + pendingCount + '</span>' : '') + '</a>';

    profDrop.innerHTML =
      '<div class="vv-dropdown-head" style="flex-direction:column;align-items:flex-start;gap:4px;">' +
        '<strong>' + esc(u.name || u.vitalverse_id || 'Crew Member') + '</strong>' +
        '<span style="font-size:11px;color:#a8e07a;font-weight:600;">' + subMeta + '</span>' +
        '<span style="font-size:11px;color:#9ba5ab;">' + esc(roleLabel) + '</span>' +
      '</div>' +
      '<a class="vv-profile-item" href="/profile.html">My profile</a>' +
      roleItems +
      '<a class="vv-profile-item" href="/health.html">Health dashboard</a>' +
      '<a class="vv-profile-item" href="/chatbot.html">Ai chatbot</a>' +
      '<a class="vv-profile-item" href="/mental.html">Mental Health</a>' +
      '<a class="vv-profile-item" href="/todo.html">Daily Routine</a>' +
      '<a class="vv-profile-item" href="/alerts.html">Alerts Center</a>' +
      '<a class="vv-profile-item" href="/login.html" title="Other tabs keep their own accounts">Use another account in this tab</a>' +
      '<button type="button" class="vv-profile-item vv-profile-item--danger" id="vvLogoutBtn">Log out</button>';

    var logoutBtn = document.getElementById('vvLogoutBtn');
    if (logoutBtn) {
      logoutBtn.addEventListener('click', function () {
        live.started = false;
        var headers = {};
        if (state.csrfToken) headers['X-CSRF-Token'] = state.csrfToken;
        fetch('/api/auth/logout', {
          method: 'POST',
          headers: headers,
          credentials: 'same-origin'
        }).finally(function () {
          state.authenticated = false;
          state.user = null;
          state.role = null;
          state.csrfToken = null;
          window.location.href = '/login.html';
        });
      });
    }
  }

  var _sessionPromise = null;

  function hydrateSessionIfAvailable(forceRefresh) {
    if (window.location.protocol === 'file:' || typeof window.fetch !== 'function') {
      return Promise.resolve({ authenticated: false, backendAvailable: false });
    }
    if (forceRefresh) {
      _sessionPromise = null;
    }
    if (_sessionPromise) return _sessionPromise;

    _sessionPromise = fetch('/api/auth/me', { credentials: 'same-origin' })
      .then(function (res) {
        if (!res.ok) {
          return {
            authenticated: false,
            backendAvailable: res.status !== 404 && res.status !== 501
          };
        }
        return res.json().then(function (parsed) {
          if (parsed && typeof parsed === 'object') {
            parsed.backendAvailable = true;
          }
          return parsed;
        });
      })
      .then(function (data) {
        if (data && data.authenticated) {
          state.authenticated = true;
          state.user = data.user || null;
          state.role = data.role || null;
          state.csrfToken = data.csrf_token || null;
          setTodoProgress(data.todo_percent || 0);
          updateBell(data.unread_alert_count || 0, data.unack_danger_count || 0);
          renderBanner(data.unack_danger_count || 0, null);
          renderProfileMenu(data);
          refreshBellDropdown();
          startLiveUpdates();
        } else {
          renderBanner(0, null);
        }
        var payload = data || { authenticated: false, backendAvailable: true };
        document.dispatchEvent(new CustomEvent('vv:session', { detail: payload }));
        return payload;
      })
      .catch(function () {
        var fallback = { authenticated: false, backendAvailable: false };
        document.dispatchEvent(new CustomEvent('vv:session', { detail: fallback }));
        return fallback;
      });
    return _sessionPromise;
  }

  window.VV_SHELL = {
    esc: esc,
    safeUrl: safeUrl,
    state: state,
    setTodoProgress: setTodoProgress,
    updateBell: updateBell,
    toast: toast,
    openWelcomeModal: openWelcomeModal,
    getSession: function () { return hydrateSessionIfAvailable(false); },
    refreshSession: function () { return hydrateSessionIfAvailable(true); },
    liveState: function () { return { started: live.started, ready: Boolean(live.parts) }; },
    init: function () {
      initActiveMenu();
      wireControls();
      setTodoProgress(0);
      updateBell(0, 0);
      hydrateSessionIfAvailable(false);
    }
  };

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', window.VV_SHELL.init);
  } else {
    window.VV_SHELL.init();
  }
})();
