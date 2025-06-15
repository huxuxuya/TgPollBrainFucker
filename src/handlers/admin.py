from telegram import Update
from telegram.ext import ContextTypes
from telegram.constants import ChatAction
import os
from datetime import datetime

from src.config import DATABASE_PATH
from src.decorators import admin_only

@admin_only
async def backup(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Sends the database file to the user."""
    await update.message.reply_chat_action(ChatAction.UPLOAD_DOCUMENT)
    try:
        with open(DATABASE_PATH, 'rb') as f:
            await update.message.reply_document(
                document=f,
                filename=f"poll_db_backup_{datetime.now().strftime('%Y%m%d_%H%M%S')}.db",
                caption="Here's your database backup."
            )
    except FileNotFoundError:
        await update.message.reply_text("Database file not found.")
    except Exception as e:
        await update.message.reply_text(f"An error occurred: {e}")

@admin_only
async def restore(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Restores the database from a file."""
    if not update.message.reply_to_message or not update.message.reply_to_message.document:
        await update.message.reply_text("Please reply to a message with a database file to restore.")
        return
        
    document = update.message.reply_to_message.document
    if not document.file_name.endswith('.db'):
        await update.message.reply_text("Please provide a valid .db file.")
        return

    try:
        db_file = await document.get_file()
        await db_file.download_to_drive(DATABASE_PATH)
        await update.message.reply_text("Database restored successfully. Please restart the bot for changes to take effect.")
    except Exception as e:
        await update.message.reply_text(f"An error occurred during restore: {e}") 