# -*- coding: utf-8 -*-
# Gemini was here
import logging
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, CallbackQuery, ReplyKeyboardRemove, ForceReply
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, ContextTypes, MessageHandler, filters, TypeHandler
from typing import Union
import sqlite3
import os
from dotenv import load_dotenv
from telegram.constants import ParseMode
from telegram.error import ChatMigrated
import time

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

# --- Флаг для включения/отключения debug-информации в результатах опроса ---
ENABLE_DEBUG_INFO = True

# Database setup
conn = sqlite3.connect('poll_data.db')
c = conn.cursor()
c.execute('''CREATE TABLE IF NOT EXISTS participants
             (chat_id INTEGER, user_id INTEGER, username TEXT, first_name TEXT, last_name TEXT, excluded INTEGER DEFAULT 0)''')
c.execute('''CREATE TABLE IF NOT EXISTS polls
             (poll_id INTEGER PRIMARY KEY AUTOINCREMENT, chat_id INTEGER, message TEXT, status TEXT, options TEXT)''')
c.execute('''CREATE TABLE IF NOT EXISTS responses
             (poll_id INTEGER, user_id INTEGER, response TEXT)''')
c.execute('''CREATE TABLE IF NOT EXISTS known_chats
             (chat_id INTEGER PRIMARY KEY, title TEXT)''')
c.execute('''CREATE TABLE IF NOT EXISTS admin_context
             (user_id INTEGER PRIMARY KEY, group_id INTEGER)''')
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
# --- ДОБАВЛЕНО: добавляем поле emoji, если его нет ---
try:
    c.execute('ALTER TABLE poll_option_settings ADD COLUMN emoji TEXT')
    conn.commit()
except Exception:
    pass  # поле уже есть

# --- ДОБАВЛЕНО: добавляем поле is_priority, если его нет ---
try:
    c.execute('ALTER TABLE poll_option_settings ADD COLUMN is_priority INTEGER DEFAULT 0')
    conn.commit()
except Exception:
    pass  # поле уже есть

try:
    c.execute('ALTER TABLE polls ADD COLUMN message_id INTEGER')
    conn.commit()
except Exception:
    pass # поле уже есть

# --- ДОБАВЛЕНО: поле для суммы сбора в настройки опроса ---
try:
    c.execute('ALTER TABLE poll_settings ADD COLUMN target_sum REAL DEFAULT 0')
    conn.commit()
except Exception:
    pass # поле уже есть

# --- ДОБАВЛЕНО: поле для суммы взноса в настройки варианта ответа ---
try:
    c.execute('ALTER TABLE poll_option_settings ADD COLUMN contribution_amount REAL DEFAULT 0')
    conn.commit()
except Exception:
    pass # поле уже есть

conn.commit()

# --- ДОБАВЛЕНО: функция для добавления пользователя в participants ---
def add_user_to_participants(update):
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

async def get_known_admin_chats(user_id: int) -> list:
    c.execute('SELECT DISTINCT chat_id, title FROM known_chats')
    chats = c.fetchall()
    admin_chats = []
    for chat_id, title in chats:
        try:
            admins = await context.bot.get_chat_administrators(chat_id)
            if user_id in [admin.user.id for admin in admins]:
                admin_chats.append((chat_id, title))
        except Exception as e:
            logger.error(f'Error checking admin status in chat {chat_id}: {e}')
    return admin_chats

async def get_admin_chats(update: Update, context: ContextTypes.DEFAULT_TYPE) -> list:
    user_id = update.effective_user.id
    admin_chats = []
    try:
        # First, try to get chats from known_chats table
        c.execute('SELECT DISTINCT chat_id, title FROM known_chats')
        known_chats = c.fetchall()
        for chat_id, title in known_chats:
            try:
                admins = await context.bot.get_chat_administrators(chat_id)
                if user_id in [admin.user.id for admin in admins]:
                    admin_chats.append(type('Chat', (), {'id': chat_id, 'title': title, 'type': 'group'}))
            except Exception as e:
                logger.error(f'Error checking admin status in known chat {chat_id}: {e}')
    except Exception as e:
        logger.error(f'Error getting chats: {e}')
    return admin_chats

async def select_chat(update: Union[Update, CallbackQuery], context: ContextTypes.DEFAULT_TYPE, command: str) -> None:
    # Handle both Update and CallbackQuery objects
    if isinstance(update, CallbackQuery):
        user_id = update.from_user.id
        admin_chats = []
        try:
            c.execute('SELECT DISTINCT chat_id, title FROM known_chats')
            known_chats = c.fetchall()
            for chat_id, title in known_chats:
                try:
                    admins = await context.bot.get_chat_administrators(chat_id)
                    if user_id in [admin.user.id for admin in admins]:
                        admin_chats.append(type('Chat', (), {'id': chat_id, 'title': title, 'type': 'group'}))
                except Exception as e:
                    logger.error(f'Error checking admin status in known chat {chat_id}: {e}')
        except Exception as e:
            logger.error(f'Error getting chats: {e}')
    else:
        user_id = update.effective_user.id
        admin_chats = await get_admin_chats(update, context)

    if len(admin_chats) == 0:
        await context.bot.send_message(chat_id=user_id, text='Я не знаю ни одной группы, где вы администратор. Пожалуйста, для начала, выполните любую команду в группе, где вы являетесь администратором, чтобы я ее узнал.')
        return
    # ВСЕГДА показываем меню выбора группы, даже если она одна
    keyboard = [[InlineKeyboardButton(chat.title, callback_data=f'selectchat_{chat.id}_{command}')] for chat in admin_chats]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await context.bot.send_message(chat_id=user_id, text='Выберите группу для выполнения команды:', reply_markup=reply_markup)

async def select_chat_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    chat_id, command = map(str, query.data.split('_')[1:])
    context.user_data['selected_chat_id'] = int(chat_id)
    # Если был флаг after_select_action, продолжаем диалог
    after = context.user_data.pop('after_select_action', None)
    if after == 'setmessage':
        context.user_data['waiting_for_poll_message'] = True
        await context.bot.send_message(chat_id=query.from_user.id, text='Пожалуйста, отправьте текст опроса одним сообщением.')
        await query.message.delete()
        return
    elif after == 'setoptions':
        context.user_data['waiting_for_poll_options'] = True
        await context.bot.send_message(chat_id=query.from_user.id, text='Пожалуйста, отправьте варианты ответа через запятую одним сообщением.')
        await query.message.delete()
        return
    # Если выбрана команда newpoll, сразу создаём черновик опроса и сообщаем об этом
    if command == 'newpoll':
        # Создаём черновик опроса
        user_id = query.from_user.id
        try:
            cursor = c.execute('INSERT INTO polls (chat_id, message, status, options) VALUES (?, ?, ?, ?)', (int(chat_id), '', 'draft', 'Перевел,Позже,Не участвую'))
            poll_id = cursor.lastrowid
            conn.commit()
            logger.info(f'[NEWPOLL] Создан новый опрос: poll_id={poll_id}, chat_id={chat_id}')
            # Удаляем все старые черновики кроме только что созданного
            c.execute('DELETE FROM polls WHERE chat_id = ? AND status = ? AND poll_id != ?', (int(chat_id), 'draft', poll_id))
            conn.commit()
            await context.bot.send_message(chat_id=user_id, text=f'Создан новый опрос с ID {poll_id}. Используйте /setmessage и /setoptions для настройки.')
        except Exception as e:
            logger.error(f'[NEWPOLL] Ошибка при создании опроса: {e}')
            await context.bot.send_message(chat_id=user_id, text=f'Ошибка при создании опроса: {e}')
        await query.message.delete()
        return
    await execute_command(update, context, command)
    await query.message.delete()

async def execute_command(update: Union[Update, CallbackQuery], context: ContextTypes.DEFAULT_TYPE, command: str) -> None:
    # Convert CallbackQuery to appropriate format for command functions
    if isinstance(update, CallbackQuery):
        # Create a wrapper object that mimics the needed Update attributes
        class UpdateWrapper:
            def __init__(self, query):
                self.effective_user = query.from_user
                self.effective_chat = query.message.chat
                self.callback_query = query
        update_obj = UpdateWrapper(update)
    else:
        update_obj = update

    add_user_to_participants(update_obj)

    if command == 'collect':
        await collect(update_obj, context)
    elif command == 'exclude':
        await exclude(update_obj, context)
    elif command == 'newpoll':
        await newpoll(update_obj, context)
    elif command == 'startpoll':
        await startpoll(update_obj, context)
    elif command == 'results':
        await results(update_obj, context)
    elif command == 'setresultoptions':  # <--- ДОБАВИТЬ ЭТО
        await setresultoptions(update_obj, context)

# --- ДОБАВЛЕНО: функция для получения названия группы по chat_id ---
def get_group_title(chat_id):
    c.execute('SELECT title FROM known_chats WHERE chat_id = ?', (chat_id,))
    row = c.fetchone()
    return row[0] if row else str(chat_id)

# --- ДОБАВЛЕНО: обработка диалога для setmessage/setoptions ---
async def message_dialog_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    chat_id = context.user_data.get('selected_chat_id')

    if not chat_id:
        logger.error(f'[MSG_DIALOG] Не выбран chat_id для user_id={user_id}')
        await update.message.reply_text('Ошибка: не выбрана группа. Пожалуйста, начните заново, выбрав группу через /newpoll.')
        context.user_data.pop('waiting_for_poll_message', None)
        context.user_data.pop('waiting_for_poll_options', None)
        return

    if context.user_data.get('waiting_for_poll_message'):
        try:
            c.execute('SELECT poll_id, message FROM polls WHERE chat_id = ? AND status = ? ORDER BY poll_id DESC LIMIT 1', (chat_id, 'draft'))
            row = c.fetchone()
            logger.info(f'[MSG_DIALOG] SELECT poll_id, message FROM polls WHERE chat_id={chat_id} AND status="draft" => {row}')
            if not row:
                logger.error(f'[MSG_DIALOG] Нет черновика опроса для chat_id={chat_id}')
                await update.message.reply_text('Сначала создайте опрос через /newpoll.')
                context.user_data.pop('waiting_for_poll_message', None)
                return
            poll_id, old_message = row
            message = update.message.text
            c.execute('UPDATE polls SET message = ? WHERE poll_id = ?', (message, poll_id))
            conn.commit()
            c.execute('SELECT message FROM polls WHERE poll_id = ?', (poll_id,))
            new_message = c.fetchone()[0]
            group_title = get_group_title(chat_id)
            debug_text = (
                f'[DEBUG] Текст опроса обновлён!\n'
                f'ID опроса: {poll_id}\n'
                f'Группа: {group_title} (ID: {chat_id})\n'
                f'Старое значение: {old_message}\n'
                f'Новое значение: {new_message}'
            )
            logger.info(debug_text)
            await update.message.reply_text(f'Сообщение для опроса {poll_id} установлено: {message}\n\n{debug_text}')
            context.user_data.pop('waiting_for_poll_message', None)
            # --- Запросить варианты ответа ---
            context.user_data['waiting_for_poll_options'] = True
            await update.message.reply_text('Пожалуйста, отправьте варианты ответа через запятую одним сообщением.')
        except Exception as e:
            logger.error(f'[MSG_DIALOG] Ошибка при установке текста опроса: {e}', exc_info=True)
            await update.message.reply_text(f'Ошибка при установке текста опроса: {e}')
        return
    if context.user_data.get('waiting_for_poll_options'):
        try:
            c.execute('SELECT poll_id, options FROM polls WHERE chat_id = ? AND status = ? ORDER BY poll_id DESC LIMIT 1', (chat_id, 'draft'))
            row = c.fetchone()
            logger.info(f'[MSG_DIALOG] SELECT poll_id, options FROM polls WHERE chat_id={chat_id} AND status="draft" => {row}')
            if not row:
                logger.error(f'[MSG_DIALOG] Нет черновика опроса для chat_id={chat_id} при установке вариантов')
                await update.message.reply_text('Сначала выберите группу через /newpoll.')
                context.user_data.pop('waiting_for_poll_options', None)
                return
            poll_id, old_options = row
            options = update.message.text.split(',')
            if len(options) < 2:
                logger.warning(f'[MSG_DIALOG] Меньше двух вариантов ответа: {options}')
                await update.message.reply_text('Укажите как минимум 2 варианта ответа через запятую.')
                return
            options_str = ','.join(options)
            c.execute('UPDATE polls SET options = ? WHERE poll_id = ?', (options_str, poll_id))
            conn.commit()
            c.execute('SELECT options FROM polls WHERE poll_id = ?', (poll_id,))
            new_options = c.fetchone()[0]
            c.execute('SELECT message FROM polls WHERE poll_id = ?', (poll_id,))
            poll_message = c.fetchone()[0]
            group_title = get_group_title(chat_id)
            debug_text = (
                f'[DEBUG] Варианты опроса обновлены!\n'
                f'ID опроса: {poll_id}\n'
                f'Группа: {group_title} (ID: {chat_id})\n'
                f'Текст опроса: {poll_message}\n'
                f'Старые варианты: {old_options}\n'
                f'Новые варианты: {new_options}'
            )
            logger.info(debug_text)
            await update.message.reply_text(f'Варианты ответов для опроса {poll_id} установлены: {options_str}\n\n{debug_text}')
            context.user_data.pop('waiting_for_poll_options', None)
        except Exception as e:
            logger.error(f'[MSG_DIALOG] Ошибка при установке вариантов ответа: {e}', exc_info=True)
            await update.message.reply_text(f'Ошибка при установке вариантов ответа: {e}')
        return

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    add_user_to_participants(update)
    chat = update.effective_chat

    if chat.type in ['group', 'supergroup']:
        # В группе просто обновляем информацию о чате и даем подсказку
        await update_known_chats(chat.id, chat.title)
        try:
            me = await context.bot.get_me()
            await update.message.reply_text(
                f"Привет! Для управления опросами, пожалуйста, напишите мне в личные сообщения: @{me.username}",
                disable_web_page_preview=True
            )
        except Exception as e:
            logger.error(f"Could not send welcome message in group {chat.id}: {e}")
    else:  # В личной переписке показываем главный экран
        await private_chat_entry_point(update, context)

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    add_user_to_participants(update)
    chat = update.effective_chat
    if chat.type == 'private':
        # В личной переписке показываем главный экран
        await private_chat_entry_point(update, context)
    else:
        # В группе показываем текстовую справку
        await update.message.reply_text(
            'Доступные команды в группе:\n/start - Начать работу с ботом\n/help - Показать эту справку'
            '\n\nВсе управление опросами (создание, настройка, результаты) происходит в личном чате с ботом.'
        )

async def collect(update: Update, context: ContextTypes.DEFAULT_TYPE):
    add_user_to_participants(update)
    chat_id = update.effective_chat.id
    if update.callback_query:
        await update.callback_query.message.reply_text("Unfortunately, collecting all group members is not directly supported in the current version of the Telegram API used by this bot. If you need to manage group members, please use Telegram's built-in features or contact support for alternative solutions.")
    else:
        await update.message.reply_text("Unfortunately, collecting all group members is not directly supported in the current version of the Telegram API used by this bot. If you need to manage group members, please use Telegram's built-in features or contact support for alternative solutions.")
    return

async def exclude(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    add_user_to_participants(update)
    user_id = update.effective_user.id
    if update.effective_chat.type == 'private':
        await context.bot.send_message(chat_id=user_id, text='Эта команда устарела. Пожалуйста, используйте меню "Участники" на панели управления.')
        await private_chat_entry_point(update, context)
    else:
        await update.message.reply_text('Для управления участниками, пожалуйста, воспользуйтесь панелью управления в личном чате с ботом.')

async def newpoll(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    add_user_to_participants(update)
    user_id = update.effective_user.id
    if update.effective_chat.type == 'private':
        await context.bot.send_message(chat_id=user_id, text='Эта команда устарела. Пожалуйста, используйте кнопку "Создать опрос" на панели управления.')
        await private_chat_entry_point(update, context)
    else:
        await update.message.reply_text("Для создания опроса, пожалуйста, воспользуйтесь панелью управления в личном чате с ботом.")

def generate_poll_text(poll_id: int) -> str:
    """Generates the text for the public poll message, including counts, fundraising info, and voter names."""
    c.execute('SELECT message, options FROM polls WHERE poll_id = ?', (poll_id,))
    poll_data = c.fetchone()
    if not poll_data:
        return "Опрос не найден."
    
    message, options_str = poll_data
    original_options = [opt.strip() for opt in options_str.split(',')]
    
    c.execute('SELECT user_id, response FROM responses WHERE poll_id = ?', (poll_id,))
    responses = c.fetchall()
    counts = {}
    for _, response in responses:
        counts[response] = counts.get(response, 0) + 1
        
    c.execute('SELECT default_show_names, default_names_style, target_sum FROM poll_settings WHERE poll_id = ?', (poll_id,))
    default_settings_res = c.fetchone()
    default_show_names, default_names_style, target_sum = (default_settings_res or (1, 'list', 0))
    
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
            'names_style': opt_settings[1] if opt_settings and opt_settings[1] is not None else default_names_style,
            'is_priority': opt_settings[2] if opt_settings and opt_settings[2] is not None else 0,
            'contribution_amount': opt_settings[3] if opt_settings and opt_settings[3] is not None else 0,
            'emoji': (opt_settings[4] + ' ') if opt_settings and opt_settings[4] else ""
        })

    options_with_settings.sort(key=lambda x: x['is_priority'], reverse=True)

    for option_data in options_with_settings:
        option_text = option_data['text']
        count = counts.get(option_text, 0)
        contribution_amount = option_data['contribution_amount']
        
        if contribution_amount > 0:
            total_collected += count * contribution_amount
            
        priority_marker = "⭐ " if option_data['is_priority'] else "☆ "
        formatted_option_text = f"*{option_text}*" if option_data['is_priority'] else option_text
        option_line = f"{priority_marker}{formatted_option_text}"

        if contribution_amount > 0:
             option_line += f" (по {int(contribution_amount)})"
        
        option_line += f": *{count}*"
        text_parts.append(option_line)

        if option_data['show_names'] and count > 0:
            responders = [r[0] for r in responses if r[1] == option_text]
            user_names = [get_user_name(uid) for uid in responders]
            names_text_list = [f"{option_data['emoji']}{name}" for name in user_names]

            names_style = option_data['names_style']
            indent = "    "
            if names_style == 'list':
                text_parts.append("\n".join(f"{indent}{name}" for name in names_text_list))
            elif names_style == 'inline':
                text_parts.append(f'{indent}{", ".join(names_text_list)}')
            elif names_style == 'small':
                small_names = [name.split()[0] for name in user_names]
                text_parts.append(f'{indent}`{", ".join(small_names)}`')
        
        text_parts.append("")

    if target_sum > 0:
        bar, percent = get_progress_bar(total_collected, target_sum)
        text_parts.append(f"💰 Собрано: *{int(total_collected)} из {int(target_sum)}* ({percent:.1f}%)\n{bar}")
    elif total_collected > 0:
        text_parts.append(f"💰 Собрано: *{int(total_collected)}*")
    
    # Clean up trailing newlines before the final summary
    while text_parts and text_parts[-1] == "":
        text_parts.pop()

    text_parts.append(f"\nВсего проголосовало: *{total_votes}*")
    
    return "\n".join(text_parts)

async def update_poll_message(poll_id: int, context: ContextTypes.DEFAULT_TYPE):
    """Fetches the latest data and edits the poll message in the group."""
    logger.info(f"[POLL_UPDATE] Attempting to update message for poll_id={poll_id}")
    c.execute('SELECT chat_id, message_id, options FROM polls WHERE poll_id = ?', (poll_id,))
    poll_data = c.fetchone()
    if not poll_data:
        logger.error(f"[POLL UPDATE] Poll {poll_id} not found.")
        return
        
    chat_id, message_id, options_str = poll_data
    logger.info(f"[POLL_UPDATE] Found poll {poll_id} in chat {chat_id} with message_id {message_id}")
    if not message_id:
        logger.warning(f"[POLL UPDATE] No message_id for poll {poll_id}.")
        return

    new_text = generate_poll_text(poll_id)
    logger.info(f"[POLL_UPDATE] Generated new text for poll {poll_id}.")
    
    options = [opt.strip() for opt in options_str.split(',')]
    keyboard = [[InlineKeyboardButton(option.strip(), callback_data=f'poll_{poll_id}_{i}')] for i, option in enumerate(options)]
    reply_markup = InlineKeyboardMarkup(keyboard)

    try:
        logger.info(f"[POLL_UPDATE] Sending edit_message_text for poll {poll_id} to chat {chat_id}, message {message_id}")
        await context.bot.edit_message_text(
            text=new_text,
            chat_id=chat_id,
            message_id=message_id,
            reply_markup=reply_markup,
            parse_mode=ParseMode.MARKDOWN
        )
        logger.info(f"[POLL_UPDATE] Successfully edited message for poll {poll_id}.")
    except ChatMigrated as e:
        logger.warning(f"[POLL UPDATE] Chat migrated for poll {poll_id}. Old: {chat_id}, New: {e.new_chat_id}")
        c.execute('UPDATE polls SET chat_id = ? WHERE poll_id = ?', (e.new_chat_id, poll_id))
        conn.commit()
    except Exception as e:
        if "Message is not modified" not in str(e):
             logger.error(f"[POLL UPDATE] Failed to edit message for poll {poll_id}: {e}")
        else:
            logger.info(f"[POLL_UPDATE] Message for poll {poll_id} was not modified.")

async def startpoll_from_dashboard(update: Update, context: ContextTypes.DEFAULT_TYPE, poll_id: int, chat_id: int):
    """Запускает опрос из панели управления."""
    user_id = update.effective_user.id
    query = update.callback_query

    # Проверка на админа
    try:
        admins = await context.bot.get_chat_administrators(chat_id)
        if user_id not in [admin.user.id for admin in admins]:
            await query.answer('Ошибка: вы больше не администратор в этой группе.', show_alert=True)
            return
    except Exception as e:
        logger.error(f'Failed to check admin status for user {user_id} in chat {chat_id}: {e}')
        await query.answer('Не удалось проверить ваши права в группе.', show_alert=True)
        return

    # Получаем черновик
    c.execute('SELECT message, options FROM polls WHERE poll_id = ? AND status = ?', (poll_id, 'draft'))
    result = c.fetchone()

    if not result:
        await query.answer("Ошибка: не найден черновик для запуска.", show_alert=True)
        return

    message, options_str = result
    if not message or not message.strip():
        await query.answer('Сначала задайте текст опроса через меню редактирования.', show_alert=True)
        return
    if not options_str or not any(opt.strip() for opt in options_str.split(',')):
        await query.answer('Сначала задайте варианты ответа через меню редактирования.', show_alert=True)
        return

    # Запускаем опрос
    options = options_str.split(',')
    c.execute('UPDATE polls SET status = ? WHERE poll_id = ?', ('active', poll_id))
    conn.commit()
    
    keyboard = [[InlineKeyboardButton(option.strip(), callback_data=f'poll_{poll_id}_{i}')] for i, option in enumerate(options)]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    initial_text = generate_poll_text(poll_id)

    try:
        poll_message = await context.bot.send_message(chat_id=chat_id, text=initial_text, reply_markup=reply_markup, parse_mode=ParseMode.MARKDOWN)
        c.execute('UPDATE polls SET message_id = ? WHERE poll_id = ?', (poll_message.message_id, poll_id))
        conn.commit()
        await query.answer(f'Опрос {poll_id} успешно запущен в группе.', show_alert=True)
    except Exception as e:
        logger.error(f"Ошибка при запуске опроса {poll_id} в чате {chat_id}: {e}")
        # Откатываем статус обратно
        c.execute('UPDATE polls SET status = ? WHERE poll_id = ?', ('draft', poll_id))
        conn.commit()
        await query.answer(f'Ошибка при запуске опроса в группе: {e}', show_alert=True)

async def startpoll(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    # Эта команда теперь считается устаревшей для личных чатов.
    # В группах она никогда не работала осмысленно.
    # Перенаправляем пользователя в личный чат.
    chat = update.effective_chat
    user_id = update.effective_user.id
    if chat.type == 'private':
        await context.bot.send_message(chat_id=user_id, text='Эта команда устарела. Пожалуйста, используйте панель управления для запуска опросов.')
        await private_chat_entry_point(update, context)
    else:
        await update.message.reply_text('Для запуска опроса, пожалуйста, воспользуйтесь панелью управления в личном чате с ботом.')

async def cleangroup(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Clears the participant list for a group."""
    add_user_to_participants(update)
    chat_id = None
    if update.effective_chat.type in ['group', 'supergroup']:
        chat_id = update.effective_chat.id
    elif 'selected_chat_id' in context.user_data:
        chat_id = context.user_data['selected_chat_id']
    
    if not chat_id:
        await update.message.reply_text('Не удалось определить группу. Если вы в личном чате, сначала выберите группу на панели управления.')
        return

    c.execute('DELETE FROM participants WHERE chat_id = ?', (chat_id,))
    conn.commit()
    group_title = get_group_title(chat_id)
    await update.message.reply_text(f'Список участников для группы "{group_title}" очищен.')

# --- Группы и выбор группы ---
async def groups(update: Update, context: ContextTypes.DEFAULT_TYPE):
    my_id = update.effective_user.id
    bot_id = (await context.bot.get_me()).id
    groups = []
    # Получаем чаты из базы опросов, где бот уже работал
    c.execute('SELECT DISTINCT chat_id FROM polls')
    chat_ids = [row[0] for row in c.fetchall()]
    for chat_id in chat_ids:
        try:
            chat = await context.bot.get_chat(chat_id)
            admins = await context.bot.get_chat_administrators(chat_id)
            if any(admin.user.id == my_id for admin in admins) and any(admin.user.id == bot_id for admin in admins):
                groups.append((chat_id, chat.title or str(chat_id)))
        except Exception:
            continue
    if not groups:
        await update.message.reply_text('Бот не найден ни в одной группе, где вы админ. Чтобы группа появилась, выполните любую команду бота в группе.')
        return
    text = 'Ваши группы:\n' + '\n'.join([f'{title} (ID: {gid})' for gid, title in groups])
    await update.message.reply_text(text)

async def use_group(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not context.args:
        await update.message.reply_text('Укажите ID группы, например: /use -123456789')
        return
    group_id = int(context.args[0])
    my_id = update.effective_user.id
    try:
        admins = await context.bot.get_chat_administrators(group_id)
        if not any(admin.user.id == my_id for admin in admins):
            await update.message.reply_text('Вы не админ в этой группе.')
            return
        bot_id = (await context.bot.get_me()).id
        if not any(admin.user.id == bot_id for admin in admins):
            await update.message.reply_text('Бот не админ в этой группе.')
            return
    except Exception as e:
        await update.message.reply_text('Ошибка доступа к группе.')
        return
    c.execute('INSERT OR REPLACE INTO admin_context (user_id, group_id) VALUES (?, ?)', (my_id, group_id))
    conn.commit()
    await update.message.reply_text(f'Теперь все команды будут работать с группой ID {group_id}')

# --- Вспомогательная функция для получения chat_id ---
def get_effective_chat_id(update, context):
    if update.effective_chat.type == 'private':
        c.execute('SELECT group_id FROM admin_context WHERE user_id = ?', (update.effective_user.id,))
        row = c.fetchone()
        if not row:
            return None
        return row[0]
    else:
        return update.effective_chat.id

# --- Настройка вывода результатов опроса ---
async def setresultoptions(update: Update, context: ContextTypes.DEFAULT_TYPE, from_dashboard: bool = False):
    add_user_to_participants(update)
    user_id = update.effective_user.id
    # Определяем chat_id
    chat_id = None
    if update.effective_chat.type in ['group', 'supergroup']:
        chat_id = update.effective_chat.id
        context.user_data['selected_chat_id'] = chat_id
    elif 'selected_chat_id' in context.user_data:
        chat_id = context.user_data['selected_chat_id']
    else:
        # If no chat is selected in a private chat, send them to the entry point
        await private_chat_entry_point(update, context)
        return
    # Получаем все опросы в группе
    c.execute('SELECT poll_id, message, status FROM polls WHERE chat_id = ? ORDER BY poll_id DESC', (chat_id,))
    polls = c.fetchall()
    if not polls:
        await context.bot.send_message(chat_id=user_id, text='Нет опросов для настройки.')
        return
    if len(polls) > 1 and 'setresultoptions_poll_id' not in context.user_data:
        # Показываем меню выбора опроса
        keyboard = []
        for poll_id, message, status in polls[:10]:
            short_msg = (message[:20] + '...') if message and len(message) > 20 else (message or f'Опрос {poll_id}')
            keyboard.append([InlineKeyboardButton(f'ID {poll_id}: {short_msg} [{status}]', callback_data=f'setresultoptionspoll_{poll_id}')])
        await context.bot.send_message(chat_id=user_id, text='Выберите опрос для настройки:', reply_markup=InlineKeyboardMarkup(keyboard))
        return
    # Если выбран poll_id через меню или остался только один
    if 'setresultoptions_poll_id' in context.user_data:
        poll_id = context.user_data.pop('setresultoptions_poll_id')
    else:
        poll_id = polls[0][0]
    # Получаем poll_message, options
    c.execute('SELECT message, options FROM polls WHERE poll_id = ?', (poll_id,))
    row = c.fetchone()
    if not row:
        await context.bot.send_message(chat_id=user_id, text='Опрос не найден.')
        return
    poll_message, options_str = row
    options = [opt.strip() for opt in options_str.split(',')]
    # Получаем настройки по умолчанию
    c.execute('SELECT default_show_names, default_names_style, default_show_count FROM poll_settings WHERE poll_id = ?', (poll_id,))
    default_settings = c.fetchone() or (1, 'list', 1)
    logger.info(f'[SETRESULTOPTIONS] Открытие меню настроек для poll_id={poll_id}. Настройки по умолчанию: {default_settings}')
    # Формируем меню для каждого варианта
    keyboard = []
    for idx, opt in enumerate(options):
        c.execute('SELECT show_names, names_style, show_count, emoji, is_priority FROM poll_option_settings WHERE poll_id = ? AND option_index = ?', (poll_id, idx))
        opt_settings = c.fetchone()
        logger.info(f'[SETRESULTOPTIONS] Вариант {idx} ({opt}): индивидуальные настройки: {opt_settings}')
        show_names = default_settings[0] if opt_settings is None or opt_settings[0] is None else opt_settings[0]
        names_style = default_settings[1] if opt_settings is None or opt_settings[1] is None else opt_settings[1]
        show_count = default_settings[2] if opt_settings is None or opt_settings[2] is None else opt_settings[2]
        emoji = opt_settings[3] if opt_settings and opt_settings[3] else None
        is_priority = opt_settings[4] if opt_settings and opt_settings[4] else 0
        btns = [
            InlineKeyboardButton(f"Показывать имена: {'✅' if show_names else '❌'}", callback_data=f"setresultoptions_{poll_id}_{idx}_shownames_{1 if not show_names else 0}"),
            InlineKeyboardButton(f"Показывать итог: {'✅' if show_count else '❌'}", callback_data=f"setresultoptions_{poll_id}_{idx}_showcount_{1 if not show_count else 0}")
        ]
        style_row = [
            InlineKeyboardButton('Список', callback_data=f'setresultoptions_{poll_id}_{idx}_namesstyle_list'),
            InlineKeyboardButton('В строку', callback_data=f'setresultoptions_{poll_id}_{idx}_namesstyle_inline'),
            InlineKeyboardButton('Мелко', callback_data=f'setresultoptions_{poll_id}_{idx}_namesstyle_small')
        ]
        emoji_btn_text = f"Смайлик: {emoji} (сменить)" if emoji else "Установить смайлик"
        emoji_btn = InlineKeyboardButton(emoji_btn_text, callback_data=f"setresultoptions_{poll_id}_{idx}_setemoji")
        priority_btn_text = "⭐ Сделать приоритетным" if not is_priority else "☆ Обычный вариант"
        priority_btn = InlineKeyboardButton(priority_btn_text, callback_data=f"setresultoptions_{poll_id}_{idx}_priority_{1 if not is_priority else 0}")
        edit_text_btn = InlineKeyboardButton("📝 Изменить текст", callback_data=f"setresultoptions_{poll_id}_{idx}_edittext")
        
        # --- ДОБАВЛЕНО: Кнопка для установки взноса ---
        c.execute('SELECT contribution_amount FROM poll_option_settings WHERE poll_id = ? AND option_index = ?', (poll_id, idx))
        contribution_res = c.fetchone()
        contribution_amount = contribution_res[0] if contribution_res and contribution_res[0] is not None else 0
        contribution_btn_text = f"💰 Взнос: {int(contribution_amount)}" if contribution_amount > 0 else "💰 Установить взнос"
        contribution_btn = InlineKeyboardButton(contribution_btn_text, callback_data=f"setresultoptions_{poll_id}_{idx}_setcontribution")

        keyboard.append([InlineKeyboardButton(f'Вариант: {opt}', callback_data='noop')])
        keyboard.append(btns)
        keyboard.append(style_row)
        keyboard.append([emoji_btn, priority_btn])
        keyboard.append([edit_text_btn, contribution_btn])
    # Кнопки для смены стиля по умолчанию для всех вариантов
    style_row_global = [
        InlineKeyboardButton('Список (все)', callback_data=f'setresultoptions_{poll_id}_STYLE_list'),
        InlineKeyboardButton('В строку (все)', callback_data=f'setresultoptions_{poll_id}_STYLE_inline'),
        InlineKeyboardButton('Мелко (все)', callback_data=f'setresultoptions_{poll_id}_STYLE_small')
    ]
    keyboard.append(style_row_global)

    # --- ДОБАВЛЕНО: Кнопка установки целевой суммы ---
    c.execute('SELECT target_sum FROM poll_settings WHERE poll_id = ?', (poll_id,))
    target_sum_res = c.fetchone()
    target_sum = target_sum_res[0] if target_sum_res and target_sum_res[0] is not None else 0
    target_sum_text = f"🎯 Цель сбора: {int(target_sum)}" if target_sum > 0 else "🎯 Установить цель сбора"
    keyboard.append([InlineKeyboardButton(target_sum_text, callback_data=f'setresultoptions_{poll_id}_settargetsum')])

    # Add the "Back" button if called from the dashboard
    if from_dashboard:
        c.execute('SELECT chat_id FROM polls WHERE poll_id = ?', (poll_id,))
        chat_id_res = c.fetchone()
        if chat_id_res:
             keyboard.append([InlineKeyboardButton("↩️ Назад к панели управления", callback_data=f"dash_group_{chat_id_res[0]}")])

    # Send or edit the message
    text_to_send = 'Настройте вывод результатов для каждого варианта:'
    reply_markup = InlineKeyboardMarkup(keyboard)

    if update.callback_query:
        try:
            # Edit the message for a smooth UI flow
            await update.callback_query.edit_message_text(text_to_send, reply_markup=reply_markup)
        except Exception as e:
            logger.error(f"Could not edit message for setresultoptions: {e}")
            # Fallback if editing fails
            await update.callback_query.message.delete()
            await context.bot.send_message(chat_id=user_id, text=text_to_send, reply_markup=reply_markup)
    else: # If called by command
        await context.bot.send_message(chat_id=user_id, text=text_to_send, reply_markup=reply_markup)

# --- Callback для изменения настроек варианта ---
async def setresultoptions_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    logger.info(f'[SETRESULTOPTIONS] setresultoptions_callback CALLED!')
    query = update.callback_query
    await query.answer()
    data = query.data.split('_')
    logger.info(f'[SETRESULTOPTIONS] Callback data: {data}')

    # --- ДОБАВЛЕНО: обработка установки целевой суммы ---
    if len(data) == 3 and data[2] == 'settargetsum':
        poll_id = int(data[1])
        user_id = query.from_user.id
        if user_id not in context.application.user_data:
            context.application.user_data[user_id] = {}
        app_user_data = context.application.user_data[user_id]
        app_user_data['waiting_for_target_sum'] = True
        app_user_data['target_sum_poll_id'] = poll_id
        await query.edit_message_text('Пожалуйста, отправьте целевую сумму сбора (число).')
        return

    # --- ДОБАВЛЕНО: обработка установки взноса ---
    if len(data) == 4 and data[3] == 'setcontribution':
        poll_id = int(data[1])
        option_index = int(data[2])
        user_id = query.from_user.id
        if user_id not in context.application.user_data:
            context.application.user_data[user_id] = {}
        app_user_data = context.application.user_data[user_id]
        app_user_data['waiting_for_contribution'] = True
        app_user_data['contribution_poll_id'] = poll_id
        app_user_data['contribution_option_index'] = option_index
        await query.edit_message_text('Пожалуйста, отправьте сумму взноса для этого варианта (число).')
        return
        
    # Handle setemoji: callback_data=f"setresultoptions_{poll_id}_{idx}_setemoji"
    # data: ['setresultoptions', poll_id, idx, 'setemoji']
    if len(data) == 4 and data[3] == 'setemoji':
        poll_id = int(data[1])
        option_index = int(data[2])
        user_id = query.from_user.id
        
        if user_id not in context.application.user_data:
            context.application.user_data[user_id] = {}
        
        app_user_data = context.application.user_data[user_id]
        app_user_data['waiting_for_emoji'] = True
        app_user_data['setemoji_poll_id'] = poll_id
        app_user_data['setemoji_option_index'] = option_index
        
        try:
            await query.edit_message_text('Пожалуйста, отправьте смайлик в чат.', reply_markup=None)
            await context.bot.send_message(
                chat_id=user_id,
                text='Пожалуйста, отправьте смайлик (эмодзи), который будет выводиться перед каждым участником для этого варианта.'
            )
            logger.info(f'[SETRESULTOPTIONS] setemoji: сообщение успешно отправлено user_id={user_id}')
        except Exception as e:
            logger.error(f'[SETRESULTOPTIONS] setemoji: ошибка при отправке сообщения user_id={user_id}: {e}')
        return
        
    if len(data) == 4 and data[3] == 'edittext':
        poll_id = int(data[1])
        option_index = int(data[2])
        user_id = query.from_user.id

        if user_id not in context.application.user_data:
            context.application.user_data[user_id] = {}
        
        app_user_data = context.application.user_data[user_id]
        app_user_data['waiting_for_option_text'] = True
        app_user_data['edittext_poll_id'] = poll_id
        app_user_data['edittext_option_index'] = option_index
        
        await query.edit_message_text('Пожалуйста, отправьте новый текст для этого варианта ответа.')
        return

    poll_id = int(data[1])

    # Handle global style change: callback_data=f'setresultoptions_{poll_id}_STYLE_list'
    # data: ['setresultoptions', poll_id, 'STYLE', 'list']
    if len(data) == 4 and data[2] == 'STYLE':
        style = data[3]
        c.execute('INSERT OR IGNORE INTO poll_settings (poll_id) VALUES (?)', (poll_id,))
        c.execute('UPDATE poll_settings SET default_names_style = ? WHERE poll_id = ?', (style, poll_id))
        conn.commit()
        logger.info(f'[SETRESULTOPTIONS] Изменён стиль по умолчанию для poll_id={poll_id}: {style}')
        
        await query.edit_message_text('Стиль по умолчанию изменён. Обновляю меню...', reply_markup=None)
        context.user_data['setresultoptions_poll_id'] = poll_id
        await setresultoptions(update, context, from_dashboard=True)
        return

    # Handle individual option settings: callback_data=f"setresultoptions_{poll_id}_{idx}_shownames_{value}"
    # data: ['setresultoptions', poll_id, idx, 'shownames', '1']
    if len(data) == 5:
        option_index = int(data[2])
        field = data[3]
        value = data[4]
        
        c.execute('INSERT OR IGNORE INTO poll_option_settings (poll_id, option_index) VALUES (?, ?)', (poll_id, option_index))
        
        if field == 'shownames':
            c.execute('UPDATE poll_option_settings SET show_names = ? WHERE poll_id = ? AND option_index = ?', (int(value), poll_id, option_index))
        elif field == 'showcount':
            c.execute('UPDATE poll_option_settings SET show_count = ? WHERE poll_id = ? AND option_index = ?', (int(value), poll_id, option_index))
        elif field == 'namesstyle':
            c.execute('UPDATE poll_option_settings SET names_style = ? WHERE poll_id = ? AND option_index = ?', (value, poll_id, option_index))
        elif field == 'priority':
            c.execute('UPDATE poll_option_settings SET is_priority = ? WHERE poll_id = ? AND option_index = ?', (int(value), poll_id, option_index))
        conn.commit()
        
        await query.edit_message_text('Настройка изменена. Обновляю меню...', reply_markup=None)
        context.user_data['setresultoptions_poll_id'] = poll_id
        await setresultoptions(update, context, from_dashboard=True)
        return
        
    logger.warning(f'Необработанные данные в setresultoptions_callback: {data}')


# --- Callback для выбора опроса ---
async def setresultoptionspoll_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    poll_id = int(query.data.split('_')[1])
    context.user_data['setresultoptions_poll_id'] = poll_id
    # Relaunch setresultoptions to show the settings menu
    await setresultoptions(update, context, from_dashboard=True)

# --- Обработчик текстового сообщения для установки эмодзи ---
async def setemoji_message_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    logger.info(f'[SETRESULTOPTIONS] setemoji_message_handler: from user_id={update.effective_user.id}, text={update.message.text}')
    user_id = update.effective_user.id
    if user_id not in context.application.user_data:
        context.application.user_data[user_id] = {}
    app_user_data = context.application.user_data[user_id]
    logger.info(f'[SETRESULTOPTIONS] setemoji_message_handler: app_user_data={app_user_data}')
    if (
        app_user_data.get('waiting_for_emoji') and
        'setemoji_poll_id' in app_user_data and
        'setemoji_option_index' in app_user_data
    ):
        poll_id = app_user_data.pop('setemoji_poll_id')
        option_index = app_user_data.pop('setemoji_option_index')
        app_user_data.pop('waiting_for_emoji', None)
        emoji = update.message.text.strip()
        logger.info(f'[SETRESULTOPTIONS] setemoji_message_handler: попытка сохранить emoji для poll_id={poll_id}, option_index={option_index}, user_id={update.effective_user.id}, emoji={emoji}')
        try:
            c.execute('SELECT emoji FROM poll_option_settings WHERE poll_id = ? AND option_index = ?', (poll_id, option_index))
            old_emoji = c.fetchone()
            logger.info(f'[SETRESULTOPTIONS] setemoji_message_handler: emoji до записи: {old_emoji}')
            c.execute('INSERT OR IGNORE INTO poll_option_settings (poll_id, option_index) VALUES (?, ?)', (poll_id, option_index))
            c.execute('UPDATE poll_option_settings SET emoji = ? WHERE poll_id = ? AND option_index = ?', (emoji, poll_id, option_index))
            conn.commit()
            c.execute('SELECT emoji FROM poll_option_settings WHERE poll_id = ? AND option_index = ?', (poll_id, option_index))
            new_emoji = c.fetchone()
            logger.info(f'[SETRESULTOPTIONS] setemoji_message_handler: emoji после записи: {new_emoji}')
            await update.message.reply_text(f'Смайлик {emoji} сохранён! Он будет отображаться перед каждым участником для этого варианта.')
            logger.info(f'[SETRESULTOPTIONS] setemoji_message_handler: сообщение об успехе отправлено user_id={update.effective_user.id}')
        except Exception as e:
            logger.error(f'[SETRESULTOPTIONS] setemoji_message_handler: ошибка при сохранении или отправке emoji для user_id={update.effective_user.id}: {e}')
        # Вернуться в меню настроек
        context.user_data['setresultoptions_poll_id'] = poll_id
        await setresultoptions(update, context, from_dashboard=True)
        return

async def setoptiontext_message_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if user_id not in context.application.user_data:
        return

    app_user_data = context.application.user_data[user_id]
    if not app_user_data.get('waiting_for_option_text'):
        return

    poll_id = app_user_data.pop('edittext_poll_id')
    option_index = app_user_data.pop('edittext_option_index')
    app_user_data.pop('waiting_for_option_text', None)
    new_text = update.message.text.strip()

    try:
        c.execute('SELECT options FROM polls WHERE poll_id = ?', (poll_id,))
        row = c.fetchone()
        if not row:
            await update.message.reply_text("Не удалось найти опрос для обновления.")
            return

        options_list = row[0].split(',')
        # The text stored in the `responses` table is always stripped.
        # The text from the `options` string might have leading spaces.
        old_text_in_db = options_list[option_index].strip() 
        
        # Now, rebuild the options list carefully to avoid propagating weird spacing.
        # Strip all options before putting the new one in.
        stripped_options = [opt.strip() for opt in options_list]
        stripped_options[option_index] = new_text # new_text is already stripped
        new_options_str = ','.join(stripped_options)

        # Update polls and responses
        c.execute('UPDATE polls SET options = ? WHERE poll_id = ?', (new_options_str, poll_id))
        c.execute('UPDATE responses SET response = ? WHERE poll_id = ? AND response = ?', (new_text, poll_id, old_text_in_db))
        conn.commit()

        await update.message.reply_text(f"Текст варианта обновлен на: '{new_text}'.")

    except Exception as e:
        logger.error(f"Ошибка при обновлении текста варианта: {e}")
        await update.message.reply_text("Произошла ошибка при обновлении текста варианта.")

    # Return to the settings menu
    context.user_data['setresultoptions_poll_id'] = poll_id
    await setresultoptions(update, context, from_dashboard=True)

# --- ДОБАВЛЕНО: Обработчики для установки числовых значений ---
async def settargetsum_message_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    app_user_data = context.application.user_data[user_id]
    poll_id_to_return = app_user_data.get('target_sum_poll_id')
    try:
        amount = float(update.message.text.strip())
        poll_id = app_user_data.pop('target_sum_poll_id')
        app_user_data.pop('waiting_for_target_sum', None)

        c.execute('INSERT OR IGNORE INTO poll_settings (poll_id) VALUES (?)', (poll_id,))
        c.execute('UPDATE poll_settings SET target_sum = ? WHERE poll_id = ?', (amount, poll_id))
        conn.commit()

        await update.message.reply_text(f'Целевая сумма {int(amount)} сохранена.')
    except (ValueError, TypeError):
        await update.message.reply_text('Неверный формат. Пожалуйста, введите число.')
    except Exception as e:
        logger.error(f"Ошибка при сохранении целевой суммы: {e}")
        await update.message.reply_text("Произошла ошибка при сохранении.")

    # Вернуться в меню настроек
    if poll_id_to_return:
        context.user_data['setresultoptions_poll_id'] = poll_id_to_return
        await setresultoptions(update, context, from_dashboard=True)

async def setcontribution_message_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    app_user_data = context.application.user_data[user_id]
    poll_id_to_return = app_user_data.get('contribution_poll_id')
    try:
        amount = float(update.message.text.strip())
        poll_id = app_user_data.pop('contribution_poll_id')
        option_index = app_user_data.pop('contribution_option_index')
        app_user_data.pop('waiting_for_contribution', None)

        c.execute('INSERT OR IGNORE INTO poll_option_settings (poll_id, option_index) VALUES (?, ?)', (poll_id, option_index))
        c.execute('UPDATE poll_option_settings SET contribution_amount = ? WHERE poll_id = ? AND option_index = ?', (amount, poll_id, option_index))
        conn.commit()

        await update.message.reply_text(f'Сумма взноса {int(amount)} сохранена.')
    except (ValueError, TypeError):
        await update.message.reply_text('Неверный формат. Пожалуйста, введите число.')
    except Exception as e:
        logger.error(f"Ошибка при сохранении взноса: {e}")
        await update.message.reply_text("Произошла ошибка при сохранении.")
    
    # Вернуться в меню настроек
    if poll_id_to_return:
        context.user_data['setresultoptions_poll_id'] = poll_id_to_return
        await setresultoptions(update, context, from_dashboard=True)

# --- ДОБАВЛЕНО: Единый обработчик текстовых сообщений ---
async def text_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    
    if user_id in context.application.user_data:
        app_user_data = context.application.user_data[user_id]
        
        # --- Poll Creation Wizard ---
        wizard_state = app_user_data.get('wizard_state')
        
        if wizard_state == 'waiting_for_title':
            title = update.message.text.strip()
            if not title:
                await update.message.reply_text("Текст опроса не может быть пустым. Попробуйте еще раз.")
                return
            app_user_data['wizard_title'] = title
            app_user_data['wizard_state'] = 'waiting_for_options'
            chat_id = app_user_data.get('wizard_chat_id')
            await update.message.reply_text(
                "✅ Отлично! (Шаг 2/2)\n\nТеперь отправьте варианты ответа. Каждый вариант с новой строки или через запятую.",
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("❌ Отмена", callback_data=f"dash_group_{chat_id}")]])
            )
            return

        if wizard_state == 'waiting_for_options':
            options_text = update.message.text
            options = [opt.strip() for opt in options_text.replace('\n', ',').split(',') if opt.strip()]
            if len(options) < 2:
                await update.message.reply_text("Нужно как минимум 2 варианта ответа. Попробуйте еще раз.")
                return

            chat_id = app_user_data.get('wizard_chat_id')
            title = app_user_data.get('wizard_title')
            options_str = ','.join(options)

            cursor = c.execute('INSERT INTO polls (chat_id, message, status, options) VALUES (?, ?, ?, ?)', (chat_id, title, 'draft', options_str))
            poll_id = cursor.lastrowid
            conn.commit()
            logger.info(f'[WIZARD] Создан новый опрос: poll_id={poll_id}, chat_id={chat_id}')
            
            # Cleanup wizard state
            app_user_data.pop('wizard_state', None)
            app_user_data.pop('wizard_chat_id', None)
            app_user_data.pop('wizard_title', None)
            
            await update.message.reply_text(f"🎉 Черновик опроса «{title}» успешно создан!")

            context.user_data['selected_chat_id'] = chat_id
            await show_group_dashboard(update, context, chat_id)
            return
            
        # --- Other handlers ---
        if app_user_data.get('waiting_for_emoji'):
            await setemoji_message_handler(update, context)
            return
        # ... (and so on for other states)

    # Deprecated flow
    if context.user_data.get('waiting_for_poll_message') or context.user_data.get('waiting_for_poll_options'):
        await message_dialog_handler(update, context)
        return


def get_user_name(user_id: int) -> str:
    """Gets a user's name from the database for display."""
    c.execute('SELECT first_name, last_name, username FROM participants WHERE user_id = ?', (user_id,))
    user_data = c.fetchone()
    if not user_data:
        # Fallback in case user is not in participants table for some reason
        return f"Пользователь (ID: {user_id})"

    first_name, last_name, username = user_data
    name = first_name or ''
    if last_name:
        name += f' {last_name}'
    
    if not name.strip():
        name = f'@{username}' if username else f"ID: {user_id}"

    return name.strip()

def get_progress_bar(progress, total, length=20):
    """Generates a text-based progress bar."""
    if total <= 0:
        return "[]", 0
    percent = progress / total
    filled_length = int(length * percent)
    bar = '█' * filled_length + '░' * (length - filled_length)
    return f"[{bar}]", percent * 100

async def show_results(update: Update, context: ContextTypes.DEFAULT_TYPE, poll_id: int, target_chat_id: int):
    """Fetches, formats, and sends the detailed results for a specific poll."""
    try:
        c.execute('SELECT message, options, status, chat_id FROM polls WHERE poll_id = ?', (poll_id,))
        poll_data = c.fetchone()
        if not poll_data:
            await context.bot.send_message(chat_id=target_chat_id, text=f"Не удалось найти опрос с ID {poll_id}.")
            return

        poll_message, options_str, status, group_chat_id = poll_data
        original_options = [opt.strip() for opt in options_str.split(',')]

        c.execute('SELECT user_id, response FROM responses WHERE poll_id = ?', (poll_id,))
        responses = c.fetchall()

        c.execute('SELECT default_show_names, default_names_style, default_show_count, target_sum FROM poll_settings WHERE poll_id = ?', (poll_id,))
        default_settings = c.fetchone() or (1, 'list', 1, 0)
        default_show_names, default_names_style, default_show_count, target_sum = default_settings

        result_text = f"📊 *Результаты опроса: {poll_message}* (ID: {poll_id})\nСтатус: {status}\n\n"
        total_collected = 0
        
        options_with_settings = []
        for i, option_text in enumerate(original_options):
            c.execute('SELECT show_names, names_style, show_count, emoji, is_priority, contribution_amount FROM poll_option_settings WHERE poll_id = ? AND option_index = ?', (poll_id, i))
            opt_settings = c.fetchone()
            options_with_settings.append({
                'text': option_text,
                'index': i,
                'settings': opt_settings or (None, None, None, None, 0, 0)
            })

        options_with_settings.sort(key=lambda x: x['settings'][4], reverse=True)
        
        for option_data in options_with_settings:
            option_text = option_data['text']
            settings = option_data['settings']
            
            show_names = default_show_names if settings[0] is None else settings[0]
            names_style = default_names_style if settings[1] is None else settings[1]
            show_count = default_show_count if settings[2] is None else settings[2]
            emoji = (settings[3] + ' ') if settings[3] else ""
            is_priority = settings[4] if settings[4] is not None else 0
            contribution_amount = settings[5] if settings[5] is not None else 0

            responders = [r[0] for r in responses if r[1] == option_text]
            num_responders = len(responders)
            
            priority_marker = "⭐ " if is_priority else "☆ "
            formatted_option_text = f"*{option_text}*" if is_priority else option_text
            option_line = f"{priority_marker}{formatted_option_text}"

            if contribution_amount > 0:
                option_total = num_responders * contribution_amount
                total_collected += option_total
                option_line += f" (по {int(contribution_amount)})"
            
            if show_count:
                option_line += f" — *{num_responders}*"
            
            result_text += option_line + "\n"

            if show_names and num_responders > 0:
                user_names = [get_user_name(uid) for uid in responders]
                names_text = [f"{emoji}{name}" for name in user_names]
                indent = "    "
                if names_style == 'list':
                    result_text += "\n".join(f"{indent}{name}" for name in names_text) + "\n\n"
                elif names_style == 'inline':
                    result_text += f'{indent}{", ".join(names_text)}\n\n'
                elif names_style == 'small':
                    small_names = [name.split()[0] for name in user_names]
                    result_text += f'{indent}`{", ".join(small_names)}`\n\n'
            else:
                 result_text += "\n"

        if target_sum > 0:
            bar, percent = get_progress_bar(total_collected, target_sum)
            result_text += f"💰 Собрано: *{int(total_collected)} из {int(target_sum)}* ({percent:.1f}%)\n{bar}\n\n"
        
        keyboard_buttons = [
            [InlineKeyboardButton("🔄 Обновить", callback_data=f"refreshresults_{poll_id}")],
            [InlineKeyboardButton("⚙️ Настроить", callback_data=f"setresultoptionspoll_{poll_id}")]
        ]
        
        query = update.callback_query
        if query:
            poll_status = 'active' if status == 'active' else 'draft'
            keyboard_buttons.append([InlineKeyboardButton("↩️ Назад к списку", callback_data=f"dash_polls_{group_chat_id}_{poll_status}")])

        reply_markup = InlineKeyboardMarkup(keyboard_buttons)
        message_kwargs = {"text": result_text, "reply_markup": reply_markup, "parse_mode": ParseMode.MARKDOWN}
        
        if query and query.data.startswith('refreshresults_'):
             try:
                await query.edit_message_text(**message_kwargs)
                await query.answer("Результаты обновлены.")
             except Exception as e:
                 if "Message is not modified" not in str(e):
                    logger.warning(f"Could not edit message for refresh, probably unchanged: {e}")
                 await query.answer("Нет изменений.")
        elif query:
            await query.edit_message_text(**message_kwargs)
        else:
            await context.bot.send_message(chat_id=target_chat_id, **message_kwargs)

    except Exception as e:
        logger.error(f"Error in show_results for poll_id {poll_id}: {e}", exc_info=True)
        await context.bot.send_message(chat_id=target_chat_id, text="Произошла серьезная ошибка при отображении результатов.")


async def results_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handles callback query for showing results."""
    query = update.callback_query
    await query.answer()
    try:
        poll_id = int(query.data.split('_')[1])
        await show_results(update, context, poll_id, query.from_user.id)
    except (IndexError, ValueError) as e:
        logger.warning(f"Could not parse poll_id from results_callback data: {query.data} ({e})")
        await query.edit_message_text("Ошибка: не удалось определить опрос для отображения результатов.")


async def refresh_results_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handles the refresh button on the results message."""
    query = update.callback_query
    try:
        poll_id = int(query.data.split('_')[1])
        # The show_results function will handle the query.answer()
        await show_results(update, context, poll_id, query.from_user.id)
    except Exception as e:
        logger.error(f"Error in refresh_results_callback: {e}", exc_info=True)
        await query.answer("Ошибка при обновлении.", show_alert=True)


async def track_group_user(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Tracks users who speak in the group to add them to the participants list."""
    if update.message:
        add_user_to_participants(update)


async def results(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    # This command is now deprecated for private chats
    if update.effective_chat.type == 'private':
        await update.message.reply_text('Для просмотра результатов, пожалуйста, воспользуйтесь панелью управления.')
        await private_chat_entry_point(update, context)
        return

    add_user_to_participants(update)
    chat_id = update.effective_chat.id
    user_id = update.effective_user.id
    
    if user_id not in [admin.user.id for admin in await context.bot.get_chat_administrators(chat_id)]:
        await update.message.reply_text('Только администраторы могут использовать эту команду.')
        return
    context.user_data['selected_chat_id'] = chat_id
    
    c.execute('SELECT poll_id FROM polls WHERE chat_id = ? AND status = ?', (chat_id, 'active'))
    active_polls = c.fetchall()
    if not active_polls:
        try:
            # Send a reply in the group that there are no active polls
            await update.message.reply_text('В этой группе нет активных опросов.')
        except Exception as e:
            logger.warning(f"Could not reply in group {chat_id}: {e}")
        return
    
    # Send results to the user's private chat
    try:
        await context.bot.send_message(chat_id=user_id, text=f'Результаты для группы "{update.effective_chat.title}":')
        for poll_id, in active_polls:
            await show_results(update, context, poll_id, user_id)
        
        # --- ENHANCEMENT: Reply in the group chat ---
        await update.message.reply_text(
            f'✅ Результаты отправлены вам в личные сообщения, {update.effective_user.first_name}.',
            disable_web_page_preview=True
        )
    except Exception as e:
        logger.error(f"Could not send results to user {user_id} or reply in group {chat_id}: {e}")
        try:
            # Fallback reply in group if sending DMs failed
            await update.message.reply_text(f'Не удалось отправить результаты в личные сообщения. Возможно, вы не начали диалог со мной? Пожалуйста, напишите мне в ЛС: @{(await context.bot.get_me()).username}')
        except Exception as e2:
            logger.error(f"Could not even send the fallback message in group {chat_id}: {e2}")


async def log_all_updates(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Logs every update received by the bot for debugging purposes."""
    logger.info(f"[GLOBAL_UPDATE_LOGGER] Update received: {update.to_dict()}")

    if context.bot_data.get('debug_mode_enabled', False):
        print("\n" + "="*80)
        print(f"DEBUG: Event received at {time.time()}")
        print(f"Update Details: {update}")
        print("="*80 + "\n")


async def toggle_debug(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Toggles the debug message mode."""
    is_enabled = context.bot_data.get('debug_mode_enabled', False)
    context.bot_data['debug_mode_enabled'] = not is_enabled
    await update.message.reply_text(f"Debug messaging is now {'ENABLED' if not is_enabled else 'DISABLED'}.")


def main() -> None:
    application = Application.builder().token(BOT_TOKEN).build()

    # --- Global Update Logger for Debugging ---
    application.add_handler(TypeHandler(Update, log_all_updates), group=-1)

    # --- Core Commands ---
    application.add_handler(CommandHandler('start', start))
    application.add_handler(CommandHandler('help', help_command))
    application.add_handler(CommandHandler('toggle_debug', toggle_debug))

    # --- Legacy/Utility Commands ---
    application.add_handler(CommandHandler('collect', collect))
    application.add_handler(CommandHandler('exclude', exclude))
    application.add_handler(CommandHandler('startpoll', startpoll)) # Deprecated
    application.add_handler(CommandHandler('results', results))
    application.add_handler(CommandHandler('cleangroup', cleangroup))
    application.add_handler(CommandHandler('setresultoptions', setresultoptions)) # Kept for potential direct access

    # --- Callback Query Handlers ---
    application.add_handler(CallbackQueryHandler(results_callback, pattern='^results_'))
    application.add_handler(CallbackQueryHandler(setresultoptions_callback, pattern='^setresultoptions_'))
    application.add_handler(CallbackQueryHandler(setresultoptionspoll_callback, pattern='^setresultoptionspoll_'))
    application.add_handler(CallbackQueryHandler(refresh_results_callback, pattern='^refreshresults_'))
    application.add_handler(CallbackQueryHandler(dashboard_callback_handler, pattern='^dash_')) # NEW MAIN HANDLER
    application.add_handler(CallbackQueryHandler(button_callback_legacy, pattern='^poll_')) # Voting handler

    # --- Message Handlers ---
    application.add_handler(MessageHandler(filters.TEXT & (~filters.COMMAND), text_handler))
    application.add_handler(MessageHandler(filters.TEXT & filters.ChatType.GROUPS, track_group_user), group=1)

    application.run_polling(allowed_updates=Update.ALL_TYPES)

# --- NEW HELPER FUNCTIONS FOR DASHBOARD ---

async def private_chat_entry_point(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Displays the main menu in a private chat, showing a list of manageable groups."""
    user_id = update.effective_user.id
    admin_chats = await get_admin_chats(update, context)

    if not admin_chats:
        message_text = (
            'Я не знаю ни одной группы, где вы администратор. '
            'Пожалуйста, для начала, выполните любую команду в группе, '
            'где вы являетесь администратором, чтобы я ее узнал.'
        )
        # Use query if available to prevent sending a new message
        if update.callback_query:
            await update.callback_query.message.edit_text(message_text)
        else:
            await context.bot.send_message(chat_id=user_id, text=message_text)
        return

    keyboard = [
        [InlineKeyboardButton(chat.title, callback_data=f"dash_group_{chat.id}")]
        for chat in admin_chats
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    message_text = "Добро пожаловать! Выберите группу для управления:"
    
    query = update.callback_query
    if query:
        try:
            await query.edit_message_text(message_text, reply_markup=reply_markup)
        except Exception as e:
            logger.warning(f"Could not edit message in private_chat_entry_point, sending new one. Error: {e}")
            await context.bot.send_message(chat_id=user_id, text=message_text, reply_markup=reply_markup)

    else:
        await context.bot.send_message(chat_id=user_id, text=message_text, reply_markup=reply_markup)


async def show_group_dashboard(update: Update, context: ContextTypes.DEFAULT_TYPE, chat_id: int):
    """Displays the main dashboard for a selected group."""
    query = update.callback_query
    c.execute('SELECT title FROM known_chats WHERE chat_id = ?', (chat_id,))
    title_res = c.fetchone()
    title = title_res[0] if title_res else f"ID: {chat_id}"

    c.execute('SELECT COUNT(*) FROM polls WHERE chat_id = ? AND status = ?', (chat_id, 'active'))
    active_polls_count = c.fetchone()[0]
    c.execute('SELECT COUNT(*) FROM polls WHERE chat_id = ? AND status = ?', (chat_id, 'draft'))
    draft_polls_count = c.fetchone()[0]

    text = f'Панель управления для группы *"{title}"*\nВыберите действие:'
    keyboard = [
        [InlineKeyboardButton("➕ Создать опрос", callback_data=f"dash_newpoll_{chat_id}")],
        [InlineKeyboardButton(f"⚡️ Активные опросы ({active_polls_count})", callback_data=f"dash_polls_{chat_id}_active")],
        [InlineKeyboardButton(f"📝 Черновики ({draft_polls_count})", callback_data=f"dash_polls_{chat_id}_draft")],
        [InlineKeyboardButton("👥 Участники", callback_data=f"dash_participants_{chat_id}")],
        [InlineKeyboardButton("↩️ Назад к выбору группы", callback_data="dash_back_to_groups")]
    ]
    
    if query:
        await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode=ParseMode.MARKDOWN)
    else:
        await context.bot.send_message(chat_id=update.effective_chat.id, text=text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode=ParseMode.MARKDOWN)


async def show_poll_list(update: Update, context: ContextTypes.DEFAULT_TYPE, chat_id: int, status: str):
    """Shows a list of polls with a given status (active or draft)."""
    query = update.callback_query
    c.execute('SELECT poll_id, message FROM polls WHERE chat_id = ? AND status = ? ORDER BY poll_id DESC', (chat_id, status))
    polls = c.fetchall()

    status_text = "Активные опросы" if status == 'active' else "Черновики"
    
    if not polls:
        text = f"Нет {status_text.lower()} в этой группе."
        keyboard = [[InlineKeyboardButton("↩️ Назад к панели управления", callback_data=f"dash_group_{chat_id}")]]
        await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard))
        return

    text = f'*{status_text}*:\n\n'
    keyboard = []
    for poll_id, message in polls:
        short_msg = (message[:30] + '...') if message and len(message) > 30 else (message or f'Опрос {poll_id}')
        
        if status == 'active':
            keyboard.append([InlineKeyboardButton(short_msg, callback_data=f"results_{poll_id}")])
        elif status == 'draft':
            button_row = [
                InlineKeyboardButton(short_msg, callback_data=f"setresultoptionspoll_{poll_id}"),
                InlineKeyboardButton("▶️", callback_data=f"dash_startpoll_{poll_id}"),
                InlineKeyboardButton("🗑", callback_data=f"dash_deletepoll_{poll_id}")
            ]
            keyboard.append(button_row)
            
    keyboard.append([InlineKeyboardButton("↩️ Назад к панели управления", callback_data=f"dash_group_{chat_id}")])
    
    await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode=ParseMode.MARKDOWN)


async def show_participants_menu(update: Update, context: ContextTypes.DEFAULT_TYPE, chat_id: int):
    """Shows the participant management menu."""
    query = update.callback_query
    c.execute('SELECT title FROM known_chats WHERE chat_id = ?', (chat_id,))
    title_res = c.fetchone()
    title = title_res[0] if title_res else f"ID: {chat_id}"
    
    text = f'👥 **Управление участниками ("{title}")**'
    keyboard = [
        [InlineKeyboardButton("📄 Показать список", callback_data=f"dash_participants_list_{chat_id}")],
        [InlineKeyboardButton("🚫 Исключить/вернуть", callback_data=f"dash_participants_exclude_{chat_id}")],
        [InlineKeyboardButton("🧹 Очистить список", callback_data=f"dash_participants_clean_{chat_id}")],
        [InlineKeyboardButton("↩️ Назад к панели управления", callback_data=f"dash_group_{chat_id}")]
    ]
    await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode='HTML')


async def wizard_start(update: Update, context: ContextTypes.DEFAULT_TYPE, chat_id: int):
    """Starts the poll creation wizard."""
    query = update.callback_query
    user_id = query.from_user.id
    if user_id not in context.application.user_data:
        context.application.user_data[user_id] = {}
    
    app_user_data = context.application.user_data[user_id]
    app_user_data['wizard_state'] = 'waiting_for_title'
    app_user_data['wizard_chat_id'] = chat_id
    
    await query.message.edit_text(
        "✨ **Мастер создания опроса (Шаг 1/2)**\n\nПожалуйста, отправьте текст (заголовок) для вашего нового опроса.",
        parse_mode='HTML',
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("❌ Отмена", callback_data=f"dash_group_{chat_id}")]])
    )


async def dashboard_callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id
    
    data = query.data.split('_')
    command = data[1]
    
    if command == "group": # dash_group_{chat_id}
        chat_id = int(data[2])
        if user_id in context.application.user_data:
            app_user_data = context.application.user_data[user_id]
            app_user_data.pop('wizard_state', None)
            app_user_data.pop('wizard_chat_id', None)
            app_user_data.pop('wizard_title', None)
            
        context.user_data['selected_chat_id'] = chat_id
        await show_group_dashboard(update, context, chat_id)
        return
        
    if command == "back" and data[2] == "to" and data[3] == "groups": # dash_back_to_groups
        await private_chat_entry_point(update, context)
        return
        
    if command == "newpoll": # dash_newpoll_{chat_id}
        chat_id = int(data[2])
        await wizard_start(update, context, chat_id)
        return

    if command == "polls": # dash_polls_{chat_id}_{status}
        chat_id = int(data[2])
        status = data[3]
        await show_poll_list(update, context, chat_id, status)
        return

    if command == "startpoll": # dash_startpoll_{poll_id}
        poll_id = int(data[2])
        c.execute('SELECT chat_id FROM polls WHERE poll_id = ?', (poll_id,))
        res = c.fetchone()
        if res:
            await startpoll_from_dashboard(update, context, poll_id, res[0])
            await show_group_dashboard(update, context, res[0])
        else:
            await query.answer("Опрос не найден!", show_alert=True)
        return
        
    if command == "deletepoll": # dash_deletepoll_{poll_id}
        poll_id = int(data[2])
        c.execute('SELECT chat_id FROM polls WHERE poll_id = ?', (poll_id,))
        res = c.fetchone()
        if res:
            chat_id = res[0]
            c.execute('DELETE FROM polls WHERE poll_id = ?', (poll_id,))
            c.execute('DELETE FROM responses WHERE poll_id = ?', (poll_id,))
            c.execute('DELETE FROM poll_settings WHERE poll_id = ?', (poll_id,))
            c.execute('DELETE FROM poll_option_settings WHERE poll_id = ?', (poll_id,))
            conn.commit()
            await query.answer(f"Черновик опроса {poll_id} удален.", show_alert=True)
            await show_poll_list(update, context, chat_id, 'draft')
        return

    if command == "participants": # dash_participants_{chat_id}
        chat_id = int(data[2])
        await show_participants_menu(update, context, chat_id)
        return


# Переименовываем старый button_callback, т.к. он теперь обрабатывает только голоса
async def button_callback_legacy(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    add_user_to_participants(update)
    query = update.callback_query
    
    logger.info(f"[VOTE_CALLBACK] Received vote callback. Data: {query.data}")

    poll_id_str, option_index_str = query.data.split('_')[1:]
    poll_id = int(poll_id_str)
    option_index = int(option_index_str)
    user_id = query.from_user.id

    logger.info(f"[VOTE_CALLBACK] Parsed: poll_id={poll_id}, option_index={option_index}, user_id={user_id}")

    c.execute('SELECT options, status FROM polls WHERE poll_id = ?', (poll_id,))
    row = c.fetchone()
    if not row:
        logger.warning(f"[VOTE_CALLBACK] Poll not found: poll_id={poll_id}")
        await query.answer("Этот опрос больше не действителен.", show_alert=True)
        return

    options_str, status = row
    logger.info(f"[VOTE_CALLBACK] Poll status for poll_id={poll_id} is '{status}'")
    if status != 'active':
        await query.answer(f"Этот опрос неактивен (статус: {status}).", show_alert=True)
        return
        
    options = [opt.strip() for opt in options_str.split(',')]
    response_text = options[option_index]

    c.execute('SELECT response FROM responses WHERE poll_id = ? AND user_id = ?', (poll_id, user_id))
    existing_response = c.fetchone()
    logger.info(f"[VOTE_CALLBACK] User {user_id} existing response for poll {poll_id}: {existing_response}")

    answer_text = ""
    if existing_response:
        if existing_response[0] == response_text:
            # User clicked the same button again, retract vote
            logger.info(f"[VOTE_CALLBACK] Action: Retracting vote for user {user_id} in poll {poll_id}. Response: '{response_text}'")
            c.execute('DELETE FROM responses WHERE poll_id = ? AND user_id = ?', (poll_id, user_id))
            answer_text = f"Ваш голос за '{response_text}' отозван."
        else:
            # User changed their vote
            logger.info(f"[VOTE_CALLBACK] Action: Changing vote for user {user_id} in poll {poll_id}. New response: '{response_text}'")
            c.execute('UPDATE responses SET response = ? WHERE poll_id = ? AND user_id = ?', (response_text, poll_id, user_id))
            answer_text = f"Ваш ответ изменен на '{response_text}'."
    else:
        # New vote
        logger.info(f"[VOTE_CALLBACK] Action: New vote for user {user_id} in poll {poll_id}. Response: '{response_text}'")
        c.execute('INSERT INTO responses (poll_id, user_id, response) VALUES (?, ?, ?)', (poll_id, user_id, response_text))
        answer_text = f"Ваш ответ '{response_text}' принят!"

    # Commit all database changes at once
    logger.info(f"[VOTE_CALLBACK] Committing DB changes for poll {poll_id}.")
    conn.commit()

    # Verify the write operation
    c.execute('SELECT response FROM responses WHERE poll_id = ? AND user_id = ?', (poll_id, user_id))
    new_db_state = c.fetchone()
    logger.info(f"[VOTE_CALLBACK] DB state after commit for user {user_id} in poll {poll_id}: {new_db_state}")

    # First, answer the callback to unfreeze the button on the user's side immediately.
    logger.info(f"[VOTE_CALLBACK] Answering callback for user {user_id} with text: '{answer_text}'")
    await query.answer(answer_text)

    # Then, update the poll message in the group. This might take a moment.
    logger.info(f"[VOTE_CALLBACK] Calling update_poll_message for poll {poll_id}.")
    await update_poll_message(poll_id, context)


if __name__ == '__main__':
    main()