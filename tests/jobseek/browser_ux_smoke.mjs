/**
 * Real-browser smoke for GitHired homepage interactions.
 * Usage:
 *   npx --yes playwright@1.49.1 install chromium
 *   node tests/jobseek/browser_ux_smoke.mjs [baseUrl]
 */
import { createServer } from "node:http";
import { readFile } from "node:fs/promises";
import path from "node:path";
import { fileURLToPath } from "node:url";
import assert from "node:assert/strict";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const siteRoot = path.join(__dirname, "..", "..", "site");
const requested = process.argv[2];

async function startStaticServer() {
  const types = {
    ".html": "text/html; charset=utf-8",
    ".js": "text/javascript; charset=utf-8",
    ".css": "text/css; charset=utf-8",
    ".json": "application/json",
    ".svg": "image/svg+xml",
  };
  const server = createServer(async (req, res) => {
    try {
      let urlPath = decodeURIComponent((req.url || "/").split("?")[0]);
      if (urlPath === "/") urlPath = "/index.html";
      const filePath = path.join(siteRoot, urlPath.replace(/^\//, ""));
      if (!filePath.startsWith(siteRoot)) {
        res.writeHead(403);
        res.end("forbidden");
        return;
      }
      const body = await readFile(filePath);
      res.writeHead(200, { "content-type": types[path.extname(filePath)] || "application/octet-stream" });
      res.end(body);
    } catch {
      res.writeHead(404);
      res.end("not found");
    }
  });
  await new Promise((resolve) => server.listen(0, "127.0.0.1", resolve));
  const { port } = server.address();
  return { server, baseUrl: `http://127.0.0.1:${port}` };
}

async function main() {
  let playwright;
  try {
    playwright = await import("playwright");
  } catch {
    console.error("Playwright is not installed. Run: npm i -D playwright && npx playwright install chromium");
    process.exit(2);
  }

  let server;
  let baseUrl = requested;
  if (!baseUrl) {
    ({ server, baseUrl } = await startStaticServer());
  }

  const browser = await playwright.chromium.launch({ headless: true });
  const page = await browser.newPage({ viewport: { width: 1366, height: 768 } });
  const failures = [];

  try {
    await page.goto(baseUrl, { waitUntil: "networkidle" });
    await page.waitForFunction(() => window.GitHiredPublic && window.GitHiredPublic.getRenderedCardCount() > 0);

    const initialCards = await page.evaluate(() => window.GitHiredPublic.getRenderedCardCount());
    assert.equal(initialCards, 20, `expected 20 cards, got ${initialCards}`);

    // All Filters toggle
    await page.click("#btn-all-filters");
    const filtersOpen = await page.evaluate(() => ({
      expanded: document.getElementById("btn-all-filters").getAttribute("aria-expanded"),
      open: document.getElementById("advanced-filters").classList.contains("is-open"),
      hidden: document.getElementById("advanced-filters").hidden,
    }));
    assert.equal(filtersOpen.expanded, "true");
    assert.equal(filtersOpen.open, true);
    assert.equal(filtersOpen.hidden, false);

    await page.click("#btn-all-filters");
    const filtersClosed = await page.evaluate(
      () => document.getElementById("btn-all-filters").getAttribute("aria-expanded")
    );
    assert.equal(filtersClosed, "false");

    // For Developers menu
    await page.click("#nav-dev-toggle");
    const dev = await page.evaluate(() => ({
      expanded: document.getElementById("nav-dev-toggle").getAttribute("aria-expanded"),
      open: document.getElementById("nav-dev-menu").classList.contains("is-open"),
      links: [...document.querySelectorAll("#nav-dev-menu a")].map((a) => a.textContent.trim()),
    }));
    assert.equal(dev.expanded, "true");
    assert.equal(dev.open, true);
    assert.deepEqual(dev.links, ["Developer API", "Connect an AI Agent", "GitHub"]);

    // Load more 20 -> 40
    await page.click("#btn-load-more");
    const afterLoad = await page.evaluate(() => ({
      cards: window.GitHiredPublic.getRenderedCardCount(),
      showing: document.getElementById("showing-count").textContent,
    }));
    assert.equal(afterLoad.cards, 40);
    assert.match(afterLoad.showing, /Showing 40 of \d+ jobs/);

    // Apply button text
    const applyText = await page.locator(".apply-btn").first().textContent();
    assert.equal(applyText.trim(), "Apply");

    // Snapshot copy
    const meta = await page.locator("#snapshot-meta").textContent();
    assert.match(meta, /verified Canadian tech jobs/);
    assert.doesNotMatch(meta, /Snapshot 20\d{2}-/);

    // Desktop nav visibility
    const desktopNav = await page.evaluate(() => ({
      desktop: getComputedStyle(document.querySelector(".desktop-nav")).display,
      hamburger: getComputedStyle(document.getElementById("menu-toggle")).display,
    }));
    assert.notEqual(desktopNav.desktop, "none");
    assert.equal(desktopNav.hamburger, "none");

    // Mobile viewport
    await page.setViewportSize({ width: 390, height: 844 });
    const mobileNav = await page.evaluate(() => ({
      desktop: getComputedStyle(document.querySelector(".desktop-nav")).display,
      hamburger: getComputedStyle(document.getElementById("menu-toggle")).display,
    }));
    assert.equal(mobileNav.desktop, "none");
    assert.notEqual(mobileNav.hamburger, "none");

    await page.click("#menu-toggle");
    const menuOpen = await page.evaluate(() => ({
      expanded: document.getElementById("menu-toggle").getAttribute("aria-expanded"),
      open: document.getElementById("mobile-menu").classList.contains("is-open"),
    }));
    assert.equal(menuOpen.expanded, "true");
    assert.equal(menuOpen.open, true);

    // Filter reset batch
    await page.setViewportSize({ width: 1366, height: 768 });
    await page.fill("#search", "zzzz-no-match-xxxxx");
    await page.waitForTimeout(50);
    const empty = await page.evaluate(() => ({
      cards: window.GitHiredPublic.getRenderedCardCount(),
      emptyHidden: document.getElementById("empty-state").hidden,
    }));
    assert.equal(empty.cards, 0);
    assert.equal(empty.emptyHidden, false);

    await page.fill("#search", "");
    await page.waitForTimeout(50);
    const reset = await page.evaluate(() => window.GitHiredPublic.getRenderedCardCount());
    assert.equal(reset, 20);

    console.log("browser_ux_smoke: PASS");
  } catch (err) {
    failures.push(err);
    console.error("browser_ux_smoke: FAIL", err);
  } finally {
    await browser.close();
    if (server) server.close();
  }

  if (failures.length) process.exit(1);
}

main();
