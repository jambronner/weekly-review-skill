"""Command line: python weekly_review.py [--home DIR] {init,check,build,send,scheduled,demo} ..."""

from __future__ import annotations

import argparse
import json
import os
import platform
import shutil
import subprocess
import sys
import time
import traceback
from datetime import date, datetime, timezone
from pathlib import Path

from . import ai, collect, mail, work
from .config import CODE_ROOT, DEFAULT_HOME, ProjectMap, Settings, load_settings, read_text, write_text
from .render import build_model, render_html, render_text, subject
from .weeks import Week, due_week, week_from_key
from .work import TYPE_NAMES, VELOCITY_TYPES, Labels


def log(msg: str) -> None:
    print(f"[{datetime.now():%Y-%m-%d %H:%M:%S}] {msg}", flush=True)


class Home:
    """The data folder: config/, history/ (keep), cache/ and out/ (both can be rebuilt)."""

    def __init__(self, path: Path):
        self.path = path
        self.config = path / "config"
        self.history = path / "history"
        self.cache = path / "cache"
        self.out = path / "out"

    def hist_path(self, week: Week) -> Path:
        return self.history / f"{week.key}.json"

    def load(self, week: Week) -> dict | None:
        p = self.hist_path(week)
        return json.loads(read_text(p)) if p.exists() else None

    def save(self, doc: dict) -> None:
        write_text(self.history / f"{doc['week_start']}.json", json.dumps(doc, indent=1, sort_keys=True) + "\n")


KEEP_ON_REFRESH = ("sent_at", "sent_via", "ai", "open_prs", "idle", "new_placements", "plans")


def ensure_week(home: Home, week: Week, settings: Settings, cache: collect.StatsCache, refresh: bool) -> dict:
    doc = home.load(week)
    if doc and doc.get("format") == collect.HISTORY_FORMAT and not refresh:
        return doc
    log(f"collecting {week.key}")
    fresh = collect.collect_week(week, settings, cache)
    if doc:  # keep send state and other extras across a data refresh
        for key in KEEP_ON_REFRESH:
            if key in doc:
                fresh[key] = doc[key]
    home.save(fresh)
    return fresh


def doc_repos(doc: dict | None) -> set[str]:
    if not doc:
        return set()
    return {c["repo"] for c in doc.get("commits", [])} | {p["repo"] for p in doc.get("prs_merged", []) + doc.get("prs_opened", [])}


# -- steps --------------------------------------------------------------------

def place_new_repos(docs: list[dict], pmap: ProjectMap, settings: Settings, cur: dict, use_ai: bool) -> None:
    unknown = sorted({
        repo for d in docs for repo in doc_repos(d)
        if not pmap.excluded(repo) and not pmap.is_operating(repo) and pmap.group_for(repo) is None
    })
    if not unknown:
        return
    log(f"placing new repositories: {', '.join(unknown)}")
    groups = [{"id": g.id, "name": g.name, "about": g.about} for g in pmap.groups]
    placements = {r: "unsorted" for r in unknown}
    if use_ai:
        try:
            got = ai.classify([collect.repo_info(r) for r in unknown], groups, settings.claude_model)
            for repo in unknown:
                for key, gid in got.items():
                    if key.lower() == repo.lower():
                        placements[repo] = gid
        except ai.ClaudeError as exc:
            log(f"placement by Claude failed, using Unsorted: {exc}")
    pmap.add_placements(placements, date.today().isoformat())
    cur.setdefault("new_placements", {}).update(placements)


def label_new_work(docs: list[dict], labels: Labels, pmap: ProjectMap, settings: Settings) -> None:
    items = work.unlabeled(docs, labels, pmap)
    if not items:
        return
    log(f"asking Claude to label {len(items)} commits and PRs")
    groups = [{"id": g.id, "name": g.name, "about": g.about} for g in pmap.groups]
    got = ai.label_work(items, groups, pmap.operating_hints, settings.claude_model)
    labels.update(got)
    if len(got) < len(items):
        log(f"{len(items) - len(got)} items have no Claude label; they use the subject-based guess")


def idle_list(week: Week, pmap: ProjectMap, settings: Settings, docs: list[dict]) -> list[dict]:
    repos = set(pmap.known_repos())
    for d in docs:
        repos.update(doc_repos(d))
    active = {r.lower() for r in doc_repos(docs[-1])}
    out = []
    for repo in sorted(repos, key=str.lower):
        if pmap.excluded(repo) or pmap.is_operating(repo) or repo.lower() in active:
            continue
        last = collect.last_activity(repo, settings, settings.idle_days, week.end_dt())
        if last:
            out.append({"repo": repo, "last": last})
    return out


def summary_context(m: dict, cur: dict) -> str:
    t, p = m["totals"], m["prev_totals"]
    week: Week = m["week"]
    out = [f"Week: {week.label()}."]
    out.append(
        f"VELOCITY TOTALS: {t['commits']} commits, {t['prs_merged']} PRs merged, {t['prs_opened']} PRs opened, "
        f"+{t['additions']}/-{t['deletions']} lines, {t['active_days']} of 7 active days, "
        f"{m['focus']['avg']} businesses per active day on average (max {m['focus']['max']}). "
        f"Agents (bots and automated identities): {t['agent_commits']} commits ({m['agent_share']}%) and "
        f"{m['agent_prs']} merged PRs."
    )
    if p:
        out.append(f"LAST WEEK: {p['commits']} commits, {p['prs_merged']} PRs merged, {p['active_days']} active days.")
    op = m["operating"]
    out.append(
        f"\nOPERATING WORK (not velocity): {op['commits']} commits = {m['operating_share']}% of all commits, in "
        + (", ".join(f"{r} ({n})" for r, n in op["repos"].most_common()) or "no repositories")
        + ". Examples: " + " | ".join(op["subjects"][-12:])
    )
    mix_total = sum(m["mix"][k] for k in VELOCITY_TYPES) or 1
    out.append("\nWORK MIX (velocity commits by type): " + ", ".join(
        f"{TYPE_NAMES[k]} {m['mix'][k]} ({round(m['mix'][k] / mix_total * 100)}%)" for k in VELOCITY_TYPES))
    out.append("\nBUSINESSES (section > business | commits | last week | PRs merged | mix)")
    for g in sorted(m["groups"].values(), key=lambda g: -g["commits"]):
        mix = ", ".join(f"{k} {n}" for k, n in g["types"].most_common())
        out.append(f"- {g['group'].section} > {g['group'].name} | {g['commits']} | {g['prev_commits']} | {g['prs_merged']} | {mix}")
    out.append("\nMERGED PRS (repo#number | business | type | title | description start)")
    for pr in m["merged"]:
        out.append(f"- {pr['repo']}#{pr['number']} | {pr['group'].name} | {pr['type']} | {pr['title']} | {pr.get('body', '')[:150]}")
    out.append("\nDIRECT COMMITS (latest subjects per business, velocity only)")
    by_group: dict[str, list[str]] = {}
    for c in m["commits"]:
        by_group.setdefault(c["group"].name, []).append(f"[{c['type']}] {c['subject']}")
    for name, subjects in by_group.items():
        out.append(f"- {name}: " + " | ".join(subjects[-10:]))
    out.append(
        f"\nOPEN PRS: {m['open_now_total']} open now; {len(m['stale'])} have waited 7 to 90 days; "
        f"{m['abandoned']} are older than 90 days (probably abandoned; mention only as a cleanup count). "
        "Waiting 7 to 90 days, oldest first:"
    )
    for s in m["stale"][:8]:
        out.append(f"- {s['repo']}#{s['number']} ({s['age']} days): {s['title']}")
    recent_idle = [i for i in m["idle"] if i["days"] <= 30]
    if recent_idle:
        out.append("\nIDLE THIS WEEK BUT ACTIVE IN THE LAST 30 DAYS: " + ", ".join(f"{i['name']} ({i['days']} days)" for i in recent_idle))
    plans = cur.get("plans") or {}
    daily = plans.get("daily")
    if daily:
        age = (week.end - date.fromisoformat(daily["date"])).days
        out.append(f"\nPLAN: newest priorities file {daily['name']}, dated {daily['date']}, {age} days before the week ended.")
        out.append("<<<PLAN TEXT\n" + daily["text"] + "\nPLAN TEXT>>>")
    else:
        out.append("\nPLAN: no priorities file.")
    if plans.get("plans_this_week"):
        out.append("PLAN FILES WRITTEN THIS WEEK: " + ", ".join(plans["plans_this_week"]))
    return "\n".join(out)


def build(home: Home, week: Week, *, refresh: bool = False, refresh_ai: bool = False, use_ai: bool = True) -> tuple[str, str, str, dict]:
    settings = load_settings(home.path)
    pmap = ProjectMap.load(home.path)
    cache = collect.StatsCache(home.cache / "commit_stats.json")
    labels = Labels(home.history / "labels.json")
    use_ai = use_ai and settings.summary_enabled

    weeks = [week.prev(3), week.prev(2), week.prev(1), week]
    docs = [ensure_week(home, w, settings, cache, refresh and w == week) for w in weeks]
    cur = docs[-1]

    if refresh or not isinstance(cur.get("open_prs"), list):
        log("listing open PRs")
        cur["open_prs"] = collect.open_prs(settings)
    if refresh or "plans" not in cur:
        cur["plans"] = collect.fetch_plans(week, settings)
    place_new_repos(docs, pmap, settings, cur, use_ai)
    if use_ai:
        label_new_work(docs, labels, pmap, settings)
    if refresh or "idle" not in cur:
        log("checking idle projects")
        cur["idle"] = idle_list(week, pmap, settings, docs)
    home.save(cur)

    works = [work.attribute(d, labels, pmap) if d else None for d in docs]
    model = build_model(week, works, cur, pmap, settings)
    has_v2 = (cur.get("ai") or {}).get("version") == 2
    if use_ai and (refresh_ai or not has_v2) and model["projects"]:
        log("asking Claude for the summary")
        merged_refs = {(p["repo"], p["number"]) for p in model["merged"]}
        try:
            cur["ai"] = ai.summarize(summary_context(model, cur), merged_refs, settings.claude_model,
                                     settings.style, settings.reader)
            home.save(cur)
            model = build_model(week, works, cur, pmap, settings)
        except (ai.ClaudeError, json.JSONDecodeError) as exc:
            log(f"summary failed, continuing without it: {exc}")

    html, text, subj = render_html(model, settings), render_text(model), subject(model)
    out = home.out / f"{week.key}.html"
    write_text(out, html)
    log(f"wrote {out} ({len(html.encode()) // 1024} KB)")
    return subj, html, text, cur


def send(home: Home, week: Week, **kw) -> None:
    settings = load_settings(home.path)
    subj, html, text, cur = build(home, week, **kw)
    result = mail.send(settings, subj, html, text)
    log(f"{result}: {subj}")
    cur["sent_at"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
    cur["sent_via"] = settings.mail.get("method", "none")
    home.save(cur)


# -- commands -------------------------------------------------------------------

def cmd_init(home: Home) -> int:
    for name in ("settings.toml", "map.toml"):
        target = home.config / name
        if target.exists():
            log(f"kept existing {target}")
        else:
            write_text(target, read_text(CODE_ROOT / "examples" / name))
            log(f"wrote {target}")
    placements = home.config / "placements.json"
    if not placements.exists():
        write_text(placements, "{}\n")
    print(f"\nNext: edit {home.config / 'settings.toml'} and {home.config / 'map.toml'}, then run: "
          f"python weekly_review.py --home {home.path} check")
    return 0


def cmd_check(home: Home) -> int:
    """Check GitHub, Claude and mail access without sending anything."""
    settings = load_settings(home.path)
    ProjectMap.load(home.path)  # fails early on a broken map
    ok = True
    steps = [
        ("GitHub", lambda: "signed in as " + collect.gh.api("user", jq=".login").strip()),
        ("Claude", lambda: ("replied " + ai.ask("Reply with only the word OK.", settings.claude_model).strip()[:20])
         if settings.summary_enabled else "summary disabled"),
        ("Mail", lambda: mail.check(settings)),
    ]
    for name, step in steps:
        try:
            print(f"{name}: OK, {step()}")
        except Exception as exc:  # noqa: BLE001
            ok = False
            print(f"{name}: FAILED, {exc}")
    return 0 if ok else 1


class RunLock:
    """A cross-platform lock file: one run at a time; a lock older than 3 hours is treated as stale."""

    def __init__(self, path: Path):
        self.path = path
        self.fd = None

    def __enter__(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        if self.path.exists() and time.time() - self.path.stat().st_mtime > 3 * 3600:
            self.path.unlink(missing_ok=True)
        try:
            self.fd = os.open(self.path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            os.write(self.fd, str(os.getpid()).encode())
            return self
        except FileExistsError:
            return None

    def __exit__(self, *exc):
        if self.fd is not None:
            os.close(self.fd)
            self.path.unlink(missing_ok=True)


def notify(home: Home, settings: Settings, message: str) -> None:
    """Tell the user about a failure: their own command, or a desktop notification where one is easy (max every 6 h)."""
    stamp = home.cache / "last_failure_notice"
    if stamp.exists() and time.time() - stamp.stat().st_mtime < 6 * 3600:
        return
    write_text(stamp, message)
    custom = settings.schedule.get("on_failure_command", "")
    try:
        if custom:
            subprocess.run(custom, shell=True, timeout=30, env={**os.environ, "WR_MESSAGE": message})
        elif platform.system() == "Darwin":
            subprocess.run(["osascript", "-e", f'display notification {json.dumps(message)} with title "Weekly review"'], timeout=20)
        elif platform.system() == "Linux" and shutil.which("notify-send"):
            subprocess.run(["notify-send", "Weekly review", message], timeout=20)
    except (OSError, subprocess.SubprocessError):
        pass


def git(home: Home, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(["git", "-C", str(home.path), *args], capture_output=True, text=True, encoding="utf-8",
                          errors="replace", timeout=120)


def cmd_scheduled(home: Home) -> int:
    """Run by your scheduler every hour (or more often). It sends once, when a report is due and not yet sent."""
    settings = load_settings(home.path)
    week = due_week(datetime.now(timezone.utc), settings.tz, settings.send_weekday, settings.send_hour)
    doc = home.load(week)
    if doc and doc.get("sent_at"):
        return 0
    with RunLock(home.cache / "run.lock") as lock:
        if lock is None:
            log("another run is active")
            return 0
        git_sync = bool(settings.schedule.get("git_sync")) and (home.path / ".git").exists()
        try:
            if git_sync:
                pull = git(home, "pull", "--ff-only", "--quiet")
                if pull.returncode != 0:
                    log(f"git pull failed, using local files: {pull.stderr.strip()}")
                doc = home.load(week)
                if doc and doc.get("sent_at"):
                    return 0
            log(f"report for {week.key} is due")
            send(home, week, refresh=True, refresh_ai=True)
            if git_sync:
                git(home, "add", "history", "config/placements.json")
                if git(home, "commit", "-m", f"Weekly review {week.key}", "--quiet").returncode == 0:
                    push = git(home, "push", "--quiet")
                    if push.returncode != 0:
                        log(f"git push failed: {push.stderr.strip()}")
            return 0
        except Exception as exc:  # noqa: BLE001 - log, notify, retry next run
            log("run failed:\n" + traceback.format_exc())
            notify(home, settings, f"Weekly review failed: {exc}"[:200])
            return 1


def cmd_demo(home: Home) -> int:
    from . import demo
    week = demo.generate(home.path)
    subj, *_ = build(home, week, use_ai=False)
    print(subj)
    print(f"Open {home.out / (week.key + '.html')} in a browser.")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="weekly_review.py", description="A weekly email of your GitHub work by business and project.")
    parser.add_argument("--home", default=str(DEFAULT_HOME), help="data folder (default: $WEEKLY_REVIEW_HOME or ~/.weekly-review)")
    sub = parser.add_subparsers(dest="cmd", required=True)
    sub.add_parser("init", help="write example config files to the data folder")
    sub.add_parser("check", help="check GitHub, Claude and mail access; sends nothing")
    for name, text in (("build", "write the report HTML; sends nothing"), ("send", "build and send the report")):
        p = sub.add_parser(name, help=text)
        p.add_argument("--week", help="first day of the week, YYYY-MM-DD (default: the week now due)")
        p.add_argument("--refresh", action="store_true", help="collect the report week again")
        p.add_argument("--refresh-ai", action="store_true", help="ask Claude again for the summary")
        p.add_argument("--no-ai", action="store_true", help="skip Claude (labels, summary and placement)")
    sub.add_parser("scheduled", help="for your scheduler: send once when a report is due")
    sub.add_parser("demo", help="build a report from made-up data in the data folder (no GitHub, no Claude)")
    args = parser.parse_args(argv)
    home = Home(Path(args.home).expanduser())

    if args.cmd == "init":
        return cmd_init(home)
    if args.cmd == "check":
        return cmd_check(home)
    if args.cmd == "scheduled":
        return cmd_scheduled(home)
    if args.cmd == "demo":
        return cmd_demo(home)
    settings = load_settings(home.path)
    week = week_from_key(args.week, settings.tz) if args.week else due_week(
        datetime.now(timezone.utc), settings.tz, settings.send_weekday, settings.send_hour)
    kw = {"refresh": args.refresh, "refresh_ai": args.refresh_ai, "use_ai": not args.no_ai}
    if args.cmd == "build":
        subj, *_ = build(home, week, **kw)
        print(subj)
    else:
        send(home, week, **kw)
    return 0


if __name__ == "__main__":
    sys.exit(main())
