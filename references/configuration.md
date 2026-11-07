# Configuration reference

Both files live in `<home>/config/`. `python weekly_review.py init` writes commented templates.

## settings.toml

### [report]

| Key | Default | Meaning |
|---|---|---|
| `to` | (required) | The email address that gets the report |
| `title` | `"Weekly review"` | Shown at the top and in the subject |
| `timezone` | `"UTC"` | IANA name, for example `"Europe/Berlin"`, `"America/New_York"` |
| `send_day` | `"monday"` | The report covers the 7 days before this day (00:00 local time) |
| `send_hour` | `7` | Local hour; `scheduled` sends at its first run after this hour |
| `top_projects` | `8` | Rows in the project table; the rest go on one "+N more" line |
| `idle_days` | `182` | Idle projects with no commits for longer leave the idle list |
| `map_url` | `""` | Optional link to edit your map (shown as "Fix the map") |

### [summary]

| Key | Default | Meaning |
|---|---|---|
| `enabled` | `true` | `false` turns off all Claude calls: no labels (subject-based guesses), no summary |
| `model` | `"sonnet"` | Any model name the `claude` CLI accepts |
| `style` | `"plain"` | `"plain"` or `"ste"` (ASD-STE100 Simplified Technical English) |
| `reader` | `""` | Optional name of the reader |

### [identity]

| Key | Meaning |
|---|---|
| `login` | Your GitHub login |
| `commit_queries` | GitHub commit-search qualifiers for your work: `author:<login>`, `author-email:<email>` |
| `pr_queries` | PR-search qualifiers: `author:<login>`, `author:app/<app-slug>` for a GitHub App |

Any identity other than `author:<login>` counts as an agent; the email shows the agent share.

### [plans] (optional)

| Key | Meaning |
|---|---|
| `local_path` | A local folder that holds your plan folders |
| `daily_dir` | Folder (relative) with dated priorities files `YYYY-MM-DD-*.md`; the newest file on or before the week's end is used |
| `plans_dir` | Folder with dated plan files; names dated inside the week are listed |
| `repo` | Optional `owner/repo` fallback that holds the same folders |
| `max_chars` | How much of the priorities file goes to Claude (default 8000) |

### [mail]

See `mail.md`. `method` is `"smtp"`, `"command"` or `"none"`.

### [schedule]

| Key | Default | Meaning |
|---|---|---|
| `git_sync` | `false` | Pull before and push after each scheduled send (the data folder is a private git repository) |
| `on_failure_command` | `""` | Run on a failed scheduled run; `WR_MESSAGE` holds the error |

## map.toml

```toml
operating = ["you/notes"]                 # notes, plans and agent context: not velocity
operating_hints = ["docs/proposals/<client>/ -> that client's group"]
exclude = ["you/sandbox"]                  # never shown

[[group]]
id = "acme"                                # stable id; labels and placements refer to it
name = "Acme Corp"                         # shown in the email
section = "My company"                     # groups with the same section are shown together, with a total
kind = "client"                            # optional: firm, client, product
about = "Client: online shop"              # helps Claude place new repositories and label work
repos = ["acme-org/shop", "you/acme-scripts"]

[[rule]]
owner = "acme-org"                         # every repository of this owner
group = "acme"

[[rule]]
prefixes = ["acme-"]                       # repository names that start with this
group = "acme"
```

Resolution order: `exclude`, then group `repos`, then rules (first match), then `placements.json`.
A repository that matches nothing is placed by Claude the first time it shows up, and the email tells you.
