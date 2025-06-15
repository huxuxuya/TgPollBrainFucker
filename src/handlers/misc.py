from telegram import Update
from telegram.ext import ContextTypes
import json

from src import database as db
from src.config import logger
from src.handlers.voting import update_poll_message

async def forwarded_message_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handles a forwarded message to add a user to the participants list."""
    user_data = context.user_data.get('user_to_add_via_forward')
    if not user_data:
        return

    chat_id_to_add = user_data.get('chat_id')
    original_message = update.message
    fwd_from = original_message.forward_from

    if not fwd_from:
        await original_message.reply_text("Не могу добавить пользователя. Либо это бот, либо у него скрыт профиль.")
        return

    # Check if participant already exists
    existing_participant = db.get_participant(chat_id_to_add, fwd_from.id)
    if existing_participant:
        await original_message.reply_text(f"Пользователь {fwd_from.full_name} уже в списке участников.")
    else:
        db.add_user_to_participants(
            chat_id=chat_id_to_add,
            user_id=fwd_from.id,
            username=fwd_from.username,
            first_name=fwd_from.first_name,
            last_name=fwd_from.last_name
        )
        await original_message.reply_text(f"Пользователь {fwd_from.full_name} добавлен в список участников.")

    # Clean up user context
    del context.user_data['user_to_add_via_forward']

async def web_app_data_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handles data sent from a Web App."""
    user = update.effective_user
    data = json.loads(update.effective_message.web_app_data.data)

    # Basic validation
    if 'poll_id' not in data or 'response' not in data:
        # Silently ignore malformed data
        return

    poll_id = data['poll_id']
    response_text = data['response']

    # We reuse the same logic as regular voting for consistency
    db.add_or_update_response(
        poll_id=poll_id,
        user_id=user.id,
        first_name=user.first_name,
        last_name=user.last_name,
        username=user.username,
        # For webapp responses, we don't have an index, so we pass the text directly.
        # We'll need to adjust `add_or_update_response` to handle this.
        option_text=response_text
    )

    # Update the visual representation of the poll
    await update_poll_message(poll_id, context) 