from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, User, WebAppInfo, InputMediaPhoto
from telegram.ext import ContextTypes
from telegram.constants import ParseMode
from telegram.error import BadRequest, RetryAfter
import asyncio
import telegram

from src import database as db
from src.config import logger, WEB_URL
from src.display import generate_poll_content

async def update_poll_message(poll_id: int, context: ContextTypes.DEFAULT_TYPE):
    """Refreshes the poll message after a vote, handling both native and webapp polls."""
    # This is a simplified version of the update logic.
    # A full implementation would handle errors and chat migrations.
    try:
        poll = db.get_poll(poll_id)
        if not poll or not poll.message_id: return

        text = generate_poll_content(poll_id)
        
        kb = []
        if poll.poll_type == 'native':
            options = poll.options.split(',')
            kb = [[InlineKeyboardButton(opt.strip(), callback_data=f'vote:{poll_id}:{i}')] for i, opt in enumerate(options)]
        elif poll.poll_type == 'webapp':
            if not poll.web_app_id:
                logger.error(f"Cannot update webapp poll {poll_id}, web_app_id is missing.")
                return
            url = f"{WEB_URL}/web_apps/{poll.web_app_id}/?poll_id={poll.poll_id}"
            kb = [[InlineKeyboardButton("⚜️ Голосовать в приложении", web_app=WebAppInfo(url=url))]]

        await context.bot.edit_message_text(
            text=text,
            chat_id=poll.chat_id,
            message_id=poll.message_id,
            reply_markup=InlineKeyboardMarkup(kb),
            parse_mode=ParseMode.MARKDOWN_V2
        )
    except Exception as e:
        if "Message is not modified" not in str(e):
             logger.error(f"Failed to edit message for poll {poll_id}: {e}", exc_info=True)


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
        new_text = generate_poll_content(poll_id)
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
    """Handles a user's vote on a poll and updates the poll message."""
    query = update.callback_query
    
    # Extract data from the callback
    try:
        _, poll_id_str, option_index_str = query.data.split(':')
        poll_id = int(poll_id_str)
        option_index = int(option_index_str)
    except (ValueError, IndexError):
        logger.error(f"Invalid vote callback data received: {query.data}")
        await query.answer("Ошибка: неверные данные для голосования.", show_alert=True)
        return

    user_id = query.from_user.id
    user_name = query.from_user.full_name
    
    session = db.SessionLocal()
    try:
        poll = session.query(db.Poll).filter_by(poll_id=poll_id).first()
        if not poll or poll.status != 'active':
            await query.answer("Этот опрос больше не активен.", show_alert=True)
            return

        # Register vote
        options = poll.options.split(',')
        if not (0 <= option_index < len(options)):
            await query.answer("Ошибка: выбранный вариант ответа недействителен.", show_alert=True)
            return
            
        selected_option = options[option_index].strip()
        has_voted, new_vote = db.add_or_update_response(poll_id, user_id, user_name, selected_option, poll.allow_multiple, session)
        session.commit() # Commit the vote registration
        
        await query.answer(f"Ваш голос за «{selected_option}» засчитан!")
        
        # After voting, update the poll message
        new_caption, new_image = generate_poll_content(poll=poll, session=session)

        # Re-generate keyboard as it might have changed
        options = poll.options.split(',')
        kb = [[InlineKeyboardButton(opt.strip(), callback_data=f'vote:{poll_id}:{i}')] for i, opt in enumerate(options)]
        reply_markup = InlineKeyboardMarkup(kb)

        try:
            # If we have a new image to show
            if new_image:
                # If it was already a photo, edit it
                if poll.photo_file_id:
                    media = InputMediaPhoto(media=new_image, caption=new_caption, parse_mode=ParseMode.MARKDOWN_V2)
                    await context.bot.edit_message_media(chat_id=poll.chat_id, message_id=poll.message_id, media=media, reply_markup=reply_markup)
                # If it was text, delete and send a new photo
                else:
                    await context.bot.delete_message(chat_id=poll.chat_id, message_id=poll.message_id)
                    new_msg = await context.bot.send_photo(chat_id=poll.chat_id, photo=new_image, caption=new_caption, reply_markup=reply_markup, parse_mode=ParseMode.MARKDOWN_V2)
                    poll.message_id = new_msg.message_id
                    if new_msg.photo:
                        poll.photo_file_id = new_msg.photo[-1].file_id
            # If we are going from photo to text or text to text
            else:
                # If it was a photo, delete and send text
                if poll.photo_file_id:
                    await context.bot.delete_message(chat_id=poll.chat_id, message_id=poll.message_id)
                    new_msg = await context.bot.send_message(chat_id=poll.chat_id, text=new_caption, reply_markup=reply_markup, parse_mode=ParseMode.MARKDOWN_V2)
                    poll.message_id = new_msg.message_id
                    poll.photo_file_id = None # Important to clear this
                # If it was already text, just edit it
                else:
                    await context.bot.edit_message_text(chat_id=poll.chat_id, message_id=poll.message_id, text=new_caption, reply_markup=reply_markup, parse_mode=ParseMode.MARKDOWN_V2)
            
            session.commit()

        except telegram.error.BadRequest as e:
            if "Message is not modified" not in str(e):
                logger.warning(f"Message not modified after vote on poll {poll_id}, likely no visible change.")
            else:
                logger.error(f"Error updating message for poll {poll_id} after vote: {e}", exc_info=True)
        except Exception as e:
            logger.error(f"Unexpected error updating message for poll {poll_id} after vote: {e}", exc_info=True)

    finally:
        session.close()

    await update_poll_message(poll_id, context) 