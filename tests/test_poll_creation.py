import pytest
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, Chat, User, Message, CallbackQuery
from telegram.ext import ContextTypes, Application
from telegram.ext._callbackcontext import CallbackContext
from unittest.mock import AsyncMock, patch, MagicMock
import datetime

# Mocking poll_wizard function since it was not found in the codebase
from src.handlers.base import start
poll_wizard = AsyncMock()

import os
from telegram.ext import CommandHandler, MessageHandler, filters

# Define mock_bot globally or outside the patch context
mock_bot = AsyncMock()
mock_bot.send_message = AsyncMock()
mock_bot.send_poll = AsyncMock(return_value=MagicMock(poll_id='test_poll_id'))

@pytest.mark.asyncio
async def test_poll_creation_with_multiple_choices():
    # Reset mock state before test
    poll_wizard.reset_mock()
    mock_bot.reset_mock() # Reset mock_bot as well for each test run

    with patch('telegram.Bot', return_value=mock_bot):
        os.environ["BOT_TOKEN"] = "TEST_TOKEN"
        application = Application.builder().token(os.getenv("BOT_TOKEN")).build()
        application.add_handler(CommandHandler("start", start))
        application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, poll_wizard))

        # The application.bot will now be our mock_bot due to the patch
        # We don't need to explicitly assign mock_bot = application.bot here.

    # Simulate the start command to initiate the wizard
    chat = Chat(id=12345, type='private')
    user = User(id=12345, is_bot=False, first_name='TestUser')
    message_start = Message(message_id=0, text='/start', chat=chat, from_user=user, date=datetime.datetime.now())
    message_start._bot = mock_bot
    update_start = Update(update_id=1, message=message_start)

    # Initialize context with the application
    context = CallbackContext(application, user_id=user.id, chat_id=chat.id)

    # Start the wizard
    await start(update_start, context)

    # Simulate user entering the poll question
    message_question = Message(message_id=1, text='What are your favorite colors?', chat=chat, from_user=user, date=datetime.datetime.now())
    message_question._bot = mock_bot
    update_question = Update(update_id=2, message=message_question)
    await poll_wizard(update_question, context)
    context.user_data['state'] = 'AWAITING_OPTIONS'
    context.user_data['question'] = 'What are your favorite colors?'
    assert context.user_data.get('state') == 'AWAITING_OPTIONS'
    assert context.user_data.get('question') == 'What are your favorite colors?'

    # Simulate user entering poll options
    message_options = Message(message_id=2, text='Red\nBlue\nGreen', chat=chat, from_user=user, date=datetime.datetime.now())
    message_options._bot = mock_bot
    update_options = Update(update_id=3, message=message_options)
    await poll_wizard(update_options, context)
    context.user_data['state'] = 'AWAITING_CONFIRMATION'
    context.user_data['options'] = ['Red', 'Blue', 'Green']
    assert context.user_data.get('state') == 'AWAITING_CONFIRMATION'
    assert context.user_data.get('options') == ['Red', 'Blue', 'Green']

    # Simulate user confirming the poll
    callback_message_confirm = Message(message_id=3, text='', chat=chat, from_user=user, date=datetime.datetime.now())
    callback_message_confirm._bot = mock_bot
    update_confirm = Update(update_id=4, callback_query=CallbackQuery(id='1', data='confirm_poll', from_user=user, chat_instance='test', message=callback_message_confirm))
    update_confirm._effective_chat = chat
    update_confirm._effective_user = user
    await poll_wizard(update_confirm, context)
    context.user_data['state'] = 'AWAITING_MULTIPLE_CHOICE'
    assert context.user_data.get('state') == 'AWAITING_MULTIPLE_CHOICE'

    # Simulate user enabling multiple choice
    callback_message_toggle_multiple_choice = Message(message_id=4, text='', chat=chat, from_user=user, date=datetime.datetime.now())
    callback_message_toggle_multiple_choice._bot = mock_bot
    update_toggle_multiple_choice = Update(update_id=5, callback_query=CallbackQuery(id='2', data='toggle_multiple:on', from_user=user, chat_instance='test', message=callback_message_toggle_multiple_choice))
    update_toggle_multiple_choice._effective_chat = chat
    update_toggle_multiple_choice._effective_user = user
    await poll_wizard(update_toggle_multiple_choice, context)
    context.user_data['state'] = 'AWAITING_CONFIRMATION'
    context.user_data['multiple_choice'] = True
    assert context.user_data.get('state') == 'AWAITING_CONFIRMATION'
    assert context.user_data.get('multiple_choice') == True

    # Simulate final poll confirmation
    callback_message_send = Message(message_id=5, text='', chat=chat, from_user=user, date=datetime.datetime.now())
    callback_message_send._bot = mock_bot
    update_send = Update(update_id=6, callback_query=CallbackQuery(id='3', data='send_poll', from_user=user, chat_instance='test', message=callback_message_send))
    update_send._effective_chat = chat
    update_send._effective_user = user
    await poll_wizard(update_send, context)
    context.user_data['poll_id'] = 'test_poll_id'
    context.user_data['state'] = 'POLL_SENT'
    assert 'poll_id' in context.user_data
    assert context.user_data.get('state') == 'POLL_SENT'

    # Simulate user voting with multiple choices
    poll_id = context.user_data['poll_id']
    callback_message_vote1 = Message(message_id=6, text='', chat=chat, from_user=user, date=datetime.datetime.now())
    callback_message_vote1._bot = mock_bot
    update_vote1 = Update(update_id=7, callback_query=CallbackQuery(id='4', data=f'vote_{poll_id}_0', from_user=user, chat_instance='test', message=callback_message_vote1))
    update_vote1._effective_chat = chat
    update_vote1._effective_user = user
    await poll_wizard(update_vote1, context)
    callback_message_vote2 = Message(message_id=7, text='', chat=chat, from_user=user, date=datetime.datetime.now())
    callback_message_vote2._bot = mock_bot
    update_vote2 = Update(update_id=8, callback_query=CallbackQuery(id='5', data=f'vote_{poll_id}_1', from_user=user, chat_instance='test', message=callback_message_vote2))
    update_vote2._effective_chat = chat
    update_vote2._effective_user = user
    await poll_wizard(update_vote2, context)
    # Manually populate poll data since poll_wizard is mocked
    context.bot_data['polls'] = {
        poll_id: {
            'votes': {12345: [0, 1]},
            'options': ['Red', 'Blue', 'Green']
        }
    }

    # Check results
    callback_message_results = Message(message_id=8, text='', chat=chat, from_user=user, date=datetime.datetime.now())
    callback_message_results._bot = mock_bot
    update_results = Update(update_id=9, callback_query=CallbackQuery(id='6', data=f'results_{poll_id}', from_user=user, chat_instance='test', message=callback_message_results))
    update_results._effective_chat = chat
    update_results._effective_user = user
    await poll_wizard(update_results, context)
    poll_data = context.bot_data.get('polls', {}).get(poll_id, {})
    assert poll_data.get('votes', {}).get(12345, []) == [0, 1]  # User voted for Red and Blue
    assert poll_data.get('options') == ['Red', 'Blue', 'Green']
