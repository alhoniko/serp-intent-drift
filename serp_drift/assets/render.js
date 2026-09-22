/* Shared rendering for the static report and the app. Exposes window.SerpDriftRender. */
(() => {
  'use strict';
  const escape = (value) => String(value ?? '').replace(/[&<>"']/g, (character) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' })[character]);
  const safeUrl = (value) => {
    try {
      const url = new URL(value);
      return ['http:', 'https:'].includes(url.protocol) && !url.username && !url.password ? escape(url.href) : '#';
    } catch { return '#'; }
  };
  const host = (value) => { try { return new URL(value).hostname.replace(/^www\./, ''); } catch { return ''; } };
  const date = (value, short = false) => value ? new Date(value).toLocaleDateString('en-GB', { day: '2-digit', month: 'short', ...(short ? {} : { year: 'numeric' }), timeZone: 'UTC' }) : 'No capture';
  const dateTime = (value) => value ? new Date(value).toLocaleString('en-GB', { day: '2-digit', month: 'short', hour: '2-digit', minute: '2-digit', timeZone: 'UTC' }) + ' UTC' : '—';
  const labels = { review: 'Review page', watch: 'Watch changes', stable: 'Stable', building_baseline: 'Building baseline', baseline_ready: 'Baseline ready', awaiting_data: 'Awaiting data', insufficient_data: 'Sparse results', stale: 'Collection overdue', collection_error: 'Collection error', data_quality: 'Check data quality' };
  const featureLabels = { ai_overview: 'AI Overview', answer_box: 'Answer box', related_questions: 'People also ask', knowledge_graph: 'Knowledge graph', local_results: 'Local results', inline_videos: 'Videos', inline_shorts: 'Short videos', inline_images: 'Images', inline_shopping: 'Shopping', top_stories: 'Top stories', ads: 'Ads', discussions_and_forums: 'Discussions' };
  const signalLabels = { intent: 'Intent mix', url_turnover: 'URL turnover', result_types: 'Result types', rank_movement: 'Rank movement', features: 'SERP features' };
  const aiLabels = { observed: 'AI Overview observed', requires_followup: 'AI Overview deferred (token only)', not_available: 'No AI Overview for this search', not_observed: 'No AI Overview', not_applicable: 'Engine has no AI Overview' };
  const status = (query) => `<span class="status status-${escape(query.status)}">${escape(labels[query.status] || query.status)}</span>`;
  const score = (value) => value === null || value === undefined ? '—' : Math.round(value);
  const percent = (value) => value === null || value === undefined ? '—' : `${Math.round(value * 100)}%`;
  const priority = { review: 0, collection_error: 1, stale: 2, insufficient_data: 3, watch: 4, stable: 5 };
  const sortQueries = (queries) => [...queries].sort((left, right) => (priority[left.status] ?? 6) - (priority[right.status] ?? 6) || (right.score || 0) - (left.score || 0));
  const market = (search) => `${escape((search.engine || 'google').replace('google_', 'google ').toUpperCase())} · ${escape((search.gl || '').toUpperCase())} / ${escape((search.hl || '').toUpperCase())}${search.device ? ` / ${escape(search.device.toUpperCase())}` : ''}${search.location ? ` · ${escape(search.location)}` : ''}`;

  function mix(distribution, label, intent) {
    const entries = Object.entries(distribution || {}).sort(([left], [right]) => left.localeCompare(right));
    return `<div class="mix-row"><div class="mix-label"><span>${escape(label)}</span><strong>${escape(intent)}</strong></div><div class="mix-track" role="img" aria-label="${escape(entries.map(([name, value]) => `${name} ${percent(value)}`).join(', '))}">${entries.map(([name, value]) => `<span class="intent-${escape(name)}" style="width:${Math.max(0, Math.min(100, value * 100))}%" title="${escape(name)}: ${percent(value)}"></span>`).join('')}</div></div>`;
  }
  function averageMix(snapshots, field = 'intent_distribution') {
    const distribution = {};
    (snapshots || []).forEach((snapshot) => Object.entries(snapshot[field] || {}).forEach(([key, value]) => { distribution[key] = (distribution[key] || 0) + value / snapshots.length; }));
    return distribution;
  }
  const legend = () => `<div class="legend">${['informational', 'commercial', 'transactional', 'navigational', 'unknown'].map((intent) => `<span><i class="intent-${intent}"></i>${intent}</span>`).join('')}</div>`;

  function signals(comparison, weights) {
    return `<div class="signals">${Object.entries(signalLabels).map(([key, label]) => `<div class="signal"><strong>${!comparison || comparison.components[key] === null ? '—' : percent(comparison.components[key])}</strong><span>${label}</span><span>${percent(weights[key])} of score</span></div>`).join('')}</div>`;
  }

  function featureChips(current, comparison) {
    const features = new Set([...(current.features || []), ...(comparison?.features_removed || [])]);
    return `<div class="feature-list">${[...features].map((key) => { const added = comparison?.features_added?.includes(key); const removed = comparison?.features_removed?.includes(key); return `<span class="feature ${added ? 'feature-added' : removed ? 'feature-removed' : ''}">${added ? '+ ' : removed ? '− ' : ''}${escape(featureLabels[key] || key)}${removed ? ' · no longer observed' : ''}</span>`; }).join('') || '<span class="mini-caption">No tracked features observed in this response.</span>'}</div>`;
  }

  function resultsTable(current, anchor, caption) {
    const old = new Map((anchor?.results || []).map((result) => [result.url, result]));
    const latest = new Map(current.results.map((result) => [result.url, result]));
    const rows = [...current.results, ...[...old.values()].filter((result) => !latest.has(result.url))];
    return `<div class="table-wrap"><table><caption>${caption}</caption><thead><tr><th scope="col">Rank</th><th scope="col">Result and classification evidence</th><th scope="col">Type / intent</th></tr></thead><tbody>${rows.map((row) => {
      const before = old.get(row.url)?.position;
      const after = latest.get(row.url)?.position;
      const movement = before && after ? `${before} → ${after}` : after ? `New → ${after}` : `${before} → out`;
      return `<tr><td class="rank">${anchor ? movement : after}</td><td><a class="result-title" href="${safeUrl(row.url)}" target="_blank" rel="noopener noreferrer">${escape(row.title || row.url)}</a><span class="result-host">${escape(host(row.url))}</span><details><summary>Inspect evidence</summary><p>${escape(row.snippet || 'No snippet returned.')}</p><ul>${(row.evidence || []).map((line) => `<li>${escape(line)}</li>`).join('') || '<li>No decisive lexical evidence. The intent remains unknown.</li>'}</ul></details></td><td class="type">${escape(row.type)}<span class="result-host">${escape(row.intent)}</span></td></tr>`;
    }).join('')}</tbody></table></div>`;
  }

  function aiOverviewBlock(current) {
    const summary = current.ai_overview;
    const label = aiLabels[current.ai_overview_status] || current.ai_overview_status;
    if (!summary) return `<div class="ai-block"><h3 class="block-heading">AI Overview</h3><p class="mini-caption">${escape(label)}.</p></div>`;
    const cited = summary.page_cited ? '<span class="page-tag tag-good">Your page is cited</span>' : summary.host_cited ? '<span class="page-tag">Your site is cited</span>' : '<span class="page-tag tag-muted">Not cited</span>';
    return `<div class="ai-block"><div class="page-fit"><div><h3 class="block-heading">AI Overview</h3><p>${escape(label)} · ${summary.references} references · ${summary.cited_hosts.length} distinct hosts${summary.unresolved_links ? ` · ${summary.unresolved_links} unresolved links` : ''}</p>${summary.excerpt ? `<blockquote class="excerpt">${escape(summary.excerpt)}</blockquote>` : ''}<div class="feature-list">${summary.cited_hosts.map((hostName) => `<span class="feature">${escape(hostName)}</span>`).join('')}</div></div>${cited}</div></div>`;
  }

  function renderDetail(query, report, container) {
    if (!query) { container.innerHTML = '<p class="empty">No query matches the current filters.</p>'; return; }
    const current = query.latest;
    const comparison = query.comparison;
    const baseline = query.baseline.at(-1);
    const search = query.search;
    const page = current?.page;
    const heading = `<div class="detail-heading"><div><span class="small-label">Selected query</span><h2>${escape(query.query)}</h2><p>${market(search)} · ${escape(date(current?.captured_at))}${query.baseline_from ? ` · baseline from ${escape(date(query.baseline_from))}` : ''}</p></div><div class="score-box"><div class="score">${score(query.score)}<span> /100</span></div><span class="small-label">Change priority</span></div></div>`;
    const finding = `<div class="finding"><strong>${status(query)}</strong>${[query.decision?.next_action, ...(query.reasons || [])].filter(Boolean).map((reason) => `<p>${escape(reason)}</p>`).join('')}</div>`;
    if (!current) { container.innerHTML = heading + finding; return; }
    const timeline = `<div><h3 class="block-heading">The change over time</h3><div class="timeline" role="img" aria-label="Change score by capture. Hatched bars indicate baseline collection.">${query.timeline.map((point) => `<div class="timeline-point" title="${escape(date(point.captured_at))}: ${point.score === null ? escape(point.phase) : `score ${point.score}`}, ${escape(point.intent)}${point.quality_ok ? '' : ', sparse capture'}"><span class="timeline-value">${score(point.score)}</span><span class="timeline-bar ${point.score === null ? 'baseline' : ''}" style="${point.score === null ? '' : `height:${Math.max(3, point.score * .65)}px`}"></span><span class="timeline-date">${escape(date(point.captured_at, true))}</span></div>`).join('')}</div><p class="mini-caption">${query.settings.baseline_size} baseline captures · ${query.settings.confirmations} confirmations · ${query.settings.interval_hours}h spacing</p></div>`;
    const composition = `<div><h3 class="block-heading">What the results suggest</h3>${mix(averageMix(query.baseline), 'Baseline average', query.baseline_intent)}${mix(current.intent_distribution, 'Latest capture', current.dominant_intent)}${legend()}<p class="mini-caption">${percent(current.classified_coverage)} of rank weight classified. Lexical proxies, not measured user intent.</p></div>`;
    const pageFit = page ? `<div class="page-fit"><div><h3 class="block-heading">The page being monitored</h3><a href="${safeUrl(page.url)}" target="_blank" rel="noopener noreferrer">${escape(page.url)} ↗</a><p>${escape(page.basis)} · ${query.page_position ? `position ${query.page_position}` : 'not found among observed organic results'}</p><p>${escape(page.caveat)}</p>${page.evidence.length ? `<details><summary>Page classification evidence</summary><ul>${page.evidence.map((line) => `<li>${escape(line)}</li>`).join('')}</ul></details>` : ''}</div><span class="page-tag">${escape(page.intent)} page</span></div>` : '<div class="page-fit"><div><h3 class="block-heading">No page profile supplied</h3><p>Add a declared intent or a local content export to enable page-fit checks.</p></div></div>';
    const featuresHtml = `<h3 class="block-heading">Observed SERP features</h3>${featureChips(current, comparison)}`;
    const table = resultsTable(current, baseline, `Ranked results · latest vs ${baseline ? `baseline anchor (${escape(date(baseline.captured_at, true))})` : 'no baseline yet'}`);
    const warnings = current.warnings.length ? `<ul class="warnings">${current.warnings.map((warning) => `<li>${escape(warning)}</li>`).join('')}</ul>` : '';
    container.innerHTML = heading + finding + `<p class="mini-caption">Classifier: ${escape(query.evidence?.classifier || "rules")} · Search context: ${escape(query.evidence?.quality?.provenance || "unverified")} · ${escape(query.evidence?.accuracy || "Coverage is not accuracy.")}</p><div class="detail-grid">${timeline}${composition}</div>` + signals(comparison, report.weights) + pageFit + aiOverviewBlock(current) + featuresHtml + table + warnings;
  }

  window.SerpDriftRender = { escape, safeUrl, host, date, dateTime, labels, featureLabels, signalLabels, aiLabels, status, score, percent, sortQueries, market, mix, averageMix, legend, signals, featureChips, resultsTable, aiOverviewBlock, renderDetail };
})();
