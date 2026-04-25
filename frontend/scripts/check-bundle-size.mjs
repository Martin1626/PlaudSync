// Fail-soft bundle size check. Walks dist/assets/, sums gzipped size, warns if
// over budget. Exits 0 either way — CI gating is a future concern.
import { gzipSync } from "node:zlib";
import { readFileSync, readdirSync, statSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const __dirname = dirname(fileURLToPath(import.meta.url));
const DIST = join(__dirname, "..", "dist");
const BUDGET_KB = 200; // Umbrella spec AC #4. W-U2 watch threshold 500.

function* walk(dir) {
  for (const entry of readdirSync(dir)) {
    const p = join(dir, entry);
    const s = statSync(p);
    if (s.isDirectory()) yield* walk(p);
    else if (/\.(js|css|html)$/.test(entry)) yield p;
  }
}

let totalGzip = 0;
const sizes = [];
for (const p of walk(DIST)) {
  const buf = readFileSync(p);
  const gz = gzipSync(buf).length;
  totalGzip += gz;
  sizes.push({ path: p.replace(DIST + "/", "").replace(DIST + "\\", ""), gz });
}
sizes.sort((a, b) => b.gz - a.gz);
const totalKB = (totalGzip / 1024).toFixed(1);
console.log(`\n[bundle-size] total gzip: ${totalKB} KB (budget ${BUDGET_KB} KB)`);
console.log("[bundle-size] top contributors:");
for (const s of sizes.slice(0, 8)) {
  console.log(`  ${(s.gz / 1024).toFixed(1).padStart(7)} KB  ${s.path}`);
}
if (totalGzip / 1024 > BUDGET_KB) {
  console.warn(
    `[bundle-size] WARNING: bundle exceeds ${BUDGET_KB} KB budget. W-U2 threshold is 500 KB; investigate.`,
  );
}
