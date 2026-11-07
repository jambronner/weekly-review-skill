# How it works

## Data sources

- **Commits:** GitHub commit search for each `commit_queries` identity, by committer date inside the week.
  Commit search covers default branches only, so work counts when it lands on the main branch. Merge commits
  and commits in forks do not count. Each commit is counted once, even if several identities find it.
- **Lines:** per-commit file stats from the GitHub API. Lock files, generated output (dist, build, `.next`,
  migration snapshots and similar), minified files, source maps and data files (JSON, CSV, SVG, text, XML) do
  not count, because they inflate the numbers without being written work. The filters are in `wr/collect.py`.
- **PRs:** issue search for each `pr_queries` identity: opened in the week, merged in the week, and open now.
- **Idle projects:** your latest commit in each known repository within `idle_days`.
- **Plans:** the newest dated priorities file (optional).

Commit file stats are cached in `cache/` (commits never change). Each week is saved in `history/` with one
record per commit and PR, so map changes and new labels apply to old weeks too.

## Work types

Claude labels each commit and PR once (cached in `history/labels.json`):

| Type | Meaning | Velocity |
|---|---|---|
| Feature | a new capability that users, clients or you can use | yes |
| Fix | a bug fix or security fix | yes |
| Content & deliverables | articles, site copy, proposals, client deliverables | yes |
| Automation & tooling | scripts, pipelines, infrastructure, tests, refactors | yes |
| Operating | notes, research capture, plans, run records, agent context | no |

Without Claude (or when a label is missing), a guess from conventional-commit prefixes (`feat:`, `fix:`,
`docs:`, `chore:` ...) and the first word of the subject is used.

## Attribution

- A commit in a normal repository counts for that repository's group.
- A commit in an `operating` repository counts for the group it serves (Claude decides, guided by
  `operating_hints`), or for nobody (operating work).
- Operating work in any repository is left out of the main numbers and shown on one line under them.

## The numbers in the email

| Number | Meaning |
|---|---|
| Commits | Velocity commits in the week, with the change from last week |
| PRs merged | PRs by your identities merged in the week; also opened, open now, and merged agent PRs |
| Lines changed | Added plus removed lines, after the filters |
| Active days | Days with one or more velocity commits; also businesses (groups) per active day |
| Work mix | Velocity commits by type |
| Commits by business | Per group, grouped by section, with merged PRs |
| Projects | One row per repository and group, with lines, open PRs and a 4-week trend |
| Top shipped | Five merged PRs that Claude picks as most important |
| Idle | Known projects with no work this week, with the time since your last commit |

The opening review gets only this data (plus the plan text) and is told to use only numbers from it.

## Limits

- GitHub search returns at most 1,000 results per query and allows 30 search requests per minute; the code
  waits between requests. A first build reads 4 weeks and can take a few minutes.
- Work on branches that never land on the default branch does not count. Squash merges count once.
- Commits by an identity that GitHub cannot match (an email with no account) need an `author-email:` query.
- The `claude` calls use your own Claude Code plan: one labeling pass for new items and one summary per week.
