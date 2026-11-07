# Scheduling

Run `python weekly_review.py scheduled` every hour with any scheduler. It does nothing unless a report is due:
after `send_hour` on `send_day` (local time in `settings.toml`), and only if that week was not sent yet. So a
computer that is asleep or off at the send hour sends at its next run, and an extra run never sends twice.

In the examples, replace the paths. Use the full path to Python and to `weekly_review.py`, and set
`WEEKLY_REVIEW_HOME` if your data folder is not `~/.weekly-review`. Schedulers start jobs with a small PATH, so
make sure `gh` and `claude` can be found (set PATH in the job, as shown). If you use `password_env`, the job
must also get that variable.

## macOS: launchd

Save as `~/Library/LaunchAgents/com.example.weekly-review.plist`, then load it with
`launchctl bootstrap gui/$(id -u) ~/Library/LaunchAgents/com.example.weekly-review.plist`.

```xml
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key><string>com.example.weekly-review</string>
  <key>ProgramArguments</key>
  <array>
    <string>/usr/bin/env</string>
    <string>python3</string>
    <string>/Users/you/.claude/skills/weekly-review/weekly_review.py</string>
    <string>scheduled</string>
  </array>
  <key>EnvironmentVariables</key>
  <dict><key>PATH</key><string>/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin</string></dict>
  <key>StartInterval</key><integer>3600</integer>
  <key>RunAtLoad</key><true/>
  <key>StandardOutPath</key><string>/Users/you/Library/Logs/weekly-review.log</string>
  <key>StandardErrorPath</key><string>/Users/you/Library/Logs/weekly-review.log</string>
</dict>
</plist>
```

Stop it with `launchctl bootout gui/$(id -u)/com.example.weekly-review`.

## Linux: systemd user timer

`~/.config/systemd/user/weekly-review.service`:

```ini
[Unit]
Description=Weekly review email

[Service]
Type=oneshot
Environment=PATH=%h/.local/bin:/usr/local/bin:/usr/bin:/bin
ExecStart=/usr/bin/python3 %h/.claude/skills/weekly-review/weekly_review.py scheduled
```

`~/.config/systemd/user/weekly-review.timer`:

```ini
[Unit]
Description=Check hourly whether the weekly review is due

[Timer]
OnCalendar=hourly
Persistent=true

[Install]
WantedBy=timers.target
```

Then: `systemctl --user daemon-reload && systemctl --user enable --now weekly-review.timer`.
For the job to run while you are logged out: `loginctl enable-linger $USER`.

## Linux or macOS: cron

`crontab -e`, then add:

```cron
5 * * * * PATH=/usr/local/bin:/usr/bin:/bin /usr/bin/python3 $HOME/.claude/skills/weekly-review/weekly_review.py scheduled >> $HOME/weekly-review.log 2>&1
```

## Windows: Task Scheduler

In PowerShell (adjust the paths; `py` is the Python launcher):

```powershell
$action  = New-ScheduledTaskAction -Execute "py" -Argument "$env:USERPROFILE\.claude\skills\weekly-review\weekly_review.py scheduled"
$trigger = New-ScheduledTaskTrigger -Once -At (Get-Date) -RepetitionInterval (New-TimeSpan -Hours 1)
$settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -WakeToRun:$false
Register-ScheduledTask -TaskName "Weekly review" -Action $action -Trigger $trigger -Settings $settings
```

`-StartWhenAvailable` runs a missed run when the computer is on again. Install the time zone data once:
`py -m pip install tzdata`.

## An always-on machine or a server

Any of the above works on a home server or a VPS. That machine needs `gh` signed in with read
access to all your repositories, the `claude` CLI signed in, and the mail password. Think about who else can
use that machine: the data folder holds private commit subjects and PR titles.

## CI (advanced)

A scheduled CI job (for example GitHub Actions with a cron trigger) can run `send` once a week. It then needs
secrets: a GitHub token that can read all your repositories, Claude Code credentials for the `claude` CLI, and
the mail password. Keep the data folder in a private repository so history persists between runs.
