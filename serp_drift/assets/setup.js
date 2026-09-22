/* Guided setup; no external requests until the user starts collection. */
window.SerpSetup = (() => {
  const esc = (s) => String(s ?? '').replace(/[&<>"']/g, (c) => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  async function mount(root, status, post, done) {
    let step = 1;
    const values = {site:status.project.site || '', name:status.project.name || '', key:'', keywords:'', gl:status.search?.gl || 'us', hl:status.search?.hl || 'en', device:'desktop', interval_hours:24, ai_overview:'expand'};
    function draw() {
      const queries = [...new Set(values.keywords.split('\n').map((x) => x.trim()).filter(Boolean))];
      const daily = Math.ceil(queries.length * 24 / Number(values.interval_hours) * (values.ai_overview === 'expand' ? 2 : 1));
      root.innerHTML = `<div class="onboarding"><div class="eyebrow">Welcome to serp-drift</div><h1>Build your first monitoring project</h1><p>Track a fixed set of searches. Inspect changes with their evidence, then decide whether your content needs attention.</p><ol class="setup-steps">${['Connect','Choose searches','Review & start'].map((label,i) => `<li ${step === i+1 ? 'aria-current="step"' : ''}>${i+1}. ${label}</li>`).join('')}</ol><form id="setup-form" class="card pad vstack">${step === 1 ? `<h2>Your project</h2><div class="form-grid"><label class="field">Site<input name="site" required value="${esc(values.site)}" placeholder="example.com"></label><label class="field">Project name<input name="name" value="${esc(values.name)}"></label></div><label class="field">SearchApi key<input name="key" type="password" autocomplete="off" value="${esc(values.key)}" placeholder="${status.workspace?.key === 'missing' ? 'Paste your API key' : 'Already configured; leave blank to keep'}"></label><p class="muted">The key is stored privately on this machine. Search queries are sent to SearchApi when you collect. You can finish setup without a key.</p>` : step === 2 ? `<h2>What do you want to monitor?</h2><label class="field">Keywords, one per line<textarea name="keywords" rows="7" required placeholder="technical seo audit\nseo reporting tools">${esc(values.keywords)}</textarea></label><div class="form-grid"><label class="field">Country code<input name="gl" required pattern="[a-z]{2}" value="${esc(values.gl)}"></label><label class="field">Language code<input name="hl" required pattern="[a-z]{2}" value="${esc(values.hl)}"></label><label class="field">Device<select name="device"><option value="desktop" ${values.device === 'desktop' ? 'selected' : ''}>Desktop</option><option value="mobile" ${values.device === 'mobile' ? 'selected' : ''}>Mobile</option></select></label></div><p class="muted">Start with 5–20 important searches. English and Finnish have built-in rules. Other languages need an optional semantic classifier for intent labels.</p>` : `<h2>Collection plan</h2><p><strong>${queries.length} searches</strong> · ${esc(values.gl.toUpperCase())} / ${esc(values.hl)} · ${esc(values.device)}</p><div class="form-grid"><label class="field">Collect every<select name="interval_hours"><option value="24" ${+values.interval_hours === 24 ? 'selected' : ''}>24 hours</option><option value="12" ${+values.interval_hours === 12 ? 'selected' : ''}>12 hours</option><option value="168" ${+values.interval_hours === 168 ? 'selected' : ''}>7 days</option></select></label><label class="field">AI Overview references<select name="ai_overview"><option value="expand" ${values.ai_overview === 'expand' ? 'selected' : ''}>Collect when available</option><option value="skip" ${values.ai_overview === 'skip' ? 'selected' : ''}>Skip expansion</option></select></label></div><div class="notice" id="setup-estimate">Up to ${daily} search/expansion requests per day before retries. Your provider determines billed credits.</div><p class="muted">The initial baseline needs three spaced captures, then two later captures to confirm an intent change. Keeping the app running is required for its scheduler.</p><p>No model calls are enabled. You can configure semantic labels and their budget later.</p>`}<p role="alert" class="inline-error"></p><div class="form-actions">${step > 1 ? '<button type="button" class="btn" id="setup-back">Back</button>' : ''}<button type="submit" class="btn primary">${step === 3 ? 'Save monitoring project' : 'Continue'}</button></div></form></div>`;
      const form = root.querySelector('form');
      const read = () => Object.assign(values, Object.fromEntries(new FormData(form)));
      root.querySelector('#setup-back')?.addEventListener('click', () => { read(); step--; draw(); });
      if (step === 3) form.addEventListener('change', () => { read(); root.querySelector('#setup-estimate').textContent = `Up to ${Math.ceil(queries.length * 24 / +values.interval_hours * (values.ai_overview === 'expand' ? 2 : 1))} search/expansion requests per day before retries. Your provider determines billed credits.`; });
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
          root.innerHTML = `<section class="card pad onboarding"><div class="eyebrow">Project ready</div><h1>Your baseline starts with one capture.</h1><p>${result.created.length} searches added. Your scheduler will collect when the app is running. You can also start the first collection now.</p><div class="form-actions"><button class="btn primary" id="setup-collect">Collect first observations</button><button class="btn" id="setup-finish">Open project</button></div><p class="inline-error" role="alert"></p></section>`;
          root.querySelector('#setup-finish').onclick = done;
          root.querySelector('#setup-collect').onclick = async (e) => { e.target.disabled = true; try { await post('/collect', {}); await done(); } catch(error) { root.querySelector('[role=alert]').textContent = error.message; e.target.disabled = false; } };
        } catch(error) { form.querySelector('[role=alert]').textContent = error.message; button.disabled = false; }
      });
    }
    draw();
  }
  return {mount};
})();
