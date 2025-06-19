import pytest
import asyncio
from unittest.mock import MagicMock, AsyncMock, patch
import io

from telegram import Update, User, Chat, Message, CallbackQuery, InlineKeyboardMarkup
from telegram.ext import ContextTypes

from src.handlers import base, dashboard, voting
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
    mocker.patch('src.database.add_participant')
    from src import database as db

    mock_update = MagicMock(spec=Update)
    mock_user = MagicMock(spec=User)
    mock_user.id = 123
    mock_user.is_bot = False
    mock_user.full_name = "Test User"

    mock_chat = Chat(id=-1001, type=Chat.GROUP)
    mock_message = Message(message_id=1, date=None, chat=mock_chat, from_user=mock_user)
    mock_update.message = mock_message
    
    # Act
    await base.register_user_activity(mock_update, MagicMock())

    # Assert
    db.add_participant.assert_called_once_with(-1001, 123, "Test User")

@pytest.mark.asyncio
async def test_register_user_activity_ignored_in_private(mocker):
    """
    Tests that user activity in a private chat is ignored for participant registration.
    """
    # Arrange
    mocker.patch('src.database.add_participant')
    from src import database as db

    mock_update = MagicMock(spec=Update)
    mock_user = MagicMock(spec=User)
    mock_user.id = 123
    mock_user.is_bot = False
    mock_user.full_name = "Test User"

    mock_chat = Chat(id=123, type=Chat.PRIVATE)
    mock_message = Message(message_id=1, date=None, chat=mock_chat, from_user=mock_user)
    mock_update.message = mock_message

    # Act
    await base.register_user_activity(mock_update, MagicMock())

    # Assert
    db.add_participant.assert_not_called()

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
@patch('src.handlers.voting.db.SessionLocal')
@patch('src.handlers.voting.db.add_or_update_response_ext')
@patch('src.handlers.voting.generate_poll_content')
async def test_vote_callback_handler_calls_db_correctly(
    mock_generate_content, mock_add_response, mock_session_local
):
    """
    Tests that the vote handler correctly processes a vote, fetches poll settings,
    and calls the database function with the correct parameters.
    """
    # --- Arrange ---
    # 1. Mock the database session and the objects it returns
    mock_session = MagicMock()
    mock_session_local.return_value = mock_session
    
    mock_poll = Poll(poll_id=42, chat_id=-1001, status='active', options="Да,Нет")
    mock_poll_settings = PollSetting(poll_id=42, allow_multiple_answers=False)
    
    # Configure the mock query to return the right objects
    mock_session.query.return_value.filter_by.side_effect = [
        MagicMock(first=lambda: mock_poll),
        MagicMock(first=lambda: mock_poll_settings)
    ]

    # 2. Mock the Telegram Update object
    mock_user = User(id=123, first_name="Тест", is_bot=False, last_name="Тестов", username="test_user")
    mock_message = AsyncMock(spec=Message)
    mock_query = AsyncMock(spec=CallbackQuery)
    mock_query.data = "vote:42:0"  # poll_id 42, option 0
    mock_query.from_user = mock_user
    mock_query.message = mock_message
    
    mock_update = MagicMock(spec=Update)
    mock_update.callback_query = mock_query

    mock_context = MagicMock(spec=ContextTypes.DEFAULT_TYPE)
    
    # Mock the return value for content generation
    mock_generate_content.return_value = ("New Caption", None)

    # --- Act ---
    await voting.vote_callback_handler(mock_update, mock_context)

    # --- Assert ---
    # 1. Check that the DB function was called correctly
    mock_add_response.assert_called_once()
    call_args, call_kwargs = mock_add_response.call_args
    
    assert call_kwargs['session'] == mock_session
    assert call_kwargs['poll_id'] == 42
    assert call_kwargs['user_id'] == 123
    assert call_kwargs['first_name'] == "Тест"
    assert call_kwargs['last_name'] == "Тестов"
    assert call_kwargs['username'] == "test_user"
    assert call_kwargs['option_index'] == 0

    # 2. Check that the session was committed
    mock_session.commit.assert_called()

    # 3. Check that the user gets a confirmation
    mock_query.answer.assert_called() 