# Roadmap

### v1 — shipped
- Live 5h + weekly rate-limit gauges from Anthropic's `anthropic-ratelimit-unified-*` headers (account-wide).
- Menu-bar disc that fills with load, color-coded green → amber → red.
- Exact reset times (clock + countdown).
- 🔔 Threshold alerts (desktop notification at 80% / 95%, once per window).
- ⏳ Projected exhaustion from current burn.
- Heavy sessions (this machine) with peak context + subagent count; click to copy `claude --resume`.
- $ cost proxy: per-day chart, today/week/30d/all-time, by-model.
- One-command installer; cross-platform core with per-OS shims.

### v1.1 — polish
- **Utilization trend sparkline** — sample each refresh into a 24h ring buffer and draw the 5h-window history.
- **Config file** (`~/.config/claude-meter/config.json`) — alert thresholds, colors, which window drives the title.
- **One computed insight line** — e.g. "68% of tokens are cache-reads → `/compact` more often."

### v2 — Linux
- Verify where Claude Code stores the OAuth token on Linux (`~/.claude/.credentials.json` vs libsecret) and finish `get_token()`.
- **waybar** custom module + **Argos** (GNOME) front-ends sharing the same core.
- `install-linux.sh`.

### Ideas / maybe
- Merge "heavy sessions" across machines (each box drops a small summary into a shared folder).
- Burn-rate ($/hour) in the active 5h block.
- Click the menu-bar title to toggle between the 5h and weekly number.
