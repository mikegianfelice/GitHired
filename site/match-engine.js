/**
 * GitHired client-side salary filters, résumé text extraction, and deterministic matching.
 * Pure logic — no DOM, no network. Works in browser and Node tests.
 */
(function (root, factory) {
  const api = factory();
  if (typeof module === "object" && module.exports) {
    module.exports = api;
  }
  root.GitHiredMatch = api;
})(typeof globalThis !== "undefined" ? globalThis : this, function () {
  "use strict";

  const DEFAULT_FX = 1.35;
  const SALARY_MAX_UI = 300000;
  const SALARY_STEP = 10000;

  const TECH_ALIASES = [
    ["Python", [/\bpython\b/i, /\bpyspark\b/i]],
    ["SQL", [/\bsql\b/i, /\bpostgres(?:ql)?\b/i, /\bmysql\b/i]],
    ["PostgreSQL", [/\bpostgres(?:ql)?\b/i]],
    ["JavaScript", [/\bjavascript\b/i, /\b(?<![a-z])js(?![a-z])\b/i]],
    ["TypeScript", [/\btypescript\b/i, /\b(?<![a-z])ts(?![a-z])\b/i]],
    ["Java", [/\bjava\b/i]],
    ["Go", [/\bgolang\b/i, /\bgo(?:lang)?\b/i]],
    ["Rust", [/\brust\b/i]],
    ["React", [/\breact(?:\.?js)?\b/i]],
    ["Node.js", [/\bnode\.?js\b/i]],
    ["AWS", [/\baws\b/i, /\bamazon web services\b/i]],
    ["Azure", [/\bazure\b/i]],
    ["GCP", [/\bgcp\b/i, /\bgoogle cloud\b/i]],
    ["Databricks", [/\bdatabricks\b/i]],
    ["Snowflake", [/\bsnowflake\b/i]],
    ["Spark", [/\bspark\b/i, /\bpyspark\b/i]],
    ["Kubernetes", [/\bkubernetes\b/i, /\bk8s\b/i]],
    ["Docker", [/\bdocker\b/i]],
    ["Terraform", [/\bterraform\b/i]],
    ["Airflow", [/\bairflow\b/i]],
    ["dbt", [/\bdbt\b/i]],
    ["Kafka", [/\bkafka\b/i]],
    ["PyTorch", [/\bpytorch\b/i]],
    ["TensorFlow", [/\btensorflow\b/i]],
    ["LLM", [/\bllm\b/i, /\blarge language models?\b/i]],
  ];

  const DISCIPLINES = [
    {
      id: "software_engineering",
      label: "Software Engineering",
      patterns: [/software engineer/i, /backend engineer/i, /frontend engineer/i, /full[\s-]?stack/i, /software developer/i],
    },
    {
      id: "data_engineering",
      label: "Data Engineering",
      patterns: [/data engineer/i, /data platform/i, /etl engineer/i],
    },
    {
      id: "ml_engineering",
      label: "AI / Machine Learning",
      patterns: [/machine learning/i, /\bml engineer/i, /\bai engineer/i, /llm engineer/i, /deep learning/i],
    },
    {
      id: "devops_sre",
      label: "DevOps / SRE",
      patterns: [/devops/i, /site reliability/i, /\bsre\b/i, /reliability engineer/i],
    },
    {
      id: "platform_engineering",
      label: "Cloud / Platform Engineering",
      patterns: [/platform engineer/i, /cloud engineer/i, /infrastructure engineer/i, /cloud architect/i],
    },
    {
      id: "security_engineering",
      label: "Security Engineering",
      patterns: [/security engineer/i, /appsec/i, /devsecops/i],
    },
    {
      id: "analytics_engineering",
      label: "Analytics Engineering",
      patterns: [/analytics engineer/i],
    },
  ];

  const SENIORITY_PATTERNS = [
    ["intern", /\b(?:intern|co[\s-]?op|coop|student|new[\s-]?grad)\b/i],
    ["junior", /\b(?:junior|jr\.?|entry[\s-]?level)\b/i],
    ["mid", /\b(?:mid[\s-]?level|intermediate)\b/i],
    ["senior", /\b(?:senior|sr\.?)\b/i],
    ["staff", /\bstaff\b/i],
    ["principal", /\bprincipal\b/i],
    ["lead", /\b(?:lead|manager|director|head of|vp)\b/i],
  ];

  const PROVINCE_PATTERNS = [
    ["ON", /\b(?:ontario|\bon\b)\b/i],
    ["BC", /\b(?:british columbia|\bbc\b)\b/i],
    ["QC", /\b(?:quebec|québec|\bqc\b)\b/i],
    ["AB", /\b(?:alberta|\bab\b)\b/i],
    ["MB", /\b(?:manitoba|\bmb\b)\b/i],
    ["SK", /\b(?:saskatchewan|\bsk\b)\b/i],
    ["NS", /\b(?:nova scotia|\bns\b)\b/i],
  ];

  function emptyProfile() {
    return {
      current_title: "",
      desired_titles: [],
      years_experience: null,
      skills: [],
      disciplines: [],
      seniority: [],
      preferred_locations: [],
      work_arrangements: [],
      minimum_salary_cad: 0,
      include_undisclosed_salary: true,
    };
  }

  function extractSkills(text) {
    const found = [];
    const blob = String(text || "");
    for (const [label, patterns] of TECH_ALIASES) {
      if (patterns.some((p) => p.test(blob)) && !found.includes(label)) {
        found.push(label);
      }
    }
    return found;
  }

  function extractDisciplines(text) {
    const found = [];
    const blob = String(text || "");
    for (const d of DISCIPLINES) {
      if (d.patterns.some((p) => p.test(blob)) && !found.includes(d.id)) {
        found.push(d.id);
      }
    }
    return found;
  }

  function extractSeniority(text) {
    const found = [];
    const blob = String(text || "");
    for (const [label, pattern] of SENIORITY_PATTERNS) {
      if (pattern.test(blob) && !found.includes(label)) found.push(label);
    }
    return found;
  }

  function extractYears(text) {
    const blob = String(text || "");
    const m =
      blob.match(/(\d{1,2})\+?\s*(?:\+)?\s*(?:years?|yrs?)\s+(?:of\s+)?(?:experience|exp)/i) ||
      blob.match(/(?:experience|exp)[:\s]+(\d{1,2})\+?\s*(?:years?|yrs?)/i);
    if (!m) return null;
    const n = Number(m[1]);
    return Number.isFinite(n) && n >= 0 && n <= 50 ? n : null;
  }

  function extractTitle(text) {
    const lines = String(text || "")
      .split(/\r?\n/)
      .map((l) => l.trim())
      .filter(Boolean);
    for (const line of lines.slice(0, 12)) {
      if (/engineer|developer|scientist|architect|sre|devops/i.test(line) && line.length < 80) {
        return line.replace(/^[-•*\d.\s]+/, "").slice(0, 80);
      }
    }
    return lines[0] ? lines[0].slice(0, 80) : "";
  }

  function extractLocations(text) {
    const found = [];
    const blob = String(text || "");
    for (const [code, pattern] of PROVINCE_PATTERNS) {
      if (pattern.test(blob) && !found.includes(code)) found.push(code);
    }
    if (/\btoronto\b/i.test(blob) && !found.includes("Toronto")) found.push("Toronto");
    if (/\bvancouver\b/i.test(blob) && !found.includes("Vancouver")) found.push("Vancouver");
    if (/\bmontr[eé]al\b/i.test(blob) && !found.includes("Montreal")) found.push("Montreal");
    if (/\bcalgary\b/i.test(blob) && !found.includes("Calgary")) found.push("Calgary");
    if (/\bcanada\b/i.test(blob) && !found.includes("Canada")) found.push("Canada");
    return found;
  }

  function extractArrangements(text) {
    const blob = String(text || "");
    const found = [];
    if (/\bremote\b/i.test(blob)) found.push("remote");
    if (/\bhybrid\b/i.test(blob)) found.push("hybrid");
    if (/\b(?:on[\s-]?site|in[\s-]?office)\b/i.test(blob)) found.push("onsite");
    return found;
  }

  function extractProfileFromText(text) {
    const profile = emptyProfile();
    const blob = String(text || "");
    if (!blob.trim()) return profile;
    profile.current_title = extractTitle(blob);
    profile.desired_titles = profile.current_title ? [profile.current_title] : [];
    profile.years_experience = extractYears(blob);
    profile.skills = extractSkills(blob);
    profile.disciplines = extractDisciplines(blob);
    profile.seniority = extractSeniority(blob);
    profile.preferred_locations = extractLocations(blob);
    profile.work_arrangements = extractArrangements(blob);
    return profile;
  }

  function salaryMaxCad(job, fx) {
    const rate = Number(fx) > 0 ? Number(fx) : DEFAULT_FX;
    if (job.salary_max_cad != null && Number.isFinite(Number(job.salary_max_cad))) {
      return Number(job.salary_max_cad);
    }
    if (!job.salary_available || job.salary_max == null) return null;
    const cur = String(job.salary_currency || "").toUpperCase();
    const hi = Number(job.salary_max);
    if (!Number.isFinite(hi)) return null;
    if (cur === "CAD") return hi;
    if (cur === "USD") return hi * rate;
    return null;
  }

  /**
   * @returns {{pass:boolean, reason:string, meets_with_max_only:boolean}}
   */
  function salaryFilterPass(job, minimumCad, includeUndisclosed, fx) {
    const min = Math.max(0, Number(minimumCad) || 0);
    if (min <= 0) {
      return { pass: true, reason: "no minimum", meets_with_max_only: false };
    }
    if (!job.salary_available) {
      return {
        pass: !!includeUndisclosed,
        reason: includeUndisclosed ? "undisclosed included" : "undisclosed excluded",
        meets_with_max_only: false,
      };
    }
    const maxCad = salaryMaxCad(job, fx);
    if (maxCad == null) {
      return {
        pass: !!includeUndisclosed,
        reason: "incomparable compensation",
        meets_with_max_only: false,
      };
    }
    if (maxCad < min) {
      return { pass: false, reason: "below minimum", meets_with_max_only: false };
    }
    const minCad =
      job.salary_min != null
        ? String(job.salary_currency || "").toUpperCase() === "USD"
          ? Number(job.salary_min) * (Number(fx) > 0 ? Number(fx) : DEFAULT_FX)
          : Number(job.salary_min)
        : maxCad;
    const meetsWithMaxOnly = Number.isFinite(minCad) && minCad < min && maxCad >= min;
    return {
      pass: true,
      reason: meetsWithMaxOnly ? "max meets minimum" : "meets minimum",
      meets_with_max_only: meetsWithMaxOnly,
    };
  }

  function normalizeSkill(s) {
    return String(s || "").trim();
  }

  function jobSkillSet(job) {
    const fromTech = Array.isArray(job.technologies) ? job.technologies : [];
    const fromTitle = extractSkills(job.title || "");
    const set = new Set();
    for (const s of [...fromTech, ...fromTitle]) {
      const n = normalizeSkill(s);
      if (n) set.add(n);
    }
    // Alias folding for overlap
    if (set.has("Node")) set.add("Node.js");
    if (set.has("Node.js")) set.add("Node");
    return set;
  }

  function titleRelevance(profile, job) {
    const norm = (t) => String(t || "").toLowerCase();
    const titles = [profile.current_title, ...(profile.desired_titles || [])]
      .map(norm)
      .filter(Boolean);
    const jobTitle = norm(job.title);
    if (!titles.length) return 0.5; // neutral when unknown
    let best = 0;
    for (const nt of titles) {
      if (jobTitle.includes(nt) || nt.includes(jobTitle)) best = Math.max(best, 1);
      else {
        const tokens = nt.split(/[^a-z0-9+#.]+/).filter((x) => x.length > 2);
        if (!tokens.length) continue;
        const hit = tokens.filter((tok) => jobTitle.includes(tok)).length;
        best = Math.max(best, hit / tokens.length);
      }
    }
    return best;
  }

  function skillOverlap(profile, job) {
    const skills = (profile.skills || []).map(normalizeSkill).filter(Boolean);
    if (!skills.length) return { score: 0.5, matched: [], unconfirmed: [] };
    const jobSkills = jobSkillSet(job);
    const matched = [];
    const unconfirmed = [];
    for (const s of skills) {
      const hit =
        jobSkills.has(s) ||
        [...jobSkills].some((js) => js.toLowerCase() === s.toLowerCase());
      if (hit) matched.push(s);
      else unconfirmed.push(s); // not evidenced in listing — not a confirmed gap
    }
    const score = matched.length / skills.length;
    return { score, matched, unconfirmed };
  }

  function seniorityScore(profile, job) {
    const wanted = (profile.seniority || []).map((s) => String(s).toLowerCase());
    const jobSen = String(job.seniority || "").toLowerCase();
    if (!wanted.length) return 0.5;
    if (!jobSen) return 0.55; // unknown job seniority — not a hard miss
    if (wanted.includes(jobSen)) return 1;
    // adjacent bands
    const order = ["junior", "mid", "senior", "staff", "principal", "lead"];
    const ji = order.indexOf(jobSen);
    if (ji < 0) return 0.4;
    const dists = wanted.map((w) => {
      const wi = order.indexOf(w);
      return wi < 0 ? 3 : Math.abs(wi - ji);
    });
    const d = Math.min(...dists);
    if (d === 0) return 1;
    if (d === 1) return 0.7;
    if (d === 2) return 0.4;
    return 0.15;
  }

  function disciplineScore(profile, job) {
    const wanted = profile.disciplines || [];
    if (!wanted.length) return 0.5;
    const track = job.track || "";
    if (!track) return 0.55;
    if (wanted.includes(track)) return 1;
    // soft adjacent
    const adjacent = {
      software_engineering: ["platform_engineering", "devops_sre"],
      data_engineering: ["analytics_engineering", "ml_engineering"],
      ml_engineering: ["data_engineering", "ai_engineering"],
      platform_engineering: ["devops_sre", "cloud_engineering", "software_engineering"],
      devops_sre: ["platform_engineering", "cloud_engineering"],
    };
    for (const w of wanted) {
      if ((adjacent[w] || []).includes(track)) return 0.65;
    }
    return 0.2;
  }

  function arrangementScore(profile, job) {
    const wanted = profile.work_arrangements || [];
    if (!wanted.length) return 0.5;
    const arr = job.work_arrangement || "unspecified";
    if (arr === "unspecified") return 0.55;
    return wanted.includes(arr) ? 1 : 0.25;
  }

  function locationHardFilter(profile, job) {
    // Public jobs are already Canada-eligible. Additional user province prefs.
    const prefs = profile.preferred_locations || [];
    if (!prefs.length) return { ok: true, reason: "no location preference" };
    const codes = prefs.filter((p) => /^[A-Z]{2}$/.test(p));
    const cities = prefs.filter((p) => !/^[A-Z]{2}$/.test(p)).map((p) => p.toLowerCase());
    if (job.remote_scope === "canada" && job.work_arrangement === "remote") {
      return { ok: true, reason: "canada-wide remote" };
    }
    if (codes.length) {
      if (job.province && codes.includes(job.province)) {
        return { ok: true, reason: "province match" };
      }
      // Province-restricted remote outside preference → ineligible
      if (job.remote_scope === "province" && job.province && !codes.includes(job.province)) {
        return { ok: false, reason: "province-restricted remote outside preference" };
      }
      // Local hybrid/onsite outside province
      if (job.work_arrangement !== "remote" && job.province && !codes.includes(job.province)) {
        // still allow if city matches
        const loc = String(job.location || "").toLowerCase();
        if (cities.some((c) => c !== "canada" && loc.includes(c.toLowerCase()))) {
          return { ok: true, reason: "city match" };
        }
        return { ok: false, reason: "location outside preferred provinces" };
      }
    }
    if (cities.length) {
      const loc = String(job.location || "").toLowerCase();
      if (cities.includes("canada")) return { ok: true, reason: "canada preference" };
      if (cities.some((c) => loc.includes(c))) return { ok: true, reason: "city match" };
    }
    return { ok: true, reason: "location soft-pass" };
  }

  /**
   * @returns {{status:'confirmed'|'possible'|'ineligible', score:number, percent:number, matched_skills:string[], unconfirmed_skills:string[], reasons:string[], salary_note:string|null, meets_with_max_only:boolean}}
   */
  function scoreJob(profile, job, fx) {
    const sal = salaryFilterPass(
      job,
      profile.minimum_salary_cad || 0,
      profile.include_undisclosed_salary !== false,
      fx
    );
    if (!sal.pass) {
      return {
        status: "ineligible",
        score: 0,
        percent: 0,
        matched_skills: [],
        unconfirmed_skills: [],
        reasons: [`Salary: ${sal.reason}`],
        salary_note: null,
        meets_with_max_only: false,
      };
    }
    const loc = locationHardFilter(profile, job);
    if (!loc.ok) {
      return {
        status: "ineligible",
        score: 0,
        percent: 0,
        matched_skills: [],
        unconfirmed_skills: [],
        reasons: [`Location: ${loc.reason}`],
        salary_note: null,
        meets_with_max_only: sal.meets_with_max_only,
      };
    }

    const title = titleRelevance(profile, job);
    const skills = skillOverlap(profile, job);
    const sen = seniorityScore(profile, job);
    const disc = disciplineScore(profile, job);
    const arr = arrangementScore(profile, job);
    const other = (arr + (loc.reason.includes("match") || loc.reason.includes("canada") ? 1 : 0.5)) / 2;

    const score =
      title * 0.3 + skills.score * 0.3 + sen * 0.15 + disc * 0.15 + other * 0.1;
    const percent = Math.round(Math.max(0, Math.min(1, score)) * 100);

    const reasons = [];
    if (title >= 0.7) reasons.push("Title aligns with your experience");
    if (skills.matched.length) reasons.push(`Skills evidenced: ${skills.matched.slice(0, 5).join(", ")}`);
    if (disc >= 0.9) reasons.push("Discipline matches your preferred tracks");
    if (sen >= 0.9) reasons.push("Seniority compatible");
    if (job.remote_scope === "canada" && job.work_arrangement === "remote") {
      reasons.push("Canada-wide remote");
    } else if (job.remote_scope === "province") {
      reasons.push("Province-scoped remote (not Canada-wide)");
    }
    if (sal.meets_with_max_only) {
      reasons.push("Advertised max meets your salary minimum (range low end is below)");
    }

    // Insufficient listing metadata → possible rather than confirmed
    const thinListing =
      (!job.technologies || job.technologies.length === 0) &&
      (!job.seniority || job.seniority === "") &&
      skills.matched.length === 0;
    let status = "confirmed";
    if (percent < 45) status = "possible";
    if (thinListing && percent < 70) status = "possible";

    return {
      status,
      score,
      percent,
      matched_skills: skills.matched,
      unconfirmed_skills: skills.unconfirmed,
      reasons: reasons.length ? reasons : ["Partial overlap with your profile"],
      salary_note: sal.meets_with_max_only ? "Max of range meets your minimum" : null,
      meets_with_max_only: sal.meets_with_max_only,
    };
  }

  function matchJobs(profile, jobs, opts) {
    const fx = (opts && opts.fx) || DEFAULT_FX;
    const limit = (opts && opts.limit) || 50;
    const results = [];
    const seen = new Set();
    for (const job of jobs || []) {
      const key = `${String(job.company || "").toLowerCase()}|${String(job.title || "").toLowerCase()}`;
      if (seen.has(key)) continue;
      seen.add(key);
      const m = scoreJob(profile, job, fx);
      if (m.status === "ineligible") continue;
      results.push({ job, match: m });
    }
    results.sort((a, b) => b.match.percent - a.match.percent || a.job.company.localeCompare(b.job.company));
    return results.slice(0, limit);
  }

  function filterBrowseJobs(jobs, filters, fx) {
    const q = String(filters.query || "").trim().toLowerCase();
    const province = filters.province || "";
    const arrangement = filters.arrangement || "";
    const seniority = filters.seniority || "";
    const minSal = Number(filters.minimum_salary_cad) || 0;
    const includeUndisclosed = filters.include_undisclosed_salary !== false;
    const sort = filters.sort || "salary";

    let out = (jobs || []).filter((job) => {
      if (q) {
        const hay = [job.title, job.company, job.location, ...(job.technologies || []), job.track || ""]
          .join(" ")
          .toLowerCase();
        if (!q.split(/\s+/).filter(Boolean).every((tok) => hay.includes(tok))) return false;
      }
      if (province && job.province !== province) return false;
      if (arrangement && job.work_arrangement !== arrangement) return false;
      if (seniority && job.seniority !== seniority) return false;
      const sal = salaryFilterPass(job, minSal, includeUndisclosed, fx);
      return sal.pass;
    });

    out = out.slice();
    if (sort === "salary") {
      out.sort((a, b) => {
        const ac = salaryMaxCad(a, fx);
        const bc = salaryMaxCad(b, fx);
        if (ac == null && bc == null) return a.company.localeCompare(b.company);
        if (ac == null) return 1;
        if (bc == null) return -1;
        return bc - ac;
      });
    } else if (sort === "recent") {
      out.sort((a, b) => String(b.first_seen || "").localeCompare(String(a.first_seen || "")));
    } else if (sort === "company") {
      out.sort((a, b) => a.company.localeCompare(b.company) || a.title.localeCompare(b.title));
    }
    return out.map((job) => {
      const sal = salaryFilterPass(job, minSal, includeUndisclosed, fx);
      return { job, salary_meta: sal };
    });
  }

  return {
    DEFAULT_FX,
    SALARY_MAX_UI,
    SALARY_STEP,
    DISCIPLINES,
    emptyProfile,
    extractProfileFromText,
    extractSkills,
    salaryMaxCad,
    salaryFilterPass,
    scoreJob,
    matchJobs,
    filterBrowseJobs,
  };
});
