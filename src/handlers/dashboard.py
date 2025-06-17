from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, CallbackQuery, WebAppInfo
from telegram.ext import ContextTypes
from telegram.constants import ParseMode
from telegram.helpers import escape_markdown
import telegram
import asyncio
import time

from src import database as db
from src.config import logger, WEB_URL
from src.display import generate_poll_text

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
    context.user_data['wizard_state'] = 'waiting_for_poll_title'
    
    await query.edit_message_text(
        "Введите название (заголовок) для вашего опроса.",
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("❌ Отмена", callback_data=f"dash:group:{chat_id}")]])
    )

async def wizard_set_webapp(query: CallbackQuery, context: ContextTypes.DEFAULT_TYPE, web_app_id: int):
    """Sets the web app for the poll and asks for the poll title."""
    context.user_data['wizard_webapp_id'] = web_app_id
    context.user_data['wizard_state'] = 'waiting_for_title'
    await query.edit_message_text(
        "Вы выбрали Web App. Теперь введите название для этого опроса (например, *Еженедельная оценка*):",
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("❌ Отмена", callback_data=f"dash:group:{context.user_data['wizard_chat_id']}")]])
    )

# +++ Poll Actions Handlers (called from dashboard) +++

async def start_poll(query: CallbackQuery, context: ContextTypes.DEFAULT_TYPE, poll_id: int):
    """Activates a draft poll and sends it to the group."""
    session = db.SessionLocal()
    try:
        poll = session.query(db.Poll).filter_by(poll_id=poll_id).first()
        if not poll or poll.status != 'draft':
            await query.answer('Опрос не является черновиком или не найден.', show_alert=True)
            return
        if not poll.message or not poll.options:
            await query.answer('Текст или варианты опроса не заданы.', show_alert=True)
            return

        initial_text = generate_poll_text(poll=poll, session=session)
        
        kb = []
        if poll.poll_type == 'native':
            options = poll.options.split(',')
            kb = [[InlineKeyboardButton(opt.strip(), callback_data=f'vote:{poll.poll_id}:{i}')] for i, opt in enumerate(options)]
        elif poll.poll_type == 'webapp':
            url = f"{WEB_URL}/vote/{poll.poll_id}"
            kb = [[InlineKeyboardButton("⚜️ Голосовать в приложении", web_app=WebAppInfo(url=url))]]

        
        try:
            msg = await context.bot.send_message(chat_id=poll.chat_id, text=initial_text, reply_markup=InlineKeyboardMarkup(kb), parse_mode=ParseMode.MARKDOWN_V2)
            poll.status = 'active'
            poll.message_id = msg.message_id
            session.commit()
            await query.answer(f'Опрос {poll.poll_id} запущен.', show_alert=True)
            await show_poll_list(query, poll.chat_id, 'draft')
        except Exception as e:
            logger.error(f"Ошибка запуска опроса {poll_id}: {e}")
            await query.answer(f'Ошибка: {e}', show_alert=True)
    finally:
        session.close()

async def close_poll(query: CallbackQuery, context: ContextTypes.DEFAULT_TYPE, poll_id: int):
    """Closes an active poll, ensuring the transaction is committed."""
    session = db.SessionLocal()
    try:
        poll = session.query(db.Poll).filter_by(poll_id=poll_id).first()
        
        if not poll or poll.status != 'active':
            await query.answer("Опрос не активен.", show_alert=True)
            return

        poll.status = 'closed'
        chat_id_for_refresh = poll.chat_id
        
        # We must commit the status change before refreshing anything.
        session.commit()
        await query.answer("Опрос завершён.", show_alert=True)
        
        # Now, generate the final text for the message in the group chat.
        final_text = generate_poll_text(poll=poll, session=session)
        
        try:
            if poll.message_id:
                await context.bot.edit_message_text(
                    chat_id=poll.chat_id, 
                    message_id=poll.message_id, 
                    text=final_text, 
                    reply_markup=None, 
                    parse_mode=ParseMode.MARKDOWN_V2
                )
        except telegram.error.BadRequest as e:
            # It's okay if the message wasn't modified.
            if "Message is not modified" not in str(e):
                logger.error(f"Could not edit final message for poll {poll_id}: {e}")
        
        # After successfully closing, refresh the list of active polls.
        await show_poll_list(query, chat_id_for_refresh, 'active')

    except Exception as e:
        logger.error(f"An unexpected error occurred while closing poll {poll_id}: {e}")
        session.rollback()
        await query.answer("Произошла неожиданная ошибка при завершении опроса.", show_alert=True)
    finally:
        session.close()

async def reopen_poll(query: CallbackQuery, context: ContextTypes.DEFAULT_TYPE, poll_id: int):
    """Reopens a closed poll."""
    session = db.SessionLocal()
    try:
        poll = session.query(db.Poll).filter_by(poll_id=poll_id).first()
        if not poll or poll.status != 'closed':
            await query.answer("Этот опрос нельзя открыть заново.", show_alert=True)
            return

        # Change status
        poll.status = 'active'
        
        # Regenerate the poll message with buttons
        new_text = generate_poll_text(poll=poll, session=session)
        kb = []
        if poll.poll_type == 'native':
            options = poll.options.split(',')
            kb = [[InlineKeyboardButton(opt.strip(), callback_data=f'vote:{poll.poll_id}:{i}')] for i, opt in enumerate(options)]
        elif poll.poll_type == 'webapp':
            url = f"{WEB_URL}/vote/{poll.poll_id}"
            kb = [[InlineKeyboardButton("⚜️ Голосовать в приложении", web_app=WebAppInfo(url=url))]]

        try:
            if poll.message_id:
                await context.bot.edit_message_text(
                    chat_id=poll.chat_id,
                    message_id=poll.message_id,
                    text=new_text,
                    reply_markup=InlineKeyboardMarkup(kb),
                    parse_mode=ParseMode.MARKDOWN_V2
                )
        except Exception as e:
            logger.error(f"Failed to edit message when reopening poll {poll_id}: {e}")
            await query.answer("Опрос открыт, но не удалось обновить сообщение в чате.", show_alert=True)
            # Rollback status change if message edit fails
            session.rollback()
            return
        
        # Commit only after the message has been successfully edited
        session.commit()
        await query.answer("Опрос снова открыт.", show_alert=True)
        
        # After reopening, show the list of closed polls, where this one will be gone.
        await show_poll_list(query, poll.chat_id, 'closed')

    except Exception as e:
        logger.error(f"An unexpected error occurred while reopening poll {poll_id}: {e}")
        session.rollback()
        await query.answer("Произошла неожиданная ошибка при открытии опроса.", show_alert=True)
    finally:
        session.close()

async def delete_poll(query: CallbackQuery, poll_id: int):
    """Deletes a poll and all associated data."""
    poll = db.get_poll(poll_id)
    if poll:
        chat_id, status = poll.chat_id, poll.status
        db.delete_responses_for_poll(poll_id)
        db.delete_poll_setting(poll_id)
        db.delete_poll_option_settings(poll_id)
        db.delete_poll(poll)
        await query.answer(f"Опрос {poll_id} удален.", show_alert=True)
        await show_poll_list(query, chat_id, status)
    else:
        await query.answer("Опрос не найден.", show_alert=True)


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
                if db.has_user_created_poll_in_chat(user_id, chat.chat_id):
                    logger.info(f"SUCCESS (Creator): User {user_id} is not an admin but created a poll in chat {chat.chat_id}.")
                    return {'id': chat.chat_id, 'title': chat.title}

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
    if not known_chats:
        logger.info(f"User {user_id} has no known chats to check.")
        await loading_message.edit_text("Я не состою ни в каких чатах. Сначала добавьте меня в группу.")
        return

    logger.info(f"Found {len(known_chats)} known chats to check for user {user_id}.")

    # Create a semaphore to limit concurrent requests to a reasonable number (e.g., 10)
    # to avoid hitting Telegram's rate limits or causing pool timeouts.
    semaphore = asyncio.Semaphore(10)

    # Create concurrent tasks for all admin checks.
    start_time = time.time()

    tasks = [check_admin_in_chat(user_id, chat, context, semaphore) for chat in known_chats]
    results = await asyncio.gather(*tasks, return_exceptions=True) # Use return_exceptions to prevent one failure from stopping all

    duration = time.time() - start_time
    logger.info(f"Admin checks for user {user_id} completed in {duration:.2f} seconds.")

    # Filter out the None results and exceptions
    admin_chats = [chat for chat in results if chat is not None and not isinstance(chat, Exception)]
    failed_checks = [r for r in results if isinstance(r, Exception)]
    
    if failed_checks:
        logger.error(f"{len(failed_checks)} checks failed with exceptions during dashboard load for user {user_id}.")


    # Edit the "Searching..." message with the final results.
    if not admin_chats:
        await loading_message.edit_text("Я не нашел групп, где вы являетесь администратором и я тоже.")
        return

    keyboard = [[InlineKeyboardButton(chat["title"], callback_data=f"dash:group:{chat['id']}")] for chat in admin_chats]
    await loading_message.edit_text(
        'Выберите чат для управления:', 
        reply_markup=InlineKeyboardMarkup(keyboard)
    )


async def show_group_dashboard(query: CallbackQuery, context: ContextTypes.DEFAULT_TYPE, chat_id: int):
    chat_title = db.get_group_title(chat_id)
    text = f"Панель управления для чата *{escape_markdown(chat_title, 2)}*:"

    keyboard = [
        [InlineKeyboardButton("📊 Активные опросы", callback_data=f'dash:polls:{chat_id}:active'),
         InlineKeyboardButton("📈 Завершенные", callback_data=f'dash:polls:{chat_id}:closed')],
        [InlineKeyboardButton("📝 Черновики", callback_data=f'dash:polls:{chat_id}:draft')],
        [InlineKeyboardButton("👥 Участники", callback_data=f'dash:participants_menu:{chat_id}')],
        [InlineKeyboardButton("✏️ Создать опрос", callback_data=f'dash:wizard_start:{chat_id}')],
        [InlineKeyboardButton("🔙 К выбору чата", callback_data='dash:back_to_chats')]
    ]
    await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode=ParseMode.MARKDOWN_V2)

async def show_poll_list(query: CallbackQuery, chat_id: int, status: str):
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
    await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(kb), parse_mode=ParseMode.MARKDOWN_V2)

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
        participants = db.get_participants(chat_id)
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
        session.commit()
    finally:
        session.close()

async def show_exclude_menu(query: CallbackQuery, chat_id: int, page: int = 0):
    """Displays a paginated menu to exclude/include participants."""
    session = db.SessionLocal()
    try:
        participants = db.get_participants(chat_id)
        title = escape_markdown(db.get_group_title(chat_id), 2)

        if not participants:
            await query.answer("Нет участников для управления.", show_alert=True)
            return

        items_per_page = 20
        start_index = page * items_per_page
        end_index = start_index + items_per_page
        paginated_participants = participants[start_index:end_index]
        total_pages = -(-len(participants) // items_per_page)

        text = f'👥 *Исключение/возврат \\(«{title}»\\)* \\(Стр\\. {page + 1}/{total_pages}\\):\nНажмите на участника, чтобы изменить его статус.'
        
        kb = []
        for p in paginated_participants:
            name = db.get_user_name(session, p.user_id)
            status_icon = "🚫" if p.excluded else "✅"
            button_text = f"{status_icon} {name}"
            callback_data = f"dash:toggle_exclude:{chat_id}:{p.user_id}:{page}"
            kb.append([InlineKeyboardButton(button_text, callback_data=callback_data)])
        
        nav_buttons = []
        if page > 0: nav_buttons.append(InlineKeyboardButton("⬅️", callback_data=f"dash:exclude_menu:{chat_id}:{page-1}"))
        if end_index < len(participants): nav_buttons.append(InlineKeyboardButton("➡️", callback_data=f"dash:exclude_menu:{chat_id}:{page+1}"))
        if nav_buttons: kb.append(nav_buttons)

        kb.append([InlineKeyboardButton("↩️ Назад", callback_data=f"dash:participants_menu:{chat_id}")])
        
        await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(kb), parse_mode=ParseMode.MARKDOWN_V2)
        session.commit()
    finally:
        session.close()

async def toggle_exclude_participant(query: CallbackQuery, chat_id: int, user_id: int, page: int):
    """Toggles the 'excluded' status for a participant."""
    participant = db.get_participant(chat_id, user_id)
    if participant:
        participant.excluded = 1 - (participant.excluded or 0)
        db.commit_session()
        await show_exclude_menu(query, chat_id, page)
    else:
        await query.answer("Участник не найден.", show_alert=True)

async def clean_participants(query: CallbackQuery, chat_id: int):
    """Deletes all participants from a chat."""
    db.delete_participants(chat_id)
    await query.answer(f'Список участников для "{db.get_group_title(chat_id)}" очищен.', show_alert=True)
    await show_participants_menu(query, chat_id)

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
    poll = db.get_poll(poll_id)
    if not poll:
        await query.answer("Опрос уже удален.", show_alert=True)
        return
    text = f"Вы уверены, что хотите удалить опрос «{escape_markdown(poll.message or str(poll_id), 2)}»? Это действие необратимо\\."
    kb = [[
        InlineKeyboardButton("✅ Да, удалить", callback_data=f"dash:delete_poll_execute:{poll_id}"),
        InlineKeyboardButton("❌ Нет, отмена", callback_data=f"dash:polls:{poll.chat_id}:{poll.status}")
    ]]
    await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(kb), parse_mode=ParseMode.MARKDOWN_V2)

async def delete_poll_execute(query: CallbackQuery, poll_id: int):
    """Deletes a poll after confirmation."""
    await delete_poll(query, poll_id)

def _get_webapp_management_menu(chat_id: int):
    """Builds the text and keyboard for the Web App management menu."""
    web_apps = db.get_web_apps_for_chat(chat_id)
    kb = [[InlineKeyboardButton("➕ Добавить приложение", callback_data=f"dash:webapp_add_start:{chat_id}")]]
    
    if web_apps:
        for app in web_apps:
            kb.append([
                InlineKeyboardButton(app.name, callback_data=f"dash:webapp_view:{app.id}"),
                InlineKeyboardButton("🗑️", callback_data=f"dash:webapp_delete_confirm:{app.id}")
            ])
            
    kb.append([InlineKeyboardButton("↩️ Назад", callback_data=f"dash:group_dashboard:{chat_id}")])
    
    text = "⚙️ *Управление Web Apps*\n\nЗдесь вы можете добавлять, просматривать и удалять свои веб-приложения."
    return text, InlineKeyboardMarkup(kb)

async def show_webapp_management_menu(query: CallbackQuery, chat_id: int):
    """Shows the Web App management menu by editing a message."""
    text, reply_markup = _get_webapp_management_menu(chat_id)
    
    try:
        await query.edit_message_text(text, reply_markup=reply_markup, parse_mode=ParseMode.MARKDOWN_V2)
    except telegram.error.BadRequest as e:
        if "Message is not modified" not in str(e):
            logger.error(f"Error in show_webapp_management_menu: {e}")


async def webapp_add_start(query: CallbackQuery, context: ContextTypes.DEFAULT_TYPE, chat_id: int):
    """Starts the wizard to add a new Web App."""
    context.user_data['wizard_state'] = 'waiting_for_webapp_name'
    context.user_data['wizard_chat_id'] = chat_id
    
    # Store message to edit later
    context.user_data['message_to_edit'] = query.message.message_id
    
    await query.edit_message_text(
        "Введите короткое, понятное название для вашего Web App (например, *Ежедневное голосование*):",
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("❌ Отмена", callback_data=f"dash:webapp_menu:{chat_id}")]]),
        parse_mode=ParseMode.MARKDOWN_V2
    )

async def webapp_delete_confirm(query: CallbackQuery, context: ContextTypes.DEFAULT_TYPE, app_id: int):
    """Asks for confirmation before deleting a web app."""
    # We don't have app details here without another DB call, so keep it generic.
    text = "Вы уверены, что хотите удалить это Web App? Это действие нельзя будет отменить."
    # We need chat_id to get back, but we don't have it here. This is a design flaw to fix later if needed.
    # For now, we'll send the user back to the chat selection.
    kb = [
        [InlineKeyboardButton("✅ Да, удалить", callback_data=f"dash:webapp_delete_execute:{app_id}")],
        [InlineKeyboardButton("❌ Нет, отмена", callback_data=f"dash:back_to_chats")]
    ]
    await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(kb))

async def webapp_delete_execute(query: CallbackQuery, context: ContextTypes.DEFAULT_TYPE, app_id: int):
    """Deletes a web app."""
    # This is a bit of a hack. Since we don't have chat_id, we can't refresh the list.
    # We'll just delete and send the user back to chat selection.
    db.delete_web_app(app_id)
    await query.answer("Web App удалено.", show_alert=True)
    await private_chat_entry_point(update=query, context=context)

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
    elif command == "toggle_exclude": await toggle_exclude_participant(query, int(params[0]), int(params[1]), int(params[2]))
    elif command == "clean_participants": await clean_participants(query, int(params[0]))
    elif command == "add_user_fw_start": await add_user_via_forward_start(query, context, int(params[0]))
    elif command == "start_poll": await start_poll(query, context, int(params[0]))
    elif command == "delete_poll_confirm": await delete_poll_confirm(query, int(params[0]))
    elif command == "delete_poll_execute": await delete_poll_execute(query, int(params[0]))
    elif command == "close_poll": await close_poll(query, context, int(params[0]))
    elif command == "reopen_poll": await reopen_poll(query, context, int(params[0]))
    elif command == "wizard_start": await wizard_start(query, context, int(params[0]))
    elif command == "wizard_set_type": await wizard_set_type(query, context, params[0], int(params[1]))
    elif command == "wizard_set_webapp": await wizard_set_webapp(query, context, int(params[0]))
    elif command == "webapp_menu": await show_webapp_management_menu(query, int(params[0]))
    elif command == "webapp_add_start": await webapp_add_start(query, context, int(params[0]))
    elif command == "webapp_delete_confirm": await webapp_delete_confirm(query, context, int(params[0]))
    elif command == "webapp_delete_execute": await webapp_delete_execute(query, context, int(params[0]))

    # Dummy handler for no-op callbacks
    elif command == "noop":
        await query.answer()
    # Other handlers will be added here 