"""Thin wrapper around the GitHub CLI (`gh api`). gh owns the login and token."""

from __future__ import annotations

import json
import shutil
import subprocess
import time

SEARCH_GAP_SECONDS = 2.5  # GitHub allows 30 search requests per minute
_last_search = 0.0


class GitHubError(RuntimeError):
    pass


def gh_path() -> str:
    path = shutil.which("gh")
    if not path:
        raise GitHubError("The GitHub CLI (gh) is not installed or not on PATH. See https://cli.github.com")
    return path


def api(path: str, params: dict[str, str] | None = None, *, paginate: bool = False, jq: str | None = None) -> str:
    global _last_search
    args = [gh_path(), "api", "-X", "GET", path]
    for key, value in (params or {}).items():
        args += ["-f", f"{key}={value}"]
    if paginate:
        args.append("--paginate")
    if jq:
        args += ["--jq", jq]

    last_err = ""
    for attempt in range(5):
        if path.startswith("search/"):
            wait = SEARCH_GAP_SECONDS - (time.monotonic() - _last_search)
            if wait > 0:
                time.sleep(wait)
            _last_search = time.monotonic()
        try:
            result = subprocess.run(args, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=180)
        except subprocess.TimeoutExpired:
            last_err = "timeout"
            time.sleep(5)
            continue
        if result.returncode == 0:
            return result.stdout
        last_err = result.stderr.strip()
        low = last_err.lower()
        if "rate limit" in low or "abuse" in low:
            time.sleep(30 * (attempt + 1))
            continue
        if "http 5" in low or "timeout" in low or "connection" in low or "eof" in low:
            time.sleep(5 * (attempt + 1))
            continue
        raise GitHubError(f"gh api {path}: {last_err}")
    raise GitHubError(f"gh api {path} failed after retries: {last_err}")


def json_lines(text: str) -> list:
    # Split on "\n" only: str.splitlines() also splits on U+2028 and similar, which tojson leaves in strings.
    return [json.loads(line) for line in text.split("\n") if line.strip()]


def search(kind: str, query: str) -> list[dict]:
    """All items for a search query (commits or issues), up to GitHub's 1000-item cap."""
    out = api(f"search/{kind}", {"q": query, "per_page": "100"}, paginate=True, jq=".items[] | tojson")
    return json_lines(out)
