# -*- coding: utf-8 -*-
# Gemini was here
import logging
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, CallbackQuery, ReplyKeyboardRemove, ForceReply
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, ContextTypes, MessageHandler, filters
from typing import Union
import sqlite3
import os
from dotenv import load_dotenv
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
    user_id = update.effective_user.id
    chat_id = update.effective_chat.id
    is_admin = False
    if chat_id < 0:  # Group chat
        is_admin = user_id in [admin.user.id for admin in await context.bot.get_chat_administrators(chat_id)]
        if is_admin:
            context.user_data['selected_chat_id'] = chat_id
            await update_known_chats(chat_id, update.effective_chat.title)
    else:  # Private chat
        admin_chats = await get_admin_chats(update, context)
        is_admin = len(admin_chats) > 0
    reply_markup = InlineKeyboardMarkup(get_admin_keyboard(is_admin))
    await context.bot.send_message(chat_id=user_id, text='Привет! Я бот для сбора денег в группе. Используйте кнопки ниже для управления.' if is_admin else 'Привет! Я бот для сбора денег в группе. Используйте /help для списка команд.', reply_markup=reply_markup)

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    add_user_to_participants(update)
    user_id = update.effective_user.id
    chat_id = update.effective_chat.id
    is_admin = False
    if chat_id < 0:  # Group chat
        is_admin = user_id in [admin.user.id for admin in await context.bot.get_chat_administrators(chat_id)]
        if is_admin:
            context.user_data['selected_chat_id'] = chat_id
            await update_known_chats(chat_id, update.effective_chat.title)
    else:  # Private chat
        admin_chats = await get_admin_chats(update, context)
        is_admin = len(admin_chats) > 0
    reply_markup = InlineKeyboardMarkup(get_admin_keyboard(is_admin))
    await context.bot.send_message(chat_id=user_id, text='Доступные команды:\n/start - Начать работу с ботом\n/help - Показать помощь\n/collect - Собрать список участников группы\n/exclude - Исключить участника из опроса\n/setmessage - Установить сообщение для опроса\n/setoptions - Установить варианты ответа для опроса\n/startpoll - Запустить опрос\n/results - Показать результаты опроса\n/newpoll - Создать новый опрос\n/mychats - Показать список известных групп\n/cleangroup - Очистить список участников группы\n/setresultoptions - Настроить вывод результатов опроса', reply_markup=reply_markup)

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
    chat_id = update.effective_chat.id
    user_id = update.effective_user.id
    if chat_id < 0:  # Group chat
        if user_id not in [admin.user.id for admin in await context.bot.get_chat_administrators(chat_id)]:
            await context.bot.send_message(chat_id=user_id, text='Только администраторы могут использовать эту команду.')
            return
        context.user_data['selected_chat_id'] = chat_id
    else:  # Private chat
        if 'selected_chat_id' not in context.user_data:
            await select_chat(update, context, 'exclude')
            return
        chat_id = context.user_data['selected_chat_id']
        if user_id not in [admin.user.id for admin in await context.bot.get_chat_administrators(chat_id)]:
            await context.bot.send_message(chat_id=user_id, text='Только администраторы могут использовать эту команду.')
            return
    
    c.execute('SELECT user_id, username, first_name, last_name, excluded FROM participants WHERE chat_id = ?', (chat_id,))
    participants = c.fetchall()
    # Убираем дубли по user_id
    unique_participants = {}
    for user_id_part, username, first_name, last_name, excluded in participants:
        if user_id_part not in unique_participants:
            unique_participants[user_id_part] = (username, first_name, last_name, excluded)
    if not participants:
        await context.bot.send_message(chat_id=user_id, text='Список участников пуст. Используйте /collect для сбора участников.')
        return
    text = '<b>Список участников группы:</b>\n'
    for user_id_part, (username, first_name, last_name, excluded) in unique_participants.items():
        name = first_name + (f' {last_name}' if last_name else '')
        display_name = f'{name} (@{username})' if username else name
        status = ' (исключен)' if excluded else ''
        text += f'- {display_name}{status}\n'
    await context.bot.send_message(chat_id=user_id, text=text, parse_mode='HTML')

async def exclude_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    add_user_to_participants(update)
    query = update.callback_query
    await query.answer()
    
    user_id_part, chat_id = map(int, query.data.split('_')[1:])
    c.execute('UPDATE participants SET excluded = NOT excluded WHERE chat_id = ? AND user_id = ?', (chat_id, user_id_part))
    conn.commit()
    
    c.execute('SELECT first_name, last_name, excluded FROM participants WHERE chat_id = ? AND user_id = ?', (chat_id, user_id_part))
    first_name, last_name, excluded = c.fetchone()
    name = first_name + (f' {last_name}' if last_name else '')
    status = 'исключен' if excluded else 'включен обратно'
    await context.bot.send_message(chat_id=query.from_user.id, text=f'{name} {status} из опроса.')
    
    c.execute('SELECT user_id, username, first_name, last_name, excluded FROM participants WHERE chat_id = ?', (chat_id,))
    participants = c.fetchall()
    keyboard = []
    for u_id, username, first_name, last_name, excluded in participants:
        name = first_name + (f' {last_name}' if last_name else '')
        display_name = f'{name} (@{username})' if username else name
        status = ' (исключен)' if excluded else ''
        keyboard.append([InlineKeyboardButton(f'{display_name}{status}', callback_data=f'exclude_{u_id}_{chat_id}')])
    reply_markup = InlineKeyboardMarkup(keyboard)
    await query.message.edit_reply_markup(reply_markup=reply_markup)

async def newpoll(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    add_user_to_participants(update)
    user_id = update.effective_user.id
    # ВСЕГДА предлагаем выбрать группу, даже если она одна
    c.execute('SELECT DISTINCT chat_id, title FROM known_chats')
    known_chats = c.fetchall()
    admin_chats = []
    for chat_id, title in known_chats:
        try:
            admins = await context.bot.get_chat_administrators(chat_id)
            if user_id in [admin.user.id for admin in admins]:
                admin_chats.append(type('Chat', (), {'id': chat_id, 'title': title, 'type': 'group'}))
        except ChatMigrated as e:
            new_chat_id = e.new_chat_id
            # Обновить chat_id во всех таблицах
            c.execute('UPDATE polls SET chat_id = ? WHERE chat_id = ?', (new_chat_id, chat_id))
            c.execute('UPDATE participants SET chat_id = ? WHERE chat_id = ?', (new_chat_id, chat_id))
            # --- fix known_chats UNIQUE constraint ---
            c.execute('SELECT title FROM known_chats WHERE chat_id = ?', (chat_id,))
            row = c.fetchone()
            title_val = row[0] if row else None
            c.execute('DELETE FROM known_chats WHERE chat_id = ?', (chat_id,))
            if title_val is not None:
                c.execute('INSERT OR IGNORE INTO known_chats (chat_id, title) VALUES (?, ?)', (new_chat_id, title_val))
            conn.commit()
            try:
                admins = await context.bot.get_chat_administrators(new_chat_id)
                if user_id in [admin.user.id for admin in admins]:
                    admin_chats.append(type('Chat', (), {'id': new_chat_id, 'title': title, 'type': 'group'}))
            except Exception as e2:
                logger.error(f'Error checking admin status in migrated chat {new_chat_id}: {e2}')
        except Exception as e:
            logger.error(f'Error checking admin status in known chat {chat_id}: {e}')
    if len(admin_chats) == 0:
        await context.bot.send_message(chat_id=user_id, text='Я не знаю ни одной группы, где вы администратор. Пожалуйста, выполните любую команду в группе, чтобы я её узнал.')
        return
    keyboard = [[InlineKeyboardButton(chat.title, callback_data=f'selectchat_{chat.id}_newpoll')] for chat in admin_chats]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await context.bot.send_message(chat_id=user_id, text='Выберите группу для создания опроса:', reply_markup=reply_markup)
    return

async def mychats(update: Update, context: ContextTypes.DEFAULT_TYPE, force_user_id=None):
    c.execute('SELECT chat_id, title FROM known_chats')
    chats = c.fetchall()
    user_id = force_user_id if force_user_id else (update.effective_user.id if update.effective_user else None)
    if not chats:
        text = 'Бот пока не знает ни одной группы. Добавьте его в группу и напишите в ней что-нибудь.'
        if force_user_id:
            await context.bot.send_message(chat_id=force_user_id, text=text)
        else:
            if update.message:
                await update.message.reply_text(text)
            elif update.callback_query:
                await update.callback_query.message.reply_text(text)
        return
    # Проверим, где пользователь админ
    admin_chats = []
    for chat_id, title in chats:
        try:
            admins = await context.bot.get_chat_administrators(chat_id)
            if user_id in [admin.user.id for admin in admins]:
                admin_chats.append((chat_id, title))
        except ChatMigrated as e:
            new_chat_id = e.new_chat_id
            c.execute('UPDATE polls SET chat_id = ? WHERE chat_id = ?', (new_chat_id, chat_id))
            c.execute('UPDATE participants SET chat_id = ? WHERE chat_id = ?', (new_chat_id, chat_id))
            # --- fix known_chats UNIQUE constraint ---
            c.execute('SELECT title FROM known_chats WHERE chat_id = ?', (chat_id,))
            row = c.fetchone()
            title_val = row[0] if row else None
            c.execute('DELETE FROM known_chats WHERE chat_id = ?', (chat_id,))
            if title_val is not None:
                c.execute('INSERT OR IGNORE INTO known_chats (chat_id, title) VALUES (?, ?)', (new_chat_id, title_val))
            conn.commit()
            try:
                admins = await context.bot.get_chat_administrators(new_chat_id)
                if user_id in [admin.user.id for admin in admins]:
                    admin_chats.append((new_chat_id, title))
            except Exception as e2:
                logger.error(f'Error checking admin status in migrated chat {new_chat_id}: {e2}')
        except Exception as e:
            logger.error(f'Error checking admin status in chat {chat_id}: {e}')
    if not admin_chats:
        text = 'Вы не являетесь администратором ни в одной из известных боту групп. Если вы уверены, что это не так, попробуйте написать что-нибудь в нужной группе, чтобы бот ее увидел.'
        if force_user_id:
            await context.bot.send_message(chat_id=force_user_id, text=text)
        else:
            if update.message:
                await update.message.reply_text(text)
            elif update.callback_query:
                await update.callback_query.message.reply_text(text)
        return
    # ВСЕГДА показываем меню выбора группы
    keyboard = [[InlineKeyboardButton(title, callback_data=f'selectchat_{chat_id}_mychats')] for chat_id, title in admin_chats]
    reply_markup = InlineKeyboardMarkup(keyboard)
    text = 'Группы, где вы администратор и бот был активен:'
    if force_user_id:
        await context.bot.send_message(chat_id=force_user_id, text=text, reply_markup=reply_markup)
    else:
        if update.message:
            await update.message.reply_text(text, reply_markup=reply_markup)
        elif update.callback_query:
            await update.callback_query.message.reply_text(text, reply_markup=reply_markup)
    return

async def setmessage(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    add_user_to_participants(update)
    user_id = update.effective_user.id
    if update.effective_chat.type in ['group', 'supergroup']:
        chat_id = update.effective_chat.id
    else:
        if 'selected_chat_id' not in context.user_data:
            await update.message.reply_text('Сначала выберите группу через /newpoll.')
            return
        chat_id = context.user_data['selected_chat_id']
    if user_id not in [admin.user.id for admin in await context.bot.get_chat_administrators(chat_id)]:
        await context.bot.send_message(chat_id=user_id, text='Только администраторы могут использовать эту команду.')
        return
    if not context.args:
        context.user_data['waiting_for_poll_message'] = True
        await context.bot.send_message(chat_id=user_id, text='Пожалуйста, отправьте текст опроса одним сообщением.')
        return
    c.execute('SELECT poll_id FROM polls WHERE chat_id = ? AND status = ? ORDER BY poll_id DESC LIMIT 1', (chat_id, 'draft'))
    row = c.fetchone()
    if not row:
        await context.bot.send_message(chat_id=user_id, text='Нет черновика опроса. Создайте новый опрос с помощью /newpoll.')
        return
    poll_id = row[0]
    message = ' '.join(context.args)
    logger.info(f'[SETMESSAGE] Устанавливаю текст для poll_id={poll_id}, chat_id={chat_id}: "{message}"')
    c.execute('UPDATE polls SET message = ? WHERE poll_id = ?', (message, poll_id))
    conn.commit()
    await context.bot.send_message(chat_id=user_id, text=f'Сообщение для опроса {poll_id} установлено: {message}')

async def setoptions(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    add_user_to_participants(update)
    user_id = update.effective_user.id
    if update.effective_chat.type in ['group', 'supergroup']:
        chat_id = update.effective_chat.id
    else:
        if 'selected_chat_id' not in context.user_data:
            await update.message.reply_text('Сначала выберите группу через /newpoll.')
            return
        chat_id = context.user_data['selected_chat_id']
    if user_id not in [admin.user.id for admin in await context.bot.get_chat_administrators(chat_id)]:
        await context.bot.send_message(chat_id=user_id, text='Только администраторы могут использовать эту команду.')
        return
    if not context.args:
        context.user_data['waiting_for_poll_options'] = True
        await context.bot.send_message(chat_id=user_id, text='Пожалуйста, отправьте варианты ответа через запятую одним сообщением.')
        return
    options = ' '.join(context.args).split(',')
    if len(options) < 2:
        await context.bot.send_message(chat_id=user_id, text='Укажите как минимум 2 варианта ответа.')
        return
    c.execute('SELECT poll_id FROM polls WHERE chat_id = ? AND status = ? ORDER BY poll_id DESC LIMIT 1', (chat_id, 'draft'))
    row = c.fetchone()
    if not row:
        await context.bot.send_message(chat_id=user_id, text='Нет черновика опроса. Создайте новый опрос с помощью /newpoll.')
        return
    poll_id = row[0]
    options_str = ','.join(options)
    logger.info(f'[SETOPTIONS] Устанавливаю варианты для poll_id={poll_id}, chat_id={chat_id}: "{options_str}"')
    c.execute('UPDATE polls SET options = ? WHERE poll_id = ?', (options_str, poll_id))
    conn.commit()
    await context.bot.send_message(chat_id=user_id, text=f'Варианты ответов для опроса {poll_id} установлены: {options_str}')

async def startpoll(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    add_user_to_participants(update)
    user_id = update.effective_user.id
    chat_id = None

    # Определяем chat_id
    if update.effective_chat.type in ['group', 'supergroup']:
        chat_id = update.effective_chat.id
        context.user_data['selected_chat_id'] = chat_id
    elif 'selected_chat_id' in context.user_data:
        chat_id = context.user_data['selected_chat_id']
    else:
        # Если мы в личке и группа не выбрана
        await select_chat(update, context, 'startpoll')
        return

    # Проверка на админа
    try:
        if user_id not in [admin.user.id for admin in await context.bot.get_chat_administrators(chat_id)]:
            await context.bot.send_message(chat_id=user_id, text='Только администраторы могут использовать эту команду.')
            return
    except Exception as e:
        logger.error(f'Failed to check admin status for user {user_id} in chat {chat_id}: {e}')
        await context.bot.send_message(chat_id=user_id, text='Не удалось проверить ваши права в группе. Убедитесь, что бот еще находится в группе и имеет права администратора.')
        return

    logger.info(f'[STARTPOLL] Пытаюсь запустить опрос: chat_id={chat_id}')
    c.execute('SELECT poll_id, message, options FROM polls WHERE chat_id = ? AND status = ? ORDER BY poll_id DESC LIMIT 1', (chat_id, 'draft'))
    result = c.fetchone()
    # Логируем все опросы для чата
    c.execute('SELECT poll_id, message, options, status FROM polls WHERE chat_id = ?', (chat_id,))
    all_polls = c.fetchall()
    logger.info(f'[STARTPOLL] Все опросы для chat_id={chat_id}: {all_polls}')
    if not result:
        await context.bot.send_message(chat_id=user_id, text='Сначала создайте опрос с помощью /newpoll и установите сообщение с помощью /setmessage.')
        return
    poll_id, message, options_str = result
    logger.info(f'[STARTPOLL] Найден опрос: poll_id={poll_id}, message="{message}", options="{options_str}"')
    if not message or not message.strip():
        await context.bot.send_message(chat_id=user_id, text='Сначала задайте текст опроса с помощью /setmessage или кнопки.')
        return
    if not options_str or not any(opt.strip() for opt in options_str.split(',')):
        await context.bot.send_message(chat_id=user_id, text='Сначала задайте варианты ответа с помощью /setoptions или кнопки.')
        return
    options = options_str.split(',')
    c.execute('UPDATE polls SET status = ? WHERE poll_id = ?', ('active', poll_id))
    conn.commit()
    keyboard = [[InlineKeyboardButton(option.strip(), callback_data=f'poll_{poll_id}_{i}')] for i, option in enumerate(options)]
    reply_markup = InlineKeyboardMarkup(keyboard)
    poll_message = await context.bot.send_message(chat_id=chat_id, text=message, reply_markup=reply_markup)
    c.execute('UPDATE polls SET message_id = ? WHERE poll_id = ?', (poll_message.message_id, poll_id))
    conn.commit()
    await context.bot.send_message(chat_id=user_id, text=f'Опрос {poll_id} запущен.')

# --- Вспомогательная функция для генерации прогресс-бара ---
def get_progress_bar_text(poll_id: int, options: list, option_voters: dict) -> str:
    progress_bar_text = ''
    try:
        c.execute('SELECT target_sum FROM poll_settings WHERE poll_id = ?', (poll_id,))
        target_sum_res = c.fetchone()
        target_sum = target_sum_res[0] if target_sum_res and target_sum_res[0] is not None else 0
        if target_sum > 0:
            total_contribution = 0
            c.execute('SELECT option_index, contribution_amount FROM poll_option_settings WHERE poll_id = ? AND contribution_amount > 0', (poll_id,))
            contributions = c.fetchall()
            contribution_map = {index: amount for index, amount in contributions}
            for idx, opt_text in enumerate(options):
                if idx in contribution_map:
                    contribution_amount = contribution_map[idx]
                    num_voters_for_option = len(option_voters.get(opt_text.strip(), set()))
                    total_contribution += num_voters_for_option * contribution_amount
            
            percentage = (total_contribution / target_sum) * 100 if target_sum > 0 else 0
            filled_blocks = int(min(percentage, 100) / 10)
            empty_blocks = 10 - filled_blocks
            progress_bar = '█' * filled_blocks + '░' * empty_blocks
            
            formatted_total = f'{total_contribution:,.0f}'.replace(',', ' ')
            formatted_target = f'{target_sum:,.0f}'.replace(',', ' ')
            
            progress_bar_text = f'\n\n<b>Сбор средств</b>\n{progress_bar} {formatted_total} / {formatted_target} ({percentage:.1f}%)'
    except Exception as e:
        logger.error(f"Error generating progress bar for poll {poll_id}: {e}")
        return ''
    return progress_bar_text

def _generate_results_text_and_options(poll_id: int, include_non_voters: bool, detailed_names: bool) -> (str, list):
    """
    Generates the complete, formatted text for poll results and the list of options.
    Handles orphaned responses to prevent KeyErrors.
    
    :param poll_id: The ID of the poll.
    :param include_non_voters: If True, a list of non-voters will be appended.
    :param detailed_names: If True, includes usernames in the voter lists.
    :return: A tuple of (formatted_result_text, options_list).
    """
    
    # 1. Fetch basic poll info
    c.execute("SELECT chat_id, message, options FROM polls WHERE poll_id = ?", (poll_id,))
    res = c.fetchone()
    if not res:
        return None, None
    chat_id, poll_message, options_str = res
    options = [opt.strip() for opt in options_str.split(',')]

    # 2. Fetch all non-excluded participants and their responses for this poll
    c.execute('SELECT p.user_id, p.username, p.first_name, p.last_name, r.response FROM participants p LEFT JOIN responses r ON p.user_id = r.user_id AND r.poll_id = ? WHERE p.chat_id = ? AND p.excluded = 0', (poll_id, chat_id))
    all_participants_with_responses = c.fetchall()
    
    # 3. Process responses and non-voters
    option_voters = {opt: set() for opt in options}
    all_voted_user_ids = set()
    not_voted_dict = {}

    for user_id_part, username, first_name, last_name, response in all_participants_with_responses:
        name = first_name + (f' {last_name}' if last_name else '')
        if response:
            # FIX: Safely handle responses that may not match current options
            if response in option_voters:
                option_voters[response].add((user_id_part, name, username))
                all_voted_user_ids.add(user_id_part)
            else:
                logger.warning(f"Orphaned response '{response}' found for poll {poll_id} from user {user_id_part}. Ignoring.")
        elif user_id_part not in not_voted_dict:
            not_voted_dict[user_id_part] = (name, username)

    # 4. Generate the result text
    # --- Get display settings ---
    c.execute('SELECT default_show_names, default_names_style, default_show_count FROM poll_settings WHERE poll_id = ?', (poll_id,))
    default_settings = c.fetchone() or (1, 'list', 1)
    
    # --- Fetch all option settings for sorting ---
    option_settings_map = {}
    for i, opt in enumerate(options):
        c.execute('SELECT is_priority FROM poll_option_settings WHERE poll_id = ? AND option_index = ?', (poll_id, i))
        opt_settings = c.fetchone()
        is_priority = opt_settings[0] if opt_settings and opt_settings[0] is not None else 0
        option_settings_map[opt] = {'is_priority': is_priority}
        
    # --- Generate progress bar ---
    progress_bar_text = get_progress_bar_text(poll_id, options, option_voters)

    # --- Generate main result text ---
    voted_count = len(all_voted_user_ids)
    header = f'<b>📊 {poll_message}</b>\n\n<b>Результаты</b> <i>(👥 {voted_count})</i>:'
    result_text = header
    if progress_bar_text:
        result_text += progress_bar_text

    # --- Sort options and add voter lists ---
    # ИЗМЕНЕНО: Сортировка по приоритету, затем по количеству голосов
    sorted_options = sorted(
        options, 
        key=lambda o: (
            option_settings_map.get(o, {}).get('is_priority', 0), 
            len(option_voters.get(o, set()))
        ), 
        reverse=True
    )
    
    for opt in sorted_options:
        original_index = options.index(opt)
        c.execute('SELECT show_names, names_style, show_count, emoji, is_priority FROM poll_option_settings WHERE poll_id = ? AND option_index = ?', (poll_id, original_index))
        opt_settings = c.fetchone()
        show_names = default_settings[0] if opt_settings is None or opt_settings[0] is None else opt_settings[0]
        names_style = default_settings[1] if opt_settings is None or opt_settings[1] is None else opt_settings[1]
        show_count = default_settings[2] if opt_settings is None or opt_settings[2] is None else opt_settings[2]
        emoji = opt_settings[3] if opt_settings and opt_settings[3] else ''
        is_priority = opt_settings[4] if opt_settings and opt_settings[4] else 0
        
        voters = option_voters.get(opt, set())
        # Header for the option
        if show_count:
            result_text += f'\n\n<b>{"⭐" if is_priority else "☆"} {opt}</b>: <b>{len(voters)}</b>'
        else:
            result_text += f'\n\n<b>{"⭐" if is_priority else "☆"} {opt}</b>:'
            
        # List of voters
        if show_names and voters:
            sorted_voters = sorted(list(voters), key=lambda x: x[1])

            if detailed_names:
                voter_names = [f'{emoji} {n}{f" (@{u})" if u else ""}' if emoji else f'{n}{f" (@{u})" if u else ""}' for _, n, u in sorted_voters]
            else:
                voter_names = [f'{emoji} {n}' if emoji else f'{n}' for _, n, u in sorted_voters]

            if names_style == 'inline':
                result_text += f' — {", ".join(voter_names)}'
            elif names_style == 'small':
                for name_str in voter_names:
                    result_text += f'\n    <i>{name_str}</i>'
            else:  # list
                for name_str in voter_names:
                    result_text += f'\n    {name_str}'

    # --- Add list of non-voters ---
    if include_non_voters and not_voted_dict:
        result_text += '\n\n<b>Не проголосовали:</b>'
        sorted_not_voted = sorted(list(not_voted_dict.values()), key=lambda x: x[0])
        if detailed_names:
            names_list = [f'{n}{f" (@{u})" if u else ""}' for n, u in sorted_not_voted]
        else:
            names_list = [f'{n}' for n, u in sorted_not_voted]
        result_text += '\n' + '\n'.join(names_list)
        
    return result_text, options

async def show_results(update: Update, context: ContextTypes.DEFAULT_TYPE, poll_id: int, user_id: int = None) -> None:
    add_user_to_participants(update)
    
    if user_id is None:
        user_id = update.effective_user.id
        
    result_text, _ = _generate_results_text_and_options(poll_id, include_non_voters=True, detailed_names=True)

    if not result_text:
        if user_id:
            await context.bot.send_message(chat_id=user_id, text=f"Опрос с ID {poll_id} не найден.")
        elif update.effective_message:
            await update.effective_message.reply_text(f"Опрос с ID {poll_id} не найден.")
        return
            
    # Кнопка обновления результатов в группе
    keyboard = [[InlineKeyboardButton('🔄 Обновить результаты в группе', callback_data=f'refreshresults_{poll_id}')]]
    await context.bot.send_message(chat_id=user_id, text=result_text, parse_mode='HTML', reply_markup=InlineKeyboardMarkup(keyboard))

async def results_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    add_user_to_participants(update)
    query = update.callback_query
    await query.answer()
    poll_id = int(query.data.split('_')[1])
    # Получаем chat_id и старый message_id
    c.execute('SELECT chat_id, message_id FROM polls WHERE poll_id = ?', (poll_id,))
    row = c.fetchone()
    if not row:
        await query.edit_message_text('Опрос не найден.')
        return
    chat_id, old_message_id = row

    result_text, options = _generate_results_text_and_options(poll_id, include_non_voters=False, detailed_names=False)

    if not result_text:
        await query.edit_message_text(f'Не удалось сформировать результаты для опроса {poll_id}.')
        return

    # Удаляем старое сообщение с результатами
    if old_message_id:
        try:
            await context.bot.delete_message(chat_id=chat_id, message_id=old_message_id)
        except Exception as e:
            logger.warning(f"Could not delete old poll message {old_message_id} in chat {chat_id}: {e}")
            pass  # Может быть уже удалено или нет прав

    # Отправляем новое сообщение в группу (тихо) с кнопками голосования
    poll_keyboard = InlineKeyboardMarkup([[InlineKeyboardButton(opt, callback_data=f'poll_{poll_id}_{i}')] for i, opt in enumerate(options)])
    try:
        new_msg = await context.bot.send_message(chat_id=chat_id, text=result_text, parse_mode='HTML', disable_notification=True, reply_markup=poll_keyboard)
        # Сохраняем новый message_id
        c.execute('UPDATE polls SET message_id = ? WHERE poll_id = ?', (new_msg.message_id, poll_id))
        conn.commit()
        await query.edit_message_text('Результаты обновлены в группе!')
    except Exception as e:
        logger.error(f"Could not send new poll message in chat {chat_id}: {e}")
        await query.edit_message_text('Ошибка при обновлении результатов в группе.')

# --- Обработчик кнопки обновления результатов в группе ---
async def refresh_results_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    poll_id = int(query.data.split('_')[1])
    # Получаем chat_id и старый message_id
    c.execute('SELECT chat_id, message_id, options, message FROM polls WHERE poll_id = ?', (poll_id,))
    row = c.fetchone()
    if not row:
        await query.edit_message_text('Опрос не найден.')
        return
    chat_id, old_message_id, options_str, poll_message = row
    
    # Формируем новое сообщение с результатами
    c.execute('SELECT p.user_id, p.username, p.first_name, p.last_name, r.response FROM participants p LEFT JOIN responses r ON p.user_id = r.user_id AND r.poll_id = ? WHERE p.chat_id = ? AND p.excluded = 0', (poll_id, chat_id))
    responses = c.fetchall()
    options = [opt.strip() for opt in options_str.split(',')]
    option_voters = {opt: set() for opt in options}
    all_voted_user_ids = set()
    for user_id_part, username, first_name, last_name, response in responses:
        if response:
            name = first_name + (f' {last_name}' if last_name else '')
            option_voters[response].add((user_id_part, name, username))
            all_voted_user_ids.add(user_id_part)
    sorted_options = sorted(options, key=lambda o: len(option_voters[o]), reverse=True)
    # --- Получаем настройки ---
    c.execute('SELECT default_show_names, default_names_style, default_show_count FROM poll_settings WHERE poll_id = ?', (poll_id,))
    default_settings = c.fetchone() or (1, 'list', 1)
    logger.info(f'[RESULTS] Формирование результатов для poll_id={poll_id}. Настройки по умолчанию: {default_settings}')

    # --- Генерация прогресс-бара ---
    progress_bar_text = get_progress_bar_text(poll_id, options, option_voters)

    result_text = f'<b>📊 {poll_message}</b>\n\n<b>Результаты</b> <i>(👥 {len(all_voted_user_ids)})</i>:'
    if progress_bar_text:
        result_text += progress_bar_text

    for idx, opt in enumerate(sorted_options):
        c.execute('SELECT show_names, names_style, show_count, emoji, is_priority FROM poll_option_settings WHERE poll_id = ? AND option_index = ?', (poll_id, options.index(opt)))
        opt_settings = c.fetchone()
        logger.info(f'[RESULTS] Вариант {idx} ({opt}): индивидуальные настройки: {opt_settings}')
        show_names = default_settings[0] if opt_settings is None or opt_settings[0] is None else opt_settings[0]
        names_style = default_settings[1] if opt_settings is None or opt_settings[1] is None else opt_settings[1]
        show_count = default_settings[2] if opt_settings is None or opt_settings[2] is None else opt_settings[2]
        emoji = opt_settings[3] if opt_settings and opt_settings[3] else ''
        is_priority = opt_settings[4] if opt_settings and opt_settings[4] else 0
        logger.info(f'[RESULTS] Вариант {idx} ({opt}): применяемые настройки: show_names={show_names}, names_style={names_style}, show_count={show_count}, emoji={emoji}, is_priority={is_priority}')
        voters = option_voters[opt]
        if show_count:
            result_text += f'\n<b>{"⭐" if is_priority else "☆"} {opt}</b>: <b>{len(voters)}</b>'
        else:
            result_text += f'\n<b>{"⭐" if is_priority else "☆"} {opt}</b>:'
        if show_names and voters:
            sorted_voters = sorted(list(voters), key=lambda x: x[1])
            if names_style == 'inline':
                names = ', '.join(f'{emoji} {n}{f" (@{u})" if u else ""}' if emoji else f'{n}{f" (@{u})" if u else ""}' for _, n, u in sorted_voters)
                result_text += f' — {names}'
            elif names_style == 'small':
                for _, n, u in sorted_voters:
                    result_text += f'\n    <i>{f"{emoji} {n}" if emoji else f"{n}"}{f" (@{u})" if u else ""}</i>'
            else:  # list
                for _, n, u in sorted_voters:
                    result_text += f'\n    {f"{emoji} {n}" if emoji else f"{n}"}{f" (@{u})" if u else ""}'
    
    # Удаляем старое сообщение с результатами
    if old_message_id:
        try:
            await context.bot.delete_message(chat_id=chat_id, message_id=old_message_id)
        except Exception as e:
            logger.warning(f"Could not delete old poll message {old_message_id} in chat {chat_id}: {e}")
            pass  # Может быть уже удалено или нет прав

    # Отправляем новое сообщение в группу (тихо) с кнопками голосования
    poll_keyboard = InlineKeyboardMarkup([[InlineKeyboardButton(opt, callback_data=f'poll_{poll_id}_{i}')] for i, opt in enumerate(options)])
    try:
        new_msg = await context.bot.send_message(chat_id=chat_id, text=result_text, parse_mode='HTML', disable_notification=True, reply_markup=poll_keyboard)
        # Сохраняем новый message_id
        c.execute('UPDATE polls SET message_id = ? WHERE poll_id = ?', (new_msg.message_id, poll_id))
        conn.commit()
        await query.edit_message_text('Результаты обновлены в группе!')
    except Exception as e:
        logger.error(f"Could not send new poll message in chat {chat_id}: {e}")
        await query.edit_message_text('Ошибка при обновлении результатов в группе.')


# --- ДОБАВЛЕНО: обновить меню с кнопкой "Список групп" ---
def get_admin_keyboard(is_admin):
    if is_admin:
        return [
            [InlineKeyboardButton('Помощь', callback_data='help')],
            [InlineKeyboardButton('Собрать участников', callback_data='collect')],
            [InlineKeyboardButton('Исключить участника', callback_data='exclude')],
            [InlineKeyboardButton('Создать опрос', callback_data='newpoll')],
            [InlineKeyboardButton('Установить текст опроса', callback_data='setmessage')],
            [InlineKeyboardButton('Установить варианты ответа', callback_data='setoptions')],
            [InlineKeyboardButton('Запустить опрос', callback_data='startpoll')],
            [InlineKeyboardButton('Результаты', callback_data='results')],
            [InlineKeyboardButton('Настроить вывод результатов', callback_data='setresultoptions')],
            [InlineKeyboardButton('Список участников', callback_data='participants')],
            [InlineKeyboardButton('Список групп', callback_data='mychats')]
        ]
    else:
        return [[InlineKeyboardButton('Помощь', callback_data='help')], [InlineKeyboardButton('Список групп', callback_data='mychats')]]

async def button_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    add_user_to_participants(update)
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id
    chat_id = query.message.chat_id
    action = query.data
    logger.info(f'Button callback triggered: action={action}, user_id={user_id}, chat_id={chat_id}')
    
    if chat_id > 0:  # Personal chat
        logger.info(f'Personal chat detected for user {user_id}')
        if action in ['collect', 'exclude', 'newpoll', 'startpoll', 'results']:
            if 'selected_chat_id' not in context.user_data:
                logger.info(f'No selected chat for user {user_id}, prompting to select chat')
                await select_chat(update, context, action)
                return
            chat_id = context.user_data['selected_chat_id']
            if user_id not in [admin.user.id for admin in await context.bot.get_chat_administrators(chat_id)]:
                logger.info(f'User {user_id} is not an admin in chat {chat_id}')
                await context.bot.send_message(chat_id=user_id, text='Только администраторы могут использовать эту команду.')
                return
    else:  # Group chat
        logger.info(f'Group chat detected for chat {chat_id}')
        if action in ['collect', 'exclude', 'newpoll', 'startpoll', 'results']:
            if user_id not in [admin.user.id for admin in await context.bot.get_chat_administrators(chat_id)]:
                logger.info(f'User {user_id} is not an admin in group chat {chat_id}')
                await context.bot.send_message(chat_id=user_id, text='Только администраторы могут использовать эту команду.')
                return
            context.user_data['selected_chat_id'] = chat_id
            await update_known_chats(chat_id, query.message.chat.title)
    
    if action == 'help':
        logger.info(f'Help action triggered for user {user_id}')
        await help_command(update, context)
    elif action == 'collect':
        logger.info(f'Collect action triggered for user {user_id}')
        await collect(update, context)
    elif action == 'exclude':
        logger.info(f'Exclude action triggered for user {user_id}')
        await exclude(update, context)
    elif action == 'newpoll':
        logger.info(f'Newpoll action triggered for user {user_id}')
        await newpoll(update, context)
    elif action == 'startpoll':
        logger.info(f'Startpoll action triggered for user {user_id}')
        await startpoll(update, context)
    elif action == 'results':
        logger.info(f'Results action triggered for user {user_id}')
        await results(update, context)
    elif action == 'setmessage':
        # Диалог для установки текста опроса
        logger.info(f'Setmessage action triggered for user {user_id} in chat {chat_id}')
        if chat_id > 0:  # Личка
            if 'selected_chat_id' not in context.user_data:
                # Попросить выбрать группу
                logger.info(f'No selected chat for setmessage, prompting user {user_id} to select chat')
                context.user_data['after_select_action'] = 'setmessage'
                await select_chat(update, context, 'setmessage')
                return
        context.user_data['waiting_for_poll_message'] = True
        logger.info(f'Setting waiting_for_poll_message for user {user_id} in chat {chat_id}')
        try:
            await context.bot.send_message(chat_id=user_id, text='Пожалуйста, отправьте текст опроса одним сообщением.')
            logger.info(f'Sent prompt for poll message to user {user_id}')
        except Exception as e:
            logger.error(f'Error sending setmessage prompt to user {user_id}: {e}')
            # Fallback to ensure the message is sent directly
            await context.bot.send_message(chat_id=query.from_user.id, text='Пожалуйста, отправьте текст опроса одним сообщением (запасной вариант).')
            logger.info(f'Sent fallback prompt for poll message to user {user_id}')
    elif action == 'setoptions':
        # Диалог для установки вариантов опроса
        logger.info(f'Setoptions action triggered for user {user_id} in chat {chat_id}')
        if chat_id > 0:  # Личка
            if 'selected_chat_id' not in context.user_data:
                logger.info(f'No selected chat for setoptions, prompting user {user_id} to select chat')
                context.user_data['after_select_action'] = 'setoptions'
                await select_chat(update, context, 'setoptions')
                return
        context.user_data['waiting_for_poll_options'] = True
        await context.bot.send_message(chat_id=user_id, text='Пожалуйста, отправьте варианты ответа через запятую одним сообщением.')
    elif action == 'mychats':
        await mychats(update, context, force_user_id=user_id)
    elif action.startswith('poll_'):
        poll_id, response_idx = action.split('_')[1], action.split('_')[2]
        
        c.execute('SELECT chat_id, message_id, options FROM polls WHERE poll_id = ?', (poll_id,))
        res = c.fetchone()
        if not res:
            logger.error(f"Poll {poll_id} not found when voting.")
            return
        poll_chat_id, poll_message_id, options_str = res

        options = options_str.split(',')
        response = options[int(response_idx)].strip()

        # Удаляем предыдущий ответ пользователя для этого poll_id
        c.execute('DELETE FROM responses WHERE poll_id = ? AND user_id = ?', (poll_id, user_id))
        # Вставляем новый ответ
        c.execute('INSERT INTO responses (poll_id, user_id, response) VALUES (?, ?, ?)', (poll_id, user_id, response))
        conn.commit()
        
        # --- ИЗМЕНЕНО: Используем новую функцию для генерации текста ---
        text_to_send, new_options = _generate_results_text_and_options(int(poll_id), include_non_voters=False, detailed_names=False)
        
        if not text_to_send:
            logger.error(f"Failed to generate poll results for poll {poll_id} after a vote.")
            return

        try:
            await context.bot.edit_message_text(
                chat_id=poll_chat_id,
                message_id=poll_message_id,
                text=text_to_send,
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton(opt.strip(), callback_data=f'poll_{poll_id}_{i}')] for i, opt in enumerate(new_options)]),
                parse_mode='HTML'
            )
        except Exception as e:
            logger.error(f'Ошибка при обновлении сообщения с опросом: {e}')
    elif action.startswith('selectchat_'):
        await select_chat_callback(update, context)
    elif action == 'setresultoptions':
        await setresultoptions(update, context)

# --- ДОБАВЛЕНО: handler для любых сообщений в группах ---
async def track_group_user(update: Update, context: ContextTypes.DEFAULT_TYPE):
    add_user_to_participants(update)
    chat = update.effective_chat
    if chat and chat.type in ['group', 'supergroup']:
        await update_known_chats(chat.id, chat.title)

# --- Команда для очистки участников группы ---
async def cleangroup(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_id = update.effective_user.id
    chat_id = update.effective_chat.id
    if chat_id < 0:
        if user_id not in [admin.user.id for admin in await context.bot.get_chat_administrators(chat_id)]:
            await update.message.reply_text('Только администраторы могут использовать эту команду.')
            return
    else:
        if 'selected_chat_id' not in context.user_data:
            await update.message.reply_text('Сначала выберите группу.')
            return
        chat_id = context.user_data['selected_chat_id']
    c.execute('DELETE FROM participants WHERE chat_id = ?', (chat_id,))
    conn.commit()
    await update.message.reply_text('Список участников для этой группы очищен.')

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

# --- Обработчик кнопки "Список участников" ---
async def participants_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    add_user_to_participants(update)
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id
    # Получаем все известные группы
    c.execute('SELECT DISTINCT chat_id FROM polls')
    chat_ids = [row[0] for row in c.fetchall()]
    if not chat_ids:
        await query.edit_message_text('Бот не знает ни одной группы. Добавьте его в группу и напишите в ней что-нибудь.')
        return
    text = ''
    for gid in chat_ids:
        c.execute('SELECT title FROM known_chats WHERE chat_id = ?', (gid,))
        row = c.fetchone()
        title = row[0] if row else str(gid)
        text += f'<b>Группа:</b> {title} (ID: {gid})\n'
        c.execute('SELECT user_id, username, first_name, last_name, excluded FROM participants WHERE chat_id = ?', (gid,))
        participants = c.fetchall()
        # Убираем дубли по user_id
        unique_participants = {}
        for user_id_part, username, first_name, last_name, excluded in participants:
            if user_id_part not in unique_participants:
                unique_participants[user_id_part] = (username, first_name, last_name, excluded)
        if not unique_participants:
            text += '  — <i>Список участников пуст</i>\n'
        else:
            for user_id_part, (username, first_name, last_name, excluded) in unique_participants.items():
                name = first_name + (f' {last_name}' if last_name else '')
                display_name = f'{name} (@{username})' if username else name
                status = ' (исключен)' if excluded else ''
                text += f'  — {display_name}{status}\n'
        text += '\n'
    await query.edit_message_text(text, parse_mode='HTML')

# Добавляю обработчик для participantschat_
async def participantschat_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    add_user_to_participants(update)
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id
    chat_id = int(query.data.split('_')[1])
    context.user_data['selected_chat_id'] = chat_id
    c.execute('SELECT user_id, username, first_name, last_name, excluded FROM participants WHERE chat_id = ?', (chat_id,))
    participants = c.fetchall()
    # Убираем дубли по user_id
    unique_participants = {}
    for user_id_part, username, first_name, last_name, excluded in participants:
        if user_id_part not in unique_participants:
            unique_participants[user_id_part] = (username, first_name, last_name, excluded)
    if not participants:
        await query.edit_message_text('Список участников пуст. Используйте /collect для сбора участников.')
        return
    text = '<b>Список участников группы:</b>\n'
    for user_id_part, (username, first_name, last_name, excluded) in unique_participants.items():
        name = first_name + (f' {last_name}' if last_name else '')
        display_name = f'{name} (@{username})' if username else name
        status = ' (исключен)' if excluded else ''
        text += f'- {display_name}{status}\n'
    await query.edit_message_text(text, parse_mode='HTML')

# --- Настройка вывода результатов опроса ---
async def setresultoptions(update: Update, context: ContextTypes.DEFAULT_TYPE):
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
        await select_chat(update, context, 'setresultoptions')
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

    await context.bot.send_message(chat_id=user_id, text='Настройте вывод результатов для каждого варианта:', reply_markup=InlineKeyboardMarkup(keyboard))

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
        await setresultoptions(update, context)
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
        await setresultoptions(update, context)
        return
        
    logger.warning(f'Необработанные данные в setresultoptions_callback: {data}')


# --- Callback для выбора опроса ---
async def setresultoptionspoll_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    poll_id = int(query.data.split('_')[1])
    context.user_data['setresultoptions_poll_id'] = poll_id
    # Перезапускаем setresultoptions для показа меню настроек
    await setresultoptions(update, context)

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
        await setresultoptions(update, context)
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
    await setresultoptions(update, context)

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
        await setresultoptions(update, context)

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
        await setresultoptions(update, context)

# --- ДОБАВЛЕНО: Единый обработчик текстовых сообщений ---
async def text_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    
    # Сначала проверяем состояния, которые не требуют авторизации или выбора чата
    # и хранятся в application.user_data
    if user_id in context.application.user_data:
        app_user_data = context.application.user_data[user_id]
        if app_user_data.get('waiting_for_emoji'):
            await setemoji_message_handler(update, context)
            return
        if app_user_data.get('waiting_for_option_text'):
            await setoptiontext_message_handler(update, context)
            return
        if app_user_data.get('waiting_for_target_sum'):
            await settargetsum_message_handler(update, context)
            return
        if app_user_data.get('waiting_for_contribution'):
            await setcontribution_message_handler(update, context)
            return

    # Затем проверяем состояния диалога, хранящиеся в user_data
    if context.user_data.get('waiting_for_poll_message') or context.user_data.get('waiting_for_poll_options'):
        await message_dialog_handler(update, context)
        return

async def results(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    add_user_to_participants(update)
    chat_id = update.effective_chat.id
    user_id = update.effective_user.id
    if chat_id < 0:  # Group chat
        if user_id not in [admin.user.id for admin in await context.bot.get_chat_administrators(chat_id)]:
            await context.bot.send_message(chat_id=user_id, text='Только администраторы могут использовать эту команду.')
            return
        context.user_data['selected_chat_id'] = chat_id
    else:  # Private chat
        if 'selected_chat_id' not in context.user_data:
            await select_chat(update, context, 'results')
            return
        chat_id = context.user_data['selected_chat_id']
        if user_id not in [admin.user.id for admin in await context.bot.get_chat_administrators(chat_id)]:
            await context.bot.send_message(chat_id=user_id, text='Только администраторы могут использовать эту команду.')
            return
    
    c.execute('SELECT poll_id, message FROM polls WHERE chat_id = ? AND status = ?', (chat_id, 'active'))
    active_polls = c.fetchall()
    if not active_polls:
        await context.bot.send_message(chat_id=user_id, text='Нет активных опросов.')
        return
    
    if len(active_polls) > 1:
        keyboard = [[InlineKeyboardButton(f'Опрос {poll_id}: {message[:20]}...', callback_data=f'results_{poll_id}')] for poll_id, message in active_polls]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await context.bot.send_message(chat_id=user_id, text='Выберите опрос для просмотра результатов:', reply_markup=reply_markup)
    else:
        poll_id = active_polls[0][0]
        await show_results(update, context, poll_id, user_id)

def main() -> None:
    application = Application.builder().token(BOT_TOKEN).build()

    application.add_handler(CommandHandler('start', start))
    application.add_handler(CommandHandler('help', help_command))
    application.add_handler(CommandHandler('groups', groups))
    application.add_handler(CommandHandler('use', use_group))
    application.add_handler(CommandHandler('collect', collect))
    application.add_handler(CommandHandler('exclude', exclude))
    application.add_handler(CommandHandler('newpoll', newpoll))
    application.add_handler(CommandHandler('setmessage', setmessage))
    application.add_handler(CommandHandler('setoptions', setoptions))
    application.add_handler(CommandHandler('startpoll', startpoll))
    application.add_handler(CommandHandler('results', results))
    application.add_handler(CommandHandler('mychats', mychats))
    application.add_handler(CommandHandler('cleangroup', cleangroup))
    application.add_handler(CallbackQueryHandler(exclude_callback, pattern='^exclude_'))
    application.add_handler(CallbackQueryHandler(results_callback, pattern='^results_'))
    application.add_handler(CallbackQueryHandler(setresultoptions_callback, pattern='^setresultoptions_'))
    application.add_handler(CallbackQueryHandler(button_callback, pattern='^(help|collect|exclude|newpoll|startpoll|results|setmessage|setoptions|mychats|poll_.*|selectchat_.*|setresultoptions)$'))
    # --- ИЗМЕНЕНО: Используем единый обработчик для текстовых сообщений ---
    application.add_handler(MessageHandler(filters.TEXT & (~filters.COMMAND), text_handler))
    # --- ДОБАВЛЕНО: handler для любых сообщений в группах ---
    application.add_handler(MessageHandler(filters.ChatType.GROUPS, track_group_user), group=1) # Даем другую группу, чтобы он не пересекался с text_handler
    
    application.add_handler(CallbackQueryHandler(refresh_results_callback, pattern='^refreshresults_'))
    application.add_handler(CallbackQueryHandler(participants_callback, pattern='^participants$'))
    application.add_handler(CallbackQueryHandler(participantschat_callback, pattern='^participantschat_'))
    application.add_handler(CommandHandler('setresultoptions', setresultoptions))
    application.add_handler(CallbackQueryHandler(setresultoptionspoll_callback, pattern='^setresultoptionspoll_'))

    application.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == '__main__':
    main() 