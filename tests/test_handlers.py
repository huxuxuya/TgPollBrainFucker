import pytest
import asyncio
from unittest.mock import MagicMock, AsyncMock, patch

from telegram import Update, User, Chat, Message, CallbackQuery, InlineKeyboardMarkup

from src.handlers import base, dashboard
from src.database import Participant

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