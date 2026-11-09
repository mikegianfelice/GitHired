/**
 * Smoke / regression checks for the job-seeker homepage UX markup + match defaults.
 * Run: node --test tests/jobseek/test_public_site_ux.js
 */
"use strict";

const { describe, it } = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");

const root = path.join(__dirname, "..", "..");
const indexHtml = fs.readFileSync(path.join(root, "site", "index.html"), "utf8");
const appJs = fs.readFileSync(path.join(root, "site", "app.js"), "utf8");
const stylesCss = fs.readFileSync(path.join(root, "site", "styles.css"), "utf8");
const M = require(path.join(root, "site", "match-engine.js"));

describe("homepage UX markup", () => {
  it("is job-search-first without the large Built for Developers hero promo", () => {
    assert.doesNotMatch(indexHtml, /Built for Developers\. Accessible to AI\./);
    assert.match(indexHtml, /Building with GitHired\?/);
    assert.match(indexHtml, /id="dev-promo"/);
    assert.ok(indexHtml.indexOf('id="view-browse"') < indexHtml.indexOf('id="dev-promo"'));
  });

  it("groups developer destinations and keeps Matches reachable", () => {
    assert.match(indexHtml, /For Developers/);
    assert.match(indexHtml, /id="nav-dev-menu"/);
    assert.match(indexHtml, /aria-controls="nav-dev-menu"/);
    assert.match(indexHtml, /data-nav="match"/);
    assert.match(indexHtml, /id="menu-toggle"/);
    assert.match(indexHtml, /aria-controls="mobile-menu"/);
    assert.match(indexHtml, /class="[^"]*mobile-quick[^"]*"[^>]*data-nav="browse"/);
    assert.match(indexHtml, /class="[^"]*mobile-quick[^"]*"[^>]*data-nav="match"/);
  });

  it("uses advanced filters with salary presets and chips", () => {
    assert.match(indexHtml, /id="btn-all-filters"/);
    assert.match(indexHtml, /id="advanced-filters"/);
    assert.match(indexHtml, /data-salary="80000"/);
    assert.match(indexHtml, /data-salary="150000"/);
    assert.match(indexHtml, /id="filter-chips"/);
    assert.match(indexHtml, /id="include-undisclosed"/);
    assert.match(indexHtml, /id="btn-load-more"/);
    assert.match(indexHtml, /value="verified" selected/);
  });

  it("rewrites Find My Matches in plain language with privacy banner", () => {
    assert.match(indexHtml, /Find jobs that match your experience/);
    assert.match(indexHtml, /Your résumé stays in this browser/);
    assert.doesNotMatch(indexHtml, /Deterministic relevance scoring against the public shortlist/);
    assert.doesNotMatch(
      indexHtml.slice(indexHtml.indexOf('id="view-match"'), indexHtml.indexOf('id="dev-promo"')),
      /GitHired CLI/
    );
  });

  it("includes accessible live region and filter drawer backdrop", () => {
    assert.match(indexHtml, /id="live-region"/);
    assert.match(indexHtml, /aria-live="polite"/);
    assert.match(indexHtml, /id="filter-drawer-backdrop"/);
  });
});

describe("homepage UX behaviour contracts", () => {
  it("batches jobs twenty at a time", () => {
    assert.match(appJs, /const BATCH_SIZE = 20/);
    assert.match(appJs, /Load 20 more jobs|btn-load-more/);
    assert.match(appJs, /visibleCount/);
  });

  it("formats verified dates without claiming posting date", () => {
    assert.match(appJs, /Verified \$\{month\}/);
    assert.match(appJs, /not the original posting date/);
  });

  it("supports mobile filter drawer and reduced motion", () => {
    assert.match(stylesCss, /filters-open/);
    assert.match(stylesCss, /prefers-reduced-motion/);
    assert.match(stylesCss, /@media \(max-width: 767px\)/);
  });

  it("match engine default sort remains verified", () => {
    const jobs = [
      {
        title: "A",
        company: "Old",
        province: "ON",
        work_arrangement: "remote",
        seniority: "mid",
        salary_available: true,
        salary_min: 100000,
        salary_max: 200000,
        salary_currency: "CAD",
        salary_max_cad: 200000,
        technologies: [],
        last_verified: "2026-01-01",
        first_seen: "2026-01-01",
      },
      {
        title: "B",
        company: "New",
        province: "ON",
        work_arrangement: "remote",
        seniority: "mid",
        salary_available: true,
        salary_min: 80000,
        salary_max: 90000,
        salary_currency: "CAD",
        salary_max_cad: 90000,
        technologies: [],
        last_verified: "2026-11-09",
        first_seen: "2026-02-01",
      },
    ];
    const out = M.filterBrowseJobs(jobs, { minimum_salary_cad: 0 }, 1.35);
    assert.equal(out[0].job.company, "New");
  });
});
