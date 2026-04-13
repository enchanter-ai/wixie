# The Science Behind Enchanted Plugins

Formal mathematical models powering every engine in the @enchanted-plugins ecosystem.

These aren't abstractions. Every formula maps to running code.

---

## Flux: Prompt Engineering

### F1. Gauss Convergence Method

**Problem:** Given a prompt $P$, minimize its deviation from ideal quality across 5 dimensions.

$$\sigma(P) = \sqrt{\frac{\sum_{i=1}^{5}(S_i(P) - 10)^2}{5}}$$

At each iteration $n$, select transformation targeting the weakest axis:

$$k^\ast = \arg\min_i S_i(P_n)$$

$$P_{n+1} = T_{k^\ast}(P_n)$$

**Regression protection:**

$$\text{Accept } P_{n+1} \iff \sigma(P_{n+1}) < \sigma(P_n)$$

**Convergence:**

$$\text{DEPLOY: } \sigma(P) < 0.45 \quad \text{PLATEAU: } \sigma(P_n) = \sigma(P_{n-1}) = \sigma(P_{n-2}) \quad \text{MAX: } n \geq 100$$

**Knowledge accumulation:**

$$K_n = K_{n-1} \cup \lbrace(k^\ast, \Delta\sigma, \text{outcome})\rbrace$$

**Implementation:** `shared/scripts/convergence.py`

---

### F2. Boolean Satisfiability Overlay

**Problem:** Continuous scoring can miss categorical failures.

Define 8 boolean predicates $A_j: P \to$ TRUE, FALSE:

$$\text{DEPLOY}(P) \iff \sigma(P) < \tau \ \wedge \ \bigwedge_{j=1}^{8} A_j(P)$$

| $j$ | Predicate | Check |
|-----|-----------|-------|
| 1 | has role | Prompt defines persona |
| 2 | has task | Prompt defines objective |
| 3 | has format | Specifies output structure |
| 4 | has constraints | Has guardrails |
| 5 | has edge cases | Handles failure modes |
| 6 | no hedges | No uncertainty language |
| 7 | no filler | No verbose padding |
| 8 | has structure | Markup present |

**Implementation:** `run_assertions()` in `shared/scripts/convergence.py`

---

### F3. Cross-Domain Adaptation

**Problem:** Transform a prompt for model $M_s$ into equivalent quality for $M_t$.

$$T: (P, M_s) \to (P', M_t)$$

$$\text{Semantic}(P') = \text{Semantic}(P) \quad \wedge \quad \text{Techniques}(P') \cap \text{AntiPatterns}(M_t) = \emptyset$$

Translation applies a composition:

$$P' = A_{M_t} \circ T_{M_t} \circ F_{M_s \to M_t}(P)$$

The 64-model registry provides per-model constraints: format, reasoning type, CoT approach, few-shot requirement, key constraint.

**Implementation:** `plugins/prompt-translate/skills/translate/SKILL.md`

---

### F4. Adversarial Robustness

**Problem:** Determine if a prompt resists adversarial inputs.

$$\Omega(P) = \frac{|\lbrace k : \delta(P, \alpha(c_k)) = \text{RESIST}\rbrace|}{|C|}$$

Hardening maximizes security without degrading quality:

$$P_{\text{hardened}} = \arg\max_{P'} \Omega(P') \quad \text{s.t.} \quad S(P') \geq S(P) - \varepsilon$$

12 attack classes cover OWASP LLM Top 10 vectors.

**Implementation:** `plugins/prompt-harden/skills/harden/SKILL.md`

---

### F5. Static-Dynamic Dual Verification

**Problem:** Static analysis and dynamic behavior can diverge.

$$\text{VERIFIED}(P) \iff \sigma(P) < \tau \ \wedge \ \text{PassRate}(P, T) = 1.0$$

$$\text{PassRate}(P, T) = \frac{|\lbrace i : \forall s \in E_i,\ s \subseteq \text{Output}(P, x_i)\rbrace|}{|T|}$$

**Implementation:** `plugins/prompt-tester/skills/test-runner/SKILL.md`

---

## Allay: Context Health

### A1. Hidden Markov Drift Detection

**Problem:** Detect unproductive loops without false positives.

Hidden states: PRODUCTIVE, READ LOOP, EDIT REVERT, TEST FAIL

$$P(\text{read loop}) = 1 \quad \text{if} \quad \text{count}(\text{read}(f, h)) \geq 3 \ \wedge \ \nexists\ \text{write}(f)$$

$$P(\text{edit revert}) = 1 \quad \text{if} \quad h(\text{write}_n(f)) = h(\text{write}_{n-2}(f))$$

$$P(\text{test fail}) = 1 \quad \text{if} \quad \text{count}(\text{bash}(\text{cmd}, \text{exit} \neq 0)) \geq 3$$

Cooldown: $\text{Alert}(t) = 1 \iff P(\text{drift}) = 1 \ \wedge \ t - t_{\text{last}} > \tau$

**Implementation:** `plugins/context-guard/hooks/post-tool-use/detect-drift.sh`

---

### A2. Linear Runway Forecasting

**Problem:** Predict turns remaining before compaction.

$$\hat{\mu} = \frac{1}{N}\sum_{i=1}^{N} \text{tokens}_i \qquad \text{runway} = \left\lfloor\frac{\text{remaining}}{\hat{\mu}}\right\rfloor$$

$$\text{CI} = t_{\alpha/2} \cdot \frac{s}{\sqrt{N}}$$

| Runway | Action |
|--------|--------|
| $> 20$ | Silent |
| $10$-$20$ | Suggest checkpoint |
| $\leq 10$ | Warning |
| $\leq 3$ | Critical |

**Implementation:** `plugins/context-guard/skills/token-awareness/SKILL.md`

---

### A3. Information-Theoretic Compression

**Problem:** Reduce token consumption while preserving semantic content.

$$O \to O' \quad \text{s.t.} \quad H(O') \geq \theta \cdot H(O) \ \wedge \ |O'| < |O|$$

| Content | $\theta$ | Compression |
|---------|----------|-------------|
| Code | $1.0$ | Lossless |
| Tests | $0.7$ | Pass/fail + first error |
| Logs | $0.3$ | Summary only |

$$CR(O) = 1 - \frac{|O'|}{|O|}$$

**Implementation:** `plugins/token-saver/hooks/pre-tool-use/compress-bash.sh`

---

### A4. Atomic State Serialization

**Problem:** Persist session state to survive compaction.

$$|\text{Checkpoint}(t)| \leq 50\text{KB}$$

$$\text{write}(f.\text{tmp}) \to \text{validate}(f.\text{tmp}) \to \text{rename}(f.\text{tmp}, f)$$

Locking: $\text{acquire} = \text{mkdir}(\text{lock})$ (atomic on all filesystems)

**Implementation:** `plugins/state-keeper/hooks/pre-compact/save-checkpoint.sh`

---

### A5. Content-Addressable Deduplication

**Problem:** Prevent re-reading unchanged files.

$$h_t = \text{SHA256}(\text{content}(f, t))$$

$$\text{Decision}(f, t) = \begin{cases} \text{BLOCK} & \text{if cache}[f].h = h_t \\\\ \text{ALLOW} & \text{if cache}[f].h \neq h_t \\\\ \text{ALLOW} & \text{if } t - \text{cache}[f].t > \text{TTL} \end{cases}$$

**Implementation:** `plugins/token-saver/hooks/pre-tool-use/block-duplicates.sh`

---

*Every formula maps to executable code in the enchanted-plugins ecosystem. The math runs.*
