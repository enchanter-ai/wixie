# The Science Behind Enchanted Plugins

Formal mathematical models powering every engine in the @enchanted-plugins ecosystem.

These aren't abstractions. Every formula maps to running code.

---

## Flux: Prompt Engineering

### F1. Gauss Convergence Method

**Problem:** Given a prompt $P$, minimize its deviation from ideal quality across $N$ dimensions.

**Formulation:**

Let $S: P \to \mathbb{R}^5$ be a scoring function mapping prompts to 5 quality axes. Define the Gauss deviation:

$$\sigma(P) = \sqrt{\frac{\sum_{i=1}^{5}(S_i(P) - 10)^2}{5}}$$

At each iteration $n$, select transformation $T_k$ targeting the weakest axis:

$$k^* = \underset{i}{\operatorname{argmin}}\ S_i(P_n)$$

$$P_{n+1} = T_{k^*}(P_n)$$

**Acceptance criterion (regression protection):**

$$\text{Accept } P_{n+1} \iff \sigma(P_{n+1}) < \sigma(P_n)$$

$$\text{Revert } P_{n+1} = P_n \text{ otherwise}$$

**Convergence conditions:**

$$\text{DEPLOY: } \sigma(P) < 0.45 \quad (\text{all axes} \geq 9.0)$$

$$\text{PLATEAU: } \sigma(P_n) = \sigma(P_{n-1}) = \sigma(P_{n-2})$$

$$\text{MAX: } n \geq 100$$

**Knowledge accumulation (Gauss Accumulation):**

$$\mathcal{K}_n = \mathcal{K}_{n-1} \cup \{(k^*, \Delta\sigma, \text{outcome})\}$$

Strategy selection at iteration $n+1$:
- Skip $k$ if historical $\text{revert\_rate}(k) > 0.5$
- Prioritize $k$ if historical $\overline{\Delta\sigma}(k) > 0$

**Implementation:** `shared/scripts/convergence.py`

---

### F2. Boolean Satisfiability Overlay

**Problem:** Continuous scoring can miss categorical failures. A prompt scoring 9.0 overall may lack a role definition entirely.

**Formulation:**

Define 8 boolean predicates $A_j: P \to \{\text{TRUE}, \text{FALSE}\}$:

$$\text{DEPLOY}(P) \iff \sigma(P) < \tau \;\wedge\; \bigwedge_{j=1}^{8} A_j(P)$$

where:

| $j$ | $A_j$ | Predicate |
|-----|-------|-----------|
| 1 | `has_role` | Prompt defines persona |
| 2 | `has_task` | Prompt defines objective |
| 3 | `has_format` | Prompt specifies output structure |
| 4 | `has_constraints` | Prompt has guardrails |
| 5 | `has_edge_cases` | Prompt handles failure modes |
| 6 | $\neg$`has_hedges` | No uncertainty language |
| 7 | $\neg$`has_filler` | No verbose padding |
| 8 | `has_structure` | Markup present |

This is a conjunction of SAT constraints overlaid on continuous optimization. The engine resolves unsatisfied predicates FIRST, then optimizes the continuous score.

**Implementation:** `run_assertions()` in `shared/scripts/convergence.py`

---

### F3. Cross-Domain Adaptation (Model Translation)

**Problem:** Transform a prompt optimized for model $M_s$ into equivalent quality for model $M_t$ while preserving semantic intent.

**Formulation:**

$$T: (P, M_s) \to (P', M_t)$$

Subject to:

$$\text{Semantic}(P') = \text{Semantic}(P)$$

$$\text{Format}(P') \in \text{Preferred}(M_t)$$

$$\text{Techniques}(P') \cap \text{AntiPatterns}(M_t) = \emptyset$$

The 64-model registry $\mathcal{R}$ provides per-model constraints:

$$\mathcal{R}(M) = \{\text{format}, \text{reasoning}, \text{cot}, \text{few\_shot}, \text{constraint}\}$$

Translation applies a composition:

$$P' = \mathcal{A}_{M_t} \circ \mathcal{T}_{M_t} \circ \mathcal{F}_{M_s \to M_t}(P)$$

**Implementation:** `plugins/prompt-translate/skills/translate/SKILL.md`

---

### F4. Adversarial Robustness (Game Theory)

**Problem:** Determine if a prompt resists adversarial inputs that attempt to override its behavior.

**Formulation (two-player zero-sum game):**

$$\text{Players: Attacker } \alpha, \text{ Defender } \delta(P)$$

$$\text{Action space: } \mathcal{C} = \{c_1, \ldots, c_{12}\}$$

For each attack class $c_k$:

$$\alpha(c_k) \to x_{\text{adversarial}}$$

$$\delta(P, x_{\text{adversarial}}) \to \{\text{RESIST}, \text{VULNERABLE}\}$$

Security score:

$$\Omega(P) = \frac{|\{k : \delta(P, \alpha(c_k)) = \text{RESIST}\}|}{|\mathcal{C}|}$$

Hardening maximizes security without degrading quality:

$$P_{\text{hardened}} = \underset{P'}{\operatorname{argmax}}\ \Omega(P') \quad \text{s.t.} \quad S(P') \geq S(P) - \varepsilon$$

**Implementation:** `plugins/prompt-harden/skills/harden/SKILL.md`

---

### F5. Static-Dynamic Dual Verification

**Problem:** Static analysis (scoring) and dynamic behavior (actual output) can diverge.

**Formulation:**

$$\text{Static: } \sigma(P) < \tau$$

$$\text{Dynamic: } \text{PassRate}(P, \mathcal{T}) = 1.0$$

$$\text{VERIFIED}(P) \iff \text{Static}(P) \wedge \text{Dynamic}(P)$$

where:

$$\text{PassRate}(P, \mathcal{T}) = \frac{|\{i : \forall s \in E_i,\ s \subseteq \text{Output}(P, x_i)\}|}{|\mathcal{T}|}$$

**Implementation:** `plugins/prompt-tester/skills/test-runner/SKILL.md`

---

## Allay: Context Health

### A1. Hidden Markov Drift Detection

**Problem:** Detect when an AI agent enters an unproductive loop without false positives.

**Formulation:**

Hidden states: $\mathcal{S} = \{\text{PRODUCTIVE}, \text{READ\_LOOP}, \text{EDIT\_REVERT}, \text{TEST\_FAIL}\}$

Observable events: $\mathcal{O} = \{\text{read}(f, h),\ \text{write}(f, h),\ \text{bash}(\text{cmd}, \text{exit})\}$

Transition detection:

$$P(\text{READ\_LOOP}) = \mathbb{1}\left[\sum_{t} \mathbb{1}[\text{read}(f, h)_t] \geq 3 \;\wedge\; \nexists\ \text{write}(f, h')_t\right]$$

$$P(\text{EDIT\_REVERT}) = \mathbb{1}\left[h(\text{write}_n(f)) = h(\text{write}_{n-2}(f))\right]$$

$$P(\text{TEST\_FAIL}) = \mathbb{1}\left[\sum_{t} \mathbb{1}[\text{bash}(\text{cmd}, \text{exit} \neq 0)_t] \geq 3\right]$$

Cooldown:

$$\text{Alert}(t) = \mathbb{1}\left[P(\text{drift}) = 1 \;\wedge\; t - t_{\text{last}} > \tau_{\text{cooldown}}\right]$$

**Implementation:** `plugins/context-guard/hooks/post-tool-use/detect-drift.sh`

---

### A2. Linear Runway Forecasting

**Problem:** Predict how many productive turns remain before context compaction.

**Formulation:**

$$\hat{\mu} = \frac{1}{N}\sum_{i=1}^{N} \text{tokens}_{i}$$

$$\text{runway} = \left\lfloor\frac{\text{window} - \text{used}}{\hat{\mu}}\right\rfloor$$

Confidence interval:

$$CI = t_{\alpha/2} \cdot \frac{s}{\sqrt{N}}$$

$$\text{runway} \in \left[\left\lfloor\frac{\text{remaining}}{\hat{\mu} + CI}\right\rfloor,\ \left\lfloor\frac{\text{remaining}}{\hat{\mu} - CI}\right\rfloor\right]$$

| Runway | Action |
|--------|--------|
| $> 20$ | Silent |
| $10$-$20$ | Suggest checkpoint |
| $\leq 10$ | Warning |
| $\leq 3$ | Critical |

**Implementation:** `plugins/context-guard/skills/token-awareness/SKILL.md`

---

### A3. Information-Theoretic Compression

**Problem:** Reduce token consumption of tool outputs while preserving semantic content above a fidelity threshold.

**Formulation:**

$$\text{Compress: } O \to O' \quad \text{s.t.} \quad H(O') \geq \theta \cdot H(O) \;\wedge\; |O'| < |O|$$

| Content type | $\theta$ | Strategy |
|-------------|----------|----------|
| Code blocks | $1.0$ | Lossless |
| Test output | $0.7$ | Pass/fail + first error |
| Verbose logs | $0.3$ | Summary only |

Compression ratio:

$$CR(O) = 1 - \frac{|O'|}{|O|}$$

| Pattern | $CR$ |
|---------|------|
| `npm test` | $\sim 0.8$ |
| `git log` | $\sim 0.9$ |
| `find` | $\sim 0.7$ |
| `cat` | $\sim 0.6$ |

**Implementation:** `plugins/token-saver/hooks/pre-tool-use/compress-bash.sh`

---

### A4. Atomic State Serialization

**Problem:** Persist enough session state to survive compaction without consuming excessive storage.

**Formulation:**

Minimal state vector:

$$\text{Checkpoint}(t) = \{\text{files},\ \text{diff},\ \text{context},\ \text{drift},\ \text{metrics}\}$$

$$\text{s.t.} \quad |\text{Checkpoint}(t)| \leq 50\text{KB}$$

Atomic persistence protocol:

$$\text{write}(f.\text{tmp}) \to \text{validate}(f.\text{tmp}) \to \text{rename}(f.\text{tmp}, f)$$

Locking (portable, no `flock`):

$$\text{acquire}() = \text{mkdir}(\text{lock\_dir}) \quad \text{(atomic on all filesystems)}$$

$$\text{release}() = \text{rmdir}(\text{lock\_dir})$$

**Implementation:** `plugins/state-keeper/hooks/pre-compact/save-checkpoint.sh`

---

### A5. Content-Addressable Deduplication

**Problem:** Prevent re-reading unchanged files that are already in context.

**Formulation:**

For each file read request $(f, t)$:

$$h_t = \text{SHA256}(\text{content}(f, t))$$

$$\text{Decision}(f, t) = \begin{cases} \text{BLOCK} & \text{if } \text{cache}[f].h = h_t \\ \text{ALLOW} & \text{if } \text{cache}[f].h \neq h_t \\ \text{ALLOW} & \text{if } t - \text{cache}[f].t > \text{TTL} \end{cases}$$

On ALLOW: update $\text{cache}[f] = (h_t, t)$

On BLOCK: return preview (first 5 lines) + "use Grep for specific lines"

**Implementation:** `plugins/token-saver/hooks/pre-tool-use/block-duplicates.sh`

---

*Every formula in this document maps to executable code in the enchanted-plugins ecosystem. The math runs.*
