import pytest
import asyncio
from unittest.mock import MagicMock, AsyncMock, patch
import io

from telegram import Update, User, Chat, Message, CallbackQuery, InlineKeyboardMarkup

from src.handlers import base, dashboard
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
    # Use a MagicMock configured to look like a User object instead of a real one.
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
    # The text is a positional argument, not a keyword argument.
    text_arg = call_args[0][0]
    assert "нет зарегистрированных участников" in text_arg
    assert "Test Group" in text_arg

@pytest.mark.asyncio
async def test_show_participants_list_with_data_and_pagination(mocker):
    """
    Tests the paginated display of a participants list.
    """
    # Arrange
    # Mocking more than one page of participants
    participants = [Participant(user_id=i, chat_id=-1001) for i in range(55)]
    mocker.patch('src.database.get_participants', return_value=participants)
    mocker.patch('src.database.get_group_title', return_value="Test Group")

    # Mock get_user_name to return a dummy name
    mocker.patch('src.database.get_user_name', side_effect=lambda session, user_id, markdown_link=False: f"User {user_id}")

    mock_query = AsyncMock(spec=CallbackQuery)

    # Act - request page 0
    await dashboard.show_participants_list(mock_query, chat_id=-1001, page=0)

    # Assert - page 0
    mock_query.edit_message_text.assert_called_once()
    call_args = mock_query.edit_message_text.call_args
    # The text is positional, and the markup is a kwarg.
    text = call_args[0][0]
    markup = call_args[1]['reply_markup']

    assert "Стр\\. 1/2" in text # Check for escaped version
    assert "User 0" in text
    assert "User 49" in text
    assert "User 50" not in text # Should not be on the first page

    # Check for the 'Next' button
    nav_buttons = markup.inline_keyboard[0]
    assert len(nav_buttons) == 1
    assert nav_buttons[0].text == "➡️"
    assert nav_buttons[0].callback_data == "dash:participants_list:-1001:1"

    # Act - request page 1
    # We need to reset the mock to check the next call correctly
    mock_query.reset_mock()
    await dashboard.show_participants_list(mock_query, chat_id=-1001, page=1)

    # Assert - page 1
    mock_query.edit_message_text.assert_called_once()
    call_args = mock_query.edit_message_text.call_args
    text = call_args[0][0]
    markup = call_args[1]['reply_markup']

    assert "Стр\\. 2/2" in text # Check for escaped version
    assert "User 50" in text
    assert "User 54" in text
    
    # Check for the 'Back' button
    nav_buttons = markup.inline_keyboard[0]
    assert len(nav_buttons) == 1
    assert nav_buttons[0].text == "⬅️"
    assert nav_buttons[0].callback_data == "dash:participants_list:-1001:0"

# --- Tests for Poll Starting ---

@pytest.mark.asyncio
@patch('src.handlers.dashboard.db.SessionLocal')
@patch('src.handlers.dashboard.generate_poll_content', return_value=("Сгенерированный текст", io.BytesIO(b"fake_image_bytes")))
@patch('src.handlers.dashboard.show_poll_list', new_callable=AsyncMock)
async def test_start_poll_success_native_with_image(mock_show_list, mock_gen_content, mock_session_local, mock_context):
    """
    Tests the successful start of a native poll, sending it as a photo.
    """
    # Arrange
    mock_session = MagicMock()
    mock_session_local.return_value = mock_session
    
    mock_poll = Poll(
        poll_id=22, chat_id=-1001, message="Заголовок", options="A,B", 
        status='draft', poll_type='native'
    )
    mock_session.query.return_value.filter_by.return_value.first.return_value = mock_poll

    # Mock the return value of send_photo to include a photo File ID
    mock_context.bot.send_photo.return_value.photo = [MagicMock(file_id="dummy_file_id")]

    mock_query = AsyncMock(spec=CallbackQuery)

    # Act
    await dashboard.start_poll(mock_query, mock_context, poll_id=22)

    # Assert
    # 1. Check if a photo was sent
    mock_context.bot.send_photo.assert_called_once()
    send_args = mock_context.bot.send_photo.call_args
    assert send_args.kwargs['chat_id'] == -1001
    assert send_args.kwargs['caption'] == "Сгенерированный текст"
    assert isinstance(send_args.kwargs['photo'], io.BytesIO)
    
    # 2. Check if poll status and photo_file_id were updated
    assert mock_poll.status == 'active'
    assert mock_poll.photo_file_id == "dummy_file_id"
    mock_session.commit.assert_called_once()
    
    # 3. Check for user feedback and list refresh
    mock_query.answer.assert_called_once_with('Опрос 22 запущен.', show_alert=True)
    mock_show_list.assert_called_once_with(mock_query, -1001, 'draft')

@pytest.mark.asyncio
@patch('src.handlers.dashboard.db.SessionLocal')
@patch('src.handlers.dashboard.generate_poll_content')
@patch('src.handlers.dashboard.show_poll_list', new_callable=AsyncMock)
async def test_start_poll_success_native(mock_show_list, mock_generate_content, mock_session_local, mock_context):
    """
    Tests the successful start of a native poll from a draft.
    """
    # Arrange
    mock_session = MagicMock()
    mock_session_local.return_value = mock_session
    
    mock_poll = Poll(
        poll_id=1, chat_id=-1001, message="Native Poll Title", options="Opt1,Opt2",
        status='draft', poll_type='native', photo_file_id='old_file_id'
    )
    mock_session.query.return_value.filter_by.return_value.first.return_value = mock_poll

    # Mock the content generation to return predictable results
    mock_generate_content.return_value = ("Final Caption", b"new_image_bytes")

    mock_query = AsyncMock(spec=CallbackQuery)
    mock_context.bot.send_photo = AsyncMock()

    # Act
    await dashboard.start_poll(mock_query, mock_context, poll_id=1)

    # Assert
    # 1. Check if the message was sent to the group
    mock_context.bot.send_photo.assert_called_once()
    mock_context.bot.send_message.assert_not_called()

    send_args = mock_context.bot.send_photo.call_args
    assert send_args.kwargs['chat_id'] == -1001
    assert send_args.kwargs['caption'] == "Final Caption"
    assert send_args.kwargs['photo'] == b"new_image_bytes"
    assert isinstance(send_args.kwargs['reply_markup'], InlineKeyboardMarkup)
    assert len(send_args.kwargs['reply_markup'].inline_keyboard) == 2 # For options "Opt1" and "Opt2"

    # 2. Check if poll status was updated and committed
    assert mock_poll.status == 'active'
    assert mock_poll.message_id is not None
    mock_session.commit.assert_called_once()
    
    # 3. Check for user feedback and list refresh
    mock_query.answer.assert_called_once_with('Опрос 1 запущен.', show_alert=True)
    mock_show_list.assert_called_once_with(mock_query, -1001, 'draft')

    # Assert that the poll content generator was called
    mock_generate_content.assert_called_once_with(poll=mock_poll, session=mock_session)

    # Assert that the bot sent a photo with the new content
    mock_context.bot.send_photo.assert_awaited_once()

@pytest.mark.asyncio
@patch('src.handlers.dashboard.db.SessionLocal')
@patch('src.handlers.dashboard.show_poll_list', new_callable=AsyncMock)
async def test_start_poll_fail_not_a_draft(mock_show_list, mock_session_local, mock_context):
    """
    Tests that starting a non-draft poll fails.
    """
    # Arrange
    mock_session = MagicMock()
    mock_session_local.return_value = mock_session
    
    mock_poll = Poll(poll_id=23, status='active') # Not a draft
    mock_session.query.return_value.filter_by.return_value.first.return_value = mock_poll

    mock_query = AsyncMock(spec=CallbackQuery)

    # Act
    await dashboard.start_poll(mock_query, mock_context, poll_id=23)

    # Assert
    mock_context.bot.send_message.assert_not_called()
    mock_session.commit.assert_not_called()
    mock_query.answer.assert_called_once_with('Опрос не является черновиком или не найден.', show_alert=True)
    mock_show_list.assert_not_called()


@pytest.mark.asyncio
@patch('src.handlers.dashboard.db.SessionLocal')
async def test_start_poll_fail_no_title(mock_session_local, mock_context):
    """
    Tests that starting a poll with no title (message) fails.
    """
    # Arrange
    mock_session = MagicMock()
    mock_session_local.return_value = mock_session
    
    mock_poll = Poll(poll_id=24, status='draft', message=None) # No title
    mock_session.query.return_value.filter_by.return_value.first.return_value = mock_poll

    mock_query = AsyncMock(spec=CallbackQuery)

    # Act
    await dashboard.start_poll(mock_query, mock_context, poll_id=24)

    # Assert
    mock_context.bot.send_message.assert_not_called()
    mock_query.answer.assert_called_once_with('Текст (заголовок) опроса не задан. Отредактируйте его в настройках.', show_alert=True)


@pytest.mark.asyncio
@patch('src.handlers.dashboard.db.SessionLocal')
async def test_start_poll_fail_no_native_options(mock_session_local, mock_context):
    """
    Tests that starting a native poll with empty options fails.
    """
    # Arrange
    mock_session = MagicMock()
    mock_session_local.return_value = mock_session

    mock_poll = Poll(
        poll_id=25, chat_id=-1002, message="Title", options=" , ", # Invalid options
        status='draft', poll_type='native'
    )
    # Ensure that merge returns the original object, not a new mock
    mock_session.merge.return_value = mock_poll 
    mock_session.query.return_value.filter_by.return_value.first.return_value = mock_poll
    
    # This mock is crucial to prevent the AttributeError
    with patch('src.display.db.get_poll_setting', return_value=PollSetting(show_heatmap=False)), \
         patch('src.display.db.get_poll_option_setting', return_value=None):
        mock_query = AsyncMock(spec=CallbackQuery)

        # Act
        await dashboard.start_poll(mock_query, mock_context, poll_id=25)

        # Assert
        mock_query.answer.assert_called_once_with(
            'Ошибка: опрос содержит пустые или некорректные варианты ответов. Пожалуйста, отредактируйте их в настройках.', 
            show_alert=True
        )
        mock_context.bot.send_photo.assert_not_called()
        mock_context.bot.send_message.assert_not_called() 