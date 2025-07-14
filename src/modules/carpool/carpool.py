from src.modules.base import PollModuleBase
from .handlers import register_carpool_handlers, get_driver_button, handle_deeplink_start
from telegram.ext import CommandHandler
from telegram import InlineKeyboardMarkup, InlineKeyboardButton
from src.database import SessionLocal, Poll

def escape_markdown(text: str) -> str:
    """Экранирует все спецсимволы для MarkdownV2."""
    escape_chars = r'_*[]()~`>#+-=|{}.!'
    return ''.join(f'\\{c}' if c in escape_chars else c for c in text)

class CarpoolModule(PollModuleBase):
    poll_type = "carpool"
    display_name = "Рассадка по машинам"

    def register_handlers(self, application):
        register_carpool_handlers(application)
        # Удалена регистрация CommandHandler('start', handle_deeplink_start)

    def get_extra_buttons(self, poll_id, bot_username):
        return [get_driver_button(poll_id, bot_username)]

    async def wizard_create_poll(self, query, context, chat_id):
        # Запросить у пользователя название опроса
        context.user_data['wizard_state'] = 'waiting_for_carpool_title'
        context.user_data['wizard_chat_id'] = chat_id
        await query.edit_message_text(
            "Введите название (заголовок) для рассадки по машинам:",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("❌ Отмена", callback_data=f"dash:group:{chat_id}")]
            ])
        )
        # Следующий шаг — обработать ввод названия в text.py или dashboard.py (по аналогии с native) 

    async def wizard_handle_text(self, state, update, context):
        if state == 'waiting_for_carpool_title':
            title = update.message.text.strip()
            chat_id = context.user_data.get('wizard_chat_id')
            message_to_edit = context.user_data.get('message_to_edit')
            if not all([chat_id, title, message_to_edit]):
                from src.handlers.text import _clean_wizard_context
                _clean_wizard_context(context)
                return True
            from src import database as db
            new_poll = db.Poll(
                chat_id=chat_id,
                message=title,
                status='draft',
                poll_type='carpool'
            )
            new_poll_id = db.add_poll(new_poll)
            bot_username = (await context.bot.get_me()).username
            buttons = self.get_extra_buttons(new_poll_id, bot_username)
            from telegram import InlineKeyboardMarkup
            static_text = escape_markdown("Опрос рассадки по машинам создан!\n\n*")
            static_text_end = escape_markdown("*")
            await context.bot.edit_message_text(
                f"{static_text}{escape_markdown(title)}{static_text_end}",
                chat_id=chat_id,
                message_id=message_to_edit,
                reply_markup=InlineKeyboardMarkup([buttons]),
                parse_mode='MarkdownV2'
            )
            from src.handlers.text import _clean_wizard_context
            _clean_wizard_context(context)
            return True
        return False 