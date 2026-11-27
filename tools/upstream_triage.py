#!/usr/bin/env python3
"""Triage upstream commits this fork has not picked up yet.

Emits a Markdown report that sorts the behind-list into "worth reviewing" vs
"probably skip", so a human decides what to merge/port. It never merges,
pushes, or edits anything - it only reads git history and prints. This is the
deliberate report/act boundary: on a fork "applies cleanly" is not "correct" -
a commit for portals the fork dropped can cherry-pick fine and still be wrong,
and that silent-wrong case is worse than a conflict. So the report stops at
ready-to-run cherry-pick lines; a human runs them.

This is the commit-level companion to check_upstream_updates.py. That tool
answers "which of my personalized framework files changed" (version stamps);
this one answers "which upstream commits deserve my attention" (commit history).
Two tools, two questions - each cross-references the other in its output.

Two signals drive the sort:

1. Already applied? A cherry-pick lands with a NEW sha but the same patch, so a
   raw sha comparison misreports it as missing. We compute git patch-ids for the
   fork-only commits and treat any upstream commit whose patch-id
   matches as already applied. A matching subject with a different patch may be a
   conflict-resolved port or an unrelated change: keep it as a distinct verify
   reason in the advisory skip list, never as proof of a cherry-pick.

2. Relevant to this fork? A commit that only touches files this fork deleted
   (e.g. removed demo portals) is almost certainly N/A. We check each commit's
   touched paths against HEAD and the shared base: a genuinely new upstream
   path is worth reviewing, rather than a file the fork chose to remove. A new
   file inside a directory the fork removed (a test added to a dropped portal)
   counts as removed too.

Usage: python tools/upstream_triage.py [--remote upstream] [--branch master]
Exits 0 always (a report, not a gate). Prints a note to stderr and exits 0 if
the upstream ref is unavailable, so a scheduled job degrades gracefully.
"""
from __future__ import annotations

import argparse
import shlex
import subprocess
import sys


def _force_utf8_output() -> None:
    """Write UTF-8 whatever the host's default encoding is.

    A piped stdout on Windows defaults to the ANSI code page (cp1252 on most
    Western installs), so printing a commit subject or author outside it
    raised UnicodeEncodeError before the report could be emitted.
    """
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure:
            reconfigure(encoding="utf-8")


def git(*args: str) -> str:
    return subprocess.run(
        ["git", *args], capture_output=True, text=True, encoding="utf-8", errors="replace", check=True
    ).stdout


def rev_list(range_spec: str) -> list[str]:
    out = git("rev-list", "--no-merges", "--topo-order", range_spec).strip()
    return out.splitlines() if out else []


def patch_id(sha: str) -> str | None:
    """Stable patch-id for a commit, or None if it has no diff."""
    show = subprocess.run(
        ["git", "show", sha], capture_output=True, text=True, encoding="utf-8", errors="replace", check=True
    ).stdout
    r = subprocess.run(
        ["git", "patch-id", "--stable"], input=show, capture_output=True, text=True, encoding="utf-8", errors="replace"
    )
    line = r.stdout.strip()
    return line.split()[0] if line else None


def subject(sha: str) -> str:
    return git("show", "-s", "--format=%s", sha).strip()


def files_touched(sha: str) -> list[str]:
    out = git("show", "--name-only", "--format=", sha).strip()
    return [f for f in out.splitlines() if f]


def path_exists(path: str, ref: str = "HEAD") -> bool:
    # Read committed trees, rather than uncommitted files in the working tree.
    r = subprocess.run(
        ["git", "cat-file", "-e", f"{ref}:{path}"], capture_output=True
    )
    return r.returncode == 0


def in_removed_dir(path: str, base: str) -> bool:
    """Whether a path absent from HEAD and base sits in a directory the fork removed.

    The nearest ancestor directory decides: one HEAD still has means the path is
    new in a directory the fork kept; one only the base has means the fork
    deleted the tree the path would land in. Directories in neither are new
    upstream too, so the walk goes on up to the root.
    """
    parts = path.split("/")[:-1]
    for depth in range(len(parts), 0, -1):
        parent = "/".join(parts[:depth])
        if path_exists(parent):
            return False
        if path_exists(parent, base):
            return True
    return False


def remote_slug(remote: str) -> str | None:
    """owner/repo for a GitHub remote, or None if it can't be parsed."""
    try:
        url = git("remote", "get-url", remote).strip()
    except subprocess.CalledProcessError:
        return None
    for sep in ("github.com/", "github.com:"):
        if sep in url:
            path = url.split(sep, 1)[1]
            return path[:-4] if path.endswith(".git") else path
    return None


def load_wontport(path: str) -> list[str]:
    """SHA prefixes the fork has decided never to port; missing file -> []."""
    try:
        with open(path, encoding="utf-8") as f:
            raw = f.read()
    except FileNotFoundError:
        return []
    entries = []
    for line in raw.splitlines():
        line = line.split("#", 1)[0].strip()
        if line:
            entries.append(line)
    return entries


# GitHub rejects issue bodies over 65536 characters; leave room for the
# "Last checked" header line the workflow prepends.
DEFAULT_MAX_CHARS = 60000


def commit_cell(short: str, sha: str, slug: str | None) -> str:
    if slug:
        return f"[`{short}`](https://github.com/{slug}/commit/{sha})"
    return f"`{short}`"


def main() -> int:
    _force_utf8_output()
    ap = argparse.ArgumentParser()
    ap.add_argument("--remote", default="upstream")
    ap.add_argument("--branch", default="master")
    ap.add_argument("--wontport", default=".github/upstream-wontport.txt")
    ap.add_argument(
        "--max-chars", type=int, default=DEFAULT_MAX_CHARS,
        help="Cap the report so it fits in a GitHub issue body "
             f"(GitHub rejects bodies over 65536 characters; default {DEFAULT_MAX_CHARS}; "
             "0 disables the cap).",
    )
    args = ap.parse_args()
    ref = f"{args.remote}/{args.branch}"
    slug = remote_slug(args.remote)
    wontport = load_wontport(args.wontport)

    try:
        git("rev-parse", "--verify", ref)
    except subprocess.CalledProcessError:
        print(
            f"note: {ref} not available (add the remote and fetch it first); "
            "nothing to triage.",
            file=sys.stderr,
        )
        print(f"_Upstream ref `{ref}` was not available when this ran._")
        return 0

    behind = rev_list(f"HEAD..{ref}")
    if not behind:
        print(f"Up to date with `{ref}`. Nothing to review. :white_check_mark:")
        _print_crossref(args.remote, args.branch)
        return 0

    fork_only = rev_list(f"{ref}..HEAD")
    fork_patch_ids = {p for p in (patch_id(s) for s in fork_only) if p}
    fork_subjects = {}
    for fork_sha in fork_only:
        fork_subjects.setdefault(subject(fork_sha), fork_sha)
    try:
        common_base = git("merge-base", "HEAD", ref).strip()
    except subprocess.CalledProcessError:
        # Without shared history, absence cannot establish a deliberate deletion.
        common_base = None

    review: list[tuple[str, str, str, list[str]]] = []
    skip: list[tuple[str, str, str, str]] = []

    for sha in behind:
        subj = subject(sha)
        short = sha[:9]
        if patch_id(sha) in fork_patch_ids:
            skip.append((short, sha, subj, "already applied (cherry-picked)"))
            continue
        if subj in fork_subjects:
            match = fork_subjects[subj][:9]
            skip.append((short, sha, subj,
                         f"subject matches fork commit {match}, patch differs: verify"))
            continue
        if any(sha.startswith(e) for e in wontport):
            skip.append((short, sha, subj, "on the fork's won't-port list"))
            continue
        touched = files_touched(sha)
        relevant = [
            f for f in touched
            if path_exists(f)
            or common_base is None
            or not (path_exists(f, common_base) or in_removed_dir(f, common_base))
        ]
        # A commit whose only surviving footprint is the changelog is one whose
        # real change lives in files this fork removed - the code doesn't apply,
        # only a doc line would. Low signal; demote it.
        substantive = [f for f in relevant if f != "CHANGELOG.md"]
        if touched and not relevant:
            skip.append((short, sha, subj, "touches only files not in this fork"))
        elif relevant and not substantive:
            skip.append((short, sha, subj, "changelog-only footprint in this fork"))
        else:
            review.append((short, sha, subj, substantive))

    crossref = _crossref_text(args.remote, args.branch)
    # --max-chars 0 (or negative) disables the cap for local full reports.
    budget = (args.max_chars - len(crossref) - 2) if args.max_chars > 0 else float("inf")
    def fits(nr: int, ns: int) -> bool:
        return len(render_report(ref, slug, behind, review, skip, nr, ns)) <= budget

    def largest(lo: int, hi: int, ok) -> int:
        # Largest n in [lo, hi] with ok(n), given ok(lo) holds and ok is monotone.
        while lo < hi:
            mid = (lo + hi + 1) // 2
            if ok(mid):
                lo = mid
            else:
                hi = mid - 1
        return lo

    # Keep every row when it fits. Otherwise trim the low-signal "probably
    # skip" rows first, then the review rows, so the report fits the issue-body
    # limit; omitted rows are counted in the report.
    n_review, n_skip = len(review), len(skip)
    if not fits(n_review, n_skip):
        if fits(n_review, 0):
            n_skip = largest(0, n_skip, lambda ns: fits(n_review, ns))
        else:
            n_skip = 0
            n_review = largest(0, n_review, lambda nr: fits(nr, 0))
    report = render_report(ref, slug, behind, review, skip, n_review, n_skip)

    print(report)
    print()
    print(crossref)
    return 0


def render_report(ref, slug, behind, review, skip, n_review, n_skip) -> str:
    lines: list[str] = []
    lines.append(f"Upstream `{ref}` has **{len(behind)}** commit(s) this fork lacks: "
                 f"**{len(review)}** worth reviewing, **{len(skip)}** probably skippable.")
    lines.append("")
    lines.append("_This is a triage report. Nothing was merged - review and port by hand._")
    lines.append("")
    if n_review < len(review) or n_skip < len(skip):
        lines.append(
            f"_Report trimmed to fit a GitHub issue: showing {n_review} of {len(review)} "
            f"review rows and {n_skip} of {len(skip)} skip rows. Run "
            f"`python tools/upstream_triage.py --remote upstream --branch master --max-chars 0` "
            "locally for the full list._"
        )
        lines.append("")
    shown_review = review[:n_review]

    lines.append("### Worth reviewing")
    if shown_review:
        lines.append("")
        lines.append("| Commit | Subject | Relevant files it touches |")
        lines.append("|---|---|---|")
        for short, sha, subj, present in shown_review:
            shown = ", ".join(f"`{p}`" for p in present[:4]) or "_(new/shared paths)_"
            if len(present) > 4:
                shown += f" +{len(present) - 4} more"
            lines.append(f"| {commit_cell(short, sha, slug)} | {subj} | {shown} |")
        if n_review < len(review):
            lines.append(f"| … | _{len(review) - n_review} more not shown_ | |")
        # Ready-to-run cherry-pick lines - still information, not action. The
        # report stops here on purpose; a human runs (and verifies) these.
        lines.append("")
        lines.append("<details><summary>Ready-to-run cherry-picks (review each before running)</summary>")
        lines.append("")
        lines.append("```bash")
        # Report rows stay newest first; commands must apply ancestors first.
        for short, sha, subj, _ in reversed(shown_review):
            lines.append(f"git cherry-pick {sha}  # {subj}")
        lines.append("```")
        lines.append("")
        lines.append("</details>")
    elif review:
        lines.append("")
        lines.append(f"_{len(review)} commit(s) not shown (report size limit)._")
    else:
        lines.append("")
        lines.append("_None._")
    lines.append("")

    lines.append("### Probably skip")
    if n_skip:
        lines.append("")
        lines.append("| Commit | Subject | Why |")
        lines.append("|---|---|---|")
        for short, sha, subj, why in skip[:n_skip]:
            lines.append(f"| {commit_cell(short, sha, slug)} | {subj} | {why} |")
        if n_skip < len(skip):
            lines.append(f"| … | _{len(skip) - n_skip} more not shown_ | |")
    elif skip:
        lines.append("")
        lines.append(f"_{len(skip)} commit(s) not shown (report size limit)._")
    else:
        lines.append("")
        lines.append("_None._")
    return "\n".join(lines)


def _crossref_text(remote: str, branch: str) -> str:
    return (
        "_For personalized-file version stamps (which methodology files changed), "
        f"run `python tools/check_upstream_updates.py --remote {shlex.quote(remote)} --branch {shlex.quote(branch)}`._"
    )


def _print_crossref(remote: str, branch: str) -> None:
    print()
    print(_crossref_text(remote, branch))


if __name__ == "__main__":
    sys.exit(main())
