from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, WebAppInfo, InputMediaPhoto
from telegram.ext import ContextTypes
from telegram.constants import ParseMode
import telegram
import asyncio

from src import database as db
from src.config import logger, WEB_URL
from src.display import generate_poll_content, generate_nudge_text
from src.drawing import generate_results_heatmap_image

async def show_draft_poll_menu(context: ContextTypes.DEFAULT_TYPE, poll_id: int, chat_id: int, message_id: int):
    """Displays the management menu for a newly created draft poll."""
    poll = db.get_poll(poll_id)
    if not poll:
        # This should not happen in the normal flow
        await context.bot.edit_message_text(chat_id=chat_id, message_id=message_id, text="Ошибка: созданный опрос не найден.")
        return

    text, _ = generate_poll_content(poll_id)
    kb_rows = [
        [
            InlineKeyboardButton("▶️ Запустить", callback_data=f"dash:start_poll:{poll_id}"),
            InlineKeyboardButton("🗑️ Удалить", callback_data=f"dash:delete_poll_confirm:{poll_id}")
        ],
        [InlineKeyboardButton("⚙️ Настроить", callback_data=f"settings:poll_menu:{poll_id}")],
        [InlineKeyboardButton("↩️ К списку черновиков", callback_data=f"dash:polls:{poll.chat_id}:draft")]
    ]
    
    reply_markup = InlineKeyboardMarkup(kb_rows)
    
    try:
        await context.bot.edit_message_text(
            chat_id=chat_id,
            message_id=message_id,
            text=text,
            reply_markup=reply_markup,
            parse_mode=ParseMode.MARKDOWN_V2
        )
    except telegram.error.BadRequest as e:
        if "Message is not modified" not in str(e):
            logger.error(f"Error showing draft poll menu for poll {poll_id}: {e}")

async def show_results(update: Update, context: ContextTypes.DEFAULT_TYPE, poll_id: int):
    """Displays the results of a poll with action buttons."""
    query = update.callback_query
    poll = db.get_poll(poll_id)
    if not poll:
        await query.edit_message_text("Опрос не найден.")
        return

    text, image_bytes = generate_poll_content(poll_id)
    kb_rows = []
    if poll.status == 'active':
        kb_rows.append([
            InlineKeyboardButton("🔄 Обновить", callback_data=f"results:refresh:{poll_id}"),
            InlineKeyboardButton("⏹️ Завершить", callback_data=f"dash:close_poll:{poll_id}")
        ])
        
        nudge_button = InlineKeyboardButton("📢 Позвать неголосующих", callback_data=f"results:nudge:{poll_id}")
        if poll.nudge_message_id:
             nudge_button = InlineKeyboardButton("🗑️ Удалить напоминание", callback_data=f"results:del_nudge:{poll_id}")

        kb_rows.append([nudge_button])
        kb_rows.append([InlineKeyboardButton("⏬ Переместить в конец чата", callback_data=f"results:move_bottom:{poll_id}")])

    elif poll.status == 'closed':
        kb_rows.append([InlineKeyboardButton("▶️ Открыть заново", callback_data=f"dash:reopen_poll:{poll_id}")])

    kb_rows.append([InlineKeyboardButton("⚙️ Настроить", callback_data=f"settings:poll_menu:{poll_id}")])
    kb_rows.append([InlineKeyboardButton("↩️ К списку", callback_data=f"dash:polls:{poll.chat_id}:{poll.status}")])
    
    reply_markup = InlineKeyboardMarkup(kb_rows)

    try:
        if image_bytes:
            # Если в сообщении уже есть картинка, пробуем отредактировать медиа
            if query.message.photo:
                media = InputMediaPhoto(media=image_bytes, caption=text, parse_mode=ParseMode.MARKDOWN_V2)
                await query.edit_message_media(media=media, reply_markup=reply_markup)
            else:
                # Иначе удаляем текстовое сообщение и шлём новое фото
                await context.bot.delete_message(chat_id=query.message.chat_id, message_id=query.message.message_id)
                await context.bot.send_photo(chat_id=query.message.chat_id,
                                             photo=image_bytes,
                                             caption=text,
                                             reply_markup=reply_markup,
                                             parse_mode=ParseMode.MARKDOWN_V2)
        else:
            # Нет изображения – показываем только текст
            if query.message.photo:
                # Старое было фото – заменяем на текст
                await context.bot.delete_message(chat_id=query.message.chat_id, message_id=query.message.message_id)
                await context.bot.send_message(chat_id=query.message.chat_id,
                                               text=text,
                                               reply_markup=reply_markup,
                                               parse_mode=ParseMode.MARKDOWN_V2)
            else:
                # Обычное обновление текста
                await query.edit_message_text(text=text,
                                              reply_markup=reply_markup,
                                              parse_mode=ParseMode.MARKDOWN_V2)
    except telegram.error.BadRequest as e:
        if "Message is not modified" in str(e):
            logger.info("Poll results were not modified, skipping message edit.")
        else:
            # Неожиданные ошибки пробрасываем выше для логирования
            raise e

    if query.data.startswith('results:refresh'):
        await query.answer("Результаты обновлены.")

async def nudge_handler(update: Update, context: ContextTypes.DEFAULT_TYPE, poll_id: int):
    """Handles the nudge button, creating or updating the nudge message."""
    query = update.callback_query
    poll = db.get_poll(poll_id)
    if not poll or poll.status != 'active':
        await query.answer("Опрос не активен.", show_alert=True)
        return

    nudge_text = await generate_nudge_text(poll_id)
    try:
        msg = await context.bot.send_message(chat_id=poll.chat_id, text=nudge_text, reply_to_message_id=poll.message_id, parse_mode=ParseMode.MARKDOWN_V2)
        poll.nudge_message_id = msg.message_id
        db.commit_session(poll)
        await query.answer("Оповещение отправлено!", show_alert=False)
    except Exception as e:
        logger.error(f"Failed to send nudge message for poll {poll_id}: {e}")
        await query.answer(f"Ошибка при отправке оповещения: {e}", show_alert=True)
    
    await show_results(update, context, poll_id)

async def del_nudge_handler(update: Update, context: ContextTypes.DEFAULT_TYPE, poll_id: int):
    """Deletes the nudge message and handles cases where it's already gone."""
    query = update.callback_query
    poll = db.get_poll(poll_id)
    
    # If poll is gone for some reason, just stop.
    if not poll:
        await query.answer("Опрос не найден.", show_alert=True)
        return

    nudge_id_to_delete = poll.nudge_message_id

    # Always clear the nudge message ID from the database first.
    # This ensures our state is corrected even if the deletion fails.
    poll.nudge_message_id = None
    db.commit_session(poll)

    if nudge_id_to_delete:
        try:
            await context.bot.delete_message(poll.chat_id, nudge_id_to_delete)
            await query.answer("Оповещение удалено.", show_alert=False)
        except telegram.error.BadRequest as e:
            if "message to delete not found" in str(e).lower():
                logger.info(f"Nudge message {nudge_id_to_delete} was already deleted.")
                await query.answer("Оповещение уже было удалено.", show_alert=False)
            else:
                logger.warning(f"Couldn't delete nudge message {nudge_id_to_delete}: {e}")
                await query.answer("Не удалось удалить оповещение.", show_alert=True)
    else:
        # This case handles when the button was pressed but there was no nudge_id in DB.
        # The state is now corrected, so we just inform the user.
        await query.answer("Оповещение уже было удалено.", show_alert=False)

    # Refresh the results message to show the updated button
    await show_results(update, context, poll_id)

async def move_to_bottom_handler(update: Update, context: ContextTypes.DEFAULT_TYPE, poll_id: int):
    """Reposts the poll to the bottom of the chat, ensuring data is saved."""
    query = update.callback_query
    session = db.SessionLocal()
    try:
        poll = session.query(db.Poll).filter_by(poll_id=poll_id).first()
        if not poll or poll.status != 'active':
            await query.answer("Опрос не активен.", show_alert=True)
            return
            
        await query.answer("Перемещаю опрос...")
        try:
            if poll.message_id: await context.bot.delete_message(poll.chat_id, poll.message_id)
        except Exception as e:
            logger.warning(f"Couldn't delete old poll message {poll.message_id}: {e}")

        # Сгенерируем контент опроса (текст + возможная тепловая карта)
        new_text, image_bytes = generate_poll_content(poll=poll, session=session)
        kb = []
        if poll.poll_type == 'native':
            options = poll.options.split(',')
            kb = [[InlineKeyboardButton(opt.strip(), callback_data=f'vote:{poll.poll_id}:{i}')] for i, opt in enumerate(options)]
        elif poll.poll_type == 'webapp':
            if not poll.web_app_id:
                # We can't easily alert the user here, but we can log it.
                logger.error(f"Cannot move poll {poll_id} to bottom, associated web app id not found.")
                session.close()
                return
            url = f"{WEB_URL}/web_apps/{poll.web_app_id}/?poll_id={poll.poll_id}"
            kb = [[InlineKeyboardButton("⚜️ Голосовать в приложении", web_app=WebAppInfo(url=url))]]
        
        try:
            if image_bytes:
                new_message = await context.bot.send_photo(
                    chat_id=poll.chat_id,
                    photo=image_bytes,
                    caption=new_text,
                    reply_markup=InlineKeyboardMarkup(kb),
                    parse_mode=ParseMode.MARKDOWN_V2
                )
            else:
                new_message = await context.bot.send_message(
                    chat_id=poll.chat_id,
                    text=new_text,
                    reply_markup=InlineKeyboardMarkup(kb),
                    parse_mode=ParseMode.MARKDOWN_V2
                )
            poll.message_id = new_message.message_id
            session.commit()
        except Exception as e:
            # We don't have a message to edit here if this fails, so we can't show the error easily.
            # Logging is the most important part.
            logger.error(f"Failed to resend poll {poll_id} on move_to_bottom: {e}")
            await context.bot.send_message(query.message.chat_id, f"Ошибка при перемещении: {e}")
    finally:
        session.close()

async def results_callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Routes all callbacks starting with 'results:'."""
    query = update.callback_query
    # Run as a background task to avoid blocking on network issues.
    asyncio.create_task(query.answer())

    parts = query.data.split(':')
    command, poll_id = parts[1], int(parts[2])

    if command == "show" or command == "refresh":
        await show_results(update, context, poll_id)
    elif command == "nudge":
        await nudge_handler(update, context, poll_id)
    elif command == "del_nudge":
        await del_nudge_handler(update, context, poll_id)
    elif command == "move_bottom":
        await move_to_bottom_handler(update, context, poll_id)