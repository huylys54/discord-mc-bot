import os
import json
import socket
import asyncio
import discord
import mcrcon
from discord.ext import commands
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


def _try_rcon(host: str) -> None:
    prev = socket.getdefaulttimeout()
    socket.setdefaulttimeout(10)
    try:
        with mcrcon.MCRcon(host, RCON_PASSWORD, port=RCON_PORT, timeout=0) as mcr:
            mcr.command("list")
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
        await interaction.followup.send("✅ Minecraft server is ready! Connect now.")
    else:
        logger.warning("Minecraft did not initialize within timeout")
        await interaction.followup.send("⚠️ VM running but Minecraft didn't start in time. Check server logs.")


@bot.tree.command(name="mc-status", description="Check server status")
@is_whitelisted()
async def mc_status(interaction):
    logger.info(f"mc-status invoked by {interaction.user}")
    instance = get_instance()
    logger.debug(f"VM status: {instance.status}")
    await interaction.response.send_message(
        f"VM Status: **{instance.status}**"
    )


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