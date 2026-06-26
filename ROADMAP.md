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

### v1.1 — shipped
- **Throttle status banner** from the `anthropic-ratelimit-unified-status` header (warning / queueing / rejected).
- **Utilization trend sparkline** — each refresh samples into a 24h ring buffer; draws the 5h-window history (account-wide).
- **Config file** (`~/.config/claude-meter/config.json`) — `alert_levels`, `active_min`, `dual_title`, `title_window`.
- **Optional dual title** — show both windows in the menu bar (`◔35 ◑48`), off by default.
- **Quick links** — repo / `~/.claude` logs / Anthropic status.
- **Computed insight line** — e.g. "95% of input is cached context → `/compact` more often."
- **Crisp light/dark-adaptive text colors** so no line reads faint.

### v2 — Linux
- Verify where Claude Code stores the OAuth token on Linux (`~/.claude/.credentials.json` vs libsecret) and finish `get_token()`.
- **waybar** custom module + **Argos** (GNOME) front-ends sharing the same core.
- `install-linux.sh`.

### Ideas / maybe
- Merge "active sessions" across machines (each box drops a small summary into a shared folder).
- Burn-rate ($/hour) in the active 5h block.
- A weekly-window sparkline alongside the 5h one.
