import pytest
import io
from unittest.mock import MagicMock, patch
from PIL import Image

from src.drawing import generate_results_heatmap_image
from src.database import Poll, Participant, Response, User

@pytest.fixture
def mock_db_session():
    """Provides a mock SQLAlchemy session."""
    return MagicMock()

@patch('src.drawing.db')
def test_heatmap_generation_success(mock_db, mock_db_session):
    """
    Tests successful heatmap image generation with valid data.
    """
    # Arrange
    poll = Poll(poll_id=1, chat_id=-100, poll_type='native', options="Да,Нет")
    participants = [Participant(user_id=101), Participant(user_id=102)]
    responses = [Response(user_id=101, response="Да")]

    mock_db.get_poll.return_value = poll
    mock_db.get_participants.return_value = participants
    mock_db.get_responses.return_value = responses
    mock_db.get_user_name.side_effect = lambda s, uid: f"User {uid}"

    # Act
    image_buffer = generate_results_heatmap_image(poll_id=1, session=mock_db_session)

    # Assert
    assert isinstance(image_buffer, io.BytesIO)
    image_buffer.seek(0)
    img = Image.open(image_buffer)
    assert img.format == 'PNG'
    # A basic check that the image has some size
    assert img.width > 100
    assert img.height > 50

@patch('src.drawing.db')
def test_heatmap_generation_no_participants(mock_db, mock_db_session):
    """
    Tests that heatmap generation returns None if there are no participants.
    """
    # Arrange
    poll = Poll(poll_id=1, chat_id=-100, poll_type='native', options="Да,Нет")
    responses = [Response(user_id=101, response="Да")]

    mock_db.get_poll.return_value = poll
    mock_db.get_participants.return_value = [] # No participants
    mock_db.get_responses.return_value = responses

    # Act
    image_buffer = generate_results_heatmap_image(poll_id=1, session=mock_db_session)

    # Assert
    assert image_buffer is None

@patch('src.drawing.db')
def test_heatmap_generation_no_options(mock_db, mock_db_session):
    """
    Tests that heatmap generation for a webapp poll with no responses (and thus no options) returns None.
    """
    # Arrange
    poll = Poll(poll_id=1, chat_id=-100, poll_type='webapp') # No predefined options
    participants = [Participant(user_id=101)]
    
    mock_db.get_poll.return_value = poll
    mock_db.get_participants.return_value = participants
    mock_db.get_responses.return_value = [] # No responses -> no options

    # Act
    image_buffer = generate_results_heatmap_image(poll_id=1, session=mock_db_session)

    # Assert
    assert image_buffer is None 