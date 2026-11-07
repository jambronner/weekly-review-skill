"""Build the report model from attributed weekly work, then render an email-safe HTML email and a text version."""

from __future__ import annotations

from collections import Counter
from datetime import date, datetime
from html import escape

from .config import UNSORTED, WEEKDAYS, ProjectMap, Settings
from .weeks import Week
from .work import TYPE_NAMES, VELOCITY_TYPES, WeekWork

# Colors: a color-blind-safe categorical palette, checked for contrast on the light card surface.
FONT = "-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,Helvetica,Arial,sans-serif"
PAGE = "#f3f2ef"
CARD = "#fcfcfb"
TILE = "#f4f3ef"
INK = "#0b0b0b"
INK2 = "#52514e"
MUTED = "#6b6a65"
FAINT = "#9a9993"
RULE = "#e6e5e0"
ACCENT = "#2a78d6"
EMPTY = "#d9d7d0"
UP = "#006300"
DOWN = "#d03b3b"
SPARK = "▁▂▃▄▅▆▇█"
TYPE_COLORS = {"feature": "#2a78d6", "fix": "#eb6834", "content": "#1baf7a", "automation": "#eda100"}
STALE_DAYS = 7
PROJECT_URL = "https://github.com/jambronner/weekly-review-skill"
ABANDONED_DAYS = 90


# -- numbers ----------------------------------------------------------------

def fmt_int(n: int) -> str:
    return f"{n:,}"


def fmt_k(n: int) -> str:
    if n >= 100_000:
        return f"{n / 1000:.0f}k"
    if n >= 10_000:
        return f"{n / 1000:.1f}k".replace(".0k", "k")
    return f"{n:,}"


def delta(cur: float, prev: float | None, unit: str = "pct") -> tuple[str, str]:
    """Arrow text and color for a change from last week."""
    if prev is None:
        return "", MUTED
    if unit == "abs":
        diff = cur - prev
        if diff == 0:
            return "no change", MUTED
        word = "day" if abs(diff) == 1 else "days"
        return (f"▲ {diff:g} {word}" if diff > 0 else f"▼ {abs(diff):g} {word}"), (UP if diff > 0 else DOWN)
    if prev == 0:
        return ("▲ from 0", UP) if cur > 0 else ("no change", MUTED)
    pct = (cur - prev) / prev * 100
    if abs(pct) < 1:
        return "no change", MUTED
    return (f"▲ {pct:.0f}%" if pct > 0 else f"▼ {abs(pct):.0f}%"), (UP if pct > 0 else DOWN)


def ago(days: int) -> str:
    if days < 14:
        return f"{days} days" if days != 1 else "1 day"
    if days < 60:
        return f"{days // 7} wk"
    return f"{days // 30} mo"


def pct_of(part: int, whole: int) -> int:
    return round(part / whole * 100) if whole else 0


# -- model --------------------------------------------------------------------

def totals(work: WeekWork | None) -> dict | None:
    if work is None:
        return None
    rows = work.rows.values()
    days = set()
    for r in rows:
        days.update(r.dates)
    return {
        "commits": sum(r.commits for r in rows),
        "prs_merged": sum(r.prs_merged for r in rows),
        "prs_opened": sum(r.prs_opened for r in rows),
        "additions": sum(r.additions for r in rows),
        "deletions": sum(r.deletions for r in rows),
        "active_days": len(days),
        "agent_commits": sum(r.agent_commits for r in rows),
    }


def build_model(week: Week, works: list[WeekWork | None], cur_doc: dict, pmap: ProjectMap, settings: Settings) -> dict:
    """works = attributed work for [w-3, w-2, w-1, w]; the last one is the report week."""
    cur, prev = works[-1], works[-2]

    open_prs = [p for p in cur_doc.get("open_prs") or [] if not pmap.excluded(p["repo"])]
    open_by_repo = Counter(p["repo"] for p in open_prs)
    week_end = week.end_dt()
    stale, abandoned = [], 0
    for p in open_prs:
        if not p.get("created_at"):
            continue
        age = (week_end - datetime.fromisoformat(p["created_at"].replace("Z", "+00:00"))).days
        if age > ABANDONED_DAYS:
            abandoned += 1  # very old PRs are probably dead, not a loose end
        elif age >= STALE_DAYS:
            stale.append({**p, "age": age})
    stale.sort(key=lambda p: -p["age"])

    projects = []
    for key, r in cur.rows.items():
        if not (r.commits or r.prs_merged or r.prs_opened):
            continue
        trend = [(w.rows[key].commits if w and key in w.rows else 0) for w in works]
        prev_commits = (prev.rows[key].commits if key in prev.rows else 0) if prev else None
        projects.append({
            "key": key,
            "repo": r.repo,
            "name": r.repo.split("/", 1)[1],
            "group": r.group,
            "operating_repo": pmap.is_operating(r.repo),
            "commits": r.commits,
            "prs_merged": r.prs_merged,
            "prs_opened": r.prs_opened,
            "open_now": 0 if pmap.is_operating(r.repo) else open_by_repo.get(r.repo, 0),
            "additions": r.additions,
            "deletions": r.deletions,
            "types": r.types,
            "trend": trend,
            "prev_commits": prev_commits,
        })
    projects.sort(key=lambda p: (-p["commits"], -p["prs_merged"], -(p["additions"] + p["deletions"]), p["name"].lower()))

    # Group and section totals, in map order.
    by_group: dict[str, dict] = {}
    for p in projects:
        g = by_group.setdefault(p["group"].id, {"group": p["group"], "commits": 0, "prs_merged": 0, "types": Counter(), "prev_commits": 0})
        g["commits"] += p["commits"]
        g["prs_merged"] += p["prs_merged"]
        g["types"].update(p["types"])
    if prev:
        for r in prev.rows.values():
            if r.group.id in by_group:
                by_group[r.group.id]["prev_commits"] += r.commits
    sections = []
    order = pmap.sections() + ([UNSORTED.section] if UNSORTED.section not in pmap.sections() else [])
    for name in order:
        members = pmap.groups_in(name) or ([UNSORTED] if name == UNSORTED.section else [])
        groups = [by_group[g.id] for g in members if g.id in by_group]
        if not groups:
            continue
        groups.sort(key=lambda g: -g["commits"])
        sections.append({
            "name": name,
            "single": len(pmap.groups_in(name)) <= 1,
            "commits": sum(g["commits"] for g in groups),
            "prs_merged": sum(g["prs_merged"] for g in groups),
            "groups": groups,
        })

    mix = Counter()
    for p in projects:
        mix.update(p["types"])

    # Focus: businesses (groups) touched on each active day.
    per_day: dict[str, set] = {}
    for c in cur.commits:
        per_day.setdefault(c["date"], set()).add(c["group"].id)
    focus = {
        "avg": round(sum(len(s) for s in per_day.values()) / len(per_day), 1) if per_day else 0,
        "max": max((len(s) for s in per_day.values()), default=0),
    }

    # Top shipped: Claude's picks, or merged features and fixes as a fallback.
    merged = {(p["repo"], p["number"]): p for p in cur.merged}
    ai = cur_doc.get("ai") or {}
    shipped = []
    for pick in ai.get("top_shipped") or []:
        pr = merged.get((pick["repo"], pick["number"]))
        if pr:
            shipped.append({**pr, "label": pick.get("label") or pr["title"]})
    if not shipped:
        shipped = [{**p, "label": p["title"]} for p in cur.merged if p["type"] in ("feature", "fix")][:5]

    active = {p["repo"].lower() for p in projects} | {r.lower() for r in cur.operating["repos"]}
    idle = []
    for item in cur_doc.get("idle") or []:
        repo = item["repo"]
        if pmap.excluded(repo) or pmap.is_operating(repo) or repo.lower() in active:
            continue
        days = (week.end - date.fromisoformat(item["last"][:10])).days
        idle.append({"repo": repo, "name": repo.split("/", 1)[1], "days": days})
    idle.sort(key=lambda i: i["days"])

    new_placements = [
        {"repo": r, "group": pmap.group(gid)} for r, gid in (cur_doc.get("new_placements") or {}).items() if not pmap.excluded(r)
    ]

    t = totals(cur)
    return {
        "week": week,
        "totals": t,
        "prev_totals": totals(prev),
        "operating": cur.operating,
        "operating_share": pct_of(cur.operating["commits"], t["commits"] + cur.operating["commits"]),
        "agent_share": pct_of(t["agent_commits"], t["commits"]),
        "agent_prs": sum(1 for p in cur.merged if p.get("agent")),
        "open_now_total": len(open_prs),
        "stale": stale,
        "abandoned": abandoned,
        "projects": projects,
        "sections": sections,
        "groups": by_group,
        "business_count": len(by_group),
        "mix": mix,
        "focus": focus,
        "shipped": shipped,
        "merged": cur.merged,
        "commits": cur.commits,
        "ai": ai if ai.get("version") == 2 else {},
        "idle": idle,
        "new_placements": new_placements,
        "title": settings.title,
        "map_url": settings.map_url,
    }


# -- HTML -----------------------------------------------------------------------

def _text(size: int, color: str = INK, weight: int = 400, extra: str = "") -> str:
    # font-family is set once on the card and inherited; this keeps the email small.
    return f"font-size:{size}px;line-height:1.45;color:{color};font-weight:{weight};{extra}"


def _label(title: str, note: str = "", size: int = 12) -> str:
    note_html = f'<span style="{_text(12, MUTED)}text-transform:none;letter-spacing:0;">&nbsp;&nbsp;{escape(note)}</span>' if note else ""
    return (
        f'<div style="{_text(size, INK2, 600, "letter-spacing:.06em;text-transform:uppercase;")}">'
        f"{escape(title)}{note_html}</div>"
    )


def _table(inner: str) -> str:
    return f'<table role="presentation" width="100%" cellpadding="0" cellspacing="0">{inner}</table>'


def _summary(m: dict) -> str:
    ai = m["ai"]
    if not ai.get("headline"):
        return ""

    def items(title: str, values: list[str]) -> str:
        if not values:
            return ""
        rows = "".join(
            f'<tr><td width="14" valign="top" style="{_text(14, ACCENT, 700)}padding:2px 0;">•</td>'
            f'<td style="{_text(14, INK, 400, "line-height:1.5;")}padding:2px 0;">{escape(v)}</td></tr>'
            for v in values
        )
        return (
            f'<div style="{_text(11, MUTED, 700, "letter-spacing:.06em;text-transform:uppercase;margin-top:12px;")}">{title}</div>'
            + _table(rows)
        )

    return (
        f'<div style="border-left:3px solid {ACCENT};padding:2px 0 2px 14px;">'
        f'<div style="{_text(17, INK, 700, "line-height:1.35;")}">{escape(ai["headline"])}</div>'
        + items("What moved", ai.get("moved", []))
        + items("How you worked", ai.get("how", []))
        + items("Next week", ai.get("next", []))
        + "</div>"
    )


def _tile(label: str, value_html: str, delta_txt: str, delta_color: str, context: str) -> str:
    delta_html = (
        f'<span style="color:{delta_color};font-weight:600">{escape(delta_txt)}</span>'
        f'<span style="color:{MUTED}"> vs last week</span>' if delta_txt else f'<span style="color:{MUTED}">first week</span>'
    )
    return (
        f'<div style="background:{TILE};border-radius:10px;padding:14px 16px;">'
        f'<div style="{_text(12, INK2, 600, "letter-spacing:.05em;text-transform:uppercase;")}">{escape(label)}</div>'
        f'<div style="{_text(30, INK, 700, "line-height:1.15;margin-top:4px;font-variant-numeric:tabular-nums;")}">{value_html}</div>'
        f'<div style="{_text(13, INK2, 400, "margin-top:4px;")}">{delta_html}</div>'
        f'<div style="{_text(12, MUTED, 400, "margin-top:2px;")}">{escape(context)}</div>'
        f"</div>"
    )


def _kpis(m: dict) -> str:
    t, p = m["totals"], m["prev_totals"]
    pv = (lambda k: p[k] if p else None)
    lines_now = t["additions"] + t["deletions"]
    lines_prev = (p["additions"] + p["deletions"]) if p else None
    tiles = [
        _tile("Commits", fmt_int(t["commits"]), *delta(t["commits"], pv("commits")),
              f"in {len(m['projects'])} projects"),
        _tile("PRs merged", fmt_int(t["prs_merged"]), *delta(t["prs_merged"], pv("prs_merged")),
              f"{t['prs_opened']} opened · {m['open_now_total']} open now"
              + (f" · {m['agent_prs']} by your agents" if m["agent_prs"] else "")),
        _tile("Lines changed", fmt_k(lines_now), *delta(lines_now, lines_prev),
              f"+{fmt_k(t['additions'])} added · −{fmt_k(t['deletions'])} removed"),
        _tile("Active days", f'{t["active_days"]}<span style="font-size:16px;color:{MUTED};font-weight:600"> / 7</span>',
              *delta(t["active_days"], pv("active_days"), "abs"),
              f"{m['focus']['avg']:g} businesses per day on average"),
    ]
    cell = lambda html: f'<td width="50%" valign="top" style="padding:6px;">{html}</td>'  # noqa: E731
    grid = _table(f"<tr>{cell(tiles[0])}{cell(tiles[1])}</tr><tr>{cell(tiles[2])}{cell(tiles[3])}</tr>")
    op = m["operating"]
    if op["commits"]:
        repos = ", ".join(r.split("/", 1)[1] for r, _ in op["repos"].most_common(3))
        grid += (
            f'<div style="{_text(12, MUTED, 400, "padding:6px 6px 0;")}">'
            f'Not counted above: <b style="color:{INK2}">{op["commits"]} operating commits</b> '
            f'({m["operating_share"]}% of all commits) in {escape(repos)}: notes, research, plans and run records.</div>'
        )
    return grid


def _mix(m: dict) -> str:
    total = sum(m["mix"][t] for t in VELOCITY_TYPES)
    if not total:
        return ""
    present = [t for t in VELOCITY_TYPES if m["mix"][t]]
    cells = []
    for i, t in enumerate(present):
        pct = max(1, round(m["mix"][t] / total * 100))
        radius = ("border-radius:4px 0 0 4px;" if i == 0 else "") + ("border-radius:0 4px 4px 0;" if i == len(present) - 1 else "")
        if len(present) == 1:
            radius = "border-radius:4px;"
        gap = f"border-right:2px solid {CARD};" if i < len(present) - 1 else ""
        cells.append(
            f'<td width="{pct}%" title="{escape(TYPE_NAMES[t])}: {m["mix"][t]} commits" '
            f'style="background:{TYPE_COLORS[t]};height:14px;{radius}{gap}font-size:0;line-height:0;">&nbsp;</td>'
        )
    legend = " ".join(
        f'<span style="white-space:nowrap;margin-right:12px;">'
        f'<span style="display:inline-block;width:10px;height:10px;border-radius:2px;background:{TYPE_COLORS[t]};vertical-align:-1px;"></span> '
        f'{escape(TYPE_NAMES[t])} <b style="color:{INK}">{m["mix"][t]}</b> '
        f'<span style="color:{FAINT}">{pct_of(m["mix"][t], total)}%</span></span>'
        for t in present
    )
    return (
        _table("<tr>" + "".join(cells) + "</tr>")
        + f'<div style="{_text(12, INK2, 400, "margin-top:8px;line-height:1.8;")}">{legend}</div>'
    )


def _bar_row(label: str, commits: int, prs: int, scale: int, indent: bool, title: str) -> str:
    pct = 0 if scale == 0 else max(2, round(commits / scale * 100))
    bar = _table(
        "<tr>"
        f'<td width="{pct}%" style="background:{ACCENT};height:12px;border-radius:0 4px 4px 0;font-size:0;line-height:0;">&nbsp;</td>'
        + ('<td style="font-size:0;line-height:0;">&nbsp;</td>' if pct < 100 else "")
        + "</tr>"
    )
    pad = "padding:5px 8px 5px 16px;" if indent else "padding:5px 8px 5px 0;"
    prs_html = f'<span style="color:{MUTED};font-weight:400"> · {prs} PR{"s" if prs != 1 else ""}</span>' if prs else ""
    return (
        f'<tr title="{escape(title)}">'
        f'<td width="38%" style="{pad}{_text(13, INK2 if indent else INK, 400)}">{escape(label)}</td>'
        f'<td style="padding:5px 0;">{bar}</td>'
        f'<td width="92" align="right" style="padding:5px 0 5px 8px;white-space:nowrap;{_text(13, INK, 600, "font-variant-numeric:tabular-nums;")}">{commits}{prs_html}</td>'
        "</tr>"
    )


def _business(m: dict) -> str:
    scale = max((g["commits"] for s in m["sections"] for g in s["groups"]), default=0)
    rows = []
    for s in m["sections"]:
        if s["single"]:
            g = s["groups"][0]
            label = s["name"] if g["group"].name == s["name"] else g["group"].name
            rows.append(_bar_row(label, g["commits"], g["prs_merged"], scale, False,
                                 f"{label}: {g['commits']} commits, {g['prs_merged']} PRs merged"))
            continue
        rows.append(
            f'<tr><td colspan="2" style="padding:8px 8px 3px 0;{_text(13, INK, 700)}">{escape(s["name"])}</td>'
            f'<td align="right" style="padding:8px 0 3px 8px;white-space:nowrap;{_text(13, INK, 700, "font-variant-numeric:tabular-nums;")}">'
            f'{s["commits"]}<span style="color:{MUTED};font-weight:400"> · {s["prs_merged"]} PRs</span></td></tr>'
        )
        for g in s["groups"]:
            rows.append(_bar_row(g["group"].name, g["commits"], g["prs_merged"], scale, True,
                                 f"{g['group'].name}: {g['commits']} commits, {g['prs_merged']} PRs merged"))
    return _table("".join(rows))


def _spark(values: list[int]) -> str:
    top = max(values) or 1
    out = []
    for v in values:
        idx = 0 if v == 0 else max(1, round(v / top * 7))
        out.append(f'<span style="color:{ACCENT if v else EMPTY}">{SPARK[idx]}</span>')
    return "".join(out)


def _projects(m: dict, settings: Settings) -> str:
    def th(label: str, align: str = "right", pad: str = "padding:0 0 6px 8px;") -> str:
        return f'<td align="{align}" style="{pad}{_text(11, MUTED, 600, "letter-spacing:.05em;text-transform:uppercase;white-space:nowrap;")}">{label}</td>'

    head = "<tr>" + th("Project", "left", "padding:0 0 6px 0;") + th("Commits") + th("PRs") + th("Lines") + th("4 wks") + "</tr>"
    rows = []
    for p in m["projects"][: settings.top_projects]:
        d_txt, d_col = delta(p["commits"], p["prev_commits"])
        lines = (
            f'+{fmt_k(p["additions"])}<br><span style="color:{MUTED}">−{fmt_k(p["deletions"])}</span>'
            if p["additions"] or p["deletions"] else f'<span style="color:{MUTED}">–</span>'
        )
        prs = f'{p["prs_merged"]}' + (f'<br><span style="{_text(11, MUTED)}">{p["open_now"]} open</span>' if p["open_now"] else "")
        sub = f'for {p["group"].name}' if p["operating_repo"] else p["group"].name
        name = p["name"]
        cell = f"border-top:1px solid {RULE};padding:8px 0 8px 8px;vertical-align:top;"
        rows.append(
            "<tr>"
            f'<td style="border-top:1px solid {RULE};padding:8px 0;vertical-align:top;">'
            f'<a href="https://github.com/{escape(p["repo"])}" style="{_text(14, INK, 600, "text-decoration:none;")}">{escape(name)}</a>'
            f'<br><span style="{_text(12, MUTED)}">{escape(sub)}</span></td>'
            f'<td align="right" style="{cell}{_text(14, INK, 600, "font-variant-numeric:tabular-nums;white-space:nowrap;")}">{p["commits"]}'
            + (f'<br><span style="{_text(11, d_col, 600)}">{escape(d_txt)}</span>' if d_txt else "")
            + "</td>"
            f'<td align="right" style="{cell}{_text(14, INK, 600, "font-variant-numeric:tabular-nums;")}">{prs}</td>'
            f'<td align="right" style="{cell}{_text(12, INK2, 400, "font-variant-numeric:tabular-nums;white-space:nowrap;")}">{lines}</td>'
            f'<td align="right" style="{cell}{_text(15, ACCENT, 400, "letter-spacing:1px;white-space:nowrap;line-height:1.2;")}">{_spark(p["trend"])}</td>'
            "</tr>"
        )
    rest = m["projects"][settings.top_projects:]
    if rest:
        names = ", ".join(
            f'{escape(p["name"])}{" for " + escape(p["group"].name) if p["operating_repo"] else ""} ({p["commits"]})'
            for p in rest
        )
        rows.append(
            f'<tr><td colspan="5" style="border-top:1px solid {RULE};padding:8px 0 0;{_text(12, MUTED)}">'
            f"+{len(rest)} more: {names}</td></tr>"
        )
    return _table(head + "".join(rows))


def _shipped(m: dict) -> str:
    rows = []
    for i, s in enumerate(m["shipped"], 1):
        rows.append(
            "<tr>"
            f'<td width="22" valign="top" style="border-top:1px solid {RULE};padding:8px 0;{_text(13, MUTED, 600)}">{i}</td>'
            f'<td style="border-top:1px solid {RULE};padding:8px 0;">'
            f'<a href="{escape(s["url"])}" style="{_text(14, INK, 600, "text-decoration:none;")}">{escape(s["label"])}</a>'
            f'<br><span style="{_text(12, MUTED)}">{escape(s["group"].name)} · {escape(s["repo"].split("/", 1)[1])} #{s["number"]}</span>'
            "</td></tr>"
        )
    return _table("".join(rows))


def _block(inner: str, pad: str = "20px 28px 4px") -> str:
    return f'<tr><td style="padding:{pad};">{inner}</td></tr>'


def render_html(m: dict, settings: Settings) -> str:
    t = m["totals"]
    week: Week = m["week"]
    preheader = m["ai"].get("headline") or f"{t['commits']} commits and {t['prs_merged']} PRs merged."
    parts = [_block(
        f'<div style="{_text(12, ACCENT, 700, "letter-spacing:.08em;text-transform:uppercase;")}">{escape(m["title"])}</div>'
        f'<div style="{_text(26, INK, 700, "line-height:1.25;margin-top:4px;")}">{escape(week.label())}</div>'
        f'<div style="{_text(14, INK2, 400, "margin-top:4px;")}">{len(m["projects"])} active projects in {m["business_count"]} groups</div>',
        "28px 28px 4px",
    )]
    summary = _summary(m)
    if summary:
        parts.append(_block(summary, "18px 28px 4px"))
    parts.append(_block(_kpis(m), "14px 22px 4px"))
    mix = _mix(m)
    if mix:
        parts.append(_block(_label("Work mix", "commits by type") + '<div style="height:10px"></div>' + mix))
    if m["sections"]:
        parts.append(_block(_label("Commits by business") + '<div style="height:8px"></div>' + _business(m)))
    if m["projects"]:
        parts.append(_block(_label("Projects", "sorted by commits") + '<div style="height:10px"></div>' + _projects(m, settings)))
    if m["shipped"]:
        parts.append(_block(_label("Top shipped") + '<div style="height:6px"></div>' + _shipped(m)))
    if m["new_placements"]:
        items = " · ".join(f'{escape(n["repo"].split("/", 1)[1])} → <b>{escape(n["group"].name)}</b>' for n in m["new_placements"])
        parts.append(_block(
            f'<div style="background:#eaf2fc;border-radius:10px;padding:12px 14px;{_text(13, INK)}">'
            f'<b>New this week.</b> Claude put these new repositories in a group: {items}. '
            + (f'<a href="{escape(m["map_url"])}" style="color:{ACCENT};font-weight:600;">Fix the map</a>' if m["map_url"] else "Fix it in config/map.toml.")
            + '</div>'
        ))
    if m["idle"]:
        items = " · ".join(
            f'<span style="white-space:nowrap">{escape(i["name"])} <span style="color:{FAINT}">{ago(i["days"])}</span></span>'
            for i in m["idle"]
        )
        parts.append(_block(
            f'<div style="{_text(11, MUTED, 600, "letter-spacing:.05em;text-transform:uppercase;")}">Idle this week</div>'
            f'<div style="{_text(12, MUTED, 400, "margin-top:4px;line-height:1.6;")}">{items}</div>',
            "22px 28px 4px",
        ))
    parts.append(_block(
        f'<div style="border-top:1px solid {RULE};padding-top:14px;{_text(11, MUTED, 400, "line-height:1.55;")}">'
        "Commits are commits by you and your agents on default branches. Merge commits do not count. "
        "Operating work (notes, research, plans, run records and agent context) does not count. "
        "Work in an operating repository that serves a business counts for that business. Claude labels each commit and PR. "
        "Lines do not include lock files, generated files or data files (JSON, CSV, SVG, text). "
        f"The week is {WEEKDAYS[settings.send_weekday].title()} to {WEEKDAYS[settings.send_weekday - 1].title()}, "
        f"time zone {escape(str(settings.tz))}.<br>"
        + (f'<a href="{escape(m["map_url"])}" style="color:{MUTED};">Project map</a> · ' if m["map_url"] else "")
        + f'<a href="{PROJECT_URL}" style="color:{MUTED};">Made with weekly-review</a></div>',
        "22px 28px 26px",
    ))
    return (
        "<!doctype html><html><head><meta charset=\"utf-8\">"
        '<meta name="viewport" content="width=device-width,initial-scale=1">'
        '<meta name="color-scheme" content="light"><meta name="supported-color-schemes" content="light">'
        f"<title>{escape(m['title'])} {escape(week.label())}</title></head>"
        f'<body style="margin:0;padding:0;background:{PAGE};">'
        f'<div style="display:none;max-height:0;overflow:hidden;opacity:0;">{escape(preheader)}</div>'
        f'<table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="background:{PAGE};">'
        f'<tr><td align="center" style="padding:20px 10px;font-family:{FONT};">'
        f'<table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="max-width:640px;background:{CARD};border:1px solid {RULE};border-radius:14px;font-family:{FONT};">'
        + "".join(parts)
        + "</table></td></tr></table></body></html>"
    )


def render_text(m: dict) -> str:
    t, week, ai = m["totals"], m["week"], m["ai"]
    lines = [f"{m['title']}: {week.label()}", ""]
    if ai.get("headline"):
        lines.append(ai["headline"])
        for title, key in (("What moved", "moved"), ("How you worked", "how"), ("Next week", "next")):
            if ai.get(key):
                lines += ["", title + ":"] + [f"  - {v}" for v in ai[key]]
        lines.append("")
    lines += [
        f"Commits: {t['commits']}   PRs merged: {t['prs_merged']}   "
        f"Lines: +{t['additions']:,} / -{t['deletions']:,}   Active days: {t['active_days']}/7",
        f"Operating commits not counted: {m['operating']['commits']}",
        "",
        "Projects:",
    ]
    for p in m["projects"]:
        lines.append(f"  {p['name']} ({p['group'].name}): {p['commits']} commits, {p['prs_merged']} PRs merged")
    if m["shipped"]:
        lines += ["", "Top shipped:"] + [f"  {i}. {s['label']} ({s['url']})" for i, s in enumerate(m["shipped"], 1)]
    return "\n".join(lines) + "\n"


def subject(m: dict) -> str:
    t = m["totals"]
    return f"{m['title']} · {m['week'].short_label()} · {t['commits']} commits · {t['prs_merged']} PRs merged"
