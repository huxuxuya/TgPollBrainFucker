import pytest
from unittest.mock import MagicMock
from sqlalchemy.orm import Session
from unittest.mock import patch

# Import the models and function to be tested
from src.database import Poll, Response, PollSetting, User
from src.display import generate_poll_content

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

@pytest.fixture
def mock_poll_with_votes(mock_poll):
    """A fixture for a poll object that simulates having votes."""
    # This is a bit of a hack, but it allows us to reuse the mock_poll
    # and just add responses for tests that need them.
    responses = [
        Response(user_id=101, response="Красный"),
        Response(user_id=102, response="Синий"),
        Response(user_id=103, response="Красный"),
    ]
    with patch('src.database.get_responses', return_value=responses):
        yield mock_poll

# --- Unit Tests for generate_poll_text ---

def test_generate_poll_text_no_votes(mocker, mock_poll, mock_session):
    """
    Tests poll text generation when there are no votes.
    """
    # Arrange: Mock DB calls
    mocker.patch('src.database.get_responses', return_value=[])
    mocker.patch('src.database.get_poll_setting', return_value=PollSetting(default_show_names=True, default_show_count=True))
    mocker.patch('src.database.get_poll_option_setting', return_value=None)
    # Mock the image generation to test the text part in isolation
    mocker.patch('src.display.generate_results_heatmap_image', return_value=b'fake_image')
    
    # Act
    text, image = generate_poll_content(poll=mock_poll, session=mock_session)

    # Assert
    assert "Какой твой любимый цвет?" in text
    assert "Красный: *0*" in text
    # Image should be None because there are no votes
    assert image is None

def test_generate_poll_content_with_votes_and_image(mocker, mock_poll_with_votes, mock_session):
    """
    Tests poll content generation with votes, expecting an image by default.
    """
    mocker.patch('src.database.get_poll_setting', return_value=PollSetting(show_heatmap=True))
    mocker.patch('src.database.get_poll_option_setting', return_value=None)
    mocker.patch('src.display.generate_results_heatmap_image', return_value=b'fake_image_bytes')
    
    text, image = generate_poll_content(poll=mock_poll_with_votes, session=mock_session)
    
    assert "Всего проголосовало: *3*" in text
    assert image == b'fake_image_bytes'

def test_generate_poll_content_with_votes_no_image(mocker, mock_poll_with_votes, mock_session):
    """
    Tests poll content generation with votes but with the heatmap setting disabled.
    """
    # Arrange: Disable the heatmap
    mocker.patch('src.database.get_poll_setting', return_value=PollSetting(show_heatmap=False))
    mocker.patch('src.database.get_poll_option_setting', return_value=None)
    # We don't need to mock the image generator as it shouldn't be called.
    
    text, image = generate_poll_content(poll=mock_poll_with_votes, session=mock_session)
    
    assert "Всего проголосовало: *3*" in text
    assert image is None

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
    mocker.patch('src.database.get_poll_setting', return_value=PollSetting(default_show_names=True, default_show_count=True, show_heatmap=True))
    mocker.patch('src.database.get_poll_option_setting', return_value=None)
    mocker.patch('src.display.generate_results_heatmap_image', return_value=b'fake_image')
    
    # Mock user name fetching
    def get_user_name_mock(session, user_id, markdown_link=False):
        names = {101: "Алиса", 102: "Боб", 103: "Вася"}
        name = names.get(user_id, "Unknown")
        return f'[{name}](tg://user?id={user_id})' if markdown_link else name
    
    mocker.patch('src.database.get_user_name', side_effect=get_user_name_mock)

    # Act
    text, image = generate_poll_content(poll=mock_poll, session=mock_session)

    # Assert
    assert "Красный: *2*" in text
    assert "Синий: *1*" in text
    assert "Зеленый: *0*" in text
    assert "Алиса" in text
    assert "Боб" in text
    assert "Вася" in text
    assert image is not None

def test_generate_poll_text_votes_no_names(mocker, mock_poll, mock_session):
    """
    Tests poll text generation with votes but without displaying voter names.
    """
    # Arrange: Mock DB calls
    responses = [Response(user_id=101, response="Красный")]
    mocker.patch('src.database.get_responses', return_value=responses)
    mocker.patch('src.database.get_poll_setting', return_value=PollSetting(default_show_names=False, show_heatmap=True)) # Names are turned OFF
    mocker.patch('src.database.get_poll_option_setting', return_value=None)
    mocker.patch('src.database.get_user_name', return_value="Алиса")
    mocker.patch('src.display.generate_results_heatmap_image', return_value=b'fake_image')

    # Act
    text, image = generate_poll_content(poll=mock_poll, session=mock_session)

    # Assert
    assert "Красный: *1*" in text
    assert "Алиса" not in text # Name should not be in the text
    assert image is not None

def test_generate_poll_text_closed_poll(mocker, mock_poll, mock_session):
    """
    Tests that a closed poll includes the 'ОПРОС ЗАВЕРШЕН' header.
    """
    # Arrange
    mock_poll.status = 'closed'
    mocker.patch('src.database.get_responses', return_value=[])
    mocker.patch('src.database.get_poll_setting', return_value=PollSetting())
    mocker.patch('src.database.get_poll_option_setting', return_value=None)
    mocker.patch('src.display.generate_results_heatmap_image', return_value=b'fake_image')

    # Act
    text, image = generate_poll_content(poll=mock_poll, session=mock_session)

    # Assert
    assert text.startswith("*ОПРОС ЗАВЕРШЕН*")
    assert image is None # No votes, no image

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
    mocker.patch('src.database.get_poll_setting', return_value=PollSetting(show_heatmap=True))
    mocker.patch('src.database.get_poll_option_setting', return_value=None)
    mocker.patch('src.display.generate_results_heatmap_image', return_value=b'fake_image')
    
    # Act
    text, image = generate_poll_content(poll=mock_poll, session=mock_session)
    
    # Assert
    assert "Красный: *1*" in text
    assert "Синий: *1*" in text
    assert "Зеленый: *1*" in text
    # Total voters should be the number of unique users (2), not the number of responses (3).
    assert "Всего проголосовало: *2*" in text
    assert image is not None

def test_generate_poll_text_for_webapp_no_votes(mocker, mock_poll, mock_session):
    """
    Tests that a webapp poll with no votes generates text but NO image,
    to avoid conflicts with the WebApp button.
    """
    # Arrange
    mock_poll.poll_type = 'webapp'
    mocker.patch('src.database.get_responses', return_value=[])
    mocker.patch('src.database.get_poll_setting', return_value=PollSetting())
    mocker.patch('src.display.generate_results_heatmap_image', return_value=b'fake_image')

    # Act
    text, image = generate_poll_content(poll=mock_poll, session=mock_session)

    # Assert
    assert "Какой твой любимый цвет?" in text
    # Crucially, the image should be None for this specific case
    assert image is None 