// Copy Vite build output to ../src/plaudsync/ui/static/ so FastAPI StaticFiles
// can mount it. Idempotent: rms target dir before copy.
import { copyFileSync, mkdirSync, readdirSync, rmSync, statSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const __dirname = dirname(fileURLToPath(import.meta.url));
const SOURCE = join(__dirname, "..", "dist");
const TARGET = join(__dirname, "..", "..", "src", "plaudsync", "ui", "static");

function copyRecursive(src, dest) {
  const stat = statSync(src);
  if (stat.isDirectory()) {
    mkdirSync(dest, { recursive: true });
    for (const entry of readdirSync(src)) {
      copyRecursive(join(src, entry), join(dest, entry));
    }
  } else {
    copyFileSync(src, dest);
  }
}

console.log(`[postbuild] cleaning ${TARGET}`);
rmSync(TARGET, { recursive: true, force: true });
mkdirSync(TARGET, { recursive: true });

console.log(`[postbuild] copying ${SOURCE} -> ${TARGET}`);
copyRecursive(SOURCE, TARGET);

console.log("[postbuild] done.");
