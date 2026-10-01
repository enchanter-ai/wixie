## Artifacts per prompt

```
prompts/<name>/
├── prompt.<ext>       production prompt, format matches target model (= strip(master) when annotated)
├── editable/
│   └── prompt.<ext>   annotated master: the only file convergence may edit, and only inside
│                      explicit "@wixie-editable/1" regions (never shown to a model)
├── metadata.json      model, tokens, cost, 5-axis scores, 8 assertions, version
├── tests.json         regression test cases (≥ 3, ≥ 1 edge-case)
├── report.pdf         dark-themed single-page audit (final only)
└── learnings.md       E6 hypothesis/outcome log — persists across sessions
```

**Folder hygiene.** Intermediate HTML / diffs / scratch live in the plugin's `state/` dir. Only the final PDF stays in `prompts/<name>/`. The prompt folder is a handoff surface, not a work-in-progress.

**Explicit editability (WIX-CONV-001).** `/converge` and `output-test.py` change only the bodies of regions a master (`editable/<shipped filename>`) explicitly marks; everything else is immutable data. A prompt without a master is scored, critiqued and given proposals (in `state/`), never rewritten. Markers are written only by `shared/scripts/prompt_regions.py annotate` from human-confirmed ranges; masters and shipped files are written together only by `prompt_regions.commit`. Protocol: [`shared/references/editable-regions.md`](shared/references/editable-regions.md).

