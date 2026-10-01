# Technique Engine

> **Model specs are sourced from [models-registry.json](../models-registry.json).** If the registry's `last_updated` date is more than 3 months old, verify model-specific anti-patterns against current benchmarks before applying. Techniques that hurt today may help tomorrow as models evolve — override outdated recommendations and note the change in the Creation Report.

Decision reference for selecting prompt engineering techniques. Read this file during Phase 3A of the creation workflow.

---

## 1. Selection Algorithm

Follow these steps in order to select the right technique(s) for a given prompt:

1. **Classify task**: Determine which category the user's task falls into:
   `[coding | data-extraction | creative-writing | analysis | agent | conversational | image-gen | decision-making | other]`

2. **Assess complexity**: Gauge the number of reasoning steps required:
   - `simple` — Single-step, well-defined, one clear answer
   - `moderate` — 2-4 steps, some ambiguity, requires modest reasoning
   - `complex` — 5+ steps, significant ambiguity, multi-faceted, or requires exploration

3. **Check target model reasoning capability**: Identify whether the target model has built-in reasoning:
   - `standard` — GPT-4o, GPT-4.1, GPT-5, Claude Sonnet 4.6, Gemini Pro, Llama 4, Mistral, etc.
   - `reasoning-native` — o1, o3, o4-mini (built-in chain-of-thought; explicit CoT is harmful)
   - `extended-thinking` — Claude Opus 4.6 with extended thinking enabled (budget-based internal reasoning; 1M context)

4. **Select primary technique** from the Decision Matrix below, cross-referencing task type, complexity, and model capability.

5. **Check anti-patterns** — If the primary technique appears in the Anti-Pattern Warning column for the target model, fall back to the next best technique in the matrix.

6. **Optionally add a secondary technique** (max 2 techniques combined with the primary). Consult the Combination Rules and the "Pairs With" column.

---

## 2. Technique Decision Matrix

| Technique | Use When | Avoid When | Best Models | Anti-Pattern Warning | Pairs With |
|-----------|----------|------------|-------------|---------------------|------------|
| **Zero-Shot** | Simple, well-defined tasks where the model is highly capable; instructions are unambiguous; no special format required | Complex multi-step reasoning; format-sensitive output where examples would clarify expectations; novel or unusual task types the model may not have seen | Universal — works across all models and capability tiers | Insufficient for multi-step logic; the model may take shortcuts or miss nuances without examples or explicit reasoning scaffolding | Constraint Prompting |
| **Few-Shot** | Format adherence is critical; classification tasks; structured output consistency; the model needs concrete examples to understand the pattern; establishing tone or style | Token-constrained contexts where examples consume too much budget; targeting o-series models where few-shot can reduce effectiveness; tasks where a single example might anchor the model to a narrow interpretation | All standard models; Claude (wrap examples in `<example>` tags for best results); **REQUIRED for Gemini** (Google's explicit recommendation) | On o-series models (o1, o3, o4-mini): few-shot examples reduce effectiveness and waste tokens because the model's internal reasoning already handles pattern recognition | Structured Output |
| **Chain-of-Thought** | Multi-step reasoning; mathematical computation; logical deduction; debugging; causal analysis; any task where showing work improves accuracy | Simple single-step tasks (adds unnecessary latency); o-series/o1/o3/o4-mini (they have built-in CoT); Claude in Extended Thinking mode (redundant with internal reasoning budget) | GPT-4o, GPT-4.1 (use explicit "think step by step"); Claude Sonnet (use explicit reasoning instructions) | **ON O-SERIES: EXPLICIT CoT HURTS PERFORMANCE** — the model already reasons internally, and adding explicit CoT creates conflicting reasoning paths. On Claude Extended Thinking: redundant and wastes tokens because the thinking budget already allocates internal reasoning | Few-Shot |
| **Zero-Shot CoT** | Quick reasoning boost without needing to craft examples; moderate complexity tasks; when you want to add "think step by step" and nothing else | O-series models (same conflict as full CoT); very simple tasks where reasoning overhead is wasteful; tasks that need structured output format | GPT-4.x, Claude Sonnet (standard mode) | Less reliable than few-shot CoT; the model may produce shallow or abbreviated reasoning steps without the anchor of worked examples | Standalone technique |
| **Tree of Thoughts** | Creative problem-solving requiring exploration of multiple solution paths; strategic planning; tasks where the first answer is unlikely to be the best; design decisions with trade-offs | Time-sensitive or latency-sensitive production systems; simple queries with obvious answers; cost-constrained scenarios (generates many tokens exploring branches) | Claude Opus, GPT-4 (requires strong reasoning to manage multiple branches without losing coherence) | Computationally expensive — generates 3-5x more tokens than linear reasoning; may cause hallucination or incoherent branches in weaker models that cannot maintain parallel reasoning threads | Meta Prompting |
| **ReAct** | Tool use and agentic workflows; tasks requiring real-time information gathering; multi-step processes that alternate between reasoning and acting; retrieval-augmented generation | Pure reasoning tasks without external data needs; environments with no tool access; simple Q&A where all information is in the prompt | All tool-augmented models (GPT-4o with function calling, Claude with tool use, Gemini with extensions) | Requires tool integration — the technique is meaningless without actual tools to call; poorly defined tool descriptions lead to incorrect tool selection and cascading errors | Constraint Prompting |
| **Self-Consistency** | High-stakes decisions where confidence matters; ambiguous problems with multiple valid approaches; verifying correctness of critical outputs; reducing variance in model responses | Cost-sensitive applications (requires multiple inference runs); simple queries with obvious single answers; real-time systems where latency of multiple runs is unacceptable | All models with temperature > 0 (needs stochastic variation to produce diverse reasoning paths) | Requires multiple inference runs — typically 3-5x cost multiplier; diminishing returns beyond 5 samples; not useful if temperature is 0 since all runs produce identical output | Chain-of-Thought |
| **Reflexion** | Iterative self-improvement; debugging and code review; tasks where first-pass output is likely to have errors; quality-critical content that benefits from self-critique and revision | Single-pass tasks where iteration adds no value; latency-sensitive production endpoints; cost-constrained scenarios (each reflection pass is an additional inference) | Claude (strong self-awareness), GPT-4 (reliable self-critique capabilities) | Multiple iterations increase cost and latency linearly — 2-3 reflection passes means 2-3x the cost; the model may over-correct on later passes, introducing new errors while fixing old ones | Chain-of-Thought |
| **Least-to-Most** | Complex multi-step problems that can be decomposed into sub-problems; compositional tasks where solving smaller pieces builds toward the full answer; math word problems; multi-part analysis | Simple tasks where decomposition overhead is not justified; non-compositional tasks that cannot be cleanly broken into sub-problems; time-sensitive queries | GPT-4, Claude (both handle sub-problem decomposition and synthesis well) | Decomposes poorly on non-compositional tasks — if the problem does not have a natural hierarchy, forced decomposition fragments context and produces worse results than direct answering | Chain-of-Thought |
| **Meta Prompting** | Multi-expert problems requiring diverse domain knowledge; complex multi-faceted tasks benefiting from multiple perspectives; architectural decisions; cross-disciplinary analysis | Simple single-domain tasks where one perspective suffices; cost-sensitive scenarios (meta-level reasoning adds substantial token overhead); tasks with clear single correct answers | Claude Opus (strong meta-cognitive capabilities), GPT-4 (handles multi-perspective reasoning well) | Overhead of meta-level reasoning — the model spends tokens orchestrating perspectives before producing useful output; on weaker models, the meta-layer may collapse into a single undifferentiated perspective | Role Prompting |
| **Prompt Chaining** | Complex pipelines with distinct stages; multi-stage data processing (extract, transform, format); workflows where each step's output feeds the next; quality gates between stages | Simple tasks completable in one pass; real-time latency constraints where sequential calls are too slow; tightly coupled steps that lose critical context when separated | Universal — works with any model since chaining is an orchestration pattern, not a model feature | Error propagation between steps — mistakes in early stages compound through the pipeline; context loss at stage boundaries can cause drift from original intent; debugging requires inspecting each stage independently | Structured Output |
| **Structured Output** | Data extraction into schemas; API response generation; consistent machine-parseable output; any task where downstream code must parse the result reliably | Free-form creative writing; exploratory brainstorming; tasks where rigid structure constrains the quality of the response; emotional or nuanced content | GPT-4.1 (native JSON mode with schema enforcement), Claude (strong XML and JSON adherence), Gemini (structured output API) | Over-constraining creative tasks kills quality — forcing rigid schemas on inherently fluid content produces wooden, formulaic output that satisfies the schema but misses the purpose | Few-Shot |
| **Role Prompting** | Domain expertise is needed (legal, medical, technical); specific tone or perspective control; creative writing with character voice; simulating a specialist consultant | Objective data analysis where bias is harmful; factual extraction where perspective should not influence results; tasks requiring strict neutrality | Universal — all models respond to role assignment, though quality varies with model capability | Can introduce bias — the model may fabricate domain-specific details to stay in character; reduces objectivity on factual tasks; overly specific roles can narrow the model's solution space unnecessarily | No specific pairing required |
| **Constraint Prompting** | Safety-critical systems; format-strict production output; tasks with clear boundaries (word limits, forbidden topics, required sections); compliance-sensitive applications | Exploratory or creative brainstorming where constraints would stifle ideation; early-stage drafting; tasks where the user does not yet know what they want | Universal — constraint following is a core capability of all instruction-tuned models | Over-constraining reduces creativity and can cause the model to focus on satisfying constraints rather than producing quality content; too many constraints create conflicts the model resolves unpredictably | Structured Output |
| **Socratic Prompting** | Teaching and education; guided exploration where the user should arrive at their own conclusion; coaching; helping users refine their own thinking; interview-style discovery | Production systems where direct answers are needed; time-sensitive queries; users who explicitly want a direct answer, not a dialogue; automated pipelines | GPT-4o, Claude Sonnet (both handle questioning and guided discovery naturally) | Frustrating when the user wants a direct answer — misapplying Socratic method to action-oriented requests wastes time and irritates users; not suitable for system prompts in production applications | No specific pairing required |
| **Chain-of-Draft** | Token-efficient reasoning where cost matters; tasks that benefit from CoT but where verbose explanations are wasteful; high-volume production systems needing reasoning at lower cost | Tasks requiring verbose, detailed explanations (teaching, documentation); situations where the reasoning trace itself is a deliverable; tasks where reasoning transparency is a requirement | All standard models (instruct the model to keep reasoning steps brief and draft-like rather than verbose) | Newer technique — less battle-tested than standard CoT; the model may over-compress reasoning and skip critical steps; finding the right brevity level requires experimentation | Standalone technique |

---

## 3. Priority Rules

These rules override the general decision matrix. Apply them in order — the first matching rule takes precedence.

### O-Series Models (o1, o3, o4-mini)

```
IF target is o-series OR o1 OR o3 OR o4-mini:
  THEN:
    - NEVER select Chain-of-Thought, Zero-Shot CoT, or Few-Shot
    - Prefer: Zero-Shot + Constraint Prompting
    - Use developer messages, NOT system messages (o-series ignores system role)
    - Add "Formatting re-enabled" as the first line of the prompt if markdown output is needed
    - Keep prompts concise — the model's internal reasoning handles complexity
    - Do NOT instruct the model to "think step by step" or "reason carefully"
    - Do NOT provide worked examples — they anchor the model and reduce flexibility
```

### Claude with Extended Thinking

```
IF target is Claude with Extended Thinking:
  THEN:
    - SKIP explicit Chain-of-Thought (redundant with internal thinking budget)
    - Use the phrase "think thoroughly" instead of "think step by step"
    - Prefer: Role Prompting + Structured Output
    - Set an appropriate thinking budget rather than prompting for reasoning
    - Focus the prompt on WHAT to produce, not HOW to reason
    - The model will automatically allocate reasoning effort proportional to task difficulty
    - Explicit reasoning instructions waste tokens by duplicating the thinking budget
```

### Gemini Models

```
IF target is Gemini:
  THEN:
    - ALWAYS include Few-Shot examples (Google's explicit guidance for best results)
    - Keep temperature at 1.0 in any configuration suggestions (Gemini's calibrated default)
    - Add a self-critique instruction for complex tasks ("Review your answer for errors before finalizing")
    - Use structured output format specifications when possible
    - Gemini benefits from explicit formatting instructions more than other model families
    - For Gemini 2.5 Pro with thinking enabled, treat as reasoning-native (similar rules to o-series)
```

### Data Extraction Tasks

```
IF task is data-extraction:
  THEN:
    - Primary technique: Structured Output + Few-Shot
    - Include a complete schema definition in the prompt (JSON Schema, TypeScript interface, or XML DTD)
    - Provide at least 2 examples showing input-to-output mapping
    - Specify handling for missing/null/ambiguous fields explicitly
    - Add a constraint: "Extract only what is explicitly stated; do not infer missing values"
    - For tabular data: specify column headers, data types, and delimiter
```

### Code Generation Tasks

```
IF task is code generation:
  THEN:
    - Primary technique: Few-Shot (with code examples) + Constraint Prompting
    - Include: target language, framework/library versions, error handling requirements
    - Specify: naming conventions, documentation style, test expectations
    - Add constraints for: no deprecated APIs, specific import styles, type safety level
    - For complex code: add Least-to-Most to decompose into functions/modules
    - For debugging: add Reflexion to have the model review its own code for errors
```

### Creative Writing Tasks

```
IF task is creative-writing:
  THEN:
    - Primary technique: Role Prompting (with minimal constraints)
    - AVOID Structured Output — rigid schemas produce wooden prose
    - AVOID heavy Constraint Prompting — too many rules stifle creativity
    - Acceptable constraints: tone, length range, audience, perspective (POV)
    - Use Few-Shot only for style matching (provide 1-2 short excerpts as style reference)
    - Let the model have creative freedom within broad guardrails
    - For poetry or lyrical content: specify form only if the user requested a specific form
```

### Agent and Tool-Use Tasks

```
IF task is agent/tool-use:
  THEN:
    - Primary technique: ReAct + Constraint Prompting
    - Include complete tool descriptions with parameter schemas
    - Specify error handling: what to do when a tool call fails
    - Add persistence instructions: how to maintain state across turns
    - Define termination conditions: when to stop acting and return a final answer
    - Include safety constraints: which actions require confirmation, rate limits, forbidden operations
    - For multi-agent systems: add Meta Prompting to coordinate agent roles
```

### Analysis Tasks

```
IF task is analysis:
  THEN:
    - Primary technique: Chain-of-Thought (for standard models) or Zero-Shot (for reasoning-native)
    - Add Structured Output for the final deliverable format
    - For comparative analysis: use Tree of Thoughts to explore multiple angles
    - For quantitative analysis: add Constraint Prompting with precision requirements
    - For qualitative analysis: add Role Prompting with relevant domain expertise
    - Always specify: what counts as evidence, acceptable confidence levels, how to handle ambiguity
```

### Decision-Making Tasks

```
IF task is decision-making:
  THEN:
    - Primary technique: Self-Consistency + Chain-of-Thought (for standard models)
    - For reasoning-native models: Zero-Shot + Constraint Prompting (specify decision criteria)
    - Always require: explicit criteria listing, pros/cons for each option, confidence level
    - Add Reflexion if the decision is high-stakes and benefits from self-review
    - Specify: who the decision-maker is, what constraints exist, what "good" looks like
    - Avoid Role Prompting if objectivity is important
```

---

## 4. Technique Combination Rules

### General Limits

- **Maximum 3 techniques per prompt** (2 preferred). Beyond 3, the prompt becomes unwieldy and the model struggles to satisfy all structural demands simultaneously.
- The **primary technique** provides the structural backbone of the prompt — it determines the overall flow and format.
- The **secondary technique** adds a specific capability on top — it augments but does not replace the primary structure.
- A **tertiary technique** should only be added when the task genuinely requires it and the prompt remains coherent.

### Valid Combinations

These pairings have been tested and produce reliable results:

| Primary | Secondary | When to Use |
|---------|-----------|-------------|
| Few-Shot | Structured Output | Format-critical extraction or classification with schema enforcement |
| Few-Shot | Chain-of-Thought | Complex tasks where examples include reasoning traces |
| Chain-of-Thought | Few-Shot | Reasoning tasks where worked examples anchor the thinking pattern |
| Chain-of-Thought | Constraint Prompting | Reasoning with strict output format or safety requirements |
| Role Prompting | Structured Output | Expert-voice responses in a machine-parseable format |
| Role Prompting | Few-Shot | Domain expert with calibrated response style via examples |
| Role Prompting | Constraint Prompting | Expert with guardrails (safety, compliance, length) |
| ReAct | Constraint Prompting | Agentic workflows with safety rails and operational boundaries |
| Structured Output | Constraint Prompting | Strict schema with additional validation rules |
| Zero-Shot | Constraint Prompting | Simple tasks with specific format or safety requirements |
| Meta Prompting | Role Prompting | Multi-expert panel where each expert has a defined role |
| Tree of Thoughts | Meta Prompting | Exploration with multiple expert perspectives evaluating branches |
| Prompt Chaining | Structured Output | Multi-stage pipeline with typed interfaces between stages |
| Least-to-Most | Chain-of-Thought | Compositional problems where each sub-problem requires reasoning |
| Reflexion | Chain-of-Thought | Self-reviewing reasoning where the model critiques its own logic |
| Self-Consistency | Chain-of-Thought | Multiple reasoning paths sampled and compared for consensus |

### Incompatible Pairs

These combinations conflict and should never be used together:

| Technique A | Technique B | Why They Conflict |
|-------------|-------------|-------------------|
| Chain-of-Thought | Chain-of-Draft | Contradictory instructions — one says "reason verbosely," the other says "reason briefly" |
| Zero-Shot | Few-Shot | Mutually exclusive by definition — you either provide examples or you do not |
| Tree of Thoughts | Chain-of-Draft | Tree of Thoughts requires expansive exploration; Chain-of-Draft compresses reasoning |
| Socratic Prompting | Constraint Prompting | Socratic method requires open-ended questioning; constraints close down the response space |
| Socratic Prompting | Structured Output | Guided questioning produces dialogue, not structured data; the formats are incompatible |
| Self-Consistency | Zero-Shot | Self-Consistency needs reasoning traces to compare; Zero-Shot produces no traces |

### Combination Ordering

When combining techniques, structure the prompt in this order:

1. **Role assignment** (if using Role Prompting) — set the persona first
2. **Task description** — what the model should do
3. **Technique scaffolding** (CoT instructions, ReAct format, etc.) — how the model should think
4. **Examples** (if using Few-Shot) — calibration via demonstration
5. **Constraints** (if using Constraint Prompting) — boundaries and rules
6. **Output format** (if using Structured Output) — the shape of the final response

---

## 5. Complexity Escalation Guide

Use this table to quickly map task complexity to the appropriate technique tier. Start at the lowest viable tier and escalate only when the simpler approach fails to produce adequate results.

| Complexity | Characteristics | Recommended Techniques | Token Budget Guidance |
|------------|----------------|----------------------|----------------------|
| **Simple** | Single-step; clear input/output; no ambiguity; factual or procedural | Zero-Shot, or Few-Shot (if format matters) | Low — keep prompts concise; examples only if format adherence is critical |
| **Moderate** | 2-4 steps; some ambiguity; requires reasoning but solution path is visible | Chain-of-Thought, or Role Prompting + Structured Output, or Few-Shot + Constraint Prompting | Medium — invest tokens in either reasoning scaffolding or examples, not both |
| **Complex** | 5+ steps; significant ambiguity; multiple valid approaches; requires exploration or iteration | Tree of Thoughts, Meta Prompting, Prompt Chaining, or Least-to-Most | High — these techniques are token-intensive by design; budget accordingly |

### Escalation Signals

Move up one complexity tier when you observe any of these:

- The model produces incorrect or incomplete answers at the current tier
- The task requires the model to consider multiple perspectives or trade-offs
- The output needs to satisfy conflicting requirements (e.g., thorough yet concise)
- The user's prompt contains implicit sub-tasks that must be addressed separately
- The task domain is highly specialized and the model lacks reliable zero-shot knowledge

### De-escalation Signals

Move down one complexity tier when you observe any of these:

- The technique overhead exceeds the task difficulty (a sledgehammer for a nail)
- The model produces correct answers with a simpler technique in testing
- Token cost is a concern and the simpler approach achieves acceptable quality
- The task is repetitive or templated, making advanced techniques wasteful
- The target model is reasoning-native (o-series) and handles complexity internally

### Quick Reference by Task Type

| Task Type | Simple | Moderate | Complex |
|-----------|--------|----------|---------|
| Coding | Zero-Shot | Few-Shot + Constraints | Least-to-Most + CoT |
| Data Extraction | Zero-Shot + Schema | Few-Shot + Structured Output | Prompt Chaining + Structured Output |
| Creative Writing | Zero-Shot + Role | Role Prompting + Few-Shot (style) | Role + Tree of Thoughts |
| Analysis | Zero-Shot | CoT + Structured Output | Meta Prompting + CoT |
| Agent/Tool-Use | ReAct | ReAct + Constraints | ReAct + Meta Prompting + Constraints |
| Conversational | Zero-Shot | Role Prompting | Role + Socratic Prompting |
| Decision-Making | Zero-Shot | CoT + Constraints | Self-Consistency + CoT |
| Image Generation | Zero-Shot (descriptive prompt) | Constraint Prompting (style, composition) | Few-Shot (reference images) + Constraints |

---

*End of technique engine reference. Return to the creation workflow after selecting techniques.*
