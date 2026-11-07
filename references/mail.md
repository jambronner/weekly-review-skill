# Mail

Set `[mail] method` in `settings.toml`:

- `"none"` - no email; the report is written to `<home>/out/<week>.html`. Good for a first run.
- `"smtp"` - any SMTP server. Recommended for most people.
- `"command"` - your own command sends it (a provider CLI, `msmtp`, a script, an API call).

Run `python weekly_review.py check` after a change. It logs in to the SMTP server but sends nothing.

## SMTP settings by provider

| Provider | `smtp_host` | `smtp_port` / `smtp_security` | Password |
|---|---|---|---|
| Gmail / Google Workspace | `smtp.gmail.com` | `465` / `ssl` | An app password (needs 2-Step Verification); set `strip_spaces = true` |
| Outlook.com | `smtp-mail.outlook.com` | `587` / `starttls` | Your password or an app password; some accounts need SMTP AUTH turned on |
| Microsoft 365 | `smtp.office365.com` | `587` / `starttls` | Your admin must allow SMTP AUTH for the mailbox |
| iCloud Mail | `smtp.mail.me.com` | `587` / `starttls` | An app-specific password |
| Fastmail | `smtp.fastmail.com` | `465` / `ssl` | An app password |
| Amazon SES | `email-smtp.<region>.amazonaws.com` | `465` / `ssl` | SMTP credentials from the SES console |

Providers change their rules; check their current help page if the login fails.

## Where the password comes from

The code never stores the password. It looks in this order:

1. `password_command` - a command that prints the password. Examples:
   - macOS Keychain: `security find-generic-password -s weekly-review -a you@example.com -w`
     (store it once with `security add-generic-password -s weekly-review -a you@example.com -w`; it asks for the password)
   - Linux Secret Service: `secret-tool lookup service weekly-review user you@example.com`
     (store it once with `secret-tool store --label="Weekly review" service weekly-review user you@example.com`)
   - Windows PowerShell SecretManagement: `pwsh -NoProfile -Command "Get-Secret weekly-review -AsPlainText"`
   - 1Password CLI: `op read "op://Private/SMTP/password"`
   - Bitwarden CLI: `bw get password weekly-review`
   - `pass`: `pass show email/weekly-review`
2. The environment variable named in `password_env` (default `WEEKLY_REVIEW_SMTP_PASSWORD`). Make sure your
   scheduler passes it to the job.
3. The optional Python `keyring` package (`pip install keyring`), service `weekly-review` (or `keyring_service`)
   and user `username`. It uses the macOS Keychain, Windows Credential Manager or Linux Secret Service.

Type secrets into these tools yourself. Do not paste a password into a chat, a config file or a shell history.

## Custom command

`method = "command"` runs `command` through the shell with these environment variables:

| Variable | Value |
|---|---|
| `WR_TO` | The `to` address |
| `WR_SUBJECT` | The subject line |
| `WR_HTML_FILE` | Path to the HTML email (a temporary file) |
| `WR_TEXT_FILE` | Path to the plain-text version |

Example with `msmtp` and a small script of your own that builds a MIME message from these files, or with your
mail provider's CLI. A non-zero exit code counts as a failure, and the scheduled job tries again later.
