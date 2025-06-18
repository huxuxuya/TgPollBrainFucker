import pytest
from unittest.mock import MagicMock
from sqlalchemy.orm import Session

# Import the models and function to be tested
from src.database import Poll, Response, PollSetting, User
from src.display import generate_poll_text

# --- Test Data Fixtures ---

@pytest.fixture
def mock_poll():
    """Provides a basic mock Poll object."""
    return Poll(
        poll_id=1,
        chat_id=-1001,
        message="Какой твой любимый цвет?",
        options="Красный,Синий,Зеленый",
        status='active',
        poll_type='native'
    )

@pytest.fixture
def mock_session(mock_poll):
    """
    Provides a mock SQLAlchemy session that returns the mock_poll when merge is called.
    """
    session = MagicMock(spec=Session)
    session.merge.return_value = mock_poll
    return session

# --- Unit Tests for generate_poll_text ---

def test_generate_poll_text_no_votes(mocker, mock_poll, mock_session):
    """
    Tests poll text generation when there are no votes.
    """
    # Arrange: Mock DB calls
    mocker.patch('src.database.get_responses', return_value=[])
    mocker.patch('src.database.get_poll_setting', return_value=PollSetting(default_show_names=True, default_show_count=True))
    mocker.patch('src.database.get_poll_option_setting', return_value=None)
    
    # Act
    text = generate_poll_text(poll=mock_poll, session=mock_session)

    # Assert
    assert "Какой твой любимый цвет?" in text
    assert "Красный: *0*" in text
    assert "Синий: *0*" in text
    assert "Зеленый: *0*" in text
    assert "Всего проголосовало: *0*" in text

def test_generate_poll_text_with_votes_and_names(mocker, mock_poll, mock_session):
    """
    Tests poll text generation with votes and displayed voter names.
    """
    # Arrange: Mock DB calls
    responses = [
        Response(user_id=101, response="Красный"),
        Response(user_id=102, response="Синий"),
        Response(user_id=103, response="Красный"),
    ]
    mocker.patch('src.database.get_responses', return_value=responses)
    mocker.patch('src.database.get_poll_setting', return_value=PollSetting(default_show_names=True, default_show_count=True))
    mocker.patch('src.database.get_poll_option_setting', return_value=None)
    
    # Mock user name fetching
    def get_user_name_mock(session, user_id, markdown_link=False):
        names = {101: "Алиса", 102: "Боб", 103: "Вася"}
        name = names.get(user_id, "Unknown")
        return f'[{name}](tg://user?id={user_id})' if markdown_link else name
    
    mocker.patch('src.database.get_user_name', side_effect=get_user_name_mock)

    # Act
    text = generate_poll_text(poll=mock_poll, session=mock_session)

    # Assert
    assert "Красный: *2*" in text
    assert "Синий: *1*" in text
    assert "Зеленый: *0*" in text
    assert "Алиса" in text
    assert "Боб" in text
    assert "Вася" in text
    assert "Всего проголосовало: *3*" in text

def test_generate_poll_text_votes_no_names(mocker, mock_poll, mock_session):
    """
    Tests poll text generation with votes but without displaying voter names.
    """
    # Arrange: Mock DB calls
    responses = [Response(user_id=101, response="Красный")]
    mocker.patch('src.database.get_responses', return_value=responses)
    mocker.patch('src.database.get_poll_setting', return_value=PollSetting(default_show_names=False)) # Names are turned OFF
    mocker.patch('src.database.get_poll_option_setting', return_value=None)
    mocker.patch('src.database.get_user_name', return_value="Алиса")

    # Act
    text = generate_poll_text(poll=mock_poll, session=mock_session)

    # Assert
    assert "Красный: *1*" in text
    assert "Алиса" not in text # Name should not be in the text

def test_generate_poll_text_closed_poll(mocker, mock_poll, mock_session):
    """
    Tests that a closed poll includes the 'ОПРОС ЗАВЕРШЕН' header.
    """
    # Arrange
    mock_poll.status = 'closed'
    mocker.patch('src.database.get_responses', return_value=[])
    mocker.patch('src.database.get_poll_setting', return_value=PollSetting())
    mocker.patch('src.database.get_poll_option_setting', return_value=None)

    # Act
    text = generate_poll_text(poll=mock_poll, session=mock_session)

    # Assert
    assert text.startswith("*ОПРОС ЗАВЕРШЕН*")

def test_generate_poll_text_multiple_choice(mocker, mock_poll, mock_session):
    """
    Tests correct calculation of total voters in a multiple-choice poll.
    """
    # Arrange
    responses = [
        Response(user_id=101, response="Красный"),
        Response(user_id=101, response="Синий"), # Same user, different choice
        Response(user_id=102, response="Зеленый"),
    ]
    mocker.patch('src.database.get_responses', return_value=responses)
    mocker.patch('src.database.get_poll_setting', return_value=PollSetting())
    mocker.patch('src.database.get_poll_option_setting', return_value=None)
    
    # Act
    text = generate_poll_text(poll=mock_poll, session=mock_session)
    
    # Assert
    assert "Красный: *1*" in text
    assert "Синий: *1*" in text
    assert "Зеленый: *1*" in text
    # Total voters should be the number of unique users (2), not the number of responses (3).
    assert "Всего проголосовало: *2*" in text 