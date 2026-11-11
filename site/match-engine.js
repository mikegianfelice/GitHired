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

  // Keep in sync with jobseek/skills/tech_extract.py (canonical labels).
  // Profile résumé extraction: PostgreSQL/MySQL also add SQL for the person.
  const TECH_ALIASES = [
    ["Python", [/\bpython\b/i, /\bpyspark\b/i]],
    ["SQL", [/\bsql\b/i, /\bpl\/?sql\b/i, /\bpostgres(?:ql)?\b/i, /\bmysql\b/i]],
    ["SQL Server", [/\bt-?sql\b/i, /\bsql\s*server\b/i, /\bmssql\b/i, /\bms[\s-]?sql\b/i]],
    ["PostgreSQL", [/\bpostgres(?:ql)?\b/i]],
    ["MySQL", [/\bmysql\b/i]],
    ["Redis", [/\bredis(?:\s+cache)?\b/i]],
    ["MongoDB", [/\bmongo(?:db)?\b/i]],
    ["ClickHouse", [/\bclickhouse\b/i]],
    ["Elasticsearch", [/\belasticsearch\b/i]],
    ["OpenSearch", [/\bopensearch\b/i]],
    ["BigQuery", [/\bbigquery\b/i, /\bbig\s*query\b/i]],
    ["PySpark", [/\bpyspark\b/i]],
    ["JavaScript", [/\bjavascript\b/i, /\b(?<![a-z])js(?![a-z])\b/i]],
    ["TypeScript", [/\btypescript\b/i, /\b(?<![a-z])ts(?![a-z])\b/i]],
    ["Java", [/\bjava\b/i]],
    ["Go", [/\bgolang\b/i, /\bgo(?:lang)?\s+(?:engineer|developer)\b/i, /\bgo(?:lang)?\b/i]],
    ["Rust", [/\brust\b/i]],
    ["React", [/\breact(?:\.?js)?\b/i]],
    ["Next.js", [/\bnext\.?js\b/i]],
    ["Node.js", [/\bnode\.?js\b/i]],
    ["GraphQL", [/\bgraphql\b/i]],
    ["gRPC", [/\bgrpc\b/i]],
    ["AWS", [/\baws\b/i, /\bamazon web services\b/i]],
    ["Azure", [/\bazure\b/i]],
    ["GCP", [/\bgcp\b/i, /\bgoogle cloud(?:\s+platform)?\b/i]],
    ["Databricks", [/\bdatabricks\b/i]],
    ["Snowflake", [/\bsnowflake\b/i]],
    ["Delta Lake", [/\bdelta\s*lake\b/i]],
    ["Spark", [/\bspark\b/i, /\bpyspark\b/i]],
    ["Kubernetes", [/\bkubernetes\b/i, /\bk8s\b/i]],
    ["Docker", [/\bdocker\b/i]],
    ["Helm", [/\bhelm\b/i]],
    ["Terraform", [/\bterraform\b/i]],
    ["Ansible", [/\bansible\b/i]],
    ["Airflow", [/\bairflow\b/i]],
    ["dbt", [/\bdbt\b/i]],
    ["Kafka", [/\bkafka\b/i]],
    ["Control-M", [/\bcontrol[\s-]?m\b/i, /\bcontrolm\b/i]],
    ["GitHub Actions", [/\bgithub\s+actions\b/i, /\bgh\s+actions\b/i]],
    ["Jenkins", [/\bjenkins\b/i]],
    ["CI/CD", [/\bci\s*\/\s*cd\b/i, /\bci-cd\b/i]],
    ["Prometheus", [/\bprometheus\b/i]],
    ["Grafana", [/\bgrafana\b/i]],
    ["PyTorch", [/\bpytorch\b/i]],
    ["TensorFlow", [/\btensorflow\b/i]],
    ["Machine Learning", [/\bmachine\s+learning\b/i]],
    ["LLM", [/\bllm\b/i, /\blarge language models?\b/i]],
    ["LangChain", [/\blangchain\b/i]],
    ["LangGraph", [/\blanggraph\b/i]],
    ["RAG", [/\bretrieval[\-\s]augmented(?:\s+generation)?\b/i, /\brag\b/i]],
    ["MCP", [/\bmodel\s+context\s+protocol\b/i, /\bmcp\b/i]],
    ["Tableau", [/\btableau\b/i]],
    ["Power BI", [/\bpower\s*bi\b/i]],
  ];

  const SKILL_ALIASES = {
    plsql: "SQL",
    "pl/sql": "SQL",
    tsql: "SQL Server",
    "t-sql": "SQL Server",
    "sql server": "SQL Server",
    sqlserver: "SQL Server",
    mssql: "SQL Server",
    "ms sql": "SQL Server",
    postgres: "PostgreSQL",
    postgresql: "PostgreSQL",
    mysql: "MySQL",
    "node.js": "Node.js",
    nodejs: "Node.js",
    node: "Node.js",
    golang: "Go",
    k8s: "Kubernetes",
    pyspark: "PySpark",
    "control m": "Control-M",
    controlm: "Control-M",
    "control-m": "Control-M",
    "google cloud": "GCP",
    "google cloud platform": "GCP",
    "github actions": "GitHub Actions",
    "gh actions": "GitHub Actions",
    "ci cd": "CI/CD",
    "ci-cd": "CI/CD",
    "next.js": "Next.js",
    nextjs: "Next.js",
    "power bi": "Power BI",
    powerbi: "Power BI",
    "machine learning": "Machine Learning",
    "model context protocol": "MCP",
  };

  // Conservative exact-match related hits (broad ≠ specific).
  const RELATED_SKILLS = {
    PostgreSQL: ["SQL"],
    MySQL: ["SQL"],
    "SQL Server": ["SQL"],
    PySpark: ["Python", "Spark"],
    "Node.js": ["JavaScript", "Node"],
    Node: ["Node.js", "JavaScript"],
    JavaScript: ["Node.js"],
  };

  const JOB_SKILL_EXPAND = {
    PySpark: ["Python", "Spark"],
    "SQL Server": ["SQL"],
    Node: ["Node.js"],
    "Node.js": ["Node"],
  };

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
      // Website default: advertised min must meet floor. API/MCP default remains flexible.
      salary_filter_mode: "strict",
    };
  }

  const SENIORITY_STOP = new Set([
    "senior",
    "sr",
    "junior",
    "jr",
    "staff",
    "principal",
    "lead",
    "intern",
    "entry",
    "mid",
    "intermediate",
    "level",
  ]);

  const BAND_YEARS = {
    intern: 0,
    junior: 1,
    mid: 3,
    senior: 6,
    staff: 9,
    principal: 12,
    lead: 8,
  };

  function inferSeniorityFromYears(years) {
    if (years == null || !Number.isFinite(years) || years < 0) return null;
    if (years < 2) return "junior";
    if (years < 5) return "mid";
    if (years < 8) return "senior";
    if (years < 12) return "staff";
    return "principal";
  }

  function roleFamilyTokens(text) {
    return String(text || "")
      .toLowerCase()
      .split(/[^a-z0-9+#.]+/)
      .filter((t) => t.length > 2 && !SENIORITY_STOP.has(t));
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
   * @param {"strict"|"flexible"|undefined} mode — strict: advertised min must meet floor;
   *   flexible: advertised max may meet floor. Default flexible for call-site compat;
   *   website profiles default salary_filter_mode to strict.
   * @returns {{pass:boolean, reason:string, meets_with_max_only:boolean}}
   */
  function salaryFilterPass(job, minimumCad, includeUndisclosed, fx, mode) {
    const min = Math.max(0, Number(minimumCad) || 0);
    const filterMode = mode === "strict" ? "strict" : "flexible";
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
    const rate = Number(fx) > 0 ? Number(fx) : DEFAULT_FX;
    const minCad =
      job.salary_min != null
        ? String(job.salary_currency || "").toUpperCase() === "USD"
          ? Number(job.salary_min) * rate
          : Number(job.salary_min)
        : maxCad;
    const meetsWithMaxOnly = Number.isFinite(minCad) && minCad < min && maxCad >= min;
    if (filterMode === "strict" && meetsWithMaxOnly) {
      return {
        pass: false,
        reason: "range starts below minimum",
        meets_with_max_only: true,
      };
    }
    return {
      pass: true,
      reason: meetsWithMaxOnly ? "max meets minimum" : "meets minimum",
      meets_with_max_only: meetsWithMaxOnly,
    };
  }

  function normalizeSkill(s) {
    const raw = String(s || "").trim();
    if (!raw) return "";
    const key = raw
      .toLowerCase()
      .replace(/_/g, " ")
      .replace(/[\/\-]+/g, " ")
      .replace(/\s+/g, " ")
      .trim();
    if (SKILL_ALIASES[key]) return SKILL_ALIASES[key];
    for (const [label] of TECH_ALIASES) {
      if (label.toLowerCase() === key || label.toLowerCase() === raw.toLowerCase()) return label;
    }
    return raw;
  }

  function jobSkillSet(job) {
    const fromTech = Array.isArray(job.technologies) ? job.technologies : [];
    const fromTitle = extractSkills(job.title || "");
    const set = new Set();
    for (const s of [...fromTech, ...fromTitle]) {
      const n = normalizeSkill(s);
      if (n) set.add(n);
    }
    for (const s of [...set]) {
      for (const r of JOB_SKILL_EXPAND[s] || []) set.add(r);
    }
    return set;
  }

  function tokenInTitle(title, token) {
    // Whole-token match only — "data" must not hit "datastores" / "database".
    const parts = new Set([
      ...roleFamilyTokens(title),
      ...String(title || "")
        .toLowerCase()
        .split(/[^a-z0-9+#.]+/)
        .filter((t) => t.length > 1),
    ]);
    return parts.has(token);
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
      if (jobTitle.includes(nt) || nt.includes(jobTitle)) {
        best = Math.max(best, 1);
        continue;
      }
      // Prefer role-family tokens (strip seniority) so "Senior Data Engineer"
      // aligns with "Lead Data Engineer" / "Senior Data Platform Engineer".
      const family = roleFamilyTokens(nt);
      if (family.length) {
        const hit = family.filter((tok) => tokenInTitle(jobTitle, tok)).length;
        best = Math.max(best, hit / family.length);
        continue;
      }
      const tokens = nt.split(/[^a-z0-9+#.]+/).filter((x) => x.length > 2);
      if (!tokens.length) continue;
      const hit = tokens.filter((tok) => tokenInTitle(jobTitle, tok)).length;
      best = Math.max(best, hit / tokens.length);
    }
    return best;
  }

  function skillOverlap(profile, job) {
    const skills = (profile.skills || []).map(normalizeSkill).filter(Boolean);
    if (!skills.length) return { score: 0.5, matched: [], unconfirmed: [] };
    const jobSkills = jobSkillSet(job);
    const matched = [];
    const unconfirmed = [];
    const seen = new Set();
    for (const s of skills) {
      if (seen.has(s)) continue;
      seen.add(s);
      const related = RELATED_SKILLS[s] || [];
      const hit =
        jobSkills.has(s) ||
        related.some((r) => jobSkills.has(r)) ||
        [...jobSkills].some((js) => js.toLowerCase() === s.toLowerCase());
      if (hit) matched.push(s);
      else unconfirmed.push(s); // not evidenced in listing — not a confirmed gap
    }
    const score = matched.length / skills.length;
    return { score, matched, unconfirmed };
  }

  function seniorityScore(profile, job) {
    let wanted = (profile.seniority || []).map((s) => String(s).toLowerCase());
    const inferred = inferSeniorityFromYears(profile.years_experience);
    if (!wanted.length && inferred) wanted = [inferred];
    const jobSen = String(job.seniority || "").toLowerCase();
    if (!wanted.length) return { score: 0.5, note: null };
    if (!jobSen) return { score: 0.55, note: "Job seniority unspecified — compatibility uncertain" };

    const order = ["junior", "mid", "senior", "staff", "principal", "lead", "intern"];
    let band = 0.4;
    if (wanted.includes(jobSen)) band = 1;
    else {
      const ji = order.indexOf(jobSen);
      if (ji >= 0) {
        const dists = wanted.map((w) => {
          const wi = order.indexOf(w);
          return wi < 0 ? 3 : Math.abs(wi - ji);
        });
        const d = Math.min(...dists);
        if (d === 0) band = 1;
        else if (d === 1) band = 0.7;
        else if (d === 2) band = 0.35;
        else band = 0.12;
      }
    }

    // Explicit years in the listing beat invented thresholds.
    const jobYears = extractYears(job.description_excerpt || job.description || "");
    const candYears = profile.years_experience;
    let mult = 1;
    let note = null;
    if (candYears != null && Number.isFinite(candYears) && jobYears != null) {
      const gap = jobYears - candYears;
      if (gap >= 4) {
        mult = 0.25;
        note = `Strong skill overlap possible, but this role may require more experience than your profile indicates (listing ~${jobYears}+ years; profile ${candYears})`;
      } else if (gap >= 2) {
        mult = 0.45;
        note = `Listing asks for ~${jobYears}+ years; your profile shows ${candYears}`;
      } else if (gap > 0) {
        mult = 0.75;
        note = `Listing asks for ~${jobYears}+ years; your profile shows ${candYears}`;
      }
    } else if (candYears != null && Number.isFinite(candYears) && jobSen && BAND_YEARS[jobSen] != null) {
      // Soft heuristic only — never invent a hard JD requirement.
      const gap = BAND_YEARS[jobSen] - candYears;
      if (gap >= 5) {
        mult = 0.35;
        note = `This ${jobSen} role typically expects more experience than your ${candYears} years indicate`;
      } else if (gap >= 3) {
        mult = 0.55;
        note = `Seniority band may require more experience than your profile indicates`;
      }
    } else if (!jobYears && candYears == null) {
      note = null;
    }

    return { score: Math.min(1, band * mult), note };
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
    if (!wanted.length) return { score: 0.5, ok: true };
    const arr = job.work_arrangement || "unspecified";
    if (arr === "unspecified" || arr === "unknown") {
      // Unknown: soft-allow (Canada eligibility already applied upstream).
      return { score: 0.55, ok: true };
    }
    if (wanted.includes(arr)) return { score: 1, ok: true };
    // Explicit allow-list is a hard filter when arrangements are selected.
    return { score: 0, ok: false };
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
    const salaryMode = profile.salary_filter_mode === "flexible" ? "flexible" : "strict";
    const sal = salaryFilterPass(
      job,
      profile.minimum_salary_cad || 0,
      profile.include_undisclosed_salary !== false,
      fx,
      salaryMode
    );
    if (!sal.pass) {
      return {
        status: "ineligible",
        score: 0,
        percent: 0,
        matched_skills: [],
        unconfirmed_skills: [],
        reasons: [`Salary: ${sal.reason}`],
        salary_note: sal.meets_with_max_only
          ? "Salary range overlaps your minimum, but starts below it"
          : null,
        meets_with_max_only: sal.meets_with_max_only,
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

    const arr = arrangementScore(profile, job);
    if (!arr.ok) {
      return {
        status: "ineligible",
        score: 0,
        percent: 0,
        matched_skills: [],
        unconfirmed_skills: [],
        reasons: [`Work arrangement ${job.work_arrangement || "unknown"} not in your allowed list`],
        salary_note: null,
        meets_with_max_only: sal.meets_with_max_only,
      };
    }

    const title = titleRelevance(profile, job);
    const skills = skillOverlap(profile, job);
    const sen = seniorityScore(profile, job);
    const disc = disciplineScore(profile, job);
    const hasTitlePref = !!(
      profile.current_title ||
      (profile.desired_titles && profile.desired_titles.length)
    );
    // Align with API/MCP: require role-family overlap when the user stated a title.
    // Strong discipline adjacency can soft-rescue near-miss titles as "possible".
    if (hasTitlePref && title < 0.6 && disc < 0.9) {
      return {
        status: "ineligible",
        score: 0,
        percent: 0,
        matched_skills: [],
        unconfirmed_skills: [],
        reasons: ["Title / role family does not sufficiently match your preferred roles"],
        salary_note: null,
        meets_with_max_only: sal.meets_with_max_only,
      };
    }
    const other =
      (arr.score + (loc.reason.includes("match") || loc.reason.includes("canada") ? 1 : 0.5)) / 2;

    // Weight seniority more heavily; large experience gaps must not look like strong matches.
    let score =
      title * 0.25 + skills.score * 0.25 + sen.score * 0.3 + disc * 0.1 + other * 0.1;
    if (sen.score < 0.4) {
      // Cap: staff/principal vs junior cannot land in the 80%+ band on skills alone.
      score = Math.min(score, 0.4 + sen.score * 0.25);
    }
    const percent = Math.round(Math.max(0, Math.min(1, score)) * 100);

    const reasons = [];
    if (title >= 0.7) reasons.push("Title aligns with your preferred role family");
    else if (title >= 0.5) reasons.push("Partial title / role-family overlap");
    if (skills.matched.length) {
      reasons.push(`Confirmed matching skills: ${skills.matched.slice(0, 5).join(", ")}`);
    }
    if (skills.unconfirmed.length) {
      reasons.push(
        `Skills not mentioned in the listing are unconfirmed, not necessarily missing: ${skills.unconfirmed.slice(0, 4).join(", ")}`
      );
    }
    if (disc >= 0.9) reasons.push("Discipline matches your preferred tracks");
    if (sen.note) reasons.push(sen.note);
    else if (sen.score >= 0.9) reasons.push("Seniority compatible");
    else if (sen.score < 0.5) {
      reasons.push("Seniority / experience may be a stretch for this listing");
    }
    if (job.remote_scope === "canada" && job.work_arrangement === "remote") {
      reasons.push("Canada-wide remote");
    } else if (job.remote_scope === "province") {
      reasons.push("Province-scoped remote (not Canada-wide)");
    }
    if (sal.meets_with_max_only) {
      reasons.push("Salary range overlaps your minimum, but starts below it");
    }

    // Insufficient listing metadata → possible rather than confirmed
    const thinListing =
      (!job.technologies || job.technologies.length === 0) &&
      (!job.seniority || job.seniority === "") &&
      skills.matched.length === 0;
    let status = "confirmed";
    if (percent < 45) status = "possible";
    if (thinListing && percent < 70) status = "possible";
    if (sen.score < 0.4 && percent >= 45) status = "possible";

    return {
      status,
      score,
      percent,
      matched_skills: skills.matched,
      unconfirmed_skills: skills.unconfirmed,
      reasons: reasons.length ? reasons : ["Partial overlap with your profile"],
      salary_note: sal.meets_with_max_only
        ? "Salary range overlaps your minimum, but starts below it"
        : null,
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

  function asFilterList(value) {
    if (Array.isArray(value)) return value.map(String).filter(Boolean);
    if (value == null || value === "") return [];
    return [String(value)];
  }

  function filterBrowseJobs(jobs, filters, fx) {
    const q = String(filters.query || "").trim().toLowerCase();
    // Accept plural arrays (preferred) or legacy single strings.
    const provinces = asFilterList(filters.provinces != null ? filters.provinces : filters.province);
    const arrangements = asFilterList(
      filters.arrangements != null ? filters.arrangements : filters.arrangement
    );
    const seniorities = asFilterList(
      filters.seniorities != null ? filters.seniorities : filters.seniority
    );
    const minSal = Number(filters.minimum_salary_cad) || 0;
    const includeUndisclosed = filters.include_undisclosed_salary !== false;
    // Browse UI defaults to strict when a minimum is set (advertised min must meet floor).
    const salaryMode = filters.salary_filter_mode === "flexible" ? "flexible" : "strict";
    // Default: newest verification date (last_verified). This is NOT the original
    // employer posting date — only when GitHired last confirmed the listing.
    const sort = filters.sort || "verified";

    let out = (jobs || []).filter((job) => {
      if (q) {
        const hay = [job.title, job.company, job.location, ...(job.technologies || []), job.track || ""]
          .join(" ")
          .toLowerCase();
        if (!q.split(/\s+/).filter(Boolean).every((tok) => hay.includes(tok))) return false;
      }
      if (provinces.length && !provinces.includes(job.province)) return false;
      if (arrangements.length && !arrangements.includes(job.work_arrangement)) return false;
      if (seniorities.length && !seniorities.includes(job.seniority)) return false;
      const sal = salaryFilterPass(job, minSal, includeUndisclosed, fx, salaryMode);
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
    } else if (sort === "verified" || sort === "recent") {
      // "verified" = last_verified desc; legacy "recent" = first_seen (discovery) desc.
      const key = sort === "recent" ? "first_seen" : "last_verified";
      out.sort((a, b) => {
        const av = String(a[key] || "");
        const bv = String(b[key] || "");
        if (bv !== av) return bv.localeCompare(av);
        // Stable tie-breakers
        const ac = salaryMaxCad(a, fx);
        const bc = salaryMaxCad(b, fx);
        if (ac != null && bc != null && bc !== ac) return bc - ac;
        return a.company.localeCompare(b.company) || a.title.localeCompare(b.title);
      });
    } else if (sort === "company") {
      out.sort((a, b) => a.company.localeCompare(b.company) || a.title.localeCompare(b.title));
    }
    return out.map((job) => {
      const sal = salaryFilterPass(job, minSal, includeUndisclosed, fx, salaryMode);
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
    extractYears,
    salaryMaxCad,
    salaryFilterPass,
    titleRelevance,
    seniorityScore,
    arrangementScore,
    scoreJob,
    matchJobs,
    filterBrowseJobs,
    asFilterList,
    inferSeniorityFromYears,
    roleFamilyTokens,
  };
});
