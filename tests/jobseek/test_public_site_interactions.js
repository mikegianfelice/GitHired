/**
 * Regression tests for homepage interactions and pagination contracts.
 * Run: node --test tests/jobseek/test_public_site_interactions.js
 */
"use strict";

const { describe, it } = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const { pathToFileURL } = require("node:url");

const root = path.join(__dirname, "..", "..");
const indexHtml = fs.readFileSync(path.join(root, "site", "index.html"), "utf8");
const appJs = fs.readFileSync(path.join(root, "site", "app.js"), "utf8");
const stylesCss = fs.readFileSync(path.join(root, "site", "styles.css"), "utf8");

describe("interaction markup contracts", () => {
  it("wires All Filters, For Developers, and Load More controls", () => {
    assert.match(indexHtml, /id="btn-all-filters"/);
    assert.match(indexHtml, /id="advanced-filters"/);
    assert.match(indexHtml, /id="nav-dev-toggle"/);
    assert.match(indexHtml, /id="nav-dev-menu"/);
    assert.match(indexHtml, /id="btn-load-more"/);
    assert.match(indexHtml, /Load 20 More Jobs/);
    assert.match(indexHtml, /Developer API/);
    assert.match(indexHtml, /Connect an AI Agent/);
  });

  it("uses desktop-only primary nav and mobile hamburger menu", () => {
    assert.match(indexHtml, /class="header-nav desktop-nav"/);
    assert.match(indexHtml, /id="menu-toggle"/);
    assert.match(indexHtml, /id="mobile-menu"/);
    assert.doesNotMatch(indexHtml, /mobile-quick/);
    assert.match(stylesCss, /@media \(min-width: 768px\)/);
    assert.match(stylesCss, /\.desktop-nav\s*\{[^}]*display:\s*flex\s*!important/s);
    assert.match(stylesCss, /\.menu-toggle\s*\{[^}]*display:\s*none\s*!important/s);
  });

  it("keeps Browse Jobs and Find My Matches inside the mobile menu", () => {
    const mobileSlice = indexHtml.slice(
      indexHtml.indexOf('id="mobile-menu"'),
      indexHtml.indexOf("</header>")
    );
    assert.match(mobileSlice, /data-nav="browse"/);
    assert.match(mobileSlice, /data-nav="match"/);
    assert.match(mobileSlice, /Developer API/);
  });
});

describe("app.js interaction contracts", () => {
  it("null-guards UI binding and exposes toggle helpers", () => {
    assert.match(appJs, /function on\(el, type, handler/);
    assert.match(appJs, /function bindUi\(/);
    assert.match(appJs, /toggleAdvancedFilters/);
    assert.match(appJs, /toggleDevMenu/);
    assert.match(appJs, /toggleMobileMenu/);
    assert.match(appJs, /getRenderedCardCount/);
  });

  it("batches with INITIAL/LOAD sizes of 20 and Apply label", () => {
    assert.match(appJs, /const BATCH_SIZE = 20/);
    assert.match(appJs, /const LOAD_MORE_BATCH_SIZE = 20/);
    assert.match(appJs, />Apply</);
    assert.doesNotMatch(appJs, /Apply Directly/);
  });

  it("formats friendly snapshot metadata from generated_at", () => {
    assert.match(appJs, /formatSnapshotMeta/);
    assert.match(appJs, /Last updated/);
    assert.doesNotMatch(appJs, /client-side filters/);
  });
});

describe("formatSnapshotMeta behaviour", () => {
  it("renders count and local date without hardcoding today", async () => {
    // Load match-engine then evaluate formatSnapshotMeta via vm-less require of logic:
    // Re-implement the contract by importing through a tiny eval of the function source.
    const start = appJs.indexOf("function formatSnapshotMeta");
    const end = appJs.indexOf("function on(el, type, handler", start);
    assert.ok(start > 0 && end > start);
    // eslint-disable-next-line no-new-func
    const formatSnapshotMeta = new Function(`${appJs.slice(start, end)}; return formatSnapshotMeta;`)();
    const out = formatSnapshotMeta(358, "2026-11-09T14:02:44Z");
    assert.match(out, /358 verified Canadian tech jobs/);
    assert.match(out, /Last updated/);
    assert.doesNotMatch(out, /Snapshot 2026-11-09T14:02:44Z/);
    assert.doesNotMatch(out, /client-side/);
  });
});

describe("asset cache busting", () => {
  it("versions CSS and JS URLs so deploys are not sticky-cached", () => {
    assert.match(indexHtml, /styles\.css\?v=/);
    assert.match(indexHtml, /app\.js\?v=/);
    assert.match(indexHtml, /match-engine\.js\?v=/);
  });
});
