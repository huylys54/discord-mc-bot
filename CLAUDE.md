# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What This Is

Discord bot that controls a Minecraft GCP VM via slash commands. `app.py` is the main entry point.

## Running

```powershell
uv run python app.py
```

Or via Docker:

```powershell
docker compose up
```

## Required Environment (`.env`)

```
DISCORD_TOKEN=
PROJECT_ID=
ZONE=
INSTANCE_NAME=
RCON_PASSWORD=
RCON_PORT=25575
GCP_SECRET_FILE=gcp-secret.json
DEV_GUILD_ID=          # optional: guild ID for fast guild-scoped command sync
NOTIFY_CHANNEL_ID=     # optional: channel ID for idle shutdown notices
```

`GCP_SECRET_FILE` path is loaded into `os.environ["GOOGLE_APPLICATION_CREDENTIALS"]` at startup. Default file is `gcp-secret.json` in repo root.

## Architecture

Two source files:

- **`app.py`** — bot logic, all commands, GCP + RCON integration
- **`logger.py`** — loguru setup: INFO+ to stderr, DEBUG+ to `logs/bot.log` (10 MB rotation, 7-day retention)

### Commands

| Command | Check | Behavior |
|---|---|---|
| `/mc-start` | whitelisted | Start VM, await `operation.result`, poll RCON (420 s timeout), mention user when ready |
| `/mc-stop` | whitelisted | Fire stop operation, do NOT await completion |
| `/mc-status` | whitelisted | Get VM status; if RUNNING, fetch player count via RCON |
| `/mc-allow` | owner-only | Add user ID to `whitelist.json` |
| `/mc-remove` | owner-only | Remove user ID from `whitelist.json` |

### Key Implementation Details

- GCP calls via `google-cloud-compute` (`compute_v1.InstancesClient`), wrapped in `asyncio.to_thread`
- `_MCRcon` subclass of `mcrcon.MCRcon` skips `signal.signal()` — safe to call from asyncio threads
- `wait_for_minecraft(hosts, timeout=420)` polls RCON via `asyncio.to_thread(_try_rcon, host)` every 10 s
- Whitelist stored in `whitelist.json` as a list of user IDs; loaded into module-level `set[int]`
- `is_whitelisted()` / `is_owner()` are `discord.app_commands.check` predicates
- `DEV_GUILD_ID` set → commands synced to that guild only (fast); unset → global sync

### Docker

`docker-compose.yml` mounts `./whitelist.json:/app/whitelist.json` so whitelist persists across container restarts. `GCP_SECRET_FILE` passed as build arg.

## Dependencies

Managed with `uv` (Python 3.13+). Install:

```powershell
uv sync
```
