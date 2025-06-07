# -*- coding: utf-8 -*-
# Gemini was here
import logging
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, CallbackQuery
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, ContextTypes, MessageHandler, filters
from typing import Union
import sqlite3
import os
from dotenv import load_dotenv
from telegram.constants import ParseMode

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
# --- ДОБАВЛЕНО: добавляем поле message_id, если его нет ---
try:
    c.execute('ALTER TABLE polls ADD COLUMN message_id INTEGER')
    conn.commit()
except Exception:
    pass  # поле уже есть
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
    await context.bot.send_message(chat_id=user_id, text='Доступные команды:\n/start - Начать работу с ботом\n/help - Показать помощь\n/collect - Собрать список участников группы\n/exclude - Исключить участника из опроса\n/setmessage - Установить сообщение для опроса\n/setoptions - Установить варианты ответов для опроса\n/startpoll - Запустить опрос\n/results - Показать результаты опроса\n/newpoll - Создать новый опрос\n/mychats - Показать список известных групп', reply_markup=reply_markup)

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
    if not participants:
        await context.bot.send_message(chat_id=user_id, text='Список участников пуст. Используйте /collect для сбора участников.')
        return
    
    keyboard = []
    for user_id_part, username, first_name, last_name, excluded in participants:
        name = first_name + (f' {last_name}' if last_name else '')
        display_name = f'{name} (@{username})' if username else name
        status = ' (исключен)' if excluded else ''
        keyboard.append([InlineKeyboardButton(f'{display_name}{status}', callback_data=f'exclude_{user_id_part}_{chat_id}')])
    reply_markup = InlineKeyboardMarkup(keyboard)
    await context.bot.send_message(chat_id=user_id, text='Выберите участника для исключения/включения:', reply_markup=reply_markup)

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
    chat_id = update.effective_chat.id
    user_id = update.effective_user.id
    if chat_id < 0:  # Group chat
        if user_id not in [admin.user.id for admin in await context.bot.get_chat_administrators(chat_id)]:
            await context.bot.send_message(chat_id=user_id, text='Только администраторы могут использовать эту команду.')
            return
        context.user_data['selected_chat_id'] = chat_id
    else:  # Private chat
        if 'selected_chat_id' not in context.user_data:
            await select_chat(update, context, 'newpoll')
            return
        chat_id = context.user_data['selected_chat_id']
        if user_id not in [admin.user.id for admin in await context.bot.get_chat_administrators(chat_id)]:
            await context.bot.send_message(chat_id=user_id, text='Только администраторы могут использовать эту команду.')
            return
    cursor = c.execute('INSERT INTO polls (chat_id, message, status, options) VALUES (?, ?, ?, ?)', (chat_id, '', 'draft', 'Перевел,Позже,Не участвую'))
    poll_id = cursor.lastrowid
    conn.commit()
    logger.info(f'[NEWPOLL] Создан новый опрос: poll_id={poll_id}, chat_id={chat_id}')
    # Удаляем все старые черновики кроме только что созданного
    c.execute('DELETE FROM polls WHERE chat_id = ? AND status = ? AND poll_id != ?', (chat_id, 'draft', poll_id))
    conn.commit()
    await context.bot.send_message(chat_id=user_id, text=f'Создан новый опрос с ID {poll_id}. Используйте /setmessage и /setoptions для настройки.')

async def mychats(update: Update, context: ContextTypes.DEFAULT_TYPE, force_user_id=None):
    c.execute('SELECT chat_id, title FROM known_chats')
    chats = c.fetchall()
    user_id = force_user_id if force_user_id else (update.effective_user.id if update.effective_user else None)
    if not chats:
        text = 'Бот пока не знает ни одной группы. Добавьте его в группу и напишите в ней что-нибудь.'
    else:
        # Проверим, где пользователь админ
        admin_chats = []
        for chat_id, title in chats:
            try:
                admins = await context.bot.get_chat_administrators(chat_id)
                if user_id in [admin.user.id for admin in admins]:
                    admin_chats.append((chat_id, title))
            except Exception as e:
                logger.error(f'Error checking admin status in chat {chat_id}: {e}')
        if not admin_chats:
            text = 'Вы не являетесь администратором ни в одной из известных боту групп. Если вы уверены, что это не так, попробуйте написать что-нибудь в нужной группе, чтобы бот ее увидел.'
        else:
            text = 'Группы, где вы администратор и бот был активен:\n'
            for chat_id, title in admin_chats:
                text += f'- {title} (ID: {chat_id})\n'
    if force_user_id:
        await context.bot.send_message(chat_id=force_user_id, text=text)
    else:
        if update.message:
            await update.message.reply_text(text)
        elif update.callback_query:
            await update.callback_query.message.reply_text(text)

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

async def show_results(update: Update, context: ContextTypes.DEFAULT_TYPE, poll_id: int, user_id: int = None) -> None:
    add_user_to_participants(update)
    
    # Получаем ID чата из опроса, чтобы корректно найти участников
    c.execute("SELECT chat_id, message_id FROM polls WHERE poll_id = ?", (poll_id,))
    res = c.fetchone()
    if not res:
        if user_id:
            await context.bot.send_message(chat_id=user_id, text=f"Опрос с ID {poll_id} не найден.")
        elif update.effective_message:
            await update.effective_message.reply_text(f"Опрос с ID {poll_id} не найден.")
        return
    chat_id, poll_message_id = res

    if user_id is None:
        user_id = update.effective_user.id
        
    c.execute('SELECT p.user_id, p.username, p.first_name, p.last_name, r.response FROM participants p LEFT JOIN responses r ON p.user_id = r.user_id AND r.poll_id = ? WHERE p.chat_id = ? AND p.excluded = 0', (poll_id, chat_id))
    responses = c.fetchall()
    
    # Подсчет количества проголосовавших
    voted_count = sum(1 for row in responses if row[4])
    
    c.execute('SELECT options, message FROM polls WHERE poll_id = ?', (poll_id,))
    poll_row = c.fetchone()
    if poll_row:
        options_str, poll_message = poll_row
        options = [opt.strip() for opt in options_str.split(',')]
    else:
        poll_message = f'Опрос {poll_id}'
        options = []
    # Собираем по вариантам: user_id, имя
    option_voters = {opt: set() for opt in options}
    all_voted_user_ids = set()
    for user_id_part, username, first_name, last_name, response in responses:
        if response:
            name = first_name + (f' {last_name}' if last_name else '')
            option_voters[response].add((user_id_part, name))
            all_voted_user_ids.add(user_id_part)
    # Сортируем варианты по числу голосов (убывание)
    sorted_options = sorted(options, key=lambda o: len(option_voters[o]), reverse=True)
    max_votes = max((len(option_voters[o]) for o in options), default=0)
    # Список не проголосовавших
    not_voted = [first_name + (f' {last_name}' if last_name else '') for user_id_part, username, first_name, last_name, response in responses if not response]
    # Формируем красивый HTML-результат
    result_text = f'<b>📊 {poll_message}</b>\n\n<b>Результаты</b> <i>(👥 {len(all_voted_user_ids)})</i>:'
    for idx, opt in enumerate(sorted_options):
        votes = len(option_voters[opt])
        result_text += f'\n<b>• {opt}</b>: <b>{votes}</b>'
        for _, n in sorted(option_voters[opt]):
            result_text += f'\n    — {n}'
    if not_voted:
        result_text += '\n\n<b>Не проголосовали:</b>\n'
        for n in not_voted:
            result_text += f'— {n}\n'
    # Кнопка обновления результатов
    keyboard = [[InlineKeyboardButton('🔄 Обновить результаты в группе', callback_data=f'refreshresults_{poll_id}')]]
    await context.bot.send_message(chat_id=user_id, text=result_text, parse_mode='HTML', reply_markup=InlineKeyboardMarkup(keyboard))

async def results_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    add_user_to_participants(update)
    query = update.callback_query
    await query.answer()
    poll_id = int(query.data.split('_')[1])
    await show_results(update, context, poll_id, query.from_user.id)

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
    # Удаляем старое сообщение с результатами
    if old_message_id:
        try:
            await context.bot.delete_message(chat_id=chat_id, message_id=old_message_id)
        except Exception as e:
            pass  # Может быть уже удалено
    # Формируем новое сообщение с результатами
    c.execute('SELECT p.user_id, p.username, p.first_name, p.last_name, r.response FROM participants p LEFT JOIN responses r ON p.user_id = r.user_id AND r.poll_id = ? WHERE p.chat_id = ? AND p.excluded = 0', (poll_id, chat_id))
    responses = c.fetchall()
    options = [opt.strip() for opt in options_str.split(',')]
    option_voters = {opt: set() for opt in options}
    all_voted_user_ids = set()
    for user_id_part, username, first_name, last_name, response in responses:
        if response:
            name = first_name + (f' {last_name}' if last_name else '')
            option_voters[response].add((user_id_part, name))
            all_voted_user_ids.add(user_id_part)
    sorted_options = sorted(options, key=lambda o: len(option_voters[o]), reverse=True)
    result_text = f'<b>📊 {poll_message}</b>\n\n<b>Результаты</b> <i>(👥 {len(all_voted_user_ids)})</i>:'
    for idx, opt in enumerate(sorted_options):
        votes = len(option_voters[opt])
        result_text += f'\n<b>• {opt}</b>: <b>{votes}</b>'
        for _, n in sorted(option_voters[opt]):
            result_text += f'\n    — {n}'
    # Отправляем новое сообщение в группу (тихо) с кнопками голосования
    poll_keyboard = InlineKeyboardMarkup([[InlineKeyboardButton(opt, callback_data=f'poll_{poll_id}_{i}')] for i, opt in enumerate(options)])
    new_msg = await context.bot.send_message(chat_id=chat_id, text=result_text, parse_mode='HTML', disable_notification=True, reply_markup=poll_keyboard)
    # Сохраняем новый message_id
    c.execute('UPDATE polls SET message_id = ? WHERE poll_id = ?', (new_msg.message_id, poll_id))
    conn.commit()
    await query.edit_message_text('Результаты обновлены в группе!')

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
        c.execute('SELECT options, message, chat_id, message_id FROM polls WHERE poll_id = ?', (poll_id,))
        options_str, poll_message, poll_chat_id, poll_message_id = c.fetchone()
        options = options_str.split(',')
        response = options[int(response_idx)].strip()
        # Удаляем предыдущий ответ пользователя для этого poll_id
        c.execute('DELETE FROM responses WHERE poll_id = ? AND user_id = ?', (poll_id, user_id))
        # Вставляем новый ответ
        c.execute('INSERT INTO responses (poll_id, user_id, response) VALUES (?, ?, ?)', (poll_id, user_id, response))
        conn.commit()
        # --- Формируем результаты без дублей ---
        names = {opt.strip(): set() for opt in options}  # set для уникальности
        # Получаем все ответы
        sql = 'SELECT r.response, p.first_name, p.last_name, p.user_id FROM responses r JOIN participants p ON r.user_id = p.user_id AND p.chat_id = ? WHERE r.poll_id = ?'
        c.execute(sql, (poll_chat_id, poll_id))
        raw_responses = c.fetchall()
        debug_sql = f"SQL: {sql} | params: ({poll_chat_id}, {poll_id}) | rows: {raw_responses}"
        for resp, first_name, last_name, uid in raw_responses:
            resp_clean = resp.strip() if resp else ''
            if resp_clean in names:
                name = first_name + (f' {last_name}' if last_name else '')
                names[resp_clean].add((uid, name))  # по user_id
        # Подсчет количества проголосовавших (уникальных user_id с ответом)
        voted_user_ids = set(uid for resp, first_name, last_name, uid in raw_responses if resp)
        voted_count = len(voted_user_ids)
        # Формируем результаты без дублей
        result_text = f'<b>{poll_message}</b>\n\n<b>Результаты</b> <i>(проголосовало: {voted_count})</i>:\n'
        for opt in options:
            opt_clean = opt.strip()
            unique_voters = names[opt_clean]
            result_text += f'\n<b>• {opt_clean}</b>: <b>{len(unique_voters)}</b>'
            for _, n in sorted(unique_voters):
                result_text += f'\n    — {n}'
        text_to_send = result_text
        try:
            await context.bot.edit_message_text(
                chat_id=poll_chat_id,
                message_id=poll_message_id,
                text=text_to_send,
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton(opt.strip(), callback_data=f'poll_{poll_id}_{i}')] for i, opt in enumerate(options)]),
                parse_mode='HTML'
            )
        except Exception as e:
            logger.error(f'Ошибка при обновлении сообщения с опросом: {e}')
    elif action.startswith('selectchat_'):
        await select_chat_callback(update, context)

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

async def use_group(update: Update, context: ContextTypes.DEFAULT_TYPE):
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
    application.add_handler(CallbackQueryHandler(button_callback, pattern='^(help|collect|exclude|newpoll|startpoll|results|setmessage|setoptions|mychats|poll_|selectchat_)'))
    # --- ДОБАВЛЕНО: handler для любых сообщений в группах ---
    application.add_handler(MessageHandler(filters.ChatType.GROUPS, track_group_user))
    application.add_handler(MessageHandler(filters.TEXT & (~filters.COMMAND), message_dialog_handler))
    application.add_handler(CallbackQueryHandler(refresh_results_callback, pattern='^refreshresults_'))

    application.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == '__main__':
    main() 