from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, User
from telegram.ext import ContextTypes
from telegram.constants import ParseMode
from telegram.error import BadRequest, RetryAfter
import asyncio

from src import database as db
from src.config import logger
from src.display import generate_poll_text # Or a smaller update function

async def update_poll_message(poll_id: int, context: ContextTypes.DEFAULT_TYPE):
    """Refreshes the poll message after a vote."""
    # This is a simplified version of the update logic.
    # A full implementation would handle errors and chat migrations.
    try:
        poll = db.get_poll(poll_id)
        if not poll or not poll.message_id: return

        text = generate_poll_text(poll_id)
        options = poll.options.split(',')
        keyboard = [[InlineKeyboardButton(opt.strip(), callback_data=f'vote:{poll_id}:{i}')] for i, opt in enumerate(options)]
        
        await context.bot.edit_message_text(
            text=text,
            chat_id=poll.chat_id,
            message_id=poll.message_id,
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode='MarkdownV2'
        )
    except Exception as e:
        if "Message is not modified" not in str(e):
             logger.error(f"Failed to edit message for poll {poll_id}: {e}")


async def process_vote(
    query: Update.callback_query,
    context: ContextTypes.DEFAULT_TYPE,
    poll_id: int,
    option_index: int,
    user: User
) -> None:
    """Core logic to process a user's vote."""
    logger.info(f"Processing vote for poll {poll_id}, option {option_index} by user {user.id}")
    
    poll = db.get_poll(poll_id)
    if not poll or poll.status != 'active':
        await query.answer("Этот опрос больше не активен.", show_alert=True)
        return

    db.add_or_update_response(
        poll_id=poll_id,
        user_id=user.id,
        first_name=user.first_name,
        last_name=user.last_name,
        username=user.username,
        option_index=option_index
    )
    
    # We answer the callback query as a background task to avoid blocking.
    asyncio.create_task(query.answer())
    
    # Try to update the poll message with new results
    try:
        new_text = generate_poll_text(poll_id)
        if query.message.text != new_text:
            await query.edit_message_text(new_text, reply_markup=query.message.reply_markup, parse_mode=ParseMode.MARKDOWN_V2)
        await query.answer("Спасибо, ваш голос учтён!")
    except RetryAfter as e:
        logger.warning(f"Flood control exceeded for poll {poll_id}. Vote was counted, but message not updated. Retry in {e.retry_after}s.")
        await query.answer("Ваш голос учтён! (Сообщение обновится позже из-за лимитов)")
    except BadRequest as e:
        if "Message is not modified" in str(e):
            await query.answer("Спасибо, ваш голос учтён (сообщение не изменилось).")
        else:
            logger.error(f"Failed to edit message for poll {poll_id}: {e}")
            await query.answer("Произошла ошибка при обновлении опроса.")
    except Exception as e:
        logger.error(f"An unexpected error occurred while updating poll message {poll_id}: {e}")
        await query.answer("Произошла ошибка.")

async def legacy_vote_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handles the old vote callback format (e.g., 'poll_22_1')."""
    query = update.callback_query
    logger.info(f"Handling legacy vote callback: {query.data}")
    
    try:
        parts = query.data.split('_')
        poll_id = int(parts[1])
        option_index = int(parts[2])
        user = update.effective_user
        
        await process_vote(query, context, poll_id, option_index, user)
    except (IndexError, ValueError) as e:
        logger.error(f"Error parsing legacy_vote_handler data '{query.data}': {e}")
        await query.answer("Ошибка: не удалось обработать старый формат голосования.", show_alert=True)


async def vote_callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handles a vote button press by parsing new format and calling the core processor."""
    query = update.callback_query
    try:
        parts = query.data.split(':')
        poll_id = int(parts[1])
        option_index = int(parts[2])
        user = update.effective_user
        
        await process_vote(query, context, poll_id, option_index, user)
    except (IndexError, ValueError) as e:
        logger.error(f"Error parsing vote_callback_handler data '{query.data}': {e}")
        await query.answer("Ошибка: неверный формат данных для голосования.", show_alert=True) 