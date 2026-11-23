import { readFileSync } from "node:fs";
import { join } from "node:path";

const root = new URL("..", import.meta.url);
const snapshot = JSON.parse(readFileSync(join(root.pathname, "data/jobs.snapshot.json"), "utf8"));

function tokens(text) {
  return String(text || "")
    .toLowerCase()
    .split(/[^a-z0-9+#.]+/i)
    .filter((t) => t.length >= 2);
}
function hasToken(hay, token) {
  const parts = tokens(hay);
  return parts.includes(String(token || "").toLowerCase());
}
function haystack(job) {
  return [
    job.title,
    job.company,
    job.location,
    job.province || "",
    job.track || "",
    job.seniority || "",
    (job.technologies || []).join(" "),
    job.description_excerpt || "",
  ]
    .join(" ")
    .toLowerCase();
}
function legacyMatches(job, q, loc, min) {
  if (min != null) {
    const cur = (job.salary_currency || "").toUpperCase();
    let hi = job.salary_max_cad != null ? job.salary_max_cad : null;
    if (hi == null && job.salary_max != null) {
      if (cur === "CAD") hi = job.salary_max;
      else if (cur === "USD") hi = job.salary_max * (snapshot.usd_to_cad || 1.35);
    }
    if (hi == null || hi < min) return false;
  }
  if (loc && !(String(job.location) + " " + (job.province || "")).toLowerCase().includes(String(loc).toLowerCase())) return false;
  if (q) {
    const all = tokens(q);
    const h = haystack(job);
    const hits = all.filter((t) => hasToken(h, t) || hasToken(job.title, t)).length;
    if (hits < all.length) return false;
  }
  return true;
}
function strictMatches(job, q, loc, min) {
  if (min != null) {
    const cur = (job.salary_currency || "").toUpperCase();
    let hi = job.salary_max_cad != null ? job.salary_max_cad : null;
    if (hi == null && job.salary_max != null) {
      if (cur === "CAD") hi = job.salary_max;
      else if (cur === "USD") hi = job.salary_max * (snapshot.usd_to_cad || 1.35);
    }
    if (hi == null || hi < min) return false;
  }
  if (loc && !(String(job.location) + " " + (job.province || "")).toLowerCase().includes(String(loc).toLowerCase())) return false;
  if (q) {
    const all = tokens(q);
    const fields = [
      job.title || "",
      job.company || "",
      job.location || "",
      job.province || "",
      job.track || "",
      job.seniority || "",
      (job.technologies || []).join(" "),
    ].map((s) => s.toLowerCase());
    const ok = all.every((t) => fields.some((f) => hasToken(f, t)));
    if (!ok) return false;
  }
  return true;
}

const q = "senior data engineer";
const loc = "Toronto";
const min = 120000;
const all = snapshot.jobs.filter((j) => j.verified);
const before = all.filter((j) => legacyMatches(j, q, loc, min));
const after = all.filter((j) => strictMatches(j, q, loc, min));
function isDataEngTitle(title) {
  const t = String(title || "").toLowerCase();
  return /\bdata\b/.test(t) && /\bengineer/.test(t);
}
const beforeTitleHits = before.filter((j) => isDataEngTitle(j.title)).length;
const afterTitleHits = after.filter((j) => isDataEngTitle(j.title)).length;

// Province filter acceptance
function countProvinceEq(p) {
  const code = typeof p === "string" && p.length > 2 ? "ON" : String(p || "").toUpperCase();
  return snapshot.jobs.filter((j) => String(j.province || "").toUpperCase() === code).length;
}
const onCount = countProvinceEq("ON");
const ontarioCount = countProvinceEq("Ontario");
const onLowerCount = countProvinceEq("on");

// Null province share in bundled snapshot
const nullProv = snapshot.jobs.filter((j) => !j.province).length;

console.log(JSON.stringify({
  dataset_id: snapshot.dataset_id,
  total: snapshot.jobs.length,
  search: { q, loc, min, before_total: before.length, before_title_hits: beforeTitleHits, after_total: after.length, after_title_hits: afterTitleHits },
  province_counts: { ON: onCount, Ontario: ontarioCount, on: onLowerCount },
  null_province_share: { count: nullProv, percent: Math.round((nullProv / snapshot.jobs.length) * 1000) / 10 },
}, null, 2));
