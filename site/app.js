(() => {
  "use strict";

  const M = window.GitHiredMatch;
  const R = window.GitHiredResume;
  const PROFILE_KEY = "githired_public_profile_v1";

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
    sort: document.getElementById("filter-sort"),
    salaryMin: document.getElementById("salary-min"),
    salaryDisplay: document.getElementById("salary-min-display"),
    includeUndisclosed: document.getElementById("include-undisclosed"),
    viewBrowse: document.getElementById("view-browse"),
    viewMatch: document.getElementById("view-match"),
    stepInput: document.getElementById("match-step-input"),
    stepProfile: document.getElementById("match-step-profile"),
    stepResults: document.getElementById("match-step-results"),
    matchList: document.getElementById("match-list"),
    matchEmpty: document.getElementById("match-empty"),
    matchSummary: document.getElementById("match-summary"),
    resumeFile: document.getElementById("resume-file"),
    resumeStatus: document.getElementById("resume-status"),
    resumePaste: document.getElementById("resume-paste"),
  };

  /** @type {any[]} */
  let jobs = [];
  /** @type {any} */
  let draftProfile = M.emptyProfile();
  /** @type {string} */
  let uploadedText = "";
  let fx = M.DEFAULT_FX;

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

  function formatSalaryCadLabel(value) {
    const n = Number(value) || 0;
    if (n >= M.SALARY_MAX_UI) return "$300,000+";
    return `$${n.toLocaleString("en-CA")}`;
  }

  function arrangementLabel(job) {
    const a = job.work_arrangement || "unspecified";
    if (a === "remote" && job.remote_scope === "province") return "Remote (province)";
    if (a === "remote" && job.remote_scope === "canada") return "Remote (Canada)";
    if (a === "onsite") return "On-site";
    if (a === "hybrid") return "Hybrid";
    if (a === "remote") return "Remote";
    return "Arrangement unspecified";
  }

  function freshnessLabel(job) {
    if (job.discovered_today && job.first_seen) return "Discovered today";
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

  function updateSalaryDisplay() {
    const v = Number(els.salaryMin.value) || 0;
    els.salaryDisplay.textContent = formatSalaryCadLabel(v);
    els.salaryMin.setAttribute("aria-valuenow", String(v));
  }

  function browseFilters() {
    return {
      query: els.search.value.trim(),
      province: els.province.value,
      arrangement: els.arrangement.value,
      seniority: els.seniority.value,
      minimum_salary_cad: Number(els.salaryMin.value) || 0,
      include_undisclosed_salary: els.includeUndisclosed.checked,
      sort: els.sort.value,
    };
  }

  function renderBrowse() {
    const rows = M.filterBrowseJobs(jobs, browseFilters(), fx);
    els.count.textContent = `${rows.length} job${rows.length === 1 ? "" : "s"} shown`;
    els.list.innerHTML = "";
    els.empty.hidden = rows.length > 0;
    for (const { job, salary_meta } of rows) {
      const salary = formatSalary(job);
      const tech = (job.technologies || []).slice(0, 4);
      const card = document.createElement("article");
      card.className = "job-card";
      const maxOnly =
        salary_meta && salary_meta.meets_with_max_only
          ? `<span class="pill warn">Max meets salary floor</span>`
          : "";
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
          ${maxOnly}
          ${tech.map((t) => `<span class="pill">${escapeHtml(t)}</span>`).join("")}
        </div>
        <div class="job-actions">
          <a class="apply-btn" href="${escapeHtml(job.apply_url)}" rel="noopener noreferrer" target="_blank">Apply Directly</a>
        </div>
      `;
      els.list.appendChild(card);
    }
  }

  function setView(name) {
    const match = name === "match";
    els.viewBrowse.hidden = match;
    els.viewMatch.hidden = !match;
    document.querySelectorAll("[data-nav]").forEach((el) => {
      const active = el.getAttribute("data-nav") === name;
      if (el.classList.contains("nav-link")) {
        el.classList.toggle("is-active", active);
      }
      // Hero (and other) primary/secondary CTAs: green fill marks the current view.
      if (el.classList.contains("btn-primary") || el.classList.contains("btn-secondary")) {
        el.classList.toggle("btn-primary", active);
        el.classList.toggle("btn-secondary", !active);
        el.setAttribute("aria-pressed", active ? "true" : "false");
      }
    });
    if (match) {
      const saved = loadSavedProfile();
      if (saved) {
        draftProfile = saved;
        showProfileStep();
      }
    }
    try {
      history.replaceState(null, "", match ? "#match" : "#browse");
    } catch (_) {
      /* ignore */
    }
  }

  function showMatchStep(step) {
    els.stepInput.hidden = step !== "input";
    els.stepProfile.hidden = step !== "profile";
    els.stepResults.hidden = step !== "results";
  }

  function csv(list) {
    return (list || []).join(", ");
  }

  function splitCsv(value) {
    return String(value || "")
      .split(",")
      .map((s) => s.trim())
      .filter(Boolean);
  }

  function fillProfileEditor(profile) {
    document.getElementById("prof-title").value = profile.current_title || "";
    document.getElementById("prof-years").value =
      profile.years_experience != null ? profile.years_experience : "";
    document.getElementById("prof-desired").value = csv(profile.desired_titles);
    document.getElementById("prof-skills").value = csv(profile.skills);
    document.getElementById("prof-seniority").value = csv(profile.seniority);
    document.getElementById("prof-disciplines").value = csv(profile.disciplines);
    document.getElementById("prof-locations").value = csv(profile.preferred_locations);
    document.getElementById("prof-arrangements").value = csv(
      profile.work_arrangements.length ? profile.work_arrangements : ["remote", "hybrid"]
    );
    document.getElementById("prof-salary").value = profile.minimum_salary_cad || 0;
    document.getElementById("prof-include-undisclosed").checked =
      profile.include_undisclosed_salary !== false;
  }

  function readProfileEditor() {
    const p = M.emptyProfile();
    p.current_title = document.getElementById("prof-title").value.trim();
    const years = document.getElementById("prof-years").value;
    p.years_experience = years === "" ? null : Number(years);
    p.desired_titles = splitCsv(document.getElementById("prof-desired").value);
    p.skills = splitCsv(document.getElementById("prof-skills").value);
    p.seniority = splitCsv(document.getElementById("prof-seniority").value).map((s) =>
      s.toLowerCase()
    );
    p.disciplines = splitCsv(document.getElementById("prof-disciplines").value);
    p.preferred_locations = splitCsv(document.getElementById("prof-locations").value).map((x) =>
      /^[a-z]{2}$/i.test(x) ? x.toUpperCase() : x
    );
    p.work_arrangements = splitCsv(document.getElementById("prof-arrangements").value).map((s) =>
      s.toLowerCase()
    );
    p.minimum_salary_cad = Number(document.getElementById("prof-salary").value) || 0;
    p.include_undisclosed_salary = document.getElementById("prof-include-undisclosed").checked;
    return p;
  }

  function showProfileStep() {
    fillProfileEditor(draftProfile);
    showMatchStep("profile");
  }

  function profileFromManual() {
    const p = M.emptyProfile();
    p.current_title = document.getElementById("manual-title").value.trim();
    p.desired_titles = p.current_title ? [p.current_title] : [];
    const years = document.getElementById("manual-years").value;
    p.years_experience = years === "" ? null : Number(years);
    p.skills = splitCsv(document.getElementById("manual-skills").value);
    p.seniority = [...document.getElementById("manual-seniority").selectedOptions].map(
      (o) => o.value
    );
    p.disciplines = [...document.getElementById("manual-disciplines").selectedOptions].map(
      (o) => o.value
    );
    const prov = document.getElementById("manual-province").value;
    const city = document.getElementById("manual-city").value.trim();
    p.preferred_locations = [prov, city].filter(Boolean);
    p.work_arrangements = [...document.querySelectorAll('input[name="manual-arr"]:checked')].map(
      (el) => el.value
    );
    p.minimum_salary_cad = Number(document.getElementById("manual-salary").value) || 0;
    return p;
  }

  function activeTab() {
    const active = document.querySelector(".tab.is-active");
    return active ? active.getAttribute("data-tab") : "upload";
  }

  function extractDraft() {
    const tab = activeTab();
    if (tab === "manual") {
      draftProfile = profileFromManual();
      return;
    }
    if (tab === "paste") {
      draftProfile = M.extractProfileFromText(els.resumePaste.value || "");
      return;
    }
    if (!uploadedText.trim()) {
      throw new Error("Upload a résumé or switch to Paste / Manual");
    }
    draftProfile = M.extractProfileFromText(uploadedText);
  }

  function loadSavedProfile() {
    try {
      const raw = localStorage.getItem(PROFILE_KEY);
      if (!raw) return null;
      return { ...M.emptyProfile(), ...JSON.parse(raw) };
    } catch (_) {
      return null;
    }
  }

  function saveProfile(profile) {
    localStorage.setItem(PROFILE_KEY, JSON.stringify(profile));
  }

  function clearProfile() {
    localStorage.removeItem(PROFILE_KEY);
    draftProfile = M.emptyProfile();
    uploadedText = "";
    if (els.resumeFile) els.resumeFile.value = "";
    if (els.resumePaste) els.resumePaste.value = "";
    if (els.resumeStatus) els.resumeStatus.textContent = "Saved profile cleared.";
    showMatchStep("input");
  }

  function renderMatches(results) {
    els.matchList.innerHTML = "";
    els.matchEmpty.hidden = results.length > 0;
    els.matchSummary.textContent = `${results.length} match${results.length === 1 ? "" : "es"} · deterministic relevance (not AI)`;
    for (const { job, match } of results) {
      const salary = formatSalary(job);
      const card = document.createElement("article");
      card.className = "job-card";
      const matched = (match.matched_skills || [])
        .map((s) => `<div class="ok">✓ ${escapeHtml(s)}</div>`)
        .join("");
      const unconfirmed = (match.unconfirmed_skills || [])
        .slice(0, 8)
        .map((s) => `<div class="maybe">? ${escapeHtml(s)} <span class="hint">(not listed — not a confirmed gap)</span></div>`)
        .join("");
      const reasons = (match.reasons || []).map((r) => `<li>${escapeHtml(r)}</li>`).join("");
      card.innerHTML = `
        <div class="job-card-top">
          <div>
            <p class="job-company">${escapeHtml(job.company)}</p>
            <h2 class="job-title">${escapeHtml(job.title)}</h2>
          </div>
          <span class="pill match">Match: ${match.percent}%</span>
        </div>
        <div class="job-meta">
          <span class="pill">${escapeHtml(job.location || "Canada")}</span>
          <span class="pill">${escapeHtml(arrangementLabel(job))}</span>
          ${salary ? `<span class="pill salary">${escapeHtml(salary)}</span>` : `<span class="pill">Salary not listed</span>`}
          ${match.meets_with_max_only ? `<span class="pill warn">Max meets salary floor</span>` : ""}
          <span class="pill">${escapeHtml(match.status)}</span>
        </div>
        <div class="skill-lists">
          ${matched ? `<div><strong>Matching</strong>${matched}</div>` : ""}
          ${unconfirmed ? `<div><strong>Unconfirmed</strong>${unconfirmed}</div>` : ""}
        </div>
        <div class="match-score-block">
          <strong>Why recommended</strong>
          <ul>${reasons}</ul>
        </div>
        <div class="job-actions">
          <a class="apply-btn" href="${escapeHtml(job.apply_url)}" rel="noopener noreferrer" target="_blank">Apply Directly</a>
        </div>
      `;
      els.matchList.appendChild(card);
    }
  }

  function runMatch() {
    draftProfile = readProfileEditor();
    const t0 = performance.now();
    const results = M.matchJobs(draftProfile, jobs, { fx, limit: 40 });
    const ms = Math.round(performance.now() - t0);
    renderMatches(results);
    els.matchSummary.textContent += ` · scored in ${ms}ms`;
    showMatchStep("results");
  }

  async function onResumeFile(file) {
    els.resumeStatus.textContent = "Parsing locally…";
    try {
      const { text, source } = await R.extractResumeText(file);
      uploadedText = text;
      // Drop file handle — do not keep original bytes
      els.resumeFile.value = "";
      if (!text) {
        els.resumeStatus.textContent = "No readable text found in that file.";
        return;
      }
      els.resumeStatus.textContent = `Parsed ${source.toUpperCase()} locally (${text.length.toLocaleString()} chars). ${R.PRIVACY_NOTICE}`;
    } catch (err) {
      uploadedText = "";
      els.resumeStatus.textContent = err && err.message ? err.message : "Could not parse file";
    }
  }

  function bindTabs() {
    document.querySelectorAll(".tab").forEach((tab) => {
      tab.addEventListener("click", () => {
        document.querySelectorAll(".tab").forEach((t) => {
          t.classList.toggle("is-active", t === tab);
          t.setAttribute("aria-selected", t === tab ? "true" : "false");
        });
        const name = tab.getAttribute("data-tab");
        ["upload", "paste", "manual"].forEach((id) => {
          const panel = document.getElementById(`tab-${id}`);
          if (panel) panel.hidden = id !== name;
        });
      });
    });
  }

  async function boot() {
    updateSalaryDisplay();
    bindTabs();
    try {
      const res = await fetch(assetUrl("jobs.json"), { cache: "no-cache" });
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const data = await res.json();
      jobs = Array.isArray(data.jobs) ? data.jobs : [];
      if (data.usd_to_cad) fx = Number(data.usd_to_cad) || fx;
      const generated = data.generated_at ? `Snapshot ${data.generated_at}` : "Snapshot time unknown";
      const count = typeof data.count === "number" ? data.count : jobs.length;
      els.meta.textContent = `${generated} · ${count} confirmed listing${count === 1 ? "" : "s"} · client-side filters & matching`;
      populateFilters(jobs);
      els.error.hidden = true;
      renderBrowse();
    } catch (err) {
      console.error(err);
      els.meta.textContent = "Could not load the public shortlist.";
      els.error.hidden = false;
      els.empty.hidden = true;
      els.count.textContent = "";
    }

    if (location.hash === "#match") setView("match");
    else setView("browse");
  }

  document.querySelectorAll("[data-nav]").forEach((el) => {
    el.addEventListener("click", (e) => {
      const nav = el.getAttribute("data-nav");
      if (!nav) return;
      if (el.tagName === "A" && nav === "browse") {
        e.preventDefault();
      }
      setView(nav);
    });
  });

  for (const el of [
    els.search,
    els.province,
    els.arrangement,
    els.seniority,
    els.sort,
    els.salaryMin,
    els.includeUndisclosed,
  ]) {
    el.addEventListener("input", () => {
      if (el === els.salaryMin) updateSalaryDisplay();
      renderBrowse();
    });
    el.addEventListener("change", () => {
      if (el === els.salaryMin) updateSalaryDisplay();
      renderBrowse();
    });
  }

  els.resumeFile.addEventListener("change", () => {
    const file = els.resumeFile.files && els.resumeFile.files[0];
    if (file) onResumeFile(file);
  });

  document.getElementById("btn-extract").addEventListener("click", () => {
    try {
      extractDraft();
      showProfileStep();
    } catch (err) {
      els.resumeStatus.textContent = err.message || String(err);
    }
  });
  document.getElementById("btn-back-input").addEventListener("click", () => showMatchStep("input"));
  document.getElementById("btn-edit-profile").addEventListener("click", () => showProfileStep());
  document.getElementById("btn-run-match").addEventListener("click", runMatch);
  document.getElementById("btn-save-profile").addEventListener("click", () => {
    draftProfile = readProfileEditor();
    saveProfile(draftProfile);
    els.resumeStatus.textContent =
      "Profile saved in this browser only. Clearing site data removes it.";
  });
  document.getElementById("btn-clear-profile").addEventListener("click", clearProfile);

  window.GitHiredPublic = {
    assetUrl,
    getJobs: () => jobs,
    renderBrowse,
    PROFILE_KEY,
  };
  boot();
})();
