# Editable regions: the explicit editability contract (WIX-CONV-001)

Audience: the Wixie skills (create, refine, converge, translate, harden, test, review). Tool:
`shared/scripts/prompt_regions.py`. Design: `docs/architecture/convergence-editability.md`.

## The rule

`/converge` (convergence.py) and `output-test.py` may change **only** the bodies of regions
that the prompt explicitly marks as editable. Everything else is immutable data.
- **Unannotated prompts.** A prompt with no explicit region can be scored, critiqued and given
  proposals. It is never written back automatically.
- **Malformed annotations.** A malformed annotation is never scored or written. The result is
  HOLD / exit 1.

## Files

| File | Role |
|---|---|
| `prompts/<name>/editable/<shipped filename>` | **Master.** The annotated source. Only `commit` writes it. |
| `prompts/<name>/<shipped filename>` | **Shipped prompt.** Always equals `strip(master)`. It never contains marker text. It is what models, tests, reports and `prompt.*` globs read. |

- One master exists per shipped variant. For example, `editable/prompt.claude.xml` is the master
  for `prompt.claude.xml`.
- Never glob into `editable/`, and never give a master to a model.

## Markers (written ONLY by the tool)

```
@wixie-editable/1 nonce=<16 hex>
@wixie-editable/1 begin <id> <nonce>
...editable prose...
@wixie-editable/1 end <id> <nonce>
```

- **No agent or LLM ever types a marker or header line.** Markers are inserted only by
  `prompt_regions.py annotate` from line ranges that a human has confirmed.
- **The whole line must match exactly.** A line that mentions `wixie-editable`, or that contains
  the nonce, is anything other than an exact marker makes the file MALFORMED.
- **Consequence:** a prompt whose content mentions the scheme cannot be annotated. It stays
  unannotated, which means critique and proposals only.

## Annotating (create / refine / legacy prompts)

1. Write the prompt **unannotated** as the shipped file.
2. Propose line ranges that cover only your own instruction prose (role, task, constraints,
   edge-case prose).
   - Never include examples, schemas, code, tables, pasted user data or tool output in a range.
   - `.json` prompts get no regions.
3. Ask **one Direction Lock question** that shows the **full text** of each proposed range, with
   its id and line numbers.
   - Truncate only a range longer than 120 lines. Show its first 60 and last 60 lines and the
     notice `[truncated: N lines hidden]`, and offer the rest.
   - Apply only ranges the user confirmed.
4. Run:
   ```bash
   python ${CLAUDE_PLUGIN_ROOT}/vendor/wixie/shared/scripts/prompt_regions.py annotate \
     prompts/<name>/<file> prompts/<name>/editable/<file> --region <id>=L<a>-L<b> [...]
   ```
   - If the last line has no newline and a range ends on it, the tool refuses. Add
     `--add-final-newline` only after telling the user.
5. Check the pair:
   ```bash
   python .../prompt_regions.py strip --check prompts/<name>/editable/<file> prompts/<name>/<file>
   ```
6. On a later refine, run `python .../prompt_regions.py check <new master> --against <old master>`.
   It lists added ids and grown regions, and every one of them must be re-confirmed.

## Translating (/translate-prompt)

- The translator outputs unannotated translated text, a mapping from each source id to a
  translated line range, and the line ranges of content it **added** (for example examples for
  Gemini, or the repeated constraints of the GPT sandwich).
- Save the translation header-only (`annotate` with no `--region`), which gives NO_REGIONS.
- Ask one Direction Lock question showing each source region body next to its translated range.
- After the user confirms, annotate with `--exclude-nonce <source nonce>`, then run:
  ```bash
  python .../prompt_regions.py check <translated master> --translated-from <source master> --added L<a>-L<b>,...
  ```
  It must exit 0. The check rejects new ids, a reused nonce, and a region that overlaps an added
  range. Regions may be dropped but never added.

## Converging

- Run `convergence.py prompts/<name>/editable/<file>` on the **master**.
- Every exit goes through `prompt_regions.commit`, which writes the master and the shipped file as
  a pair and re-reads both. If either changed on disk during the run, the verdict is HOLD and
  nothing is written.
- The JSON payload carries `editability`, `mutation`, `master_sha256` and `shipped_sha256`.
- On an unannotated prompt: pass `--proposal-out ${CLAUDE_PROJECT_DIR}/state/converge-proposals/<name>/<utc>.json`.
  - The run never writes the prompt.
  - A DEPLOY there has `mutation: "none"`. Report it as "meets the heuristic bar, unmodified",
    never as "converged".
- A manual fallback edit may touch region bodies only. It must pass
  `prompt_regions.py verify <master before> <candidate>` and then
  `prompt_regions.py commit <master> <candidate>`. Otherwise discard it.

## metadata.json

Add this object. It is informational only:

```json
"editability": {
  "scheme": "wixie-editable/1",
  "master": "editable/<file>",
  "shipped": "<file>",
  "nonce": "...",
  "regions": ["..."],
  "annotated_by": "create|refine|translate|human|annotate-tool",
  "approved_in": "direction-lock|manual",
  "master_sha256": "...",
  "shipped_sha256": "...",
  "last_converge": {"mutation": "...", "status": "..."}
}
```

Leave it out, or set it to `null`, for an unannotated prompt.
