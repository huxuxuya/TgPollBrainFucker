from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, CallbackQuery
from telegram.ext import ContextTypes
from telegram.constants import ParseMode
from telegram.helpers import escape_markdown
import telegram

from src import database as db
from src.config import logger
from src.display import generate_poll_text

async def wizard_start(query: CallbackQuery, context: ContextTypes.DEFAULT_TYPE, chat_id: int):
    """Starts the poll creation wizard."""
    context.user_data['wizard_chat_id'] = chat_id
    context.user_data['wizard_state'] = 'waiting_for_title'
    await query.edit_message_text(
        "Введите название опроса. Вы сможете его изменить позже.",
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("❌ Отмена", callback_data=f"dash:group:{chat_id}")]])
    )

# +++ Poll Actions Handlers (called from dashboard) +++

async def start_poll(query: CallbackQuery, context: ContextTypes.DEFAULT_TYPE, poll_id: int):
    """Activates a draft poll and sends it to the group."""
    poll = db.get_poll(poll_id)
    if not poll or poll.status != 'draft':
        await query.answer('Опрос не является черновиком или не найден.', show_alert=True)
        return
    if not poll.message or not poll.options:
        await query.answer('Текст или варианты опроса не заданы.', show_alert=True)
        return

    initial_text = generate_poll_text(poll.poll_id)
    options = poll.options.split(',')
    kb = [[InlineKeyboardButton(opt.strip(), callback_data=f'vote:{poll.poll_id}:{i}')] for i, opt in enumerate(options)]
    
    try:
        msg = await context.bot.send_message(chat_id=poll.chat_id, text=initial_text, reply_markup=InlineKeyboardMarkup(kb), parse_mode=ParseMode.MARKDOWN_V2)
        poll.status = 'active'
        poll.message_id = msg.message_id
        db.commit_session()
        await query.answer(f'Опрос {poll.poll_id} запущен.', show_alert=True)
        await show_poll_list(query, poll.chat_id, 'draft')
    except Exception as e:
        logger.error(f"Ошибка запуска опроса {poll_id}: {e}")
        await query.answer(f'Ошибка: {e}', show_alert=True)

async def close_poll(query: CallbackQuery, context: ContextTypes.DEFAULT_TYPE, poll_id: int):
    """Closes an active poll."""
    poll = db.get_poll(poll_id)
    if not poll or poll.status != 'active':
        await query.answer("Опрос не активен.", show_alert=True)
        return

    poll.status = 'closed'
    db.commit_session()

    final_text = generate_poll_text(poll_id)
    try:
        if poll.message_id:
            await context.bot.edit_message_text(chat_id=poll.chat_id, message_id=poll.message_id, text=final_text, reply_markup=None, parse_mode=ParseMode.MARKDOWN_V2)
        await query.answer("Опрос завершён.", show_alert=True)
    except telegram.error.BadRequest as e:
        if "Message is not modified" in str(e):
            logger.info(f"Poll {poll_id} message was not modified on close, ignoring.")
            await query.answer("Опрос завершён.", show_alert=True)
        else:
            logger.error(f"Could not edit final message for poll {poll_id}: {e}")
            await query.answer("Опрос завершён, но не удалось обновить сообщение в чате.", show_alert=True)
    except Exception as e:
        logger.error(f"An unexpected error occurred while closing poll {poll_id}: {e}")
        await query.answer("Произошла неожиданная ошибка при завершении опроса.", show_alert=True)

    await show_group_dashboard(query, context, poll.chat_id)

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


async def private_chat_entry_point(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_id = update.effective_user.id
    admin_chats = []
    known_chats = db.get_known_chats()
    for chat in known_chats:
        try:
            admins = await context.bot.get_chat_administrators(chat.chat_id)
            if user_id in [admin.user.id for admin in admins]:
                admin_chats.append(type('Chat', (), {'id': chat.chat_id, 'title': chat.title, 'type': 'group'}))
        except Exception as e:
            logger.error(f'Error checking admin status in known chat {chat.chat_id}: {e}')

    if not admin_chats:
        await update.effective_message.reply_text("Я не нашел групп, где вы являетесь администратором и я тоже.")
        return

    keyboard = [[InlineKeyboardButton(chat.title, callback_data=f'dash:group:{chat.id}')] for chat in admin_chats]
    await update.effective_message.reply_text('Выберите чат для управления:', reply_markup=InlineKeyboardMarkup(keyboard))

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
        name = escape_markdown(db.get_user_name(p.user_id), 2)
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

async def show_exclude_menu(query: CallbackQuery, chat_id: int, page: int = 0):
    """Displays a paginated menu to exclude/include participants."""
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
        name = db.get_user_name(p.user_id)
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

async def dashboard_callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    
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
    elif command == "wizard_start": await wizard_start(query, context, int(params[0]))
    # Other handlers will be added here 