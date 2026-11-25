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

  // Profile specialization → broader job tag only (not PySpark→Python).
  const RELATED_SKILLS = {
    PostgreSQL: ["SQL"],
    MySQL: ["SQL"],
    "SQL Server": ["SQL"],
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

  const SHORT_ROLE_TOKENS = new Set(["ai", "ml", "bi", "qa", "ux", "ui", "sre", "de", "ae"]);
  const GENERIC_ROLE_TOKENS = new Set([
    "engineer",
    "developer",
    "software",
    "programmer",
    "specialist",
    "consultant",
    "manager",
    "associate",
    "member",
  ]);
  // Preferred-role specific tokens → job-title synonyms (title gate only).
  const SPECIFIC_TOKEN_ALIASES = {
    data: ["lakehouse", "etl"],
    ai: ["llm", "ml"],
    ml: ["ai", "llm"],
    deployed: ["forward"],
    forward: ["deployed"],
  };

  function roleFamilyTokens(text) {
    return String(text || "")
      .toLowerCase()
      .split(/[^a-z0-9+#.]+/)
      .filter((t) => {
        if (SENIORITY_STOP.has(t)) return false;
        if (t.length > 2) return true;
        return SHORT_ROLE_TOKENS.has(t);
      });
  }

  /**
   * True when index sits on a Not claimed / Exclude line or a wrapped continuation of one.
   */
  function inDeniedSection(blob, index) {
    let pos = index;
    for (let hops = 0; hops < 6 && pos >= 0; hops += 1) {
      const lineStart = blob.lastIndexOf("\n", pos - 1) + 1;
      let lineEnd = blob.indexOf("\n", lineStart);
      if (lineEnd < 0) lineEnd = blob.length;
      const line = blob.slice(lineStart, lineEnd);
      if (
        /^\s*(?:not\s+claimed|do\s+not\s+claim|don'?t\s+claim|exclude[ds]?|excluding)\b/i.test(line)
      ) {
        return true;
      }
      // Stop at blank lines or new ALL-CAPS / labeled sections.
      if (!line.trim()) return false;
      if (
        hops > 0 &&
        /^\s*(?:technical skills|professional (?:summary|experience)|education|job search|core:|cloud and|analytics:|[A-Z][A-Z0-9 /&-]{3,})\s*$/i.test(
          line.trim()
        )
      ) {
        return false;
      }
      if (lineStart === 0) return false;
      pos = lineStart - 1;
    }
    return false;
  }

  /**
   * Classify a keyword hit as confirmed, denied, or aspirational using local context.
   * Used for skills, seniority tokens, disciplines, and arrangements.
   */
  function mentionStatus(text, index) {
    const blob = String(text || "");
    if (index < 0 || index >= blob.length) return "denied";
    const lineStart = blob.lastIndexOf("\n", index - 1) + 1;
    let lineEnd = blob.indexOf("\n", index);
    if (lineEnd < 0) lineEnd = blob.length;
    const line = blob.slice(lineStart, lineEnd);
    const before = blob.slice(Math.max(0, index - 160), index).replace(/\s+/g, " ");
    const sentStart = Math.max(
      blob.lastIndexOf(".", index - 1) + 1,
      blob.lastIndexOf(";", index - 1) + 1,
      lineStart
    );
    let sentEnd = blob.length;
    for (const ch of [".", ";", "\n"]) {
      const at = blob.indexOf(ch, index);
      if (at >= 0 && at < sentEnd) sentEnd = at;
    }
    const sentence = blob.slice(sentStart, sentEnd);

    if (inDeniedSection(blob, index)) return "denied";
    if (
      /^\s*(?:not\s+claimed|do\s+not\s+claim|don'?t\s+claim|exclude[ds]?|excluding)\b/i.test(line)
    ) {
      return "denied";
    }
    // "no production LLM", "without Kubernetes", "never used Java",
    // "no professional experience with Kubernetes, Java, or Azure", etc.
    if (
      /\b(?:no|not|without|never|lack(?:ing)?|zero)\b(?:\s+(?:professional|production|hands[\s-]?on|prior|direct|real[\s-]?world))?(?:[\s\w,/+&|.-]{0,80})$/i.test(
        before
      )
    ) {
      return "denied";
    }
    if (/\bno\s+professional\s+experience\s+with\b/i.test(before)) {
      return "denied";
    }
    if (/\b(?:exclude[ds]?|excluding|except(?:\s+for)?)\b[\w\s,/+.-]{0,100}$/i.test(before)) {
      return "denied";
    }
    if (
      /\b(?:interested\s+in\s+learning|want(?:s)?\s+to\s+learn|hoping\s+to\s+learn|plan(?:s|ning)?\s+to\s+learn|currently\s+learning)\b/i.test(
        sentence
      ) &&
      !/\b(?:built|developed|implemented|used|using|hands[\s-]?on|production|professional\s+experience)\b/i.test(
        sentence
      )
    ) {
      return "aspirational";
    }
    return "confirmed";
  }

  function eachMatch(blob, pattern, fn) {
    const flags = pattern.flags.includes("g") ? pattern.flags : `${pattern.flags}g`;
    const re = new RegExp(pattern.source, flags);
    let m;
    while ((m = re.exec(blob)) !== null) {
      fn(m);
      if (m.index === re.lastIndex) re.lastIndex += 1;
    }
  }

  function extractSkills(text) {
    const found = [];
    const blob = String(text || "");
    for (const [label, patterns] of TECH_ALIASES) {
      let confirmed = false;
      for (const p of patterns) {
        eachMatch(blob, p, (m) => {
          if (!confirmed && mentionStatus(blob, m.index) === "confirmed") confirmed = true;
        });
        if (confirmed) break;
      }
      if (confirmed && !found.includes(label)) found.push(label);
    }
    return found;
  }

  function extractDisciplines(text) {
    const found = [];
    const blob = String(text || "");
    for (const d of DISCIPLINES) {
      let confirmed = false;
      for (const p of d.patterns) {
        eachMatch(blob, p, (m) => {
          if (!confirmed && mentionStatus(blob, m.index) === "confirmed") confirmed = true;
        });
        if (confirmed) break;
      }
      if (confirmed && !found.includes(d.id)) found.push(d.id);
    }
    return found;
  }

  function extractSeniorityRaw(text) {
    const found = [];
    const blob = String(text || "");
    for (const [label, pattern] of SENIORITY_PATTERNS) {
      eachMatch(blob, pattern, (m) => {
        if (mentionStatus(blob, m.index) === "confirmed" && !found.includes(label)) {
          found.push(label);
        }
      });
    }
    return found;
  }

  function resolveSeniorityBands(raw, years, title) {
    const order = ["intern", "junior", "mid", "senior", "staff", "principal", "lead"];
    const titleBands = extractSeniorityRaw(String(title || ""));
    let bands = raw.slice();
    const inferred = inferSeniorityFromYears(years);

    if (years != null && Number.isFinite(years)) {
      if (years >= 5) bands = bands.filter((b) => b !== "junior" && b !== "intern");
      if (years < 2) bands = bands.filter((b) => !["senior", "staff", "principal", "lead"].includes(b));
    }
    // Prefer title-derived bands when present.
    if (titleBands.length) {
      bands = [...new Set([...titleBands, ...bands.filter((b) => titleBands.includes(b))])];
      if (years != null && years >= 5) {
        bands = bands.filter((b) => b !== "junior" && b !== "intern");
      }
    }
    if (!bands.length && inferred) bands = [inferred];
    if (inferred && !bands.includes(inferred)) {
      const oi = order.indexOf(inferred);
      const near = bands.some((b) => Math.abs(order.indexOf(b) - oi) <= 1);
      if (!near || !bands.length) bands = [inferred, ...bands];
    }
    // Conflicting junior+senior from noisy text → keep the more senior signal.
    if (bands.includes("senior") || bands.includes("staff") || bands.includes("principal")) {
      bands = bands.filter((b) => b !== "junior" && b !== "intern");
    }
    return bands;
  }

  function extractSeniority(text) {
    return extractSeniorityRaw(text);
  }

  function extractYears(text) {
    const blob = String(text || "");
    const m =
      blob.match(
        /(\d{1,2})\+?\s*(?:\+)?\s*(?:years?|yrs?)\s+(?:of\s+)?(?:(?:professional|relevant|industry|total|combined)\s+)?(?:experience|exp)\b/i
      ) ||
      blob.match(/(?:experience|exp)[:\s]+(\d{1,2})\+?\s*(?:years?|yrs?)/i) ||
      blob.match(/(\d{1,2})\+?\s*(?:years?|yrs?)\s+(?:of\s+)?(?:professional|relevant|industry)\b/i);
    if (!m) return null;
    const n = Number(m[1]);
    return Number.isFinite(n) && n >= 0 && n <= 50 ? n : null;
  }

  function extractTitle(text) {
    const lines = String(text || "")
      .split(/\r?\n/)
      .map((l) => l.trim())
      .filter(Boolean);
    const roleRe = /engineer|developer|scientist|architect|sre|devops|analyst/i;
    for (const line of lines.slice(0, 16)) {
      // "Senior Data Engineer | Toronto | email" — take the role segment.
      const rolePart = line.split("|")[0].trim().replace(/^[-•*\d.\s]+/, "");
      if (roleRe.test(rolePart) && rolePart.length < 80) {
        // Skip lines that are mostly a person name + role jammed without separators when too long overall
        return rolePart.slice(0, 80);
      }
      if (roleRe.test(line) && line.length < 100) {
        return line.replace(/^[-•*\d.\s]+/, "").slice(0, 80);
      }
    }
    return "";
  }

  function extractDesiredTitles(text, fallbackTitle) {
    const blob = String(text || "");
    // Stop before ". Location" / newline so wrapped preference lines don't leak.
    const m = blob.match(
      /preferred titles?\s*:\s*([^\n]+?)(?:\.\s*(?:location|minimum|employment|exclude)\b|\n|$)/i
    );
    const out = [];
    if (m) {
      for (const part of m[1].split(/,|\/|;|\band\b/i)) {
        const t = part.replace(/\.\s*$/, "").trim();
        if (
          t &&
          t.length < 80 &&
          /engineer|developer|scientist|architect|analyst|sre|devops|manager/i.test(t) &&
          !out.includes(t)
        ) {
          out.push(t);
        }
      }
    }
    if (fallbackTitle && !out.includes(fallbackTitle)) out.unshift(fallbackTitle);
    return out;
  }

  function extractMinimumSalaryCad(text) {
    const blob = String(text || "");
    const patterns = [
      /minimum(?:\s+desired)?(?:\s+base)?\s+salary\s*:\s*CAD\s*\$?\s*([\d,]+)/i,
      /CAD\s*\$\s*([\d,]+)(?:\s*(?:annually|\/\s*year|per\s+year))?/i,
      /\$\s*([\d,]+)\s*(?:CAD|canadian)/i,
      /(?:salary|compensation|base)\s*(?:expectation|target|floor|minimum)?\s*(?:of|:)?\s*CAD\s*\$?\s*([\d,]+)/i,
    ];
    for (const p of patterns) {
      const m = blob.match(p);
      if (!m) continue;
      const n = Number(String(m[1]).replace(/,/g, ""));
      if (Number.isFinite(n) && n >= 30000 && n <= 500000) return Math.round(n);
    }
    return 0;
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
    const tryAdd = (label, pattern) => {
      let ok = false;
      eachMatch(blob, pattern, (m) => {
        if (!ok && mentionStatus(blob, m.index) === "confirmed") ok = true;
      });
      if (ok && !found.includes(label)) found.push(label);
    };
    tryAdd("remote", /\bremote\b/i);
    tryAdd("hybrid", /\bhybrid\b/i);
    tryAdd("onsite", /\b(?:on[\s-]?site|in[\s-]?office)\b/i);
    return found;
  }

  function extractProfileFromText(text) {
    const profile = emptyProfile();
    const blob = String(text || "");
    if (!blob.trim()) return profile;
    profile.current_title = extractTitle(blob);
    profile.desired_titles = extractDesiredTitles(blob, profile.current_title);
    profile.years_experience = extractYears(blob);
    profile.skills = extractSkills(blob);
    profile.disciplines = extractDisciplines(blob);
    profile.seniority = resolveSeniorityBands(
      extractSeniorityRaw(blob),
      profile.years_experience,
      profile.current_title
    );
    profile.preferred_locations = extractLocations(blob);
    profile.work_arrangements = extractArrangements(blob);
    profile.minimum_salary_cad = extractMinimumSalaryCad(blob);
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
    if (parts.has(token)) return true;
    for (const alias of SPECIFIC_TOKEN_ALIASES[token] || []) {
      if (parts.has(alias)) return true;
    }
    return false;
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
      const family = roleFamilyTokens(nt);
      const specific = family.filter((tok) => !GENERIC_ROLE_TOKENS.has(tok));
      if (jobTitle.includes(nt) || nt.includes(jobTitle)) {
        if (!specific.length || specific.some((tok) => tokenInTitle(jobTitle, tok))) {
          best = Math.max(best, 1);
        }
        continue;
      }
      // Prefer role-family tokens (strip seniority) so "Senior Data Engineer"
      // aligns with "Lead Data Engineer" / "Senior Data Platform Engineer".
      // Specific tokens (data, ai, …) must hit — "AI Engineer" ≠ every engineer.
      if (family.length) {
        if (specific.length) {
          const specificHits = specific.filter((tok) => tokenInTitle(jobTitle, tok)).length;
          if (specificHits === 0) {
            best = Math.max(best, 0.35);
            continue;
          }
          const generic = family.filter((tok) => GENERIC_ROLE_TOKENS.has(tok));
          const specScore = specificHits / specific.length;
          const genBonus = generic.length
            ? 0.15 * (generic.filter((tok) => tokenInTitle(jobTitle, tok)).length / generic.length)
            : 0.1;
          const raw = specScore * 0.85 + genBonus;
          best = Math.max(best, Math.min(1, Math.max(0.6, raw)));
          continue;
        }
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
    const juniorProfile = wanted.some((b) => b === "junior" || b === "intern");
    const order = ["intern", "junior", "mid", "senior", "staff", "principal", "lead"];
    const candIdx = Math.max(
      -1,
      ...wanted.map((w) => order.indexOf(w)).filter((i) => i >= 0)
    );
    const seniorPlusProfile = candIdx >= order.indexOf("senior");
    const juniorJob =
      jobSen === "junior" ||
      jobSen === "intern" ||
      titleJuniorSignal(job.title);

    if (!wanted.length) return { score: 0.5, note: null };

    // Senior (or above) candidate vs explicit junior/entry role — directional mismatch.
    // Soft demotion only: do not hard-exclude unless the user opted out elsewhere.
    if (seniorPlusProfile && juniorJob) {
      return {
        score: 0.12,
        note: "Job is junior/entry-level; your profile targets more senior roles",
      };
    }
    if (candIdx >= order.indexOf("mid") && juniorJob && candIdx - order.indexOf("junior") >= 2) {
      return {
        score: 0.22,
        note: "Job is junior/entry-level; your profile is more experienced",
      };
    }

    // Unknown job seniority: cautious — never invent junior eligibility.
    if (!jobSen) {
      if (juniorProfile) {
        if (titleJuniorSignal(job.title)) {
          return { score: 0.95, note: null };
        }
        if (titleSeniorSignal(job.title)) {
          return {
            score: 0.18,
            note: "Title signals a more senior role than your junior profile",
          };
        }
        return {
          score: 0.35,
          note: "Job seniority unspecified — compatibility uncertain for junior profiles",
        };
      }
      if (seniorPlusProfile && titleJuniorSignal(job.title)) {
        return {
          score: 0.12,
          note: "Job is junior/entry-level; your profile targets more senior roles",
        };
      }
      return { score: 0.55, note: "Job seniority unspecified — compatibility uncertain" };
    }

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
        // Overqualified: candidate band clearly above job band.
        if (candIdx >= 0 && ji >= 0 && candIdx - ji >= 2) {
          band = Math.min(band, 0.25);
        }
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

    if (!note && candIdx >= 0 && jobSen && order.indexOf(jobSen) >= 0 && candIdx - order.indexOf(jobSen) >= 2) {
      note = `Job seniority (${jobSen}) is below your profile band (${wanted[0]})`;
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

  function titleJuniorSignal(title) {
    return /\b(?:junior|jr\.?|entry[\s-]?level|new[\s-]?grad|graduate|trainee|intern|co-?op|coop)\b/i.test(
      title || ""
    );
  }

  function titleSeniorSignal(title) {
    return /\b(?:senior|sr\.?|staff|principal|director|vp\b|head of)\b/i.test(title || "");
  }

  function arrangementScore(profile, job) {
    const wanted = profile.work_arrangements || [];
    if (!wanted.length) return { score: 0.5, ok: true };
    const arr = job.work_arrangement || "unspecified";
    // Explicit selection is a hard allow-list — remote-only must not include unspecified.
    if (arr === "unspecified" || arr === "unknown") {
      return { score: 0, ok: false };
    }
    if (wanted.includes(arr)) return { score: 1, ok: true };
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

    // Prefer role-family + seniority; skills matter but cannot dominate career fit.
    let score =
      title * 0.3 + skills.score * 0.2 + sen.score * 0.3 + disc * 0.15 + other * 0.05;
    if (sen.score < 0.4) {
      // Cap: staff/principal vs junior cannot land in the 80%+ band on skills alone.
      score = Math.min(score, 0.35 + sen.score * 0.25);
    }
    if ((profile.skills || []).length && skills.matched.length === 0) {
      // Title/discipline alone must not look like a strong confirmed skill match.
      score = Math.min(score, 0.58);
    }
    const wantedSen = (profile.seniority || []).map((s) => String(s).toLowerCase());
    const inferredSen = inferSeniorityFromYears(profile.years_experience);
    const juniorProfile =
      wantedSen.includes("junior") ||
      wantedSen.includes("intern") ||
      inferredSen === "junior";
    const seniorPlusProfile =
      wantedSen.some((b) => ["senior", "staff", "principal", "lead"].includes(b)) ||
      (inferredSen && ["senior", "staff", "principal"].includes(inferredSen));
    if (juniorProfile) {
      if (titleJuniorSignal(job.title) || String(job.seniority || "").toLowerCase() === "junior") {
        score = Math.min(1, score + 0.12);
      } else if (
        ["mid", "senior", "staff", "principal", "lead"].includes(
          String(job.seniority || "").toLowerCase()
        ) ||
        titleSeniorSignal(job.title)
      ) {
        score = Math.max(0, score - 0.18);
      }
    } else if (seniorPlusProfile) {
      if (titleJuniorSignal(job.title) || String(job.seniority || "").toLowerCase() === "junior") {
        score = Math.max(0, score - 0.2);
      } else if (title >= 0.7 && disc >= 0.9 && sen.score >= 0.7) {
        score = Math.min(1, score + 0.06);
      }
    }
    const percent = Math.round(Math.max(0, Math.min(1, score)) * 100);

    const reasons = [];
    if (title >= 0.7) reasons.push("Title aligns with your preferred role family");
    else if (title >= 0.5) reasons.push("Partial title / role-family overlap");
    else if (title < 0.45 && hasTitlePref) {
      reasons.push("Role family differs from your preferred titles");
    }
    if (skills.matched.length) {
      reasons.push(`Confirmed matching skills: ${skills.matched.slice(0, 5).join(", ")}`);
    }
    if (skills.unconfirmed.length) {
      reasons.push(
        `Skills not mentioned in the listing are unconfirmed, not necessarily missing: ${skills.unconfirmed.slice(0, 4).join(", ")}`
      );
    }
    if (disc >= 0.9) reasons.push("Discipline matches your preferred tracks");
    else if (disc <= 0.25 && (profile.disciplines || []).length) {
      reasons.push("Discipline / track differs from your preferred fields");
    }
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
    // Browse default: highest advertised salary (CAD-normalized max).
    // Find My Matches uses matchJobs() and sorts by relevance separately.
    const sort = filters.sort || "salary";

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
