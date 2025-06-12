import logging
import os
import time
from typing import Union

from dotenv import load_dotenv
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, CallbackQuery
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, ContextTypes, MessageHandler, filters, TypeHandler
from telegram.constants import ParseMode, ChatAction
from telegram.error import ChatMigrated
from telegram.helpers import escape_markdown

from src.database import init_database, run_migration, add_user_to_participants as db_add_user, update_known_chats as db_update_chats, get_group_title as db_get_group_title, get_user_name as db_get_user_name, session, Poll, Response, PollSetting, PollOptionSetting, Participant, KnownChat

# Load environment variables from .env file
load_dotenv()

# Получение токена из переменной окружения
try:
    BOT_TOKEN = os.environ['BOT_TOKEN']
except KeyError:
    raise RuntimeError('Переменная окружения BOT_TOKEN не установлена!')

# Enable logging
logging.basicConfig(format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO)
logger = logging.getLogger(__name__)

# Database setup
init_database()

BOT_OWNER_ID = None

async def backup_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global BOT_OWNER_ID
    user_id = update.effective_user.id
    if BOT_OWNER_ID is None:
        BOT_OWNER_ID = user_id
    if user_id != BOT_OWNER_ID:
        await update.message.reply_text("Только владелец бота может делать резервную копию.")
        return
    db_path = 'poll_data.db'
    if not os.path.exists(db_path):
        await update.message.reply_text("Файл базы данных не найден.")
        return
    await update.message.reply_chat_action(ChatAction.UPLOAD_DOCUMENT)
    await update.message.reply_document(open(db_path, 'rb'), filename='poll_data.db', caption='Резервная копия базы данных.')

async def restore_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global BOT_OWNER_ID
    user_id = update.effective_user.id
    if BOT_OWNER_ID is None:
        BOT_OWNER_ID = user_id
    if user_id != BOT_OWNER_ID:
        await update.message.reply_text("Только владелец бота может загружать резервную копию.")
        return
    await update.message.reply_text("Пожалуйста, отправьте файл poll_data.db в ответ на это сообщение.")
    context.user_data['awaiting_restore'] = True

async def document_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global BOT_OWNER_ID
    user_id = update.effective_user.id
    if not context.user_data.get('awaiting_restore'):
        return
    if user_id != BOT_OWNER_ID:
        await update.message.reply_text("Только владелец бота может загружать резервную копию.")
        return
    document = update.message.document
    if document.file_name != 'poll_data.db':
        await update.message.reply_text("Имя файла должно быть poll_data.db")
        return
    file = await document.get_file()
    await file.download_to_drive('poll_data.db')
    context.user_data['awaiting_restore'] = False
    await update.message.reply_text("База данных успешно восстановлена. Перезапустите бота для применения изменений.")

async def add_user_to_participants(update: Update, context: ContextTypes.DEFAULT_TYPE = None):
    user = update.effective_user
    chat = update.effective_chat
    if user and chat and chat.type in ['group', 'supergroup']:
        db_add_user(chat.id, user.id, user.username, user.first_name, user.last_name)

async def update_known_chats(chat_id: int, title: str) -> None:
    db_update_chats(chat_id, title)

async def get_admin_chats(update: Update, context: ContextTypes.DEFAULT_TYPE) -> list:
    user_id = update.effective_user.id
    admin_chats = []
    known_chats = session.query(KnownChat).all()
    for chat in known_chats:
        try:
            admins = await context.bot.get_chat_administrators(chat.chat_id)
            if user_id in [admin.user.id for admin in admins]:
                admin_chats.append(type('Chat', (), {'id': chat.chat_id, 'title': chat.title, 'type': 'group'}))
        except Exception as e:
            logger.error(f'Error checking admin status in known chat {chat.chat_id}: {e}')
    return admin_chats

def get_group_title(chat_id: int) -> str:
    return db_get_group_title(chat_id)

def get_user_name(user_id: int, markdown_link: bool = False) -> str:
    return db_get_user_name(user_id, markdown_link)

def get_progress_bar(progress, total, length=20):
    if total <= 0: return "[]", 0
    percent = progress / total
    filled_length = int(length * percent)
    bar = '█' * filled_length + '░' * (length - filled_length)
    return f"[{bar}]", percent * 100

# --- Poll Display Logic ---

def generate_poll_text(poll_id: int) -> str:
    poll = session.query(Poll).filter_by(poll_id=poll_id).first()
    if not poll: return "Опрос не найден."
    
    message, options_str = poll.message, poll.options
    original_options = [opt.strip() for opt in options_str.split(',')]
    
    responses = session.query(Response).filter_by(poll_id=poll_id).all()
    counts = {opt: 0 for opt in original_options}
    for resp in responses:
        if resp.response in counts: counts[resp.response] += 1
        
    poll_setting = session.query(PollSetting).filter_by(poll_id=poll_id).first()
    default_show_names = 1
    target_sum = 0
    default_show_count = 1
    if poll_setting:
        default_show_names = poll_setting.default_show_names
        target_sum = poll_setting.target_sum
        default_show_count = poll_setting.default_show_count
    
    total_votes = len(responses)
    total_collected = 0
    text_parts = [escape_markdown(message, version=1), ""]

    options_with_settings = []
    for i, option_text in enumerate(original_options):
        opt_setting = session.query(PollOptionSetting).filter_by(poll_id=poll_id, option_index=i).first()
        options_with_settings.append({
            'text': option_text,
            'show_names': opt_setting.show_names if opt_setting and opt_setting.show_names is not None else default_show_names,
            'names_style': opt_setting.names_style if opt_setting and opt_setting.names_style else 'list',
            'is_priority': opt_setting.is_priority if opt_setting else 0,
            'contribution_amount': opt_setting.contribution_amount if opt_setting else 0,
            'emoji': (opt_setting.emoji + ' ') if opt_setting and opt_setting.emoji else "",
            'show_count': opt_setting.show_count if opt_setting and opt_setting.show_count is not None else default_show_count,
            'show_contribution': opt_setting.show_contribution if opt_setting and opt_setting.show_contribution is not None else 1,
        })

    options_with_settings.sort(key=lambda x: x['is_priority'], reverse=True)

    for option_data in options_with_settings:
        option_text = option_data['text']
        count = counts.get(option_text, 0)
        contribution = option_data['contribution_amount']
        if contribution > 0: total_collected += count * contribution
            
        marker = "⭐ " if option_data['is_priority'] else ""
        escaped_option_text = escape_markdown(option_text, version=1)
        formatted_text = f"*{escaped_option_text}*" if option_data['is_priority'] else escaped_option_text
        line = f"{marker}{formatted_text}"
        if contribution > 0 and option_data['show_contribution']:
            line += f" (по {int(contribution)})"
        if option_data['show_count']:
            line += f": *{count}*"
        text_parts.append(line)

        if option_data['show_names'] and count > 0:
            responders = [r.user_id for r in responses if r.response == option_text]
            user_names = [get_user_name(uid, markdown_link=True) for uid in responders]
            names_list = [f"{option_data['emoji']}{name}" for name in user_names]
            indent = "    "
            if option_data['names_style'] == 'list': text_parts.append("\n".join(f"{indent}{name}" for name in names_list))
            elif option_data['names_style'] == 'inline': text_parts.append(f'{indent}{", ".join(names_list)}')
            elif option_data['names_style'] == 'numbered': text_parts.append("\n".join(f"{indent}{i}. {name}" for i, name in enumerate(names_list, 1)))
        text_parts.append("")

    if target_sum > 0:
        bar, percent = get_progress_bar(total_collected, target_sum)
        text_parts.append(f"💰 Собрано: *{int(total_collected)} из {int(target_sum)}* ({percent:.1f}%)\n{bar}")
    elif total_collected > 0:
        text_parts.append(f"💰 Собрано: *{int(total_collected)}*")
    
    while text_parts and text_parts[-1] == "": text_parts.pop()
    text_parts.append(f"\nВсего проголосовало: *{total_votes}*")
    return "\n".join(text_parts)

async def generate_nudge_text(poll_id: int, context: ContextTypes.DEFAULT_TYPE) -> str:
    poll = session.query(Poll).filter_by(poll_id=poll_id).first()
    if not poll: return "Опрос не найден."
    chat_id = poll.chat_id

    participants = session.query(Participant).filter_by(chat_id=chat_id, excluded=0).all()
    participant_ids = {p.user_id for p in participants}

    respondents = session.query(Response).filter_by(poll_id=poll_id).all()
    respondent_ids = {r.user_id for r in respondents}
    
    non_voters = participant_ids - respondent_ids

    poll_setting = session.query(PollSetting).filter_by(poll_id=poll_id).first()
    neg_emoji = poll_setting.nudge_negative_emoji if poll_setting and poll_setting.nudge_negative_emoji else '❌'

    text_parts = ["📢 *Ждем вашего голоса:*"]
    
    if not non_voters:
        text_parts.append("\n_Все участники проголосовали!_ 🎉")
    else:
        text_parts.append("\n")
        sorted_non_voters = sorted(list(non_voters), key=lambda uid: get_user_name(uid))
        for user_id in sorted_non_voters:
            user_mention = get_user_name(user_id, markdown_link=True)
            text_parts.append(f"{neg_emoji} {user_mention}")

    return "\n".join(text_parts)

async def update_nudge_message(poll_id: int, context: ContextTypes.DEFAULT_TYPE):
    logger.info(f"Attempting to update nudge message for poll {poll_id}")
    poll = session.query(Poll).filter_by(poll_id=poll_id).first()
    if not poll: return
    
    chat_id, nudge_message_id = poll.chat_id, poll.nudge_message_id
    if not nudge_message_id:
        logger.info(f"No nudge message to update for poll {poll_id}.")
        return

    try:
        new_text = await generate_nudge_text(poll_id, context)
        await context.bot.edit_message_text(
            text=new_text,
            chat_id=chat_id,
            message_id=nudge_message_id,
            parse_mode=ParseMode.MARKDOWN
        )
        logger.info(f"Successfully updated nudge message {nudge_message_id} for poll {poll_id}")
    except Exception as e:
        if "Message is not modified" not in str(e):
            logger.error(f"Failed to update nudge message {nudge_message_id} for poll {poll_id}: {e}")
            if "message to edit not found" in str(e).lower():
                # Message was deleted, so we clear the ID
                poll.nudge_message_id = None
                session.commit()

async def update_poll_message(poll_id: int, context: ContextTypes.DEFAULT_TYPE):
    logger.info(f"[POLL_UPDATE] Updating message for poll_id={poll_id}")
    poll = session.query(Poll).filter_by(poll_id=poll_id).first()
    if not poll or not poll.message_id: return
        
    chat_id, message_id, options_str = poll.chat_id, poll.message_id, poll.options
    new_text = generate_poll_text(poll_id)
    options = [opt.strip() for opt in options_str.split(',')]
    keyboard = [[InlineKeyboardButton(opt, callback_data=f'poll_{poll_id}_{i}')] for i, opt in enumerate(options)]
    
    try:
        await context.bot.edit_message_text(text=new_text, chat_id=chat_id, message_id=message_id, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode=ParseMode.MARKDOWN)
    except ChatMigrated as e:
        logger.warning(f"Chat migrated for poll {poll_id}. Old: {chat_id}, New: {e.new_chat_id}")
        poll.chat_id = e.new_chat_id
        session.commit()
    except Exception as e:
        if "Message is not modified" not in str(e): logger.error(f"Failed to edit message for poll {poll_id}: {e}")

# --- Core Commands & Entry Points ---

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await add_user_to_participants(update, context)
    if update.effective_chat.type in ['group', 'supergroup']:
        await update_known_chats(update.effective_chat.id, update.effective_chat.title)
        me = await context.bot.get_me()
        await update.message.reply_text(f"Привет! Для управления опросами, напишите мне: @{me.username}")
    else:
        await private_chat_entry_point(update, context)

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await add_user_to_participants(update, context)
    if update.effective_chat.type == 'private': await private_chat_entry_point(update, context)
    else: await update.message.reply_text('Команды: /start, /help. Управление опросами в ЛС.')

async def toggle_debug(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    context.bot_data['debug_mode_enabled'] = not context.bot_data.get('debug_mode_enabled', False)
    status = "включен" if context.bot_data['debug_mode_enabled'] else "отключен"
    await update.message.reply_text(f"Режим отладки {status}.")

async def log_all_updates(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if context.bot_data.get('debug_mode_enabled', False): logger.info(f"[DEBUG_UPDATE]: {update.to_dict()}")

# --- Dashboard UI ---

def build_group_dashboard_content(chat_id: int, user_id: int) -> (str, InlineKeyboardMarkup):
    chat_title = get_group_title(chat_id)
    text = f"Панель управления для чата *{escape_markdown(chat_title, 1)}*:"
    
    keyboard = [
        [InlineKeyboardButton("📊 Активные опросы", callback_data=f'dash_polls_{chat_id}_active'),
         InlineKeyboardButton("📈 Завершенные опросы", callback_data=f'dash_polls_{chat_id}_closed')],
        [InlineKeyboardButton("👥 Участники", callback_data=f'dash_participants_menu_{chat_id}')],
        [InlineKeyboardButton("✏️ Создать опрос", callback_data=f'dash_wizard_start_{chat_id}')],
        [InlineKeyboardButton("🔙 Назад к выбору чата", callback_data='dash_back_to_chats')]
    ]
    return text, InlineKeyboardMarkup(keyboard)

async def private_chat_entry_point(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_id = update.effective_user.id
    admin_chats = await get_admin_chats(update, context)
    global BOT_OWNER_ID
    if BOT_OWNER_ID is None:
        BOT_OWNER_ID = user_id
        logger.info(f"Set BOT_OWNER_ID to {user_id} as the first user to access dashboard")
    
    text, kb = "Добро пожаловать! Выберите группу:", [[InlineKeyboardButton(c.title, callback_data=f"dash_group_{c.id}")] for c in admin_chats]
    if not admin_chats: text, kb = 'Я не знаю групп, где вы админ.', []
    
    if BOT_OWNER_ID is not None and user_id == BOT_OWNER_ID:
        kb.append([InlineKeyboardButton("⚙️ Настройки бота", callback_data="admin_settings")])
    
    if update.callback_query: await update.callback_query.message.edit_text(text, reply_markup=InlineKeyboardMarkup(kb))
    else: await context.bot.send_message(chat_id=user_id, text=text, reply_markup=InlineKeyboardMarkup(kb))

async def show_group_dashboard(query: CallbackQuery, context: ContextTypes.DEFAULT_TYPE, chat_id: int):
    text, keyboard = build_group_dashboard_content(chat_id, query.from_user.id)
    await query.message.edit_text(text, reply_markup=keyboard, parse_mode=ParseMode.MARKDOWN)

async def show_poll_list(query: CallbackQuery, chat_id: int, status: str):
    polls = session.query(Poll).filter_by(chat_id=chat_id, status=status).order_by(Poll.poll_id.desc()).all()
    status_text_map = {'active': 'активных опросов', 'draft': 'черновиков', 'closed': 'завершённых опросов'}
    status_text = status_text_map.get(status, f'{status} опросов')

    if not polls:
        text = f"Нет {status_text} в этой группе."
        kb = [[InlineKeyboardButton("↩️ Назад", callback_data=f"dash_group_{chat_id}")]]
        await query.message.edit_text(text, reply_markup=InlineKeyboardMarkup(kb))
        return

    status_title_map = {'active': 'Активные опросы', 'draft': 'Черновики', 'closed': 'Завершённые опросы'}
    text = f'*{status_title_map.get(status, status.capitalize())}*:'
    kb = []
    for poll in polls:
        msg = (poll.message or f'Опрос {poll.poll_id}')[:40]
        if status == 'active':
            kb.append([InlineKeyboardButton(msg, callback_data=f"results_{poll.poll_id}")])
        elif status == 'draft':
            kb.append([
                InlineKeyboardButton(msg, callback_data=f"setresultoptionspoll_{poll.poll_id}"),
                InlineKeyboardButton("▶️", callback_data=f"dash_startpoll_{poll.poll_id}"),
                InlineKeyboardButton("🗑", callback_data=f"dash_deletepoll_{poll.poll_id}")
            ])
        elif status == 'closed':
            kb.append([
                InlineKeyboardButton(msg, callback_data=f"results_{poll.poll_id}"),
                InlineKeyboardButton("🗑", callback_data=f"dash_deletepoll_{poll.poll_id}")
            ])
    kb.append([InlineKeyboardButton("↩️ Назад", callback_data=f"dash_group_{chat_id}")])
    await query.message.edit_text(text, reply_markup=InlineKeyboardMarkup(kb), parse_mode=ParseMode.MARKDOWN)

async def show_participants_menu(query: CallbackQuery, chat_id: int):
    text = f'👥 *Управление участниками ("{get_group_title(chat_id)}")*'
    kb = [
        [InlineKeyboardButton("📄 Показать список", callback_data=f"dash_participants_{chat_id}_list")],
        [InlineKeyboardButton("🚫 Исключить/вернуть", callback_data=f"dash_participants_{chat_id}_exclude")],
        [InlineKeyboardButton("🧹 Очистить список", callback_data=f"dash_participants_{chat_id}_clean")],
        [InlineKeyboardButton("↩️ Назад", callback_data=f"dash_group_{chat_id}")]
    ]
    await query.message.edit_text(text, reply_markup=InlineKeyboardMarkup(kb), parse_mode=ParseMode.MARKDOWN)

async def show_participants_list(query: CallbackQuery, context: ContextTypes.DEFAULT_TYPE, chat_id: int, page: int = 0):
    participants = session.query(Participant).filter_by(chat_id=chat_id).order_by(Participant.first_name, Participant.last_name).all()
    
    title = get_group_title(chat_id)

    if not participants:
        text = f"В чате «{title}» нет зарегистрированных участников."
        kb = [[InlineKeyboardButton("↩️ Назад", callback_data=f"dash_participants_{chat_id}_menu")]]
        await query.message.edit_text(text, reply_markup=InlineKeyboardMarkup(kb))
        return

    items_per_page = 50
    start_index = page * items_per_page
    end_index = start_index + items_per_page
    paginated_participants = participants[start_index:end_index]
    total_pages = -(-len(participants) // items_per_page)

    text_parts = [f'👥 *Список участников («{title}»)* (Стр. {page + 1}/{total_pages}):\n']
    
    for i, participant in enumerate(paginated_participants, start=start_index + 1):
        name = participant.first_name or ''
        if participant.last_name: name += f' {participant.last_name}'
        name = name.strip()
        if not name: name = f'@{participant.username}' if participant.username else "Без имени"
        
        name = escape_markdown(name, version=1)
        status = " (🚫)" if participant.excluded else ""
        text_parts.append(f"{i}. {name}{status}")
    
    text = "\n".join(text_parts)
    
    kb_rows = []
    nav_buttons = []
    if page > 0:
        nav_buttons.append(InlineKeyboardButton("⬅️ Назад", callback_data=f"dash_participants_{chat_id}_list_{page - 1}"))
    if end_index < len(participants):
        nav_buttons.append(InlineKeyboardButton("Вперед ➡️", callback_data=f"dash_participants_{chat_id}_list_{page + 1}"))
    
    if nav_buttons:
        kb_rows.append(nav_buttons)
    
    kb_rows.append([InlineKeyboardButton("↩️ В меню", callback_data=f"dash_participants_{chat_id}_menu")])
    
    try:
        await query.message.edit_text(text, reply_markup=InlineKeyboardMarkup(kb_rows), parse_mode=ParseMode.MARKDOWN)
    except Exception as e:
        if "Message is not modified" not in str(e):
            logger.error(f"Error showing participants list: {e}")
        await query.answer()

async def show_exclude_menu(query: CallbackQuery, context: ContextTypes.DEFAULT_TYPE, chat_id: int, page: int = 0):
    c.execute('SELECT user_id, MAX(first_name) as first, MAX(last_name) as last, MAX(username) as user, MAX(excluded) as ex FROM participants WHERE chat_id = ? GROUP BY user_id ORDER BY first, last', (chat_id,))
    participants = c.fetchall()
    
    title = get_group_title(chat_id)

    if not participants:
        text = f"В чате «{title}» нет зарегистрированных участников для исключения."
        kb = [[InlineKeyboardButton("↩️ Назад", callback_data=f"dash_participants_{chat_id}_menu")]]
        await query.message.edit_text(text, reply_markup=InlineKeyboardMarkup(kb))
        return

    items_per_page = 20
    start_index = page * items_per_page
    end_index = start_index + items_per_page
    paginated_participants = participants[start_index:end_index]
    total_pages = -(-len(participants) // items_per_page)

    text = f'👥 *Исключение/возврат («{title}»)* (Стр. {page + 1}/{total_pages}):\nНажмите на участника, чтобы изменить его статус.'
    
    kb = []
    for user_id, first_name, last_name, username, excluded in paginated_participants:
        name = first_name or ''
        if last_name: name += f' {last_name}'
        name = name.strip()
        if not name: name = f'@{username}' if username else f"User ID: {user_id}"
        
        status_icon = "🚫" if excluded else "✅"
        button_text = f"{status_icon} {name}"
        callback_data = f"dash_participants_{chat_id}_toggle_{user_id}_{page}"
        kb.append([InlineKeyboardButton(button_text, callback_data=callback_data)])
    
    nav_buttons = []
    if page > 0:
        nav_buttons.append(InlineKeyboardButton("⬅️", callback_data=f"dash_participants_{chat_id}_exclude_{page-1}"))
    if end_index < len(participants):
        nav_buttons.append(InlineKeyboardButton("➡️", callback_data=f"dash_participants_{chat_id}_exclude_{page+1}"))
    
    if nav_buttons:
        kb.append(nav_buttons)

    kb.append([InlineKeyboardButton("↩️ Назад", callback_data=f"dash_participants_{chat_id}_menu")])
    
    await query.message.edit_text(text, reply_markup=InlineKeyboardMarkup(kb), parse_mode=ParseMode.MARKDOWN)

async def wizard_start(query: CallbackQuery, context: ContextTypes.DEFAULT_TYPE, chat_id: int):
    user_id = query.from_user.id
    # Store message details to edit it later
    context.user_data.update({
        'wizard_state': 'waiting_for_title',
        'wizard_chat_id': chat_id,
        'wizard_message_id': query.message.message_id
    })
    await query.message.edit_text(
        "✨ *Мастер создания (1/2)*: Отправьте заголовок опроса.",
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("❌ Отмена", callback_data=f"dash_group_{chat_id}")]])
    )

async def startpoll_from_dashboard(query: CallbackQuery, context: ContextTypes.DEFAULT_TYPE, poll_id: int, chat_id: int):
    c.execute('SELECT message, options FROM polls WHERE poll_id = ? AND status = ?', (poll_id, 'draft'))
    result = c.fetchone()
    if not result or not result[0] or not result[1]:
        await query.answer('Текст или варианты опроса не заданы.', show_alert=True)
        return

    initial_text = generate_poll_text(poll_id)
    options = result[1].split(',')
    kb = [[InlineKeyboardButton(opt.strip(), callback_data=f'poll_{poll_id}_{i}')] for i, opt in enumerate(options)]
    
    try:
        msg = await context.bot.send_message(chat_id=chat_id, text=initial_text, reply_markup=InlineKeyboardMarkup(kb), parse_mode=ParseMode.MARKDOWN)
        c.execute('UPDATE polls SET status = ?, message_id = ? WHERE poll_id = ?', ('active', msg.message_id, poll_id))
        conn.commit()
        await query.answer(f'Опрос {poll_id} запущен.', show_alert=True)
    except Exception as e:
        logger.error(f"Ошибка запуска опроса {poll_id}: {e}")
        await query.answer(f'Ошибка: {e}', show_alert=True)

async def close_poll(query: CallbackQuery, context: ContextTypes.DEFAULT_TYPE, poll_id: int):
    c.execute('SELECT chat_id, message_id FROM polls WHERE poll_id = ? AND status = ?', (poll_id, 'active'))
    poll_data = c.fetchone()

    if not poll_data:
        await query.answer("Опрос не найден или уже не активен.", show_alert=True)
        return

    chat_id, message_id = poll_data

    c.execute('UPDATE polls SET status = ? WHERE poll_id = ?', ('closed', poll_id))
    conn.commit()

    final_text = generate_poll_text(poll_id)
    try:
        if message_id:
            await context.bot.edit_message_text(
                chat_id=chat_id,
                message_id=message_id,
                text=final_text,
                reply_markup=None,
                parse_mode=ParseMode.MARKDOWN
            )
        await query.answer("Опрос завершён.", show_alert=True)
    except Exception as e:
        logger.error(f"Could not edit final message for poll {poll_id}: {e}")
        await query.answer(f"Опрос завершён, но не удалось обновить сообщение в чате.", show_alert=True)

    await show_group_dashboard(query, context, chat_id)

async def setresultoptions(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    poll_id = int(query.data.split('_')[1])
    
    c.execute('SELECT options, chat_id, status FROM polls WHERE poll_id = ?', (poll_id,))
    row = c.fetchone()
    if not row:
        await query.answer('Опрос не найден.', show_alert=True)
        return
    options, chat_id, status = row
    
    kb = [[InlineKeyboardButton(f"Настроить: {opt.strip()}", callback_data=f'setresopt_{poll_id}_{i}_menu')] for i, opt in enumerate(options.split(','))]
    kb.append([InlineKeyboardButton("⚙️ Общие настройки опроса", callback_data=f"setpollsettings_{poll_id}_menu")])
    kb.append([InlineKeyboardButton("↩️ Назад к списку", callback_data=f"dash_polls_{chat_id}_{status}")])
    await query.message.edit_text(
        'Выберите вариант для детальной настройки или перейдите к общим настройкам:',
        reply_markup=InlineKeyboardMarkup(kb)
    )

async def show_results(update: Update, context: ContextTypes.DEFAULT_TYPE, poll_id: int):
    query = update.callback_query
    poll = session.query(Poll).filter_by(poll_id=poll_id).first()
    if not poll:
        await query.edit_message_text("Опрос не найден.")
        return

    status, group_chat_id, nudge_message_id = poll.status, poll.chat_id, poll.nudge_message_id
    result_text = generate_poll_text(poll_id)
    
    kb_rows = []
    if status == 'active':
        kb_rows.append([
            InlineKeyboardButton("🔄 Обновить", callback_data=f"refreshresults_{poll_id}"),
            InlineKeyboardButton("⏹️ Завершить", callback_data=f"dash_closepoll_{poll_id}")
        ])
        
        if nudge_message_id:
            nudge_button = InlineKeyboardButton("🗑️ Убрать оповещение", callback_data=f"dash_delnudge_{poll_id}")
        else:
            nudge_button = InlineKeyboardButton("📢 Позвать неголосующих", callback_data=f"nudge_{poll_id}")
        
        kb_rows.append([nudge_button])
        kb_rows.append([InlineKeyboardButton("⏬ Переместить в конец чата", callback_data=f"movetobottom_{poll_id}")])

    kb_rows.append([InlineKeyboardButton("⚙️ Настроить", callback_data=f"setresultoptionspoll_{poll_id}")])
    kb_rows.append([InlineKeyboardButton("↩️ К списку", callback_data=f"dash_polls_{group_chat_id}_{status}")])
    
    try:
        await query.edit_message_text(text=result_text, reply_markup=InlineKeyboardMarkup(kb_rows), parse_mode=ParseMode.MARKDOWN)
        if query.data.startswith('refreshresults_'):
            await query.answer("Результаты обновлены.")
    except Exception as e:
        if "Message is not modified" not in str(e):
            logger.warning(f"Could not edit results msg: {e}")
        else:
            await query.answer("Нет изменений.")

async def nudge_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    poll_id = int(query.data.split('_')[1])

    c.execute('SELECT chat_id, message_id, nudge_message_id FROM polls WHERE poll_id = ? AND status = ?', (poll_id, 'active'))
    poll_data = c.fetchone()

    if not poll_data:
        await query.answer("Не удалось найти активный опрос.", show_alert=True)
        return

    chat_id, poll_message_id, nudge_message_id = poll_data
    
    if nudge_message_id:
        await query.answer("Обновляю список...", show_alert=False)
        await update_nudge_message(poll_id, context)
    else:
        await query.answer("Создаю список для оповещения...", show_alert=False)
        try:
            nudge_text = await generate_nudge_text(poll_id, context)
            msg = await context.bot.send_message(
                chat_id=chat_id,
                text=nudge_text,
                reply_to_message_id=poll_message_id,
                parse_mode=ParseMode.MARKDOWN,
                disable_notification=False
            )
            c.execute('UPDATE polls SET nudge_message_id = ? WHERE poll_id = ?', (msg.message_id, poll_id))
            conn.commit()
            logger.info(f"Created nudge message {msg.message_id} for poll {poll_id} as reply to {poll_message_id}")
            await show_results(update, context, poll_id)
        except Exception as e:
            logger.error(f"Failed to send nudge message for poll {poll_id}: {e}")
            await query.answer(f"Ошибка при создании списка: {e}", show_alert=True)

async def move_to_bottom_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    poll_id = int(query.data.split('_')[1])
    
    c.execute('SELECT chat_id, message_id, options FROM polls WHERE poll_id = ? AND status = ?', (poll_id, 'active'))
    poll_data = c.fetchone()
    
    if not poll_data:
        await query.answer("Не удалось найти активный опрос.", show_alert=True)
        return
        
    chat_id, old_message_id, options_str = poll_data
    
    await query.answer("Перемещаю опрос...")

    # 1. Delete the old message
    try:
        if old_message_id:
            await context.bot.delete_message(chat_id=chat_id, message_id=old_message_id)
    except Exception as e:
        logger.warning(f"Could not delete old poll message {old_message_id} in chat {chat_id}: {e}")

    # 2. Send a new message silently
    try:
        new_text = generate_poll_text(poll_id)
        options = [opt.strip() for opt in options_str.split(',')]
        keyboard = [[InlineKeyboardButton(opt, callback_data=f'poll_{poll_id}_{i}')] for i, opt in enumerate(options)]
        
        new_message = await context.bot.send_message(
            chat_id=chat_id,
            text=new_text,
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode=ParseMode.MARKDOWN,
            disable_notification=True
        )
        
        # 3. Update the message_id in the database
        c.execute('UPDATE polls SET message_id = ? WHERE poll_id = ?', (new_message.message_id, poll_id))
        conn.commit()
        
    except Exception as e:
        logger.error(f"Failed to resend poll {poll_id} silently: {e}")
        try:
            await query.edit_message_text(text=query.message.text + f"\n\nОшибка при перемещении опроса: {e}")
        except:
            pass # Ignore if we can't edit the message

# --- Admin Vote Editing ---

async def show_poll_list_for_editing(query: CallbackQuery, chat_id: int):
    """Показывает список опросов для редактирования голосов."""
    c.execute("SELECT poll_id, message FROM polls WHERE chat_id = ? AND status = 'active' ORDER BY poll_id DESC", (chat_id,))
    polls = c.fetchall()
    
    if not polls:
        await query.answer("В этом чате нет активных опросов для редактирования.", show_alert=True)
        return

    keyboard = []
    for poll_id, message in polls:
        keyboard.append([InlineKeyboardButton(message[:50], callback_data=f'admin_edit_poll_{poll_id}')])
    
    keyboard.append([InlineKeyboardButton("🔙 Назад", callback_data=f'dash_show_{chat_id}')])
    
    await query.edit_message_text(
        "Выберите опрос для редактирования голосов:",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )

async def show_poll_options_for_editing(query: CallbackQuery, poll_id: int):
    """Показывает варианты ответа в опросе для выбора."""
    c.execute('SELECT options FROM polls WHERE poll_id = ?', (poll_id,))
    res = c.fetchone()
    if not res:
        await query.answer("Опрос не найден.", show_alert=True)
        return
    options_str = res[0]
    options = [opt.strip() for opt in options_str.split(',')]
    
    keyboard = []
    for i, option_text in enumerate(options):
        keyboard.append([InlineKeyboardButton(option_text, callback_data=f'admin_edit_option_{poll_id}_{i}')])

    c.execute('SELECT chat_id FROM polls WHERE poll_id = ?', (poll_id,))
    chat_id_res = c.fetchone()
    if chat_id_res:
        keyboard.append([InlineKeyboardButton("🔙 Назад к опросам", callback_data=f'dash_edit_votes_polls_{chat_id_res[0]}')])
    
    await query.edit_message_text(
        "Выберите вариант ответа, чтобы добавить голос:",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )

async def show_users_for_adding_vote(query: CallbackQuery, poll_id: int, option_index: int, page: int = 0):
    """Показывает список участников для добавления голоса."""
    c.execute('SELECT chat_id, options FROM polls WHERE poll_id = ?', (poll_id,))
    res = c.fetchone()
    if not res:
        await query.answer("Опрос не найден.", show_alert=True)
        return
    chat_id, options_str = res
    options = [opt.strip() for opt in options_str.split(',')]
    if option_index >= len(options):
        await query.answer("Неверный вариант ответа.", show_alert=True)
        return
    selected_option = options[option_index]

    c.execute('SELECT user_id FROM participants WHERE chat_id = ? AND excluded = 0', (chat_id,))
    all_participants = {row[0] for row in c.fetchall()}

    c.execute('SELECT user_id FROM responses WHERE poll_id = ? AND response = ?', (poll_id, selected_option))
    voted_users = {row[0] for row in c.fetchall()}
    
    eligible_users = sorted(list(all_participants - voted_users), key=lambda uid: get_user_name(uid))

    if not eligible_users:
        await query.answer("Все участники чата уже проголосовали за этот вариант или исключены.", show_alert=True)
        return

    items_per_page = 15
    start_index = page * items_per_page
    end_index = start_index + items_per_page
    paginated_users = eligible_users[start_index:end_index]

    keyboard = []
    for user_id in paginated_users:
        user_name = get_user_name(user_id)
        keyboard.append([InlineKeyboardButton(user_name, callback_data=f'admin_add_vote_{poll_id}_{option_index}_{user_id}')])

    nav_buttons = []
    if page > 0:
        nav_buttons.append(InlineKeyboardButton("⬅️", callback_data=f'admin_user_page_{poll_id}_{option_index}_{page-1}'))
    if end_index < len(eligible_users):
        nav_buttons.append(InlineKeyboardButton("➡️", callback_data=f'admin_user_page_{poll_id}_{option_index}_{page+1}'))
    if nav_buttons:
        keyboard.append(nav_buttons)

    keyboard.append([InlineKeyboardButton("🔙 Назад к вариантам", callback_data=f'admin_edit_poll_{poll_id}')])

    await query.edit_message_text(
        f"Выберите пользователя, чтобы добавить его голос за '{escape_markdown(selected_option, 1)}':",
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode=ParseMode.MARKDOWN
    )

async def add_user_vote(query: CallbackQuery, poll_id: int, option_index: int, user_id: int, context: ContextTypes.DEFAULT_TYPE):
    """Добавляет голос пользователя к варианту ответа."""
    c.execute('SELECT options FROM polls WHERE poll_id = ?', (poll_id,))
    res = c.fetchone()
    if not res:
        await query.answer("Опрос не найден.", show_alert=True)
        return
        
    options_str = res[0]
    options = [opt.strip() for opt in options_str.split(',')]
    if option_index >= len(options):
        await query.answer("Неверный вариант ответа.", show_alert=True)
        return
    selected_option = options[option_index]

    c.execute('DELETE FROM responses WHERE poll_id = ? AND user_id = ?', (poll_id, user_id))
    c.execute('INSERT INTO responses (poll_id, user_id, response) VALUES (?, ?, ?)', (poll_id, user_id, selected_option))
    conn.commit()

    user_name = get_user_name(user_id)
    await query.answer(f"Голос от {user_name} добавлен за '{selected_option}'.")

    await show_users_for_adding_vote(query, poll_id, option_index, page=0)
    
    try:
        await update_poll_message(poll_id, context)
        await update_nudge_message(poll_id, context)
    except Exception as e:
        logger.error(f"Error updating messages after adding vote for poll {poll_id}: {e}")

async def dashboard_callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    try:
        await query.answer()
    except Exception as e:
        logger.error(f"Failed to answer callback query: {e}")
    data = query.data.split('_')
    command, params = data[1], data[2:]
    
    # Normalize combined commands like 'wizard_start' or 'edit_votes_polls'
    if command == "wizard" and params and params[0] == "start":
        command = "wizard_start"
        params = params[1:]
    elif command == "edit" and len(params) >= 2 and params[0] == "votes" and params[1] == "polls":
        command = "edit_votes_polls"
        params = params[2:]

    if command == "group":
        if context.user_data: context.user_data.clear()
        await show_group_dashboard(query, context, int(params[0]))
    elif command == "back": await private_chat_entry_point(update, context)
    elif command == "newpoll": await wizard_start(query, context, int(params[0]))
    elif command == "polls":
        if len(params) < 2:
            logger.error(f"Invalid callback data for 'polls' command: {query.data}")
            await query.answer("Ошибка: неверные данные.", show_alert=True)
            return
        await show_poll_list(query, int(params[0]), params[1])
    elif command == "show":
        if len(params) < 1:
            logger.error(f"Invalid callback data for 'show' command: {query.data}")
            await query.answer("Ошибка: неверные данные.", show_alert=True)
            return
        chat_id = int(params[0])
        await show_group_dashboard(query, context, chat_id)
    elif command == "addfwd":
        if params[0] == "cancel":
            context.user_data.clear()
            await query.message.edit_text("Действие отменено.")
            return
            
        if 'user_to_add_via_forward' not in context.user_data:
            await query.message.edit_text("Не найдена информация о пользователе для добавления. Пожалуйста, перешлите сообщение еще раз.", reply_markup=None)
            return

        chat_id_to_add = int(params[0])
        user_data = context.user_data['user_to_add_via_forward']

        c.execute(
            'INSERT OR IGNORE INTO participants (chat_id, user_id, username, first_name, last_name) VALUES (?, ?, ?, ?, ?)',
            (chat_id_to_add, user_data['id'], user_data['username'], user_data['first_name'], user_data['last_name'])
        )
        conn.commit()

        user_name = user_data['first_name'] or f"@{user_data['username']}"
        group_title = get_group_title(chat_id_to_add)

        await query.answer(f"Пользователь {user_name} добавлен в группу «{group_title}».", show_alert=True)
        
        context.user_data.clear()
        await show_group_dashboard(query, context, chat_id_to_add)
    elif command == "startpoll":
        poll_id = int(params[0])
        c.execute('SELECT chat_id FROM polls WHERE poll_id = ?', (poll_id,))
        res = c.fetchone()
        if res:
            await startpoll_from_dashboard(query, context, poll_id, res[0])
            await show_group_dashboard(query, context, res[0])
    elif command == "closepoll":
        poll_id = int(params[0])
        await close_poll(query, context, poll_id)
    elif command == "delnudge":
        poll_id = int(params[0])
        c.execute('SELECT chat_id, nudge_message_id FROM polls WHERE poll_id = ?', (poll_id,))
        res = c.fetchone()
        if res:
            chat_id, nudge_message_id = res
            if nudge_message_id:
                try:
                    await context.bot.delete_message(chat_id=chat_id, message_id=nudge_message_id)
                    await query.answer("Сообщение с оповещением удалено.")
                except Exception as e:
                    logger.warning(f"Could not delete nudge message {nudge_message_id}: {e}")
                    await query.answer("Не удалось удалить сообщение.", show_alert=True)
                
                c.execute('UPDATE polls SET nudge_message_id = NULL WHERE poll_id = ?', (poll_id,))
                conn.commit()
        await show_results(update, context, poll_id)
    elif command == "deletepoll":
        poll_id = int(params[0])
        c.execute('SELECT chat_id, status FROM polls WHERE poll_id = ?', (poll_id,))
        res = c.fetchone()
        if res:
            chat_id, status = res
            for table in ['polls', 'responses', 'poll_settings', 'poll_option_settings']:
                c.execute(f'DELETE FROM {table} WHERE poll_id = ?', (poll_id,))
            conn.commit()
            await query.answer(f"Опрос {poll_id} удален.", show_alert=True)
            await show_poll_list(query, chat_id, status)
    elif command == "participants":
        # Allow both orders: <chat_id>_<action> or <action>_<chat_id>
        if params and params[0].lstrip('-').isdigit():
            chat_id = int(params[0])
            action = params[1] if len(params) > 1 else "menu"
        elif params and len(params) > 1 and params[1].lstrip('-').isdigit():
            action = params[0]
            chat_id = int(params[1])
        else:
            logger.error(f"Invalid participants callback data: {query.data}")
            await query.answer("Ошибка: неверные данные.", show_alert=True)
            return

        if action == "menu":
            await show_participants_menu(query, chat_id)
        elif action == "list":
            page = int(params[2]) if len(params) > 2 else 0
            await show_participants_list(query, context, chat_id, page)
        elif action == "exclude":
            page = int(params[2]) if len(params) > 2 else 0
            await show_exclude_menu(query, context, chat_id, page)
        elif action == "clean":
            c.execute('DELETE FROM participants WHERE chat_id = ?', (chat_id,))
            conn.commit()
            await query.answer(f'Список участников для "{get_group_title(chat_id)}" очищен.', show_alert=True)
            await show_participants_menu(query, chat_id)
        elif action == "toggle":
            if len(params) < 3:
                logger.error(f"Invalid callback for participants-toggle: {query.data}")
                return
            user_to_toggle = int(params[2])
            page = int(params[3]) if len(params) > 3 else 0
            
            c.execute('SELECT MAX(excluded) FROM participants WHERE chat_id = ? AND user_id = ? GROUP BY user_id', (chat_id, user_to_toggle))
            res = c.fetchone()

            if res:
                current_status = res[0] or 0
                new_status = 1 - current_status
                c.execute('UPDATE participants SET excluded = ? WHERE chat_id = ? AND user_id = ?', (new_status, chat_id, user_to_toggle))
                conn.commit()
                await show_exclude_menu(query, context, chat_id, page)
            else:
                await query.answer("Участник не найден.", show_alert=True)
    elif command == 'wizard_start':
        if not params:
            logger.error(f"Invalid callback data for wizard_start: {query.data}")
            return
        chat_id = int(params[0])
        await wizard_start(query, context, chat_id)
    elif command == 'edit_votes_polls':
        if not params:
            logger.error(f"Invalid callback data for edit_votes_polls: {query.data}")
            return
        chat_id = int(params[0])
        await query.answer("Функция редактирования голосов перемещена в настройки опроса.", show_alert=True)
        await show_group_dashboard(query, context, chat_id)
    else:
        logger.warning(f"Unknown dashboard action: {command}")
        await query.answer("Неизвестное действие.")

async def vote_callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await add_user_to_participants(update, context)
    query = update.callback_query
    poll_id, option_index = map(int, query.data.split('_')[1:])
    user_id = query.from_user.id

    c.execute('SELECT options, status FROM polls WHERE poll_id = ?', (poll_id,))
    row = c.fetchone()
    if not row or row[1] != 'active':
        await query.answer("Опрос неактивен.", show_alert=True)
        return
        
    response_text = row[0].split(',')[option_index].strip()
    c.execute('SELECT response FROM responses WHERE poll_id = ? AND user_id = ?', (poll_id, user_id))
    existing = c.fetchone()

    if existing and existing[0] == response_text:
        c.execute('DELETE FROM responses WHERE poll_id = ? AND user_id = ?', (poll_id, user_id))
        await query.answer(f"Голос за '{response_text}' отозван.")
    elif existing:
        c.execute('UPDATE responses SET response = ? WHERE poll_id = ? AND user_id = ?', (response_text, poll_id, user_id))
        await query.answer(f"Ответ изменен на '{response_text}'.")
    else:
        c.execute('INSERT INTO responses (poll_id, user_id, response) VALUES (?, ?, ?)', (poll_id, user_id, response_text))
        await query.answer(f"Ответ '{response_text}' принят!")
    conn.commit()
    
    await update_poll_message(poll_id, context)
    await update_nudge_message(poll_id, context)

async def results_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    await show_results(update, context, int(query.data.split('_')[1]))

async def refresh_results_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await show_results(update, context, int(update.callback_query.data.split('_')[1]))

async def settings_callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data.split('_')
    poll_id, option_index, command = int(data[1]), int(data[2]), data[3]
    
    c.execute('INSERT OR IGNORE INTO poll_settings (poll_id) VALUES (?)', (poll_id,))
    c.execute('INSERT OR IGNORE INTO poll_option_settings (poll_id, option_index) VALUES (?, ?)', (poll_id, option_index))
    conn.commit() # Commit insertions
    
    if command == "menu":
        await show_option_settings_menu(query, context, poll_id, option_index)
        return
    elif command in ('setemoji', 'setcontribution', 'edittext'):
        context.user_data.update({
            'settings_state': f'waiting_for_{command}',
            'poll_id': poll_id,
            'option_index': option_index,
            'message_id': query.message.message_id # Store message_id to edit it later
        })
        prompts = {'setemoji': 'Отправьте смайлик:', 'setcontribution': 'Отправьте сумму взноса:', 'edittext': 'Отправьте новый текст варианта:'}
        await query.message.edit_text(prompts[command], reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("❌ Отмена", callback_data=f"setresopt_{poll_id}_{option_index}_menu")]]))
        return
    elif command == "shownames": c.execute('UPDATE poll_option_settings SET show_names = ? WHERE poll_id = ? AND option_index = ?', (int(data[4]), poll_id, option_index))
    elif command == "priority": c.execute('UPDATE poll_option_settings SET is_priority = ? WHERE poll_id = ? AND option_index = ?', (int(data[4]), poll_id, option_index))
    elif command == "namesstyle": c.execute('UPDATE poll_option_settings SET names_style = ? WHERE poll_id = ? AND option_index = ?', (data[4], poll_id, option_index))
    elif command == "showcount": c.execute('UPDATE poll_option_settings SET show_count = ? WHERE poll_id = ? AND option_index = ?', (int(data[4]), poll_id, option_index))
    elif command == "showcontribution": c.execute('UPDATE poll_option_settings SET show_contribution = ? WHERE poll_id = ? AND option_index = ?', (int(data[4]), poll_id, option_index))
    
    conn.commit()
    await show_option_settings_menu(query, context, poll_id, option_index)

async def poll_settings_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data.split('_')
    poll_id, command = int(data[1]), data[2]

    c.execute('INSERT OR IGNORE INTO poll_settings (poll_id) VALUES (?)', (poll_id,))
    conn.commit()

    if command == "menu":
        await show_poll_settings_menu(query, context, poll_id)
    elif command == "settargetsum":
        context.user_data.update({
            'settings_state': 'waiting_for_target_sum',
            'poll_id': poll_id,
            'message_id': query.message.message_id
        })
        await query.message.edit_text(
            "Отправьте целевую сумму сбора (введите 0, чтобы убрать):",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("❌ Отмена", callback_data=f"setpollsettings_{poll_id}_menu")]])
        )
    elif command == "edittext":
        context.user_data.update({
            'settings_state': 'waiting_for_poll_text',
            'poll_id': poll_id,
            'message_id': query.message.message_id
        })
        await query.message.edit_text(
            "Отправьте новый заголовок опроса:",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("❌ Отмена", callback_data=f"setpollsettings_{poll_id}_menu")]])
        )
    elif command == "setnudgeneg":
        context.user_data.update({
            'settings_state': 'waiting_for_nudge_neg',
            'poll_id': poll_id,
            'message_id': query.message.message_id
        })
        await query.message.edit_text("Отправьте новый 'негативный' эмодзи:")
    elif command == "nudgeemojis":
        await show_nudge_emoji_menu(query, context, poll_id)

async def show_nudge_emoji_menu(query: Union[CallbackQuery, None], context: ContextTypes.DEFAULT_TYPE, poll_id: int, message_id: int = None, chat_id: int = None):
    c.execute('SELECT nudge_negative_emoji FROM poll_settings WHERE poll_id = ?', (poll_id,))
    res = c.fetchone()
    neg_emoji = (res[0] if res and res[0] else '❌')

    text = "Настройте эмодзи для списка оповещений (для тех, кто не проголосовал):"
    kb = [
        [InlineKeyboardButton(f"Эмодзи: {neg_emoji}", callback_data=f"setpollsettings_{poll_id}_setnudgeneg")],
        [InlineKeyboardButton("↩️ Назад к общим настройкам", callback_data=f"setpollsettings_{poll_id}_menu")]
    ]

    if query:
        await query.message.edit_text(text, reply_markup=InlineKeyboardMarkup(kb))
    elif message_id and chat_id:
        await context.bot.edit_message_text(text, chat_id=chat_id, message_id=message_id, reply_markup=InlineKeyboardMarkup(kb))

async def show_option_settings_menu(query: Union[CallbackQuery, None], context: ContextTypes.DEFAULT_TYPE, poll_id: int, option_index: int, message_id: int = None, chat_id: int = None):
    c.execute('SELECT options FROM polls WHERE poll_id = ?', (poll_id,))
    option_text = c.fetchone()[0].split(',')[option_index].strip()
    c.execute('SELECT default_show_names, default_show_count FROM poll_settings WHERE poll_id = ?', (poll_id,))
    res = c.fetchone()
    default_show_names, default_show_count = (res or (1, 1))
    
    c.execute('SELECT show_names, emoji, is_priority, contribution_amount, names_style, show_count, show_contribution FROM poll_option_settings WHERE poll_id = ? AND option_index = ?', (poll_id, option_index))
    opt_settings = c.fetchone()
    
    show_names = default_show_names if not opt_settings or opt_settings[0] is None else opt_settings[0]
    emoji = (opt_settings[1] or "Не задан") if opt_settings else "Не задан"
    is_priority = (opt_settings[2] or 0) if opt_settings else 0
    contribution = (opt_settings[3] or 0) if opt_settings else 0
    names_style = (opt_settings[4] or 'list') if opt_settings and opt_settings[4] else 'list'
    show_count = default_show_count if not opt_settings or opt_settings[5] is None else opt_settings[5]
    show_contribution = 1 if not opt_settings or opt_settings[6] is None else opt_settings[6]

    text = f"Настройки для: *{option_text}*"

    if names_style == 'list':
        style_text = "Списком"
        new_style = "inline"
    elif names_style == 'inline':
        style_text = "В строку"
        new_style = "numbered"
    else: # numbered
        style_text = "Нумерованный"
        new_style = "list"
    style_button = InlineKeyboardButton(f"Стиль: {style_text}", callback_data=f"setresopt_{poll_id}_{option_index}_namesstyle_{new_style}")
    count_button = InlineKeyboardButton(f"Счётчик: {'✅' if show_count else '❌'}", callback_data=f"setresopt_{poll_id}_{option_index}_showcount_{int(not show_count)}")

    kb = [
        [
            InlineKeyboardButton(f"Имена: {'✅' if show_names else '❌'}", callback_data=f"setresopt_{poll_id}_{option_index}_shownames_{int(not show_names)}"),
            style_button
        ],
        [
            count_button,
            InlineKeyboardButton(f"⭐ Приоритет: {'✅' if is_priority else '❌'}", callback_data=f"setresopt_{poll_id}_{option_index}_priority_{int(not is_priority)}")
        ],
        [
            InlineKeyboardButton(f"Взнос: {contribution}", callback_data=f"setresopt_{poll_id}_{option_index}_setcontribution"),
            InlineKeyboardButton(f"Показ суммы: {'✅' if show_contribution else '❌'}", callback_data=f"setresopt_{poll_id}_{option_index}_showcontribution_{int(not show_contribution)}")
        ],
        [
            InlineKeyboardButton("📝 Изменить текст", callback_data=f"setresopt_{poll_id}_{option_index}_edittext"),
            InlineKeyboardButton(f"Смайлик: {emoji}", callback_data=f"setresopt_{poll_id}_{option_index}_setemoji")
        ],
        [InlineKeyboardButton("↩️ Назад", callback_data=f"setresultoptionspoll_{poll_id}")]
    ]
    if message_id and chat_id:
        await context.bot.edit_message_text(text, chat_id=chat_id, message_id=message_id, reply_markup=InlineKeyboardMarkup(kb), parse_mode=ParseMode.MARKDOWN)
    elif query:
        await query.message.edit_text(text, reply_markup=InlineKeyboardMarkup(kb), parse_mode=ParseMode.MARKDOWN)

async def show_poll_settings_menu(query: Union[CallbackQuery, None], context: ContextTypes.DEFAULT_TYPE, poll_id: int, message_id: int = None, chat_id: int = None):
    c.execute('INSERT OR IGNORE INTO poll_settings (poll_id) VALUES (?)', (poll_id,))
    c.execute('SELECT target_sum FROM poll_settings WHERE poll_id = ?', (poll_id,))
    settings = c.fetchone()
    target_sum = (settings[0] if settings and settings[0] is not None else 0)

    text = f"⚙️ *Общие настройки опроса {poll_id}*"
    kb = [
        [InlineKeyboardButton("📝 Изменить текст опроса", callback_data=f"setpollsettings_{poll_id}_edittext")],
        [InlineKeyboardButton(f"💰 Целевая сумма сбора: {int(target_sum)}", callback_data=f"setpollsettings_{poll_id}_settargetsum")],
        [InlineKeyboardButton("⚙️ Эмодзи оповещений", callback_data=f"setpollsettings_{poll_id}_nudgeemojis")],
        [InlineKeyboardButton("✍️ Редактировать голоса", callback_data=f"admin_edit_poll_{poll_id}")],
        [InlineKeyboardButton("↩️ Назад к настройкам", callback_data=f"setresultoptionspoll_{poll_id}")]
    ]
    
    # Logic to either edit an existing message or the query's message
    if message_id and chat_id:
        await context.bot.edit_message_text(text, chat_id=chat_id, message_id=message_id, reply_markup=InlineKeyboardMarkup(kb), parse_mode=ParseMode.MARKDOWN)
    elif query:
        await query.message.edit_text(text, reply_markup=InlineKeyboardMarkup(kb), parse_mode=ParseMode.MARKDOWN)

async def text_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if not context.user_data: return
    
    app_user_data = context.user_data
    message = update.message

    # --- WIZARD HANDLER ---
    if 'wizard_state' in app_user_data:
        wizard_state = app_user_data['wizard_state']
        text_input = message.text.strip()
        wizard_message_id = app_user_data['wizard_message_id']
        chat_id_for_dashboard = app_user_data['wizard_chat_id']
        
        if wizard_state == 'waiting_for_title':
            if not text_input:
                await message.reply_text("Заголовок не может быть пустым.")
                return
            app_user_data['wizard_title'] = text_input
            app_user_data['wizard_state'] = 'waiting_for_options'
            await context.bot.edit_message_text(
                "✅ *Шаг 1/2*: Заголовок сохранен.\n\n✨ *Шаг 2/2*: Теперь отправьте варианты ответа. Каждый вариант с новой строки или через запятую.",
                chat_id=user_id, message_id=wizard_message_id, parse_mode=ParseMode.MARKDOWN,
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("❌ Отмена", callback_data=f"dash_group_{chat_id_for_dashboard}")]])
            )
            await message.delete()

        elif wizard_state == 'waiting_for_options':
            options = [opt.strip() for opt in text_input.replace('\n', ',').split(',') if opt.strip()]
            if len(options) < 2:
                await message.reply_text("Нужно как минимум 2 варианта ответа.")
                return

            poll_title = app_user_data['wizard_title']
            c.execute('INSERT INTO polls (chat_id, message, status, options) VALUES (?, ?, ?, ?)', (chat_id_for_dashboard, poll_title, 'draft', ','.join(options)))
            conn.commit()
            
            await message.delete()
            await context.bot.delete_message(chat_id=user_id, message_id=wizard_message_id)
            
            text, kb = build_group_dashboard_content(chat_id_for_dashboard, user_id)
            await context.bot.send_message(user_id, f"🎉 Черновик «{poll_title}» создан!", reply_markup=kb, parse_mode=ParseMode.MARKDOWN)
            context.user_data.clear()

    # --- SETTINGS HANDLER ---
    elif 'settings_state' in app_user_data:
        settings_state = app_user_data['settings_state']
        await message.delete()
        poll_id = app_user_data['poll_id']
        message_id = app_user_data['message_id']
        text_input = message.text.strip()

        if settings_state == 'waiting_for_setemoji':
            c.execute('UPDATE poll_option_settings SET emoji = ? WHERE poll_id = ? AND option_index = ?', (text_input, poll_id, app_user_data['option_index']))
        elif settings_state == 'waiting_for_edittext':
            c.execute('SELECT options FROM polls WHERE poll_id = ?', (poll_id,))
            options_list = c.fetchone()[0].split(',')
            old_text = options_list[app_user_data['option_index']].strip()
            options_list[app_user_data['option_index']] = text_input
            c.execute('UPDATE polls SET options = ? WHERE poll_id = ?', (','.join(options_list), poll_id))
            c.execute('UPDATE responses SET response = ? WHERE poll_id = ? AND response = ?', (text_input, poll_id, old_text))
        elif settings_state == 'waiting_for_setcontribution':
            try:
                c.execute('UPDATE poll_option_settings SET contribution_amount = ? WHERE poll_id = ? AND option_index = ?', (float(text_input), poll_id, app_user_data['option_index']))
            except (ValueError, TypeError): pass # Ignore invalid input, just show menu again
        elif settings_state == 'waiting_for_target_sum':
            try:
                c.execute('UPDATE poll_settings SET target_sum = ? WHERE poll_id = ?', (float(text_input), poll_id))
            except (ValueError, TypeError): pass # Ignore invalid input
        elif settings_state == 'waiting_for_poll_text':
            if text_input:
                c.execute('UPDATE polls SET message = ? WHERE poll_id = ?', (text_input, poll_id))
        elif settings_state == 'waiting_for_nudge_neg':
             c.execute('UPDATE poll_settings SET nudge_negative_emoji = ? WHERE poll_id = ?', (text_input, poll_id))

        conn.commit()
        
        option_index_to_restore = app_user_data.get('option_index')
        context.user_data.clear()

        if settings_state in ('waiting_for_target_sum', 'waiting_for_poll_text'):
            await show_poll_settings_menu(None, context, poll_id, message_id=message_id, chat_id=user_id)
        elif settings_state in ('waiting_for_nudge_pos', 'waiting_for_nudge_neg'):
            await show_nudge_emoji_menu(None, context, poll_id, message_id=message_id, chat_id=user_id)
        else:
            await show_option_settings_menu(None, context, poll_id, option_index_to_restore, message_id=message_id, chat_id=user_id)

async def forwarded_message_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.effective_chat.type != 'private' or not update.message.forward_from:
        return

    user_to_add = update.message.forward_from

    context.user_data['user_to_add_via_forward'] = {
        'id': user_to_add.id,
        'username': user_to_add.username,
        'first_name': user_to_add.first_name,
        'last_name': user_to_add.last_name,
    }

    admin_chats = await get_admin_chats(update, context)

    if not admin_chats:
        await update.message.reply_text("Я не знаю групп, где вы являетесь администратором. Не могу добавить пользователя.")
        context.user_data.clear()
        return

    user_name = user_to_add.first_name or f"@{user_to_add.username}"
    text = f"В какую группу вы хотите принудительно добавить пользователя {escape_markdown(user_name, version=1)}?"
    
    kb = [[InlineKeyboardButton(c.title, callback_data=f"dash_addfwd_{c.id}")] for c in admin_chats]
    kb.append([InlineKeyboardButton("❌ Отмена", callback_data="dash_addfwd_cancel")])

    await update.message.reply_text(text, reply_markup=InlineKeyboardMarkup(kb), parse_mode=ParseMode.MARKDOWN)

async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Log any error that occurs."""
    try:
        raise context.error
    except Exception as e:
        logger.error(f"Exception while handling an update: {e}", exc_info=True)

async def admin_callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    if query.data == "admin_backup":
        await backup_command(update, context)
        return
    elif query.data == "admin_restore":
        await restore_command(update, context)
        return
    elif query.data == "admin_settings":
        await query.answer()
        kb = [
            [InlineKeyboardButton("💾 Бэкап БД", callback_data="admin_backup")],
            [InlineKeyboardButton("♻️ Восстановить БД", callback_data="admin_restore")],
            [InlineKeyboardButton("🔙 Назад", callback_data="dash_back_to_chats")]
        ]
        await query.message.edit_text("⚙️ Настройки бота", reply_markup=InlineKeyboardMarkup(kb))
        return
    await query.answer()
    parts = query.data.split('_')

    # Expected formats:
    # admin_edit_poll_<poll_id>
    # admin_edit_option_<poll_id>_<option_index>
    # admin_user_page_<poll_id>_<option_index>_<page>
    # admin_add_vote_<poll_id>_<option_index>_<user_id>

    if len(parts) < 2:
        logger.warning(f"Invalid admin callback data: {query.data}")
        return

    action = parts[1]

    try:
        # --- Navigate through edit menus ---
        if action == "edit":
            subtype = parts[2]
            if subtype == "poll":
                poll_id = int(parts[3])
                await show_poll_options_for_editing(query, poll_id)
            elif subtype == "option":
                poll_id = int(parts[3])
                option_index = int(parts[4])
                await show_users_for_adding_vote(query, poll_id, option_index, page=0)

        # --- Pagination for user list ---
        elif action == "user" and parts[2] == "page":
            poll_id = int(parts[3])
            option_index = int(parts[4])
            page = int(parts[5])
            await show_users_for_adding_vote(query, poll_id, option_index, page)

        # --- Add a vote on behalf of a user ---
        elif action == "add" and parts[2] == "vote":
            poll_id = int(parts[3])
            option_index = int(parts[4])
            user_id = int(parts[5])
            await add_user_vote(query, poll_id, option_index, user_id, context)

        else:
            logger.warning(f"Unknown admin callback action: {query.data}")
    except Exception as e:
        logger.error(f"Error handling admin callback '{query.data}': {e}")

def main() -> None:
    """Start the bot."""
    # Create the Application and pass it your bot's token.
    application = Application.builder().token(BOT_TOKEN).build()
    
    application.add_handler(TypeHandler(Update, add_user_to_participants), group=-1)

    # on different commands - answer in Telegram
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("help", help_command))
    application.add_handler(CommandHandler("setresultoptions", setresultoptions))
    application.add_handler(CommandHandler("showresults", show_results))
    application.add_handler(CommandHandler("nudge", nudge_handler))
    application.add_handler(CommandHandler("movetobottom", move_to_bottom_handler))
    application.add_handler(CommandHandler("debug", toggle_debug))
    application.add_handler(CommandHandler("backup", backup_command))
    application.add_handler(CommandHandler("restore", restore_command))
    application.add_handler(MessageHandler(filters.Document.ALL, document_handler))

    application.add_handler(CallbackQueryHandler(dashboard_callback_handler, pattern='^dash_'))
    application.add_handler(CallbackQueryHandler(vote_callback_handler, pattern='^poll_'))
    application.add_handler(CallbackQueryHandler(results_callback, pattern='^results_'))
    application.add_handler(CallbackQueryHandler(refresh_results_callback, pattern='^refreshresults_'))
    application.add_handler(CallbackQueryHandler(settings_callback_handler, pattern='^settings_'))
    application.add_handler(CallbackQueryHandler(settings_callback_handler, pattern='^setresopt_'))
    application.add_handler(CallbackQueryHandler(setresultoptions, pattern='^setresultoptionspoll_'))
    application.add_handler(CallbackQueryHandler(poll_settings_handler, pattern='^setpollsettings_'))
    application.add_handler(CallbackQueryHandler(poll_settings_handler, pattern='^pollsettings_'))
    application.add_handler(CallbackQueryHandler(admin_callback_handler, pattern='^admin_'))

    application.add_handler(CallbackQueryHandler(nudge_handler, pattern='^nudge_'))
    application.add_handler(CallbackQueryHandler(move_to_bottom_handler, pattern='^movetobottom_'))
    application.add_handler(MessageHandler(filters.FORWARDED, forwarded_message_handler))

    application.add_handler(MessageHandler(filters.TEXT & (~filters.COMMAND), text_handler))
    
    # Add global error handler
    application.add_error_handler(error_handler)

    application.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == '__main__':
    main()