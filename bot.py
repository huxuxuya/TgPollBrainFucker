# -*- coding: utf-8 -*-
# Gemini was here
import logging
import sqlite3
import os
import time
from typing import Union

from dotenv import load_dotenv
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, CallbackQuery
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, ContextTypes, MessageHandler, filters, TypeHandler
from telegram.constants import ParseMode
from telegram.error import ChatMigrated

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
conn = sqlite3.connect('poll_data.db', check_same_thread=False)
c = conn.cursor()
c.execute('''CREATE TABLE IF NOT EXISTS participants
             (chat_id INTEGER, user_id INTEGER, username TEXT, first_name TEXT, last_name TEXT, excluded INTEGER DEFAULT 0)''')
c.execute('''CREATE TABLE IF NOT EXISTS polls
             (poll_id INTEGER PRIMARY KEY AUTOINCREMENT, chat_id INTEGER, message TEXT, status TEXT, options TEXT, message_id INTEGER)''')
c.execute('''CREATE TABLE IF NOT EXISTS responses
             (poll_id INTEGER, user_id INTEGER, response TEXT)''')
c.execute('''CREATE TABLE IF NOT EXISTS known_chats
             (chat_id INTEGER PRIMARY KEY, title TEXT)''')
c.execute('''CREATE TABLE IF NOT EXISTS poll_settings (
    poll_id INTEGER PRIMARY KEY,
    default_show_names INTEGER DEFAULT 1,
    default_names_style TEXT DEFAULT 'list',
    default_show_count INTEGER DEFAULT 1,
    target_sum REAL DEFAULT 0
)''')
c.execute('''CREATE TABLE IF NOT EXISTS poll_option_settings (
    poll_id INTEGER,
    option_index INTEGER,
    show_names INTEGER DEFAULT NULL,
    names_style TEXT DEFAULT NULL,
    show_count INTEGER DEFAULT NULL,
    emoji TEXT DEFAULT NULL,
    is_priority INTEGER DEFAULT 0,
    contribution_amount REAL DEFAULT 0,
    PRIMARY KEY (poll_id, option_index)
)''')

def run_migration(query: str):
    try:
        c.execute(query)
        conn.commit()
    except Exception:
        pass

run_migration('ALTER TABLE poll_option_settings ADD COLUMN emoji TEXT')
run_migration('ALTER TABLE poll_option_settings ADD COLUMN is_priority INTEGER DEFAULT 0')
run_migration('ALTER TABLE polls ADD COLUMN message_id INTEGER')
run_migration('ALTER TABLE poll_settings ADD COLUMN target_sum REAL DEFAULT 0')
run_migration('ALTER TABLE poll_option_settings ADD COLUMN contribution_amount REAL DEFAULT 0')

# --- Utility Functions ---

def add_user_to_participants(update: Update):
    user = update.effective_user
    chat = update.effective_chat
    if user and chat and chat.type in ['group', 'supergroup']:
        c.execute(
            'INSERT OR IGNORE INTO participants (chat_id, user_id, username, first_name, last_name) VALUES (?, ?, ?, ?, ?)',
            (chat.id, user.id, user.username, user.first_name, user.last_name)
        )
        conn.commit()

async def update_known_chats(chat_id: int, title: str) -> None:
    c.execute('INSERT OR REPLACE INTO known_chats (chat_id, title) VALUES (?, ?)', (chat_id, title))
    conn.commit()

async def get_admin_chats(update: Update, context: ContextTypes.DEFAULT_TYPE) -> list:
    user_id = update.effective_user.id
    admin_chats = []
    c.execute('SELECT DISTINCT chat_id, title FROM known_chats')
    known_chats = c.fetchall()
    for chat_id, title in known_chats:
        try:
            admins = await context.bot.get_chat_administrators(chat_id)
            if user_id in [admin.user.id for admin in admins]:
                admin_chats.append(type('Chat', (), {'id': chat_id, 'title': title, 'type': 'group'}))
        except Exception as e:
            logger.error(f'Error checking admin status in known chat {chat_id}: {e}')
    return admin_chats

def get_group_title(chat_id: int) -> str:
    c.execute('SELECT title FROM known_chats WHERE chat_id = ?', (chat_id,))
    row = c.fetchone()
    return row[0] if row else f"ID: {chat_id}"

def get_user_name(user_id: int) -> str:
    c.execute('SELECT first_name, last_name, username FROM participants WHERE user_id = ?', (user_id,))
    user_data = c.fetchone()
    if not user_data: return f"User ID: {user_id}"
    first_name, last_name, username = user_data
    name = first_name or ''
    if last_name: name += f' {last_name}'
    if not name.strip(): name = f'@{username}' if username else f"ID: {user_id}"
    return name.strip()

def get_progress_bar(progress, total, length=20):
    if total <= 0: return "[]", 0
    percent = progress / total
    filled_length = int(length * percent)
    bar = '█' * filled_length + '░' * (length - filled_length)
    return f"[{bar}]", percent * 100

# --- Poll Display Logic ---

def generate_poll_text(poll_id: int) -> str:
    c.execute('SELECT message, options FROM polls WHERE poll_id = ?', (poll_id,))
    poll_data = c.fetchone()
    if not poll_data: return "Опрос не найден."
    
    message, options_str = poll_data
    original_options = [opt.strip() for opt in options_str.split(',')]
    
    c.execute('SELECT user_id, response FROM responses WHERE poll_id = ?', (poll_id,))
    responses = c.fetchall()
    counts = {opt: 0 for opt in original_options}
    for _, response in responses:
        if response in counts: counts[response] += 1
        
    c.execute('SELECT default_show_names, default_names_style, target_sum FROM poll_settings WHERE poll_id = ?', (poll_id,))
    default_settings_res = c.fetchone()
    default_show_names, _, target_sum = (default_settings_res or (1, 'list', 0))
    
    total_votes = len(responses)
    total_collected = 0
    text_parts = [message, ""]

    options_with_settings = []
    for i, option_text in enumerate(original_options):
        c.execute('SELECT show_names, names_style, is_priority, contribution_amount, emoji FROM poll_option_settings WHERE poll_id = ? AND option_index = ?', (poll_id, i))
        opt_settings = c.fetchone()
        options_with_settings.append({
            'text': option_text,
            'show_names': opt_settings[0] if opt_settings and opt_settings[0] is not None else default_show_names,
            'names_style': opt_settings[1] if opt_settings and opt_settings[1] else 'list',
            'is_priority': opt_settings[2] if opt_settings and opt_settings[2] else 0,
            'contribution_amount': opt_settings[3] if opt_settings and opt_settings[3] else 0,
            'emoji': (opt_settings[4] + ' ') if opt_settings and opt_settings[4] else ""
        })

    options_with_settings.sort(key=lambda x: x['is_priority'], reverse=True)

    for option_data in options_with_settings:
        option_text = option_data['text']
        count = counts.get(option_text, 0)
        contribution = option_data['contribution_amount']
        if contribution > 0: total_collected += count * contribution
            
        marker = "⭐ " if option_data['is_priority'] else ""
        formatted_text = f"*{option_text}*" if option_data['is_priority'] else option_text
        line = f"{marker}{formatted_text}"
        if contribution > 0: line += f" (по {int(contribution)})"
        line += f": *{count}*"
        text_parts.append(line)

        if option_data['show_names'] and count > 0:
            responders = [r[0] for r in responses if r[1] == option_text]
            user_names = [get_user_name(uid) for uid in responders]
            names_list = [f"{option_data['emoji']}{name}" for name in user_names]
            indent = "    "
            if option_data['names_style'] == 'list': text_parts.append("\n".join(f"{indent}{name}" for name in names_list))
            elif option_data['names_style'] == 'inline': text_parts.append(f'{indent}{", ".join(names_list)}')
        text_parts.append("")

    if target_sum > 0:
        bar, percent = get_progress_bar(total_collected, target_sum)
        text_parts.append(f"💰 Собрано: *{int(total_collected)} из {int(target_sum)}* ({percent:.1f}%)\n{bar}")
    elif total_collected > 0:
        text_parts.append(f"💰 Собрано: *{int(total_collected)}*")
    
    while text_parts and text_parts[-1] == "": text_parts.pop()
    text_parts.append(f"\nВсего проголосовало: *{total_votes}*")
    return "\n".join(text_parts)

async def update_poll_message(poll_id: int, context: ContextTypes.DEFAULT_TYPE):
    logger.info(f"[POLL_UPDATE] Updating message for poll_id={poll_id}")
    c.execute('SELECT chat_id, message_id, options FROM polls WHERE poll_id = ?', (poll_id,))
    poll_data = c.fetchone()
    if not poll_data or not poll_data[1]: return
        
    chat_id, message_id, options_str = poll_data
    new_text = generate_poll_text(poll_id)
    options = [opt.strip() for opt in options_str.split(',')]
    keyboard = [[InlineKeyboardButton(opt, callback_data=f'poll_{poll_id}_{i}')] for i, opt in enumerate(options)]
    
    try:
        await context.bot.edit_message_text(text=new_text, chat_id=chat_id, message_id=message_id, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode=ParseMode.MARKDOWN)
    except ChatMigrated as e:
        logger.warning(f"Chat migrated for poll {poll_id}. Old: {chat_id}, New: {e.new_chat_id}")
        c.execute('UPDATE polls SET chat_id = ? WHERE poll_id = ?', (e.new_chat_id, poll_id))
        conn.commit()
    except Exception as e:
        if "Message is not modified" not in str(e): logger.error(f"Failed to edit message for poll {poll_id}: {e}")

# --- Core Commands & Entry Points ---

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    add_user_to_participants(update)
    if update.effective_chat.type in ['group', 'supergroup']:
        await update_known_chats(update.effective_chat.id, update.effective_chat.title)
        me = await context.bot.get_me()
        await update.message.reply_text(f"Привет! Для управления опросами, напишите мне: @{me.username}")
    else:
        await private_chat_entry_point(update, context)

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    add_user_to_participants(update)
    if update.effective_chat.type == 'private': await private_chat_entry_point(update, context)
    else: await update.message.reply_text('Команды: /start, /help. Управление опросами в ЛС.')

async def toggle_debug(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    context.bot_data['debug_mode_enabled'] = not context.bot_data.get('debug_mode_enabled', False)
    status = "включен" if context.bot_data['debug_mode_enabled'] else "отключен"
    await update.message.reply_text(f"Режим отладки {status}.")

async def log_all_updates(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if context.bot_data.get('debug_mode_enabled', False): logger.info(f"[DEBUG_UPDATE]: {update.to_dict()}")

# --- Dashboard UI ---

def build_group_dashboard_content(chat_id: int) -> (str, InlineKeyboardMarkup):
    title = get_group_title(chat_id)
    c.execute('SELECT COUNT(*) FROM polls WHERE chat_id = ? AND status = ?', (chat_id, 'active'))
    active = c.fetchone()[0]
    c.execute('SELECT COUNT(*) FROM polls WHERE chat_id = ? AND status = ?', (chat_id, 'draft'))
    draft = c.fetchone()[0]
    text = f'Панель управления для *"{title}"*:'
    kb = [
        [InlineKeyboardButton("➕ Создать опрос", callback_data=f"dash_newpoll_{chat_id}")],
        [InlineKeyboardButton(f"⚡️ Активные ({active})", callback_data=f"dash_polls_{chat_id}_active")],
        [InlineKeyboardButton(f"📝 Черновики ({draft})", callback_data=f"dash_polls_{chat_id}_draft")],
        [InlineKeyboardButton("👥 Участники", callback_data=f"dash_participants_{chat_id}_menu")],
        [InlineKeyboardButton("↩️ К выбору группы", callback_data="dash_back_to_groups")]
    ]
    return text, InlineKeyboardMarkup(kb)

async def private_chat_entry_point(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_id = update.effective_user.id
    admin_chats = await get_admin_chats(update, context)
    text, kb = "Добро пожаловать! Выберите группу:", [[InlineKeyboardButton(c.title, callback_data=f"dash_group_{c.id}")] for c in admin_chats]
    if not admin_chats: text, kb = 'Я не знаю групп, где вы админ.', []
    
    if update.callback_query: await update.callback_query.message.edit_text(text, reply_markup=InlineKeyboardMarkup(kb))
    else: await context.bot.send_message(chat_id=user_id, text=text, reply_markup=InlineKeyboardMarkup(kb))

async def show_group_dashboard(query: CallbackQuery, context: ContextTypes.DEFAULT_TYPE, chat_id: int):
    text, keyboard = build_group_dashboard_content(chat_id)
    await query.message.edit_text(text, reply_markup=keyboard, parse_mode=ParseMode.MARKDOWN)

async def show_poll_list(query: CallbackQuery, chat_id: int, status: str):
    c.execute('SELECT poll_id, message FROM polls WHERE chat_id = ? AND status = ? ORDER BY poll_id DESC', (chat_id, status))
    polls = c.fetchall()
    status_text = "Активные опросы" if status == 'active' else "Черновики"
    
    if not polls:
        text = f"Нет {status_text.lower()} в этой группе."
        kb = [[InlineKeyboardButton("↩️ Назад", callback_data=f"dash_group_{chat_id}")]]
        await query.message.edit_text(text, reply_markup=InlineKeyboardMarkup(kb))
        return

    text = f'*{status_text}*:'
    kb = []
    for poll_id, message in polls:
        msg = (message or f'Опрос {poll_id}')[:40]
        if status == 'active': kb.append([InlineKeyboardButton(msg, callback_data=f"results_{poll_id}")])
        else: kb.append([
            InlineKeyboardButton(msg, callback_data=f"setresultoptionspoll_{poll_id}"),
            InlineKeyboardButton("▶️", callback_data=f"dash_startpoll_{poll_id}"),
            InlineKeyboardButton("🗑", callback_data=f"dash_deletepoll_{poll_id}")
        ])
    kb.append([InlineKeyboardButton("↩️ Назад", callback_data=f"dash_group_{chat_id}")])
    await query.message.edit_text(text, reply_markup=InlineKeyboardMarkup(kb), parse_mode=ParseMode.MARKDOWN)

async def show_participants_menu(query: CallbackQuery, chat_id: int):
    text = f'👥 *Управление участниками ("{get_group_title(chat_id)}")*'
    kb = [
        [InlineKeyboardButton("📄 Показать список", callback_data=f"dash_participants_list_{chat_id}")],
        [InlineKeyboardButton("🚫 Исключить/вернуть", callback_data=f"dash_participants_exclude_{chat_id}")],
        [InlineKeyboardButton("🧹 Очистить список", callback_data=f"dash_participants_clean_{chat_id}")],
        [InlineKeyboardButton("↩️ Назад", callback_data=f"dash_group_{chat_id}")]
    ]
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
    c.execute('SELECT status, chat_id FROM polls WHERE poll_id = ?', (poll_id,))
    poll_data = c.fetchone()
    if not poll_data:
        await query.edit_message_text("Опрос не найден.")
        return

    status, group_chat_id = poll_data
    result_text = generate_poll_text(poll_id)
    kb = [
        [InlineKeyboardButton("🔄 Обновить", callback_data=f"refreshresults_{poll_id}")],
        [InlineKeyboardButton("⚙️ Настроить", callback_data=f"setresultoptionspoll_{poll_id}")],
        [InlineKeyboardButton("↩️ К списку", callback_data=f"dash_polls_{group_chat_id}_{status}")]
    ]
    try:
        await query.edit_message_text(text=result_text, reply_markup=InlineKeyboardMarkup(kb), parse_mode=ParseMode.MARKDOWN)
        if query.data.startswith('refreshresults_'): await query.answer("Результаты обновлены.")
    except Exception as e:
        if "Message is not modified" not in str(e): logger.warning(f"Could not edit results msg: {e}")
        else: await query.answer("Нет изменений.")

# --- Callback Handlers ---

async def dashboard_callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    data = query.data.split('_')
    command, params = data[1], data[2:]
    
    if command == "group":
        if context.user_data: context.user_data.clear()
        await show_group_dashboard(query, context, int(params[0]))
    elif command == "back": await private_chat_entry_point(update, context)
    elif command == "newpoll": await wizard_start(query, context, int(params[0]))
    elif command == "polls": await show_poll_list(query, int(params[0]), params[1])
    elif command == "startpoll":
        poll_id = int(params[0])
        c.execute('SELECT chat_id FROM polls WHERE poll_id = ?', (poll_id,))
        res = c.fetchone()
        if res:
            await startpoll_from_dashboard(query, context, poll_id, res[0])
            await show_group_dashboard(query, context, res[0])
    elif command == "deletepoll":
        poll_id = int(params[0])
        c.execute('SELECT chat_id FROM polls WHERE poll_id = ?', (poll_id,))
        res = c.fetchone()
        if res:
            chat_id = res[0]
            for table in ['polls', 'responses', 'poll_settings', 'poll_option_settings']:
                c.execute(f'DELETE FROM {table} WHERE poll_id = ?', (poll_id,))
            conn.commit()
            await query.answer(f"Черновик {poll_id} удален.", show_alert=True)
            await show_poll_list(query, chat_id, 'draft')
    elif command == "participants":
        chat_id = int(params[-1])
        action = params[0]
        if action == "menu": await show_participants_menu(query, chat_id)
        elif action == "clean":
            c.execute('DELETE FROM participants WHERE chat_id = ?', (chat_id,))
            conn.commit()
            await query.answer(f'Список участников для "{get_group_title(chat_id)}" очищен.', show_alert=True)
            await show_participants_menu(query, chat_id)
        elif action in ["list", "exclude"]: await query.answer("В разработке.", show_alert=True)

async def vote_callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    add_user_to_participants(update)
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
    
    conn.commit()
    await show_option_settings_menu(query, context, poll_id, option_index)

async def show_option_settings_menu(query: Union[CallbackQuery, None], context: ContextTypes.DEFAULT_TYPE, poll_id: int, option_index: int, message_id: int = None, chat_id: int = None):
    c.execute('SELECT options FROM polls WHERE poll_id = ?', (poll_id,))
    option_text = c.fetchone()[0].split(',')[option_index].strip()
    c.execute('SELECT default_show_names FROM poll_settings WHERE poll_id = ?', (poll_id,))
    default_show = (c.fetchone() or (1,))[0]
    c.execute('SELECT show_names, emoji, is_priority, contribution_amount FROM poll_option_settings WHERE poll_id = ? AND option_index = ?', (poll_id, option_index))
    opt_settings = c.fetchone()
    
    show_names = default_show if not opt_settings or opt_settings[0] is None else opt_settings[0]
    emoji = (opt_settings[1] or "Не задан") if opt_settings else "Не задан"
    is_priority = (opt_settings[2] or 0) if opt_settings else 0
    contribution = (opt_settings[3] or 0) if opt_settings else 0

    text = f"Настройки для: *{option_text}*"
    kb = [
        [
            InlineKeyboardButton(f"Имена: {'✅' if show_names else '❌'}", callback_data=f"setresopt_{poll_id}_{option_index}_shownames_{int(not show_names)}"),
            InlineKeyboardButton(f"⭐ Приоритет: {'✅' if is_priority else '❌'}", callback_data=f"setresopt_{poll_id}_{option_index}_priority_{int(not is_priority)}")
        ],
        [
            InlineKeyboardButton(f"Смайлик: {emoji}", callback_data=f"setresopt_{poll_id}_{option_index}_setemoji"),
            InlineKeyboardButton(f"Взнос: {contribution}", callback_data=f"setresopt_{poll_id}_{option_index}_setcontribution")
        ],
        [InlineKeyboardButton("📝 Изменить текст", callback_data=f"setresopt_{poll_id}_{option_index}_edittext")],
        [InlineKeyboardButton("↩️ Назад", callback_data=f"setresultoptionspoll_{poll_id}")]
    ]
    if message_id and chat_id:
        await context.bot.edit_message_text(text, chat_id=chat_id, message_id=message_id, reply_markup=InlineKeyboardMarkup(kb), parse_mode=ParseMode.MARKDOWN)
    elif query:
        await query.message.edit_text(text, reply_markup=InlineKeyboardMarkup(kb), parse_mode=ParseMode.MARKDOWN)

async def show_poll_settings_menu(query: Union[CallbackQuery, None], context: ContextTypes.DEFAULT_TYPE, poll_id: int, message_id: int = None, chat_id: int = None):
    c.execute('SELECT target_sum FROM poll_settings WHERE poll_id = ?', (poll_id,))
    settings = c.fetchone()
    target_sum = (settings[0] if settings and settings[0] is not None else 0)

    text = f"⚙️ *Общие настройки опроса {poll_id}*"
    kb = [
        [InlineKeyboardButton(f"💰 Целевая сумма сбора: {int(target_sum)}", callback_data=f"setpollsettings_{poll_id}_settargetsum")],
        [InlineKeyboardButton("↩️ Назад к настройкам", callback_data=f"setresultoptionspoll_{poll_id}")]
    ]
    
    # Logic to either edit an existing message or the query's message
    if message_id and chat_id:
        await context.bot.edit_message_text(text, chat_id=chat_id, message_id=message_id, reply_markup=InlineKeyboardMarkup(kb), parse_mode=ParseMode.MARKDOWN)
    elif query:
        await query.message.edit_text(text, reply_markup=InlineKeyboardMarkup(kb), parse_mode=ParseMode.MARKDOWN)

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

# --- Text Handlers ---

async def text_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if not context.user_data: return
    
    app_user_data = context.user_data
    state = app_user_data.get('wizard_state') or app_user_data.get('settings_state')
    message = update.message
    
    if not state: return

    # --- WIZARD HANDLER ---
    if state.startswith('wizard_'):
        title = message.text.strip()
        wizard_message_id = app_user_data['wizard_message_id']
        chat_id_for_dashboard = app_user_data['wizard_chat_id']
        
        if state == 'waiting_for_title':
            if not title:
                await message.reply_text("Заголовок не может быть пустым.")
                return
            app_user_data['wizard_title'] = title
            app_user_data['wizard_state'] = 'waiting_for_options'
            await context.bot.edit_message_text(
                "✅ *Шаг 1/2*: Заголовок сохранен.\n\n✨ *Шаг 2/2*: Теперь отправьте варианты ответа. Каждый вариант с новой строки или через запятую.",
                chat_id=user_id, message_id=wizard_message_id, parse_mode=ParseMode.MARKDOWN,
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("❌ Отмена", callback_data=f"dash_group_{chat_id_for_dashboard}")]])
            )
            await message.delete()

        elif state == 'waiting_for_options':
            options = [opt.strip() for opt in title.replace('\n', ',').split(',') if opt.strip()]
            if len(options) < 2:
                await message.reply_text("Нужно как минимум 2 варианта ответа.")
                return

            poll_title = app_user_data['wizard_title']
            c.execute('INSERT INTO polls (chat_id, message, status, options) VALUES (?, ?, ?, ?)', (chat_id_for_dashboard, poll_title, 'draft', ','.join(options)))
            conn.commit()
            
            await message.delete()
            await context.bot.delete_message(chat_id=user_id, message_id=wizard_message_id)
            
            text, kb = build_group_dashboard_content(chat_id_for_dashboard)
            await context.bot.send_message(user_id, f"🎉 Черновик «{poll_title}» создан!", reply_markup=kb, parse_mode=ParseMode.MARKDOWN)
            context.user_data.clear()

    # --- SETTINGS HANDLER ---
    elif state.startswith('waiting_for_'):
        await message.delete()
        poll_id = app_user_data['poll_id']
        message_id = app_user_data['message_id']
        text_input = message.text.strip()

        if state == 'waiting_for_setemoji':
            c.execute('UPDATE poll_option_settings SET emoji = ? WHERE poll_id = ? AND option_index = ?', (text_input, poll_id, app_user_data['option_index']))
        elif state == 'waiting_for_edittext':
            c.execute('SELECT options FROM polls WHERE poll_id = ?', (poll_id,))
            options_list = c.fetchone()[0].split(',')
            old_text = options_list[app_user_data['option_index']].strip()
            options_list[app_user_data['option_index']] = text_input
            c.execute('UPDATE polls SET options = ? WHERE poll_id = ?', (','.join(options_list), poll_id))
            c.execute('UPDATE responses SET response = ? WHERE poll_id = ? AND response = ?', (text_input, poll_id, old_text))
        elif state == 'waiting_for_setcontribution':
            try:
                c.execute('UPDATE poll_option_settings SET contribution_amount = ? WHERE poll_id = ? AND option_index = ?', (float(text_input), poll_id, app_user_data['option_index']))
            except (ValueError, TypeError): pass # Ignore invalid input, just show menu again
        elif state == 'waiting_for_target_sum':
            try:
                c.execute('UPDATE poll_settings SET target_sum = ? WHERE poll_id = ?', (float(text_input), poll_id))
            except (ValueError, TypeError): pass # Ignore invalid input

        conn.commit()
        context.user_data.clear()

        # Restore the relevant settings menu
        if state == 'waiting_for_target_sum':
            await show_poll_settings_menu(None, context, poll_id, message_id=message_id, chat_id=user_id)
        else:
            await show_option_settings_menu(None, context, poll_id, app_user_data['option_index'], message_id=message_id, chat_id=user_id)

def main() -> None:
    application = Application.builder().token(BOT_TOKEN).build()
    application.add_handler(TypeHandler(Update, log_all_updates), group=-1)
    application.add_handler(CommandHandler('start', start))
    application.add_handler(CommandHandler('help', help_command))
    application.add_handler(CommandHandler('toggle_debug', toggle_debug))
    application.add_handler(CallbackQueryHandler(dashboard_callback_handler, pattern='^dash_'))
    application.add_handler(CallbackQueryHandler(vote_callback_handler, pattern='^poll_'))
    application.add_handler(CallbackQueryHandler(results_callback, pattern='^results_'))
    application.add_handler(CallbackQueryHandler(refresh_results_callback, pattern='^refreshresults_'))
    application.add_handler(CallbackQueryHandler(setresultoptions, pattern='^setresultoptionspoll_'))
    application.add_handler(CallbackQueryHandler(poll_settings_handler, pattern='^setpollsettings_'))
    application.add_handler(CallbackQueryHandler(settings_callback_handler, pattern='^setresopt_'))
    application.add_handler(MessageHandler(filters.TEXT & (~filters.COMMAND), text_handler))
    application.add_handler(MessageHandler(filters.StatusUpdate.NEW_CHAT_MEMBERS, add_user_to_participants))
    application.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == '__main__':
    main()