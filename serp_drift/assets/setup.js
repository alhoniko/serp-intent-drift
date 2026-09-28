/* Guided setup; no external requests until the user starts collection. */
window.SerpSetup = (() => {
  const esc = (s) => String(s ?? '').replace(/[&<>"']/g, (c) => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  const icon = (name) => window.SerpIcons.get(name);
  async function mount(root, status, post, done) {
    let step = 1;
    const values = {site:status.project.site || '', name:status.project.name || '', key:'', keywords:'', gl:status.search?.gl || 'us', hl:status.search?.hl || 'en', device:'desktop', interval_hours:24, ai_overview:'expand'};
    const hasKey = status.workspace?.key && status.workspace.key !== 'missing';
    function draw() {
      const queries = [...new Set(values.keywords.split('\n').map((x) => x.trim()).filter(Boolean))];
      const daily = Math.ceil(queries.length * 24 / Number(values.interval_hours) * (values.ai_overview === 'expand' ? 2 : 1));
      const steps = ['Your project', 'Searches', 'Collection plan'].map((label, i) => `${i ? '<span class="ln"></span>' : ''}<span class="st ${step === i + 1 ? 'on' : step > i + 1 ? 'done' : ''}"><i>${step > i + 1 ? icon('check') : i + 1}</i>${label}</span>`).join('');
      root.innerHTML = `<div class="page"><div class="onboarding"><div class="stack" style="gap:12px"><h1>Watch a search results page change.</h1><p class="lead">serp-drift captures the top 10 for each query on a schedule, compares it with a fixed baseline and tells you when the change deserves a content review. Everything stays in one SQLite file in this workspace.</p></div><div class="steps">${steps}</div>
        <form id="setup-form" class="card pad">${step === 1 ? `<div class="card-head"><h3 style="font-size:15px">Your project</h3></div><div class="form-grid"><label class="field">Site<input name="site" required value="${esc(values.site)}" placeholder="example.com"></label><label class="field">Project name<input name="name" value="${esc(values.name)}"></label></div><label class="field">SearchApi key<input name="key" type="password" autocomplete="off" value="${esc(values.key)}" placeholder="${hasKey ? 'Already configured; leave blank to keep' : 'Paste your API key'}"><span class="help">Stored privately on this machine and sent only when you collect. You can finish setup without a key.</span></label>`
          : step === 2 ? `<div class="card-head"><h3 style="font-size:15px">What do you want to monitor?</h3></div><label class="field">Queries, one per line<textarea name="keywords" rows="7" required placeholder="technical seo audit\nseo reporting tools">${esc(values.keywords)}</textarea><span class="help">Start with 5–20 important searches. English and Finnish have built-in intent rules; other languages need the optional model classifier for intent labels.</span></label><div class="form-grid"><label class="field">Country code<input name="gl" required pattern="[a-z]{2}" value="${esc(values.gl)}"></label><label class="field">Language code<input name="hl" required pattern="[a-z]{2}" value="${esc(values.hl)}"></label><label class="field">Device<select name="device"><option value="desktop" ${values.device === 'desktop' ? 'selected' : ''}>Desktop</option><option value="mobile" ${values.device === 'mobile' ? 'selected' : ''}>Mobile</option></select></label></div>`
          : `<div class="card-head"><h3 style="font-size:15px">Collection plan</h3><span class="meta">${queries.length} searches · ${esc(values.gl.toUpperCase())} · ${esc(values.hl)} · ${esc(values.device)}</span></div><div class="form-grid"><label class="field">Collect every<select name="interval_hours"><option value="24" ${+values.interval_hours === 24 ? 'selected' : ''}>24 hours</option><option value="12" ${+values.interval_hours === 12 ? 'selected' : ''}>12 hours</option><option value="168" ${+values.interval_hours === 168 ? 'selected' : ''}>7 days</option></select></label><label class="field">AI Overview references<select name="ai_overview"><option value="expand" ${values.ai_overview === 'expand' ? 'selected' : ''}>Collect when available</option><option value="skip" ${values.ai_overview === 'skip' ? 'selected' : ''}>Skip expansion</option></select></label></div><div class="switch-row"><span class="t"><b id="setup-estimate">Up to ${daily} requests a day before retries</b><span>Your provider determines billed credits.</span></span></div><p class="note">The baseline needs three spaced captures; after that, two agreeing captures confirm an intent change. The scheduler collects while the app runs. No model calls are enabled.</p>`}
          <p role="alert" class="inline-error"></p><div class="form-actions">${step > 1 ? '<button type="button" class="btn ghost" id="setup-back">Back</button>' : ''}<button type="submit" class="btn primary">${step === 3 ? 'Save and create panels' : 'Continue'}</button></div></form>
        <div class="source" style="cursor:default">${icon('flask')}<span class="t"><b>Look around first</b><span>Run <span class="mono">serp-drift demo</span> for a synthetic report: four queries, 24 invented captures on reserved .example domains.</span></span></div></div></div>`;
      const form = root.querySelector('form');
      const read = () => Object.assign(values, Object.fromEntries(new FormData(form)));
      root.querySelector('#setup-back')?.addEventListener('click', () => { read(); step--; draw(); });
      if (step === 3) form.addEventListener('change', () => { read(); root.querySelector('#setup-estimate').textContent = `Up to ${Math.ceil(queries.length * 24 / +values.interval_hours * (values.ai_overview === 'expand' ? 2 : 1))} requests a day before retries`; });
      form.addEventListener('submit', async (event) => {
        event.preventDefault(); read();
        if (step < 3) { step++; draw(); return; }
        const button = form.querySelector('[type=submit]'); button.disabled = true;
        try {
          if (!queries.length || queries.length > 100) throw new Error('Choose between 1 and 100 keywords.');
          await post('/project', {site:values.site, name:values.name});
          if (values.key) { await post('/key', {key:values.key}); values.key = ''; }
          await post('/settings', {interval_hours:+values.interval_hours, ai_overview:values.ai_overview});
          const result = await post('/panels/bulk', {source:'guided-setup', panels:queries.map((query) => ({query, gl:values.gl, hl:values.hl, device:values.device}))});
          if (result.errors?.length) throw new Error(result.errors.map((e) => e.error).join(' '));
          root.innerHTML = `<div class="page"><div class="onboarding"><div class="stack" style="gap:12px"><h1>Your baseline starts with one capture.</h1><p class="lead">${result.created.length} searches added. The scheduler collects while the app is running; you can also start the first collection now.</p></div><div class="form-actions"><button class="btn primary" id="setup-collect">${icon('collect')}Collect first observations</button><button class="btn" id="setup-finish">Open the project</button></div><p class="inline-error" role="alert"></p></div></div>`;
          root.querySelector('#setup-finish').onclick = done;
          root.querySelector('#setup-collect').onclick = async (e) => { e.target.disabled = true; try { await post('/collect', {}); await done(); } catch(error) { root.querySelector('[role=alert]').textContent = error.message; e.target.disabled = false; } };
        } catch(error) { form.querySelector('[role=alert]').textContent = error.message; button.disabled = false; }
      });
    }
    draw();
  }
  return {mount};
})();
