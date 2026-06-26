# claude-meter

A tiny macOS menu-bar gauge for your **Claude Code usage** — the real 5‑hour and weekly rate-limit numbers Anthropic enforces, pulled live from the API's response headers (not estimated), with desktop alerts before you hit a wall.

```
  ◔ 45%        ← menu bar: a disc that fills with your 5h load, color-coded
  ──────────────────────────────────────────────────────────
  5h   ▕██████▎░░░░░░░▏  45%
       resets Fri 1:50 PM · 3h01m · at this rate → ~89% at reset
  week ▕██████▉░░░░░░░▏  49%
       resets Tue 11:00 PM · 4d12h · at this rate → 100% by Mon 12:30 AM (~1d22h locked out)
  📈 5h · 24h  ▕▁▂▃▅▆█▇▅▃▂▁·····▂▄▆▏  now 45%
  ──────────────────────────────────────────────────────────
  ● live — Anthropic headers · 2m ago · ↻ refresh
  ──────────────────────────────────────────────────────────
  ⚡ Active sessions · this machine
  click a row to reopen that session in a terminal
  Set up mosh via ZeroTier   $224.95 · ctx 294k · 2 subagents · 4m ago
  ──────────────────────────────────────────────────────────
  💡 95% of input is cached context — /compact more often
  ──────────────────────────────────────────────────────────
  💵 Cost & history (local $ proxy)   ▸   (per-day · totals · by-model)
  🔗 Links                            ▸   (repo · ~/.claude · status)
```

The menu-bar glyph is itself a gauge that fills with your 5‑hour load…

| ◯ | ◔ | ◑ | ◕ | ● |
|---|---|---|---|---|
| 0% | ~25% | ~50% | ~75% | 100% |

…and shifts **green → amber → red** as it fills.

## Why

Claude Code shows your usage with `/usage`, but only when you go looking. claude-meter keeps the two numbers that actually gate you — the **5‑hour** and **weekly** windows — glanceable in the menu bar, and pings you *before* you hit the cap, so a big run never dies halfway.

## What it shows

- **Live 5h + weekly % gauges**, color-coded, from Anthropic's rate-limit headers.
- **Exact reset times** — clock time *and* countdown (`resets Tue 11:00 PM · in 4d 12h`).
- **🔔 Threshold alerts** — a desktop notification when a window crosses 80% / 95%, once per crossing per window (runs in the background, even with the menu closed).
- **⏳ Projected exhaustion** — "on pace to hit the weekly cap ~Mon 2 AM" from your current burn.
- **🚦 Throttle status** — a banner if Anthropic is warning / queueing / rejecting your requests, so you know *why* Claude feels slow.
- **📈 Utilization trend** — a 24-hour sparkline of your 5h window, **account-wide** (sampled from the headers each refresh).
- **Active sessions (this machine)** — sessions with log activity in the last 30 min, ranked by spend, with peak context size and subagent count; **click one to reopen it in a terminal** (runs `claude --resume` for you).
- **$ proxy stats** — per-day burn chart, today / week / 30d / all-time, and a by-model breakdown.
- **💡 Insight line** — one computed tip from your week (e.g. "95% of input is cached context — `/compact` more often").
- **🔗 Quick links** — jump to the repo, your `~/.claude` logs, or Anthropic's status page.

### Account-wide vs. local — important

- **The two % gauges are account-wide.** Anthropic enforces the rate limit *server-side per account*, so the utilization headers already reflect **every machine** you're signed into. Run claude-meter on any one of them and the bars are correct for your whole account.
- **The $ figures and "active sessions" are local** — parsed from *this* machine's `~/.claude/projects` logs. They tell you where *this machine's* tokens went, not your global breakdown. The section is labeled "this machine" so it's never misleading.

## How it works

- On each refresh it sends a **1-token** request to the Anthropic API and reads the response's `anthropic-ratelimit-unified-*` headers (`5h`/`7d` utilization + reset timestamps). Those are the source of truth.
- It authenticates with **your own Claude Code OAuth token**, read from the macOS Keychain (`Claude Code-credentials`) — the same token Claude Code already uses. Nothing is stored or transmitted anywhere except that one call to `api.anthropic.com`.
- The dollar figures come from a **local cost proxy** that parses `~/.claude/projects/**/*.jsonl` and prices the tokens at Anthropic's published rates. On a Pro/Max plan these are *equivalent* API costs, not money billed — a usage proxy. If the API is unreachable (token expired, offline), the widget falls back to this proxy for the percentage bars too.

## Requirements

- **macOS** (the menu-bar host, SwiftBar, is macOS — a Linux port is on the roadmap)
- [**Homebrew**](https://brew.sh)
- **Claude Code**, installed and logged in (so the OAuth token is in your Keychain)
- **Python 3** (system / conda / brew — no third-party packages)
- [**SwiftBar**](https://github.com/swiftbar/SwiftBar) — the installer adds it for you

## Install

```sh
git clone https://github.com/FHunist/claude-meter.git
cd claude-meter
./install.sh
```

The installer installs SwiftBar via Homebrew if needed, copies `claude-meter.5m.py` into `~/SwiftBarPlugins/`, points SwiftBar at that folder, and launches it.

### First run — two one-time grants

1. **Plugin folder.** On its first launch SwiftBar asks you to choose a plugin folder. Pick **`~/SwiftBarPlugins`** (the installer just created it). The disc then appears in your menu bar.
2. **Keychain.** The first live fetch pops *"SwiftBar wants to use the Claude Code-credentials key."* Click **Always Allow** so it can read your token each refresh. Deny it and the widget still runs — it just shows `○ proxy` and uses the local estimate.

## Usage notes

- Auto-refreshes every **5 minutes** (the `.5m.` in the filename). The dropdown has a **↻ Refresh now** button that force-pings past the cache, and an *"updated Xm ago"* freshness line.
- Polling cost is negligible: one 1-token Haiku request per refresh (~288/day).

## Customize

- **Refresh interval:** rename the file — `claude-meter.2m.py` (2 min), `.10m.py`, `.1h.py`, …
- **Alert thresholds:** edit `ALERT_LEVELS` near the top of the plugin (default `[80, 95]`).
- **Active-session window:** edit `ACTIVE_MIN` (default `30` min) — how recently a session must have logged to count as active.
- **Config file (no code edits):** create `~/.config/claude-meter/config.json` with any of:
  ```json
  {"alert_levels": [80, 95], "active_min": 30, "dual_title": false, "title_window": "5h", "terminal": "Terminal"}
  ```
  `dual_title: true` shows **both** windows in the menu bar (`◔35 ◑48`); `title_window: "weekly"` makes the single gauge track the weekly window instead of the 5h. `terminal` picks where a clicked session reopens: `"Terminal"` (default) or `"iTerm"` — both reliable via AppleScript; `"Warp"` also works but drives the app with simulated keystrokes (needs Accessibility permission and can be flaky). On first click macOS asks to let SwiftBar control the terminal → **Allow**.
- **Show / hide sections:** add a `show` object to trim the dropdown to exactly what you want — set any to `false`:
  ```json
  {"show": {"forecast": true, "trend": true, "sessions": true, "insight": true, "cost": true, "links": true}}
  ```
  e.g. `{"show": {"cost": false, "links": false, "trend": false}}` gives a minimal menu. The menu-bar gauge and the 5h + weekly bars always show.
- **Colors:** edit `clr()` (default: green <50%, amber <80%, red ≥80%).
- **Offline fallback caps (optional):** drop `claude_limit.txt` (5h) / `claude_weekly_limit.txt` (weekly) into `~/.config/claude-meter/`, one number each — used only to scale the proxy bars when the API is down.

## Uninstall

```sh
./uninstall.sh
```

Removes the plugin and the `~/.config/claude-meter` cache. SwiftBar is left in place (`brew uninstall --cask swiftbar` to remove it too).

## Privacy & security

- Your OAuth token is read from the Keychain at refresh time and used **only** as the bearer for a single request to `api.anthropic.com`. It's never written to disk, logged, or sent anywhere else.
- The only thing cached locally is the parsed utilization numbers + alert state under `~/.config/claude-meter/`.
- It's one dependency-free Python file — read it before you run it.

## Roadmap

See [ROADMAP.md](ROADMAP.md) — next up: a utilization trend sparkline, a config file, and a **Linux port** (waybar / Argos) for non-Mac workstations.

## License

MIT — see [LICENSE](LICENSE).
