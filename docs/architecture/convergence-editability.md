# WIX-CONV-001: explicit editability contract (architecture, Tranche 7, rev 3)

> **Rev 3:** section 10 holds normative amendments RC2-01..RC2-09 from the rev-2 re-review.
> Where section 10 differs from sections 1-9, section 10 wins.

- **Status:** design only, no product code.
- **Revision:** rev 2 answers the fresh-reviewer verdict APPROVE_WITH_CHANGES
  (`tranche7/verify/conv3-arch/ARCH_REVIEW.{json,md}`). The Review response table in section 9 maps
  every RC item to the section that addresses it.
- **Base:** `31a537f`, which has the f1011ca-era `convergence.py`. The rejected t5 `prompt_spans.py`
  series is not on this branch.
- **Binding decisions:** D12 (as superseded by D15), D14 item 3, D15 item 1, U1, U3.
- **Orchestrator defaults** (adopted from the reviewer; the user may override them): the answers to
  Q1-Q4 in section 8.

## 0. Why inference is abandoned

- Five rounds inferred "safe prose" from Markdown/XML syntax.
- Every round closed its predecessor's counterexamples, and the next verifier found new ones. Tranche 6
  found these:
  - M1/M2: a stray `<!--` paired across a fence or an `<example>`.
  - M3: `a<b` followed by a newline and `>` was read as a tag.
  - M4: an indented fence closer was accepted.
  - M5: the extent of an unclosed `<example>` was wrong.
- The single root cause: the region boundary was a function of the whole surrounding syntax. A gap in
  recognition widened an editable span, and then the same scanner certified the damage.
- This design makes the boundary depend only on exact marker lines. Nothing about the surrounding
  syntax is consulted.

## 1. Representation options

| | A. In-band line markers + per-file nonce | B. Sidecar region map (offsets + hashes) | C. Hybrid (A + sidecar skeleton hash) | D. Format-native tags (`<wixie:editable>`, `<!-- -->`) |
|---|---|---|---|---|
| Boundary depends on surrounding syntax | No: whole-line byte equality | No | No | **Yes**: this is the syntax that failed |
| Confusable with data | No. Quoted or spoofed marker text fails closed (section 2) | Never | As A | **Yes**: `<editable>` inside data |
| Survives /translate-prompt | Yes: the same bytes in every format; ids are carried mechanically (section 5) | **No**: no byte survives, so the map must be re-derived | As A, but the sidecar must also be rebuilt | Needs a different variant per format |
| Survives human editing | Yes, and the markers are visible | **Silently stale** (fails closed on hash) | As A, plus a stale sidecar | Yes |
| Must be stripped before shipping | Yes: whole-line removal, done by `commit()` | No | Yes | Yes, per format |

**Choice: A.**
- It is the only option that is both syntax-independent and survives translation and human editing.
- A nonce-free header-only variant is smaller, but quoted marker text would then be read as real
  markers. The nonce is the minimum that meets "cannot be confused".
- C adds a second source of truth for a guarantee that D15 does not ask for. D15's invariant is per
  run.

## 2. Grammar (normative, byte level)

```
file    = [BOM] header *line                  ; BOM = EF BB BF, only at offset 0
TERM    = CR LF / LF / CR                      ; CRLF matched first; NO other separator
PREFIX  = "@wixie-editable/1 "                 ; ASCII, case-sensitive
header  = PREFIX "nonce=" NONCE TERM           ; physical line 1 (after BOM)
begin   = PREFIX "begin " ID " " NONCE TERM
end     = PREFIX "end "   ID " " NONCE (TERM / end-of-file)
NONCE   = 16 * (%x30-39 / %x61-66)             ; lowercase hex, 64 bits
ID      = %x61-7A 0*31(%x61-7A / %x30-39 / "_" / "-")   ; must not contain NONCE
```

**Byte rules (RC-11).**
- Lines are split on bytes, on CR, LF and CRLF only.
- `str.splitlines`, text-mode reads and universal-newline reads are forbidden everywhere on the
  prompt path.
- VT, FF, 0x1C, NEL, U+2028 and U+2029 are ordinary line content.
- Recognition is exact byte equality and never normalises (U3).
- A **marker line** is its content plus its TERM. **Skeleton** = BOM + header + all marker lines +
  all bytes outside region bodies.
- A **body** runs from the end of a begin line's TERM to the first byte of its end line. A body is
  therefore empty or ends with a TERM.
- Partial-line (inline) regions do not exist.

Example (the same marker lines are used in XML, Markdown, minimal and few-shot prompts):
```
@wixie-editable/1 nonce=3f9a0c71d2e4b856
<role>
@wixie-editable/1 begin role 3f9a0c71d2e4b856
You are a contracts analyst.
@wixie-editable/1 end role 3f9a0c71d2e4b856
</role>
<example>...data, never editable...</example>
```

**`parse(raw)`** is a single linear pass:

1. Remove the BOM at offset 0. A U+FEFF anywhere else is data.
2. Decide how the file is annotated:
   - If line 1 is exactly `header`, the file is annotated.
   - If line 1 is not exactly `header` but its *detection form* (defined in step 3) contains
     `wixie-editable`, the result is `MALFORMED(E_BAD_HEADER)`. This covers a double BOM, a BOM
     plus a ZWSP, and header typos.
   - Otherwise the file is `UNANNOTATED`. Any marker-like lines elsewhere in it are inert and are
     reported as `warnings: [marker_like_text_ignored@L<n>]` (RC-03). Such a file is never a valid
     master (section 5).
3. Classify every later line of an annotated file. These rules are detection only (RC-01): the
   normalisation never accepts a line.
   - The line is exactly an own-nonce `begin` or `end`: it is a **marker**.
   - Otherwise, compute the line's detection form: decode UTF-8, drop Unicode category Cf and all
     whitespace, apply NFKC, then ASCII-lowercase. If that form contains the nonce or the string
     `wixie-editable`, the result is `MALFORMED(E_SPOOFED_MARKER)`.

     This deliberately includes *well-formed foreign-nonce markers*. The reviewer suggested
     allowing them, and I tighten that. A foreign marker could never ship (RC-03 rejects any
     shipped line containing `wixie-editable`), so treating it as spoofed removes the class
     without any loss.
   - Otherwise the line is data. The raw bytes are additionally checked with an ASCII
     case-insensitive nonce search, which catches an upper-case nonce.
4. Apply the stack rules. None of these is ever repaired.

   | Condition | Result |
   |---|---|
   | `begin` while a region is open (also catches interleaving) | `E_NESTED` |
   | `end` with no open region | `E_STRAY_END` |
   | `end` id differs from the open id | `E_MISMATCHED_END` |
   | Id repeated | `E_DUPLICATE_ID` |
   | Id contains the nonce | `E_BAD_ID` |
   | `begin` without a TERM at EOF | `E_TRUNCATED` |
   | Region still open at EOF | `E_UNCLOSED` |
   | Invalid UTF-8 | `E_DECODE` |

   `E_DECODE` also applies to invalid UTF-8 in an `UNANNOTATED` file: it becomes `MALFORMED`, with
   no write and no scoring (RC-18.7).
5. Result: `ANNOTATED` (at least 1 region), `NO_REGIONS`, `UNANNOTATED` or `MALFORMED(code, line)`.

**Region EOL.**
- If all TERMs in a body are identical, the region's EOL is that TERM.
- If the body is empty, the region uses the begin line's TERM.
- If the TERMs are mixed, the region is read-only for this run (`frozen_reason="mixed-eol"`). This
  is local, never document-wide.

**Expected status of spoofed variants** (acceptance item 3).

| Variant | Status |
|---|---|
| ZWSP or soft hyphen inside the nonce | `E_SPOOFED_MARKER` |
| Fullwidth `＠` or fullwidth digits | `E_SPOOFED_MARKER` (NFKC detects it) |
| Upper-case nonce | `E_SPOOFED_MARKER` |
| Trailing space or indentation | `E_SPOOFED_MARKER` |
| Homoglyph in the prefix only (the nonce is intact) | `E_SPOOFED_MARKER` |
| Foreign well-formed marker | `E_SPOOFED_MARKER` |
| U+FB00 (`ﬀ`) near an `ff` nonce | `E_SPOOFED_MARKER`: a fail-closed false positive, accepted |

**Stated residual.** A line with non-NFKC-foldable homoglyphs in *both* the prefix and the nonce (for
example Cyrillic letters) is inert data.
- It cannot open or close a region: only exact lines can.
- It can only matter by "replacing" a real `end`. The region would then need to close at a *later*
  exact own-nonce `end` with the same id. That line must be an exact marker that someone deliberately
  wrote (see A1 below), because ids are unique.
- So this residual cannot produce a widening without a deliberately authored exact marker line.

**Why an exact own-nonce line can only be deliberate.**
- `annotate` guarantees that the nonce is absent from the content.
- Fixers cannot emit the nonce (section 3).
- No LLM writes marker lines (RC-06, section 5).
- An exact own-nonce line is therefore an explicit marker by definition. This includes one inside a
  fence (probe A1).

**Proof sketch: surrounding syntax cannot move a region (RC-10).**
- Region extents are a function only of:
  - the set M of exact marker lines (content plus TERM);
  - the positions of nonce and prefix occurrences in the detection forms.
- Take any change to bytes *outside the marker lines*, for example an unclosed fence, tag, comment,
  CDATA section, quote or bracket, a stray `<`, a table, or an exotic separator. There are three
  cases:
  1. It adds or removes no nonce or prefix occurrence. Then M and every extent are unchanged.
  2. It removes the TERM that precedes a marker line, merging the two lines. The merged line is not
     exact but contains the nonce, so the result is `MALFORMED`.
  3. It adds a nonce or prefix occurrence. The result is `MALFORMED`.
- So no change outside the marker lines moves an extent.
- A change to a marker's own TERM is a marker mutation. It may shift an extent by those TERM bytes
  only (probe B), and it is tested separately.
- M1-M5 cannot recur: `<!--`, `<b`, fence bytes and `<example>` are never consulted.

## 3. Mutation contract

**Fixer input and output.**
- Input is a `FixContext`:
  - `view`: the stripped document, used only for decisions;
  - `bodies`: a list of `RegionView(id, text, editable)`, where `text` is decoded and normalised to
    `\n`.
- The fixer returns a new text or `None` for each region. It has no API that addresses the skeleton.

**Body rules** (checked by `verify`). A new body:
- is empty (`""`) or ends with `\n`;
- contains no `\r`;
- does not contain the nonce;
- adds no detection-form `wixie-editable` occurrence.

Within those rules the body may replace, insert or delete text and newlines, or be emptied. Regions
are never created, removed, renamed, reordered or moved.

**Additions.** Prepends go to the start of the first editable region; appends go to the end of the
last editable region. If there is no editable region, nothing is added.

**`apply` (byte level).**
- The output is `raw[:b0.start] + enc(body0) + raw[b0.end:b1.start] + …`, where `enc` maps `\n` to
  the region's EOL and encodes UTF-8.
- Skeleton bytes are copied slices of the input and are never re-encoded.
- If a candidate equals its input byte for byte, nothing is written, so the mtime is unchanged
  (RC-13).

**`verify(orig_doc, cand_raw)`: the single invariant.** It re-parses the candidate, independently of
`apply`, and requires all of the following:
- `ANNOTATED`;
- the same BOM, the same nonce and the same ordered ids;
- byte-identical skeleton slices;
- the body rules;
- mixed-EOL (read-only) bodies byte-identical to the original.

On failure it raises `RegionViolation`.

`verify` runs at these points:
- after every fixer pass;
- in the per-iteration gate, before the score check;
- inside `commit()`, before and after each write;
- in `try_offline_fix` and the output-test LLM fix (section 4).

**`commit(master_path, shipped_path, new_master, expected_master_on_disk)`** (RC-04, RC-08).

1. Re-read the master and the shipped file from disk. If either differs from what this run read at
   start (the master, or `strip(master)` for the shipped file), raise `ConcurrentModification`. No
   write happens. This handles a human editing the file mid-run (TOCTOU).
2. Run `verify(orig, new_master)`, then compute `shipped = strip(new_master)`. `strip` itself
   rejects any output line whose detection form contains `wixie-editable` (RC-03).
3. Write both files as temp files. Then `os.replace` the master, then `os.replace` the shipped file.
4. Re-read both. Require the master to equal `new_master`, the shipped file to equal `strip` of it,
   and `verify` to pass.
5. On any failure in steps 3-4, restore both original byte strings by compare-and-swap: restore a
   file only if the disk holds the bytes this run wrote. Then raise.

`commit` returns `{master_sha256, shipped_sha256}`.

A crash between the two replaces leaves a master/shipped mismatch. The next run's start-up check
(`strip --check`) treats that mismatch as a usage error (exit 2): nothing is written, and the user is
told to decide which file wins.

**Exit mapping for `convergence.py`.** These are the WIX-EVAL-004 codes. The payload gains
`editability{status, warnings, code, line}`, `mutation`, `master_sha256` and `shipped_sha256`.

| Situation | Write | Verdict / exit |
|---|---|---|
| A candidate fails `verify` | Candidate discarded, logged `reverted: region contract`; the loop continues | n/a |
| `commit` fails, or a concurrent modification is detected | CAS-restore / none | HOLD / 1, `structural_trip: true` |
| Master and shipped file mismatch at start, or no shipped sibling without `--no-shipped` | None | Usage error / 2 |
| `MALFORMED` input | None, no scoring | HOLD / 1, `editability.status=MALFORMED` + code + line |
| Exception anywhere | Guard: CAS-restore the originals if the disk holds this run's bytes. If the disk holds neither this run's bytes nor the originals, touch nothing and report `concurrent modification` | 3 |
| `UNANNOTATED` / `NO_REGIONS`, and the unmodified input meets the bar | None, mtime unchanged | DEPLOY / 0, `mutation: "none"` (score-only, see Q4) |
| `ANNOTATED`, the bar is met, `commit` succeeds (or the candidate equals the input) | Committed (or none) | DEPLOY / 0, `mutation: "applied"` or `"none"` |
| Anything else | Best candidate committed (`ANNOTATED`) or none | HOLD / 1 |

These are the only DEPLOY/0 rows.

**Exit-code difference for readers (RC-13).** `self-eval.py`, `token-count.py` and `efficacy-replay.py`
exit **2** on `MALFORMED`. They have no HOLD verdict, and 2 is their documented "unusable input"
code. `convergence.py` uses HOLD/1 because D15 maps a structural failure to HOLD. Both codes are
non-zero and neither is ever DEPLOY.

## 4. Unannotated and region-free prompts, and output-test.py

**/converge on an `UNANNOTATED`, `NO_REGIONS` or `MALFORMED` prompt.**
- `run()` branches before the loop. The prompt path is never opened for writing.
- `learnings.json` is still written, because it is E6 state, not the prompt.
- Critique (failed assertions and weakest axes) is always printed.
- `--proposal-out PATH` writes `wixie-converge-proposal/1`:
  - `input_sha256`, status, scores, assertions;
  - for each axis, a unified diff of that fixer applied once, in memory, to the whole text, labelled
    `unverified: may touch data; apply manually`.
- `--proposal-out` refuses (exit 2) any path that, after `realpath`/`samefile`, is:
  - inside `prompts/<name>/`, including the master and the shipped file;
  - or an existing file (RC-14).
- Skills pass `${CLAUDE_PROJECT_DIR}/state/converge-proposals/<name>/<utc>.json`.

**Mutation-backed DEPLOY.** This means a DEPLOY where the prompt bytes on disk differ from the input.
For these statuses it is structurally impossible: there is no write call. Tests make any write on the
prompt path raise.

**Q4.** DEPLOY/0 with `mutation: "none"` is allowed only under these conditions:
- nothing was written and the mtime is unchanged;
- the skill reports it as "meets the heuristic bar, unmodified", never as "converged";
- efficacy-replay (Step 2.5) still decides the product DEPLOY.

**output-test.py (RC-05: mandatory, same boundary).**
- **Loader.** It reads bytes, never text mode.
- **Which file it works on.** If `editable/<shipped filename>` exists, the working prompt is that
  master and writes go through `commit()`. Otherwise the working prompt is the shipped file, and it
  is never written.
- **What models see.** `run_generate`, `run_llm_evaluation` and `generate_fix` all receive `view()`
  of the working bytes. No model sees a marker.
- **`try_offline_fix`.** Delegates to `convergence.fix_document`, which runs `verify`. It is not
  applied when:
  - the status is `UNANNOTATED`, `NO_REGIONS` or `MALFORMED`;
  - the module or the function is missing (fail closed).
- **LLM fix (`generate_fix` / `apply_fix`).**
  - **Annotated input.** The fixer model receives the editable bodies with their ids and must
    return `{region_id, target, replacement}`. The target must occur **exactly once** in that
    region's body. The new body must pass the body rules, then `verify`, then `commit`.
  - **Any other case.** The fix is written as a proposal under
    `state/test-proposals/<name>/<utc>.json`.
  - **Text-mode write.** The text-mode `open(prompt_file, "w")` write (line 1063) is removed.
  - **In-memory edits.** Offline-fix edits held in memory are persisted only through that same
    `commit()`.

## 5. Lifecycle

**Two files per shipped prompt (Q1, RC-02).**
- The master is `prompts/<name>/editable/<shipped filename>`, for example
  `editable/prompt.claude.xml` for `prompt.claude.xml`.
- There is one master per variant, with the same extension.
- `prompt.*` globs in the folder never match a master.
- The shipped `prompts/<name>/<shipped filename>` is always `strip(master)` and is written only by
  `commit()`.
- These readers read only the shipped file: `report-gen`, `output-schema`, `output-sim`,
  `dispatch-via-cli` (docs) and every skill glob (converge Step 1, test-runner Step 1).
- Only convergence and output-test open a master.
- If `convergence.py` is given a shipped file that has a master, the file is `UNANNOTATED`. The run
  is read-only and warns `master exists at editable/<f>; run on it`.

**Annotation authority is mechanical (Q2, RC-06).**
- No LLM ever types a header or a marker line. `prompt_regions.py annotate` is the only writer.
- **/create and /refine:**
  - write *unannotated* text plus a proposed range list (`id=Lx-Ly`) that covers only the crafter's
    own instruction prose;
  - never include examples, schemas, code, tables, pasted data or tool output in a range;
  - ask one Direction Lock question showing each range's first and last lines and its line count;
  - on confirmation, run `annotate`, then `commit`.
- **Legacy prompts** follow the same path: /refine may *propose* ranges for confirmation. No tool
  suggests ranges heuristically.
- **`check --against <previous master>`** prints added ids and body growth. /refine and /translate
  must re-confirm any added or grown region.
- **`annotate` details:**
  - **Nonce** = the first 16 hex characters of `sha256(b"wixie-editable/1\0" + content)`. It is
    rehashed with a counter until it is absent from the content (ASCII case-insensitive, and also in
    the detection form) and differs from every `--exclude-nonce <hex>` (RC-12).
  - **Inserted marker lines** take the TERM of the adjacent content line: the first line of the
    range for `begin`, the last line of the range for `end`. The header takes line 1's TERM. An
    empty file uses LF (RC-09).
  - **Unterminated last line** (RC-09). A range that includes it is refused with
    `E_RANGE_UNTERMINATED`, unless `--add-final-newline` is given. That option appends the file's
    dominant TERM (LF if the file has none), and the self-check becomes `strip(result) == x + TERM`,
    which is reported. This affects 4 of the 45 corpus prompts.
  - **`.json` prompts** (RC-15). `annotate` and `check` refuse regions in them.

**/translate-prompt (RC-07).**
- The translator (an LLM) outputs unannotated translated text plus two lists:
  - a per-id mapping to translated line ranges;
  - the line ranges of content it **added**, for example Gemini examples or the GPT sandwich repeat.
- The translation is saved as `NO_REGIONS` (header only, via `annotate` with no ranges) until the
  user confirms the side-by-side mapping (source body vs translated range) in one Direction Lock
  question.
- After confirmation, `annotate --exclude-nonce <source nonce>` adds the regions.
- `check --translated-from SRC --added L1-L2,…` fails in any of these cases:
  - an id is not in the source;
  - the nonce is reused;
  - a region overlaps a declared added range (a declared-range check, not a heuristic).
- Regions may be dropped (o-series) but never added.

**Strip.**
- Removes the header and marker lines with their TERMs; the BOM and all other bytes are kept.
- Deterministic and idempotent.
- **Refuses** unless the input is `ANNOTATED` or `NO_REGIONS`.
- **Refuses** if any output line's detection form contains `wixie-editable` (RC-03).
- `strip --check MASTER SHIPPED` enforces byte equality.
- The prompt-reviewer check is: no line in any shipped file contains `wixie-editable`.

**/harden Step 6 and test-runner (RC-16).**
- A hardened prompt is saved as a new unannotated version, or edited through
  `annotate`/`commit`.
- test-runner and harden read the shipped file.
- `prompts/index.json` lists only shipped files. An entry gains `master: "editable/<f>" | null`.

**metadata.json.** Adds `editability{scheme, master, shipped, nonce, regions, annotated_by,
approved_in, master_sha256, shipped_sha256, last_converge{mutation, status}}`. This is informational
only; convergence reads only the files.

**The 45 existing prompts.**
- They are `UNANNOTATED` and are never auto-annotated.
- /converge only critiques and proposes for them until they are explicitly annotated.
- **Usefulness stays reported (RC-17).** The D12 editable-share metric is reported under the new
  scheme:
  - 0% on the legacy corpus, by construction;
  - measured on the ≥6 annotated real-prompt fixtures;
  - shown next to the 73% baseline and the t5 69% figure.

  D15 governs acceptance; the number stays visible.

**Removed f1011ca-era code (not kept as advisory):**

| Group | Removed |
|---|---|
| Section definitions | `EDITABLE_XML_SECTIONS`, `ALWAYS_FROZEN_XML_ELEMENTS` |
| Structure analysis | `analyze_structure`, `_Structure`, `_free_segments`, `_local_spans`, `_backtick_spans`, `_merge_intervals` |
| Fingerprints and region checks | `structure_fingerprint`, `find_protected_regions`, `protected_regions_equal`, `_keep_if_structure_same` |
| Guarded editing helpers | `_safe_sub`, `_append_safely`, `_insert_before_close` |
| Read and save helpers | `_read_text_preserving`, `_split_keepends_and_strip`, `_safe_text_for_save`, `_candidate_is_structurally_safe`, `_written_file_matches`, and the terminator reconstruction in `_save` |

- This is done in one commit; the history stays.
- `prompt_spans` is not imported.

## 6. Shared module `shared/scripts/prompt_regions.py` (stdlib only, linear, no recursion)

```python
SCHEME = "wixie-editable/1"
class Status(str, Enum): ANNOTATED; NO_REGIONS; UNANNOTATED; MALFORMED
@dataclass(frozen=True) class Region:   id: str; start: int; end: int; eol: bytes; frozen_reason: str | None
@dataclass(frozen=True) class Document: raw: bytes; bom: bool; status: Status; nonce: str | None
                                        regions: tuple[Region, ...]; error: "RegionError | None"; warnings: tuple[str, ...]
class RegionError(ValueError):       code: str; line: int | None        # E_* parse / annotate / strip causes
class RegionViolation(ValueError):   code: str; region_id: str | None   # contract breach in a candidate
class ConcurrentModification(RuntimeError)

def parse(raw: bytes) -> Document                        # never raises on content
def bodies(doc) -> list[RegionView]
def apply(doc, new: Sequence[str | None]) -> bytes        # raises RegionViolation
def verify(orig: Document, candidate: bytes) -> None     # THE invariant
def strip(raw: bytes) -> bytes                           # raises RegionError (status / marker text)
def view(raw: bytes) -> str                              # RC2-01: ANNOTATED/NO_REGIONS -> strip decoded; UNANNOTATED -> raw decoded; MALFORMED raises
def read_view(path) -> str                               # self-eval / token-count / efficacy-replay
def master_for(shipped_path) -> str | None; shipped_for(master_path) -> str
def commit(master_path, shipped_path, new_master: bytes, *, expected: tuple[bytes, bytes]) -> dict
def annotate(raw, ranges, *, exclude_nonces=(), add_final_newline=False) -> bytes
# CLI: check [--against M] [--translated-from S --added R] | strip IN OUT | strip --check M S
#      | annotate IN OUT --region id=Lx-Ly ... | verify A B
```

**Call sites:**
1. **`convergence.py`**
   - Delete the code listed in section 5.
   - Fixers become body-level over a `FixContext`.
   - Add `fix_document(doc, axis) -> bytes`, which runs `verify`.
   - `run()` reads bytes, parses, performs the start-up `strip --check`, dispatches by status,
     scores `view` and writes only through `commit`.
   - Add the crash guard (CAS), `--proposal-out`, `--no-shipped` and the payload fields.
   - Retire `FIXERS[axis](text)` as a public text API.
2. **`output-test.py`:** all of section 4.
3. **`self-eval.py`, `token-count.py`, `efficacy-replay.py`:** use `read_view`.
4. **`report-gen.py`, `output-schema.py`, `output-sim.py`, `dispatch-via-cli.py` docs:** read the
   shipped file only; never glob into `editable/`.
5. **Vendoring:** regenerate with `scripts/vendor-conduct.py`. The closure comes from the imports.
   `--check --offline` must pass. Update the expectation in `tests/distribution/test_runtime_closure`.
6. **Skills:**
   - Add `Bash(python ${CLAUDE_PLUGIN_ROOT}/vendor/wixie/shared/scripts/prompt_regions.py *)` to the
     allowed-tools of converge, prompt-creator, prompt-improver, translate, harden and test-runner.
   - **converge:**
     - Step 1 locates the master and the shipped file.
     - Step 2.5 runs efficacy-replay on the shipped file after asserting
       `sha256(shipped) == payload.shipped_sha256`.
     - Step 3 drops the separate strip step.
     - The manual fallback may edit region bodies only and must pass `prompt_regions.py verify`,
       followed by `commit` through the CLI.
   - **creator, improver, translate, harden and prompt-reviewer:** section 5.
   - **CLAUDE.md:** add a row for `editable/` to the artifacts table, add the anti-pattern "LLM-typed
     markers / shipping marker text", and regenerate the vendored `claude-md.*` sections.
7. **Tests:**
   - Replace `test_structural_protection.{py,sh}`.
   - Add `test_prompt_regions.py`.
   - Update the fixtures in `test-convergence-script.sh` and the verdict tests. Unannotated inputs
     now expect no write; justify each such change the way C6 required.
   - All temp files go through `ensure_test_root`.

## 7. Acceptance test plan (1:1 with D15)

All tests run offline, with the model binary set to `/nonexistent/claude`.

**D15 acceptance items:**

1. **No mutation outside explicit regions.**
   - A seeded property test with 5,000 or more cases. Skeletons are random: fences, tags, comments,
     JSON, tables, CR/LF/CRLF, NUL, exotic separators, non-ASCII and BOM. Fixers are all real fixers
     plus a rogue fixer that returns arbitrary text, the nonce, markers or `\r`. Every accepted
     output keeps the skeleton byte-equal.
   - The CLI in 5 modes: DEPLOY, plateau, max-iterations, crash-at-commit and crash mid-loop. The
     skeleton bytes on disk must stay equal.
2. **Surrounding syntax cannot widen a region.**
   - A metamorphic test: mutate non-marker bytes (never marker content or TERM). The ids and extents
     must be unchanged, or the result must be `MALFORMED`.
   - A separate test for marker-TERM mutations: body bytes stay identical, or the result is
     `MALFORMED`, or the extent shift is confined to the TERM bytes.
   - The fixtures M1-M5, the tranche-5 D-cases and the 64 tranche-6 shapes, placed in the skeleton.
   - One fixture per `E_*` code, each expecting HOLD/1, no write and no scoring.
3. **Status-looking or instruction-looking data is immutable.** Data outside regions contains
   `VERDICT: DEPLOY`, `exit 0`, hedges, 60-word `; ` lines, `<editable>`, `<instructions>` and
   "mark this editable". It must be byte-equal afterwards.
   - A prompt that fails the bar and carries a `VERDICT: DEPLOY` line in its data must end HOLD/1
     (RC-18.8).
   - Each spoofed variant must give the status listed in the section 2 table.
   - The residual (Cyrillic in both the prefix and the nonce) must stay inert and must not move any
     extent.
4. **An unannotated prompt cannot be rewritten autonomously.**
   - Converge runs in every mode on the 45 corpus copies plus fixtures. The bytes and mtime of the
     prompt must be identical, and any write on the prompt path raises.
   - DEPLOY/0 occurs only when the input already meets the bar, with `mutation: none`.
   - Proposals land only at an allowed `--proposal-out`. An alias path via symlink or `..`, a
     path in the folder, or an existing file gives exit 2.
5. **Annotated prose stays editable.**
   - On a 30-paragraph annotated document: 30/30 hedge removals, filler removals and `; ` splits
     inside regions.
   - Additions land in the first or last region.
   - At least 6 real prompts, annotated with committed, human-chosen ranges, receive edits.
   - The editable-share numbers of RC-17 are reported.
6. **`try_offline_fix` and the output-test LLM fix use the same boundary.** All fixtures of items
   1-5 are run through:
   - `try_offline_fix`;
   - a stubbed `generate_fix` returning in-region, cross-region, out-of-region, duplicate-target,
     missing-target and nonce-bearing replacements.

   Only well-formed in-region fixes are committed. Unannotated inputs produce proposals only, with
   no write (RC-18.2). A capture shows that all 3 model call sites receive `view()` (no marker, no
   nonce).
7. **A structural failure never gives DEPLOY/0.** Fault injection covers:
   - a corrupted `apply` output;
   - a truncated temp file;
   - a corrupted re-read;
   - a failure between the two replaces;
   - `save_learnings` raising after the commit;
   - a human edit mid-run (TOCTOU).

   Every case must end HOLD/1, 2 or 3, with the files CAS-restored or untouched as specified
   (RC-08). Across the whole suite, the number of DEPLOY/0 exits with a failing post-write
   `verify` must be 0.

**Additional tests:**

| Area | Tests |
|---|---|
| Two-file consistency (RC-18.1) | After every converge and output-test exit: `strip(master) == shipped`, and the payload's sha256 values match the disk. |
| No marker text ever ships (RC-18.3) | A displaced header, a double BOM and foreign markers are refused by `strip` / `check`. No shipped file anywhere contains `wixie-editable`. |
| EOL/BOM | LF, CRLF, CR, mixed and BOM files; no final newline; `end` at EOF; a mixed-EOL region stays read-only; lines inserted into a CRLF region are CRLF; exotic separators stay line content (RC-11). |
| Determinism | parse, apply, strip and annotate are pure. Two converge runs on copies give identical bytes, and identical JSON once timestamps and paths are normalised (RC-18.5). |
| Round trip (RC-09) | `strip(annotate(x, R)) == x` for the 41 terminated corpus prompts × random ranges. For the 4 unterminated prompts: without the flag, `E_RANGE_UNTERMINATED`; with it, `x + TERM`. Also `strip∘strip = strip`, and `annotate --exclude-nonce` never reuses a nonce. `check --translated-from` rejects an added id, a reused nonce and an added-range overlap, and accepts a dropped id. `.json` regions are refused. |
| Install | From each consuming plugin's vendored tree: `vendor-conduct --check --offline`, plus a runtime import of `prompt_regions` (RC-18.6). |
| Invalid UTF-8 (RC-18.7) | In an `UNANNOTATED` file: `MALFORMED(E_DECODE)`, HOLD/1 in converge, exit 2 in the readers. |

**Held-out plan for the verifier** (not shown to the implementer):
- forgery through every Unicode class in the section 2 table;
- exotic separators around markers;
- U+FB00;
- fullwidth `＠`;
- a double BOM;
- a displaced header;
- scale: 10,000 regions and 1 MB bodies;
- invalid UTF-8;
- skeleton chaos;
- a rogue fixer registered in `FIXERS`;
- crashes and TOCTOU on every exit path;
- an adversarial stubbed LLM fix;
- proposal-path aliasing;
- a translation with undeclared additions (expected to be caught only if declared; see residual R3).

Targets: 0 damaged runs, 0 DEPLOY/0 exits with a violation, 0 writes to unannotated files, and 0
shipped marker text.

## 8. Risks, decisions, effort

**Residual risks.**

| # | Risk | Mitigation |
|---|---|---|
| R1 | An author may confirm a range that contains data. | By design. Mitigated by showing the range text in Direction Lock and recording provenance. |
| R2 | The legacy prompts cannot be converged autonomously until they are annotated. | Reported (RC-17). |
| R3 | A translator can fail to declare an added range. Correspondence is confirmed by a human, not checked mechanically. | Human confirmation of the mapping. |
| R4 | A crash between the two replaces leaves a mismatch between master and shipped file. | Detected at the next start as exit 2; never silently resolved. |
| R5 | SAT keywords in protected data can satisfy assertions. | None needed for D15: this is pre-existing and outside D15 scope. |

**Orchestrator defaults** (from the reviewer; the user may override):

| # | Question | Default |
|---|---|---|
| Q1 | File layout | Two files: `editable/<shipped filename>` master plus the shipped file, bound by `commit()`. |
| Q2 | Region suggestions | No heuristic suggestion anywhere. /create and /refine propose ranges; Direction Lock shows their text; only `annotate` applies them. |
| Q3 | output-test LLM fix | Under the same boundary; mandatory (section 4). |
| Q4 | Unannotated prompt that already meets the bar | DEPLOY/0 with `mutation: "none"`, only if nothing is written and the mtime is unchanged. Never called "converged". Efficacy-replay still applies. |

**Effort.** About 2.5 implementer-days:

| Work | Estimate |
|---|---|
| Module and property tests | 0.75 day |
| Convergence refactor, commit and the CAS/TOCTOU guards | 0.5 day |
| output-test (both fix paths, three model call sites) | 0.5 day |
| Readers, vendoring, skills and CLAUDE.md | 0.25 day |
| Acceptance suite and one full run | 0.5 day |

Plus one fresh verifier session. The corpus in `C:/git/enchanter-ai/wixie` is never touched; the
annotated real-prompt fixtures are copies.

## 9. Review response

| RC | Resolution | Section |
|---|---|---|
| RC-01 (B) | A detection pass (drop Cf and whitespace, NFKC, ASCII-lowercase) gives `E_SPOOFED_MARKER`; recognition stays exact bytes. **Tightened:** well-formed foreign markers are also spoofed in a master, because they could never ship (RC-03). There is a per-variant status table and the residual is stated. | 2, 7.3 |
| RC-02 (B) | The master is `prompts/<name>/editable/<shipped filename>`; loaders and globs read shipped files only. | 5, 6 |
| RC-03 (M) | `strip`/`check` refuse any status other than `ANNOTATED`/`NO_REGIONS` and any `wixie-editable` in the output; `E_BAD_HEADER` catches a double BOM or a displaced header; warnings are surfaced. | 2, 5 |
| RC-04 (B) | `commit()` writes master and shipped file as a pair; both sha256 values go in the payload; Step 2.5 asserts them; `--no-shipped` is available. | 3, 6 |
| RC-05 (B) | Q3 is mandatory: region-id-scoped exactly-once replacement, `verify`, `commit`; unannotated inputs get a proposal only; all 3 model call sites get `view()`; the text-mode write is removed. | 4 |
| RC-06 (M) | Only `annotate` writes markers; Direction Lock shows the range text; `check --against` flags changes; allowed-tools are updated. | 5, 6 |
| RC-07 (M) | A translation is saved as `NO_REGIONS` until the mapping is confirmed; declared added ranges are checked. | 5 |
| RC-08 (M) | CAS restore on exit 3; a TOCTOU re-read inside `commit`; test 7 is aligned. | 3, 7.7 |
| RC-09 (B) | `E_RANGE_UNTERMINATED` / `--add-final-newline`; inserted TERMs are specified; the acceptance row is fixed (41 + 4). | 5, 7 |
| RC-10 | A marker line is content plus TERM; the proof is restated; a separate TERM test is added. | 2, 7.2 |
| RC-11 | Byte-level splitting is normative; recognition never normalises; exotic-separator cases added. | 2, 7 |
| RC-12 | `--exclude-nonce`. | 5 |
| RC-13 | Score-only DEPLOY row added; no write when bytes are unchanged; the MALFORMED exit-code difference is documented. | 3 |
| RC-14 | `realpath`/`samefile` check, folder refusal, no overwrite. | 4 |
| RC-15 | `.json` regions are refused. | 5 |
| RC-16 | /harden Step 6, test-runner, `index.json` and the reader list are covered. | 5, 6 |
| RC-17 | The D12 metric is kept and reported. | 5, 7.5 |
| RC-18 | Tests 1-8 added. | 7 |

**Disagreements.** Only one, and it is a tightening rather than a rejection: RC-01's allowance for
well-formed foreign markers in a master. Given RC-03, such a master could never ship, so this design
classifies them as `E_SPOOFED_MARKER` at parse time instead of failing later at strip. An unannotated
prompt that quotes marker text is unaffected: it stays `UNANNOTATED`, and the text is inert data with
a warning.


## 10. Rev 3 normative amendments (RC2-01..RC2-09; these override sections 1-9)

**RC2-01: `view` is split from `strip`.**
- `strip()` is the lifecycle function, used by `commit`, the `strip` CLI and `strip --check`. It
  stays strict: it accepts only `ANNOTATED`/`NO_REGIONS` input, and its output may contain no
  scheme text.
- `view(raw)` and `read_view(path)` are the reader functions, used by scorers, readers and model
  input:

  | Input status | `view` returns |
  |---|---|
  | `ANNOTATED` / `NO_REGIONS` | `strip(raw)`, decoded |
  | `UNANNOTATED` | the raw bytes decoded (BOM dropped), with warnings passed through |
  | `MALFORMED` | raises `RegionError` (readers exit 2, converge gives HOLD/1) |

- Test: on all 45 corpus prompts and on every shipped file, `view` equals the decoded input.

**RC2-02: how a master and its shipped file identify each other.**
- A **master** is a file whose parent directory is named exactly `editable`.
- `shipped_for(master)` is the parent of the master's parent directory, joined with the same file
  name. It must differ from the input, and it must resolve inside `prompts/<name>/` (the directory
  that contains `editable/`).
- `convergence.py` dispatch:

  | File | Status | Behaviour |
  |---|---|---|
  | master | `ANNOTATED` / `NO_REGIONS` | Normal. Its shipped file must exist, else exit 2, unless `--no-shipped` (writes the master only). |
  | master | `UNANNOTATED` | Exit 2: not a valid master. |
  | master | `MALFORMED` | HOLD/1. |
  | non-master | `ANNOTATED` / `NO_REGIONS` | Exit 2, unless `--no-shipped` (then this file is treated as a master with no shipped pair). |
  | non-master | `UNANNOTATED` | The critique/propose path: exit 0/1, never a write, never exit 2. |
  | non-master | `MALFORMED` | HOLD/1. |

**RC2-03: detection form.**
- Order: NFKC, then drop code points in Cf, Mn, Me, `Default_Ignorable_Code_Point` and all
  whitespace, then NFKC again, then ASCII-lowercase.
- Python's stdlib has no Default_Ignorable property, so the implementation uses the explicit list
  from DerivedCoreProperties: U+00AD, U+034F, U+061C, U+115F-1160, U+17B4-17B5, U+180B-180F,
  U+200B-200F, U+202A-202E, U+2060-206F, U+3164, U+FE00-FE0F, U+FEFF, U+FFA0, U+FFF0-FFF8,
  U+1BCA0-1BCA3, U+1D173-1D17A, U+E0000-E0FFF.
- Held-out cases add U+034F (CGJ) and U+FE0F (VS16) in both the prefix and the nonce. They give
  `E_SPOOFED_MARKER`.
- **Residual:** a non-foldable script homoglyph (for example Cyrillic) in both the prefix and the
  nonce stays inert data. It cannot move an extent unless an exact end marker is deliberately
  authored.

**Expressiveness limit (condition of the accepted foreign-nonce tightening).**
- An annotated master (`ANNOTATED`/`NO_REGIONS`) cannot contain any non-marker line whose detection
  form contains `wixie-editable`. This includes prose that merely mentions the scheme.
- Such prompts stay `UNANNOTATED` and can only be critiqued and proposed against.
- `annotate` refuses them up front with `E_CONTENT_MENTIONS_SCHEME`.

**RC2-04: commit temp files.**
- Temp files are named `.<filename>.wixie-tmp-<pid>`. They are created in the target's directory,
  never match `prompt.*`, and are removed on failure.
- Stale ones are reported as a start-up warning. They are never globbed and never deleted
  automatically.
- The CAS restore is compare-then-replace, not atomic, under a stated single-writer assumption.

**RC2-05: output-test sequencing.**
- An accepted offline or LLM fix on a master is committed immediately after it is accepted.
- The caller then advances `expected` to the `(master, shipped)` bytes that `commit` returns.
- An LLM target must be non-empty and occur exactly once in the named body. The replacement may be
  empty.

**RC2-06: annotate edge cases.**
- The header takes line 1's TERM, else the dominant TERM, else LF. This covers a single unterminated
  line and a no-range `NO_REGIONS` translation. With a single unterminated line, the header is
  inserted before that line, and the line keeps no TERM.
- `annotate` refuses `E_CONTENT_MENTIONS_SCHEME` content (see the expressiveness limit above).
- It self-checks that `parse(result).status` is `ANNOTATED` or `NO_REGIONS`.

**RC2-07: scope of the "no scheme text" rule (orchestrator decision).**
- The rule applies to files produced by `strip`/`commit` (shipped files that have a master) and to
  masters.
- An `UNANNOTATED` legacy file that quotes the scheme is plain data: it is never modified and cannot
  be annotated. The prompt-reviewer check is scoped to shipped files that have a master.

**RC2-08: Direction Lock shows the full text.**
- Each proposed range is shown in full.
- Only a range longer than 120 lines is truncated. It shows the first 60 and last 60 lines, with an
  explicit `[truncated: N lines hidden]` notice in between, and the user may ask for the rest.

**RC2-09: payload hashes for non-master runs.**
- For a run on a non-master file (critique path), `shipped_sha256` is `sha256(input file)` and
  `master_sha256` is `null`.
- Step 2.5's assertion is therefore defined on every path.

## 11. Implementation notes (deltas settled during implementation; the verifier should check them)

1. **Displaced header.** `E_BAD_HEADER` fires only when line 1's detection form starts with
   `@wixie-editable`. A header anywhere else in a non-master file is plain data (RC2-07) and
   produces a `marker_like_text_ignored@L<n>` warning. Under `editable/` the same file is
   `UNANNOTATED`, which gives exit 2 (RC2-02). Such a file therefore cannot reach a shipped
   file, because only `commit` writes shipped files.
2. **Strip is not re-applied.** `strip` refuses `UNANNOTATED` input (RC2-01), so
   `strip(strip(x))` raises `E_NOT_ANNOTATED`. The lifecycle property that is tested instead:
   - `view(strip(x)) == view(x)`;
   - `strip(annotate(x, R)) == x`.
3. **Where output-test records LLM proposals.** They go inline in
   `output-test-results.json` as `iterations_detail[].fix.proposal` (region_id, target,
   replacement, reason), not as a separate `state/test-proposals/` file. The results file is a
   run record, never a prompt, so it cannot alias the prompt (RC-14's concern).
4. **Readers normalise line endings.** `self-eval.py`, `token-count.py`, `efficacy-replay.py`
   and output-test normalise CR/CRLF to LF after `read_view`. This is exactly what their
   previous text-mode reads did, so scores and model inputs are unchanged for unannotated
   prompts. `convergence.py` scores the same normalised view.
5. **Line numbers in `check --added`.** They are in the stripped numbering, which is the
   translator's unannotated output.
6. **Manual fallback CLI.** `prompt_regions.py commit MASTER CANDIDATE [--no-shipped]`
   exposes `commit` for the converge skill's manual fallback. It runs the same `verify`,
   pair check and CAS restore as the library call.
7. **Where learnings are written.** For a master they go to the prompt folder (the parent of
   `editable/`), never inside `editable/`.
8. **Auxiliary-write aliasing (fix round 1, verifier CX-1 / CX-2).** A run writes files outside
   `commit`: `learnings.json` and `learnings.md` in the prompt folder, `--json-out` and
   `--proposal-out`, and in output-test `output-reference.md` and `output-test-results.json`.
   None of these may resolve to the input prompt, the master or the shipped file.
   - **How it is checked.** Paths are compared after realpath, normcase (case-folding on
     Windows) and a samefile check (hard links, 8.3 names, junctions).
   - **What is refused.** Any Windows alternate-data-stream path (`x:stream`) is refused. So is
     any prompt, master or shipped file whose name is reserved (`learnings.md`,
     `learnings.json`, `output-reference.md`, `output-test-results.json`).
   - **When.** All of this is checked with exit 2 before any work. A refused `--json-out` is
     never written. `--json-out` is written only after this check has accepted it (WIX-CONV-002):
     a malformed command line (bad or missing `--max` value, no prompt argument, ...) fails
     before the check can run, so it exits 2 without writing `--json-out` (stdout `--json` and
     stderr still report the error).
   - **Before any exit that reports DEPLOY or `mutation: "applied"`.** The master and the
     shipped file are re-read from disk. Two conditions must hold: `strip(master) == shipped`,
     and both hashes equal the payload's. On a mismatch the run exits HOLD / 1 with
     `structural_trip` and `post_check` set, and restores by compare-then-replace.
   - **Read-only runs.** They re-check that the input's bytes and mtime are unchanged before
     exit.
