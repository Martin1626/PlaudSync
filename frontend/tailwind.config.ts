// Tailwind 4 reads design tokens from CSS @theme directive in src/index.css.
// This file is retained for tooling that scans for tailwind.config.* (IDE plugins,
// linters); it intentionally exports an empty config.
import type { Config } from "tailwindcss";

export default {
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
} satisfies Config;
