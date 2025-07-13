from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, CallbackQuery, WebAppInfo, InputMediaPhoto
from telegram.ext import ContextTypes
from telegram.constants import ParseMode
from telegram.helpers import escape_markdown
import telegram
import asyncio
import time
from telegram.error import BadRequest

from src import database as db
from src.config import logger, WEB_URL, BOT_OWNER_ID
from src.display import generate_poll_content
from src.handlers import admin

async def wizard_start(query: CallbackQuery, context: ContextTypes.DEFAULT_TYPE, chat_id: int):
    """Starts the poll creation wizard by asking for the poll type."""
    context.user_data['wizard_chat_id'] = chat_id
    context.user_data['message_to_edit'] = query.message.message_id # Save message ID
    
    keyboard = [
        [InlineKeyboardButton("📊 Обычный опрос (кнопки в чате)", callback_data=f"dash:wizard_set_type:native:{chat_id}")],
        [InlineKeyboardButton("🌐 Web App опрос (отдельная страница)", callback_data=f"dash:wizard_set_type:webapp:{chat_id}")],
        [InlineKeyboardButton("❌ Отмена", callback_data=f"dash:group:{chat_id}")]
    ]
    
    await query.edit_message_text(
        "Выберите тип опроса, который хотите создать:",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )

async def wizard_set_type(query: CallbackQuery, context: ContextTypes.DEFAULT_TYPE, poll_type: str, chat_id: int):
    """Handles the poll type selection and proceeds to the next step."""
    context.user_data['wizard_poll_type'] = poll_type
    
    if poll_type == 'native':
        # Ask about multiple answers
        keyboard = [
            [InlineKeyboardButton("Да (несколько вариантов)", callback_data=f"dash:wizard_set_multiple:yes:{chat_id}")],
            [InlineKeyboardButton("Нет (один вариант)", callback_data=f"dash:wizard_set_multiple:no:{chat_id}")],
            [InlineKeyboardButton("❌ Отмена", callback_data=f"dash:group:{chat_id}")]
        ]
        await query.edit_message_text(
            "Разрешить выбор нескольких вариантов ответа?",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
    elif poll_type == 'webapp':
        context.user_data['wizard_allow_multiple'] = False # Webapps handle this internally
        await wizard_show_webapp_selection(query, context, chat_id)

async def wizard_set_multiple(query: CallbackQuery, context: ContextTypes.DEFAULT_TYPE, allow_multiple: str, chat_id: int):
    """Sets the multiple answers option and asks for the poll title."""
    context.user_data['wizard_allow_multiple'] = (allow_multiple == 'yes')
    context.user_data['wizard_state'] = 'waiting_for_poll_title'
    await query.edit_message_text(
        "Введите название (заголовок) для вашего опроса.",
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("❌ Отмена", callback_data=f"dash:group:{chat_id}")]])
    )

async def wizard_show_webapp_selection(query: CallbackQuery, context: ContextTypes.DEFAULT_TYPE, chat_id: int):
    """Shows a list of available bundled web apps to attach to the poll."""
    bundled_apps = context.bot_data.get('BUNDLED_WEB_APPS', {})
    
    if not bundled_apps:
        await query.edit_message_text(
            "В боте не найдено встроенных Web Apps. Проверьте конфигурацию.",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("❌ Отмена", callback_data=f"dash:group:{chat_id}")]])
        )
        return

    kb = []
    for app_id, app_data in bundled_apps.items():
        kb.append([InlineKeyboardButton(app_data['name'], callback_data=f"dash:wizard_select_webapp:{app_id}")])
    kb.append([InlineKeyboardButton("❌ Отмена", callback_data=f"dash:group:{chat_id}")])

    await query.edit_message_text(
        "Выберите Web App, которое будет использоваться для этого опроса:",
        reply_markup=InlineKeyboardMarkup(kb)
    )

async def wizard_select_webapp(query: CallbackQuery, context: ContextTypes.DEFAULT_TYPE, app_id: str):
    """Saves the selected web app and asks for the poll title."""
    context.user_data['wizard_web_app_id'] = app_id
    context.user_data['wizard_state'] = 'waiting_for_poll_title'

    chat_id = context.user_data.get('wizard_chat_id')
    if not chat_id:
        await query.edit_message_text("Ошибка: ID чата не найден. Попробуйте начать заново.", reply_markup=None)
        return

    app_data = context.bot_data.get('BUNDLED_WEB_APPS', {}).get(app_id)
    app_name = app_data['name'] if app_data else f"ID {app_id}"
    
    await query.edit_message_text(
        f"Вы выбрали «{escape_markdown(app_name, 2)}»\\.\n\nТеперь введите название \\(заголовок\\) для вашего опроса\\.",
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("❌ Отмена", callback_data=f"dash:group:{chat_id}")]])
    )

# +++ Poll Actions Handlers (called from dashboard) +++

async def start_poll(query: CallbackQuery, context: ContextTypes.DEFAULT_TYPE, poll_id: int):
    """Activates a draft poll and sends it to the group as a photo with a caption."""
    logger.info(f"Attempting to start poll_id: {poll_id}")
    session = db.SessionLocal()
    try:
        poll = session.query(db.Poll).filter_by(poll_id=poll_id).first()
        
        if not poll:
            logger.error(f"start_poll: Poll {poll_id} not found in database.")
            await query.answer('Опрос не найден.', show_alert=True)
            return

        # Add detailed debug logging
        logger.info(
            f"[DEBUG_START_POLL] Poll {poll_id} data: "
            f"type='{poll.poll_type}', status='{poll.status}', "
            f"options='{poll.options}', "
            f"web_app_id='{poll.web_app_id}'"
        )

        if poll.status != 'draft':
            await query.answer('Опрос не является черновиком или не найден.', show_alert=True)
            return

        # More specific checks for poll validity
        if not poll.message:
            await query.answer('Текст (заголовок) опроса не задан. Отредактируйте его в настройках.', show_alert=True)
            return

        caption, image_bytes = generate_poll_content(poll=poll, session=session)
        
        # Determine keyboard
        kb = []
        if poll.poll_type == 'native':
            # Validation for native poll options.
            if not poll.options or any(not opt.strip() for opt in poll.options.split(',')):
                await query.answer('Ошибка: опрос содержит пустые или некорректные варианты ответов. Пожалуйста, отредактируйте их в настройках.', show_alert=True)
                return
            options = poll.options.split(',')
            options = poll.options.split(',')
            kb = []
            row = []
            for i, opt in enumerate(options):
                row.append(
                    InlineKeyboardButton(opt.strip(),
                                         callback_data=f'vote:{poll.poll_id}:{i}')
                )
                # группируем по 3 кнопки в строке
                if len(row) == 3:
                    kb.append(row)
                    row = []
            if row:
                kb.append(row)
        elif poll.poll_type == 'webapp':
            if not poll.web_app_id:
                await query.answer('Ошибка: для этого опроса не задан ID веб-приложения.', show_alert=True)
                return
            url = f"{WEB_URL}/web_apps/{poll.web_app_id}/?poll_id={poll.poll_id}"
            kb = [[InlineKeyboardButton("⚜️ Голосовать в приложении", web_app=WebAppInfo(url=url))]]
        
        # Final debug logging before sending
        log_text = caption.replace('\n', ' ')
        logger.info(f"[DEBUG_START_POLL] Final text being sent: '{log_text}'")
        logger.info(f"[DEBUG_START_POLL] Keyboard object: {kb}")
        
        try:
            msg = None
            # If we have an image, send a photo.
            if image_bytes:
                msg = await context.bot.send_photo(
                    chat_id=poll.chat_id,
                    photo=image_bytes,
                    caption=caption,
                    reply_markup=InlineKeyboardMarkup(kb),
                    parse_mode=ParseMode.MARKDOWN_V2
                )
                if msg.photo:
                    poll.photo_file_id = msg.photo[-1].file_id
            # Otherwise, send a text message.
            else:
                msg = await context.bot.send_message(
                    chat_id=poll.chat_id,
                    text=caption,
                    reply_markup=InlineKeyboardMarkup(kb),
                    parse_mode=ParseMode.MARKDOWN_V2
                )

            poll.status = 'active'
            poll.message_id = msg.message_id
            session.commit()
            await query.answer(f'Опрос {poll.poll_id} запущен.', show_alert=True)
            await show_poll_list(query, poll.chat_id, 'draft')
        except Exception as e:
            logger.error(f"Ошибка запуска опроса {poll_id}: {e}", exc_info=True)
            await query.answer(f'Ошибка: {e}', show_alert=True)
    finally:
        session.close()

async def close_poll(query: CallbackQuery, context: ContextTypes.DEFAULT_TYPE, poll_id: int):
    """Closes an active poll, updating the photo and caption."""
    session = db.SessionLocal()
    try:
        poll = session.query(db.Poll).filter_by(poll_id=poll_id).first()
        
        if not poll or poll.status != 'active':
            await query.answer("Опрос не активен.", show_alert=True)
            return

        poll.status = 'closed'
        chat_id_for_refresh = poll.chat_id
        session.commit() # Commit status change first
        
        final_caption, final_image = generate_poll_content(poll=poll, session=session)
        
        try:
            # If we have a final image (and a message to edit), update the media.
            if poll.message_id and final_image:
                # We need a file_id to edit media. If we don't have one (e.g., poll started as text),
                # we must delete the old message and send a new photo.
                if poll.photo_file_id:
                    media = InputMediaPhoto(media=final_image, caption=final_caption, parse_mode=ParseMode.MARKDOWN_V2)
                    await context.bot.edit_message_media(chat_id=poll.chat_id, message_id=poll.message_id, media=media, reply_markup=None)
                else:
                    await context.bot.delete_message(chat_id=poll.chat_id, message_id=poll.message_id)
                    new_msg = await context.bot.send_photo(chat_id=poll.chat_id, photo=final_image, caption=final_caption, parse_mode=ParseMode.MARKDOWN_V2)
                    poll.message_id = new_msg.message_id
                    if new_msg.photo:
                        poll.photo_file_id = new_msg.photo[-1].file_id
            # If there's no final image, just edit the text.
            elif poll.message_id:
                 # If it was a photo, we need to delete and send text
                if poll.photo_file_id:
                    await context.bot.delete_message(chat_id=poll.chat_id, message_id=poll.message_id)
                    new_msg = await context.bot.send_message(chat_id=poll.chat_id, text=final_caption, parse_mode=ParseMode.MARKDOWN_V2)
                    poll.message_id = new_msg.message_id
                    poll.photo_file_id = None # Important to clear this
                # If it was already text, just edit it
                else:
                    await context.bot.edit_message_text(chat_id=poll.chat_id, message_id=poll.message_id, text=final_caption, reply_markup=None, parse_mode=ParseMode.MARKDOWN_V2)

        except telegram.error.BadRequest as e:
            if "Message is not modified" not in str(e):
                logger.error(f"Could not edit final message for poll {poll_id}: {e}")
        
        session.commit()
        await query.answer("Опрос завершён.", show_alert=True)
        await show_poll_list(query, chat_id_for_refresh, 'active')

    except Exception as e:
        logger.error(f"An unexpected error occurred while closing poll {poll_id}: {e}")
        session.rollback()
        await query.answer("Произошла неожиданная ошибка при завершении опроса.", show_alert=True)
    finally:
        session.close()

async def reopen_poll(query: CallbackQuery, context: ContextTypes.DEFAULT_TYPE, poll_id: int):
    """Reopens a closed poll, updating the photo, caption, and keyboard."""
    session = db.SessionLocal()
    try:
        poll = session.query(db.Poll).filter_by(poll_id=poll_id).first()
        if not poll or poll.status != 'closed':
            await query.answer("Этот опрос нельзя открыть заново.", show_alert=True)
            return

        poll.status = 'active'
        # No need to commit here, it will be committed after the message is successfully sent/edited

        new_caption, new_image = generate_poll_content(poll=poll, session=session)
        
        kb = []
        if poll.poll_type == 'native':
            options = poll.options.split(',')
            kb = []
            row = []
            for i, opt in enumerate(options):
                row.append(
                    InlineKeyboardButton(opt.strip(), callback_data=f'vote:{poll.poll_id}:{i}')
                )
                # group buttons by 3 per row
                if len(row) == 3:
                    kb.append(row)
                    row = []
            if row:
                kb.append(row)
        elif poll.poll_type == 'webapp':
            if not poll.web_app_id:
                await query.answer('Ошибка: для этого опроса не задан ID веб-приложения.', show_alert=True)
                session.close()
                return
            url = f"{WEB_URL}/web_apps/{poll.web_app_id}/?poll_id={poll.poll_id}"
            kb = [[InlineKeyboardButton("⚜️ Голосовать в приложении", web_app=WebAppInfo(url=url))]]
        
        reply_markup = InlineKeyboardMarkup(kb)

        try:
            if not poll.message_id:
                # This case shouldn't happen for a closed poll, but as a fallback
                msg = await context.bot.send_message(chat_id=poll.chat_id, text=new_caption, reply_markup=reply_markup, parse_mode=ParseMode.MARKDOWN_V2)
                poll.message_id = msg.message_id
            # If we have a new image to show
            elif new_image:
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
            await query.answer("Опрос снова открыт.", show_alert=True)
            await show_poll_list(query, poll.chat_id, 'closed')
        except Exception as e:
            logger.error(f"Failed to edit message when reopening poll {poll_id}: {e}")
            await query.answer("Опрос открыт, но не удалось обновить сообщение в чате.", show_alert=True)
            session.rollback()
            return

    except Exception as e:
        logger.error(f"An unexpected error occurred while reopening poll {poll_id}: {e}")
        session.rollback()
        await query.answer("Произошла неожиданная ошибка при открытии опроса.", show_alert=True)
    finally:
        session.close()

async def delete_poll(query: CallbackQuery, poll_id: int):
    """Deletes a poll and all associated data."""
    session = db.SessionLocal()
    try:
        poll = session.query(db.Poll).filter_by(poll_id=poll_id).first()
        if poll:
            chat_id, status = poll.chat_id, poll.status
            # Cascade delete is configured in the model, so this should be enough
            session.delete(poll)
            session.commit()
            await query.answer(f"Опрос {poll_id} удален.", show_alert=True)
            await show_poll_list(query, chat_id, status)
        else:
            await query.answer("Опрос не найден.", show_alert=True)
    finally:
        session.close()


async def check_admin_in_chat(user_id: int, chat: db.KnownChat, context: ContextTypes.DEFAULT_TYPE, semaphore: asyncio.Semaphore):
    """
    Helper to check admin/creator status for one chat, respecting a semaphore and with an individual timeout.
    A user is considered "authorized" if they are a real admin OR if they have created a poll in that chat.
    """
    async with semaphore:
        try:
            # Add a 5-second timeout to each individual check to prevent hangs
            async def check_logic():
                # Don't check private chats. The 'type' must be explicitly not 'private'.
                if chat.type == 'private':
                    return None
                    
                # --- Primary Check: Is the user a visible admin? ---
                logger.info(f"Checking admin status for user {user_id} in chat {chat.chat_id} ('{chat.title}')...")
                admins = await context.bot.get_chat_administrators(chat.chat_id)
                admin_ids = [admin.user.id for admin in admins]

                if user_id in admin_ids:
                    logger.info(f"SUCCESS (Admin): User {user_id} IS admin in chat {chat.chat_id}.")
                    return {'id': chat.chat_id, 'title': chat.title}

                # --- Fallback Check: Has the user created any polls in this chat? ---
                session = db.SessionLocal()
                try:
                    if db.has_user_created_poll_in_chat(session, user_id, chat.chat_id):
                        logger.info(f"SUCCESS (Creator): User {user_id} is not an admin but created a poll in chat {chat.chat_id}.")
                        return {'id': chat.chat_id, 'title': chat.title}
                finally:
                    session.close()

                # If neither check passes, log for diagnostics.
                logger.warning(
                    f"INFO: User {user_id} is NOT in the admin list for chat {chat.chat_id} "
                    f"('{chat.title}') and has not created polls there. Received admin IDs: {admin_ids}"
                )
                return None

            # Wrap the logic with a 5-second timeout.
            return await asyncio.wait_for(check_logic(), timeout=5.0)

        except asyncio.TimeoutError:
            logger.warning(f"TIMEOUT: Check for chat {chat.chat_id} ('{chat.title}') took too long and was skipped.")
        except Exception as e:
            logger.warning(f"FAILED to check admin status in chat {chat.chat_id} ('{chat.title}'): {e}")
        
        return None

async def private_chat_entry_point(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handles the /start command in a private chat by concurrently finding all chats where the user is an admin."""
    user_id = update.effective_user.id
    logger.info(f"User {user_id} started dashboard process. Finding admin chats.")
    
    # Immediately send a "loading" message to give user feedback.
    loading_message = await update.effective_message.reply_text("🔎 Ищу чаты, где вы админ...")

    known_chats = db.get_known_chats()
    
    admin_chats = []
    if known_chats:
        logger.info(f"Found {len(known_chats)} known chats to check for user {user_id}.")
        semaphore = asyncio.Semaphore(10)
        start_time = time.time()
        tasks = [check_admin_in_chat(user_id, chat, context, semaphore) for chat in known_chats]
        results = await asyncio.gather(*tasks, return_exceptions=True)
        duration = time.time() - start_time
        logger.info(f"Admin checks for user {user_id} completed in {duration:.2f} seconds.")
        admin_chats = [chat for chat in results if chat is not None and not isinstance(chat, Exception)]
        failed_checks = [r for r in results if isinstance(r, Exception)]
        if failed_checks:
            logger.error(f"{len(failed_checks)} checks failed with exceptions during dashboard load for user {user_id}.")

    kb = []
    if admin_chats:
        kb.extend([[InlineKeyboardButton(chat["title"], callback_data=f"dash:group:{chat['id']}")] for chat in admin_chats])
    
    if user_id == BOT_OWNER_ID:
        kb.append([InlineKeyboardButton("⚙️ Панель администратора", callback_data="dash:admin_panel")])

    if not kb:
        await loading_message.edit_text("Я не нашел групп, где вы являетесь администратором, или бот вообще не состоит в группах.")
        return
        
    text = 'Выберите чат для управления:' if admin_chats else 'Панель администратора:'
    await loading_message.edit_text(
        text, 
        reply_markup=InlineKeyboardMarkup(kb)
    )


async def show_group_dashboard(query: CallbackQuery, context: ContextTypes.DEFAULT_TYPE, chat_id: int):
    chat_title = db.get_group_title(chat_id)
    text = f"Панель управления для чата *{escape_markdown(chat_title, 2)}*:"

    keyboard = [
        [InlineKeyboardButton("📊 Активные опросы", callback_data=f'dash:polls:{chat_id}:active'),
         InlineKeyboardButton("📈 Завершенные", callback_data=f'dash:polls:{chat_id}:closed')],
        [InlineKeyboardButton("📝 Черновики", callback_data=f'dash:polls:{chat_id}:draft')],
        [InlineKeyboardButton("✏️ Создать опрос", callback_data=f'dash:wizard_start:{chat_id}')],
        [InlineKeyboardButton("👥 Участники", callback_data=f'dash:participants_menu:{chat_id}')],
        [InlineKeyboardButton("🔙 К выбору чата", callback_data='dash:back_to_chats')]
    ]
    await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode=ParseMode.MARKDOWN_V2)

async def show_poll_list(query: CallbackQuery, chat_id: int, status: str):
    session = db.SessionLocal()
    try:
        polls = db.get_polls_by_status(chat_id, status)
        status_text_map = {'active': 'активных опросов', 'draft': 'черновиков', 'closed': 'завершённых опросов'}
        text_part = status_text_map.get(status, f'{status} опросов')

        if not polls:
            text = f"Нет {text_part} в этой группе."
            kb = [[InlineKeyboardButton("↩️ Назад", callback_data=f"dash:group:{chat_id}")]]
            await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(kb))
            return

        title_map = {'active': 'Активные опросы', 'draft': 'Черновики', 'closed': 'Завершённые опросы'}
        text = f'*{title_map.get(status, status.capitalize())}*:'
        kb = []
        for poll in polls:
            msg = (poll.message or f'Опрос {poll.poll_id}')[:40]
            # Common delete button for closed and draft polls
            delete_button = InlineKeyboardButton("🗑", callback_data=f"dash:delete_poll_confirm:{poll.poll_id}")
            
            if status == 'active': 
                kb.append([InlineKeyboardButton(msg, callback_data=f"results:show:{poll.poll_id}")])
            elif status == 'draft': 
                kb.append([
                    InlineKeyboardButton(f"✏️ {msg}", callback_data=f"settings:poll_menu:{poll.poll_id}"), 
                    InlineKeyboardButton("▶️", callback_data=f"dash:start_poll:{poll.poll_id}"), 
                    delete_button
                ])
            elif status == 'closed': 
                kb.append([
                    InlineKeyboardButton(f"📊 {msg}", callback_data=f"results:show:{poll.poll_id}"), 
                    delete_button
                ])
        kb.append([InlineKeyboardButton("↩️ Назад", callback_data=f"dash:group:{chat_id}")])

        try:
            await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(kb), parse_mode=ParseMode.MARKDOWN_V2)
        except BadRequest as e:
            if "There is no text in the message" in str(e):
                # Если исходное сообщение было фото/медиа без текста
                if query.message and query.message.photo:
                    await query._bot.edit_message_caption(
                        chat_id=query.message.chat_id,
                        message_id=query.message.message_id,
                        caption=text,
                        reply_markup=InlineKeyboardMarkup(kb),
                        parse_mode=ParseMode.MARKDOWN_V2,
                    )
                else:
                    # fallback: удалить и отправить новое текстовое сообщение
                    await query._bot.delete_message(chat_id=query.message.chat_id, message_id=query.message.message_id)
                    await query._bot.send_message(
                        chat_id=query.message.chat_id,
                        text=text,
                        reply_markup=InlineKeyboardMarkup(kb),
                        parse_mode=ParseMode.MARKDOWN_V2,
                    )
            else:
                raise
    finally:
        session.close()

async def show_participants_menu(query: CallbackQuery, chat_id: int):
    title = escape_markdown(db.get_group_title(chat_id), 2)
    text = f"👥 *Управление участниками в* `{title}`"
    kb = [
        [InlineKeyboardButton("📄 Показать список", callback_data=f"dash:participants_list:{chat_id}:0")],
        [InlineKeyboardButton("➕ Добавить по сообщению", callback_data=f"dash:add_user_fw_start:{chat_id}")],
        [InlineKeyboardButton("🚫 Исключить/вернуть", callback_data=f"dash:exclude_menu:{chat_id}:0")],
        [InlineKeyboardButton("🧹 Очистить список", callback_data=f"dash:clean_participants:{chat_id}")],
        [InlineKeyboardButton("↩️ Назад", callback_data=f"dash:group:{chat_id}")]
    ]
    await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(kb), parse_mode=ParseMode.MARKDOWN_V2)

async def show_participants_list(query: CallbackQuery, chat_id: int, page: int = 0):
    """Displays a paginated list of group participants."""
    session = db.SessionLocal()
    try:
        participants = db.get_participants(chat_id, session=session)
        title = escape_markdown(db.get_group_title(chat_id), 2)

        if not participants:
            text = f"В чате «{title}» нет зарегистрированных участников."
            kb = [[InlineKeyboardButton("↩️ Назад", callback_data=f"dash:participants_menu:{chat_id}")]]
            await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(kb))
            return

        items_per_page = 50
        start_index = page * items_per_page
        end_index = start_index + items_per_page
        paginated_participants = participants[start_index:end_index]
        total_pages = -(-len(participants) // items_per_page)

        text_parts = [f'👥 *Список участников \\(«{title}»\\)* \\(Стр\\. {page + 1}/{total_pages}\\):\n']
        
        for i, p in enumerate(paginated_participants, start=start_index + 1):
            name = escape_markdown(db.get_user_name(session, p.user_id), 2)
            status = " \\(🚫\\)" if p.excluded else ""
            text_parts.append(f"{i}\\. {name}{status}")
        
        text = "\n".join(text_parts)
        
        kb_rows = []
        nav_buttons = []
        if page > 0:
            nav_buttons.append(InlineKeyboardButton("⬅️", callback_data=f"dash:participants_list:{chat_id}:{page - 1}"))
        if end_index < len(participants):
            nav_buttons.append(InlineKeyboardButton("➡️", callback_data=f"dash:participants_list:{chat_id}:{page + 1}"))
        
        if nav_buttons: kb_rows.append(nav_buttons)
        kb_rows.append([InlineKeyboardButton("↩️ В меню", callback_data=f"dash:participants_menu:{chat_id}")])
        
        await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(kb_rows), parse_mode=ParseMode.MARKDOWN_V2)
    finally:
        session.close()

async def show_exclude_menu(query: CallbackQuery, chat_id: int, page: int = 0):
    """Displays a paginated menu to exclude/include participants."""
    session = db.SessionLocal()
    try:
        participants = db.get_participants(chat_id, session=session)
        title = escape_markdown(db.get_group_title(chat_id), 2)

        if not participants:
            await query.answer("Нет участников для управления.", show_alert=True)
            return

        items_per_page = 20
        start_index = page * items_per_page
        end_index = start_index + items_per_page
        paginated_participants = participants[start_index:end_index]
        total_pages = -(-len(participants) // items_per_page)

        text = f'👥 *Исключение/возврат \\(«{title}»\\)* \\(Стр\\. {page + 1}/{total_pages}\\):\\.\nНажмите на участника, чтобы изменить его статус\.'
        
        kb = []
        current_row = []
        MAX_PER_ROW = 3  # up to 3 short buttons per row
        SHORT_LEN = 15   # threshold to treat button as short
        for p in paginated_participants:
            name = db.get_user_name(session, p.user_id)
            status_icon = "🚫" if p.excluded else "✅"
            username_part = f" (@{p.username})" if p.username else ""
            button_text = f"{status_icon} {name}{username_part}"
            callback_data = f"dash:toggle_exclude:{chat_id}:{p.user_id}:{page}"
            btn = InlineKeyboardButton(button_text, callback_data=callback_data)
            if len(button_text) <= SHORT_LEN:
                current_row.append(btn)
                if len(current_row) == MAX_PER_ROW:
                    kb.append(current_row)
                    current_row = []
            else:
                if current_row:
                    kb.append(current_row)
                    current_row = []
                kb.append([btn])
        if current_row:
            kb.append(current_row)
        
        nav_buttons = []
        if page > 0: nav_buttons.append(InlineKeyboardButton("⬅️", callback_data=f"dash:exclude_menu:{chat_id}:{page-1}"))
        if end_index < len(participants): nav_buttons.append(InlineKeyboardButton("➡️", callback_data=f"dash:exclude_menu:{chat_id}:{page+1}"))
        if nav_buttons: kb.append(nav_buttons)

        kb.append([InlineKeyboardButton("↩️ Назад", callback_data=f"dash:participants_menu:{chat_id}")])
        
        await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(kb), parse_mode=ParseMode.MARKDOWN_V2)
    finally:
        session.close()

async def toggle_exclude_participant(query: CallbackQuery, context: ContextTypes.DEFAULT_TYPE, chat_id: int, user_id: int, page: int):
    """Toggles the 'excluded' status for a participant."""
    session = db.SessionLocal()
    try:
        participant = session.query(db.Participant).filter_by(chat_id=chat_id, user_id=user_id).first()
        if participant:
            participant.excluded = not participant.excluded
            session.commit()
            await show_exclude_menu(query, chat_id, page)

            # --- Refresh nudge messages for active polls in this chat ---
            from src.display import generate_nudge_text
            polls = session.query(db.Poll).filter_by(chat_id=chat_id, status='active').all()
            for poll in polls:
                nudge_text = await generate_nudge_text(poll.poll_id)
                try:
                    if poll.nudge_message_id:
                        await context.bot.edit_message_text(
                            chat_id=chat_id,
                            message_id=poll.nudge_message_id,
                            text=nudge_text,
                            parse_mode=ParseMode.MARKDOWN_V2,
                        )
                        if "Все участники проголосовали" in nudge_text:
                            poll.nudge_message_id = None
                    else:
                        if "Все участники проголосовали" not in nudge_text:
                            new_msg = await context.bot.send_message(
                                chat_id=chat_id,
                                text=nudge_text,
                                parse_mode=ParseMode.MARKDOWN_V2,
                            )
                            poll.nudge_message_id = new_msg.message_id
                    session.commit()
                except BadRequest as e:
                    if "Message is not modified" not in str(e):
                        logger.warning(f"Failed to update nudge for poll {poll.poll_id}: {e}")
        else:
            await query.answer("Участник не найден.", show_alert=True)
    finally:
        session.close()

async def clean_participants(query: CallbackQuery, chat_id: int):
    """Deletes all participants from a chat."""
    session = db.SessionLocal()
    try:
        db.delete_participants(session, chat_id)
        session.commit()
        await query.answer(f'Список участников для "{db.get_group_title(chat_id)}" очищен.', show_alert=True)
        await show_participants_menu(query, chat_id)
    finally:
        session.close()

async def add_user_via_forward_start(query: CallbackQuery, context: ContextTypes.DEFAULT_TYPE, chat_id: int):
    """Puts the bot in a state to wait for a forwarded message."""
    context.user_data['user_to_add_via_forward'] = {'chat_id': chat_id}
    await query.edit_message_text(
        "Перешлите мне любое сообщение от пользователя, которого хотите добавить в список участников этого чата.\n\n"
        "Важно: у пользователя не должно быть включено ограничение на пересылку сообщений.",
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("↩️ Отмена", callback_data=f"dash:participants_menu:{chat_id}")]])
    )

async def delete_poll_confirm(query: CallbackQuery, poll_id: int):
    """Asks for confirmation before deleting a poll."""
    session = db.SessionLocal()
    try:
        poll = session.query(db.Poll).filter_by(poll_id=poll_id).first()
        if not poll:
            await query.answer("Опрос уже удален.", show_alert=True)
            return
        text = f"Вы уверены, что хотите удалить опрос «{escape_markdown(poll.message or str(poll.poll_id), 2)}»? Это действие необратимо\\."
        kb = [[
            InlineKeyboardButton("✅ Да, удалить", callback_data=f"dash:delete_poll_execute:{poll_id}"),
            InlineKeyboardButton("❌ Нет, отмена", callback_data=f"dash:polls:{poll.chat_id}:{poll.status}")
        ]]
        await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(kb), parse_mode=ParseMode.MARKDOWN_V2)
    finally:
        session.close()

async def delete_poll_execute(query: CallbackQuery, poll_id: int):
    """Deletes a poll after confirmation."""
    await delete_poll(query, poll_id)

async def show_admin_panel(query: CallbackQuery, context: ContextTypes.DEFAULT_TYPE):
    """Shows the admin panel with admin-only commands."""
    text = "⚙️ *Панель администратора*\n\nЗдесь собраны команды для управления ботом."
    text = escape_markdown(text, version=2)
    kb = [
        [InlineKeyboardButton("📤 Экспорт данных (JSON)", callback_data="dash:admin_export_json")],
        [InlineKeyboardButton("📥 Инструкция по импорту (JSON)", callback_data="dash:admin_import_info")],
        [InlineKeyboardButton("🔙 К выбору чата", callback_data='dash:back_to_chats')]
    ]
    await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(kb), parse_mode=ParseMode.MARKDOWN_V2)

async def admin_import_info(query: CallbackQuery, context: ContextTypes.DEFAULT_TYPE):
    """Shows instructions for importing data."""
    text = (
        "📥 *Инструкция по импорту данных*\n\n"
        "1\\. Отправьте в этот чат файл экспорта \\(`.json`\\)\\.\n"
        "2\\. Ответьте на сообщение с файлом командой `/import_json`\\.\n\n"
        "⚠️ *ВНИМАНИЕ\\!* Импорт полностью сотрет все текущие данные в базе\\."
    )
    kb = [[InlineKeyboardButton("🔙 Назад в админ-панель", callback_data="dash:admin_panel")]]
    await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(kb), parse_mode=ParseMode.MARKDOWN_V2)


async def dashboard_callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Routes all callbacks starting with 'dash:'."""
    query = update.callback_query
    # It's better to answer the query right at the start.
    # Specific handlers can override this with their own answers if needed.
    # We run this as a background task to avoid blocking on network issues.
    asyncio.create_task(query.answer())

    # Simplified parsing for clarity
    # format: "dash:command:param1:param2:..."
    parts = query.data.split(':')
    command = parts[1]
    params = parts[2:]

    if command == "back_to_chats": await private_chat_entry_point(update, context)
    elif command == "group": await show_group_dashboard(query, context, int(params[0]))
    elif command == "polls": await show_poll_list(query, int(params[0]), params[1])
    elif command == "participants_menu": await show_participants_menu(query, int(params[0]))
    elif command == "participants_list": await show_participants_list(query, int(params[0]), int(params[1]))
    elif command == "exclude_menu": await show_exclude_menu(query, int(params[0]), int(params[1]))
    elif command == "toggle_exclude": await toggle_exclude_participant(query, context, int(params[0]), int(params[1]), int(params[2]))
    elif command == "clean_participants": await clean_participants(query, int(params[0]))
    elif command == "add_user_fw_start": await add_user_via_forward_start(query, context, int(params[0]))
    elif command == "start_poll": await start_poll(query, context, int(params[0]))
    elif command == "delete_poll_confirm": await delete_poll_confirm(query, int(params[0]))
    elif command == "delete_poll_execute": await delete_poll_execute(query, int(params[0]))
    elif command == "close_poll": await close_poll(query, context, int(params[0]))
    elif command == "reopen_poll": await reopen_poll(query, context, int(params[0]))
    elif command == "wizard_start": await wizard_start(query, context, int(params[0]))
    elif command == "wizard_set_type": await wizard_set_type(query, context, params[0], int(params[1]))
    elif command == "wizard_set_multiple": await wizard_set_multiple(query, context, params[0], int(params[1]))
    elif command == "wizard_select_webapp": await wizard_select_webapp(query, context, params[0])
    elif command == "admin_panel": await show_admin_panel(query, context)
    elif command == "admin_export_json":
        await query.answer("Запускаю экспорт...")
        await admin.export_json(update, context)
    elif command == "admin_import_info": await admin_import_info(query, context)

    # Dummy handler for no-op callbacks
    elif command == "noop":
        await query.answer()
    # Other handlers will be added here 