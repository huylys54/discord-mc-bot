# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What This Is

Discord bot that controls a Minecraft GCP VM via slash commands. `bot.py` is the main entry point — `main.py` is a placeholder.

## Running

```powershell
uv run python bot.py
```

## Required Environment (`.env`)

```
DISCORD_TOKEN=
PROJECT_ID=
ZONE=
INSTANCE_NAME=
RCON_PASSWORD=
```

`gcp-key.json` must be present in repo root — used directly via `os.environ["GOOGLE_APPLICATION_CREDENTIALS"]`.

## Architecture

Single-file bot (`bot.py`):
- Uses `discord.py` app commands (`bot.tree.command`) with `!` prefix bot for legacy compat
- Three slash commands: `/mc-start`, `/mc-stop`, `/mc-status`
- GCP calls via `google-cloud-compute` (`compute_v1.InstancesClient`)
- `mc-start` polls operation status in a loop (`asyncio.sleep(3)`) — blocking style in async context
- `mc-stop` does NOT await operation completion before sending followup

## Dependencies

Managed with `uv` (Python 3.13+). Install:

```powershell
uv sync
```
