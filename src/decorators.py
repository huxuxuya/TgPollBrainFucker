from functools import wraps
from telegram import Update
from telegram.ext import ContextTypes

from src.config import BOT_OWNER_ID, logger

def admin_only(func):
    """Decorator to restrict access to the bot owner."""
    @wraps(func)
    async def wrapped(update: Update, context: ContextTypes.DEFAULT_TYPE, *args, **kwargs):
        user_id = update.effective_user.id
        if user_id != BOT_OWNER_ID:
            logger.warning(f"Unauthorized access denied for {user_id}.")
            # Optionally, send a message to the user.
            # await update.message.reply_text("You are not authorized to use this command.")
            return
        return await func(update, context, *args, **kwargs)
    return wrapped 