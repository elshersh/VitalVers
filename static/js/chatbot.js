/* Vitalverse Hybrid AI Chatbot UI wiring (On-board + Online via /api/chat) */
(function () {
  'use strict';

  var ENGINE_STORAGE_KEY = 'vv_chat_engine';
  var BOT_SVG =
    '<svg viewBox="0 0 36 22" fill="none" stroke="#a8e07a" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round">' +
      '<path d="M1 11h7l3-8 5 16 4-12 3 4h12"/>' +
    '</svg>';

  var chatLog = document.getElementById('chatLog');
  var chatForm = document.getElementById('chatForm');
  var chatInput = document.getElementById('chatInput');
  var chatSendBtn = document.getElementById('chatSendBtn');
  var newChatBtn = document.getElementById('newChatBtn');
  var roleBadge = document.getElementById('chatRoleBadge');
  var astronautSelect = document.getElementById('chatAstronautSelect');
  var promptChips = document.getElementById('promptChips');
  var engineOfflineBtn = document.getElementById('engineOfflineBtn');
  var engineOnlineBtn = document.getElementById('engineOnlineBtn');
  var engineHint = document.getElementById('engineHint');
  var onlinePrivacyNotice = document.getElementById('onlinePrivacyNotice');

  var state = {
    session: null,
    selectedAstronautId: null,
    engine: 'offline',
    onlineStatus: {
      available: false,
      active_provider: 'gemini',
      provider_label: 'Gemini',
      service_name: 'Google Gemini',
      button_label: 'Online',
      unavailable_hint: 'Online assistant unavailable',
      privacy_notice:
        'Online mode sends your question and a short summary of your health data to an external AI service (Google Gemini).'
    },
    busy: false
  };

  function esc(str) {
    return window.VV_SHELL ? window.VV_SHELL.esc(str) : String(str || '');
  }

  function readStoredEngine() {
    try {
      return window.sessionStorage ? window.sessionStorage.getItem(ENGINE_STORAGE_KEY) : null;
    } catch (_) {
      return null;
    }
  }

  function writeStoredEngine(eng) {
    try {
      if (window.sessionStorage) window.sessionStorage.setItem(ENGINE_STORAGE_KEY, eng);
    } catch (_) {}
  }

  function applyEngineUi() {
    var st = state.onlineStatus || {};
    var onlineAvailable = Boolean(st.available);
    if (engineOnlineBtn) {
      engineOnlineBtn.textContent = st.button_label || 'Online';
      engineOnlineBtn.disabled = !onlineAvailable;
      engineOnlineBtn.setAttribute('aria-disabled', onlineAvailable ? 'false' : 'true');
    }
    if (engineHint) {
      engineHint.textContent = st.unavailable_hint || 'Online assistant unavailable';
      if (onlineAvailable) {
        engineHint.setAttribute('hidden', '');
      } else {
        engineHint.removeAttribute('hidden');
      }
    }
    if (!onlineAvailable && state.engine === 'online') {
      state.engine = 'offline';
      writeStoredEngine('offline');
    }

    var isOnline = state.engine === 'online' && onlineAvailable;
    if (engineOfflineBtn) {
      engineOfflineBtn.classList.toggle('active', !isOnline);
      engineOfflineBtn.setAttribute('aria-pressed', !isOnline ? 'true' : 'false');
    }
    if (engineOnlineBtn) {
      engineOnlineBtn.classList.toggle('active', isOnline);
      engineOnlineBtn.setAttribute('aria-pressed', isOnline ? 'true' : 'false');
    }
    if (onlinePrivacyNotice) {
      onlinePrivacyNotice.textContent =
        st.privacy_notice ||
        'Online mode sends your question and a short summary of your health data to an external AI service (' +
          (st.service_name || 'Google Gemini') +
          ').';
      if (isOnline) {
        onlinePrivacyNotice.removeAttribute('hidden');
      } else {
        onlinePrivacyNotice.setAttribute('hidden', '');
      }
    }
  }

  function setEngine(nextEngine) {
    if (nextEngine === 'online' && !state.onlineStatus.available) {
      state.engine = 'offline';
      writeStoredEngine('offline');
      applyEngineUi();
      return;
    }
    state.engine = nextEngine === 'online' ? 'online' : 'offline';
    writeStoredEngine(state.engine);
    applyEngineUi();
  }

  function fetchOnlineStatus() {
    return fetch('/api/chat/status', { credentials: 'same-origin' })
      .then(function (res) {
        return res.ok ? res.json() : null;
      })
      .then(function (data) {
        if (data && typeof data === 'object') {
          state.onlineStatus = data;
          var saved = readStoredEngine();
          if (saved === 'online' && data.available) {
            state.engine = 'online';
          }
        }
        applyEngineUi();
      })
      .catch(function () {
        state.onlineStatus.available = false;
        applyEngineUi();
      });
  }

  function scrollToBottom() {
    if (chatLog) {
      chatLog.scrollTop = chatLog.scrollHeight;
    }
  }

  function autoResizeInput() {
    if (!chatInput) return;
    chatInput.style.height = 'auto';
    chatInput.style.height = Math.min(chatInput.scrollHeight, 120) + 'px';
  }

  function appendUserBubble(text) {
    var row = document.createElement('div');
    row.className = 'vv-chat-row vv-chat-row--user';
    row.innerHTML = '<div class="vv-bubble vv-bubble--user">' + esc(text) + '</div>';
    chatLog.appendChild(row);
    scrollToBottom();
  }

  function appendTypingRow() {
    var row = document.createElement('div');
    row.className = 'vv-chat-row vv-chat-row--bot';
    row.id = 'vvTypingRow';
    row.innerHTML =
      '<div class="vv-bot-avatar" aria-hidden="true">' + BOT_SVG + '</div>' +
      '<div class="vv-bubble vv-bubble--bot">' +
        '<div class="vv-typing-dots" aria-label="Thinking"><span></span><span></span><span></span></div>' +
      '</div>';
    chatLog.appendChild(row);
    scrollToBottom();
    return row;
  }

  function appendBotPayload(data) {
    var row = document.createElement('div');
    row.className = 'vv-chat-row vv-chat-row--bot';

    var bubbleClass = 'vv-bubble vv-bubble--bot';
    var inner = '';

    if (data && data.fallback_notice) {
      inner += '<div class="vv-fallback-note">' + esc(data.fallback_notice) + '</div>';
    }

    if (data && data.urgent_escalation) {
      bubbleClass += ' vv-urgent-card';
      var surgeon = data.flight_surgeon_contact || 'Ground Medical Control';
      inner +=
        '<div class="vv-urgent-heading">Contact your flight surgeon now</div>' +
        '<div class="vv-urgent-contact">Flight surgeon channel: <strong>' + esc(surgeon) + '</strong></div>';
    } else if (data && data.refused) {
      bubbleClass += ' vv-chat-refusal';
      inner += '<div class="vv-refusal-title">Out of scope</div>';
    } else if (data && data.login_required) {
      bubbleClass += ' vv-login-card';
      inner += '<div class="vv-refusal-title" style="color:var(--green)">Crew Sign-In Required</div>';
    }

    inner += '<div>' + esc((data && data.answer) || 'No response available.') + '</div>';

    if (data && data.did_you_mean) {
      inner +=
        '<div><button type="button" class="vv-did-you-mean" data-suggestion="' +
        esc(data.did_you_mean) +
        '">Did you mean: "' + esc(data.did_you_mean) + '"?</button></div>';
    }

    if (data && data.login_required) {
      inner +=
        '<div style="margin-top:12px;"><a class="btn" href="login.html" style="padding:8px 16px;font-size:12px;">Sign in to Vitalverse</a></div>';
    }

    var engineLabel = (data && data.engine_label) || 'On-board';
    var engineTagClass = 'vv-engine-tag' + (data && data.engine_used === 'online' ? ' vv-engine-tag--online' : '');
    var metaParts = [];
    if (data && data.astronaut_id) metaParts.push('Crew ' + esc(data.astronaut_id));
    if (data && data.intent) metaParts.push('Intent: ' + esc(data.intent));
    if (data && data.sources && data.sources !== 'none') metaParts.push('Source: ' + esc(data.sources));

    inner +=
      '<div class="vv-bubble-meta">' +
        '<span class="' + engineTagClass + '">' + esc(engineLabel) + '</span>' +
        (metaParts.length ? '<span>' + metaParts.join(' · ') + '</span>' : '') +
      '</div>';

    row.innerHTML =
      '<div class="vv-bot-avatar" aria-hidden="true">' + BOT_SVG + '</div>' +
      '<div class="' + bubbleClass + '">' + inner + '</div>';

    chatLog.appendChild(row);

    var dymBtn = row.querySelector('.vv-did-you-mean');
    if (dymBtn) {
      dymBtn.addEventListener('click', function () {
        sendQuestion(dymBtn.getAttribute('data-suggestion') || '');
      });
    }

    scrollToBottom();
  }

  function renderWelcome() {
    chatLog.innerHTML = '';
    var greeting =
      'Hello! I am your Vitalverse health assistant. Ask about your heart rate, sleep, mood, alerts, pre-flight baselines, or orbital countermeasures.';
    if (state.session && state.session.authenticated && state.session.role === 'doctor') {
      greeting =
        'Doctor session active. Select an approved crew member above and ask about their 180-day telemetry, baseline comparisons, or alerts.';
    } else if (!state.session || !state.session.authenticated) {
      greeting += '\nSign in for personal telemetry answers, or try a prompt chip above.';
    }
    appendBotPayload({
      answer: greeting,
      intent: 'greeting',
      engine_used: 'offline',
      engine_label: 'On-board',
      sources: 'offline_ai_chatbot'
    });
  }

  function setBusy(flag) {
    state.busy = flag;
    if (chatSendBtn) chatSendBtn.disabled = flag;
    if (chatInput) chatInput.disabled = flag;
  }

  function sendQuestion(rawText) {
    var question = String(rawText || '').trim();
    if (!question || state.busy) return;

    appendUserBubble(question);
    if (chatInput) {
      chatInput.value = '';
      autoResizeInput();
    }

    setBusy(true);
    var typingRow = appendTypingRow();

    var payload = {
      question: question,
      engine: state.engine === 'online' && state.onlineStatus.available ? 'online' : 'offline'
    };
    if (state.session && state.session.role === 'doctor' && state.selectedAstronautId) {
      payload.astronaut_id = state.selectedAstronautId;
    }

    fetch('/api/chat', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      credentials: 'same-origin',
      body: JSON.stringify(payload)
    })
      .then(function (res) {
        return res.json().then(function (body) {
          return { ok: res.ok, body: body };
        });
      })
      .then(function (result) {
        if (typingRow && typingRow.parentNode) typingRow.parentNode.removeChild(typingRow);
        if (!result.ok) {
          appendBotPayload({
            refused: true,
            intent: 'error',
            engine_used: 'offline',
            engine_label: 'On-board',
            answer: (result.body && result.body.detail) || 'Unable to process this request.'
          });
          return;
        }
        appendBotPayload(result.body);
      })
      .catch(function () {
        if (typingRow && typingRow.parentNode) typingRow.parentNode.removeChild(typingRow);
        appendBotPayload({
          refused: true,
          intent: 'error',
          engine_used: 'offline',
          engine_label: 'On-board',
          answer: 'Connection error while contacting the Vitalverse chatbot backend.'
        });
      })
      .finally(function () {
        setBusy(false);
        if (chatInput) chatInput.focus();
      });
  }

  function hydrateSubject(session) {
    state.session = session || { authenticated: false };
    if (!state.session.authenticated) {
      roleBadge.className = 'vv-badge vv-badge--warn';
      roleBadge.textContent = 'Guest preview — sign in for personal data';
      astronautSelect.setAttribute('hidden', '');
      renderWelcome();
      return;
    }

    var u = state.session.user || {};
    if (state.session.role === 'astronaut') {
      state.selectedAstronautId = u.astronaut_id || null;
      roleBadge.className = 'vv-badge vv-badge--ok';
      roleBadge.textContent = (u.name || 'Astronaut') + ' (' + (u.astronaut_id || '') + ')';
      astronautSelect.setAttribute('hidden', '');
      renderWelcome();
      return;
    }

    if (state.session.role === 'doctor') {
      roleBadge.className = 'vv-badge vv-badge--ok';
      roleBadge.textContent = (u.name || 'Doctor') + ' · Approved Crew';
      fetch('/api/doctor/astronauts', { credentials: 'same-origin' })
        .then(function (res) { return res.ok ? res.json() : { approved: [] }; })
        .then(function (docData) {
          var list = (docData && docData.approved) || [];
          if (!list.length) {
            astronautSelect.setAttribute('hidden', '');
            state.selectedAstronautId = null;
          } else {
            astronautSelect.innerHTML = list.map(function (a) {
              return '<option value="' + esc(a.id) + '">' + esc(a.name + ' (' + a.id + ')') + '</option>';
            }).join('');
            astronautSelect.removeAttribute('hidden');
            state.selectedAstronautId = list[0].id;
            astronautSelect.value = list[0].id;
          }
          renderWelcome();
        })
        .catch(function () {
          renderWelcome();
        });
    }
  }

  if (engineOfflineBtn) {
    engineOfflineBtn.addEventListener('click', function () {
      setEngine('offline');
    });
  }

  if (engineOnlineBtn) {
    engineOnlineBtn.addEventListener('click', function () {
      if (!engineOnlineBtn.disabled) {
        setEngine('online');
      }
    });
  }

  if (astronautSelect) {
    astronautSelect.addEventListener('change', function () {
      state.selectedAstronautId = astronautSelect.value || null;
      renderWelcome();
    });
  }

  if (newChatBtn) {
    newChatBtn.addEventListener('click', function () {
      renderWelcome();
    });
  }

  if (promptChips) {
    promptChips.addEventListener('click', function (e) {
      var btn = e.target.closest ? e.target.closest('button[data-question]') : null;
      if (!btn) return;
      sendQuestion(btn.getAttribute('data-question'));
    });
  }

  if (chatForm) {
    chatForm.addEventListener('submit', function (e) {
      e.preventDefault();
      sendQuestion(chatInput ? chatInput.value : '');
    });
  }

  if (chatInput) {
    chatInput.addEventListener('input', autoResizeInput);
    chatInput.addEventListener('keydown', function (e) {
      if (e.key === 'Enter' && !e.shiftKey) {
        e.preventDefault();
        sendQuestion(chatInput.value);
      }
    });
  }

  function start() {
    applyEngineUi();
    fetchOnlineStatus();
    if (window.VV_SHELL && typeof window.VV_SHELL.getSession === 'function') {
      window.VV_SHELL.getSession().then(hydrateSubject);
    } else {
      hydrateSubject({ authenticated: false });
    }
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', start);
  } else {
    start();
  }
})();
