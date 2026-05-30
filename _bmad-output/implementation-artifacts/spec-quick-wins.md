---
title: 'Quick Wins: Failure Reporting, In-Game Warning, Live Presence'
type: 'feature'
created: '2026-05-28'
status: 'done'
baseline_commit: 'fd9747795ad2caee76743f4cf0f02518d9a5f093'
context: []
---

<frozen-after-approval reason="human-owned intent — do not modify unless human renegotiates">

## Intent

**Problem:** GCP errors vanish into logs with no Discord feedback; `/mc-stop` kills the server without warning players in-game; bot presence is static and gives no server state at a glance.

**Approach:** (1) Wrap all GCP calls in try/except and surface plain-English errors to the invoking interaction. (2) Fire an RCON `say` 60s before `/mc-stop` executes, and at the 25-min idle mark before VM auto-shutdown. (3) Call `bot.change_presence()` on start/stop/idle events to reflect live server state; update the notify channel topic with the server IP when online.

## Boundaries & Constraints

**Always:** RCON warning failures must be caught and silently skipped — never block a stop. GCP error messages must be user-readable (no raw stack traces to Discord). Presence updates use `discord.Game` activity string only.

**Ask First:** If the notify channel lacks `manage_channels` permission for topic updates — skip topic update, log warning, do not crash.

**Never:** Do not add retry logic to GCP calls. Do not await `operation.result` in `/mc-stop` (fire-and-forget intentional). Do not introduce new env vars.

## I/O & Edge-Case Matrix

| Scenario | Input / State | Expected Output / Behavior | Error Handling |
|----------|--------------|---------------------------|----------------|
| `/mc-start` GCP error | `client.start()` or `operation.result()` raises | Followup: "❌ Failed to start VM: {e}" | Caught, message sent, return |
| `/mc-stop` normal | RCON reachable | Discord: "⚠️ Shutting down in 60s"; RCON say fires; 60s wait; VM stop called | — |
| `/mc-stop` RCON unreachable | RCON down or IP fetch fails | RCON say skipped silently; VM stop still proceeds after 60s | Exception caught, logged |
| `/mc-stop` GCP error | `client.stop()` raises | Followup: "❌ Failed to stop VM: {e}" | Caught, message sent |
| `/mc-status` GCP error | `get_instance()` raises | Followup: "❌ Failed to get VM status: {e}" | Caught, message sent |
| Idle 25-min mark | 0 players for 25 min | Discord warning + RCON say "Server auto-shutting down in ~5 minutes, find shelter!" | RCON error silently skipped |
| `mc_start` success | VM + MC ready | Presence → "🟢 MC online" | — |
| `mc_stop` called | After stop fires | Presence → "⚫ MC offline" | — |
| Idle STOPPED transition | VM goes STOPPED/TERMINATED | Presence → "⚫ MC offline"; channel topic cleared | — |
| Channel topic update | `mc_start` success, IP known | `NOTIFY_CHANNEL_ID` topic set to "🟢 MC online — {ip}" | Missing permission: log warning, skip |
| Bot startup | `on_ready` fires | Presence → "⚫ MC offline" | — |

</frozen-after-approval>

## Code Map

- `app.py:95-102` — `_try_rcon`: model for new `_rcon_say(host, msg)` helper
- `app.py:208-221` — `on_ready`: set initial offline presence
- `app.py:224-256` — `mc_start`: needs try/except around GCP calls; presence update on success; channel topic update
- `app.py:259-274` — `mc_status`: needs try/except around `get_instance()`
- `app.py:277-296` — `mc_stop`: add RCON say + 60s wait before stop; try/except around GCP call; presence update
- `app.py:148-200` — `idle_watcher`: RCON say at 25-min mark; presence + topic update on STOPPED transition

## Tasks & Acceptance

**Execution:**
- [x] `app.py` -- Add `_rcon_say(host: str, message: str) -> None` sync helper using `_MCRcon`; raises on failure (callers catch) -- reuses existing RCON pattern
- [x] `app.py` -- Wrap `mc_start` GCP calls in try/except; send "❌ Failed to start VM: {e}" on error; add `bot.change_presence` + channel topic update on success
- [x] `app.py` -- In `mc_stop`: change initial response to "⚠️ Sending shutdown warning... stopping in 60 seconds"; try to fetch IP + call `asyncio.to_thread(_rcon_say, ...)` (catch silently); `await asyncio.sleep(60)`; wrap `client.stop()` in try/except; set presence to offline after stop fires
- [x] `app.py` -- Wrap `mc_status` `get_instance()` in try/except; send "❌ Failed to get VM status: {e}" on error
- [x] `app.py` -- In `idle_watcher` at 25-min mark: add `asyncio.to_thread(_rcon_say, ...)` call (catch silently); on STOPPED/TERMINATED transition: set presence to offline + clear channel topic
- [x] `app.py` -- In `on_ready`: set initial presence to offline via `await bot.change_presence(status=discord.Status.idle, activity=discord.Game("⚫ MC offline"))`

**Acceptance Criteria:**
- Given `/mc-start` and GCP raises, when command runs, then Discord shows "❌ Failed to start VM: ..." without waiting 420s
- Given `/mc-stop` and server is reachable, when command runs, then RCON say fires, 60s elapses, then VM stop is called
- Given `/mc-stop` and RCON is down, when command runs, then VM stop proceeds without blocking or error to Discord
- Given idle watcher hits 25-min mark with 0 players, when RCON reachable, then in-game warning fires alongside Discord warning
- Given `mc_start` succeeds, when Minecraft is ready, then bot presence shows "🟢 MC online" and channel topic shows IP
- Given VM transitions to STOPPED/TERMINATED, when idle watcher detects it, then bot presence shows "⚫ MC offline"
- Given bot starts, when `on_ready` fires, then presence shows "⚫ MC offline"

## Spec Change Log

## Verification

**Manual checks (if no CLI):**
- Invoke `/mc-start` with bad GCP creds — Discord shows "❌ Failed to start VM: ..." within seconds (not after 420s timeout)
- Invoke `/mc-stop` — Discord shows 60s warning; in-game `say` visible if server up; VM stop fires after delay; bot sidebar presence changes
- Check `NOTIFY_CHANNEL_ID` channel topic after `/mc-start` success — shows "🟢 MC online — {ip}"
- Bot restart — presence shows "⚫ MC offline" immediately

## Suggested Review Order

**RCON Say Helper**

- New `_rcon_say` sync helper; identical pattern to `_try_rcon`, sends `say` command
  [`app.py:105`](../../app.py#L105)

**Failure Reporting**

- `mc_start`: GCP start + operation.result wrapped; fast-fails to Discord on error
  [`app.py:253`](../../app.py#L253)

- `mc_start`: second try/except for IP fetch; separate error message preserves context
  [`app.py:270`](../../app.py#L270)

- `mc_status`: single try/except around get_instance; clean early return
  [`app.py:301`](../../app.py#L301)

- `mc_stop`: try/except around client.stop; error surfaced before return
  [`app.py:337`](../../app.py#L337)

**In-Game Warning**

- `mc_stop`: response message changed; RCON say + 60s sleep before GCP stop call
  [`app.py:325`](../../app.py#L325)

- `idle_watcher`: RCON say at 25-min mark alongside Discord warning; silently skipped on failure
  [`app.py:214`](../../app.py#L214)

**Live Presence**

- `on_ready`: initial offline presence set before any user interaction
  [`app.py:241`](../../app.py#L241)

- `mc_start`: online presence + channel topic set only on confirmed MC ready
  [`app.py:282`](../../app.py#L282)

- `mc_stop`: offline presence set after stop fires successfully
  [`app.py:350`](../../app.py#L350)

- `idle_watcher`: offline presence + topic clear on STOPPED/TERMINATED transition (fires once per transition)
  [`app.py:180`](../../app.py#L180)
