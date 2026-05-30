# Deferred Work

## From quick-wins-dashboard-countdown (2026-05-30)

- **First Blood Ping** — `/mc-start --watch`; polls RCON post-start, pings starter when first player joins
- **Session Intent** — optional `reason` param on `/mc-start`, shown in the ready notification

## From spec-quick-wins-dashboard-countdown (2026-05-30)

- `app.py:213` — `idle_watcher` 30-min branch sends "shutting down now" but the bot never issues a GCP stop command; VM self-terminates via its own idle policy. Message is accurate by design (per CLAUDE.md) but could be confusing if the VM's idle policy is ever changed.
- `app.py:154` — `_idle_warned_minutes` (and `_idle_empty_minutes`) are not reset when `idle_watcher` task restarts mid-session (e.g., on Discord reconnect). Pre-existing behavior inherited from old boolean flags. If the watcher restarts while idle, some threshold warnings may be skipped for that session.

## From spec-quick-wins (2026-05-28)

- `app.py:312` — `mc_status`: unguarded `instance.network_interfaces[0].access_configs[0].nat_i_p` — if VM is RUNNING but has no external access config, raises IndexError. Pre-existing issue, not introduced by quick-wins change.
