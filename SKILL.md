---
name: weekly-review
description: Set up, run and tune a weekly email report of someone's GitHub work by business and project - commits, PRs merged, lines changed, active days, 4-week trends, a work-mix chart (features, fixes, content, automation), an "operating base" for notes repositories, agent and bot identities, and a Claude-written review of how the week went with a plan-versus-actual check. Use this skill whenever the user wants a weekly or periodic productivity review, an engineering digest, a "what did I ship this week" report, commit or PR metrics across repositories, clients or products, a dashboard of their GitHub output by project, or wants to change, debug or reschedule an existing weekly review, even if they do not say "weekly review".
---

# Weekly review

This skill sets up and runs a weekly HTML email that shows a person's GitHub work grouped by business and
project. The code in this folder does the work, so every user gets the same layout, charts and metrics.
Your job is to configure it with the user, check that it works on their machine, and schedule it.

See `docs/screenshot-desktop.png` for what the email looks like (it is made from fictional demo data).

## How the pieces fit

- **Code:** this skill folder. Entry point: `python weekly_review.py` (use `python3` or `py` where that is the
  name of Python 3.11+). Run it from any folder by giving the full path to `weekly_review.py`.
- **Data folder ("home"):** the user's own config, history and labels. Default `~/.weekly-review`, or set
  `WEEKLY_REVIEW_HOME`, or pass `--home DIR` before the command. Keep it outside this skill folder so that an
  update of the skill never touches the user's data.
  - `config/settings.toml` - who gets the email, time zone, identities, mail, plans, schedule options
  - `config/map.toml` - groups (businesses, clients, products), rules, exclusions, operating repositories
  - `history/` - one JSON file per week plus `labels.json` (Claude's work labels). Keep it; trends need it.
  - `cache/` and `out/` - can be rebuilt; `out/<week>.html` is the rendered email
- **Commands:** `init`, `demo`, `check`, `build`, `send`, `scheduled`. `--help` shows the options.

The report reads GitHub through the `gh` CLI (the user's own login) and asks Claude through the local
`claude` CLI (the user's own Claude Code plan). No other service gets the data, except the mail server.

## Set it up with the user

Work through these steps in order. Look up facts yourself instead of asking the user for them; ask the user
only for decisions. Show your proposals (for example the group map) and let the user correct them.

1. **Check the requirements.** Python 3.11 or later; `gh auth status` shows a login; `claude --version` works.
   On Windows, `pip install tzdata` is needed for time zones. If something is missing, say what and how to
   install it for their operating system; do not install system software without asking.
2. **Show the demo first** so the user sees what they will get:
   `python weekly_review.py --home <temp folder> demo`, then open the HTML file it names.
3. **Create the data folder:** `python weekly_review.py init` (add `--home` if they want another place).
4. **Identities.** Get the login with `gh api user --jq .login`. Then look for the user's agents: PR authors
   other than the user in their own repositories (`gh search prs --owner <login> --json author`), and commit
   emails on default branches that are not theirs. Agents that act for the user (a coding bot, a GitHub App,
   a CI identity) count as the user's work. Confirm each one with the user before you add it, because a shared
   bot can also act for teammates. Write them to `[identity]` in `settings.toml`.
5. **Group map.** List repositories with recent activity (`gh repo list <owner> --limit 200 --json
   nameWithOwner,description,pushedAt` for the user and each org from `gh api user/orgs`). Propose groups from
   the names and descriptions: usually a company section with its website, clients and products, then side
   projects and personal tools. Ask the user to confirm or correct it, and which repositories to exclude
   (sandboxes, forks of other projects, abandoned experiments). Add `[[rule]]` entries (owner or name prefix)
   so new repositories land in the right group without upkeep.
6. **Operating repositories.** Ask whether they keep a repository for notes, plans or agent context. Its work
   should not count as velocity; list it under `operating`, and write `operating_hints` that tell Claude which
   paths or commit scopes serve which group (for example client proposals).
7. **Plans (optional).** Ask whether they keep dated priorities files (`YYYY-MM-DD-*.md`). If yes, set
   `[plans]` so the summary can compare plan and result.
8. **Writing style.** `plain` by default; `ste` (ASD-STE100 Simplified Technical English) if they want it.
9. **Mail.** Read `references/mail.md` and set `[mail]` with the user. Never write a password into a file or
   a command line; use an environment variable, the OS keychain or a password manager command. When the user
   must type a secret, give them the command to run themselves.
10. **Check and preview.** `python weekly_review.py check` (sends nothing), then
    `python weekly_review.py build`. The first build reads 4 weeks of history and asks Claude to label the
    work once; that can take a few minutes. Show the user `out/<week>.html` and adjust the map or hints.
11. **Test email.** `python weekly_review.py send` sends the current week's report. Ask first; it emails.
12. **Schedule.** Read `references/scheduling.md` and set up the user's own scheduler (launchd, cron, systemd,
    Task Scheduler or another). It runs `scheduled` every hour; the command sends only once per week, after the
    send hour, so a laptop that was asleep still sends when it wakes.

## Run and maintain

- `build --week YYYY-MM-DD` renders any past week (the date is the first day of the week).
- `build --refresh` collects the week again; `--refresh-ai` asks Claude for a new summary.
- A wrong group: add the repository to the right `[[group]]` in `map.toml`. Claude's guesses for new
  repositories are in `config/placements.json` and show in the email under "New this week".
- A wrong work label: labels are cached in `history/labels.json` by commit SHA (first 12 characters) or
  `owner/repo#number`. Delete an entry, or the whole file, to label again on the next build. Better hints in
  `operating_hints` fix most attribution problems.
- A failed scheduled run is logged and retried on the next run. `schedule.on_failure_command` can alert the user.

Read `references/how-it-works.md` when the user asks what a number means or why a count looks wrong.

## Keep the user's data private

The history files contain commit subjects and PR titles from private repositories. If the user wants their
data folder in git, it must be a private repository (`schedule.git_sync = true` pulls and pushes it). Never add
the data folder, tokens or passwords to this skill folder or to a public repository.

## Reference files

- `references/configuration.md` - every setting in `settings.toml` and `map.toml`
- `references/mail.md` - SMTP providers, password sources per operating system, custom send commands
- `references/scheduling.md` - macOS, Linux, Windows and other schedulers
- `references/how-it-works.md` - metrics, work types, attribution, filters and limits
