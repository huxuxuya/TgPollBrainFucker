import logging
import os
from dotenv import load_dotenv

# --- Helper to check if we are in a pytest run ---
IS_TESTING = 'PYTEST_CURRENT_TEST' in os.environ

# Enable logging
logging.basicConfig(format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO)
logger = logging.getLogger(__name__)

# Load environment variables from .env file
load_dotenv()

# Get bot token from environment variable
BOT_TOKEN = os.environ.get('BOT_TOKEN')
if not BOT_TOKEN and not IS_TESTING:
    logger.warning('Environment variable BOT_TOKEN is not set!')

# Get bot owner ID from environment variable. It's better to set it here.
# The previous logic of setting it on the first use of /backup is fragile.
BOT_OWNER_ID_STR = os.environ.get('BOT_OWNER_ID', '0')
try:
    BOT_OWNER_ID = int(BOT_OWNER_ID_STR)
except ValueError:
    BOT_OWNER_ID = 0
    if BOT_OWNER_ID_STR != '0' and BOT_OWNER_ID_STR != 'your_telegram_user_id_here':
        logger.warning(f'Invalid BOT_OWNER_ID: {BOT_OWNER_ID_STR}, using 0')

# Development mode switch. Set to "true" or "1" for local polling.
DEV_MODE = os.environ.get('DEV_MODE', 'false').lower() in ('true', '1')

# URL for the web app, required for webhook setup
WEB_URL = os.environ.get('WEB_URL')
if not DEV_MODE and not WEB_URL and not IS_TESTING:
    logger.warning('Environment variable WEB_URL is not set while not in DEV_MODE!')

DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///poll_data.db") 