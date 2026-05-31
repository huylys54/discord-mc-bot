import os
import re
import json
import socket
import asyncio
from datetime import datetime, timezone
import discord
import mcrcon
from discord.ext import commands, tasks
from google.cloud import compute_v1
from dotenv import load_dotenv
from logger import logger

load_dotenv()

TOKEN = os.getenv("DISCORD_TOKEN")

PROJECT_ID = os.getenv("PROJECT_ID")
ZONE = os.getenv("ZONE")
INSTANCE_NAME = os.getenv("INSTANCE_NAME")
RCON_PORT = int(os.getenv("RCON_PORT", 25575))
RCON_PASSWORD = os.getenv("RCON_PASSWORD")

WHITELIST_FILE = "whitelist.json"
DEV_GUILD_ID = os.getenv("DEV_GUILD_ID")
NOTIFY_CHANNEL_ID = int(os.getenv("NOTIFY_CHANNEL_ID", 0)) or None

os.environ["GOOGLE_APPLICATION_CREDENTIALS"] = os.getenv("GCP_SECRET_FILE")

intents = discord.Intents.default()
bot = commands.Bot(command_prefix="!", intents=intents)


def load_whitelist() -> set[int]:
    try:
        with open(WHITELIST_FILE) as f:
            return set(json.load(f))
    except FileNotFoundError:
        return set()


def save_whitelist(whitelist: set[int]) -> None:
    with open(WHITELIST_FILE, "w") as f:
        json.dump(list(whitelist), f)


whitelist: set[int] = load_whitelist()


def is_whitelisted():
    async def predicate(interaction: discord.Interaction) -> bool:
        if await interaction.client.is_owner(interaction.user):
            return True
        if interaction.user.id in whitelist:
            return True
        await interaction.response.send_message("❌ You don't have permission to use this command.", ephemeral=True)
        return False
    return discord.app_commands.check(predicate)


def is_owner():
    async def predicate(interaction: discord.Interaction) -> bool:
        if await interaction.client.is_owner(interaction.user):
            return True
        await interaction.response.send_message("❌ Only the bot owner can use this command.", ephemeral=True)
        return False
    return discord.app_commands.check(predicate)


def get_instance():
    client = compute_v1.InstancesClient()
    return client.get(
        project=PROJECT_ID,
        zone=ZONE,
        instance=INSTANCE_NAME,
    )


class _MCRcon(mcrcon.MCRcon):
    """Signal-free MCRcon subclass safe for use in threads."""
    def __init__(self, host, password, port=25575, tlsmode=0, timeout=0):
        self.host = host
        self.password = password
        self.port = port
        self.tlsmode = tlsmode
        self.timeout = timeout
        self.socket = None

    def _read(self, length):
        data = b""
        while len(data) < length:
            data += self.socket.recv(length - len(data))
        return data


def _try_rcon(host: str) -> None:
    prev = socket.getdefaulttimeout()
    socket.setdefaulttimeout(10)
    try:
        with _MCRcon(host, RCON_PASSWORD, port=RCON_PORT) as mcr:
            mcr.command("list")
    finally:
        socket.setdefaulttimeout(prev)


def _rcon_say(host: str, message: str) -> None:
    prev = socket.getdefaulttimeout()
    socket.setdefaulttimeout(10)
    try:
        with _MCRcon(host, RCON_PASSWORD, port=RCON_PORT) as mcr:
            mcr.command(f"say {message}")
    finally:
        socket.setdefaulttimeout(prev)


def _get_player_count(host: str) -> str | None:
    prev = socket.getdefaulttimeout()
    socket.setdefaulttimeout(5)
    try:
        with _MCRcon(host, RCON_PASSWORD, port=RCON_PORT) as mcr:
            response = mcr.command("list")
        match = re.search(r"(\d+).*?of.*?(\d+)", response)
        if match:
            return f"{match.group(1)}/{match.group(2)}"
        return None
    except Exception:
        return None
    finally:
        socket.setdefaulttimeout(prev)


def _get_players(host: str) -> tuple[str, list[str]] | None:
    prev = socket.getdefaulttimeout()
    socket.setdefaulttimeout(5)
    try:
        with _MCRcon(host, RCON_PASSWORD, port=RCON_PORT) as mcr:
            response = mcr.command("list")
        match = re.search(r"(\d+).*?of.*?(\d+)", response)
        if not match:
            return None
        count_str = f"{match.group(1)}/{match.group(2)}"
        parts = response.split(":", 1)
        names = [n.strip() for n in parts[1].split(",") if n.strip()] if len(parts) > 1 else []
        return count_str, names
    except Exception:
        return None
    finally:
        socket.setdefaulttimeout(prev)


def _fmt_uptime(ts: str) -> str:
    try:
        start = datetime.fromisoformat(ts)
        delta = datetime.now(timezone.utc) - start.astimezone(timezone.utc)
        total_minutes = max(0, int(delta.total_seconds() // 60))
        h, m = divmod(total_minutes, 60)
        return f"{h}h {m:02d}m" if h else f"{m}m"
    except Exception:
        return "—"


async def wait_for_minecraft(hosts: list[str], timeout: int = 420) -> bool:
    loop = asyncio.get_running_loop()
    deadline = loop.time() + timeout
    while loop.time() < deadline:
        results = await asyncio.gather(
            *[asyncio.to_thread(_try_rcon, h) for h in hosts],
            return_exceptions=True,
        )
        if any(r is None for r in results):
            return True
        if any(isinstance(r, mcrcon.MCRconException) and "authentication" in str(r).lower() for r in results):
            logger.error("RCON auth failed — check RCON_PASSWORD")
            return False
        logger.warning(f"Minecraft not ready ({[(type(r).__name__, str(r)) for r in results if isinstance(r, Exception)]}), retrying in 10s...")
        remaining = deadline - loop.time()
        if remaining <= 0:
            break
        await asyncio.sleep(min(10, remaining))
    return False


_idle_empty_minutes = 0
_idle_last_vm_status: str | None = None
_idle_warned_minutes: set[int] = set()
_health_consecutive_failures: int = 0


@tasks.loop(minutes=1)
async def idle_watcher():
    global _idle_empty_minutes, _idle_last_vm_status, _idle_warned_minutes

    if not NOTIFY_CHANNEL_ID:
        return
    try:
        channel = await bot.fetch_channel(NOTIFY_CHANNEL_ID)
    except Exception as e:
        logger.error(f"idle_watcher: cannot fetch channel {NOTIFY_CHANNEL_ID}: {e}")
        return

    try:
        instance = await asyncio.to_thread(get_instance)
        status = instance.status
    except Exception as e:
        logger.warning(f"idle_watcher: failed to get instance: {e}")
        return

    if _idle_last_vm_status == "RUNNING" and status in ("STOPPED", "TERMINATED"):
        _idle_empty_minutes = 0
        _idle_warned_minutes.clear()
        logger.warning(f"idle_watcher: VM transitioned RUNNING → {status}")
        await channel.send("💤 Minecraft server is offline.")
        await bot.change_presence(status=discord.Status.idle, activity=discord.Game("⚫ MC offline"))
        if isinstance(channel, discord.TextChannel):
            try:
                await channel.edit(topic="⚫ MC offline")
            except discord.Forbidden:
                logger.warning("idle_watcher: missing manage_channels permission, skipping topic clear")

    if _idle_last_vm_status != "RUNNING" and status == "RUNNING":
        _idle_empty_minutes = 0
        _idle_warned_minutes.clear()
        logger.info("idle_watcher: VM became RUNNING — resetting idle counters")

    _idle_last_vm_status = status

    if status != "RUNNING":
        return

    try:
        external_ip = instance.network_interfaces[0].access_configs[0].nat_i_p
    except (IndexError, AttributeError):
        return

    players_str = await asyncio.to_thread(_get_player_count, external_ip)
    uptime = _fmt_uptime(instance.last_start_timestamp or "")
    count_display = players_str if players_str is not None else "?/?"
    await bot.change_presence(status=discord.Status.online, activity=discord.Game(f"🟢 MC | {uptime} | {count_display}"))
    if players_str is None:
        return

    current = int(players_str.split("/")[0])

    if current > 0:
        _idle_empty_minutes = 0
        _idle_warned_minutes.clear()
    else:
        _idle_empty_minutes += 1
        logger.info(f"idle_watcher: empty for {_idle_empty_minutes} min")

        if _idle_empty_minutes >= 30 and 30 not in _idle_warned_minutes:
            _idle_warned_minutes.add(30)
            await channel.send("🔴 Server empty for 30 minutes — shutting down now.")
        elif _idle_empty_minutes >= 25 and 25 not in _idle_warned_minutes:
            _idle_warned_minutes.add(25)
            await channel.send("⚠️ Server empty for 25 minutes — closing in ~5 minutes.")
            try:
                await asyncio.to_thread(_rcon_say, external_ip, "Server auto-shutting down in ~5 minutes, find shelter!")
                logger.info("idle_watcher: RCON 25-min warning sent")
            except Exception as e:
                logger.warning(f"idle_watcher: RCON warning skipped: {e}")
        elif _idle_empty_minutes >= 20 and 20 not in _idle_warned_minutes:
            _idle_warned_minutes.add(20)
            await channel.send("⚠️ Server empty for 20 minutes — shutting down in 10 minutes if no one joins.")
        elif _idle_empty_minutes >= 15 and 15 not in _idle_warned_minutes:
            _idle_warned_minutes.add(15)
            await channel.send("⚠️ Server empty for 15 minutes — shutting down in 15 minutes if no one joins.")


@idle_watcher.before_loop
async def before_idle_watcher():
    await bot.wait_until_ready()


@idle_watcher.error
async def idle_watcher_error(error):
    logger.error(f"idle_watcher crashed: {error}")


@tasks.loop(minutes=5)
async def health_checker():
    global _health_consecutive_failures
    if _idle_last_vm_status != "RUNNING":
        _health_consecutive_failures = 0
        return
    if not NOTIFY_CHANNEL_ID:
        return
    try:
        instance = await asyncio.to_thread(get_instance)
        external_ip = instance.network_interfaces[0].access_configs[0].nat_i_p
    except Exception as e:
        logger.warning(f"health_checker: failed to get instance: {e}")
        return
    try:
        await asyncio.to_thread(_try_rcon, external_ip)
        _health_consecutive_failures = 0
    except Exception:
        _health_consecutive_failures += 1
        logger.warning(f"health_checker: RCON unreachable ({_health_consecutive_failures} consecutive)")
        if _health_consecutive_failures == 3:
            try:
                channel = await bot.fetch_channel(NOTIFY_CHANNEL_ID)
                await channel.send("🚨 Minecraft RCON unreachable for 15 minutes — server may have crashed.")
            except Exception as e:
                logger.error(f"health_checker: cannot send alert: {e}")


@health_checker.before_loop
async def before_health_checker():
    await bot.wait_until_ready()


@health_checker.error
async def health_checker_error(error):
    logger.error(f"health_checker crashed: {error}")


@bot.event
async def on_ready():
    if DEV_GUILD_ID:
        guild = discord.Object(id=int(DEV_GUILD_ID))
        bot.tree.copy_global_to(guild=guild)
        await bot.tree.sync(guild=guild)
        # clear global commands so they don't duplicate guild commands
        bot.tree.clear_commands(guild=None)
        await bot.tree.sync()
    else:
        await bot.tree.sync()
    if not idle_watcher.is_running():
        idle_watcher.start()
    if not health_checker.is_running():
        health_checker.start()
    await bot.change_presence(status=discord.Status.idle, activity=discord.Game("⚫ MC offline"))
    logger.info(f"Logged in as {bot.user}")


@bot.tree.command(name="mc-start", description="Start Minecraft VM")
@discord.app_commands.describe(reason="Why are you starting the server?")
@is_whitelisted()
async def mc_start(interaction, reason: str | None = None):
    logger.info(f"mc-start invoked by {interaction.user}")
    await interaction.response.send_message("🟡 Starting Minecraft server...")

    client = compute_v1.InstancesClient()

    try:
        operation = await asyncio.to_thread(
            client.start,
            project=PROJECT_ID,
            zone=ZONE,
            instance=INSTANCE_NAME,
        )
        logger.debug("Waiting for VM to start...")
        await asyncio.to_thread(operation.result)
    except Exception as e:
        logger.error(f"mc-start: GCP error: {e}")
        await interaction.followup.send(f"❌ Failed to start VM: {e}")
        return

    logger.info("VM started, waiting for Minecraft to initialize...")
    await interaction.followup.send("🟢 VM started. Waiting for Minecraft to initialize...")

    try:
        instance = await asyncio.to_thread(get_instance)
        external_ip = instance.network_interfaces[0].access_configs[0].nat_i_p
    except Exception as e:
        logger.error(f"mc-start: failed to get instance IP: {e}")
        await interaction.followup.send(f"❌ Failed to get VM info: {e}")
        return

    ready = await wait_for_minecraft([external_ip])
    if ready:
        logger.info("Minecraft server ready")
        players_str = await asyncio.to_thread(_get_player_count, external_ip)
        embed = discord.Embed(colour=0x00b300, title="✅ Minecraft server is ready!")
        embed.set_author(name=interaction.user.display_name, icon_url=interaction.user.display_avatar.url)
        embed.add_field(name="IP", value=external_ip, inline=True)
        embed.add_field(name="Players", value=f"{players_str} players" if players_str else "? players", inline=True)
        if reason:
            embed.add_field(name="Reason", value=reason[:1024], inline=False)
        await interaction.followup.send(interaction.user.mention, embed=embed)
        await bot.change_presence(status=discord.Status.online, activity=discord.Game("🟢 MC online"))
        if NOTIFY_CHANNEL_ID:
            channel = bot.get_channel(NOTIFY_CHANNEL_ID)
            if isinstance(channel, discord.TextChannel):
                try:
                    await channel.edit(topic=f"🟢 MC online — {external_ip}")
                except discord.Forbidden:
                    logger.warning("mc-start: missing manage_channels permission, skipping topic update")
    else:
        logger.warning("Minecraft did not initialize within timeout")
        await interaction.followup.send("⚠️ VM running but Minecraft didn't start in time. Check server logs.")


@bot.tree.command(name="mc-status", description="Check server status")
@is_whitelisted()
async def mc_status(interaction):
    logger.info(f"mc-status invoked by {interaction.user}")
    await interaction.response.defer()

    try:
        instance = await asyncio.to_thread(get_instance)
    except Exception as e:
        logger.error(f"mc-status: GCP error: {e}")
        await interaction.followup.send(f"❌ Failed to get VM status: {e}")
        return

    status = instance.status
    logger.debug(f"VM status: {status}")

    W = 26
    top = "╔" + "═" * 30 + "╗"
    bottom = "╚" + "═" * 30 + "╝"

    def line(content: str) -> str:
        return f"║  {content:<{W}}  ║"

    if status == "RUNNING":
        try:
            external_ip = instance.network_interfaces[0].access_configs[0].nat_i_p
        except (IndexError, AttributeError):
            external_ip = None

        result = await asyncio.to_thread(_get_players, external_ip) if external_ip else None
        count_str, names = result if result else ("—", [])
        uptime = _fmt_uptime(instance.last_start_timestamp or "")

        rows = [
            top,
            line("MC SERVER — ONLINE"),
            line(f"Uptime : {uptime}"),
            line(f"Players: {count_str}"),
        ]
        for name in names:
            rows.append(line(f"  • {name}"))
        rows.append(bottom)
        status_icon = "🟢"
    else:
        rows = [top, line("MC SERVER — OFFLINE"), bottom]
        status_icon = "🔴"

    panel = "\n".join(rows)
    await interaction.followup.send(f"{status_icon}\n```\n{panel}\n```")


@bot.tree.command(name="mc-stop", description="Stop Minecraft VM")
@is_whitelisted()
async def mc_stop(interaction):
    logger.info(f"mc-stop invoked by {interaction.user}")
    await interaction.response.send_message("⚠️ Sending shutdown warning... stopping in 60 seconds.")

    try:
        instance = await asyncio.to_thread(get_instance)
        external_ip = instance.network_interfaces[0].access_configs[0].nat_i_p
        await asyncio.to_thread(_rcon_say, external_ip, "Server shutting down in 60 seconds, find shelter!")
        logger.info("mc-stop: RCON shutdown warning sent")
    except Exception as e:
        logger.warning(f"mc-stop: RCON warning skipped: {e}")

    await asyncio.sleep(60)

    client = compute_v1.InstancesClient()
    try:
        await asyncio.to_thread(
            client.stop,
            project=PROJECT_ID,
            zone=ZONE,
            instance=INSTANCE_NAME,
        )
    except Exception as e:
        logger.error(f"mc-stop: GCP error: {e}")
        await interaction.followup.send(f"❌ Failed to stop VM: {e}")
        return

    logger.info("VM stop requested")
    await interaction.followup.send("✅ VM stop requested.")
    await bot.change_presence(status=discord.Status.idle, activity=discord.Game("⚫ MC offline"))


@bot.tree.command(name="mc-allow", description="Allow a user to use MC commands")
@is_owner()
async def mc_allow(interaction, user: discord.Member):
    whitelist.add(user.id)
    save_whitelist(whitelist)
    logger.info(f"{interaction.user} granted access to {user}")
    await interaction.response.send_message(f"✅ {user.mention} can now use MC commands.", ephemeral=True)


@bot.tree.command(name="mc-remove", description="Remove a user's access to MC commands")
@is_owner()
async def mc_remove(interaction, user: discord.Member):
    whitelist.discard(user.id)
    save_whitelist(whitelist)
    logger.info(f"{interaction.user} revoked access from {user}")
    await interaction.response.send_message(f"✅ {user.mention}'s access has been removed.", ephemeral=True)


bot.run(TOKEN)