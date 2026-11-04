/**
 * Privacy / validation helpers for local résumé parsing.
 * Run: node --test tests/jobseek/test_resume_privacy.js
 */
"use strict";

const { describe, it } = require("node:test");
const assert = require("node:assert/strict");
const path = require("node:path");
const fs = require("node:fs");

const R = require(path.join(__dirname, "..", "..", "site", "resume.js"));

describe("resume privacy helpers", () => {
  it("exposes privacy notice", () => {
    assert.match(R.PRIVACY_NOTICE, /browser/i);
    assert.match(R.PRIVACY_NOTICE, /don'?t upload/i);
  });

  it("rejects oversized files", () => {
    assert.throws(
      () => R.assertSize({ size: R.MAX_BYTES + 1, name: "big.pdf" }),
      /5 MB/
    );
  });

  it("accepts files at the limit", () => {
    assert.doesNotThrow(() => R.assertSize({ size: R.MAX_BYTES, name: "ok.txt" }));
  });

  it("app does not auto-write localStorage on load", () => {
    const app = fs.readFileSync(path.join(__dirname, "..", "..", "site", "app.js"), "utf8");
    assert.match(app, /btn-save-profile/);
    assert.match(app, /localStorage\.setItem/);
    // save only inside saveProfile called from explicit button
    assert.match(app, /function saveProfile/);
    assert.ok(!/boot\(\)[\s\S]{0,800}saveProfile\(/.test(app));
  });

  it("public jobs.json has no résumé/profile fields", () => {
    const data = JSON.parse(
      fs.readFileSync(path.join(__dirname, "..", "..", "site", "jobs.json"), "utf8")
    );
    const blob = JSON.stringify(data);
    assert.ok(!/"resume"\s*:/.test(blob));
    assert.ok(!/"cv_path"\s*:/.test(blob));
    assert.ok(!/"email"\s*:/.test(blob));
    assert.equal(data.schema_version, 2);
    assert.ok("usd_to_cad" in data);
  });
});
