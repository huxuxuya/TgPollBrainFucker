from telegram import Update
from telegram.ext import ContextTypes

from src import database as db
from src.config import logger
from src.handlers import dashboard, settings

async def text_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handles text messages, primarily for wizards and settings."""
    message = update.message
    text_input = message.text
    app_user_data = context.user_data

    if 'wizard_state' in app_user_data:
        state = app_user_data['wizard_state']
        
        if state == 'waiting_for_title':
            app_user_data['wizard_title'] = text_input
            app_user_data['wizard_state'] = 'waiting_for_options'
            await message.reply_text("Отлично. Теперь отправьте варианты ответа, каждый в новой строке. Когда закончите, нажмите /done.")
        
        elif state == 'waiting_for_options':
            if 'wizard_options' not in app_user_data:
                app_user_data['wizard_options'] = []
            app_user_data['wizard_options'].append(text_input)
            await message.reply_text(f"Добавлен вариант: '{text_input}'. Добавьте еще или нажмите /done.")

    elif 'settings_state' in app_user_data:
        state = app_user_data.get('settings_state')
        poll_id = app_user_data.get('poll_id')
        
        if state == 'waiting_for_set_option_emoji':
            opt_setting = db.get_poll_option_setting(poll_id, app_user_data['option_index'])
            if not opt_setting:
                opt_setting = db.PollOptionSetting(poll_id=poll_id, option_index=app_user_data['option_index'])
                db.add_poll_option_setting(opt_setting)
            opt_setting.emoji = text_input
        elif state == 'waiting_for_set_option_text':
            poll = db.get_poll(poll_id)
            options_list = poll.options.split(',')
            old_text = options_list[app_user_data['option_index']].strip()
            options_list[app_user_data['option_index']] = text_input
            poll.options = ','.join(options_list)
            # Also update existing responses
            responses = db.get_responses(poll_id)
            for resp in responses:
                if resp.response == old_text:
                    resp.response = text_input
        elif state == 'waiting_for_set_option_contrib':
            try:
                value = float(text_input)
                opt_setting = db.get_poll_option_setting(poll_id, app_user_data['option_index'])
                if not opt_setting:
                    opt_setting = db.PollOptionSetting(poll_id=poll_id, option_index=app_user_data['option_index'])
                    db.add_poll_option_setting(opt_setting)
                opt_setting.contribution_amount = value
            except (ValueError, TypeError): pass
        elif state == 'waiting_for_set_poll_target':
            try:
                value = float(text_input)
                poll_setting = db.get_poll_setting(poll_id)
                if not poll_setting:
                    poll_setting = db.PollSetting(poll_id=poll_id)
                    db.add_poll_setting(poll_setting)
                poll_setting.target_sum = value
            except (ValueError, TypeError): pass
        elif state == 'waiting_for_set_poll_text':
            poll = db.get_poll(poll_id)
            poll.message = text_input
        elif state == 'waiting_for_set_nudge_neg_emoji':
            poll_setting = db.get_poll_setting(poll_id)
            if not poll_setting:
                poll_setting = db.PollSetting(poll_id=poll_id)
                db.add_poll_setting(poll_setting)
            poll_setting.nudge_negative_emoji = text_input

        # After handling, commit changes and return to the appropriate menu
        db.commit_session()
        
        # Return to the correct menu, by editing the "please enter..." message
        msg_to_edit = app_user_data.get('message_to_edit')
        chat_id_to_edit = app_user_data.get('chat_id_to_edit')
        
        # Clean up state
        option_index_to_restore = app_user_data.get('option_index')
        for key in ['settings_state', 'poll_id', 'option_index', 'message_to_edit', 'chat_id_to_edit']:
            app_user_data.pop(key, None)

        if option_index_to_restore is not None:
            await settings.show_option_settings_menu(None, context, poll_id, option_index_to_restore, msg_to_edit, chat_id_to_edit)
        else:
            await settings.show_poll_settings_menu(None, context, poll_id, msg_to_edit, chat_id_to_edit)
        
        await message.delete()

    elif state == 'waiting_for_option_setting':
        poll_id = context.user_data.get('wizard_poll_id')
        option_index = context.user_data.get('wizard_option_index')
        setting_key = context.user_data.get('wizard_setting_key')
        msg_to_edit = context.user_data.get('wizard_message_id')
        chat_id_to_edit = update.effective_chat.id

        if poll_id is not None and option_index is not None and setting_key:
            if setting_key == 'text':
                poll = db.get_poll(poll_id)
                if poll:
                    options = poll.options.split(',')
                    if 0 <= option_index < len(options):
                        options[option_index] = text_input
                        poll.options = ','.join(options)
                        db.commit_session()
                        await update.message.reply_text(f"Текст варианта {option_index + 1} изменен.")
                    else:
                        await update.message.reply_text("Ошибка: неверный индекс варианта.")
            else:
                option_setting = db.get_poll_option_setting(poll_id, option_index, create=True)
                
                value = text_input
                if setting_key == 'contribution_amount':
                    try:
                        value = float(text_input.replace(',', '.'))
                    except ValueError:
                        await update.message.reply_text("Пожалуйста, введите число.")
                        return # Stay in the same state

                setattr(option_setting, setting_key, value)
                db.commit_session()
                await update.message.reply_text(f"Настройка варианта обновлена.")
            
            await settings.show_single_option_settings_menu(None, context, poll_id, option_index, msg_to_edit, chat_id_to_edit)

        clean_wizard_context(context)

async def done_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Finishes the poll creation wizard."""
    app_user_data = context.user_data
    if app_user_data.get('wizard_state') == 'waiting_for_options':
        chat_id = app_user_data['wizard_chat_id']
        title = app_user_data['wizard_title']
        options = app_user_data['wizard_options']

        if not options:
            await update.message.reply_text("Вы не добавили ни одного варианта. Мастер отменен.")
        else:
            new_poll = db.Poll(chat_id=chat_id, message=title, status='draft', options=','.join(options))
            db.add_poll(new_poll)
            await update.message.reply_text(f"Черновик опроса '{title}' создан!")
        
        # Clean up wizard data
        for key in ['wizard_state', 'wizard_title', 'wizard_options', 'wizard_chat_id']:
            app_user_data.pop(key, None)
        
        # Show the dashboard again
        # This is tricky because we don't have the query object.
        # A better approach would be to refactor how menus are called.
        # For now, we just send a confirmation.
        await update.message.reply_text("Вы можете управлять новым опросом из меню черновиков.") 