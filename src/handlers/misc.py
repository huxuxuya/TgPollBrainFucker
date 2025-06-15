from telegram import Update
from telegram.ext import ContextTypes

from src import database as db
from src.config import logger

async def forwarded_message_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    Handles a forwarded message to add a user to a participant list.
    This is initiated from the dashboard.
    """
    user_data_to_add = context.user_data.get('user_to_add_via_forward')
    if not user_data_to_add:
        return

    forwarded_from = update.message.forward_from
    if not forwarded_from:
        await update.message.reply_text("Не могу определить пользователя из этого сообщения. Возможно, он скрыл свой профиль.")
        return

    chat_id_to_add = user_data_to_add['chat_id']
    user_to_add = forwarded_from

    existing_participant = db.get_participant(chat_id_to_add, user_to_add.id)
    if existing_participant:
        await update.message.reply_text(f"Пользователь {user_to_add.first_name} уже в списке участников '{db.get_group_title(chat_id_to_add)}'.")
    else:
        # We also need to add them to the main Users table
        db.add_user_to_participants(chat_id_to_add, user_to_add.id, user_to_add.username, user_to_add.first_name, user_to_add.last_name)
        await update.message.reply_text(f"Пользователь {user_to_add.first_name} добавлен в список участников '{db.get_group_title(chat_id_to_add)}'.")
    
    # Clean up state
    del context.user_data['user_to_add_via_forward'] 