(() => {
  "use strict";

  const M = window.GitHiredMatch;
  const R = window.GitHiredResume;
  const PROFILE_KEY = "githired_public_profile_v1";
  const BATCH_SIZE = 20;
  const LOAD_MORE_BATCH_SIZE = 20;
  const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];

  const els = {
    meta: document.getElementById("snapshot-meta"),
    list: document.getElementById("job-list"),
    empty: document.getElementById("empty-state"),
    error: document.getElementById("error-state"),
    count: document.getElementById("result-count"),
    search: document.getElementById("search"),
    provincePanel: document.getElementById("filter-province-panel"),
    arrangementPanel: document.getElementById("filter-arrangement-panel"),
    seniorityPanel: document.getElementById("filter-seniority-panel"),
    sort: document.getElementById("filter-sort"),
    salaryMin: document.getElementById("salary-min"),
    salaryDisplay: document.getElementById("salary-min-display"),
    includeUndisclosed: document.getElementById("include-undisclosed"),
    viewBrowse: document.getElementById("view-browse"),
    viewMatch: document.getElementById("view-match"),
    heroBrowse: document.getElementById("view-hero-browse"),
    stepInput: document.getElementById("match-step-input"),
    stepProfile: document.getElementById("match-step-profile"),
    stepResults: document.getElementById("match-step-results"),
    matchList: document.getElementById("match-list"),
    matchEmpty: document.getElementById("match-empty"),
    matchSummary: document.getElementById("match-summary"),
    resumeFile: document.getElementById("resume-file"),
    resumeStatus: document.getElementById("resume-status"),
    resumePaste: document.getElementById("resume-paste"),
    advanced: document.getElementById("advanced-filters"),
    allFiltersBtn: document.getElementById("btn-all-filters"),
    chips: document.getElementById("filter-chips"),
    clearFilters: document.getElementById("btn-clear-filters"),
    clearFiltersAdv: document.getElementById("btn-clear-filters-adv"),
    clearEmpty: document.getElementById("btn-clear-empty"),
    applyFilters: document.getElementById("btn-apply-filters"),
    loadMoreWrap: document.getElementById("load-more-wrap"),
    loadMore: document.getElementById("btn-load-more"),
    showingCount: document.getElementById("showing-count"),
    menuToggle: document.getElementById("menu-toggle"),
    mobileMenu: document.getElementById("mobile-menu"),
    devToggle: document.getElementById("nav-dev-toggle"),
    devMenu: document.getElementById("nav-dev-menu"),
    live: document.getElementById("live-region"),
    backdrop: document.getElementById("filter-drawer-backdrop"),
  };

  /** @type {any[]} */
  let jobs = [];
  /** @type {any} */
  let draftProfile = M.emptyProfile();
  /** @type {string} */
  let uploadedText = "";
  let fx = M.DEFAULT_FX;
  /** @type {any[]} */
  let filteredRows = [];
  let visibleCount = BATCH_SIZE;
  let totalJobCount = 0;

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

  function announce(msg) {
    if (els.live) els.live.textContent = msg;
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

  function formatVerifiedDate(iso) {
    if (!iso) return null;
    const m = String(iso).match(/^(\d{4})-(\d{2})-(\d{2})/);
    if (!m) return `Verified ${iso}`;
    const month = MONTHS[Number(m[2]) - 1] || m[2];
    const day = String(Number(m[3]));
    return `Verified ${month} ${day}`;
  }

  function formatSnapshotMeta(count, generatedAt) {
    const n = Number(count) || 0;
    const primary = `${n.toLocaleString("en-CA")} verified Canadian tech jobs`;
    if (!generatedAt) return primary;
    const d = new Date(generatedAt);
    if (Number.isNaN(d.getTime())) return primary;
    const updated = d.toLocaleDateString(undefined, {
      year: "numeric",
      month: "short",
      day: "numeric",
    });
    return `${primary} · Last updated ${updated}`;
  }

  function on(el, type, handler, options) {
    if (!el) return false;
    el.addEventListener(type, handler, options);
    return true;
  }

  function arrangementLabel(job) {
    const a = job.work_arrangement || "unspecified";
    if (a === "remote" && job.remote_scope === "province") return "Remote (province)";
    if (a === "remote" && job.remote_scope === "canada") return "Remote (Canada)";
    if (a === "onsite") return "On-site";
    if (a === "hybrid") return "Hybrid";
    if (a === "remote") return "Remote";
    return null;
  }

  function shouldShowArrangement(job, label) {
    if (!label) return false;
    const loc = String(job.location || "").toLowerCase();
    if (label === "Remote (province)") return true;
    if (/\bremote\b/.test(loc) && label.startsWith("Remote")) return false;
    return true;
  }

  function truncateLocation(loc) {
    const raw = String(loc || "Canada").trim();
    if (raw.length <= 72) return { text: raw, full: raw, truncated: false };
    const parts = raw.split(/[;|]/).map((s) => s.trim()).filter(Boolean);
    if (parts.length > 2) {
      const text = `${parts[0]}; ${parts[1]} +${parts.length - 2} more`;
      return { text, full: raw, truncated: true };
    }
    return { text: `${raw.slice(0, 69)}…`, full: raw, truncated: true };
  }

  const ARRANGEMENT_OPTIONS = [
    { value: "remote", label: "Remote" },
    { value: "hybrid", label: "Hybrid" },
    { value: "onsite", label: "On-site" },
    { value: "unspecified", label: "Unspecified" },
  ];

  function selectedValues(panel) {
    if (!panel) return [];
    return [...panel.querySelectorAll('input[type="checkbox"]:checked')].map((el) => el.value);
  }

  function updateMultiFilterSummary(root) {
    const panel = root.querySelector(".multi-filter-panel");
    const toggle = root.querySelector(".multi-filter-toggle");
    if (!panel || !toggle) return;
    const selected = selectedValues(panel);
    if (!selected.length) {
      toggle.textContent = "All";
      return;
    }
    const labels = selected.map((value) => {
      const input = [...panel.querySelectorAll("input")].find((el) => el.value === value);
      const text = input && input.parentElement ? input.parentElement.textContent.trim() : value;
      return text;
    });
    toggle.textContent =
      labels.length <= 2 ? labels.join(", ") : `${labels.length} selected`;
  }

  function fillMultiFilter(panel, options, { preserve = true } = {}) {
    const prev = preserve ? new Set(selectedValues(panel)) : new Set();
    panel.innerHTML = "";
    for (const opt of options) {
      const value = typeof opt === "string" ? opt : opt.value;
      const label = typeof opt === "string" ? opt : opt.label;
      const row = document.createElement("label");
      row.className = "multi-filter-option";
      row.setAttribute("role", "option");
      const input = document.createElement("input");
      input.type = "checkbox";
      input.value = value;
      input.checked = prev.has(value);
      input.addEventListener("change", () => {
        updateMultiFilterSummary(panel.closest(".multi-filter"));
        onFiltersChanged();
      });
      row.appendChild(input);
      row.appendChild(document.createTextNode(` ${label}`));
      panel.appendChild(row);
    }
    updateMultiFilterSummary(panel.closest(".multi-filter"));
  }

  function setMultiFilterOpen(root, open) {
    const panel = root.querySelector(".multi-filter-panel");
    const toggle = root.querySelector(".multi-filter-toggle");
    if (!panel || !toggle) return;
    panel.hidden = !open;
    toggle.setAttribute("aria-expanded", open ? "true" : "false");
    root.classList.toggle("is-open", open);
  }

  function closeAllMultiFilters(except) {
    document.querySelectorAll(".multi-filter").forEach((root) => {
      if (root !== except) setMultiFilterOpen(root, false);
    });
  }

  function bindMultiFilters() {
    document.querySelectorAll(".multi-filter").forEach((root) => {
      const toggle = root.querySelector(".multi-filter-toggle");
      if (!toggle || toggle.dataset.bound === "1") return;
      toggle.dataset.bound = "1";
      toggle.addEventListener("click", (e) => {
        e.stopPropagation();
        const willOpen = root.querySelector(".multi-filter-panel").hidden;
        closeAllMultiFilters(root);
        setMultiFilterOpen(root, willOpen);
      });
    });
    document.addEventListener("click", (e) => {
      if (!e.target.closest(".multi-filter")) closeAllMultiFilters();
    });
  }

  function populateFilters(data) {
    const provinces = [...new Set(data.map((j) => j.province).filter(Boolean))].sort();
    const seniorities = [...new Set(data.map((j) => j.seniority).filter(Boolean))].sort();
    fillMultiFilter(els.provincePanel, provinces);
    fillMultiFilter(els.arrangementPanel, ARRANGEMENT_OPTIONS);
    fillMultiFilter(
      els.seniorityPanel,
      seniorities.map((s) => ({
        value: s,
        label: s.charAt(0).toUpperCase() + s.slice(1),
      }))
    );
  }

  function updateSalaryDisplay() {
    const v = Number(els.salaryMin.value) || 0;
    els.salaryDisplay.textContent = formatSalaryCadLabel(v);
    els.salaryMin.setAttribute("aria-valuenow", String(v));
    document.querySelectorAll(".preset-btn").forEach((btn) => {
      const val = Number(btn.getAttribute("data-salary")) || 0;
      btn.classList.toggle("is-active", val === v);
      btn.setAttribute("aria-pressed", val === v ? "true" : "false");
    });
  }

  function browseFilters() {
    return {
      query: els.search.value.trim(),
      provinces: selectedValues(els.provincePanel),
      arrangements: selectedValues(els.arrangementPanel),
      seniorities: selectedValues(els.seniorityPanel),
      minimum_salary_cad: Number(els.salaryMin.value) || 0,
      include_undisclosed_salary: els.includeUndisclosed.checked,
      sort: els.sort.value || "verified",
    };
  }

  function hasActiveFilters(f) {
    return Boolean(
      f.query ||
        f.provinces.length ||
        f.arrangements.length ||
        f.seniorities.length ||
        f.minimum_salary_cad > 0 ||
        !f.include_undisclosed_salary
    );
  }

  function clearAllFilters() {
    els.search.value = "";
    els.salaryMin.value = "0";
    els.includeUndisclosed.checked = true;
    els.sort.value = "verified";
    document.querySelectorAll(".multi-filter-panel input[type='checkbox']").forEach((input) => {
      input.checked = false;
    });
    document.querySelectorAll(".multi-filter").forEach((root) => updateMultiFilterSummary(root));
    updateSalaryDisplay();
    setAdvancedOpen(false);
    onFiltersChanged();
    announce("Filters cleared");
  }

  function renderChips(f) {
    const chips = [];
    if (f.query) chips.push({ key: "q", label: `Search: ${f.query}` });
    for (const p of f.provinces) chips.push({ key: `province:${p}`, label: `Province: ${p}` });
    for (const a of f.arrangements) {
      const opt = ARRANGEMENT_OPTIONS.find((o) => o.value === a);
      chips.push({ key: `arrangement:${a}`, label: opt ? opt.label : a });
    }
    for (const s of f.seniorities) chips.push({ key: `seniority:${s}`, label: `Seniority: ${s}` });
    if (f.minimum_salary_cad > 0) {
      chips.push({ key: "salary", label: `Min ${formatSalaryCadLabel(f.minimum_salary_cad)} CAD` });
    }
    if (!f.include_undisclosed_salary) {
      chips.push({ key: "disclosed", label: "Advertised salary only" });
    }

    els.chips.hidden = chips.length === 0;
    els.clearFilters.hidden = chips.length === 0;
    els.chips.innerHTML = chips
      .map(
        (c) =>
          `<button type="button" class="filter-chip" data-chip="${escapeHtml(c.key)}" aria-label="Remove ${escapeHtml(c.label)}">${escapeHtml(c.label)} <span aria-hidden="true">×</span></button>`
      )
      .join("");
  }

  function removeChip(key) {
    if (key === "q") els.search.value = "";
    else if (key === "salary") {
      els.salaryMin.value = "0";
      updateSalaryDisplay();
    } else if (key === "disclosed") els.includeUndisclosed.checked = true;
    else if (key.startsWith("province:")) {
      const v = key.slice(9);
      const input = [...els.provincePanel.querySelectorAll("input")].find((el) => el.value === v);
      if (input) input.checked = false;
      updateMultiFilterSummary(els.provincePanel.closest(".multi-filter"));
    } else if (key.startsWith("arrangement:")) {
      const v = key.slice(12);
      const input = [...els.arrangementPanel.querySelectorAll("input")].find((el) => el.value === v);
      if (input) input.checked = false;
      updateMultiFilterSummary(els.arrangementPanel.closest(".multi-filter"));
    } else if (key.startsWith("seniority:")) {
      const v = key.slice(10);
      const input = [...els.seniorityPanel.querySelectorAll("input")].find((el) => el.value === v);
      if (input) input.checked = false;
      updateMultiFilterSummary(els.seniorityPanel.closest(".multi-filter"));
    }
    onFiltersChanged();
  }

  function buildJobCard(job, salary_meta, { match } = {}) {
    const salary = formatSalary(job);
    const arr = arrangementLabel(job);
    const loc = truncateLocation(job.location);
    const verifiedLabel = formatVerifiedDate(job.last_verified);
    const card = document.createElement("article");
    card.className = "job-card";
    const maxOnly =
      salary_meta && salary_meta.meets_with_max_only
        ? `<span class="pill warn">Max meets salary floor</span>`
        : "";
    const matchBadge = match
      ? `<span class="pill match">Match ${match.percent}%</span>`
      : "";
    const verifiedMark = !match && job.last_verified
      ? `<span class="verified-badge" title="${escapeHtml(verifiedLabel || "Verified listing")} — not the original posting date" aria-label="${escapeHtml(verifiedLabel || "Verified listing")}"><svg viewBox="0 0 24 24" width="16" height="16" aria-hidden="true" focusable="false"><path fill="currentColor" d="M12 2.5l2.09 1.52 2.5-.3 1.08 2.28 2.28 1.08-.3 2.5L21.5 12l-1.52 2.09.3 2.5-2.28 1.08-1.08 2.28-2.5-.3L12 21.5l-2.09-1.52-2.5.3-1.08-2.28-2.28-1.08.3-2.5L2.5 12l1.52-2.09-.3-2.5 2.28-1.08L7.08 3.72l2.5.3L12 2.5zm-1.2 12.3 5.3-5.3-1.4-1.4-3.9 3.9-1.8-1.8-1.4 1.4 3.2 3.2z"/></svg></span>`
      : "";

    let extras = "";
    if (match) {
      const matched = (match.matched_skills || [])
        .map((s) => `<div class="ok">✓ ${escapeHtml(s)}</div>`)
        .join("");
      const unconfirmed = (match.unconfirmed_skills || [])
        .slice(0, 8)
        .map(
          (s) =>
            `<div class="maybe">? ${escapeHtml(s)} <span class="hint">(not listed)</span></div>`
        )
        .join("");
      const reasons = (match.reasons || []).map((r) => `<li>${escapeHtml(r)}</li>`).join("");
      extras = `
        <div class="skill-lists">
          ${matched ? `<div><strong>Matching</strong>${matched}</div>` : ""}
          ${unconfirmed ? `<div><strong>Unconfirmed</strong>${unconfirmed}</div>` : ""}
        </div>
        <div class="match-score-block">
          <strong>Why recommended</strong>
          <ul>${reasons}</ul>
        </div>`;
    }

    card.innerHTML = `
      <div class="job-card-top">
        <div>
          <p class="job-company">${escapeHtml(job.company)}${verifiedMark}</p>
          <h2 class="job-title">${escapeHtml(job.title)}</h2>
        </div>
        ${matchBadge}
      </div>
      <div class="job-meta">
        <span class="pill location"${loc.truncated ? ` title="${escapeHtml(loc.full)}"` : ""}>${escapeHtml(loc.text)}</span>
        ${shouldShowArrangement(job, arr) ? `<span class="pill">${escapeHtml(arr)}</span>` : ""}
        ${job.seniority ? `<span class="pill">${escapeHtml(job.seniority)}</span>` : ""}
        ${salary ? `<span class="pill salary">${escapeHtml(salary)}</span>` : `<span class="pill">Salary not listed</span>`}
        ${maxOnly}
        ${match && match.status ? `<span class="pill">${escapeHtml(match.status)}</span>` : ""}
      </div>
      ${extras}
      <div class="job-actions">
        <a class="apply-btn" href="${escapeHtml(job.apply_url)}" rel="noopener noreferrer" target="_blank">Apply</a>
      </div>
    `;
    return card;
  }

  function renderBrowse({ append = false } = {}) {
    const f = browseFilters();
    if (!append) {
      filteredRows = M.filterBrowseJobs(jobs, f, fx);
      visibleCount = BATCH_SIZE;
    }
    const total = filteredRows.length;
    const shown = Math.min(visibleCount, total);
    const slice = filteredRows.slice(0, shown);

    els.count.textContent =
      total === 0
        ? "0 jobs shown"
        : shown < total
          ? `${total} jobs match · showing ${shown}`
          : `${total} job${total === 1 ? "" : "s"} shown`;
    renderChips(f);

    if (!append) {
      els.list.innerHTML = "";
    } else {
      // Only append new cards beyond what is already rendered
      const existing = els.list.children.length;
      const toAdd = slice.slice(existing);
      for (const { job, salary_meta } of toAdd) {
        els.list.appendChild(buildJobCard(job, salary_meta));
      }
      els.empty.hidden = total > 0;
      els.loadMoreWrap.hidden = shown >= total || total === 0;
      els.showingCount.textContent = total ? `Showing ${shown} of ${total} jobs` : "";
      syncUrlState();
      return;
    }

    els.list.innerHTML = "";
    els.empty.hidden = total > 0;
    for (const { job, salary_meta } of slice) {
      els.list.appendChild(buildJobCard(job, salary_meta));
    }
    els.loadMoreWrap.hidden = shown >= total || total === 0;
    els.showingCount.textContent = total ? `Showing ${shown} of ${total} jobs` : "";
    syncUrlState();
  }

  function onFiltersChanged() {
    visibleCount = BATCH_SIZE;
    renderBrowse({ append: false });
  }

  function loadMore() {
    const before = window.scrollY;
    visibleCount += LOAD_MORE_BATCH_SIZE;
    renderBrowse({ append: true });
    requestAnimationFrame(() => window.scrollTo(0, before));
    announce(`Showing ${Math.min(visibleCount, filteredRows.length)} of ${filteredRows.length} jobs`);
  }

  function isMobileFilters() {
    return window.matchMedia("(max-width: 767px)").matches;
  }

  function setAdvancedOpen(open) {
    if (!els.advanced || !els.allFiltersBtn) return;
    const mobile = isMobileFilters();
    if (open) {
      els.advanced.removeAttribute("hidden");
      els.advanced.hidden = false;
      els.advanced.classList.add("is-open");
    } else {
      els.advanced.setAttribute("hidden", "");
      els.advanced.hidden = true;
      els.advanced.classList.remove("is-open");
    }
    els.allFiltersBtn.setAttribute("aria-expanded", open ? "true" : "false");
    els.allFiltersBtn.classList.toggle("is-active", open);
    document.body.classList.toggle("filters-open", open && mobile);
    if (els.backdrop) {
      if (open && mobile) {
        els.backdrop.removeAttribute("hidden");
        els.backdrop.hidden = false;
      } else {
        els.backdrop.setAttribute("hidden", "");
        els.backdrop.hidden = true;
      }
    }
    if (open && mobile && els.applyFilters) {
      els.applyFilters.focus();
    }
  }

  function toggleAdvancedFilters() {
    const open = els.allFiltersBtn.getAttribute("aria-expanded") !== "true";
    setAdvancedOpen(open);
    return open;
  }

  function setMobileMenuOpen(open) {
    if (!els.mobileMenu || !els.menuToggle) return;
    if (open) {
      els.mobileMenu.removeAttribute("hidden");
      els.mobileMenu.hidden = false;
      els.mobileMenu.classList.add("is-open");
    } else {
      els.mobileMenu.setAttribute("hidden", "");
      els.mobileMenu.hidden = true;
      els.mobileMenu.classList.remove("is-open");
    }
    els.menuToggle.setAttribute("aria-expanded", open ? "true" : "false");
    els.menuToggle.setAttribute("aria-label", open ? "Close menu" : "Open menu");
    document.body.classList.toggle("menu-open", open);
  }

  function toggleMobileMenu() {
    const open = els.menuToggle.getAttribute("aria-expanded") !== "true";
    setMobileMenuOpen(open);
    if (open) setDevMenuOpen(false);
    return open;
  }

  function setDevMenuOpen(open) {
    if (!els.devMenu || !els.devToggle) return;
    if (open) {
      els.devMenu.removeAttribute("hidden");
      els.devMenu.hidden = false;
      els.devMenu.classList.add("is-open");
    } else {
      els.devMenu.setAttribute("hidden", "");
      els.devMenu.hidden = true;
      els.devMenu.classList.remove("is-open");
    }
    els.devToggle.setAttribute("aria-expanded", open ? "true" : "false");
  }

  function toggleDevMenu() {
    const open = els.devToggle.getAttribute("aria-expanded") !== "true";
    setDevMenuOpen(open);
    return open;
  }

  function setView(name) {
    const match = name === "match";
    els.viewBrowse.hidden = match;
    els.viewMatch.hidden = !match;
    if (els.heroBrowse) els.heroBrowse.hidden = match;
    const promo = document.getElementById("dev-promo");
    if (promo) promo.hidden = match;

    document.querySelectorAll("[data-nav]").forEach((el) => {
      const active = el.getAttribute("data-nav") === name;
      if (
        el.classList.contains("nav-link") ||
        el.classList.contains("mobile-menu-link")
      ) {
        el.classList.toggle("is-active", active);
      }
    });

    if (match) {
      const saved = loadSavedProfile();
      if (saved) {
        draftProfile = saved;
        showProfileStep();
      }
    }
    setMobileMenuOpen(false);
    setDevMenuOpen(false);
    try {
      const url = new URL(window.location.href);
      url.hash = match ? "match" : "browse";
      history.replaceState(null, "", url);
    } catch (_) {
      /* ignore */
    }
  }

  function syncUrlState() {
    try {
      const f = browseFilters();
      const url = new URL(window.location.href);
      const params = url.searchParams;
      const setOrDel = (k, v) => {
        if (v == null || v === "" || v === "0" || v === false) params.delete(k);
        else params.set(k, String(v));
      };
      setOrDel("q", f.query || "");
      setOrDel("salary", f.minimum_salary_cad > 0 ? f.minimum_salary_cad : "");
      setOrDel("undisclosed", f.include_undisclosed_salary ? "" : "0");
      setOrDel("sort", f.sort === "verified" ? "" : f.sort);
      setOrDel("province", f.provinces.join(",") || "");
      setOrDel("arrangement", f.arrangements.join(",") || "");
      setOrDel("seniority", f.seniorities.join(",") || "");
      history.replaceState(null, "", url);
    } catch (_) {
      /* ignore */
    }
  }

  function restoreUrlState() {
    try {
      const params = new URL(window.location.href).searchParams;
      if (params.has("q")) els.search.value = params.get("q") || "";
      if (params.has("salary")) {
        els.salaryMin.value = String(Number(params.get("salary")) || 0);
      }
      if (params.get("undisclosed") === "0") els.includeUndisclosed.checked = false;
      if (params.has("sort")) {
        const s = params.get("sort");
        if ([...els.sort.options].some((o) => o.value === s)) els.sort.value = s;
      }
      const applyMulti = (panel, raw) => {
        if (!raw || !panel) return;
        const wanted = new Set(raw.split(",").filter(Boolean));
        panel.querySelectorAll("input").forEach((input) => {
          input.checked = wanted.has(input.value);
        });
        updateMultiFilterSummary(panel.closest(".multi-filter"));
      };
      applyMulti(els.provincePanel, params.get("province"));
      applyMulti(els.arrangementPanel, params.get("arrangement"));
      applyMulti(els.seniorityPanel, params.get("seniority"));
      updateSalaryDisplay();
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
    els.matchSummary.textContent = `${results.length} match${results.length === 1 ? "" : "es"}`;
    for (const { job, match } of results) {
      els.matchList.appendChild(buildJobCard(job, { meets_with_max_only: match.meets_with_max_only }, { match }));
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
    els.resumeStatus.textContent = "Reading résumé in this browser…";
    try {
      const { text, source } = await R.extractResumeText(file);
      uploadedText = text;
      els.resumeFile.value = "";
      if (!text) {
        els.resumeStatus.textContent = "No readable text found in that file.";
        return;
      }
      els.resumeStatus.textContent = `Ready (${source.toUpperCase()}, ${text.length.toLocaleString()} characters). Nothing left this device.`;
    } catch (err) {
      uploadedText = "";
      els.resumeStatus.textContent = err && err.message ? err.message : "Could not read file";
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
      totalJobCount = typeof data.count === "number" ? data.count : jobs.length;
      if (els.meta) {
        els.meta.textContent = formatSnapshotMeta(totalJobCount, data.generated_at);
        if (data.generated_at) {
          els.meta.title = `Dataset generated ${data.generated_at}`;
        }
      }
      populateFilters(jobs);
      restoreUrlState();
      els.error.hidden = true;
      renderBrowse();
    } catch (err) {
      console.error(err);
      els.meta.textContent = "Could not load jobs right now.";
      els.error.hidden = false;
      els.empty.hidden = true;
      els.count.textContent = "";
    }

    if (location.hash === "#match") setView("match");
    else setView("browse");

    window.addEventListener("hashchange", () => {
      setView(location.hash === "#match" ? "match" : "browse");
    });
  }

  function bindUi() {
    document.querySelectorAll("[data-nav]").forEach((el) => {
      on(el, "click", (e) => {
        const nav = el.getAttribute("data-nav");
        if (!nav) return;
        if (el.tagName === "A" && nav === "browse") e.preventDefault();
        setView(nav);
      });
    });

    bindMultiFilters();

    for (const el of [els.search, els.sort, els.salaryMin, els.includeUndisclosed]) {
      on(el, "input", () => {
        if (el === els.salaryMin) updateSalaryDisplay();
        onFiltersChanged();
      });
      on(el, "change", () => {
        if (el === els.salaryMin) updateSalaryDisplay();
        onFiltersChanged();
      });
    }

    document.querySelectorAll(".preset-btn").forEach((btn) => {
      on(btn, "click", () => {
        if (!els.salaryMin) return;
        els.salaryMin.value = String(Number(btn.getAttribute("data-salary")) || 0);
        updateSalaryDisplay();
        onFiltersChanged();
      });
    });

    // Root cause of prior "does nothing" failures: listeners were attached
    // without null-guards, so one missing node aborted the whole bind chain.
    on(els.allFiltersBtn, "click", (e) => {
      e.preventDefault();
      e.stopPropagation();
      toggleAdvancedFilters();
    });
    on(els.applyFilters, "click", () => {
      onFiltersChanged();
      setAdvancedOpen(false);
      announce(`${filteredRows.length} jobs match your filters`);
    });
    on(els.clearFilters, "click", clearAllFilters);
    on(els.clearFiltersAdv, "click", clearAllFilters);
    on(els.clearEmpty, "click", clearAllFilters);
    on(els.loadMore, "click", (e) => {
      e.preventDefault();
      loadMore();
    });
    on(els.chips, "click", (e) => {
      const btn = e.target.closest("[data-chip]");
      if (btn) removeChip(btn.getAttribute("data-chip"));
    });
    on(els.backdrop, "click", () => setAdvancedOpen(false));

    on(els.menuToggle, "click", (e) => {
      e.preventDefault();
      e.stopPropagation();
      toggleMobileMenu();
    });

    on(els.devToggle, "click", (e) => {
      e.preventDefault();
      e.stopPropagation();
      toggleDevMenu();
    });

    document.addEventListener("click", (e) => {
      if (!e.target.closest("#nav-developers")) setDevMenuOpen(false);
    });

    document.addEventListener("keydown", (e) => {
      if (e.key === "Escape") {
        closeAllMultiFilters();
        setAdvancedOpen(false);
        setMobileMenuOpen(false);
        setDevMenuOpen(false);
      }
    });

    on(els.resumeFile, "change", () => {
      const file = els.resumeFile.files && els.resumeFile.files[0];
      if (file) onResumeFile(file);
    });

    on(document.getElementById("btn-extract"), "click", () => {
      try {
        extractDraft();
        showProfileStep();
      } catch (err) {
        if (els.resumeStatus) els.resumeStatus.textContent = err.message || String(err);
      }
    });
    on(document.getElementById("btn-back-input"), "click", () => showMatchStep("input"));
    on(document.getElementById("btn-edit-profile"), "click", () => showProfileStep());
    on(document.getElementById("btn-run-match"), "click", runMatch);
    on(document.getElementById("btn-save-profile"), "click", () => {
      draftProfile = readProfileEditor();
      saveProfile(draftProfile);
      if (els.resumeStatus) {
        els.resumeStatus.textContent =
          "Profile saved in this browser only. Clearing site data removes it.";
      }
    });
    on(document.getElementById("btn-clear-profile"), "click", clearProfile);
  }

  window.GitHiredPublic = {
    assetUrl,
    getJobs: () => jobs,
    renderBrowse: () => renderBrowse({ append: false }),
    getFilteredCount: () => filteredRows.length,
    getVisibleCount: () => Math.min(visibleCount, filteredRows.length),
    getRenderedCardCount: () => (els.list ? els.list.querySelectorAll(".job-card").length : 0),
    loadMore,
    toggleAdvancedFilters,
    toggleDevMenu,
    toggleMobileMenu,
    setAdvancedOpen,
    setDevMenuOpen,
    setMobileMenuOpen,
    formatSnapshotMeta,
    BATCH_SIZE,
    LOAD_MORE_BATCH_SIZE,
    PROFILE_KEY,
  };

  try {
    bindUi();
  } catch (err) {
    console.error("GitHired UI bind failed", err);
  }
  boot();
})();
