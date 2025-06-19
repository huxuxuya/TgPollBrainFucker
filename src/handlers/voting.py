from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, User, WebAppInfo, InputMediaPhoto
from telegram.ext import ContextTypes
from telegram.constants import ParseMode
from telegram.error import BadRequest
import telegram

from src import database as db
from src.config import logger, WEB_URL
from src.display import generate_poll_content


# Текст ошибки Telegram при невозможности удаления сообщения.
DELETE_ERROR_PHRASE = "Message can't be deleted"


async def update_poll_message(poll_id: int, context: ContextTypes.DEFAULT_TYPE):
    """
    Refreshes the poll message after a vote, handling text and photo updates.
    This function can now handle transitions between text-only and photo messages.
    """
    session = db.SessionLocal()
    try:
        # Use session to query to ensure data is fresh
        poll = session.query(db.Poll).filter_by(poll_id=poll_id).first()
        if not poll or not poll.message_id:
            logger.warning(f"update_poll_message: Poll {poll_id} or its message_id not found.")
            return

        # Generate new content, which may include an image
        new_caption, new_image = generate_poll_content(poll=poll, session=session)

        # Regenerate keyboard
        kb = []
        if poll.poll_type == 'native' and poll.options:
            options = poll.options.split(',')
            kb = [[InlineKeyboardButton(opt.strip(), callback_data=f'vote:{poll.poll_id}:{i}')] for i, opt in enumerate(options)]
        elif poll.poll_type == 'webapp' and poll.web_app_id:
            url = f"{WEB_URL}/web_apps/{poll.web_app_id}/?poll_id={poll.poll_id}"
            kb = [[InlineKeyboardButton("⚜️ Голосовать в приложении", web_app=WebAppInfo(url=url))]]
        
        reply_markup = InlineKeyboardMarkup(kb) if kb else None

        try:
            if new_image and not poll.photo_file_id:
                # Раньше было текстовое сообщение, теперь хотим добавить изображение
                new_msg = await context.bot.send_photo(
                    chat_id=poll.chat_id,
                    photo=new_image,
                    caption=new_caption,
                    reply_markup=reply_markup,
                    parse_mode=ParseMode.MARKDOWN_V2,
                )
                # После успешной отправки пробуем удалить старое текстовое сообщение
                try:
                    await context.bot.delete_message(chat_id=poll.chat_id, message_id=poll.message_id)
                except BadRequest as e:
                    if DELETE_ERROR_PHRASE not in str(e):
                        raise
                    logger.warning(f"Couldn't delete old text message {poll.message_id}: {e}")

                poll.message_id = new_msg.message_id
                poll.photo_file_id = new_msg.photo[-1].file_id if new_msg.photo else None
            elif poll.photo_file_id:
                # Сообщение уже содержит фото. Если сгенерировано новое изображение —
                # заменяем медиаконтент, иначе обновляем только подпись.
                if new_image:
                    media = InputMediaPhoto(media=new_image, caption=new_caption, parse_mode=ParseMode.MARKDOWN_V2)
                    await context.bot.edit_message_media(
                        chat_id=poll.chat_id,
                        message_id=poll.message_id,
                        media=media,
                        reply_markup=reply_markup,
                    )
                    # После успешного обновления медиа можно попробовать извлечь file_id,
                    # но API не возвращает его напрямую. Оставляем прежний, чтобы в
                    # дальнейшем всё равно пытаться редактировать без пересылки.
                else:
                    # Изображение не изменилось — правим только подпись.
                    await context.bot.edit_message_caption(
                        chat_id=poll.chat_id,
                        message_id=poll.message_id,
                        caption=new_caption,
                        reply_markup=reply_markup,
                        parse_mode=ParseMode.MARKDOWN_V2,
                    )
            else:
                # обычное текстовое сообщение
                await context.bot.edit_message_text(text=new_caption, chat_id=poll.chat_id, message_id=poll.message_id, reply_markup=reply_markup, parse_mode=ParseMode.MARKDOWN_V2)

            session.commit()

        except BadRequest as e:
            if "Message is not modified" not in str(e):
                logger.error(f"Failed to edit message for poll {poll_id}: {e}", exc_info=True)
        except Exception as e:
            logger.error(f"Unexpected failure in update_poll_message for poll {poll_id}: {e}", exc_info=True)

    finally:
        session.close()


async def legacy_vote_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handles the old vote callback format (e.g., 'poll_22_1')."""
    query = update.callback_query
    logger.info(f"Handling legacy vote callback: {query.data}")
    
    try:
        parts = query.data.split('_')
        poll_id = int(parts[1])
        option_index = int(parts[2])
        user = update.effective_user
        
        db.add_or_update_response(
            poll_id=poll_id,
            user_id=user.id,
            first_name=user.first_name,
            last_name=user.last_name,
            username=user.username,
            option_index=option_index
        )
        await query.answer("Спасибо, ваш голос учтён!")
        await update_poll_message(poll_id, context)

    except (IndexError, ValueError) as e:
        logger.error(f"Error parsing legacy_vote_handler data '{query.data}': {e}")
        await query.answer("Ошибка: не удалось обработать старый формат голосования.", show_alert=True)


async def vote_callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handles a user's vote on a poll and updates the poll message."""
    query = update.callback_query
    
    try:
        _, poll_id_str, option_index_str = query.data.split(':')
        poll_id = int(poll_id_str)
        option_index = int(option_index_str)
    except (ValueError, IndexError):
        logger.error(f"Invalid vote callback data received: {query.data}")
        await query.answer("Ошибка: неверные данные для голосования.", show_alert=True)
        return

    user = query.from_user
    
    # Register the vote first
    db.add_or_update_response(
        poll_id=poll_id,
        user_id=user.id,
        first_name=user.first_name,
        last_name=user.last_name,
        username=user.username,
        option_index=option_index
    )
    
    # Acknowledge the vote immediately
    await query.answer("Спасибо, ваш голос учтён!")
    
    # Trigger the message update logic
    await update_poll_message(poll_id, context) 