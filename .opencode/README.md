# .opencode — Centralized Deployment & Configuration

This directory holds deployment-wide configuration and settings for the Wixie agent network.

## Files

### `deployment.config.yaml` (Single Source of Truth)

**Status:** v2.2.0 (2026-06-01)

Central configuration file for all model versions, port numbers, context windows, VRAM requirements, and framework versions. Referenced by scripts, conduct modules, and deployment automation.

#### Key Sections

- **`metadata`** — Version, author, update instructions
- **`frameworks`** — LMStudio 0.14.13, vLLM 0.21.0, Anthropic SDK 1.31.0
- **`models.local`** — Qwen 3.5-27B and Gamma 4-24B (full specs)
- **`cloud_models`** — Claude Opus 4.8, Sonnet 4.6, Haiku 4.5 (backup/fallback)
- **`inference_endpoints`** — Port 1234 (LMStudio), 8001 (vLLM)
- **`orchestration.agents`** — plan_agent, build_agent, verify_agent routing
- **`environments`** — dev, staging, production configurations
- **`quick_reference`** — Fast lookup table

#### Usage Examples

**Python (YAML loader):**
```python
import yaml
with open('.opencode/deployment.config.yaml') as f:
    config = yaml.safe_load(f)
context_window = config['models']['local']['qwen_3_5_27b']['context_window']
# → 102400
```

**Shell (yq):**
```bash
yq eval '.models.local.qwen_3_5_27b.context_window' .opencode/deployment.config.yaml
# → 102400
```

**Conduct Modules (in shared/conduct/xx.md):**
```markdown
"Qwen 3.5-27B (context_window: 102K per .opencode/deployment.config.yaml)"
"Use port 1234 for LMStudio endpoint (per deployment.config.yaml)"
"VRAM: 16.8GB Q4_K_M (see deployment.config.yaml for full precision specs)"
```

#### Quick Reference

| Model | Port | Context | Framework | Tier | VRAM (Q4) |
|-------|------|---------|-----------|------|-----------|
| Qwen 3.5-27B | 1234 | 102K | LMStudio 0.14.13 | Sonnet | 16.8GB |
| Gamma 4-24B | 8001 | 16K | vLLM 0.21.0 | Haiku | 4GB |

#### Health Endpoints

- `http://localhost:1234/health` (LMStudio)
- `http://localhost:8001/health` (vLLM)

#### Models Endpoints

- `http://localhost:1234/v1/models` (list Qwen)
- `http://localhost:8001/v1/models` (list Gamma)

---

## When to Edit

Edit `deployment.config.yaml` when:
- Framework versions change (LMStudio, vLLM, Anthropic SDK)
- Model versions change (new Qwen, Gamma releases)
- Port assignments change
- VRAM specifications shift
- New models added to the network
- Orchestration roles updated

## Impact Zone

Changes here affect:
- ✓ `shared/scripts/inference-engine.py` (model references)
- ✓ `shared/conduct/*.md` (context window specs)
- ✓ `plugins/*/` (orchestration routing)
- ✓ `bootstrap.ps1`, `security-validate.py` (deployment validation)
- ✓ `preflight-checklist.py` (VRAM requirements)

## Versioning

- **v2.2.0** (2026-06-01) — Unified ports, expanded VRAM specs, wixie roles, SLA targets
- **v2.1.0** (2026-05-20) — Initial LMStudio/vLLM structure
- **v2.0.0** — Prior dual-model setup

---

See `deployment.config.yaml` for full documentation and all deployment details.
