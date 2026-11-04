(() => {
  "use strict";

  const BASE = (() => {
    const path = window.location.pathname || "/";
    if (path.endsWith("/")) return path;
    if (path.endsWith(".html")) return path.slice(0, path.lastIndexOf("/") + 1);
    return path.endsWith("/") ? path : `${path}/`;
  })();

  const els = {
    meta: document.getElementById("snapshot-meta"),
    list: document.getElementById("job-list"),
    empty: document.getElementById("empty-state"),
    error: document.getElementById("error-state"),
    count: document.getElementById("result-count"),
    search: document.getElementById("search"),
    province: document.getElementById("filter-province"),
    arrangement: document.getElementById("filter-arrangement"),
    seniority: document.getElementById("filter-seniority"),
    salary: document.getElementById("filter-salary"),
  };

  /** @type {any[]} */
  let jobs = [];

  function assetUrl(name) {
    return new URL(name, window.location.href).toString();
  }

  function escapeHtml(text) {
    return String(text)
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;");
  }

  function formatSalary(job) {
    if (!job.salary_available || job.salary_min == null || job.salary_max == null) {
      return null;
    }
    const cur = job.salary_currency || "";
    const lo = Math.round(Number(job.salary_min)).toLocaleString("en-CA");
    const hi = Math.round(Number(job.salary_max)).toLocaleString("en-CA");
    return lo === hi ? `${cur} ${lo}` : `${cur} ${lo}–${hi}`;
  }

  function arrangementLabel(job) {
    const a = job.work_arrangement || "unspecified";
    if (a === "remote" && job.remote_scope === "province") {
      return "Remote (province)";
    }
    if (a === "remote" && job.remote_scope === "canada") {
      return "Remote (Canada)";
    }
    if (a === "onsite") return "On-site";
    if (a === "hybrid") return "Hybrid";
    if (a === "remote") return "Remote";
    return "Arrangement unspecified";
  }

  function freshnessLabel(job) {
    if (job.discovered_today && job.first_seen) {
      return "Discovered today";
    }
    return job.last_verified ? `Verified ${job.last_verified}` : "Verified";
  }

  function fillSelect(select, values, placeholder) {
    const current = select.value;
    select.innerHTML = "";
    const all = document.createElement("option");
    all.value = "";
    all.textContent = placeholder;
    select.appendChild(all);
    for (const value of values) {
      const opt = document.createElement("option");
      opt.value = value;
      opt.textContent = value;
      select.appendChild(opt);
    }
    if ([...select.options].some((o) => o.value === current)) {
      select.value = current;
    }
  }

  function populateFilters(data) {
    const provinces = [...new Set(data.map((j) => j.province).filter(Boolean))].sort();
    const seniorities = [...new Set(data.map((j) => j.seniority).filter(Boolean))].sort();
    fillSelect(els.province, provinces, "All");
    fillSelect(els.seniority, seniorities, "All");
  }

  function matches(job, query) {
    if (!query) return true;
    const hay = [
      job.title,
      job.company,
      job.location,
      ...(job.technologies || []),
      job.track || "",
    ]
      .join(" ")
      .toLowerCase();
    return query
      .toLowerCase()
      .split(/\s+/)
      .filter(Boolean)
      .every((token) => hay.includes(token));
  }

  function filteredJobs() {
    const q = els.search.value.trim();
    const province = els.province.value;
    const arrangement = els.arrangement.value;
    const seniority = els.seniority.value;
    const salary = els.salary.value;
    return jobs.filter((job) => {
      if (!matches(job, q)) return false;
      if (province && job.province !== province) return false;
      if (arrangement && job.work_arrangement !== arrangement) return false;
      if (seniority && job.seniority !== seniority) return false;
      if (salary === "listed" && !job.salary_available) return false;
      if (salary === "hidden" && job.salary_available) return false;
      return true;
    });
  }

  function render() {
    const visible = filteredJobs();
    els.count.textContent = `${visible.length} job${visible.length === 1 ? "" : "s"} shown`;
    els.list.innerHTML = "";
    els.empty.hidden = visible.length > 0;
    for (const job of visible) {
      const salary = formatSalary(job);
      const tech = (job.technologies || []).slice(0, 4);
      const card = document.createElement("article");
      card.className = "job-card";
      card.innerHTML = `
        <div class="job-card-top">
          <div>
            <p class="job-company">${escapeHtml(job.company)}</p>
            <h2 class="job-title">${escapeHtml(job.title)}</h2>
          </div>
          <span class="freshness">${escapeHtml(freshnessLabel(job))}</span>
        </div>
        <div class="job-meta">
          <span class="pill">${escapeHtml(job.location || "Canada")}</span>
          <span class="pill">${escapeHtml(arrangementLabel(job))}</span>
          ${job.seniority ? `<span class="pill">${escapeHtml(job.seniority)}</span>` : ""}
          ${job.verified ? `<span class="pill verified">Verified</span>` : ""}
          ${salary ? `<span class="pill salary">${escapeHtml(salary)}</span>` : `<span class="pill">Salary not listed</span>`}
          ${tech.map((t) => `<span class="pill">${escapeHtml(t)}</span>`).join("")}
        </div>
        <div class="job-actions">
          <a class="apply-btn" href="${escapeHtml(job.apply_url)}" rel="noopener noreferrer" target="_blank">Apply</a>
        </div>
      `;
      els.list.appendChild(card);
    }
  }

  function onFiltersChanged() {
    render();
  }

  async function boot() {
    try {
      const res = await fetch(assetUrl("jobs.json"), { cache: "no-cache" });
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const data = await res.json();
      jobs = Array.isArray(data.jobs) ? data.jobs : [];
      const generated = data.generated_at ? `Snapshot ${data.generated_at}` : "Snapshot time unknown";
      const count = typeof data.count === "number" ? data.count : jobs.length;
      els.meta.textContent = `${generated} · ${count} confirmed listing${count === 1 ? "" : "s"} · client-side filters only`;
      populateFilters(jobs);
      els.error.hidden = true;
      render();
    } catch (err) {
      console.error(err);
      els.meta.textContent = "Could not load the public shortlist.";
      els.error.hidden = false;
      els.empty.hidden = true;
      els.count.textContent = "";
    }
  }

  for (const el of [els.search, els.province, els.arrangement, els.seniority, els.salary]) {
    el.addEventListener("input", onFiltersChanged);
    el.addEventListener("change", onFiltersChanged);
  }

  // Expose base for tests / debugging under project Pages paths.
  window.GitHiredPublic = { BASE, assetUrl };
  boot();
})();
