import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

# Import the models and function to be tested
from src.database import Base, Poll, Response, PollSetting, User, add_or_update_response

# --- Test Database Fixture ---

@pytest.fixture(scope="function")
def db_session():
    """
    Creates a new in-memory SQLite database session for each test function.
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

# --- Test Data ---

USER_1 = {"user_id": 101, "first_name": "Алиса", "last_name": "", "username": "alice"}
USER_2 = {"user_id": 102, "first_name": "Боб", "last_name": "", "username": "bob"}

# --- Unit Tests for add_or_update_response ---

def test_single_choice_first_vote(db_session):
    # Arrange: Create a single-choice poll
    poll = Poll(poll_id=1, options="A,B", status='active')
    poll_setting = PollSetting(poll_id=1, allow_multiple_answers=False)
    db_session.add_all([poll, poll_setting])
    db_session.commit()

    # Act
    add_or_update_response(poll_id=1, option_index=0, **USER_1)

    # Assert
    responses = db_session.query(Response).filter_by(poll_id=1, user_id=USER_1['user_id']).all()
    assert len(responses) == 1
    assert responses[0].response == "A"

def test_single_choice_change_vote(db_session):
    # Arrange: Create a poll and an initial vote
    poll = Poll(poll_id=1, options="A,B", status='active')
    poll_setting = PollSetting(poll_id=1, allow_multiple_answers=False)
    initial_response = Response(poll_id=1, user_id=USER_1['user_id'], response="A")
    db_session.add_all([poll, poll_setting, initial_response])
    db_session.commit()

    # Act: User changes their vote from A to B
    add_or_update_response(poll_id=1, option_index=1, **USER_1)

    # Assert
    responses = db_session.query(Response).filter_by(poll_id=1, user_id=USER_1['user_id']).all()
    assert len(responses) == 1
    assert responses[0].response == "B"

def test_multiple_choice_first_vote(db_session):
    # Arrange: Create a multiple-choice poll
    poll = Poll(poll_id=1, options="A,B,C", status='active')
    poll_setting = PollSetting(poll_id=1, allow_multiple_answers=True)
    db_session.add_all([poll, poll_setting])
    db_session.commit()

    # Act
    add_or_update_response(poll_id=1, option_index=0, **USER_1)

    # Assert
    responses = db_session.query(Response).filter_by(poll_id=1, user_id=USER_1['user_id']).all()
    assert len(responses) == 1
    assert responses[0].response == "A"

def test_multiple_choice_second_vote(db_session):
    # Arrange: Poll where user has already voted for A
    poll = Poll(poll_id=1, options="A,B,C", status='active')
    poll_setting = PollSetting(poll_id=1, allow_multiple_answers=True)
    initial_response = Response(poll_id=1, user_id=USER_1['user_id'], response="A")
    db_session.add_all([poll, poll_setting, initial_response])
    db_session.commit()
    
    # Act: User also votes for C
    add_or_update_response(poll_id=1, option_index=2, **USER_1)

    # Assert: User should now have two responses (A and C)
    responses = db_session.query(Response).filter_by(poll_id=1, user_id=USER_1['user_id']).all()
    assert len(responses) == 2
    response_texts = {r.response for r in responses}
    assert response_texts == {"A", "C"}

def test_multiple_choice_unvote(db_session):
    # Arrange: Poll where user has voted for A and C
    poll = Poll(poll_id=1, options="A,B,C", status='active')
    poll_setting = PollSetting(poll_id=1, allow_multiple_answers=True)
    initial_responses = [
        Response(poll_id=1, user_id=USER_1['user_id'], response="A"),
        Response(poll_id=1, user_id=USER_1['user_id'], response="C")
    ]
    db_session.add_all([poll, poll_setting] + initial_responses)
    db_session.commit()
    
    # Act: User clicks on A again to un-vote
    add_or_update_response(poll_id=1, option_index=0, **USER_1)

    # Assert: User should now only have one response (C)
    responses = db_session.query(Response).filter_by(poll_id=1, user_id=USER_1['user_id']).all()
    assert len(responses) == 1
    assert responses[0].response == "C"

def test_user_data_is_created_and_updated(db_session):
    # Arrange
    poll = Poll(poll_id=1, options="A,B", status='active')
    poll_setting = PollSetting(poll_id=1, allow_multiple_answers=False)
    db_session.add_all([poll, poll_setting])
    db_session.commit()

    # Act: First time we see this user
    add_or_update_response(poll_id=1, option_index=0, **USER_1)

    # Assert: User is created in the User table
    user_in_db = db_session.query(User).filter_by(user_id=USER_1['user_id']).first()
    assert user_in_db is not None
    assert user_in_db.first_name == "Алиса"

    # Act: User changes their name and votes again
    updated_user_data = USER_1.copy()
    updated_user_data["first_name"] = "Алиса-новое-имя"
    add_or_update_response(poll_id=1, option_index=1, **updated_user_data)
    
    # Assert: User's name is updated in the database
    user_in_db = db_session.query(User).filter_by(user_id=USER_1['user_id']).first()
    assert user_in_db.first_name == "Алиса-новое-имя" 