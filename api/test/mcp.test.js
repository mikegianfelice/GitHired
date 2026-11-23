import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { test } from "node:test";
import { fileURLToPath } from "node:url";

const __dirname = dirname(fileURLToPath(import.meta.url));
const root = join(__dirname, "..");
const mcpSrc = readFileSync(join(root, "src/mcp.ts"), "utf8");
const indexSrc = readFileSync(join(root, "src/index.ts"), "utf8");

test("MCP route is wired on /mcp", () => {
  assert.match(indexSrc, /pathname === ["']\/mcp["']/);
  assert.match(indexSrc, /handleMcp/);
});

test("MCP implements required JSON-RPC methods", () => {
  for (const method of [
    "initialize",
    "tools/list",
    "tools/call",
    "ping",
    "resources/list",
    "prompts/list",
  ]) {
    assert.match(mcpSrc, new RegExp(`method === ["']${method.replace("/", "\\/")}["']`));
  }
  assert.match(mcpSrc, /PROTOCOL_VERSION\s*=\s*["']2024-11-05["']/);
});

test("MCP exposes documented tools", () => {
  for (const name of ["search_jobs", "get_job", "match_profile", "get_market_stats", "list_companies"]) {
    assert.match(mcpSrc, new RegExp(`name:\\s*["']${name}["']`));
  }
});

test("MCP tools declare directory-required annotations", () => {
  assert.match(mcpSrc, /readOnlyHint:\s*true/);
  assert.match(mcpSrc, /destructiveHint:\s*false/);
  assert.match(mcpSrc, /openWorldHint:\s*true/);
  assert.match(mcpSrc, /idempotentHint:\s*true/);
  assert.match(mcpSrc, /annotations:\s*READ_ONLY_OPEN_WORLD/);
});

test("MCP notifications return 202 instead of Internal error", () => {
  // Cursor (and other Streamable HTTP clients) send notifications/initialized with no id.
  assert.match(mcpSrc, /acceptedResponse/);
  assert.match(mcpSrc, /responses\.length === 0\) return acceptedResponse\(\)/);
});

test("MCP minimum_salary ignores non-positive values", () => {
  assert.match(mcpSrc, /args\.minimum_salary > 0/);
});

const restSrc = readFileSync(join(root, "src/rest.ts"), "utf8");
test("REST exports acceptedResponse for MCP notifications", () => {
  assert.match(restSrc, /export function acceptedResponse/);
  assert.match(restSrc, /status:\s*202/);
});

test("snapshot ClickHouse Control Plane is not US-only labeled", () => {
  const snapshot = JSON.parse(readFileSync(join(root, "data/jobs.snapshot.json"), "utf8"));
  const hit = snapshot.jobs.find(
    (j) => j.company === "ClickHouse" && String(j.title).includes("Control Plane"),
  );
  if (!hit) {
    // Dataset may rotate; protocol/tool surface still covered above.
    return;
  }
  assert.match(String(hit.location), /canada/i);
  assert.notEqual(String(hit.location).toLowerCase().trim(), "united states (remote)");
  assert.equal(hit.remote_scope, "canada");
});
