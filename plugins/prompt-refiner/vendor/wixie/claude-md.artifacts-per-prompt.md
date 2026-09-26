## Artifacts per prompt

```
prompts/<name>/
├── prompt.<ext>       production prompt, format matches target model
├── metadata.json      model, tokens, cost, 5-axis scores, 8 assertions, version
├── tests.json         regression test cases (≥ 3, ≥ 1 edge-case)
├── report.pdf         dark-themed single-page audit (final only)
└── learnings.md       E6 hypothesis/outcome log — persists across sessions
```

**Folder hygiene.** Intermediate HTML / diffs / scratch live in the plugin's `state/` dir. Only the final PDF stays in `prompts/<name>/`. The prompt folder is a handoff surface, not a work-in-progress.

