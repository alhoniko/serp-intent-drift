/* Explicit opt-in: no model call is made by saving this form. */
window.SerpLabeling = (() => {
  const esc = (v) => String(v ?? '').replace(/[&<>"']/g, (c) => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  function mount(root, status, post, refresh) {
    const s = status.labeling || {};
    const label = document.createElement('div'); label.className = 'lbl';
    label.innerHTML = '<b>Intent classification</b><p>Rules work offline. A model can also inspect the query, result format and the task a result serves.</p>';
    const form = document.createElement('form'); form.className = 'card pad vstack g14';
    form.innerHTML = `<div class="form-grid"><label class="field">Classifier<select name="provider"><option value="none" ${s.provider === 'none' ? 'selected' : ''}>Local rules only</option><option value="openai" ${s.provider === 'openai' ? 'selected' : ''}>Rules + compatible model</option></select></label><label class="field">Model coverage<select name="mode"><option value="gaps" ${s.mode !== 'all' ? 'selected' : ''}>Fill unclassified results</option><option value="all" ${s.mode === 'all' ? 'selected' : ''}>Review every result</option></select></label><label class="field span-all">Endpoint base URL<input name="base_url" type="url" required value="${esc(s.base_url || 'https://api.openai.com/v1')}"></label><label class="field">Model name<input name="model" value="${esc(s.model)}" placeholder="Model supported by your endpoint"></label><label class="field">New API key (optional)<input name="key" type="password" autocomplete="off" placeholder="Stored locally; never shown again"></label><label class="field">Maximum results sent per run<input name="max_items_per_run" type="number" min="1" max="10000" required value="${s.max_items_per_run || 200}"></label><label class="field">Batch size<input name="batch_size" type="number" min="1" max="100" required value="${s.batch_size || 40}"></label></div><p class="muted">Enabling the model sends each selected result's query, title, snippet and URL to this endpoint. Charges depend on your provider. The result cap limits each run; cached results are reused. Saving does not send data. Changing the model, endpoint or mode starts a separate baseline; earlier observations remain in the database.</p><p class="inline-error" role="alert"></p><div><button type="submit" class="btn primary">Save classification settings</button></div>`;
    form.addEventListener('submit', async (event) => {
      event.preventDefault(); const button = form.querySelector('button'); button.disabled = true;
      const body = Object.fromEntries(new FormData(form)); const key = body.key.trim(); delete body.key;
      body.max_items_per_run = Number(body.max_items_per_run); body.batch_size = Number(body.batch_size);
      try {
        await post('/labeling', body);
        if (key) { await post('/key', {service:'labeling',key}); form.elements.key.value = ''; }
        await refresh();
      } catch (error) { form.querySelector('[role="alert"]').textContent = error.message; button.disabled = false; }
    });
    root.append(label, form);
  }
  return {mount};
})();
