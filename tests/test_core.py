import json
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from wr.__main__ import Home, RunLock, build, main
from wr.collect import ignored_path
from wr.config import ProjectMap, Settings
from wr.render import build_model, delta, fmt_k, render_html
from wr.weeks import Week, due_week, local_date
from wr.work import Labels, attribute, guess_type, unlabeled

TZ = ZoneInfo("America/New_York")

MAP = """
exclude = ["me/Skip-Me"]
operating = ["me/ops"]
[[group]]
id = "a"
name = "Alpha"
section = "Biz"
repos = ["me/Alpha-Site"]
[[group]]
id = "b"
name = "Beta"
section = "Biz"
repos = []
[[rule]]
owner = "Org"
group = "a"
[[rule]]
prefixes = ["beta"]
group = "b"
"""


def settings(**over) -> Settings:
    base = dict(home=Path("."), to="x@example.com", title="Weekly review", tz=TZ, send_weekday=0, send_hour=7,
                top_projects=8, idle_days=182, map_url="", summary_enabled=True, claude_model="sonnet",
                style="plain", reader="", login="me", commit_queries=["author:me"], pr_queries=["author:me"])
    base.update(over)
    return Settings(**base)


class WeekTests(unittest.TestCase):
    # Defaults: send on Monday at 07:00; the report covers the 7 days before (Monday to Sunday).
    def test_due_before_send_hour_is_previous_week(self):
        self.assertEqual(due_week(datetime(2026, 11, 9, 6, 59, tzinfo=TZ), TZ).key, "2026-10-26")

    def test_due_at_send_hour_is_this_week(self):
        self.assertEqual(due_week(datetime(2026, 11, 9, 7, 0, tzinfo=TZ), TZ).key, "2026-11-02")

    def test_due_midweek(self):
        self.assertEqual(due_week(datetime(2026, 11, 12, 15, 0, tzinfo=TZ), TZ).key, "2026-11-02")

    def test_other_send_day(self):
        friday = 4
        self.assertEqual(due_week(datetime(2026, 11, 13, 9, 0, tzinfo=TZ), TZ, send_weekday=friday, send_hour=8).key, "2026-11-06")

    def test_search_range_crosses_dst(self):
        w = Week(datetime(2026, 10, 26).date(), TZ)
        self.assertEqual(w.search_range(), "2026-10-26T00:00:00-04:00..2026-11-01T23:59:59-05:00")
        self.assertEqual(w.label(), "Oct 26 – Nov 1, 2026")

    def test_local_date(self):
        self.assertEqual(local_date("2026-11-07T03:00:00Z", TZ), "2026-11-06")


class MapTests(unittest.TestCase):
    def setUp(self):
        self.pmap = ProjectMap.from_toml(MAP, {"me/new-thing": {"group": "b"}})

    def test_explicit_is_case_insensitive(self):
        self.assertEqual(self.pmap.group_for("ME/alpha-site").id, "a")

    def test_rules(self):
        self.assertEqual(self.pmap.group_for("Org/whatever").id, "a")
        self.assertEqual(self.pmap.group_for("me/beta-two").id, "b")

    def test_placements_and_unknown(self):
        self.assertEqual(self.pmap.group_for("me/new-thing").id, "b")
        self.assertIsNone(self.pmap.group_for("me/unknown"))

    def test_exclude_and_operating(self):
        self.assertTrue(self.pmap.excluded("me/skip-me"))
        self.assertTrue(self.pmap.is_operating("ME/ops"))

    def test_known_repos_keep_spelling(self):
        self.assertIn("me/Alpha-Site", self.pmap.known_repos())


class CollectTests(unittest.TestCase):
    def test_ignored_paths(self):
        for p in ["package-lock.json", "web/yarn.lock", "dist/app.js", "a/b.min.js", "src/__generated__/schema.ts",
                  "db/migrations/meta/0001_snapshot.json", "THIRD_PARTY_LICENSES.txt", "data/export.json", "icons/logo.svg"]:
            self.assertTrue(ignored_path(p), p)
        for p in ["src/app.ts", "README.md", "build.py", "lockers/x.ts", "db/migrations/0001_init.sql"]:
            self.assertFalse(ignored_path(p), p)


def _commit(sha, repo, subject, date="2026-11-02", add=10, rem=1, agent=False):
    return {"sha": sha * 12, "repo": repo, "subject": subject, "date": date, "ts": date + "T15:00:00Z",
            "add": add, "del": rem, "agent": agent, "paths": []}


def _pr(repo, number, title):
    return {"repo": repo, "number": number, "title": title, "url": f"https://github.com/{repo}/pull/{number}",
            "author": "me", "agent": False, "draft": False, "created_at": "2026-10-20T10:00:00Z", "merged_at": "", "body": ""}


DOC = {
    "format": 2, "week_start": "2026-11-02",
    "commits": [
        _commit("a", "me/alpha-site", "feat: add pricing page", "2026-11-02", 100, 5),
        _commit("b", "me/alpha-site", "fix: broken link", "2026-11-03", 3, 1, agent=True),
        _commit("c", "me/ops", "feat(beta): beta article draft", "2026-11-03", 50, 0),
        _commit("d", "me/ops", "Record meeting notes", "2026-11-04", 20, 0),
        _commit("e", "me/skip-me", "feat: hidden", "2026-11-04"),
    ],
    "prs_merged": [_pr("me/alpha-site", 7, "Add pricing page")],
    "prs_opened": [],
    "open_prs": [_pr("me/alpha-site", 9, "Old idea")],
}


class WorkTests(unittest.TestCase):
    def setUp(self):
        self.pmap = ProjectMap.from_toml(MAP)
        self.tmp = tempfile.TemporaryDirectory()
        self.labels = Labels(Path(self.tmp.name) / "labels.json")
        self.labels.update({"cccccccccccc": {"t": "content", "g": "b"}})  # ops commit c serves group b

    def tearDown(self):
        self.tmp.cleanup()

    def test_guess_type(self):
        self.assertEqual(guess_type("feat(x): thing"), "feature")
        self.assertEqual(guess_type("fix: thing"), "fix")
        self.assertEqual(guess_type("docs: readme"), "content")
        self.assertEqual(guess_type("Record the call notes"), "operating")
        self.assertEqual(guess_type("Add a search box"), "feature")
        self.assertEqual(guess_type("Update the README"), "automation")

    def test_attribute_operating_repo(self):
        w = attribute(DOC, self.labels, self.pmap)
        self.assertEqual(w.rows[("me/alpha-site", "a")].commits, 2)
        self.assertEqual(w.rows[("me/alpha-site", "a")].agent_commits, 1)
        self.assertEqual(w.rows[("me/ops", "b")].commits, 1)       # credited to the business it serves
        self.assertEqual(w.rows[("me/ops", "b")].types["content"], 1)
        self.assertEqual(w.operating["commits"], 1)               # the meeting notes
        self.assertNotIn(("me/skip-me", "a"), w.rows)              # excluded

    def test_unlabeled_lists_only_new_items(self):
        ids = {i["id"] for i in unlabeled([DOC], self.labels, self.pmap)}
        self.assertNotIn("cccccccccccc", ids)
        self.assertIn("dddddddddddd", ids)
        self.assertIn("me/alpha-site#7", ids)
        self.assertNotIn("eeeeeeeeeeee", ids)

    def test_render_smoke(self):
        week = Week(datetime(2026, 11, 2).date(), TZ)
        works = [None, None, None, attribute(DOC, self.labels, self.pmap)]
        m = build_model(week, works, DOC, self.pmap, settings())
        self.assertEqual(m["totals"]["commits"], 3)
        self.assertEqual(m["operating_share"], 25)
        self.assertEqual(len(m["stale"]), 1)
        html = render_html(m, settings())
        self.assertIn("Work mix", html)
        self.assertIn("1 operating commits", html)
        self.assertIn("for Beta", html)
        self.assertIn("Monday to Sunday", html)
        self.assertNotIn("None", html)


class HelperTests(unittest.TestCase):
    def test_delta(self):
        self.assertEqual(delta(150, 100)[0], "▲ 50%")
        self.assertEqual(delta(50, 100)[0], "▼ 50%")
        self.assertEqual(delta(5, 0)[0], "▲ from 0")
        self.assertEqual(delta(5, None)[0], "")
        self.assertEqual(delta(6, 5, "abs")[0], "▲ 1 day")

    def test_fmt_k(self):
        self.assertEqual(fmt_k(950), "950")
        self.assertEqual(fmt_k(12_345), "12.3k")
        self.assertEqual(fmt_k(20_000), "20k")

    def test_run_lock_is_exclusive(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "run.lock"
            with RunLock(path) as first:
                self.assertIsNotNone(first)
                with RunLock(path) as second:
                    self.assertIsNone(second)
            self.assertFalse(path.exists())


class EndToEndTests(unittest.TestCase):
    def test_demo_builds_offline(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.assertEqual(main(["--home", tmp, "demo"]), 0)
            html = (Path(tmp) / "out" / "2026-11-02.html").read_text(encoding="utf-8")
            self.assertIn("Contoso Studio", html)
            self.assertIn("Northwind and Wingtip carried the week", html)
            self.assertIn("github.com/demo_dev/", html)  # "_" is not allowed in GitHub names
            self.assertLess(len(html.encode()), 90_000)  # Gmail clips messages over about 102 KB

    def test_init_writes_templates_once(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.assertEqual(main(["--home", tmp, "init"]), 0)
            settings_file = Path(tmp) / "config" / "settings.toml"
            self.assertIn("your-github-login", settings_file.read_text(encoding="utf-8"))
            settings_file.write_text("changed", encoding="utf-8")
            main(["--home", tmp, "init"])
            self.assertEqual(settings_file.read_text(encoding="utf-8"), "changed")
            self.assertEqual(json.loads((Path(tmp) / "config" / "placements.json").read_text(encoding="utf-8")), {})


if __name__ == "__main__":
    unittest.main()
