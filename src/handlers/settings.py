from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, CallbackQuery
from telegram.ext import ContextTypes
from telegram.constants import ParseMode
from telegram.helpers import escape_markdown
from typing import Union
from telegram.error import BadRequest
import asyncio
import math

from src import database as db
from src.config import logger

async def _edit_message_safely(
    context: ContextTypes.DEFAULT_TYPE,
    text: str,
    query: CallbackQuery = None,
    chat_id: int = None,
    message_id: int = None,
    reply_markup: InlineKeyboardMarkup = None
):
    """A wrapper to safely edit messages, handling common non-fatal errors."""
    try:
        escaped_text = escape_markdown(text, version=2)
        if query:
            await query.edit_message_text(escaped_text, reply_markup=reply_markup, parse_mode=ParseMode.MARKDOWN_V2)
        elif chat_id and message_id:
            await context.bot.edit_message_text(
                chat_id=chat_id,
                message_id=message_id,
                text=escaped_text,
                reply_markup=reply_markup,
                parse_mode=ParseMode.MARKDOWN_V2
            )
    except BadRequest as e:
        if "Message is not modified" in str(e):
            logger.info("Message not modified, ignoring.")
            if query: await query.answer() # Still acknowledge the callback
        else:
            logger.error(f"BadRequest on editing message: {e}\nOriginal text: {text}")
            if query: await query.answer("Произошла ошибка при обновлении сообщения.", show_alert=True)
            # Re-raising might be too disruptive, logging is often enough.
            # raise

async def show_nudge_emoji_menu(query: Union[CallbackQuery, None], context: ContextTypes.DEFAULT_TYPE, poll_id: int, message_id: int = None, chat_id: int = None):
    poll_setting = db.get_poll_setting(poll_id)
    neg_emoji = (poll_setting.nudge_negative_emoji if poll_setting and poll_setting.nudge_negative_emoji else '❌')
    text = f"⚙️ Настройка эмодзи для оповещения\n\nТекущий негативный эмодзи: {neg_emoji}"
    kb = [[InlineKeyboardButton("📝 Изменить", callback_data=f"settings:set_nudge_neg_emoji:{poll_id}")],
          [InlineKeyboardButton("↩️ Назад", callback_data=f"settings:poll_menu:{poll_id}")]]
    
    await _edit_message_safely(context, text, query=query, chat_id=chat_id, message_id=message_id, reply_markup=InlineKeyboardMarkup(kb))

async def show_option_settings_menu(query: Union[CallbackQuery, None], context: ContextTypes.DEFAULT_TYPE, poll_id: int, option_index: int, message_id: int = None, chat_id: int = None):
    poll = db.get_poll(poll_id)
    option_text = poll.options.split(',')[option_index].strip()
    poll_setting = db.get_poll_setting(poll_id)
    default_show_names, default_show_count = (1, 1) if not poll_setting else (poll_setting.default_show_names, poll_setting.default_show_count)
    
    opt_setting = db.get_poll_option_setting(poll_id, option_index)
    
    show_names = default_show_names if not opt_setting or opt_setting.show_names is None else opt_setting.show_names
    names_style = (poll_setting.default_names_style if not opt_setting or not opt_setting.names_style else opt_setting.names_style) or 'list'
    is_priority = opt_setting.is_priority if opt_setting else 0
    contribution = opt_setting.contribution_amount if opt_setting else 0
    emoji = (opt_setting.emoji if opt_setting and opt_setting.emoji else "–")
    show_count = default_show_count if not opt_setting or opt_setting.show_count is None else opt_setting.show_count
    show_contrib = 1 if not opt_setting or opt_setting.show_contribution is None else opt_setting.show_contribution

    text = f"⚙️ *Настройки варианта:* `{escape_markdown(option_text, 2)}`\n\n" \
           f"Показывать имена: {'Да' if show_names else 'Нет'}\n" \
           f"Стиль имен: {names_style}\n" \
           f"Приоритетный: {'Да' if is_priority else 'Нет'}\n" \
           f"Сумма взноса: {contribution}\n" \
           f"Эмодзи для голосовавших: {emoji}\n" \
           f"Показывать кол-во голосов: {'Да' if show_count else 'Нет'}\n" \
           f"Показывать сумму взноса: {'Да' if show_contrib else 'Нет'}"

    kb = [
        [InlineKeyboardButton(f"Показ имен: {'✅' if show_names else '❌'}", callback_data=f"settings:option:{poll_id}:{option_index}:shownames:{1-show_names}")],
        [InlineKeyboardButton(f"Приоритет: {'⭐' if is_priority else '➖'}", callback_data=f"settings:option:{poll_id}:{option_index}:priority:{1-is_priority}")],
        [InlineKeyboardButton(f"Показ кол-ва: {'✅' if show_count else '❌'}", callback_data=f"settings:option:{poll_id}:{option_index}:showcount:{1-show_count}")],
        [InlineKeyboardButton(f"Показ взноса: {'✅' if show_contrib else '❌'}", callback_data=f"settings:option:{poll_id}:{option_index}:showcontribution:{1-show_contrib}")],
        [InlineKeyboardButton("📝 Изменить текст", callback_data=f"settings:set_option_text:{poll_id}:{option_index}")],
        [InlineKeyboardButton("💰 Указать взнос", callback_data=f"settings:set_option_contrib:{poll_id}:{option_index}")],
        [InlineKeyboardButton("😀 Задать эмодзи", callback_data=f"settings:set_option_emoji:{poll_id}:{option_index}")],
        [InlineKeyboardButton("↩️ Назад к общим настройкам", callback_data=f"settings:poll_menu:{poll_id}")]
    ]
    
    await _edit_message_safely(context, text, query=query, chat_id=chat_id, message_id=message_id, reply_markup=InlineKeyboardMarkup(kb))

async def show_poll_settings_menu(query: Union[CallbackQuery, None], context: ContextTypes.DEFAULT_TYPE, poll_id: int, message_id: int = None, chat_id: int = None):
    """Shows the main settings menu for a specific poll."""
    poll = db.get_poll(poll_id)
    if not poll:
        if query: await query.answer("Опрос не найден.", show_alert=True)
        return

    poll_setting = db.get_poll_setting(poll_id, create=True)
    multiple_answers = poll_setting.allow_multiple_answers

    title = poll.message or f"Опрос {poll.poll_id}"
    text = f"⚙️ *Общие настройки опроса: «{escape_markdown(title, 2)}»*\n\n" \
           f"Несколько ответов: {'Да' if multiple_answers else 'Нет'}\n" \
           f"Показывать тепловую карту: {'Да' if poll_setting.show_heatmap else 'Нет'}"

    kb = [
        [
            InlineKeyboardButton("📝 Заголовок", callback_data=f"settings:ask_text:{poll_id}:message"),
            InlineKeyboardButton("📝 Варианты", callback_data=f"settings:ask_text:{poll_id}:options")
        ],
        [InlineKeyboardButton(f"Несколько ответов: {'✅' if multiple_answers else '❌'}", callback_data=f"settings:toggle_setting:{poll_id}:allow_multiple_answers")],
        [InlineKeyboardButton(f"Тепловая карта: {'✅' if poll_setting.show_heatmap else '❌'}", callback_data=f"settings:toggle_setting:{poll_id}:show_heatmap")],
        [InlineKeyboardButton("⚙️ Настроить варианты ответов", callback_data=f"settings:poll_options_menu:{poll_id}")],
        [InlineKeyboardButton("📢 Эмодзи для напоминаний", callback_data=f"settings:ask_text:{poll_id}:nudge_negative_emoji")],
        [InlineKeyboardButton("🚫 Исключить участников", callback_data=f"settings:excl_menu:{poll_id}:0")],
        [InlineKeyboardButton("↩️ К результатам/списку", callback_data=f"results:show:{poll.poll_id}")]
    ]
    
    await _edit_message_safely(context, text, query=query, chat_id=chat_id, message_id=message_id, reply_markup=InlineKeyboardMarkup(kb))

async def show_poll_options_settings_menu(query: CallbackQuery, context: ContextTypes.DEFAULT_TYPE, poll_id: int):
    """Shows the settings menu for poll options."""
    poll = db.get_poll(poll_id)
    if not poll:
        await query.answer("Опрос не найден.", show_alert=True)
        return
    
    title = poll.message or f"Опрос {poll.poll_id}"
    text = f"⚙️ *Настройки вариантов для «{title}»*:\nВыберите вариант для настройки."
    
    options = poll.options.split(',')
    kb = []
    for i, option_text in enumerate(options):
        button_text = f"✏️ {option_text.strip()[:30]}"
        kb.append([InlineKeyboardButton(button_text, callback_data=f"settings:option_menu:{poll_id}:{i}")])
    kb.append([InlineKeyboardButton("↩️ К настройкам опроса", callback_data=f"settings:poll_menu:{poll_id}")])

    await _edit_message_safely(context, text, query=query, reply_markup=InlineKeyboardMarkup(kb))

async def show_single_option_settings_menu(query: Union[CallbackQuery, None], context: ContextTypes.DEFAULT_TYPE, poll_id: int, option_index: int, message_id: int = None, chat_id: int = None):
    """Shows the detailed settings menu for a single poll option."""
    poll = db.get_poll(poll_id)
    if not poll:
        if query: await query.answer("Опрос не найден.", show_alert=True)
        return
    
    option_text = poll.options.split(',')[option_index].strip()
    opt_setting = db.get_poll_option_setting(poll_id, option_index, create=True)
    poll_setting = db.get_poll_setting(poll_id, create=True)

    show_names = opt_setting.show_names if opt_setting.show_names is not None else poll_setting.default_show_names
    show_count = opt_setting.show_count if opt_setting.show_count is not None else poll_setting.default_show_count
    names_style = opt_setting.names_style or poll_setting.default_names_style
    is_priority = opt_setting.is_priority
    contribution = opt_setting.contribution_amount
    emoji = opt_setting.emoji or '—'

    text = f"Настройки для варианта: *{escape_markdown(option_text, 2)}*"
    kb = [
        [InlineKeyboardButton("📝 Изменить текст", callback_data=f"settings:ask_option_text:{poll_id}:{option_index}:text")],
        [
            InlineKeyboardButton(f"Показ имен: {'✅' if show_names else '❌'}", callback_data=f"settings:toggle_option_setting:{poll_id}:{option_index}:show_names"),
            InlineKeyboardButton(f"Показ кол-ва: {'✅' if show_count else '❌'}", callback_data=f"settings:toggle_option_setting:{poll_id}:{option_index}:show_count")
        ],
        [
            InlineKeyboardButton(f"Стиль: {names_style}", callback_data=f"settings:toggle_option_setting:{poll_id}:{option_index}:names_style"),
            InlineKeyboardButton(f"Приоритет: {'⭐' if is_priority else '➖'}", callback_data=f"settings:toggle_option_setting:{poll_id}:{option_index}:is_priority")
        ],
        [
            InlineKeyboardButton("💰 Взнос", callback_data=f"settings:ask_option_text:{poll_id}:{option_index}:contribution_amount"),
            InlineKeyboardButton(f"Эмодзи: {emoji}", callback_data=f"settings:ask_option_text:{poll_id}:{option_index}:emoji")
        ],
        [InlineKeyboardButton("↩️ К списку вариантов", callback_data=f"settings:poll_options_menu:{poll_id}")]
    ]
    await _edit_message_safely(context, text, query=query, chat_id=chat_id, message_id=message_id, reply_markup=InlineKeyboardMarkup(kb))

async def text_input_for_setting(query: CallbackQuery, context: ContextTypes.DEFAULT_TYPE, poll_id: int, setting_key: str):
    """Prompts user for text input for a given setting."""
    # Storing state for the text_handler
    context.user_data['wizard_state'] = 'waiting_for_poll_setting'
    context.user_data['wizard_poll_id'] = poll_id
    context.user_data['wizard_setting_key'] = setting_key
    if query.message:
        context.user_data['wizard_message_id'] = query.message.message_id
        
    text_map = {
        "message": "Введите новый заголовок опроса:",
        "options": "Введите новые варианты, разделенные запятой (или каждый на новой строке):",
        "nudge_negative_emoji": "Введите новый эмодзи для 'не проголосовал':",
    }
    cancel_cb = f"settings:poll_menu:{poll_id}"
    text = text_map.get(setting_key, "Введите новое значение:")

    await _edit_message_safely(context, text, query=query, reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("❌ Отмена", callback_data=cancel_cb)]]))

async def text_input_for_option_setting(query: CallbackQuery, context: ContextTypes.DEFAULT_TYPE, poll_id: int, option_index: int, setting_key: str):
    """Prompts user for text input for a given option setting."""
    # Storing state for the text_handler
    context.user_data['wizard_state'] = 'waiting_for_option_setting'
    context.user_data['wizard_poll_id'] = poll_id
    context.user_data['wizard_option_index'] = option_index
    context.user_data['wizard_setting_key'] = setting_key
    if query.message:
        context.user_data['wizard_message_id'] = query.message.message_id

    text_map = {
        "text": "Введите новый текст для этого варианта:",
        "contribution_amount": "Введите сумму взноса для этого варианта:",
        "emoji": "Отправьте один эмодзи для этого варианта:",
    }
    text = text_map.get(setting_key, "Введите значение:")
    
    await _edit_message_safely(
        context,
        text,
        query=query,
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("❌ Отмена", callback_data=f"settings:option_menu:{poll_id}:{option_index}")]])
    )

async def settings_callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Routes all callbacks starting with 'settings:'."""
    query = update.callback_query
    # Run as a background task to avoid blocking on network issues.
    asyncio.create_task(query.answer())
    
    parts = query.data.split(':')
    command = parts[1]
    poll_id = int(parts[2])

    if command == "poll_menu":
        await show_poll_settings_menu(query, context, poll_id)
    elif command == "poll_options_menu":
        await show_poll_options_settings_menu(query, context, poll_id)
    elif command == "option_menu":
        await show_single_option_settings_menu(query, context, poll_id, int(parts[3]))
    elif command == "ask_text":
        await text_input_for_setting(query, context, poll_id, parts[3])
    elif command == "ask_option_text":
        await text_input_for_option_setting(query, context, poll_id, int(parts[3]), parts[4])
    elif command == "toggle_setting":
        setting_key = parts[3]
        toggle_boolean_setting(poll_id, setting_key)
        await show_poll_settings_menu(query, context, poll_id)
    elif command == "excl_menu":
        page = int(parts[3])
        await show_poll_exclusion_menu(query, context, poll_id, page)
    elif command == "toggle_excl":
        user_id = int(parts[3])
        page = int(parts[4])
        await toggle_exclude_in_poll(query, context, poll_id, user_id, page)
    elif command == "toggle_option_setting":
        option_index = int(parts[3])
        setting_key = parts[4]
        toggle_boolean_option_setting(poll_id, option_index, setting_key)
        await show_single_option_settings_menu(query, context, poll_id, option_index)

def toggle_boolean_setting(poll_id: int, setting_key: str):
    """Toggles a boolean setting for a poll."""
    setting = db.get_poll_setting(poll_id, create=True)
    if hasattr(setting, setting_key):
        current_value = getattr(setting, setting_key, False)
        setattr(setting, setting_key, not current_value)
        db.commit_session(setting)
    else:
        logger.warning(f"Attempted to toggle non-existent setting '{setting_key}' on poll {poll_id}")

def toggle_boolean_option_setting(poll_id: int, option_index: int, setting_key: str):
    """Toggles a boolean setting for a specific poll option."""
    option_setting = db.get_poll_option_setting(poll_id, option_index, create=True)
    
    if setting_key == 'names_style':
        # Get default from main settings if not set
        poll_setting = db.get_poll_setting(poll_id, create=True)
        current_style = option_setting.names_style or poll_setting.default_names_style or 'list'
        styles = ['list', 'inline', 'numbered']
        next_style_index = (styles.index(current_style) + 1) % len(styles)
        option_setting.names_style = styles[next_style_index]
    else:
        current_value = getattr(option_setting, setting_key)
        current_value = 1 if current_value is None else current_value
        setattr(option_setting, setting_key, 1 - current_value)

    db.commit_session(option_setting)

async def show_poll_exclusion_menu(query: CallbackQuery, context: ContextTypes.DEFAULT_TYPE, poll_id: int, page: int = 0):
    """Показывает список участников чата с возможностью исключения из опроса."""
    PAGE_SIZE = 20

    poll = db.get_poll(poll_id)
    if not poll:
        await query.answer("Опрос не найден.", show_alert=True)
        return

    session = db.SessionLocal()
    try:
        participants = db.get_participants(poll.chat_id, session=session)
        excluded_ids = db.get_poll_exclusions(poll_id, session=session)

        total_pages = max(1, math.ceil(len(participants) / PAGE_SIZE))
        page = max(0, min(page, total_pages - 1))

        start = page * PAGE_SIZE
        end = start + PAGE_SIZE
        page_participants = participants[start:end]

        text_lines = ["*Исключение участников из опроса:*", f"Стр. {page+1}/{total_pages}", ""]
        kb_rows = []
        for p in page_participants:
            name = db.get_user_name(session, p.user_id, markdown_link=True)
            is_exc = p.user_id in excluded_ids
            icon = "🚫" if is_exc else "✅"
            text_lines.append(f"{icon} {name}")
            kb_rows.append([InlineKeyboardButton(icon, callback_data=f"settings:toggle_excl:{poll_id}:{p.user_id}:{page}")])

        # Навигация
        nav_row = []
        if page > 0:
            nav_row.append(InlineKeyboardButton("⬅️", callback_data=f"settings:excl_menu:{poll_id}:{page-1}"))
        if page < total_pages - 1:
            nav_row.append(InlineKeyboardButton("➡️", callback_data=f"settings:excl_menu:{poll_id}:{page+1}"))
        if nav_row:
            kb_rows.append(nav_row)

        kb_rows.append([InlineKeyboardButton("↩️ Назад", callback_data=f"settings:poll_menu:{poll_id}")])

        await _edit_message_safely(context, "\n".join(text_lines), query=query, reply_markup=InlineKeyboardMarkup(kb_rows))
    finally:
        session.close()

async def toggle_exclude_in_poll(query: CallbackQuery, context: ContextTypes.DEFAULT_TYPE, poll_id: int, user_id: int, page: int):
    """Переключает исключение участника и возвращает в меню."""
    excluded = db.toggle_poll_exclusion(poll_id, user_id)
    await query.answer("Исключён" if excluded else "Включён", show_alert=False)
    # Обновляем меню той же страницы
    await show_poll_exclusion_menu(query, context, poll_id, page) 