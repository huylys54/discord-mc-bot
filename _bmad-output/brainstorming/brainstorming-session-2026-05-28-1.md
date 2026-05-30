---
stepsCompleted: [1, 2, 3, 4]
session_topic: Feature ideas for Discord MC bot — player experience and ops/admin
session_goals: Generate focused, actionable feature ideas for a small crew (2-3 people) using the bot after office hours. Bot controls a Minecraft GCP VM as an experiment to gauge interest before moving to cheaper hosting.
selected_approach: ai-recommended
techniques_used: [SCAMPER, What If Scenarios, Reverse Brainstorming]
ideas_generated: 12
context_file: ''
workflow_completed: true
---

## Session Overview

**Topic:** Feature ideas for Discord MC bot — Player Experience + Ops/Admin
**Goals:** Actionable features for a small after-hours crew. Bot is part of a hosting experiment — data matters.

**Key Constraints:**
- Small crew (2-3 people), coordinates via Discord chat already
- VM shuts down on the VM side (not bot-controlled) after 30min inactivity
- Cost discipline — server starts only on demand, no auto-triggers
- Bot runs in Docker on a separate VM

---

## Technique Selection

**Approach:** AI-Recommended
**Phase 1:** SCAMPER Method — systematic mutation of existing commands
**Phase 2:** What If Scenarios — push past obvious ideas
**Phase 3:** Reverse Brainstorming — find ops pain points via anti-patterns

---

## Ideas Generated

### Player Experience

**[Player XP #1]**: Who Started It
_Concept:_ `/mc-start` completion message shows the invoker's Discord avatar/name in a rich embed — "huylys fired up the server! Join now." Includes server IP, player count, timestamp.
_Novelty:_ Turns a system event into a social moment — coworker sees it and feels invited, not just informed.

**[Player XP #2]**: The Dashboard
_Concept:_ `/mc-status` returns a code-block ASCII panel — server state, online players with names, VM uptime, estimated GCP cost this session.
_Novelty:_ Feels like a real ops tool. All context in one glance, no follow-up questions needed.

```
╔══════════════════════════════╗
║  🟢 MC SERVER — ONLINE       ║
║  Uptime : 1h 23m             ║
║  Players: 2/20               ║
║    • huylys      (45m)       ║
║    • coworker    (12m)       ║
║  Est. cost: $0.18            ║
╚══════════════════════════════╝
```

**[Player XP #3]**: First Blood Ping
_Concept:_ `/mc-start` gains optional `--watch` flag. After server ready, bot polls RCON player list every 30s. First player joins → pings the starter "coworker just joined!"
_Novelty:_ Closes the "is anyone actually playing?" loop without manual `/mc-status` polling.

**[Player XP #4]**: Live Presence
_Concept:_ Bot's Discord status reflects server state — "🟢 MC online · 2 players" when running, "⚫ MC offline" when stopped. Updates on start/stop/idle shutdown.
_Novelty:_ Zero-command status check. Crew sees it in the member list sidebar instantly. Also updates `#minecraft` channel topic with IP when online.

**[Player XP #5]**: In-Game Warning
_Concept:_ `/mc-stop` fires RCON `say` command — "Server shutting down in 60 seconds, find shelter!" — waits 60s, then stops VM. Idle shutdown also broadcasts via RCON before VM kill.
_Novelty:_ Players get warned inside the game, not just Discord. No more dying because server vanished mid-fight.

**[Player XP #6]**: Session Intent
_Concept:_ `/mc-start` gains optional `reason` parameter. If provided, shows in ready notification — "huylys started the server · grinding diamonds tonight 🎮". Logged to session data.
_Novelty:_ Turns server start into a social invite. Coworkers see what's happening before they decide to join.

---

### Ops/Admin

**[Ops #1]**: Shutdown Countdown
_Concept:_ Idle watcher sends warnings at 15min, 10min, 5min before shutdown (currently warns at 25min and 30min). Each message includes "⏱️ X minutes until shutdown." Final message confirms shutdown.
_Novelty:_ More granular warnings give players time to react. Also doubles as a cost-awareness signal.
_Note:_ No cancel mechanic — VM handles shutdown on its own side.

**[Ops #2]**: Session Cost Tracker
_Concept:_ Bot records VM start timestamp. On `/mc-status`, shutdown, and idle kill — calculates elapsed time × VM hourly rate = estimated cost. Shows in dashboard and shutdown summary "Session: 1h 23m · ~$0.31"
_Novelty:_ Makes cloud cost tangible. Natural nudge to shut down when you see the meter running.

**[Ops #3]**: Experiment Dashboard — `/mc-stats`
_Concept:_ Persistent log (JSON/SQLite) tracks every session — start time, duration, players, estimated cost, session reason. `/mc-stats` shows cumulative: total sessions, unique players, avg session length, total VM hours, total estimated spend.
_Novelty:_ Reframes the bot as an experiment tracker. The "should we get real hosting?" answer in one command backed by real data.

**[Ops #4]**: Health Check
_Concept:_ Periodic RCON ping every 5min while VM is RUNNING. If RCON fails 3× consecutive → bot posts alert "⚠️ Server may be down — VM running but MC unreachable" in notify channel.
_Novelty:_ Catches silent failures (VM running, MC process dead). Bad experience = skewed experiment data.

**[Ops #5]**: Failure Reporting
_Concept:_ All GCP errors surface in Discord with plain-English messages — "Failed to start VM: quota exceeded", "Stop failed: instance not found". Currently errors vanish into logs only. Also fast-fails with specific GCP error within seconds, not after 420s timeout.
_Novelty:_ Ops errors visible where the crew lives. No more mystery timeouts.

**[Ops #6]**: Auto-Restart ✅ IMPLEMENTED
_Concept:_ `restart: unless-stopped` added to `docker-compose.yml`. Bot crashes → Docker restarts it automatically. Won't restart on manual `docker compose stop`.
_Novelty:_ Eliminates the #1 manual ops task — SSH-ing in to restart the bot.

---

## Prioritization

### Quick Wins (high impact, low effort)
- ✅ **Auto-Restart** — done
- **Failure Reporting** — wrap GCP calls in try/except, surface errors
- **In-Game Warning** — one RCON `say` call before stop
- **Live Presence** — `bot.change_presence()` on start/stop events

### Medium Effort, High Value
- **Who Started It + Dashboard** — embed upgrade across commands
- **Shutdown Countdown** — extend idle watcher with more warning intervals
- **First Blood Ping** — poll RCON player list post-start with watch flag
- **Session Intent** — add optional `reason` param to `/mc-start`

### Bigger Builds
- **Session Cost Tracker** — needs VM hourly rate config + session log
- **Experiment Dashboard `/mc-stats`** — needs persistent storage
- **Health Check** — background task, periodic RCON ping

---

## Session Summary

**12 ideas** generated across player experience and ops/admin themes.
**1 idea implemented** during session (Auto-Restart).
**Next action:** Implement quick wins — Failure Reporting, In-Game Warning, Live Presence.

**Key insight:** This bot serves double duty — player UX tool AND experiment tracker. Features that generate data (session logs, cost tracking, player counts) serve the hosting migration decision, not just day-to-day convenience.
