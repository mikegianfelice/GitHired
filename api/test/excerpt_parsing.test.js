import assert from "node:assert";
import { test } from "node:test";

function ghApiUrl(url) {
  const m = url.match(/greenhouse\.io\/([^/]+)\/jobs\/(\d+)/i);
  if (!m) return null;
  return `https://boards-api.greenhouse.io/v1/boards/${m[1]}/jobs/${m[2]}?content=true`;
}

function leverApiUrl(url) {
  const m = url.match(/jobs\.lever\.co\/([^/]+)\/([A-Za-z0-9-]+)(?:\/|$)/i);
  if (!m) return null;
  return `https://api.lever.co/v0/postings/${m[1]}/${m[2]}?expand=true`;
}

function ashbyBoardAndId(url) {
  const m = url.match(/jobs\.ashbyhq\.com\/([^/]+)\/([A-Za-z0-9-]+)/i);
  if (!m) return null;
  return { board: m[1], id: m[2] };
}

function workableApiUrl(url) {
  const m = url.match(/apply\.workable\.com\/(?:[^/]+\/)?j\/([A-Z0-9]+)/i);
  if (!m) return null;
  return `https://apply.workable.com/api/v1/widget/jobs/${m[1]}`;
}

function smartRecruitersApiUrl(url) {
  const api = url.match(/api\.smartrecruiters\.com\/v1\/companies\/([^/]+)\/postings\/([^/?#]+)/i);
  if (api) return `https://api.smartrecruiters.com/v1/companies/${api[1]}/postings/${api[2]}`;
  const web = url.match(/jobs\.smartrecruiters\.com\/([^/]+)\/([^/?#]+)/i);
  if (web) return `https://api.smartrecruiters.com/v1/companies/${web[1]}/postings/${web[2]}`;
  return null;
}

test("greenhouse parsing builds API URL", () => {
  const u = "https://job-boards.greenhouse.io/affirm/jobs/8205742003";
  const api = ghApiUrl(u);
  assert.ok(api?.includes("/v1/boards/affirm/jobs/8205742003"));
});

test("lever parsing builds API URL", () => {
  const u = "https://jobs.lever.co/exampleco/abcd-1234/apply";
  const api = leverApiUrl(u);
  assert.ok(api?.includes("/v0/postings/exampleco/abcd-1234"));
});

test("ashby parsing extracts board and id", () => {
  const u = "https://jobs.ashbyhq.com/acme/123e4567-e89b-12d3-a456-426614174000";
  const got = ashbyBoardAndId(u);
  assert.deepEqual(got, { board: "acme", id: "123e4567-e89b-12d3-a456-426614174000" });
});

test("workable parsing builds API URL", () => {
  const u = "https://apply.workable.com/j/EFAAA98160/";
  const api = workableApiUrl(u);
  assert.ok(api?.endsWith("/api/v1/widget/jobs/EFAAA98160"));
});

test("smartrecruiters parsing covers api and web forms", () => {
  const apiForm = "https://api.smartrecruiters.com/v1/companies/myco/postings/12345";
  const webForm = "https://jobs.smartrecruiters.com/myco/12345-something";
  const a = smartRecruitersApiUrl(apiForm);
  const b = smartRecruitersApiUrl(webForm);
  assert.ok(a?.includes("/v1/companies/myco/postings/12345"));
  assert.ok(b?.includes("/v1/companies/myco/postings/12345"));
});

