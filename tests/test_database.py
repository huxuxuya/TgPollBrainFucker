import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

# Import the models and function to be tested
from src.database import (
    Base, Poll, Participant, Response, PollSetting, User, add_or_update_response
)

# --- Fixtures ---

@pytest.fixture(scope="function")
def db_session():
    """
    Creates an in-memory SQLite database session for each test function.
    This ensures tests are isolated from each other.
    """
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    session = Session()

    # Monkeypatch the SessionLocal in the original database module
    # so that the function-under-test uses this in-memory DB
    from src import database
    database.SessionLocal = lambda: session

    yield session

    session.close()
    Base.metadata.drop_all(engine)

@pytest.fixture
def user_1():
    """Provides test data for the first user."""
    return {"user_id": 101, "first_name": "\u0410\u043b\u0438\u0441\u0430", "last_name": "", "username": "alice"}

@pytest.fixture
def user_2():
    """Provides test data for the second user."""
    return {"user_id": 102, "first_name": "\u0411\u043e\u0431", "last_name": "", "username": "bob"}

@pytest.fixture
def single_choice_poll(db_session):
    """Creates a single-choice poll and adds it to the database."""
    poll = Poll(poll_id=1, chat_id=-1001, options="A,B,C", status='active')
    poll_setting = PollSetting(poll_id=1, allow_multiple_answers=False)
    db_session.add_all([poll, poll_setting])
    db_session.commit()
    return poll

@pytest.fixture
def multiple_choice_poll(db_session):
    """Creates a multiple-choice poll and adds it to the database."""
    poll = Poll(poll_id=2, chat_id=-1002, options="X,Y,Z", status='active')
    poll_setting = PollSetting(poll_id=2, allow_multiple_answers=True)
    db_session.add_all([poll, poll_setting])
    db_session.commit()
    return poll

# --- Unit Tests for add_or_update_response ---

def test_single_choice_first_vote(db_session, single_choice_poll, user_1):
    # Arrange
    poll_id = single_choice_poll.poll_id

    # Act
    add_or_update_response(poll_id=poll_id, option_index=0, **user_1)

    # Assert
    responses = db_session.query(Response).filter_by(poll_id=poll_id, user_id=user_1['user_id']).all()
    assert len(responses) == 1
    assert responses[0].response == "A"

def test_single_choice_change_vote(db_session, single_choice_poll, user_1):
    # Arrange
    poll_id = single_choice_poll.poll_id
    initial_response = Response(poll_id=poll_id, user_id=user_1['user_id'], response="A")
    db_session.add(initial_response)
    db_session.commit()

    # Act: User changes their vote from A to B
    add_or_update_response(poll_id=poll_id, option_index=1, **user_1)

    # Assert
    responses = db_session.query(Response).filter_by(poll_id=poll_id, user_id=user_1['user_id']).all()
    assert len(responses) == 1
    assert responses[0].response == "B"

def test_multiple_choice_first_vote(db_session, multiple_choice_poll, user_1):
    # Arrange
    poll_id = multiple_choice_poll.poll_id

    # Act
    add_or_update_response(poll_id=poll_id, option_index=0, **user_1)

    # Assert
    responses = db_session.query(Response).filter_by(poll_id=poll_id, user_id=user_1['user_id']).all()
    assert len(responses) == 1
    assert responses[0].response == "X"

def test_multiple_choice_second_vote(db_session, multiple_choice_poll, user_1):
    # Arrange
    poll_id = multiple_choice_poll.poll_id
    initial_response = Response(poll_id=poll_id, user_id=user_1['user_id'], response="X")
    db_session.add(initial_response)
    db_session.commit()
    
    # Act: User also votes for Z
    add_or_update_response(poll_id=poll_id, option_index=2, **user_1)

    # Assert: User should now have two responses (X and Z)
    responses = db_session.query(Response).filter_by(poll_id=poll_id, user_id=user_1['user_id']).all()
    assert len(responses) == 2
    response_texts = {r.response for r in responses}
    assert response_texts == {"X", "Z"}

def test_multiple_choice_unvote(db_session, multiple_choice_poll, user_1):
    # Arrange
    poll_id = multiple_choice_poll.poll_id
    initial_responses = [
        Response(poll_id=poll_id, user_id=user_1['user_id'], response="X"),
        Response(poll_id=poll_id, user_id=user_1['user_id'], response="Z")
    ]
    db_session.add_all(initial_responses)
    db_session.commit()
    
    # Act: User clicks on X again to un-vote
    add_or_update_response(poll_id=poll_id, option_index=0, **user_1)

    # Assert: User should now only have one response (Z)
    responses = db_session.query(Response).filter_by(poll_id=poll_id, user_id=user_1['user_id']).all()
    assert len(responses) == 1
    assert responses[0].response == "Z"

def test_user_data_is_created_and_updated(db_session, single_choice_poll, user_1):
    # Arrange
    poll_id = single_choice_poll.poll_id

    # Act: First time we see this user
    add_or_update_response(poll_id=poll_id, option_index=0, **user_1)

    # Assert: User is created in the User table
    user_in_db = db_session.query(User).filter_by(user_id=user_1['user_id']).first()
    assert user_in_db is not None
    assert user_in_db.first_name == "\u0410\u043b\u0438\u0441\u0430"

    # Act: User changes their name and votes again
    updated_user_data = user_1.copy()
    updated_user_data["first_name"] = "\u0410\u043b\u0438\u0441\u0430-\u043d\u043e\u0432\u043e\u0435-\u0438\u043c\u044f"
    add_or_update_response(poll_id=poll_id, option_index=1, **updated_user_data)
    
    # Assert: User's name is updated in the database
    user_in_db = db_session.query(User).filter_by(user_id=user_1['user_id']).first()
    assert user_in_db.first_name == "\u0410\u043b\u0438\u0441\u0430-\u043d\u043e\u0432\u043e\u0435-\u0438\u043c\u044f"

# --- Тесты для исключений участников внутри опроса -------------------------

def test_toggle_poll_exclusion(db_session):
    # Arrange: создать опрос и участника
    poll = Poll(poll_id=99, chat_id=-200, options="A,B", status='active')
    participant = Participant(chat_id=-200, user_id=555)
    db_session.add_all([poll, participant])
    db_session.commit()

    # Act: исключаем участника
    from src import database as db
    excluded = db.toggle_poll_exclusion(99, 555)
    assert excluded is True

    # Assert: запись существует
    excl_ids = db.get_poll_exclusions(99, session=db_session)
    assert 555 in excl_ids

    # Act: включаем обратно
    excluded = db.toggle_poll_exclusion(99, 555)
    assert excluded is False

    excl_ids = db.get_poll_exclusions(99, session=db_session)
    assert 555 not in excl_ids
 