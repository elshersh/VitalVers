/* =========================================================
   Vitalverse – dashboard.js
   Shared real-API logic for astronaut-dashboard.html and doctor-dashboard.html.
   Role and authorized astronaut(s) always come from server-side /api/auth/me.
   ========================================================= */
(function () {
  'use strict';

  const CONFIG = {
    granularity: 'daily',
    historyDays: 180,
    lineColors: ['#a8e07a', '#e4f7c8', '#ffffff', '#9aa0a6', '#f5c451', '#ff8a7a', '#6fd3c6', '#8ab4f8', '#d7aeff', '#f79c5b']
  };

  const STATUS = {
    normal: { label: 'Normal', rank: 0, color: '#a8e07a' },
    watch: { label: 'Monitor', rank: 1, color: '#f5c451' },
    alert: { label: 'Attention', rank: 2, color: '#ff7a6b' }
  };

  const METRICS = [
    {
      id: 'hr', name: 'Heart Rate', short: 'Heart Rate', unit: 'bpm', decimals: 0,
      about: 'Resting heart rate beats per minute.',
      channels: [{ key: 'value', label: 'Heart rate' }],
      thresholds: { watch: 10, alert: 20, direction: 'both' },
      trendMin: 1.5, sigChange: 5
    },
    {
      id: 'bp', name: 'Blood Pressure', short: 'Blood Pressure', unit: 'mmHg', decimals: 0,
      about: 'The force of blood against artery walls (systolic / diastolic).',
      channels: [
        { key: 'sys', label: 'Systolic' },
        { key: 'dia', label: 'Diastolic' }
      ],
      thresholds: { watch: 7, alert: 12, direction: 'both' },
      trendMin: 1.5, sigChange: 4
    },
    {
      id: 'spo2', name: 'Oxygen Saturation', short: 'SpO2', unit: '%', decimals: 1, max: 100,
      about: 'Blood oxygen saturation percentage.',
      channels: [{ key: 'value', label: 'SpO2' }],
      thresholds: { watch: 2, alert: 4, direction: 'low' },
      trendMin: 0.5, sigChange: 1.5
    },
    {
      id: 'temp', name: 'Body Temperature', short: 'Temp', unit: '°C', decimals: 1,
      about: 'Core body temperature in degrees Celsius.',
      channels: [{ key: 'value', label: 'Body temp' }],
      thresholds: { watch: 1.5, alert: 3, direction: 'both' },
      trendMin: 0.4, sigChange: 1.0
    },
    {
      id: 'glucose', name: 'Blood Glucose', short: 'Glucose', unit: 'mg/dL', decimals: 0,
      about: 'Fasting blood glucose concentration.',
      channels: [{ key: 'value', label: 'Blood glucose' }],
      thresholds: { watch: 15, alert: 30, direction: 'both' },
      trendMin: 3, sigChange: 8
    },
    {
      id: 'sleep', name: 'Sleep Monitoring', short: 'Sleep', unit: 'hours', decimals: 1, max: 12,
      about: 'Daily sleep duration compared with your Pre-Mission Baseline.',
      channels: [{ key: 'value', label: 'Sleep hours' }],
      thresholds: { watch: 12, alert: 22, direction: 'low' },
      trendMin: 2, sigChange: 6
    },
    {
      id: 'activity', name: 'Physical Activity', short: 'Activity', unit: 'min', decimals: 0,
      about: 'Daily countermeasure exercise duration in minutes.',
      channels: [{ key: 'value', label: 'Activity min' }],
      thresholds: { watch: 20, alert: 35, direction: 'both' },
      trendMin: 4, sigChange: 12
    },
    {
      id: 'mood', name: 'Psychological State / Mood', short: 'Mood', unit: '/ 100', decimals: 0, max: 100,
      about: 'Mood score on a 0–100 scale (daily check-in score x 20 when logged, otherwise telemetry mood value).',
      channels: [{ key: 'value', label: 'Mood score' }],
      thresholds: { watch: 8, alert: 16, direction: 'low' },
      trendMin: 1.5, sigChange: 5
    },
    {
      id: 'immune', name: 'Immune System', short: 'Immune', unit: '/ 100', decimals: 0, max: 100,
      about: 'An index of immune-system markers. Higher is stronger.',
      channels: [{ key: 'value', label: 'Immune index' }],
      thresholds: { watch: 8, alert: 15, direction: 'low' },
      trendMin: 1.5, sigChange: 5
    },
    {
      id: 'bone', name: 'Bone Health', short: 'Bone', unit: '% index', decimals: 2,
      about: 'Estimated bone-density index compared with the start of the mission.',
      channels: [{ key: 'value', label: 'Bone index' }],
      thresholds: { watch: 1, alert: 2, direction: 'low' },
      trendMin: 0.05, sigChange: 0.3
    }
  ];

  const STATUS_NOTE = {
    watch: 'Worth keeping an eye on over the next few days.',
    alert: 'Please inform the medical team and follow the medical monitoring protocol.'
  };

  function esc(str) {
    return window.VV_SHELL ? window.VV_SHELL.esc(str) : String(str || '');
  }

  /* =======================================================
     CALCULATIONS
     ======================================================= */
  const mean = a => a.length ? a.reduce((s, x) => s + x, 0) / a.length : 0;
  const std = a => {
    if (!a.length) return 0;
    const mu = mean(a);
    return Math.sqrt(mean(a.map(x => (x - mu) ** 2)));
  };
  const pct = (value, ref) => (ref ? ((value - ref) / ref) * 100 : 0);
  const metricById = id => METRICS.find(m => m.id === id);

  function signed(x, digits) {
    const d = digits === undefined ? (Math.abs(x) < 1 ? 2 : 1) : digits;
    return (x > 0 ? '+' : x < 0 ? '−' : '') + Math.abs(x).toFixed(d) + '%';
  }

  function statusFor(metric, dev) {
    const t = metric.thresholds;
    const effective = t.direction === 'low' ? Math.max(0, -dev)
      : t.direction === 'high' ? Math.max(0, dev)
      : Math.abs(dev);
    if (effective >= t.alert) return 'alert';
    if (effective >= t.watch) return 'watch';
    return 'normal';
  }

  function formatReading(metric, values) {
    return values.map(v => Number(v).toFixed(metric.decimals)).join('/');
  }

  function summarizeMetric(ast, m) {
    const chs = ast.series[m.id].channels;
    const N = chs[0].values.length;
    const slice = (arr, n, offset) => arr.slice(Math.max(0, N - n - (offset || 0)), Math.max(0, N - (offset || 0)));
    const p = chs[0];
    const cur = p.values[N - 1];
    const prev = N > 1 ? p.values[N - 2] : cur;
    const wk = mean(slice(p.values, 7));
    const prevWkSlice = slice(p.values, 7, 7);
    const prevWk = prevWkSlice.length ? mean(prevWkSlice) : wk;
    const dev = pct(cur, p.baseline);
    const channels = chs.map(c => ({
      label: c.label,
      baseline: c.baseline,
      current: c.values[N - 1],
      latest: c.values[N - 1]
    }));
    return {
      metric: m,
      current: cur,
      baseline: p.baseline,
      dev,
      status: statusFor(m, dev),
      trend: pct(cur, prev),
      weekChange: pct(wk, prevWk),
      channels,
      currentText: formatReading(m, channels.map(c => c.current)),
      latestText: formatReading(m, channels.map(c => c.latest)),
      baselineText: formatReading(m, channels.map(c => c.baseline))
    };
  }

  function summarizeAstronaut(ast) {
    const metrics = {};
    METRICS.forEach(m => { metrics[m.id] = summarizeMetric(ast, m); });
    const list = Object.values(metrics);
    const counts = { normal: 0, watch: 0, alert: 0 };
    list.forEach(s => counts[s.status]++);
    const overall = counts.alert ? 'alert' : counts.watch ? 'watch' : 'normal';
    return { metrics, counts, overall };
  }

  function hydrateAstronautFromApi(dashPayload, predPayload) {
    const a = dashPayload.astronaut || {};
    const times = (dashPayload.times || []).map(ts => new Date(ts));
    const missionDays = dashPayload.mission_days || times.map((_, idx) => idx + 1);
    const rawSeries = dashPayload.series || {};
    const series = {};

    METRICS.forEach(m => {
      const apiMetric = rawSeries[m.id] || { channels: [] };
      const channels = m.channels.map((mc, idx) => {
        const apiCh = apiMetric.channels[idx] || {};
        return {
          key: mc.key,
          label: mc.label,
          baseline: Number(apiCh.baseline || 0),
          values: (apiCh.values || []).map(Number),
          sources: apiCh.sources || null,
          schemaBadge: apiCh.schema_badge || 'Placeholder'
        };
      });
      series[m.id] = { channels };
    });

    const prediction = predPayload && predPayload.predictions
      ? {
          model_version: predPayload.model_version,
          selected_architecture: predPayload.selected_architecture,
          latest: predPayload.latest,
          history: predPayload.predictions
        }
      : (dashPayload.prediction || null);

    const ast = {
      id: a.id,
      name: a.name || a.id,
      initials: a.initials || 'VV',
      role: a.role || 'Crew Member',
      mission: a.mission || 'Orbital Mission',
      age: a.age || '--',
      missionDay: a.missionDay || times.length,
      totalDays: a.totalDays || times.length,
      flightSurgeon: a.flightSurgeon || '',
      times,
      missionDays,
      series,
      prediction
    };
    ast.summary = summarizeAstronaut(ast);
    return ast;
  }

  function getSeries(ast, m, range, cutoffDays) {
    const N = Math.min(ast.times.length, cutoffDays || ast.times.length);
    const fmtDay = d => d.toLocaleDateString('en-US', { month: 'short', day: 'numeric' });
    const count = range === 'week' ? Math.min(N, 7)
      : range === 'month' ? Math.min(N, 30)
      : N;
    const start = Math.max(0, N - count);
    const indices = [];
    for (let i = start; i < N; i++) indices.push(i);
    return {
      labels: indices.map(i => fmtDay(ast.times[i])),
      fullLabels: indices.map(i => 'Day ' + (ast.missionDays[i] || (i + 1)) + ' · ' + fmtDay(ast.times[i])),
      channels: ast.series[m.id].channels.map(c => ({
        key: c.key,
        label: c.label,
        baseline: c.baseline,
        values: indices.map(i => c.values[i]),
        sources: c.sources ? indices.map(i => c.sources[i]) : null
      }))
    };
  }

  const timeText = ast => ast.times.length
    ? ast.times[ast.times.length - 1].toLocaleString('en-GB', { day: 'numeric', month: 'short', year: 'numeric' })
    : '--';

  /* =======================================================
     ADVICE & CLINICAL INSIGHTS
     ======================================================= */
  const ADVICE = {
    hr: {
      up: { title: 'Heart rate is above your baseline',
        body: 'Your heart rate is {pct} above your Pre-Mission Baseline. Please follow the medical monitoring protocol: rest, drink water and avoid strenuous activity until it settles.',
        tips: ['Take a few minutes of slow, relaxed breathing', 'Note any dizziness, chest discomfort or unusual tiredness', 'Report it to the medical team if it stays elevated'] },
      down: { title: 'Heart rate is below your baseline',
        body: 'Your heart rate is {pct} below your Pre-Mission Baseline. Keep following the medical monitoring protocol and let the medical team know if you feel faint or unusually tired.',
        tips: ['Stand up slowly after resting', 'Note any dizziness or fatigue', 'Share the reading at your next medical check-in'] }
    },
    bp: {
      up: { title: 'Blood pressure is above your baseline',
        body: 'Your blood pressure is {pct} higher than your Pre-Mission Baseline. Follow the medical monitoring protocol and take it easy until the next reading.',
        tips: ['Rest quietly for a few minutes before re-measuring', 'Stay hydrated and follow your nutrition plan', 'Report headaches or vision changes to the medical team'] },
      down: { title: 'Blood pressure is below your baseline',
        body: 'Your blood pressure is {pct} lower than your Pre-Mission Baseline. Follow the medical monitoring protocol and report any lightheadedness.',
        tips: ['Change position slowly', 'Make sure you are drinking enough fluids', 'Share the reading at your next medical check-in'] }
    },
    spo2: {
      down: { title: 'Oxygen saturation is below baseline',
        body: 'Your SpO2 is {pct} lower than your Pre-Mission Baseline. Verify pulse oximeter placement and notify the flight surgeon if persistent.',
        tips: ['Re-check finger sensor warmth and position', 'Take calm, deep breaths and rest', 'Confirm cabin O2/CO2 telemetry with crew'] }
    },
    temp: {
      up: { title: 'Body temperature is elevated',
        body: 'Your temperature is {pct} higher than your Pre-Mission Baseline. Monitor for early signs of infection or heat strain.',
        tips: ['Hydrate steadily and rest', 'Check for cough, chills or fatigue', 'Log another reading at your next check-in'] },
      down: { title: 'Body temperature is below baseline',
        body: 'Your temperature is {pct} below your Pre-Mission Baseline. Verify sensor reading and cabin thermal comfort.',
        tips: ['Re-check with a clean measurement', 'Adjust suit or cabin thermal layers'] }
    },
    glucose: {
      up: { title: 'Blood glucose is above baseline',
        body: 'Your blood glucose is {pct} above your Pre-Mission Baseline. Review recent meal timing and hydration.',
        tips: ['Note meal timing before measurement', 'Keep hydration steady', 'Follow medical monitoring protocol if elevated'] },
      down: { title: 'Blood glucose is below baseline',
        body: 'Your blood glucose is {pct} below your Pre-Mission Baseline. Follow crew nutrition and monitoring guidance.',
        tips: ['Have a balanced scheduled snack if approved', 'Report any lightheadedness or shakiness'] }
    },
    sleep: {
      down: { title: 'Sleep quality has dropped',
        body: 'Your sleep quality is {pct} below your Pre-Mission Baseline. Small routine changes can help.',
        tips: ['Keep a consistent sleep and wake time', 'Dim lights and reduce screen time an hour before sleep', 'Keep your sleeping area quiet and comfortable', 'Limit caffeine in the hours before bed'] }
    },
    activity: {
      down: { title: 'Activity is lower than usual',
        body: 'Your activity level is {pct} below your Pre-Mission Baseline. Regular exercise matters in space, so try to get back on your exercise plan.',
        tips: ['Schedule short sessions rather than skipping the day', 'Follow your crew exercise plan (resistance and cardio)', 'Tell the medical team if something is preventing you from exercising'] },
      up: { title: 'Activity is higher than usual',
        body: 'Your activity level is {pct} above your Pre-Mission Baseline. Make sure you are balancing exercise with rest and nutrition.',
        tips: ['Plan recovery time between sessions', 'Keep up fluids and meals', 'Mention any aches or strain at your next check-in'] }
    },
    mood: {
      down: { title: 'Mood score is lower than usual',
        body: 'Your mood score is {pct} below your Pre-Mission Baseline. Long missions can be demanding, and support is available.',
        tips: ['Schedule a video call with family or friends', 'Spend some time on a hobby or something relaxing', 'Consider a check-in with the psychological support team'] }
    },
    immune: {
      down: { title: 'Immune index is lower than usual',
        body: 'Your immune index is {pct} below your Pre-Mission Baseline. Rest, nutrition and hygiene all support your body.',
        tips: ['Prioritize sleep and regular meals', 'Keep up good hand and surface hygiene', 'Report fever, cough or other symptoms right away'] }
    },
    bone: {
      down: { title: 'Bone index is lower than expected',
        body: 'Your bone-health index is {pct} below your starting value. Exercise and nutrition are key to protecting bone in microgravity.',
        tips: ['Do not skip your resistance-exercise sessions', 'Follow the nutrition and supplement plan set by the medical team', 'Ask about your next scheduled bone assessment'] }
    }
  };

  const fill = (text, vars) => text.replace(/\{(\w+)\}/g, (_, k) => vars[k]);

  function adviceFor(ast) {
    const cards = [];
    METRICS.forEach(m => {
      const s = ast.summary.metrics[m.id];
      if (s.status === 'normal') return;
      const dir = s.dev >= 0 ? 'up' : 'down';
      const t = (ADVICE[m.id] && (ADVICE[m.id][dir] || ADVICE[m.id].down || ADVICE[m.id].up));
      if (!t) return;
      cards.push({
        status: s.status,
        metric: m,
        rank: STATUS[s.status].rank,
        absDev: Math.abs(s.dev),
        title: t.title,
        body: fill(t.body, { pct: Math.abs(s.dev).toFixed(Math.abs(s.dev) < 1 ? 2 : 1) + '%' }) + ' ' + STATUS_NOTE[s.status],
        tips: t.tips,
        basis: `Based on: latest daily reading ${s.currentText} ${m.unit} vs. Pre-Mission Baseline ${s.baselineText} ${m.unit} (${signed(s.dev)}).`
      });
    });
    cards.sort((a, b) => b.rank - a.rank || b.absDev - a.absDev);
    return cards;
  }

  function attentionList(ast) {
    return METRICS.map(m => ast.summary.metrics[m.id])
      .filter(s => s.status !== 'normal')
      .sort((a, b) => STATUS[b.status].rank - STATUS[a.status].rank || Math.abs(b.dev) - Math.abs(a.dev));
  }

  function significantChanges(ast) {
    return METRICS.map(m => ast.summary.metrics[m.id])
      .filter(s => Math.abs(s.weekChange) >= s.metric.sigChange)
      .sort((a, b) => Math.abs(b.weekChange / b.metric.sigChange) - Math.abs(a.weekChange / a.metric.sigChange));
  }

  function crossInsights(ast) {
    const sm = ast.summary.metrics;
    const off = (id, dir) => sm[id].status !== 'normal' && (dir === 'up' ? sm[id].dev > 0 : sm[id].dev < 0);
    const out = [];
    if (off('hr', 'up') && off('bp', 'up'))
      out.push('Heart rate and blood pressure are both above baseline at the same time. Consider a cardiovascular review and check workload, hydration and stress factors.');
    if (off('sleep', 'down') && off('mood', 'down'))
      out.push('Lower sleep quality coincides with a lower mood score. A combined sleep and psychological-support review may be useful.');
    if (off('sleep', 'down') && off('hr', 'up'))
      out.push('Reduced sleep quality alongside a raised heart rate may point to accumulated fatigue or stress. Review rest schedule and workload.');
    if (off('immune', 'down') && (off('sleep', 'down') || off('mood', 'down')))
      out.push('A lower immune index appears together with reduced sleep or mood. Consider recovery support and screen for infection symptoms.');
    if (off('activity', 'down') && off('bone', 'down'))
      out.push('Reduced activity coincides with a lower bone index. Review adherence to the exercise countermeasure plan.');
    if (!out.length) {
      out.push(attentionList(ast).length
        ? 'Flagged metrics look isolated: cross-metric rules found no combined pattern.'
        : `No concerning cross-metric patterns found. All ${METRICS.length} metrics are close to this astronaut's baseline.`);
    }
    return out;
  }

  function followUps(ast) {
    const items = [];
    attentionList(ast).forEach(s => {
      items.push(s.status === 'alert'
        ? { status: 'alert', text: `Review ${s.metric.name} with the astronaut within 24 hours (${signed(s.dev)} vs. baseline).` }
        : { status: 'watch', text: `Re-check ${s.metric.name} at the next scheduled review (${signed(s.dev)} vs. baseline).` });
    });
    if (items.some(i => i.status === 'alert'))
      items.push({ status: 'watch', text: 'Confirm sensor calibration and data quality before making clinical decisions.' });
    if (!items.length)
      items.push({ status: 'normal', text: 'Continue the routine monitoring schedule. No immediate follow-up flagged.' });
    return items;
  }

  /* =======================================================
     CHART BUILDERS
     ======================================================= */
  const charts = {};
  function drawChart(canvasId, config) {
    const canvas = document.getElementById(canvasId);
    if (!canvas || typeof Chart === 'undefined') return;
    if (charts[canvasId]) charts[canvasId].destroy();
    charts[canvasId] = new Chart(canvas, config);
  }

  function setupChartDefaults() {
    if (typeof Chart === 'undefined') return;
    Chart.defaults.color = '#9a9aa2';
    Chart.defaults.font.family = "'Inter', system-ui, sans-serif";
    Chart.defaults.font.size = 12;
    Chart.defaults.borderColor = 'rgba(255,255,255,0.07)';
  }

  const tooltipStyle = {
    backgroundColor: '#111', borderColor: 'rgba(255,255,255,0.2)', borderWidth: 1,
    titleColor: '#fff', bodyColor: '#cfcfd4', padding: 10, boxPadding: 4
  };

  function lineConfig(m, series, range) {
    const datasets = [];
    series.channels.forEach((ch, i) => {
      const color = CONFIG.lineColors[i];
      const multi = series.channels.length > 1;
      datasets.push({
        label: multi ? ch.label : 'Current data',
        data: ch.values, borderColor: color, backgroundColor: color + '1f',
        fill: !multi, tension: 0.3, borderWidth: 2,
        pointRadius: range === 'week' ? 3 : 0, pointHoverRadius: 5
      });
      datasets.push({
        label: multi ? ch.label + ' baseline' : 'Pre-Mission Baseline',
        data: ch.values.map(() => ch.baseline), borderColor: i === 0 ? 'rgba(255,255,255,0.55)' : 'rgba(228,247,200,0.45)',
        borderDash: [6, 5], borderWidth: 1.5, pointRadius: 0, pointHoverRadius: 0, fill: false
      });
    });
    return {
      type: 'line',
      data: { labels: series.labels, datasets },
      options: {
        responsive: true, maintainAspectRatio: false,
        interaction: { mode: 'index', intersect: false },
        plugins: {
          legend: { position: 'top', align: 'end', labels: { usePointStyle: true, boxWidth: 8, boxHeight: 8 } },
          tooltip: {
            ...tooltipStyle,
            callbacks: {
              title: items => series.fullLabels[items[0].dataIndex],
              label: c => `${c.dataset.label}: ${c.parsed.y.toFixed(m.decimals)} ${m.unit}`,
              afterLabel: c => {
                if (m.id === 'mood' && c.datasetIndex === 0 && series.channels[0].sources) {
                  return 'Source: ' + (series.channels[0].sources[c.dataIndex] || 'simulated data');
                }
                return '';
              }
            }
          }
        },
        scales: {
          x: { grid: { display: false }, ticks: { maxTicksLimit: 10, maxRotation: 0 } },
          y: { title: { display: true, text: m.unit }, ticks: { callback: v => Number(v.toFixed(m.decimals)) } }
        }
      }
    };
  }

  function deviationConfig(ast) {
    const list = METRICS.map(m => ast.summary.metrics[m.id]);
    return {
      type: 'bar',
      data: {
        labels: list.map(s => s.metric.short),
        datasets: [{
          data: list.map(s => Number(s.dev.toFixed(2))),
          backgroundColor: list.map(s => STATUS[s.status].color),
          borderRadius: 6, maxBarThickness: 22
        }]
      },
      options: {
        indexAxis: 'y', responsive: true, maintainAspectRatio: false,
        plugins: {
          legend: { display: false },
          tooltip: {
            ...tooltipStyle,
            callbacks: {
              label: c => {
                const s = list[c.dataIndex];
                return [`${signed(s.dev)} vs. baseline`, `${s.currentText} ${s.metric.unit} (baseline ${s.baselineText})`, `Status: ${STATUS[s.status].label}`];
              }
            }
          }
        },
        scales: {
          x: { title: { display: true, text: '% change vs. Pre-Mission Baseline' } },
          y: { grid: { display: false } }
        }
      }
    };
  }

  function multiLineConfig(ast, range, cutoffDays) {
    const datasets = METRICS.map((m, i) => {
      const ser = getSeries(ast, m, range, cutoffDays);
      const ch = ser.channels[0];
      return {
        label: m.short, data: ch.values.map(v => Number(pct(v, ch.baseline).toFixed(2))),
        borderColor: CONFIG.lineColors[i % CONFIG.lineColors.length],
        backgroundColor: CONFIG.lineColors[i % CONFIG.lineColors.length],
        borderWidth: 2, tension: 0.3, pointRadius: range === 'week' ? 3 : 0, pointHoverRadius: 5
      };
    });
    const ser0 = getSeries(ast, METRICS[0], range, cutoffDays);
    return {
      type: 'line',
      data: { labels: ser0.labels, datasets },
      options: {
        responsive: true, maintainAspectRatio: false,
        interaction: { mode: 'index', intersect: false },
        plugins: {
          legend: { position: 'top', align: 'end', labels: { usePointStyle: true, boxWidth: 8, boxHeight: 8 } },
          tooltip: {
            ...tooltipStyle,
            callbacks: {
              title: items => ser0.fullLabels[items[0].dataIndex],
              label: c => `${c.dataset.label}: ${signed(c.parsed.y)}`
            }
          }
        },
        scales: {
          x: { grid: { display: false }, ticks: { maxTicksLimit: 10, maxRotation: 0 } },
          y: {
            title: { display: true, text: '% change vs. baseline' },
            grid: { color: c => c.tick.value === 0 ? 'rgba(255,255,255,0.5)' : 'rgba(255,255,255,0.07)' },
            ticks: { callback: v => v + '%' }
          }
        }
      }
    };
  }

  /* =======================================================
     RENDERING
     ======================================================= */
  const ROLE = (typeof document !== 'undefined' && document.body) ? document.body.dataset.role : 'astronaut';
  const $ = id => document.getElementById(id);

  let CREW_LIST = [];
  const AST_CACHE = {};

  const state = {
    ast: null,
    section: null,
    metricId: 'hr',
    metricRange: 'mission',
    historyMetric: 'hr',
    historyRange: 'mission',
    replayDay: CONFIG.historyDays
  };

  const pillHtml = (status, large) =>
    `<span class="pill pill-${esc(status)}${large ? ' pill-lg' : ''}"><i></i>${esc(STATUS[status].label)}</span>`;

  function modelPillHtml(prediction, fallbackStatus, large) {
    if (prediction && prediction.status_label) {
      const st = prediction.ui_status || fallbackStatus || 'normal';
      return `<span class="pill pill-${esc(st)}${large ? ' pill-lg' : ''}" id="${large ? 'modelStatusPill' : ''}"><i></i>${esc(prediction.status_label)}</span>`;
    }
    return pillHtml(fallbackStatus || 'normal', large);
  }

  function trendHtml(s) {
    const m = s.metric;
    if (Math.abs(s.trend) < m.trendMin) return '► Steady <span>vs. previous day</span>';
    const arrow = s.trend > 0 ? '▲' : '▼';
    return `${arrow} ${Math.abs(s.trend).toFixed(Math.abs(s.trend) < 1 ? 2 : 1)}% <span>vs. previous day</span>`;
  }

  function metricCardHtml(s) {
    const m = s.metric;
    return `
      <article class="card metric-card s-${s.status}">
        <div class="card-top"><span class="metric-name">${esc(m.name)}</span>${pillHtml(s.status)}</div>
        <div class="metric-value">${esc(s.currentText)}<span class="unit">${esc(m.unit)}</span></div>
        <div class="metric-sub">Baseline ${esc(s.baselineText)} ${esc(m.unit)} · ${esc(signed(s.dev))}</div>
        <div class="trend">${trendHtml(s)}</div>
      </article>`;
  }

  function overallSentence(ast, who) {
    const c = ast.summary.counts;
    const latest = ast.prediction && ast.prediction.latest;
    const predNote = latest
      ? `AI model prediction for Day ${latest.mission_day}: ${latest.status_label} (${(latest.confidence * 100).toFixed(1)}% confidence). `
      : '';
    if (!c.alert && !c.watch) return `${predNote}All ${METRICS.length} health metrics are close to ${who} Pre-Mission Baseline.`;
    const parts = [];
    if (c.alert) parts.push(`${c.alert} metric${c.alert > 1 ? 's need' : ' needs'} attention`);
    if (c.watch) parts.push(`${c.watch} ${c.watch > 1 ? 'are' : 'is'} worth monitoring`);
    return predNote + parts.join(' and ') + '. The other ' + (METRICS.length - c.alert - c.watch) + ' are stable.';
  }

  function overallHtml(ast, who) {
    const strip = METRICS.map(m => {
      const s = ast.summary.metrics[m.id];
      return `<span><i class="dot dot-${s.status}"></i>${esc(m.short)}</span>`;
    }).join('');
    const latest = ast.prediction && ast.prediction.latest;
    const modelVer = (ast.prediction && ast.prediction.model_version) || 'health_model';
    return `
      <div>
        <div class="eyebrow">Health Status / Alerts (AI Model · ${esc(modelVer)})</div>
        <div class="overall-title">${modelPillHtml(latest, ast.summary.overall, true)}</div>
        <p class="muted">${esc(overallSentence(ast, who))}</p>
      </div>
      <div class="status-strip">${strip}</div>`;
  }

  function setSegActive(id, value) {
    document.querySelectorAll('#' + id + ' button').forEach(b => b.classList.toggle('active', b.dataset.range === value));
  }

  function singleMetricTable(ast, m, range) {
    const ser = getSeries(ast, m, range);
    const rows = [];
    for (let i = ser.labels.length - 1; i >= 0; i--) {
      const vals = ser.channels.map(c => c.values[i]);
      const base = ser.channels[0];
      const dev = pct(vals[0], base.baseline);
      const st = statusFor(m, dev);
      rows.push(`<tr><td>${esc(ser.fullLabels[i])}</td><td>${esc(formatReading(m, vals))} <small>${esc(m.unit)}</small></td><td>${esc(signed(dev))}</td><td>${pillHtml(st)}</td></tr>`);
    }
    return `<table><thead><tr><th>Date</th><th>Daily reading</th><th>vs. baseline</th><th>Status</th></tr></thead><tbody>${rows.join('')}</tbody></table>`;
  }

  function plainText(s) {
    const n = s.metric.name;
    if (s.status === 'normal') return `Your ${n} is close to your Pre-Mission Baseline. Nothing to do but keep up your routine.`;
    if (s.status === 'watch') return `Your ${n} is somewhat different from your Pre-Mission Baseline. It is worth keeping an eye on.`;
    return `Your ${n} differs noticeably from your Pre-Mission Baseline. Please follow the medical monitoring protocol.`;
  }

  function statsHtml(ast, m, series) {
    const s = ast.summary.metrics[m.id];
    const rows = [
      ['Pre-Mission Baseline', `${s.baselineText} ${m.unit}`],
      ['Difference', signed(s.dev)],
      ['Status', pillHtml(s.status)]
    ];
    if (ROLE === 'doctor') {
      const vals = series.channels[0].values;
      const t = m.thresholds;
      rows.splice(1, 0, ['Latest reading', `${s.latestText} ${m.unit}`]);
      rows.push(
        ['Period average', `${mean(vals).toFixed(m.decimals + 1)} ${m.unit.split(' ')[0]}`],
        ['Period min / max', `${Math.min(...vals).toFixed(m.decimals)} / ${Math.max(...vals).toFixed(m.decimals)}`],
        ['Std. deviation', std(vals).toFixed(m.decimals + 1)],
        ['7-day change', signed(s.weekChange)],
        ['Thresholds', `Monitor ${t.watch}% · Attention ${t.alert}%${t.direction === 'both' ? '' : ' (' + t.direction + ' side)'}`]
      );
    }
    return `
      <div class="stat-label">Latest daily reading</div>
      <div class="stat-big">${esc(s.currentText)}<span class="unit">${esc(m.unit)}</span></div>
      ${rows.map(r => `<div class="stat-row"><span>${esc(r[0])}</span><b>${r[0] === 'Status' ? r[1] : esc(r[1])}</b></div>`).join('')}
      ${ROLE === 'astronaut' ? `<p class="plain">${esc(plainText(s))}</p>` : ''}
      <p class="about">${esc(m.about)}</p>`;
  }

  function detailTableHtml(ast, range) {
    const rows = METRICS.map(m => {
      const ser = getSeries(ast, m, range);
      const vals = ser.channels[0].values;
      const s = ast.summary.metrics[m.id];
      const d = m.decimals + 1;
      return `<tr>
        <td><b>${esc(m.name)}</b>${m.channels.length > 1 ? ' <small>(systolic)</small>' : ''}</td>
        <td>${esc(s.baselineText)} <small>${esc(m.unit)}</small></td>
        <td>${mean(vals).toFixed(d)}</td><td>${Math.min(...vals).toFixed(d)}</td><td>${Math.max(...vals).toFixed(d)}</td>
        <td>${std(vals).toFixed(d)}</td>
        <td class="c-${s.status === 'normal' ? '' : s.status}">${esc(signed(s.dev))}</td>
        <td>${pillHtml(s.status)}</td></tr>`;
    }).join('');
    return `<table><thead><tr><th>Metric</th><th>Baseline</th><th>Period avg</th><th>Min</th><th>Max</th><th>Std dev</th><th>Latest vs. baseline</th><th>Status</th></tr></thead><tbody>${rows}</tbody></table>`;
  }

  function renderExplorer() {
    const ast = state.ast;
    if (!ast) return;
    const m = metricById(state.metricId);
    $('metricChips').innerHTML = METRICS.map(x =>
      `<button class="chip${x.id === m.id ? ' active' : ''}" data-metric="${x.id}">${esc(x.short)}</button>`).join('');
    setSegActive('metricRange', state.metricRange);
    const series = getSeries(ast, m, state.metricRange);
    drawChart('metricChart', lineConfig(m, series, state.metricRange));
    $('metricStats').innerHTML = statsHtml(ast, m, series);
    if (ROLE === 'doctor') $('metricsDetailTable').innerHTML = detailTableHtml(ast, state.metricRange);
    else drawChart('deviationChart', deviationConfig(ast));
  }

  function renderAstronautOverview() {
    const ast = state.ast;
    if (!ast) return;
    $('overviewSubtitle').textContent = `${ast.name} (${ast.id}) · Mission Day ${ast.missionDay} of ${ast.totalDays} · Last updated ${timeText(ast)}`;
    $('overallStatus').innerHTML = overallHtml(ast, 'your');
    $('overviewCards').innerHTML = METRICS.map(m => metricCardHtml(ast.summary.metrics[m.id])).join('');
  }

  function renderAstronautHistory() {
    const ast = state.ast;
    if (!ast) return;
    const m = metricById(state.historyMetric);
    $('historyMetric').value = m.id;
    setSegActive('historyRange', state.historyRange);
    const series = getSeries(ast, m, state.historyRange);
    drawChart('historyChart', lineConfig(m, series, state.historyRange));
    const vals = series.channels[0].values;
    const d = m.decimals;
    $('historySummary').innerHTML = [
      ['Average', mean(vals).toFixed(d)], ['Lowest', Math.min(...vals).toFixed(d)],
      ['Highest', Math.max(...vals).toFixed(d)], ['Baseline', series.channels[0].baseline.toFixed(d)]
    ].map(x => `<div><span class="stat-label">${esc(x[0])}${m.channels.length > 1 ? ' (systolic)' : ''}</span><b>${esc(x[1])} <span class="unit">${esc(m.unit)}</span></b></div>`).join('');
    $('historyTable').innerHTML = singleMetricTable(ast, m, state.historyRange);
  }

  function renderAstronautAdvice() {
    const ast = state.ast;
    if (!ast) return;
    const cards = adviceFor(ast);
    if (!cards.length) {
      $('adviceList').innerHTML = `
        <article class="card advice-card s-normal" style="grid-column:1/-1">
          <div class="card-top"><span class="metric-name">All metrics</span>${pillHtml('normal')}</div>
          <h3>Everything looks steady</h3>
          <p>All ${METRICS.length} health metrics are close to your Pre-Mission Baseline. Keep up your sleep, exercise and nutrition routine, and continue your regular medical check-ins.</p>
        </article>`;
      return;
    }
    const stable = METRICS.length - cards.length;
    $('adviceList').innerHTML = cards.map(c => `
      <article class="card advice-card s-${c.status}">
        <div class="card-top"><span class="metric-name">${esc(c.metric.name)}</span>${pillHtml(c.status)}</div>
        <h3>${esc(c.title)}</h3>
        <p>${esc(c.body)}</p>
        <ul class="tips">${c.tips.map(t => `<li>${esc(t)}</li>`).join('')}</ul>
        <p class="basis">${esc(c.basis)}</p>
      </article>`).join('') + (stable ? `
      <article class="card advice-card s-normal">
        <div class="card-top"><span class="metric-name">Other metrics</span>${pillHtml('normal')}</div>
        <h3>The rest looks steady</h3>
        <p>The other ${stable} metric${stable > 1 ? 's are' : ' is'} close to your Pre-Mission Baseline. Keep up your routine.</p>
      </article>` : '');
  }

  function renderDoctorOverview() {
    const ast = state.ast;
    if (!ast) return;
    $('astronautList').innerHTML = '<h3>Approved Astronauts</h3>' + CREW_LIST.map(a => `
      <button class="ast-item${a.id === ast.id ? ' active' : ''}" data-id="${esc(a.id)}">
        <span class="avatar">${esc(a.initials)}</span>
        <span class="ast-meta"><b>${esc(a.name)}</b><small>${esc(a.id)} · ${esc(a.role)}</small></span>
        ${modelPillHtml(a.prediction, 'normal', false)}
      </button>`).join('');

    const rows = METRICS.map(m => {
      const s = ast.summary.metrics[m.id];
      return `<tr>
        <td><b>${esc(m.name)}</b></td>
        <td>${esc(s.latestText)} <small>${esc(m.unit)}</small></td>
        <td>${esc(s.currentText)}</td>
        <td>${esc(s.baselineText)}</td>
        <td class="c-${s.status === 'normal' ? '' : s.status}">${esc(signed(s.dev))}</td>
        <td>${trendHtml(s).replace(/<span>.*<\/span>/, '')}</td>
        <td>${pillHtml(s.status)}</td></tr>`;
    }).join('');

    const latestPred = ast.prediction && ast.prediction.latest;
    $('astronautDetail').innerHTML = `
      <div class="card">
        <div class="ast-head">
          <div>
            <h2>${esc(ast.name)} (${esc(ast.id)})</h2>
            <div class="ast-facts">
              <span><b>${esc(ast.role)}</b></span><span>Age <b>${esc(ast.age)}</b></span>
              <span>Mission Day <b>${esc(ast.missionDay)} / ${esc(ast.totalDays)}</b></span><span>Updated <b>${esc(timeText(ast))}</b></span>
            </div>
          </div>
          <div>
            <div class="eyebrow" style="margin-bottom:6px">Overall AI Model Status</div>
            ${modelPillHtml(latestPred, ast.summary.overall, true)}
          </div>
        </div>
        <p class="muted" style="font-size:.88rem">${esc(overallSentence(ast, 'their'))}</p>
      </div>
      <div class="card">
        <h3>Most recent measurements</h3>
        <div class="table-wrap"><table>
          <thead><tr><th>Metric</th><th>Latest</th><th>Daily reading</th><th>Baseline</th><th>Change</th><th>Trend</th><th>Status</th></tr></thead>
          <tbody>${rows}</tbody></table></div>
        <p class="chart-note">Blood pressure is shown as systolic/diastolic. Trend compares the latest day with the previous day.</p>
      </div>`;
  }

  function renderDoctorMetrics() {
    if (!state.ast) return;
    $('metricsSubtitle').textContent = `${state.ast.name} (${state.ast.id}) · current readings, trends and comparison with the Pre-Mission Baseline`;
    renderExplorer();
  }

  function renderDoctorHistory() {
    const ast = state.ast;
    if (!ast) return;
    const range = state.historyRange;
    const maxDay = ast.times.length;
    const cutoff = Math.max(1, Math.min(maxDay, state.replayDay || maxDay));
    const slider = $('missionDaySlider');
    const lbl = $('missionDayLabel');
    if (slider) {
      slider.max = String(maxDay);
      slider.value = String(cutoff);
      const pctFill = maxDay > 1 ? ((cutoff - 1) / (maxDay - 1)) * 100 : 100;
      slider.style.setProperty('--range-pct', pctFill.toFixed(1) + '%');
    }
    if (lbl) lbl.textContent = `Mission day ${cutoff} of ${maxDay}`;
    $('historySubtitle').textContent = `${ast.name} · Mission day ${cutoff} of ${maxDay} (Personal trend — illustrative %)`;
    setSegActive('historyRange', range);
    drawChart('historyChart', multiLineConfig(ast, range, cutoff));

    const all = METRICS.map(m => getSeries(ast, m, range, cutoff));
    const n = all[0].labels.length;
    const head = METRICS.map(m => `<th>${esc(m.short)}<br><small>${esc(m.unit)}</small></th>`).join('');
    const rows = [];
    for (let i = n - 1; i >= 0; i--) {
      const cells = METRICS.map((m, k) => {
        const chs = all[k].channels;
        const dev = pct(chs[0].values[i], chs[0].baseline);
        const st = statusFor(m, dev);
        return `<td class="${st === 'normal' ? '' : 'c-' + st}">${esc(formatReading(m, chs.map(c => c.values[i])))}</td>`;
      }).join('');
      rows.push(`<tr><td>${esc(all[0].fullLabels[i])}</td>${cells}</tr>`);
    }
    $('historyTable').innerHTML =
      `<table><thead><tr><th>Date</th>${head}</tr></thead><tbody>${rows.join('')}</tbody></table>`;
  }

  function renderDoctorInsights() {
    const ast = state.ast;
    if (!ast) return;
    $('insightsSubtitle').textContent = `${ast.name} (${ast.id}) · alerts, significant changes and suggested follow-up`;

    const alerts = attentionList(ast);
    $('alertsList').innerHTML = alerts.length ? alerts.map(s => `
      <div class="list-item"><i class="dot dot-${s.status}"></i><div>
        <b>${esc(s.metric.name)} ${pillHtml(s.status)}</b>
        <p>Daily reading ${esc(s.currentText)} ${esc(s.metric.unit)} is ${esc(signed(s.dev))} vs. baseline ${esc(s.baselineText)}.
        Thresholds: Monitor ${s.metric.thresholds.watch}%, Attention ${s.metric.thresholds.alert}%.</p>
      </div></div>`).join('') : '<p class="list-empty">No alerts. All metrics are within the configured thresholds.</p>';

    const changes = significantChanges(ast);
    $('changesList').innerHTML = changes.length ? changes.map(s => `
      <div class="list-item"><i class="dot dot-${Math.abs(s.weekChange) >= s.metric.sigChange * 2 ? 'alert' : 'watch'}"></i><div>
        <b>${esc(s.metric.name)}: ${esc(signed(s.weekChange))}</b>
        <p>7-day average compared with the previous 7 days (flag level ±${s.metric.sigChange}%).</p>
      </div></div>`).join('') : '<p class="list-empty">No significant week-over-week changes.</p>';

    $('insightsList').innerHTML = crossInsights(ast).map(t => `
      <div class="list-item"><i class="dot dot-normal"></i><div><p>${esc(t)}</p></div></div>`).join('');

    $('followupList').innerHTML = followUps(ast).map(f => `
      <div class="list-item"><i class="dot dot-${f.status}"></i><div><p>${esc(f.text)}</p></div></div>`).join('');
  }

  /* =======================================================
     UI & API LOADING
     ======================================================= */
  function renderCurrent() {
    const id = state.section;
    if (!id || !state.ast) return;
    if (ROLE === 'astronaut') {
      if (id === 'overview') renderAstronautOverview();
      if (id === 'metrics') renderExplorer();
      if (id === 'history') renderAstronautHistory();
      if (id === 'advice') renderAstronautAdvice();
    } else {
      if (id === 'overview') renderDoctorOverview();
      if (id === 'metrics') renderDoctorMetrics();
      if (id === 'history') renderDoctorHistory();
      if (id === 'insights') renderDoctorInsights();
    }
  }

  function showSection(id) {
    const ids = Array.from(document.querySelectorAll('.dash-section')).map(s => s.id);
    if (!ids.includes(id)) id = ids[0];
    state.section = id;
    document.querySelectorAll('.dash-section').forEach(s => { s.hidden = s.id !== id; });
    document.querySelectorAll('#sectionTabs a').forEach(a => a.classList.toggle('active', a.dataset.section === id));
    renderCurrent();
  }

  function buildNotifications() {
    if (!state.ast) return;
    const items = [];
    attentionList(state.ast).forEach(s => items.push({ ast: state.ast, s }));
    items.sort((x, y) => STATUS[y.s.status].rank - STATUS[x.s.status].rank || Math.abs(y.s.dev) - Math.abs(x.s.dev));

    const bellList = document.getElementById('vvBellList');
    if (bellList && items.length) {
      bellList.innerHTML = items.slice(0, 8).map(it => {
        const cls = it.s.status === 'alert' ? 'vv-dropdown-item--danger' : it.s.status === 'watch' ? 'vv-dropdown-item--warn' : '';
        return `<a class="vv-dropdown-item ${cls}" href="${ROLE === 'doctor' ? '#insights' : '#advice'}" data-ast="${esc(it.ast.id)}">
          <strong>${ROLE === 'doctor' ? esc(it.ast.name) + ' · ' : ''}${esc(it.s.metric.name)}</strong> (${esc(signed(it.s.dev))} vs baseline)<br>
          <span>${esc(STATUS[it.s.status].label)}</span>
        </a>`;
      }).join('');
    }
  }

  function fetchAstronautBundle(aid) {
    if (AST_CACHE[aid]) return Promise.resolve(AST_CACHE[aid]);
    return Promise.all([
      fetch('/api/health/' + encodeURIComponent(aid) + '/dashboard', { credentials: 'same-origin' }),
      fetch('/api/astronauts/' + encodeURIComponent(aid) + '/predictions', { credentials: 'same-origin' })
    ]).then(([dashRes, predRes]) => {
      if (!dashRes.ok) throw new Error('Unable to load astronaut dashboard (' + dashRes.status + ')');
      return Promise.all([dashRes.json(), predRes.ok ? predRes.json() : Promise.resolve(null)]);
    }).then(([dashData, predData]) => {
      const hydrated = hydrateAstronautFromApi(dashData, predData);
      AST_CACHE[aid] = hydrated;
      return hydrated;
    });
  }

  function setAstronaut(id) {
    fetchAstronautBundle(id).then(ast => {
      state.ast = ast;
      state.replayDay = ast.times.length;
      const sel = $('astronautSelect');
      if (sel) sel.value = id;
      renderCurrent();
      buildNotifications();
    }).catch(err => {
      const box = $('loadError');
      if (box) {
        box.hidden = false;
        box.textContent = err.message || 'Failed to switch astronaut record.';
      }
    });
  }

  function setupPanels() {
    const bellList = document.getElementById('vvBellList');
    if (bellList) {
      bellList.addEventListener('click', e => {
        const b = e.target.closest('[data-ast]');
        if (!b) return;
        const dd = document.getElementById('vvBellDropdown');
        if (dd) dd.setAttribute('hidden', '');
      });
    }
  }

  function setupControls() {
    document.querySelectorAll('[data-range="day"]').forEach(b => { b.hidden = true; });

    $('metricChips').addEventListener('click', e => {
      const b = e.target.closest('[data-metric]');
      if (!b) return;
      state.metricId = b.dataset.metric;
      renderExplorer();
    });
    $('metricRange').addEventListener('click', e => {
      const b = e.target.closest('[data-range]');
      if (!b) return;
      state.metricRange = b.dataset.range;
      renderExplorer();
    });
    $('historyRange').addEventListener('click', e => {
      const b = e.target.closest('[data-range]');
      if (!b) return;
      state.historyRange = b.dataset.range;
      renderCurrent();
    });
    const slider = $('missionDaySlider');
    if (slider) {
      slider.addEventListener('input', e => {
        state.replayDay = Number(e.target.value) || CONFIG.historyDays;
        renderDoctorHistory();
      });
    }

    if (ROLE === 'astronaut') {
      $('historyMetric').innerHTML = METRICS.map(m => `<option value="${m.id}">${esc(m.name)}</option>`).join('');
      $('historyMetric').addEventListener('change', e => {
        state.historyMetric = e.target.value;
        renderAstronautHistory();
      });
    } else {
      $('astronautSelect').addEventListener('change', e => setAstronaut(e.target.value));
      $('astronautList').addEventListener('click', e => {
        const b = e.target.closest('[data-id]');
        if (b) setAstronaut(b.dataset.id);
      });
    }

    window.addEventListener('hashchange', () => showSection(location.hash.slice(1)));
  }

  function init() {
    if (typeof Chart === 'undefined') {
      const err = $('loadError');
      if (err) {
        err.hidden = false;
        err.textContent = 'Charts could not load (Chart.js is unavailable).';
      }
    }
    setupChartDefaults();
    setupControls();
    setupPanels();

    const getSess = (window.VV_SHELL && typeof window.VV_SHELL.getSession === 'function')
      ? window.VV_SHELL.getSession()
      : fetch('/api/auth/me', { credentials: 'same-origin' }).then(r => r.json());

    getSess.then(session => {
      if (!session || !session.authenticated || !session.user) {
        const box = $('loadError');
        if (box) {
          box.hidden = false;
          box.innerHTML = 'Sign in required to load live mission telemetry. <a href="/login.html" style="color:#a8e07a;text-decoration:underline;">Log in</a>';
        }
        return;
      }

      // This tab's account decides the page. A page made for another account (another tab's account, or one
      // mixed up by a forwarding relay) is swapped once for the right one, named by this tab's account.
      if (session.role && session.role !== ROLE) {
        let tried = false;
        try { tried = sessionStorage.getItem('vvRoleReload') === '1'; sessionStorage.setItem('vvRoleReload', '1'); } catch (e) {}
        if (!tried) {
          const base = '/health.html?_vv=' + Date.now().toString(36) + location.hash;
          location.replace(window.VV_ACCOUNT ? window.VV_ACCOUNT.pageUrl(base) : base);
          return;
        }
      }
      try { sessionStorage.removeItem('vvRoleReload'); } catch (e) {}
      document.addEventListener('vv:changed', onLiveChange);

      if (ROLE === 'astronaut') {
        const aid = session.user.astronaut_id;
        return fetchAstronautBundle(aid).then(ast => {
          state.ast = ast;
          state.replayDay = ast.times.length;
          buildNotifications();
          showSection(location.hash.slice(1));
        });
      }

      return fetch('/api/doctor/astronauts', { credentials: 'same-origin' })
        .then(r => {
          if (!r.ok) throw new Error('Doctor authorization required.');
          return r.json();
        })
        .then(docData => {
          CREW_LIST = docData.approved || [];
          const sel = $('astronautSelect');
          if (sel) {
            sel.innerHTML = CREW_LIST.map(a => `<option value="${esc(a.id)}">${esc(a.name)} (${esc(a.id)} · ${esc(a.role)})</option>`).join('');
          }
          if (!CREW_LIST.length) {
            const box = $('loadError');
            if (box) {
              box.hidden = false;
              box.textContent = 'No approved astronauts linked to your doctor account yet.';
            }
            return;
          }
          const firstId = CREW_LIST[0].id;
          return fetchAstronautBundle(firstId).then(ast => {
            state.ast = ast;
            state.replayDay = ast.times.length;
            if (sel) sel.value = firstId;
            buildNotifications();
            showSection(location.hash.slice(1));
          });
        });
    }).catch(err => {
      const box = $('loadError');
      if (box) {
        box.hidden = false;
        box.textContent = err.message || 'Unable to load mission dashboard data.';
      }
    });
  }

  // ---- live updates (static/js/shell.js): reload what changed, keep the open section and choices ----
  const LIVE_PARTS = ['access', 'health', 'profile', 'mood', 'alerts'];
  let liveRunning = null;
  let liveAgain = false;

  function reloadAstronaut(id) {
    const wasLatest = !state.ast || state.ast.id !== id || state.replayDay >= state.ast.times.length;
    delete AST_CACHE[id];
    return fetchAstronautBundle(id).then(ast => {
      state.ast = ast;
      if (wasLatest) state.replayDay = ast.times.length;
      const box = $('loadError');
      if (box && !box.hidden && /approved astronauts/.test(box.textContent)) box.hidden = true;
      buildNotifications();
      showSection(state.section || location.hash.slice(1));
    });
  }

  function reloadDoctorCrew() {
    return fetch('/api/doctor/astronauts', { credentials: 'same-origin' })
      .then(r => (r.ok ? r.json() : null))
      .then(docData => {
        if (!docData) return;
        CREW_LIST = docData.approved || [];
        if (!CREW_LIST.length) {
          // access ended: start over so no record of that astronaut stays on screen
          if (state.ast) location.reload();
          return;
        }
        const keep = state.ast && CREW_LIST.some(a => a.id === state.ast.id);
        const id = keep ? state.ast.id : CREW_LIST[0].id;
        const sel = $('astronautSelect');
        if (sel) {
          sel.innerHTML = CREW_LIST.map(a => `<option value="${esc(a.id)}">${esc(a.name)} (${esc(a.id)} · ${esc(a.role)})</option>`).join('');
          sel.value = id;
        }
        return reloadAstronaut(id);
      });
  }

  function onLiveChange(ev) {
    const parts = (ev && ev.detail && ev.detail.parts) || [];
    if (!parts.some(p => LIVE_PARTS.indexOf(p) !== -1)) return;
    if (liveRunning) { liveAgain = true; return; }
    const job = ROLE === 'doctor' ? reloadDoctorCrew() : (state.ast ? reloadAstronaut(state.ast.id) : Promise.resolve());
    liveRunning = Promise.resolve(job).catch(() => {}).then(() => {
      liveRunning = null;
      if (liveAgain) { liveAgain = false; onLiveChange({ detail: { parts: LIVE_PARTS } }); }
    });
  }

  const api = { CONFIG, METRICS, adviceFor, crossInsights, followUps, significantChanges };
  if (typeof module !== 'undefined' && module.exports) module.exports = api;
  if (typeof window !== 'undefined') {
    window.Vitalverse = api;
    if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', init);
    else init();
  }
})();
