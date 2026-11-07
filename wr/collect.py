"""Collect one week of your GitHub activity: commits on default branches, lines, PRs, plans."""

from __future__ import annotations

import base64
import json
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from pathlib import Path

from . import gh
from .config import Settings, read_text, write_text
from .weeks import Week, local_date

HISTORY_FORMAT = 2  # per-commit and per-PR records; labels and the map apply at render time

IGNORED_NAMES = {
    "package-lock.json", "npm-shrinkwrap.json", "pnpm-lock.yaml", "yarn.lock", "bun.lock", "bun.lockb",
    "Cargo.lock", "poetry.lock", "uv.lock", "Pipfile.lock", "Gemfile.lock", "composer.lock", "go.sum",
    "flake.lock", "mix.lock", "pubspec.lock", "Podfile.lock", "packages.lock.json", "deno.lock",
}
IGNORED_SUFFIXES = (
    ".min.js", ".min.css", ".map", ".snap", ".lock", ".lockb", ".pb.go", "_pb2.py", ".generated.ts", ".gen.ts",
    # data files: dumps, fixtures, exports and licenses inflate line counts without being written work
    ".json", ".jsonl", ".ndjson", ".csv", ".tsv", ".svg", ".txt", ".xml", ".geojson",
)
IGNORED_DIRS = {
    "node_modules", "dist", "build", ".next", ".astro", ".svelte-kit", ".turbo", ".vercel", ".netlify",
    "coverage", "vendor", "generated", "__generated__", "_generated", "__snapshots__",
}
IGNORED_PATH_PARTS = ("drizzle/meta/", "migrations/meta/")
IGNORED_NAME_PREFIXES = ("THIRD_PARTY", "THIRD-PARTY", "LICENSE", "LICENCE", "NOTICE")


def ignored_path(path: str) -> bool:
    """True for lock files, generated output and data files, which do not count as lines of work."""
    parts = path.split("/")
    name = parts[-1]
    if name in IGNORED_NAMES or name.lower().endswith(IGNORED_SUFFIXES) or name.upper().startswith(IGNORED_NAME_PREFIXES):
        return True
    if any(marker in path for marker in IGNORED_PATH_PARTS):
        return True
    return any(p in IGNORED_DIRS for p in parts[:-1])


def count_lines(files: list[list]) -> list[int]:
    add = rem = 0
    for name, a, d in files:
        if not ignored_path(name):
            add += a
            rem += d
    return [add, rem]


# -- commit line stats (immutable, so cached by SHA) -----------------------

class StatsCache:
    """Per-file changes for each commit SHA ([[filename, additions, deletions], ...]). Commits never change."""

    def __init__(self, path: Path):
        self.path = path
        self.data: dict[str, list[list]] = json.loads(read_text(path)) if path.exists() else {}

    def save(self) -> None:
        write_text(self.path, json.dumps(self.data, separators=(",", ":")))


def _fetch_files(repo: str, sha: str) -> list[list]:
    out = gh.api(f"repos/{repo}/commits/{sha}", paginate=True, jq=".files[] | [.filename, .additions, .deletions] | tojson")
    return gh.json_lines(out)


def commit_stats(commits: list[dict], cache: StatsCache) -> dict[str, list[int]]:
    todo = [c for c in commits if c["sha"] not in cache.data]

    def work(c):
        try:
            return c["sha"], _fetch_files(c["repo"], c["sha"])
        except gh.GitHubError:
            return c["sha"], None

    with ThreadPoolExecutor(max_workers=8) as pool:
        for sha, files in pool.map(work, todo):
            if files is not None:
                cache.data[sha] = files
    cache.save()
    return {c["sha"]: count_lines(cache.data.get(c["sha"], [])) for c in commits}


# -- fetching ---------------------------------------------------------------

def _repo_from_url(url: str) -> str:
    return url.split("/repos/", 1)[1]


def fetch_commits(week: Week, settings: Settings) -> list[dict]:
    """Your non-merge commits on default branches, committed in the week (all identities, deduped)."""
    seen: dict[str, dict] = {}
    own = f"author:{settings.login}"
    for q in settings.commit_queries:
        for it in gh.search("commits", f"{q} committer-date:{week.search_range()}"):
            sha = it["sha"]
            if sha in seen:
                continue
            repo = it.get("repository") or {}
            seen[sha] = {
                "sha": sha,
                "repo": repo.get("full_name", ""),
                "fork": bool(repo.get("fork")),
                "date": it["commit"]["committer"]["date"],
                "merge": len(it.get("parents") or []) > 1,
                "subject": it["commit"]["message"].split("\n", 1)[0][:160],
                "agent": q != own,  # found through an agent identity, not your own login
            }
    return [c for c in seen.values() if c["repo"] and not c["merge"] and not c["fork"]]


def fetch_prs(qualifier: str, settings: Settings) -> list[dict]:
    seen: dict[str, dict] = {}
    for q in settings.pr_queries:
        for it in gh.search("issues", f"is:pr {q} {qualifier}"):
            body = " ".join((it.get("body") or "").split())
            seen[it["html_url"]] = {
                "repo": _repo_from_url(it["repository_url"]),
                "number": it["number"],
                "title": it["title"],
                "url": it["html_url"],
                "author": (it.get("user") or {}).get("login", ""),
                "agent": q != f"author:{settings.login}",
                "draft": bool(it.get("draft")),
                "created_at": it.get("created_at", ""),
                "merged_at": ((it.get("pull_request") or {}).get("merged_at")) or "",
                "body": body[:400],
            }
    return list(seen.values())


def top_paths(files: list[list], n: int = 6) -> list[str]:
    """The paths with the most changed lines in a commit (for labeling)."""
    ranked = sorted(files, key=lambda f: -(f[1] + f[2]))
    return [f[0] for f in ranked[:n]]


def collect_week(week: Week, settings: Settings, cache: StatsCache) -> dict:
    commits = fetch_commits(week, settings)
    stats = commit_stats(commits, cache)
    records = []
    for c in sorted(commits, key=lambda c: c["date"]):
        add, rem = stats.get(c["sha"], [0, 0])
        records.append({
            "sha": c["sha"],
            "repo": c["repo"],
            "date": local_date(c["date"], settings.tz),
            "ts": c["date"],
            "add": add,
            "del": rem,
            "subject": c["subject"],
            "agent": c["agent"],
            "paths": top_paths(cache.data.get(c["sha"], [])),
        })
    rng = week.search_range()
    return {
        "format": HISTORY_FORMAT,
        "week_start": week.key,
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "commits": records,
        "prs_opened": fetch_prs(f"created:{rng}", settings),
        "prs_merged": fetch_prs(f"merged:{rng}", settings),
    }


def open_prs(settings: Settings) -> list[dict]:
    return fetch_prs("is:open", settings)


def fetch_plans(week: Week, settings: Settings) -> dict:
    """Newest dated priorities file on or before the week's end, plus plan files dated inside the week.

    Files are found by a date prefix in their name (YYYY-MM-DD-...). The folder can be local
    (`local_path`) or a folder in a GitHub repository (`repo`); the local folder wins.
    """
    cfg = settings.plans
    if not cfg.get("daily_dir"):
        return {}
    last_day = week.last_day.isoformat()
    local = Path(cfg["local_path"]).expanduser() if cfg.get("local_path") else None

    def list_dir(rel: str) -> list[str]:
        if not rel:
            return []
        if local and (local / rel).is_dir():
            return sorted(p.name for p in (local / rel).iterdir() if p.is_file())
        if cfg.get("repo"):
            try:
                return gh.json_lines(gh.api(f"repos/{cfg['repo']}/contents/{rel}", jq=".[] | .name | tojson"))
            except (gh.GitHubError, ValueError):
                return []
        return []

    def read(rel: str) -> str:
        if local and (local / rel).is_file():
            return (local / rel).read_text(encoding="utf-8", errors="replace")
        raw = gh.api(f"repos/{cfg['repo']}/contents/{rel}", jq=".content")
        return base64.b64decode(raw).decode("utf-8", "replace")

    out: dict = {}
    dated = [n for n in list_dir(cfg["daily_dir"]) if n[:4].isdigit() and n[:10] <= last_day]
    if dated:
        name = sorted(dated)[-1]
        try:
            text = read(f"{cfg['daily_dir']}/{name}")
            out["daily"] = {"name": name, "date": name[:10], "text": text[: int(cfg.get("max_chars", 8000))]}
        except (OSError, gh.GitHubError, ValueError):
            pass
    out["plans_this_week"] = [n for n in list_dir(cfg.get("plans_dir", "")) if week.key <= n[:10] <= last_day]
    return out


def last_activity(repo: str, settings: Settings, since_days: int, until: datetime) -> str | None:
    """Date of your latest commit on the default branch in the `since_days` before `until`, or None."""
    fmt = "%Y-%m-%dT%H:%M:%SZ"
    until_utc = until.astimezone(timezone.utc)
    since = (until_utc - timedelta(days=since_days)).strftime(fmt)
    best = None
    for author in settings.commit_authors:
        try:
            params = {"author": author, "since": since, "until": until_utc.strftime(fmt), "per_page": "1"}
            out = gh.api(f"repos/{repo}/commits", params, jq=".[0].commit.committer.date // empty")
        except gh.GitHubError:
            continue
        value = out.strip()
        if value and (best is None or value > best):
            best = value
    return best


def repo_info(repo: str) -> dict:
    """Name, description and a README excerpt, for Claude placement of new repositories."""
    info = {"repo": repo, "description": "", "readme": ""}
    try:
        meta = json.loads(gh.api(f"repos/{repo}", jq="{d: .description}"))
        info["description"] = meta.get("d") or ""
    except (gh.GitHubError, json.JSONDecodeError):
        pass
    try:
        readme = gh.api(f"repos/{repo}/readme", jq=".content")
        info["readme"] = base64.b64decode(readme).decode("utf-8", "replace")[:1500]
    except (gh.GitHubError, ValueError):
        pass
    return info
