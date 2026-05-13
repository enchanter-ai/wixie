# TypeScript MCP Client — Inventory for Agent Port

## Naming note

This document inventories `c:/git/enchanted-skills/client/enchanter/` — a **TypeScript MCP client enforcement library**, NOT the Enchanter inspector. The actual inspector is a Rust dashboard (located elsewhere) that consumes the JSONL events this client emits. The Rust inspector is **not** being ported; with the agent enforcing every previously-optional rule, post-hoc inspection becomes redundant.

## Major finding

The TS MCP client at `c:/git/enchanted-skills/client/enchanter/` (`v0.5.0`, node ≥ 22) already implements the runtime enforcement architecture we were about to design. The Python agent build pivots from "design the runtime" to "port the TS client to Python + add conduct injection + wire inference substrate."

## Scope adjustment — inspector-facing surfaces dropped

Because the agent enforces every previously-optional rule, the external observability layer is redundant. **Dropped from the port:**

- JSONL event bridge (TCP/file/stdout) — no external consumer
- TcpControlSink + ControlDispatcher (bidirectional approve/veto over TCP) — no Rust dashboard sending control
- Ring-buffer bus tap exposed for external query
- Cross-process event propagation
- OpenTelemetry (already dead-weight; declared dep, zero usage)

**Kept:** all internal enforcement surfaces (lifecycle, plugin protocol, trust-pin, transports, OAuth, body caps, phase timeouts). Internal logging stays — but as a rotating file via stdlib `logging`, not as a bridge protocol.

## Human-in-the-loop

The dropped control channel handled external approve/veto for destructive ops. The agent replaces this with two modes:

- **Default:** CLI prompt requires explicit user "yes" before proceeding past a destructive-op gate (matches `conduct/verification.md` § Dry-run for destructive ops)
- **`--strict` flag:** hard-deny, no prompt; user must rewrite the request. Appropriate for CI/headless.

## What the inspector already has

- **7-phase lifecycle:** `anchor → trust-gate → pre-dispatch → dispatch → post-response → post-session → cross-session`
- **Required vs. advisory plugins** — fail-closed / fail-open with per-phase timeouts
- **PluginAdapter interface:** `{name, phases, required, topics, budget_tier, onPhase(event, ctx) → PluginAck}`
- **9 plugin adapters wired** (crow, djinn, emu, gorgon, hydra, lich, naga, pech, sylph)
- **Trust-pin:** SHA-256 over cmd+args+binary+env-allowlist+url+schema-digests. TOFU + mismatch veto. JSONL persistence
- **Tool-name collision guard** — `ToolNameCollisionError` on bare-name resolution when 2+ servers export the same tool
- **Schema-digest pinning** — `SchemaDigestMismatchError` on re-registration with changed schema (MCPoison FM-10)
- **MCP transports:** stdio (JSON-RPC + 8MB cap) + Streamable-HTTP (POST + SSE GET)
- **OAuth 2.1/PKCE** — generateCodeVerifier, deriveS256Challenge, verifyS256, audience binding (RFC 8707), nonce/timestamp replay defense
- **SSRF guard** — rejects RFC-1918, loopback, cloud-metadata IPs, IPv4-mapped IPv6, link-local, non-HTTPS for OAuth metadata
- **TLS certificate pinning** — TOFU + mismatch veto on TLS leaf cert SHA-256 per origin
- **In-process bus** — 10k-event ring buffer, correlation-id tap, derived event propagation
- **JSONL bridge** — bidirectional TCP control channel; serializes every bus event; receives `approval.response` commands; reconnect with backoff + 200-event buffer while disconnected
- **Body caps:** 8MB on stdio and HTTP (FM-5 unbounded resource defense)
- **ACK dedup** — prevents double-execution when plugin subscribes to both domain topic and `lifecycle.<phase>` topic

## What the inspector does NOT have

These are the genuine gaps the Python agent must add:

1. **Conduct injection.** The TS inspector gates *tool calls*, but doesn't inject conduct into *system prompts*. Our agent must add a layer that wraps relevant conduct modules in XML tags at every system-prompt build (per the formatting decision).
2. **Inference substrate.** The TS `packages/plugin-wixie` workspace exists but is not wired as a runtime adapter. `inference-engine.py` is Python-only and lives in the wixie repo, not in the inspector. We wire this in as the cross-session accumulation layer.
3. **Tier router.** The TS `budget_tier` enum (`always` / `med-or-higher` / `high-only`) gates *which plugins run*, not *which model handles the task*. Our tier router (task class → model id) is a new concern.
4. **Cost ledger as a hard gate.** The TS `pech` plugin tracks costs but doesn't enforce a hard budget cap. Our agent adds a hard-stop budget ledger.
5. **DEPLOY-bar verifier sidecar.** The TS lifecycle doesn't have an independent-model verification step. Our agent adds one that fires at `post-response`.

## Decisions locked by this inventory

1. **Translate, don't wrap.** Port the TS runtime to idiomatic Python (`asyncio`, `Protocol`, `dataclass`). One language across the agent. ~2500 lines of mostly mechanical translation.
2. **Drop OpenTelemetry.** Declared dependency in `package.json` but **zero usage** in `src/`. Inherited dep, never wired. The JSONL bridge is the actual observability surface.
3. **Keep the 7-phase lifecycle as the spine.** Don't redesign. The lifecycle is already proven and maps cleanly to async Python.
4. **Map TS plugins to Python engines 1:1** — preserve `PluginAdapter` shape as a Python `Protocol`. Drop the workspace-per-plugin npm packaging; flat `enchanter.engines.*` namespace.

## Three-layer architecture

```
┌─ Conduct injection (NEW) ────────────────────┐
│  Per-rule enforcement: tag                   │
│  Code-enforced → Python middleware           │
│  Prompt-conveyed → XML in system prompt      │
└──────────────────────────────────────────────┘
┌─ Enforcement runtime (PORTED from TS) ──────┐
│  7-phase lifecycle                           │
│  Plugin protocol + 9 ported adapters         │
│  Transports (stdio, Streamable-HTTP)         │
│  Trust-pin, namespace registry, body caps    │
│  OAuth/PKCE, SSRF guard, TLS pinning         │
│  Bus + JSONL bridge                          │
└──────────────────────────────────────────────┘
┌─ Inference substrate (WIRE-IN) ──────────────┐
│  inference-engine.py (already Python)        │
│  catalog.json + artifacts.jsonl              │
│  Briefings render at session start           │
└──────────────────────────────────────────────┘
```

## Engine mapping (TS plugin → Python engine, professional names)

| TS plugin | Python engine(s) |
|---|---|
| hydra | `cve-pattern-gate` + `secret-mask` |
| sylph | `destructive-op-gate` |
| crow | `trust-scorer` |
| djinn | `intent-anchor` + `lcs-drift` |
| emu | `token-runway` |
| gorgon | `import-graph-pagerank` |
| lich | `tool-poisoning-scan` |
| naga | `structural-fingerprint` |
| pech | `cost-ledger` |
| (new) | `conduct-injector` |
| (new) | `inference-substrate` |
| (new) | `tier-router` |
| (new) | `deploy-bar-verifier` |

## Tier 1 capabilities (must port for v0)

- 7-phase lifecycle + required/advisory split + ACK dedup + derived event propagation
- PluginAdapter contract + PluginRegistry
- CVE/pattern veto, destructive-op veto, secret masking
- Tool-name collision guard + schema-digest pinning + trust-pin
- Human-in-the-loop control channel (approve/veto over JSONL bridge)
- Ring-buffer bus tap + JSONL event bridge (stdout/file/TCP)
- stdio + Streamable-HTTP MCP transports
- 8MB body caps
- JSON-RPC correlation, phase timeout map

## Tier 4 — do not port

- OpenTelemetry — declared dep, zero usage in `src/`
- npm workspace packaging (`packages/plugin-*`)
- TypeScript build scaffolding (tsconfig, type declarations)
- `node-notifier` desktop notifications
- TS-specific dev scripts (`scripts/release-prep`, publish, stress, red-team scripts)

## Open questions raised by the inventory

1. **Trust-pin storage path.** The TS uses a caller-configured JSONL file. Python equivalent: XDG data dir, project-local `.enchanter/`, or runtime config?
2. **Ring-buffer coroutine safety.** If Python is `asyncio`, choose `asyncio.Queue` vs. `deque` with lock.
3. **Binary digest on Windows.** TS handles PATHEXT and warns on oversized binaries (cap 64 MiB). Python port needs the same.
4. **OAuth resource server scope.** TS validates audience claim. The Python port needs to know which Anthropic-side resource URIs to expect.
5. **SSE resume on HTTP transport.** TS disables resume by default (FM-8 defense). Python port needs the same opt-in flag.
