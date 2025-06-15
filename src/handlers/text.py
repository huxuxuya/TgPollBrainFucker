from telegram import Update
from telegram.ext import ContextTypes
import asyncio

from src import database as db
from src.config import logger
from src.handlers import dashboard, settings

# --- Main router ---

async def text_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Handles all incoming text messages and routes them based on the user's state.
    """
    state = context.user_data.get('wizard_state')
    if not state:
        return # Not in a wizard, ignore text

    logger.info(f"Text handler triggered with state: {state} for user {update.effective_user.id}")
    
    # Immediately delete the user's text message to keep the UI clean
    try:
        await update.message.delete()
    except Exception as e:
        logger.warning(f"Could not delete user message: {e}")

    # Route to the appropriate handler
    if state.startswith('waiting_for_poll_'):
        await _handle_poll_creation(update, context)
    elif state.startswith('waiting_for_webapp_'):
        await _handle_webapp_creation(update, context)
    elif state == 'waiting_for_poll_setting' or state == 'waiting_for_option_setting':
        await _handle_settings_update(update, context)
    else:
        logger.warning(f"Unhandled wizard state: {state}. Cleaning context.")
        _clean_wizard_context(context)

# --- State-specific handlers ---

async def _handle_poll_creation(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handles text input during the poll creation wizard."""
    state = context.user_data.get('wizard_state')
    text_input = update.message.text
    app_user_data = context.user_data
    
    message_to_edit = app_user_data.get('message_to_edit')
    if not message_to_edit:
        logger.error("Cannot handle poll creation, message_to_edit is missing from context.")
        _clean_wizard_context(context)
        return

    if state == 'waiting_for_poll_title':
        app_user_data['wizard_title'] = text_input
        app_user_data['wizard_state'] = 'waiting_for_poll_options'
        prompt = "Отлично. Теперь отправьте варианты ответа, каждый на новой строке. Когда закончите, нажмите /done."
        await context.bot.edit_message_text(prompt, chat_id=update.effective_chat.id, message_id=message_to_edit)

    elif state == 'waiting_for_poll_options':
        if 'wizard_options' not in app_user_data:
            app_user_data['wizard_options'] = []
        options = app_user_data['wizard_options']
        options.append(text_input)
        
        # Give feedback by updating the message
        current_options_text = "\n".join([f"▫️ {opt}" for opt in options])
        prompt = f"Отлично. Добавлен вариант. \n\n*Текущие варианты:*\n{current_options_text}\n\nПродолжайте добавлять или нажмите /done."
        await context.bot.edit_message_text(prompt, chat_id=update.effective_chat.id, message_id=message_to_edit, parse_mode='MarkdownV2')


async def _handle_webapp_creation(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handles text input during the Web App creation wizard."""
    state = context.user_data.get('wizard_state')
    text_input = update.message.text
    app_user_data = context.user_data
    
    message_to_edit = app_user_data.get('message_to_edit')
    chat_id = app_user_data.get('wizard_chat_id')
    if not message_to_edit or not chat_id:
        logger.error(f"Cannot handle webapp creation, context is missing data: {app_user_data}")
        _clean_wizard_context(context)
        return

    if state == 'waiting_for_webapp_name':
        app_user_data['wizard_webapp_name'] = text_input
        app_user_data['wizard_state'] = 'waiting_for_webapp_url'
        await context.bot.edit_message_text(
            chat_id=chat_id,
            message_id=message_to_edit,
            text="Отлично. Теперь введите полный URL вашего Web App, начиная с `https://`:"
        )

    elif state == 'waiting_for_webapp_url':
        name = app_user_data['wizard_webapp_name']
        url = text_input
        db.add_web_app(chat_id, name, url)

        # After adding, show the main webapp menu again
        text, reply_markup = dashboard._get_webapp_management_menu(chat_id)
        await context.bot.edit_message_text(
            chat_id=chat_id,
            message_id=message_to_edit,
            text=text,
            reply_markup=reply_markup,
            parse_mode='MarkdownV2'
        )
        _clean_wizard_context(context)


async def _handle_settings_update(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handles text input for changing poll or option settings."""
    text_input = update.message.text
    app_user_data = context.user_data

    poll_id = app_user_data.get('wizard_poll_id')
    setting_key = app_user_data.get('wizard_setting_key')
    message_id = app_user_data.get('wizard_message_id')
    chat_id = update.effective_chat.id

    if not all([poll_id, setting_key, message_id]):
        logger.error(f"Missing context for settings update: {app_user_data}")
        _clean_wizard_context(context)
        return

    session = db.SessionLocal()
    try:
        # --- Option-specific settings ---
        if context.user_data['wizard_state'] == 'waiting_for_option_setting':
            option_index = app_user_data.get('wizard_option_index')
            if option_index is None:
                raise ValueError("State is for option setting but 'wizard_option_index' is missing.")

            if setting_key == 'text':
                poll = session.query(db.Poll).filter_by(poll_id=poll_id).first()
                if poll:
                    options_list = poll.options.split(',')
                    if option_index < len(options_list):
                        old_text = options_list[option_index].strip()
                        for resp in poll.responses:
                            if resp.response == old_text:
                                resp.response = text_input
                        options_list[option_index] = text_input
                        poll.options = ','.join(options_list)
                    else:
                        logger.error(f"Option index {option_index} out of bounds for poll {poll_id}")
            else:
                setting = db.get_poll_option_setting(poll_id, option_index, create=True, session=session)
                if setting_key == 'emoji':
                    setting.emoji = text_input
                elif setting_key == 'contribution_amount':
                    try:
                        setting.contribution_amount = float(text_input.replace(',', '.'))
                    except ValueError:
                         logger.warning(f"Invalid contribution amount: {text_input}")
                         # Should we notify the user? For now, we don't.
            
            session.commit()
            await settings.show_single_option_settings_menu(None, context, poll_id, option_index, chat_id=chat_id, message_id=message_id)

        # --- Poll-level settings ---
        elif context.user_data['wizard_state'] == 'waiting_for_poll_setting':
            poll = session.query(db.Poll).filter_by(poll_id=poll_id).first()
            if poll:
                if setting_key == 'message':
                    poll.message = text_input
                elif setting_key == 'options':
                    poll.options = text_input.replace('\n', ',')
                elif setting_key == 'nudge_negative_emoji':
                    poll_setting = db.get_poll_setting(poll_id, create=True, session=session)
                    poll_setting.nudge_negative_emoji = text_input
            
            session.commit()
            await settings.show_poll_settings_menu(None, context, poll_id, chat_id=chat_id, message_id=message_id)

    except Exception as e:
        logger.error(f"Error updating setting: {e}", exc_info=True)
        session.rollback()
    finally:
        session.close()
        _clean_wizard_context(context)

# --- Utility Functions ---

def _clean_wizard_context(context: ContextTypes.DEFAULT_TYPE):
    """Clears all wizard-related keys from user_data."""
    keys_to_clean = [key for key in context.user_data if key.startswith('wizard_')]
    for key in keys_to_clean:
        context.user_data.pop(key, None)
    
    # Clean old/alternative keys for safety
    legacy_keys = ['settings_state', 'poll_id', 'option_index', 'message_to_edit', 'chat_id_to_edit']
    for key in legacy_keys:
        context.user_data.pop(key, None)
        
    logger.debug(f"Cleaned wizard context. Remaining user_data keys: {list(context.user_data.keys())}")


async def done_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Finishes the poll creation wizard."""
    app_user_data = context.user_data
    state = app_user_data.get('wizard_state')
    
    if not state or not state.startswith('waiting_for_poll_'):
        await update.message.reply_text("Нет активного процесса создания опроса.", quote=False)
        return
        
    try:
        await update.message.delete()
    except Exception:
        pass # Ignore if already deleted

    poll_type = app_user_data.get('wizard_poll_type', 'native')
    chat_id = app_user_data.get('wizard_chat_id')
    title = app_user_data.get('wizard_title')
    message_to_edit = app_user_data.get('message_to_edit')

    if not all([chat_id, title, message_to_edit]):
        logger.error(f"Cannot complete wizard, context is missing data: {app_user_data}")
        _clean_wizard_context(context)
        return

    if poll_type == 'native':
        options = app_user_data.get('wizard_options', [])
        if not options:
            await context.bot.edit_message_text("Вы не добавили ни одного варианта. Мастер отменен.", chat_id=chat_id, message_id=message_to_edit)
        else:
            new_poll = db.Poll(chat_id=chat_id, message=title, status='draft', options=','.join(options), poll_type='native')
            db.add_poll(new_poll)
            await context.bot.edit_message_text(f"✅ Черновик обычного опроса '{title}' создан!\nВы можете управлять им из меню черновиков.", chat_id=chat_id, message_id=message_to_edit)

    elif poll_type == 'webapp':
        webapp_id = app_user_data.get('wizard_webapp_id')
        session = db.SessionLocal()
        try:
            webapp = session.query(db.WebApp).filter_by(id=webapp_id).first()
            if not webapp:
                 await context.bot.edit_message_text("Ошибка: Web App не найдено. Мастер отменен.", chat_id=chat_id, message_id=message_to_edit)
            else:
                new_poll = db.Poll(chat_id=chat_id, message=title, status='draft', options=webapp.url, poll_type='webapp')
                db.add_poll(new_poll)
                await context.bot.edit_message_text(f"✅ Черновик Web App опроса '{title}' создан!\nВы можете управлять им из меню черновиков.", chat_id=chat_id, message_id=message_to_edit)
        finally:
            session.close()

    _clean_wizard_context(context) 