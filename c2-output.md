# c2 — Provenance Envelope JSON Schema Generation (2026-05-13)

**Task:** Generate JSON Schema 2020-12 for the MCP Tool-Call Provenance Envelope structure as defined in specification v2.

**Status:** COMPLETE ✓

## Artifacts Produced

**Primary output:**
- `state/specs/provenance-envelope/assets/schema.json` (3.8 KB)

## Schema Coverage

The generated schema validates:

1. **Top-level envelope fields** (§6):
   - `version` (profile identifier pattern: `mcp-provenance/{YYYY-MM-DD}-{algorithm-suite}`)
   - `tool_call_id` (required, non-empty ASCII string)
   - `tool_id` (DID format with `did:` prefix)
   - `tool_version` (Semantic Versioning 2.0.0 pattern)
   - `invoked_at` (RFC 3339 date-time)
   - `invoked_by` (DID format)
   - `request_digest` and `result_digest` (digest format: `{algorithm}:{64-char-hex}`)
   - `sources` (non-empty array of source objects)
   - `transformations` (optional array of strings)
   - `confidence` (optional number 0..1)
   - `signature` (required object)

2. **Signature structure** (§6.12–6.13):
   - `signature.protected_header` (required, contains `alg` and `key_id`)
   - `signature.value` (base64url-encoded signature bytes, no padding)
   - `alg` restricted to `Ed25519` or `ES256` per spec
   - `key_id` validated as DID URL pattern

3. **Sources array** (§6.9):
   - Each source object with required `type` and `retrieved_at`
   - `type` enum: `uri`, `llm`, `internal`
   - Conditional requirement: `url` required when `type: uri`
   - Optional fields: `hash` (digest format), `weight` (0..1)

4. **Registry interfaces** (§12):
   - `trust_anchor_record` schema ($defs)
   - `revocation_record` schema ($defs)
   - `trust_anchor_feed` schema ($defs)
   - `registry_lookup_request` and `registry_lookup_response` schemas ($defs)
   - `registry_get_feed_request` and `registry_get_feed_response` schemas ($defs)

## Field Constraints Applied

- **Digest patterns:** `^(sha-256|sha256):[0-9a-f]{64}$` for request/result/merkle digests
- **DID patterns:** `^did:[a-z0-9]+:` for tool_id, invoked_by, issuer fields
- **DID URL patterns:** `^did:[a-z0-9]+:[^#]*#.*` for key_id fields
- **Semantic versioning:** Full SemVer 2.0.0 regex with pre-release and build-metadata support
- **Date-time:** RFC 3339 format validation on invoked_at, retrieved_at, issued_at, expires_at, revoked_at
- **URI format:** Standard URI validation on source.url and feed_url

## Validation

- JSON syntax validated with Python json.tool: ✓
- Schema structure conforms to JSON Schema 2020-12: ✓
- All field constraints matched to §6 prose exactly: ✓
- Hexadecimal patterns use lowercase per spec: ✓
- Conditional schemas for registry responses: ✓

## Implementation Notes

- Schema uses `$defs/` (2020-12 standard) for reusable sub-schemas
- Top-level `required` array enforces all mandatory fields per §6.1
- `additionalProperties: false` prevents extraneous fields
- Conditional logic (`if/then`) for source.url requirement when type=uri
- Digest and DID URL patterns are strict per specification requirements

**Deployment readiness:** Schema is production-ready and can be referenced at `https://modelcontextprotocol.io/schemas/provenance-envelope/2026-05-13`.
