/* B3 Profile Page Controller (Astronaut & Doctor roles, uploads, access control, password/session security) */
(function () {
  'use strict';

  var esc = function (s) { return window.VV_SHELL.esc(s); };
  var safeUrl = function (u) { return window.VV_SHELL.safeUrl(u); };
  var state = {
    session: null,
    tab: '',
    astroData: null,
    accessRequests: [],
    doctorProfile: null,
    doctorAstronauts: { approved: [], pending: [] },
    selectedPatientId: '',
    selectedPatientData: null,
    pendingRevokeId: null,
    msg: null
  };

  function barHtml(seed) {
    var s = (seed || 'VITALVERSE') + '-VERIFIED';
    var h = '';
    for (var i = 0; i < 48; i++) {
      var c = s.charCodeAt(i % s.length) + i * 7;
      h += '<i style="width:' + (1 + (c % 3)) + 'px;margin-right:' + (1 + ((c >> 2) % 2)) + 'px"></i>';
    }
    return h;
  }

  function showMessage(text, isErr) {
    state.msg = { text: text, isErr: Boolean(isErr) };
    render();
  }

  async function apiJson(url, opts) {
    var headers = Object.assign({}, (opts && opts.headers) || {});
    if (opts && opts.method && opts.method !== 'GET' && state.session && state.session.csrf_token) {
      headers['X-CSRF-Token'] = state.session.csrf_token;
    }
    var res = await fetch(url, Object.assign({ credentials: 'same-origin' }, opts || {}, { headers: headers }));
    var body = await res.json().catch(function () { return {}; });
    if (!res.ok) throw new Error(body.detail || 'Request failed (' + res.status + ').');
    return body;
  }

  function renderBoardingPass() {
    var pill = document.getElementById('pfRolePill');
    var nameEl = document.getElementById('pfPassName');
    var vidEl = document.getElementById('pfPassVid');
    var avEl = document.getElementById('pfPassAvatar');
    var rowsEl = document.getElementById('pfPassRows');
    var barEl = document.getElementById('pfBar');
    if (!state.session) return;

    var u = state.session.user || {};
    var role = state.session.role;
    pill.textContent = role === 'doctor' ? 'Medical pass' : 'Crew pass';
    vidEl.textContent = u.vitalverse_id || '';
    barEl.innerHTML = barHtml(u.vitalverse_id);

    if (role === 'astronaut' && state.astroData) {
      var p = state.astroData.personal || {};
      var fl = state.astroData.flight || {};
      nameEl.textContent = p.name || u.name || '';
      if (state.astroData.avatar_url && safeUrl(state.astroData.avatar_url)) {
        avEl.innerHTML = '<img src="' + esc(safeUrl(state.astroData.avatar_url)) + '" alt="Profile avatar">';
        var avImg = avEl.querySelector('img');
        if (avImg) {
          avImg.addEventListener('error', function () {
            avEl.textContent = u.initials || 'VV';
          });
        }
      } else {
        avEl.textContent = u.initials || 'VV';
      }
      rowsEl.innerHTML =
        '<div class="pf-r"><span>Astronaut ID</span><b>' + esc(state.astroData.astronaut_id) + '</b></div>' +
        '<div class="pf-r"><span>Mission Role</span><b>' + esc(p.mission_role || '-') + '</b></div>' +
        '<div class="pf-r"><span>Destination</span><b>' + esc(fl.destination_for_flight || '-') + '</b></div>' +
        '<div class="pf-r"><span>Flight Surgeon</span><b>' + esc(p.contact_flight_surgeon || '-') + '</b></div>';
    } else if (role === 'doctor' && state.doctorProfile) {
      var d = state.doctorProfile;
      nameEl.textContent = d.full_name || u.name || '';
      avEl.textContent = u.initials || 'DR';
      rowsEl.innerHTML =
        '<div class="pf-r"><span>Staff ID</span><b>' + esc(d.staff_id || '-') + '</b></div>' +
        '<div class="pf-r"><span>Specialty</span><b>' + esc(d.specialization || '-') + '</b></div>' +
        '<div class="pf-r"><span>Agency</span><b>' + esc(d.organization || '-') + '</b></div>' +
        '<div class="pf-r"><span>Approved Crew</span><b>' + String((state.doctorAstronauts.approved || []).length) + '</b></div>';
    }
  }

  function msgBoxHtml() {
    if (!state.msg) return '';
    return '<div class="pf-msg ' + (state.msg.isErr ? 'pf-msg--err' : 'pf-msg--ok') + '">' + esc(state.msg.text) + '</div>';
  }

  function securityTabHtml() {
    return (
      '<form id="pfPwdForm" class="pf-grid2">' +
        '<div class="pf-field-wrap pf-full"><label>Current Password</label><input class="vv-field" type="password" id="pfCurPwd" required autocomplete="current-password"></div>' +
        '<div class="pf-field-wrap"><label>New Password (min 8 characters)</label><input class="vv-field" type="password" id="pfNewPwd" minlength="8" required autocomplete="new-password"></div>' +
        '<div class="pf-field-wrap"><label>Confirm New Password</label><input class="vv-field" type="password" id="pfConfPwd" minlength="8" required autocomplete="new-password"></div>' +
        '<div class="pf-full" style="display:flex;gap:12px;flex-wrap:wrap;margin-top:6px;">' +
          '<button type="submit" class="btn">Update Password</button>' +
          '<button type="button" class="btn danger" id="pfLogoutAllBtn">Log out of all devices</button>' +
        '</div>' +
      '</form>'
    );
  }

  function healthFormHtml(h, aid) {
    return (
      '<form class="pf-grid2" data-health-aid="' + esc(aid) + '" id="pfHealthForm">' +
        '<div class="pf-field-wrap"><label>Age</label><input class="vv-field" type="number" min="0" name="age" value="' + esc(h.age == null ? '' : h.age) + '"></div>' +
        '<div class="pf-field-wrap"><label>Gender</label><input class="vv-field" name="gender" value="' + esc(h.gender || '') + '"></div>' +
        '<div class="pf-field-wrap"><label>Weight (kg)</label><input class="vv-field" type="number" step="0.1" name="weight_kg" value="' + esc(h.weight_kg == null ? '' : h.weight_kg) + '"></div>' +
        '<div class="pf-field-wrap"><label>Height (cm)</label><input class="vv-field" type="number" step="0.1" name="height_cm" value="' + esc(h.height_cm == null ? '' : h.height_cm) + '"></div>' +
        '<div class="pf-field-wrap pf-full"><label>Blood Type</label><input class="vv-field" name="blood_type" value="' + esc(h.blood_type || '') + '"></div>' +
        '<div class="pf-field-wrap pf-full"><label>Allergies</label><textarea class="vv-field" rows="2" name="allergies">' + esc(h.allergies || '') + '</textarea></div>' +
        '<div class="pf-field-wrap pf-full"><label>Previous Surgeries</label><textarea class="vv-field" rows="2" name="previous_surgeries">' + esc(h.previous_surgeries || '') + '</textarea></div>' +
        '<div class="pf-field-wrap pf-full"><label>Previous Injuries</label><textarea class="vv-field" rows="2" name="previous_injuries">' + esc(h.previous_injuries || '') + '</textarea></div>' +
        '<div class="pf-field-wrap pf-full"><label>Immunization History</label><textarea class="vv-field" rows="2" name="immunization_history">' + esc(h.immunization_history || '') + '</textarea></div>' +
        '<div class="pf-field-wrap pf-full"><label>Family Medical History</label><textarea class="vv-field" rows="2" name="family_medical_history">' + esc(h.family_medical_history || '') + '</textarea></div>' +
        '<div class="pf-full"><button type="submit" class="btn">Save Health Info</button></div>' +
      '</form>'
    );
  }

  function flightFormHtml(fl, aid) {
    return (
      '<form class="pf-grid2" data-flight-aid="' + esc(aid) + '" id="pfFlightForm">' +
        '<div class="pf-field-wrap pf-full"><label>Type of Aircraft</label><input class="vv-field" name="type_of_aircraft" value="' + esc(fl.type_of_aircraft || '') + '"></div>' +
        '<div class="pf-field-wrap"><label>Estimated Flight Duration (days)</label><input class="vv-field" type="number" min="1" name="estimated_time_for_flight_days" value="' + esc(fl.estimated_time_for_flight_days == null ? '' : fl.estimated_time_for_flight_days) + '"></div>' +
        '<div class="pf-field-wrap"><label>Flight Destination</label><input class="vv-field" name="destination_for_flight" value="' + esc(fl.destination_for_flight || '') + '"></div>' +
        '<div class="pf-full"><button type="submit" class="btn">Save Flight Info</button></div>' +
      '</form>'
    );
  }

  function renderAstronautBody() {
    var d = state.astroData;
    var tab = state.tab;
    if (tab === 'Personal') {
      var p = d.personal || {};
      return (
        '<form class="pf-grid2" id="pfPersonalForm">' +
          '<div class="pf-field-wrap pf-full"><label>Full Name</label><input class="vv-field" name="name" required value="' + esc(p.name || '') + '"></div>' +
          '<div class="pf-field-wrap"><label>Mission Role</label><input class="vv-field" name="mission_role" value="' + esc(p.mission_role || '') + '"></div>' +
          '<div class="pf-field-wrap"><label>Nationality</label><input class="vv-field" name="nationality" value="' + esc(p.nationality || '') + '"></div>' +
          '<div class="pf-field-wrap pf-full"><label>Contact Flight Surgeon</label><input class="vv-field" name="contact_flight_surgeon" value="' + esc(p.contact_flight_surgeon || '') + '"></div>' +
          '<div class="pf-field-wrap pf-full"><label><input type="checkbox" name="previous_flight" ' + (p.previous_flight ? 'checked' : '') + ' style="margin-right:8px;">Previous spaceflight experience</label></div>' +
          '<div class="pf-full"><button type="submit" class="btn">Save Personal Info</button></div>' +
        '</form>' +
        '<hr style="border:0;border-top:1px solid rgba(255,255,255,.12);margin:20px 0">' +
        '<form id="pfAvatarForm" style="display:flex;gap:12px;align-items:center;flex-wrap:wrap">' +
          '<label style="font-size:12px;color:var(--muted)">Update Profile Photo (PNG/JPG <= 5 MB):</label>' +
          '<input type="file" id="pfAvatarFile" accept="image/*" style="font-size:12px;color:#fff">' +
          '<button type="submit" class="btn ghost">Upload Photo</button>' +
        '</form>'
      );
    }
    if (tab === 'Health') return healthFormHtml(d.health || {}, d.astronaut_id);
    if (tab === 'Flight') return flightFormHtml(d.flight || {}, d.astronaut_id);
    if (tab === 'Songs & Photos') {
      var songsHtml = (d.playlist || []).map(function (s) {
        var u = safeUrl(s.url);
        return '<div class="pf-item"><div><strong>' + esc(s.title) + '</strong> <span class="vv-badge">' + esc(s.tag) + '</span> ' +
          (u ? '<a href="' + esc(u) + '" target="_blank" rel="noopener" style="color:var(--green);font-size:12px;margin-left:8px;">Open</a>' : '') +
          '</div><button type="button" class="btn danger" style="padding:6px 12px;font-size:11px" data-del-song="' + s.id + '">Delete</button></div>';
      }).join('') || '<div class="vv-empty">No preferred songs added yet.</div>';

      var photosHtml = (d.photos || []).map(function (ph) {
        var u = safeUrl(ph.url);
        return '<div class="pf-photo-card">' + (u ? '<img src="' + esc(u) + '" alt="Comfort photo">' : '') +
          '<div class="pf-photo-meta"><span class="vv-badge">' + esc(ph.tag) + '</span>' +
          '<button type="button" class="btn danger" style="padding:4px 10px;font-size:11px" data-del-photo="' + ph.id + '">Remove</button></div></div>';
      }).join('');

      return (
        '<h3 style="margin:0 0 8px;font-size:15px">Preferred Songs (used in Mental Check-In)</h3>' +
        '<form id="pfAddSongForm" class="pf-grid2" style="margin-bottom:12px">' +
          '<input class="vv-field" id="pfSongTitle" placeholder="Song title" required>' +
          '<select class="vv-field" id="pfSongTag"><option value="comfort">comfort</option><option value="happy">happy</option><option value="energy">energy</option></select>' +
          '<input class="vv-field" id="pfSongUrl" placeholder="Streaming URL (https://...) or upload audio below">' +
          '<input type="file" id="pfSongAudio" accept=".mp3,.m4a,.wav,audio/*" style="font-size:12px;color:#fff;align-self:center">' +
          '<div class="pf-full"><button type="submit" class="btn">+ Add Song</button></div>' +
        '</form>' +
        '<div class="pf-list">' + songsHtml + '</div>' +
        '<hr style="border:0;border-top:1px solid rgba(255,255,255,.12);margin:20px 0">' +
        '<h3 style="margin:0 0 8px;font-size:15px">Preferred Comfort Photos</h3>' +
        '<form id="pfAddPhotoForm" style="display:flex;gap:10px;align-items:center;flex-wrap:wrap">' +
          '<input type="file" id="pfPhotoFile" accept="image/*" required style="font-size:12px;color:#fff">' +
          '<select class="vv-field" id="pfPhotoTag" style="width:auto"><option value="comfort">comfort</option><option value="happy">happy</option><option value="energy">energy</option></select>' +
          '<button type="submit" class="btn ghost">+ Upload Photo</button>' +
        '</form>' +
        (photosHtml ? '<div class="pf-photo-grid">' + photosHtml + '</div>' : '<div class="vv-empty" style="margin-top:12px">No comfort photos uploaded yet.</div>')
      );
    }
    if (tab === 'Access') {
      var list = state.accessRequests || [];
      if (!list.length) return '<div class="vv-empty">No doctor access requests yet.</div>';
      return '<div class="pf-list">' + list.map(function (r) {
        var badgeCls = r.status === 'approved' ? 'vv-badge--ok' : (r.status === 'pending' ? 'vv-badge--warn' : 'vv-badge--danger');
        var btns = '';
        if (r.status === 'pending') {
          btns = '<button type="button" class="btn" style="padding:7px 14px" data-acc-approve="' + r.id + '">Approve</button>' +
                 '<button type="button" class="btn ghost" style="padding:7px 14px" data-acc-decline="' + r.id + '">Decline</button>';
        } else if (r.status === 'approved') {
          btns = '<button type="button" class="btn danger" style="padding:7px 14px" data-acc-revoke="' + r.id + '" data-acc-name="' + esc(r.doctor_name) + '">Revoke access</button>';
        }
        return '<div class="pf-item"><div><strong>' + esc(r.doctor_name) + '</strong> <span style="font-size:12px;color:var(--green)">' + esc(r.doctor_vitalverse_id) + '</span>' +
          '<div style="font-size:12px;color:var(--muted);margin-top:3px">' + esc([r.specialization, r.organization].filter(Boolean).join(' · ') || 'Flight Surgeon') + '</div>' +
          (r.mission_crew_note ? '<div style="font-size:12px;color:#d9dde0;margin-top:4px">' + esc(r.mission_crew_note) + '</div>' : '') +
          '</div><div style="display:flex;align-items:center;gap:8px;flex-wrap:wrap"><span class="vv-badge ' + badgeCls + '">' + esc(r.status) + '</span>' + btns + '</div></div>';
      }).join('') + '</div>';
    }
    return securityTabHtml();
  }

  function renderDoctorBody() {
    var tab = state.tab;
    if (tab === 'Doctor info') {
      var d = state.doctorProfile || {};
      return (
        '<form class="pf-grid2" id="pfDoctorForm">' +
          '<div class="pf-field-wrap pf-full"><label>Full Name</label><input class="vv-field" name="full_name" required value="' + esc(d.full_name || '') + '"></div>' +
          '<div class="pf-field-wrap"><label>Staff ID</label><input class="vv-field" name="staff_id" value="' + esc(d.staff_id || '') + '"></div>' +
          '<div class="pf-field-wrap"><label>Specialization</label><input class="vv-field" name="specialization" value="' + esc(d.specialization || '') + '"></div>' +
          '<div class="pf-field-wrap"><label>Organization</label><input class="vv-field" name="organization" value="' + esc(d.organization || '') + '"></div>' +
          '<div class="pf-field-wrap"><label>Work Contact</label><input class="vv-field" name="contact" value="' + esc(d.contact || '') + '"></div>' +
          '<div class="pf-field-wrap pf-full"><label>Credential Reference</label><input class="vv-field" name="credential" value="' + esc(d.credential || '') + '"></div>' +
          '<div class="pf-full"><button type="submit" class="btn">Save Doctor Info</button></div>' +
        '</form>'
      );
    }
    if (tab === 'My astronauts') {
      var appr = state.doctorAstronauts.approved || [];
      var pend = state.doctorAstronauts.pending || [];
      var editorHtml = '';
      if (appr.length) {
        var opts = appr.map(function (a) {
          return '<option value="' + esc(a.id) + '" ' + (a.id === state.selectedPatientId ? 'selected' : '') + '>' + esc(a.id + ' — ' + a.name) + '</option>';
        }).join('');
        var pt = state.selectedPatientData;
        editorHtml =
          '<div style="margin-bottom:18px">' +
            '<label style="display:block;font-size:12px;color:var(--muted);margin-bottom:6px">Approved Astronaut Record (view &amp; edit Health/Flight)</label>' +
            '<select class="vv-field" id="pfDocAstSel">' + opts + '</select>' +
          '</div>' +
          (pt ? (
            '<h3 style="margin:14px 0 8px;font-size:15px">Edit Health Background (' + esc(pt.astronaut_id) + ')</h3>' +
            healthFormHtml(pt.health || {}, pt.astronaut_id) +
            '<h3 style="margin:22px 0 8px;font-size:15px">Edit Flight Info (' + esc(pt.astronaut_id) + ')</h3>' +
            flightFormHtml(pt.flight || {}, pt.astronaut_id)
          ) : '');
      } else {
        editorHtml = '<div class="vv-empty" style="margin-bottom:18px">No approved astronauts yet.</div>';
      }

      var pendHtml = pend.length ? (
        '<div style="margin-bottom:18px"><h3 style="font-size:14px;color:var(--warn);margin-bottom:8px">Pending Requests</h3><div class="pf-list">' +
        pend.map(function (p) {
          return '<div class="pf-item"><span><strong>' + esc(p.id + ' — ' + p.name) + '</strong></span><span class="vv-badge vv-badge--warn">pending</span></div>';
        }).join('') + '</div></div>'
      ) : '';

      return (
        editorHtml + pendHtml +
        '<hr style="border:0;border-top:1px solid rgba(255,255,255,.12);margin:20px 0">' +
        '<h3 style="margin:0 0 8px;font-size:15px">Request access to another astronaut</h3>' +
        '<form class="pf-grid2" id="pfReqAstForm">' +
          '<div class="pf-field-wrap"><label>Astronaut Vitalverse ID or Mission ID (e.g. VTA-DEMO01 or A002)</label><input class="vv-field" id="pfReqTarget" required></div>' +
          '<div class="pf-field-wrap"><label>Mission / Crew Note</label><input class="vv-field" id="pfReqNote" placeholder="Flight medical assignment"></div>' +
          '<div class="pf-full"><label style="font-size:12px;color:var(--muted)"><input type="checkbox" id="pfReqConsent" required style="margin-right:8px;">I confirm this access request has the astronaut\'s authorization.</label></div>' +
          '<div class="pf-full"><button type="submit" class="btn ghost">Send Access Request</button></div>' +
        '</form>'
      );
    }
    return securityTabHtml();
  }

  function wireFormHandlers(root) {
    var pfForm = root.querySelector('#pfPersonalForm');
    if (pfForm) {
      pfForm.addEventListener('submit', async function (e) {
        e.preventDefault();
        try {
          var fd = new FormData(pfForm);
          var body = await apiJson('/api/profile/' + encodeURIComponent(state.astroData.astronaut_id) + '/personal', {
            method: 'PUT',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
              name: fd.get('name'),
              mission_role: fd.get('mission_role'),
              nationality: fd.get('nationality'),
              contact_flight_surgeon: fd.get('contact_flight_surgeon'),
              previous_flight: pfForm.querySelector('[name="previous_flight"]').checked
            })
          });
          state.astroData = body.profile;
          showMessage('Personal profile saved.', false);
        } catch (err) { showMessage(err.message, true); }
      });
    }

    var avForm = root.querySelector('#pfAvatarForm');
    if (avForm) {
      avForm.addEventListener('submit', async function (e) {
        e.preventDefault();
        var fileInput = root.querySelector('#pfAvatarFile');
        if (!fileInput || !fileInput.files || !fileInput.files[0]) return showMessage('Select an image file first.', true);
        try {
          var fd = new FormData();
          fd.append('purpose', 'profile_photo');
          fd.append('file', fileInput.files[0]);
          await apiJson('/api/uploads/' + encodeURIComponent(state.astroData.astronaut_id), { method: 'POST', body: fd });
          state.astroData = await apiJson('/api/profile/' + encodeURIComponent(state.astroData.astronaut_id));
          if (window.VV_SHELL && window.VV_SHELL.refreshSession) window.VV_SHELL.refreshSession();
          showMessage('Profile photo updated.', false);
        } catch (err) { showMessage(err.message, true); }
      });
    }

    var hForm = root.querySelector('#pfHealthForm');
    if (hForm) {
      hForm.addEventListener('submit', async function (e) {
        e.preventDefault();
        try {
          var aid = hForm.dataset.healthAid;
          var fd = new FormData(hForm);
          var numOrNull = function (v) { return String(v || '').trim() === '' ? null : Number(v); };
          var body = await apiJson('/api/profile/' + encodeURIComponent(aid) + '/health', {
            method: 'PUT',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
              age: numOrNull(fd.get('age')),
              gender: fd.get('gender') || '',
              weight_kg: numOrNull(fd.get('weight_kg')),
              height_cm: numOrNull(fd.get('height_cm')),
              blood_type: fd.get('blood_type') || '',
              allergies: fd.get('allergies') || '',
              previous_surgeries: fd.get('previous_surgeries') || '',
              previous_injuries: fd.get('previous_injuries') || '',
              immunization_history: fd.get('immunization_history') || '',
              family_medical_history: fd.get('family_medical_history') || ''
            })
          });
          if (state.session.role === 'astronaut') state.astroData = body.profile;
          else state.selectedPatientData = body.profile;
          showMessage('Health information saved.', false);
        } catch (err) { showMessage(err.message, true); }
      });
    }

    var flForm = root.querySelector('#pfFlightForm');
    if (flForm) {
      flForm.addEventListener('submit', async function (e) {
        e.preventDefault();
        try {
          var aid = flForm.dataset.flightAid;
          var fd = new FormData(flForm);
          var dur = String(fd.get('estimated_time_for_flight_days') || '').trim();
          var body = await apiJson('/api/profile/' + encodeURIComponent(aid) + '/flight', {
            method: 'PUT',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
              type_of_aircraft: fd.get('type_of_aircraft') || '',
              estimated_time_for_flight_days: dur ? Number(dur) : null,
              destination_for_flight: fd.get('destination_for_flight') || ''
            })
          });
          if (state.session.role === 'astronaut') state.astroData = body.profile;
          else state.selectedPatientData = body.profile;
          showMessage('Flight information saved.', false);
        } catch (err) { showMessage(err.message, true); }
      });
    }

    var songForm = root.querySelector('#pfAddSongForm');
    if (songForm) {
      songForm.addEventListener('submit', async function (e) {
        e.preventDefault();
        try {
          var title = root.querySelector('#pfSongTitle').value.trim();
          var tag = root.querySelector('#pfSongTag').value;
          var url = root.querySelector('#pfSongUrl').value.trim();
          var audio = (root.querySelector('#pfSongAudio').files || [])[0];
          var aid = state.astroData.astronaut_id;
          if (audio) {
            var fd = new FormData();
            fd.append('purpose', 'song_audio');
            fd.append('tag', tag);
            fd.append('title', title);
            fd.append('file', audio);
            await apiJson('/api/uploads/' + encodeURIComponent(aid), { method: 'POST', body: fd });
          } else {
            await apiJson('/api/profile/' + encodeURIComponent(aid) + '/playlist', {
              method: 'POST',
              headers: { 'Content-Type': 'application/json' },
              body: JSON.stringify({ title: title, tag: tag, url: url })
            });
          }
          state.astroData = await apiJson('/api/profile/' + encodeURIComponent(aid));
          showMessage('Song added to your comfort library.', false);
        } catch (err) { showMessage(err.message, true); }
      });
    }

    var photoForm = root.querySelector('#pfAddPhotoForm');
    if (photoForm) {
      photoForm.addEventListener('submit', async function (e) {
        e.preventDefault();
        try {
          var file = (root.querySelector('#pfPhotoFile').files || [])[0];
          if (!file) return showMessage('Choose a photo first.', true);
          var fd = new FormData();
          fd.append('purpose', 'photo');
          fd.append('tag', root.querySelector('#pfPhotoTag').value);
          fd.append('file', file);
          var aid = state.astroData.astronaut_id;
          await apiJson('/api/uploads/' + encodeURIComponent(aid), { method: 'POST', body: fd });
          state.astroData = await apiJson('/api/profile/' + encodeURIComponent(aid));
          showMessage('Comfort photo uploaded.', false);
        } catch (err) { showMessage(err.message, true); }
      });
    }

    root.querySelectorAll('[data-del-song]').forEach(function (b) {
      b.addEventListener('click', async function () {
        try {
          var aid = state.astroData.astronaut_id;
          var out = await apiJson('/api/profile/' + encodeURIComponent(aid) + '/playlist/' + b.dataset.delSong, { method: 'DELETE' });
          state.astroData = out.profile;
          showMessage('Song removed.', false);
        } catch (err) { showMessage(err.message, true); }
      });
    });

    root.querySelectorAll('[data-del-photo]').forEach(function (b) {
      b.addEventListener('click', async function () {
        try {
          var aid = state.astroData.astronaut_id;
          var out = await apiJson('/api/profile/' + encodeURIComponent(aid) + '/photos/' + b.dataset.delPhoto, { method: 'DELETE' });
          state.astroData = out.profile;
          showMessage('Photo removed.', false);
        } catch (err) { showMessage(err.message, true); }
      });
    });

    root.querySelectorAll('[data-acc-approve]').forEach(function (b) {
      b.addEventListener('click', async function () {
        try {
          await apiJson('/api/access/requests/' + b.dataset.accApprove + '/approve', { method: 'POST' });
          var acc = await apiJson('/api/access/requests');
          state.accessRequests = acc.requests || [];
          if (window.VV_SHELL && window.VV_SHELL.refreshSession) window.VV_SHELL.refreshSession();
          showMessage('Doctor access approved.', false);
        } catch (err) { showMessage(err.message, true); }
      });
    });

    root.querySelectorAll('[data-acc-decline]').forEach(function (b) {
      b.addEventListener('click', async function () {
        try {
          await apiJson('/api/access/requests/' + b.dataset.accDecline + '/decline', { method: 'POST' });
          var acc = await apiJson('/api/access/requests');
          state.accessRequests = acc.requests || [];
          if (window.VV_SHELL && window.VV_SHELL.refreshSession) window.VV_SHELL.refreshSession();
          showMessage('Doctor access request declined.', false);
        } catch (err) { showMessage(err.message, true); }
      });
    });

    root.querySelectorAll('[data-acc-revoke]').forEach(function (b) {
      b.addEventListener('click', function () {
        state.pendingRevokeId = b.dataset.accRevoke;
        document.getElementById('pfRevokeDesc').textContent =
          'Revoke access for ' + (b.dataset.accName || 'this doctor') + '? They will immediately receive 403 on your records.';
        document.getElementById('pfRevokeModal').classList.add('show');
      });
    });

    var docForm = root.querySelector('#pfDoctorForm');
    if (docForm) {
      docForm.addEventListener('submit', async function (e) {
        e.preventDefault();
        try {
          var fd = new FormData(docForm);
          var payload = {
            full_name: fd.get('full_name'),
            staff_id: fd.get('staff_id') || '',
            specialization: fd.get('specialization') || '',
            organization: fd.get('organization') || '',
            contact: fd.get('contact') || '',
            credential: fd.get('credential') || ''
          };
          await apiJson('/api/doctor/profile', {
            method: 'PUT',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(payload)
          });
          state.doctorProfile = Object.assign({}, state.doctorProfile, payload);
          showMessage('Doctor profile updated.', false);
        } catch (err) { showMessage(err.message, true); }
      });
    }

    var docAstSel = root.querySelector('#pfDocAstSel');
    if (docAstSel) {
      docAstSel.addEventListener('change', async function () {
        state.selectedPatientId = docAstSel.value;
        state.selectedPatientData = await apiJson('/api/profile/' + encodeURIComponent(state.selectedPatientId));
        render();
      });
    }

    var reqForm = root.querySelector('#pfReqAstForm');
    if (reqForm) {
      reqForm.addEventListener('submit', async function (e) {
        e.preventDefault();
        try {
          await apiJson('/api/doctor/requests', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
              target_id: root.querySelector('#pfReqTarget').value,
              mission_crew_note: root.querySelector('#pfReqNote').value,
              consent: root.querySelector('#pfReqConsent').checked
            })
          });
          state.doctorAstronauts = await apiJson('/api/doctor/astronauts');
          showMessage('Access request sent. Status is pending until approved by the astronaut.', false);
        } catch (err) { showMessage(err.message, true); }
      });
    }

    var pwdForm = root.querySelector('#pfPwdForm');
    if (pwdForm) {
      pwdForm.addEventListener('submit', async function (e) {
        e.preventDefault();
        try {
          await apiJson('/api/auth/password', {
            method: 'PUT',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
              current_password: root.querySelector('#pfCurPwd').value,
              new_password: root.querySelector('#pfNewPwd').value,
              confirm_password: root.querySelector('#pfConfPwd').value
            })
          });
          pwdForm.reset();
          showMessage('Password updated cleanly. All other sessions revoked.', false);
        } catch (err) { showMessage(err.message, true); }
      });
    }

    var loAll = root.querySelector('#pfLogoutAllBtn');
    if (loAll) {
      loAll.addEventListener('click', async function () {
        await apiJson('/api/auth/logout-all', { method: 'POST' });
        window.location.href = '/login.html';
      });
    }
  }

  function render() {
    renderBoardingPass();
    var root = document.getElementById('pfApp');
    if (!root || !state.session) return;

    var tabs = state.session.role === 'doctor'
      ? ['Doctor info', 'My astronauts', 'Security']
      : ['Personal', 'Health', 'Flight', 'Songs & Photos', 'Access', 'Security'];
    if (tabs.indexOf(state.tab) === -1) state.tab = tabs[0];

    var pendingBadge = state.accessRequests.filter(function (r) { return r.status === 'pending'; }).length;
    var tabHtml = tabs.map(function (t) {
      var label = t === 'Access' && pendingBadge > 0 ? t + ' (' + pendingBadge + ')' : t;
      return '<button type="button" class="pill-btn ' + (t === state.tab ? 'active' : '') + '" data-pf-tab="' + esc(t) + '">' + esc(label) + '</button>';
    }).join('');

    var bodyHtml = state.session.role === 'doctor' ? renderDoctorBody() : renderAstronautBody();
    root.innerHTML =
      '<span class="eyebrow">' + esc(state.session.role === 'doctor' ? 'MEDICAL CREDENTIALS & CREW' : 'ASTRONAUT PROFILE & PRIVACY') + '</span>' +
      '<h1>My <span>Profile</span></h1>' +
      '<div class="pills pf-tabs">' + tabHtml + '</div>' +
      msgBoxHtml() +
      bodyHtml;

    root.querySelectorAll('[data-pf-tab]').forEach(function (btn) {
      btn.addEventListener('click', function () {
        state.tab = btn.dataset.pfTab;
        state.msg = null;
        render();
      });
    });
    wireFormHandlers(root);
  }

  function wireRevokeModal() {
    var modal = document.getElementById('pfRevokeModal');
    var close = function () { modal.classList.remove('show'); state.pendingRevokeId = null; };
    document.getElementById('pfRevokeClose').onclick = close;
    document.getElementById('pfRevokeCancel').onclick = close;
    document.getElementById('pfRevokeConfirm').onclick = async function () {
      if (!state.pendingRevokeId) return close();
      try {
        await apiJson('/api/access/requests/' + state.pendingRevokeId + '/revoke', { method: 'POST' });
        var acc = await apiJson('/api/access/requests');
        state.accessRequests = acc.requests || [];
        if (window.VV_SHELL && window.VV_SHELL.refreshSession) window.VV_SHELL.refreshSession();
        close();
        showMessage('Doctor access revoked.', false);
      } catch (err) {
        close();
        showMessage(err.message, true);
      }
    };
  }

  (async function init() {
    wireRevokeModal();
    var sess = await window.VV_SHELL.getSession();
    if (!sess || !sess.authenticated) {
      if (sess && sess.backendAvailable) {
        window.location.href = '/login.html';
      }
      return;
    }
    state.session = sess;
    if (sess.role === 'astronaut' && sess.user && sess.user.astronaut_id) {
      var aid = sess.user.astronaut_id;
      var res = await Promise.all([
        apiJson('/api/profile/' + encodeURIComponent(aid)),
        apiJson('/api/access/requests')
      ]);
      state.astroData = res[0];
      state.accessRequests = res[1].requests || [];
      state.tab = (window.location.hash === '#access') ? 'Access' : 'Personal';
      window.addEventListener('hashchange', function () {
        if (window.location.hash === '#access' && state.tab !== 'Access') {
          state.tab = 'Access';
          render();
        }
      });
    } else if (sess.role === 'doctor') {
      var dres = await Promise.all([
        apiJson('/api/doctor/profile'),
        apiJson('/api/doctor/astronauts')
      ]);
      state.doctorProfile = dres[0];
      state.doctorAstronauts = dres[1] || { approved: [], pending: [] };
      if (state.doctorAstronauts.approved && state.doctorAstronauts.approved.length) {
        state.selectedPatientId = state.doctorAstronauts.approved[0].id;
        state.selectedPatientData = await apiJson('/api/profile/' + encodeURIComponent(state.selectedPatientId));
      }
      state.tab = 'Doctor info';
    }
    render();
  })();
})();
