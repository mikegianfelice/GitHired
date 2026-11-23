/**
 * REST search filter validation (esbuild-bundled TypeScript).
 * Run: npm test (from api/)
 */
import assert from "node:assert/strict";
import { spawnSync } from "node:child_process";
import { mkdirSync } from "node:fs";
import { dirname, join } from "node:path";
import { test, before } from "node:test";
import { fileURLToPath, pathToFileURL } from "node:url";

const __dirname = dirname(fileURLToPath(import.meta.url));
const root = join(__dirname, "..");
const bundlePath = join(root, "test/.cache/search.bundle.mjs");

let parseSearchFilters;
let SearchFilterValidationError;

before(async () => {
  mkdirSync(dirname(bundlePath), { recursive: true });
  const build = spawnSync(
    "npx",
    [
      "--yes",
      "esbuild",
      "src/search.ts",
      "--bundle",
      "--platform=neutral",
      "--format=esm",
      `--outfile=${bundlePath}`,
    ],
    { cwd: root, encoding: "utf8" },
  );
  if (build.status !== 0) {
    throw new Error(`esbuild failed: ${build.stderr || build.stdout}`);
  }
  const mod = await import(pathToFileURL(bundlePath).href + `?t=${Date.now()}`);
  parseSearchFilters = mod.parseSearchFilters;
  SearchFilterValidationError = mod.SearchFilterValidationError;
});

test("invalid work_mode=telepathy raises SearchFilterValidationError", () => {
  assert.throws(
    () => parseSearchFilters(new URLSearchParams("work_mode=telepathy")),
    (err) =>
      err instanceof SearchFilterValidationError &&
      err.code === "invalid_work_mode" &&
      /telepathy/i.test(err.message),
  );
});

test("valid work_mode values remain accepted", () => {
  for (const mode of ["remote", "hybrid", "onsite", "REMOTE"]) {
    const filters = parseSearchFilters(new URLSearchParams(`work_mode=${mode}`));
    assert.equal(filters.work_mode, mode.toLowerCase());
  }
});

test("omitted work_mode stays undefined (backward compatible)", () => {
  const filters = parseSearchFilters(new URLSearchParams("q=engineer"));
  assert.equal(filters.work_mode, undefined);
  assert.equal(filters.q, "engineer");
});

test("province accepts codes and full names case-insensitively; invalid raises", () => {
  // Codes
  let f = parseSearchFilters(new URLSearchParams("province=ON"));
  assert.equal(f.province, "ON");
  f = parseSearchFilters(new URLSearchParams("province=on"));
  assert.equal(f.province, "ON");
  // Full names
  f = parseSearchFilters(new URLSearchParams("province=Ontario"));
  assert.equal(f.province, "ON");
  f = parseSearchFilters(new URLSearchParams("province=ontario"));
  assert.equal(f.province, "ON");
  // Invalid
  assert.throws(
    () => parseSearchFilters(new URLSearchParams("province=Ontarionnn")),
    (err) => err instanceof SearchFilterValidationError && err.code === "invalid_province",
  );
});

test("seniority normalizes aliases and validates values", () => {
  let f = parseSearchFilters(new URLSearchParams("seniority=sr"));
  assert.equal(f.seniority, "senior");
  f = parseSearchFilters(new URLSearchParams("seniority=Senior"));
  assert.equal(f.seniority, "senior");
  assert.throws(
    () => parseSearchFilters(new URLSearchParams("seniority=wizard")),
    (err) => err instanceof SearchFilterValidationError && err.code === "invalid_seniority",
  );
});
