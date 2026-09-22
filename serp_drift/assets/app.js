/* serp-drift app · calm redesign. Hash routes over the JSON API; no build step, no dependencies. */
(() => {
  'use strict';
  const $ = (id) => document.getElementById(id);
  const esc = (v) => String(v ?? '').replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' })[c]);
  const safeUrl = (v) => { try { const u = new URL(v); return ['http:', 'https:'].includes(u.protocol) && !u.username ? esc(u.href) : '#'; } catch { return '#'; } };
  const hostPath = (v) => { try { const u = new URL(v); return (u.hostname.replace(/^www\./, '') + u.pathname.replace(/\/$/, '') + (u.search || '')); } catch { return v || ''; } };
  const host = (v) => { try { return new URL(v).hostname.replace(/^www\./, ''); } catch { return ''; } };
  const D = (v, o = {}) => v ? new Date(v).toLocaleDateString('en-GB', { day: 'numeric', month: 'short', ...(o.year ? { year: 'numeric' } : {}), timeZone: 'UTC' }) : '—';
  const DT = (v) => v ? new Date(v).toLocaleString('en-GB', { day: 'numeric', month: 'short', hour: '2-digit', minute: '2-digit', timeZone: 'UTC' }) : '—';
  const T = (v) => v ? new Date(v).toLocaleTimeString('en-GB', { hour: '2-digit', minute: '2-digit', timeZone: 'UTC' }) : '—';
  const ago = (v) => { if (!v) return '—'; const days = Math.floor((Date.now() - new Date(v).getTime()) / 86400000); return days <= 0 ? 'today' : days === 1 ? 'yesterday' : `${days} days`; };
  const pct = (v) => v == null ? '—' : `${Math.round(v * 100)}%`;
  const n = (v) => v == null ? '—' : Number(v).toLocaleString('en-GB');
  const plural = (c, w) => `${c} ${w}${c === 1 ? '' : 's'}`;
  const addDays = (iso, days) => { const d = new Date(iso); d.setUTCDate(d.getUTCDate() + days); return d.toISOString(); };
  const INTENTS = ['informational', 'commercial', 'transactional', 'navigational', 'unknown'];
  const DEVICES = ['desktop', 'mobile', 'tablet'];
  // One select component: options are strings or [value, label] pairs; the chevron and colours come from app.css.
  const select = (attrs, options, value) => `<select ${attrs}>${options.map((o) => { const [v, label] = Array.isArray(o) ? o : [o, o]; return `<option value="${esc(v)}"${String(v) === String(value ?? '') ? ' selected' : ''}>${esc(label)}</option>`; }).join('')}</select>`;
  const healthKind = (p) => p ? ({ ok: 'ok', error: 'err', stale: 'hollow', muted: 'hollow' }[p.health_kind] || 'hollow') : 'hollow';
  const MOD = /mac|iphone|ipad/i.test(navigator.userAgentData?.platform || navigator.platform || '') ? '⌘' : 'Ctrl';
  const AGENT_ICON = '<svg viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><rect x="2.5" y="5" width="11" height="8" rx="2"/><path d="M8 5V2.5M5.5 13v1.5M10.5 13v1.5M2.5 8.5h-1M14.5 8.5h-1"/><circle cx="6" cy="9" r=".7" fill="currentColor" stroke="none"/><circle cx="10" cy="9" r=".7" fill="currentColor" stroke="none"/></svg>';
  const SEARCH_ICON = '<svg viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" aria-hidden="true"><circle cx="7" cy="7" r="4.5"/><path d="m10.5 10.5 3.5 3.5"/></svg>';
  const FEATURES = { ai_overview: 'AI Overview', answer_box: 'Answer box', related_questions: 'People also ask', knowledge_graph: 'Knowledge graph', local_results: 'Local results', inline_videos: 'Videos', inline_shorts: 'Short videos', inline_images: 'Images', inline_shopping: 'Shopping', top_stories: 'Top stories', ads: 'Ads', discussions_and_forums: 'Discussions' };
  const COMPONENTS = [['intent', 'Intent mix'], ['url_turnover', 'URL turnover'], ['result_types', 'Result types'], ['rank_movement', 'Rank movement'], ['features', 'SERP features']];
  const state = { status: null, portfolio: null, project: null, reports: new Map(), panels: new Map(), pollTimer: null, palette: { open: false, index: 0, items: [] } };

  // --- status helpers ------------------------------------------------------------------------------------------------
  function kind(status) { return { review: 'review', watch: 'watch', stable: 'ok', building_baseline: 'info', baseline_ready: 'info', awaiting_data: 'hollow', insufficient_data: 'hollow', stale: 'hollow', collection_error: 'err', data_quality: 'err' }[status] || 'hollow'; }
  function word(q) {
    const s = q.status || q;
    if (s === 'building_baseline' && q.baseline) return `Building ${q.baseline.length} / ${q.settings?.baseline_size ?? 3}`;
    return { review: 'Review', watch: 'Watch', stable: 'Stable', building_baseline: 'Building', baseline_ready: 'Baseline ready', awaiting_data: 'Awaiting data', insufficient_data: 'Sparse', stale: 'Stale', collection_error: 'Error', data_quality: 'Check data' }[s] || s;
  }
  const dot = (k) => `<i class="dot ${k}"></i>`;
  const statusHtml = (q) => `<span class="status ${kind(q.status)}">${dot(kind(q.status))}${esc(word(q))}${q.paused ? ' · paused' : ''}</span>`;
  const marketHtml = (search) => `<span class="market"><b>${esc(engineLabel(search.engine))}</b><span>${esc((search.gl || '').toUpperCase())} · ${esc(search.hl || '')}${search.device ? ` · ${esc(search.device)}` : ''}${search.location ? ` · ${esc(search.location.split(',')[0])}` : ''}</span></span>`;
  function engineLabel(engine) { return (state.status?.engines || {})[engine || 'google'] || 'Google'; }
  function scoreDelta(q) { const t = q.timeline || []; const scored = t.filter((p) => p.score != null); if (scored.length < 2) return null; return Math.round(scored[scored.length - 1].score - scored[scored.length - 2].score); }
  const deltaHtml = (d) => d == null ? '' : `<span class="delta ${d > 0 ? 'up' : d < 0 ? 'down' : 'flat'}">${d > 0 ? '+' : d < 0 ? '−' : ''}${Math.abs(d)}</span>`;
  function position(q) { if (q.site?.position) return { pos: q.site.position, url: q.site.url }; if (q.page_position && q.latest?.page) return { pos: q.page_position, url: q.latest.page.url }; return null; }
  const priority = { data_quality: 1, review: 0, collection_error: 1, stale: 2, watch: 3, insufficient_data: 4, baseline_ready: 5, building_baseline: 6, awaiting_data: 7, stable: 8 };
  const sortQueries = (qs) => [...qs].sort((a, b) => (priority[a.status] ?? 9) - (priority[b.status] ?? 9) || (b.score || 0) - (a.score || 0) || a.query.localeCompare(b.query));

  // --- plumbing --------------------------------------------------------------------------------------------------------
  async function api(path, options = {}) {
    const init = { method: options.method || 'GET', headers: { 'X-Requested-With': 'serp-drift' } };
    if (options.body !== undefined) { init.headers['Content-Type'] = options.raw ? 'text/plain; charset=utf-8' : 'application/json'; init.body = options.raw ? options.body : JSON.stringify(options.body); }
    const response = await fetch(path, init);
    let body = null;
    try { body = await response.json(); } catch { body = null; }
    if (!response.ok) throw new Error(body?.error || `${response.status} ${response.statusText}`);
    return body;
  }
  const P = (path) => `/api/p/${encodeURIComponent(state.project)}${path}`;
  function toast(message, error = false) { const el = document.createElement('div'); el.className = `toast${error ? ' error' : ''}`; el.textContent = message; $('toasts').appendChild(el); setTimeout(() => el.remove(), error ? 7000 : 3500); }
  const fail = (error) => { toast(error.message || String(error), true); console.error(error); };
  const go = (hash) => { location.hash = hash; };
  const route = () => { const [path, query] = location.hash.replace(/^#\/?/, '').split('?'); return { parts: path.split('/').filter(Boolean).map(decodeURIComponent), params: new URLSearchParams(query || '') }; };
  async function loadStatus() { state.status = await api('/api/status'); if (!state.project || !state.status.projects.some((p) => p.id === state.project)) state.project = state.status.project.id; }
  async function report(pid = state.project, fresh = false) { if (fresh || !state.reports.has(pid)) state.reports.set(pid, await api(`/api/p/${encodeURIComponent(pid)}/report`)); return state.reports.get(pid); }
  async function panelData(id, fresh = false) { const key = `${state.project}/${id}`; if (fresh || !state.panels.has(key)) state.panels.set(key, await api(P(`/panels/${encodeURIComponent(id)}`))); return state.panels.get(key); }
  function invalidate() { state.reports.clear(); state.panels.clear(); state.portfolio = null; }
  const projectRow = (pid = state.project) => (state.status?.projects || []).find((p) => p.id === pid);

  // --- collection + polling ---------------------------------------------------------------------------------------------
  async function collect(ids, force) {
    try { const result = await api(P('/collect'), { method: 'POST', body: { ids, force } }); toast(result.started ? (ids ? 'Collecting this panel…' : 'Collecting every due panel…') : 'A collection is already running.'); startPolling(); } catch (error) { fail(error); }
  }
  function startPolling() { if (!state.pollTimer) state.pollTimer = setInterval(pollRun, 3000); renderTopActions(); }
  async function pollRun() {
    try { await loadStatus(); } catch (error) { return fail(error); }
    const running = (state.status.projects || []).some((p) => p.running);
    renderTopActions();
    if (!running) { clearInterval(state.pollTimer); state.pollTimer = null; const last = projectRow()?.last_run; if (last) toast(last.error ? `Collection error: ${last.error}` : `${last.collected} collected · ${last.skipped} skipped · ${last.failed} failed`, Boolean(last.error || last.failed)); invalidate(); render(); }
  }

  // --- shell ------------------------------------------------------------------------------------------------------------
  function switcherHtml(id, current, row) {
    const label = current.portfolio ? '<span class="nowrap">All projects</span>' : `${dot(healthKind(row))}<span class="nowrap">${esc(row?.name || state.project)}</span>`;
    return `<div class="switcher-wrap"><button class="switcher" id="${id}" type="button" aria-haspopup="menu" aria-expanded="false" aria-label="Switch project">${label}<span class="caret">⌄</span></button><div class="menu" id="${id}-menu" role="menu" hidden></div></div>`;
  }
  function projectMenu(current) {
    const s = state.status; const items = [];
    if (s.multi_project) items.push({ href: '#/portfolio', label: 'All projects', meta: plural((s.projects || []).length, 'project'), active: current.portfolio, sepAfter: true });
    (s.projects || []).forEach((p) => items.push({ href: `#/p/${encodeURIComponent(p.id)}`, label: p.name, meta: p.attention ? `${p.attention} to review` : plural(p.panels, 'panel'), active: !current.portfolio && p.id === state.project, dotk: healthKind(p) }));
    if (s.projects_root) items.push({ href: '#/new-project', label: 'New project', muted: true, sepBefore: true });
    return items;
  }
  function bindMenu(id, items) {
    const button = $(id); const menu = $(`${id}-menu`);
    menu.innerHTML = items.map((i) => `${i.sepBefore ? '<div class="sep"></div>' : ''}<a role="menuitem" href="${i.href}"${i.active ? ' aria-current="true"' : ''}${i.muted ? ' class="muted"' : ''}>${i.dotk ? dot(i.dotk) : ''}<span class="nowrap">${esc(i.label)}</span>${i.meta ? `<span class="k">${esc(i.meta)}</span>` : ''}${i.active ? '<span class="check">✓</span>' : ''}</a>${i.sepAfter ? '<div class="sep"></div>' : ''}`).join('');
    const links = () => [...menu.querySelectorAll('a')];
    const open = (focus) => { menu.hidden = false; button.setAttribute('aria-expanded', 'true'); if (focus) (links().find((a) => a.hasAttribute('aria-current')) || links()[0])?.focus(); };
    const close = () => { menu.hidden = true; button.setAttribute('aria-expanded', 'false'); };
    button.addEventListener('click', () => (menu.hidden ? open(false) : close()));
    button.addEventListener('keydown', (e) => { if (e.key === 'ArrowDown') { e.preventDefault(); open(true); } });
    menu.addEventListener('keydown', (e) => { const l = links(); const i = l.indexOf(document.activeElement); if (e.key === 'ArrowDown') { e.preventDefault(); l[(i + 1) % l.length]?.focus(); } else if (e.key === 'ArrowUp') { e.preventDefault(); l[(i - 1 + l.length) % l.length]?.focus(); } else if (e.key === 'Escape') { close(); button.focus(); } });
  }
  document.addEventListener('click', (e) => { document.querySelectorAll('.switcher-wrap').forEach((w) => { const m = w.querySelector('.menu'); if (m && !m.hidden && !w.contains(e.target)) { m.hidden = true; w.querySelector('.switcher').setAttribute('aria-expanded', 'false'); } }); });
  function renderSidebar(current) {
    const s = state.status; const row = projectRow();
    const attention = row?.attention || 0;
    const items = current.portfolio ? [['#/portfolio', 'Portfolio', current.view === 'portfolio'], ['#/portfolio/insights', 'Insights', current.view === 'pinsights'], ['#/portfolio/runs', 'Runs', current.view === 'pruns']]
      : [[`#/p/${state.project}`, 'Overview', current.view === 'dashboard', attention], [`#/p/${state.project}/panels`, 'Panels', current.view === 'panels' || current.view === 'panel'], [`#/p/${state.project}/activity`, 'Activity', current.view === 'activity'], [`#/p/${state.project}/insights`, 'Insights', current.view === 'insights'], [`#/p/${state.project}/runs`, 'Runs', current.view === 'runs'], [`#/p/${state.project}/settings`, 'Settings', current.view === 'settings' || current.view === 'import']];
    const sched = s.scheduler; const nextAt = sched.enabled ? (current.portfolio ? sched.next_due_at : (sched.next_by_project || {})[state.project]) : null;
    $('sidebar').innerHTML = `<div class="brand"><i></i>serp-drift</div>
      ${switcherHtml('switcher', current, row)}
      <button class="search-btn" id="search-btn" type="button">${SEARCH_ICON}<span>Search panels…</span><kbd>${MOD} K</kbd></button>
      <nav class="nav">${items.map(([href, label, active, count]) => `<a href="${href}" ${active ? 'aria-current="page"' : ''}>${label}${count ? `<span class="count">${count}</span>` : ''}</a>`).join('')}</nav>
      <a class="connect" href="#/p/${encodeURIComponent(state.project)}/connect" ${current.view === 'connect' ? 'aria-current="page"' : ''}>${AGENT_ICON}<span>Connect agent</span></a>
      <div class="sidebar-foot"><span class="status">${dot(sched.enabled ? 'ok' : 'hollow')}${sched.enabled ? `Scheduler on${nextAt ? ` · next ${T(nextAt)} UTC` : ''}` : 'Scheduler off'}</span><span>${current.portfolio ? n((s.projects || []).reduce((a, p) => a + (p.credits_per_day || 0), 0)) : n(row?.credits_per_day)} requests / day, estimated maximum before retries</span><a href="#" id="theme-toggle">Theme: ${document.documentElement.dataset.theme || 'system'}</a></div>`;
    bindMenu('switcher', projectMenu(current));
    $('search-btn').addEventListener('click', openPalette);
    $('theme-toggle').addEventListener('click', (event) => { event.preventDefault(); cycleTheme(); });
    $('topbar-project').innerHTML = switcherHtml('switcher-m', current, row);
    bindMenu('switcher-m', projectMenu(current));
    $('sidebar').classList.remove('open'); $('scrim').hidden = true;
  }
  function renderTopActions() {
    const running = (state.status?.projects || []).some((p) => p.running);
    $('topbar-actions').innerHTML = `<button class="icon-btn" id="search-m" type="button" aria-label="Search">${SEARCH_ICON}</button><button class="btn primary small" id="collect-m" type="button" ${running ? 'disabled' : ''}>${running ? 'Collecting…' : 'Collect'}</button>`;
    $('search-m').addEventListener('click', openPalette);
    $('collect-m')?.addEventListener('click', () => collect(undefined, false));
    document.querySelectorAll('[data-collect]').forEach((button) => { button.disabled = running; button.textContent = running ? 'Collecting…' : button.dataset.collect; });
  }
  function cycleTheme() { const cur = document.documentElement.dataset.theme || 'system'; const next = { system: 'light', light: 'dark', dark: 'system' }[cur]; if (next === 'system') delete document.documentElement.dataset.theme; else document.documentElement.dataset.theme = next; try { localStorage.setItem('serp-drift-theme', next); } catch {} $('theme-toggle').textContent = `Theme: ${next}`; }
  try { const forced = new URLSearchParams(location.search).get('theme'); const saved = forced || localStorage.getItem('serp-drift-theme'); if (saved && saved !== 'system') document.documentElement.dataset.theme = saved; } catch {}
  $('menu-toggle').addEventListener('click', () => { $('sidebar').classList.toggle('open'); $('scrim').hidden = !$('sidebar').classList.contains('open'); });
  $('scrim').addEventListener('click', () => { $('sidebar').classList.remove('open'); $('scrim').hidden = true; });

  // --- palette (⌘K) ------------------------------------------------------------------------------------------------------
  async function openPalette() {
    const items = [];
    (state.status.projects || []).forEach((p) => items.push({ label: p.name, meta: `project · ${p.panels} panels`, href: `#/p/${encodeURIComponent(p.id)}` }));
    if (state.status.multi_project) items.push({ label: 'Portfolio', meta: 'all projects', href: '#/portfolio' });
    try { const rep = await report(); sortQueries(rep.queries).forEach((q) => items.push({ label: q.query, meta: `${word(q)} · ${engineLabel(q.search?.engine)} ${(q.search?.gl || '').toUpperCase()} ${q.search?.device || 'desktop'}${state.status.multi_project ? ` · ${projectRow()?.name || ''}` : ''}`, href: `#/p/${encodeURIComponent(state.project)}/panel/${encodeURIComponent(q.id)}` })); } catch {}
    state.palette = { open: true, index: 0, items, all: items };
    state.palette.returnFocus = document.activeElement; $('palette').hidden = false; $('palette').showModal(); $('palette-input').value = ''; renderPalette(); $('palette-input').focus();
  }
  function renderPalette() { const p = state.palette; $('palette-input').setAttribute('aria-activedescendant', p.items.length ? `jump-${p.index}` : ''); $('palette-list').innerHTML = p.items.slice(0, 40).map((item, i) => `<li id="jump-${i}" role="option" aria-selected="${i === p.index}" data-href="${esc(item.href)}"><span class="nowrap">${esc(item.label)}</span><span class="k">${esc(item.meta)}</span></li>`).join('') || '<li class="muted">No match</li>'; }
  function closePalette() { state.palette.open = false; $('palette').close(); $('palette').hidden = true; state.palette.returnFocus?.focus(); }
  $('palette-input').addEventListener('input', () => { const q = $('palette-input').value.trim().toLowerCase(); state.palette.items = state.palette.all.filter((i) => i.label.toLowerCase().includes(q) || i.meta.toLowerCase().includes(q)); state.palette.index = 0; renderPalette(); });
  $('palette-input').addEventListener('keydown', (event) => { const p = state.palette; if (event.key === 'ArrowDown') { p.index = Math.min(p.index + 1, p.items.length - 1); renderPalette(); event.preventDefault(); } else if (event.key === 'ArrowUp') { p.index = Math.max(p.index - 1, 0); renderPalette(); event.preventDefault(); } else if (event.key === 'Enter') { const item = p.items[p.index]; if (item) { closePalette(); go(item.href); } } else if (event.key === 'Escape') closePalette(); });
  $('palette-list').addEventListener('click', (event) => { const li = event.target.closest('li[data-href]'); if (li) { closePalette(); go(li.dataset.href); } });
  $('palette').addEventListener('cancel', (event) => { event.preventDefault(); closePalette(); });
  $('palette').addEventListener('click', (event) => { if (event.target === $('palette')) closePalette(); });
  document.addEventListener('keydown', (event) => { if ((event.metaKey || event.ctrlKey) && event.key.toLowerCase() === 'k') { event.preventDefault(); state.palette.open ? closePalette() : openPalette(); } if (event.key === 'Escape' && state.palette.open) closePalette(); if (!state.palette.open && (event.key === 'j' || event.key === 'k')) rowNav(event); });

  function rowNav(event) { if (event.target.matches('input, textarea, select') || event.metaKey || event.ctrlKey) return; const rows = [...document.querySelectorAll('a.gr')]; if (!rows.length) return; const idx = rows.indexOf(document.activeElement); const next = event.key === 'j' ? Math.min(idx + 1, rows.length - 1) : Math.max(idx - 1, 0); rows[next].focus(); }

  // --- attention list -------------------------------------------------------------------------------------------------
  function attentionHtml(items, withProject) {
    if (!items.length) return null;
    const dotKind = { review: 'review', error: 'err', stale: 'hollow', config: 'err' };
    const action = (a) => a.kind === 'config' ? { label: 'Fix →', href: `#/p/${encodeURIComponent(a.project || state.project)}/settings` } : a.kind === 'error' ? { label: 'Retry now', act: 'retry' } : a.kind === 'stale' ? { label: 'Collect now', act: 'collect' } : { label: 'Open →', href: `#/p/${encodeURIComponent(a.project || state.project)}/panel/${encodeURIComponent(a.panel)}` };
    return items.map((a) => { const act = action(a); return `<div class="attn">${dot(dotKind[a.kind] || 'hollow')}<div class="nowrap"><div class="title"><b>${esc(a.title)}</b><span class="secondary">${withProject ? esc(a.project_name || a.project) + ' · ' : ''}${esc(a.kind === 'review' ? 'review' : a.kind)}${a.at ? ` · ${ago(a.at)}` : ''}</span></div><div class="why">${esc(a.why)}</div></div>${act.href ? `<a class="act" href="${act.href}">${act.label}</a>` : `<button class="btn link act" type="button" data-attn-act="${act.act}" data-project="${esc(a.project || state.project)}" data-panel="${esc(a.panel || '')}">${act.label}</button>`}</div>`; }).join('');
  }
  function bindAttention(container) {
    container.querySelectorAll('[data-attn-act]').forEach((button) => button.addEventListener('click', async () => {
      const pid = button.dataset.project; const panel = button.dataset.panel;
      try { await api(`/api/p/${encodeURIComponent(pid)}/collect`, { method: 'POST', body: { ids: panel ? [panel] : undefined, force: true } }); toast('Collecting…'); startPolling(); } catch (error) { fail(error); }
    }));
  }

  // --- panels table -----------------------------------------------------------------------------------------------------
  function panelRows(queries, limit) {
    const cols = 'grid-template-columns:minmax(0,1.6fr) 130px 90px 200px 110px';
    const rows = queries.slice(0, limit || queries.length).map((q) => { const p = position(q); const d = scoreDelta(q); return `<a class="gr" href="#/p/${encodeURIComponent(state.project)}/panel/${encodeURIComponent(q.id)}" style="${cols}"><span class="q">${esc(q.query)}${q.group ? `<span class="tag">${esc(q.group)}</span>` : ""}<small class="block muted">${esc(q.baseline_intent)} → ${esc(q.latest?.dominant_intent || "pending")} · ${pct(q.latest?.classified_coverage)} classified</small></span>${statusHtml(q)}<span class="num">${q.score == null ? (q.status === 'building_baseline' && q.baseline ? `<span class="muted">${q.baseline.length} / ${q.settings.baseline_size}</span>` : '—') : Math.round(q.score)}${deltaHtml(d)}</span><span class="pos">${p ? `<b>#${p.pos}</b><span class="mono">${esc(hostPath(p.url))}</span>` : '<b>—</b><span class="mono muted">not ranking</span>'}</span><span class="right muted">${esc(ago(q.latest?.captured_at))}</span></a>`; }).join('');
    return `<div class="card grid-table"><div class="gh" style="${cols}"><span>Query</span><span>Status</span><span class="right">Score ↓</span><span>Your position · URL</span><span class="right">Last capture</span></div>${rows || '<div class="empty-card">No panels match.</div>'}${limit && queries.length > limit ? `<div class="gf"><span>${limit} of ${queries.length}</span><a href="#/p/${encodeURIComponent(state.project)}/panels">Show all</a></div>` : ''}</div>`;
  }
  function filterBar(id) { return `<div class="spacer"><span class="seg" id="${id}-seg">${['all', 'review', 'watch', 'quality', 'unknown', 'building', 'cited', 'ranking'].map((k) => `<button type="button" data-f="${k}" aria-pressed="${k === 'all'}">${{ all: 'All', review: 'Review', watch: 'Watch', quality: 'Data issues', unknown: 'Uncertain intent', building: 'Building', cited: 'Cited', ranking: 'Ranking' }[k]}</button>`).join('')}</span><input id="${id}-text" type="search" placeholder="Filter…" aria-label="Filter keywords" style="width:180px"><select id="${id}-group" aria-label="Keyword group"><option value="">All groups</option></select><select id="${id}-sort" aria-label="Sort keywords"><option value="priority">Priority</option><option value="query">Keyword A–Z</option><option value="coverage">Lowest coverage</option><option value="score">Highest change</option></select><button class="btn small" type="button" id="${id}-reset">Reset view</button></div>`; }
  function applyFilter(queries, filter, text) { return queries.filter((q) => (!text || q.query.toLowerCase().includes(text)) && (filter === 'all' || (filter === 'quality' && ['data_quality', 'insufficient_data', 'collection_error', 'stale'].includes(q.status)) || (filter === 'unknown' && ['unknown', 'mixed'].includes(q.latest?.dominant_intent)) || (filter === 'review' && q.status === 'review') || (filter === 'watch' && q.status === 'watch') || (filter === 'building' && ['building_baseline', 'baseline_ready', 'awaiting_data'].includes(q.status)) || (filter === 'cited' && (q.site?.cited || q.latest?.ai_overview?.page_cited)) || (filter === 'ranking' && position(q)))); }
  function bindFilters(id, queries, target, limit) {
    const key = `serp-drift-view:${state.project}:${id}`;
    let filter = 'all', text = '', sort = 'priority', group = '';
    try { const saved = JSON.parse(localStorage.getItem(key) || '{}'); filter = saved.filter || filter; text = saved.text || ''; sort = saved.sort || sort; group = saved.group || group; } catch {}
    $(`${id}-group`).innerHTML += [...new Set(queries.map((q) => q.group).filter(Boolean))].sort().map((g) => `<option value="${esc(g)}">${esc(g)}</option>`).join('');
    $(`${id}-group`).value = group;
    const draw = () => {
      let rows = applyFilter(queries, filter, text).filter((q) => !group || q.group === group);
      if (sort === 'query') rows.sort((a,b) => a.query.localeCompare(b.query));
      if (sort === 'coverage') rows.sort((a,b) => (a.latest?.classified_coverage || 0) - (b.latest?.classified_coverage || 0));
      if (sort === 'score') rows.sort((a,b) => (b.score || 0) - (a.score || 0));
      $(target).innerHTML = panelRows(rows, limit);
      $(`${id}-seg`).querySelectorAll('button').forEach((b) => b.setAttribute('aria-pressed', String(b.dataset.f === filter)));
      try { localStorage.setItem(key, JSON.stringify({filter,text,sort,group})); } catch {}
    };
    $(`${id}-text`).value = text; $(`${id}-sort`).value = sort;
    $(`${id}-seg`).addEventListener('click', (event) => { const b = event.target.closest('button[data-f]'); if (b) { filter = b.dataset.f; draw(); } });
    $(`${id}-text`).addEventListener('input', (e) => { text = e.target.value.trim().toLowerCase(); draw(); });
    $(`${id}-group`).addEventListener('change', (e) => { group = e.target.value; draw(); });
    $(`${id}-sort`).addEventListener('change', (e) => { sort = e.target.value; draw(); });
    $(`${id}-reset`).addEventListener('click', () => { filter = 'all'; text = ''; sort = 'priority'; group = ''; $(`${id}-group`).value = ''; $(`${id}-text`).value = ''; $(`${id}-sort`).value = sort; draw(); });
    draw();
  }

  // --- views: dashboard, panels -----------------------------------------------------------------------------------------
  async function renderDashboard() {
    const row = projectRow(); let rep, attention;
    try { [rep, attention] = await Promise.all([report(), api(P('/attention'))]); } catch (error) { $('main').innerHTML = `<div class="notice">${esc(error.message)}</div><p class="secondary">Fix the configuration on the <a href="#/p/${encodeURIComponent(state.project)}/settings">Settings</a> page.</p>`; return; }
    const queries = sortQueries(rep.queries); const site = rep.project?.site;
    if (!queries.length) return SerpSetup.mount($('main'), await api(P('/status')), (path, body) => api(P(path), {method:'POST', body}), async () => { invalidate(); await loadStatus(); await render(); });
    const counts = (s) => queries.filter((q) => q.status === s).length;
    const building = queries.filter((q) => ['building_baseline', 'baseline_ready', 'awaiting_data'].includes(q.status));
    const firstScores = [...new Set(building.map((q) => expectedScoreDate(q)).filter(Boolean).map((d) => d.slice(0, 10)))].sort();
    const ranking = queries.filter((q) => position(q)); const top3 = queries.filter((q) => (position(q)?.pos || 99) <= 3); const cited = queries.filter((q) => q.site?.cited || q.latest?.ai_overview?.page_cited);
    const last = row?.last_run;
    $('main').innerHTML = `
      <div class="page-head"><h1>${esc(rep.project?.name || site || state.project)}</h1>${rep.search ? marketHtml(rep.search) : ''}<span class="secondary">${plural(queries.length, 'panel')}${last?.finished_at ? ` · collected ${ago(last.finished_at)} ${T(last.finished_at)}` : ''}</span><div class="spacer"><a class="btn" href="#/p/${encodeURIComponent(state.project)}/import">Import keywords</a><button class="btn primary" type="button" id="collect-now" data-collect="Collect now">Collect now</button></div></div>
      ${SerpReview.overview(queries)}<section class="section"><div class="section-head"><h2>Review queue</h2><span class="secondary">${attention.attention.length || ''}</span></div><div class="card list" id="attention">${attentionHtml(attention.attention) || `<div class="attn-empty">No unhandled confirmed change. ${queries.length ? `${plural(queries.length, 'panel')}${last?.finished_at ? ` collected ${ago(last.finished_at)}` : ''}.` : 'Add panels to start.'}</div>`}</div></section>
      <div class="summary-line"><span><b>${counts('stable')}</b> stable</span><span><b>${counts('watch')}</b> watch</span><span><b>${building.length}</b> building${firstScores.length ? ` · first scores ${D(firstScores[0])}${firstScores.length > 1 && firstScores[firstScores.length - 1] !== firstScores[0] ? `–${D(firstScores[firstScores.length - 1])}` : ''}` : ''}</span>${site ? `<span class="spacer">${esc(site)} ranks in <b>${ranking.length}</b> of ${queries.length} · top 3 in <b>${top3.length}</b> · cited by AI Overview in <b>${cited.length}</b></span>` : `<span class="spacer"><a href="#/p/${encodeURIComponent(state.project)}/settings">Set the project site</a> to track your ranking URLs automatically</span>`}</div>
      <section class="section"><div class="section-head"><h2>Panels</h2><span class="secondary">${queries.length}</span>${filterBar('dash')}</div><div id="dash-table"></div>${!queries.length ? `<div class="card empty-card">No panels yet. <a href="#/p/${encodeURIComponent(state.project)}/import">Import the keywords ${esc(site || 'your site')} already ranks for</a>, or add one by hand in <a href="#/p/${encodeURIComponent(state.project)}/settings">Settings</a>.</div>` : ''}</section>`;
    bindAttention($('attention'));
    bindFilters('dash', queries, 'dash-table', 10);
    $('collect-now').addEventListener('click', () => collect(undefined, false));
    renderTopActions();
  }
  async function renderPanels() {
    const rep = await report(); const queries = sortQueries(rep.queries);
    $('main').innerHTML = `<div class="page-head"><h1>Panels</h1><span class="secondary">${plural(queries.length, 'panel')}</span><div class="spacer"><a class="btn" href="#/p/${encodeURIComponent(state.project)}/import">Import keywords</a><a class="btn" href="#/p/${encodeURIComponent(state.project)}/settings#add">Add by hand</a></div></div><section class="section"><div class="section-head">${filterBar('all')}</div><div id="all-table"></div></section>`;
    bindFilters('all', queries, 'all-table', 0);
  }
  function expectedScoreDate(q) {
    const latest = q.latest?.captured_at; if (!latest) return null;
    const need = (q.settings?.baseline_size ?? 3) - (q.baseline?.length ?? 0) + 1;
    return addDays(latest, Math.max(1, need) * ((q.settings?.interval_hours ?? 24) / 24));
  }

  // --- panel page --------------------------------------------------------------------------------------------------------
  async function renderPanel(id, tab) {
    let panel; try { panel = await panelData(id); } catch (error) { $('main').innerHTML = `<div class="notice">${esc(error.message)}</div>`; return; }
    const rep = await report(); const q = rep.queries.find((x) => x.id === id) || panel.analysis;
    const a = panel.analysis; const captures = panel.captures.length;
    const base = `#/p/${encodeURIComponent(state.project)}/panel/${encodeURIComponent(id)}`;
    const tabs = [['overview', 'Overview'], ['history', `History${captures ? ` · ${captures}` : ''}`], ['compare', 'Compare'], ['evidence', 'Data quality'], ['review', 'Review'], ['ai', 'AI Overview'], ['settings', 'Settings']];
    $('main').innerHTML = `<div class="crumbs"><a href="#/p/${encodeURIComponent(state.project)}/panels">Panels</a> / ${esc(panel.target.query)}</div>
      <div class="page-head top"><h1>${esc(panel.target.query)}</h1>${marketHtml(panel.target.search)}${tab !== 'overview' && q.score != null ? `<span class="status ${kind(q.status)} mt4">${dot(kind(q.status))}${esc(word(q))} · ${Math.round(q.score)}</span>` : ''}<div class="spacer"><a class="btn" href="/api/p/${encodeURIComponent(state.project)}/export/report.json" download="serp-drift-report.json">Export JSON</a><button class="btn" type="button" id="collect-one" data-collect="Collect now">Collect now</button></div></div>
      <nav class="tabs">${tabs.map(([k, l]) => `<a href="${base}?tab=${k}" ${k === tab ? 'aria-current="page"' : ''}>${l}</a>`).join('')}</nav><div id="tab" class="vstack g16"></div>`;
    $('collect-one').addEventListener('click', () => collect([id], true));
    renderTopActions();
    const body = $('tab');
    if (tab === 'evidence' || tab === 'review') {
      body.innerHTML = tab === 'evidence' ? SerpReview.evidence(panel) : SerpReview.review(panel);
      SerpReview.bind(body, panel, (action, data) => api(P(`/panels/${encodeURIComponent(id)}/${action}`), { method:'POST', body:data }), async () => { invalidate(); await loadStatus(); await render(); });
    }
    else if (tab === 'history') renderHistory(panel, q, body);
    else if (tab === 'compare') renderCompare(panel, q, body);
    else if (tab === 'ai') renderAi(panel, q, body);
    else if (tab === 'settings') renderPanelSettings(panel, q, body);
    else renderOverview(panel, q, body);
  }

  function summaryText(q, panel) {
    return { big:q.score == null ? null : String(Math.round(q.score)), phrase:q.decision?.title || word(q),
      small:deltaText(q), text:[...(q.decision?.reasons || []), q.decision?.next_action || ''].join(' '),
      actions:[['Compare observations','compare'],['Check data quality','evidence'],['Record a decision','review']] };
  }
  function deltaText(q) { const d = scoreDelta(q); return d == null ? '' : `${d > 0 ? '+' : d < 0 ? '−' : ''}${Math.abs(d)} vs previous`; }
  function avgMix(list, field = 'intent_distribution') { const out = {}; (list || []).forEach((s) => Object.entries(s[field] || {}).forEach(([k, v]) => { out[k] = (out[k] || 0) + v / list.length; })); return out; }
  const stackHtml = (mix) => `<span class="stack">${INTENTS.filter((i) => mix[i]).map((i) => `<i class="i-${i}" style="flex:${(mix[i] * 100).toFixed(1)}" title="${i} ${pct(mix[i])}"></i>`).join('')}</span>`;

  function scoreChart(timeline, settings, statusKind, width = 480, height = 140) {
    const pts = timeline || []; if (!pts.length) return '<div class="secondary">No captures yet.</div>';
    const th = settings?.drift_threshold ?? 35; const pad = { l: 0, r: 0, t: 8, b: 20 }; const w = width, h = height - pad.b;
    const x = (i) => pts.length === 1 ? w / 2 : pad.l + i * (w - pad.l - pad.r) / (pts.length - 1); const y = (v) => pad.t + (h - pad.t) - (v / 100) * (h - pad.t);
    const baseline = pts.filter((p) => p.phase === 'baseline'); const bx = baseline.length ? x(pts.indexOf(baseline[baseline.length - 1])) : null;
    const scored = pts.map((p, i) => [p, i]).filter(([p]) => p.score != null);
    const path = scored.map(([p, i], k) => `${k ? 'L' : 'M'}${x(i).toFixed(1)},${y(p.score).toFixed(1)}`).join(' ');
    const evidence = new Set(scored.slice(-(settings?.confirmations || 2)).map(([, i]) => i));
    const labelEvery = Math.max(1, Math.ceil(pts.length / 12));
    return `<svg class="chart" viewBox="0 0 ${w} ${height}" role="img" aria-label="Change score per capture">${bx != null ? `<rect x="0" y="0" width="${Math.max(bx, 8).toFixed(1)}" height="${h}" fill="var(--line-soft)"></rect><text x="6" y="14">baseline${baseline.length > 1 ? ` · ${D(baseline[0].captured_at)}–${D(baseline[baseline.length - 1].captured_at)}` : ''}</text>` : ''}<line x1="0" x2="${w}" y1="${y(th).toFixed(1)}" y2="${y(th).toFixed(1)}" stroke="var(--line)" stroke-dasharray="3 4"></line><text x="${w}" y="${(y(th) - 4).toFixed(1)}" text-anchor="end">watch ${th}</text>${path ? `<path d="${path}" fill="none" stroke="var(--ink)" stroke-width="1.5" stroke-linejoin="round"></path>` : ''}${pts.map((p, i) => p.score == null ? `<circle cx="${x(i).toFixed(1)}" cy="${y(0).toFixed(1)}" r="3" fill="var(--faint)"><title>${esc(D(p.captured_at))} · ${esc(p.phase)}${p.quality_ok ? '' : ' · sparse'}</title></circle>` : `<circle cx="${x(i).toFixed(1)}" cy="${y(p.score).toFixed(1)}" r="${i === pts.length - 1 ? 3.5 : 3}" fill="${evidence.has(i) && (statusKind === 'review' || statusKind === 'watch') ? 'var(--review)' : 'var(--ink)'}"><title>${esc(D(p.captured_at))} · score ${Math.round(p.score)} · ${esc(p.intent)}${p.site_position ? ` · your site #${p.site_position}` : ''}</title></circle>`).join('')}${pts.map((p, i) => i % labelEvery === 0 || i === pts.length - 1 ? `<text x="${x(i).toFixed(1)}" y="${height - 4}" text-anchor="${i === 0 ? 'start' : i === pts.length - 1 ? 'end' : 'middle'}">${esc(D(p.captured_at))}</text>` : '').join('')}</svg>`;
  }

  function renderOverview(panel, q, body) {
    const latest = q.latest; const site = q.site;
    const comps = q.comparison?.components; const weights = panel.weights || {};
    const moved = `<div class="card pad" style="display:grid;gap:10px;align-content:start"><div class="card-head"><b>What moved</b><span class="muted">weight · score</span></div>${COMPONENTS.map(([k, l]) => { const v = comps ? comps[k] : null; return `<div class="meter-row ${comps ? '' : 'off'}"><span>${l}</span><span class="meter"><i style="width:${v == null ? 0 : Math.round(v * 100)}%"></i></span><span class="muted right">${Math.round((weights[k] || 0) * 100)} %</span><span class="right">${v == null ? (comps ? '—' : 'not yet') : Math.round(v * 100)}</span></div>`; }).join('')}<div style="border-top:1px solid var(--line-soft);padding-top:10px;display:grid;gap:6px">${q.baseline?.length ? `<div class="stack-row"><span>Baseline</span>${stackHtml(avgMix(q.baseline))}</div>` : ''}${latest ? `<div class="stack-row"><span>Latest</span>${stackHtml(latest.intent_distribution || {})}</div>` : ''}<div class="small muted">${latest ? INTENTS.slice(0, 4).map((i) => `${i} ${q.baseline?.length ? pct(avgMix(q.baseline)[i] || 0) + ' → ' : ''}${pct(latest.intent_distribution?.[i] || 0)}`).join(' · ') : ''}${latest ? ` · unknown ${pct(latest.intent_distribution?.unknown || 0)} <a href="#" data-help="unknown">what is unknown?</a>` : ''}</div></div></div>`;
    const chart = `<div class="card pad vstack"><div class="card-head"><b>Score · ${plural(panel.captures.length, 'capture')}</b><span class="muted">${panel.captures.length ? `${D(panel.captures[0])} – ${D(panel.captures[panel.captures.length - 1])}` : ''}</span></div>${scoreChart(panel.timeline, q.settings, kind(q.status))}<div class="small muted">${q.status === 'review' || q.status === 'watch' ? 'Highlighted points show recent comparisons, not independent proof of a change. ' : ''}Grey dots on the axis are baseline captures without a score. Hover a point for its breakdown.</div></div>`;
    const declared = latest?.page; const fit = declared ? fitText(declared, latest) : null;
    const yourSite = `<div class="card pad" style="display:grid;gap:8px;font-size:13px"><div class="card-head"><b>${panel.project?.site ? 'Your site' : 'Your page'}</b>${site?.ranking_url_changed ? `<span class="c-review">Ranking URL changed ${D(latest?.captured_at)}</span>` : ''}</div>${site?.url || (declared && q.page_position) ? `<div style="display:flex;align-items:baseline;gap:10px"><span class="kpi">#${site?.position || q.page_position}</span><span class="mono">${esc(hostPath(site?.url || declared.url))}</span></div>` : `<div class="kpi muted fs20">Not in the top ten</div>`}<div class="muted pretty">${site?.previous_url && site.ranking_url_changed ? `Previously ${esc(hostPath(site.previous_url))} at #${site.previous_position}. Two of your URLs have held this query — possible cannibalisation.` : site?.hits > 1 ? `${site.hits} of your URLs are in the top ten.` : panel.project?.site ? `Tracked automatically for ${esc(panel.project.site)}.` : 'Set the project site in Settings to track your ranking URL automatically.'}</div>${declared ? `<div class="row-between" style="border-top:1px solid var(--line-soft);padding-top:8px;flex-wrap:wrap"><span class="muted">Declared <span class="mono ink">${esc(hostPath(declared.url))}</span> · ${esc(declared.intent)}</span><span class="${fit.cls} medium">${esc(fit.text)}</span></div>` : `<div class="muted small" style="border-top:1px solid var(--line-soft);padding-top:8px">No declared page. <a href="#" data-act="settings">Declare one</a> to get a page-fit verdict.</div>`}</div>`;
    const cit = panel.citations; const hostsTop = cit.hosts.slice(0, 4);
    const aio = `<div class="card pad" style="display:grid;gap:8px;font-size:13px;align-content:start"><div class="card-head"><b>AI Overview · ${cit.observed} of ${cit.total} captures</b>${cit.observed ? `<a href="#" data-act="ai">Read latest →</a>` : ''}</div>${cit.observed ? `<div style="display:flex;gap:16px;flex-wrap:wrap"><span class="${cit.site_cited ? 'c-ok' : 'muted'} medium">Site cited ${cit.site_cited} / ${cit.observed}</span>${declared ? `<span class="muted">Declared page cited ${cit.page_cited} / ${cit.observed}</span>` : ''}</div><div style="display:grid;grid-template-columns:1fr auto;gap:4px 12px" class="muted">${hostsTop.map((h) => `<span class="mono ${h.mine ? 'ink' : ''}">${esc(h.host)}</span><span class="${h.mine ? 'ink' : ''}">${h.citations}</span>`).join('')}</div>` : `<div class="muted">${latest?.ai_overview_status === 'not_available' ? 'Google reports no AI Overview for this query.' : latest?.ai_overview_status === 'requires_followup' ? 'Overview deferred by Google and not expanded (expansion is off or failed).' : latest?.ai_overview_status === 'not_applicable' ? 'This engine has no AI Overview.' : 'No AI Overview observed yet.'}</div>`}</div>`;
    const anchor = q.baseline?.[q.baseline.length - 1]; const old = new Map((anchor?.results || []).map((r) => [r.url, r.position]));
    const results = latest ? `<section class="section" id="results"><div class="section-head"><h2>Results · ${D(latest.captured_at)}</h2><span class="secondary">${q.comparison ? `${(q.comparison.entered || []).length} entered · ${(q.comparison.exited || []).length} exited from baseline window · ` : ''}coverage ${pct(latest.classified_coverage)} <a href="#" data-help="coverage">?</a></span></div><div class="card clip">${latest.results.map((r) => { const mine = panel.project?.site && (host(r.url) === panel.project.site || host(r.url).endsWith('.' + panel.project.site)); const before = old.get(r.url); const move = !anchor ? '' : before == null ? '↑ entered' : before === r.position ? '=' : `${before} → ${r.position}`; return `<div class="result ${mine ? 'mine' : ''}"><button class="result-row" type="button" aria-expanded="false"><span class="muted">${r.position}</span><span class="nowrap"><span class="t"><b>${esc(r.title || r.url)}</b>${mine ? '<span class="tag">your site</span>' : ''}${declared && r.url === canonical(declared.url) ? '<span class="tag">declared page</span>' : ''}</span><span class="url">${esc(hostPath(r.url))}</span></span><span class="intent"><i class="sw i-${esc(r.intent)}"></i>${esc(r.intent)}</span><span class="muted move">${esc(move)}</span><span class="faint">›</span></button><div class="result-evidence hidden"><div><b>Evidence</b> · ${r.evidence.length ? esc(r.evidence.join(' · ')) : 'no lexical rule matched the title, snippet, or URL'}${r.basis === 'llm' ? ' · labelled by the model' : ''}</div><div>Type: ${esc(r.type)} · <a href="${safeUrl(r.url)}" target="_blank" rel="noopener noreferrer">open ↗</a></div>${r.semantic_label ? `<div>Task: ${esc(r.semantic_label.task || 'unresolved')} · Semantic evidence: ${esc(r.semantic_label.evidence || 'unavailable')}${r.label_disagreement ? ` · Rule label disagrees: ${esc(r.rule_label?.intent)}` : ''}</div>` : ''}${r.snippet ? `<div>${esc(r.snippet)}</div>` : ''}</div></div>`; }).join('')}</div>${latest.warnings?.length ? `<div class="secondary">${latest.warnings.map(esc).join(' · ')}</div>` : ''}</section>` : '';
    body.innerHTML = SerpReview.hero(q, `#/p/${encodeURIComponent(state.project)}/panel/${encodeURIComponent(panel.target.id)}`) + SerpReview.dimensions(q) + `<div class="two">${chart}${moved}</div>` + SerpReview.aligned(q) + `<div class="two">${yourSite}${aio}</div>` + results;
    body.querySelectorAll('.result-row').forEach((row) => row.addEventListener('click', () => { const open = row.getAttribute('aria-expanded') === 'true'; row.setAttribute('aria-expanded', String(!open)); row.nextElementSibling.classList.toggle('hidden', open); row.lastElementChild.textContent = open ? '›' : '⌄'; }));
    body.querySelectorAll('[data-act]').forEach((el) => el.addEventListener('click', async (event) => {
      event.preventDefault(); const act = el.dataset.act; const base = `#/p/${encodeURIComponent(state.project)}/panel/${encodeURIComponent(panel.target.id)}`;
      if (act === 'compare' || act === 'history' || act === 'settings' || act === 'ai' || act === 'evidence' || act === 'review') return go(`${base}?tab=${act}`);
      if (act === 'results') return $('results')?.scrollIntoView({ behavior: 'smooth' });
      if (act === 'collect') return collect([panel.target.id], true);
      if (act === 'ack') { try { await api(P(`/panels/${encodeURIComponent(panel.target.id)}/acknowledge`), { method: 'POST', body: {} }); toast('Marked as reviewed.'); invalidate(); await loadStatus(); render(); } catch (error) { fail(error); } }
    }));
    body.querySelectorAll('[data-help]').forEach((el) => el.addEventListener('click', (event) => { event.preventDefault(); toast(el.dataset.help === 'unknown' ? 'Unknown means no rule in the language pack matched the title, snippet, or URL decisively. Unknowns never trigger a page-fit alert.' : 'Coverage is the share of rank weight (position 1 counts most) that received a decisive intent label.'); }));
  }
  const canonical = (u) => { try { const x = new URL(u); x.hash = ''; x.hostname = x.hostname.replace(/^www\./, ''); return x.href.replace(/\/$/, '') ; } catch { return u; } };
  function fitText(page, latest) {
    const dom = latest?.dominant_intent; const share = latest?.intent_distribution?.[page.intent] || 0;
    if (!dom || dom === 'unknown') return { cls: 'muted', text: 'Fit: unclear — SERP intent unknown' };
    if (dom === 'mixed') return { cls: 'c-watch', text: `Fit: mixed SERP · ${page.intent} ${pct(share)} rank weight` };
    if (dom === page.intent) return { cls: 'c-ok', text: `Latest profile: aligned · ${page.intent} ${pct(share)} rank weight` };
    return { cls: share < 0.25 ? 'c-review' : 'c-watch', text: `Fit: ${share < 0.25 ? 'possible mismatch' : 'partial'} — latest SERP leans ${dom} ${pct(latest.intent_distribution?.[dom] || 0)} rank weight` };
  }

  // --- history ------------------------------------------------------------------------------------------------------------
  function renderHistory(panel, q, body) {
    const t = panel.timeline; const traj = panel.trajectories; const site = panel.project?.site;
    let range = 'all';
    const draw = () => {
      const cut = range === 'all' ? 0 : Date.now() - (range === '30' ? 30 : 7) * 86400000;
      const pts = t.filter((p) => new Date(p.captured_at).getTime() >= cut);
      $('hist-chart').innerHTML = scoreChart(pts, q.settings, kind(q.status), 1120, 130);
    };
    const idxByDate = new Map(traj.captures.map((c, i) => [c, i]));
    const cell = (p, i, positions) => { if (p == null) { const exited = i > 0 && positions[i - 1] != null; return `<div class="cell ${exited ? 'exit' : ''}">${exited ? '×' : ''}</div>`; } const band = p <= 3 ? 'r1' : p <= 6 ? 'r2' : 'r3'; const entered = i > 0 && positions[i - 1] == null && i > 0; return `<div class="cell ${band}" title="#${p} on ${esc(D(traj.captures[i]))}">${entered ? '↑' : ''}${p}</div>`; };
    const cols = `grid-template-columns:260px repeat(${traj.captures.length},minmax(40px,1fr))`;
    const every = Math.max(1, Math.ceil(traj.captures.length / 15));
    const siteChangeIdx = (panel.changes || []).filter((c) => c.ranking_url_changed).map((c) => ({ url: c.site_after?.url, at: c.captured_at }));
    const matrix = traj.urls.length ? `<div class="card matrix-wrap"><div class="matrix"><div class="mh" style="${cols}"><div>URL</div>${traj.captures.map((c, i) => `<div title="${esc(DT(c))}">${i % every === 0 || i === traj.captures.length - 1 ? esc(D(c)) : ''}</div>`).join('')}</div>${traj.urls.slice(0, 80).map((u) => { const flag = siteChangeIdx.find((c) => c.url === u.url); return `<div class="mr ${u.mine ? 'mine' : ''}" style="${cols}"><div><span class="url" title="${esc(u.url)}">${esc(hostPath(u.url))}</span>${flag ? `<span class="flag">ranking URL · since ${esc(D(flag.at))}</span>` : u.mine && u.current ? `<span class="flag" style="color:var(--muted)">your site · best #${u.best}</span>` : ''}</div>${u.positions.map((p, i) => cell(p, i, u.positions)).join('')}</div>`; }).join('')}</div></div>${traj.urls.length > 80 ? `<p class="secondary">Showing 80 of ${traj.urls.length} URLs.</p>` : ''}` : '<div class="card empty-card">No captures yet.</div>';
    const rowsC = [...t].reverse().slice(0, 30).map((p) => { const change = (panel.changes || []).find((c) => c.captured_at === p.captured_at); const notes = change ? [change.ranking_url_changed ? `ranking URL → ${hostPath(change.site_after?.url || '')}` : '', ...change.entered.slice(0, 2).map((u) => `${host(u)} entered`), ...change.features_added.map((f) => `+ ${FEATURES[f] || f}`), ...change.features_removed.map((f) => `− ${FEATURES[f] || f}`), change.intent_before !== change.intent_after ? `intent ${change.intent_before} → ${change.intent_after}` : ''].filter(Boolean).join(' · ') : (p.phase === 'baseline' ? 'baseline capture' : ''); return `<a class="gr" href="#" data-capture="${esc(p.captured_at)}" style="grid-template-columns:90px 60px 70px 70px 1fr"><span class="ink">${esc(D(p.captured_at))}</span><span class="right ${p.quality_ok ? 'ink' : 'muted'}">${p.score == null ? '—' : Math.round(p.score)}</span><span class="right muted">${p.results}</span><span class="right">${p.site_position ? `#${p.site_position}` : p.page_position ? `#${p.page_position}` : '—'}</span><span class="nowrap muted">${esc(!p.quality_ok ? `sparse — ${p.results} results` : notes)}</span></a>`; }).join('');
    const changes = (panel.changes || []).slice(0, 12).map((c) => { const bits = [c.ranking_url_changed ? `Ranking URL changed ${hostPath(c.site_before?.url || '')} → ${hostPath(c.site_after?.url || '')} (now #${c.site_after?.position}).` : '', ...c.entered.slice(0, 3).map((u) => `${hostPath(u)} entered at #${(c.moved.find((m) => m.url === u) || {}).after || ''}`.replace(/ at #$/, '')), c.exited.length ? `${c.exited.slice(0, 3).map(hostPath).join(', ')} exited.` : '', c.features_added.length ? `+ ${c.features_added.map((f) => FEATURES[f] || f).join(', ')}.` : '', c.features_removed.length ? `− ${c.features_removed.map((f) => FEATURES[f] || f).join(', ')}.` : '', c.intent_before !== c.intent_after ? `Intent ${c.intent_before} → ${c.intent_after}.` : '', c.site_before?.position && c.site_after?.position && c.site_before.position !== c.site_after.position && !c.ranking_url_changed ? `Your URL ${c.site_before.position} → ${c.site_after.position}.` : ''].filter(Boolean).join(' '); return `<div style="display:grid;grid-template-columns:110px 1fr;gap:12px;padding:10px 16px;border-bottom:1px solid var(--line-soft);font-size:13px"><span class="muted">${esc(D(c.previous_at))} → ${esc(D(c.captured_at))}</span><span class="pretty ${c.quiet ? 'muted' : ''}">${c.quiet ? 'No change against the previous capture.' : esc(bits)}</span></div>`; }).join('');
    body.innerHTML = `<div class="card pad vstack g10"><div class="card-head"><b>Score per capture</b><span class="seg" id="hist-range"><button type="button" data-r="all" aria-pressed="true">All ${t.length}</button><button type="button" data-r="30">30 d</button><button type="button" data-r="7">7 d</button></span></div><div id="hist-chart"></div></div>
      <section class="section"><div class="section-head"><h2>URL trajectories</h2><span class="secondary">${traj.urls.length} URLs seen · positions per capture</span><span class="legend"><span><i style="background:var(--r1)"></i>1–3</span><span><i style="background:var(--r2)"></i>4–6</span><span><i style="background:var(--r3)"></i>7–10</span><span>↑ entered</span><span>× exited</span>${site ? '<span><i style="background:var(--mine);border:1px solid var(--line)"></i>your site</span>' : ''}</span></div>${matrix}</section>
      <div class="two"><section class="section"><h2 class="section-title">Captures</h2><div class="card grid-table"><div class="gh" style="grid-template-columns:90px 60px 70px 70px 1fr"><span>Date</span><span class="right">Score</span><span class="right">Results</span><span class="right">Your pos</span><span>Notes</span></div>${rowsC || '<div class="empty-card">No captures.</div>'}</div></section>
      <section class="section"><h2 class="section-title">Change log</h2><div class="card clip">${changes || '<div class="empty-card">Changes appear from the second capture on.</div>'}</div></section></div>`;
    $('hist-range').addEventListener('click', (event) => { const b = event.target.closest('button[data-r]'); if (!b) return; range = b.dataset.r; $('hist-range').querySelectorAll('button').forEach((x) => x.setAttribute('aria-pressed', x === b)); draw(); });
    body.querySelectorAll('[data-capture]').forEach((row) => row.addEventListener('click', (event) => { event.preventDefault(); go(`#/p/${encodeURIComponent(state.project)}/panel/${encodeURIComponent(panel.target.id)}?tab=ai&at=${encodeURIComponent(row.dataset.capture)}`); }));
    draw();
  }

  // --- compare -----------------------------------------------------------------------------------------------------------
  function renderCompare(panel, q, body) {
    const caps = panel.captures; const params = route().params;
    const presets = [['baseline-latest', 'Baseline → latest', { preset: 'baseline' }, { preset: 'latest' }], ['weeks', 'Last 7 days → previous 7', { preset: 'previous_7_days' }, { preset: 'last_7_days' }], ['date', 'Before / after a date', null, null], ['captures', 'Two captures', null, null]];
    let mode = params.get('mode') || 'baseline-latest'; let left = { preset: 'baseline' }, right = { preset: 'latest' };
    if (params.get('a')) { try { left = JSON.parse(params.get('a')); right = JSON.parse(params.get('b')); mode = 'custom'; } catch {} }
    body.innerHTML = `<div class="chips" id="cmp-presets">${presets.map(([k, l]) => `<button class="chip" type="button" data-mode="${k}" aria-pressed="${k === mode}">${l}</button>`).join('')}</div><div class="sides" id="cmp-sides"></div><div id="cmp-result"><div class="card empty-card">Choose two sides.</div></div>`;
    const sideCard = (name, spec) => { const label = spec.preset ? ({ baseline: 'Baseline', latest: 'Latest', last_7_days: 'Last 7 days', previous_7_days: 'Previous 7 days', last_30_days: 'Last 30 days', first_week: 'First week' })[spec.preset] : spec.capture ? DT(spec.capture) : `${spec.from || '…'} → ${spec.to || '…'}`; return `<div class="card pad side"><div class="lab"><span>${name} · ${esc(label)}</span><a href="#" data-change="${name}">change</a></div><div class="val" data-val="${name}">…</div><div class="form hidden" data-form="${name}"><label class="field"><span>One capture</span>${select(`data-capture="${name}"`, [['', '—'], ...caps.map((c) => [c, DT(c)])])}</label><div class="form-grid"><label class="field"><span>From</span><input type="date" data-from="${name}"></label><label class="field"><span>To</span><input type="date" data-to="${name}"></label></div><button class="btn small" type="button" data-apply="${name}">Apply</button></div></div>`; };
    const drawSides = () => { $('cmp-sides').innerHTML = `${sideCard('A', left)}<div class="arrow">→</div>${sideCard('B', right)}`; bindSides(); };
    const bindSides = () => {
      $('cmp-sides').querySelectorAll('[data-change]').forEach((a) => a.addEventListener('click', (event) => { event.preventDefault(); const f = $('cmp-sides').querySelector(`[data-form="${a.dataset.change}"]`); f.classList.toggle('hidden'); }));
      $('cmp-sides').querySelectorAll('[data-apply]').forEach((b) => b.addEventListener('click', () => { const name = b.dataset.apply; const cap = $('cmp-sides').querySelector(`[data-capture="${name}"]`).value; const from = $('cmp-sides').querySelector(`[data-from="${name}"]`).value; const to = $('cmp-sides').querySelector(`[data-to="${name}"]`).value; const spec = cap ? { capture: cap } : { from: from || undefined, to: to || undefined }; if (name === 'A') left = spec; else right = spec; mode = 'custom'; $('cmp-presets').querySelectorAll('button').forEach((x) => x.setAttribute('aria-pressed', 'false')); run(); }));
    };
    $('cmp-presets').addEventListener('click', (event) => { const b = event.target.closest('button[data-mode]'); if (!b) return; mode = b.dataset.mode; $('cmp-presets').querySelectorAll('button').forEach((x) => x.setAttribute('aria-pressed', x === b)); const p = presets.find((x) => x[0] === mode); if (p[2]) { left = p[2]; right = p[3]; run(); } else if (mode === 'date') { const mid = caps[Math.floor(caps.length / 2)] || ''; left = { from: caps[0]?.slice(0, 10), to: mid.slice(0, 10) }; right = { from: mid.slice(0, 10), to: caps[caps.length - 1]?.slice(0, 10) }; run(); } else { left = { capture: caps[Math.max(0, caps.length - 2)] }; right = { capture: caps[caps.length - 1] }; run(); } });
    async function run() {
      drawSides(); const result = $('cmp-result'); result.innerHTML = '<div class="card empty-card">Comparing…</div>';
      try {
        const data = await api(P(`/panels/${encodeURIComponent(panel.target.id)}/compare`), { method: 'POST', body: { left, right } });
        history.replaceState(null, '', `${location.pathname}#/p/${encodeURIComponent(state.project)}/panel/${encodeURIComponent(panel.target.id)}?tab=compare&a=${encodeURIComponent(JSON.stringify(left))}&b=${encodeURIComponent(JSON.stringify(right))}`);
        $('cmp-sides').querySelector('[data-val="A"]').innerHTML = `${esc(D(data.left.from))}${data.left.from !== data.left.to ? ` – ${esc(D(data.left.to))}` : ''} · ${plural(data.left.captures, 'capture')}${data.left.captures > 1 ? ', averaged' : ''}<div class="secondary">intent ${esc(data.left.dominant_intent)}</div>`;
        $('cmp-sides').querySelector('[data-val="B"]').innerHTML = `${esc(D(data.right.from))}${data.right.from !== data.right.to ? ` – ${esc(D(data.right.to))}` : ''} · ${plural(data.right.captures, 'capture')}${data.right.captures > 1 ? ', averaged' : ''}<div class="secondary">intent ${esc(data.right.dominant_intent)}</div>`;
        const [capA, capB] = await Promise.all([api(P(`/panels/${encodeURIComponent(panel.target.id)}/captures/${encodeURIComponent(data.left.to)}`)), api(P(`/panels/${encodeURIComponent(panel.target.id)}/captures/${encodeURIComponent(data.right.to)}`))]);
        const aRes = capA.snapshot.results; const bRes = capB.snapshot.results; const bUrls = new Set(bRes.map((r) => r.url)); const aPos = new Map(aRes.map((r) => [r.url, r.position])); const site = panel.project?.site; const mine = (u) => site && (host(u) === site || host(u).endsWith('.' + site));
        const weights = panel.weights || {}; const th = q.settings?.drift_threshold ?? 35;
        result.innerHTML = `<div class="card clip"><div class="cmp-row head"><span>Component</span><span class="right">Weight</span><span class="right">Distance</span><span>Contribution</span><span class="right">Points</span></div>${COMPONENTS.map(([k, l]) => { const v = data.components[k]; const pts = v == null ? 0 : v * (weights[k] || 0) * 100; return `<div class="cmp-row"><span class="ink medium">${l}</span><span class="right muted">${Math.round((weights[k] || 0) * 100)} %</span><span class="right ${v == null ? 'muted' : 'ink'}">${v == null ? '—' : Math.round(v * 100)}</span><span class="bar"><span class="meter"><i style="width:${Math.round(pts / (weights[k] || 1) / 100 * 100)}%;background:${pts >= 15 ? 'var(--review)' : 'var(--ink)'}"></i></span><b>${pts ? '+' + pts.toFixed(1) : '0'}</b></span><span class="right muted">${v == null ? 'n/a' : ''}</span></div>`; }).join('')}<div class="cmp-row"><span class="ink semibold">Change score</span><span></span><span class="right ink semibold fs16">${data.score}</span><span class="muted">watch ≥ ${th} · review with repeated evidence</span><span></span></div></div>
          <div class="two"><div class="card side-list clip"><div class="row-between card-title"><b class="ink">A · top 10 (${esc(D(data.left.to))})</b><span class="secondary">intent</span></div>${aRes.map((r) => `<div class="lr ${mine(r.url) ? 'mine' : ''}"><span class="muted">${r.position}</span><span class="u ${bUrls.has(r.url) ? '' : 'out'}" title="${esc(r.title)}">${esc(hostPath(r.url))}</span><span></span><i class="sw i-${esc(r.intent)}"></i></div>`).join('')}</div><div class="card side-list clip"><div class="row-between card-title"><b class="ink">B · top 10 (${esc(D(data.right.to))})</b><span class="secondary">move · intent</span></div>${bRes.map((r) => { const before = aPos.get(r.url); const move = before == null ? '↑ new' : before === r.position ? '=' : `${before} → ${r.position}`; return `<div class="lr ${mine(r.url) ? 'mine' : ''}"><span class="muted">${r.position}</span><span class="u" title="${esc(r.title)}">${esc(hostPath(r.url))}</span><span class="right small ${before == null ? 'c-ok' : 'muted'}">${esc(move)}</span><i class="sw i-${esc(r.intent)}"></i></div>`; }).join('')}</div></div>
          <div class="three"><div class="card pad mini-list"><b class="ink medium">Entered · ${data.entered.length}</b>${data.entered.map((u) => `<span class="mono c-ok">${esc(hostPath(u))} · #${bRes.find((r) => r.url === u)?.position ?? '?'}</span>`).join('') || '<span class="muted">none</span>'}</div><div class="card pad mini-list"><b class="ink medium">Exited · ${data.exited.length}</b>${data.exited.map((u) => `<span class="mono c-review">${esc(hostPath(u))} · was #${aPos.get(u) ?? '?'}</span>`).join('') || '<span class="muted">none</span>'}</div><div class="card pad mini-list"><b class="ink medium">SERP features</b>${data.features_added.map((f) => `<span class="c-ok">+ ${esc(FEATURES[f] || f)}</span>`).join('')}${(capB.snapshot.features || []).filter((f) => !data.features_added.includes(f)).map((f) => `<span class="muted">= ${esc(FEATURES[f] || f)}</span>`).join('')}${data.features_removed.map((f) => `<span class="c-review">− ${esc(FEATURES[f] || f)}</span>`).join('')}</div></div>`;
      } catch (error) { result.innerHTML = `<div class="notice">${esc(error.message)}</div>`; }
    }
    if (!caps.length) { body.innerHTML = '<div class="card empty-card">Nothing to compare until the first capture.</div>'; return; }
    run();
  }

  // --- AI overview --------------------------------------------------------------------------------------------------------
  async function renderAi(panel, q, body) {
    const c = panel.citations; const site = panel.project?.site; const declared = panel.target.page?.url;
    const withOverview = c.captures.filter((r) => r.status === 'observed').map((r) => r.captured_at);
    let at = route().params.get('at') || withOverview[withOverview.length - 1] || null;
    const max = Math.max(1, ...c.hosts.map((h) => h.citations));
    body.innerHTML = `<div class="stats-row"><span><b class="kpi">${c.observed}</b>of ${c.total} captures had an overview</span><span><b class="kpi ${c.site_cited ? 'c-ok' : ''}">${c.site_cited}</b>cited ${esc(site || 'your site')}</span>${declared ? `<span><b class="kpi">${c.page_cited}</b>cited the declared page</span>` : ''}<span><b class="kpi">${c.references_per_overview ?? '—'}</b>citations per overview</span></div>
      ${c.observed ? `<div style="display:grid;grid-template-columns:400px 1fr;gap:16px;align-items:start" class="ai-grid"><div class="vstack g16"><div class="card hosts clip"><div class="row-between card-title"><b class="ink">Cited hosts</b><span class="secondary">captures cited</span></div>${c.hosts.slice(0, 12).map((h) => `<div class="hr ${h.mine ? 'mine' : ''}"><span class="mono ink nowrap">${esc(h.host)}</span><span class="meter"><i style="width:${Math.round(h.citations / max * 100)}%"></i></span><span class="right ink">${h.citations}</span></div>`).join('')}</div><div class="card grid-table"><div class="gh" style="grid-template-columns:70px 1fr 60px 70px"><span>Capture</span><span>Overview</span><span class="right">Cites</span><span class="right">Your site</span></div>${[...c.captures].reverse().slice(0, 20).map((r) => `<a class="gr ${r.captured_at === at ? 'hover' : ''}" href="#" data-at="${esc(r.captured_at)}" style="grid-template-columns:70px 1fr 60px 70px"><span class="ink">${esc(D(r.captured_at))}</span><span class="muted">${r.status === 'observed' ? 'yes' : r.status === 'not_available' ? 'none' : r.status === 'requires_followup' ? 'deferred' : !r.quality_ok ? 'sparse' : '—'}</span><span class="right muted">${r.status === 'observed' ? r.references : '—'}</span><span class="right ${r.site_cited || r.page_cited ? 'c-ok' : 'muted'}">${r.status === 'observed' ? (r.site_cited || r.page_cited ? 'cited' : 'not cited') : '—'}</span></a>`).join('')}</div></div><div class="card pad reader" id="ai-reader"><div class="muted">Loading…</div></div></div>` : `<div class="card empty-card">${c.total ? `No AI Overview in ${plural(c.total, 'capture')}.` : 'No captures yet.'} ${q.settings && state.status.settings?.ai_overview === 'skip' ? 'Overview expansion is off for this project — turn it on in project Settings (1 credit per capture).' : ''}</div>`}`;
    body.querySelectorAll('[data-at]').forEach((row) => row.addEventListener('click', (event) => { event.preventDefault(); at = row.dataset.at; body.querySelectorAll('[data-at]').forEach((x) => x.classList.toggle('hover', x.dataset.at === at)); loadReader(); }));
    async function loadReader() {
      const reader = $('ai-reader'); if (!reader || !at) return;
      try {
        const data = await api(P(`/panels/${encodeURIComponent(panel.target.id)}/captures/${encodeURIComponent(at)}`));
        const ov = data.ai_overview; const results = data.snapshot.results; const idx = withOverview.indexOf(at);
        const nav = `<span class="seg">${idx > 0 ? `<button type="button" data-nav="${esc(withOverview[idx - 1])}">‹ ${esc(D(withOverview[idx - 1]))}</button>` : ''}<button type="button" disabled>${idx === withOverview.length - 1 ? 'latest' : esc(D(at))}</button>${idx >= 0 && idx < withOverview.length - 1 ? `<button type="button" data-nav="${esc(withOverview[idx + 1])}">${esc(D(withOverview[idx + 1]))} ›</button>` : ''}</span>`;
        if (!ov) { reader.innerHTML = `<div class="card-head"><b>Overview · ${esc(DT(at))}</b>${nav}</div><p class="muted">${data.snapshot.ai_overview_status === 'observed' ? 'The full text of this overview was not stored.' : 'No overview in this capture.'}</p>`; bindNav(); return; }
        const refs = ov.reference_links || [];
        const block = (b) => { const text = b.answer || b.text || b.snippet || ''; const sup = (b.reference_indexes || []).map((i) => `<sup>${i + 1}</sup>`).join(''); if (b.type === 'header') return `<h4>${esc(text)}</h4>`; if ((b.type || '').includes('list')) return `<ul>${(b.list || []).map((li) => `<li>${esc(typeof li === 'string' ? li : li.answer || li.title || li.text || '')}${(li.reference_indexes || []).map((i) => `<sup>${i + 1}</sup>`).join('')}</li>`).join('')}</ul>`; return `<p>${esc(text)}${sup}</p>`; };
        const rank = (u) => { const r = results.find((x) => hostPath(x.url) === hostPath(u)); return r ? r.position : null; };
        reader.innerHTML = `<div class="card-head"><b>Overview text · ${esc(DT(at))}</b>${nav}</div>${ov.text_blocks.map(block).join('')}<div class="refs">${refs.map((ref, i) => { const mine = site && (host(ref.link) === site || host(ref.link).endsWith('.' + site)); const r = rank(ref.link); return `<div class="ref ${mine ? 'mine' : ''}"><span class="n">${i + 1}</span><span><a href="${safeUrl(ref.link)}" target="_blank" rel="noopener noreferrer" class="ink">${esc(ref.title || ref.link)}</a> <span class="u">${esc(hostPath(ref.link))}</span> <span class="${mine ? 'c-ok' : 'muted'}">· ${mine ? 'your site' : esc(ref.source || '')}${r ? `${mine ? ', ranks' : ' · also ranks'} #${r}` : mine ? ', not in top 10' : ' · not in top 10'}</span></span></div>`; }).join('')}</div><div class="small muted" style="border-top:1px solid var(--line-soft);padding-top:10px">Text is stored as captured; references are resolved from Google's redirect URLs to final hosts. Expansion costs one credit per capture.</div>`;
        bindNav();
      } catch (error) { reader.innerHTML = `<div class="notice">${esc(error.message)}</div>`; }
      function bindNav() { reader.querySelectorAll('[data-nav]').forEach((b) => b.addEventListener('click', () => { at = b.dataset.nav; body.querySelectorAll('[data-at]').forEach((x) => x.classList.toggle('hover', x.dataset.at === at)); loadReader(); })); }
    }
    if (c.observed) loadReader();
  }

  // --- panel settings ------------------------------------------------------------------------------------------------------
  function renderPanelSettings(panel, q, body) {
    const t = panel.target; const s = panel.settings; const site = panel.project?.site; const attempts = panel.attempts;
    const failed = attempts.filter((a) => !a.success).length;
    body.innerHTML = `<form id="ps-form" class="settings">
      <div class="lbl"><b>Your page</b><p>Optional. ${site ? `Without it the app tracks whichever ${esc(site)} URL ranks.` : 'Set the project site in project Settings to track your ranking URL automatically.'}</p></div>
      <div class="card pad vstack"><label class="field"><span>Declared page URL</span><input type="url" name="page_url" class="mono" value="${esc(t.page?.url || '')}" placeholder="https://${esc(site || 'example.com')}/page/"></label><div class="field"><span>Intent this page serves</span><div class="chips" id="ps-intents">${INTENTS.slice(0, 4).map((i) => `<button class="chip" type="button" data-intent="${i}" aria-pressed="${(t.page?.intent || '') === i}"><i class="sw i-${i}"></i>${i}</button>`).join('')}</div></div>${q.site?.url ? `<div class="small muted">Currently ranking: <span class="mono">${esc(hostPath(q.site.url))}</span> at #${q.site.position}${t.page?.url && canonical(t.page.url) !== canonical(q.site.url) ? ' — differs from the declared page.' : ''}</div>` : ''}</div>
      <div class="lbl"><b>Keyword group</b><p>Organize panels by topic, client work or content plan.</p></div><div class="card pad"><label class="field">Group<input name="group" maxlength="80" value="${esc(s.group || '')}" placeholder="e.g. SEO foundations"></label></div>
      <div class="lbl"><b>Baseline</b><p>Scores are measured against the first ${q.settings?.baseline_size ?? 3} spaced captures after this date.</p></div>
      <div class="card pad vstack"><div style="display:flex;gap:16px;align-items:end;flex-wrap:wrap"><label class="field" style="width:180px"><span>Anchored from</span><input type="date" name="baseline_from" value="${esc((s.baseline_from || '').slice(0, 10))}"></label><span class="muted pb8">${q.baseline?.length ? `baseline = ${q.baseline.map((b) => D(b.captured_at)).join(', ')}` : 'baseline not complete yet'}</span>${s.baseline_from ? '<button class="btn small push" type="button" id="ps-clear">Use the first captures</button>' : ''}</div><div class="small muted">Re-anchoring keeps all captures; only the reference changes. The status returns to building until ${q.settings?.baseline_size ?? 3} spaced captures pass the new date.</div></div>
      <div class="lbl"><b>Collection</b></div>
      <div class="card pad"><div class="row-between"><span><span class="ink medium">Expand AI Overview</span><span class="small muted block">Up to one additional request per capture · provider pricing applies · project-wide setting</span></span><span class="muted small">${state.status.settings?.ai_overview === 'expand' ? 'on' : 'off'} · <a href="#/p/${encodeURIComponent(state.project)}/settings">change</a></span></div><div class="row-between"><span><span class="ink medium">Follow project schedule</span><span class="small muted block">Every ${q.settings?.interval_hours ?? 24} h · pause here without removing the panel</span></span><button class="toggle" type="button" id="ps-pause" role="switch" aria-label="Follow project schedule" aria-checked="${!q.paused}"><i></i></button></div></div>
      <div class="lbl"><b>Identity</b><p>Fixed after creation — create a new panel to change.</p></div>
      <div class="card pad identity"><span>Engine<b>${esc(engineLabel(t.search.engine))}</b></span><span>Country · language<b>${esc((t.search.gl || '').toUpperCase())} · ${esc(t.search.hl || '')}</b></span><span>Device · location<b>${esc(t.search.device || '—')} · ${esc(t.search.location || '—')}</b></span><span>Panel id<b class="mono">${esc(t.id)}</b></span><span class="full">${plural(panel.captures.length, 'capture')} · ${plural(attempts.length, 'attempt')}, ${failed} failed${attempts[0] ? ` · last ${esc(DT(attempts[0].attempted_at))} (${esc(attempts[0].code)})` : ''} · identity <span class="mono">${esc(t.identity)}</span></span></div>
      <div class="lbl danger"><b>Remove panel</b></div>
      <div class="card pad row-between"><span class="muted pretty">Removes the panel from monitor.toml. Stored captures stay in the database. Type the query to confirm.</span><span style="display:flex;gap:8px;align-items:center"><input type="text" id="ps-confirm" placeholder="${esc(t.query)}" style="width:220px"><button class="btn danger" type="button" id="ps-remove" disabled>Remove…</button></span></div>
      </form><div class="form-actions end narrow"><button class="btn" type="button" id="ps-discard">Discard</button><button class="btn primary" type="button" id="ps-save">Save changes</button></div>`;
    let intent = t.page?.intent || '';
    $('ps-intents').addEventListener('click', (event) => { const b = event.target.closest('button[data-intent]'); if (!b) return; intent = intent === b.dataset.intent ? '' : b.dataset.intent; $('ps-intents').querySelectorAll('button').forEach((x) => x.setAttribute('aria-pressed', x.dataset.intent === intent)); });
    $('ps-confirm').addEventListener('input', () => { $('ps-remove').disabled = $('ps-confirm').value.trim() !== t.query; });
    $('ps-pause').addEventListener('click', async () => { const on = $('ps-pause').getAttribute('aria-checked') === 'true'; try { await api(P(`/panels/${encodeURIComponent(t.id)}/pause`), { method: 'POST', body: { paused: on } }); $('ps-pause').setAttribute('aria-checked', String(!on)); toast(on ? 'Panel paused.' : 'Panel follows the schedule again.'); invalidate(); } catch (error) { fail(error); } });
    $('ps-clear')?.addEventListener('click', async () => { try { await api(P(`/panels/${encodeURIComponent(t.id)}/baseline`), { method: 'POST', body: { from: null } }); toast('Baseline reset to the first captures.'); invalidate(); render(); } catch (error) { fail(error); } });
    $('ps-discard').addEventListener('click', () => { invalidate(); render(); });
    $('ps-save').addEventListener('click', async () => {
      const form = $('ps-form'); const url = form.elements.page_url.value.trim(); const from = form.elements.baseline_from.value;
      try {
        if (url !== (t.page?.url || '') || intent !== (t.page?.intent || '')) await api(P(`/panels/${encodeURIComponent(t.id)}/page`), { method: 'POST', body: { page_url: url || null, intent: intent || null } });
        if (from !== (s.baseline_from || '').slice(0, 10)) await api(P(`/panels/${encodeURIComponent(t.id)}/baseline`), { method: 'POST', body: { from: from || null } });
        if (form.elements.group.value.trim() !== (s.group || '')) await api(P(`/panels/${encodeURIComponent(t.id)}/group`), {method: 'POST', body: {group: form.elements.group.value.trim()}});
        toast('Saved.'); invalidate(); await loadStatus(); render();
      } catch (error) { fail(error); }
    });
    $('ps-remove').addEventListener('click', async () => { try { await api(P(`/panels/${encodeURIComponent(t.id)}`), { method: 'DELETE' }); toast('Panel removed.'); invalidate(); await loadStatus(); go(`#/p/${encodeURIComponent(state.project)}/panels`); } catch (error) { fail(error); } });
  }

  // --- activity, runs, insights ----------------------------------------------------------------------------------------------
  async function renderActivity() {
    const data = await api(P('/activity'));
    const items = [...data.events.map((e) => ({ at: e.at, kind: e.kind, panel: e.target_id, text: eventText(e) })), ...data.runs.map((r) => ({ at: r.finished_at, kind: 'run', panel: null, text: `Run (${r.trigger}): ${r.collected} collected, ${r.skipped} skipped, ${r.failed} failed, ${r.requests} requests${r.error ? ` · ${r.error}` : ''}` }))].sort((a, b) => b.at.localeCompare(a.at)).slice(0, 150);
    $('main').innerHTML = `<div class="page-head"><h1>Activity</h1><span class="secondary">status changes, runs, and configuration events</span></div><div class="card clip">${items.map((i) => `<div style="display:grid;grid-template-columns:130px 110px 1fr;gap:12px;padding:9px 16px;border-bottom:1px solid var(--line-soft);font-size:13px"><span class="muted">${esc(DT(i.at))}</span><span class="${i.kind === 'status_change' ? 'ink' : 'muted'}">${esc(i.kind.replace('_', ' '))}</span><span class="pretty">${i.panel ? `<a href="#/p/${encodeURIComponent(state.project)}/panel/${encodeURIComponent(i.panel)}">${esc(i.panel)}</a> · ` : ''}${esc(i.text)}</span></div>`).join('') || '<div class="empty-card">Nothing yet.</div>'}</div>`;
  }
  function eventText(e) { const p = e.payload || {}; if (e.kind === 'import_fetch') return `Fetched ${p.rows} keywords from Ahrefs for ${p.target}${p.units != null ? ` (${p.units} units)` : ''}`; if (e.kind === 'status_change') return `${word(p.before)} → ${word(p.after)}${p.score != null ? ` · score ${Math.round(p.score)}` : ''}`; if (e.kind === 'notification') return `${p.kind} · ${p.ok ? 'delivered' : 'failed'}${p.status ? ` (${p.status})` : ''}`; if (e.kind === 'import') return `${p.source}: ${p.created} created, ${p.skipped} skipped, ${p.errors} errors`; if (e.kind === 'baseline_moved') return `baseline from ${p.to ? D(p.to) : 'first captures'}`; return Object.entries(p).map(([k, v]) => `${k}: ${typeof v === 'object' ? JSON.stringify(v) : v}`).join(', '); }
  async function renderRuns(portfolio) {
    const pids = portfolio ? (state.status.projects || []).map((p) => p.id) : [state.project];
    const all = (await Promise.all(pids.map(async (pid) => (await api(`/api/p/${encodeURIComponent(pid)}/runs`)).runs.map((r) => ({ ...r, pid }))))).flat().sort((a, b) => b.started_at.localeCompare(a.started_at)).slice(0, 100);
    $('main').innerHTML = `<div class="page-head"><h1>Runs</h1><span class="secondary">scheduler, Collect button, cron, CI, and MCP</span></div><div class="card grid-table"><div class="gh" style="grid-template-columns:130px ${portfolio ? '120px ' : ''}90px 70px 70px 70px 80px 1fr"><span>Started</span>${portfolio ? '<span>Project</span>' : ''}<span>Trigger</span><span class="right">Collected</span><span class="right">Skipped</span><span class="right">Failed</span><span class="right">Requests</span><span>Errors</span></div>${all.map((r) => `<div class="gr" style="grid-template-columns:130px ${portfolio ? '120px ' : ''}90px 70px 70px 70px 80px 1fr"><span>${esc(DT(r.started_at))}</span>${portfolio ? `<span class="nowrap">${esc(r.pid)}</span>` : ''}<span class="muted">${esc(r.trigger)}</span><span class="right">${r.collected}</span><span class="right">${r.skipped}</span><span class="right ${r.failed ? 'c-review' : ''}">${r.failed}</span><span class="right">${r.requests}</span><span class="nowrap muted">${esc(r.error || Object.entries(r.errors || {}).map(([k, v]) => `${k}: ${v}`).join(', ') || '—')}</span></div>`).join('') || '<div class="empty-card">No runs yet.</div>'}</div>`;
  }
  async function renderInsights(params, portfolio) {
    const days = params.get('days') || '';
    const pids = portfolio ? (state.status.projects || []).map((p) => p.id) : [state.project];
    const all = await Promise.all(pids.map((pid) => api(`/api/p/${encodeURIComponent(pid)}/insights${days ? `?days=${encodeURIComponent(days)}` : ''}`).then((d) => ({ ...d, pid })).catch(() => null)));
    const data = all.filter(Boolean); if (!data.length) { $('main').innerHTML = '<div class="card empty-card">No insights yet.</div>'; return; }
    const d = portfolio ? mergeInsights(data) : data[0];
    const share = (v) => v == null ? '—' : pct(v);
    const group = (title, rows) => `<div class="card grid-table"><div class="gh" style="grid-template-columns:1fr 70px 80px 90px 90px 90px 90px"><span>${title}</span><span class="right">Panels</span><span class="right">Captures</span><span class="right">AI Overview</span><span class="right">Turnover</span><span class="right">Intent known</span><span class="right">Coverage</span></div>${Object.entries(rows).map(([k, r]) => `<div class="gr" style="grid-template-columns:1fr 70px 80px 90px 90px 90px 90px"><span class="ink">${esc(k)}</span><span class="right">${r.panels}</span><span class="right">${r.captures}</span><span class="right">${share(r.ai_overview_share)}</span><span class="right">${share(r.turnover)}</span><span class="right">${share(r.intent_known)}</span><span class="right">${share(r.coverage)}</span></div>`).join('')}</div>`;
    const panelRowsHtml = (items) => `<div class="card grid-table"><div class="gh" style="grid-template-columns:minmax(0,1.5fr) 80px 80px 90px 120px 90px 90px"><span>Panel</span><span class="right">Turnover</span><span class="right">Rank moves</span><span class="right">Volatility</span><span>Intent</span><span class="right">AI Overview</span><span class="right">Your page</span></div>${items.map((i) => `<a class="gr" href="#/p/${encodeURIComponent(i.pid || state.project)}/panel/${encodeURIComponent(i.id)}" style="grid-template-columns:minmax(0,1.5fr) 80px 80px 90px 120px 90px 90px"><span class="q">${esc(i.query)}</span><span class="right">${share(i.turnover)}</span><span class="right">${i.rank_movement ?? '—'}</span><span class="right">${share(i.feature_volatility)}</span><span>${esc(i.intent)} <span class="muted small">${share(i.intent_stability)}</span></span><span class="right">${share(i.ai_overview_share)}</span><span class="right">${i.page_position ? `#${i.page_position}` : '—'}</span></a>`).join('') || '<div class="empty-card">Not enough captures yet.</div>'}</div>`;
    $('main').innerHTML = `<div class="page-head"><h1>Insights</h1><span class="secondary">${d.days ? `last ${d.days} days` : 'all time'} · rule version ${esc(d.analysis_version)}</span><div class="spacer">${select('id="ins-days" class="auto"', [['', 'All time'], ['7', 'Last 7 days'], ['30', 'Last 30 days'], ['90', 'Last 90 days']], days)}${portfolio ? '' : `<a class="btn" href="/api/p/${encodeURIComponent(state.project)}/export/dataset.zip${days ? `?days=${encodeURIComponent(days)}` : ''}" download="serp-drift-dataset.zip">Download dataset</a>`}</div></div>
      <div class="stats-row"><span><b class="kpi">${d.panels}</b>panels</span><span><b class="kpi">${n(d.captures)}</b>captures</span><span><b class="kpi">${share(d.overall.ai_overview_share)}</b>with an AI Overview</span><span><b class="kpi">${share(d.overall.turnover)}</b>mean top-10 turnover</span><span><b class="kpi">${share(d.overall.intent_known)}</b>decisive intent</span><span><b class="kpi">${share(d.coverage_median)}</b>median coverage</span><span><b class="kpi">${d.your_pages.in_top_10_now}<span class="muted fs14"> / ${d.your_pages.tracked}</span></b>your pages in top 10</span></div>
      <div class="two"><div class="card grid-table"><div class="gh" style="grid-template-columns:1fr 80px 120px"><span>SERP feature</span><span class="right">Captures</span><span class="right">Share</span></div>${d.features.map((f) => `<div class="gr" style="grid-template-columns:1fr 80px 120px"><span class="ink">${esc(FEATURES[f.feature] || f.feature)}</span><span class="right">${f.captures}</span><span class="right"><span class="meter" style="display:inline-block;width:60px;vertical-align:middle;margin-right:8px"><i style="width:${Math.round((f.share || 0) * 100)}%"></i></span>${share(f.share)}</span></div>`).join('')}</div><div class="card grid-table"><div class="gh" style="grid-template-columns:1fr 80px 80px"><span>Most cited hosts in AI Overviews</span><span class="right">Citations</span><span class="right">Panels</span></div>${d.hosts.slice(0, 12).map((h) => `<div class="gr" style="grid-template-columns:1fr 80px 80px"><span class="mono ink">${esc(h.host)}</span><span class="right">${h.citations}</span><span class="right">${h.panels}</span></div>`).join('') || '<div class="empty-card">No expanded overviews yet.</div>'}</div></div>
      ${group('By language', d.by.language)}${group('By device', d.by.device)}${group('By engine', d.by.engine)}
      <section class="section"><div class="section-head"><h2>Most volatile</h2></div>${panelRowsHtml(d.most_volatile)}</section><section class="section"><div class="section-head"><h2>Most stable</h2></div>${panelRowsHtml(d.most_stable)}</section>`;
    $('ins-days').addEventListener('change', (e) => go(`${portfolio ? '#/portfolio/insights' : `#/p/${encodeURIComponent(state.project)}/insights`}${e.target.value ? `?days=${e.target.value}` : ''}`));
  }
  function mergeInsights(list) {
    const sum = (k) => list.reduce((a, d) => a + (d[k] || 0), 0);
    const avg = (get) => { const v = list.map(get).filter((x) => x != null); return v.length ? v.reduce((a, b) => a + b, 0) / v.length : null; };
    const hosts = {}; list.forEach((d) => d.hosts.forEach((h) => { hosts[h.host] = hosts[h.host] || { host: h.host, citations: 0, panels: 0 }; hosts[h.host].citations += h.citations; hosts[h.host].panels += h.panels; }));
    const features = {}; list.forEach((d) => d.features.forEach((f) => { features[f.feature] = features[f.feature] || { feature: f.feature, captures: 0 }; features[f.feature].captures += f.captures; }));
    const captures = sum('captures');
    const by = {}; ['language', 'device', 'engine'].forEach((g) => { by[g] = {}; list.forEach((d) => Object.entries(d.by[g]).forEach(([k, r]) => { const t = by[g][k] || (by[g][k] = { panels: 0, captures: 0, ai_overview_share: null, turnover: null, intent_known: null, coverage: null, _n: 0 }); t.panels += r.panels; t.captures += r.captures; ['ai_overview_share', 'turnover', 'intent_known', 'coverage'].forEach((f) => { if (r[f] != null) t[f] = ((t[f] || 0) * t._n + r[f]) / (t._n + 1); }); t._n += 1; })); });
    const metrics = list.flatMap((d) => d.panel_metrics.map((m) => ({ ...m, pid: d.pid })));
    return { days: list[0].days, analysis_version: list[0].analysis_version, panels: sum('panels'), captures, overall: { ai_overview_share: avg((d) => d.overall.ai_overview_share), turnover: avg((d) => d.overall.turnover), intent_known: avg((d) => d.overall.intent_known) }, coverage_median: avg((d) => d.coverage_median), features: Object.values(features).map((f) => ({ ...f, share: captures ? f.captures / captures : null })).sort((a, b) => b.captures - a.captures), hosts: Object.values(hosts).sort((a, b) => b.citations - a.citations), by, your_pages: { tracked: list.reduce((a, d) => a + d.your_pages.tracked, 0), in_top_10_now: list.reduce((a, d) => a + d.your_pages.in_top_10_now, 0) }, most_volatile: metrics.filter((m) => m.turnover != null).sort((a, b) => b.turnover - a.turnover).slice(0, 10), most_stable: metrics.filter((m) => m.turnover != null).sort((a, b) => a.turnover - b.turnover).slice(0, 10) };
  }

  // --- project settings ----------------------------------------------------------------------------------------------------------
  async function renderSettings() {
    const s = await api(P('/status')); const set = s.settings || {}; const notify = s.notify || {}; const engines = Object.entries(s.engines || {}); const row = projectRow();
    $('main').innerHTML = `<div class="page-head"><h1>Settings</h1><span class="secondary">${esc(row?.name || '')} · ${esc(s.workspace.dir)}</span></div>${s.config_error ? `<div class="notice">Configuration problem: ${esc(s.config_error)}</div>` : ''}
      <div class="settings">
        <div class="lbl"><b>Project</b><p>The site lets the app find your ranking URL in every capture without declaring pages.</p></div>
        <form class="card pad form-grid" id="f-project"><label class="field"><span>Name</span><input type="text" name="name" value="${esc(s.project?.name || '')}"></label><label class="field"><span>Site (hostname)</span><input type="text" name="site" value="${esc(s.project?.site || '')}" placeholder="example.com"></label><div class="form-actions"><button class="btn primary" type="submit">Save</button></div></form>
        <div class="lbl"><b>SearchApi key</b><p>Stored as a 0600 file in the workspace; never shown again.</p></div>
        <form class="card pad form-grid" id="f-key"><label class="field"><span>${s.workspace.key === 'missing' ? 'No key yet' : `Key source: ${esc(s.workspace.key)}`}</span><input type="password" name="key" placeholder="paste a new key to replace" autocomplete="off"></label><div class="form-actions"><button class="btn" type="submit">Save key</button><button class="btn" type="button" id="refresh-credits">Check credits</button><span class="secondary" id="credits">${s.account?.data ? `${n(s.account.data.account.remaining_credits)} credits left` : ''}</span></div></form>
        <div class="lbl"><b>Integrations</b><p>Keyword discovery only; every capture still comes from SearchApi.</p></div>
        <form class="card pad form-grid" id="f-ahrefs"><label class="field"><span>Ahrefs API token · ${s.integrations?.ahrefs?.key === 'missing' ? 'not set' : `source: ${esc(s.integrations?.ahrefs?.key)}`}</span><input type="password" name="key" placeholder="paste a token to save or replace" autocomplete="off"></label><div class="form-actions"><button class="btn" type="submit">Save token</button><a class="btn link" href="#/p/${encodeURIComponent(state.project)}/import">Import keywords →</a><span class="secondary">Estimated ${s.integrations?.ahrefs?.per_row_units || 19} API units per keyword; check your provider account for current limits.</span></div></form>
        <div class="lbl"><b>Collection</b><p>Applies to every panel in this project.</p></div>
        <form class="card pad vstack g14" id="f-settings"><div class="form-grid">${[['interval_hours', 'Interval (hours)'], ['baseline_size', 'Baseline captures'], ['confirmations', 'Confirmations'], ['min_results', 'Minimum results'], ['drift_threshold', 'Watch threshold'], ['raw_retention_days', 'Keep raw responses (days)'], ['max_requests_per_run', 'Max requests per run'], ['request_delay_seconds', 'Delay between requests (s)']].map(([k, l]) => `<label class="field"><span>${l}</span><input type="number" step="any" name="${k}" value="${esc(set[k] ?? '')}"></label>`).join('')}</div><div class="row-between"><span><span class="ink medium">Expand AI Overview</span><span class="small muted block">Up to one additional request per capture · provider pricing applies</span></span><button class="toggle" type="button" id="t-aio" role="switch" aria-label="Expand AI Overview" aria-checked="${set.ai_overview === 'expand'}"><i></i></button></div><div class="row-between"><span><span class="ink medium">Resolve Google redirect links</span><span class="small muted block">Real URLs for AI Overview references · no extra credit</span></span><button class="toggle" type="button" id="t-links" role="switch" aria-label="Resolve Google redirect links" aria-checked="${Boolean(set.resolve_links)}"><i></i></button></div><div class="form-actions"><button class="btn primary" type="submit">Save collection settings</button><span class="estimate">${n(s.credits_per_day)} requests / day, before retries (upper estimate)</span></div></form>
        <div class="lbl"><b>Notifications</b><p>One message per run listing panels that changed into a chosen state; optional digest.</p></div>
        <form class="card pad vstack g14" id="f-notify"><div class="form-grid"><label class="field span-all"><span>Webhook URL (Slack, Discord, ntfy, or any JSON endpoint)</span><input type="url" name="webhook_url" value="${esc(notify.webhook_url || '')}"></label><label class="field"><span>Format</span>${select('name="format"', ['json', 'slack', 'discord', 'ntfy'], notify.format)}</label><label class="field"><span>Digest</span>${select('name="digest"', ['none', 'daily', 'weekly'], notify.digest)}</label><label class="field"><span>Digest day</span>${select('name="digest_day"', ['monday', 'tuesday', 'wednesday', 'thursday', 'friday', 'saturday', 'sunday'], notify.digest_day)}</label></div><div class="field"><span>Notify when a panel changes to</span><div class="chips">${['review', 'watch', 'stable', 'collection_error', 'stale', 'insufficient_data', 'data_quality'].map((k) => `<button class="chip" type="button" data-on="${k}" aria-pressed="${(notify.on || []).includes(k)}">${word(k)}</button>`).join('')}</div></div><div class="form-actions"><button class="btn primary" type="submit">Save notifications</button><button class="btn" type="button" id="test-webhook" ${notify.webhook_configured ? '' : 'disabled'}>Send a test</button><a class="btn" href="/api/p/${encodeURIComponent(state.project)}/digest.svg?days=7" target="_blank" rel="noopener">Preview digest card</a></div></form>
        <div class="lbl" id="add"><b>Add a panel by hand</b><p>Or <a href="#/p/${encodeURIComponent(state.project)}/import">import keywords</a> from Search Console or Ahrefs.</p></div>
        <form class="card pad vstack g14" id="f-add"><div class="form-grid"><label class="field span2"><span>Query</span><input type="text" name="query" required placeholder="e.g. topical authority"></label><label class="field"><span>Engine</span>${select('name="engine"', engines, s.search?.engine || 'google')}</label><label class="field"><span>Country (gl)</span><input type="text" name="gl" value="${esc(s.search?.gl || 'us')}"></label><label class="field"><span>Language (hl)</span><input type="text" name="hl" value="${esc(s.search?.hl || 'en')}"></label><label class="field"><span>Device</span>${select('name="device"', DEVICES, s.search?.device || 'desktop')}</label><label class="field span2"><span>Location (type a city for canonical names)</span><input type="text" name="location" list="loc-opts" autocomplete="off"><datalist id="loc-opts"></datalist></label><label class="field span2"><span>Declared page URL (optional)</span><input type="url" name="page_url" placeholder="https://${esc(s.project?.site || 'example.com')}/page/"></label><label class="field"><span>Declared intent</span>${select('name="intent"', [['', 'none'], ...INTENTS.slice(0, 4)])}</label></div><div class="form-actions"><button class="btn primary" type="submit">Add panel</button></div></form>
      </div>`;
    SerpLabeling.mount(document.querySelector('.settings'), s, (path, body) => api(P(path), {method:'POST', body}), () => { invalidate(); return render(); });
    $('f-project').addEventListener('submit', async (e) => { e.preventDefault(); try { await api(P('/project'), { method: 'POST', body: { name: e.target.elements.name.value, site: e.target.elements.site.value } }); toast('Project saved.'); invalidate(); await loadStatus(); render(); } catch (error) { fail(error); } });
    $('f-key').addEventListener('submit', async (e) => { e.preventDefault(); const key = e.target.elements.key.value.trim(); if (!key) return toast('Paste a key first.', true); try { await api(P('/key'), { method: 'POST', body: { key } }); e.target.elements.key.value = ''; toast('Key saved.'); await loadStatus(); render(); } catch (error) { fail(error); } });
    $('f-ahrefs').addEventListener('submit', async (e) => { e.preventDefault(); const key = e.target.elements.key.value.trim(); if (!key) return toast('Paste a token first.', true); try { await api(P('/key'), { method: 'POST', body: { key, service: 'ahrefs' } }); e.target.elements.key.value = ''; toast('Ahrefs token saved.'); await loadStatus(); render(); } catch (error) { fail(error); } });
    $('refresh-credits').addEventListener('click', async () => { try { const acc = await api(P('/account/refresh'), { method: 'POST', body: {} }); $('credits').textContent = acc.data ? `${n(acc.data.account.remaining_credits)} credits left · ${acc.data.api_usage.searches_this_hour} searches this hour` : acc.error; } catch (error) { fail(error); } });
    const toggle = (id) => $(id).addEventListener('click', () => $(id).setAttribute('aria-checked', String($(id).getAttribute('aria-checked') !== 'true')));
    toggle('t-aio'); toggle('t-links');
    $('f-settings').addEventListener('submit', async (e) => { e.preventDefault(); const body = {}; e.target.querySelectorAll('input[type=number]').forEach((i) => { if (i.value !== '') body[i.name] = Number(i.value); }); body.ai_overview = $('t-aio').getAttribute('aria-checked') === 'true' ? 'expand' : 'skip'; body.resolve_links = $('t-links').getAttribute('aria-checked') === 'true'; try { await api(P('/settings'), { method: 'POST', body }); toast('Settings saved.'); invalidate(); await loadStatus(); render(); } catch (error) { fail(error); } });
    $('f-notify').querySelectorAll('[data-on]').forEach((b) => b.addEventListener('click', () => b.setAttribute('aria-pressed', String(b.getAttribute('aria-pressed') !== 'true'))));
    $('f-notify').addEventListener('submit', async (e) => { e.preventDefault(); const f = e.target; try { await api(P('/notify'), { method: 'POST', body: { ...(f.elements.webhook_url.value.trim() ? {webhook_url:f.elements.webhook_url.value.trim()} : {}), format: f.elements.format.value, digest: f.elements.digest.value, digest_day: f.elements.digest_day.value, on: [...f.querySelectorAll('[data-on][aria-pressed=true]')].map((b) => b.dataset.on) } }); toast('Notifications saved.'); invalidate(); await loadStatus(); render(); } catch (error) { fail(error); } });
    $('test-webhook').addEventListener('click', async () => { try { const r = await api(P('/notify/test'), { method: 'POST', body: {} }); toast(r.ok ? `Webhook answered ${r.status}.` : `Webhook failed: ${r.status || r.error}`, !r.ok); } catch (error) { fail(error); } });
    let timer = null; const loc = $('f-add').elements.location;
    loc.addEventListener('input', () => { clearTimeout(timer); const v = loc.value.trim(); if (v.length < 2 || v.includes(',')) return; timer = setTimeout(async () => { try { const d = await api(P(`/locations?q=${encodeURIComponent(v)}`)); $('loc-opts').innerHTML = d.locations.map((r) => `<option value="${esc(r.canonical_name)}">${esc(r.target_type || '')} · ${esc(r.country_code || '')}</option>`).join(''); } catch {} }, 350); });
    $('f-add').addEventListener('submit', async (e) => { e.preventDefault(); const f = e.target; const body = Object.fromEntries(['query', 'engine', 'gl', 'hl', 'device', 'location', 'page_url', 'intent'].map((k) => [k, f.elements[k].value.trim()])); try { const added = await api(P('/panels'), { method: 'POST', body }); toast(`Added ${added.id}.`); invalidate(); await loadStatus(); go(`#/p/${encodeURIComponent(state.project)}/panel/${encodeURIComponent(added.id)}`); } catch (error) { fail(error); } });
    if (location.hash.endsWith('#add')) $('add')?.scrollIntoView();
  }

  // --- import wizard --------------------------------------------------------------------------------------------------------------
  async function renderImport() {
    const s = await api(P('/status')); const site = s.project?.site; const set = s.settings || {}; const perPanel = set.ai_overview === 'expand' ? 2 : 1;
    const ah = s.integrations?.ahrefs || { key: 'missing', limits: [100, 250, 500, 1000], per_row_units: 19, per_row_units_traffic: 29 };
    let preview = null; let selected = new Set(); let filters = { min: 0, posMax: 100, hideExisting: true, brand: site ? site.split('.')[0] : '', hideBrand: false, text: '' };
    const crumbs = `<div class="crumbs"><a href="#/p/${encodeURIComponent(state.project)}">Overview</a> / Import keywords</div>`;
    const step = (k) => `<div class="stepper"><b>${k === 1 ? '1 Source' : '1 Source ✓'}</b><span>${k === 2 ? '<b>2 Choose queries</b>' : k > 2 ? '2 Choose queries ✓' : '2 Choose queries'}</span><span>${k === 3 ? '<b>3 Confirm</b>' : '3 Confirm'}</span></div>`;
    // One row model for both sources: CSV rows carry impressions/clicks, Ahrefs rows carry volume/url/source_intent.
    const isAhrefs = () => preview?.source?.name === 'ahrefs';
    const metric = (c) => (isAhrefs() ? c.volume : c.impressions);
    const cols = () => (isAhrefs() ? 'grid-template-columns:24px minmax(0,1.2fr) 80px 70px minmax(0,1fr) 160px' : 'grid-template-columns:24px minmax(0,1fr) 90px 70px 70px 160px');
    const head = () => `<span></span><span>${isAhrefs() ? 'Keyword' : 'Query'}</span>${isAhrefs() ? '<span class="right">Volume</span><span class="right">Position</span><span>Ranking URL</span>' : '<span class="right">Impressions</span><span class="right">Clicks</span><span class="right">Position</span>'}<span>Suggested intent</span>`;
    const intentCell = (c) => `<span class="muted nowrap">${esc(c.suggested_intent)}${c.source_intent && c.source_intent !== c.suggested_intent ? ` <span class="small faint">· Ahrefs: ${esc(c.source_intent)}</span>` : ''}</span>`;
    const cells = (c) => (isAhrefs() ? `<span class="right">${n(c.volume)}</span><span class="right">${c.position ?? '—'}</span><span class="mono nowrap">${esc(c.url ? hostPath(c.url) : '—')}</span>` : `<span class="right">${n(c.impressions)}</span><span class="right">${n(c.clicks)}</span><span class="right">${c.position ?? '—'}</span>`) + intentCell(c);
    const sourceLine = () => (isAhrefs() ? `Ahrefs · ${esc(preview.source.target)} · ${esc((preview.source.country || '').toUpperCase())}${preview.source.units != null ? ` · ${n(preview.source.units)} units spent` : ''}` : esc(preview.detected.columns));
    const render1 = () => {
      $('main').innerHTML = `${crumbs}<div class="page-head"><h1>Import keywords</h1><span class="secondary">turn the queries ${esc(site || 'your site')} already ranks for into panels</span></div>${step(1)}
        <div class="two"><div class="card pad vstack"><div class="card-head"><b>Search Console export</b><span class="secondary">CSV · free</span></div><div class="drop" id="drop">Drop the Queries CSV here, or <label style="color:var(--accent);cursor:pointer">choose a file<input type="file" id="file" accept=".csv,text/csv" hidden></label>.<div class="small mt8">Search Console → Performance → Export → download the zip → use <span class="mono">Queries.csv</span>. Any CSV with a query column works.</div></div><label class="field"><span>Or paste CSV text</span><textarea id="paste" placeholder="Top queries,Clicks,Impressions,CTR,Position"></textarea></label><div class="form-actions"><button class="btn primary" type="button" id="parse">Read queries</button></div></div>
        <div class="card pad vstack"><div class="card-head"><b>Ahrefs API</b><span class="secondary">organic keywords · API units</span></div>${ah.key === 'missing' ? `<p class="secondary">No Ahrefs token yet. Add one under <a href="#/p/${encodeURIComponent(state.project)}/settings">Settings → Integrations</a>. Lite plans and up include API units; fetching 500 keywords costs about ${n(500 * ah.per_row_units)}.</p>` : `<div class="form-grid"><label class="field"><span>Target</span><input type="text" id="a-target" value="${esc(site || '')}" placeholder="example.com"></label><label class="field"><span>Country</span><input type="text" id="a-country" value="${esc(s.search?.gl || 'us')}" maxlength="2"></label><label class="field"><span>Keywords to fetch</span>${select('id="a-limit"', ah.limits.map(String), '500')}</label><label class="field"><span>Order by</span>${select('id="a-order"', [['volume', 'Search volume'], ['traffic', 'Traffic estimate (+10 units per row)']], 'volume')}</label></div><div class="row-between"><span class="estimate" id="a-units"></span><button class="btn primary" type="button" id="fetch">Fetch keywords</button></div><p class="small muted">Your Ahrefs plan caps rows per request (Lite 100, Standard 250, Advanced 500). Keyword discovery only: every capture still comes from SearchApi.</p>`}</div></div>`;
      const drop = $('drop'); const readFile = (file) => { const r = new FileReader(); r.onload = () => { $('paste').value = String(r.result || ''); parse(); }; r.readAsText(file); };
      drop.addEventListener('dragover', (e) => { e.preventDefault(); drop.classList.add('over'); }); drop.addEventListener('dragleave', () => drop.classList.remove('over'));
      drop.addEventListener('drop', (e) => { e.preventDefault(); drop.classList.remove('over'); const f = e.dataTransfer.files[0]; if (f) readFile(f); });
      $('file').addEventListener('change', (e) => { const f = e.target.files[0]; if (f) readFile(f); });
      $('parse').addEventListener('click', parse);
      if (ah.key !== 'missing') {
        const units = () => { const rows = Number($('a-limit').value) || 0; const per = $('a-order').value === 'traffic' ? ah.per_row_units_traffic : ah.per_row_units; $('a-units').innerHTML = `about <b>${n(Math.max(50, rows * per))}</b> API units for this fetch`; };
        ['a-limit', 'a-order'].forEach((id) => $(id).addEventListener('change', units)); units();
        $('fetch').addEventListener('click', fetchAhrefs);
      }
    };
    async function fetchAhrefs() {
      const body = { source: 'ahrefs', target: $('a-target').value.trim(), country: $('a-country').value.trim().toLowerCase(), limit: Number($('a-limit').value), traffic: $('a-order').value === 'traffic' };
      $('fetch').disabled = true; $('fetch').textContent = 'Fetching…';
      try { preview = await api(P('/import/fetch'), { method: 'POST', body }); selected = new Set(); render2(); } catch (error) { fail(error); $('fetch').disabled = false; $('fetch').textContent = 'Fetch keywords'; }
    }
    async function parse() { const text = $('paste').value; if (!text.trim()) return toast('Nothing to read.', true); try { preview = await api(P('/import/preview'), { method: 'POST', body: text, raw: true }); selected = new Set(); render2(); } catch (error) { fail(error); } }
    const visible = () => (preview?.candidates || []).filter((c) => (!filters.hideExisting || !c.existing) && (metric(c) == null || metric(c) >= filters.min) && (c.position == null || c.position <= filters.posMax) && (!filters.hideBrand || !(c.branded || (filters.brand && c.query.toLowerCase().includes(filters.brand.toLowerCase())))) && (!filters.text || c.query.toLowerCase().includes(filters.text)));
    const render2 = () => {
      const rows = visible();
      $('main').innerHTML = `${crumbs}<div class="page-head"><h1>Choose ${isAhrefs() ? 'keywords' : 'queries'}</h1><span class="secondary">${preview.total} found · ${sourceLine()}</span><div class="spacer"><button class="btn" type="button" id="back1">Back</button><button class="btn" type="button" id="import-all">Import all visible</button><button class="btn primary" type="button" id="next3">Continue</button></div></div>${step(2)}
        <div class="card pad form-grid"><label class="field"><span>${isAhrefs() ? 'Min volume' : 'Min impressions'}</span><input type="number" id="f-min" value="${filters.min}"></label><label class="field"><span>Max position</span><input type="number" id="f-pos" value="${filters.posMax}"></label><label class="field"><span>Brand term to exclude</span><input type="text" id="f-brand" value="${esc(filters.brand)}"></label><label class="field"><span>Search</span><input type="search" id="f-text" placeholder="filter…"></label><label class="field row"><input type="checkbox" id="f-existing" ${filters.hideExisting ? 'checked' : ''}><span>hide already monitored</span></label><label class="field row"><input type="checkbox" id="f-hidebrand" ${filters.hideBrand ? 'checked' : ''}><span>hide brand queries${isAhrefs() ? ' (Ahrefs flag or the brand term)' : ''}</span></label></div>
        <div class="row-between"><span class="form-actions"><button class="btn small" type="button" id="sel-all">Select visible</button><button class="btn small" type="button" id="sel-none">Clear</button><button class="btn small" type="button" id="sel-top">Select top 50</button></span><span class="estimate" id="estimate"></span></div>
        <div class="card cands clip"><div class="cr head" style="${cols()}">${head()}</div><div id="cand-rows">${rows.slice(0, 500).map((c) => `<label class="cr ${c.existing ? 'existing' : ''}" style="${cols()}"><input type="checkbox" data-q="${esc(c.query)}" ${selected.has(c.query) ? 'checked' : ''} ${c.existing ? 'disabled' : ''}><span class="nowrap">${esc(c.query)}${c.existing ? ' <span class="small">· already monitored</span>' : ''}</span>${cells(c)}</label>`).join('') || '<div class="empty-card">No candidates match the filters.</div>'}</div>${rows.length > 500 ? `<div class="gf">Showing 500 of ${rows.length}; narrow the filters.</div>` : ''}</div>`;
      const est = () => { $('estimate').innerHTML = `<b>${selected.size}</b> selected · about <b>${selected.size * perPanel}</b> credits / day, <b>${n(selected.size * perPanel * 30)}</b> / month${set.ai_overview === 'expand' ? ' (with AI Overview expansion)' : ''}`; };
      $('cand-rows').addEventListener('change', (e) => { const cb = e.target.closest('input[data-q]'); if (!cb) return; cb.checked ? selected.add(cb.dataset.q) : selected.delete(cb.dataset.q); est(); });
      const rerender = () => { filters = { min: Number($('f-min').value) || 0, posMax: Number($('f-pos').value) || 100, brand: $('f-brand').value.trim(), hideExisting: $('f-existing').checked, hideBrand: $('f-hidebrand').checked, text: $('f-text').value.trim().toLowerCase() }; render2(); };
      ['f-min', 'f-pos', 'f-brand', 'f-existing', 'f-hidebrand'].forEach((id) => $(id).addEventListener('change', rerender)); $('f-text').addEventListener('input', rerender);
      $('sel-all').addEventListener('click', () => { visible().filter((c) => !c.existing).forEach((c) => selected.add(c.query)); render2(); });
      $('sel-none').addEventListener('click', () => { selected.clear(); render2(); });
      $('sel-top').addEventListener('click', () => { selected.clear(); visible().filter((c) => !c.existing).slice(0, 50).forEach((c) => selected.add(c.query)); render2(); });
      $('import-all').addEventListener('click', () => { const all = visible().filter((c) => !c.existing); if (!all.length) return toast('Nothing to import.', true); selected = new Set(all.map((c) => c.query)); render3(); });
      $('back1').addEventListener('click', render1); $('next3').addEventListener('click', () => (selected.size ? render3() : toast('Select at least one query.', true)));
      est();
    };
    const render3 = () => {
      const items = (preview.candidates || []).filter((c) => selected.has(c.query));
      $('main').innerHTML = `${crumbs}<div class="page-head"><h1>Confirm</h1><span class="secondary">${plural(items.length, 'panel')} will be created · existing panels are untouched</span><div class="spacer"><button class="btn" type="button" id="back2">Back</button><button class="btn primary" type="button" id="create">Create panels</button></div></div>${step(3)}
        <div class="card pad form-grid"><label class="field"><span>Engine</span>${select('id="c-engine"', Object.entries(s.engines), s.search?.engine || 'google')}</label><label class="field"><span>Country (gl)</span><input type="text" id="c-gl" value="${esc(isAhrefs() && preview.source.country ? preview.source.country : (s.search?.gl || 'us'))}"></label><label class="field"><span>Language (hl)</span><input type="text" id="c-hl" value="${esc(s.search?.hl || 'en')}"></label><label class="field"><span>Device</span>${select('id="c-device"', DEVICES, s.search?.device || 'desktop')}</label><label class="field row"><input type="checkbox" id="c-collect" checked><span>collect the first capture now (${items.length * perPanel} credits)</span></label><label class="field row"><input type="checkbox" id="c-intent" checked><span>use the suggested intent as the declared page intent when a page is set later</span></label></div>
        <div class="card cands clip"><div class="cr head" style="${cols()}">${head()}</div>${items.map((c) => `<div class="cr" style="${cols()}"><span></span><span class="nowrap">${esc(c.query)}</span>${cells(c)}</div>`).join('')}</div>`;
      $('back2').addEventListener('click', render2);
      $('create').addEventListener('click', async () => {
        const engine = $('c-engine').value, gl = $('c-gl').value.trim(), hl = $('c-hl').value.trim(), device = $('c-device').value;
        const panels = items.map((c) => ({ query: c.query, engine, gl, hl, device }));
        $('create').disabled = true; $('create').textContent = 'Creating…';
        try { const r = await api(P('/panels/bulk'), { method: 'POST', body: { panels, source: isAhrefs() ? 'ahrefs' : 'search-console', collect: $('c-collect').checked } }); toast(`${r.created.length} created, ${r.skipped.length} skipped${r.errors.length ? `, ${r.errors.length} errors` : ''}.`); invalidate(); await loadStatus(); if (r.collect_started) startPolling(); go(`#/p/${encodeURIComponent(state.project)}`); } catch (error) { fail(error); $('create').disabled = false; $('create').textContent = 'Create panels'; }
      });
    };
    render1();
  }

  // --- connect an agent (MCP) ------------------------------------------------------------------------------------------------
  const copyText = async (text, label) => { try { await navigator.clipboard.writeText(text); toast(`${label} copied.`); } catch { toast('Copy failed; select the text and copy it by hand.', true); } };
  async function renderConnect() {
    const info = await api(P('/mcp')); const row = projectRow(); let client = info.clients[0].id;
    const current = () => info.clients.find((c) => c.id === client);
    $('main').innerHTML = `<div class="page-head"><h1>Connect an agent</h1><span class="secondary">${esc(row?.name || state.project)} · Model Context Protocol over stdio</span></div>
      <p class="pretty" style="max-width:720px">Claude Code, Claude Desktop, Cursor, Codex, VS Code, or any MCP client can read this project's panels, history, comparisons, AI Overview citations, and insights, and start a collection when you allow it. The server runs on this machine from the workspace below; the SearchApi key never leaves it.</p>
      <div class="two">
        <div class="vstack g16">
          <div class="card pad vstack"><div class="card-head"><b>1 · Add the server to your client</b><span class="seg" id="client-seg">${info.clients.map((c) => `<button type="button" data-c="${c.id}" aria-pressed="${c.id === client}">${esc(c.label)}</button>`).join('')}</span></div><div id="client-body"></div></div>
          <div class="card pad vstack"><div class="card-head"><b>2 · Check it works</b><button class="btn" type="button" id="mcp-test">Test the connection</button></div><p class="secondary">Launches the same command a client would and runs the handshake (initialize, tools/list). Nothing is collected and no credits are spent.</p><div id="mcp-result"></div></div>
          <div class="card pad vstack"><div class="card-head"><b>3 · Ask</b></div><div class="mini-list">${info.prompts.map((p) => `<span>“${esc(p)}”</span>`).join('')}</div><p class="small muted">Intent labels are lexical estimates: ask the agent for the reasons and evidence before acting. <span class="mono">collect_now</span> spends SearchApi credits, so approve it deliberately.</p></div>
        </div>
        <div class="vstack g16">
          <div class="card pad vstack"><div class="card-head"><b>Server command</b><button class="btn small" type="button" id="copy-shell">Copy</button></div><pre class="code" id="shell">${esc(info.shell)}</pre><p class="small muted">Workspace <span class="mono">${esc(info.workspace)}</span>${info.env.PYTHONPATH ? ' · runs from a source checkout, so PYTHONPATH is included in every snippet' : ''}. Protocol ${esc(info.protocol)}.</p></div>
          <div class="card clip"><div class="card-title row-between"><b class="ink">Tools the agent gets</b><span class="secondary">${info.tools.length}</span></div>${info.tools.map((t) => `<div class="attn" style="grid-template-columns:150px minmax(0,1fr)"><span class="mono ink">${esc(t.name)}</span><span class="secondary pretty">${esc(t.description)}</span></div>`).join('')}</div>
        </div>
      </div>`;
    const drawClient = () => { const c = current(); $('client-body').innerHTML = `<pre class="code">${esc(c.text)}</pre><div class="row-between mt8"><span class="small muted pretty">${esc(c.where)}</span><button class="btn small" type="button" id="copy-client">Copy</button></div>`; $('copy-client').addEventListener('click', () => copyText(c.text, `${c.label} config`)); };
    $('client-seg').addEventListener('click', (e) => { const b = e.target.closest('button[data-c]'); if (!b) return; client = b.dataset.c; $('client-seg').querySelectorAll('button').forEach((x) => x.setAttribute('aria-pressed', x === b)); drawClient(); });
    $('copy-shell').addEventListener('click', () => copyText(info.shell, 'Command'));
    $('mcp-test').addEventListener('click', async () => {
      $('mcp-test').disabled = true; $('mcp-test').textContent = 'Testing…'; $('mcp-result').innerHTML = '<div class="skeleton" style="width:60%"></div>';
      try { const r = await api(P('/mcp/check'), { method: 'POST', body: {} }); $('mcp-result').innerHTML = r.ok ? `<div class="status ok">${dot('ok')}Connected: ${esc(r.server?.name || 'server')} ${esc(r.server?.version || '')} · ${plural(r.tools.length, 'tool')} · protocol ${esc(r.protocol || '')}</div>` : `<div class="notice">Not working: ${esc(r.error)}<br><span class="mono">${esc(r.command)}</span></div>`; } catch (error) { fail(error); }
      $('mcp-test').disabled = false; $('mcp-test').textContent = 'Test the connection';
    });
    drawClient();
  }

  // --- portfolio + new project ----------------------------------------------------------------------------------------------------
  async function renderPortfolio() {
    const pf = state.portfolio = await api('/api/portfolio'); const rows = pf.projects; const lastRuns = rows.map((r) => r.last_run?.finished_at).filter(Boolean).sort();
    const healthCls = { ok: 'muted', error: 'c-review', stale: 'c-review', muted: 'muted' }; const dotOf = (r) => r.counts?.review ? 'review' : r.health_kind === 'error' ? 'err' : r.health_kind === 'stale' ? 'hollow' : r.counts?.watch ? 'watch' : (r.counts?.building_baseline || r.counts?.awaiting_data) && !r.counts?.stable ? 'info' : 'ok';
    const statusText = (c) => [c.review ? `${c.review} review` : '', c.watch ? `${c.watch} watch` : '', (c.building_baseline || 0) + (c.baseline_ready || 0) ? `${(c.building_baseline || 0) + (c.baseline_ready || 0)} building` : '', c.collection_error ? `${c.collection_error} errors` : ''].filter(Boolean).join(' · ') || (c.stable ? 'all stable' : 'no captures');
    const cols = 'grid-template-columns:minmax(0,1.5fr) 150px 70px 220px 140px 90px';
    $('main').innerHTML = `<div class="page-head"><h1>Portfolio</h1><span class="secondary">${plural(rows.length, 'project')} · ${plural(pf.panels, 'panel')}${lastRuns.length ? ` · collected ${ago(lastRuns[lastRuns.length - 1])} ${T(lastRuns[lastRuns.length - 1])}` : ''}</span><div class="spacer">${state.status.projects_root ? '<a class="btn" href="#/new-project">New project</a>' : ''}<button class="btn primary" type="button" id="collect-all" data-collect="Collect all">Collect all</button></div></div>
      <section class="section"><div class="section-head"><h2>Needs attention</h2><span class="secondary">${pf.attention.length || ''}</span></div><div class="card list" id="attention">${attentionHtml(pf.attention, true) || `<div class="attn-empty">No unhandled confirmed change. ${plural(pf.panels, 'panel')}${lastRuns.length ? ` collected ${ago(lastRuns[lastRuns.length - 1])}` : ''}.</div>`}</div></section>
      <section class="section"><h2 class="section-title">Projects</h2><div class="card grid-table"><div class="gh" style="${cols}"><span>Project</span><span>Market</span><span class="right">Panels</span><span>Status</span><span>Collection</span><span class="right">Credits / day</span></div>${rows.map((r) => `<a class="gr" href="#/p/${encodeURIComponent(r.id)}" style="${cols}"><span style="display:flex;align-items:center;gap:10px;min-width:0">${dot(dotOf(r))}<span class="q">${esc(r.name)}</span></span><span class="muted">${esc(r.market || '—')}</span><span class="right">${r.panels}</span><span class="muted">${esc(statusText(r.counts || {}))}</span><span class="${healthCls[r.health_kind] || 'muted'}">${esc(r.health)}</span><span class="right">${r.credits_per_day}</span></a>`).join('')}</div></section>`;
    bindAttention($('attention'));
    $('collect-all').addEventListener('click', async () => { try { await api('/api/collect-all', { method: 'POST', body: {} }); toast('Collecting every project…'); startPolling(); } catch (error) { fail(error); } });
    renderTopActions();
  }
  function renderNewProject() {
    $('main').innerHTML = `<div class="crumbs"><a href="#/portfolio">Portfolio</a> / New project</div><div class="page-head"><h1>New project</h1><span class="secondary">one site, one market default, its own database</span></div>
      <form class="card pad settings narrow" id="f-new"><div class="lbl"><b>Site</b><p>The hostname the app should look for in results.</p></div><div class="form-grid"><label class="field"><span>Site</span><input type="text" name="site" required placeholder="example.com"></label><label class="field"><span>Name</span><input type="text" name="name" placeholder="defaults to the site"></label></div><div class="lbl"><b>Default market</b><p>Panels inherit it; each panel can override.</p></div><div class="form-grid"><label class="field"><span>Country (gl)</span><input type="text" name="gl" value="us"></label><label class="field"><span>Language (hl)</span><input type="text" name="hl" value="en"></label><label class="field"><span>Device</span>${select('name="device"', DEVICES, 'desktop')}</label></div><div class="lbl"><b>SearchApi key</b><p>Optional here; add it later in the project's Settings.</p></div><div class="form-grid"><label class="field"><span>Key</span><input type="password" name="api_key" autocomplete="off"></label></div><div></div><div class="form-actions"><button class="btn primary" type="submit">Create project</button><a class="btn" href="#/portfolio">Cancel</a></div></form>`;
    $('f-new').addEventListener('submit', async (e) => { e.preventDefault(); const f = e.target; try { const r = await api('/api/projects', { method: 'POST', body: { site: f.elements.site.value.trim(), name: f.elements.name.value.trim(), gl: f.elements.gl.value.trim(), hl: f.elements.hl.value.trim(), device: f.elements.device.value, api_key: f.elements.api_key.value.trim() || undefined } }); toast(`Project ${r.name} created.`); invalidate(); await loadStatus(); go(`#/p/${encodeURIComponent(r.id)}/import`); } catch (error) { fail(error); } });
  }

  // --- router -----------------------------------------------------------------------------------------------------------------------
  async function render() {
    const { parts, params } = route();
    try { if (!state.status) await loadStatus(); } catch (error) { $('main').innerHTML = `<div class="notice">Cannot reach the app: ${esc(error.message)}</div>`; return; }
    let view = 'dashboard'; let portfolio = false;
    if (parts[0] === 'p' && parts[1]) { state.project = parts[1]; view = parts[2] || 'dashboard'; if (view === 'panel') view = 'panel'; }
    else if (parts[0] === 'portfolio') { portfolio = true; view = parts[1] === 'insights' ? 'pinsights' : parts[1] === 'runs' ? 'pruns' : 'portfolio'; }
    else if (parts[0] === 'new-project') { portfolio = true; view = 'new'; }
    else if (state.status.multi_project && !parts.length) { portfolio = true; view = 'portfolio'; }
    if (!state.status.projects.some((p) => p.id === state.project)) state.project = state.status.project.id;
    renderSidebar({ view, portfolio });
    renderTopActions();
    $('main').innerHTML = '<div class="skeleton" style="width:40%"></div>';
    try {
      if (view === 'portfolio') return await renderPortfolio();
      if (view === 'pinsights') return await renderInsights(params, true);
      if (view === 'pruns') return await renderRuns(true);
      if (view === 'new') return renderNewProject();
      if (view === 'panel' && parts[3]) return await renderPanel(parts[3], params.get('tab') || 'overview');
      if (view === 'panels') return await renderPanels();
      if (view === 'activity') return await renderActivity();
      if (view === 'insights') return await renderInsights(params, false);
      if (view === 'runs') return await renderRuns(false);
      if (view === 'settings') return await renderSettings();
      if (view === 'import') return await renderImport();
      if (view === 'connect') return await renderConnect();
      return await renderDashboard();
    } catch (error) { $('main').innerHTML = `<div class="notice">${esc(error.message)}</div>`; console.error(error); }
  }
  window.addEventListener('hashchange', render);
  render().then(() => { if ((state.status?.projects || []).some((p) => p.running)) startPolling(); });
})();
