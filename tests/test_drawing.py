import pytest
import io
from unittest.mock import MagicMock, patch, call
from PIL import Image

from src.drawing import generate_results_heatmap_image
from src.database import Poll, Participant, Response

@pytest.fixture
def mock_db_session():
    """Provides a mock SQLAlchemy session with basic mocked methods."""
    session = MagicMock()
    session.query.return_value.filter_by.return_value.first.return_value = None
    session.query.return_value.all.return_value = []
    return session

@patch('src.drawing.db.SessionLocal')
@patch('src.drawing.db')
def test_heatmap_generation_with_internal_session(mock_db, mock_session_local):
    """
    Tests successful heatmap generation when no session is passed,
    ensuring internal session management works as expected.
    This test covers the scenario that was previously failing.
    """
    # Arrange
    # This mock session will be returned by SessionLocal() inside the function
    mock_internal_session = MagicMock()
    mock_session_local.return_value = mock_internal_session

    poll = Poll(poll_id=1, chat_id=-100, poll_type='native', options="Да,Нет")
    participants = [Participant(user_id=101), Participant(user_id=102, excluded=True)]
    responses = [Response(user_id=101, response="Да")]

    # Mock DB functions. 
    # get_poll and get_responses are now called without session.
    mock_db.get_poll.return_value = poll
    mock_db.get_responses.return_value = responses
    
    # These functions are called with the internally created session.
    mock_db.get_participants.return_value = participants
    mock_db.get_user_name.side_effect = lambda s, uid: f"User {uid}"

    # Act
    image_buffer = generate_results_heatmap_image(poll_id=1)

    # Assert
    assert isinstance(image_buffer, io.BytesIO)
    image_buffer.seek(0)
    img = Image.open(image_buffer)
    assert img.format == 'PNG'
    assert img.width > 100 and img.height > 50

    # Verify that the functions were called correctly.
    # get_poll and get_responses should be called without the session argument.
    mock_db.get_poll.assert_called_once_with(1)
    mock_db.get_responses.assert_called_once_with(1)
    
    # get_participants and get_user_name should be called with the session
    # that was created inside generate_results_heatmap_image.
    mock_db.get_participants.assert_called_once_with(-100, session=mock_internal_session)
    
    # Assert that get_user_name was called for both the active and the excluded participant
    expected_calls = [
        call(mock_internal_session, 101),
        call(mock_internal_session, 102)
    ]
    mock_db.get_user_name.assert_has_calls(expected_calls, any_order=True)
    
    # Check that the internal session was closed.
    mock_internal_session.close.assert_called_once()

@patch('src.drawing.db')
def test_heatmap_generation_no_participants(mock_db):
    """
    Tests that heatmap generation returns None if there are no participants.
    """
    # Arrange
    poll = Poll(poll_id=2, chat_id=-101, poll_type='native', options="A,B")
    mock_db.get_poll.return_value = poll
    mock_db.get_participants.return_value = [] # No participants
    mock_db.get_responses.return_value = [] # To truly test no participants, there should be no responses either

    # Act
    image_buffer = generate_results_heatmap_image(poll_id=2)

    # Assert
    assert image_buffer is None
    mock_db.get_poll.assert_called_once_with(2)
    mock_db.get_participants.assert_called_once() # We don't care about args here as much
    
@patch('src.drawing.db')
def test_heatmap_generation_no_options(mock_db):
    """
    Tests that heatmap generation for a webapp poll with no responses (and thus no options) returns None.
    """
    # Arrange
    poll = Poll(poll_id=3, chat_id=-102, poll_type='webapp')
    participants = [Participant(user_id=101)]
    
    mock_db.get_poll.return_value = poll
    mock_db.get_participants.return_value = participants
    mock_db.get_responses.return_value = [] # No responses -> no options

    # Act
    image_buffer = generate_results_heatmap_image(poll_id=3)

    # Assert
    assert image_buffer is None
    mock_db.get_poll.assert_called_once_with(3)
    mock_db.get_responses.assert_called_once_with(3)
    mock_db.get_participants.assert_called_once() 