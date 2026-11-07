"""Settings and the project map. Code lives in the skill folder; your data lives in a separate home folder."""

from __future__ import annotations

import json
import os
import tomllib
from dataclasses import dataclass, field
from pathlib import Path
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

CODE_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_HOME = Path(os.environ.get("WEEKLY_REVIEW_HOME", "~/.weekly-review")).expanduser()
WEEKDAYS = ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"]


def read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def zone(name: str) -> ZoneInfo:
    try:
        return ZoneInfo(name)
    except ZoneInfoNotFoundError as exc:
        raise SystemExit(
            f"Unknown time zone {name!r}. Use an IANA name such as 'Europe/Berlin' or 'America/New_York'. "
            "On Windows, install the time zone data first: pip install tzdata"
        ) from exc


@dataclass(frozen=True)
class Group:
    id: str
    name: str
    section: str
    kind: str = ""
    about: str = ""


UNSORTED = Group("unsorted", "Unsorted", "Unsorted", "", "Not placed in a group yet")


@dataclass
class Settings:
    home: Path
    to: str
    title: str
    tz: ZoneInfo
    send_weekday: int
    send_hour: int
    top_projects: int
    idle_days: int
    map_url: str
    summary_enabled: bool
    claude_model: str
    style: str
    reader: str
    login: str
    commit_queries: list[str]
    pr_queries: list[str]
    mail: dict = field(default_factory=dict)
    plans: dict = field(default_factory=dict)
    schedule: dict = field(default_factory=dict)

    @property
    def commit_authors(self) -> list[str]:
        """Values for the REST `author=` filter (login or email), from the search qualifiers."""
        out = []
        for q in self.commit_queries:
            key, _, value = q.partition(":")
            if key in ("author", "author-email") and value:
                out.append(value)
        return out


def _weekday(value) -> int:
    if isinstance(value, int):
        return value % 7
    return WEEKDAYS.index(str(value).strip().lower())


def load_settings(home: Path = DEFAULT_HOME) -> Settings:
    path = home / "config" / "settings.toml"
    if not path.exists():
        raise SystemExit(f"No settings at {path}. Run: python weekly_review.py init --home {home}")
    data = tomllib.loads(read_text(path))
    r, ident, summ = data.get("report", {}), data["identity"], data.get("summary", {})
    return Settings(
        home=home,
        to=r["to"],
        title=r.get("title", "Weekly review"),
        tz=zone(r.get("timezone", "UTC")),
        send_weekday=_weekday(r.get("send_day", "monday")),
        send_hour=int(r.get("send_hour", 7)),
        top_projects=int(r.get("top_projects", 8)),
        idle_days=int(r.get("idle_days", 182)),
        map_url=r.get("map_url", ""),
        summary_enabled=bool(summ.get("enabled", True)),
        claude_model=summ.get("model", "sonnet"),
        style=summ.get("style", "plain"),
        reader=summ.get("reader", ""),
        login=ident["login"],
        commit_queries=list(ident["commit_queries"]),
        pr_queries=list(ident["pr_queries"]),
        mail=dict(data.get("mail", {})),
        plans=dict(data.get("plans", {})),
        schedule=dict(data.get("schedule", {})),
    )


@dataclass
class ProjectMap:
    groups: list[Group]
    explicit: dict[str, str]                 # lower(repo) -> group id
    rules: list[dict]
    exclude: set[str]                        # lower(repo)
    placements: dict[str, dict] = field(default_factory=dict)  # repo -> {"group", "placed_on", "by"}
    path: Path | None = None
    names: dict[str, str] = field(default_factory=dict)       # lower(repo) -> spelling in map.toml
    operating: set[str] = field(default_factory=set)          # lower(repo)
    operating_hints: list[str] = field(default_factory=list)

    @classmethod
    def from_toml(cls, text: str, placements: dict | None = None, path: Path | None = None) -> "ProjectMap":
        data = tomllib.loads(text)
        groups, explicit, names = [], {}, {}
        for g in data.get("group", []):
            groups.append(Group(g["id"], g["name"], g.get("section", g["name"]), g.get("kind", ""), g.get("about", "")))
            for repo in g.get("repos", []):
                explicit[repo.lower()] = g["id"]
                names[repo.lower()] = repo
        ids = {g.id for g in groups}
        for rule in data.get("rule", []):
            if rule["group"] not in ids:
                raise ValueError(f"rule points to unknown group {rule['group']!r}")
        return cls(
            groups=groups,
            explicit=explicit,
            rules=list(data.get("rule", [])),
            exclude={r.lower() for r in data.get("exclude", [])},
            placements=placements or {},
            path=path,
            names=names,
            operating={r.lower() for r in data.get("operating", [])},
            operating_hints=list(data.get("operating_hints", [])),
        )

    @classmethod
    def load(cls, home: Path = DEFAULT_HOME) -> "ProjectMap":
        placements_path = home / "config" / "placements.json"
        placements = json.loads(read_text(placements_path)) if placements_path.exists() else {}
        return cls.from_toml(read_text(home / "config" / "map.toml"), placements, placements_path)

    # -- lookups -----------------------------------------------------------

    def group(self, gid: str) -> Group:
        for g in self.groups:
            if g.id == gid:
                return g
        return UNSORTED

    def has_group(self, gid: str) -> bool:
        return any(g.id == gid for g in self.groups)

    def excluded(self, repo: str) -> bool:
        return repo.lower() in self.exclude

    def is_operating(self, repo: str) -> bool:
        return repo.lower() in self.operating

    def by_rule(self, repo: str) -> Group | None:
        owner, _, name = repo.lower().partition("/")
        for rule in self.rules:
            if "owner" in rule and rule["owner"].lower() != owner:
                continue
            prefixes = [p.lower() for p in rule.get("prefixes", [])]
            if prefixes and not any(name.startswith(p) for p in prefixes):
                continue
            return self.group(rule["group"])
        return None

    def placed(self, repo: str) -> Group | None:
        for key, value in self.placements.items():
            if key.lower() == repo.lower():
                return self.group(value["group"])
        return None

    def group_for(self, repo: str) -> Group | None:
        """Group for a repository, or None if it has never been placed."""
        gid = self.explicit.get(repo.lower())
        if gid:
            return self.group(gid)
        return self.by_rule(repo) or self.placed(repo)

    def sections(self) -> list[str]:
        seen: list[str] = []
        for g in self.groups:
            if g.section not in seen:
                seen.append(g.section)
        return seen

    def groups_in(self, section: str) -> list[Group]:
        return [g for g in self.groups if g.section == section]

    def known_repos(self) -> set[str]:
        """Repositories listed in the map or placed by Claude (original spelling)."""
        return set(self.names.values()) | set(self.placements)

    # -- updates -----------------------------------------------------------

    def add_placements(self, new: dict[str, str], placed_on: str) -> None:
        for repo, gid in new.items():
            self.placements[repo] = {"group": gid, "placed_on": placed_on, "by": "claude"}
        if self.path:
            write_text(self.path, json.dumps(self.placements, indent=2, sort_keys=True) + "\n")
