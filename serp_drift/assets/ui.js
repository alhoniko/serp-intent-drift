/* Shared formatting and marks for the app views: status pills, capture strips and charts, score contributions, intent mix. */
window.SerpUI = (() => {
  'use strict';
  const I = (name, cls) => window.SerpIcons.get(name, cls);
  const esc = (v) => String(v ?? '').replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' })[c]);
  const safeUrl = (v) => { try { const u = new URL(v); return ['http:', 'https:'].includes(u.protocol) && !u.username ? esc(u.href) : '#'; } catch { return '#'; } };
  const host = (v) => { try { return new URL(v).hostname.replace(/^www\./, ''); } catch { return ''; } };
  const hostPath = (v) => { try { const u = new URL(v); return (u.hostname.replace(/^www\./, '') + u.pathname.replace(/\/$/, '') + (u.search || '')); } catch { return v || ''; } };
  const pathOnly = (v) => { try { const u = new URL(v); return (u.pathname.replace(/\/$/, '') || '/') + (u.search || ''); } catch { return v || ''; } };
  const TZ = { timeZone: 'UTC' };
  const D = (v) => v ? new Date(v).toLocaleDateString('en-GB', { day: 'numeric', month: 'short', ...TZ }) : '—';
  const T = (v) => v ? new Date(v).toLocaleTimeString('en-GB', { hour: '2-digit', minute: '2-digit', ...TZ }) : '—';
  const DT = (v) => v ? `${D(v)} ${T(v)}` : '—';
  const dayKey = (v) => (v || '').slice(0, 10);
  const today = () => new Date().toISOString().slice(0, 10);
  const dayLabel = (key) => { const t = today(); const y = new Date(Date.now() - 86400000).toISOString().slice(0, 10); const d = D(`${key}T12:00:00Z`); return key === t ? `Today · ${d}` : key === y ? `Yesterday · ${d}` : new Date(`${key}T12:00:00Z`).toLocaleDateString('en-GB', { weekday: 'long', day: 'numeric', month: 'short', ...TZ }); };
  const span = (ms) => { const m = Math.round(Math.abs(ms) / 60000); if (m < 60) return `${m} min`; const h = Math.floor(m / 60); if (h < 24) return `${h} h${m % 60 && h < 6 ? ` ${m % 60} min` : ''}`; const d = Math.round(h / 24); return `${d} day${d === 1 ? '' : 's'}`; };
  const ago = (v) => { if (!v) return '—'; const ms = Date.now() - new Date(v).getTime(); if (ms < 60000) return 'just now'; if (ms < 86400000) return `${span(ms)} ago`; const days = Math.round(ms / 86400000); return days === 1 ? 'yesterday' : `${days} days ago`; };
  const until = (v) => { if (!v) return ''; const ms = new Date(v).getTime() - Date.now(); return ms <= 60000 ? 'due now' : `in ${span(ms)}`; };
  const addHours = (iso, h) => iso ? new Date(new Date(iso).getTime() + h * 3600000).toISOString() : null;
  const pct = (v) => v == null ? '—' : `${Math.round(v * 100)} %`;
  const n = (v) => v == null ? '—' : Number(v).toLocaleString('en-US');
  const plural = (c, w, many) => `${n(c)} ${c === 1 ? w : (many || `${w}s`)}`;
  const ordinal = (k) => `${k}${['th', 'st', 'nd', 'rd'][(k % 100 > 10 && k % 100 < 14) ? 0 : Math.min(k % 10, 4) % 4] || 'th'}`;
  const cap = (s) => s ? s[0].toUpperCase() + s.slice(1) : s;

  const INTENTS = ['informational', 'commercial', 'transactional', 'navigational', 'unknown'];
  const FEATURES = { ai_overview: 'AI Overview', answer_box: 'Answer box', related_questions: 'People also ask', knowledge_graph: 'Knowledge graph', local_results: 'Local results', inline_videos: 'Videos', inline_shorts: 'Short videos', inline_images: 'Images', inline_shopping: 'Shopping', top_stories: 'Top stories', ads: 'Ads', discussions_and_forums: 'Discussions' };
  const COMPONENTS = [['url_turnover', 'URL turnover'], ['intent', 'Intent mix'], ['result_types', 'Result types'], ['features', 'SERP features'], ['rank_movement', 'Rank movement']];
  const WORDS = { review: 'Review', watch: 'Watch', stable: 'Stable', building_baseline: 'Building', baseline_ready: 'Baseline ready', awaiting_data: 'Awaiting data', insufficient_data: 'Sparse results', stale: 'Overdue', collection_error: 'Collection error', data_quality: 'Check data' };
  const BUILDING = ['building_baseline', 'baseline_ready', 'awaiting_data'];
  const ISSUES = ['collection_error', 'data_quality', 'insufficient_data', 'stale'];
  const REJECTED = ['query_mismatch', 'excluded', 'quarantined'];
  function kind(status) { return status === 'review' ? 'review' : status === 'watch' ? 'watch' : status === 'stable' ? 'stable' : BUILDING.includes(status) ? 'building' : ISSUES.includes(status) ? 'issue' : 'idle'; }
  function word(q) {
    const s = q?.status ?? q;
    if (s === 'building_baseline' && q?.baseline) return `Building ${q.baseline.length} / ${q.settings?.baseline_size ?? 3}`;
    return WORDS[s] || String(s || '').replace(/_/g, ' ');
  }
  const score = (v) => v == null ? '—' : Math.round(v);
  function pill(q, withScore = false) {
    const k = kind(q?.status ?? q);
    const label = `${word(q)}${withScore && q?.score != null ? ` · ${Math.round(q.score)}` : ''}${q?.paused ? ' · paused' : ''}`;
    return `<span class="pill ${k}">${k === 'issue' ? I('alert') : '<i></i>'}${esc(label)}</span>`;
  }
  const pillFor = (status) => pill({ status });
  function marketText(search, engines) {
    const s = search || {};
    return [engines?.[s.engine || 'google'] || 'Google', (s.gl || '').toUpperCase(), s.hl, s.device, s.location ? s.location.split(',')[0] : ''].filter(Boolean).join(' · ');
  }
  function marketTags(search, base, engines) {
    const s = search || {}; const b = base || {}; const out = [];
    if ((s.engine || 'google') !== (b.engine || 'google')) out.push(engines?.[s.engine] || s.engine);
    if (s.gl && b.gl && s.gl !== b.gl) out.push(s.gl.toUpperCase());
    if (s.hl && b.hl && s.hl !== b.hl) out.push(s.hl);
    if (s.device && s.device !== (b.device || 'desktop')) out.push(s.device);
    if (s.location) out.push(s.location.split(',')[0]);
    return out.map((t) => `<span class="tag">${esc(t)}</span>`).join('');
  }

  // --- captures --------------------------------------------------------------------------------------------------------
  function capKind(p) { if (REJECTED.includes(p.quality_state)) return 'x'; if (p.score == null) return p.phase === 'baseline' ? 'b' : (p.quality_ok === false ? 'x' : 'b'); return 's'; }
  function strip(timeline, { count = 12, threshold = 35, wide = false } = {}) {
    const pts = (timeline || []).slice(-count);
    if (!pts.length) return '<span class="strip"></span>';
    return `<span class="strip${wide ? ' wide' : ''}" aria-hidden="true">${pts.map((p) => { const k = capKind(p); if (k !== 's') return `<i class="${k}"></i>`; return `<i class="${p.score >= threshold ? 'w' : ''}" style="height:${Math.max(2, Math.round(p.score / 100 * (wide ? 20 : 22)))}px"></i>`; }).join('')}</span>`;
  }
  function captureTitle(p) {
    const k = capKind(p);
    const why = p.quality_state === 'query_mismatch' ? 'results for another query, not used' : p.quality_state === 'excluded' ? 'excluded by you' : p.quality_state === 'quarantined' ? 'quarantined' : p.quality_ok === false ? 'sparse capture, not used' : '';
    return `${DT(p.captured_at)} UTC · ${k === 's' ? `score ${Math.round(p.score)}` : k === 'b' ? 'baseline capture' : why}${p.intent ? ` · ${p.intent}` : ''}${p.site_position ? ` · your site #${p.site_position}` : ''}`;
  }
  function chart(timeline, settings, { height = 150, maxCols = 48, times = true, labelLast = 2 } = {}) {
    const all = timeline || [];
    if (!all.length) return '<div class="empty">No captures yet.</div>';
    const pts = all.slice(-maxCols);
    const th = settings?.drift_threshold ?? 35;
    const scored = pts.map((p, i) => [p, i]).filter(([p]) => capKind(p) === 's');
    const labelled = new Set(scored.slice(-labelLast).filter(([p]) => p.score >= th || scored.length <= 1).map(([, i]) => i));
    if (!labelled.size && scored.length) labelled.add(scored[scored.length - 1][1]);
    const firstBase = pts.findIndex((p) => capKind(p) === 'b');
    let prevDay = '';
    const xl = pts.map((p, i) => { const d = dayKey(p.captured_at); const show = d !== prevDay; prevDay = d; return `<span class="${i === pts.length - 1 ? '' : ''}">${show ? esc(D(p.captured_at)) : '&nbsp;'}${times ? `<small>${esc(T(p.captured_at))}</small>` : ''}</span>`; }).join('');
    const cols = pts.map((p, i) => {
      const k = capKind(p); const title = esc(captureTitle(p));
      if (k === 'x') return `<div class="c" title="${title}"><span class="x">${I('x')}</span></div>`;
      if (k === 'b') return `<div class="c base" title="${title}">${i === firstBase ? '<span class="baselbl">baseline</span>' : ''}<i class="m"></i></div>`;
      const h = Math.max(2, Math.round(p.score)); const cls = p.score >= th ? 'over' : '';
      return `<div class="c" title="${title}">${labelled.has(i) ? `<span class="v" style="bottom:calc(${h}% + 3px)">${Math.round(p.score)}</span>` : ''}<i class="b ${cls}" style="height:${h}%"></i></div>`;
    }).join('');
    const g = pts.length > 30 ? 3 : pts.length > 18 ? 5 : 6;
    return `<div class="chart" style="--h:${height}px;--g:${g}px"><div class="plot" role="img" aria-label="Change score for each capture; threshold ${th}">${cols}<div class="thr" style="bottom:${th}%"><span>watch at ${th}</span></div></div><div class="xl">${xl}</div>${all.length > pts.length ? `<div class="note">Showing the latest ${pts.length} of ${all.length} captures.</div>` : ''}</div>`;
  }
  const chartKey = (timeline) => { const has = (k) => (timeline || []).some((p) => capKind(p) === k); return `<span class="chart-key">${has('b') ? '<span><i class="base"></i>baseline window</span>' : ''}<span><i></i>score</span><span><i class="over"></i>at or over the threshold</span>${has('x') ? `<span>${I('x')}not used</span>` : ''}</span>`; };

  // --- score explanation --------------------------------------------------------------------------------------------------
  function contributions(components, weights) {
    return COMPONENTS.map(([key, label]) => { const d = components ? components[key] : null; const w = weights?.[key] ?? 0; return { key, label, weight: w, distance: d, points: d == null ? null : d * w * 100 }; })
      .sort((a, b) => (b.points ?? -1) - (a.points ?? -1));
  }
  function contribBar(list, threshold) {
    let rank = 0;
    const segs = list.filter((c) => c.points).map((c) => `<i class="c${Math.min(4, ++rank)}" style="width:${c.points.toFixed(2)}%" title="${esc(c.label)} +${c.points.toFixed(1)}"></i>`).join('');
    return `<div class="contrib" role="img" aria-label="${esc(list.map((c) => `${c.label} ${c.points == null ? 'n/a' : c.points.toFixed(1)}`).join(', '))}">${segs}<i class="rest"></i>${threshold != null ? `<span class="tick" style="left:${threshold}%" title="watch at ${threshold}"></span>` : ''}</div>`;
  }
  function contribLegend(list) {
    let rank = 0;
    return `<div class="contrib-legend">${list.map((c) => c.points == null ? `<span class="na"><i class="sw c0"></i>${esc(c.label)} <b>n/a</b></span>` : `<span><i class="sw c${c.points ? Math.min(4, ++rank) : 0}"></i>${esc(c.label)} <b>+${c.points.toFixed(1)}</b></span>`).join('')}</div>`;
  }
  function avgMix(list, field = 'intent_distribution') { const out = {}; (list || []).forEach((s) => Object.entries(s[field] || {}).forEach(([k, v]) => { out[k] = (out[k] || 0) + v / list.length; })); return out; }
  function mixBar(mix) { const keys = INTENTS.filter((k) => (mix[k] || 0) > 0.004).sort((a, b) => (mix[b] || 0) - (mix[a] || 0)); return `<span class="bar">${keys.map((k) => `<i class="${k}" style="flex:${(mix[k] * 100).toFixed(1)}" title="${k} ${pct(mix[k])}"></i>`).join('') || '<i class="unknown" style="flex:1"></i>'}</span>`; }
  function mixHtml(before, after, labels = ['Baseline', 'Latest'], notes = ['', '']) {
    const keys = INTENTS.filter((k) => (before?.[k] || 0) > 0.004 || (after?.[k] || 0) > 0.004).sort((a, b) => ((after?.[b] || 0) + (before?.[b] || 0)) - ((after?.[a] || 0) + (before?.[a] || 0)));
    return `<div class="mix">${before ? `<span>${esc(labels[0])}</span>${mixBar(before)}<span>${esc(notes[0])}</span>` : ''}${after ? `<span>${esc(labels[1])}</span>${mixBar(after)}<span>${esc(notes[1])}</span>` : ''}</div><div class="mix-legend">${keys.map((k) => `<span><i class="sw ${k}"></i>${k} ${before && after ? `${Math.round((before[k] || 0) * 100)} → ${Math.round((after[k] || 0) * 100)} %` : pct((after || before)[k])}</span>`).join('')}</div>`;
  }

  // --- your site, reasons, next capture -------------------------------------------------------------------------------
  // A 0.6 server returns no per-capture site position: take the current one from q.site and infer nothing from the history.
  const hasTrack = (q) => (q?.timeline || []).some((p) => 'site_position' in p);
  function siteTrack(q) {
    const pts = (q?.timeline || []).filter((p) => capKind(p) !== 'x');
    if (!hasTrack(q)) return { now: q?.site?.position || null, url: q?.site?.url || null, ever: q?.site?.position ? 1 : 0, captures: pts.length, partial: true };
    const last = pts[pts.length - 1];
    const seen = pts.filter((p) => p.site_position);
    const now = last?.site_position || null;
    const out = { now, url: q?.site?.url || last?.site_url || null, ever: seen.length, captures: pts.length };
    if (!now && seen.length) { const lastSeen = seen[seen.length - 1]; const idx = pts.indexOf(lastSeen); out.dropped = true; out.was = lastSeen.site_position; out.url = lastSeen.site_url; out.leftAt = pts[idx + 1]?.captured_at; out.heldFrom = Math.min(...seen.map((p) => p.site_position)); out.heldTo = Math.max(...seen.map((p) => p.site_position)); out.heldCount = seen.length; }
    const prev = pts.length > 1 ? pts[pts.length - 2].site_position : null;
    if (now && prev && now !== prev) { out.moved = true; out.from = prev; }
    if (now && !prev && pts.length > 1) out.entered = true;
    if (q?.site?.ranking_url_changed) out.urlChanged = q.site.previous_url;
    return out;
  }
  function positions(q, count = 10) { return hasTrack(q) ? (q.timeline || []).filter((p) => capKind(p) !== 'x').slice(-count).map((p) => p.site_position || null) : []; }
  function cellsHtml(list) { return `<div class="cells">${list.map((v) => `<i class="${v == null ? '' : v <= 3 ? 'b1' : v <= 6 ? 'b2' : 'b3'}">${v == null ? '–' : v}</i>`).join('')}</div>`; }
  function flapInfo(events, id, days = 7) {
    const since = Date.now() - days * 86400000;
    const list = (events || []).filter((e) => e.kind === 'status_change' && e.target_id === id && new Date(e.at).getTime() >= since);
    const toWatch = list.filter((e) => e.payload?.after === 'watch');
    const recent = list.filter((e) => new Date(e.at).getTime() >= Date.now() - 3 * 86400000);
    return { changes: list.length, recent: recent.length, watches: toWatch.length, first: toWatch.length ? toWatch[toWatch.length - 1].at : null };
  }
  function whyLine(q, events) {
    const parts = []; const s = siteTrack(q); const cmp = q.comparison; const cov = q.latest?.classified_coverage;
    if (cmp) { const tu = cmp.components?.url_turnover; const ent = (cmp.entered || []).length; if (tu != null && tu >= 0.99 && ent) parts.push('Top 10 replaced'); else if (ent) parts.push(`${ent} new in the top 10`); }
    if (s.dropped) parts.push(`your page dropped out (was #${s.was})`); else if (s.moved) parts.push(`your page #${s.from} → #${s.now}`); else if (s.entered) parts.push(`your page entered at #${s.now}`); else if (s.urlChanged) parts.push('your ranking URL changed');
    const f = flapInfo(events, q.id);
    if (f.watches >= 2 && q.status === 'watch') parts.push(`watch for the ${ordinal(f.watches)} time since ${D(f.first)}`);
    if ((cmp?.features_added || []).length && parts.length < 2) parts.push(`${FEATURES[cmp.features_added[0]] || cmp.features_added[0]} appeared`);
    if (cov != null && cov < 0.5 && parts.length < 3) parts.push(`${pct(cov)} classified`);
    if (!parts.length) parts.push(q.decision?.title || word(q));
    return cap(parts.join(' · '));
  }
  function nextCapture(q) { if (q?.collection_ended) return null; const at = q?.last_attempt?.attempted_at || q?.latest?.captured_at; return at ? addHours(at, q?.settings?.interval_hours ?? 24) : null; }
  function verdictText(q) {
    const out = []; const cmp = q.comparison; const s = siteTrack(q); const lat = q.latest || {};
    if (cmp) { const ent = (cmp.entered || []).length; const ex = (cmp.exited || []).length; const tu = cmp.components?.url_turnover; if (tu != null && tu >= 0.99 && ent) out.push(`All ${ent} results in the latest capture are new since the baseline; ${ex} left.`); else if (ent || ex) out.push(`${ent} ${ent === 1 ? 'result' : 'results'} entered and ${ex} left since the baseline.`); }
    const dom = lat.dominant_intent; const base = q.baseline_intent;
    if (dom && base && dom !== 'unknown' && dom === base && q.status !== 'review') out.push(`The mix stays mostly ${dom} (${pct(lat.intent_distribution?.[dom])} of rank weight), so the change cannot confirm a review on its own.`);
    else if (dom && base && dom !== base && q.status !== 'review') out.push(`The estimated intent moved from ${base} to ${dom}; a review needs spaced captures that agree.`);
    if (s.dropped) out.push(`Your page ${hostPath(s.url)} left the top 10 after ${plural(s.heldCount, 'capture')} at #${s.heldFrom}${s.heldTo !== s.heldFrom ? `–#${s.heldTo}` : ''}.`);
    else if (s.moved) out.push(`Your page moved from #${s.from} to #${s.now}.`);
    else if (s.urlChanged) out.push(`Your ranking URL changed from ${hostPath(s.urlChanged)} to ${hostPath(s.url)}.`);
    return out.join(' ');
  }
  function hbar(label, value, max, { extra = '', mine = false, suffix = '', note = '' } = {}) {
    return `<div class="hbar${mine ? ' mine' : ''}"><span class="l"><span>${esc(label)}</span>${mine ? '<span class="tag you">your site</span>' : ''}${note}</span><span class="t"><i style="width:${max ? Math.max(2, Math.round(value / max * 100)) : 0}%"></i></span><span class="v">${esc(String(value))}${suffix}</span>${extra ? `<span class="s">${extra}</span>` : ''}</div>`;
  }
  const kbd = (k) => `<span class="kbd">${esc(k)}</span>`;
  const MOD = /mac|iphone|ipad/i.test(navigator.userAgentData?.platform || navigator.platform || '') ? '⌘' : 'Ctrl';

  return { I, esc, safeUrl, host, hostPath, pathOnly, D, T, DT, dayKey, dayLabel, ago, until, addHours, pct, n, plural, ordinal, cap, INTENTS, FEATURES, COMPONENTS, BUILDING, ISSUES, REJECTED, kind, word, score, pill, pillFor, marketText, marketTags, capKind, strip, chart, chartKey, captureTitle, contributions, contribBar, contribLegend, avgMix, mixBar, mixHtml, siteTrack, positions, cellsHtml, flapInfo, whyLine, nextCapture, verdictText, hbar, kbd, MOD };
})();
