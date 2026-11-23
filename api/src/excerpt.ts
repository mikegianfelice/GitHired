// On-demand description excerpt fetchers for GET /api/v1/jobs/{id}
// Best-effort: when the bundled snapshot omits description_excerpt due to size slimming,
// try to fetch a short plain-text excerpt from the ATS using the job's apply_url.

const MAX_EXCERPT = 900;

function stripHtml(html: string): string {
  const text = html.replace(/<[^>]+>/g, " ").replace(/\s+/g, " ").trim();
  return text.length <= MAX_EXCERPT ? text : text.slice(0, MAX_EXCERPT - 1).trimEnd() + "…";
}

function ghApiUrl(url: string): string | null {
  // https://job-boards.greenhouse.io/<board>/jobs/<id>
  const m = url.match(/greenhouse\.io\/([^/]+)\/jobs\/(\d+)/i);
  if (!m) return null;
  const board = m[1];
  const id = m[2];
  return `https://boards-api.greenhouse.io/v1/boards/${encodeURIComponent(board)}/jobs/${encodeURIComponent(id)}?content=true`;
}

function leverApiUrl(url: string): string | null {
  // https://jobs.lever.co/<board>/<id>(/apply)?
  const m = url.match(/jobs\.lever\.co\/([^/]+)\/([A-Za-z0-9-]+)(?:\/|$)/i);
  if (!m) return null;
  const board = m[1];
  const id = m[2];
  return `https://api.lever.co/v0/postings/${encodeURIComponent(board)}/${encodeURIComponent(id)}?expand=true`;
}

function ashbyBoardAndId(url: string): { board: string; id: string } | null {
  // https://jobs.ashbyhq.com/<board>/<uuid>
  const m = url.match(/jobs\.ashbyhq\.com\/([^/]+)\/([A-Za-z0-9-]+)/i);
  if (!m) return null;
  return { board: m[1], id: m[2] };
}

function workableApiUrl(url: string): string | null {
  // https://apply.workable.com/j/<CODE>  or  https://apply.workable.com/<company>/j/<CODE>/
  const m = url.match(/apply\.workable\.com\/(?:[^/]+\/)?j\/([A-Z0-9]+)/i);
  if (!m) return null;
  const code = m[1];
  return `https://apply.workable.com/api/v1/widget/jobs/${encodeURIComponent(code)}`;
}

function smartRecruitersApiUrl(url: string): string | null {
  // https://api.smartrecruiters.com/v1/companies/<company>/postings/<id>
  const api = url.match(/api\.smartrecruiters\.com\/v1\/companies\/([^/]+)\/postings\/([^/?#]+)/i);
  if (api) return `https://api.smartrecruiters.com/v1/companies/${api[1]}/postings/${api[2]}`;
  // https://jobs.smartrecruiters.com/<company>/<slug-or-id>
  const web = url.match(/jobs\.smartrecruiters\.com\/([^/]+)\/([^/?#]+)/i);
  if (web) return `https://api.smartrecruiters.com/v1/companies/${web[1]}/postings/${web[2]}`;
  return null;
}

async function tryFetchJsonText(endpoint: string, jsonPathCandidates: string[]): Promise<string | null> {
  try {
    const res = await fetch(endpoint, { cf: { cacheEverything: true }, headers: { accept: "application/json" } });
    if (!res.ok) return null;
    const data = await res.json();
    for (const path of jsonPathCandidates) {
      const parts = path.split(".");
      let cur: any = data;
      let ok = true;
      for (const p of parts) {
        if (cur && typeof cur === "object" && p in cur) cur = cur[p];
        else {
          ok = false;
          break;
        }
      }
      if (ok && typeof cur === "string" && cur.trim()) {
        return stripHtml(cur);
      }
    }
  } catch {
    // ignore
  }
  return null;
}

async function tryFetchHtml(url: string): Promise<string | null> {
  try {
    const res = await fetch(url, { cf: { cacheEverything: true }, headers: { accept: "text/html,application/xhtml+xml" } });
    if (!res.ok) return null;
    const html = await res.text();
    if (!html) return null;
    return stripHtml(html);
  } catch {
    return null;
  }
}

export async function fetchDescriptionExcerptOnDemand(applyUrl: string, source?: string | null): Promise<string | null> {
  const url = applyUrl || "";
  // 1) Greenhouse
  const gh = ghApiUrl(url);
  if (gh) {
    const text = await tryFetchJsonText(gh, ["content", "content.plain", "job_post.content"]);
    if (text) return text;
  }
  // 2) Lever
  const lv = leverApiUrl(url);
  if (lv) {
    const text = await tryFetchJsonText(lv, ["text", "descriptionPlain", "description"]);
    if (text) return text;
  }
  // 3) Ashby
  const ash = ashbyBoardAndId(url);
  if (ash) {
    // No single-post endpoint: fetch board and locate posting by id
    const endpoint = `https://api.ashbyhq.com/posting-api/job-board/${encodeURIComponent(ash.board)}`;
    try {
      const res = await fetch(endpoint, { cf: { cacheEverything: true }, headers: { accept: "application/json" } });
      if (res.ok) {
        const data = (await res.json()) as any;
        const posts: any[] = data?.jobs || data?.postings || [];
        const match = posts.find((p) => (p?.id || p?.jobPostingId) === ash.id);
        const html = match?.descriptionHtml || match?.description || match?.contentHtml || "";
        if (typeof html === "string" && html.trim()) return stripHtml(html);
      }
    } catch {
      // ignore
    }
  }
  // 4) Workable
  const wk = workableApiUrl(url);
  if (wk) {
    const text = await tryFetchJsonText(wk, ["full_description", "description"]);
    if (text) return text;
  }
  // 5) SmartRecruiters
  const sr = smartRecruitersApiUrl(url);
  if (sr) {
    const text = await tryFetchJsonText(sr, ["jobAd.sections.jobDescription.text", "jobAd.jobTitle", "jobAd.jobDescription"]);
    if (text) return text;
  }
  // 6) Fallback: fetch page HTML and strip
  const fallback = await tryFetchHtml(url);
  return fallback;
}

// Export URL parsers for tests
export const __parsers = { ghApiUrl, leverApiUrl, ashbyBoardAndId, workableApiUrl, smartRecruitersApiUrl };

