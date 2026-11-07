"""Work types and attribution: what each commit and PR was, and which business it served."""

from __future__ import annotations

import json
import re
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path

from .config import UNSORTED, Group, ProjectMap

TYPES = ["feature", "fix", "content", "automation", "operating"]
VELOCITY_TYPES = ["feature", "fix", "content", "automation"]
TYPE_NAMES = {
    "feature": "Features",
    "fix": "Fixes",
    "content": "Content & deliverables",
    "automation": "Automation & tooling",
    "operating": "Operating",
}
OPERATING = "operating"

_PREFIX = {
    "feat": "feature", "perf": "feature", "fix": "fix", "hotfix": "fix", "security": "fix",
    "docs": "content", "content": "content", "copy": "content",
    "chore": "automation", "refactor": "automation", "test": "automation", "tests": "automation",
    "ci": "automation", "build": "automation", "style": "automation", "deps": "automation",
}


def commit_id(c: dict) -> str:
    return c["sha"][:12]


def pr_id(p: dict) -> str:
    return f"{p['repo']}#{p['number']}"


def guess_type(text: str) -> str:
    """Fallback label from a commit subject or PR title (used when Claude has no label)."""
    s = text.strip().lower()
    m = re.match(r"^([a-z]+)(\([^)]*\))?!?:", s)
    if m and m.group(1) in _PREFIX:
        return _PREFIX[m.group(1)]
    if s.startswith(("record ", "log ", "note ", "notes ", "capture ")):
        return "operating"
    if s.startswith(("fix", "repair", "correct", "resolve", "patch ")):
        return "fix"
    if s.startswith(("add ", "build ", "create ", "implement", "introduce", "support ", "ship ", "launch ")):
        return "feature"
    return "automation"


class Labels:
    """Claude's labels, cached in history/labels.json so they stay stable: id -> {"t": type, "g": group}."""

    def __init__(self, path: Path):
        self.path = path
        self.data: dict[str, dict] = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}

    def get(self, key: str) -> dict | None:
        return self.data.get(key)

    def update(self, new: dict[str, dict]) -> None:
        self.data.update(new)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(self.data, indent=0, sort_keys=True) + "\n", encoding="utf-8")


@dataclass
class Row:
    """One report row: a repository's work for one group in one week."""
    repo: str
    group: Group
    commits: int = 0
    additions: int = 0
    deletions: int = 0
    dates: set = field(default_factory=set)
    prs_merged: int = 0
    prs_opened: int = 0
    agent_commits: int = 0
    types: Counter = field(default_factory=Counter)

    @property
    def key(self) -> tuple[str, str]:
        return (self.repo, self.group.id)


@dataclass
class WeekWork:
    rows: dict[tuple[str, str], Row]
    operating: dict                      # commits, additions, deletions, prs_merged, repos (Counter), subjects
    merged: list[dict]                   # velocity PRs merged, each with "type" and "group"
    opened: list[dict]
    commits: list[dict]                  # velocity commits, each with "type" and "group"


def _label(labels: Labels, key: str, text: str) -> dict:
    lab = labels.get(key) or {}
    t = lab.get("t") if lab.get("t") in TYPES else guess_type(text)
    return {"t": t, "g": lab.get("g")}


def _target(repo: str, lab: dict, pmap: ProjectMap) -> Group | None:
    """Group the work counts for, or None when it is operating work."""
    if lab["t"] == OPERATING:
        return None
    if pmap.is_operating(repo):
        g = lab.get("g")
        if not g or g == OPERATING or not pmap.has_group(g):
            return None
        return pmap.group(g)
    return pmap.group_for(repo) or UNSORTED


def attribute(doc: dict | None, labels: Labels, pmap: ProjectMap) -> WeekWork:
    rows: dict[tuple[str, str], Row] = {}
    op = {"commits": 0, "additions": 0, "deletions": 0, "prs_merged": 0, "repos": Counter(), "subjects": []}
    merged_out, opened_out, commits_out = [], [], []
    if not doc:
        return WeekWork(rows, op, merged_out, opened_out, commits_out)

    def row(repo: str, group: Group) -> Row:
        return rows.setdefault((repo, group.id), Row(repo, group))

    for c in doc.get("commits", []):
        if pmap.excluded(c["repo"]):
            continue
        lab = _label(labels, commit_id(c), c["subject"])
        group = _target(c["repo"], lab, pmap)
        if group is None:
            op["commits"] += 1
            op["additions"] += c["add"]
            op["deletions"] += c["del"]
            op["repos"][c["repo"]] += 1
            op["subjects"].append(c["subject"])
            continue
        r = row(c["repo"], group)
        r.commits += 1
        r.additions += c["add"]
        r.deletions += c["del"]
        r.dates.add(c["date"])
        r.agent_commits += 1 if c.get("agent") else 0
        r.types[lab["t"]] += 1
        commits_out.append({**c, "type": lab["t"], "group": group})

    for kind, out in (("prs_merged", merged_out), ("prs_opened", opened_out)):
        for p in doc.get(kind, []):
            if pmap.excluded(p["repo"]):
                continue
            lab = _label(labels, pr_id(p), p["title"])
            group = _target(p["repo"], lab, pmap)
            if group is None:
                if kind == "prs_merged":
                    op["prs_merged"] += 1
                continue
            r = row(p["repo"], group)
            setattr(r, kind, getattr(r, kind) + 1)
            out.append({**p, "type": lab["t"], "group": group})
    return WeekWork(rows, op, merged_out, opened_out, commits_out)


def unlabeled(docs: list[dict | None], labels: Labels, pmap: ProjectMap) -> list[dict]:
    """Items that still need a Claude label, ready for the labeling prompt."""
    items, seen = [], set()
    for doc in docs:
        if not doc:
            continue
        for c in doc.get("commits", []):
            key = commit_id(c)
            if key in seen or labels.get(key) or pmap.excluded(c["repo"]):
                continue
            seen.add(key)
            items.append({"id": key, "repo": c["repo"], "op": pmap.is_operating(c["repo"]),
                          "text": c["subject"], "paths": c.get("paths", [])[:6]})
        for p in doc.get("prs_merged", []) + doc.get("prs_opened", []):
            key = pr_id(p)
            if key in seen or labels.get(key) or pmap.excluded(p["repo"]):
                continue
            seen.add(key)
            items.append({"id": key, "repo": p["repo"], "op": pmap.is_operating(p["repo"]),
                          "text": p["title"], "body": p.get("body", "")[:300]})
    return items
