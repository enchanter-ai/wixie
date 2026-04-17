// Post-processor: inject an engineering-blueprint background into a Mermaid SVG.
//
// Why: Mermaid can't draw a grid pattern. We render the diagram normally, then
// overlay a navy background + subtle grid beneath the content so the result
// reads as a blueprint/CAD drawing rather than a neutral dark card.
//
// Usage:
//   node apply-blueprint.js path/to/diagram.svg [path/to/another.svg ...]

const fs = require("fs");
const path = require("path");

const BG = "#0a1628";          // deep navy "blueprint paper"
const MAJOR = "#1e3a5f";       // major grid, every 40 units
const MINOR = "#16304f";       // minor grid, every 10 units
const MAJOR_W = 0.75;
const MINOR_W = 0.35;
const MAJOR_OP = 0.55;
const MINOR_OP = 0.35;

function blueprint(svgPath) {
  let svg = fs.readFileSync(svgPath, "utf8");

  const vbMatch = svg.match(/viewBox="([^"]+)"/);
  if (!vbMatch) {
    throw new Error(`${svgPath}: no viewBox attribute`);
  }
  const [vx, vy, vw, vh] = vbMatch[1].trim().split(/\s+/).map(Number);

  // Replace the mermaid-inlined white/neutral bg with navy.
  svg = svg.replace(
    /background-color:\s*(?:rgb\([^)]+\)|#[0-9a-fA-F]+)/,
    `background-color: ${BG}`
  );

  // Pattern: major 40-unit grid + finer 10-unit sub-grid.
  const defs = `<defs><pattern id="bp-grid" x="${vx}" y="${vy}" width="40" height="40" patternUnits="userSpaceOnUse"><path d="M 10 0 L 10 40 M 20 0 L 20 40 M 30 0 L 30 40 M 0 10 L 40 10 M 0 20 L 40 20 M 0 30 L 40 30" fill="none" stroke="${MINOR}" stroke-width="${MINOR_W}" opacity="${MINOR_OP}"/><path d="M 40 0 L 0 0 L 0 40" fill="none" stroke="${MAJOR}" stroke-width="${MAJOR_W}" opacity="${MAJOR_OP}"/></pattern></defs>`;

  // Solid navy base + grid overlay, both sized to the viewBox so they cover the
  // full drawable area regardless of the mermaid layout.
  const bg = `<rect x="${vx}" y="${vy}" width="${vw}" height="${vh}" fill="${BG}"/><rect x="${vx}" y="${vy}" width="${vw}" height="${vh}" fill="url(#bp-grid)"/>`;

  // Inject defs+bg immediately after the opening <svg ...> tag so they paint
  // behind the diagram content.
  svg = svg.replace(/(<svg[^>]*>)/, `$1${defs}${bg}`);

  fs.writeFileSync(svgPath, svg, "utf8");
  console.log(`  blueprinted ${path.relative(process.cwd(), svgPath)}`);
}

const targets = process.argv.slice(2);
if (targets.length === 0) {
  console.error("usage: node apply-blueprint.js <svg> [<svg> ...]");
  process.exit(1);
}
for (const t of targets) blueprint(t);
