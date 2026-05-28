import os
import re
import json
import socket
import asyncio
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
_idle_warned_25 = False
_idle_warned_30 = False


@tasks.loop(minutes=1)
async def idle_watcher():
    global _idle_empty_minutes, _idle_last_vm_status, _idle_warned_25, _idle_warned_30

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
        _idle_warned_25 = False
        _idle_warned_30 = False
        await channel.send("💤 Minecraft server is offline.")

    _idle_last_vm_status = status

    if status != "RUNNING":
        return

    try:
        external_ip = instance.network_interfaces[0].access_configs[0].nat_i_p
    except (IndexError, AttributeError):
        return

    players_str = await asyncio.to_thread(_get_player_count, external_ip)
    if players_str is None:
        return

    current = int(players_str.split("/")[0])

    if current > 0:
        _idle_empty_minutes = 0
        _idle_warned_25 = False
        _idle_warned_30 = False
    else:
        _idle_empty_minutes += 1
        logger.info(f"idle_watcher: empty for {_idle_empty_minutes} min")

        if _idle_empty_minutes >= 30 and not _idle_warned_30:
            _idle_warned_30 = True
            await channel.send("🔴 Server empty for 30 minutes — shutting down now.")
        elif _idle_empty_minutes >= 25 and not _idle_warned_25:
            _idle_warned_25 = True
            await channel.send("⚠️ Server empty for 25 minutes — closing in ~5 minutes.")


@idle_watcher.before_loop
async def before_idle_watcher():
    await bot.wait_until_ready()


@idle_watcher.error
async def idle_watcher_error(error):
    logger.error(f"idle_watcher crashed: {error}")


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
    logger.info(f"Logged in as {bot.user}")


@bot.tree.command(name="mc-start", description="Start Minecraft VM")
@is_whitelisted()
async def mc_start(interaction):
    logger.info(f"mc-start invoked by {interaction.user}")
    await interaction.response.send_message(
        "🟡 Starting Minecraft server..."
    )

    client = compute_v1.InstancesClient()

    operation = await asyncio.to_thread(
        client.start,
        project=PROJECT_ID,
        zone=ZONE,
        instance=INSTANCE_NAME,
    )

    logger.debug("Waiting for VM to start...")
    await asyncio.to_thread(operation.result)

    logger.info("VM started, waiting for Minecraft to initialize...")
    await interaction.followup.send("🟢 VM started. Waiting for Minecraft to initialize...")

    instance = await asyncio.to_thread(get_instance)
    external_ip = instance.network_interfaces[0].access_configs[0].nat_i_p

    ready = await wait_for_minecraft([external_ip])
    if ready:
        logger.info("Minecraft server ready")
        await interaction.followup.send(f"✅ {interaction.user.mention} Minecraft server is ready! Connect now.")
    else:
        logger.warning("Minecraft did not initialize within timeout")
        await interaction.followup.send("⚠️ VM running but Minecraft didn't start in time. Check server logs.")


@bot.tree.command(name="mc-status", description="Check server status")
@is_whitelisted()
async def mc_status(interaction):
    logger.info(f"mc-status invoked by {interaction.user}")
    await interaction.response.defer()
    instance = await asyncio.to_thread(get_instance)
    status = instance.status
    logger.debug(f"VM status: {status}")

    if status == "RUNNING":
        external_ip = instance.network_interfaces[0].access_configs[0].nat_i_p
        players = await asyncio.to_thread(_get_player_count, external_ip)
        player_info = f" — {players} players" if players else ""
        await interaction.followup.send(f"🟢 **{status}**{player_info}")
    else:
        await interaction.followup.send(f"🔴 **{status}**")


@bot.tree.command(name="mc-stop", description="Stop Minecraft VM")
@is_whitelisted()
async def mc_stop(interaction):
    logger.info(f"mc-stop invoked by {interaction.user}")
    await interaction.response.send_message(
        "🔴 Stopping Minecraft VM..."
    )

    client = compute_v1.InstancesClient()

    client.stop(
        project=PROJECT_ID,
        zone=ZONE,
        instance=INSTANCE_NAME
    )

    logger.info("VM stop requested")
    await interaction.followup.send(
        "✅ VM stopped"
    )


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