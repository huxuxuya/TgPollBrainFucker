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
    user = update.effective_user
    chat = update.effective_chat

    if user and chat:
        # We need to handle both private and group chats
        if chat.type in ['group', 'supergroup']:
            db.update_known_chats(chat.id, chat.title)
            db.add_user_to_participants(chat.id, user.id, user.username, user.first_name, user.last_name)
            me = await context.bot.get_me()
            await update.message.reply_text(f"Привет! Для управления опросами, напишите мне в личном чате: @{me.username}")
            await update.message.reply_text(f"Список участников для группы *{escape_markdown(db.get_group_title(chat.id))}*:\n")
        else: # private chat
            await dashboard.private_chat_entry_point(update, context)


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

async def log_all_updates(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if context.bot_data.get('debug_mode_enabled', False):
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