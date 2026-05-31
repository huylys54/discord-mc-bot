# Deferred Work

## From spec-health-check-live-presence (2026-05-31) — review findings

- `app.py:196` (idle_watcher) + `app.py:301` (health_checker) — `bot.fetch_channel` / `channel.send` called without `isinstance(channel, discord.TextChannel)` check. If `NOTIFY_CHANNEL_ID` points to a non-text channel (voice, category), `.send()` raises HTTPException, caught and logged silently. Pre-existing pattern in `idle_watcher`.
- `app.py:330` — `mc_start` sets static `"🟢 MC online"` presence on success; `idle_watcher` overwrites it within 60 s with the dynamic format. Static string is now redundant — only visible for < 1 min. Pre-existing after Live Presence change.
- `app.py:282` — `_health_consecutive_failures` not reset when `health_checker` restarts after a crash (via `on_ready` reconnect). Stale count could suppress or falsely advance the alert threshold.

## From spec-health-check-live-presence (2026-05-31)

- `app.py:299` — `health_checker` alert uses `== 3` (fires once per burst, then silent). If RCON stays broken beyond 3 ticks no further alerts fire until recovery + 3 more failures. Consider re-alerting at a longer interval (e.g. every N ticks) if longer outages need visibility.
- `app.py:285` — `health_checker` gates on `_idle_last_vm_status` (set by `idle_watcher`). On bot cold-start with VM already RUNNING, the first health_checker tick skips until `idle_watcher` has set the status (1-min lag max). Acceptable but worth noting.
- `app.py:299` — Alert message hardcodes "15 minutes" (3 ticks × 5 min). If the loop interval changes, this string becomes stale.

## From spec-session-intent (2026-05-31)

- `app.py:333` — `reason` embed field value is not sanitized for Discord markdown. Whitelisted users only so risk is low, but a future `/mc-start` open to more users should strip or escape backtick-heavy content.

## From feat/health-check-session-intent split (2026-05-31)

- **Health Check** — background `tasks.loop` that pings RCON every 5 min while VM is RUNNING; alerts `NOTIFY_CHANNEL_ID` after 3 consecutive RCON failures. Pattern: reuse `_try_rcon` + `idle_watcher` task structure.
- **Live Presence** — update `bot.change_presence` every `idle_watcher` tick when RUNNING to show uptime + player count (e.g. `"🟢 MC | 1h 23m | 2/20"`). Requires calling `_fmt_uptime` and `_get_player_count` inside `idle_watcher`.

## From quick-wins-dashboard-countdown (2026-05-30)

- **First Blood Ping** — `/mc-start --watch`; polls RCON post-start, pings starter when first player joins
- **Session Intent** — optional `reason` param on `/mc-start`, shown in the ready notification

## From spec-player-xp-2-mc-status-dashboard (2026-05-30)

- `app.py:132,116` — `_get_players` and `_get_player_count` duplicate the RCON connection + timeout-restore boilerplate. Candidate for extraction into a shared `_rcon_command(host, cmd)` helper when a third RCON function is needed.

## From spec-quick-wins-dashboard-countdown (2026-05-30)

- `app.py:213` — `idle_watcher` 30-min branch sends "shutting down now" but the bot never issues a GCP stop command; VM self-terminates via its own idle policy. Message is accurate by design (per CLAUDE.md) but could be confusing if the VM's idle policy is ever changed.
- `app.py:154` — `_idle_warned_minutes` (and `_idle_empty_minutes`) are not reset when `idle_watcher` task restarts mid-session (e.g., on Discord reconnect). Pre-existing behavior inherited from old boolean flags. If the watcher restarts while idle, some threshold warnings may be skipped for that session.

## From spec-quick-wins (2026-05-28)

- `app.py:312` — `mc_status`: unguarded `instance.network_interfaces[0].access_configs[0].nat_i_p` — if VM is RUNNING but has no external access config, raises IndexError. Pre-existing issue, not introduced by quick-wins change.
