import pytest
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes
from bot import start, poll_wizard, application

@pytest.mark.asyncio
async def test_poll_creation_with_multiple_choices():
    # Simulate the start command to initiate the wizard
    update = Update(
        update_id=1,
        message=None,
        callback_query=None,
        effective_chat=Update.effective_chat(id=12345, type='private'),
        effective_user=Update.effective_user(id=12345, is_bot=False, first_name='TestUser')
    )
    context = ContextTypes.DEFAULT_TYPE()

    # Start the wizard
    await start(update, context)
    assert context.user_data.get('state') == 'AWAITING_QUESTION'

    # Simulate user entering the poll question
    update.message = Update.message(text='What are your favorite colors?')
    await poll_wizard(update, context)
    assert context.user_data.get('state') == 'AWAITING_OPTIONS'
    assert context.user_data.get('question') == 'What are your favorite colors?'

    # Simulate user entering poll options
    update.message.text = 'Red\nBlue\nGreen'
    await poll_wizard(update, context)
    assert context.user_data.get('state') == 'AWAITING_CONFIRMATION'
    assert context.user_data.get('options') == ['Red', 'Blue', 'Green']

    # Simulate user confirming the poll
    update.callback_query = Update.callback_query(data='confirm_poll')
    await poll_wizard(update, context)
    assert context.user_data.get('state') == 'AWAITING_MULTIPLE_CHOICE'

    # Simulate user enabling multiple choice
    update.callback_query.data = 'toggle_multiple:on'
    await poll_wizard(update, context)
    assert context.user_data.get('multiple_choice') == True

    # Simulate final poll confirmation
    update.callback_query.data = 'send_poll'
    await poll_wizard(update, context)
    assert 'poll_id' in context.user_data
    assert context.user_data.get('state') == 'POLL_SENT'

    # Simulate user voting with multiple choices
    poll_id = context.user_data['poll_id']
    update.callback_query.data = f'vote_{poll_id}_0'
    await poll_wizard(update, context)
    update.callback_query.data = f'vote_{poll_id}_1'
    await poll_wizard(update, context)

    # Check results
    update.callback_query.data = f'results_{poll_id}'
    await poll_wizard(update, context)
    poll_data = context.bot_data.get('polls', {}).get(poll_id, {})
    assert poll_data.get('votes', {}).get(12345, []) == [0, 1]  # User voted for Red and Blue
    assert poll_data.get('options') == ['Red', 'Blue', 'Green']
