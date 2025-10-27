import discord
from discord.ext import commands
from discord import app_commands
import os
from dotenv import load_dotenv
from database.schema import Database

# Load environment variables with explicit path
import pathlib
env_path = pathlib.Path(__file__).parent / '.env'
load_dotenv(dotenv_path=env_path)

# Bot configuration (validate required environment variables)
def _get_env_str(name: str) -> str:
    val = os.getenv(name)
    if not val:
        raise RuntimeError(f"Missing required environment variable: {name}")
    return val

def _get_env_int(name: str) -> int:
    raw = os.getenv(name)
    if not raw:
        raise RuntimeError(f"Missing required environment variable: {name}")
    try:
        return int(raw)
    except ValueError:
        raise RuntimeError(f"Environment variable {name} must be an integer (got: {raw!r})")

try:
    TOKEN = _get_env_str('DISCORD_TOKEN')
    GUILD_ID = _get_env_int('GUILD_ID')
    LOG_CHANNEL = _get_env_int('LOG_CHANNEL_ID')
    REPORT_CHANNEL = _get_env_int('REPORT_CHANNEL_ID')
except RuntimeError as e:
    # Print a clear error and exit early to avoid confusing tracebacks
    print(f"[ERROR] {e}")
    raise SystemExit(1)

# Optional multi-channel support
def _parse_int_list(env_value: str) -> set[int]:
    vals = set()
    for part in env_value.split(','):
        part = part.strip()
        if not part:
            continue
        try:
            vals.add(int(part))
        except ValueError:
            print(f"[WARN] Skipping invalid channel id in ALLOWED_CHANNEL_IDS: {part!r}")
    return vals

ALLOWED_CHANNEL_IDS: set[int] | None = None
raw_allowed = os.getenv('ALLOWED_CHANNEL_IDS')
if raw_allowed:
    parsed = _parse_int_list(raw_allowed)
    ALLOWED_CHANNEL_IDS = parsed if parsed else None
else:
    # Legacy single-channel env var support (optional)
    raw_legacy = os.getenv('YAP_CHANNEL_ID')
    if raw_legacy:
        try:
            ALLOWED_CHANNEL_IDS = {int(raw_legacy)}
        except ValueError:
            print(f"[WARN] Invalid YAP_CHANNEL_ID: {raw_legacy!r}")

# Configure intents
intents = discord.Intents.default()
intents.message_content = True  # Required to read message content
intents.members = True  # Required for member tracking
intents.reactions = True  # Required for reaction tracking

class EngagementBot(commands.Bot):
    def __init__(self):
        super().__init__(
            command_prefix="!",  # Prefix for text commands (backup)
            intents=intents,
            application_id=None  # Bot application ID
        )
        self.db = Database()
        # Store allowed channels (None means all channels allowed)
        self.allowed_channel_ids = ALLOWED_CHANNEL_IDS
        self.log_channel_id = LOG_CHANNEL
        self.report_channel_id = REPORT_CHANNEL
    async def setup_hook(self):
        """Called when bot is starting up"""
        # Connect to database
        await self.db.connect()
        print("✓ Database connected")

        # Load runtime config overrides from DB (if any)
        try:
            cfg_allowed = await self.db.get_allowed_channel_ids()
            if cfg_allowed is not None:
                self.allowed_channel_ids = cfg_allowed
                print(f"✓ Allowed channels loaded from DB: {sorted(self.allowed_channel_ids)}")
            cfg_log = await self.db.get_config_int('log_channel_id')
            if cfg_log:
                self.log_channel_id = cfg_log
                print(f"✓ Log channel loaded from DB: {self.log_channel_id}")
            cfg_report = await self.db.get_config_int('report_channel_id')
            if cfg_report:
                self.report_channel_id = cfg_report
                print(f"✓ Report channel loaded from DB: {self.report_channel_id}")
        except Exception as e:
            print(f"[WARN] Failed to load config from DB: {e}")

        # Load command cogs
        await self.load_extension('commands.engagement')
        await self.load_extension('commands.admin')
        await self.load_extension('events.message_handler')
        print("✓ Extensions loaded")

        # Sync slash commands to guild
        guild = discord.Object(id=GUILD_ID)
        self.tree.copy_global_to(guild=guild)
        await self.tree.sync(guild=guild)
        print(f"✓ Commands synced to guild {GUILD_ID}")

    async def on_ready(self):
        """Called when bot successfully connects to Discord"""
        print(f'✓ Logged in as {self.user.name} (ID: {self.user.id})')
        print(f'✓ Connected to {len(self.guilds)} guild(s)')

        # Set bot status
        await self.change_presence(
            activity=discord.Activity(
                type=discord.ActivityType.watching,
                name="creator engagement 👀"
            )
        )
        print('✓ Bot is ready!')


# Create and run bot instance
bot = EngagementBot()

if __name__ == "__main__":
    bot.run(TOKEN)
