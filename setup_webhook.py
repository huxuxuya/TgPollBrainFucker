import asyncio
import os
from telegram import Bot
from src.config import BOT_TOKEN, logger

# Set your Vercel deployment URL in your environment variables
VERCEL_URL = os.getenv("VERCEL_URL")

async def main():
    """A simple script to set the Telegram webhook to the Vercel URL."""
    if not VERCEL_URL:
        logger.error("Please set the VERCEL_URL environment variable before running this script.")
        logger.error("Example: VERCEL_URL=https://your-app-name.vercel.app python setup_webhook.py")
        return

    bot = Bot(token=BOT_TOKEN)
    webhook_url = f"{VERCEL_URL.rstrip('/')}/telegram"
    
    try:
        logger.info(f"Setting webhook to: {webhook_url}")
        if await bot.set_webhook(url=webhook_url):
            logger.info("Webhook set successfully.")
            webhook_info = await bot.get_webhook_info()
            logger.info(f"Current webhook info: {webhook_info}")
        else:
            logger.error("Webhook setting failed.")
    except Exception as e:
        logger.error(f"An error occurred: {e}")

if __name__ == "__main__":
    asyncio.run(main())
