# Claude Usage Widget

A tiny always-on-top desktop widget that shows your live **Claude Code** usage —
the 5-hour session window, the weekly (all-models) window, and per-model weekly
windows when your plan exposes them.

It reads the OAuth token Claude Code already stores on your machine
(`~/.claude/.credentials.json`) and polls Anthropic's usage endpoint every
60 seconds. **Your token is never stored, logged, or sent anywhere except
`api.anthropic.com`.**

![widget](docs/screenshot.png)

## Features

- **Live usage bars** for session (5h), weekly all-models, and weekly Opus/Sonnet.
- **Always on top**, frameless, semi-transparent.
- **Move** — drag the title bar.
- **Resize** — drag the `◢` grip in the bottom-right corner.
- **Minimise** to the taskbar with the `–` button.
- **Right-click menu** — Refresh now, Minimise, toggle Always-on-top, Quit.
- Color-coded thresholds (orange → amber at 75% → red at 90%).
- Reports overage / extra-usage spend when enabled on your account.

## Run from source

```powershell
pip install -r requirements.txt
python claude_usage_widget.py
```

Quick check without the GUI:

```powershell
python claude_usage_widget.py --once
```

## Download the .exe

Grab `ClaudeUsageWidget.exe` from the [Releases](../../releases) page, or build
it yourself (see below). No Python install required to run the `.exe`.

## Build the .exe yourself

```powershell
.\build.ps1
# or:  build.bat
```

The standalone executable lands in `dist\ClaudeUsageWidget.exe`. To use a custom
icon, drop an `icon.ico` next to the script before building.

## Releasing on GitHub (auto-build)

A GitHub Actions workflow (`.github/workflows/build.yml`) builds the `.exe` on
`windows-latest`. Push a version tag and it attaches the binary to the release:

```powershell
git tag v1.0.0
git push origin v1.0.0
```

You can also trigger it manually from the **Actions** tab (Run workflow) and
download the `.exe` from the build artifacts.

## How it works

| Field shown            | API field (`/api/oauth/usage`) |
| ---------------------- | ------------------------------ |
| Session · 5-hour       | `five_hour.utilization`        |
| Weekly · all models    | `seven_day.utilization`        |
| Weekly · Opus          | `seven_day_opus.utilization`   |
| Weekly · Sonnet        | `seven_day_sonnet.utilization` |
| Extra usage            | `extra_usage`                  |

`utilization` is a percentage (0–100). `resets_at` is an ISO timestamp shown as
a countdown. Buckets your plan doesn't track come back `null` and are hidden.

If the token has expired, the widget shows a notice — open Claude Code once to
refresh it, and the widget picks up the new token on the next poll (it re-reads
the credentials file every minute).

## Notes

- Windows-first (the minimise-to-taskbar trick uses Win32). The widget still
  runs on macOS/Linux; minimise falls back to the standard `iconify`.
- The usage endpoint is an undocumented endpoint used by Claude Code itself;
  Anthropic may change it without notice.

## License

[MIT](LICENSE)
