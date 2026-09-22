# Optional semantic classification

Rules run locally by default. In Settings → Intent classification, opt into an OpenAI-compatible endpoint only if you accept sending queries, titles, snippets and URLs there. Saving settings makes no provider call. A remote endpoint requires HTTPS; localhost HTTP supports a local model.

```toml
[labeling]
provider = "openai"
base_url = "https://api.openai.com/v1"
model = "your-model"
api_key_env = "OPENAI_API_KEY"
mode = "all"                  # or "gaps" to classify only rule unknowns
max_items_per_run = 200
batch_size = 40
```

Use an environment variable or `serp-drift key set --service labeling` to save a 0600 `labeling.key`. The UI can also store the key locally. Never put credentials in TOML or the endpoint URL.

Each response must be an object containing intent, format, task and supporting evidence. Non-unknown intent needs an excerpt from the supplied result. Plain label strings, invented excerpts, absent IDs and invalid formats are rejected. These checks validate structure and grounding, not semantic accuracy. A model can still misunderstand the query or follow misleading snippets.

In `all` mode the model reviews strong lexical classifications too. The result keeps its rule label and marks a disagreement. A model abstention becomes unknown. In `gaps` mode rule labels are preserved. The result budget counts attempted items; caching avoids repeat sends, and transport/parse failures are not cached. Exhausted or incomplete classification suppresses confirmation. Costs depend on the provider and model; the local cap is per run, not an account-wide spending limit.

Cache identity includes the endpoint, provider, model, mode, prompt version, query and evidence text. Changing endpoint/model/mode starts a separate panel analysis identity and a fresh baseline. Earlier observations remain in SQLite under the earlier identity; switch the settings back to view it. Classification is not retroactively rerun on old captures. `reanalyze` recalculates drift from the stored labels without model requests.

Assess both rules and models using [blind human labels](evaluation.md). Improved coverage is not proof of improved accuracy.
