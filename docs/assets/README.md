# docs/assets — rendered diagrams & equations

These SVGs are **pre-rendered** so GitHub's mobile app (which renders neither
` ```mermaid ` blocks nor `$$...$$` math) shows them correctly. README.md and
docs/science/README.md reference the files here as `<img>`.

## Files

| File | Source | Regenerate |
|------|--------|-----------|
| `pipeline.svg` | `pipeline.mmd` | `npx @mermaid-js/mermaid-cli -i pipeline.mmd -o pipeline.svg -c mermaid.config.json -b "#0a1628" -w 1400 && node apply-blueprint.js pipeline.svg` |
| `lifecycle.svg` | `lifecycle.mmd` | `npx @mermaid-js/mermaid-cli -i lifecycle.mmd -o lifecycle.svg -c mermaid.config.json -b "#0a1628" -w 1400 && node apply-blueprint.js lifecycle.svg` |
| `math/*.svg` | `render-math.js` | `npm install --prefix . mathjax-full && node render-math.js` |

The `apply-blueprint.js` step overlays an engineering-blueprint grid (navy `#0a1628` paper, `#1e3a5f` major lines / `#16304f` minor lines) onto the rendered diagram so it reads as a CAD drawing rather than a neutral dark card.

Run the commands from `docs/assets/` (paths are relative). The toolchain
(`node_modules/`, `package.json`, `package-lock.json`) is gitignored; only the
rendered SVGs and source files are committed.
