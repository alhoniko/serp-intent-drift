(() => {
  'use strict';
  const R = window.SerpDriftRender;
  const { escape, status, score, date } = R;
  const report = JSON.parse(document.getElementById('report-data').textContent);
  const queries = R.sortQueries(report.queries);
  let selectedId = queries[0]?.id;
  const summary = [
    [queries.length, 'Queries tracked', 'Separate search panels'],
    [queries.filter((query) => query.status === 'review').length, 'Ready for review', 'Repeated intent / page-fit signal'],
    [queries.reduce((total, query) => total + query.snapshot_count, 0), 'Snapshots stored', report.synthetic ? 'Synthetic fixture captures' : 'Successful stored captures'],
    [queries.filter((query) => query.status === 'stable').length, 'Stable panels', 'No confirmed mismatch'],
  ];
  document.getElementById('summary').innerHTML = summary.map(([value, label, caption]) => `<div><p class="metric-label">${label}</p><p class="value">${value}</p><p class="caption">${caption}</p></div>`).join('');
  document.getElementById('data-banner').innerHTML = `<strong>${report.synthetic ? 'SYNTHETIC DEMO' : 'COLLECTED DATA'}</strong><span>${report.synthetic ? 'Example scenarios, invented URLs, and simulated changes. These are not live Google findings.' : 'SearchApi observations. Read collection status and timestamps before acting.'} <span class="muted">Report generated ${escape(date(report.generated_at))}.</span></span>`;

  function renderList() {
    const text = document.getElementById('query-search').value.trim().toLowerCase();
    const filter = document.getElementById('status-filter').value;
    const matches = queries.filter((query) => query.query.toLowerCase().includes(text) && (filter === 'all' || query.status === filter || (filter === 'health' && !['review', 'watch', 'stable'].includes(query.status))));
    if (!matches.some((query) => query.id === selectedId)) selectedId = matches[0]?.id;
    document.getElementById('query-count').textContent = String(matches.length).padStart(2, '0');
    document.getElementById('query-list').innerHTML = matches.map((query) => `<button type="button" class="query-button" data-query-id="${escape(query.id)}" aria-pressed="${query.id === selectedId}"><span class="query-title">${escape(query.query)}</span><span class="query-meta">${R.market(query.search)}</span><span class="query-bottom">${status(query)}<span class="query-score">${score(query.score)}</span></span></button>`).join('') || '<p class="empty">No matching queries. Clear the filters to see the panel.</p>';
    R.renderDetail(matches.find((query) => query.id === selectedId), report, document.getElementById('detail'));
  }
  document.getElementById('query-list').addEventListener('click', (event) => {
    const button = event.target.closest('button[data-query-id]');
    if (!button) return;
    selectedId = button.dataset.queryId;
    renderList();
    document.querySelector(`[data-query-id="${CSS.escape(selectedId)}"]`)?.focus({ preventScroll: true });
  });
  document.getElementById('query-search').addEventListener('input', renderList);
  document.getElementById('status-filter').addEventListener('change', renderList);
  const download = (content, name, type) => {
    const url = URL.createObjectURL(new Blob([content], { type }));
    const link = document.createElement('a');
    link.href = url; link.download = name; link.click();
    setTimeout(() => URL.revokeObjectURL(url), 1000);
  };
  document.getElementById('download-json').addEventListener('click', () => download(JSON.stringify(report, null, 2), 'serp-drift-report.json', 'application/json'));
  document.getElementById('download-csv').addEventListener('click', () => {
    const cell = (value) => { const text = String(value ?? ''); return `"${(/^[\s]*[=+@-]|^[\t\r]/.test(text) ? "'" + text : text).replaceAll('"', '""')}"`; };
    const rows = [['query', 'engine', 'country', 'language', 'device', 'status', 'drift_score', 'baseline_intent', 'current_intent', 'page_mismatch', 'captured_at', 'source'], ...report.queries.map((query) => [query.query, query.search.engine, query.search.gl, query.search.hl, query.search.device, query.status, query.score, query.baseline_intent, query.latest?.dominant_intent, String(query.confirmed_mismatch), query.latest?.captured_at, report.source])];
    download(rows.map((row) => row.map(cell).join(',')).join('\r\n'), 'serp-drift-report.csv', 'text/csv;charset=utf-8');
  });
  document.getElementById('print-report').addEventListener('click', () => window.print());
  renderList();
})();
