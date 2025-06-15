from telegram import Update
from telegram.ext import ContextTypes
from telegram.error import ChatMigrated
import logging
from functools import wraps
from telegram.helpers import escape_markdown

from src import database as db
from src.config import BOT_OWNER_ID, logger
from src.handlers import dashboard
from src.decorators import admin_only

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Sends a welcome message and the chat selection keyboard."""
    if update.effective_chat.type == 'private':
        await dashboard.private_chat_entry_point(update, context)
    else:
        # If /start is used in a group, just give a brief intro.
        await update.message.reply_text("Я — бот для опросов. Используйте меня в личном чате для управления.")

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    help_text = (
        "Этот бот помогает создавать опросы и управлять ими в группах.\n\n"
        "Основные команды:\n"
        "/start - Начать работу с ботом и открыть панель управления.\n"
        "/help - Показать это сообщение.\n\n"
        "Все управление происходит через кнопки в этом чате."
    )
    await update.message.reply_text(help_text)

@admin_only
async def toggle_debug(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Toggles verbose update logging on and off."""
    debug_enabled = not context.bot_data.get('debug_mode_enabled', False)
    context.bot_data['debug_mode_enabled'] = debug_enabled
    
    if debug_enabled:
        await update.message.reply_text("Подробное логирование всех событий ВКЛЮЧЕНО.")
    else:
        await update.message.reply_text("Подробное логирование всех событий ВЫКЛЮЧЕНО.")

async def track_chats(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Tracks every chat the bot is in. Called by the TypeHandler."""
    if update.effective_chat:
        # This will add the chat to the DB if it's not there, or update its title if it changed.
        db.update_known_chats(
            chat_id=update.effective_chat.id, 
            title=update.effective_chat.title or "Unknown Title", 
            chat_type=update.effective_chat.type
        )

async def log_all_updates(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Logs every update received by the bot for debugging purposes."""
    if context.bot_data.get('debug_mode', False):
        logger.info(f"[DEBUG_UPDATE]: {update.to_dict()}")

async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    logger.error("Exception while handling an update:", exc_info=context.error)
    if isinstance(context.error, ChatMigrated):
        old_chat_id = context.error.chat_id
        new_chat_id = context.error.new_chat_id
        logger.warning(f"Chat migrated from {old_chat_id} to {new_chat_id}")
        # Here you would ideally have a function to update the chat_id in all relevant tables
        # For now, we'll just log it. A proper migration would be more involved.

async def unrecognized_button(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    logger.warning(f"Unrecognized callback_data received: '{query.data}'")
    await query.answer("Хм, я не распознал эту кнопку. Возможно, она от старого сообщения.", show_alert=True) 