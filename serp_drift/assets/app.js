/* serp-drift app · triage redesign (0.7). Hash routes over the JSON API; no build step, no dependencies. */
(() => {
  'use strict';
  const U = window.SerpUI;
  const { I, esc, D, T, ago, until, pct, n, plural } = U;
  const $ = (id) => document.getElementById(id);
  const enc = encodeURIComponent;
  const REPO = 'https://github.com/alhoniko/serp-intent-drift';
  const state = { status: null, project: null, reports: new Map(), panels: new Map(), activity: new Map(), attention: new Map(), pollTimer: null, theme: 'dark', keys: null, palette: { open: false, index: 0, items: [], all: [] } };

  // --- plumbing ----------------------------------------------------------------------------------------------------
  async function api(path, options = {}) {
    const init = { method: options.method || 'GET', headers: { 'X-Requested-With': 'serp-drift' } };
    if (options.body !== undefined) { init.headers['Content-Type'] = options.raw ? 'text/plain; charset=utf-8' : 'application/json'; init.body = options.raw ? options.body : JSON.stringify(options.body); }
    const response = await fetch(path, init);
    let body = null;
    try { body = await response.json(); } catch { body = null; }
    if (!response.ok) throw new Error(body?.error || `${response.status} ${response.statusText}`);
    return body;
  }
  const P = (path, pid = state.project) => `/api/p/${enc(pid)}${path}`;
  const link = { project: (pid = state.project) => `#/p/${enc(pid)}`, view: (v, pid = state.project) => `#/p/${enc(pid)}/${v}`, panel: (id, tab, pid = state.project) => `#/p/${enc(pid)}/panel/${enc(id)}${tab ? `?tab=${tab}` : ''}` };
  function toast(message, error = false) { const el = document.createElement('div'); el.className = `toast${error ? ' error' : ''}`; el.textContent = message; $('toasts').appendChild(el); setTimeout(() => el.remove(), error ? 7000 : 3500); }
  const fail = (error) => { toast(error.message || String(error), true); console.error(error); };
  const go = (hash) => { location.hash = hash; };
  const route = () => { const [path, query] = location.hash.replace(/^#\/?/, '').split('?'); return { parts: path.split('/').filter(Boolean).map(decodeURIComponent), params: new URLSearchParams(query || '') }; };
  async function loadStatus() { state.status = await api('/api/status'); if (!state.project || !state.status.projects.some((p) => p.id === state.project)) state.project = state.status.project.id; }
  async function report(pid = state.project, fresh = false) { if (fresh || !state.reports.has(pid)) state.reports.set(pid, await api(P('/report', pid))); return state.reports.get(pid); }
  async function panelData(id, pid = state.project, fresh = false) { const key = `${pid}/${id}`; if (fresh || !state.panels.has(key)) state.panels.set(key, await api(P(`/panels/${enc(id)}`, pid))); return state.panels.get(key); }
  async function activity(pid = state.project) { if (!state.activity.has(pid)) state.activity.set(pid, await api(P('/activity', pid)).catch(() => ({ events: [], runs: [] }))); return state.activity.get(pid); }
  async function attention(pid = state.project) { if (!state.attention.has(pid)) state.attention.set(pid, await api(P('/attention', pid)).catch(() => ({ attention: [] }))); return state.attention.get(pid); }
  function invalidate() { state.reports.clear(); state.panels.clear(); state.activity.clear(); state.attention.clear(); }
  const projects = () => state.status?.projects || [];
  const projectRow = (pid = state.project) => projects().find((p) => p.id === pid);
  const engines = () => state.status?.engines || {};
  const isRunning = () => projects().some((p) => p.running);
  const priority = { review: 0, collection_error: 1, data_quality: 1, stale: 2, watch: 3, insufficient_data: 4, baseline_ready: 5, building_baseline: 6, awaiting_data: 7, stable: 8 };
  const sortQueries = (qs) => [...qs].sort((a, b) => (priority[a.status] ?? 9) - (priority[b.status] ?? 9) || (b.score || 0) - (a.score || 0) || a.query.localeCompare(b.query));
  function scoreDelta(q) { const scored = (q.timeline || []).filter((p) => p.score != null && U.capKind(p) === 's'); if (scored.length < 2) return null; return Math.round(scored[scored.length - 1].score - scored[scored.length - 2].score); }
  const deltaHtml = (d) => d == null ? '<span class="delta"></span>' : `<span class="delta${d > 0 ? ' up' : ''}">${d > 0 ? '+' : d < 0 ? '−' : ''}${Math.abs(d)}</span>`;
  const seen = (q) => Boolean(q.acknowledged_at && q.latest?.captured_at && q.acknowledged_at >= q.latest.captured_at);
  function siteHit(q) { const s = U.siteTrack(q); return s.dropped || s.moved || s.entered || s.urlChanged ? 1 : 0; }
  function sitePosition(q) { if (q.site?.position) return { pos: q.site.position, url: q.site.url }; if (q.page_position && q.latest?.page) return { pos: q.page_position, url: q.latest.page.url }; return null; }
  const cited = (q) => Boolean(q.site?.cited || q.latest?.ai_overview?.page_cited || q.latest?.ai_overview?.host_cited);

  // --- collection + polling ----------------------------------------------------------------------------------------
  async function collect(ids, force, pid = state.project) {
    try { const result = await api(P('/collect', pid), { method: 'POST', body: { ids, force } }); toast(result.started ? (ids ? 'Collecting this panel…' : 'Collecting every due panel…') : 'A collection is already running.'); startPolling(); } catch (error) { fail(error); }
  }
  async function collectAll() { try { await api('/api/collect-all', { method: 'POST', body: {} }); toast('Collecting every due panel in every project…'); startPolling(); } catch (error) { fail(error); } }
  function startPolling() { if (!state.pollTimer) state.pollTimer = setInterval(pollRun, 3000); renderCollector(); }
  async function pollRun() {
    try { await loadStatus(); } catch (error) { return fail(error); }
    renderCollector();
    if (!isRunning()) { clearInterval(state.pollTimer); state.pollTimer = null; const last = projectRow()?.last_run; if (last) toast(last.error ? `Collection error: ${last.error}` : `${last.collected} collected · ${last.skipped} skipped · ${last.failed} failed`, Boolean(last.error || last.failed)); invalidate(); render(); }
  }

  // --- theme ---------------------------------------------------------------------------------------------------------
  const THEMES = ['dark', 'light', 'system'];
  function applyTheme(theme) { state.theme = THEMES.includes(theme) ? theme : 'dark'; if (state.theme === 'dark') delete document.documentElement.dataset.theme; else document.documentElement.dataset.theme = state.theme; }
  function cycleTheme() { applyTheme(THEMES[(THEMES.indexOf(state.theme) + 1) % THEMES.length]); try { localStorage.setItem('serp-drift-theme', state.theme); } catch {} const b = $('theme-btn'); if (b) { b.innerHTML = themeIcon(); b.title = `Theme: ${state.theme}`; } toast(`Theme: ${state.theme}`); }
  const themeIcon = () => I(state.theme === 'light' ? 'sun' : state.theme === 'system' ? 'system' : 'moon');
  try { applyTheme(new URLSearchParams(location.search).get('theme') || localStorage.getItem('serp-drift-theme') || 'dark'); } catch { applyTheme('dark'); }

  // --- shell ---------------------------------------------------------------------------------------------------------
  const initial = (name) => (String(name || '?').replace(/^(study:|the )\s*/i, '').trim()[0] || '?').toUpperCase();
  function inboxCount(row) { if (!row) return 0; return (row.counts?.watch || 0) + (row.attention || 0); }
  function navItems(view, portfolio) {
    if (portfolio) return [['#/portfolio', 'projects', 'Projects', view === 'portfolio', projects().length], ['#/portfolio/inbox', 'inbox', 'Inbox', view === 'pinbox', projects().reduce((a, p) => a + inboxCount(p), 0)], ['#/portfolio/insights', 'insights', 'Insights', view === 'pinsights'], ['#/portfolio/log', 'log', 'Log', view === 'plog']];
    const row = projectRow();
    return [[link.project(), 'inbox', 'Inbox', view === 'inbox', inboxCount(row), (row?.counts?.review || 0) > 0], [link.view('panels'), 'panels', 'Panels', view === 'panels' || view === 'panel' || view === 'add', row?.panels], [link.view('insights'), 'insights', 'Insights', view === 'insights'], [link.view('log'), 'log', 'Log', view === 'log'], [link.view('settings'), 'settings', 'Settings', view === 'settings']];
  }
  function switcherMenu(portfolio) {
    const items = [];
    if (state.status.multi_project) items.push(`<a role="menuitem" href="#/portfolio"${portfolio ? ' aria-current="true"' : ''}><span class="avatar">∗</span><span class="nowrap">All projects</span><span class="k">${plural(projects().length, 'project')}</span></a><div class="sep"></div>`);
    projects().forEach((p) => { const dotKind = p.counts?.review ? 'review' : p.health_kind === 'error' ? 'err' : p.counts?.watch ? 'watch' : p.health_kind === 'ok' ? 'ok' : 'hollow'; items.push(`<a role="menuitem" href="${link.project(p.id)}"${!portfolio && p.id === state.project ? ' aria-current="true"' : ''}><span class="avatar">${esc(initial(p.name))}</span><span class="nowrap">${esc(p.name)}</span><span class="k"><i class="dot ${dotKind}"></i> ${p.counts?.watch ? `${p.counts.watch} watching` : plural(p.panels, 'panel')}</span></a>`); });
    if (state.status.projects_root) items.push(`<div class="sep"></div><a role="menuitem" href="#/new-project">${I('plus')}<span>New project</span></a>`);
    return items.join('');
  }
  function collectorHtml(portfolio) {
    const sched = state.status.scheduler || {}; const row = portfolio ? null : projectRow(); const running = portfolio ? isRunning() : row?.running;
    const budget = row?.budget; const stopped = Boolean(budget?.stopped);
    const nextAt = sched.enabled ? (portfolio ? sched.next_due_at : sched.next_by_project?.[state.project]) : null;
    const label = running ? 'Collecting now…' : stopped ? 'Collection ended' : sched.enabled ? 'Collecting on schedule' : 'Scheduler off';
    const perDay = portfolio ? projects().reduce((a, p) => a + (p.credits_per_day || 0), 0) : row?.credits_per_day;
    const used = portfolio ? projects().reduce((a, p) => a + (p.budget?.used || 0), 0) : budget?.used;
    const capped = !portfolio && budget?.cap;
    return `<div class="collector" id="collector"><div class="state"><i class="dot ${running ? 'run' : stopped || !sched.enabled ? 'hollow' : 'ok'}"></i><span>${label}</span></div>
      ${sched.enabled && !stopped ? `<div class="kv">Next run<b>${nextAt ? `${T(nextAt)} UTC · ${until(nextAt)}` : '—'}</b></div>` : !sched.enabled ? '<div class="kv">Runs<b>on Collect, cron or CI</b></div>' : ''}
      <div class="kv">Requests<b class="num">${n(used || 0)}${capped ? ` / ${n(budget.cap)}` : ' · no cap'}</b></div>
      ${capped ? `<div class="track"><i style="width:${Math.min(100, (budget.used / budget.cap) * 100).toFixed(1)}%"></i></div>` : ''}
      <div class="note">${!portfolio && budget?.until ? `${stopped ? 'Stopped' : 'Stops'} ${D(budget.until)}, ${T(budget.until)} UTC` : `≈ ${n(perDay || 0)} requests a day before retries`}</div>
      <button class="btn small block" type="button" id="collect-btn" ${running || stopped ? 'disabled' : ''}>${I('collect')}${running ? 'Collecting…' : portfolio ? 'Collect all due' : 'Collect now'}</button>
      <div class="src">Captures via SearchApi</div></div>`;
  }
  function renderCollector() {
    const box = $('collector'); if (!box || !state.status) return;
    box.outerHTML = collectorHtml(state.scope === 'portfolio');
    $('collect-btn')?.addEventListener('click', () => (state.scope === 'portfolio' ? collectAll() : collect(undefined, false)));
  }
  function renderSidebar(view, portfolio) {
    const row = projectRow();
    const name = portfolio ? 'All projects' : row?.name || state.project;
    const meta = portfolio ? `${plural(projects().length, 'project')} · ${plural(projects().reduce((a, p) => a + (p.panels || 0), 0), 'panel')}` : `${row?.site || 'no site set'} · ${plural(row?.panels || 0, 'panel')}`;
    $('sidebar').innerHTML = `<div class="brand"><i class="mark"></i><b>serp-drift</b><span class="ver">${esc((state.status.version || '').replace(/\.0$/, ''))}</span><span class="grow"></span><a class="icon-btn" href="${REPO}" target="_blank" rel="noopener noreferrer" title="Source code" aria-label="Source code">${I('source')}</a><button class="icon-btn" type="button" id="theme-btn" title="Theme: ${state.theme}" aria-label="Switch theme">${themeIcon()}</button></div>
      <div class="gap-10"></div>
      <div class="switcher-wrap"><button class="switcher" id="switcher" type="button" aria-haspopup="menu" aria-expanded="false"><span class="avatar">${portfolio ? '∗' : esc(initial(name))}</span><span class="t"><b class="nowrap">${esc(name)}</b><span class="nowrap">${esc(meta)}</span></span>${I('updown')}</button><div class="menu" id="switcher-menu" role="menu" hidden>${switcherMenu(portfolio)}</div></div>
      <div class="gap-8"></div>
      <button class="search-btn" type="button" id="search-btn">${I('search')}<span>Search or jump to…</span>${U.kbd(`${U.MOD}K`)}</button>
      <div class="gap-12"></div>
      <nav class="nav" aria-label="Sections">${navItems(view, portfolio).map(([href, icon, label, active, count, hot]) => `<a href="${href}"${active ? ' aria-current="page"' : ''}>${I(icon)}<span>${label}</span>${count ? `<span class="count${hot ? ' hot' : ''}">${n(count)}</span>` : ''}</a>`).join('')}</nav>
      <div class="fill"></div>
      <nav class="nav secondary" aria-label="More">${portfolio ? '' : `<a href="${link.view('connect')}"${view === 'connect' ? ' aria-current="page"' : ''}>${I('agent')}<span>Agent (MCP)</span></a>`}<a href="${REPO}#readme" target="_blank" rel="noopener noreferrer">${I('docs')}<span>Documentation</span><span class="ext">${I('external')}</span></a></nav>
      ${collectorHtml(portfolio)}`;
    const button = $('switcher'); const menu = $('switcher-menu');
    const links = () => [...menu.querySelectorAll('a')];
    const open = (focus) => { menu.hidden = false; button.setAttribute('aria-expanded', 'true'); if (focus) (links().find((a) => a.hasAttribute('aria-current')) || links()[0])?.focus(); };
    const close = () => { menu.hidden = true; button.setAttribute('aria-expanded', 'false'); };
    button.addEventListener('click', () => (menu.hidden ? open(false) : close()));
    button.addEventListener('keydown', (e) => { if (e.key === 'ArrowDown') { e.preventDefault(); open(true); } });
    menu.addEventListener('keydown', (e) => { const l = links(); const i = l.indexOf(document.activeElement); if (e.key === 'ArrowDown') { e.preventDefault(); l[(i + 1) % l.length]?.focus(); } else if (e.key === 'ArrowUp') { e.preventDefault(); l[(i - 1 + l.length) % l.length]?.focus(); } else if (e.key === 'Escape') { close(); button.focus(); } });
    $('theme-btn').addEventListener('click', cycleTheme);
    $('search-btn').addEventListener('click', openPalette);
    $('collect-btn')?.addEventListener('click', () => (portfolio ? collectAll() : collect(undefined, false)));
    $('sidebar').classList.remove('open'); $('scrim').hidden = true;
  }
  function renderMobile(view, portfolio) {
    const row = projectRow(); const name = portfolio ? 'All projects' : row?.name || state.project;
    $('topbar').innerHTML = `<button class="icon-btn" type="button" id="drawer-btn" aria-label="Open navigation">${I('menu')}</button><button class="proj" type="button" id="drawer-btn-2"><span class="avatar">${portfolio ? '∗' : esc(initial(name))}</span><b>${esc(name)}</b></button><button class="icon-btn boxed" type="button" id="search-m" aria-label="Search">${I('search')}</button>`;
    const tabs = portfolio ? [['#/portfolio', 'projects', 'Projects', view === 'portfolio'], ['#/portfolio/inbox', 'inbox', 'Inbox', view === 'pinbox'], ['#/portfolio/insights', 'insights', 'Insights', view === 'pinsights'], ['#/portfolio/log', 'log', 'Log', view === 'plog']]
      : [[link.project(), 'inbox', 'Inbox', view === 'inbox'], [link.view('panels'), 'panels', 'Panels', view === 'panels' || view === 'panel'], [link.view('insights'), 'insights', 'Insights', view === 'insights'], [link.view('log'), 'log', 'Log', view === 'log']];
    $('tabbar').innerHTML = tabs.map(([href, icon, label, active]) => `<a href="${href}"${active ? ' aria-current="page"' : ''}>${I(icon)}<span>${label}</span></a>`).join('') + `<button type="button" id="more-m">${I('more')}<span>More</span></button>`;
    const drawer = () => { $('sidebar').classList.add('open'); $('scrim').hidden = false; };
    ['drawer-btn', 'drawer-btn-2', 'more-m'].forEach((id) => $(id)?.addEventListener('click', drawer));
    $('search-m').addEventListener('click', openPalette);
  }
  $('scrim').addEventListener('click', () => { $('sidebar').classList.remove('open'); $('scrim').hidden = true; });
  document.addEventListener('click', (e) => { [['switcher', 'switcher-menu'], ['p-more', 'p-more-menu']].forEach(([b, m]) => { const button = $(b); const menu = $(m); if (button && menu && !menu.hidden && !menu.contains(e.target) && !button.contains(e.target)) { menu.hidden = true; button.setAttribute('aria-expanded', 'false'); } }); });

  // --- command palette -------------------------------------------------------------------------------------------------
  async function paletteItems() {
    const items = []; const pid = state.project; const r = route();
    const panelId = r.parts[0] === 'p' && r.parts[2] === 'panel' ? r.parts[3] : null;
    let rep = null; try { rep = await report(pid); } catch {}
    if (rep) sortQueries(rep.queries).forEach((q) => items.push({ group: 'Panels', icon: 'panels', label: q.query, meta: `${U.word(q)}${q.score != null ? ` ${Math.round(q.score)}` : ''} · ${U.marketText(q.search, engines())}`, href: link.panel(q.id), pill: q.status === 'watch' || q.status === 'review' ? q : null, key: 'open' }));
    if (state.status.multi_project) { items.push({ group: 'Projects', icon: 'projects', label: 'All projects', meta: plural(projects().length, 'project'), href: '#/portfolio' }); projects().forEach((p) => items.push({ group: 'Projects', icon: 'projects', label: p.name, meta: `${plural(p.panels, 'panel')}${p.counts?.watch ? ` · ${p.counts.watch} watching` : ''}`, href: link.project(p.id) })); }
    if (rep) { const seenUrls = new Map(); rep.queries.forEach((q) => (q.latest?.results || []).forEach((res) => { const hp = U.hostPath(res.url); if (!seenUrls.has(hp)) seenUrls.set(hp, { url: res.url, hits: [] }); seenUrls.get(hp).hits.push({ q, pos: res.position }); })); items.push(...[...seenUrls.entries()].map(([hp, v]) => ({ group: 'Pages and hosts', icon: 'globe', label: hp, meta: v.hits.slice(0, 2).map((h) => `#${h.pos} for ${h.q.query}`).join(' · ') + (v.hits.length > 2 ? ` · +${v.hits.length - 2}` : ''), href: link.panel(v.hits[0].q.id, 'history'), hidden: true }))); }
    if (panelId && rep) { const q = rep.queries.find((x) => x.id === panelId); if (q) items.push({ group: 'Actions', icon: 'compare', label: `Compare ${q.query}: baseline → latest`, href: link.panel(q.id, 'compare') }, { group: 'Actions', icon: 'log', label: `Open ${q.query} history`, href: link.panel(q.id, 'history') }, { group: 'Actions', icon: 'collect', label: `Collect ${q.query} now`, meta: 'spends credits', act: () => collect([q.id], true) }); }
    items.push({ group: 'Actions', icon: 'collect', label: 'Collect every due panel now', meta: 'spends credits', act: () => collect(undefined, false) }, { group: 'Actions', icon: 'plus', label: 'Add keywords', href: link.view('add') }, { group: 'Actions', icon: 'settings', label: 'Open settings', href: link.view('settings') }, { group: 'Actions', icon: 'agent', label: 'Connect an agent (MCP)', href: link.view('connect') }, { group: 'Actions', icon: 'download', label: 'Export report JSON', href: `/api/p/${enc(pid)}/export/report.json`, download: true }, { group: 'Actions', icon: 'moon', label: 'Switch theme', meta: `now ${state.theme}`, act: cycleTheme });
    return items;
  }
  async function openPalette() {
    const p = state.palette; p.returnFocus = document.activeElement; p.all = []; p.items = []; p.index = 0; p.open = true;
    $('palette-icon').innerHTML = I('search'); $('palette-input').value = ''; $('palette').showModal(); $('palette-input').focus(); renderPalette();
    p.all = await paletteItems(); filterPalette();
  }
  function filterPalette() {
    const p = state.palette; const q = $('palette-input').value.trim().toLowerCase();
    const match = (i) => i.label.toLowerCase().includes(q) || (i.meta || '').toLowerCase().includes(q);
    const pick = (group, limit) => p.all.filter((i) => i.group === group && (q ? match(i) : !i.hidden)).slice(0, limit);
    p.items = [...pick('Panels', q ? 8 : 6), ...pick('Projects', 5), ...(q.length >= 2 ? pick('Pages and hosts', 5) : []), ...pick('Actions', q ? 6 : 5)];
    p.index = Math.min(p.index, Math.max(0, p.items.length - 1)); renderPalette();
  }
  function renderPalette() {
    const p = state.palette; let last = '';
    $('palette-list').innerHTML = p.items.map((i, k) => { const head = i.group !== last ? `<li class="g" role="presentation">${esc(i.group)}</li>` : ''; last = i.group; return `${head}<li class="o" id="pal-${k}" role="option" aria-selected="${k === p.index}" data-k="${k}">${I(i.icon)}<b>${esc(i.label)}</b>${i.pill ? U.pill(i.pill, true) : ''}<span class="m">${esc(i.meta || '')}</span>${k === p.index ? `<span class="k">↵ ${i.act ? 'run' : 'open'}</span>` : ''}</li>`; }).join('') || (p.all.length ? '<li class="none">No match.</li>' : '<li class="none">Loading…</li>');
    $('palette-input').setAttribute('aria-activedescendant', p.items.length ? `pal-${p.index}` : '');
    $(`pal-${p.index}`)?.scrollIntoView({ block: 'nearest' });
  }
  function closePalette() { const p = state.palette; p.open = false; $('palette').close(); p.returnFocus?.focus?.(); }
  function runPalette(item) { if (!item) return; closePalette(); if (item.act) return item.act(); if (item.download) { const a = document.createElement('a'); a.href = item.href; a.download = 'serp-drift-report.json'; a.click(); return; } go(item.href); }
  $('palette-input').addEventListener('input', () => { state.palette.index = 0; filterPalette(); });
  $('palette-input').addEventListener('keydown', (e) => { const p = state.palette; if (e.key === 'ArrowDown') { p.index = Math.min(p.index + 1, p.items.length - 1); renderPalette(); e.preventDefault(); } else if (e.key === 'ArrowUp') { p.index = Math.max(p.index - 1, 0); renderPalette(); e.preventDefault(); } else if (e.key === 'Enter') { e.preventDefault(); runPalette(p.items[p.index]); } });
  $('palette-list').addEventListener('click', (e) => { const li = e.target.closest('li[data-k]'); if (li) runPalette(state.palette.items[Number(li.dataset.k)]); });
  $('palette').addEventListener('close', () => { state.palette.open = false; });
  $('palette').addEventListener('click', (e) => { if (e.target === $('palette')) closePalette(); });
  document.addEventListener('keydown', (e) => {
    if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === 'k') { e.preventDefault(); state.palette.open ? closePalette() : openPalette(); return; }
    if (state.palette.open || e.metaKey || e.ctrlKey || e.altKey || e.target.matches('input, textarea, select, [contenteditable]')) return;
    if (e.key === '/') { e.preventDefault(); openPalette(); return; }
    if (state.keys) state.keys(e);
  });
  function rowKeys(selector) {
    return (e) => { if (!['j', 'k', 'Enter'].includes(e.key)) return; const rows = [...document.querySelectorAll(selector)]; if (!rows.length) return; const i = rows.indexOf(document.activeElement); if (e.key === 'Enter') { if (i >= 0) rows[i].click(); return; } e.preventDefault(); const next = e.key === 'j' ? Math.min(i + 1, rows.length - 1) : Math.max(i - 1, 0); rows[next].focus(); rows[next].scrollIntoView({ block: 'nearest' }); };
  }

  // --- inbox ---------------------------------------------------------------------------------------------------------
  async function renderInbox(params, portfolio) {
    const pids = portfolio ? projects().map((p) => p.id) : [state.project];
    const bundles = await Promise.all(pids.map(async (pid) => { const [rep, att, act] = await Promise.all([report(pid), attention(pid), activity(pid)]); return { pid, name: projectRow(pid)?.name || pid, rep, att: att.attention || [], events: [...(act.events || [])].sort((a, b) => b.at.localeCompare(a.at)) }; }));
    if (!portfolio && !bundles[0].rep.queries.length) { const status = await api(P('/status')); return window.SerpSetup.mount($('main'), status, (path, body) => api(P(path), { method: 'POST', body }), async () => { invalidate(); await loadStatus(); await render(); }); }
    const all = bundles.flatMap((b) => b.rep.queries.map((q) => ({ key: `${b.pid}:${q.id}`, pid: b.pid, pname: b.name, q, events: b.events, rep: b.rep })));
    const byKey = new Map(all.map((e) => [e.key, e]));
    const reviews = bundles.flatMap((b) => b.att.filter((a) => a.kind === 'review' && a.panel).map((a) => ({ ...byKey.get(`${b.pid}:${a.panel}`), att: a }))).filter((e) => e.q);
    const reviewKeys = new Set(reviews.map((e) => e.key));
    const issues = bundles.flatMap((b) => b.att.filter((a) => a.kind !== 'review').map((a, i) => { const base = a.panel ? byKey.get(`${b.pid}:${a.panel}`) : null; return { ...(base || { pid: b.pid, pname: b.name, events: b.events }), key: a.panel ? `${b.pid}:${a.panel}` : `${b.pid}:!${i}`, att: a, issue: true }; }));
    const watching = all.filter((e) => e.q.status === 'watch' && !reviewKeys.has(e.key)).sort((a, b) => siteHit(b.q) - siteHit(a.q) || (b.q.score || 0) - (a.q.score || 0));
    const unseen = watching.filter((e) => !seen(e.q)); const seenList = watching.filter((e) => seen(e.q));
    const since = Date.now() - 86400000;
    const settled = bundles.flatMap((b) => { const latest = new Map(); b.events.filter((ev) => ev.kind === 'status_change' && new Date(ev.at).getTime() >= since).forEach((ev) => { if (!latest.has(ev.target_id)) latest.set(ev.target_id, ev); }); return [...latest.values()].filter((ev) => ev.payload?.after === 'stable' && ['watch', 'review'].includes(ev.payload?.before)).map((ev) => ({ ...byKey.get(`${b.pid}:${ev.target_id}`), ev })).filter((x) => x.q && x.q.status === 'stable'); });
    const order = [...reviews, ...unseen, ...issues, ...seenList, ...settled];
    let sel = params.get('sel'); if (!order.some((e) => e.key === sel)) sel = order[0]?.key || null;
    const count = (k) => all.filter((e) => U.kind(e.q.status) === k).length;
    const total = all.length; const nWatch = watching.length; const nReview = reviews.length; const nIssue = issues.length;
    const today = new Date().toISOString().slice(0, 10);
    const capturedToday = all.filter((e) => (e.q.latest?.captured_at || '').startsWith(today)).length;
    const across = portfolio && pids.length > 1 ? ` across ${pids.length} projects` : '';
    const headline = nReview ? `${nReview === 1 ? 'One change needs' : `${nReview} changes need`} a decision.${nWatch ? ` ${nWatch} more drifting${across}.` : ''}`
      : nWatch ? `${nWatch} ${nWatch === 1 ? 'panel is' : 'panels are'} drifting${across}. Nothing is confirmed.`
      : count('building') === total ? 'Building baselines. No scores yet.'
      : `All quiet${across || ` across ${plural(total, 'panel')}`}.`;
    const building = all.filter((e) => U.BUILDING.includes(e.q.status));
    const firstScore = building.map((e) => U.addHours(e.q.latest?.captured_at, ((e.q.settings?.baseline_size ?? 3) - (e.q.baseline?.length ?? 0) + 1) * (e.q.settings?.interval_hours ?? 24))).filter(Boolean).sort()[0];
    const explainer = [capturedToday === total ? `All ${plural(total, 'panel')} were captured today.` : `${capturedToday} of ${plural(total, 'panel')} were captured today.`, nIssue ? `${plural(nIssue, 'collection issue')} ${nIssue === 1 ? 'needs' : 'need'} a fix.` : '', building.length ? `${plural(building.length, 'panel')} still ${building.length === 1 ? 'builds its' : 'build their'} baseline${firstScore ? `; first scores around ${D(firstScore)}` : ''}.` : '', nWatch && !nReview ? 'A watch becomes a review only when two spaced captures agree on an intent or page-fit change, so a reshuffled top 10 alone never asks you to rewrite a page.' : ''].filter(Boolean).join(' ');
    const seg = [['review', count('review'), 'Review'], ['watch', count('watch'), 'Watch'], ['stable', count('stable'), 'Stable'], ['building', count('building'), 'Building'], ['issues', count('issue'), 'Collection issues']];
    const rep0 = bundles[0].rep; const last = all.map((e) => e.q.latest?.captured_at).filter(Boolean).sort().pop();
    const meta = portfolio ? `${plural(pids.length, 'project')} · ${plural(total, 'panel')}${last ? ` · last capture ${T(last)} UTC` : ''}` : `${U.marketText(rep0.search, engines())} · ${plural(total, 'panel')}${last ? ` · last capture ${T(last)} UTC, ${ago(last)}` : ''}`;
    const head = (title, n2, extra = '') => `<div class="qhead"><span>${title}</span><span class="n">${n2}</span><span class="grow"></span>${extra}</div>`;
    const base = (e) => e.rep?.search || rep0.search;
    const qrow = (e, sub, extraCls = '') => `<div class="qrow${extraCls}" role="option" tabindex="-1" data-key="${esc(e.key)}" aria-selected="${e.key === sel}"><div class="t"><div class="row"><b>${esc(e.q.query)}</b>${U.marketTags(e.q.search, base(e), engines())}${siteHit(e.q) ? '<span class="tag you">your site</span>' : ''}${portfolio ? `<span class="tag">${esc(e.pname)}</span>` : ''}</div><small>${esc(sub)}</small></div>${U.strip(e.q.timeline, { count: 10, threshold: e.q.settings?.drift_threshold ?? 35 })}<div class="s"><b>${U.score(e.q.score)}</b>${deltaHtml(scoreDelta(e.q))}</div></div>`;
    const compact = (e, text, when) => `<div class="qrow compact" role="option" tabindex="-1" data-key="${esc(e.key)}" aria-selected="${e.key === sel}"><i class="dot stable"></i><div class="t"><span class="grow">${esc(e.q.query)}</span></div><span class="when">${esc(text)}</span><span class="when">${esc(when)}</span></div>`;
    const queue = [
      head('Needs a decision', nReview),
      nReview ? reviews.map((e) => qrow(e, U.cap(e.att.why || U.whyLine(e.q, e.events)))).join('') : `<div class="qempty">${I('ok')}Nothing confirmed. A review needs two spaced captures that agree.</div>`,
      '<div class="qdiv"></div>', head('Watching', unseen.length, unseen.length > 1 ? '<span class="hint">your site first, then score</span>' : ''),
      unseen.length ? unseen.map((e) => qrow(e, U.whyLine(e.q, e.events))).join('') : `<div class="qempty">${I('ok')}${nWatch ? 'Every watch is marked as seen.' : 'No panel is over the watch threshold.'}</div>`,
      nIssue ? `<div class="qdiv"></div>${head('Collection health', nIssue)}${issues.map((e) => e.q ? qrow(e, U.cap(e.att.why || ''), '') : `<div class="qrow" role="option" tabindex="-1" data-key="${esc(e.key)}" aria-selected="${e.key === sel}"><div class="t"><div class="row"><b>${esc(e.att.title)}</b>${portfolio ? `<span class="tag">${esc(e.pname)}</span>` : ''}</div><small>${esc(e.att.why || '')}</small></div>${U.pillFor('collection_error')}</div>`).join('')}` : '',
      seenList.length ? `<div class="qdiv"></div>${head('Seen', seenList.length, '<span class="hint">returns with the next capture</span>')}${seenList.map((e) => qrow(e, U.whyLine(e.q, e.events), ' seen')).join('')}` : '',
      settled.length ? `<div class="qdiv"></div>${head('Settled in the last 24 h', settled.length)}${settled.slice(0, 8).map((e) => compact(e, `${U.word(e.ev.payload.before)} → Stable`, T(e.ev.at))).join('')}<div class="gap-8"></div>` : '',
    ].join('');
    $('main').innerHTML = `<div class="page">
      <div class="page-head"><div class="title"><h1>Inbox</h1><span class="meta">${esc(meta)}</span></div>${unseen.length ? '<button class="btn ghost" type="button" id="mark-all">Mark all seen</button>' : ''}</div>
      <div class="headline"><h2>${esc(headline)}</h2>${explainer ? `<p>${esc(explainer)}</p>` : ''}</div>
      <div class="spectrum"><div class="bar" role="img" aria-label="${esc(seg.map(([, c, l]) => `${l} ${c}`).join(', '))}">${seg.filter(([, c]) => c).map(([k, c]) => `<i class="${k}" style="flex:${c}" title="${c} ${k}"></i>`).join('')}</div>
        <div class="legend">${seg.map(([k, c, l]) => `<span>${k === 'issues' ? I('alert') : `<i class="dot ${k === 'review' ? 'review' : k === 'watch' ? 'watch' : k === 'stable' ? 'stable' : 'hollow'}"></i>`}${l}<b class="${c ? '' : 'zero'}">${c}</b></span>`).join('')}</div></div>
      ${order.length ? `<div class="split"><div class="card clip queue" id="queue" role="listbox" aria-label="Inbox">${queue}</div><div class="card preview-pane" id="preview"></div></div>` : `<div class="card empty"><b>Nothing needs you.</b>${plural(total, 'panel')} are stable. <a class="link" href="${portfolio ? '#/portfolio' : link.view('panels')}">Open ${portfolio ? 'projects' : 'panels'}</a></div>`}
    </div>`;
    const select = (key, push = true) => {
      sel = key; document.querySelectorAll('#queue .qrow').forEach((r) => r.setAttribute('aria-selected', String(r.dataset.key === key)));
      const e = order.find((x) => x.key === key); if (e) renderPreview(e, portfolio);
      if (push) { const r = route(); r.params.set('sel', key); history.replaceState(null, '', `${location.pathname}#/${r.parts.map(enc).join('/')}?${r.params}`); }
    };
    const rows = () => [...document.querySelectorAll('#queue .qrow')];
    document.querySelectorAll('#queue .qrow').forEach((row) => { row.addEventListener('click', () => { select(row.dataset.key); row.focus({ preventScroll: true }); }); row.addEventListener('dblclick', () => { const e = order.find((x) => x.key === row.dataset.key); if (e?.q) go(link.panel(e.q.id, '', e.pid)); }); });
    state.keys = (ev) => {
      if (!['j', 'k', 'Enter', 'ArrowDown', 'ArrowUp', 'e'].includes(ev.key)) return;
      const list = rows(); const i = list.findIndex((r) => r.dataset.key === sel);
      if (ev.key === 'Enter') { const e = order.find((x) => x.key === sel); if (e?.q) go(link.panel(e.q.id, '', e.pid)); return; }
      if (ev.key === 'e') { const e = order.find((x) => x.key === sel); if (e?.q?.status === 'watch' && !seen(e.q)) markSeen(e); return; }
      ev.preventDefault(); const next = list[(ev.key === 'j' || ev.key === 'ArrowDown') ? Math.min(i + 1, list.length - 1) : Math.max(i - 1, 0)]; if (next) { select(next.dataset.key); next.focus({ preventScroll: true }); next.scrollIntoView({ block: 'nearest' }); }
    };
    $('mark-all')?.addEventListener('click', async () => { try { for (const e of unseen) await api(P(`/panels/${enc(e.q.id)}/acknowledge`, e.pid), { method: 'POST', body: {} }); toast(`${plural(unseen.length, 'watch', 'watches')} marked as seen.`); invalidate(); await loadStatus(); render(); } catch (error) { fail(error); } });
    if (sel) select(sel, false);
  }
  async function markSeen(e) { try { await api(P(`/panels/${enc(e.q.id)}/acknowledge`, e.pid), { method: 'POST', body: {} }); toast('Marked as seen until the next capture.'); invalidate(); await loadStatus(); render(); } catch (error) { fail(error); } }
  function renderPreview(e, portfolio) {
    const box = $('preview'); if (!box) return;
    if (!e.q) {
      const a = e.att; const act = a.action === 'settings' ? `<a class="btn primary" href="${link.view('settings', e.pid)}">Open settings</a>` : '';
      box.innerHTML = `<div class="preview"><div class="ph"><h2>${esc(a.title)}</h2>${U.pillFor('collection_error')}</div><p class="verdict-b">${esc(a.why)}</p><div class="form-actions">${act}</div></div>`; return;
    }
    const q = e.q; const th = q.settings?.drift_threshold ?? 35; const s = U.siteTrack(q); const lat = q.latest || {};
    const contribs = q.comparison ? U.contributions(q.comparison.components, e.rep?.weights) : null;
    const next = U.nextCapture(q); const cov = lat.classified_coverage;
    const aiPts = (q.timeline || []).filter((p) => U.capKind(p) !== 'x'); const aiSeen = aiPts.filter((p) => p.ai_overview_status === 'observed'); const aiCited = aiSeen.filter((p) => p.site_cited);
    const actions = e.att?.kind === 'review' ? `<a class="btn" href="${link.panel(q.id, '', e.pid)}">Open panel</a><a class="btn primary" href="${link.panel(q.id, 'evidence', e.pid)}">Record decision</a>`
      : e.issue ? `<a class="btn" href="${link.panel(q.id, '', e.pid)}">Open panel</a><button class="btn primary" type="button" id="pv-retry">${I('collect')}${e.att.action === 'collect' ? 'Collect now' : 'Retry now'}</button>`
      : q.status === 'watch' && !seen(q) ? `<button class="btn" type="button" id="pv-seen">Mark as seen</button><a class="btn primary" href="${link.panel(q.id, '', e.pid)}">Open panel</a>`
      : `<a class="btn primary" href="${link.panel(q.id, '', e.pid)}">Open panel</a>`;
    const verdict = [U.verdictText(q), q.decision?.next_action && q.status === 'review' ? q.decision.next_action : ''].filter(Boolean).join(' ') || q.decision?.next_action || '';
    box.innerHTML = `<div class="preview">
      <div class="ph"><h2>${esc(q.query)}</h2>${U.pill(q, true)}<span class="chip">${esc(U.marketText(q.search, engines()))}</span>${portfolio ? `<span class="tag">${esc(e.pname)}</span>` : ''}<span class="grow"></span>${actions}</div>
      <div class="stack" style="gap:6px"><div class="verdict-t">${esc(e.issue ? e.att.title : q.decision?.title || U.word(q))}</div>${(e.issue ? e.att.why : verdict) ? `<p class="verdict-b">${esc(e.issue ? e.att.why : verdict)}</p>` : ''}</div>
      <div class="stack" style="gap:10px"><div class="sub-h"><span>Score by capture</span><span class="grow"></span>${U.chartKey(q.timeline)}</div>${U.chart(q.timeline, q.settings, { height: 112, maxCols: 24, times: false })}</div>
      ${contribs ? `<div class="stack" style="gap:10px"><div class="sub-h"><span>Why ${U.score(q.score)}</span><span class="meta">· points out of 100, weights are fixed and versioned</span></div>${U.contribBar(contribs, th)}${U.contribLegend(contribs)}</div>` : ''}
      ${q.baseline?.length && lat.intent_distribution ? `<div class="stack" style="gap:8px"><div class="sub-h"><span>Intent mix</span><span class="meta">· ${pct(cov)} of rank weight classified · lexical estimate, not measured intent</span></div>${U.mixHtml(U.avgMix(q.baseline), lat.intent_distribution)}</div>` : ''}
      <div class="facts"><div class="fact"><span class="l">${I('globe')}Your site</span><b>${s.now ? `#${s.now}${s.moved ? ` (was #${s.from})` : ''}` : s.dropped ? 'Dropped out of the top 10' : 'Not in the top 10'}</b><p>${esc(s.now ? U.hostPath(s.url) : s.dropped ? `${U.hostPath(s.url)} held #${s.heldFrom}${s.heldTo !== s.heldFrom ? `–#${s.heldTo}` : ''} until ${U.DT(aiPts[aiPts.findIndex((p) => p.captured_at === s.leftAt) - 1]?.captured_at || s.leftAt)} UTC.` : e.rep?.project?.site ? `Tracked automatically for ${e.rep.project.site}.` : 'Set the project site to track your ranking URL.')}</p></div>
        <div class="fact"><span class="l">${I('quote')}AI Overview</span><b>${aiSeen.length ? `In ${aiSeen.length} of ${aiPts.length} captures` : 'Not observed'}</b><p>${aiSeen.length ? `${esc(e.rep?.project?.site || 'Your site')} cited in ${aiCited.length} of ${aiSeen.length}.` : 'No Overview in the accepted captures.'}</p></div></div>
      <div class="pfoot">${I('clock')}${next ? `Next capture ${T(next)} UTC, ${until(next)}.` : 'No capture scheduled.'}${q.paused ? ' Collection is paused for this panel.' : ''}</div>
    </div>`;
    $('pv-seen')?.addEventListener('click', () => markSeen(e));
    $('pv-retry')?.addEventListener('click', () => collect([q.id], true, e.pid));
  }

  // --- panels table -------------------------------------------------------------------------------------------------------
  async function renderPanels() {
    const rep = await report(); const events = (await activity()).events || []; const queries = sortQueries(rep.queries); const site = rep.project?.site; const base = rep.search;
    const is = { all: () => true, watch: (q) => q.status === 'watch', review: (q) => q.status === 'review', ranking: (q) => Boolean(sitePosition(q)), cited: cited, notranking: (q) => !sitePosition(q), building: (q) => U.BUILDING.includes(q.status), issues: (q) => U.ISSUES.includes(q.status) };
    const views = [['all', 'All'], ['watch', 'Watch'], ['review', 'Review'], ['ranking', 'Ranking'], ['cited', 'Cited'], ['notranking', 'Not ranking'], ['building', 'Building'], ['issues', 'Issues']].map(([k, l]) => [k, l, queries.filter(is[k]).length]).filter(([k, , c]) => c || ['all', 'watch', 'ranking', 'issues'].includes(k));
    const key = `serp-drift-view:${state.project}:panels`;
    let view = 'all', text = '', sort = 'priority', group = '';
    try { const saved = JSON.parse(localStorage.getItem(key) || '{}'); view = views.some(([k]) => k === saved.view) ? saved.view : view; text = saved.text || ''; sort = saved.sort || sort; group = saved.group || ''; } catch {}
    const groups = [...new Set(queries.map((q) => q.group).filter(Boolean))].sort();
    const ranking = queries.filter((q) => sitePosition(q)); const top3 = ranking.filter((q) => sitePosition(q).pos <= 3); const citedN = queries.filter(cited);
    $('main').innerHTML = `<div class="page">
      <div class="page-head"><div class="title"><h1>Panels</h1><span class="meta">${plural(queries.length, 'panel')}${site ? ` · ${esc(site)} ranks in ${ranking.length}, top 3 in ${top3.length} · cited by an AI Overview in ${citedN.length}` : ' · set the project site to track your ranking URLs'}</span></div><a class="btn hide-sm" href="/api/p/${enc(state.project)}/export/report.json" download="serp-drift-report.json">${I('download')}Export</a><a class="btn primary" href="${link.view('add')}">${I('plus')}Add keywords</a></div>
      <div class="toolbar"><input type="search" id="pf-text" placeholder="Filter by query or URL" aria-label="Filter panels" value="${esc(text)}"><div class="seg" id="pf-views">${views.map(([k, l, c]) => `<button type="button" data-v="${k}" aria-pressed="${k === view}">${l}<span class="n">${c}</span></button>`).join('')}</div><span class="grow"></span>${groups.length ? `<select class="input small" id="pf-group" aria-label="Keyword group"><option value="">All groups</option>${groups.map((g) => `<option value="${esc(g)}"${g === group ? ' selected' : ''}>${esc(g)}</option>`).join('')}</select>` : ''}<select class="input small" id="pf-sort" aria-label="Sort panels">${[['priority', 'Sort: priority'], ['score', 'Sort: change score'], ['query', 'Sort: A–Z'], ['coverage', 'Sort: lowest coverage']].map(([v, l]) => `<option value="${v}"${v === sort ? ' selected' : ''}>${l}</option>`).join('')}</select></div>
      <div class="card clip"><div class="table ptable"><div class="thead"><span>Query</span><span>Status</span><span class="right">Score ${I('down')}</span><span class="c-strip">Last 12 captures</span><span class="c-intent">Intent · coverage</span><span class="c-site">Your site</span><span class="c-aio">AI Overview</span><span class="right c-when">Captured</span></div><div id="pf-rows"></div></div><div class="tfoot" id="pf-foot"></div></div></div>`;
    const draw = () => {
      let rows = queries.filter(is[view]).filter((q) => !group || q.group === group).filter((q) => !text || q.query.toLowerCase().includes(text) || (q.latest?.results || []).some((r) => r.url.toLowerCase().includes(text)));
      if (sort === 'score') rows.sort((a, b) => (b.score ?? -1) - (a.score ?? -1));
      if (sort === 'query') rows.sort((a, b) => a.query.localeCompare(b.query));
      if (sort === 'coverage') rows.sort((a, b) => (a.latest?.classified_coverage ?? 2) - (b.latest?.classified_coverage ?? 2));
      $('pf-rows').innerHTML = rows.map((q) => {
        const pos = sitePosition(q); const s = U.siteTrack(q); const lat = q.latest || {}; const dom = lat.dominant_intent;
        const path = pos ? (site && U.host(pos.url).endsWith(site) ? U.pathOnly(pos.url) : U.hostPath(pos.url)) : '';
        const ai = lat.ai_overview_status === 'observed' ? (cited(q) ? `${I('quote')}<span>cited</span>` : '<span class="muted">not cited</span>') : '<span class="faint">—</span>';
        const flap = U.flapInfo(events, q.id);
        return `<a class="trow" href="${link.panel(q.id)}"><span class="cell-2"><span class="row"><span class="q nowrap">${esc(q.query)}</span>${U.marketTags(q.search, base, engines())}${q.group ? `<span class="tag">${esc(q.group)}</span>` : ''}</span>${flap.recent >= 3 ? `<span class="sub">${I('repeat')} ${flap.recent} status changes in 3 days</span>` : ''}</span><span>${U.pill(q)}</span><span class="right">${deltaHtml(scoreDelta(q))}<span class="score">${q.score == null ? (q.baseline && q.status === 'building_baseline' ? `<span class="muted">${q.baseline.length}/${q.settings?.baseline_size ?? 3}</span>` : '—') : Math.round(q.score)}</span></span><span class="c-strip">${U.strip(q.timeline, { count: 12, threshold: q.settings?.drift_threshold ?? 35, wide: true })}</span><span class="c-intent">${dom ? `<i class="sw ${esc(dom)}"></i><span class="dim">${esc(dom)}</span><span class="muted">${pct(lat.classified_coverage)}</span>` : '<span class="faint">—</span>'}</span><span class="c-site">${pos ? `<b class="num">#${pos.pos}</b><span class="dim nowrap">${esc(path)}</span>` : `<span class="muted nowrap">— ${s.dropped ? `dropped out (was #${s.was})` : 'not in top 10'}</span>`}</span><span class="c-aio">${ai}</span><span class="right muted c-when">${esc(ago(lat.captured_at))}</span></a>`;
      }).join('') || '<div class="empty">No panels match this view.</div>';
      $('pf-foot').innerHTML = `<span>${rows.length} of ${plural(queries.length, 'panel')}</span><span class="hints hide-sm"><span>${U.kbd('J')}${U.kbd('K')} move</span><span>${U.kbd('↵')} open</span><span>${U.kbd('/')} search</span></span>`;
      $('pf-views').querySelectorAll('button').forEach((b) => b.setAttribute('aria-pressed', String(b.dataset.v === view)));
      try { localStorage.setItem(key, JSON.stringify({ view, text, sort, group })); } catch {}
    };
    $('pf-views').addEventListener('click', (e) => { const b = e.target.closest('button[data-v]'); if (b) { view = b.dataset.v; draw(); } });
    $('pf-text').addEventListener('input', (e) => { text = e.target.value.trim().toLowerCase(); draw(); });
    $('pf-sort').addEventListener('change', (e) => { sort = e.target.value; draw(); });
    $('pf-group')?.addEventListener('change', (e) => { group = e.target.value; draw(); });
    state.keys = rowKeys('#pf-rows a.trow');
    draw();
  }

  // --- insights -------------------------------------------------------------------------------------------------------
  function mergeInsights(list) {
    const sum = (k) => list.reduce((a, d) => a + (d[k] || 0), 0);
    const avg = (get) => { const v = list.map(get).filter((x) => x != null); return v.length ? v.reduce((a, b) => a + b, 0) / v.length : null; };
    const hosts = {}; list.forEach((d) => d.hosts.forEach((h) => { hosts[h.host] = hosts[h.host] || { host: h.host, citations: 0, panels: 0, mine: false }; hosts[h.host].citations += h.citations; hosts[h.host].panels += h.panels; hosts[h.host].mine = hosts[h.host].mine || Boolean(h.mine); }));
    const features = {}; list.forEach((d) => d.features.forEach((f) => { features[f.feature] = features[f.feature] || { feature: f.feature, captures: 0 }; features[f.feature].captures += f.captures; }));
    const captures = sum('captures');
    const by = {}; ['language', 'device', 'engine'].forEach((g) => { by[g] = {}; list.forEach((d) => Object.entries(d.by[g] || {}).forEach(([k, r]) => { const t = by[g][k] || (by[g][k] = { panels: 0, captures: 0, ai_overview_share: null, turnover: null, intent_known: null, coverage: null, _n: 0 }); t.panels += r.panels; t.captures += r.captures; ['ai_overview_share', 'turnover', 'intent_known', 'coverage'].forEach((f) => { if (r[f] != null) t[f] = ((t[f] || 0) * t._n + r[f]) / (t._n + 1); }); t._n += 1; })); });
    const metrics = list.flatMap((d) => d.panel_metrics.map((m) => ({ ...m, pid: d.pid })));
    return { days: list[0].days, analysis_version: list[0].analysis_version, panels: sum('panels'), captures, overall: { ai_overview_share: avg((d) => d.overall.ai_overview_share), turnover: avg((d) => d.overall.turnover), intent_known: avg((d) => d.overall.intent_known) }, coverage_median: avg((d) => d.coverage_median), features: Object.values(features).map((f) => ({ ...f, share: captures ? f.captures / captures : null })).sort((a, b) => b.captures - a.captures), hosts: Object.values(hosts).sort((a, b) => b.citations - a.citations), by, your_pages: { tracked: list.reduce((a, d) => a + d.your_pages.tracked, 0), in_top_10_now: list.reduce((a, d) => a + d.your_pages.in_top_10_now, 0) }, most_volatile: metrics.filter((m) => m.turnover != null).sort((a, b) => b.turnover - a.turnover).slice(0, 10), most_stable: metrics.filter((m) => m.turnover != null).sort((a, b) => a.turnover - b.turnover).slice(0, 10) };
  }
  async function renderInsights(params, portfolio) {
    const days = params.get('days') || ''; const which = params.get('v') || 'volatile';
    const pids = portfolio ? projects().map((p) => p.id) : [state.project];
    const all = await Promise.all(pids.map((pid) => api(P(`/insights${days ? `?days=${enc(days)}` : ''}`, pid)).then((d) => ({ ...d, pid })).catch(() => null)));
    const data = all.filter(Boolean);
    const base = portfolio ? '#/portfolio/insights' : link.view('insights');
    const qs = (o) => { const p = new URLSearchParams({ ...(days ? { days } : {}), ...(which !== 'volatile' ? { v: which } : {}), ...o }); [...p.keys()].forEach((k) => { if (!p.get(k)) p.delete(k); }); const s = p.toString(); return s ? `?${s}` : ''; };
    if (!data.length || !data.some((d) => d.captures)) { $('main').innerHTML = `<div class="page"><div class="page-head"><div class="title"><h1>Insights</h1></div></div><div class="card empty"><b>No captures yet.</b>Insights appear after the first collection.</div></div>`; return; }
    const d = portfolio ? mergeInsights(data) : data[0];
    const site = portfolio ? null : (await report()).project?.site;
    const share = (v) => v == null ? '—' : pct(v);
    const maxHost = Math.max(1, ...d.hosts.slice(0, 10).map((h) => h.citations));
    const rowsFor = (items) => items.map((i) => `<a class="trow" href="${link.panel(i.id, '', i.pid || state.project)}"><span class="nowrap q">${esc(i.query)}</span><span class="right num">${share(i.turnover)}</span><span class="right num hide-sm">${i.rank_movement ?? '—'}</span><span class="hide-sm"><i class="sw ${esc(i.intent)}"></i><span class="muted nowrap">${esc(i.intent)} ${share(i.intent_stability)}</span></span><span class="right num hide-sm">${share(i.ai_overview_share)}</span><span class="right"><b class="num">${i.page_position ? `#${i.page_position}` : '<span class="faint">—</span>'}</b></span></a>`).join('') || '<div class="empty">Not enough captures yet.</div>';
    const slices = [...Object.entries(d.by.engine || {}).map(([k, r]) => [engines()[k] || k, r]), ...Object.entries(d.by.device || {}).map(([k, r]) => [U.cap(k), r]), ...Object.entries(d.by.language || {}).map(([k, r]) => [`Language ${k}`, r])];
    $('main').innerHTML = `<div class="page">
      <div class="page-head"><div class="title"><h1>Insights</h1><span class="meta">${days ? `Last ${days} days` : 'All stored captures'} · ${plural(d.captures, 'capture')} · rule version ${esc(d.analysis_version)}</span></div><div class="seg">${[['', 'All time'], ['7', '7 d'], ['30', '30 d'], ['90', '90 d']].map(([v, l]) => `<a href="${base}${qs({ days: v })}"${v === days ? ' aria-current="true"' : ''}>${l}</a>`).join('')}</div>${portfolio ? '' : `<a class="btn" href="/api/p/${enc(state.project)}/export/dataset.zip${days ? `?days=${enc(days)}` : ''}" download="serp-drift-dataset.zip">${I('download')}Download dataset</a>`}</div>
      <div class="stats"><div><b>${share(d.overall.ai_overview_share)}</b><span>captures with an AI Overview</span></div><div><b>${share(d.features.find((f) => f.feature === 'related_questions')?.share)}</b><span>with People also ask</span></div><div><b>${share(d.overall.turnover)}</b><span>mean top-10 turnover</span></div><div><b>${share(d.overall.intent_known)}</b><span>panels with decisive intent</span></div><div><b>${share(d.coverage_median)}</b><span>median coverage</span></div><div><b>${d.your_pages.in_top_10_now}<small> / ${d.your_pages.tracked}</small></b><span>your pages in the top 10</span></div></div>
      <div class="two"><div class="card pad"><div class="card-head"><h3>SERP features</h3><span class="meta">share of captures</span></div><div class="stack">${d.features.map((f) => U.hbar(U.FEATURES[f.feature] || f.feature, Math.round((f.share || 0) * 100), 100, { suffix: ' %', extra: n(f.captures) })).join('') || '<div class="note">No features observed yet.</div>'}</div></div>
        <div class="card pad"><div class="card-head"><h3>Most cited hosts in AI Overviews</h3><span class="meta">citations · panels</span></div><div class="stack">${d.hosts.slice(0, 10).map((h) => U.hbar(h.host, h.citations, maxHost, { mine: Boolean(h.mine || (site && (h.host === site || h.host.endsWith(`.${site}`)))), extra: plural(h.panels, 'panel') })).join('') || '<div class="note">No expanded Overviews yet.</div>'}</div></div></div>
      <div class="with-rail wide"><div class="card clip"><div class="card-head" style="padding:16px 18px 10px"><h3>${which === 'stable' ? 'Most stable' : 'Most volatile'}</h3><span class="meta">top-10 turnover · rank moves · intent stability</span><span class="grow"></span><div class="seg small">${[['volatile', 'Most volatile'], ['stable', 'Most stable']].map(([v, l]) => `<a href="${base}${qs({ v: v === 'volatile' ? '' : v })}"${v === which ? ' aria-current="true"' : ''}>${l}</a>`).join('')}</div></div><div class="table itable"><div class="thead"><span>Panel</span><span class="right">Turnover</span><span class="right hide-sm">Rank moves</span><span class="hide-sm">Intent · stability</span><span class="right hide-sm">AI Overview</span><span class="right">Your page</span></div>${rowsFor(which === 'stable' ? d.most_stable : d.most_volatile)}</div></div>
        <div class="card clip"><div class="card-head" style="padding:16px 18px 10px"><h3>By engine, device and language</h3></div><div class="table stable-t"><div class="thead"><span>Slice</span><span class="right">Panels</span><span class="right">AI Overview</span><span class="right">Turnover</span></div>${slices.map(([l, r]) => `<div class="trow"><span class="nowrap">${esc(l)}</span><span class="right num">${r.panels}</span><span class="right num">${share(r.ai_overview_share)}</span><span class="right num">${share(r.turnover)}</span></div>`).join('')}</div>${slices.some(([, r]) => r.panels < 3) ? '<div class="note" style="padding:10px 18px 14px">Slices with one or two panels are anecdotes, not trends.</div>' : ''}</div></div>
    </div>`;
    state.keys = rowKeys('.itable a.trow');
  }

  // --- log -------------------------------------------------------------------------------------------------------------
  function eventText(e) {
    const p = e.payload || {};
    if (e.kind === 'import_fetch') return `Fetched ${p.rows} keywords from Ahrefs for ${p.target}${p.units != null ? ` (${p.units} units)` : ''}`;
    if (e.kind === 'notification') return `Notification ${p.kind || ''} · ${p.ok ? 'delivered' : 'failed'}${p.status ? ` (${p.status})` : ''}`;
    if (e.kind === 'import') return `Import from ${p.source}: ${p.created} created, ${p.skipped} skipped, ${p.errors} errors`;
    if (e.kind === 'baseline_moved') return `Baseline anchored ${p.to ? `from ${D(p.to)}` : 'to the first captures'}`;
    if (e.kind === 'acknowledged') return `Marked as seen through ${U.DT(p.through)} UTC`;
    if (e.kind === 'paused' || e.kind === 'resumed') return e.kind === 'paused' ? 'Collection paused' : 'Collection resumed';
    if (e.kind === 'panel_group') return p.group ? `Group set to “${p.group}”` : 'Group removed';
    if (e.kind === 'decision') return `Decision: ${p.decision || p.status || ''}`;
    return `${U.cap(e.kind.replace(/_/g, ' '))}${Object.keys(p).length ? ` · ${Object.entries(p).map(([k, v]) => `${k} ${typeof v === 'object' ? JSON.stringify(v) : v}`).join(', ')}` : ''}`;
  }
  async function renderLog(params, portfolio) {
    const f = params.get('f') || 'changes';
    const pids = portfolio ? projects().map((p) => p.id) : [state.project];
    const bundles = await Promise.all(pids.map(async (pid) => { const [act, rep] = await Promise.all([activity(pid), report(pid).catch(() => null)]); return { pid, name: projectRow(pid)?.name || pid, act, names: new Map((rep?.queries || []).map((q) => [q.id, q.query])) }; }));
    const events = bundles.flatMap((b) => (b.act.events || []).map((e) => ({ ...e, pid: b.pid, pname: b.name, who: b.names.get(e.target_id) || e.target_id })));
    const runs = bundles.flatMap((b) => (b.act.runs || []).map((r) => ({ ...r, pid: b.pid, pname: b.name, at: r.finished_at || r.started_at })));
    const changes = events.filter((e) => e.kind === 'status_change'); const config = events.filter((e) => e.kind !== 'status_change');
    const items = (f === 'changes' ? changes.map((e) => ({ t: 'change', at: e.at, e })) : f === 'runs' ? runs.map((r) => ({ t: 'run', at: r.at, r })) : f === 'config' ? config.map((e) => ({ t: 'config', at: e.at, e })) : [...changes.map((e) => ({ t: 'change', at: e.at, e })), ...runs.map((r) => ({ t: 'run', at: r.at, r })), ...config.map((e) => ({ t: 'config', at: e.at, e }))]).filter((i) => i.at).sort((a, b) => b.at.localeCompare(a.at));
    const limit = Number(params.get('n') || 60); const shown = items.slice(0, limit);
    const recent = (id, pid, at) => { const t = new Date(at).getTime(); return changes.filter((c) => c.target_id === id && c.pid === pid && new Date(c.at).getTime() <= t && new Date(c.at).getTime() >= t - 3 * 86400000).length; };
    const cls = (s) => `to-${U.kind(s) === 'review' || U.kind(s) === 'issue' ? 'review' : U.kind(s) === 'watch' ? 'watch' : 'stable'}`;
    let lastDay = '';
    const rows = shown.map((i) => {
      const day = U.dayKey(i.at); const sep = day !== lastDay ? `<div class="log-day">${esc(U.dayLabel(day))}</div>` : ''; lastDay = day;
      const tag = portfolio ? `<span class="tag">${esc(i.e?.pname || i.r?.pname)}</span>` : '';
      if (i.t === 'change') { const e = i.e; const p = e.payload || {}; const k = recent(e.target_id, e.pid, e.at); return `${sep}<a class="log-row" href="${link.panel(e.target_id, '', e.pid)}"><span class="when">${T(e.at)}</span><span class="who">${esc(e.who)}</span><span class="what"><i class="dot ${U.kind(p.before) === 'watch' ? 'watch' : U.kind(p.before) === 'review' ? 'review' : U.kind(p.before) === 'stable' ? 'stable' : 'hollow'}"></i>${esc(U.word(p.before))}<span class="arrow">→</span><i class="dot ${U.kind(p.after) === 'watch' ? 'watch' : U.kind(p.after) === 'review' ? 'review' : U.kind(p.after) === 'stable' ? 'stable' : 'hollow'}"></i><span class="${cls(p.after)}">${esc(U.word(p.after))}</span>${p.score != null ? `<span class="muted">· score ${Math.round(p.score)}</span>` : ''}${tag}</span><span>${k >= 3 ? `<span class="flap">${I('repeat')}${U.ordinal(k)} change in 3 days</span>` : ''}</span></a>`; }
      if (i.t === 'run') { const r = i.r; return `${sep}<div class="log-row"><span class="when">${T(r.started_at)}</span><span class="who">${esc(U.cap(r.trigger || 'run'))} run</span><span class="what">${r.collected} collected · ${r.skipped} skipped · <span class="${r.failed ? 'to-review' : ''}">${r.failed} failed</span> · ${plural(r.requests, 'request')}${tag}</span><span class="muted nowrap">${esc(r.error || Object.entries(r.errors || {}).map(([k, v]) => `${k}: ${v}`).join(', '))}</span></div>`; }
      const e = i.e; return `${sep}<div class="log-row"><span class="when">${T(e.at)}</span><span class="who">${esc(e.target_id ? e.who : 'Project')}</span><span class="what">${esc(eventText(e))}${tag}</span><span></span></div>`;
    }).join('');
    const perDay = new Map(); const now = Date.now();
    const firstRun = runs.map((r) => U.dayKey(r.started_at)).filter(Boolean).sort()[0] || new Date(now).toISOString().slice(0, 10);
    for (let k = 6; k >= 0; k--) { const key = new Date(now - k * 86400000).toISOString().slice(0, 10); if (key >= firstRun) perDay.set(key, 0); }
    runs.forEach((r) => { const k = U.dayKey(r.started_at); if (perDay.has(k)) perDay.set(k, perDay.get(k) + (r.requests || 0)); });
    const vals = [...perDay.entries()]; const maxV = Math.max(1, ...vals.map(([, v]) => v));
    const row0 = portfolio ? null : projectRow(); const budget = row0?.budget;
    const flappers = [...new Set(changes.filter((c) => new Date(c.at).getTime() >= now - 3 * 86400000).map((c) => `${c.pid}:${c.target_id}`))].map((k) => { const [pid, id] = [k.slice(0, k.indexOf(':')), k.slice(k.indexOf(':') + 1)]; const list = changes.filter((c) => c.pid === pid && c.target_id === id && new Date(c.at).getTime() >= now - 3 * 86400000).sort((a, b) => a.at.localeCompare(b.at)); return { pid, id, who: list[0]?.who, list }; }).filter((x) => x.list.length >= 3).sort((a, b) => b.list.length - a.list.length);
    const baseHref = portfolio ? '#/portfolio/log' : link.view('log');
    $('main').innerHTML = `<div class="page">
      <div class="page-head"><div class="title"><h1>Log</h1><span class="meta">Status changes, collection runs and configuration edits in one timeline</span></div><div class="seg">${[['changes', 'Status changes', changes.length], ['runs', 'Runs', runs.length], ['config', 'Configuration', config.length], ['all', 'All', '']].map(([v, l, c]) => `<a href="${baseHref}?f=${v}"${v === f ? ' aria-current="true"' : ''}>${l}${c !== '' ? `<span class="n">${c}</span>` : ''}</a>`).join('')}</div></div>
      <div class="with-rail wide"><div class="card clip">${rows || '<div class="empty">Nothing recorded yet.</div>'}${items.length > limit ? `<a class="more-link" href="${baseHref}?f=${f}&n=${limit + 100}">Show earlier entries</a>` : ''}</div>
        <div class="rail"><div class="card pad"><div class="card-head">${I('activity')}<h3>Requests per day</h3></div><div class="vbars">${vals.map(([k, v], i) => `<div class="${i === vals.length - 1 ? 'cur' : ''}"><span>${v || ''}</span><i style="height:${Math.round(v / maxV * 84)}px"></i></div>`).join('')}</div><div class="vbars-x">${vals.map(([k], i) => `<span>${i === vals.length - 1 ? 'today' : D(`${k}T12:00:00Z`).split(' ')[0]}</span>`).join('')}</div><div class="note">${budget?.cap ? `${n(budget.used)} of ${n(budget.cap)} used${budget.until ? `; collection stops ${D(budget.until)}, ${T(budget.until)} UTC` : ''}.` : `${n(runs.reduce((a, r) => a + (r.requests || 0), 0))} requests in the last ${plural(runs.length, 'run')}.`} ${runs.filter((r) => r.failed).length ? `${plural(runs.filter((r) => r.failed).length, 'run')} had failures.` : `No failed runs in ${runs.length}.`}</div></div>
          <div class="card pad"><div class="card-head">${I('repeat')}<h3>Flapping panels</h3><span class="grow"></span><span class="meta">72 h</span></div>${flappers.length ? `<p class="note" style="color:var(--text-2);font-size:12.5px">${plural(flappers.length, 'panel')} crossed the watch line three or more times in three days. Their SERPs reshuffle on every capture, so a watch there is noise until something is confirmed.</p><div class="stack">${flappers.slice(0, 8).map((x) => `<a class="row" href="${link.panel(x.id, '', x.pid)}" style="min-height:26px"><span class="grow nowrap">${esc(x.who)}</span><span class="marks">${x.list.map((c) => `<i class="${c.payload?.after === 'watch' ? 'w' : c.payload?.after === 'review' ? 'r' : ''}"></i>`).join('')}</span></a>`).join('')}</div><div class="note" style="border-top:1px solid var(--line);padding-top:10px">Raise the watch threshold in Settings → Collection, or keep it and rely on confirmation.</div>` : '<p class="note">No panel changed status three times in the last three days.</p>'}</div></div></div>
    </div>`;
    state.keys = rowKeys('a.log-row');
  }

  // --- all projects ------------------------------------------------------------------------------------------------------
  async function renderPortfolio() {
    const pf = await api('/api/portfolio'); const rows = pf.projects;
    const reps = new Map((await Promise.all(rows.map(async (r) => [r.id, await report(r.id).catch(() => null)]))));
    const watch = rows.reduce((a, r) => a + (r.counts?.watch || 0), 0); const reviewN = rows.reduce((a, r) => a + (r.counts?.review || 0), 0);
    const today = new Date().toISOString().slice(0, 10);
    const collectedToday = rows.filter((r) => (r.last_run?.finished_at || '').startsWith(today) || (reps.get(r.id)?.queries || []).some((q) => (q.latest?.captured_at || '').startsWith(today))).length;
    const headline = reviewN ? `${reviewN === 1 ? 'One change needs' : `${reviewN} changes need`} a decision.` : watch ? `${watch} ${watch === 1 ? 'panel is' : 'panels are'} drifting across ${plural(rows.length, 'project')}. Nothing is confirmed.` : `All quiet across ${plural(rows.length, 'project')}.`;
    const sched = state.status.scheduler || {};
    const explainer = [`${collectedToday === rows.length ? (rows.length === 1 ? 'The project' : `All ${rows.length} projects`) : `${collectedToday} of ${rows.length} projects`} collected today.`, ...rows.filter((r) => r.budget?.until && !r.budget.stopped).map((r) => `${r.name} stops collecting on ${D(r.budget.until)}.`), ...rows.filter((r) => r.budget?.stopped).map((r) => `${r.name} has ended collection.`), sched.enabled ? '' : 'The scheduler is off in this process.'].filter(Boolean).join(' ');
    const watchList = rows.flatMap((r) => (reps.get(r.id)?.queries || []).filter((q) => q.status === 'watch' || q.status === 'review').map((q) => ({ pid: r.id, pname: r.name, q, events: [] }))).sort((a, b) => (a.q.status === 'review' ? -1 : 0) - (b.q.status === 'review' ? -1 : 0) || siteHit(b.q) - siteHit(a.q) || (b.q.score || 0) - (a.q.score || 0));
    $('main').innerHTML = `<div class="page">
      <div class="page-head"><div class="title"><h1>All projects</h1><span class="meta">${plural(rows.length, 'workspace')} on this machine · ${plural(pf.panels, 'panel')} · one scheduler</span></div>${state.status.projects_root ? `<a class="btn" href="#/new-project">${I('plus')}New project</a>` : ''}<button class="btn primary" type="button" id="collect-all"${isRunning() ? ' disabled' : ''}>Collect all due</button></div>
      <div class="headline"><h2>${esc(headline)}</h2><p>${esc(explainer)}</p></div>
      <div class="card clip"><div class="table pftable"><div class="thead"><span>Project</span><span>Panels · drift</span><span class="hide-sm">Your site</span><span class="hide-sm">Collection</span><span class="hide-sm">Requests</span><span></span></div>${rows.map((r) => {
        const rep = reps.get(r.id); const qs = rep?.queries || []; const c = r.counts || {}; const tot = r.panels || 1;
        const rk = qs.filter((q) => sitePosition(q)); const t3 = rk.filter((q) => sitePosition(q).pos <= 3); const ct = qs.filter(cited);
        const segs = [['review', c.review], ['watch', c.watch], ['stable', c.stable], ['building', (c.building_baseline || 0) + (c.baseline_ready || 0) + (c.awaiting_data || 0)], ['issues', (c.collection_error || 0) + (c.stale || 0) + (c.data_quality || 0) + (c.insufficient_data || 0)]].filter(([, v]) => v);
        return `<a class="trow" href="${link.project(r.id)}"><span class="row"><span class="avatar lg">${esc(initial(r.name))}</span><span class="cell-2"><b class="q nowrap">${esc(r.name)}</b><span class="sub nowrap">${esc(r.market || '')}</span></span></span><span class="cell-2" style="width:100%"><span class="spectrum" style="width:100%"><span class="bar" style="height:6px">${segs.map(([k, v]) => `<i class="${k}" style="flex:${v / tot}"></i>`).join('')}</span></span><span class="row" style="gap:12px;font-size:12px"><b style="font-weight:500">${plural(r.panels, 'panel')}</b>${c.review ? `<span class="row" style="gap:5px"><i class="dot review"></i>${c.review} review</span>` : ''}${c.watch ? `<span class="row" style="gap:5px"><i class="dot watch"></i>${c.watch} watch</span>` : ''}<span class="row muted" style="gap:5px"><i class="dot stable"></i>${c.stable || 0} stable</span></span></span><span class="cell-2 hide-sm"><span class="dim">${r.site ? `ranks in ${rk.length} · top 3 in ${t3.length}` : 'no site set'}</span>${ct.length ? `<span class="sub">cited in ${plural(ct.length, 'Overview')}</span>` : ''}</span><span class="hide-sm"><i class="dot ${r.running ? 'run' : r.health_kind === 'ok' ? 'ok' : r.health_kind === 'error' ? 'err' : 'hollow'}"></i><span class="dim nowrap">${esc(r.health || '')}</span></span><span class="cell-2 hide-sm"><span class="dim">${n(r.credits_per_day)} a day</span>${r.budget?.cap ? `<span class="track" style="width:140px"><i style="width:${Math.min(100, r.budget.used / r.budget.cap * 100).toFixed(1)}%"></i></span>` : ''}<span class="sub">${r.budget?.cap ? `${n(r.budget.used)} of ${n(r.budget.cap)}${r.budget.until ? ` · stops ${D(r.budget.until)}` : ''}` : `${n(r.budget?.used || 0)} recorded · no cap`}</span></span><span class="right muted">${I('right')}</span></a>`;
      }).join('')}</div></div>
      <div class="card clip"><div class="card-head" style="padding:14px 18px;border-bottom:1px solid var(--line)"><h3>Watching across projects</h3><span class="meta">${watchList.length}</span><span class="grow"></span><a class="link" href="#/portfolio/inbox">Open the merged inbox →</a></div>${watchList.slice(0, 6).map((e) => `<a class="qrow" href="${link.panel(e.q.id, '', e.pid)}"><i class="dot ${e.q.status === 'review' ? 'review' : 'watch'}"></i><div class="t"><div class="row"><b>${esc(e.q.query)}</b><span class="tag">${esc(e.pname)}</span>${siteHit(e.q) ? '<span class="tag you">your site</span>' : ''}</div><small>${esc(U.whyLine(e.q, e.events))}</small></div><div class="s"><b>${U.score(e.q.score)}</b></div>${I('right')}</a>`).join('') || '<div class="empty">No panel is drifting.</div>'}</div>
    </div>`;
    $('collect-all').addEventListener('click', collectAll);
    state.keys = rowKeys('.pftable a.trow');
  }

  // --- router ------------------------------------------------------------------------------------------------------------
  const ctx = { $, api, P, link, state, report, panelData, activity, attention, invalidate, loadStatus, go, route, toast, fail, collect, startPolling, projectRow, engines, sortQueries, scoreDelta, deltaHtml, seen, markSeen, sitePosition, render: () => render() };
  async function render() {
    const { parts, params } = route();
    try { if (!state.status) await loadStatus(); } catch (error) { $('main').innerHTML = `<div class="page"><div class="notice err"><span class="ib">${I('alert')}</span><div class="t"><b>Cannot reach the app</b><p>${esc(error.message)}</p></div></div></div>`; return; }
    let view = 'inbox'; let portfolio = false;
    if (parts[0] === 'p' && parts[1]) { state.project = parts[1]; view = parts[2] || 'inbox'; }
    else if (parts[0] === 'portfolio') { portfolio = true; view = { inbox: 'pinbox', insights: 'pinsights', log: 'plog', runs: 'plog' }[parts[1]] || 'portfolio'; }
    else if (parts[0] === 'new-project') { portfolio = true; view = 'new'; }
    else if (state.status.multi_project && !parts.length) { portfolio = true; view = 'portfolio'; }
    if (!projects().some((p) => p.id === state.project)) state.project = state.status.project.id;
    if (view === 'activity' || view === 'runs') { view = 'log'; if (!params.get('f')) params.set('f', parts[2] === 'runs' ? 'runs' : 'all'); }
    if (view === 'import') view = 'add';
    if (view === 'dashboard') view = 'inbox';
    state.scope = portfolio ? 'portfolio' : 'project'; state.keys = null;
    renderSidebar(view, portfolio); renderMobile(view, portfolio);
    $('main').innerHTML = '<div class="page"><div class="skeleton" style="width:36%"></div><div class="skeleton" style="width:62%;height:28px"></div></div>';
    document.title = `${portfolio ? 'All projects' : projectRow()?.name || 'serp-drift'} · serp-drift`;
    try {
      if (view === 'portfolio') return await renderPortfolio();
      if (view === 'pinbox') return await renderInbox(params, true);
      if (view === 'pinsights') return await renderInsights(params, true);
      if (view === 'plog') return await renderLog(params, true);
      if (view === 'new') return window.SerpManage.newProject(ctx);
      if (view === 'panel' && parts[3]) return await window.SerpPanel.render(ctx, parts[3], params.get('tab') || 'summary');
      if (view === 'panels') return await renderPanels();
      if (view === 'insights') return await renderInsights(params, false);
      if (view === 'log') return await renderLog(params, false);
      if (view === 'settings') return await window.SerpManage.settings(ctx, params.get('s') || 'general');
      if (view === 'add') return await window.SerpManage.add(ctx);
      if (view === 'connect') return await window.SerpManage.connect(ctx);
      return await renderInbox(params, false);
    } catch (error) { $('main').innerHTML = `<div class="page"><div class="notice err"><span class="ib">${I('alert')}</span><div class="t"><b>Something went wrong</b><p>${esc(error.message)}</p></div></div></div>`; console.error(error); }
  }
  window.addEventListener('hashchange', render);
  render().then(() => { if (isRunning()) startPolling(); });
  setInterval(() => { if (!state.pollTimer && document.visibilityState === 'visible' && state.status) renderCollector(); }, 60000);
})();
