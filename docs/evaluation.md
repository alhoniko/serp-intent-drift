# Human evaluation before accuracy claims

The executable benchmark workflow separates evidence shown to annotators from model predictions. It does not supply human ground truth or certify a release.

```sh
serp-drift --dir ~/serp-drift benchmark export --out ~/serp-benchmark --holdout-after 2026-09-18
# Human reviewers read observations.jsonl and fill a COPY of labels.template.jsonl.
serp-drift benchmark score --predictions ~/serp-benchmark/predictions.jsonl --labels ~/serp-benchmark/labels.jsonl
```

The export refuses to overwrite annotation files. Keep real queries and snippets private. `observations.jsonl` has unlabelled result evidence and time windows; keep `predictions.jsonl` away from reviewers until annotation is frozen. Every filled label needs `source: "human"` and a reviewer name. Null means unresolved and is excluded from the relevant metric. It must not be turned into a negative label.

For a result, label the intent served *for this query*, plus its content format. Review the actual result when snippets are insufficient; document that in `note`. For a window, judge whether the latest observations provide repeated evidence of a material intent shift compared with the baseline, and separately whether they conflict with the declared page profile. Mark collection corruption or insufficient evidence unresolved, and record why. Do not use rank movement alone as the positive criterion. Two independent reviewers should resolve disagreements before scoring.

Query text, normalized for casing/whitespace, is hashed and sorted to allocate the first 20% of families (rounded up) to `test`, including every locale/device/time instance of the same query. The partition is fixed for this export; adding new queries can change the boundary, so do not combine independently split exports as one benchmark. Review related query variants manually and move whole related families into the same partition before tuning. With `--holdout-after`, later observations from calibration queries enter a separate `temporal_test`. Freeze the split, model, prompt and rules before looking at held-out outcomes; keep a copy of all three files with a checksum. Do not tune on the holdouts.

The score reports, separately by split and held-out language:

- intent-shift and page-mismatch precision, recall, TP/FP/FN/TN;
- labeled result count, classified coverage and accuracy including/excluding model abstentions;
- annotated episodes, detected episodes and mean first-detection delay in capture hours.

Uncertain annotations break episodes. Missing annotation windows can censor detection delay; fully annotate consecutive sequences before interpreting it. The delay starts at the first annotated positive capture, not the unknowable time Google actually changed. Point-wise windows from the same query are correlated, so neither a large window count nor a high score alone establishes generalization.

Target release evidence: at least 90% precision for actionable intent alerts on held-out queries, with recall, detection delay, false positives and coverage published alongside it; results separated by language. This is a target, not an achieved result. Include stable controls, real intent changes, topic changes, format-only changes, locale/device changes, sparse responses, model failures and ambiguous queries. Use at least 100 independently reviewed alert episodes across diverse query families before treating the precision estimate as more than a pilot. Report uncertainty and disagreement rates; publish no classifier ranking from synthetic fixtures.
