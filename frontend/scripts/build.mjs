#!/usr/bin/env node
/**
 * Full static-site build: assembles a deployable copy of the frontend in
 * `dist/`, compiles Tailwind into it, and bakes the API base URL into its
 * HTML only.
 *
 * WHY a separate dist/ instead of building in place: the source HTML files
 * are committed with the literal placeholder `{{API_BASE_URL}}` (see
 * js/config.js, which reads it from a <meta name="jobhub:api-base"> tag) so
 * the exact same source works for local dev, a Railway preview, and
 * production — each just sets API_BASE_URL differently before building.
 * Substituting that placeholder in place, in the tracked source files, would
 * dirty the git working tree on every local build and bake whichever
 * environment last ran the build into what the next `git diff` shows. Baking
 * it only into a gitignored dist/ output keeps the source environment-agnostic
 * and the build reproducible.
 *
 * `serve.json` (cleanUrls: false — see its own comment) travels into dist/
 * too since `serve` reads it from its own working directory.
 */
import { cpSync, rmSync, mkdirSync, readdirSync, readFileSync, writeFileSync, existsSync } from "node:fs";
import { join, dirname } from "node:path";
import { fileURLToPath } from "node:url";
import { execFileSync } from "node:child_process";

const root = join(dirname(fileURLToPath(import.meta.url)), "..");
const dist = join(root, "dist");

rmSync(dist, { recursive: true, force: true });
mkdirSync(dist, { recursive: true });

const htmlFiles = readdirSync(root).filter((f) => f.endsWith(".html"));
for (const entry of ["js", "serve.json", ...htmlFiles]) {
  const from = join(root, entry);
  if (existsSync(from)) cpSync(from, join(dist, entry), { recursive: true });
}

// Tailwind compiles straight into dist/css — css/input.css itself is a build
// input only, nothing references it directly, so it doesn't need copying.
mkdirSync(join(dist, "css"), { recursive: true });
execFileSync(
  "npx",
  ["tailwindcss", "-i", "./css/input.css", "-o", "./dist/css/tailwind.css", "--minify"],
  { cwd: root, stdio: "inherit" },
);

// Bake API_BASE_URL into dist's HTML only. Defaults to the no-Docker local
// dev API port so a plain `npm run build` with no env vars still matches the
// existing local dev workflow.
const apiBase = (process.env.API_BASE_URL || "http://localhost:8000").replace(/\/+$/, "");
let patched = 0;
for (const file of htmlFiles) {
  const path = join(dist, file);
  const html = readFileSync(path, "utf8");
  const next = html.replaceAll("{{API_BASE_URL}}", apiBase);
  if (next !== html) {
    writeFileSync(path, next);
    patched += 1;
  }
}

console.log(`build: dist/ ready — API_BASE_URL=${apiBase} baked into ${patched} page(s)`);
