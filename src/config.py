import logging
import os
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()

# Get bot token from environment variable
try:
    BOT_TOKEN = os.environ['BOT_TOKEN']
except KeyError:
    raise RuntimeError('Environment variable BOT_TOKEN is not set!')

# Get bot owner ID from environment variable. It's better to set it here.
# The previous logic of setting it on the first use of /backup is fragile.
BOT_OWNER_ID = int(os.environ.get('BOT_OWNER_ID', 0))

# Development mode switch. Set to "true" or "1" for local polling.
DEV_MODE = os.environ.get('DEV_MODE', 'false').lower() in ('true', '1')

# URL for the web app, required for webhook setup
WEB_URL = os.environ.get('WEB_URL')
if not DEV_MODE and not WEB_URL:
    raise RuntimeError('Environment variable WEB_URL is not set while not in DEV_MODE!')

DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///poll_data.db")
DATABASE_PATH = DATABASE_URL.split("///")[-1] if DATABASE_URL.startswith("sqlite:///") else "poll_data.db"

# Enable logging
logging.basicConfig(format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO)
logger = logging.getLogger(__name__) 