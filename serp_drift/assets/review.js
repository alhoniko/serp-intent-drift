/* Evidence and review UI. Uses the same decision contract as exports and agent tools. */
window.SerpReview = (() => {
  'use strict';
  const U = window.SerpUI;
  const { I, esc, DT, pct, plural } = U;
  const words = (v) => U.cap(String(v || 'unknown').replace(/_/g, ' '));
  const option = (values, selected) => values.map(([v, l]) => `<option value="${esc(v)}" ${v === selected ? 'selected' : ''}>${esc(l)}</option>`).join('');
  // The query check is a heuristic: a reviewer who confirms the results are right for the query can keep the observation.
  const keepable = (o) => o.quality?.state === 'query_mismatch' && !o.review;
  const STATUSES = [['investigating', 'Investigating'], ['decided', 'Decision recorded'], ['monitoring', 'Monitoring outcome'], ['closed', 'Closed']];
  const DECISIONS = [['', 'Choose a decision'], ['update_page', 'Update the current page'], ['create_page', 'Create a separate page'], ['wait', 'Wait for more evidence'], ['no_action', 'No content change needed'], ['incorrect_observation', 'Observation is incorrect'], ['incorrect_label', 'Classification is incorrect']];

  function statePill(o) {
    const st = o.quality?.state;
    if (o.review?.excluded) return `<span class="pill idle">${I('x')}Excluded by you</span>`;
    if (st === 'query_mismatch') return `<span class="pill issue">${I('x')}Rejected · another query</span>`;
    if (st === 'quarantined') return `<span class="pill issue">${I('alert')}Quarantined</span>`;
    if (st === 'accepted') return `<span class="pill idle">${I('ok')}Accepted${o.review && o.review.excluded === false ? ' · kept by you' : ''}</span>`;
    return `<span class="pill idle">${esc(words(st || 'legacy · unverified'))}</span>`;
  }

  function decisionCard(q) {
    const cases = q.reviews || []; const active = cases.find((r) => r.active) || cases.find((r) => ['decided', 'monitoring'].includes(r.status));
    if (!(q.status === 'review' || active)) return '';
    return `<section class="card pad" id="decision"><div class="card-head">${I('checks')}<h3>${active ? esc(words(active.status)) : 'New confirmed change'}</h3><span class="meta">Your rationale stays attached to this change</span></div>
      <form id="review-decision" class="stack" style="gap:14px"><div class="form-grid"><label class="field">Review status<select name="status">${option(STATUSES, active?.status || 'investigating')}</select></label><label class="field">Decision<select name="decision">${option(DECISIONS, active?.decision || '')}</select></label><label class="field">Check again on<input name="review_on" type="date" value="${esc(active?.review_on || '')}"></label></div>
      <label class="field">Rationale<textarea name="note" rows="4" maxlength="4000" placeholder="What changed, what you checked, and why this action fits">${esc(active?.note || '')}</textarea></label><p class="inline-error" role="alert"></p><div class="form-actions"><button type="submit" class="btn primary">Save decision</button><span class="note">Inspect the original results and your page before deciding.</span></div></form></section>`;
  }

  function evidence(ctx, panel, q, body) {
    const obs = panel.observations || []; const e = q.evidence || {}; const topic = q.topic_check; const id = panel.target.id;
    const accepted = obs.filter((o) => o.quality?.state === 'accepted' && !o.review?.excluded).length;
    const rejected = obs.filter((o) => U.REJECTED.includes(o.quality?.state) && !o.review?.excluded).length;
    const excluded = obs.filter((o) => o.review?.excluded).length;
    const mismatch = obs.filter((o) => o.quality?.state === 'query_mismatch');
    const cases = q.reviews || [];
    const trail = [...(panel.events || []).filter((ev) => ev.kind === 'status_change' || ev.kind.startsWith('review_') || ev.kind === 'observation_review' || ev.kind === 'acknowledged' || ev.kind === 'baseline_moved')].sort((a, b) => b.at.localeCompare(a.at)).slice(0, 12);
    let limit = 12;
    const row = (o, i) => `<div class="obs"><button class="trow" type="button" data-i="${i}" aria-expanded="false" style="width:100%;border:0;background:none;text-align:left;cursor:pointer;grid-template-columns:130px minmax(0,1fr) 64px 150px 110px"><span class="dim num">${esc(DT(o.captured_at))}</span><span>${statePill(o)}</span><span class="right dim num">${o.results ?? '—'}</span><span class="hide-sm ${o.quality?.state === 'query_mismatch' ? '' : 'muted'}" style="${o.quality?.state === 'query_mismatch' ? 'color:var(--review-text)' : ''}">${o.quality?.state === 'query_mismatch' ? 'misses the query terms' : o.quality?.state === 'accepted' ? 'passes' : o.quality ? words(o.quality.state) : 'unverified'}</span><span class="right ${keepable(o) ? 'link' : 'muted'}">${keepable(o) ? 'Keep as evidence' : o.review?.excluded ? 'Restore…' : 'Exclude…'}</span></button>
      <div style="padding:4px 18px 16px 18px;display:none"></div></div>`;
    const detail = (o, i) => `<div class="stack" style="gap:10px;padding:4px 0 6px"><p class="note" style="color:var(--text-2)">${esc((o.quality?.reasons || []).join(' ') || 'No collection-quality issue recorded.')}${o.intent ? ` Dominant intent: ${esc(o.intent)}.` : ''}</p><details><summary class="note" style="cursor:pointer">Search trace${o.quality?.trace?.request_id ? ` · ${esc(o.quality.trace.request_id)}` : ''}</summary><pre class="code" style="margin-top:8px;max-height:220px;overflow:auto">${esc(JSON.stringify(o.quality?.trace || { note: 'Search response provenance was not retained.' }, null, 2))}</pre></details><form data-observation="${i}" class="stack" style="gap:8px"><label class="field">Reason for ${keepable(o) ? 'keeping' : o.review?.excluded ? 'restoring' : 'excluding'} this observation<textarea name="reason" required maxlength="2000" rows="2" placeholder="Describe the evidence for this decision"></textarea></label><p class="inline-error" role="alert"></p><div><button class="btn small" type="submit">${keepable(o) ? 'Keep in analysis' : o.review?.excluded ? 'Restore to analysis' : 'Exclude from analysis'}</button></div></form></div>`;
    const draw = () => {
      body.innerHTML = `${decisionCard(q)}
        <div class="stats"><div><b>${obs.length}</b><span>captures stored</span></div><div><b>${accepted}</b><span>accepted as evidence</span></div><div><b>${rejected}</b><span>rejected: another query or quarantined</span></div><div><b>${excluded}</b><span>excluded by you</span></div></div>
        ${mismatch.length ? `<div class="notice"><span class="ib">${I('rejected')}</span><div class="t"><b>${plural(mismatch.length, 'capture')} returned results for another query</b><p>Their organic results miss the query terms, often matching only one word of it. They are kept as observations and never counted as evidence${q.settings && ctx.state.status?.settings?.retry_query_mismatch ? '; each was retried after a short pause' : ''}. If you think the check is wrong for a capture, keep it as evidence below.</p></div></div>` : ''}
        ${topic?.inspection_suggested ? `<div class="notice"><span class="ib">${I('alert')}</span><div class="t"><b>Inspect query relevance</b><p>Result titles differ substantially between captures${topic.unusual_baseline_captures?.length ? `, including ${plural(topic.unusual_baseline_captures.length, 'baseline capture')}` : ''}. This can be a real shift or a collection problem; it is not excluded automatically.</p></div></div>` : ''}
        <div class="with-rail wide"><div class="card clip"><div class="card-head" style="padding:16px 18px 10px"><h3>Observation ledger</h3><span class="meta">every capture, newest first · nothing is ever deleted</span></div><div class="table"><div class="thead" style="grid-template-columns:130px minmax(0,1fr) 64px 150px 110px"><span>Captured (UTC)</span><span>State</span><span class="right">Results</span><span class="hide-sm">Query check</span><span></span></div>${obs.slice(0, limit).map(row).join('') || '<div class="empty">No observations yet.</div>'}</div>${obs.length > limit ? `<button class="more-link" type="button" id="obs-more">Show ${plural(obs.length - limit, 'more capture')}</button>` : ''}</div>
          <div class="rail"><div class="card pad"><div class="card-head">${I('scale')}<h3>What this evidence can tell you</h3></div><dl class="kv"><dt>Classifier</dt><dd>${esc(e.classifier || 'rules')}</dd><dt>Coverage</dt><dd>${pct(e.classified_coverage)} of rank weight (latest)</dd><dt>Search context</dt><dd>${esc(e.quality?.provenance || 'unverified')}${e.quality?.trace?.verified_fields ? `: ${esc(e.quality.trace.verified_fields.join(', '))}` : ''}</dd><dt>Baseline</dt><dd>${e.baseline_captures || 0} / ${e.baseline_required || 3} captures · ${plural(e.confirmation_required || 2, 'confirmation')}</dd><dt>Baseline variation</dt><dd>${e.baseline_variation == null ? 'not available' : `${pct(e.baseline_variation)} intent distance`}</dd><dt>Recent comparison</dt><dd>${q.recent_comparison ? `${Math.round(q.recent_comparison.score)} / 100 against up to seven earlier captures` : 'not enough data'}</dd></dl><p class="note">${esc(e.accuracy || 'Not independently benchmarked. Coverage is not accuracy.')} Treat intent labels as estimates and read the evidence before changing a page.</p></div>
            <div class="card pad"><div class="card-head">${I('checks')}<h3>Decisions and status</h3></div>${cases.length ? `<div class="stack">${cases.map((c) => `<div class="stack" style="gap:3px;padding-bottom:8px;border-bottom:1px solid var(--line)"><b style="font-weight:500">${esc(words(c.status))} · ${esc(words(c.decision || 'no decision yet'))}</b><span class="note">${esc(c.note || 'No rationale recorded yet.')}</span><span class="note">Opened ${esc(DT(c.opened_at))}${c.review_on ? ` · check again ${esc(c.review_on)}` : ''}${c.active ? ' · active signal' : ''}</span></div>`).join('')}</div>` : ''}
              <div class="stack" style="gap:0">${trail.map((ev, i) => { const p = ev.payload || {}; const title = ev.kind === 'status_change' ? `${U.word(p.before)} → ${U.word(p.after)}` : words(ev.kind); const sub = ev.kind === 'status_change' && p.score != null ? `score ${Math.round(p.score)}` : ev.kind === 'observation_review' ? (p.reason || '') : ev.kind === 'acknowledged' ? 'marked as seen' : ''; return `<div class="row" style="align-items:flex-start;gap:12px;padding:8px 0"><i class="dot ${i === 0 ? (U.kind(p.after) === 'watch' ? 'watch' : U.kind(p.after) === 'review' ? 'review' : 'stable') : 'hollow'}" style="margin-top:5px"></i><span class="stack" style="gap:2px"><b style="font-weight:500;${i ? 'color:var(--text-2)' : ''}">${esc(title)}</b><span class="note">${esc(DT(ev.at))} UTC${sub ? ` · ${esc(sub)}` : ''}</span></span></div>`; }).join('') || '<p class="note">No status changes yet.</p>'}</div>
              ${q.status !== 'review' && !cases.length ? '<p class="note">No decisions yet. A decision form appears when a review is confirmed; watches can be marked as seen.</p>' : ''}</div></div></div>`;
      body.querySelectorAll('.obs > button').forEach((b) => b.addEventListener('click', () => { const open = b.getAttribute('aria-expanded') === 'true'; const box = b.nextElementSibling; b.setAttribute('aria-expanded', String(!open)); if (!open && !box.innerHTML) box.innerHTML = detail(obs[Number(b.dataset.i)], Number(b.dataset.i)); box.style.display = open ? 'none' : 'block'; bindForms(); }));
      ctx.$('obs-more')?.addEventListener('click', () => { limit = obs.length; draw(); });
      const refresh = async () => { ctx.invalidate(); await ctx.loadStatus(); await ctx.render(); };
      ctx.$('review-decision')?.addEventListener('submit', async (event) => {
        event.preventDefault(); const form = event.target; const button = form.querySelector('button'); button.disabled = true;
        const current = cases.find((r) => r.active) || cases.find((r) => ['decided', 'monitoring'].includes(r.status));
        try { await ctx.api(ctx.P(`/panels/${encodeURIComponent(id)}/decision`), { method: 'POST', body: { ...Object.fromEntries(new FormData(form)), case_id: current?.id } }); ctx.toast('Decision saved.'); await refresh(); }
        catch (error) { form.querySelector('[role="alert"]').textContent = error.message; button.disabled = false; }
      });
      function bindForms() {
        body.querySelectorAll('form[data-observation]:not([data-bound])').forEach((form) => { form.dataset.bound = '1'; form.addEventListener('submit', async (event) => {
          event.preventDefault(); const o = obs[Number(form.dataset.observation)]; const button = form.querySelector('button'); button.disabled = true;
          try { await ctx.api(ctx.P(`/panels/${encodeURIComponent(id)}/observation-review`), { method: 'POST', body: { captured_at: o.captured_at, excluded: keepable(o) ? false : !o.review?.excluded, reason: form.elements.reason.value } }); ctx.toast('Observation updated.'); await refresh(); }
          catch (error) { form.querySelector('[role="alert"]').textContent = error.message; button.disabled = false; }
        }); });
      }
    };
    draw();
  }
  return { evidence, keepable };
})();
