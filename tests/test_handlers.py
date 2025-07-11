import pytest
import asyncio
from unittest.mock import MagicMock, AsyncMock, patch
import io

from telegram import Update, User, Chat, Message, CallbackQuery, InlineKeyboardMarkup
from telegram.ext import ContextTypes

from src.handlers import base, dashboard, voting, results
from src.database import Participant, Poll, PollSetting

@pytest.fixture
def mock_context():
    """Provides a mock context with a bot."""
    mock_bot = AsyncMock()
    context = MagicMock()
    context.bot = mock_bot
    return context

@pytest.mark.asyncio
async def test_register_user_activity_in_group(mocker):
    """
    Tests that a user sending a message in a group gets registered.
    """
    # Arrange
    mocker.patch('src.database.add_user_to_participants')
    from src import database as db

    mock_update = MagicMock(spec=Update)
    mock_user = MagicMock(spec=User)
    mock_user.id = 123
    mock_user.is_bot = False
    mock_user.full_name = "Test User"
    mock_user.username = "testuser"
    mock_user.first_name = "Test"
    mock_user.last_name = "User"

    mock_chat = Chat(id=-1001, type=Chat.GROUP)
    mock_message = Message(message_id=1, date=None, chat=mock_chat, from_user=mock_user)
    mock_update.message = mock_message
    
    # Act
    await base.register_user_activity(mock_update, MagicMock())

    # Assert
    db.add_user_to_participants.assert_called_once_with(
        chat_id=-1001,
        user_id=123,
        username="testuser",
        first_name="Test",
        last_name="User",
    )

@pytest.mark.asyncio
async def test_register_user_activity_ignored_in_private(mocker):
    """
    Tests that user activity in a private chat is ignored for participant registration.
    """
    # Arrange
    mocker.patch('src.database.add_user_to_participants')
    from src import database as db

    mock_update = MagicMock(spec=Update)
    mock_user = MagicMock(spec=User)
    mock_user.id = 123
    mock_user.is_bot = False
    mock_user.full_name = "Test User"
    mock_user.username = "testuser"
    mock_user.first_name = "Test"
    mock_user.last_name = "User"

    mock_chat = Chat(id=123, type=Chat.PRIVATE)
    mock_message = Message(message_id=1, date=None, chat=mock_chat, from_user=mock_user)
    mock_update.message = mock_message

    # Act
    await base.register_user_activity(mock_update, MagicMock())

    # Assert
    db.add_user_to_participants.assert_not_called()

@pytest.mark.asyncio
async def test_show_participants_list_empty(mocker):
    """
    Tests the display of an empty participants list.
    """
    # Arrange
    mocker.patch('src.database.get_participants', return_value=[])
    mocker.patch('src.database.get_group_title', return_value="Test Group")
    mock_query = AsyncMock(spec=CallbackQuery)

    # Act
    await dashboard.show_participants_list(mock_query, chat_id=-1001, page=0)

    # Assert
    mock_query.edit_message_text.assert_called_once()
    call_args = mock_query.edit_message_text.call_args
    text_arg = call_args[0][0]
    assert "нет зарегистрированных участников" in text_arg
    assert "Test Group" in text_arg

@pytest.mark.asyncio
async def test_show_participants_list_with_data_and_pagination(mocker):
    """
    Tests the paginated display of a participants list.
    """
    # Arrange
    participants = [Participant(user_id=i, chat_id=-1001) for i in range(55)]
    mocker.patch('src.database.get_participants', return_value=participants)
    mocker.patch('src.database.get_group_title', return_value="Test Group")
    mocker.patch('src.database.get_user_name', side_effect=lambda session, user_id, markdown_link=False: f"User {user_id}")
    mock_query = AsyncMock(spec=CallbackQuery)

    # Act (Page 0)
    await dashboard.show_participants_list(mock_query, chat_id=-1001, page=0)

    # Assert (Page 0)
    mock_query.edit_message_text.assert_called_once()
    text = mock_query.edit_message_text.call_args[0][0]
    markup = mock_query.edit_message_text.call_args[1]['reply_markup']
    assert "Стр\\. 1/2" in text and "User 50" not in text
    assert markup.inline_keyboard[0][0].callback_data == "dash:participants_list:-1001:1"

    # Act (Page 1)
    mock_query.reset_mock()
    await dashboard.show_participants_list(mock_query, chat_id=-1001, page=1)

    # Assert (Page 1)
    mock_query.edit_message_text.assert_called_once()
    text = mock_query.edit_message_text.call_args[0][0]
    markup = mock_query.edit_message_text.call_args[1]['reply_markup']
    assert "Стр\\. 2/2" in text and "User 50" in text
    assert markup.inline_keyboard[0][0].callback_data == "dash:participants_list:-1001:0"

@pytest.mark.asyncio
@patch('src.handlers.dashboard.db.SessionLocal')
@patch('src.handlers.dashboard.generate_poll_content', return_value=("Сгенерированный текст", io.BytesIO(b"fake_image_bytes")))
@patch('src.handlers.dashboard.show_poll_list', new_callable=AsyncMock)
async def test_start_poll_success_native_with_image(mock_show_list, mock_gen_content, mock_session_local, mock_context):
    mock_session = MagicMock()
    mock_session_local.return_value = mock_session
    mock_poll = Poll(poll_id=22, chat_id=-1001, message="Заголовок", options="A,B", status='draft', poll_type='native')
    mock_session.query.return_value.filter_by.return_value.first.return_value = mock_poll
    mock_context.bot.send_photo.return_value.photo = [MagicMock(file_id="dummy_file_id")]
    mock_query = AsyncMock(spec=CallbackQuery)
    await dashboard.start_poll(mock_query, mock_context, poll_id=22)
    mock_context.bot.send_photo.assert_called_once()
    assert mock_poll.status == 'active'
    mock_show_list.assert_called_once_with(mock_query, -1001, 'draft')

@pytest.mark.asyncio
@patch('src.handlers.dashboard.db.SessionLocal')
@patch('src.handlers.dashboard.generate_poll_content')
@patch('src.handlers.dashboard.show_poll_list', new_callable=AsyncMock)
async def test_start_poll_success_native(mock_show_list, mock_generate_content, mock_session_local, mock_context):
    mock_session = MagicMock()
    mock_session_local.return_value = mock_session
    mock_poll = Poll(poll_id=1, chat_id=-1001, message="Native Poll Title", options="Opt1,Opt2", status='draft', poll_type='native')
    mock_session.query.return_value.filter_by.return_value.first.return_value = mock_poll
    mock_generate_content.return_value = ("Final Caption", b"new_image_bytes")
    mock_query = AsyncMock(spec=CallbackQuery)
    mock_context.bot.send_photo = AsyncMock()
    await dashboard.start_poll(mock_query, mock_context, poll_id=1)
    mock_context.bot.send_photo.assert_called_once()
    assert mock_poll.status == 'active'
    mock_show_list.assert_called_once_with(mock_query, -1001, 'draft')

@pytest.mark.asyncio
@patch('src.handlers.dashboard.db')
async def test_show_draft_poll_list(mock_db, mock_context):
    """
    Tests that the list of draft polls is displayed correctly.
    This test mocks the entire db module inside dashboard.py to bypass issues.
    """
    chat_id = -1001
    draft_polls = [
        Poll(poll_id=10, chat_id=chat_id, status='draft', message="Draft Poll 1"),
        Poll(poll_id=11, chat_id=chat_id, status='draft', message="Draft Poll 2"),
    ]
    mock_db.get_polls_by_status.return_value = draft_polls
    mock_query = AsyncMock(spec=CallbackQuery)

    await dashboard.show_poll_list(mock_query, chat_id=chat_id, status='draft')

    # Assert db call is correct
    mock_db.get_polls_by_status.assert_called_once_with(chat_id, 'draft')

    # Assert message is edited correctly
    mock_query.edit_message_text.assert_called_once()
    call_args = mock_query.edit_message_text.call_args
    text = call_args.args[0]
    markup = call_args.kwargs['reply_markup']
    assert "*Черновики*" in text
    assert len(markup.inline_keyboard) == 3  # 2 polls + 1 back button
    assert markup.inline_keyboard[0][0].callback_data == "settings:poll_menu:10"
    assert markup.inline_keyboard[0][1].callback_data == "dash:start_poll:10"

@pytest.mark.asyncio
@patch('src.handlers.dashboard.db.SessionLocal')
@patch('src.handlers.dashboard.show_poll_list', new_callable=AsyncMock)
async def test_start_poll_fail_not_a_draft(mock_show_list, mock_session_local, mock_context):
    mock_session = MagicMock()
    mock_session_local.return_value = mock_session
    mock_poll = Poll(poll_id=23, status='active')
    mock_session.query.return_value.filter_by.return_value.first.return_value = mock_poll
    mock_query = AsyncMock(spec=CallbackQuery)
    await dashboard.start_poll(mock_query, mock_context, poll_id=23)
    mock_context.bot.send_photo.assert_not_called()
    mock_session.commit.assert_not_called()
    mock_query.answer.assert_called_once_with('Опрос не является черновиком или не найден.', show_alert=True)
    mock_show_list.assert_not_called()

@pytest.mark.asyncio
@patch('src.handlers.dashboard.db.SessionLocal')
async def test_start_poll_fail_no_title(mock_session_local, mock_context):
    mock_session = MagicMock()
    mock_session_local.return_value = mock_session
    mock_poll = Poll(poll_id=24, status='draft', message=None)
    mock_session.query.return_value.filter_by.return_value.first.return_value = mock_poll
    mock_query = AsyncMock(spec=CallbackQuery)
    await dashboard.start_poll(mock_query, mock_context, poll_id=24)
    mock_query.answer.assert_called_once_with('Текст (заголовок) опроса не задан. Отредактируйте его в настройках.', show_alert=True)

@pytest.mark.asyncio
@patch('src.handlers.dashboard.db.SessionLocal')
async def test_start_poll_fail_no_native_options(mock_session_local, mock_context):
    mock_session = MagicMock()
    mock_session_local.return_value = mock_session
    mock_poll = Poll(poll_id=25, status='draft', message='title', poll_type='native', options=None)
    mock_session.query.return_value.filter_by.return_value.first.return_value = mock_poll
    mock_query = AsyncMock(spec=CallbackQuery)
    with patch('src.handlers.dashboard.generate_poll_content', return_value=("", None)):
        await dashboard.start_poll(mock_query, mock_context, poll_id=25)
    mock_query.answer.assert_called_once_with('Ошибка: опрос содержит пустые или некорректные варианты ответов. Пожалуйста, отредактируйте их в настройках.', show_alert=True)

@pytest.mark.asyncio
@patch('src.handlers.voting.db.add_user_to_participants')
@patch('src.handlers.voting.db.SessionLocal')
@patch('src.handlers.voting.db.add_or_update_response')
@patch('src.handlers.voting.generate_poll_content')
async def test_vote_callback_handler_calls_db_correctly(
    mock_generate_content, mock_add_response, mock_session_local, mock_add_participant
):
    """
    Tests that the vote handler correctly processes a vote, fetches poll settings,
    and calls the database function with the correct parameters.
    This test is corrected to align with the actual implementation.
    """
    # --- Arrange ---
    # 1. Mock the database session and the objects it returns
    mock_session = MagicMock()
    mock_session_local.return_value = mock_session
    
    mock_poll = Poll(poll_id=42, chat_id=-1001, message_id=999, status='active', options="Да,Нет")
    
    # Configure the mock query to return the poll object.
    mock_session.query.return_value.filter_by.return_value.first.return_value = mock_poll

    # 2. Mock the Telegram Update object
    mock_user = User(id=123, first_name="Тест", is_bot=False, last_name="Тестов", username="test_user")
    mock_message = AsyncMock(spec=Message)
    mock_query = AsyncMock(spec=CallbackQuery)
    mock_query.data = "vote:42:0"  # poll_id 42, option 0
    mock_query.from_user = mock_user
    mock_query.message = mock_message
    
    mock_update = MagicMock(spec=Update)
    mock_update.callback_query = mock_query
    mock_update.effective_chat.id = -1001

    mock_context = MagicMock(spec=ContextTypes.DEFAULT_TYPE)
    mock_context.bot = AsyncMock()
    
    # Mock the return value for content generation
    mock_generate_content.return_value = ("New Caption", None)

    # --- Act ---
    await voting.vote_callback_handler(mock_update, mock_context)

    # --- Assert ---
    # 1. Check that participant was added
    mock_add_participant.assert_called_once_with(
        chat_id=-1001,
        user_id=123,
        username="test_user",
        first_name="Тест",
        last_name="Тестов",
    )

    # 2. Check that the response was added/updated
    mock_add_response.assert_called_once_with(
        poll_id=42,
        user_id=123,
        first_name="Тест",
        last_name="Тестов",
        username="test_user",
        option_index=0
    )

    # 3. Check that the session was committed inside update_poll_message
    mock_session.commit.assert_called_once()

    # 4. Check that the user gets a confirmation
    mock_query.answer.assert_called_once_with("Спасибо, ваш голос учтён!")

    # 5. Check that the poll message is updated
    mock_context.bot.edit_message_text.assert_called_once()

# --- NEW TESTS FOR HEATMAP DISPLAY IN show_results ---

@pytest.mark.asyncio
@patch('src.handlers.results.generate_poll_content', return_value=("Caption", io.BytesIO(b"imgbytes")))
async def test_show_results_edits_existing_photo(mock_generate_content, mocker, mock_context):
    """Если сообщение уже содержит фото, show_results должен редактировать медиа."""
    from src.handlers import results
    from src.database import Poll

    # Подготовка фиктивного опроса
    poll = Poll(poll_id=1, chat_id=-1001, message="title", status='active')
    mocker.patch('src.handlers.results.db.get_poll', return_value=poll)

    # CallbackQuery с сообщением-фото
    mock_query = AsyncMock(spec=CallbackQuery)
    message = MagicMock()
    message.photo = [MagicMock()]
    message.chat_id = -1001
    message.message_id = 55
    mock_query.message = message
    mock_query.data = 'results:refresh:1'
    mock_query.edit_message_media = AsyncMock()
    mock_query.answer = AsyncMock()

    # Update
    mock_update = MagicMock(spec=Update)
    mock_update.callback_query = mock_query

    # Context
    context = mock_context

    # Act
    await results.show_results(mock_update, context, poll_id=1)

    # Assert
    mock_query.edit_message_media.assert_called_once()
    context.bot.send_photo.assert_not_called()

@pytest.mark.asyncio
@patch('src.handlers.results.generate_poll_content', return_value=("Caption", io.BytesIO(b"imgbytes")))
async def test_show_results_sends_photo_when_text(mock_generate_content, mocker, mock_context):
    """Если сообщение было текстовым, show_results должен удалить его и отправить новое фото."""
    from src.handlers import results
    from src.database import Poll

    poll = Poll(poll_id=2, chat_id=-1001, message="title", status='active')
    mocker.patch('src.handlers.results.db.get_poll', return_value=poll)

    mock_query = AsyncMock(spec=CallbackQuery)
    message = MagicMock()
    message.photo = []  # нет фото
    message.chat_id = -1001
    message.message_id = 56
    mock_query.message = message
    mock_query.data = 'results:refresh:2'
    mock_query.edit_message_media = AsyncMock()
    mock_query.answer = AsyncMock()

    mock_update = MagicMock(spec=Update)
    mock_update.callback_query = mock_query

    context = mock_context
    # bot.delete_message нужно для проверки
    context.bot.delete_message = AsyncMock()

    await results.show_results(mock_update, context, poll_id=2)

    context.bot.send_photo.assert_called_once()
    context.bot.delete_message.assert_called_once_with(chat_id=-1001, message_id=56)
    mock_query.edit_message_media.assert_not_called() 