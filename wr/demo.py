"""Made-up data for a demo report and the README screenshots. No GitHub calls, no Claude calls.

Everything here is fictional. The brand names are Microsoft's well-known fictional sample brands (Contoso,
Northwind, Fabrikam, Tailspin, Wingtip). Account names contain "_", which GitHub does not allow, so no link
can reach a real account.
"""

from __future__ import annotations

import hashlib
import json
import random
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

from .config import ProjectMap, load_settings, write_text
from .weeks import Week

LOGIN = "demo_dev"
ORG = "contoso_studio"
NOTES = f"{LOGIN}/studio-notes"
FIRST_WEEK = date(2026, 10, 12)  # a Monday; the report week is the fourth week

SETTINGS = f"""[report]
to = "you@example.com"
title = "Weekly review"
timezone = "America/New_York"
send_day = "monday"
send_hour = 7
top_projects = 8
idle_days = 182
map_url = ""

[summary]
enabled = true
model = "sonnet"
style = "plain"
reader = ""

[identity]
login = "{LOGIN}"
commit_queries = ["author:{LOGIN}", "author-email:agent@example.com"]
pr_queries = ["author:{LOGIN}", "author:app/demo_build_agent"]

[mail]
method = "none"
"""

MAP = f"""operating = ["{NOTES}"]
operating_hints = ["Proposals and estimates for a client -> that client's group", "Notes, research, plans -> operating"]

[[group]]
id = "web"
name = "Website & marketing"
section = "Contoso Studio"
about = "The studio website and marketing"
repos = ["{ORG}/studio-site"]

[[group]]
id = "northwind"
name = "Northwind Outfitters"
section = "Contoso Studio"
kind = "client"
about = "Client: an online outdoor clothing shop"
repos = ["{ORG}/northwind-shop"]

[[group]]
id = "fabrikam"
name = "Fabrikam Dental"
section = "Contoso Studio"
kind = "client"
about = "Client: booking and reminders for a dental practice"
repos = ["{ORG}/fabrikam-booking"]

[[group]]
id = "tailspin"
name = "Tailspin"
section = "Contoso Studio"
kind = "product"
about = "Product: invoicing for small teams"
repos = ["{ORG}/tailspin"]

[[group]]
id = "wingtip"
name = "Wingtip"
section = "Contoso Studio"
kind = "product"
about = "Product: a tide and surf forecast app"
repos = ["{ORG}/wingtip-app"]

[[group]]
id = "side"
name = "Side projects"
section = "Side projects"
about = "Things that could ship one day"
repos = ["{LOGIN}/pixel-garden"]

[[group]]
id = "personal"
name = "Personal tools"
section = "Personal tools"
about = "Tools only for me"
repos = ["{LOGIN}/recipe-box"]
"""

# repo -> (commits per week [w-3..w], type weights, themes per type)
REPOS = {
    f"{ORG}/studio-site": ([6, 9, 4, 8], {"feature": 3, "fix": 2, "content": 4, "automation": 1}, {
        "feature": ["case study pages", "a newsletter sign-up", "an accessible color theme"],
        "fix": ["broken footer links", "a slow hero image", "the contact form spam filter"],
        "content": ["the spring case study", "the pricing page copy", "the services page"],
        "automation": ["image checks in CI"]}),
    f"{ORG}/northwind-shop": ([14, 18, 22, 26], {"feature": 4, "fix": 4, "content": 1, "automation": 2}, {
        "feature": ["gift cards", "saved carts", "a size guide", "back-in-stock alerts"],
        "fix": ["checkout tax rounding", "the mobile menu", "search ranking for sale items", "duplicate order emails"],
        "content": ["the holiday landing page copy"],
        "automation": ["the nightly price sync", "payment webhook tests"]}),
    f"{ORG}/fabrikam-booking": ([10, 6, 3, 5], {"feature": 3, "fix": 3, "content": 1, "automation": 1}, {
        "feature": ["SMS reminders", "an insurance form", "family bookings"],
        "fix": ["the reminder time zone bug", "double bookings on Mondays"],
        "content": ["the patient FAQ"],
        "automation": ["calendar sync retries"]}),
    f"{ORG}/tailspin": ([18, 22, 15, 12], {"feature": 4, "fix": 3, "content": 1, "automation": 2}, {
        "feature": ["CSV import", "multi-currency invoices", "team roles", "recurring invoices"],
        "fix": ["rounding in tax totals", "PDF page breaks", "the reminder schedule"],
        "content": ["the billing help pages"],
        "automation": ["a database backup check", "the dependency update bot"]}),
    f"{ORG}/wingtip-app": ([4, 0, 8, 11], {"feature": 5, "fix": 3, "content": 1, "automation": 1}, {
        "feature": ["offline mode", "tide alerts", "a swell chart", "favorite beaches"],
        "fix": ["a crash on older Android phones", "wrong units in the wind chart"],
        "content": ["the App Store text"],
        "automation": ["release builds in CI"]}),
    f"{LOGIN}/pixel-garden": ([0, 5, 2, 3], {"feature": 4, "fix": 2, "automation": 1}, {
        "feature": ["seasonal plants", "save slots", "a watering minigame"],
        "fix": ["the night sky colors"], "automation": ["the web build"]}),
    f"{LOGIN}/recipe-box": ([2, 0, 0, 0], {"feature": 1}, {"feature": ["shopping lists"]}),
    NOTES: ([8, 10, 7, 12], {"operating": 5, "content": 2}, {
        "operating": ["the weekly client call notes", "research on booking APIs", "the Tailspin launch checklist",
                      "the agent context for Northwind", "the Monday plan"],
        "content": ["the Fabrikam phase 2 proposal", "the Northwind Q4 estimate"]}),
}
PREFIX = {"feature": "feat: add", "fix": "fix:", "content": "docs: write", "automation": "chore: update", "operating": "Record"}
SIZES = {"feature": (80, 420), "fix": (4, 70), "content": (30, 260), "automation": (10, 140), "operating": (15, 160)}
PATHS = {"feature": "src/features", "fix": "src", "content": "content", "automation": ".github/workflows", "operating": "notes"}

# PRs that must merge in the report week (the summary and "Top shipped" talk about them).
FORCED = [
    (f"{ORG}/northwind-shop", "Add gift cards", "feature"),
    (f"{ORG}/northwind-shop", "Add saved carts", "feature"),
    (f"{ORG}/northwind-shop", "Fix checkout tax rounding", "fix"),
    (f"{ORG}/wingtip-app", "Add offline mode", "feature"),
    (f"{ORG}/wingtip-app", "Add tide alerts", "feature"),
    (f"{ORG}/tailspin", "Add CSV import", "feature"),
    (f"{ORG}/fabrikam-booking", "Fix the reminder time zone bug", "fix"),
]


def _sha(*parts) -> str:
    return hashlib.sha1("|".join(map(str, parts)).encode()).hexdigest()


def _weekday_dates(start: date, rng: random.Random, n: int) -> list[str]:
    weights = [6, 6, 6, 6, 5, 1, 1]  # Mon ... Sun
    days = rng.choices(range(7), weights=weights, k=n)
    return sorted((start + timedelta(days=d)).isoformat() for d in days)


def _week_doc(index: int, start: date, labels: dict) -> dict:
    rng = random.Random(100 + index)
    commits, merged, opened = [], [], []
    pr_number = {repo: 40 + 30 * index for repo in REPOS}
    for repo, (counts, weights, themes) in REPOS.items():
        n = counts[index]
        types = rng.choices(list(weights), weights=list(weights.values()), k=n)
        for i, (t, day) in enumerate(zip(types, _weekday_dates(start, rng, n))):
            theme = rng.choice(themes[t])
            subject = f"{PREFIX[t]} {theme}"
            sha = _sha(repo, index, i, subject)
            lo, hi = SIZES[t]
            agent = repo.endswith(("northwind-shop", "tailspin")) and rng.random() < 0.18
            commits.append({"sha": sha, "repo": repo, "date": day, "ts": day + "T15:00:00Z",
                             "add": rng.randint(lo, hi), "del": rng.randint(0, hi // 4),
                             "subject": subject, "agent": agent,
                             "paths": [f"{PATHS[t]}/{theme.split()[-1]}.ts" if t != "operating" else f"notes/{day}.md"]})
            group = None
            if repo == NOTES and t == "content":
                group = "fabrikam" if "Fabrikam" in theme else "northwind"
            labels[sha[:12]] = {"t": t, "g": (group or ("operating" if repo == NOTES else None))}
            if repo != NOTES and t != "operating" and rng.random() < 0.55:
                pr_number[repo] += 1
                pr = {"repo": repo, "number": pr_number[repo], "title": subject.split(": ", 1)[-1].capitalize(),
                      "url": f"https://github.com/{repo}/pull/{pr_number[repo]}", "author": LOGIN,
                      "agent": agent, "draft": False, "created_at": day + "T10:00:00Z",
                      "merged_at": day + "T17:00:00Z", "body": ""}
                merged.append(pr)
                opened.append(pr)
                labels[f"{repo}#{pr['number']}"] = {"t": t, "g": None}
    if index == 3:
        for repo, title, t in FORCED:
            pr_number[repo] += 1
            day = (start + timedelta(days=rng.choice([2, 3, 4, 5, 6]))).isoformat()
            pr = {"repo": repo, "number": pr_number[repo], "title": title,
                  "url": f"https://github.com/{repo}/pull/{pr_number[repo]}", "author": LOGIN, "agent": False,
                  "draft": False, "created_at": day + "T10:00:00Z", "merged_at": day + "T17:00:00Z", "body": ""}
            merged.append(pr)
            opened.append(pr)
            labels[f"{repo}#{pr['number']}"] = {"t": t, "g": None}
    return {"format": 2, "week_start": start.isoformat(), "generated_at": "2026-11-09T12:00:00+00:00",
            "commits": sorted(commits, key=lambda c: c["date"]), "prs_merged": merged, "prs_opened": opened}


def generate(home: Path) -> Week:
    """Write a demo data folder (config, 4 weeks of history, labels) and return the report week."""
    write_text(home / "config" / "settings.toml", SETTINGS)
    write_text(home / "config" / "map.toml", MAP)
    write_text(home / "config" / "placements.json", json.dumps(
        {f"{LOGIN}/reading-list": {"group": "personal", "placed_on": "2026-11-09", "by": "claude"}}, indent=2) + "\n")

    labels: dict = {}
    docs = []
    for i in range(4):
        docs.append(_week_doc(i, FIRST_WEEK + timedelta(days=7 * i), labels))
    cur = docs[-1]
    # A new repository that Claude placed this week, so the "New this week" box shows.
    rt = f"{LOGIN}/reading-list"
    for j, day in enumerate(["2026-11-03", "2026-11-05"]):
        sha = _sha(rt, j)
        cur["commits"].append({"sha": sha, "repo": rt, "date": day, "ts": day + "T07:00:00Z", "add": 120, "del": 6,
                               "subject": "feat: add a books-per-month chart", "agent": False, "paths": ["src/chart.ts"]})
        labels[sha[:12]] = {"t": "feature", "g": None}
    cur["new_placements"] = {rt: "personal"}
    week_end = datetime(2026, 11, 9, tzinfo=timezone.utc)
    cur["open_prs"] = [
        {"repo": f"{ORG}/tailspin", "number": 131, "title": "Multi-currency invoices", "url": f"https://github.com/{ORG}/tailspin/pull/131",
         "author": LOGIN, "agent": False, "draft": False, "created_at": (week_end - timedelta(days=19)).isoformat(), "merged_at": "", "body": ""},
        {"repo": f"{ORG}/northwind-shop", "number": 140, "title": "Back-in-stock alerts", "url": f"https://github.com/{ORG}/northwind-shop/pull/140",
         "author": "demo_build_agent[bot]", "agent": True, "draft": False, "created_at": (week_end - timedelta(days=3)).isoformat(), "merged_at": "", "body": ""},
        {"repo": f"{ORG}/studio-site", "number": 12, "title": "Old blog theme experiment", "url": f"https://github.com/{ORG}/studio-site/pull/12",
         "author": LOGIN, "agent": False, "draft": True, "created_at": (week_end - timedelta(days=140)).isoformat(), "merged_at": "", "body": ""},
    ]
    cur["idle"] = [
        {"repo": f"{LOGIN}/recipe-box", "last": "2026-10-15T12:00:00Z"},
        {"repo": f"{ORG}/old-portfolio", "last": "2026-08-02T12:00:00Z"},
    ]
    cur["plans"] = {}
    write_text(home / "history" / "labels.json", json.dumps(labels, indent=0, sort_keys=True) + "\n")
    for d in docs:
        write_text(home / "history" / f"{d['week_start']}.json", json.dumps(d, indent=1, sort_keys=True) + "\n")

    # Write the summary from the real numbers of the demo data, as Claude would.
    from .render import build_model
    from .work import Labels, attribute
    settings = load_settings(home)
    pmap = ProjectMap.load(home)
    lab = Labels(home / "history" / "labels.json")
    week = Week(FIRST_WEEK + timedelta(days=21), settings.tz)
    works = [attribute(d, lab, pmap) for d in docs]
    m = build_model(week, works, cur, pmap, settings)
    mix_total = sum(m["mix"].values()) or 1
    fixes = round(m["mix"]["fix"] / mix_total * 100)
    stale = m["stale"][0]
    g = m["groups"]
    picks = [("northwind-shop", "Add gift cards", "Gift cards at checkout"),
             ("wingtip-app", "Add offline mode", "Offline mode for the app"),
             ("tailspin", "Add CSV import", "CSV import for invoices"),
             ("northwind-shop", "Fix checkout tax rounding", "Correct tax totals at checkout"),
             ("wingtip-app", "Add tide alerts", "Tide alerts")]
    top = []
    for repo, title, label in picks:
        pr = next(p for p in cur["prs_merged"] if p["repo"].endswith(repo) and p["title"] == title)
        top.append({"repo": pr["repo"], "number": pr["number"], "label": label})
    cur["ai"] = {
        "version": 2,
        "headline": "Northwind and Wingtip carried the week; Tailspin slowed again.",
        "moved": [
            "Northwind Outfitters: gift cards and saved carts shipped, and checkout tax totals are now correct.",
            "Wingtip: offline mode and tide alerts are ready for the beta.",
            "Tailspin: CSV import shipped; multi-currency invoices are still in review.",
            "Fabrikam Dental: the phase 2 proposal went out, and the reminder time zone bug is fixed.",
        ],
        "how": [
            f"Focus was spread thin. You touched {m['focus']['avg']:g} businesses per active day, "
            f"and Northwind alone took {g['northwind']['commits']} commits.",
            f"Healthy mix. Fixes were {fixes}% of velocity commits, operating work stayed at {m['operating_share']}%, "
            f"and your agents made {m['agent_share']}% of commits.",
        ],
        "next": [
            f"Tailspin fell from {g['tailspin']['prev_commits']} to {g['tailspin']['commits']} commits. "
            "Block one day for multi-currency invoices.",
            f"Review {stale['repo'].split('/')[1]}#{stale['number']}; it has waited {stale['age']} days.",
        ],
        "top_shipped": top,
    }
    write_text(home / "history" / f"{cur['week_start']}.json", json.dumps(cur, indent=1, sort_keys=True) + "\n")
    return week
